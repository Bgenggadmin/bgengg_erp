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
        
        return (pd.DataFrame(p_res.data or []), 
                pd.DataFrame(l_res.data or []), 
                pd.DataFrame(m_res.data or []), 
                pd.DataFrame(j_res.data or []),
                pd.DataFrame(pur_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_projects, df_logs, df_master_gates, df_job_plans, df_purchase = get_master_data()
all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []
all_workers = master.get('workers', [])
all_activities = [f"{g['gate_name']} | {g['sub_task']}" for g in master.get('gates_full', [])]

# --- 4. NAVIGATION ---
tab_plan, tab_entry, tab_analytics, tab_master = st.tabs([
    "🏗️ Scheduling & Execution", "👷 Daily Entry", "📊 Analytics & Reports", "⚙️ Master Settings"
])

# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
        # RESTORED DELIVERY DASHBOARD
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            with st.container(border=True):
                po_num = p_data.get('po_no') or "---"
                po_disp_dt = pd.to_datetime(p_data.get('po_delivery_date')).date() if pd.notnull(p_data.get('po_delivery_date')) else None
                rev_dt = pd.to_datetime(p_data.get('revised_delivery_date')).date() if pd.notnull(p_data.get('revised_delivery_date')) else None
                
                c1, c2, c3, c4 = st.columns(4)
                c1.write(f"📄 **PO No: {po_num}**")
                c2.write(f"🚚 **Original Dispatch**\n{po_disp_dt.strftime('%d-%b-%Y') if po_disp_dt else '---'}")
                c3.write(f"🔴 **Revised Date**\n{rev_dt.strftime('%d-%b-%Y') if rev_dt else '---'}")
                
                final_target = rev_dt if rev_dt else po_disp_dt
                if final_target:
                    days_left = (final_target - date.today()).days
                    c4.metric("Days left", f"{days_left} Days")

        # RESTORED URGENT MATERIAL TRIGGER
        with st.expander("🚨 Urgent Material Request", expanded=False):
            with st.form("urgent_purchase_form"):
                r1, r2 = st.columns([3, 1])
                it_name = r1.text_input("Material Item")
                it_qty = r2.text_input("Qty")
                it_specs = st.text_area("Reason/Specs")
                if st.form_submit_button("Send Requisition"):
                    conn.table("purchase_orders").insert({"job_no": target_job, "item_name": it_name, "specs": f"URGENT: {it_specs} ({it_qty})", "status": "Triggered"}).execute()
                    st.cache_data.clear(); st.rerun()

        st.divider()
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()
        
        # RESTORED CLONE LOGIC
        if current_job_steps.empty:
            src_job = st.selectbox("Clone Sequence from:", ["-- Select --"] + all_jobs)
            if st.button("🚀 Clone Plan") and src_job != "-- Select --":
                source_steps = df_job_plans[df_job_plans['job_no'] == src_job]
                new_steps = [{"job_no": target_job, "gate_name": s['gate_name'], "sub_task": s['sub_task'], "step_order": s['step_order'], "current_status": "Pending"} for _, s in source_steps.iterrows()]
                conn.table("job_planning").insert(new_steps).execute()
                st.cache_data.clear(); st.rerun()

        # MANAGE PLAN
        with st.expander("➕ Add Single Gate", expanded=False):
            with st.form("add_gate"):
                sc1, sc2 = st.columns(2)
                ng_gate_raw = sc1.selectbox("Gate", all_activities)
                ng_order = sc2.number_input("Step Order", value=len(current_job_steps)+1)
                if st.form_submit_button("Add to Sequence"):
                    ng_gate, ng_sub = ng_gate_raw.split(" | ")
                    conn.table("job_planning").insert({"job_no": target_job, "gate_name": ng_gate, "sub_task": ng_sub, "step_order": ng_order, "current_status": "Pending"}).execute()
                    st.cache_data.clear(); st.rerun()

# --- TAB 2: DAILY ENTRY (RESTORED CORRECTION TOOLS & MULTIPLE WORKERS) ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="ent_job")
    
    if f_job != "-- Select --":
        active_list = df_job_plans[(df_job_plans['job_no'] == f_job) & (df_job_plans['current_status'] == 'Active')]
        
        if active_list.empty:
            st.warning("No Active gates. Start a gate in Scheduling first.")
        else:
            with st.form("prod_form", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                gate_opts = {f"{r['gate_name']} ({r['sub_task']})": r for _, r in active_list.iterrows()}
                f_gate = f1.selectbox("Process", list(gate_opts.keys()))
                
                # MULTIPLE WORKER SELECTION
                f_wrk_list = f1.multiselect("Workers Involved", all_workers)
                
                f_hrs = f2.number_input("Hrs (Per Person)", min_value=0.5, step=0.5)
                f_unit = f2.selectbox("Unit", ["Nos", "Mtrs", "Joints", "Kgs"])
                f_out = f3.number_input("Produced Qty", min_value=0.0)
                f_notes = st.text_input("Notes / Remarks")
                
                if st.form_submit_button("🚀 Log Progress"):
                    if f_wrk_list:
                        worker_str = ", ".join(f_wrk_list)
                        conn.table("production").insert({
                            "Job_Code": f_job, "Activity": str(f_gate), "Worker": worker_str,
                            "Hours": f_hrs, "Output": f_out, "Unit": f_unit, "notes": f_notes or ""
                        }).execute()
                        st.cache_data.clear(); st.success("Logged!"); st.rerun()

    # RESTORED CORRECTION TOOLS & TABLE
    st.divider()
    if not df_logs.empty:
        log_view = df_logs[df_logs['Job_Code'] == f_job] if f_job != "-- Select --" else df_logs
        st.write("#### Recent Activity")
        st.dataframe(log_view[['created_at', 'Activity', 'Worker', 'Hours', 'Output', 'notes']].head(10), use_container_width=True)

# --- TAB 4: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ Gate & Sub-Task Master")
    with st.form("new_gate"):
        mg1, mg2, mg3 = st.columns([2, 2, 1])
        ng_name = mg1.text_input("Main Gate")
        ng_sub = mg2.text_input("Sub-Task")
        ng_order = mg3.number_input("Order", value=len(df_master_gates)+1)
        if st.form_submit_button("Add to Master"):
            conn.table("production_gates").insert({"gate_name": ng_name, "sub_task": ng_sub, "step_order": ng_order}).execute()
            st.cache_data.clear(); st.rerun()
    st.dataframe(df_master_gates.sort_values('step_order'), use_container_width=True, hide_index=True)
