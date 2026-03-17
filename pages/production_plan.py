import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz

# --- 1. SETUP & CONNECTION ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master ERP | B&G", layout="wide", page_icon="🏗️")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SESSION STATE & MASTER RECOVERY ---
if 'master_data' not in st.session_state:
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
        st.session_state.master_data = {"workers": [], "staff": [], "gates": []}

master = st.session_state.get('master_data', {})

# --- 3. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_production_data():
    try:
        p_res = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
        l_res = conn.table("production").select("*").order("created_at", desc=True).limit(100).execute()
        m_res = conn.table("production_gates").select("*").order("step_order").execute()
        j_res = conn.table("job_planning").select("*").order("step_order").execute()
        
        return (pd.DataFrame(p_res.data or []), 
                pd.DataFrame(l_res.data or []), 
                pd.DataFrame(m_res.data or []),
                pd.DataFrame(j_res.data or []))
    except Exception as e:
        st.error(f"Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_projects, df_logs, df_master_gates, df_job_plans = get_production_data()

# Mappings
all_jobs = sorted(df_projects['job_no'].unique().tolist()) if not df_projects.empty else []
all_workers = master.get('workers', [])
all_staff = master.get('staff', [])

# --- 4. TABS ---
tab_plan, tab_entry, tab_analytics, tab_master = st.tabs([
    "🏗️ Scheduling & Execution", "👷 Daily Entry", "📊 Analytics", "⚙️ Master"
])

# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
        # A. DELIVERY DASHBOARD (IMAGE 2 LOGIC)
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                
                po_dt = pd.to_datetime(p_data.get('po_delivery_date')).date() if pd.notnull(p_data.get('po_delivery_date')) else None
                rev_dt = pd.to_datetime(p_data.get('revised_delivery_date')).date() if pd.notnull(p_data.get('revised_delivery_date')) else None
                
                c1.write(f"**PO Delivery Date**\n{po_dt.strftime('%d-%b-%Y') if po_dt else 'Not Set'}")
                
                if rev_dt:
                    c2.write(f"🔴 **Revised Date**\n{rev_dt.strftime('%d-%b-%Y')}")
                else:
                    c2.write("**Revised Date**\nNo Revision")
                
                final_target = rev_dt if rev_dt else po_dt
                if final_target:
                    days_left = (final_target - date.today()).days
                    c3.metric("Days to Dispatch", f"{days_left} Days", delta=days_left, delta_color="normal" if days_left > 7 else "inverse")
                
                if c4.button("📝 Edit", key="edit_btn"):
                    @st.dialog("Update Delivery Schedule")
                    def update_dates():
                        n_po = st.date_input("PO Date", value=po_dt if po_dt else date.today())
                        n_rev = st.date_input("Revised Date", value=rev_dt if rev_dt else n_po)
                        if st.button("Save Changes"):
                            conn.table("anchor_projects").update({"po_delivery_date": str(n_po), "revised_delivery_date": str(n_rev)}).eq("job_no", target_job).execute()
                            st.cache_data.clear(); st.rerun()
                    update_dates()

        st.divider()

        # B. EDD LOGIC
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()
        
        if not current_job_steps.empty:
            valid_dates = pd.to_datetime(current_job_steps['planned_end_date']).dropna()
            if not valid_dates.empty:
                edd = valid_dates.max().date()
                days_rem = (edd - date.today()).days
                st.info(f"📅 **Projected Completion (EDD): {edd.strftime('%d %b %Y')}** ({days_rem} days remaining)")

        # C. PLANNING LOGIC (RESTORED CLONING/INITIALIZATION)
        if current_job_steps.empty:
            st.warning("⚠️ No plan found for this job. Setup the sequence below:")
            col_left, col_right = st.columns(2)
            
            with col_left:
                st.markdown("#### 👯 Option 1: Clone Plan")
                source_job = st.selectbox("Select Source Template", ["-- Select --"] + all_jobs, key="src_clone")
                if st.button("🚀 Clone Sequence") and source_job != "-- Select --":
                    source_steps = df_job_plans[df_job_plans['job_no'] == source_job]
                    if not source_steps.empty:
                        clones = []
                        for _, s_row in source_steps.iterrows():
                            clones.append({
                                "job_no": target_job, "gate_name": s_row['gate_name'], "step_order": s_row['step_order'],
                                "planned_start_date": str(date.today()), "planned_end_date": str(date.today() + timedelta(days=3)),
                                "current_status": "Pending"
                            })
                        conn.table("job_planning").insert(clones).execute()
                        st.cache_data.clear(); st.rerun()

            with col_right:
                st.markdown("#### 🛠️ Option 2: Manual Initialization")
                if st.button("🆕 Apply Default Gate Sequence"):
                    defaults = []
                    for i, gname in enumerate(master.get('gates', []), 1):
                        defaults.append({
                            "job_no": target_job, "gate_name": gname, "step_order": i,
                            "planned_start_date": str(date.today()), "planned_end_date": str(date.today() + timedelta(days=2)),
                            "current_status": "Pending"
                        })
                    conn.table("job_planning").insert(defaults).execute()
                    st.cache_data.clear(); st.rerun()

        # D. GATE EXECUTION (THE STEPS)
        else:
            st.markdown(f"### 🏁 Execution Flow: {target_job}")
            for index, row in current_job_steps.sort_values('step_order').iterrows():
                with st.container(border=True):
                    g1, g2, g3, g4 = st.columns([2, 1, 1, 1])
                    g1.markdown(f"**Step {row['step_order']}: {row['gate_name']}**")
                    
                    status = row['current_status']
                    if status == "Pending":
                        g2.warning("⏳ Pending")
                        if g4.button("▶️ Start", key=f"btn_start_{row['id']}"):
                            conn.table("job_planning").update({"current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    elif status == "Active":
                        g2.info("🚀 Active")
                        if g4.button("✅ Close", key=f"btn_end_{row['id']}"):
                            conn.table("job_planning").update({"current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    else:
                        g2.success("🏁 Completed")
                        g3.caption(f"Finished: {pd.to_datetime(row['actual_end_date']).strftime('%d %b')}")

# --- TAB 2: DAILY ENTRY ---
with tab_entry:
    st.subheader("👷 Daily Work Entry")
    with st.container(border=True):
        e_job = st.selectbox("Select Job", ["-- Select --"] + all_jobs, key="ent_job")
        if e_job != "-- Select --":
            active_gates = df_job_plans[(df_job_plans['job_no'] == e_job) & (df_job_plans['current_status'] == 'Active')]['gate_name'].tolist()
            if not active_gates:
                st.warning("⚠️ No active gates for this job. Please start a gate in the Scheduling tab.")
            else:
                with st.form("entry_form", clear_on_submit=True):
                    f1, f2 = st.columns(2)
                    f_gate = f1.selectbox("Process Gate", active_gates)
                    f_worker = f1.selectbox("Worker", ["-- Select --"] + all_workers)
                    f_hrs = f2.number_input("Hours Spent", min_value=0.5, max_value=24.0, step=0.5)
                    f_out = f2.number_input("Output Qty", min_value=0.0, step=1.0)
                    f_notes = st.text_input("Remarks")
                    if st.form_submit_button("🚀 Log Work"):
                        conn.table("production").insert({
                            "Job_Code": e_job, "Activity": f_gate, "Worker": f_worker,
                            "Hours": f_hrs, "Output": f_out, "Notes": f_notes,
                            "created_at": datetime.now(IST).isoformat()
                        }).execute()
                        st.cache_data.clear(); st.success("Logged!"); st.rerun()

    st.divider()
    if not df_logs.empty:
        st.markdown("#### 🕒 Recent Activity")
        st.dataframe(df_logs[['created_at', 'Job_Code', 'Activity', 'Worker', 'Hours', 'Output']].head(10), use_container_width=True, hide_index=True)

# --- TAB 3: ANALYTICS ---
with tab_analytics:
    st.subheader("📊 Production Insights")
    if not df_logs.empty:
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce')
        st.bar_chart(df_logs.groupby('Job_Code')['Hours'].sum())
        st.markdown("#### Man-Hours by Process")
        st.dataframe(df_logs.groupby('Activity')['Hours'].sum().reset_index(), use_container_width=True)

# --- TAB 4: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ System Configuration")
    m_col1, m_col2 = st.columns(2)
    with m_col1:
        st.write("**Manage Gates**")
        new_g = st.text_input("New Gate Name")
        if st.button("Add Gate"):
            conn.table("production_gates").insert({"gate_name": new_g, "step_order": len(df_master_gates)+1}).execute()
            st.cache_data.clear(); st.rerun()
        st.dataframe(df_master_gates[['step_order', 'gate_name']], hide_index=True)
