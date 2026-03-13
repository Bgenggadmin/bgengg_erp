import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz

# --- 1. SETTINGS & AUTH ---
st.set_page_config(page_title="B&G Production Control", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)
IST = pytz.timezone('Asia/Kolkata')

# Simple Password Protection
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🔒 B&G Production Gateway")
    pwd = st.text_input("Enter Access Code", type="password")
    if st.button("Unlock Systems"):
        if pwd == "0990":
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Invalid Code")
    st.stop()

# --- 2. DATA ENGINE ---
def get_data():
    # Projects: All won projects for selection
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    # Production Logs
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    # Purchase Status
    try:
        pur = conn.table("purchase_orders").select("*").execute()
        df_pur = pd.DataFrame(pur.data or [])
    except:
        df_pur = pd.DataFrame(columns=['job_no', 'item_name', 'status', 'purchase_reply', 'notes'])
    
    df_p = pd.DataFrame(p.data or [])
    df_l = pd.DataFrame(l.data or [])
    return df_p, df_l, df_pur

df_jobs, df_logs, df_purchase = get_data()

def get_master(m_type):
    if df_logs.empty: return []
    return sorted(df_logs[df_logs['Notes'] == m_type]['Worker'].unique().tolist())

# --- 3. SIDEBAR NAVIGATION ---
st.sidebar.title("B&G Navigation")
menu = st.sidebar.radio("Navigate", [
    "📊 Founder Dashboard", 
    "➕ New Job Entry",
    "📅 Job-wise Activity Plan", 
    "👷 Daily Logging", 
    "🛠️ Master Data"
])

# --- TAB: NEW JOB ENTRY (Requested) ---
if menu == "➕ New Job Entry":
    st.header("🚀 Register New Production Job")
    with st.form("new_job_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        j_no = c1.text_input("Job Number (e.g., BG-2024-001)")
        j_cust = c1.selectbox("Customer", get_master("CUSTOMER_MASTER"))
        j_val = c2.number_input("Project Budgeted Hours (Total)", min_value=0)
        j_desc = c2.text_area("Job Description / Equipment Type")
        
        if st.form_submit_button("Create Job Record"):
            # Note: This inserts into anchor_projects so it appears in selection
            conn.table("anchor_projects").insert({
                "job_no": j_no, "customer_name": j_cust, "status": "Won", "value": j_val
            }).execute()
            st.success(f"Job {j_no} created successfully!")
            st.rerun()

# --- TAB: MASTER DATA ---
elif menu == "🛠️ Master Data":
    st.header("🛠️ Resource & Entity Masters")
    c1, c2, c3 = st.columns(3)
    with c1:
        nw = st.text_input("New Worker Name")
        if st.button("Register Worker") and nw:
            conn.table("production").insert({"Worker": nw, "Notes": "WORKER_MASTER", "Hours": 0}).execute()
            st.success("Worker Registered")
    with c2:
        ne = st.text_input("New Engineer Name")
        if st.button("Register Engineer") and ne:
            conn.table("production").insert({"Worker": ne, "Notes": "ENGINEER_MASTER", "Hours": 0}).execute()
            st.success("Engineer Registered")
    with c3:
        nc = st.text_input("New Customer Name")
        if st.button("Register Customer") and nc:
            conn.table("production").insert({"Worker": nc, "Notes": "CUSTOMER_MASTER", "Hours": 0}).execute()
            st.success("Customer Registered")
        nm = st.text_input("New Machine/Station")
        if st.button("Register Machine") and nm:
            conn.table("production").insert({"Worker": nm, "Notes": "MACHINE_MASTER", "Hours": 0}).execute()
            st.success("Machine Registered")

# --- TAB: JOB-WISE ACTIVITY PLAN ---
elif menu == "📅 Job-wise Activity Plan":
    st.header("📅 Planning & Critical Materials")
    if not df_jobs.empty:
        col1, col2, col3 = st.columns(3)
        sel_job = col1.selectbox("Select Job No", df_jobs['job_no'].unique())
        sel_eng = col2.selectbox("Engineer In-Charge", get_master("ENGINEER_MASTER"))
        sel_unit = col3.selectbox("Unit", ["Unit 1", "Unit 2", "Unit 3"])

        # Material Section
        st.subheader("🛒 Critical Material Status")
        with st.expander("Update Purchase Status"):
            with st.form("pur_update"):
                p_item = st.text_input("Item Name")
                p_stat = st.selectbox("Status", ["Shortage", "Ordered", "Received"])
                p_reply = st.text_input("Purchase Reply / ETD")
                p_notes = st.text_area("Purchase Notes")
                if st.form_submit_button("Save Status"):
                    conn.table("purchase_orders").insert({
                        "job_no": str(sel_job), "item_name": p_item, "status": p_stat,
                        "purchase_reply": p_reply, "notes": p_notes
                    }).execute()
                    st.rerun()
        
        # Lead Time Days Input
        st.subheader("📝 Lead Time Planning (Days)")
        plan_data = pd.DataFrame([
            {"Activity": "1. Engineering", "Days": 7},
            {"Activity": "2. Marking/Cutting", "Days": 5},
            {"Activity": "3. Shell Fab", "Days": 15},
            {"Activity": "4. Assembly", "Days": 10}
        ])
        edited_plan = st.data_editor(plan_data, hide_index=True)

        # Timeline Display
        st.subheader("📊 Timeline & Productivity")
        start_date = datetime.now().date()
        plan_rows = []
        curr = start_date
        for i, row in edited_plan.iterrows():
            end = curr + timedelta(days=row['Days'])
            act_hrs = df_logs[(df_logs['Job_Code'] == str(sel_job)) & (df_logs['Activity'] == row['Activity'])]['Hours'].sum() if not df_logs.empty else 0
            plan_rows.append({
                "Activity": row['Activity'], "Schedule": f"{curr.strftime('%d-%b')} to {end.strftime('%d-%b')}",
                "Actual Hrs": act_hrs, "Status": "✅" if act_hrs > 0 else "⏳"
            })
            curr = end
        st.table(pd.DataFrame(plan_rows))

# --- TAB: DAILY LOGGING ---
elif menu == "👷 Daily Logging":
    st.header("👷 Daily Shop Floor Log")
    with st.form("log_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_job = c1.selectbox("Job No", df_jobs['job_no'].unique() if not df_jobs.empty else [])
        f_wrk = c1.selectbox("Worker", get_master("WORKER_MASTER"))
        f_mach = c2.selectbox("Machine/Station", get_master("MACHINE_MASTER"))
        f_act = c2.text_input("Activity (e.g., Welding)")
        f_hrs = c2.number_input("Hours", min_value=0.0, step=0.5)
        f_note = st.text_input("Customer Name / Remarks")
        if st.form_submit_button("💾 Save Log"):
            conn.table("production").insert({
                "Job_Code": str(f_job), "Worker": f_wrk, "Machine": f_mach,
                "Activity": f_act, "Hours": f_hrs, "Notes": f_note,
                "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
            }).execute()
            st.success("Logged successfully.")

# --- TAB: FOUNDER DASHBOARD (Enhanced with Downloads) ---
elif menu == "📊 Founder Dashboard":
    st.header("📊 Production Analytics & Productivity")
    if not df_logs.empty:
        # Data Preparation
        main_df = df_logs[~df_logs['Notes'].str.contains('MASTER', na=False)].copy()
        
        # DOWNLOAD SECTION
        st.sidebar.subheader("📥 Export Data")
        csv = main_df.to_csv(index=False).encode('utf-8')
        st.sidebar.download_button("Download Raw Logs CSV", data=csv, file_name="production_logs.csv", mime='text/csv')

        t1, t2, t3, t4 = st.tabs(["👷 Worker Analysis", "📂 Job Analysis", "🏢 Customer View", "🛠️ Machine Load"])
        
        with t1:
            st.subheader("Worker-wise Productivity")
            w_df = main_df.groupby('Worker')['Hours'].sum().reset_index()
            st.table(w_df)
            st.download_button("Download Worker CSV", w_df.to_csv(index=False), "worker_data.csv")

        with t2:
            st.subheader("Job-wise Man-Hours")
            j_df = main_df.groupby('Job_Code')['Hours'].sum().reset_index()
            st.table(j_df)
            st.download_button("Download Job CSV", j_df.to_csv(index=False), "job_data.csv")

        with t3:
            st.subheader("Customer-wise Allocation")
            c_df = main_df.groupby('Notes')['Hours'].sum().reset_index().rename(columns={'Notes':'Customer'})
            st.table(c_df)
            st.download_button("Download Customer CSV", c_df.to_csv(index=False), "customer_data.csv")

        with t4:
            st.subheader("Machine Station Loading")
            m_df = main_df.groupby('Machine')['Hours'].sum().reset_index()
            st.table(m_df)
