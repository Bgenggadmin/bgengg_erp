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

# --- 3. DATA LOADERS ---
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
    "🏗️ Scheduling & Execution", "👷 Daily Entry", "📊 Analytics & Reports", "⚙️ Master Settings"
])

# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
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

        if current_job_steps.empty:
            st.warning("⚠️ No Plan Detected")
            src_job = st.selectbox("Clone from Job Template:", ["-- Select --"] + all_jobs, key="clone_src")
            if st.button("🚀 Clone Sequence") and src_job != "-- Select --":
                source_steps = df_job_plans[df_job_plans['job_no'] == src_job]
                if not source_steps.empty:
                    new_steps = [{"job_no": target_job, "gate_name": s['gate_name'], "step_order": s['step_order'], "planned_start_date": date.today().isoformat(), "planned_end_date": (date.today()+timedelta(days=5)).isoformat(), "current_status": "Pending"} for _, s in source_steps.iterrows()]
                    conn.table("job_planning").insert(new_steps).execute()
                    st.cache_data.clear(); st.rerun()

        if not current_job_steps.empty:
            valid_dates = pd.to_datetime(current_job_steps['planned_end_date'], errors='coerce').dropna()
            if not valid_dates.empty:
                edd = valid_dates.max().date()
                st.info(f"📅 **Projected Completion (EDD): {edd.strftime('%d %b %Y')}**")

            st.divider()
            st.subheader(f"🏁 Execution: {target_job}")
            for _, row in current_job_steps.sort_values('step_order').iterrows():
                p_end = pd.to_datetime(row['planned_end_date']).date() if pd.notnull(row['planned_end_date']) else None
                today = date.today()
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
                        if p_end:
                            diff = (today - p_end).days
                            if diff > 0: col3.metric("Delay", f"{diff} Days", delta=f"-{diff}", delta_color="inverse")
                            else: col3.success("On Track")
                        if col4.button("✅ Close", key=f"cl_{row['id']}"):
                            conn.table("job_planning").update({"current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    else:
                        col2.success("🏁 Completed")

# --- TAB 2: DAILY ENTRY ---
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

    st.divider()
    st.markdown("### 🕒 Recent Entries (IST)")
    if not df_logs.empty:
        try:
            display_logs = df_logs.copy()
            # CRASH PROOF PARSING
            display_logs['created_at_dt'] = pd.to_datetime(display_logs['created_at'], utc=True, errors='coerce')
            display_logs = display_logs.dropna(subset=['created_at_dt'])
            display_logs['Time (IST)'] = display_logs['created_at_dt'].dt.tz_convert(IST).dt.strftime('%d-%b %I:%M %p')
            
            with st.expander("🛠️ Correction Tools"):
                last_row = display_logs.iloc[0]
                c1, c2, c3 = st.columns([2, 2, 1])
                c1.info(f"Last Log: {last_row['Worker']}")
                if c2.button("✏️ Edit Last"):
                    @st.dialog("Edit Log")
                    def edit_log(item):
                        nh = st.number_input("Hrs", value=float(item['Hours']))
                        nq = st.number_input("Qty", value=float(item['Output']))
                        if st.button("Save"):
                            conn.table("production").update({"Hours": nh, "Output": nq}).eq("id", item['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    edit_log(last_row)
                if c3.button("🗑️ Delete", type="primary"):
                    conn.table("production").delete().eq("id", last_row['id']).execute()
                    st.cache_data.clear(); st.rerun()

            st.dataframe(display_logs[['Time (IST)', 'Job_Code', 'Activity', 'Worker', 'Hours', 'Output', 'Unit']].head(20), use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Display Error: {e}")

# --- TAB 3: ANALYTICS ---
with tab_analytics:
    st.subheader("📊 Production Intelligence")
    if not df_logs.empty:
        # SYNCED IST LOGIC
        df_logs['dt'] = pd.to_datetime(df_logs['created_at'], utc=True, errors='coerce')
        df_logs = df_logs.dropna(subset=['dt'])
        df_logs['dt'] = df_logs['dt'].dt.tz_convert(IST)
        df_logs['date_only'] = df_logs['dt'].dt.date
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce').fillna(0)
        
        with st.container(border=True):
            f1, f2, f3 = st.columns(3)
            today = date.today()
            period = f1.selectbox("Period", ["Last 7 Days", "Current Month", "Custom"])
            if period == "Last 7 Days": d_range = [today - timedelta(days=7), today]
            elif period == "Current Month": d_range = [today.replace(day=1), today]
            else: d_range = f1.date_input("Range", [today - timedelta(days=30), today])
            
            f_jobs = f2.multiselect("Jobs", all_jobs, default=all_jobs)
            f_staff_sel = f3.multiselect("Workers", all_workers, default=all_workers)

        if len(d_range) == 2:
            mask = (df_logs['date_only'] >= d_range[0]) & (df_logs['date_only'] <= d_range[1]) & (df_logs['Job_Code'].isin(f_jobs)) & (df_logs['Worker'].isin(f_staff_sel))
            rdf = df_logs.loc[mask]
            if not rdf.empty:
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Hrs", f"{rdf['Hours'].sum():.1f}")
                m2.metric("Workers", rdf['Worker'].nunique())
                m3.metric("Jobs", rdf['Job_Code'].nunique())
                st.bar_chart(rdf.groupby('Job_Code')['Hours'].sum())
            else:
                st.warning("No data found.")

# --- TAB 4: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ Gate Master")
    with st.form("new_gate"):
        ng_name = st.text_input("Gate Name")
        ng_order = st.number_input("Order", value=len(df_master_gates)+1)
        if st.form_submit_button("Add Gate"):
            conn.table("production_gates").insert({"gate_name": ng_name, "step_order": ng_order}).execute()
            st.cache_data.clear(); st.rerun()
    st.dataframe(df_master_gates.sort_values('step_order')[['step_order', 'gate_name']], hide_index=True)
