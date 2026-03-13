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
    
    try:
        hist_res = conn.table("job_gate_history").select("*").order("entered_at", desc=True).execute()
        df_hist = pd.DataFrame(hist_res.data or [])
    except:
        df_hist = pd.DataFrame()

    try:
        rev_res = conn.table("dispatch_revision_history").select("*").order("revised_at", desc=True).execute()
        df_revs = pd.DataFrame(rev_res.data or [])
    except:
        df_revs = pd.DataFrame()
    
    return (pd.DataFrame(plan_res.data or []), 
            pd.DataFrame(prod_res.data or []), 
            pd.DataFrame(pur_res.data or []),
            pd.DataFrame(gate_res.data or []),
            df_hist,
            df_revs)

df_plan, df_logs, df_pur, df_gates, df_hist, df_revs = get_master_data()

# --- 3. DYNAMIC MAPPING ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
universal_stages = df_gates['gate_name'].tolist() if not df_gates.empty else ["Stage 1"]

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
    st.subheader("🚀 Shop Floor Gate Control & Delivery Tracking")
    if not df_plan.empty:
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for index, row in df_plan.iterrows():
            job_id = str(row['job_no']).strip().upper()
            actual_hrs = hrs_sum.get(job_id, 0)
            budget = 200 if any(x in str(row['project_description']).upper() for x in ["REACTOR", "ANFD", "COLUMN"]) else 100
            
            # --- DATE LOGIC (DRAGGED FROM ANCHOR) ---
            po_date = row.get('customer_po_date')
            orig_disp = row.get('promised_dispatch_date') # Baseline from Sales
            revised_disp = row.get('revised_dispatch_date') # Current Floor Promise
            
            # Active Commitment: Use Revised if it exists, otherwise use Original from Sales
            current_commitment = revised_disp if revised_disp else orig_disp
            
            updated_at = pd.to_datetime(row.get('updated_at', datetime.now(IST)))
            days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
            manual_limit = row.get('manual_days_limit', 7) 
            
            current_stage = row['drawing_status']
            prog_idx = universal_stages.index(current_stage) if current_stage in universal_stages else 0
            rem_gates = len(universal_stages) - (prog_idx + 1)
            practical_eta = (datetime.now(IST) + timedelta(days=rem_gates * manual_limit)).date()

            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c1.caption(f"🛠️ {row['project_description']}")
                
                # Column 2: Sales Baseline
                c2.metric("PO Date", str(po_date) if po_date else "N/A")
                c2.caption(f"Original Disp: {orig_disp}")
                
                # Column 3: Shop Floor Aging
                aging_color = "normal" if days_at_gate <= manual_limit else "inverse"
                c3.metric("Days at Gate", f"{days_at_gate}d", delta=f"Limit: {manual_limit}d", delta_color=aging_color)
                
                # Column 4: Delivery Risk
                is_late = current_commitment and practical_eta > pd.to_datetime(current_commitment).date()
                c4.metric("Current Promise", str(current_commitment) if current_commitment else "Not Set",
                          delta="⚠️ Late" if is_late else "On Track", delta_color="inverse" if is_late else "normal")
                
                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                # --- HISTORIES ---
                h1, h2 = st.columns(2)
                with h1.expander("📜 Gate History"):
                    if not df_hist.empty: st.table(df_hist[df_hist['job_no'] == job_id].head(3))
                with h2.expander("📅 Delivery Revisions"):
                    if not df_revs.empty: st.table(df_revs[df_revs['job_no'] == job_id].head(3))

                st.divider()

                # --- UPDATE CONTROLS ---
                col1, col2, col3, col4 = st.columns(4)
                new_gate = col1.selectbox("Move Gate", universal_stages, index=prog_idx, key=f"gt_{row['id']}")
                new_limit = col2.number_input("Allowed Days/Gate", min_value=1, value=int(manual_limit), key=f"lim_{row['id']}")
                
                # Set default date for calendar
                cal_default = pd.to_datetime(current_commitment).date() if current_commitment else datetime.now(IST).date()
                new_promise = col3.date_input("Revise Dispatch", value=cal_default, key=f"dp_{row['id']}")
                new_rem = col4.text_input("Remarks/Reason", value=row.get('shortage_details', ""), key=f"rm_{row['id']}")

                if st.button("Update Status", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    if new_gate != current_stage:
                        conn.table("job_gate_history").insert({"job_no": job_id, "gate_name": current_stage, "days_spent": days_at_gate, "entered_at": updated_at.isoformat()}).execute()
                    
                    if current_commitment and str(new_promise) != str(current_commitment):
                        conn.table("dispatch_revision_history").insert({"job_no": job_id, "old_date": str(current_commitment), "new_date": str(new_promise), "reason": new_rem}).execute()

                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate, "manual_days_limit": new_limit, "revised_dispatch_date": str(new_promise),
                        "shortage_details": new_rem, "updated_at": datetime.now(IST).isoformat()
                    }).eq("id", row['id']).execute()
                    st.rerun()

# --- TABS 2, 3, 4 (Audited Line-by-Line) ---
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
                conn.table("production").insert({"Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job, "Activity": f_act, "Hours": f_hrs, "Output": f_out, "Notes": f_nts}).execute()
                st.success("Work Logged!"); st.rerun()

with tab_analytics:
    if not df_logs.empty:
        st.subheader("📅 Today's Shift Report")
        df_logs['created_at'] = pd.to_datetime(df_logs['created_at']).dt.tz_convert(IST)
        today_logs = df_logs[df_logs['created_at'].dt.date == datetime.now(IST).date()]
        if not today_logs.empty:
            st.dataframe(today_logs[['created_at', 'Worker', 'Job_Code', 'Activity', 'Hours', 'Notes']], hide_index=True, use_container_width=True)
            st.metric("Total Hours Today", f"{today_logs['Hours'].sum()} Hrs")
        
        st.divider()
        clean_logs = df_logs[df_logs['Notes'] != "SYSTEM_NEW_ITEM"]
        fig = px.bar(clean_logs.groupby('Job_Code')['Hours'].sum().reset_index(), x='Job_Code', y='Hours', title="Cumulative Man-Hours")
        st.plotly_chart(fig, use_container_width=True)

with tab_masters:
    st.subheader("🛠️ Master Registration")
    m1, m2 = st.columns(2)
    with m1:
        new_w = st.text_input("Register New Worker")
        if st.button("Add Person") and new_w:
            conn.table("production").insert({"Worker": new_w, "Notes": "SYSTEM_NEW_ITEM", "Hours": 0, "Activity": "N/A", "Job_Code": "N/A"}).execute()
            st.rerun()
    with m2:
        st.write("Current Workflow Gates:")
        st.dataframe(df_gates[['step_order', 'gate_name']], hide_index=True, height=200)
        new_g = st.text_input("Add New Gate Name")
        new_o = st.number_input("Gate Order", min_value=1, value=len(universal_stages)+1)
        if st.button("Add Gate") and new_g:
            conn.table("production_gates").insert({"gate_name": new_g, "step_order": new_o}).execute()
            st.rerun()
