import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
from supabase import create_client, Client
import plotly.express as px

# --- 1. CONFIGURATION & DATABASE ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G ERP | Project Master", layout="wide", page_icon="🏗️")

# Initialize Supabase using Secrets (Ensures gateway connectivity)
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(URL, KEY)
except Exception as e:
    st.error(f"❌ Connection Error: Check Streamlit Secrets. {e}")
    st.stop()

# --- 2. DATA LOADING ---
@st.cache_data(ttl=2)
def load_erp_data():
    try:
        # Get active jobs (Won Projects)
        jobs_res = supabase.table("anchor_projects").select("*").eq("status", "Won").execute()
        # Get production logs (Productivity)
        logs_res = supabase.table("production").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(jobs_res.data or []), pd.DataFrame(logs_res.data or [])
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

df_jobs, df_logs = load_erp_data()

# --- 3. DYNAMIC MASTER LOGIC ---
base_sups = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
# Zoho-derived Technical Activities
default_acts = [
    "Drawing Preparation", "RM Procurement", "Shell Fabrication", "Dished End Prep",
    "Limpet/Jacket Fitting", "Internal Coil Work", "Nozzle Fit-up", "Welding", 
    "Grinding/Buffing", "Hydro-test", "Insulation", "Dispatch"
]

if not df_logs.empty:
    all_workers = sorted(list(set(df_logs["Worker"].dropna().unique().tolist())))
    all_acts = sorted(list(set(default_acts + df_logs["Activity"].dropna().unique().tolist())))
    all_job_codes = sorted(df_jobs["job_no"].unique().tolist()) if not df_jobs.empty else []
else:
    all_workers, all_acts, all_job_codes = [], default_acts, []

# --- 4. NAVIGATION TABS ---
tab_plan, tab_entry, tab_costing, tab_masters = st.tabs([
    "🏗️ Project Planning", "👷 Daily Work Entry", "📊 Costing Analytics", "🛠️ Manage Masters"
])

# --- TAB 1: PROJECT PLANNING (The Zoho Replacement & Alerts) ---
with tab_plan:
    st.subheader("Live Project Status & Budget Alerts")
    if not df_jobs.empty:
        # Pre-calculate hours for Budget Alerts
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for _, job in df_jobs.iterrows():
            jid = str(job['job_no'])
            used_hrs = hrs_sum.get(jid, 0)
            # Logic: Budget 200hrs for Reactors/ANFD, 100hrs for Tanks
            budget = 200 if any(x in job['project_description'].upper() for x in ["REACTOR", "ANFD", "COLUMN"]) else 100
            is_over = used_hrs > budget

            with st.container(border=True):
                # Alert Banner
                if is_over:
                    st.error(f"⚠️ BUDGET ALERT: {jid} has exceeded {budget} estimated hours!")
                
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.markdown(f"### {jid} | {job['client_name']}")
                c1.caption(f"Equipment: {job['project_description']}")
                
                c2.metric("Total Used", f"{used_hrs} Hrs", 
                          delta=f"{used_hrs - budget} Over" if is_over else None, delta_color="inverse")
                
                # Update Zoho-style Status
                curr_status = job.get('drawing_status', 'Drawing Preparation')
                new_status = c3.selectbox("Current Activity", all_acts, 
                                          index=all_acts.index(curr_status) if curr_status in all_acts else 0,
                                          key=f"status_{job['id']}")
                
                if c3.button("Update Stage", key=f"upd_{job['id']}"):
                    supabase.table("anchor_projects").update({"drawing_status": new_status}).eq("id", job['id']).execute()
                    st.toast("Project Stage Updated")
                    st.rerun()

# --- TAB 2: DAILY WORK ENTRY (Work Measurement) ---
with tab_entry:
    st.subheader("Shop-Floor Work Measurement")
    with st.form("entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            f_sup = st.selectbox("Supervisor", base_sups)
            f_wrk = st.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
            f_job = st.selectbox("Job Code", ["-- Select --"] + all_job_codes)
        with col2:
            f_act = st.selectbox("Task/Activity", ["-- Select --"] + all_acts)
            f_unt = st.selectbox("Unit", ["Meters (Mts)", "Joints (Nos)", "Components (Nos)", "Layouts (Nos)"])
            f_out = f_hrs = st.number_input("Output Value", min_value=0.0)
        
        f_hrs = st.number_input("Time Spent (Hours)", min_value=0.0, step=0.5)
        f_nts = st.text_area("Work Remarks (e.g. Welding of Dish to Shell)")

        if st.form_submit_button("💾 Save Productivity Log", type="primary"):
            if "-- Select --" in [f_wrk, f_job, f_act]:
                st.warning("Please fill all dropdowns.")
            else:
                payload = {
                    "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                    "Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job,
                    "Activity": f_act, "Unit": f_unt, "Output": f_out, "Hours": f_hrs, "Notes": f_nts
                }
                supabase.table("production").insert(payload).execute()
                st.success(f"Work logged for {f_job}")
                st.rerun()

# --- TAB 3: COSTING ANALYTICS ---
with tab_costing:
    st.subheader("💰 Internal Burn & Efficiency")
    if not df_logs.empty:
        clean_logs = df_logs[df_logs['Notes'] != "SYSTEM_NEW_ITEM"].copy()
        
        # 1. Job vs Hours Bar Chart
        cost_df = clean_logs.groupby('Job_Code')['Hours'].sum().reset_index()
        st.plotly_chart(px.bar(cost_df, x='Job_Code', y='Hours', color='Hours', title="Total Hours by Equipment"), use_container_width=True)
        
        # 2. Activity Breakdown Pie Chart
        act_df = clean_logs.groupby('Activity')['Hours'].sum().reset_index()
        st.plotly_chart(px.pie(act_df, values='Hours', names='Activity', hole=0.4, title="Time Distribution per Process"), use_container_width=True)
        
        # CSV Export for final record keeping
        st.download_button("📥 Download Master Costing CSV", clean_logs.to_csv(index=False).encode('utf-8'), "BG_ERP_Logs.csv")

# --- TAB 4: MANAGE MASTERS (The "Flexibility" Feature) ---
with tab_masters:
    st.subheader("ERP Master Data Configuration")
    st.info("Add new resources here to instantly update dropdowns for customized jobs.")
    
    def add_master(field, value):
        payload = {
            "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
            "Supervisor": "N/A", "Worker": value if field=="Worker" else "N/A",
            "Job_Code": "N/A", "Activity": value if field=="Activity" else "N/A",
            "Unit": "N/A", "Output": 0, "Hours": 0, "Notes": "SYSTEM_NEW_ITEM"
        }
        supabase.table("production").insert(payload).execute()
        st.success(f"Registered {value}")
        st.rerun()

    ma, mb = st.columns(2)
    new_worker = ma.text_input("New Worker/Engineer Name")
    if ma.button("Add to Team") and new_worker: add_master("Worker", new_worker)
    
    new_activity = mb.text_input("New Technical Task/Activity")
    if mb.button("Add to Process List") and new_activity: add_master("Activity", new_activity)
