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
        # Pulling specific columns to ensure po_delivery_date and revised_delivery_date are included
        plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        prod_res = conn.table("production").select("*").order("created_at", desc=True).limit(100).execute()
        gate_master_res = conn.table("production_gates").select("*").order("step_order").execute()
        job_plan_res = conn.table("job_planning").select("*").order("step_order").execute()
        
        return (pd.DataFrame(plan_res.data or []), 
                pd.DataFrame(prod_res.data or []), 
                pd.DataFrame(gate_master_res.data or []),
                pd.DataFrame(job_plan_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- 4. DYNAMIC MAPPING ---
all_staff = master.get('staff', [])
master_workers = master.get('workers', [])
all_workers = sorted(list(set(master_workers))) 
all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []
all_activities = master.get('gates', ["Cutting", "Fitting", "Welding", "Grinding", "Painting", "Assembly"])

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
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()

        if current_job_steps.empty:
            with st.container(border=True):
                st.markdown("### 👯 No Plan Detected")
                st.write("Would you like to clone a sequence from a similar job?")
                source_job = st.selectbox("Select Source Template", ["-- Select --"] + all_jobs, key="src_job_clone")
                
                if st.button("🚀 Clone Sequence") and source_job != "-- Select --":
                    source_steps = df_job_plans[df_job_plans['job_no'] == source_job]
                    if not source_steps.empty:
                        new_steps = []
                        for _, s_row in source_steps.iterrows():
                            new_steps.append({
                                "job_no": target_job,
                                "gate_name": s_row['gate_name'],
                                "step_order": s_row['step_order'],
                                "planned_start_date": date.today().isoformat(),
                                "planned_end_date": (date.today() + timedelta(days=5)).isoformat(),
                                "current_status": "Pending"
                            })
                        conn.table("job_planning").insert(new_steps).execute()
                        st.cache_data.clear()
                        st.success(f"Successfully copied {len(new_steps)} steps!")
                        st.rerun()

        if not current_job_steps.empty:
            valid_dates = pd.to_datetime(current_job_steps['planned_end_date'], errors='coerce').dropna()
            if not valid_dates.empty:
                edd = valid_dates.max().date()
                days_left = (edd - date.today()).days
                st.info(f"📅 **Projected Completion (EDD): {edd.strftime('%d %b %Y')}** ({days_left} days remaining)")

        st.divider()

        if not current_job_steps.empty:
            st.subheader(f"🏁 Active Execution: {target_job}")
            for index, row in current_job_steps.sort_values('step_order').iterrows():
                status = row['current_status']
                p_end = pd.to_datetime(row['planned_end_date']).date() if row['planned_end_date'] else date.today()
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                    col1.markdown(f"**Step {row['step_order']}: {row['gate_name']}**")
                    if status == "Pending":
                        col2.warning("⏳ Pending")
                        if col4.button("▶️ Start", key=f"start_btn_{row['id']}", use_container_width=True):
                            conn.table("job_planning").update({"current_status": "Active", "actual_start_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear()
                            st.rerun()
                    elif status == "Active":
                        col2.info("🚀 Active")
                        delay = (date.today() - p_end).days if date.today() > p_end else 0
                        if delay > 0: col3.metric("Delay", f"{delay} Days", delta_color="inverse")
                        else: col3.success("On Track")
                        if col4.button("✅ Close", key=f"end_btn_{row['id']}", use_container_width=True):
                            conn.table("job_planning").update({"current_status": "Completed", "actual_end_date": datetime.now(IST).isoformat()}).eq("id", row['id']).execute()
                            st.cache_data.clear()
                            st.rerun()
                    elif status == "Completed":
                        col2.success("🏁 Completed")
                        col3.caption(f"Finished: {pd.to_datetime(row['actual_end_date']).strftime('%d %b')}")

# --- TAB 2: DAILY WORK ENTRY ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    
    # --- FORM SECTION ---
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
                                    "Unit": f_unit, "Notes": f_nts, 
                                    "created_at": datetime.now(IST).isoformat()
                                }).execute()
                                st.cache_data.clear()
                                st.success(f"Logged: {f_out_val} {f_unit}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.warning(f"⚠️ No gates are 'Active' for {f_job}. Start a gate in the Planning tab.")

    st.divider()

    # --- RECENT LOGS SECTION ---
    st.markdown("### 🕒 Recent Entries (IST)")
    if not df_logs.empty:
        try:
            display_logs = df_logs.copy()
            # Standardize time
            display_logs['Time (IST)'] = pd.to_datetime(
                display_logs['created_at'], utc=True, format='ISO8601'
            ).dt.tz_convert(IST).dt.strftime('%d-%b %I:%M %p')
            
            # --- ACTION BAR (Edit/Delete/Download) ---
            with st.expander("🛠️ Correction Tools (Edit/Delete Last Entry)"):
                last_row = display_logs.iloc[0]
                c1, c2, c3 = st.columns([2, 2, 1])
                c1.info(f"Last Log: {last_row['Worker']} ({last_row['Hours']} hrs)")
                
                # Update logic for the very last entry
                if c2.button("✏️ Edit Last Entry"):
                    # This opens a small dialog to edit
                    @st.dialog("Edit Last Log")
                    def edit_dialog(item):
                        new_h = st.number_input("Hours", value=float(item['Hours']), step=0.5)
                        new_q = st.number_input("Qty", value=float(item['Output']), step=0.1)
                        if st.button("Save Changes"):
                            conn.table("production").update({"Hours": new_h, "Output": new_q}).eq("id", item['id']).execute()
                            st.cache_data.clear()
                            st.rerun()
                    edit_dialog(last_row)

                # Delete logic for the very last entry
                if c3.button("🗑️ Delete Last", type="primary"):
                    conn.table("production").delete().eq("id", last_row['id']).execute()
                    st.cache_data.clear()
                    st.rerun()

            # --- SEARCH & DOWNLOAD ---
            search_col, dl_col = st.columns([3, 1])
            search_query = search_col.text_input("🔍 Search Worker or Job", "").lower()
            
            if search_query:
                mask = (display_logs['Worker'].str.lower().str.contains(search_query) |
                        display_logs['Job_Code'].str.lower().str.contains(search_query))
                filtered_logs = display_logs[mask]
            else:
                filtered_logs = display_logs

            # Prepare table for display
            log_view = filtered_logs[['Time (IST)', 'Job_Code', 'Activity', 'Worker', 'Hours', 'Output', 'Unit', 'Notes']].head(20)
            log_view.columns = ['Time', 'Job', 'Process', 'Worker', 'Hrs', 'Qty', 'Unit', 'Remarks']
            
            # Download Button
            csv_data = log_view.to_csv(index=False).encode('utf-8')
            dl_col.download_button("📥 Download CSV", data=csv_data, file_name="recent_logs.csv", mime='text/csv')
            
            # Table Display (The compact version you prefer)# --- TAB 2: DAILY WORK ENTRY ---
with tab_entry:
    st.subheader("👷 Labor & Output Tracking")
    
    # --- FORM SECTION ---
    with st.container(border=True):
        f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="entry_job_sel")
        if f_job != "-- Select --":
            # Correctly pulls ONLY active gates to prevent data entry errors
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
                                    "Unit": f_unit, "Notes": f_nts, 
                                    "created_at": datetime.now(IST).isoformat()
                                }).execute()
                                st.cache_data.clear()
                                st.success(f"Logged: {f_out_val} {f_unit}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.warning(f"⚠️ No gates are 'Active' for {f_job}. Start a gate in the Planning tab.")

    st.divider()

    # --- RECENT LOGS SECTION ---
    st.markdown("### 🕒 Recent Entries (IST)")
    if not df_logs.empty:
        try:
            display_logs = df_logs.copy()
            # Standardize time for display
            display_logs['Time (IST)'] = pd.to_datetime(
                display_logs['created_at'], utc=True, format='ISO8601'
            ).dt.tz_convert(IST).dt.strftime('%d-%b %I:%M %p')
            
            # --- ACTION BAR (Correction Tools) ---
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
                            st.cache_data.clear()
                            st.rerun()
                    edit_dialog(last_row)

                if c3.button("🗑️ Delete Last", type="primary"):
                    conn.table("production").delete().eq("id", last_row['id']).execute()
                    st.cache_data.clear()
                    st.rerun()

            # --- SEARCH & DOWNLOAD ---
            search_col, dl_col = st.columns([3, 1])
            search_query = search_col.text_input("🔍 Search Worker or Job", "").lower()
            
            if search_query:
                mask = (display_logs['Worker'].str.lower().str.contains(search_query) |
                        display_logs['Job_Code'].str.lower().str.contains(search_query))
                filtered_logs = display_logs[mask]
            else:
                filtered_logs = display_logs

            # Compact Table Formatting
            log_view = filtered_logs[['Time (IST)', 'Job_Code', 'Activity', 'Worker', 'Hours', 'Output', 'Unit', 'Notes']].head(20)
            log_view.columns = ['Time', 'Job', 'Process', 'Worker', 'Hrs', 'Qty', 'Unit', 'Remarks']
            
            csv_data = log_view.to_csv(index=False).encode('utf-8')
            dl_col.download_button("📥 Download CSV", data=csv_data, file_name="recent_logs.csv", mime='text/csv')
            
            st.dataframe(log_view, use_container_width=True, hide_index=True)
                        
        except Exception as e:
            st.error(f"Log Display Error: {e}")
    else:
        st.info("No logs found.")
            st.dataframe(log_view, use_container_width=True, hide_index=True)
                        
        except Exception as e:
            st.error(f"Log Display Error: {e}")
    else:
        st.info("No logs found.")

# --- TAB 3: ANALYTICS ---
with tab_analytics:
    st.subheader("📊 Production Intelligence")
    
    if not df_logs.empty:
        try:
            # Standardize time and ensure Hours is numeric
            df_logs['created_at_dt'] = pd.to_datetime(
                df_logs['created_at'], utc=True, format='ISO8601'
            ).dt.tz_convert(IST)
            df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce').fillna(0)
            
            clean_logs = df_logs.dropna(subset=['created_at_dt']).copy()
            clean_logs['date_only'] = clean_logs['created_at_dt'].dt.date
            
            # --- 1. SMART FILTERS ---
            with st.container(border=True):
                f1, f2, f3 = st.columns([2, 2, 2])
                today = date.today()
                
                period = f1.selectbox("Quick Period", ["Last 7 Days", "Current Month", "Custom Range"])
                if period == "Last 7 Days":
                    d_range = [today - timedelta(days=7), today]
                elif period == "Current Month":
                    d_range = [today.replace(day=1), today]
                else:
                    d_range = f1.date_input("Select Range", [today - timedelta(days=30), today])

                f_jobs = f2.multiselect("Filter Jobs", all_jobs, default=all_jobs)
                f_staff = f3.multiselect("Filter Workers", all_workers, default=all_workers)

            if len(d_range) == 2:
                mask = ((clean_logs['date_only'] >= d_range[0]) & (clean_logs['date_only'] <= d_range[1]) &
                        (clean_logs['Job_Code'].isin(f_jobs)) & (clean_logs['Worker'].isin(f_staff)))
                report_df = clean_logs.loc[mask].copy()

                if not report_df.empty:
                    # --- 2. KEY METRICS ---
                    total_hrs = report_df['Hours'].sum()
                    unique_workers = report_df['Worker'].nunique()
                    
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Total Man-Hours", f"{total_hrs:.1f}")
                    m2.metric("Active Workers", unique_workers)
                    m3.metric("Jobs in Progress", report_df['Job_Code'].nunique())

                    st.divider()

                    # --- 3. VISUAL CHART ---
                    st.markdown("#### 📈 Man-Hours Trend by Job")
                    job_chart_data = report_df.groupby('Job_Code')['Hours'].sum().sort_values(ascending=False)
                    st.bar_chart(job_chart_data, color="#1565C0")

                    st.divider()

                    # --- 4. WORKER & JOB ANALYTICS (CLEAN FORMAT) ---
                    col_left, col_right = st.columns(2)

                    with col_left:
                        st.markdown("#### 👷 Man-Hours by Worker")
                        worker_stats = report_df.groupby('Worker')['Hours'].sum().sort_values(ascending=False).reset_index()
                        # Formatting to 1 decimal place and cleaning display
                        worker_stats['Hours'] = worker_stats['Hours'].map('{:,.1f}'.format)
                        st.dataframe(worker_stats, use_container_width=True, hide_index=True)
                        
                    with col_right:
                        st.markdown("#### 🏗️ Man-Hours by Job")
                        job_stats = report_df.groupby('Job_Code')['Hours'].sum().sort_values(ascending=False).reset_index()
                        job_stats['Hours'] = job_stats['Hours'].map('{:,.1f}'.format)
                        st.dataframe(job_stats, use_container_width=True, hide_index=True)

                    st.divider()

                    # --- 5. DETAILED BREAKDOWN & EXPORT ---
                    st.markdown("#### 🔍 Activity Deep-Dive")
                    detailed_pivot = report_df.groupby(['Worker', 'Job_Code', 'Activity'])['Hours'].sum().reset_index()
                    detailed_pivot['Hours'] = detailed_pivot['Hours'].map('{:,.1f}'.format)
                    st.dataframe(detailed_pivot, use_container_width=True, hide_index=True)

                    # Export Feature
                    full_csv = report_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Download Detailed Report (CSV)",
                        data=full_csv,
                        file_name=f"bg_production_report_{d_range[0]}.csv",
                        mime='text/csv',
                    )
                else:
                    st.warning("No data found for the selected filters.")
        except Exception as e:
            st.error(f"Analytics Data Error: {e}")

# --- TAB 4: MASTER SETTINGS ---
with tab_master:
    st.subheader("⚙️ Shop Floor Gate Master")
    col_m1, col_m2 = st.columns([1, 2])
    with col_m1:
        st.markdown("### ➕ Add New Gate")
        with st.form("master_gate_form", clear_on_submit=True):
            new_g_name = st.text_input("Gate Name").strip()
            new_g_order = st.number_input("Sequence", min_value=1, value=len(df_master_gates)+1)
            if st.form_submit_button("🔨 Add to Master"):
                if new_g_name:
                    conn.table("production_gates").insert({"gate_name": new_g_name, "step_order": new_g_order}).execute()
                    st.cache_data.clear()
                    st.rerun()
    with col_m2:
        if not df_master_gates.empty:
            for _, m_row in df_master_gates.sort_values('step_order').iterrows():
                with st.container(border=True):
                    mc1, mc2 = st.columns([4, 1])
                    mc1.write(f"**{m_row['step_order']}. {m_row['gate_name']}**")
                    if mc2.button("🗑️", key=f"del_m_{m_row['id']}"):
                        conn.table("production_gates").delete().eq("id", m_row['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
