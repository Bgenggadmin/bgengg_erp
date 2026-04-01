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

# Mappings
all_staff = master.get('staff', [])
all_workers = sorted(list(set(master.get('workers', []))))
all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []
# Displays as "Welding | Tagging" in dropdowns
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
        # A. DELIVERY DASHBOARD (PRESERVED)
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            with st.container(border=True):
                po_num = p_data.get('po_no') or "---"
                po_placed_dt = pd.to_datetime(p_data.get('po_date')).date() if pd.notnull(p_data.get('po_date')) else None
                po_disp_dt = pd.to_datetime(p_data.get('po_delivery_date')).date() if pd.notnull(p_data.get('po_delivery_date')) else None
                rev_dt = pd.to_datetime(p_data.get('revised_delivery_date')).date() if pd.notnull(p_data.get('revised_delivery_date')) else None
                
                c1, c2, c3, c4 = st.columns([1.5, 1.5, 1.5, 1.5])
                c1.write(f"📄 **PO No: {po_num}**\nDate: {po_placed_dt.strftime('%d-%b-%Y') if po_placed_dt else '---'}")
                c2.write(f"🚚 **PO Dispatch**\n{po_disp_dt.strftime('%d-%b-%Y') if po_disp_dt else '---'}")
                c3.write(f"🔴 **Revised Date**\n{rev_dt.strftime('%d-%b-%Y') if rev_dt else '---'}")
                
                final_target = rev_dt if rev_dt else po_disp_dt
                if final_target:
                    days_left = (final_target - date.today()).days
                    c4.metric("Days to Dispatch", f"{days_left} Days", delta=days_left, delta_color="normal" if days_left > 7 else "inverse")

                if st.button("📝 Update Schedule", key="edit_delivery"):
                    @st.dialog("Update Commitment")
                    def update_dates():
                        n_po_disp = st.date_input("Original PO Dispatch Date", value=po_disp_dt if po_disp_dt else date.today())
                        n_rev = st.date_input("Revised Delivery Date", value=rev_dt if rev_dt else n_po_disp)
                        if st.button("Save Changes"):
                            conn.table("anchor_projects").update({"po_delivery_date": str(n_po_disp), "revised_delivery_date": str(n_rev)}).eq("job_no", target_job).execute()
                            st.cache_data.clear(); st.rerun()
                    update_dates()

        # B. URGENT MATERIAL (PRESERVED)
        with st.expander("🚨 Trigger Urgent Purchase Requisition", expanded=False):
            with st.form("urgent_purchase_form", clear_on_submit=True):
                r1, r2, r3 = st.columns([2, 1, 1])
                it_name = r1.text_input("Material Item Name")
                it_qty = r2.text_input("Qty")
                it_date = r3.date_input("Required By", value=date.today() + timedelta(days=2))
                it_specs = st.text_area("Specs / Reason for Urgency")
                if st.form_submit_button("🔥 Send Urgent Request"):
                    if it_name and it_qty:
                        conn.table("purchase_orders").insert({
                            "job_no": target_job, "item_name": it_name,
                            "specs": f"URGENT (By {it_date.strftime('%d-%b')}): {it_specs} (Qty: {it_qty})",
                            "status": "Triggered", "created_at": datetime.now(IST).isoformat()
                        }).execute()
                        st.cache_data.clear(); st.success("Urgent request sent!"); st.rerun()

        st.divider()
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()
        
        # C. CLONE LOGIC (PRESERVED)
        if current_job_steps.empty:
            st.warning("⚠️ No Plan Detected")
            src_job = st.selectbox("Clone from Template:", ["-- Select --"] + all_jobs, key="clone_src")
            if st.button("🚀 Clone Sequence") and src_job != "-- Select --":
                source_steps = df_job_plans[df_job_plans['job_no'] == src_job]
                if not source_steps.empty:
                    new_steps = [{"job_no": target_job, "gate_name": s['gate_name'], "step_order": s['step_order'], "planned_start_date": date.today().isoformat(), "planned_end_date": (date.today()+timedelta(days=5)).isoformat(), "current_status": "Pending"} for _, s in source_steps.iterrows()]
                    conn.table("job_planning").insert(new_steps).execute()
                    st.cache_data.clear(); st.rerun()

        with st.expander("➕ Add Single Gate to Plan", expanded=False):
            with st.form("add_gate_form", clear_on_submit=True):
                sc1, sc2, sc3 = st.columns([2, 2, 1])
                ng_gate_raw = sc1.selectbox("Process Gate", all_activities)
                ng_dates = sc2.date_input("Planned Window", [date.today(), date.today()+timedelta(days=5)])
                ng_order = sc3.number_input("Step Order", min_value=0.1, value=float(len(current_job_steps)+1), step=0.1)
                if st.form_submit_button("🚀 Add to Plan"):
                    if len(ng_dates) == 2 and " | " in ng_gate_raw:
                        gate_main, gate_sub = ng_gate_raw.split(" | ")
                        conn.table("job_planning").insert({"job_no": target_job, "gate_name": gate_main, "step_order": ng_order, "planned_start_date": ng_dates[0].isoformat(), "planned_end_date": ng_dates[1].isoformat(), "current_status": "Pending"}).execute()
                        st.cache_data.clear(); st.rerun()

# --- TAB 2: DAILY ENTRY (MULTI-WORKER INTEGRATED) ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="ent_job")
    if f_job != "-- Select --":
        active_gates_df = df_job_plans[df_job_plans['job_no'] == f_job]
        active_list = active_gates_df[active_gates_df['current_status'] == 'Active']['gate_name'].tolist()
        fallback_list = active_gates_df['gate_name'].tolist()
        form_gates = active_list if active_list else fallback_list
        if not form_gates:
            st.warning("⚠️ No gates found in plan.")
        else:
            with st.form("prod_form", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                f_act = f1.selectbox("Gate", form_gates)
                f_wrk_list = f1.multiselect("Workers Involved", all_workers)
                f_hrs = f2.number_input("Hrs (Per Person)", min_value=0.0, step=0.5)
                f_unit = f2.selectbox("Unit", ["Nos", "Mtrs", "Sq.Ft", "Kgs", "Joints"])
                f_out = f3.number_input("Qty Produced", min_value=0.0, step=0.1)
                f_notes = st.text_input("Remarks / Notes")
                if st.form_submit_button("🚀 Log Progress"):
                    if f_wrk_list:
                        worker_string = ", ".join(f_wrk_list)
                        conn.table("production").insert({
                            "Job_Code": f_job, "Activity": f_act, "Worker": worker_string, 
                            "Hours": f_hrs, "Output": f_out, "Unit": f_unit, "notes": f_notes,
                            "created_at": datetime.now(IST).isoformat()
                        }).execute()
                        st.cache_data.clear(); st.success("Logged successfully!"); st.rerun()
                    else: st.error("Select at least one worker.")

    # CORRECTION TOOLS (PRESERVED)
    st.divider()
    if not df_logs.empty:
        display_logs = df_logs[df_logs['Job_Code'] == f_job] if f_job != "-- Select --" else df_logs
        with st.expander("🛠️ Correction Tools"):
            if not display_logs.empty:
                last_row = display_logs.iloc[0]
                if st.button("✏️ Edit Last Entry"):
                    @st.dialog("Edit Log")
                    def edit_log(item):
                        nh = st.number_input("Hrs", value=float(item['Hours']))
                        nq = st.number_input("Qty", value=float(item['Output']))
                        if st.button("Save"):
                            conn.table("production").update({"Hours": nh, "Output": nq}).eq("id", item['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    edit_log(last_row)
        st.dataframe(display_logs[['created_at', 'Job_Code', 'Activity', 'Worker', 'Hours', 'Output', 'Unit', 'notes']].head(10), use_container_width=True, hide_index=True)

# --- TAB 3: ANALYTICS & REPORTS (TABLES ONLY) ---
with tab_analytics:
    st.subheader("📊 Production Intelligence")
    if not df_logs.empty:
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce').fillna(0)
        df_logs['Output'] = pd.to_numeric(df_logs['Output'], errors='coerce').fillna(0)
        
        k1, k2, k3 = st.columns(3)
        total_hrs = df_logs['Hours'].sum()
        k1.metric("Total Man-Hours", f"{total_hrs:.1f} hrs")
        k2.metric("Total Output", f"{df_logs['Output'].sum():.0f} Units")
        k3.metric("Productivity Index", f"{(df_logs['Output'].sum() / total_hrs if total_hrs > 0 else 0):.2f} U/Hr")
        
        st.divider()
        t_col1, t_col2 = st.columns(2)
        with t_col1:
            st.markdown("##### 🕒 Hours per Job")
            jsum = df_logs.groupby('Job_Code').agg({'Hours':'sum', 'Output':'sum'}).reset_index()
            st.dataframe(jsum.sort_values('Hours', ascending=False), hide_index=True, use_container_width=True)
        with t_col2:
            st.markdown("##### 👷 Worker Contribution")
            wsum = df_logs.groupby('Worker').agg({'Hours':'sum', 'Job_Code':'nunique'}).reset_index()
            st.dataframe(wsum.sort_values('Hours', ascending=False), hide_index=True, use_container_width=True)

# --- TAB 4: MASTER SETTINGS (SUB-TASK SUPPORT) ---
with tab_master:
    st.subheader("⚙️ Gate Master")
    with st.form("new_gate"):
        mg1, mg2, mg3 = st.columns([2, 2, 1])
        ng_name = mg1.text_input("Main Gate Name")
        ng_sub = mg2.text_input("Sub-Task (e.g., Pre-bending, Helper)")
        ng_order = mg3.number_input("Unique Step Order (e.g., 3.1)", value=float(len(df_master_gates)+1), step=0.1)
        if st.form_submit_button("Add to Master"):
            # IMPORTANT: Using a unique ng_order avoids the Primary Key/Unique crash
            conn.table("production_gates").insert({"gate_name": ng_name, "sub_task": ng_sub, "step_order": ng_order}).execute()
            st.cache_data.clear(); st.rerun()
    if not df_master_gates.empty:
        st.dataframe(df_master_gates.sort_values('step_order')[['step_order', 'gate_name', 'sub_task']], use_container_width=True, hide_index=True)
