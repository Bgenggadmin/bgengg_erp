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
    
    # Filter plans for this specific job
    current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()

    # SECTION A: DATE-BASED SCHEDULING (Pre-Planning)
    with st.expander("📅 Step 1: Design Schedule (Start & End Dates)", expanded=False):
        st.info("Set the planned start and end dates for each gate to define the Critical Path.")
        
        with st.form("add_schedule_form"):
            c1, c2, c3 = st.columns([2, 2, 1])
            g_name = c1.selectbox("Gate Name", all_activities)
            # Date Range Picker
            d_range = c2.date_input("Planned Schedule", [date.today(), date.today() + timedelta(days=5)])
            g_order = c3.number_input("Step Order", min_value=1, value=len(current_job_steps)+1)
            
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

    st.divider()

    # SECTION B: LIVE EXECUTION TRACK (Moving the Job)
    if not current_job_steps.empty:
        st.subheader(f"🏁 Execution Track: {target_job}")
        
        for index, row in current_job_steps.sort_values('step_order').iterrows():
            status = row['current_status']
            p_start = pd.to_datetime(row['planned_start_date']).date()
            p_end = pd.to_datetime(row['planned_end_date']).date()
            
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                
                # Column 1: Info & Target
                col1.markdown(f"**{row['step_order']}. {row['gate_name']}**")
                col1.caption(f"Target: {p_start.strftime('%d %b')} to {p_end.strftime('%d %b')}")
                
                # Column 2 & 3: Progress & Alerts
                if status == "Pending":
                    col2.warning("⏳ Pending")
                    if col4.button("▶️ Start", key=f"start_{row['id']}"):
                        conn.table("job_planning").update({
                            "current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()
                        }).eq("id", row['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
                        
                elif status == "Active":
                    col2.info("🚀 Active")
                    # Delay Calculation (Critical Path Logic)
                    if date.today() > p_end:
                        delay = (date.today() - p_end).days
                        col3.metric("Status", f"DELAYED", delta=f"{delay} days", delta_color="inverse")
                    else:
                        col3.success("On Track")
                    
                    if col4.button("✅ Close", key=f"end_{row['id']}"):
                        conn.table("job_planning").update({
                            "current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()
                        }).eq("id", row['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
                        
                elif status == "Completed":
                    col2.success("🏁 Done")
                    act_start = pd.to_datetime(row['actual_start_date']).date()
                    act_end = pd.to_datetime(row['actual_end_date']).date()
                    col3.write(f"Actual: {act_start.strftime('%d %b')} - {act_end.strftime('%d %b')}")
    else:
        st.info("No schedule defined for this job yet.")

# --- TAB 2: DAILY WORK ENTRY (DYNAMIC) ---
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
            st.error("⚠️ No active gate. Supervisor must 'Start' the gate first.")

# --- TAB 3: ANALYTICS & GANTT ---
with tab_analytics:
    st.subheader("📊 Planned vs. Actual Performance")
    
    if not df_job_plans.empty:
        # Prepare Data for Gantt
        gantt_list = []
        for _, row in df_job_plans.iterrows():
            # Add PLANNED bars
            gantt_list.append(dict(Job=f"{row['job_no']}", Start=row['planned_start_date'], 
                                   Finish=row['planned_end_date'], Type='Planned Schedule', Gate=row['gate_name']))
            
            # Add ACTUAL bars (if started)
            if row['actual_start_date']:
                a_finish = row['actual_end_date'] if row['actual_end_date'] else datetime.now(IST).isoformat()
                gantt_list.append(dict(Job=f"{row['job_no']}", Start=row['actual_start_date'], 
                                       Finish=a_finish, Type='Actual Progress', Gate=row['gate_name']))

        if gantt_list:
            df_gantt = pd.DataFrame(gantt_list)
            fig = px.timeline(df_gantt, x_start="Start", x_end="Finish", y="Job", color="Type",
                              hover_data=["Gate"], title="Critical Path: Planned vs Actual Timeline",
                              color_discrete_map={"Planned Schedule": "#CBD5E0", "Actual Progress": "#4299E1"})
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)
            
        
    # Pie Chart for Man-Hours
    if not df_logs.empty:
        st.divider()
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce')
        fig_pie = px.pie(df_logs, values='Hours', names='Activity', hole=0.4, title="Man-Hour Distribution")
        st.plotly_chart(fig_pie, use_container_width=True)
