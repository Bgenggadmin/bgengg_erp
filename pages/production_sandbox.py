import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz

# --- 1. CONFIG & DB CONNECTION ---
IST = pytz.timezone('Asia/Kolkata')
TODAY = datetime.now(IST).date()
st.set_page_config(page_title="B&G Production Base", layout="wide")

# Initialize Connection
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. CORE DATA LOADERS ---
@st.cache_data(ttl=2)
def load_base_data():
    # Load Won Projects
    proj = conn.table("anchor_projects").select("id, job_no, client_name").eq("status", "Won").execute()
    # Load Master Gate Definitions
    m_gates = conn.table("production_gates").select("*").order("step_order").execute()
    # Load Current Job Plans
    plans = conn.table("job_planning").select("*").order("step_order").execute()
    # Load Sub-Tasks
    subs = conn.table("job_sub_tasks").select("*").execute()
    
    return pd.DataFrame(proj.data), pd.DataFrame(m_gates.data), pd.DataFrame(plans.data), pd.DataFrame(subs.data)

df_p, df_mg, df_plans, df_subs = load_base_data()

# --- 3. UI TABS ---
tab1, tab2, tab3 = st.tabs(["🏗️ Project Planning", "👷 Daily Progress", "📊 Status Overview"])

# --- TAB 1: PLANNING LOGIC (Gates & Sub-tasks) ---
with tab1:
    st.subheader("Plan Process for Job")
    sel_job = st.selectbox("Select Active Job", df_p['job_no'].unique())
    
    if sel_job:
        job_id = df_p[df_p['job_no'] == sel_job].iloc[0]['id']
        
        # Action: Add a Gate to the Job
        with st.expander("➕ Add Process Gate (e.g., Fabrication, Painting)"):
            with st.form("add_gate"):
                gate_name = st.selectbox("Gate Name", df_mg['gate_name'].unique())
                if st.form_submit_button("Add Gate to Job"):
                    conn.table("job_planning").insert({
                        "job_no": sel_job, 
                        "gate_name": gate_name,
                        "current_status": "Pending"
                    }).execute()
                    st.cache_data.clear(); st.rerun()

        # Display Existing Gates for this Job
        current_gates = df_plans[df_plans['job_no'] == sel_job]
        for _, gate in current_gates.iterrows():
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                col1.markdown(f"### Gate: {gate['gate_name']}")
                
                # Logic: Toggle Gate Status
                if gate['current_status'] != "Completed":
                    if col2.button("✅ Mark Gate Done", key=f"g_done_{gate['id']}"):
                        conn.table("job_planning").update({"current_status": "Completed"}).eq("id", gate['id']).execute()
                        st.cache_data.clear(); st.rerun()
                else:
                    col2.success("Gate Finished")

                # --- NESTED SUB-TASKS LOGIC ---
                st.write("**Specific Work Items (Sub-tasks):**")
                gate_subs = df_subs[df_subs['parent_gate_id'] == gate['id']]
                
                for _, sub in gate_subs.iterrows():
                    sc1, sc2 = st.columns([4, 1])
                    status_icon = "✅" if sub['current_status'] == "Completed" else "⏳"
                    sc1.write(f"{status_icon} {sub['sub_task_name']}")
                    if sc2.button("Toggle", key=f"s_tog_{sub['id']}"):
                        new_stat = "Pending" if sub['current_status'] == "Completed" else "Completed"
                        conn.table("job_sub_tasks").update({"current_status": new_stat}).eq("id", sub['id']).execute()
                        st.cache_data.clear(); st.rerun()

                # Form to add Sub-task to this specific Gate
                with st.form(f"sub_form_{gate['id']}", clear_on_submit=True):
                    sub_n = st.text_input("New Sub-task Name")
                    if st.form_submit_button("Add Sub-task"):
                        conn.table("job_sub_tasks").insert({
                            "project_id": int(job_id),
                            "parent_gate_id": int(gate['id']),
                            "sub_task_name": sub_n,
                            "current_status": "Pending"
                        }).execute()
                        st.cache_data.clear(); st.rerun()

# --- TAB 2: DAILY ENTRY ---
with tab2:
    st.subheader("Log Worker Activity")
    with st.form("daily_entry"):
        e_job = st.selectbox("Job", df_p['job_no'].unique())
        # Only show gates that are currently in the plan for this job
        active_gates = df_plans[df_plans['job_no'] == e_job]['gate_name'].unique()
        e_gate = st.selectbox("Activity Gate", active_gates)
        e_worker = st.text_input("Worker Name")
        e_hrs = st.number_input("Hours", min_value=0.5, step=0.5)
        
        if st.form_submit_button("Submit Daily Log"):
            conn.table("production").insert({
                "Job_Code": e_job, "Activity": e_gate, "Worker": e_worker, "Hours": e_hrs
            }).execute()
            st.success("Log recorded!")

# --- TAB 3: SUMMARY ---
with tab3:
    st.subheader("High-Level Progress")
    # Simple calculation: (Completed Gates / Total Gates) per Job
    if not df_plans.empty:
        summary = df_plans.groupby('job_no')['current_status'].apply(
            lambda x: f"{(x == 'Completed').sum()} / {len(x)} Gates Done"
        )
        st.table(summary)
