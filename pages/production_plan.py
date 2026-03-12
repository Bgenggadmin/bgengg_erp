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

# --- 2. DATA ENGINE (Includes Purchase Integration) ---
def get_data():
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    # Pulling from purchase table for material alerts
    pur = conn.table("purchase_orders").select("*").execute() 
    
    df_p = pd.DataFrame(p.data or [])
    df_l = pd.DataFrame(l.data or [])
    df_pur = pd.DataFrame(pur.data or [])
    
    if not df_p.empty:
        df_p['created_at'] = pd.to_datetime(df_p['created_at']).dt.tz_localize(None)
    return df_p, df_l, df_pur

df_jobs, df_logs, df_purchase = get_data()

# --- 3. GLOBAL RECIPE ---
DEFAULT_TASKS = [
    {"Activity": "1. Engineering", "Days": 7, "Type": "Sequential"},
    {"Activity": "2. Marking/Cutting", "Days": 5, "Type": "Sequential"},
    {"Activity": "3. Shell Fab", "Days": 15, "Type": "Sequential"},
    {"Activity": "4. Drive Assembly", "Days": 12, "Type": "Parallel"},
    {"Activity": "5. Main Assembly", "Days": 7, "Type": "Sequential"},
    {"Activity": "6. Hydro/NDT", "Days": 4, "Type": "Sequential"},
    {"Activity": "7. Finishing/Dispatch", "Days": 3, "Type": "Sequential"}
]

menu = st.sidebar.radio("Navigate", ["📊 Founder Dashboard", "📅 Job-wise Activity Plan", "👷 Daily Logging", "🛠️ Master Data"])

# --- TAB 1: FOUNDER DASHBOARD (Actionable & Minimal) ---
if menu == "📊 Founder Dashboard":
    st.header("📊 Executive Control Center")
    
    # KPIs
    c1, c2, c3 = st.columns(3)
    c1.metric("Active Projects", len(df_jobs))
    c2.metric("Total Shop Hours", f"{df_logs['Hours'].sum():.1f}")
    
    # 1. MATERIAL SHORTAGE (Integrated from Purchase Console)
    st.subheader("⚠️ Critical Material Alerts")
    if not df_purchase.empty:
        # Filter for shortages or delays
        shortages = df_purchase[df_purchase['status'].str.contains('Shortage|Delayed|Pending', case=False, na=False)]
        if not shortages.empty:
            st.error("Shortage detected in the following items:")
            st.dataframe(shortages[['job_no', 'item_name', 'status', 'expected_delivery']], use_container_width=True)
        else:
            st.success("✅ All materials cleared for production.")

    # 2. JOB STATUS TABLE
    st.subheader("📂 Production Progress by Job")
    if not df_logs.empty:
        summary = df_logs[df_logs['Notes'] != "MASTER_DATA"].groupby('Job_Code').agg({'Hours':'sum', 'Output':'sum'}).reset_index()
        st.table(summary)

# --- TAB 2: JOB-WISE ACTIVITY PLAN (With Critical Path Merge Logic) ---
elif menu == "📅 Job-wise Activity Plan":
    st.header("📅 Interactive Critical Path Scheduler")
    if not df_jobs.empty:
        selected_job = st.selectbox("Select Job", df_jobs['job_no'].unique())
        job_data = df_jobs[df_jobs['job_no'] == selected_job].iloc[0]
        
        # Check specific material status
        if not df_purchase.empty:
            job_pur = df_purchase[df_purchase['job_no'] == str(selected_job)]
            if not job_pur[job_pur['status'] == 'Shortage'].empty:
                st.warning("🚨 Alert: This job has marked Material Shortages in Purchase Console.")

        edited_df = st.data_editor(pd.DataFrame(DEFAULT_TASKS), key="v4_editor", hide_index=True)

        # RECALCULATION WITH MERGE LOGIC
        start_date = job_data['created_at']
        plan_results = []
        kettle_end = start_date
        drive_end = start_date + timedelta(days=5) # Default offset for drive

        for i, row in edited_df.iterrows():
            # Main Kettle Path (Tasks 1, 2, 3)
            if i <= 2:
                t_start = kettle_end
                t_end = t_start + timedelta(days=row['Days'])
                kettle_end = t_end
                path_type = "Critical Path"
            # Parallel Drive Path (Task 4)
            elif i == 3:
                t_start = start_date + timedelta(days=5)
                t_end = t_start + timedelta(days=row['Days'])
                drive_end = t_end
                path_type = "Parallel/Buffer"
            # Assembly Merge Point (Task 5 onwards)
            else:
                # Main Assembly starts only when BOTH Kettle and Drive are ready
                merge_start = max(kettle_end, drive_end) if i == 4 else kettle_end
                t_start = merge_start
                t_end = t_start + timedelta(days=row['Days'])
                kettle_end = t_end
                path_type = "Critical Path"
            
            # Check Actuals
            act_hrs = df_logs[(df_logs['Job_Code'] == str(selected_job)) & (df_logs['Activity'] == row['Activity'])]['Hours'].sum() if not df_logs.empty else 0

            plan_results.append({
                "Activity": row['Activity'], "Start": t_start, "End": t_end, 
                "Days": row['Days'], "Actual Hrs": act_hrs, "Path": path_type
            })

        df_plan = pd.DataFrame(plan_results)
        
        # Display Table
        disp = df_plan.copy()
        disp['Start'] = disp['Start'].dt.strftime('%d-%b')
        disp['End'] = disp['End'].dt.strftime('%d-%b')
        st.table(disp[['Activity', 'Start', 'End', 'Days', 'Actual Hrs', 'Path']])

        if st.button("📊 Generate Critical Path Gantt"):
            fig = px.timeline(df_plan, x_start="Start", x_end="End", y="Activity", color="Path",
                             color_discrete_map={"Critical Path": "#EF553B", "Parallel/Buffer": "#636EFA"})
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

# --- TAB 3: DAILY LOGGING ---
elif menu == "👷 Daily Logging":
    st.header("👷 Shop Floor Productivity Entry")
    with st.form("final_log_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_job = c1.selectbox("Job Code", df_jobs['job_no'].unique() if not df_jobs.empty else [])
        
        master_acts = [t['Activity'] for t in DEFAULT_TASKS]
        logged_acts = df_logs['Activity'].unique().tolist() if not df_logs.empty else []
        f_act = c1.selectbox("Activity", sorted(list(set(master_acts + logged_acts))))
        
        # Filter for real workers (exclude system/master tags)
        worker_list = df_logs[df_logs['Worker'] != 'SYSTEM']['Worker'].unique().tolist() if not df_logs.empty else []
        f_wrk = c2.selectbox("Worker", worker_list if worker_list else ["Add in Master Data"])
        
        f_hrs = c2.number_input("Hours", min_value=0.0, step=0.5)
        f_out = c2.number_input("Output Value", min_value=0.0)
        f_nts = st.text_input("Remarks")
        
        if st.form_submit_button("💾 Save Log Entry", type="primary"):
            conn.table("production").insert({
                "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                "Job_Code": str(f_job), "Worker": f_wrk, "Activity": f_act,
                "Hours": f_hrs, "Output": f_out, "Notes": f_nts
            }).execute()
            st.success("Log Saved!")
            st.rerun()

# --- TAB 4: MASTER DATA ---
elif menu == "🛠️ Master Data":
    st.header("🛠️ ERP Resource Masters")
    c1, c2 = st.columns(2)
    with c1:
        nw = st.text_input("New Worker Name")
        if st.button("Register Worker") and nw:
            conn.table("production").insert({"Worker": nw, "Notes": "MASTER_DATA", "Hours": 0}).execute()
            st.success("Worker Registered")
    with c2:
        na = st.text_input("New Activity")
        if st.button("Register Activity") and na:
            conn.table("production").insert({"Activity": na, "Notes": "MASTER_DATA", "Hours": 0, "Worker": "SYSTEM"}).execute()
            st.success("Activity Registered")
