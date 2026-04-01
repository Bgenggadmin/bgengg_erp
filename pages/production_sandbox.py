import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz

# --- 1. SETUP & CONNECTION ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master ERP | B&G", layout="wide", page_icon="🏗️")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SESSION STATE & MASTER RECOVERY ---
if 'master_data' not in st.session_state or not st.session_state.master_data:
    try:
        w_res = conn.table("master_workers").select("name").order("name").execute()
        s_res = conn.table("master_staff").select("name").order("name").execute()
        # Fetching gate name and sub_task as per your JSON schema
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
        return (pd.DataFrame(p_res.data or []), pd.DataFrame(l_res.data or []), pd.DataFrame(m_res.data or []), pd.DataFrame(j_res.data or []), pd.DataFrame(pur_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_projects, df_logs, df_master_gates, df_job_plans, df_purchase = get_master_data()

all_staff = master.get('staff', [])
all_workers = sorted(list(set(master.get('workers', []))))
all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []
# Updated list to combine Gate + Sub Task for the dropdowns
all_activities = [f"{g['gate_name']} | {g.get('sub_task', 'General')}" for g in master.get('gates_full', [])]

# --- 4. NAVIGATION ---
tab_plan, tab_entry, tab_analytics, tab_master = st.tabs(["🏗️ Scheduling & Execution", "👷 Daily Entry", "📊 Analytics & Reports", "⚙️ Master Settings"])

# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    if target_job != "-- Select --":
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            with st.container(border=True):
                po_num, po_disp_dt, rev_dt = p_data.get('po_no') or "---", pd.to_datetime(p_data.get('po_delivery_date')).date() if pd.notnull(p_data.get('po_delivery_date')) else None, pd.to_datetime(p_data.get('revised_delivery_date')).date() if pd.notnull(p_data.get('revised_delivery_date')) else None
                c1, c2, c3, c4 = st.columns(4)
                c1.write(f"📄 **PO No: {po_num}**"); c2.write(f"🚚 **PO Dispatch**\n{po_disp_dt.strftime('%d-%b-%Y') if po_disp_dt else '---'}"); c3.write(f"🔴 **Revised Date**\n{rev_dt.strftime('%d-%b-%Y') if rev_dt else '---'}")
                final_target = rev_dt if rev_dt else po_disp_dt
                if final_target:
                    days_left = (final_target - date.today()).days
                    c4.metric("Days left", f"{days_left} Days")

        with st.expander("➕ Add Single Gate to Plan", expanded=False):
            with st.form("add_gate_form", clear_on_submit=True):
                sc1, sc2, sc3 = st.columns([2, 2, 1])
                ng_gate_raw = sc1.selectbox("Process Gate", all_activities)
                ng_dates = sc2.date_input("Planned Window", [date.today(), date.today()+timedelta(days=5)])
                ng_order = sc3.number_input("Step Order", min_value=0.1, value=float(len(df_job_plans[df_job_plans['job_no'] == target_job])+1), step=0.1)
                if st.form_submit_button("🚀 Add to Plan"):
                    if len(ng_dates) == 2 and " | " in ng_gate_raw:
                        gate_main = ng_gate_raw.split(" | ")[0]
                        conn.table("job_planning").insert({"job_no": target_job, "gate_name": gate_main, "step_order": ng_order, "planned_start_date": ng_dates[0].isoformat(), "planned_end_date": ng_dates[1].isoformat(), "current_status": "Pending"}).execute()
                        st.cache_data.clear(); st.rerun()

# --- TAB 2: DAILY ENTRY (INTEGRATED MULTI-WORKER SELECTION) ---
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
                gate_opts = {f"{r['gate_name']}": r for _, r in active_list.iterrows()}
                f_act = f1.selectbox("Process", list(gate_opts.keys()))
                f_wrk_list = f1.multiselect("Workers Involved", all_workers)
                f_hrs = f2.number_input("Hrs (Per Person)", min_value=0.0, step=0.5); f_unit = f2.selectbox("Unit", ["Nos", "Mtrs", "Joints", "Kgs"])
                f_out = f3.number_input("Qty Produced", min_value=0.0); f_notes = st.text_input("Notes / Remarks")
                if st.form_submit_button("🚀 Log Progress"):
                    if f_wrk_list:
                        worker_string = ", ".join(f_wrk_list)
                        conn.table("production").insert({"Job_Code": f_job, "Activity": str(f_act), "Worker": worker_string, "Hours": f_hrs, "Output": f_out, "Unit": f_unit, "notes": f_notes or "", "created_at": datetime.now(IST).isoformat()}).execute()
                        st.cache_data.clear(); st.success("Logged!"); st.rerun()
                    else: st.error("Select workers.")

# --- TAB 3: ANALYTICS & REPORTS ---
with tab_analytics:
    st.subheader("📊 Production Intelligence")
    if not df_logs.empty:
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce').fillna(0)
        c_a1, c_a2 = st.columns(2)
        with c_a1:
            st.markdown("##### 🕒 Hours per Job")
            job_sum = df_logs.groupby('Job_Code').agg({'Hours':'sum', 'Output':'sum'}).reset_index()
            st.dataframe(job_sum.sort_values('Hours', ascending=False), use_container_width=True, hide_index=True)
        with c_a2:
            st.markdown("##### 👷 Worker Contribution")
            work_sum = df_logs.groupby('Worker').agg({'Hours':'sum', 'Job_Code':'nunique'}).reset_index()
            st.dataframe(work_sum.sort_values('Hours', ascending=False), use_container_width=True, hide_index=True)

# --- TAB 4: MASTER SETTINGS (FIXED INSERT LOGIC) ---
with tab_master:
    st.subheader("⚙️ Gate Master")
    with st.form("new_gate"):
        mg1, mg2, mg3 = st.columns([2, 2, 1])
        ng_name = mg1.text_input("Main Gate Name")
        ng_sub = mg2.text_input("Sub-Task Name")
        ng_order = mg3.number_input("Unique Step Order (e.g., 3.1)", value=float(len(df_master_gates)+1), step=0.1)
        if st.form_submit_button("Add to Master"):
            # Providing 0 defaults for numeric buffer columns to prevent DB rejection
            conn.table("production_gates").insert({
                "gate_name": ng_name, "sub_task": ng_sub or "General", "step_order": ng_order,
                "days_buffer": 0, "days_small": 0, "days_medium": 0, "days_large": 0
            }).execute()
            st.cache_data.clear(); st.rerun()
    st.dataframe(df_master_gates.sort_values('step_order')[['step_order', 'gate_name', 'sub_task']], use_container_width=True, hide_index=True)
