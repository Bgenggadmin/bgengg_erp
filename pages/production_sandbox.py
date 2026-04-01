import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP & CONNECTION ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master ERP | B&G", layout="wide", page_icon="🏗️")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SESSION STATE & MASTER RECOVERY ---
if 'master_data' not in st.session_state or not st.session_state.master_data:
    try:
        w_res = conn.table("master_workers").select("name").order("name").execute()
        s_res = conn.table("master_staff").select("name").order("name").execute()
        g_res = conn.table("production_gates").select("gate_name, sub_task").order("step_order").execute()
        
        st.session_state.master_data = {
            "workers": [w['name'] for w in (w_res.data or [])],
            "staff": [s['name'] for s in (s_res.data or [])],
            "gates_full": g_res.data or []
        }
    except Exception as e:
        st.error(f"Master Sync Error: {e}")

master = st.session_state.get('master_data', {})

# --- 3. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_master_data():
    try:
        p_res = conn.table("anchor_projects").select("job_no, status, po_no, po_date, po_delivery_date, revised_delivery_date").eq("status", "Won").execute()
        l_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        m_res = conn.table("production_gates").select("*").order("step_order").execute()
        j_res = conn.table("job_planning").select("*").order("step_order").execute()
        pur_res = conn.table("purchase_orders").select("*").execute()
        
        df_p = pd.DataFrame(p_res.data or []).fillna("")
        df_l = pd.DataFrame(l_res.data or []).fillna({"notes": "", "Activity": "Uncategorized"})
        df_m = pd.DataFrame(m_res.data or []).fillna("Unknown Gate")
        df_j = pd.DataFrame(j_res.data or []).fillna("")
        df_pur = pd.DataFrame(pur_res.data or []).fillna("")
        
        return df_p, df_l, df_m, df_j, df_pur
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_projects, df_logs, df_master_gates, df_job_plans, df_purchase = get_master_data()
all_jobs = sorted(df_projects['job_no'].unique().tolist()) if not df_projects.empty else []
all_workers = master.get('workers', [])

# --- 4. NAVIGATION ---
tab_plan, tab_entry, tab_analytics, tab_master = st.tabs([
    "🏗️ Scheduling & Execution", "👷 Daily Entry", "📊 Analytics & Reports", "⚙️ Master Settings"
])

# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()
        
        with st.expander("➕ Add Single Gate to Plan", expanded=False):
            with st.form("add_gate_form", clear_on_submit=True):
                sc1, sc2, sc3 = st.columns([2, 2, 1])
                gate_list = [f"{g['gate_name']} | {g['sub_task']}" for g in master.get('gates_full', [])]
                ng_gate_raw = sc1.selectbox("Process Gate", gate_list if gate_list else ["No Gates Defined"])
                ng_dates = sc2.date_input("Planned Window", [date.today(), date.today()+timedelta(days=5)])
                ng_order = sc3.number_input("Step Order", min_value=1, value=len(current_job_steps)+1)
                
                if st.form_submit_button("🚀 Add to Plan"):
                    if len(ng_dates) == 2 and " | " in ng_gate_raw:
                        ng_gate = ng_gate_raw.split(" | ")[0]
                        ng_sub = ng_gate_raw.split(" | ")[1]
                        conn.table("job_planning").insert({
                            "job_no": target_job, 
                            "gate_name": ng_gate, 
                            "sub_task": ng_sub, 
                            "step_order": ng_order, 
                            "planned_start_date": ng_dates[0].isoformat(), 
                            "planned_end_date": ng_dates[1].isoformat(), 
                            "current_status": "Pending"
                        }).execute()
                        st.cache_data.clear(); st.rerun()

# --- TAB 2: DAILY ENTRY (UPDATED FOR MULTIPLE WORKERS) ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="ent_job")
    
    if f_job != "-- Select --":
        active_gates_df = df_job_plans[df_job_plans['job_no'] == f_job]
        active_list = active_gates_df[active_gates_df['current_status'] == 'Active']
        
        if active_list.empty:
            st.warning("⚠️ No 'Active' gates found. Start a gate in Scheduling first.")
        else:
            with st.form("prod_form", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                gate_options = {f"{r['gate_name']} ({r['sub_task']})": r for _, r in active_list.iterrows()}
                f_gate_label = f1.selectbox("Active Process", list(gate_options.keys()))
                
                # CHANGED TO MULTISELECT
                f_wrk_list = f1.multiselect("Workers (Select all involved)", all_workers)
                
                f_hrs = f2.number_input("Hrs (Per Person)", min_value=0.0, step=0.5)
                f_unit = f2.selectbox("Unit", ["Nos", "Mtrs", "Sq.Ft", "Kgs", "Joints"])
                f_out = f3.number_input("Total Qty Produced", min_value=0.0, step=0.1)
                f_notes = st.text_input("Remarks / Notes")
                
                if st.form_submit_button("🚀 Log Progress"):
                    if not f_wrk_list:
                        st.error("Please select at least one worker.")
                    elif not f_gate_label:
                        st.error("Gate/Activity is missing.")
                    else:
                        # Convert list of workers to a single string for storage
                        worker_string = ", ".join(f_wrk_list)
                        
                        conn.table("production").insert({
                            "Job_Code": f_job, 
                            "Activity": str(f_gate_label),
                            "Worker": worker_string, # Now stores "Fitter, Helper1, Helper2"
                            "Hours": f_hrs, 
                            "Output": f_out, 
                            "Unit": f_unit,
                            "notes": f_notes or "",
                            "created_at": datetime.now(IST).isoformat()
                        }).execute()
                        st.cache_data.clear()
                        st.success(f"Logged {len(f_wrk_list)} workers successfully!")
                        st.rerun()

# --- TAB 4: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ Gate & Sub-Task Master")
    with st.form("new_gate"):
        mg1, mg2, mg3 = st.columns([2, 2, 1])
        ng_name = mg1.text_input("Main Gate (e.g., Welding)")
        ng_sub = mg2.text_input("Sub-Task (e.g., Tagging)")
        ng_order = mg3.number_input("Order", value=len(df_master_gates)+1)
        if st.form_submit_button("Add to Master"):
            conn.table("production_gates").insert({
                "gate_name": ng_name, 
                "sub_task": ng_sub, 
                "step_order": ng_order
            }).execute()
            st.cache_data.clear(); st.rerun()
    
    if not df_master_gates.empty:
        st.dataframe(df_master_gates.sort_values('step_order')[['step_order', 'gate_name', 'sub_task']], hide_index=True)
