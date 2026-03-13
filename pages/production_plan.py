import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP & CONNECTION ---
# Using your existing working connection logic
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master | B&G", layout="wide", page_icon="🏭")

# This is the connection method that works in your other consoles
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=5)
def get_master_data():
    # Fetch Won Jobs for Planning
    plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
    # Fetch Production Logs for Analytics & Productivity
    prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
    return pd.DataFrame(plan_res.data or []), pd.DataFrame(prod_res.data or [])

df_plan, df_logs = get_master_data()

# --- 3. DYNAMIC MAPPING (Zoho & Technical) ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
# Universal Gates for Planning
universal_stages = [
    "1. Engineering & MTC Verify", "2. Marking & Cutting", "3. Sub-Assembly & Machining",
    "4. Shell/Body Fabrication", "5. Main Assembly/Internals", "6. Nozzles & Accessories",
    "7. Inspection & NDT", "8. Hydro/Pressure Testing", "9. Insulation & Finishing",
    "10. Final Assembly & Dispatch"
]
# Days to finish for Target Dispatch logic
days_to_finish = {s: d for s, d in zip(universal_stages, [45, 40, 35, 30, 22, 15, 10, 7, 4, 1])}

# Pull Dynamic Lists for dropdowns
if not df_logs.empty:
    all_workers = sorted(list(set(df_logs["Worker"].dropna().unique().tolist())))
    all_activities = sorted(list(set(universal_stages + df_logs["Activity"].dropna().unique().tolist())))
else:
    all_workers, all_activities = [], universal_stages

# --- 4. NAVIGATION TABS ---
tab_plan, tab_entry, tab_analytics, tab_masters = st.tabs([
    "🏗️ Production Planning", "👷 Daily Work Entry", "📊 Costing & Analytics", "🛠️ Manage Masters"
])

# --- TAB 1: PRODUCTION PLANNING (Original Logic + Alerts) ---
with tab_plan:
    st.subheader("Live Shop Floor Gates")
    if not df_plan.empty:
        # Pre-calculate hours for Budget Alerts
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for index, row in df_plan.iterrows():
            job_id = str(row['job_no'])
            actual_hrs = hrs_sum.get(job_id, 0)
            budget = 200 if any(x in row['project_description'].upper() for x in ["REACTOR", "ANFD", "COLUMN"]) else 100
            
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c1.caption(f"🛠️ {row['project_description']}")
                
                # Efficiency Metric
                c2.metric("Man-Hours Used", f"{actual_hrs} Hrs", 
                          delta=f"{actual_hrs-budget} Over" if actual_hrs > budget else None, delta_color="inverse")
                
                # Target Dispatch Logic
                days_left = days_to_finish.get(row['drawing_status'], 45)
                proj_date = (datetime.now() + timedelta(days=days_left)).strftime('%d-%b')
                c3.metric("Target Dispatch", proj_date, f"{days_left} Days")

                st.progress((universal_stages.index(row['drawing_status']) + 1) / len(universal_stages) if row['drawing_status'] in universal_stages else 0.1)

                # Update Section
                col1, col2, col3 = st.columns(3)
                new_stage = col1.selectbox("Move to Gate", universal_stages, 
                                          index=universal_stages.index(row['drawing_status']) if row['drawing_status'] in universal_stages else 0,
                                          key=f"gate_{row['id']}")
                new_shortage = col2.toggle("Shortage Alert", value=row.get('material_shortage', False), key=f"sh_{row['id']}")
                new_note = col3.text_input("Floor Remarks", value=row.get('shortage_details', ""), key=f"nt_{row['id']}")

                if st.button("💾 Sync Progress", key=f"btn_{row['id']}", type="primary", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "drawing_status": new_stage,
                        "material_shortage": new_shortage,
                        "shortage_details": new_note
                    }).eq("id", row['id']).execute()
                    st.toast("Progress Updated!")
                    st.rerun()

# --- TAB 2: DAILY WORK ENTRY (Work Measurement) ---
with tab_entry:
    st.subheader("Worker & Engineer Output Entry")
    with st.form("productivity_form", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        job_list = df_plan['job_no'].unique().tolist() if not df_plan.empty else []
        
        f_sup = f1.selectbox("Supervisor", base_supervisors)
        f_wrk = f1.selectbox("Person", ["-- Select --"] + all_workers)
        f_job = f2.selectbox("Job Code", ["-- Select --"] + job_list)
        f_act = f2.selectbox("Activity", all_activities)
        
        # WORK MEASUREMENT
        f_unt = f3.selectbox("Unit", ["Meters (Mts)", "Joints (Nos)", "Components (Nos)", "Layouts (Nos)"])
        f_out = f3.number_input("Output Value", min_value=0.0)
        f_hrs = st.number_input("Total Hours Spent", min_value=0.0, step=0.5)
        f_nts = st.text_area("Specific Remarks (e.g. Dish-to-Shell Seam)")

        if st.form_submit_button("🚀 Submit Productivity Log", use_container_width=True):
            if "-- Select --" in [f_wrk, f_job]:
                st.warning("Please select Worker and Job Code.")
            else:
                conn.table("production").insert({
                    "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                    "Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job,
                    "Activity": f_act, "Unit": f_unt, "Output": f_out, "Hours": f_hrs, "Notes": f_nts
                }).execute()
                st.success("Log Saved!")
                st.rerun()

# --- TAB 3: ANALYTICS & COSTING ---
with tab_analytics:
    st.subheader("💰 Job-Wise Man-Hour Burn")
    if not df_logs.empty:
        clean_logs = df_logs[df_logs['Notes'] != "SYSTEM_NEW_ITEM"].copy()
        
        fig = px.bar(clean_logs.groupby('Job_Code')['Hours'].sum().reset_index(), 
                     x='Job_Code', y='Hours', color='Hours', title="Cumulative Hours per Equipment")
        st.plotly_chart(fig, use_container_width=True)
        
        act_fig = px.pie(clean_logs.groupby('Activity')['Hours'].sum().reset_index(), 
                         values='Hours', names='Activity', hole=0.4, title="Time Distribution by Stage")
        st.plotly_chart(act_fig, use_container_width=True)

# --- TAB 4: MANAGE MASTERS ---
with tab_masters:
    st.subheader("Manage Workers & Tasks")
    ma, mb = st.columns(2)
    new_w = ma.text_input("New Worker/Engineer Name")
    if ma.button("Register Person") and new_w:
        conn.table("production").insert({"Worker": new_w, "Notes": "SYSTEM_NEW_ITEM", "Hours": 0, "Activity": "N/A", "Job_Code": "N/A"}).execute()
        st.rerun()
    
    new_a = mb.text_input("New Technical Activity")
    if mb.button("Register Activity") and new_a:
        conn.table("production").insert({"Activity": new_a, "Notes": "SYSTEM_NEW_ITEM", "Hours": 0, "Worker": "N/A", "Job_Code": "N/A"}).execute()
        st.rerun()
