import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Sandbox | B&G", layout="wide", page_icon="🧪")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_master_data():
    try:
        plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        pur_res = conn.table("purchase_orders").select("*").execute()
        gate_res = conn.table("production_gates").select("*").order("step_order").execute()
        
        return (pd.DataFrame(plan_res.data or []), 
                pd.DataFrame(prod_res.data or []), 
                pd.DataFrame(pur_res.data or []),
                pd.DataFrame(gate_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_plan, df_logs, df_pur, df_gates = get_master_data()

# --- 3. DYNAMIC MAPPING ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
all_activities = ["Cutting", "Fitting", "Welding", "Grinding", "Painting", "Assembly", "Buffing", "Others"]

if not df_gates.empty:
    universal_stages = df_gates['gate_name'].tolist()
else:
    universal_stages = all_activities

all_jobs = sorted(df_plan['job_no'].astype(str).unique().tolist()) if not df_plan.empty else []
all_workers = sorted(df_logs['Worker'].unique().tolist()) if not df_logs.empty else []

# --- 4. NAVIGATION ---
tab_plan, tab_entry, tab_analytics = st.tabs(["🏗️ Planning", "👷 Daily Entry", "📊 Analytics"])

with tab_plan:
    st.subheader("📋 Job-Specific Blueprint & Planning")
    
    # Selection for Pre-Planning
    target_job = st.selectbox("Select Job to Plan/View", all_jobs)
    
    # 1. FETCH SPECIFIC GATES FOR THIS JOB
    job_steps = conn.table("job_planning").select("*").eq("job_no", target_job).order("step_order").execute()
    steps_df = pd.DataFrame(job_steps.data or [])

    # 2. PRE-PLANNING UI (If no gates exist yet)
    with st.expander("🛠️ Define/Edit Job Gates"):
        new_g_name = st.selectbox("Add Gate", all_activities)
        new_g_days = st.number_input("Planned Days for this Gate", min_value=1, value=3)
        if st.button("➕ Add Gate to Job"):
            next_order = len(steps_df) + 1
            conn.table("job_planning").insert({
                "job_no": target_job, "gate_name": new_g_name, 
                "step_order": next_order, "planned_days": new_g_days
            }).execute()
            st.rerun()

    # 3. PLANNED VS ACTUAL VISUALIZER
    if not steps_df.empty:
        st.write(f"### Progress for Job: {target_job}")
        for _, step in steps_df.iterrows():
            # Logic: Check if work logs exist for THIS job AND THIS activity
            actual_work = df_logs[(df_logs['Job_Code'] == target_job) & 
                                  (df_logs['Activity'] == step['gate_name'])]
            total_hrs = actual_work['Hours'].sum()
            
            col_a, col_b = st.columns([3, 1])
            with col_a:
                # Progress Bar based on time vs planned days
                planned_hrs = step['planned_days'] * 8
                progress = min(total_hrs / planned_hrs, 1.0) if planned_hrs > 0 else 0
                st.write(f"**{step['step_order']}. {step['gate_name']}** ({total_hrs} / {planned_hrs} Hrs)")
                st.progress(progress)
            with col_b:
                if total_hrs > planned_hrs:
                    st.error(f"⚠️ Overdue by {total_hrs - planned_hrs} Hrs")
                else:
                    st.success("On Track")

# --- TAB 3: ANALYTICS (Charts Added) ---
with tab_analytics:
    if not df_logs.empty:
        st.subheader("📊 Man-Hour Distribution")
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce')
        fig = px.pie(df_logs, values='Hours', names='Activity', hole=0.4, 
                     title="Total Work Hours by Activity Type")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No logs available for charts yet.")
