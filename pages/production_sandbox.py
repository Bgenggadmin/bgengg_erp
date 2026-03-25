import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
import plotly.express as px
import io

# --- 1. SETUP & CONNECTION ---
IST = pytz.timezone('Asia/Kolkata')
TODAY_IST = datetime.now(IST).date()
st.set_page_config(page_title="Production Master ERP | B&G", layout="wide", page_icon="🏗️")

# --- EXCEL EXPORT HELPER ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Production_Report')
        workbook  = writer.book
        worksheet = writer.sheets['Production_Report']
        header_format = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
            worksheet.set_column(col_num, col_num, 20)
    return output.getvalue()

# --- PASSWORD PROTECTION ---
def check_password():
    def password_entered():
        if st.session_state["password"] == "9025":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    return True

if not check_password():
    st.stop()

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SESSION STATE & MASTER RECOVERY ---
if 'master_data' not in st.session_state:
    try:
        # Fetching names and rates for labor cost calculation
        w_res = conn.table("master_workers").select("name, category, hourly_rate").order("name").execute()
        s_res = conn.table("master_staff").select("name").order("name").execute()
        g_res = conn.table("production_gates").select("gate_name").order("step_order").execute()
        
        st.session_state.master_data = {
            "workers_df": pd.DataFrame(w_res.data or []),
            "workers": [w['name'] for w in (w_res.data or [])],
            "staff": [s['name'] for s in (s_res.data or [])],
            "gates": [g['gate_name'] for g in (g_res.data or [])]
        }
    except Exception as e:
        st.error(f"Master Sync Error: {e}")

master = st.session_state.get('master_data', {"workers": [], "staff": [], "gates": [], "workers_df": pd.DataFrame()})

# --- 3. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_master_data():
    try:
        p_res = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
        l_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        m_res = conn.table("production_gates").select("*").order("step_order").execute()
        j_res = conn.table("job_planning").select("*").order("step_order").execute()
        pur_res = conn.table("purchase_orders").select("*").execute()
        sub_res = conn.table("job_sub_tasks").select("*").execute()
        
        return (pd.DataFrame(p_res.data or []), 
                pd.DataFrame(l_res.data or []), 
                pd.DataFrame(m_res.data or []), 
                pd.DataFrame(j_res.data or []), 
                pd.DataFrame(pur_res.data or []), 
                pd.DataFrame(sub_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return [pd.DataFrame()] * 6

df_projects, df_logs, df_master_gates, df_job_plans, df_purchase, df_sub_tasks = get_master_data()

all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []
all_activities = master.get('gates', [])
all_workers = master.get('workers', [])

# --- 4. NAVIGATION ---
tab_summary, tab_plan, tab_entry, tab_analytics, tab_master = st.tabs([
    "📊 Executive Summary", "🏗️ Scheduling", "👷 Daily Entry", "📈 Analytics", "⚙️ Master Settings"
])

# --- TAB 1: EXECUTIVE SUMMARY ---
with tab_summary:
    st.subheader("📊 Factory-Wide Progress")
    if df_job_plans.empty:
        st.info("No active production plans found.")
    else:
        job_stats = []
        for job in all_jobs:
            job_gates = df_job_plans[df_job_plans['job_no'] == job]
            if not job_gates.empty:
                total = len(job_gates)
                done = len(job_gates[job_gates['current_status'] == "Completed"])
                progress = int((done / total) * 100)
                
                pending_materials = df_purchase[(df_purchase['job_no'] == job) & (df_purchase['status'] != "Received")] if not df_purchase.empty else pd.DataFrame()
                mat_status = "✅ Ready" if pending_materials.empty else f"⚠️ Missing {len(pending_materials)} Items"
                
                job_stats.append({"Job No": job, "Progress": progress, "Materials": mat_status})

        if job_stats:
            st.dataframe(pd.DataFrame(job_stats), use_container_width=True, hide_index=True)

# --- TAB 2: SCHEDULING ---
with tab_plan:
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    if target_job != "-- Select --":
        # Delivery Dashboard
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            c1, c2, c3 = st.columns(3)
            c1.metric("PO Dispatch", pd.to_datetime(p_data.get('po_delivery_date')).strftime('%d-%b') if p_data.get('po_delivery_date') else "N/A")
            c2.metric("Revised Date", pd.to_datetime(p_data.get('revised_delivery_date')).strftime('%d-%b') if p_data.get('revised_delivery_date') else "None")
            
            if st.button("📝 Edit Dates"):
                @st.dialog("Update Dates")
                def up_dt():
                    nd = st.date_input("Revised Date")
                    if st.button("Save"):
                        conn.table("anchor_projects").update({"revised_delivery_date": str(nd)}).eq("job_no", target_job).execute()
                        st.cache_data.clear(); st.rerun()
                up_dt()

        # Gate Management
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job].sort_values('step_order')
        for _, row in current_job_steps.iterrows():
            with st.container(border=True):
                gc1, gc2, gc3 = st.columns([3, 1, 1])
                gc1.write(f"### {row['gate_name']}")
                gc2.write(f"Status: {row['current_status']}")
                if row['current_status'] != "Completed":
                    if gc3.button("✅ Close", key=f"cl_{row['id']}"):
                        conn.table("job_planning").update({"current_status": "Completed"}).eq("id", row['id']).execute()
                        st.cache_data.clear(); st.rerun()

# --- TAB 3: DAILY ENTRY ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    f_job = st.selectbox("Select Job", ["-- Select --"] + all_jobs, key="ent_job")
    
    if f_job != "-- Select --":
        job_gates = df_job_plans[df_job_plans['job_no'] == f_job]
        active_list = job_gates[job_gates['current_status'] == 'Active']['gate_name'].tolist()
        form_gates = active_list if active_list else job_gates['gate_name'].tolist()

        with st.form("prod_form", clear_on_submit=True):
            f1, f2, f3 = st.columns(3)
            f_act = f1.selectbox("Gate", form_gates)
            f_wrk = f1.selectbox("Worker", ["-- Select --"] + all_workers)
            f_hrs = f2.number_input("Hrs", min_value=0.0, step=0.5)
            f_unit = f2.selectbox("Unit", ["Nos", "Mtrs", "Sq.Ft", "Kgs", "Joints"])
            f_out = f3.number_input("Qty", min_value=0.0, step=0.1)
            f_notes = st.text_input("Remarks")
            
            if st.form_submit_button("🚀 Log Progress"):
                if f_wrk != "-- Select --":
                    # Fetching rate for labor_cost
                    w_df = master['workers_df']
                    meta = w_df[w_df['name'] == f_wrk].iloc[0] if not w_df.empty else {}
                    cost = f_hrs * float(meta.get('hourly_rate', 0))
                    
                    conn.table("production").insert({
                        "Job_Code": f_job, "Activity": f_act, "Worker": f_wrk, 
                        "Hours": f_hrs, "Output": f_out, "Unit": f_unit,
                        "Notes": f_notes, "labor_cost": cost, 
                        "worker_category": meta.get('category', 'Helper'),
                        "created_at": datetime.now(IST).isoformat()
                    }).execute()
                    st.cache_data.clear(); st.success("Logged!"); st.rerun()

# --- TAB 4: ANALYTICS ---
with tab_analytics:
    if not df_logs.empty:
        # Cost Analysis
        st.write("### 💰 Financial Overview")
        cost_df = df_logs.groupby('Job_Code')['labor_cost'].sum().reset_index()
        st.plotly_chart(px.bar(cost_df, x='Job_Code', y='labor_cost', title="Labor Cost per Job (₹)"), use_container_width=True)
        
        # Man-Hours
        st.write("### 🕒 Efficiency")
        hrs_df = df_logs.groupby('Worker')['Hours'].sum().reset_index()
        st.plotly_chart(px.pie(hrs_df, values='Hours', names='Worker', title="Worker Hour Distribution"), use_container_width=True)

# --- TAB 5: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ Settings")
    st.info("Use this section to add new workers or process gates to the master list.")
    # Gate addition logic from old code
    with st.form("new_gate"):
        ng_name = st.text_input("New Gate Name")
        if st.form_submit_button("Add Gate"):
            conn.table("production_gates").insert({"gate_name": ng_name}).execute()
            st.cache_data.clear(); st.rerun()
