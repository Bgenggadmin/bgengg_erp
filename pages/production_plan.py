import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP ---
st.set_page_config(page_title="B&G Interactive Planner", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)
IST = pytz.timezone('Asia/Kolkata')

def get_data():
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    df_p = pd.DataFrame(p.data or [])
    df_l = pd.DataFrame(l.data or [])
    if not df_p.empty:
        df_p['created_at'] = pd.to_datetime(df_p['created_at']).dt.tz_localize(None)
    return df_p, df_l

df_jobs, df_logs = get_data()

# --- 2. NAVIGATION ---
menu = st.sidebar.radio("Navigate", ["📊 Founder Dashboard", "📅 Job-wise Activity Plan", "👷 Daily Logging", "🛠️ Master Data"])

# --- TAB: JOB-WISE ACTIVITY PLAN (INTERACTIVE) ---
if menu == "📅 Job-wise Activity Plan":
    st.header("📅 Interactive Job Scheduler")
    
    if not df_jobs.empty:
        selected_job = st.selectbox("Select Job to Plan", df_jobs['job_no'].unique())
        job_data = df_jobs[df_jobs['job_no'] == selected_job].iloc[0]
        
        # Default Recipe
        base_tasks = [
            {"Activity": "1. Engineering", "Days": 7, "Type": "Sequential"},
            {"Activity": "2. Marking/Cutting", "Days": 5, "Type": "Sequential"},
            {"Activity": "3. Shell Fab", "Days": 15, "Type": "Sequential"},
            {"Activity": "4. Drive Assembly", "Days": 12, "Type": "Parallel"},
            {"Activity": "5. Main Assembly", "Days": 7, "Type": "Sequential"},
            {"Activity": "6. Hydro/NDT", "Days": 4, "Type": "Sequential"},
            {"Activity": "7. Finishing/Dispatch", "Days": 3, "Type": "Sequential"}
        ]

        st.subheader(f"Edit Lead Times for Job: {selected_job}")
        st.info("💡 Change the 'Days' below to recalculate the timeline. Start Date is based on Order Date.")
        
        # EDITABLE TABLE: Engineer can change "Days"
        edited_df = st.data_editor(
            pd.DataFrame(base_tasks),
            column_config={
                "Days": st.column_config.NumberColumn("Planned Days", min_value=1, step=1),
                "Type": st.column_config.SelectboxColumn("Path Type", options=["Sequential", "Parallel"])
            },
            hide_index=True,
            use_container_width=True
        )

        # RECALCULATION LOGIC
        start_date = job_data['created_at']
        plan_results = []
        current_cursor = start_date
        
        for index, row in edited_df.iterrows():
            # Parallel tasks start from project start + fixed offset (e.g. 7 days)
            t_start = start_date + timedelta(days=7) if row['Type'] == "Parallel" else current_cursor
            t_end = t_start + timedelta(days=row['Days'])
            
            # Fetch Actuals from Logs
            act_hrs = 0
            if not df_logs.empty:
                act_hrs = df_logs[(df_logs['Job_Code'] == str(selected_job)) & (df_logs['Activity'] == row['Activity'])]['Hours'].sum()

            plan_results.append({
                "Activity": row['Activity'],
                "Start": t_start,
                "End": t_end,
                "Planned Days": row['Days'],
                "Actual Hrs Logged": act_hrs,
                "Status": "✅ Active/Done" if act_hrs > 0 else "⏳ Waiting"
            })
            if row['Type'] == "Sequential":
                current_cursor = t_end

        df_final_plan = pd.DataFrame(plan_results)

        # DISPLAY FINAL CALCULATED DATES
        st.subheader("Final Calculated Schedule")
        view_df = df_final_plan.copy()
        view_df['Start'] = view_df['Start'].dt.strftime('%d-%b-%Y')
        view_df['End'] = view_df['End'].dt.strftime('%d-%b-%Y')
        st.dataframe(view_df[["Activity", "Start", "End", "Planned Days", "Actual Hrs Logged", "Status"]], use_container_width=True)

        if st.button("📊 View Critical Path Gantt"):
            fig = px.timeline(df_final_plan, x_start="Start", x_end="End", y="Activity", color="Status", 
                             title=f"Schedule for {selected_job}")
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

# --- (Other sections: Daily Logging, Master Data, Dashboard remain same as previous version) ---
elif menu == "👷 Daily Logging":
    st.header("👷 Shop Floor Entry")
    with st.form("log_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_job = c1.selectbox("Job Code", df_jobs['job_no'].unique() if not df_jobs.empty else [])
        f_wrk = c1.selectbox("Worker", df_logs['Worker'].unique() if not df_logs.empty else ["Add in Masters"])
        f_act = c2.selectbox("Activity", [t['Activity'] for t in base_tasks] + df_logs['Activity'].unique().tolist())
        f_hrs = c2.number_input("Actual Hours Spent", min_value=0.0, step=0.5)
        f_out = c2.number_input("Output Value", min_value=0.0)
        f_nts = st.text_input("Remarks")
        
        if st.form_submit_button("Save Log Entry", type="primary"):
            conn.table("production").insert({
                "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                "Job_Code": str(f_job), "Worker": f_wrk, "Activity": f_act,
                "Hours": f_hrs, "Output": f_out, "Notes": f_nts
            }).execute()
            st.success("Log Saved.")

elif menu == "🛠️ Master Data":
    st.header("🛠️ Resource Masters")
    col1, col2 = st.columns(2)
    with col1:
        nw = st.text_input("Register New Worker")
        if st.button("Add Worker") and nw:
            conn.table("production").insert({"Worker": nw, "Notes": "MASTER_DATA", "Hours": 0}).execute()
            st.success("Added")
    with col2:
        na = st.text_input("Register New Activity")
        if st.button("Add Activity") and na:
            conn.table("production").insert({"Activity": na, "Notes": "MASTER_DATA", "Hours": 0}).execute()
            st.success("Added")

elif menu == "📊 Founder Dashboard":
    st.header("📊 Executive Summary")
    if not df_logs.empty:
        display_df = df_logs[df_logs['Notes'] != "MASTER_DATA"].copy()
        st.subheader("Overall Job Progress (Actual Hours)")
        job_sum = display_df.groupby('Job_Code')['Hours'].sum().reset_index()
        st.table(job_sum)
        st.subheader("Raw Shop Floor Logs")
        st.dataframe(display_df[['created_at', 'Job_Code', 'Worker', 'Activity', 'Hours', 'Output']], use_container_width=True)
