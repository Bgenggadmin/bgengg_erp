import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETTINGS & CONNECTION ---
st.set_page_config(page_title="B&G Production Control", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)
IST = pytz.timezone('Asia/Kolkata')

# --- 2. GLOBAL DEFAULTS (The "Recipe") ---
DEFAULT_TASKS = [
    {"Activity": "1. Engineering", "Days": 7, "Type": "Sequential"},
    {"Activity": "2. Marking/Cutting", "Days": 5, "Type": "Sequential"},
    {"Activity": "3. Shell Fab", "Days": 15, "Type": "Sequential"},
    {"Activity": "4. Drive Assembly", "Days": 12, "Type": "Parallel"},
    {"Activity": "5. Main Assembly", "Days": 7, "Type": "Sequential"},
    {"Activity": "6. Hydro/NDT", "Days": 4, "Type": "Sequential"},
    {"Activity": "7. Finishing/Dispatch", "Days": 3, "Type": "Sequential"}
]

def get_data():
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    df_p = pd.DataFrame(p.data or [])
    df_l = pd.DataFrame(l.data or [])
    if not df_p.empty:
        df_p['created_at'] = pd.to_datetime(df_p['created_at']).dt.tz_localize(None)
    return df_p, df_l

df_jobs, df_logs = get_data()

# --- 3. NAVIGATION ---
menu = st.sidebar.radio("Navigate", ["📊 Founder Dashboard", "📅 Job-wise Activity Plan", "👷 Daily Logging", "🛠️ Master Data"])

# --- TAB: JOB-WISE ACTIVITY PLAN (WITH SAVE LOGIC) ---
if menu == "📅 Job-wise Activity Plan":
    st.header("📅 Interactive Job Scheduler")
    if not df_jobs.empty:
        selected_job = st.selectbox("Select Job to Plan", df_jobs['job_no'].unique())
        job_data = df_jobs[df_jobs['job_no'] == selected_job].iloc[0]
        
        st.subheader(f"Edit Lead Times for Job: {selected_job}")
        # The Editor: Planner changes Days here
        edited_df = st.data_editor(
            pd.DataFrame(DEFAULT_TASKS),
            column_config={
                "Days": st.column_config.NumberColumn("Planned Days", min_value=1),
                "Type": st.column_config.SelectboxColumn("Path", options=["Sequential", "Parallel"])
            },
            hide_index=True, key="plan_editor"
        )

        # Recalculate Timeline based on Edits
        start_date = job_data['created_at']
        plan_results = []
        current_cursor = start_date
        
        for _, row in edited_df.iterrows():
            t_start = start_date + timedelta(days=5) if row['Type'] == "Parallel" else current_cursor
            t_end = t_start + timedelta(days=row['Days'])
            
            act_hrs = 0
            if not df_logs.empty:
                act_hrs = df_logs[(df_logs['Job_Code'] == str(selected_job)) & (df_logs['Activity'] == row['Activity'])]['Hours'].sum()

            plan_results.append({
                "Activity": row['Activity'], "Start": t_start, "End": t_end,
                "Days": row['Days'], "Actual Hrs": act_hrs, 
                "Status": "✅ Active" if act_hrs > 0 else "⏳ Waiting"
            })
            if row['Type'] == "Sequential": current_cursor = t_end

        df_final = pd.DataFrame(plan_results)
        
        # Display Final Plan Table
        view_df = df_final.copy()
        view_df['Start'] = view_df['Start'].dt.strftime('%d-%b-%Y')
        view_df['End'] = view_df['End'].dt.strftime('%d-%b-%Y')
        st.dataframe(view_df[["Activity", "Start", "End", "Days", "Actual Hrs", "Status"]], use_container_width=True)

        if st.button("📊 Show Gantt Chart"):
            fig = px.timeline(df_final, x_start="Start", x_end="End", y="Activity", color="Status")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

# --- TAB: DAILY LOGGING (FIXED SUBMIT & NAME ERROR) ---
elif menu == "👷 Daily Logging":
    st.header("👷 Shop Floor Entry")
    # Wrap in a proper form with a submit button
    with st.form("logging_form_v2", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_job = c1.selectbox("Job Code", df_jobs['job_no'].unique() if not df_jobs.empty else [])
        
        # Pull activities from the global DEFAULT_TASKS to avoid NameError
        master_acts = [t['Activity'] for t in DEFAULT_TASKS]
        logged_acts = df_logs['Activity'].unique().tolist() if not df_logs.empty else []
        f_act = c1.selectbox("Activity", sorted(list(set(master_acts + logged_acts))))
        
        f_wrk = c2.selectbox("Worker", df_logs['Worker'].unique() if not df_logs.empty else ["Register in Masters"])
        f_hrs = c2.number_input("Actual Hours", min_value=0.0, step=0.5)
        f_out = c2.number_input("Output Value", min_value=0.0)
        f_nts = st.text_input("Remarks")
        
        # The Missing Submit Button
        submit = st.form_submit_button("💾 Save Log Entry", type="primary")
        
        if submit:
            if f_job and f_wrk:
                conn.table("production").insert({
                    "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                    "Job_Code": str(f_job), "Worker": f_wrk, "Activity": f_act,
                    "Hours": f_hrs, "Output": f_out, "Notes": f_nts
                }).execute()
                st.success(f"Entry for {f_job} saved successfully!")
                st.rerun()
            else:
                st.error("Please select a Job and Worker.")

# --- TAB: MASTER DATA ---
elif menu == "🛠️ Master Data":
    st.header("🛠️ Resource Masters")
    col1, col2 = st.columns(2)
    with col1:
        nw = st.text_input("New Worker Name")
        if st.button("Add Worker") and nw:
            conn.table("production").insert({"Worker": nw, "Notes": "MASTER_DATA", "Hours": 0}).execute()
            st.success("Worker Registered")
    with col2:
        na = st.text_input("New Activity Name")
        if st.button("Add Activity") and na:
            conn.table("production").insert({"Activity": na, "Notes": "MASTER_DATA", "Hours": 0, "Worker": "SYSTEM"}).execute()
            st.success("Activity Registered")

# --- TAB: FOUNDER DASHBOARD ---
elif menu == "📊 Founder Dashboard":
    st.header("📊 Executive Production Summary")
    if not df_logs.empty:
        # Filter out Master Data placeholders
        display_df = df_logs[df_logs['Notes'] != "MASTER_DATA"].copy()
        
        # Table 1: Hour Accumulation
        st.subheader("Job-wise Man-Hour Total")
        job_stats = display_df.groupby('Job_Code')['Hours'].sum().reset_index()
        st.table(job_stats)
        
        # Table 2: Raw Logs
        st.subheader("Detailed Worker Logs")
        st.dataframe(display_df[['created_at', 'Job_Code', 'Worker', 'Activity', 'Hours', 'Output', 'Notes']], use_container_width=True)
