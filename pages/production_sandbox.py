import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
import plotly.express as px
import io

# --- 1. SETUP & CONNECTION ---
IST = pytz.timezone('Asia/Kolkata')
TODAY_IST = datetime.now(IST).date()
st.set_page_config(page_title="Production Master ERP | B&G", layout="wide", page_icon="🏗️")

# --- EXCEL EXPORT HELPER ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Production_Report')
    return output.getvalue()

# --- PASSWORD PROTECTION ---
def check_password():
    if "password_correct" not in st.session_state:
        st.text_input("🔑 Enter Master Password", type="password", on_change=lambda: st.session_state.update({"password_correct": st.session_state.password == "9025"}), key="password")
        return False
    return st.session_state["password_correct"]

if not check_password():
    st.stop()

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS (Enhanced) ---
@st.cache_data(ttl=2)
def get_full_data():
    try:
        # Fetch all necessary tables
        p_res = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
        l_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        m_res = conn.table("production_gates").select("*").order("step_order").execute()
        j_res = conn.table("job_planning").select("*").order("step_order").execute()
        pur_res = conn.table("purchase_orders").select("*").execute()
        sub_res = conn.table("job_sub_tasks").select("*").execute()
        w_res = conn.table("master_workers").select("name").order("name").execute()

        return (
            pd.DataFrame(p_res.data or []),
            pd.DataFrame(l_res.data or []),
            pd.DataFrame(m_res.data or []),
            pd.DataFrame(j_res.data or []),
            pd.DataFrame(pur_res.data or []),
            pd.DataFrame(sub_res.data or []),
            [w['name'] for w in (w_res.data or [])]
        )
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return [pd.DataFrame()] * 6 + [[]]

df_p, df_logs, df_m_gates, df_j_plans, df_pur, df_sub, all_workers = get_full_data()

# --- 3. NAVIGATION ---
tab_summary, tab_plan, tab_entry, tab_analytics = st.tabs([
    "📊 Executive Summary", "🏗️ Scheduling", "👷 Daily Entry", "📈 Analytics"
])

# --- TAB 1: EXECUTIVE SUMMARY ---
with tab_summary:
    st.subheader("📊 Factory-Wide Progress")
    if not df_j_plans.empty:
        job_stats = []
        for job in df_p['job_no'].unique():
            # Calculate Gate-level progress
            job_gates = df_j_plans[df_j_plans['job_no'] == job]
            if job_gates.empty: continue
            
            prog = int((len(job_gates[job_gates['current_status'] == "Completed"]) / len(job_gates)) * 100)
            
            # Check for critical material blockers
            pending_po = df_pur[(df_pur['job_no'] == job) & (df_pur['status'] != "Received")] if not df_pur.empty else pd.DataFrame()
            
            job_stats.append({
                "Job": job,
                "Client": df_p[df_p['job_no'] == job].iloc[0]['client_name'],
                "Progress": prog,
                "Materials": "✅ OK" if pending_po.empty else f"⚠️ {len(pending_po)} Pending"
            })
        
        st.dataframe(pd.DataFrame(job_stats), use_container_width=True, hide_index=True)

# --- TAB 2: SCHEDULING (The Core Logic) ---
with tab_plan:
    sel_job = st.selectbox("Select Job", ["-- Select --"] + sorted(df_p['job_no'].unique().tolist()))
    
    if sel_job != "-- Select --":
        curr_proj = df_p[df_p['job_no'] == sel_job].iloc[0]
        
        # 1. Add New Gate
        with st.expander("➕ Add Process Gate"):
            with st.form("new_gate"):
                g_name = st.selectbox("Gate Type", df_m_gates['gate_name'].tolist())
                g_dates = st.date_input("Schedule", [TODAY_IST, TODAY_IST + timedelta(days=7)])
                if st.form_submit_button("Add to Plan"):
                    conn.table("job_planning").insert({
                        "job_no": sel_job, "gate_name": g_name, 
                        "planned_start_date": g_dates[0].isoformat(), 
                        "planned_end_date": g_dates[1].isoformat(), "current_status": "Pending"
                    }).execute()
                    st.cache_data.clear(); st.rerun()

        # 2. List Gates and Sub-tasks
        job_steps = df_j_plans[df_j_plans['job_no'] == sel_job]
        for _, row in job_steps.iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 1, 1])
                c1.subheader(f"{row['gate_name']}")
                
                # Update Status Buttons
                if row['current_status'] == "Pending" and c2.button("▶️ Start", key=f"st_{row['id']}"):
                    conn.table("job_planning").update({"current_status": "Active"}).eq("id", row['id']).execute()
                    st.cache_data.clear(); st.rerun()
                elif row['current_status'] == "Active" and c2.button("✅ Complete", key=f"cp_{row['id']}"):
                    conn.table("job_planning").update({"current_status": "Completed"}).eq("id", row['id']).execute()
                    st.cache_data.clear(); st.rerun()
                
                # Sub-task Logic
                st.write("---")
                subs = df_sub[df_sub['parent_gate_id'] == row['id']]
                for _, s in subs.iterrows():
                    sc1, sc2, sc3 = st.columns([4, 2, 1])
                    sc1.write(f"{'✅' if s['current_status'] == 'Completed' else '⏳'} {s['sub_task_name']}")
                    if sc3.button("🔄", key=f"tog_s_{s['id']}"):
                        new_stat = "Pending" if s['current_status'] == "Completed" else "Completed"
                        conn.table("job_sub_tasks").update({"current_status": new_stat}).eq("id", s['id']).execute()
                        st.cache_data.clear(); st.rerun()

                # Add Sub-task
                with st.form(f"sub_form_{row['id']}", clear_on_submit=True):
                    sc_in, sc_btn = st.columns([3, 1])
                    new_sub_n = sc_in.text_input("New Sub-task", placeholder="e.g. Drilling, Welding...")
                    if sc_btn.form_submit_button("➕"):
                        conn.table("job_sub_tasks").insert({
                            "project_id": int(curr_proj['id']), "parent_gate_id": int(row['id']),
                            "sub_task_name": new_sub_n, "current_status": "Pending",
                            "planned_end_date": (TODAY_IST + timedelta(days=2)).isoformat()
                        }).execute()
                        st.cache_data.clear(); st.rerun()

# --- TAB 3: DAILY ENTRY ---
with tab_entry:
    e_job = st.selectbox("Job No", ["-- Select --"] + sorted(df_p['job_no'].unique().tolist()), key="e_j")
    if e_job != "-- Select --":
        e_gates = df_j_plans[df_j_plans['job_no'] == e_job]
        
        with st.form("daily_log"):
            gate_sel = st.selectbox("Gate", e_gates['gate_name'].tolist())
            worker_sel = st.selectbox("Worker", all_workers)
            hrs = st.number_input("Hours Spent", min_value=0.5, step=0.5)
            rem = st.text_input("Work Details / Remarks")
            
            if st.form_submit_button("Log Work"):
                conn.table("production").insert({
                    "Job_Code": e_job, "Activity": gate_sel, 
                    "Worker": worker_sel, "Hours": hrs, "notes": rem
                }).execute()
                st.success("Entry Saved!"); st.cache_data.clear(); st.rerun()
