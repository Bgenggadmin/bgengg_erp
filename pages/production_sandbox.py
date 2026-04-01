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

# Mappings
all_staff = master.get('staff', [])
all_workers = sorted(list(set(master.get('workers', []))))
all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []
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
        # A. RESTORED DELIVERY DASHBOARD
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            with st.container(border=True):
                po_num = p_data.get('po_no') or "---"
                po_placed_dt = pd.to_datetime(p_data.get('po_date')).date() if pd.notnull(p_data.get('po_date')) and p_data.get('po_date') != "" else None
                po_disp_dt = pd.to_datetime(p_data.get('po_delivery_date')).date() if pd.notnull(p_data.get('po_delivery_date')) and p_data.get('po_delivery_date') != "" else None
                rev_dt = pd.to_datetime(p_data.get('revised_delivery_date')).date() if pd.notnull(p_data.get('revised_delivery_date')) and p_data.get('revised_delivery_date') != "" else None
                
                c1, c2, c3, c4 = st.columns([1.5, 1.5, 1.5, 1.5])
                c1.write(f"📄 **PO No: {po_num}**\nDate: {po_placed_dt.strftime('%d-%b-%Y') if po_placed_dt else '---'}")
                c2.write(f"🚚 **Anchor Commitment**\n{po_disp_dt.strftime('%d-%b-%Y') if po_disp_dt else '---'}")
                c3.write(f"🔴 **Revised Date**\n{rev_dt.strftime('%d-%b-%Y') if rev_dt else '---'}")
                
                final_target = rev_dt if rev_dt else po_disp_dt
                if final_target:
                    days_left = (final_target - date.today()).days
                    c4.metric("Days to Dispatch", f"{days_left} Days", delta=days_left, delta_color="normal" if days_left > 7 else "inverse")

                if st.button("📝 Update Dispatch Dates"):
                    @st.dialog("Update Schedule")
                    def update_dates():
                        n_po_disp = st.date_input("PO Dispatch Date", value=po_disp_dt if po_disp_dt else date.today())
                        n_rev = st.date_input("Revised Date", value=rev_dt if rev_dt else n_po_disp)
                        if st.button("Save Changes"):
                            conn.table("anchor_projects").update({"po_delivery_date": str(n_po_disp), "revised_delivery_date": str(n_rev)}).eq("job_no", target_job).execute()
                            st.cache_data.clear(); st.rerun()
                    update_dates()

        # B. RESTORED URGENT MATERIAL TRIGGER
        with st.expander("🚨 Trigger Urgent Purchase Requisition", expanded=False):
            with st.form("urgent_purchase_form", clear_on_submit=True):
                r1, r2, r3 = st.columns([2, 1, 1])
                it_name = r1.text_input("Item Name")
                it_qty = r2.text_input("Qty")
                it_date = r3.date_input("Need By", value=date.today() + timedelta(days=2))
                it_specs = st.text_area("Reason/Specs")
                if st.form_submit_button("🔥 Send Urgent Request"):
                    if it_name:
                        conn.table("purchase_orders").insert({
                            "job_no": target_job, "item_name": it_name,
                            "specs": f"URGENT (By {it_date.strftime('%d-%b')}): {it_specs} (Qty: {it_qty})",
                            "status": "Triggered", "created_at": datetime.now(IST).isoformat()
                        }).execute()
                        st.cache_data.clear(); st.success("Urgent request sent!"); st.rerun()

        st.divider()
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()

        # C. RESTORED CLONE LOGIC
        if current_job_steps.empty:
            st.warning("⚠️ No Plan Detected")
            src_job = st.selectbox("Clone Sequence from Template:", ["-- Select --"] + all_jobs, key="clone_src")
            if st.button("🚀 Clone Sequence") and src_job != "-- Select --":
                source_steps = df_job_plans[df_job_plans['job_no'] == src_job]
                if not source_steps.empty:
                    new_steps = [{"job_no": target_job, "gate_name": s['gate_name'], "sub_task": s.get('sub_task', ''), "step_order": s['step_order'], "current_status": "Pending"} for _, s in source_steps.iterrows()]
                    conn.table("job_planning").insert(new_steps).execute()
                    st.cache_data.clear(); st.rerun()

        # D. PLAN MANAGEMENT
        with st.expander("➕ Add Single Gate to Sequence", expanded=False):
            with st.form("add_gate_form", clear_on_submit=True):
                sc1, sc2, sc3 = st.columns([2, 2, 1])
                ng_gate_raw = sc1.selectbox("Process Gate", all_activities if all_activities else ["No Gates Defined"])
                ng_dates = sc2.date_input("Planned Window", [date.today(), date.today()+timedelta(days=5)])
                ng_order = sc3.number_input("Order", min_value=1, value=len(current_job_steps)+1)
                if st.form_submit_button("🚀 Add to Plan"):
                    if len(ng_dates) == 2 and " | " in ng_gate_raw:
                        ng_gate, ng_sub = ng_gate_raw.split(" | ")
                        conn.table("job_planning").insert({
                            "job_no": target_job, "gate_name": ng_gate, "sub_task": ng_sub, "step_order": ng_order,
                            "planned_start_date": ng_dates[0].isoformat(), "planned_end_date": ng_dates[1].isoformat(), "current_status": "Pending"
                        }).execute()
                        st.cache_data.clear(); st.rerun()

        if not current_job_steps.empty:
            with st.expander("📝 Edit Sequence & Milestones", expanded=False):
                for _, edit_row in current_job_steps.sort_values('step_order').iterrows():
                    with st.container(border=True):
                        ec1, ec2, ec3 = st.columns([3, 1, 1])
                        ec1.write(f"**Step {edit_row['step_order']}: {edit_row['gate_name']}** ({edit_row['current_status']})")
                        if ec2.button("💾 Edit", key=f"edit_{edit_row['id']}"):
                            @st.dialog("Edit Step")
                            def edit_step_dialog(row):
                                n_order = st.number_input("Order", value=int(row['step_order']))
                                if st.button("Update"):
                                    conn.table("job_planning").update({"step_order": n_order}).eq("id", row['id']).execute()
                                    st.cache_data.clear(); st.rerun()
                            edit_step_dialog(edit_row)
                        if ec3.button("🗑️", key=f"del_{edit_row['id']}"):
                            conn.table("job_planning").delete().eq("id", edit_row['id']).execute()
                            st.cache_data.clear(); st.rerun()

# --- TAB 2: DAILY ENTRY (INTEGRATED MULTIPLE WORKERS) ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="ent_job")
    
    if f_job != "-- Select --":
        active_gates_df = df_job_plans[df_job_plans['job_no'] == f_job]
        active_list = active_gates_df[active_gates_df['current_status'] == 'Active']
        
        if active_list.empty:
            st.warning("⚠️ No 'Active' gates. Start a gate in Scheduling first.")
        else:
            with st.form("prod_form", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                gate_options = {f"{r['gate_name']} ({r['sub_task']})": r for _, r in active_list.iterrows()}
                f_gate_label = f1.selectbox("Process", list(gate_options.keys()))
                
                # INTEGRATED: MULTIPLE WORKER SELECTION
                f_wrk_list = f1.multiselect("Workers Involved", all_workers)
                
                f_hrs = f2.number_input("Hrs (Per Person)", min_value=0.0, step=0.5)
                f_unit = f2.selectbox("Unit", ["Nos", "Mtrs", "Sq.Ft", "Kgs", "Joints"])
                f_out = f3.number_input("Qty Produced", min_value=0.0, step=0.1)
                f_notes = st.text_input("Remarks / Notes")
                
                if st.form_submit_button("🚀 Log Progress"):
                    if not f_wrk_list:
                        st.error("Please select at least one worker.")
                    else:
                        worker_string = ", ".join(f_wrk_list)
                        conn.table("production").insert({
                            "Job_Code": f_job, "Activity": str(f_gate_label), "Worker": worker_string,
                            "Hours": f_hrs, "Output": f_out, "Unit": f_unit, "notes": f_notes or "",
                            "created_at": datetime.now(IST).isoformat()
                        }).execute()
                        st.cache_data.clear(); st.success("Logged successfully!"); st.rerun()

    st.divider()
    if not df_logs.empty:
        log_view = df_logs[df_logs['Job_Code'] == f_job] if f_job != "-- Select --" else df_logs
        st.write("#### 📑 Recent Activity")
        # RESTORED: CORRECTION TOOLS
        with st.expander("🛠️ Correction Tools"):
            if not log_view.empty:
                last_row = log_view.iloc[0]
                if st.button("✏️ Edit Last Entry"):
                    @st.dialog("Edit Log")
                    def edit_log(item):
                        nh = st.number_input("Hrs", value=float(item['Hours']))
                        nq = st.number_input("Qty", value=float(item['Output']))
                        if st.button("Save"):
                            conn.table("production").update({"Hours": nh, "Output": nq}).eq("id", item['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    edit_log(last_row)
        
        st.dataframe(log_view[['created_at', 'Activity', 'Worker', 'Hours', 'Output', 'notes']].head(15), use_container_width=True, hide_index=True)

# --- TAB 3: RESTORED ANALYTICS ---
with tab_analytics:
    st.subheader("📊 Production Intelligence")
    if not df_logs.empty:
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce').fillna(0)
        df_logs['Output'] = pd.to_numeric(df_logs['Output'], errors='coerce').fillna(0)
        
        k1, k2, k3 = st.columns(3)
        total_hrs = df_logs['Hours'].sum()
        k1.metric("Total Man-Hours", f"{total_hrs:.1f} hrs")
        k2.metric("Total Output", f"{df_logs['Output'].sum():.0f} Units")
        k3.metric("Avg Productivity", f"{(df_logs['Output'].sum() / total_hrs if total_hrs > 0 else 0):.2f} U/Hr")
        
        st.divider()
        v1, v2 = st.columns(2)
        with v1:
            job_data = df_logs.groupby('Job_Code')['Hours'].sum().reset_index()
            st.plotly_chart(px.bar(job_data, x='Job_Code', y='Hours', title="Hours Spent per Job"), use_container_width=True)
        with v2:
            worker_data = df_logs.groupby('Worker')['Hours'].sum().reset_index()
            st.plotly_chart(px.pie(worker_data, values='Hours', names='Worker', title="Worker Contribution"), use_container_width=True)

# --- TAB 4: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ Production Master Settings")
    with st.form("new_gate"):
        mg1, mg2, mg3 = st.columns([2, 2, 1])
        ng_name = mg1.text_input("Gate Name")
        ng_sub = mg2.text_input("Sub-Task")
        ng_order = mg3.number_input("Order", value=len(df_master_gates)+1)
        if st.form_submit_button("Add to Master"):
            conn.table("production_gates").insert({"gate_name": ng_name, "sub_task": ng_sub, "step_order": ng_order}).execute()
            st.cache_data.clear(); st.rerun()
    st.dataframe(df_master_gates.sort_values('step_order'), use_container_width=True, hide_index=True)
