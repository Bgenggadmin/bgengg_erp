import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master | B&G", layout="wide", page_icon="🏭")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=5)
def get_master_data():
    # Only fetch jobs won by Anchors
    plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
    prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
    return pd.DataFrame(plan_res.data or []), pd.DataFrame(prod_res.data or [])

df_plan, df_logs = get_master_data()

# --- 3. DYNAMIC MAPPING ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
universal_stages = [
    "1. Engineering & MTC Verify", "2. Marking & Cutting", "3. Sub-Assembly & Machining",
    "4. Shell/Body Fabrication", "5. Main Assembly/Internals", "6. Nozzles & Accessories",
    "7. Inspection & NDT", "8. Hydro/Pressure Testing", "9. Insulation & Finishing",
    "10. Final Assembly & Dispatch"
]

# Pull Lists for dropdowns
if not df_logs.empty:
    all_workers = sorted(list(set(df_logs["Worker"].dropna().unique().tolist())))
    all_activities = sorted(list(set(universal_stages + df_logs["Activity"].dropna().unique().tolist())))
else:
    all_workers, all_activities = [], universal_stages

# --- 4. NAVIGATION TABS ---
tab_plan, tab_entry, tab_analytics, tab_masters = st.tabs([
    "🏗️ Production Planning", "👷 Daily Work Entry", "📊 Analytics & Shift Report", "🛠️ Manage Masters"
])

# --- TAB 1: PRODUCTION PLANNING ---
with tab_plan:
    st.subheader("🚀 Shop Floor Gate Control")
    if not df_plan.empty:
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for index, row in df_plan.iterrows():
            job_id = str(row['job_no'])
            actual_hrs = hrs_sum.get(job_id, 0)
            budget = 200 if any(x in str(row['project_description']).upper() for x in ["REACTOR", "ANFD", "COLUMN"]) else 100
            
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c1.caption(f"🛠️ {row['project_description']}")
                
                c2.metric("Total Man-Hours", f"{actual_hrs} Hrs", 
                          delta=f"{actual_hrs-budget} Over" if actual_hrs > budget else None, delta_color="inverse")
                
                # Progress Bar
                current_stage = row['drawing_status']
                prog_idx = universal_stages.index(current_stage) if current_stage in universal_stages else 0
                st.progress((prog_idx + 1) / len(universal_stages))

                col1, col2, col3 = st.columns(3)
                new_gate = col1.selectbox("Current Gate", universal_stages, index=prog_idx, key=f"gt_{row['id']}")
                new_short = col2.toggle("Material Shortage", value=row.get('material_shortage', False), key=f"sh_{row['id']}")
                new_rem = col3.text_input("Floor Remarks", value=row.get('shortage_details', ""), key=f"rm_{row['id']}")

                if st.button("Update Gate Status", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate,
                        "material_shortage": new_short,
                        "shortage_details": new_rem
                    }).eq("id", row['id']).execute()
                    st.toast("Status Synced to Anchor Portal!")
                    st.rerun()

# --- TAB 2: DAILY WORK ENTRY ---
with tab_entry:
    st.subheader("👷 Labor Output Entry")
    with st.form("prod_form", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        job_list = df_plan['job_no'].unique().tolist() if not df_plan.empty else []
        
        f_sup = f1.selectbox("Supervisor", base_supervisors)
        f_wrk = f1.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
        f_job = f2.selectbox("Job Code", ["-- Select --"] + job_list)
        f_act = f2.selectbox("Activity", all_activities)
        f_hrs = f3.number_input("Hours Spent", min_value=0.0, step=0.5)
        f_out = f3.number_input("Output (Qty)", min_value=0.0)
        f_nts = st.text_area("Task Details")

        if st.form_submit_button("🚀 Log Productivity", use_container_width=True):
            if "-- Select --" not in [f_wrk, f_job]:
                conn.table("production").insert({
                    "Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job,
                    "Activity": f_act, "Hours": f_hrs, "Output": f_out, "Notes": f_nts
                }).execute()
                st.success("Work Logged!")
                st.rerun()

# --- TAB 3: ANALYTICS & SHIFT REPORT ---
with tab_analytics:
    if not df_logs.empty:
        # Today's Shift Report
        st.subheader("📅 Today's Shift Report")
        df_logs['created_at'] = pd.to_datetime(df_logs['created_at']).dt.tz_convert(IST)
        today_logs = df_logs[df_logs['created_at'].dt.date == datetime.now(IST).date()]
        
        if not today_logs.empty:
            st.dataframe(today_logs[['created_at', 'Worker', 'Job_Code', 'Activity', 'Hours', 'Notes']], hide_index=True, use_container_width=True)
            st.metric("Total Man-Power Utilized Today", f"{today_logs['Hours'].sum()} Hrs")
        else:
            st.info("No logs entered for today yet.")
        
        st.divider()
        st.subheader("📊 Cumulative Job Analytics")
        clean_logs = df_logs[df_logs['Notes'] != "SYSTEM_NEW_ITEM"]
        fig = px.bar(clean_logs.groupby('Job_Code')['Hours'].sum().reset_index(), x='Job_Code', y='Hours', title="Hours Spent per Job")
        st.plotly_chart(fig, use_container_width=True)

# --- TAB 4: MASTERS ---
with tab_masters:
    st.subheader("🛠️ Master Registration")
    m1, m2 = st.columns(2)
    new_w = m1.text_input("Register New Worker")
    if m1.button("Add Person") and new_w:
        conn.table("production").insert({"Worker": new_w, "Notes": "SYSTEM_NEW_ITEM", "Hours": 0, "Activity": "N/A", "Job_Code": "N/A"}).execute()
        st.rerun()
