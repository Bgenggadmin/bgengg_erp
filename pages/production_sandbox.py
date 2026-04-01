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

# --- 4. NAVIGATION ---
tab_plan, tab_entry, tab_analytics, tab_master = st.tabs([
    "🏗️ Scheduling & Execution", "👷 Daily Entry", "📊 Analytics & Reports", "⚙️ Master Settings"
])

# --- TAB 1: SCHEDULING & EXECUTION (RESTORED FULL LIVE LOGIC) ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
        # A. RESTORED DELIVERY DASHBOARD
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
                else:
                    c4.caption("⏳ No target date set")

                if st.button("📝 Update Schedule", key="edit_delivery"):
                    @st.dialog("Update Commitment")
                    def update_dates():
                        n_po_disp = st.date_input("Original PO Dispatch Date", value=po_disp_dt if po_disp_dt else date.today())
                        n_rev = st.date_input("Revised Delivery Date", value=rev_dt if rev_dt else n_po_disp)
                        if st.button("Save Changes"):
                            conn.table("anchor_projects").update({"po_delivery_date": str(n_po_disp), "revised_delivery_date": str(n_rev)}).eq("job_no", target_job).execute()
                            st.cache_data.clear(); st.rerun()
                    update_dates()

        # B. RESTORED URGENT MATERIAL TRIGGER
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

        # C. RESTORED MATERIAL STATUS
        with st.expander("🛒 Current Material Status", expanded=False):
            job_purchase = df_purchase[df_purchase['job_no'] == target_job] if not df_purchase.empty else pd.DataFrame()
            if not job_purchase.empty:
                for _, p_item in job_purchase.iterrows():
                    pc1, pc2, pc3 = st.columns([2, 2, 1])
                    pc1.write(f"🔹 **{p_item['item_name']}**")
                    pc2.caption(f"{p_item['specs']}")
                    if p_item['status'] == "Received": pc3.success(p_item['status'])
                    else: pc3.warning(p_item['status'])
            else: st.info("No materials tracked.")

        st.divider()
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()
        
        # D. RESTORED CLONE LOGIC
        if current_job_steps.empty:
            st.warning("⚠️ No Plan Detected")
            src_job = st.selectbox("Clone from Template:", ["-- Select --"] + all_jobs, key="clone_src")
            if st.button("🚀 Clone Sequence") and src_job != "-- Select --":
                source_steps = df_job_plans[df_job_plans['job_no'] == src_job]
                if not source_steps.empty:
                    new_steps = [{"job_no": target_job, "gate_name": s['gate_name'], "step_order": s['step_order'], "planned_start_date": date.today().isoformat(), "planned_end_date": (date.today()+timedelta(days=5)).isoformat(), "current_status": "Pending"} for _, s in source_steps.iterrows()]
                    conn.table("job_planning").insert(new_steps).execute()
                    st.cache_data.clear(); st.rerun()

        # E. RESTORED STEP MANAGEMENT & EXECUTION
        if not current_job_steps.empty:
            st.subheader(f"🏁 Execution: {target_job}")
            for _, row in current_job_steps.sort_values('step_order').iterrows():
                p_start = pd.to_datetime(row['planned_start_date']).date() if pd.notnull(row['planned_start_date']) else None
                p_end = pd.to_datetime(row['planned_end_date']).date() if pd.notnull(row['planned_end_date']) else None
                
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([2.5, 1, 1, 1])
                    with col1:
                        st.markdown(f"**Step {row['step_order']}: {row['gate_name']}**")
                        if p_start and p_end:
                            st.caption(f"🗓️ Planned: {p_start.strftime('%d %b')} — {p_end.strftime('%d %b')}")

                    if row['current_status'] == "Pending":
                        col2.warning("⏳ Pending")
                        if col4.button("▶️ Start", key=f"st_{row['id']}", use_container_width=True):
                            conn.table("job_planning").update({"current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    elif row['current_status'] == "Active":
                        col2.info("🚀 Active")
                        if p_end:
                            diff = (date.today() - p_end).days
                            if diff > 0: col3.metric("Delay", f"{diff} Days", delta=f"-{diff}", delta_color="inverse")
                            else: col3.success("On Track")
                        if col4.button("✅ Close", key=f"cl_{row['id']}", use_container_width=True):
                            conn.table("job_planning").update({"current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    else:
                        col2.success("🏁 Completed")
                        if pd.notnull(row.get('actual_end_date')):
                            act_end = pd.to_datetime(row['actual_end_date']).date()
                            col3.caption(f"Finished: {act_end.strftime('%d %b')}")

# --- TAB 2: DAILY ENTRY (SPLITTING SUB-TASKS & MULTI-WORKERS) ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="ent_job")
    if f_job != "-- Select --":
        active_gates = df_job_plans[(df_job_plans['job_no'] == f_job) & (df_job_plans['current_status'] == 'Active')]
        if active_gates.empty:
            st.warning("No Active gates. Start a process in Scheduling first.")
        else:
            with st.form("prod_form", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                f_gate = f1.selectbox("Main Gate", active_gates['gate_name'].tolist())
                
                # Dynamic Sub-Task Splitting
                gate_rec = df_master_gates[df_master_gates['gate_name'] == f_gate].iloc[0]
                sub_tasks = [s.strip() for s in str(gate_rec.get('sub_task', 'General')).split(",")]
                
                f_sub = f1.selectbox("Specific Sub-Task", sub_tasks)
                f_wrk_list = f1.multiselect("Workers Involved", all_workers)
                
                f_hrs = f2.number_input("Hrs (Per Person)", min_value=0.0, step=0.5)
                f_unit = f2.selectbox("Unit", ["Nos", "Mtrs", "Joints", "Kgs"])
                f_out = f3.number_input("Qty Produced", min_value=0.0)
                f_notes = st.text_input("Remarks")
                
                if st.form_submit_button("🚀 Log Progress"):
                    if f_wrk_list:
                        conn.table("production").insert({
                            "Job_Code": f_job, "Activity": f_gate, "sub_task": f_sub,
                            "Worker": ", ".join(f_wrk_list), "Hours": f_hrs, "Output": f_out, "Unit": f_unit, "notes": f_notes
                        }).execute()
                        st.cache_data.clear(); st.success("Logged!"); st.rerun()

# --- TAB 3: ANALYTICS (RESTORED TABLES) ---
with tab_analytics:
    st.subheader("📊 Production Intelligence")
    if not df_logs.empty:
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce').fillna(0)
        c_a1, c_a2 = st.columns(2)
        with c_a1:
            st.markdown("##### 🕒 Hours per Job")
            jsum = df_logs.groupby('Job_Code').agg({'Hours':'sum'}).reset_index()
            st.dataframe(jsum.sort_values('Hours', ascending=False), hide_index=True, use_container_width=True)
        with c_a2:
            st.markdown("##### 👷 Worker Contribution")
            wsum = df_logs.groupby('Worker').agg({'Hours':'sum'}).reset_index()
            st.dataframe(wsum.sort_values('Hours', ascending=False), hide_index=True, use_container_width=True)

# --- TAB 4: MASTER SETTINGS (RESTORED APPEND LOGIC) ---
with tab_master:
    st.subheader("⚙️ Gate & Sub-Task Master")
    with st.form("append_subtask"):
        st.write("➕ Add Sub-Tasks to Existing Gate")
        target_g = st.selectbox("Select Gate", sorted(df_master_gates['gate_name'].unique().tolist()))
        current_data = df_master_gates[df_master_gates['gate_name'] == target_g].iloc[0]
        st.caption(f"Existing: {current_data['sub_task']}")
        new_sub_input = st.text_input("Enter New Sub-Task")
        if st.form_submit_button("Append Sub-Task"):
            if new_sub_input:
                existing_subs = str(current_data['sub_task'])
                updated = new_sub_input if existing_subs == "General" else f"{existing_subs}, {new_sub_input}"
                conn.table("production_gates").update({"sub_task": updated}).eq("gate_name", target_g).execute()
                st.cache_data.clear(); st.success("Updated!"); st.rerun()
    st.divider()
    st.dataframe(df_master_gates.sort_values('step_order')[['step_order', 'gate_name', 'sub_task']], use_container_width=True, hide_index=True)
