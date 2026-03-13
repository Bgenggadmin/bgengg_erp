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
    # Fetch History for the expanders
    hist_res = conn.table("job_gate_history").select("*").order("entered_at", desc=True).execute()
    
    return (pd.DataFrame(plan_res.data or []), 
            pd.DataFrame(prod_res.data or []), 
            pd.DataFrame(pur_res.data or []),
            pd.DataFrame(gate_res.data or []),
            pd.DataFrame(hist_res.data or []))

df_plan, df_logs, df_pur, df_gates, df_hist = get_master_data()

# --- 3. DYNAMIC MAPPING ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]

if not df_gates.empty:
    universal_stages = df_gates['gate_name'].tolist()
else:
    universal_stages = [
        "1. Engineering & MTC Verify", "2. Marking & Cutting", "3. Sub-Assembly & Machining",
        "4. Shell/Body Fabrication", "5. Main Assembly/Internals", "6. Nozzles & Accessories",
        "7. Inspection & NDT", "8. Hydro/Pressure Testing", "9. Insulation & Finishing",
        "10. Final Assembly & Dispatch"
    ]

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
    st.subheader("🚀 Shop Floor Gate Control & Bottleneck Tracking")
    if not df_plan.empty:
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for index, row in df_plan.iterrows():
            job_id = str(row['job_no']).strip().upper()
            actual_hrs = hrs_sum.get(job_id, 0)
            budget = 200 if any(x in str(row['project_description']).upper() for x in ["REACTOR", "ANFD", "COLUMN"]) else 100
            
            # --- CALCULATE GATE AGING & ETA ---
            updated_at = pd.to_datetime(row.get('updated_at', datetime.now(IST)))
            days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
            manual_limit = row.get('manual_days_limit', 7) # Manual days from DB
            
            current_stage = row['drawing_status']
            prog_idx = universal_stages.index(current_stage) if current_stage in universal_stages else 0
            
            # ETA Calculation based on manual days x remaining gates
            rem_gates = len(universal_stages) - (prog_idx + 1)
            eta_finish = (datetime.now(IST) + timedelta(days=rem_gates * manual_limit)).strftime("%d %b %Y")

            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c1.caption(f"🛠️ {row['project_description']}")
                
                # Metric 1: Man Hours
                c2.metric("Total Man-Hours", f"{actual_hrs} Hrs", 
                          delta=f"{actual_hrs-budget} Over" if actual_hrs > budget else None, delta_color="inverse")
                
                # Metric 2: Gate Aging (Bottleneck Detection)
                aging_color = "normal" if days_at_gate <= manual_limit else "inverse"
                c3.metric("Days at Gate", f"{days_at_gate} Days", 
                          delta=f"Limit: {manual_limit}d" if days_at_gate > manual_limit else "On Track", delta_color=aging_color)
                
                # Metric 3: Projected ETA
                c4.metric("Projected Finish", eta_finish)
                
                # Progress Bar
                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                # --- NEW: GATE HISTORY LOG ---
                with st.expander("📜 View Production History"):
                    if not df_hist.empty:
                        job_h = df_hist[df_hist['job_no'] == job_id]
                        if not job_h.empty:
                            st.dataframe(job_h[['gate_name', 'entered_at', 'days_spent']], hide_index=True, use_container_width=True)
                        else:
                            st.write("No gate transitions recorded yet.")

                # --- MATERIAL SHORTAGE TRIGGER ---
                with st.expander("🚨 Material Shortage? Trigger Purchase Request"):
                    mc1, mc2, mc3 = st.columns([2, 1, 1])
                    req_item = mc1.text_input("Item Name", key=f"req_{row['id']}")
                    req_qty = mc2.text_input("Qty/Spec", key=f"qty_{row['id']}")
                    if mc3.button("Request Item", key=f"rqb_{row['id']}", use_container_width=True):
                        if req_item:
                            conn.table("purchase_orders").insert({
                                "job_no": job_id, "item_name": f"SHOP-FLOOR: {req_item}",
                                "specs": req_qty, "status": "Urgent"
                            }).execute()
                            st.toast("Sent to Purchase Team!"); st.rerun()
                
                # --- LIVE PURCHASE FEEDBACK ---
                if not df_pur.empty:
                    job_items = df_pur[df_pur['job_no'] == job_id]
                    if not job_items.empty:
                        st.caption("📦 Procurement Status:")
                        for _, item in job_items.tail(1).iterrows():
                            color = "orange" if item['status'] != "Received" else "green"
                            reply = f" | 💬 {item['purchase_reply']}" if item['purchase_reply'] else ""
                            st.markdown(f":{color}[**{item['item_name']}**: {item['status']}{reply}]")

                st.divider()

                col1, col2, col3, col4 = st.columns(4)
                new_gate = col1.selectbox("Current Gate", universal_stages, index=prog_idx, key=f"gt_{row['id']}")
                new_limit = col2.number_input("Allowed Days/Gate", min_value=1, value=int(manual_limit), key=f"lim_{row['id']}")
                new_short = col3.toggle("Alert Active", value=row.get('material_shortage', False), key=f"sh_{row['id']}")
                new_rem = col4.text_input("Floor Remarks", value=row.get('shortage_details', ""), key=f"rm_{row['id']}")

                if st.button("Update Gate Status", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    # Record history if gate has changed
                    if new_gate != current_stage:
                        conn.table("job_gate_history").insert({
                            "job_no": job_id, "gate_name": current_stage, "days_spent": days_at_gate,
                            "entered_at": updated_at.isoformat()
                        }).execute()

                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate, 
                        "manual_days_limit": new_limit,
                        "material_shortage": new_short, 
                        "shortage_details": new_rem,
                        "updated_at": datetime.now(IST).isoformat()
                    }).eq("id", row['id']).execute()
                    st.toast("Status Synced!"); st.rerun()

# --- TAB 2: DAILY WORK ENTRY ---
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

# --- TAB 3: ANALYTICS ---
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

# --- TAB 4: MASTERS ---
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
        new_o = st.number_input("Gate Order", min_value=1, step=1, value=len(universal_stages)+1)
        if st.button("Add Gate") and new_g:
            conn.table("production_gates").insert({"gate_name": new_g, "step_order": new_o}).execute()
            st.rerun()
