import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETTINGS ---
st.set_page_config(page_title="B&G Production Control", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)
IST = pytz.timezone('Asia/Kolkata')

# --- 2. DATA ENGINES ---
def get_data():
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    df_p = pd.DataFrame(p.data or [])
    df_l = pd.DataFrame(l.data or [])
    
    # Fix timezones immediately to avoid comparison errors
    if not df_p.empty:
        df_p['created_at'] = pd.to_datetime(df_p['created_at']).dt.tz_localize(None)
    if not df_l.empty:
        df_l['created_at'] = pd.to_datetime(df_l['created_at']).dt.tz_localize(None)
    
    return df_p, df_l

df_jobs, df_logs = get_data()

# --- 3. THE PLANNING LOGIC ---
RECIPE = {
    "1. Engineering": 7, "2. Marking/Cutting": 5, "3. Shell Fab": 15,
    "4. Drive Assembly (Parallel)": 12, "5. Main Assembly": 7,
    "6. Hydro/NDT": 4, "7. Finishing/Dispatch": 3
}

# --- 4. NAVIGATION ---
menu = st.sidebar.radio("Navigate", ["📊 Founder Dashboard", "📅 Job-wise Activity Plan", "👷 Daily Logging", "🛠️ Master Data"])

# --- TAB 1: MASTER DATA ---
if menu == "🛠️ Master Data":
    st.header("🛠️ Master Resource Management")
    col1, col2 = st.columns(2)
    with col1:
        new_worker = st.text_input("New Worker Name")
        if st.button("Add Worker") and new_worker:
            conn.table("production").insert({"Worker": new_worker, "Notes": "MASTER_DATA", "Hours": 0, "Activity": "N/A"}).execute()
            st.success(f"{new_worker} Added")
    with col2:
        new_act = st.text_input("New Activity Type")
        if st.button("Add Activity") and new_act:
            conn.table("production").insert({"Activity": new_act, "Notes": "MASTER_DATA", "Hours": 0, "Worker": "SYSTEM"}).execute()
            st.success("Activity Added")

# --- TAB 2: JOB-WISE ACTIVITY PLAN ---
elif menu == "📅 Job-wise Activity Plan":
    st.header("📅 Planned Timeline vs Actuals")
    if not df_jobs.empty:
        selected_job = st.selectbox("Select Job", df_jobs['job_no'].unique())
        job_data = df_jobs[df_jobs['job_no'] == selected_job].iloc[0]
        
        # Calculate Dates
        start = job_data['created_at']
        plan_rows = []
        curr = start
        
        for act, days in RECIPE.items():
            t_start = start + timedelta(days=7) if "Parallel" in act else curr
            t_end = t_start + timedelta(days=days)
            
            # Get actual logs for this specific activity and job
            act_hrs = 0
            if not df_logs.empty:
                act_hrs = df_logs[(df_logs['Job_Code'] == str(selected_job)) & (df_logs['Activity'] == act)]['Hours'].sum()

            plan_rows.append({
                "Activity": act, 
                "Start": t_start, # Keep as datetime for Plotly
                "End": t_end,     # Keep as datetime for Plotly
                "Days": days,
                "Actual Hrs": act_hrs,
                "Status": "✅ Done" if act_hrs > 0 else "⏳ Pending"
            })
            if "Parallel" not in act: curr = t_end
            
        df_plan = pd.DataFrame(plan_rows)
        
        # Display table with formatted dates for the user
        display_plan = df_plan.copy()
        display_plan['Start'] = display_plan['Start'].dt.strftime('%d-%b')
        display_plan['End'] = display_plan['End'].dt.strftime('%d-%b')
        st.table(display_plan[["Activity", "Start", "End", "Days", "Actual Hrs", "Status"]])
        
        if st.button("Generate Critical Path Chart"):
            # This uses the hidden datetime objects to avoid TypeError
            fig = px.timeline(df_plan, x_start="Start", x_end="End", y="Activity", color="Status")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

# --- TAB 3: DAILY LOGGING ---
elif menu == "👷 Daily Logging":
    st.header("👷 Shop Floor Entry")
    with st.form("log_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_job = c1.selectbox("Job Code", df_jobs['job_no'].unique() if not df_jobs.empty else [])
        # Filter dropdowns to only show unique names from logs
        f_wrk = c1.selectbox("Worker", df_logs['Worker'].unique() if not df_logs.empty else [])
        f_act = c2.selectbox("Activity", list(RECIPE.keys()) + (df_logs['Activity'].unique().tolist()))
        f_hrs = c2.number_input("Actual Hours Spent", min_value=0.0, step=0.5)
        f_out = c2.number_input("Output Value", min_value=0.0)
        f_nts = st.text_input("Remarks/Notes")
        
        if st.form_submit_button("Save Log Entry", type="primary"):
            conn.table("production").insert({
                "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                "Job_Code": str(f_job), "Worker": f_wrk, "Activity": f_act,
                "Hours": f_hrs, "Output": f_out, "Notes": f_nts
            }).execute()
            st.success("Log Saved.")
            st.rerun()

# --- TAB 4: FOUNDER DASHBOARD ---
elif menu == "📊 Founder Dashboard":
    st.header("📈 Production Master Table")
    if not df_logs.empty:
        display_df = df_logs[df_logs['Notes'] != "MASTER_DATA"].copy()
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Man-Hours spent", f"{display_df['Hours'].sum():.1f}")
        m2.metric("Active Projects", len(df_jobs))
        m3.metric("Last Log Entry", str(display_df['created_at'].max().strftime('%d-%b %H:%M')))
        
        st.subheader("All Shop Floor Logs")
        st.dataframe(display_df[['created_at', 'Job_Code', 'Worker', 'Activity', 'Hours', 'Output', 'Notes']], use_container_width=True)
        
        st.subheader("Total Hours Accumulated per Job")
        st.table(display_df.groupby('Job_Code')['Hours'].sum().reset_index())
