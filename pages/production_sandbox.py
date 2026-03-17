import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP & CONNECTION ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master ERP | B&G", layout="wide", page_icon="🏗️")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SESSION STATE & MASTER RECOVERY ---
if 'master_data' not in st.session_state or not st.session_state.master_data:
    try:
        w_res = conn.table("master_workers").select("name").order("name").execute()
        s_res = conn.table("master_staff").select("name").order("name").execute()
        g_res = conn.table("production_gates").select("gate_name").order("step_order").execute()
        st.session_state.master_data = {
            "workers": [w['name'] for w in (w_res.data or [])],
            "staff": [s['name'] for s in (s_res.data or [])],
            "gates": [g['gate_name'] for g in (g_res.data or [])]
        }
    except Exception as e:
        st.error(f"Master Sync Error: {e}")

master = st.session_state.get('master_data', {})

# --- 3. DATA LOADERS (Cached) ---
@st.cache_data(ttl=2)
def get_master_data():
    try:
        p_res = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
        l_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        m_res = conn.table("production_gates").select("*").order("step_order").execute()
        j_res = conn.table("job_planning").select("*").order("step_order").execute()
        return pd.DataFrame(p_res.data or []), pd.DataFrame(l_res.data or []), pd.DataFrame(m_res.data or []), pd.DataFrame(j_res.data or [])
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_projects, df_logs, df_master_gates, df_job_plans = get_master_data()

# Mappings
all_staff = master.get('staff', [])
all_workers = sorted(list(set(master.get('workers', []))))
all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []
all_activities = master.get('gates', [])

# --- 4. NAVIGATION ---
tab_plan, tab_entry, tab_analytics, tab_master = st.tabs([
    "🏗️ Scheduling & Execution", "👷 Daily Entry", "📊 Analytics & Gantt", "⚙️ Master Settings"
])

# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
        # A. DELIVERY DASHBOARD (IMAGE 2 LAYOUT)
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                po_dt = pd.to_datetime(p_data.get('po_delivery_date')).date() if pd.notnull(p_data.get('po_delivery_date')) else None
                rev_dt = pd.to_datetime(p_data.get('revised_delivery_date')).date() if pd.notnull(p_data.get('revised_delivery_date')) else None
                
                c1.write(f"**PO Delivery Date**\n{po_dt.strftime('%d-%b-%Y') if po_dt else 'Not Set'}")
                c2.write(f"🔴 **Revised Date**\n{rev_dt.strftime('%d-%b-%Y') if rev_dt else 'None'}")
                
                final_target = rev_dt if rev_dt else po_dt
                if final_target:
                    days_left = (final_target - date.today()).days
                    c3.metric("Days to Dispatch", f"{days_left} Days", delta=days_left, delta_color="normal" if days_left > 7 else "inverse")
                
                if c4.button("📝 Edit", key="edit_delivery"):
                    @st.dialog("Update Schedule")
                    def update_dates():
                        n_po = st.date_input("PO Date", value=po_dt if po_dt else date.today())
                        n_rev = st.date_input("Revised Date", value=rev_dt if rev_dt else n_po)
                        if st.button("Save Changes"):
                            conn.table("anchor_projects").update({"po_delivery_date": str(n_po), "revised_delivery_date": str(n_rev)}).eq("job_no", target_job).execute()
                            st.cache_data.clear(); st.rerun()
                    update_dates()

        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()

        # B. CLONE / INITIALIZE (RESTORED LOGIC)
        if current_job_steps.empty:
            st.warning("⚠️ No Plan Detected")
            col_a, col_b = st.columns(2)
            with col_a:
                src_job = st.selectbox("Clone from Job:", ["-- Select --"] + all_jobs, key="clone_src")
                if st.button("🚀 Clone Sequence") and src_job != "-- Select --":
                    source_steps = df_job_plans[df_job_plans['job_no'] == src_job]
                    if not source_steps.empty:
                        new_steps = [{"job_no": target_job, "gate_name": s['gate_name'], "step_order": s['step_order'], "planned_start_date": date.today().isoformat(), "planned_end_date": (date.today()+timedelta(days=5)).isoformat(), "current_status": "Pending"} for _, s in source_steps.iterrows()]
                        conn.table("job_planning").insert(new_steps).execute()
                        st.cache_data.clear(); st.rerun()

        # C. EDD & MANAGEMENT
        if not current_job_steps.empty:
            valid_dates = pd.to_datetime(current_job_steps['planned_end_date'], errors='coerce').dropna()
            if not valid_dates.empty:
                edd = valid_dates.max().date()
                st.info(f"📅 **Projected Completion (EDD): {edd.strftime('%d %b %Y')}**")

            with st.expander("📝 Manage Sequence & Dates"):
                for _, edit_row in current_job_steps.sort_values('step_order').iterrows():
                    e_id = edit_row['id']
                    with st.container(border=True):
                        ec1, ec2, ec3, ec4 = st.columns([2, 2, 1, 1])
                        u_gate = ec1.selectbox("Gate", all_activities, index=all_activities.index(edit_row['gate_name']) if edit_row['gate_name'] in all_activities else 0, key=f"e_gate_{e_id}")
                        u_dates = ec2.date_input("Dates", [pd.to_datetime(edit_row['planned_start_date']).date(), pd.to_datetime(edit_row['planned_end_date']).date()], key=f"e_dt_{e_id}")
                        u_order = ec3.number_input("Order", value=int(edit_row['step_order']), key=f"e_ord_{e_id}")
                        if ec4.button("💾", key=f"sv_{e_id}"):
                            conn.table("job_planning").update({"gate_name": u_gate, "planned_start_date": u_dates[0].isoformat(), "planned_end_date": u_dates[1].isoformat(), "step_order": u_order}).eq("id", e_id).execute()
                            st.cache_data.clear(); st.rerun()
                        if ec4.button("🗑️", key=f"dl_{e_id}"):
                            conn.table("job_planning").delete().eq("id", e_id).execute(); st.cache_data.clear(); st.rerun()

            st.divider()
            st.subheader(f"🏁 Execution: {target_job}")
            for _, row in current_job_steps.sort_values('step_order').iterrows():
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                    col1.markdown(f"**Step {row['step_order']}: {row['gate_name']}**")
                    if row['current_status'] == "Pending":
                        col2.warning("⏳ Pending")
                        if col4.button("▶️ Start", key=f"st_{row['id']}"):
                            conn.table("job_planning").update({"current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    elif row['current_status'] == "Active":
                        col2.info("🚀 Active")
                        if col4.button("✅ Close", key=f"cl_{row['id']}"):
                            conn.table("job_planning").update({"current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    else:
                        col2.success("🏁 Completed")

# --- TAB 2: DAILY ENTRY (SANDBOX LOGIC) ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="ent_job")
    if f_job != "-- Select --":
        active_gates = df_job_plans[(df_job_plans['job_no'] == f_job) & (df_job_plans['current_status'] == 'Active')]['gate_name'].tolist()
        if active_gates:
            with st.form("prod_form", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                f_act = f1.selectbox("Gate", active_gates)
                f_wrk = f1.selectbox("Worker", ["-- Select --"] + all_workers)
                f_hrs = f2.number_input("Hrs", min_value=0.0, step=0.5)
                f_out = f3.number_input("Qty", min_value=0.0, step=0.1)
                f_unit = f3.selectbox("Unit", ["Nos", "Mtrs", "Sq.Ft", "Kgs", "Joints"])
                if st.form_submit_button("🚀 Log Progress"):
                    conn.table("production").insert({"Job_Code": f_job, "Activity": f_act, "Worker": f_wrk, "Hours": f_hrs, "Output": f_out, "Unit": f_unit, "created_at": datetime.now(IST).isoformat()}).execute()
                    st.cache_data.clear(); st.success("Logged!"); st.rerun()

# --- TAB 3: ANALYTICS & GANTT (BULLETPROOF VERSION) ---
with tab_analytics:
    st.subheader("📊 Performance Analytics")
    if not df_job_plans.empty:
        gantt_list = []
        for _, row in df_job_plans.iterrows():
            if pd.notna(row.get('planned_start_date')) and pd.notna(row.get('planned_end_date')):
                gantt_list.append(dict(Job=row['job_no'], Start=row['planned_start_date'], Finish=row['planned_end_date'], Type='Planned', Gate=row['gate_name']))
            if pd.notna(row.get('actual_start_date')):
                f_val = row['actual_end_date'] if pd.notna(row['actual_end_date']) else datetime.now(IST).isoformat()
                gantt_list.append(dict(Job=row['job_no'], Start=row['actual_start_date'], Finish=f_val, Type='Actual', Gate=row['gate_name']))
        
        if gantt_list:
            df_g = pd.DataFrame(gantt_list)
            df_g['Start'] = pd.to_datetime(df_g['Start'], errors='coerce')
            df_g['Finish'] = pd.to_datetime(df_g['Finish'], errors='coerce')
            df_g = df_g.dropna(subset=['Start', 'Finish'])
            df_g['Start'] = df_g['Start'].dt.tz_localize(None)
            df_g['Finish'] = df_g['Finish'].dt.tz_localize(None)
            fig = px.timeline(df_g, x_start="Start", x_end="Finish", y="Job", color="Type", barmode='group')
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

# --- TAB 4: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ Gate Master")
    with st.form("new_gate"):
        ng_name = st.text_input("Gate Name")
        ng_order = st.number_input("Order", value=len(df_master_gates)+1)
        if st.form_submit_button("Add Gate"):
            conn.table("production_gates").insert({"gate_name": ng_name, "step_order": ng_order}).execute()
            st.cache_data.clear(); st.rerun()
