import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
from supabase import create_client, Client
import plotly.express as px

# --- 1. CONFIGURATION & SECRETS VALIDATION ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G ERP | Project Master", layout="wide", page_icon="🏗️")

# Check for secrets before initializing
if "SUPABASE_URL" not in st.secrets or "SUPABASE_KEY" not in st.secrets:
    st.error("🛑 **Missing Configuration Keys!**")
    st.info("""
    Please add the following to your Streamlit Cloud Secrets:
    1. Go to App Settings > Secrets
    2. Paste exactly:
    ```toml
    SUPABASE_URL = "your_url_here"
    SUPABASE_KEY = "your_key_here"
    ```
    """)
    st.stop()

# Initialize Supabase
try:
    supabase: Client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
except Exception as e:
    st.error(f"❌ Supabase Connection Failed: {e}")
    st.stop()

# --- 2. DATA LOADING ---
@st.cache_data(ttl=2)
def load_erp_data():
    try:
        jobs_res = supabase.table("anchor_projects").select("*").eq("status", "Won").execute()
        logs_res = supabase.table("production").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(jobs_res.data or []), pd.DataFrame(logs_res.data or [])
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

df_jobs, df_logs = load_erp_data()

# --- 3. DYNAMIC MASTER LOGIC (ZOHO MAPPING) ---
base_sups = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
# Activities mapped directly from your 8KL Reactor & 30KL Tank exports
zoho_tasks = [
    "Drawing Preparation", "RM Procurement", "Shell Fabrication", "Dished End Prep",
    "Limpet/Jacket Fitting", "Internal Coil Work", "Nozzle Fit-up", "Welding", 
    "Grinding/Polishing", "Hydro-test", "Insulation", "Dispatch"
]

if not df_logs.empty:
    all_workers = sorted(list(set(df_logs["Worker"].dropna().unique().tolist())))
    all_acts = sorted(list(set(zoho_tasks + df_logs["Activity"].dropna().unique().tolist())))
    all_job_codes = sorted(df_jobs["job_no"].unique().tolist()) if not df_jobs.empty else []
else:
    all_workers, all_acts, all_job_codes = [], zoho_tasks, []

# --- 4. NAVIGATION TABS ---
tab_plan, tab_entry, tab_costing, tab_masters = st.tabs([
    "🏗️ Project Planning", "👷 Daily Work Entry", "📊 Costing Analytics", "🛠️ Manage Masters"
])

# --- TAB 1: PROJECT PLANNING (The Zoho Replacement) ---
with tab_plan:
    st.subheader("Active Job Status & Budget Efficiency")
    if not df_jobs.empty:
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for _, job in df_jobs.iterrows():
            jid = str(job['job_no'])
            used_hrs = hrs_sum.get(jid, 0)
            # Budget Alert: 200hrs for heavy vessels, 100hrs for others
            budget = 200 if any(x in job['project_description'].upper() for x in ["REACTOR", "ANFD", "COLUMN"]) else 100
            
            with st.container(border=True):
                if used_hrs > budget:
                    st.error(f"⚠️ BUDGET ALERT: {jid} has used {used_hrs} / {budget} Hrs")
                
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.markdown(f"### {jid} | {job['client_name']}")
                c1.caption(f"Project: {job['project_description']}")
                
                c2.metric("Used Hours", f"{used_hrs} Hrs", 
                          delta=f"{used_hrs - budget} Excess" if used_hrs > budget else None, delta_color="inverse")
                
                curr_st = job.get('drawing_status', 'Drawing Preparation')
                new_st = c3.selectbox("Current Milestone", all_acts, index=all_acts.index(curr_st) if curr_st in all_acts else 0, key=f"s_{job['id']}")
                
                if c3.button("Save Milestone", key=f"b_{job['id']}"):
                    supabase.table("anchor_projects").update({"drawing_status": new_st}).eq("id", job['id']).execute()
                    st.rerun()

# --- TAB 2: DAILY WORK ENTRY (Work Measurement) ---
with tab_entry:
    st.subheader("Shop-Floor Productivity Log")
    with st.form("entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            f_sup = st.selectbox("Supervisor", base_sups)
            f_wrk = st.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
            f_job = st.selectbox("Job Code", ["-- Select --"] + all_job_codes)
        with col2:
            f_act = st.selectbox("Task Name", ["-- Select --"] + all_acts)
            # WORK MEASUREMENT Logic
            f_unt = st.selectbox("Unit", ["Meters (Mts)", "Joints (Nos)", "Components (Nos)", "Layouts (Nos)"])
            f_out = st.number_input("Output Value", min_value=0.0)
        
        f_hrs = st.number_input("Hours Spent", min_value=0.0, step=0.5)
        f_nts = st.text_area("Work Remarks / Serial Numbers")

        if st.form_submit_button("💾 Save Productivity Log", type="primary"):
            if "-- Select --" in [f_wrk, f_job, f_act]:
                st.warning("⚠️ All fields are mandatory.")
            else:
                payload = {
                    "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                    "Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job,
                    "Activity": f_act, "Unit": f_unt, "Output": f_out, "Hours": f_hrs, "Notes": f_nts
                }
                supabase.table("production").insert(payload).execute()
                st.success("Log Saved!")
                st.rerun()

# --- TAB 3: COSTING ANALYTICS ---
with tab_costing:
    st.subheader("💰 Internal Cost & Project Analytics")
    if not df_logs.empty:
        clean_logs = df_logs[df_logs['Notes'] != "SYSTEM_NEW_ITEM"].copy()
        st.plotly_chart(px.bar(clean_logs.groupby('Job_Code')['Hours'].sum().reset_index(), x='Job_Code', y='Hours', color='Hours', title="Hours per Project"), use_container_width=True)
        st.plotly_chart(px.pie(clean_logs.groupby('Activity')['Hours'].sum().reset_index(), values='Hours', names='Activity', hole=0.4, title="Time per Process"), use_container_width=True)
        st.download_button("📥 Export Audit Report (CSV)", clean_logs.to_csv(index=False).encode('utf-8'), "B&G_Analytics.csv")

# --- TAB 4: MANAGE MASTERS ---
with tab_masters:
    st.subheader("ERP Dynamic Configuration")
    def add_master(field, value):
        supabase.table("production").insert({
            "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
            "Supervisor": "N/A", "Worker": value if field=="Worker" else "N/A",
            "Job_Code": "N/A", "Activity": value if field=="Activity" else "N/A",
            "Unit": "N/A", "Output": 0, "Hours": 0, "Notes": "SYSTEM_NEW_ITEM"
        }).execute()
        st.success(f"Registered {value}")
        st.rerun()

    ma, mb = st.columns(2)
    new_w = ma.text_input("Register New Person")
    if ma.button("Add Worker/Engineer") and new_w: add_master("Worker", new_w)
    new_a = mb.text_input("Create New Task Type")
    if mb.button("Add Activity") and new_a: add_master("Activity", new_a)
