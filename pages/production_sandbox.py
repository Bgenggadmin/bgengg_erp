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
        g_res = conn.table("production_gates").select("gate_name").order("step_order").execute()
        
        st.session_state.master_data = {
            "workers": [w['name'] for w in (w_res.data or [])],
            "staff": [s['name'] for s in (s_res.data or [])],
            "gates": [g['gate_name'] for g in (g_res.data or [])]
        }
    except Exception as e:
        st.error(f"Master Sync Error: {e}")

master = st.session_state.get('master_data', {})

# --- 3. DATA LOADERS (Cached) ---
@st.cache_data(ttl=2)
def get_master_data():
    try:
        plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        gate_master_res = conn.table("production_gates").select("*").order("step_order").execute()
        job_plan_res = conn.table("job_planning").select("*").order("step_order").execute()
        
        return (pd.DataFrame(plan_res.data or []), 
                pd.DataFrame(prod_res.data or []), 
                pd.DataFrame(gate_master_res.data or []),
                pd.DataFrame(job_plan_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_projects, df_logs, df_master_gates, df_job_plans = get_master_data()

# --- 4. DYNAMIC MAPPING ---
all_staff = master.get('staff', [])
all_workers = sorted(list(set(master.get('workers', []))))
all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []
all_activities = master.get('gates', [])

# --- 5. NAVIGATION ---
tab_plan, tab_entry, tab_analytics, tab_master = st.tabs([
    "🏗️ Scheduling & Execution", 
    "👷 Daily Entry", 
    "📊 Analytics & Reports",
    "⚙️ Master Settings"
])

# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
        # A. DELIVERY DASHBOARD (IMAGE 2 LAYOUT)
        proj_match = df_projects[df_projects['job_no'] == target_job]
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                po_dt = pd.to_datetime(p_data.get('po_delivery_date')).date() if pd.notnull(p_data.get('po_delivery_date')) else None
                rev_dt = pd.to_datetime(p_data.get('revised_delivery_date')).date() if pd.notnull(p_data.get('revised_delivery_date')) else None
                
                c1.write(f"**PO Delivery Date**\n{po_dt.strftime('%d-%b-%Y') if po_dt else 'Not Set'}")
                c2.write(f"🔴 **Revised Date**\n{rev_dt.strftime('%d-%b-%Y') if rev_dt else 'None'}")
                
                final_target = rev_dt if rev_dt else po_dt
                if final_target:
                    days_left = (final_target - date.today()).days
                    c3.metric("Days to Dispatch", f"{days_left} Days", delta=days_left, delta_color="normal" if days_left > 7 else "inverse")
                
                if c4.button("📝 Edit", key="edit_delivery"):
                    @st.dialog("Update Schedule")
                    def update_dates():
                        n_po = st.date_input("PO Date", value=po_dt if po_dt else date.today())
                        n_rev = st.date_input("Revised Date", value=rev_dt if rev_dt else n_po)
                        if st.button("Save Changes"):
                            conn.table("anchor_projects").update({"po_delivery_date": str(n_po), "revised_delivery_date": str(n_rev)}).eq("job_no", target_job).execute()
                            st.cache_data.clear(); st.rerun()
                    update_dates()

        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()

        # B. CLONE LOGIC
        if current_job_steps.empty:
            st.warning("⚠️ No Plan Detected")
            src_job = st.selectbox("Clone from Job Template:", ["-- Select --"] + all_jobs, key="clone_src")
            if st.button("🚀 Clone Sequence") and src_job != "-- Select --":
                source_steps = df_job_plans[df_job_plans['job_no'] == src_job]
                if not source_steps.empty:
                    new_steps = [{"job_no": target_job, "gate_name": s['gate_name'], "step_order": s['step_order'], "planned_start_date": date.today().isoformat(), "planned_end_date": (date.today()+timedelta(days=5)).isoformat(), "current_status": "Pending"} for _, s in source_steps.iterrows()]
                    conn.table("job_planning").insert(new_steps).execute()
                    st.cache_data.clear(); st.rerun()

        # C. EXECUTION FLOW WITH STRICT DELAY LOGIC
        if not current_job_steps.empty:
            valid_dates = pd.to_datetime(current_job_steps['planned_end_date'], errors='coerce').dropna()
            if not valid_dates.empty:
                edd = valid_dates.max().date()
                st.info(f"📅 **Projected Completion (EDD): {edd.strftime('%d %b %Y')}**")

            st.divider()
            st.subheader(f"🏁 Execution: {target_job}")
            for _, row in current_job_steps.sort_values('step_order').iterrows():
                p_end = pd.to_datetime(row['planned_end_date']).date() if pd.notnull(row['planned_end_date']) else None
                today = date.today()

                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                    col1.markdown(f"**Step {row['step_order']}: {row['gate_name']}**")
                    
                    if row['current_status'] == "Pending":
                        col2.warning("⏳ Pending")
                        if col4.button("▶️ Start", key=f"st_{row['id']}"):
                            conn.table("job_planning").update({"current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                            
                    elif row['current_status'] == "Active":
                        col2.info("🚀 Active")
                        if p_end:
                            diff = (today - p_end).days
                            if diff > 0:
                                col3.metric("Delay", f"{diff} Days", delta=f"-{diff}", delta_color="inverse")
                            else:
                                col3.success("On Track")
                        
                        if col4.button("✅ Close", key=f"cl_{row['id']}"):
                            conn.table("job_planning").update({"current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    else:
                        col2.success("🏁 Completed")

# --- TAB 2: DAILY WORK ENTRY (SYNCED FROM SANDBOX) ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    with st.container(border=True):
        f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="entry_job_sel")
        if f_job != "-- Select --":
            active_gates = df_job_plans[(df_job_plans['job_no'] == f_job) & (df_job_plans['current_status'] == 'Active')]['gate_name'].tolist()
            if active_gates:
                f_act = st.selectbox("🎯 Current Active Gate", active_gates)
                with st.form("prod_form", clear_on_submit=True):
                    f1, f2, f3 = st.columns(3)
                    f_sup = f1.selectbox("Supervisor", ["-- Select --"] + all_staff)
                    f_wrk = f1.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
                    f_hrs = f2.number_input("Time Spent (Hrs)", min_value=0.0, max_value=24.0, step=0.5)
                    f_out_val = f3.number_input("Output Quantity", min_value=0.0, step=0.1)
                    f_unit = f3.selectbox("Unit of Measure", ["Nos", "Mtrs", "Sq.Ft", "Kgs", "Inches", "Joints"])
                    f_nts = st.text_area("Work Details / Remarks")
                    
                    if st.form_submit_button("🚀 Log Progress"):
                        if f_wrk == "-- Select --":
                            st.error("Please select a Worker.")
                        else:
                            try:
                                conn.table("production").insert({
                                    "Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job,
                                    "Activity": f_act, "Hours": f_hrs, "Output": f_out_val,
                                    "Unit": f_unit, "Notes": f_nts, "created_at": datetime.now(IST).isoformat()
                                }).execute()
                                st.cache_data.clear(); st.success(f"Logged: {f_out_val} {f_unit}"); st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.warning("⚠️ No active gates for this job.")

    st.divider()
    st.markdown("### 🕒 Recent Entries (IST)")
          # --- RECENT LOGS SECTION (CRASH PROOF) ---
    if not df_logs.empty:
        try:
            display_logs = df_logs.copy()
        
        # 1. Convert safely (errors='coerce' prevents the crash)
        display_logs['created_at_dt'] = pd.to_datetime(display_logs['created_at'], utc=True, errors='coerce')
        
        # 2. Drop rows that failed to parse so they don't break tz_convert
        display_logs = display_logs.dropna(subset=['created_at_dt'])
        
        # 3. Now safely convert to IST and Format
        display_logs['Time (IST)'] = display_logs['created_at_dt'].dt.tz_convert(IST).dt.strftime('%d-%b %I:%M %p')
        
        # ... [Rest of your correction tools and dataframe code]
        display_logs = df_logs.copy()
        display_logs['Time (IST)'] = pd.to_datetime(display_logs['created_at'], utc=True).dt.tz_convert(IST).dt.strftime('%d-%b %I:%M %p')
        
        with st.expander("🛠️ Correction Tools (Edit/Delete Last Entry)"):
            last_row = display_logs.iloc[0]
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.info(f"Last Log: {last_row['Worker']} ({last_row['Hours']} hrs)")
            if c2.button("✏️ Edit Last Entry"):
                @st.dialog("Edit Last Log")
                def edit_dialog(item):
                    new_h = st.number_input("Hours", value=float(item['Hours']), step=0.5)
                    new_q = st.number_input("Qty", value=float(item['Output']), step=0.1)
                    if st.button("Save Changes"):
                        conn.table("production").update({"Hours": new_h, "Output": new_q}).eq("id", item['id']).execute()
                        st.cache_data.clear(); st.rerun()
                edit_dialog(last_row)
            if c3.button("🗑️ Delete Last", type="primary"):
                conn.table("production").delete().eq("id", last_row['id']).execute()
                st.cache_data.clear(); st.rerun()

        st.dataframe(display_logs[['Time (IST)', 'Job_Code', 'Activity', 'Worker', 'Hours', 'Output', 'Unit']].head(20), use_container_width=True, hide_index=True)

# --- TAB 3: ANALYTICS (SYNCED FROM SANDBOX) ---
with tab_analytics:
    st.subheader("📊 Production Intelligence")
    if not df_logs.empty:
       df_logs['created_at_dt'] = pd.to_datetime(df_logs['created_at'], utc=True, errors='coerce')
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce').fillna(0)
        clean_logs = df_logs.dropna(subset=['created_at_dt']).copy()
        clean_logs['date_only'] = clean_logs['created_at_dt'].dt.date
        
        with st.container(border=True):
            f1, f2, f3 = st.columns(3)
            today = date.today()
            period = f1.selectbox("Quick Period", ["Last 7 Days", "Current Month", "Custom Range"])
            if period == "Last 7 Days": d_range = [today - timedelta(days=7), today]
            elif period == "Current Month": d_range = [today.replace(day=1), today]
            else: d_range = f1.date_input("Select Range", [today - timedelta(days=30), today])
            
            f_jobs = f2.multiselect("Filter Jobs", all_jobs, default=all_jobs)
            f_staff_sel = f3.multiselect("Filter Workers", all_workers, default=all_workers)

        if len(d_range) == 2:
            mask = (clean_logs['date_only'] >= d_range[0]) & (clean_logs['date_only'] <= d_range[1]) & (clean_logs['Job_Code'].isin(f_jobs)) & (clean_logs['Worker'].isin(f_staff_sel))
            report_df = clean_logs.loc[mask].copy()
            if not report_df.empty:
                m1, m2, m3 = st.columns(3)
                m1.metric("Total Man-Hours", f"{report_df['Hours'].sum():.1f}")
                m2.metric("Active Workers", report_df['Worker'].nunique())
                m3.metric("Jobs in Progress", report_df['Job_Code'].nunique())
                st.bar_chart(report_df.groupby('Job_Code')['Hours'].sum())
                st.dataframe(report_df.groupby('Worker')['Hours'].sum().reset_index(), use_container_width=True, hide_index=True)
            else:
                st.warning("No data found for selected filters.")

# --- TAB 4: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ Gate Master")
    with st.form("new_gate"):
        ng_name = st.text_input("Gate Name")
        ng_order = st.number_input("Order", value=len(df_master_gates)+1)
        if st.form_submit_button("Add Gate"):
            conn.table("production_gates").insert({"gate_name": ng_name, "step_order": ng_order}).execute()
            st.cache_data.clear(); st.rerun()
    st.dataframe(df_master_gates.sort_values('step_order')[['step_order', 'gate_name']], hide_index=True)
