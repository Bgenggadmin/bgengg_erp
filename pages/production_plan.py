import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. INITIALIZATION ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G ERP | Founder Dashboard", layout="wide", page_icon="🏗️")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. THE PARALLEL RECIPE (PLANNING MASTER) ---
# Defines the Parallel Paths and Dependencies
PLANNING_RECIPE = {
    "1. Engineering & MTC": {"dur": 7, "deps": [0]},
    "2. Shell Fabrication": {"dur": 15, "deps": [1]},
    "3. Jacket/Limpet Fitting": {"dur": 10, "deps": [2]},
    "4. DRIVE ASSEMBLY (Parallel)": {"dur": 12, "deps": [1]}, # Starts after Engineering
    "5. Internal Coil Fab (Parallel)": {"dur": 10, "deps": [1]}, # Starts after Engineering
    "6. MAIN ASSEMBLY": {"dur": 7, "deps": [3, 4, 5]}, # Waits for Shell, Drive, and Coils
    "7. Hydro-test & NDT": {"dur": 4, "deps": [6]},
    "8. Dispatch": {"dur": 2, "deps": [7]}
}

@st.cache_data(ttl=2)
def get_all_data():
    p = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    l = conn.table("production").select("*").order("created_at", desc=True).execute()
    return pd.DataFrame(p.data or []), pd.DataFrame(l.data or [])

df_p, df_l = get_all_data()

# --- 3. DASHBOARD TABS ---
tab_founder, tab_planning, tab_entry, tab_masters = st.tabs([
    "📈 Founder Dashboard", "🗓️ Parallel Scheduling", "👷 Shop Entry", "🛠️ Masters"
])

# --- TAB 1: FOUNDER DASHBOARD (REPLACING ZOHO REPORTS) ---
with tab_founder:
    st.title("Executive Summary")
    if not df_l.empty:
        clean_l = df_l[df_l['Notes'] != "SYSTEM_NEW_ITEM"]
        
        # Top Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Man-Hours Spent", f"{clean_l['Hours'].sum():.1f}")
        m2.metric("Active Jobs", len(df_p))
        m3.metric("Total Output Units", f"{clean_l['Output'].sum():.0f}")
        m4.metric("Avg Worker Efficiency", f"{(clean_l['Output'].sum()/clean_l['Hours'].sum() if clean_l['Hours'].sum()>0 else 0):.2f} unit/hr")

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Man-Hour Distribution by Activity")
            fig_pie = px.pie(clean_l, values='Hours', names='Activity', hole=0.5, color_discrete_sequence=px.colors.sequential.RdBu)
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with c2:
            st.subheader("Project Burn Rate (Hours per Job)")
            fig_bar = px.bar(clean_l.groupby('Job_Code')['Hours'].sum().reset_index(), x='Job_Code', y='Hours', color='Hours')
            st.plotly_chart(fig_bar, use_container_width=True)

        st.subheader("Detailed Resource Utilization Table")
        st.dataframe(clean_l[['created_at', 'Worker', 'Job_Code', 'Activity', 'Hours', 'Output', 'Supervisor']], use_container_width=True)

# --- TAB 2: PARALLEL SCHEDULING (THE GANTT ENGINE) ---
with tab_planning:
    st.subheader("Automated Parallel Timeline (Kettle + Drive)")
    
    def calc_gantt(job_df):
        all_tasks = []
        for _, job in job_df.iterrows():
            start_date = pd.to_datetime(job['created_at'])
            finish_map = {0: start_date}
            
            for i, (name, val) in enumerate(PLANNING_RECIPE.items(), 1):
                t_start = max([finish_map[d] for d in val['deps']])
                t_end = t_start + timedelta(days=val['dur'])
                finish_map[i] = t_end
                all_tasks.append({"Job": job['job_no'], "Task": name, "Start": t_start, "Finish": t_end, "Type": "Main" if "Parallel" not in name else "Parallel"})
        return pd.DataFrame(all_tasks)

    if not df_p.empty:
        df_g = calc_gantt(df_p)
        fig_g = px.timeline(df_g, x_start="Start", x_end="Finish", y="Job", color="Task", hover_name="Task")
        fig_g.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_g, use_container_width=True)
        
        # List of Dispatch Dates
        st.write("**Calculated Dispatch Dates:**")
        st.dataframe(df_g.groupby("Job")["Finish"].max())

# --- TAB 3: SHOP ENTRY (WORK MEASUREMENT) ---
with tab_entry:
    with st.form("entry_form", clear_on_submit=True):
        st.subheader("Log Productivity")
        e1, e2, e3 = st.columns(3)
        job_sel = e1.selectbox("Job Code", df_p['job_no'].unique() if not df_p.empty else [])
        work_sel = e1.selectbox("Worker/Engineer", sorted(df_l['Worker'].unique()) if not df_l.empty else [])
        act_sel = e2.selectbox("Activity", list(PLANNING_RECIPE.keys()))
        unit_sel = e2.selectbox("Unit", ["Meters (Mts)", "Joints (Nos)", "Layouts (Nos)"])
        out_val = e3.number_input("Output Value", min_value=0.0)
        hr_val = e3.number_input("Hours Spent", min_value=0.0)
        notes = st.text_area("Notes/Remarks")
        
        if st.form_submit_button("💾 Save Entry", type="primary"):
            conn.table("production").insert({
                "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S'),
                "Job_Code": str(job_sel), "Worker": work_sel, "Activity": act_sel,
                "Unit": unit_sel, "Output": out_val, "Hours": hr_val, "Notes": notes, "Supervisor": "Auto"
            }).execute()
            st.success("Entry Saved!")
            st.rerun()

# --- TAB 4: MASTERS ---
with tab_masters:
    st.subheader("Manage Masters")
    new_w = st.text_input("New Worker/Engineer Name")
    if st.button("Add Person"):
        conn.table("production").insert({"Worker": new_w, "Notes": "SYSTEM_NEW_ITEM", "Activity": "N/A", "Job_Code": "N/A", "Hours": 0}).execute()
        st.success(f"{new_w} Added")
        st.rerun()
