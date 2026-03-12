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

# --- 2. DATA ENGINE (With Protection) ---
def get_data():
    # Essential Tables
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    
    # Optional Purchase Table (Prevents APIError if table is missing)
    try:
        pur = conn.table("purchase_orders").select("*").execute()
        df_pur = pd.DataFrame(pur.data or [])
    except Exception:
        df_pur = pd.DataFrame(columns=['job_no', 'item_name', 'status', 'expected_delivery'])
    
    df_p = pd.DataFrame(p.data or [])
    df_l = pd.DataFrame(l.data or [])
    
    if not df_p.empty:
        df_p['created_at'] = pd.to_datetime(df_p['created_at']).dt.tz_localize(None)
    return df_p, df_l, df_pur

df_jobs, df_logs, df_purchase = get_data()

# --- 3. GLOBAL PLANNING RECIPE ---
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

# --- TAB 1: FOUNDER DASHBOARD ---
if menu == "📊 Founder Dashboard":
    st.header("📊 Executive Production Control")
    
    # KPI Row
    k1, k2, k3 = st.columns(3)
    k1.metric("Active Projects", len(df_jobs))
    k2.metric("Total Man-Hours", f"{df_logs['Hours'].sum():.1f}")
    k3.metric("Material Alerts", len(df_purchase[df_purchase['status'] == 'Shortage']) if not df_purchase.empty else 0)

    # 1. DISPATCH COUNTDOWN
    st.subheader("🏁 Dispatch Countdown & Urgency")
    if not df_jobs.empty:
        countdown_data = []
        for _, job in df_jobs.iterrows():
            # Critical Path Calculation for Dispatch Date
            seq_days = sum([t['Days'] for t in DEFAULT_TASKS if t['Type'] == "Sequential"])
            dispatch_date = job['created_at'] + timedelta(days=seq_days)
            days_left = (dispatch_date - datetime.now()).days
            
            countdown_data.append({
                "Job No": job['job_no'],
                "Client": job['client_name'],
                "Planned Dispatch": dispatch_date.strftime('%d-%b-%Y'),
                "Days Left": days_left,
                "Status": "🔴 OVERDUE" if days_left < 0 else "🟢 ON TRACK"
            })
        st.table(pd.DataFrame(countdown_data).sort_values("Days Left"))

    # 2. MATERIAL SHORTAGE NOTIFICATION
    st.subheader("⚠️ Material Shortages (Purchase Sync)")
    if not df_purchase.empty:
        shortages = df_purchase[df_purchase['status'].isin(['Shortage', 'Delayed', 'Pending'])]
        if not shortages.empty:
            st.error("Purchase Team reports missing materials for these jobs:")
            st.dataframe(shortages[['job_no', 'item_name', 'status', 'expected_delivery']], use_container_width=True)
        else:
            st.success("All materials confirmed in-house.")

# --- TAB 2: JOB-WISE ACTIVITY PLAN ---
elif menu == "📅 Job-wise Activity Plan":
    st.header("📅 Critical Path Scheduler")
    if not df_jobs.empty:
        selected_job = st.selectbox("Select Job", df_jobs['job_no'].unique())
        job_data = df_jobs[df_jobs['job_no'] == selected_job].iloc[0]
        
        # Interactive Lead Time Editor
        st.subheader("Edit Lead Times for this Job")
        edited_df = st.data_editor(pd.DataFrame(DEFAULT_TASKS), hide_index=True, key="job_editor")

        # RECALCULATION WITH MERGE LOGIC
        start_date = job_data['created_at']
        plan_results = []
        kettle_end = start_date
        drive_end = start_date + timedelta(days=5)

        for i, row in edited_df.iterrows():
            if i <= 2: # Kettle Branch
                t_start, t_end = kettle_end, kettle_end + timedelta(days=row['Days'])
                kettle_end = t_end
                path = "Critical"
            elif i == 3: # Parallel Drive
                t_start, t_end = start_date + timedelta(days=5), (start_date + timedelta(days=5)) + timedelta(days=row['Days'])
                drive_end = t_end
                path = "Buffer"
            else: # Merge Point (Assembly)
                # Assembly waits for the MAX of Kettle vs Drive
                m_start = max(kettle_end, drive_end) if i == 4 else kettle_end
                t_start, t_end = m_start, m_start + timedelta(days=row['Days'])
                kettle_end = t_end
                path = "Critical"
            
            # Fetch Actuals
            act_hrs = df_logs[(df_logs['Job_Code'] == str(selected_job)) & (df_logs['Activity'] == row['Activity'])]['Hours'].sum() if not df_logs.empty else 0

            plan_results.append({
                "Activity": row['Activity'], "Start": t_start, "End": t_end, 
                "Planned Days": row['Days'], "Actual Hrs": act_hrs, "Path": path
            })

        df_cp = pd.DataFrame(plan_results)
        
        # Display Plan Table
        view_df = df_cp.copy()
        view_df['Start'] = view_df['Start'].dt.strftime('%d-%b')
        view_df['End'] = view_df['End'].dt.strftime('%d-%b')
        st.dataframe(view_df[['Activity', 'Start', 'End', 'Planned Days', 'Actual Hrs', 'Path']], use_container_width=True)

        if st.button("📊 Show Critical Path Gantt"):
            fig = px.timeline(df_cp, x_start="Start", x_end="End", y="Activity", color="Path",
                             color_discrete_map={"Critical": "#D62728", "Buffer": "#1F77B4"})
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(fig, use_container_width=True)
            

# --- TAB 3: DAILY LOGGING ---
elif menu == "👷 Daily Logging":
    st.header("👷 Shop Floor Productivity Log")
    with st.form("log_form_vfinal", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_job = c1.selectbox("Job Code", df_jobs['job_no'].unique() if not df_jobs.empty else [])
        f_act = c1.selectbox("Activity", sorted(list(set([t['Activity'] for t in DEFAULT_TASKS] + (df_logs['Activity'].unique().tolist() if not df_logs.empty else [])))))
        
        # Pull Workers from Master Data (Notes == MASTER_DATA)
        worker_master = df_logs[df_logs['Notes'] == 'MASTER_DATA']['Worker'].unique().tolist() if not df_logs.empty else []
        f_wrk = c2.selectbox("Worker/Operator", worker_master if worker_master else ["No Workers Found"])
        f_hrs = c2.number_input("Actual Hours Spent", min_value=0.0, step=0.5)
        f_out = c2.number_input("Output (Mts/Joints)", min_value=0.0)
        
        if st.form_submit_button("💾 Save Entry", type="primary"):
            conn.table("production").insert({
                "Job_Code": str(f_job), "Worker": f_wrk, "Activity": f_act, 
                "Hours": f_hrs, "Output": f_out, "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
            }).execute()
            st.success("Log Saved!")
            st.rerun()

# --- TAB 4: MASTER DATA ---
elif menu == "🛠️ Master Data":
    st.header("🛠️ Production Masters")
    col1, col2 = st.columns(2)
    with col1:
        new_w = st.text_input("Register New Worker")
        if st.button("Add Worker") and new_w:
            conn.table("production").insert({"Worker": new_w, "Notes": "MASTER_DATA", "Hours": 0}).execute()
            st.success(f"{new_w} added to worker pool.")
    with col2:
        new_m = st.text_input("Register New Machine/Station")
        if st.button("Add Machine") and new_m:
            conn.table("production").insert({"Supervisor": new_m, "Notes": "MASTER_DATA", "Hours": 0}).execute()
            st.success(f"Station {new_m} registered.")
