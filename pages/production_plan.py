import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
from supabase import create_client, Client
import plotly.express as px

# --- 1. SETTINGS & CONNECTION ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G ERP | Production Master", layout="wide", page_icon="🏗️")

try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(URL, KEY)
except Exception:
    st.error("❌ Database Connection Error. Check Streamlit Secrets.")
    st.stop()

# --- 2. DATABASE FUNCTIONS ---
def load_data():
    try:
        response = supabase.table("production").select("*").order("created_at", desc=True).execute()
        # Also fetch job details from your projects table to show client names
        jobs_res = supabase.table("anchor_projects").select("job_no, client_name, project_description").eq("status", "Won").execute()
        
        df_logs = pd.DataFrame(response.data) if response.data else pd.DataFrame()
        df_jobs = pd.DataFrame(jobs_res.data) if jobs_res.data else pd.DataFrame()
        return df_logs, df_jobs
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

df, df_active_jobs = load_data()

# --- 3. DYNAMIC DROPDOWN LOGIC ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
# Updated Activities based on your Zoho exports (Reactor & Tank)
default_activities = [
    "Drawing Preparation", "RM Procurement", "Shell Fabrication", 
    "Limpet/Jacket Fitting", "Nozzle Fit-up", "Welding", "Grinding", 
    "Hydro-test", "Painting", "Packing/Dispatch"
]

if not df.empty:
    all_supervisors = sorted(list(set(base_supervisors + [s for s in df["Supervisor"].dropna().unique().tolist() if s not in ["N/A", ""]])))
    all_workers = sorted([w for w in df["Worker"].dropna().unique().tolist() if w not in ["N/A", ""]])
    # Pull Job Codes from the Active Jobs table instead of logs for better control
    all_jobs = sorted(df_active_jobs["job_no"].unique().tolist()) if not df_active_jobs.empty else []
    all_activities = sorted(list(set(default_activities + [a for a in df["Activity"].dropna().unique().tolist() if a not in ["N/A", ""]])))
else:
    all_supervisors = sorted(base_supervisors)
    all_activities = sorted(default_activities)
    all_workers, all_jobs = [], []

# --- 4. NAVIGATION ---
st.sidebar.title("🛠️ B&G ERP Control")
menu = st.sidebar.radio("Go to:", ["🏗️ Daily Entry", "📊 Job Analytics", "🗂️ Manage Masters"])

# --- PAGE 1: PRODUCTION ENTRY ---
if menu == "🏗️ Daily Entry":
    st.title("Daily Production & Engineer Log")
    
    with st.form("entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            sup = st.selectbox("Supervisor", ["-- Select --"] + all_supervisors)
            wrk = st.selectbox("Person (Worker/Engineer)", ["-- Select --"] + all_workers)
            jb = st.selectbox("Job Code", ["-- Select --"] + all_jobs)
            act = st.selectbox("Activity (Zoho Task)", ["-- Select --"] + all_activities)
        with col2:
            unt = st.selectbox("Unit", ["Meters (Mts)", "Components (Nos)", "Joints/Points (Nos)", "Layouts (Nos)"])
            out = st.number_input("Output Value", min_value=0.0)
            hrs = st.number_input("Hours Spent", min_value=0.0, step=0.5)
            nts = st.text_area("Specific Remarks (e.g. Shell A-B Seam)")

        if st.form_submit_button("💾 Save to Cloud", type="primary"):
            if "-- Select --" in [sup, wrk, jb, act]:
                st.warning("⚠️ Please select all required fields.")
            else:
                payload = {
                    "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                    "Supervisor": sup, "Worker": wrk, "Job_Code": jb,
                    "Activity": act, "Unit": unt, "Output": float(out),
                    "Hours": float(hrs), "Notes": nts
                }
                supabase.table("production").insert(payload).execute()
                st.success(f"✅ Logged for {jb} successfully!")
                st.rerun()

    st.divider()
    st.subheader("📋 Recent Activity")
    if not df.empty:
        log_display = df[df['Notes'] != "SYSTEM_NEW_ITEM"].head(10)
        st.dataframe(log_display[['created_at', 'Worker', 'Job_Code', 'Activity', 'Hours']], use_container_width=True)

# --- PAGE 2: JOB ANALYTICS (The Zoho Replacement) ---
elif menu == "📊 Job Analytics":
    st.title("Project Costing & Man-Hour Analytics")
    
    if not df.empty:
        clean_df = df[df['Notes'] != "SYSTEM_NEW_ITEM"].copy()
        
        # Summary Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Man-Hours Logged", f"{clean_df['Hours'].sum():,.1f}")
        m2.metric("Active Projects", len(clean_df['Job_Code'].unique()))
        m3.metric("Avg Hours/Log", f"{(clean_df['Hours'].mean()):,.1f}")

        # Job Wise Breakdown
        st.subheader("⏱️ Hours Spent per Job (Costing)")
        job_hrs = clean_df.groupby('Job_Code')['Hours'].sum().reset_index()
        fig = px.bar(job_hrs, x='Job_Code', y='Hours', color='Hours', title="Cumulative Man-Hours")
        st.plotly_chart(fig, use_container_width=True)
        
        # Activity Breakdown
        st.subheader("🛠️ Stage-wise Distribution")
        act_hrs = clean_df.groupby('Activity')['Hours'].sum().reset_index()
        fig2 = px.pie(act_hrs, values='Hours', names='Activity', hole=0.4)
        st.plotly_chart(fig2, use_container_width=True)
        
        # Raw Data Download
        csv = clean_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Master CSV for Audit", data=csv, file_name="BG_ERP_Master_Logs.csv")
    else:
        st.info("No data available for analytics.")

# --- PAGE 3: MANAGE MASTERS ---
elif menu == "🗂️ Manage Masters":
    st.title("ERP Master Lists")
    st.info("Add new resources here to update the dropdowns.")
    
    def add_item(col, val):
        payload = {
            "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'), 
            "Supervisor": val if col == "Supervisor" else "N/A", 
            "Worker": val if col == "Worker" else "N/A", 
            "Job_Code": val if col == "Job_Code" else "N/A", 
            "Activity": val if col == "Activity" else "N/A", 
            "Unit": "N/A", "Output": 0, "Hours": 0, "Notes": "SYSTEM_NEW_ITEM"
        }
        supabase.table("production").insert(payload).execute()
        st.success(f"✅ Added {val} to Master.")
        st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        new_w = st.text_input("New Worker/Engineer Name")
        if st.button("Add Person") and new_w: add_item("Worker", new_w)
    with c2:
        new_act = st.text_input("New Activity/Task Name")
        if st.button("Add Activity") and new_act: add_item("Activity", new_act)
