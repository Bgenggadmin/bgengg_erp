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

# --- 2. DATA ENGINE (With API Error Protection) ---
def get_data():
    # Fetch Projects & Logs (Essential)
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    
    # Fetch Purchase Alerts (Safe-check for table existence)
    try:
        pur = conn.table("purchase_orders").select("*").execute()
        df_pur = pd.DataFrame(pur.data or [])
    except Exception:
        # If table doesn't exist, create an empty dataframe to prevent crash
        df_pur = pd.DataFrame(columns=['job_no', 'item_name', 'status', 'expected_delivery'])
    
    df_p = pd.DataFrame(p.data or [])
    df_l = pd.DataFrame(l.data or [])
    
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

# --- TAB 1: FOUNDER DASHBOARD (With Dispatch Countdown) ---
if menu == "📊 Founder Dashboard":
    st.header("📊 Executive Production & Dispatch Control")
    
    # Calculate Dispatch Dates for all Jobs for the Countdown
    dispatch_list = []
    if not df_jobs.empty:
        for _, job in df_jobs.iterrows():
            total_days = sum([t['Days'] for t in DEFAULT_TASKS if t['Type'] == "Sequential"])
            # Parallel tasks don't add to total time unless they are longer, 
            # for simplicity we use the sequential sum here.
            planned_dispatch = job['created_at'] + timedelta(days=total_days)
            days_left = (planned_dispatch - datetime.now()).days
            dispatch_list.append({
                "Job": job['job_no'],
                "Client": job['client_name'],
                "Planned Dispatch": planned_dispatch.strftime('%d-%b-%Y'),
                "Days Remaining": days_left,
                "Urgency": "🔴 OVERDUE" if days_left < 0 else ("🟡 CRITICAL" if days_left < 7 else "🟢 ON TRACK")
            })

    # Display Countdown Table
    st.subheader("🏁 Dispatch Countdown (Live)")
    if dispatch_list:
        st.table(pd.DataFrame(dispatch_list).sort_values(by="Days Remaining"))
    
    # 1. MATERIAL SHORTAGE (Safe View)
    st.subheader("⚠️ Material Alerts (from Purchase)")
    if not df_purchase.empty:
        shortages = df_purchase[df_purchase['status'].str.contains('Shortage|Delayed|Pending', case=False, na=False)]
        if not shortages.empty:
            st.error("Shortage items found:")
            st.table(shortages[['job_no', 'item_name', 'status']])
        else:
            st.success("✅ No material shortages reported.")
    else:
        st.info("ℹ️ Purchase monitoring table not found. Connect 'purchase_orders' table to see alerts.")

# --- TAB 2: JOB-WISE ACTIVITY PLAN ---
elif menu == "📅 Job-wise Activity Plan":
    st.header("📅 Critical Path Scheduler")
    if not df_jobs.empty:
        selected_job = st.selectbox("Select Job", df_jobs['job_no'].unique())
        job_data = df_jobs[df_jobs['job_no'] == selected_job].iloc[0]
        
        # Merge Logic for Critical Path
        edited_df = st.data_editor(pd.DataFrame(DEFAULT_TASKS), key="v5_editor", hide_index=True)
        
        start_date = job_data['created_at']
        plan_results = []
        kettle_end = start_date
        drive_end = start_date + timedelta(days=5)

        for i, row in edited_df.iterrows():
            if i <= 2: # Kettle Branch
                t_start, t_end = kettle_end, kettle_end + timedelta(days=row['Days'])
                kettle_end = t_end
                path = "Critical"
            elif i == 3: # Drive Branch
                t_start, t_end = start_date + timedelta(days=5), (start_date + timedelta(days=5)) + timedelta(days=row['Days'])
                drive_end = t_end
                path = "Parallel"
            else: # Merge
                m_start = max(kettle_end, drive_end) if i == 4 else kettle_end
                t_start, t_end = m_start, m_start + timedelta(days=row['Days'])
                kettle_end = t_end
                path = "Critical"
            
            plan_results.append({"Activity": row['Activity'], "Start": t_start, "End": t_end, "Path": path})

        df_cp = pd.DataFrame(plan_results)
        st.table(df_cp.assign(Start=df_cp['Start'].dt.strftime('%d-%b'), End=df_cp['End'].dt.strftime('%d-%b')))

        if st.button("📊 Generate Critical Path Chart"):
            fig = px.timeline(df_cp, x_start="Start", x_end="End", y="Activity", color="Path",
                             color_discrete_map={"Critical": "#D62728", "Parallel": "#1F77B4"})
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)

# --- (Daily Logging and Master Data logic remains the same) ---
elif menu == "👷 Daily Logging":
    st.header("👷 Shop Floor Entry")
    with st.form("logging_v3", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_job = c1.selectbox("Job Code", df_jobs['job_no'].unique() if not df_jobs.empty else [])
        f_act = c1.selectbox("Activity", [t['Activity'] for t in DEFAULT_TASKS])
        f_wrk = c2.selectbox("Worker", df_logs['Worker'].unique() if not df_logs.empty else ["SYSTEM"])
        f_hrs = c2.number_input("Hours", min_value=0.0)
        if st.form_submit_button("Save Log", type="primary"):
            conn.table("production").insert({"Job_Code":str(f_job), "Worker":f_wrk, "Activity":f_act, "Hours":f_hrs}).execute()
            st.success("Logged.")
            st.rerun()

elif menu == "🛠️ Master Data":
    st.header("🛠️ Resource Masters")
    nw = st.text_input("New Worker Name")
    if st.button("Register") and nw:
        conn.table("production").insert({"Worker": nw, "Notes": "MASTER_DATA", "Hours": 0}).execute()
        st.success("Added")
