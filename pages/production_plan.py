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
# This ensures that even if you refresh this specific page, the dropdowns don't break.
if 'master_data' not in st.session_state or not st.session_state.master_data:
    try:
        # Fetching directly from Master tables to populate session state
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

# Access the recovered data
master = st.session_state.get('master_data', {})

# --- 3. DATA LOADERS (Cached) ---
@st.cache_data(ttl=2)
def get_master_data():
    try:
        plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        # Note: we use production_gates for the master gate list
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

# --- 4. DYNAMIC MAPPING (STRICT MODE) ---
# 1. Pull approved lists strictly from Master Data
all_staff = master.get('staff', [])
master_workers = master.get('workers', [])

# 2. Final Clean List for Dropdowns
# This ensures ONLY names in Master Setup appear. 
# Names present in old logs but NOT in Master Setup are excluded.
all_workers = sorted(list(set(master_workers))) 

# 3. Pull Job Numbers
all_jobs = sorted(df_projects['job_no'].astype(str).unique().tolist()) if not df_projects.empty else []

# 4. Pull Gate Names (Activities)
all_activities = master.get('gates', ["Cutting", "Fitting", "Welding", "Grinding", "Painting", "Assembly"])

# --- 4. NAVIGATION ---
tab_plan, tab_entry, tab_analytics, tab_master = st.tabs([
    "🏗️ Scheduling & Execution", 
    "👷 Daily Entry", 
    "📊 Analytics & Gantt",
    "⚙️ Master Settings"
])

# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
        # Load planning data specifically for the selected job
        current_job_steps = df_job_plans[df_job_plans['job_no'] == target_job] if not df_job_plans.empty else pd.DataFrame()

        # --- 0. CLONE TEMPLATE FEATURE ---
        if current_job_steps.empty:
            with st.container(border=True):
                st.markdown("### 👯 No Plan Detected")
                st.write("Would you like to clone a sequence from a similar job (e.g., another Tank or Dryer)?")
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

        # --- 1. EDD & STATUS HEADER ---
        if not current_job_steps.empty:
            valid_dates = pd.to_datetime(current_job_steps['planned_end_date'], errors='coerce').dropna()
            if not valid_dates.empty:
                edd = valid_dates.max().date()
                days_left = (edd - date.today()).days
                st.info(f"📅 **Projected Completion (EDD): {edd.strftime('%d %b %Y')}** ({days_left} days remaining)")

        # --- 2. FLEXIBLE SCHEDULING (ADD GATES) ---
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

        # --- 3. SEQUENCE MANAGEMENT (EDIT/DELETE) ---
        if not current_job_steps.empty:
            with st.expander("📝 Manage Sequence & Dates", expanded=False):
                for _, edit_row in current_job_steps.sort_values('step_order').iterrows():
                    e_id = edit_row['id']
                    with st.container(border=True):
                        ec1, ec2, ec3, ec4 = st.columns([2, 2, 1, 1])
                        gate_idx = all_activities.index(edit_row['gate_name']) if edit_row['gate_name'] in all_activities else 0
                        u_gate = ec1.selectbox("Gate", all_activities, index=gate_idx, key=f"e_name_{e_id}")
                        
                        st_dt = pd.to_datetime(edit_row['planned_start_date']).date() if not pd.isna(edit_row['planned_start_date']) else date.today()
                        en_dt = pd.to_datetime(edit_row['planned_end_date']).date() if not pd.isna(edit_row['planned_end_date']) else date.today()
                        u_dates = ec2.date_input("Dates", [st_dt, en_dt], key=f"e_date_{e_id}")
                        u_order = ec3.number_input("Order", value=int(edit_row['step_order']), key=f"e_order_{e_id}")
                        
                        with ec4:
                            if st.button("💾", key=f"save_{e_id}"):
                                if len(u_dates) == 2:
                                    conn.table("job_planning").update({
                                        "gate_name": u_gate, "planned_start_date": u_dates[0].isoformat(),
                                        "planned_end_date": u_dates[1].isoformat(), "step_order": u_order
                                    }).eq("id", e_id).execute()
                                    st.cache_data.clear()
                                    st.rerun()
                            if st.button("🗑️", key=f"del_{e_id}"):
                                conn.table("job_planning").delete().eq("id", e_id).execute()
                                st.cache_data.clear()
                                st.rerun()

        st.divider()

        # --- 4. SHOP FLOOR EXECUTION ---
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
                            conn.table("job_planning").update({
                                "current_status": "Active", 
                                "actual_start_date": datetime.now(IST).isoformat()
                            }).eq("id", row['id']).execute()
                            st.cache_data.clear()
                            st.rerun()
                            
                    elif status == "Active":
                        col2.info("🚀 Active")
                        delay = (date.today() - p_end).days if date.today() > p_end else 0
                        if delay > 0:
                            col3.metric("Delay", f"{delay} Days", delta_color="inverse")
                        else:
                            col3.success("On Track")
                        if col4.button("✅ Close", key=f"end_btn_{row['id']}", use_container_width=True):
                            conn.table("job_planning").update({
                                "current_status": "Completed", 
                                "actual_end_date": datetime.now(IST).isoformat()
                            }).eq("id", row['id']).execute()
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
            # Filter the already loaded df_job_plans for speed
            active_gates = df_job_plans[
                (df_job_plans['job_no'] == f_job) & 
                (df_job_plans['current_status'] == 'Active')
            ]['gate_name'].tolist()
            
            if active_gates:
                f_act = st.selectbox("🎯 Current Active Gate", active_gates)
                
                with st.form("prod_form", clear_on_submit=True):
                    f1, f2, f3 = st.columns(3)
                    
                    # Column 1: Who
                    # Inside tab_entry form:
                    f_sup = f1.selectbox("Supervisor", ["-- Select --"] + all_staff) # Pulls from master_staff
                    f_wrk = f1.selectbox("Worker/Engineer", ["-- Select --"] + all_workers) # Pulls from master_workers
                    
                    # Column 2: Time
                    f_hrs = f2.number_input("Time Spent (Hrs)", min_value=0.0, max_value=24.0, step=0.5, help="Enter decimal hours, e.g., 1.5 for 1hr 30m")
                    
                    # Column 3: Output Logic (The Change)
                    f_out_val = f3.number_input("Output Quantity", min_value=0.0, step=0.1)
                    f_unit = f3.selectbox("Unit of Measure", ["Nos", "Mtrs", "Sq.Ft", "Kgs", "Inches", "Joints"])
                    
                    f_nts = st.text_area("Work Details / Remarks")

                    if st.form_submit_button("🚀 Log Progress"):
                        if f_wrk == "-- Select --":
                            st.error("Please select a Worker.")
                        else:
                            try:
                                # We combine output and unit for clear database records
                                # Or if your 'production' table has a 'Unit' column, use that!
                                conn.table("production").insert({
                                    "Supervisor": f_sup, 
                                    "Worker": f_wrk, 
                                    "Job_Code": f_job,
                                    "Activity": f_act, 
                                    "Hours": f_hrs, 
                                    "Output": f_out_val,
                                    "Unit": f_unit, # Ensure this column exists in Supabase!
                                    "Notes": f_nts, 
                                    "created_at": datetime.now(IST).isoformat()
                                }).execute()
                                
                                st.cache_data.clear()
                                st.success(f"Logged: {f_out_val} {f_unit} in {f_hrs} hrs for {f_wrk}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}. Check if 'Unit' column exists in your Supabase table.")
            else:
                st.warning(f"⚠️ No gates are 'Active' for {f_job}. Start a gate in the Planning tab.")

# --- TAB 3: ANALYTICS & GANTT (FIXED SECTION) ---
with tab_analytics:
    st.subheader("📊 Production Reports & Exports")
    
    # --- 1. FILTERS ---
    with st.container(border=True):
        f1, f2, f3 = st.columns([2, 2, 2])
        
        # Date Range Selection
        today = date.today()
        d_range = f1.date_input("Select Period (Weekly/Monthly)", [today - timedelta(days=7), today])
        
        # Multi-select for Jobs and Workers
        f_jobs = f2.multiselect("Filter Jobs", all_jobs, default=all_jobs)
        f_staff = f3.multiselect("Filter Workers", all_workers, default=all_workers)

   # --- 2. GANTT CHART SECTION (RE-FIXED) ---
st.divider()
st.markdown("#### 📅 Project Timeline (Planned vs Actual)")
g_job = st.selectbox("Select Job for Timeline View", ["-- Select --"] + all_jobs, key="gantt_job_sel")

if g_job != "-- Select --":
    job_plan = df_job_plans[df_job_plans['job_no'] == g_job].copy()
    
    if not job_plan.empty:
        gantt_data = []
        for _, row in job_plan.iterrows():
            # Robust conversion: errors='coerce' turns invalid dates into NaT
            p_start = pd.to_datetime(row['planned_start_date'], errors='coerce')
            p_end = pd.to_datetime(row['planned_end_date'], errors='coerce')
            a_start = pd.to_datetime(row['actual_start_date'], errors='coerce')
            a_end = pd.to_datetime(row['actual_end_date'], errors='coerce')

            # 1. Add Planned Bar (Only if both dates are valid)
            if pd.notnull(p_start) and pd.notnull(p_end):
                gantt_data.append({
                    "Task": f"{row['step_order']}. {row['gate_name']}",
                    "Start": p_start,
                    "Finish": p_end,
                    "Type": "Planned",
                    "Status": row.get('current_status', 'N/A')
                })
            
            # 2. Add Actual Bar (Only if it has at least a start date)
            if pd.notnull(a_start):
                # If finished, use actual end. If still active, use current time.
                finish_val = a_end if pd.notnull(a_end) else pd.Timestamp.now(tz=IST)
                
                # Ensure finish is always after start to avoid Plotly geometry errors
                if finish_val < a_start:
                    finish_val = a_start + pd.Timedelta(hours=1)

                gantt_data.append({
                    "Task": f"{row['step_order']}. {row['gate_name']}",
                    "Start": a_start,
                    "Finish": finish_val,
                    "Type": "Actual",
                    "Status": row.get('current_status', 'N/A')
                })

        if gantt_data:
            df_gantt = pd.DataFrame(gantt_data)
            
            # FINAL SAFETY CHECK: Ensure no NaT values reached px.timeline
            df_gantt = df_gantt.dropna(subset=['Start', 'Finish'])
            
            fig_gantt = px.timeline(
                df_gantt, 
                x_start="Start", 
                x_end="Finish", 
                y="Task", 
                color="Type",
                hover_data=["Status"],
                # Standard blue/gray for Planned, Green for Actual
                color_discrete_map={"Planned": "#BDC3C7", "Actual": "#2ECC71"}
            )
            fig_gantt.update_yaxes(autorange="reversed") 
            st.plotly_chart(fig_gantt, use_container_width=True)
        else:
            st.info("No valid dates found to display the Gantt chart.")

    # --- 3. DATA PROCESSING (With ValueError Protection) ---
    st.divider()
    if not df_logs.empty and len(d_range) == 2:
        try:
            # ROBUST DATE CONVERSION: 
            # errors='coerce' turns bad dates into NaT (Not a Time) instead of crashing
            df_logs['created_at_dt'] = pd.to_datetime(df_logs['created_at'], errors='coerce')
            
            # Drop rows where dates are broken to prevent the ValueError you saw
            clean_logs = df_logs.dropna(subset=['created_at_dt']).copy()
            clean_logs['date_only'] = clean_logs['created_at_dt'].dt.date
            
            # Filter logic using your mask
            mask = (
                (clean_logs['date_only'] >= d_range[0]) & 
                (clean_logs['date_only'] <= d_range[1]) &
                (clean_logs['Job_Code'].isin(f_jobs)) &
                (clean_logs['Worker'].isin(f_staff))
            )
            report_df = clean_logs.loc[mask].copy()

            if not report_df.empty:
                # --- 3. DUAL VIEW SUMMARIES ---
                col_left, col_right = st.columns(2)

                with col_left:
                    st.markdown("#### 🏗️ Job-Wise Effort")
                    job_summary = report_df.groupby(['Job_Code', 'Activity'])['Hours'].sum().unstack(fill_value=0)
                    st.dataframe(job_summary, use_container_width=True)

                with col_right:
                    st.markdown("#### 👷 Worker-Wise Effort")
                    worker_summary = report_df.groupby(['Worker', 'Job_Code'])['Hours'].sum().reset_index()
                    st.dataframe(worker_summary, use_container_width=True)

                # --- 4. THE EXPORT BUTTONS ---
                st.markdown("### 📥 Download CSV Reports")
                d1, d2, d3 = st.columns(3)

                # Your custom CSV logic preserved
                def to_csv(df):
                    return df.to_csv(index=True if isinstance(df, pd.DataFrame) and not df.index.name is None else False).encode('utf-8')

                d1.download_button(
                    "📄 Full Detailed Log (Includes Notes)", 
                    data=to_csv(report_df), 
                    file_name=f"Detailed_Logs_{d_range[0]}_to_{d_range[1]}.csv",
                    use_container_width=True
                )
                
                d2.download_button(
                    "🏗️ Job Matrix Export", 
                    data=to_csv(job_summary), 
                    file_name=f"Job_Effort_Matrix_{today}.csv",
                    use_container_width=True
                )

                d3.download_button(
                    "👷 Worker Job-Split Export", 
                    data=to_csv(worker_summary), 
                    file_name=f"Worker_Job_Distribution_{today}.csv",
                    use_container_width=True
                )
            else:
                st.warning("No data found for the selected filters.")
                
        except Exception as e:
            st.error(f"Analytics Error: {e}")
    else:
        st.info("Please select a full date range (Start and End date) to see the reports.")

# --- TAB 4: MASTER SETTINGS (Robust Version) ---
with tab_master:
    st.subheader("⚙️ Shop Floor Gate Master")
    col_m1, col_m2 = st.columns([1, 2])
    
    with col_m1:
        st.markdown("### ➕ Add New Gate")
        with st.form("master_gate_form", clear_on_submit=True):
            new_g_name = st.text_input("Gate Name (e.g., Shot Blasting)").strip()
            new_g_order = st.number_input("Standard Sequence", min_value=1, value=len(df_master_gates)+1)
            
            if st.form_submit_button("🔨 Add to Master"):
                if new_g_name:
                    # Check if gate already exists in the dataframe to avoid API Error
                    if not df_master_gates.empty and new_g_name.lower() in df_master_gates['gate_name'].str.lower().values:
                        st.error(f"Gate '{new_g_name}' already exists!")
                    else:
                        try:
                            # Attempt Insert
                            conn.table("production_gates").insert({
                                "gate_name": new_g_name, 
                                "step_order": new_g_order
                            }).execute()
                            st.cache_data.clear()
                            st.success(f"Added {new_g_name}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Database Error: {e}")
                else:
                    st.warning("Please enter a gate name.")

    with col_m2:
        st.markdown("### 📋 Existing Master Gates")
        if not df_master_gates.empty:
            # Sort by step order for clarity
            for _, m_row in df_master_gates.sort_values('step_order').iterrows():
                with st.container(border=True):
                    mc1, mc2 = st.columns([4, 1])
                    mc1.write(f"**{m_row['step_order']}. {m_row['gate_name']}**")
                    # Delete logic
                    if mc2.button("🗑️", key=f"del_m_{m_row['id']}"):
                        try:
                            conn.table("production_gates").delete().eq("id", m_row['id']).execute()
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error("Cannot delete: This gate might be in use in active schedules.")
        else:
            st.info("No master gates defined. Add your first gate (e.g., 'Cutting') to start.")
