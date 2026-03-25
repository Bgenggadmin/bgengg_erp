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
        p_res = conn.table("anchor_projects").select("id, job_no, status, po_no, po_date, po_delivery_date, revised_delivery_date").eq("status", "Won").execute()
        l_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        m_res = conn.table("production_gates").select("*").order("step_order").execute()
        j_res = conn.table("job_planning").select("*").order("step_order").execute()
        pur_res = conn.table("purchase_orders").select("*").execute()
        # NEW: Load Sub-tasks
        sub_res = conn.table("job_sub_tasks").select("*").execute()
        
        return (pd.DataFrame(p_res.data or []), 
                pd.DataFrame(l_res.data or []), 
                pd.DataFrame(m_res.data or []), 
                pd.DataFrame(j_res.data or []),
                pd.DataFrame(pur_res.data or []),
                pd.DataFrame(sub_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_projects, df_logs, df_master_gates, df_job_plans, df_purchase, df_sub_tasks = get_master_data()

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
        # (Delivery Dashboard & Material Trigger code remains exactly the same as your paste)
        # ... [Skipping repeated UI code for brevity] ...
        
        # [Existing Delivery Dashboard code here]
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            job_internal_id = p_data.get('id') # Used for sub-task linking
            # [Rest of your Dashboard logic...]

        # --- D. EXECUTION & SUB-TASKS ---
        st.divider()
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()

        if not current_job_steps.empty:
            st.subheader(f"🏁 Execution: {target_job}")
            for _, row in current_job_steps.sort_values('step_order').iterrows():
                gate_id = row['id']
                p_start = pd.to_datetime(row['planned_start_date']).date() if pd.notnull(row['planned_start_date']) else None
                p_end = pd.to_datetime(row['planned_end_date']).date() if pd.notnull(row['planned_end_date']) else None
                
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([2.5, 1, 1, 1])
                    
                    with col1:
                        st.markdown(f"**Step {row['step_order']}: {row['gate_name']}**")
                        st.caption(f"🗓️ Planned: {p_start.strftime('%d %b') if p_start else '??'} — {p_end.strftime('%d %b') if p_end else '??'}")

                    # Status & Action Buttons
                    if row['current_status'] == "Pending":
                        col2.warning("⏳ Pending")
                        if col4.button("▶️ Start", key=f"st_{gate_id}", use_container_width=True):
                            conn.table("job_planning").update({"current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()}).eq("id", gate_id).execute()
                            st.cache_data.clear(); st.rerun()
                    elif row['current_status'] == "Active":
                        col2.info("🚀 Active")
                        if col4.button("✅ Close", key=f"cl_{gate_id}", use_container_width=True):
                            conn.table("job_planning").update({"current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()}).eq("id", gate_id).execute()
                            st.cache_data.clear(); st.rerun()
                    else:
                        col2.success("🏁 Completed")

                    # --- SUB-TASK NESTED SECTION ---
                    with st.expander("➕ Add Single Gate to Plan", expanded=False):
    with st.form("add_gate_form", clear_on_submit=True):
        sc1, sc2, sc3 = st.columns([2, 2, 1])
        ng_gate = sc1.selectbox("Process Gate", all_activities)
        ng_dates = sc2.date_input("Planned Window", [date.today(), date.today()+timedelta(days=5)])
        ng_order = sc3.number_input("Step Order", min_value=1, value=len(current_job_steps)+1)
        
        # New Option: Auto-populate sub-tasks?
        auto_sub = st.checkbox("Auto-add standard sub-tasks from Master?", value=True)
        
        if st.form_submit_button("🚀 Add to Plan"):
            if len(ng_dates) == 2:
                # 1. Insert the Main Gate
                gate_res = conn.table("job_planning").insert({
                    "job_no": target_job, 
                    "gate_name": ng_gate, 
                    "step_order": ng_order, 
                    "planned_start_date": ng_dates[0].isoformat(), 
                    "planned_end_date": ng_dates[1].isoformat(), 
                    "current_status": "Pending"
                }).execute()
                
                # 2. Logic to Auto-Add Sub-tasks
                if auto_sub and gate_res.data:
                    new_gate_id = gate_res.data[0]['id']
                    
                    # Fetch template sub-tasks for this gate name
                    m_subs = conn.table("master_sub_tasks").select("sub_task_name").eq("gate_name", ng_gate).execute()
                    
                    if m_subs.data:
                        sub_payload = [{
                            "project_id": int(job_internal_id) if 'job_internal_id' in locals() else None,
                            "parent_gate_id": int(new_gate_id),
                            "sub_task_name": s['sub_task_name'],
                            "current_status": "Pending"
                        } for s in m_subs.data]
                        
                        conn.table("job_sub_tasks").insert(sub_payload).execute()
                
                st.cache_data.clear()
                st.success(f"Added {ng_gate} with standard sub-tasks!")
                st.rerun()


# --- TAB 2: DAILY WORK ENTRY ---
with tab_entry:
    st.subheader("👷 Labor Output Entry")
    
    unit_map = {
        "Welding": "MTs", 
        "Buffing": "Sq.Ft", 
        "Painting": "Sq.Ft",
        "Cutting": "Nos", 
        "Fitting": "Nos", 
        "Grinding": "Nos",
        "Assembly": "Nos", 
        "Others": "Nos"
    }

    f_act = st.selectbox("🎯 Select Current Activity", all_activities, key="act_main")
    current_unit = unit_map.get(f_act, "Nos")

    with st.form("prod_form", clear_on_submit=True):
        st.markdown(f"Logging work for: **{f_act}** | Target Unit: **{current_unit}**")
        
        f1, f2, f3 = st.columns(3)
        f_sup = f1.selectbox("Supervisor", base_supervisors)
        f_wrk = f1.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
        
        f_job = f2.selectbox("Job Code", ["-- Select --"] + all_jobs)
        f2.caption(f"Unit type: {current_unit}")
        
        f_hrs = f3.number_input("Hours Spent", min_value=0.0, step=0.5, format="%.1f")
        f_out = f3.number_input(f"Total Output ({current_unit})", min_value=0.0, format="%.2f")
        
        f_nts = st.text_area("Task Details / Remarks", placeholder="Enter specific details here...")

        if st.form_submit_button("🚀 Log Productivity", use_container_width=True):
            if f_act == "Others" and not f_nts.strip():
                st.error("⚠️ Please provide details in 'Task Details' for 'Others'.")
            elif "-- Select --" in [f_wrk, f_job]:
                st.error("❌ Selection Missing: Please select both Worker and Job Code.")
            elif f_hrs <= 0:
                st.error("❌ Invalid Hours: Must be greater than 0.")
            else:
                try:
                    conn.table("production").insert({
                        "Supervisor": f_sup, 
                        "Worker": f_wrk, 
                        "Job_Code": f_job,
                        "Activity": f_act, 
                        "Hours": f_hrs, 
                        "Output": f_out, 
                        "Unit": current_unit,
                        "Notes": f_nts,
                        "created_at": datetime.now(IST).isoformat()
                    }).execute()
                    
                    st.cache_data.clear()
                    st.success(f"✅ Success! {f_out} {current_unit} recorded.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Database Error: {e}")

# --- TAB 3: ANALYTICS ---
with tab_analytics:
    st.subheader("📅 Production Shift Report")
    
    a1, a2 = st.columns([1, 3])
    with a1:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    with a2:
        report_date = st.date_input("Select Report Date", datetime.now(IST).date())

    if not df_logs.empty and 'created_at' in df_logs.columns:
        df_logs['created_at'] = pd.to_datetime(df_logs['created_at'], errors='coerce')
        df_logs = df_logs.dropna(subset=['created_at']).copy()
        
        if df_logs['created_at'].dt.tz is None:
            df_logs['created_at'] = df_logs['created_at'].dt.tz_localize('UTC')
        
        df_logs['ist_time'] = df_logs['created_at'].dt.tz_convert(IST)
        filtered_logs = df_logs[df_logs['ist_time'].dt.date == report_date].copy()
        
        if not filtered_logs.empty:
            filtered_logs['Logged At'] = filtered_logs['ist_time'].dt.strftime('%I:%M %p')
            filtered_logs = filtered_logs.sort_values('ist_time', ascending=False)
            
            st.dataframe(
                filtered_logs[['Logged At', 'Worker', 'Job_Code', 'Activity', 'Hours', 'Output', 'Unit', 'Notes']], 
                hide_index=True,
                use_container_width=True
            )
            
            m1, m2 = st.columns(2)
            m1.metric("Total Man-Hours", f"{filtered_logs['Hours'].sum():.1f} Hrs")
            m2.metric("Total Entries", len(filtered_logs))
        else:
            st.info(f"No entries found for {report_date.strftime('%d %b %Y')}.")
    else:
        st.warning("No logs found in the database.")

# --- TAB 4: MANAGE MASTERS ---
with tab_master:
    st.divider()
    st.subheader("📋 Sub-task Templates")
    with st.form("new_sub_template"):
        t_gate = st.selectbox("Assign to Gate", all_activities)
        t_sub = st.text_input("Sub-task Name (e.g., Grinding)")
        if st.form_submit_button("Save Template"):
            conn.table("master_sub_tasks").insert({"gate_name": t_gate, "sub_task_name": t_sub}).execute()
            st.cache_data.clear(); st.rerun()
            
    # Show existing templates
    m_sub_df = conn.table("master_sub_tasks").select("*").execute()
    if m_sub_df.data:
        st.dataframe(pd.DataFrame(m_sub_df.data)[['gate_name', 'sub_task_name']], hide_index=True)
