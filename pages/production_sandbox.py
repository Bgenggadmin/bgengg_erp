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

# --- TAB 1: PRODUCTION CONTROL (EXECUTION) ---
with tab_plan:
    target_job = st.selectbox("Select Job to Manage", all_jobs)
    
    # Fetch the Blueprint
    job_steps = conn.table("job_planning").select("*").eq("job_no", target_job).order("step_order").execute()
    steps_df = pd.DataFrame(job_steps.data or [])

    if not steps_df.empty:
        st.subheader(f"🏁 Execution Track: {target_job}")
        
        for index, row in steps_df.iterrows():
            status = row['current_status']
            bg_color = "#f0f2f6" if status == "Pending" else "#d4edda" if status == "Completed" else "#fff3cd"
            
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                
                # Column 1: Gate Info
                col1.markdown(f"**{row['step_order']}. {row['gate_name']}**")
                col1.caption(f"Target: {row['planned_days']} Days")
                
                # Column 2: Status Tag
                if status == "Pending":
                    col2.warning("⏳ Pending")
                    if col4.button("▶️ Start Gate", key=f"start_{row['id']}"):
                        conn.table("job_planning").update({
                            "current_status": "Active",
                            "actual_start_date": datetime.now(IST).isoformat()
                        }).eq("id", row['id']).execute()
                        st.rerun()
                        
                elif status == "Active":
                    col2.info("🚀 In-Progress")
                    # Calculate Live Aging
                    start_dt = pd.to_datetime(row['actual_start_date'])
                    days_spent = (datetime.now(IST).date() - start_dt.date()).days
                    col3.metric("Days Spent", f"{days_spent}d", delta=f"Vs {row['planned_days']}d")
                    
                    if col4.button("✅ Close Gate", key=f"end_{row['id']}"):
                        conn.table("job_planning").update({
                            "current_status": "Completed",
                            "actual_end_date": datetime.now(IST).isoformat()
                        }).eq("id", row['id']).execute()
                        st.rerun()
                        
                elif status == "Completed":
                    col2.success("🏁 Done")
                    start_dt = pd.to_datetime(row['actual_start_date'])
                    end_dt = pd.to_datetime(row['actual_end_date'])
                    total_taken = (end_dt.date() - start_dt.date()).days
                    col3.write(f"Took: **{total_taken} Days**")
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
