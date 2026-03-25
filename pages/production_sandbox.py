import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
import plotly.express as px
import io

# --- 1. SETUP & CONNECTION ---
IST = pytz.timezone('Asia/Kolkata')
TODAY_IST = datetime.now(IST).date()
st.set_page_config(page_title="Production Master ERP | B&G", layout="wide", page_icon="🏗️")

# --- PASSWORD PROTECTION ---
def check_password():
    def password_entered():
        if st.session_state["password"] == "9025":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    return True

if not check_password():
    st.stop()

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
        st.error(f"Master Sync Error: {e}")

master = st.session_state.get('master_data', {"workers": [], "staff": [], "gates": []})

# --- 3. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_master_data():
    try:
        p_res = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
        l_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        m_res = conn.table("production_gates").select("*").order("step_order").execute()
        j_res = conn.table("job_planning").select("*").order("step_order").execute()
        pur_res = conn.table("purchase_orders").select("*").execute()
        # New Sub-Tasks Table
        sub_res = conn.table("job_sub_tasks").select("*").execute()
        
        return (pd.DataFrame(p_res.data or []), 
                pd.DataFrame(l_res.data or []), 
                pd.DataFrame(m_res.data or []), 
                pd.DataFrame(j_res.data or []),
                pd.DataFrame(pur_res.data or []),
                pd.DataFrame(sub_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return [pd.DataFrame()] * 6

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
    
    # --- EXECUTIVE OVERDUE ALERTS ---
    if not df_sub_tasks.empty:
        overdue_mask = (pd.to_datetime(df_sub_tasks['planned_end_date']).dt.date < TODAY_IST) & (df_sub_tasks['current_status'] != "Completed")
        all_overdue = df_sub_tasks[overdue_mask]
        if not all_overdue.empty:
            with st.expander(f"🚨 CRITICAL: {len(all_overdue)} DELAYED SUB-TASKS", expanded=True):
                alert_df = all_overdue.merge(df_projects[['id', 'job_no']], left_on='project_id', right_on='id')
                for _, alert in alert_df.iterrows():
                    st.error(f"**{alert['job_no']}**: {alert['sub_task_name']} (Due: {pd.to_datetime(alert['planned_end_date']).strftime('%d-%b')})")

    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            current_project_id = int(p_data['id'])
            
            # --- DELIVERY & PROJECTION DASHBOARD ---
            with st.container(border=True):
                po_disp_dt = pd.to_datetime(p_data.get('po_delivery_date')).date() if pd.notnull(p_data.get('po_delivery_date')) else TODAY_IST
                rev_dt = pd.to_datetime(p_data.get('revised_delivery_date')).date() if pd.notnull(p_data.get('revised_delivery_date')) else None
                
                # Calculate Projection based on sub-task delays
                proj_subs = df_sub_tasks[df_sub_tasks['project_id'] == current_project_id]
                max_delay = 0
                if not proj_subs.empty:
                    delays = (TODAY_IST - pd.to_datetime(proj_subs[proj_subs['current_status'] != "Completed"]['planned_end_date']).dt.date).dt.days
                    max_delay = max(0, delays.max()) if not delays.empty else 0
                
                projected_dt = (rev_dt or po_disp_dt) + timedelta(days=max_delay)

                c1, c2, c3, c4 = st.columns(4)
                c1.write(f"📄 **PO No: {p_data.get('po_no', '---')}**")
                c2.metric("PO Dispatch", po_disp_dt.strftime('%d-%b'))
                c3.metric("Projected Delivery", projected_dt.strftime('%d-%b'), delta=f"{max_delay} Days Delay" if max_delay > 0 else "On Track", delta_color="inverse" if max_delay > 0 else "normal")
                
                if st.button("📝 Update PO Dates"):
                    @st.dialog("Update Commitment")
                    def update_dates():
                        n_po_disp = st.date_input("Original PO Dispatch", value=po_disp_dt)
                        n_rev = st.date_input("Revised Date", value=rev_dt if rev_dt else n_po_disp)
                        if st.button("Save Changes"):
                            conn.table("anchor_projects").update({"po_delivery_date": str(n_po_disp), "revised_delivery_date": str(n_rev)}).eq("id", current_project_id).execute()
                            st.cache_data.clear(); st.rerun()
                    update_dates()

            # --- EXECUTION GATES & SUB-TASKS ---
            st.divider()
            current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job].sort_values('step_order')
            
            if current_job_steps.empty:
                st.info("No plan for this job. Add a gate below.")
            
            # 1. Form to Add New Gate
            with st.expander("➕ Add Gate to Plan", expanded=False):
                with st.form("add_gate"):
                    g_col1, g_col2, g_col3 = st.columns([2, 2, 1])
                    ng_gate = g_col1.selectbox("Process Gate", all_activities)
                    ng_dates = g_col2.date_input("Planned Window", [TODAY_IST, TODAY_IST + timedelta(days=5)])
                    ng_order = g_col3.number_input("Step Order", value=len(current_job_steps)+1)
                    if st.form_submit_button("🚀 Add Gate"):
                        conn.table("job_planning").insert({"job_no": target_job, "gate_name": ng_gate, "step_order": ng_order, "planned_start_date": ng_dates[0].isoformat(), "planned_end_date": ng_dates[1].isoformat(), "current_status": "Pending"}).execute()
                        st.cache_data.clear(); st.rerun()

            # 2. Display Gates
            for _, row in current_job_steps.iterrows():
                with st.container(border=True):
                    gc1, gc2, gc3, gc4 = st.columns([2.5, 1, 1, 1])
                    gc1.markdown(f"### {row['gate_name']}")
                    gc1.caption(f"📅 {pd.to_datetime(row['planned_start_date']).strftime('%d %b')} - {pd.to_datetime(row['planned_end_date']).strftime('%d %b')}")
                    
                    # Status Control
                    if row['current_status'] == "Pending":
                        gc2.warning("⏳ Pending")
                        if gc4.button("▶️ Start", key=f"start_{row['id']}"):
                            conn.table("job_planning").update({"current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    elif row['current_status'] == "Active":
                        gc2.info("🚀 Active")
                        if gc4.button("✅ Close", key=f"close_{row['id']}"):
                            conn.table("job_planning").update({"current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    else:
                        gc2.success("🏁 Done")

                    # --- NESTED SUB-TASKS ---
                    with st.expander(f"📋 Sub-Work Detail ({row['gate_name']})", expanded=row['current_status']=="Active"):
                        # List existing
                        gate_subs = df_sub_tasks[df_sub_tasks['parent_gate_id'] == row['id']]
                        for _, sub in gate_subs.iterrows():
                            s_c1, s_c2, s_c3 = st.columns([3, 2, 1.5])
                            sub_done = sub['current_status'] == "Completed"
                            sub_overdue = (pd.to_datetime(sub['planned_end_date']).date() < TODAY_IST) and not sub_done
                            
                            icon = "✅" if sub_done else ("🚨" if sub_overdue else "⏳")
                            s_c1.markdown(f"{icon} {'~~' if sub_done else ''}{sub['sub_task_name']}{'~~' if sub_done else ''}")
                            s_c2.caption(f"Due: {pd.to_datetime(sub['planned_end_date']).strftime('%d %b')}")
                            
                            # Toggle / Delete
                            b1, b2 = s_c3.columns(2)
                            if b1.button("✔️" if not sub_done else "↩️", key=f"tog_{sub['id']}"):
                                new_stat = "Completed" if not sub_done else "Pending"
                                conn.table("job_sub_tasks").update({"current_status": new_stat}).eq("id", sub['id']).execute()
                                st.cache_data.clear(); st.rerun()
                            if b2.button("🗑️", key=f"del_sub_{sub['id']}"):
                                conn.table("job_sub_tasks").delete().eq("id", sub['id']).execute()
                                st.cache_data.clear(); st.rerun()
                        
                        # Add new sub-task
                        with st.form(key=f"add_sub_{row['id']}", clear_on_submit=True):
                            st.write("Add Sub-Item")
                            sn, sd = st.columns([2,1])
                            sub_n = sn.text_input("Work Detail")
                            sub_d = sd.date_input("Target", value=TODAY_IST + timedelta(days=2))
                            if st.form_submit_button("➕ Add"):
                                conn.table("job_sub_tasks").insert({"project_id": current_project_id, "parent_gate_id": int(row['id']), "sub_task_name": sub_n, "planned_start_date": TODAY_IST.isoformat(), "planned_end_date": sub_d.isoformat(), "current_status": "Pending"}).execute()
                                st.cache_data.clear(); st.rerun()

# --- TAB 2: DAILY ENTRY ---
with tab_entry:
    st.subheader("👷 Daily Labor Entry")
    f_job = st.selectbox("Select Job", ["-- Select --"] + all_jobs, key="ent_job")
    
    if f_job != "-- Select --":
        # Get gates for this job
        job_gates = df_job_plans[df_job_plans['job_no'] == f_job]
        active_gate_names = job_gates['gate_name'].tolist()
        
        with st.form("entry_form", clear_on_submit=True):
            f1, f2 = st.columns(2)
            sel_gate = f1.selectbox("Main Gate", active_gate_names)
            
            # Dynamic Sub-Work Selection
            gate_id = job_gates[job_gates['gate_name'] == sel_gate]['id'].values[0]
            sub_options = ["-- General --"] + df_sub_tasks[df_sub_tasks['parent_gate_id'] == gate_id]['sub_task_name'].tolist()
            sel_sub = f1.selectbox("Specific Sub-Work", sub_options)
            
            worker = f2.selectbox("Worker", all_workers)
            hrs = f2.number_input("Hours", min_value=0.5, step=0.5)
            notes = st.text_input("Remarks")
            
            if st.form_submit_button("🚀 Log Progress"):
                final_notes = f"Sub-Work: {sel_sub} | {notes}" if sel_sub != "-- General --" else notes
                conn.table("production").insert({"Job_Code": f_job, "Activity": sel_gate, "Worker": worker, "Hours": hrs, "notes": final_notes, "created_at": datetime.now(IST).isoformat()}).execute()
                st.cache_data.clear(); st.success("Logged!"); st.rerun()

# --- TAB 3: ANALYTICS & EXCEL ---
with tab_analytics:
    st.subheader("📊 Performance Reports")
    
    # 1. EXCEL EXPORT TOOL
    st.write("### 📥 Download Reports")
    def export_excel():
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            # Labor Analysis
            if not df_logs.empty:
                df_logs.to_excel(writer, sheet_name='Labor_Logs', index=False)
            # Status Analysis
            if not df_sub_tasks.empty:
                df_sub_tasks.to_excel(writer, sheet_name='SubTask_Checklist', index=False)
        return buffer.getvalue()
    
    st.download_button("📂 Download Excel Report", data=export_excel(), file_name=f"BG_Report_{TODAY_IST}.xlsx", mime="application/vnd.ms-excel")
    
    # 2. VISUALS (Sub-Work Hours)
    if not df_logs.empty:
        df_logs['Sub_Work'] = df_logs['notes'].apply(lambda x: x.split("Sub-Work: ")[1].split(" |")[0] if "Sub-Work: " in str(x) else "General")
        sub_hrs = df_logs.groupby('Sub_Work')['Hours'].sum().reset_index().sort_values('Hours', ascending=False)
        st.plotly_chart(px.bar(sub_hrs, x='Sub_Work', y='Hours', title="Hours by Specific Task Type"), use_container_width=True)

# --- TAB 4: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ Gate Master")
    with st.form("new_gate"):
        ng_name = st.text_input("Gate Name")
        ng_order = st.number_input("Order", value=len(df_master_gates)+1)
        if st.form_submit_button("Add Gate"):
            conn.table("production_gates").insert({"gate_name": ng_name, "step_order": ng_order}).execute()
            st.cache_data.clear(); st.rerun()
    if not df_master_gates.empty:
        st.dataframe(df_master_gates.sort_values('step_order')[['step_order', 'gate_name']], hide_index=True)
