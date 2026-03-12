import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz
import plotly.express as px

# --- 1. CONFIGURATION & DATABASE ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Production Master", layout="wide", page_icon="🏭")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS (Cached for Speed) ---
@st.cache_data(ttl=5)
def get_unified_data():
    plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
    prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
    return pd.DataFrame(plan_res.data or []), pd.DataFrame(prod_res.data or [])

df_plan, df_logs = get_unified_data()

# --- 3. MASTER MAPPINGS ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
universal_gates = [
    "1. Engineering & MTC Verify", "2. Marking & Cutting", "3. Sub-Assembly & Machining",
    "4. Shell/Body Fabrication", "5. Main Assembly/Internals", "6. Nozzles & Accessories",
    "7. Inspection & NDT", "8. Hydro/Pressure Testing", "9. Insulation & Finishing",
    "10. Final Assembly & Dispatch"
]

# --- 4. THE UI TABS ---
tab_plan, tab_work, tab_costing = st.tabs([
    "🏗️ Production Planning & Gates", 
    "👷 Daily Worker Productivity", 
    "💰 Job Costing & Analytics"
])

# --- TAB 1: PRODUCTION PLANNING & QUALITY GATES ---
with tab_plan:
    st.subheader("Live Shop Floor Gates & Quality Alerts")
    
    if not df_plan.empty:
        # Pre-calculate hours for the "Red Alert" logic
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for index, row in df_plan.iterrows():
            job_id = str(row['job_no'])
            actual_hrs = hrs_sum.get(job_id, 0)
            
            # Simple Budget Logic: 200hrs for heavy equip, 100hrs for light
            budget = 200 if any(x in row['project_description'].upper() for x in ["REACTOR", "COLUMN", "ANFD"]) else 100
            is_over = actual_hrs > budget

            with st.container(border=True):
                # Header Section
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1:
                    st.markdown(f"### Job {job_id} | {row['client_name']}")
                    st.caption(f"📦 {row['project_description']}")
                
                with c2:
                    color = "normal" if not is_over else "inverse"
                    st.metric("Man-Hours Used", f"{actual_hrs} Hrs", 
                              delta=f"{actual_hrs - budget} Over" if is_over else None, 
                              delta_color=color)
                
                with c3:
                    if row.get('material_shortage'):
                        st.error(f"🚨 SHORTAGE: {row.get('shortage_details', 'Pending')}")
                    else:
                        st.success("✅ Materials OK")

                # Controls Section
                col_a, col_b, col_c = st.columns([1.5, 1.5, 1])
                new_gate = col_a.selectbox("Current Gate", universal_gates, 
                                          index=universal_gates.index(row['drawing_status']) if row['drawing_status'] in universal_gates else 0,
                                          key=f"gt_{row['id']}")
                
                sh_toggle = col_b.toggle("Report Shortage", value=row.get('material_shortage', False), key=f"tg_{row['id']}")
                sh_note = col_b.text_input("Shortage Detail", value=row.get('shortage_details', ""), key=f"shn_{row['id']}")
                
                if col_c.button("Update Status", key=f"sav_{row['id']}", use_container_width=True, type="primary"):
                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate,
                        "material_shortage": sh_toggle,
                        "shortage_details": sh_note
                    }).eq("id", row['id']).execute()
                    st.toast("Updated Successfully")
                    st.rerun()

                # Critical Checklist Expander
                with st.expander("🛠️ View Quality Checklist & Budget Progress"):
                    st.progress(min(actual_hrs/budget, 1.0), text=f"Budget Consumption: {int((actual_hrs/budget)*100)}%")
                    st.write("---")
                    qc_cols = st.columns(3)
                    qc_cols[0].checkbox("MTC/Plate ID Verified", key=f"qc1_{row['id']}")
                    qc_cols[1].checkbox("Weld Plan Approved", key=f"qc2_{row['id']}")
                    qc_cols[2].checkbox("NDT/Radiography Clear", key=f"qc3_{row['id']}")
    else:
        st.info("No active 'Won' projects found.")

# --- TAB 2: WORKER PRODUCTIVITY (Integrated from bg_app.py) ---
with tab_work:
    st.subheader("Daily Productivity Log")
    
    with st.form("worker_entry", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        
        # Pull dynamic lists for better accuracy
        all_workers = sorted(df_logs["Worker"].unique().tolist()) if not df_logs.empty else []
        all_job_codes = sorted(df_plan["job_no"].unique().tolist()) if not df_plan.empty else []

        w_sup = f1.selectbox("Supervisor", base_supervisors)
        w_name = f1.selectbox("Worker Name", ["-- Select --"] + all_workers)
        
        w_job = f2.selectbox("Job Code", ["-- Select --"] + all_job_codes)
        w_act = f2.selectbox("Activity", ["Welding", "Fitting", "Grinding", "Marking", "Plasma Cutting", "Bending"])
        
        w_out = f3.number_input("Output Value", min_value=0.0)
        w_hrs = f3.number_input("Hours Spent", min_value=0.0)
        
        w_nts = st.text_area("Specific Work Notes")
        
        if st.form_submit_button("💾 Save to Cloud", use_container_width=True):
            if "-- Select --" in [w_name, w_job]:
                st.warning("Worker and Job Code are required.")
            else:
                payload = {
                    "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                    "Supervisor": w_sup, "Worker": w_name, "Job_Code": w_job,
                    "Activity": w_act, "Unit": "Nos/Mts", "Output": w_out,
                    "Hours": w_hrs, "Notes": w_nts
                }
                conn.table("production").insert(payload).execute()
                st.success("Log Saved!")
                st.rerun()

    st.divider()
    st.write("### Recent Logs (Last 10)")
    if not df_logs.empty:
        st.dataframe(df_logs.head(10), use_container_width=True, hide_index=True)

# --- TAB 3: JOB COSTING & ANALYTICS ---
with tab_costing:
    st.subheader("💰 Financial & Man-Hour Analytics")
    
    if not df_logs.empty:
        clean_df = df_logs[df_logs['Notes'] != "SYSTEM_NEW_ITEM"].copy()
        
        # Chart 1: Job vs Hours
        cost_df = clean_df.groupby('Job_Code')['Hours'].sum().reset_index()
        fig_cost = px.bar(cost_df, x='Job_Code', y='Hours', title="Cumulative Man-Hours by Job", color='Hours')
        st.plotly_chart(fig_cost, use_container_width=True)

        # Chart 2: Activity Breakdown
        act_df = clean_df.groupby('Activity')['Hours'].sum().reset_index()
        fig_pie = px.pie(act_df, values='Hours', names='Activity', title="Where is the time going?", hole=0.3)
        st.plotly_chart(fig_pie, use_container_width=True)
        
        # Download Master Data
        csv = clean_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download Master Productivity Sheet", data=csv, file_name="BG_Master_Costing.csv")
    else:
        st.info("Log data for analysis.")
