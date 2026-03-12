import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px

# --- 1. SETTINGS & CONNECTION ---
st.set_page_config(page_title="Planning & Scheduling", layout="wide", page_icon="🗓️")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. THE MASTER PLANNING RECIPE ---
# 0 = Project Start. Other numbers = Gate ID dependency.
# This replaces Zoho's dependency engine.
PLANNING_LOGIC = {
    "1. Engineering & MTC": {"dur": 7, "deps": [0], "type": "Main"},
    "2. Shell Fabrication": {"dur": 15, "deps": [1], "type": "Main"},
    "3. Jacket/Limpet Fitting": {"dur": 10, "deps": [2], "type": "Main"},
    "4. DRIVE ASSEMBLY (Parallel)": {"dur": 12, "deps": [1], "type": "Parallel"},
    "5. INTERNAL COIL FAB (Parallel)": {"dur": 10, "deps": [1], "type": "Parallel"},
    "6. MAIN ASSEMBLY": {"dur": 7, "deps": [3, 4, 5], "type": "Main"}, # Waits for all 3
    "7. Hydro-test & NDT": {"dur": 4, "deps": [6], "type": "Main"},
    "8. Finishing & Painting": {"dur": 3, "deps": [7], "type": "Main"},
    "9. Dispatch": {"dur": 1, "deps": [8], "type": "Main"}
}

@st.cache_data(ttl=5)
def load_planning_data():
    # Fetch Won Projects from Anchor Console
    res = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    df = pd.DataFrame(res.data or [])
    if not df.empty:
        # Convert to naive datetime to prevent TypeError during comparison
        df['created_at'] = pd.to_datetime(df['created_at']).dt.tz_localize(None)
    return df

df_projects = load_planning_data()

# --- 3. THE SCHEDULING ENGINE ---
def generate_schedule(project_start, recipe):
    schedule = []
    finish_times = {0: project_start}
    
    for i, (name, val) in enumerate(recipe.items(), 1):
        # Start time is the maximum finish time of all dependencies
        start_time = max([finish_times[d] for d in val['deps']])
        end_time = start_time + timedelta(days=val['dur'])
        finish_times[i] = end_time
        
        schedule.append({
            "Task": name,
            "Start": start_time,
            "Finish": end_time,
            "Category": val['type']
        })
    return pd.DataFrame(schedule)

# --- 4. INTERFACE ---
st.title("🏗️ Project Master Scheduler")
st.markdown("### *Lead-Time Based Parallel Planning (Zoho Replacement)*")

tab_gantt, tab_status, tab_masters = st.tabs(["📊 Master Gantt Chart", "📍 Current Stage Update", "🛠️ Manage Masters"])

# --- TAB 1: MASTER GANTT ---
with tab_gantt:
    if not df_projects.empty:
        all_schedules = []
        for _, job in df_projects.iterrows():
            job_sch = generate_schedule(job['created_at'], PLANNING_LOGIC)
            job_sch['Job_Code'] = f"{job['job_no']} - {job['client_name']}"
            all_schedules.append(job_sch)
        
        master_gantt_df = pd.concat(all_schedules)
        
        fig = px.timeline(
            master_gantt_df, 
            x_start="Start", 
            x_end="Finish", 
            y="Job_Code", 
            color="Task",
            hover_data=["Category"],
            title="Consolidated Shop-Floor Timeline"
        )
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No 'Won' projects found in the database.")

# --- TAB 2: CURRENT STAGE UPDATE ---
with tab_status:
    st.subheader("Update Project Milestones")
    if not df_projects.empty:
        for _, job in df_projects.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.markdown(f"**Job {job['job_no']}** | {job['client_name']}")
                c1.caption(f"Details: {job['project_description']}")
                
                # Dropdown for current gate (replaces Zoho task tracking)
                current_gate = job.get('drawing_status', "1. Engineering & MTC")
                all_gates = list(PLANNING_LOGIC.keys())
                
                new_gate = c2.selectbox(
                    "Current Gate", 
                    all_gates, 
                    index=all_gates.index(current_gate) if current_gate in all_gates else 0,
                    key=f"gate_{job['id']}"
                )
                
                if c3.button("Update Progress", key=f"upd_{job['id']}", type="primary"):
                    conn.table("anchor_projects").update({"drawing_status": new_gate}).eq("id", job['id']).execute()
                    st.toast(f"Job {job['job_no']} updated to {new_gate}")
                    st.rerun()

# --- TAB 3: MANAGE MASTERS ---
with tab_masters:
    st.subheader("Planning Master Data")
    st.info("Since this app replaces Zoho, use this section to manage your technical parameters.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.write("**Current Lead Times (Read Only)**")
        st.table(pd.DataFrame([
            {"Task": k, "Duration (Days)": v['dur']} for k, v in PLANNING_LOGIC.items()
        ]))
    
    with col2:
        st.write("**Add New Project Metadata**")
        new_tag = st.text_input("New Custom Activity Name")
        if st.button("Register Activity"):
            # This would allow you to expand the dropdowns in App 2
            st.success("New Activity Registered for Shop Floor Monitor.")
