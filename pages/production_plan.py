import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz

# --- 1. SETTINGS & CONNECTION ---
st.set_page_config(page_title="B&G Production Control", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)
IST = pytz.timezone('Asia/Kolkata')

# --- 2. DATA ENGINE ---
def get_data():
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    try:
        pur = conn.table("purchase_orders").select("*").execute()
        df_pur = pd.DataFrame(pur.data or [])
    except Exception:
        # Prevents app crash if table is missing or API fails
        df_pur = pd.DataFrame(columns=['job_no', 'item_name', 'status', 'expected_delivery', 'notes'])
    
    df_p = pd.DataFrame(p.data or [])
    df_l = pd.DataFrame(l.data or [])
    if not df_p.empty:
        df_p['created_at'] = pd.to_datetime(df_p['created_at']).dt.tz_localize(None)
    return df_p, df_l, df_pur

df_jobs, df_logs, df_purchase = get_data()

# Helper to pull masters (Worker, Machine, Engineer, Customer)
def get_master(m_type):
    if df_logs.empty: return []
    return sorted(df_logs[df_logs['Notes'] == m_type]['Worker'].unique().tolist())

# --- 3. NAVIGATION ---
menu = st.sidebar.radio("Navigate", ["📊 Founder Dashboard", "📅 Job-wise Activity Plan", "👷 Daily Logging", "🛠️ Master Data"])

# --- TAB: MASTER DATA ---
if menu == "🛠️ Master Data":
    st.header("🛠️ Resource Masters")
    c1, c2, c3 = st.columns(3)
    with c1:
        nw = st.text_input("New Worker")
        if st.button("Add Worker") and nw:
            conn.table("production").insert({"Worker": nw, "Notes": "WORKER_MASTER", "Hours": 0}).execute()
            st.success("Worker Registered")
        nm = st.text_input("New Machine")
        if st.button("Add Machine") and nm:
            conn.table("production").insert({"Worker": nm, "Notes": "MACHINE_MASTER", "Hours": 0}).execute()
            st.success("Machine Registered")
    with c2:
        ne = st.text_input("New Engineer")
        if st.button("Add Engineer") and ne:
            conn.table("production").insert({"Worker": ne, "Notes": "ENGINEER_MASTER", "Hours": 0}).execute()
            st.success("Engineer Registered")
    with c3:
        nc = st.text_input("New Customer")
        if st.button("Add Customer") and nc:
            conn.table("production").insert({"Worker": nc, "Notes": "CUSTOMER_MASTER", "Hours": 0}).execute()
            st.success("Customer Registered")

# --- TAB: JOB-WISE ACTIVITY PLAN ---
elif menu == "📅 Job-wise Activity Plan":
    st.header("📅 Job-wise Activity Plan & Lead Time Planning")
    if not df_jobs.empty:
        # Top Dropdowns
        col1, col2, col3, col4 = st.columns(4)
        sel_job = col1.selectbox("Select Job No", df_jobs['job_no'].unique())
        sel_cust = col2.selectbox("Customer Name", get_master("CUSTOMER_MASTER"))
        sel_eng = col3.selectbox("Engineer In-Charge", get_master("ENGINEER_MASTER"))
        sel_unit = col4.selectbox("Unit", ["Unit 1", "Unit 2", "Unit 3"])
        
        # 1. Critical Material Notification (Display & Entry)
        st.subheader("🛒 Critical Material Notification")
        with st.expander("📝 Add/Update Material Status & Purchase Notes"):
            with st.form("pur_form", clear_on_submit=True):
                m1, m2, m3 = st.columns(3)
                p_item = m1.text_input("Item Name")
                p_stat = m2.selectbox("Status", ["Shortage", "Ordered", "Received", "Delayed"])
                p_reply = m3.text_input("Purchase Reply (Expected Delivery)")
                p_notes = st.text_area("Internal Procurement Notes")
                if st.form_submit_button("Update Purchase Console"):
                    conn.table("purchase_orders").insert({
                        "job_no": str(sel_job), "item_name": p_item, "status": p_stat, 
                        "expected_delivery": p_reply, "notes": p_notes
                    }).execute()
                    st.success("Status Recorded")
                    st.rerun()

        # Show Purchase Status Table
        job_mat = df_purchase[df_purchase['job_no'] == str(sel_job)]
        if not job_mat.empty:
            st.table(job_mat[['item_name', 'status', 'expected_delivery', 'notes']])
        else:
            st.info("No material shortages reported for this job.")

        # 2. Lead Time Planning (Duration Input)
        st.subheader("📝 Lead Time Planning (Number of Days)")
        DEFAULT_RECIPE = [
            {"Activity": "1. Engineering", "Days": 7},
            {"Activity": "2. Marking/Cutting", "Days": 5},
            {"Activity": "3. Shell Fab", "Days": 15},
            {"Activity": "4. Drive Assembly", "Days": 12},
            {"Activity": "5. Main Assembly", "Days": 7}
        ]
        edited_days = st.data_editor(pd.DataFrame(DEFAULT_RECIPE), hide_index=True, key="day_editor")

        # 3. Actual vs Planned (Automatic Date Stacking)
        st.subheader("📊 Actual vs Planned")
        start_date = datetime.now().date()
        plan_rows = []
        current_cursor = start_date
        
        for i, row in edited_days.iterrows():
            end_dt = current_cursor + timedelta(days=row['Days'])
            act_hrs = df_logs[(df_logs['Job_Code'] == str(sel_job)) & (df_logs['Activity'] == row['Activity'])]['Hours'].sum() if not df_logs.empty else 0
            plan_rows.append({
                "Activity": row['Activity'],
                "Planned Window": f"{current_cursor.strftime('%d-%b')} to {end_dt.strftime('%d-%b')}",
                "Days": row['Days'],
                "Actual Hrs": act_hrs,
                "Status": "✅ Active" if act_hrs > 0 else "⏳ Waiting"
            })
            current_cursor = end_dt # Stack sequentially
        
        st.table(pd.DataFrame(plan_rows))

# --- TAB: DAILY LOGGING ---
elif menu == "👷 Daily Logging":
    st.header("👷 Shop Floor Productivity Log")
    with st.form("prod_log", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_job = c1.selectbox("Job No", df_jobs['job_no'].unique() if not df_jobs.empty else [])
        f_cust = c1.selectbox("Customer", get_master("CUSTOMER_MASTER"))
        f_eng = c2.selectbox("Engineer Logging", get_master("ENGINEER_MASTER"))
        f_mach = c2.selectbox("Machine/Station", get_master("MACHINE_MASTER"))
        f_wrk = c1.selectbox("Worker", get_master("WORKER_MASTER"))
        f_act = c2.text_input("Activity Name")
        f_hrs = c2.number_input("Hours Spent", min_value=0.0, step=0.5)
        
        if st.form_submit_button("💾 Save Entry", type="primary"):
            conn.table("production").insert({
                "Job_Code": str(f_job), "Worker": f_wrk, "Supervisor": f_eng, 
                "Notes": f_cust, "Activity": f_act, "Hours": f_hrs, "Machine": f_mach,
                "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
            }).execute()
            st.success("Entry Logged.")
            st.rerun()

# --- TAB: FOUNDER DASHBOARD ---
elif menu == "📊 Founder Dashboard":
    st.header("📊 Executive Analytics")
    if not df_logs.empty:
        main_df = df_logs[~df_logs['Notes'].str.contains('MASTER', na=False)].copy()
        main_df['Date'] = pd.to_datetime(main_df['created_at']).dt.date

        tab1, tab2, tab3, tab4 = st.tabs(["Worker/Job", "Customer/Day", "Machine Load", "Material Summary"])
        
        with tab1:
            st.subheader("Worker Efficiency")
            st.table(main_df.groupby('Worker')['Hours'].sum().reset_index())
            st.subheader("Job-wise Progress")
            st.table(main_df.groupby('Job_Code')['Hours'].sum().reset_index())
        with tab2:
            st.subheader("Customer-wise Allocation")
            st.table(main_df.groupby('Notes')['Hours'].sum().reset_index().rename(columns={'Notes':'Customer'}))
            st.subheader("Daily Shop Load")
            st.line_chart(main_df.groupby('Date')['Hours'].sum())
        with tab3:
            st.subheader("Machine Station Usage")
            st.table(main_df.groupby('Machine')['Hours'].sum().reset_index())
        with tab4:
            st.subheader("Global Shortage List")
            if not df_purchase.empty:
                st.dataframe(df_purchase[df_purchase['status'] == 'Shortage'], use_container_width=True)
