import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px
import plotly.figure_factory as ff

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master | B&G", layout="wide", page_icon="🧪")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_master_data():
    try:
        plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        pur_res = conn.table("purchase_orders").select("*").execute()
        gate_res = conn.table("production_gates").select("*").order("step_order").execute()
        # Fetch Job Planning for Gantt and logic
        job_plan_res = conn.table("job_planning").select("*").order("step_order").execute()
        
        return (pd.DataFrame(plan_res.data or []), 
                pd.DataFrame(prod_res.data or []), 
                pd.DataFrame(pur_res.data or []),
                pd.DataFrame(gate_res.data or []),
                pd.DataFrame(job_plan_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_plan, df_logs, df_pur, df_gates, df_job_plans = get_master_data()

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
tab_plan, tab_entry, tab_analytics = st.tabs(["🏗️ Planning & Execution", "👷 Daily Entry", "📊 Analytics & Gantt"])

# --- TAB 1: PRODUCTION CONTROL (PLANNING & EXECUTION) ---
with tab_plan:
    st.subheader("📋 Job Blueprint & Execution")
    target_job = st.selectbox("Select Job to Manage", all_jobs)
    
    # Filter plans for this specific job
    current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()

    # SECTION A: GATE ENTRY LOGIC (Blueprint Designer)
    with st.expander("🛠️ Step 1: Design Job Blueprint (Pre-Planning)", expanded=False):
        st.info("Add gates in sequence. This defines the 'Planned' timeline.")
        
        if not current_job_steps.empty:
            st.dataframe(current_job_steps[['step_order', 'gate_name', 'planned_days', 'current_status']], 
                         hide_index=True, use_container_width=True)
        
        with st.form("add_gate_form"):
            c1, c2, c3 = st.columns([2,1,1])
            g_name = c1.selectbox("Select Activity", all_activities)
            g_days = c2.number_input("Planned Days", min_value=1, value=3)
            g_order = c3.number_input("Step Order", min_value=1, value=len(current_job_steps)+1)
            
            if st.form_submit_button("➕ Add Gate to Job"):
                conn.table("job_planning").insert({
                    "job_no": target_job, "gate_name": g_name,
                    "planned_days": g_days, "step_order": g_order,
                    "current_status": "Pending"
                }).execute()
                st.cache_data.clear()
                st.rerun()

    st.divider()

    # SECTION B: EXECUTION LOGIC (Moving the Job)
    if not current_job_steps.empty:
        st.subheader(f"🏁 Step 2: Live Execution Track")
        
        for index, row in current_job_steps.sort_values('step_order').iterrows():
            status = row['current_status']
            
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                col1.markdown(f"**{row['step_order']}. {row['gate_name']}**")
                col1.caption(f"Target: {row['planned_days']} Days")
                
                if status == "Pending":
                    col2.warning("⏳ Pending")
                    if col4.button("▶️ Start Gate", key=f"start_{row['id']}"):
                        conn.table("job_planning").update({
                            "current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()
                        }).eq("id", row['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
                        
                elif status == "Active":
                    col2.info("🚀 In-Progress")
                    start_dt = pd.to_datetime(row['actual_start_date']).tz_convert(IST)
                    days_spent = (datetime.now(IST).date() - start_dt.date()).days
                    col3.metric("Days Spent", f"{days_spent}d", delta=f"Vs {row['planned_days']}d", delta_color="inverse" if days_spent > row['planned_days'] else "normal")
                    
                    if col4.button("✅ Close Gate", key=f"end_{row['id']}"):
                        conn.table("job_planning").update({
                            "current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()
                        }).eq("id", row['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
                        
                elif status == "Completed":
                    col2.success("🏁 Done")
                    start_dt = pd.to_datetime(row['actual_start_date']).tz_convert(IST)
                    end_dt = pd.to_datetime(row['actual_end_date']).tz_convert(IST)
                    total_taken = (end_dt.date() - start_dt.date()).days
                    col3.write(f"Took: **{total_taken} Days**")
    else:
        st.info("No gates planned for this job yet.")

# --- TAB 2: DAILY WORK ENTRY (DYNAMIC) ---
with tab_entry:
    st.subheader("👷 Labor Output Entry")
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs)
    
    if f_job != "-- Select --":
        # Only show the gate that is currently 'Active'
        active_gate_query = conn.table("job_planning").select("gate_name").eq("job_no", f_job).eq("current_status", "Active").execute()
        active_options = [g['gate_name'] for g in active_gate_query.data]
        
        if active_options:
            f_act = st.selectbox("🎯 Current Active Gate", active_options)
            with st.form("prod_form", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                f_sup = f1.selectbox("Supervisor", base_supervisors)
                f_wrk = f1.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
                f_hrs = f2.number_input("Hours Spent", min_value=0.0, step=0.5)
                f_out = f3.number_input("Output Quantity", min_value=0.0)
                f_nts = st.text_area("Remarks")

                if st.form_submit_button("🚀 Log Productivity"):
                    if "-- Select --" not in [f_wrk]:
                        conn.table("production").insert({
                            "Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job,
                            "Activity": f_act, "Hours": f_hrs, "Output": f_out,
                            "Notes": f_nts, "created_at": datetime.now(IST).isoformat()
                        }).execute()
                        st.cache_data.clear()
                        st.success("Entry Logged!")
                        st.rerun()
        else:
            st.error("⚠️ No gate is currently 'Active' for this job. Start a gate in the Planning tab.")

# --- TAB 3: ANALYTICS & GANTT ---
with tab_analytics:
    st.subheader("📊 Production Insights")
    
    # 1. GANTT CHART LOGIC
    if not df_job_plans.empty:
        st.markdown("### 📅 Project Timeline (Gantt)")
        gantt_data = []
        for _, row in df_job_plans.iterrows():
            if row['actual_start_date']:
                start = pd.to_datetime(row['actual_start_date'])
                # If finished, use actual end. If active, use today.
                finish = pd.to_datetime(row['actual_end_date']) if row['actual_end_date'] else datetime.now(IST)
                
                gantt_data.append(dict(
                    Task=f"Job: {row['job_no']}",
                    Start=start,
                    Finish=finish,
                    Resource=row['gate_name'],
                    Status=row['current_status']
                ))
        
        if gantt_data:
            df_gantt = pd.DataFrame(gantt_data)
            fig_gantt = px.timeline(df_gantt, x_start="Start", x_end="Finish", y="Task", color="Resource", 
                                    hover_data=["Status"], title="Live Shop Floor Timeline")
            fig_gantt.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_gantt, use_container_width=True)
            
        else:
            st.info("No active or completed gates to display on Gantt chart.")

    st.divider()

    # 2. MAN-HOUR PIE CHART
    if not df_logs.empty:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 🥧 Hour Distribution")
            df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce')
            fig_pie = px.pie(df_logs, values='Hours', names='Activity', hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            st.markdown("### 📈 Recent Activity")
            st.dataframe(df_logs[['Worker', 'Job_Code', 'Activity', 'Hours']].head(10), hide_index=True)
