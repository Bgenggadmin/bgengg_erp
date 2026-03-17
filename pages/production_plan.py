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
        plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        # Increased limit to 100 so the search bar has more data to work with
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

df_projects, df_logs, df_master_gates, df_job_plans = get_master_data()

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

        with st.expander("➕ Add/Insert New Gate", expanded=False):
            with st.form("add_schedule_form", clear_on_submit=True):
                c1, c2, c3 = st.columns([2, 2, 1])
                g_name = c1.selectbox("Process Gate", all_activities)
                d_range = c2.date_input("Planned Window", [date.today(), date.today() + timedelta(days=5)])
                g_order = c3.number_input("Step No.", min_value=1, value=len(current_job_steps)+1)
                if st.form_submit_button("🚀 Add to Plan"):
                    if len(d_range) == 2:
                        conn.table("job_planning").insert({
                            "job_no": target_job, "gate_name": g_name, "step_order": g_order,
                            "planned_start_date": d_range[0].isoformat(),
                            "planned_end_date": d_range[1].isoformat(),
                            "current_status": "Pending"
                        }).execute()
                        st.cache_data.clear()
                        st.rerun()

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

    # --- RECENT LOGS WITH SEARCH ---
    st.markdown("### 🕒 Recent Entries (IST)")
    if not df_logs.empty:
        try:
            display_logs = df_logs.copy()
            # Standardizing all time formats to IST safely
            display_logs['created_at'] = pd.to_datetime(
                display_logs['created_at'], utc=True, format='ISO8601'
            ).dt.tz_convert(IST).dt.strftime('%d-%b %I:%M %p')
            
            # Simple Search Bar
            search_query = st.text_input("🔍 Search Logs (Worker, Job, or Process)", "").lower()
            
            # Filtering Logic
            if search_query:
                mask = (
                    display_logs['Worker'].str.lower().str.contains(search_query) |
                    display_logs['Job_Code'].str.lower().str.contains(search_query) |
                    display_logs['Activity'].str.lower().str.contains(search_query)
                )
                filtered_logs = display_logs[mask]
            else:
                filtered_logs = display_logs

            log_view = filtered_logs[['created_at', 'Job_Code', 'Activity', 'Worker', 'Hours', 'Output', 'Unit', 'Notes']].head(15)
            log_view.columns = ['Time (IST)', 'Job', 'Process', 'Worker', 'Hrs', 'Qty', 'Unit', 'Remarks']
            st.dataframe(log_view, use_container_width=True, hide_index=True)
            
        except Exception as e:
            st.error(f"Log Display Error: {e}")
    else:
        st.info("No logs found for today yet.")

# --- TAB 3: ANALYTICS ---
with tab_analytics:
    st.subheader("📊 Production Reports & Exports")
    
    st.markdown("#### 📅 Project Schedule Tracker")
    g_job = st.selectbox("Select Job for Schedule View", ["-- Select --"] + all_jobs, key="schedule_job_sel")
    if g_job != "-- Select --":
        job_plan = df_job_plans[df_job_plans['job_no'] == g_job].copy()
        if not job_plan.empty:
            date_cols = ['planned_start_date', 'planned_end_date', 'actual_start_date', 'actual_end_date']
            for col in date_cols:
                job_plan[col] = pd.to_datetime(job_plan[col], errors='coerce').dt.strftime('%d-%b-%Y')
            
            schedule_view = job_plan[['step_order', 'gate_name', 'planned_start_date', 'planned_end_date', 'actual_start_date', 'actual_end_date', 'current_status']].sort_values('step_order')
            st.dataframe(schedule_view, use_container_width=True, hide_index=True)

    st.divider()
    with st.container(border=True):
        f1, f2, f3 = st.columns([2, 2, 2])
        today = date.today()
        d_range = f1.date_input("Select Period", [today - timedelta(days=7), today])
        f_jobs = f2.multiselect("Filter Jobs", all_jobs, default=all_jobs)
        f_staff = f3.multiselect("Filter Workers", all_workers, default=all_workers)

    if not df_logs.empty and len(d_range) == 2:
        try:
            df_logs['created_at_dt'] = pd.to_datetime(
                df_logs['created_at'], utc=True, format='ISO8601'
            ).dt.tz_convert(IST)
            
            clean_logs = df_logs.dropna(subset=['created_at_dt']).copy()
            clean_logs['date_only'] = clean_logs['created_at_dt'].dt.date
            
            mask = ((clean_logs['date_only'] >= d_range[0]) & (clean_logs['date_only'] <= d_range[1]) &
                    (clean_logs['Job_Code'].isin(f_jobs)) & (clean_logs['Worker'].isin(f_staff)))
            report_df = clean_logs.loc[mask].copy()

            if not report_df.empty:
                st.markdown("#### 🏗️ Effort Summary")
                c_left, c_right = st.columns(2)
                c_left.dataframe(report_df.groupby(['Job_Code', 'Activity'])['Hours'].sum().unstack(fill_value=0), use_container_width=True)
                c_right.dataframe(report_df.groupby(['Worker', 'Job_Code'])['Hours'].sum().reset_index(), use_container_width=True)
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
        st.markdown("### 📋 Existing Master Gates")
        if not df_master_gates.empty:
            for _, m_row in df_master_gates.sort_values('step_order').iterrows():
                with st.container(border=True):
                    mc1, mc2 = st.columns([4, 1])
                    mc1.write(f"**{m_row['step_order']}. {m_row['gate_name']}**")
                    if mc2.button("🗑️", key=f"del_m_{m_row['id']}"):
                        conn.table("production_gates").delete().eq("id", m_row['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
