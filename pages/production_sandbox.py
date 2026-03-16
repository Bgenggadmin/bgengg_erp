import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master ERP | B&G", layout="wide", page_icon="🏗️")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_master_data():
    try:
        plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        gate_res = conn.table("production_gates").select("*").order("step_order").execute()
        job_plan_res = conn.table("job_planning").select("*").order("step_order").execute()
        
        return (pd.DataFrame(plan_res.data or []), 
                pd.DataFrame(prod_res.data or []), 
                pd.DataFrame(gate_res.data or []),
                pd.DataFrame(job_plan_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_projects, df_logs, df_gates, df_job_plans = get_master_data()

# --- 3. DYNAMIC MAPPING ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
all_activities = ["Cutting", "Fitting", "Welding", "Grinding", "Painting", "Assembly", "Buffing", "Others"]
all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []
all_workers = sorted(df_logs['Worker'].unique().tolist()) if not df_logs.empty else []

# --- 4. NAVIGATION ---
tab_plan, tab_entry, tab_analytics = st.tabs(["🏗️ Scheduling & Execution", "👷 Daily Entry", "📊 Analytics & Gantt"])

# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", all_jobs)
    
    current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()

    # --- SECTION A: SCHEDULING (INSERT) ---
    with st.expander("📅 Step 1: Design Schedule (New Gates)", expanded=False):
        with st.form("add_schedule_form"):
            c1, c2, c3 = st.columns([2, 2, 1])
            g_name = c1.selectbox("Gate Name", all_activities)
            d_range = c2.date_input("Planned Schedule", [date.today(), date.today() + timedelta(days=5)])
            g_order = c3.number_input("Sequence", min_value=1, value=len(current_job_steps)+1)
            
            if st.form_submit_button("🚀 Save to Schedule"):
                if len(d_range) == 2:
                    conn.table("job_planning").insert({
                        "job_no": target_job, "gate_name": g_name, "step_order": g_order,
                        "planned_start_date": d_range[0].isoformat(),
                        "planned_end_date": d_range[1].isoformat(),
                        "current_status": "Pending"
                    }).execute()
                    st.cache_data.clear()
                    st.rerun()

    # --- SECTION B: EDIT / DELETE LOGIC ---
    if not current_job_steps.empty:
        with st.expander("📝 Edit or Remove Planned Gates", expanded=False):
            st.info("Modify sequence or dates for existing gates. Changes reflect on Gantt instantly.")
            
            for _, edit_row in current_job_steps.sort_values('step_order').iterrows():
                e_id = edit_row['id']
                with st.container(border=True):
                    ec1, ec2, ec3, ec4 = st.columns([2, 2, 1, 1])
                    
                    # Pre-load existing gate index
                    gate_idx = all_activities.index(edit_row['gate_name']) if edit_row['gate_name'] in all_activities else 0
                    u_gate = ec1.selectbox("Gate", all_activities, index=gate_idx, key=f"e_name_{e_id}")
                    
                    # Pre-load dates
                    st_dt = pd.to_datetime(edit_row['planned_start_date']).date() if not pd.isna(edit_row['planned_start_date']) else date.today()
                    en_dt = pd.to_datetime(edit_row['planned_end_date']).date() if not pd.isna(edit_row['planned_end_date']) else date.today()
                    u_dates = ec2.date_input("Dates", [st_dt, en_dt], key=f"e_date_{e_id}")
                    
                    u_order = ec3.number_input("Seq", value=int(edit_row['step_order']), key=f"e_order_{e_id}")
                    
                    with ec4:
                        st.write("") # Spacer
                        if st.button("💾 Save", key=f"save_{e_id}", use_container_width=True):
                            if len(u_dates) == 2:
                                conn.table("job_planning").update({
                                    "gate_name": u_gate,
                                    "planned_start_date": u_dates[0].isoformat(),
                                    "planned_end_date": u_dates[1].isoformat(),
                                    "step_order": u_order
                                }).eq("id", e_id).execute()
                                st.cache_data.clear()
                                st.rerun()
                        
                        if st.button("🗑️ Del", key=f"del_{e_id}", use_container_width=True, type="secondary"):
                            conn.table("job_planning").delete().eq("id", e_id).execute()
                            st.cache_data.clear()
                            st.rerun()

    st.divider()

    # --- SECTION C: EXECUTION TRACK ---
    if not current_job_steps.empty:
        st.subheader(f"🏁 Execution Track: {target_job}")
        for index, row in current_job_steps.sort_values('step_order').iterrows():
            status = row['current_status']
            p_start_val, p_end_val = row.get('planned_start_date'), row.get('planned_end_date')

            if pd.isna(p_start_val) or pd.isna(p_end_val):
                continue 

            p_start, p_end = pd.to_datetime(p_start_val).date(), pd.to_datetime(p_end_val).date()
            
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                col1.markdown(f"**{row['step_order']}. {row['gate_name']}**")
                col1.caption(f"Planned: {p_start.strftime('%d %b')} — {p_end.strftime('%d %b')}")
                
                if status == "Pending":
                    col2.warning("⏳ Pending")
                    if col4.button("▶️ Start", key=f"start_btn_{row['id']}"):
                        conn.table("job_planning").update({
                            "current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()
                        }).eq("id", row['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
                        
                elif status == "Active":
                    col2.info("🚀 Active")
                    if date.today() > p_end:
                        delay = (date.today() - p_end).days
                        col3.metric("Status", "DELAYED", delta=f"{delay}d", delta_color="inverse")
                    else:
                        col3.success("On Track")
                    if col4.button("✅ Close", key=f"end_btn_{row['id']}"):
                        conn.table("job_planning").update({
                            "current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()
                        }).eq("id", row['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
                        
                elif status == "Completed":
                    col2.success("🏁 Done")
                    a_s = pd.to_datetime(row['actual_start_date']).date() if row['actual_start_date'] else "N/A"
                    a_e = pd.to_datetime(row['actual_end_date']).date() if row['actual_end_date'] else "N/A"
                    col3.write(f"Actual: {a_s} to {a_e}")
    else:
        st.info("No schedule defined for this job yet.")

# --- TAB 2: DAILY WORK ENTRY ---
with tab_entry:
    st.subheader("👷 Labor Output Entry")
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="entry_job_sel")
    
    if f_job != "-- Select --":
        active_gate_query = conn.table("job_planning").select("gate_name").eq("job_no", f_job).eq("current_status", "Active").execute()
        active_options = [g['gate_name'] for g in active_gate_query.data]
        
        if active_options:
            f_act = st.selectbox("🎯 Current Active Gate", active_options)
            with st.form("prod_form", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                f_sup = f1.selectbox("Supervisor", base_supervisors)
                f_wrk = f1.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
                f_hrs = f2.number_input("Hours Spent", min_value=0.0, step=0.5)
                f_out = f3.number_input("Output Quantity", min_value=0.0)
                f_nts = st.text_area("Remarks")

                if st.form_submit_button("🚀 Log Productivity"):
                    conn.table("production").insert({
                        "Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job,
                        "Activity": f_act, "Hours": f_hrs, "Output": f_out,
                        "Notes": f_nts, "created_at": datetime.now(IST).isoformat()
                    }).execute()
                    st.cache_data.clear()
                    st.success("Entry Logged!")
                    st.rerun()
        else:
            st.error("⚠️ Supervisor must 'Start' a gate in the Planning tab.")

# --- TAB 3: ANALYTICS & GANTT ---
with tab_analytics:
    st.subheader("📊 Performance Analytics")
    
    
    if not df_job_plans.empty:
        gantt_list = []
        for _, row in df_job_plans.iterrows():
            if not pd.isna(row.get('planned_start_date')) and not pd.isna(row.get('planned_end_date')):
                gantt_list.append(dict(Job=f"{row['job_no']}", Start=row['planned_start_date'], 
                                       Finish=row['planned_end_date'], Type='Planned', Gate=row['gate_name']))
            
            if row.get('actual_start_date'):
                a_finish = row['actual_end_date'] if row['actual_end_date'] else datetime.now(IST).isoformat()
                gantt_list.append(dict(Job=f"{row['job_no']}", Start=row['actual_start_date'], 
                                       Finish=a_finish, Type='Actual', Gate=row['gate_name']))

        if gantt_list:
            df_g = pd.DataFrame(gantt_list)
            fig = px.timeline(df_g, x_start="Start", x_end="Finish", y="Job", color="Type",
                              hover_data=["Gate"], title="Critical Path: Planned vs Actual",
                              color_discrete_map={"Planned": "#E2E8F0", "Actual": "#3182CE"})
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

    if not df_logs.empty:
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce')
            fig_pie = px.pie(df_logs, values='Hours', names='Activity', hole=0.4, title="Man-Hour Distribution")
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            st.markdown("### 📝 Recent Production Logs")
            st.dataframe(df_logs[['Worker', 'Job_Code', 'Activity', 'Hours']].head(15), hide_index=True)
