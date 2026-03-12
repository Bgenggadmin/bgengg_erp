import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz

# --- 1. SETTINGS ---
st.set_page_config(page_title="B&G Production Control", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)
IST = pytz.timezone('Asia/Kolkata')

# --- 2. DATA ENGINES ---
def get_data():
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    # Filter 'Masters' out of the logs for the founder view
    df_l = pd.DataFrame(l.data or [])
    return pd.DataFrame(p.data or []), df_l

df_jobs, df_logs = get_data()

# --- 3. THE PLANNING & SCHEDULING LOGIC ---
# Standard Lead Times for Parallel Path Logic
RECIPE = {
    "1. Engineering": 7, "2. Marking/Cutting": 5, "3. Shell Fab": 15,
    "4. Drive Assembly (Parallel)": 12, "5. Main Assembly": 7,
    "6. Hydro/NDT": 4, "7. Finishing/Dispatch": 3
}

# --- 4. NAVIGATION ---
menu = st.sidebar.radio("Navigate", ["📊 Founder Dashboard", "📅 Job-wise Activity Plan", "👷 Daily Logging", "🛠️ Master Data"])

# --- TAB 4: MASTER DATA (ADD NEW RESOURCES) ---
if menu == "🛠️ Master Data":
    st.header("🛠️ Master Resource Management")
    st.info("Register New Job Codes, Workers, Machines, or Activities here.")
    
    col1, col2 = st.columns(2)
    with col1:
        new_worker = st.text_input("New Worker/Operator Name")
        if st.button("Add Worker") and new_worker:
            conn.table("production").insert({"Worker": new_worker, "Notes": "MASTER_DATA", "Hours": 0, "Activity": "N/A"}).execute()
            st.success(f"{new_worker} added.")

        new_machine = st.text_input("New Machine/Station (e.g., Lather-01)")
        if st.button("Add Machine") and new_machine:
            conn.table("production").insert({"Supervisor": new_machine, "Notes": "MASTER_DATA", "Hours": 0, "Activity": "N/A"}).execute()
            st.success(f"{new_machine} added.")

    with col2:
        new_act = st.text_input("New Activity Type")
        if st.button("Add Activity") and new_act:
            conn.table("production").insert({"Activity": new_act, "Notes": "MASTER_DATA", "Hours": 0}).execute()
            st.success(f"{new_act} added.")

# --- TAB 2: JOB-WISE ACTIVITY PLAN ---
elif menu == "📅 Job-wise Activity Plan":
    st.header("📅 Planned Timeline per Job")
    if not df_jobs.empty:
        selected_job = st.selectbox("Select Job to View Plan", df_jobs['job_no'].unique())
        job_data = df_jobs[df_jobs['job_no'] == selected_job].iloc[0]
        
        # Calculate Dates
        start = pd.to_datetime(job_data['created_at']).tz_localize(None)
        plan_rows = []
        curr = start
        for act, days in RECIPE.items():
            # Parallel logic for Drive Assembly
            t_start = start + timedelta(days=7) if "Parallel" in act else curr
            t_end = t_start + timedelta(days=days)
            plan_rows.append({"Activity": act, "Planned Start": t_start.strftime('%d-%b'), "Planned End": t_end.strftime('%d-%b'), "Days": days})
            if "Parallel" not in act: curr = t_end
            
        st.table(pd.DataFrame(plan_rows))
        
        if st.button("Show Critical Path Chart"):
            import plotly.express as px
            fig = px.timeline(pd.DataFrame(plan_rows), x_start="Planned Start", x_end="Planned End", y="Activity", color="Activity")
            st.plotly_chart(fig, use_container_width=True)

# --- TAB 3: DAILY LOGGING ---
elif menu == "👷 Daily Logging":
    st.header("👷 Shop Floor Entry")
    with st.form("log_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_job = c1.selectbox("Job Code", df_jobs['job_no'].unique() if not df_jobs.empty else [])
        f_wrk = c1.selectbox("Worker", df_logs['Worker'].unique() if not df_logs.empty else [])
        f_act = c2.selectbox("Activity", list(RECIPE.keys()) + (df_logs['Activity'].unique().tolist()))
        f_hrs = c2.number_input("Actual Hours Spent", min_value=0.0)
        f_out = c2.number_input("Output Value", min_value=0.0)
        f_nts = st.text_input("Remarks")
        
        if st.form_submit_button("Save Log Entry", type="primary"):
            conn.table("production").insert({
                "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                "Job_Code": str(f_job), "Worker": f_wrk, "Activity": f_act,
                "Hours": f_hrs, "Output": f_out, "Notes": f_nts
            }).execute()
            st.success("Log Saved.")

# --- TAB 1: FOUNDER DASHBOARD ---
elif menu == "📊 Founder Dashboard":
    st.header("📈 Executive Production Table")
    if not df_logs.empty:
        # Clean data for viewing
        display_df = df_logs[df_logs['Notes'] != "MASTER_DATA"].copy()
        
        # Summary Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Hours Logged", display_df['Hours'].sum())
        m2.metric("Active Jobs", len(df_jobs))
        m3.metric("Total Logs", len(display_df))
        
        st.subheader("Recent Activity Logs")
        st.dataframe(display_df[['created_at', 'Job_Code', 'Worker', 'Activity', 'Hours', 'Output', 'Notes']], use_container_width=True)
        
        st.subheader("Job-wise Hour Accumulation")
        job_summary = display_df.groupby('Job_Code')['Hours'].sum().reset_index()
        st.table(job_summary)
