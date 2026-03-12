import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G ERP | Founder Dashboard", layout="wide", page_icon="🏗️")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. THE MASTER ACTIVITY PLAN (DEPENDENCY LOGIC) ---
PLANNING_RECIPE = {
    "1. Engineering & MTC": {"dur": 7, "deps": [0]},
    "2. Shell Fabrication": {"dur": 15, "deps": [1]},
    "3. Jacket/Limpet Fitting": {"dur": 10, "deps": [2]},
    "4. DRIVE ASSEMBLY (Parallel)": {"dur": 12, "deps": [1]},
    "5. MAIN ASSEMBLY": {"dur": 7, "deps": [3, 4]},
    "6. Hydro-test": {"dur": 4, "deps": [5]},
    "7. Dispatch": {"dur": 2, "deps": [6]}
}

@st.cache_data(ttl=2)
def get_all_data():
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    df_projects = pd.DataFrame(p.data or [])
    df_logs = pd.DataFrame(l.data or [])
    
    # Crucial Fix: Ensure 'created_at' is datetime and timezone-naive for comparison
    if not df_projects.empty:
        df_projects['created_at'] = pd.to_datetime(df_projects['created_at']).dt.tz_localize(None)
    if not df_logs.empty:
        df_logs['created_at'] = pd.to_datetime(df_logs['created_at']).dt.tz_localize(None)
        
    return df_projects, df_logs

df_p, df_l = get_all_data()

# --- 3. LOGIC: MERGING PLAN VS ACTUAL (FIXED COMPARISON) ---
def get_plan_vs_actual(df_jobs, df_logs):
    rows = []
    now_naive = datetime.now().replace(microsecond=0) # Naive comparison time
    
    for _, job in df_jobs.iterrows():
        start_date = job['created_at']
        finish_map = {0: start_date}
        
        for i, (name, val) in enumerate(PLANNING_RECIPE.items(), 1):
            # CALCULATE PLAN
            p_start = max([finish_map[d] for d in val['deps']])
            p_end = p_start + timedelta(days=val['dur'])
            finish_map[i] = p_end
            
            # CALCULATE ACTUAL (From Logs)
            act_hrs = 0
            if not df_logs.empty:
                job_act_logs = df_logs[(df_logs['Job_Code'] == str(job['job_no'])) & (df_logs['Activity'] == name)]
                act_hrs = job_act_logs['Hours'].sum()
            
            act_status = "In Progress" if act_hrs > 0 else "Pending"
            
            # FIXED COMPARISON LOGIC
            is_delayed = (now_naive > p_end) and (act_status == "Pending")

            rows.append({
                "Job": job['job_no'],
                "Activity": name,
                "Planned Finish": p_end.strftime('%d-%b'),
                "Actual Hrs": act_hrs,
                "Status": "🔴 DELAYED" if is_delayed else "🟢 On Track" if act_hrs > 0 else "⚪ Waiting",
            })
    return pd.DataFrame(rows)

# --- 4. DASHBOARD TABS ---
tab_founder, tab_planning, tab_entry = st.tabs(["📈 Founder Dashboard", "🗓️ Activity Plan", "👷 Shop Entry"])

with tab_founder:
    st.subheader("Founder Control Tower")
    if not df_p.empty:
        df_analysis = get_plan_vs_actual(df_p, df_l)
        
        # Delay Summary
        delayed_df = df_analysis[df_analysis['Status'] == "🔴 DELAYED"]
        if not delayed_df.empty:
            st.error(f"🚨 {len(delayed_df)} Activities are behind schedule!")
            st.dataframe(delayed_df, use_container_width=True)
        else:
            st.success("✅ All active jobs are within planned timelines.")

        # Analytics Charts
        c1, c2 = st.columns(2)
        if not df_l.empty:
            with c1:
                fig_pie = px.pie(df_l, values='Hours', names='Activity', title="Man-Hour Distribution", hole=0.4)
                st.plotly_chart(fig_pie, use_container_width=True)
            with c2:
                fig_bar = px.bar(df_l.groupby('Worker')['Hours'].sum().reset_index(), x='Worker', y='Hours', title="Worker Workload (Total Hrs)")
                st.plotly_chart(fig_bar, use_container_width=True)

with tab_planning:
    st.subheader("Parallel Project Gantt")
    if not df_p.empty:
        # Generate data for Timeline
        gantt_list = []
        for _, job in df_p.iterrows():
            start = job['created_at']
            f_map = {0: start}
            for i, (name, val) in enumerate(PLANNING_RECIPE.items(), 1):
                ts = max([f_map[d] for d in val['deps']])
                te = ts + timedelta(days=val['dur'])
                f_map[i] = te
                gantt_list.append({"Job": job['job_no'], "Task": name, "Start": ts, "Finish": te, "Type": "Parallel" if "Parallel" in name else "Standard"})
        
        df_g = pd.DataFrame(gantt_list)
        fig_g = px.timeline(df_g, x_start="Start", x_end="Finish", y="Job", color="Task", title="Automatic Schedule")
        fig_g.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_g, use_container_width=True)

with tab_entry:
    st.subheader("New Productivity Log")
    with st.form("entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        sel_job = col1.selectbox("Select Job Code", df_p['job_no'].unique() if not df_p.empty else [])
        sel_act = col1.selectbox("Select Activity", list(PLANNING_RECIPE.keys()))
        sel_wrk = col2.selectbox("Worker Name", sorted(df_l['Worker'].unique()) if not df_l.empty else ["Add in Master"])
        in_hrs = col2.number_input("Hours Spent", min_value=0.0, step=0.5)
        in_out = col2.number_input("Output (Mts/Nos)", min_value=0.0)
        
        if st.form_submit_button("Submit Work Log"):
            conn.table("production").insert({
                "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                "Job_Code": str(sel_job), "Activity": sel_act, "Worker": sel_wrk,
                "Hours": in_hrs, "Output": in_out, "Notes": "Verified Entry"
            }).execute()
            st.success("Log Saved Successfully!")
            st.rerun()
