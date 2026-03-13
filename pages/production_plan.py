import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master | B&G", layout="wide", page_icon="🏭")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=5)
def get_master_data():
    plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
    prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
    pur_res = conn.table("purchase_orders").select("*").execute()
    gate_res = conn.table("production_gates").select("*").order("step_order").execute()
    
    return (pd.DataFrame(plan_res.data or []), 
            pd.DataFrame(prod_res.data or []), 
            pd.DataFrame(pur_res.data or []),
            pd.DataFrame(gate_res.data or []))

df_plan, df_logs, df_pur, df_gates = get_master_data()

# --- 3. DYNAMIC MAPPING ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
universal_stages = df_gates['gate_name'].tolist() if not df_gates.empty else []

if not df_logs.empty:
    all_workers = sorted(list(set(df_logs["Worker"].dropna().unique().tolist())))
    all_activities = sorted(list(set(universal_stages + df_logs["Activity"].dropna().unique().tolist())))
else:
    all_workers, all_activities = [], universal_stages

# --- 4. NAVIGATION TABS ---
tab_plan, tab_entry, tab_analytics, tab_masters = st.tabs([
    "🏗️ Production Planning", "👷 Daily Work Entry", "📊 Analytics & Shift Report", "🛠️ Manage Masters"
])

# --- TAB 1: PRODUCTION PLANNING ---
with tab_plan:
    st.subheader("🚀 Shop Floor Control Center")
    if not df_plan.empty:
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for index, row in df_plan.iterrows():
            job_id = str(row['job_no']).strip().upper()
            actual_hrs = hrs_sum.get(job_id, 0)
            
            # --- AGING & MANUAL LIMIT LOGIC ---
            updated_at = pd.to_datetime(row.get('updated_at', datetime.now(IST)))
            days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
            
            manual_limit = row.get('manual_days_limit', 7) 
            current_gate = row['drawing_status']
            prog_idx = universal_stages.index(current_gate) if current_gate in universal_stages else 0
            rem_gates_count = len(universal_stages) - prog_idx

            with st.container(border=True):
                # We define inputs first so the metric above can react to them instantly
                col1, col2, col3, col4 = st.columns(4)
                new_gate = col1.selectbox("Move Gate", universal_stages, index=prog_idx, key=f"gt_{row['id']}")
                # The logic source:
                new_limit = col2.number_input("Allowed Days/Gate", min_value=1, value=int(manual_limit), key=f"lim_{row['id']}")
                new_short = col3.toggle("Shortage", value=row.get('material_shortage', False), key=f"sh_{row['id']}")
                new_rem = col4.text_input("Remarks", value=row.get('shortage_details', ""), key=f"rm_{row['id']}")

                # Logic: Total remaining days = gates left * lead time currently in the input box
                total_rem_days = rem_gates_count * new_limit
                est_completion = (datetime.now(IST) + timedelta(days=total_rem_days)).strftime("%d %b %Y")

                # Header Metrics
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c1.caption(f"🛠️ {row['project_description']}")
                
                c2.metric("Man-Hours", f"{actual_hrs} Hrs")
                
                is_slow = days_at_gate > manual_limit
                c3.metric("Gate Aging", f"{days_at_gate} Days", 
                          delta=f"Limit: {manual_limit}d" if is_slow else "OK", delta_color="inverse" if is_slow else "normal")
                
                # FIXED LOGIC: Estimated completion Date reactively based on 'new_limit'
                c4.metric("Est. Completion Date", est_completion, delta=f"{total_rem_days} Days Rem.")

                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                # Material Feed
                if not df_pur.empty:
                    job_items = df_pur[df_pur['job_no'] == job_id]
                    if not job_items.empty:
                        item = job_items.iloc[-1]
                        st.caption(f"📦 Procurement: {item['item_name']} - **{item['status']}**")

                st.divider()

                if st.button("Update Master Status", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate, 
                        "manual_days_limit": new_limit, 
                        "material_shortage": new_short, 
                        "shortage_details": new_rem,
                        "updated_at": datetime.now(IST).isoformat()
                    }).eq("id", row['id']).execute()
                    st.toast("Updated Successfully!"); st.rerun()

# --- TABS 2, 3, 4 (Unchanged) ---
with tab_entry:
    st.subheader("👷 Labor Output Entry")
    with st.form("prod_form", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        job_list = df_plan['job_no'].unique().tolist() if not df_plan.empty else []
        f_sup = f1.selectbox("Supervisor", base_supervisors)
        f_wrk = f1.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
        f_job = f2.selectbox("Job Code", ["-- Select --"] + job_list)
        f_act = f2.selectbox("Activity", all_activities)
        f_hrs = f3.number_input("Hours Spent", min_value=0.0, step=0.5)
        f_out = f3.number_input("Output (Qty)", min_value=0.0)
        f_nts = st.text_area("Task Details")
        if st.form_submit_button("🚀 Log Productivity", use_container_width=True):
            if "-- Select --" not in [f_wrk, f_job]:
                conn.table("production").insert({
                    "Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job,
                    "Activity": f_act, "Hours": f_hrs, "Output": f_out, "Notes": f_nts
                }).execute()
                st.success("Work Logged!"); st.rerun()

with tab_analytics:
    if not df_logs.empty:
        st.subheader("📅 Today's Shift Report")
        df_logs['created_at'] = pd.to_datetime(df_logs['created_at']).dt.tz_convert(IST)
        today_logs = df_logs[df_logs['created_at'].dt.date == datetime.now(IST).date()]
        if not today_logs.empty:
            st.dataframe(today_logs[['created_at', 'Worker', 'Job_Code', 'Activity', 'Hours', 'Notes']], hide_index=True, use_container_width=True)
        
        st.divider()
        clean_logs = df_logs[df_logs['Notes'] != "SYSTEM_NEW_ITEM"]
        fig = px.bar(clean_logs.groupby('Job_Code')['Hours'].sum().reset_index(), x='Job_Code', y='Hours', title="Cumulative Man-Hours")
        st.plotly_chart(fig, use_container_width=True)

with tab_masters:
    st.subheader("🛠️ Master Registration")
    m1, m2 = st.columns(2)
    with m1:
        new_w = st.text_input("Register Worker")
        if st.button("Add Person") and new_w:
            conn.table("production").insert({"Worker": new_w, "Notes": "SYSTEM_NEW_ITEM", "Hours": 0, "Activity": "N/A", "Job_Code": "N/A"}).execute()
            st.rerun()
    with m2:
        st.write("Production Gates:")
        st.dataframe(df_gates[['step_order', 'gate_name']], hide_index=True)
        new_g = st.text_input("New Gate Name")
        if st.button("Add Gate") and new_g:
            conn.table("production_gates").insert({"gate_name": new_g, "step_order": len(universal_stages)+1}).execute()
            st.rerun()
