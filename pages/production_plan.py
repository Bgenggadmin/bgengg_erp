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
    return pd.DataFrame(p.data or []), pd.DataFrame(l.data or [])

df_p, df_l = get_all_data()

# --- 3. LOGIC: MERGING PLAN VS ACTUAL ---
def get_plan_vs_actual(df_jobs, df_logs):
    rows = []
    for _, job in df_jobs.iterrows():
        start_date = pd.to_datetime(job['created_at'])
        finish_map = {0: start_date}
        
        for i, (name, val) in enumerate(PLANNING_RECIPE.items(), 1):
            # CALCULATE PLAN
            p_start = max([finish_map[d] for d in val['deps']])
            p_end = p_start + timedelta(days=val['dur'])
            finish_map[i] = p_end
            
            # CALCULATE ACTUAL (From Logs)
            job_act_logs = df_logs[(df_logs['Job_Code'] == str(job['job_no'])) & (df_logs['Activity'] == name)]
            act_hrs = job_act_logs['Hours'].sum()
            act_status = "In Progress" if act_hrs > 0 else "Pending"
            
            # Identify Delays
            is_delayed = (datetime.now(IST).replace(tzinfo=None) > p_end) and (act_status == "Pending")

            rows.append({
                "Job": job['job_no'],
                "Activity": name,
                "Planned Finish": p_end.strftime('%d-%b'),
                "Actual Hrs Logged": act_hrs,
                "Status": "🔴 DELAYED" if is_delayed else "🟢 On Track" if act_hrs > 0 else "⚪ Waiting",
                "Progress": f"{act_hrs} Hrs"
            })
    return pd.DataFrame(rows)

# --- 4. DASHBOARD TABS ---
tab_founder, tab_planning, tab_entry = st.tabs(["📈 Founder Dashboard", "🗓️ Activity Plan", "👷 Shop Entry"])

# --- TAB 1: FOUNDER DASHBOARD ---
with tab_founder:
    st.subheader("Executive Control: Plan vs. Logs")
    if not df_p.empty:
        df_analysis = get_plan_vs_actual(df_p, df_l)
        
        # Quick Alert for Delayed Activities
        delays = df_analysis[df_analysis['Status'] == "🔴 DELAYED"]
        if not delays.empty:
            st.error(f"⚠️ Warning: {len(delays)} activities have missed their Planned Finish dates!")
            st.dataframe(delays, use_container_width=True)

        # Activity Breakdown Pie
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Hours Spent per Activity**")
            fig = px.pie(df_l[df_l['Notes'] != "SYSTEM_NEW_ITEM"], values='Hours', names='Activity', hole=0.4)
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.write("**Resource Distribution**")
            fig2 = px.bar(df_l[df_l['Notes'] != "SYSTEM_NEW_ITEM"].groupby('Worker')['Hours'].sum().reset_index(), x='Worker', y='Hours')
            st.plotly_chart(fig2, use_container_width=True)

# --- TAB 2: ACTIVITY PLAN (GANTT) ---
with tab_planning:
    st.subheader("Parallel Master Gantt")
    if not df_p.empty:
        # Drawing the Gantt chart using Calculated Dates
        gantt_rows = []
        for _, job in df_p.iterrows():
            start_date = pd.to_datetime(job['created_at'])
            finish_map = {0: start_date}
            for i, (name, val) in enumerate(PLANNING_RECIPE.items(), 1):
                t_s = max([finish_map[d] for d in val['deps']])
                t_e = t_s + timedelta(days=val['dur'])
                finish_map[i] = t_e
                gantt_rows.append({"Job": job['job_no'], "Task": name, "Start": t_s, "Finish": t_e})
        
        fig_g = px.timeline(pd.DataFrame(gantt_rows), x_start="Start", x_end="Finish", y="Job", color="Task")
        fig_g.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_g, use_container_width=True)

# --- TAB 3: SHOP ENTRY (LOGS) ---
with tab_entry:
    st.subheader("Daily Productivity Log")
    with st.form("entry", clear_on_submit=True):
        col1, col2 = st.columns(2)
        f_job = col1.selectbox("Job", df_p['job_no'].unique() if not df_p.empty else [])
        f_act = col1.selectbox("Activity", list(PLANNING_RECIPE.keys()))
        f_wrk = col2.selectbox("Worker", df_l['Worker'].unique() if not df_l.empty else [])
        f_hrs = col2.number_input("Hours", min_value=0.0)
        f_out = col2.number_input("Output Value", min_value=0.0)
        
        if st.form_submit_button("Save Log"):
            conn.table("production").insert({
                "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                "Job_Code": str(f_job), "Activity": f_act, "Worker": f_wrk, 
                "Hours": f_hrs, "Output": f_out, "Notes": "Daily Log"
            }).execute()
            st.rerun()
