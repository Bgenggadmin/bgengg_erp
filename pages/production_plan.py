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
    except: df_hist = pd.DataFrame()

    try:
        rev_res = conn.table("dispatch_revision_history").select("*").order("revised_at", desc=True).execute()
        df_revs = pd.DataFrame(rev_res.data or [])
    except: df_revs = pd.DataFrame()
    
    return (pd.DataFrame(plan_res.data or []), pd.DataFrame(prod_res.data or []), 
            pd.DataFrame(pur_res.data or []), pd.DataFrame(gate_res.data or []),
            df_hist, df_revs)

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
            
            limit_key = f"lim_{row['id']}"
            live_limit = st.session_state.get(limit_key, row.get('manual_days_limit', 7))
            
            # --- DATE LOGIC ---
            po_date = row.get('customer_po_date')
            orig_disp = row.get('promised_dispatch_date') 
            revised_disp = row.get('revised_dispatch_date') 
            current_commitment = revised_disp if revised_disp else orig_disp
            
            current_stage = row['drawing_status']
            prog_idx = universal_stages.index(current_stage) if current_stage in universal_stages else 0
            rem_gates = len(universal_stages) - (prog_idx + 1)
            practical_eta = (datetime.now(IST) + timedelta(days=rem_gates * live_limit)).date()

            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c1.caption(f"🛠️ {row['project_description']}")
                
                c2.metric("PO Date", str(po_date) if po_date else "N/A")
                
                updated_at = pd.to_datetime(row.get('updated_at', datetime.now(IST)))
                days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
                aging_color = "normal" if days_at_gate <= live_limit else "inverse"
                c3.metric("Days @ Gate", f"{days_at_gate}d", delta=f"Limit: {live_limit}d", delta_color=aging_color)
                
                is_late = current_commitment and practical_eta > pd.to_datetime(current_commitment).date()
                c4.metric("Practical ETA", str(practical_eta), 
                          delta="⚠️ Late" if is_late else "On Track", 
                          delta_color="inverse" if is_late else "normal")
                
                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                # --- PURCHASE & HISTORY SECTION ---
                h1, h2 = st.columns(2)
                
                with h1:
                    st.write("**📦 Purchase Requests & Replies**")
                    if not df_pur.empty:
                        # FIX: Filter first, then select ONLY available columns to avoid KeyError
                        job_pur = df_pur[df_pur['job_no'] == job_id]
                        available_cols = [c for c in ['item_name', 'status', 'eta', 'vendor_name'] if c in job_pur.columns]
                        
                        if not job_pur.empty:
                            st.dataframe(job_pur[available_cols], hide_index=True, height=150, use_container_width=True)
                        else:
                            st.info("No active material requests.")
                    else:
                        st.info("Purchase table is empty.")
                    
                    with st.expander("🚨 Trigger New Request"):
                        mc1, mc2, mc3 = st.columns([2, 1, 1])
                        req_item = mc1.text_input("Item Name", key=f"req_{row['id']}")
                        req_qty = mc2.text_input("Qty/Spec", key=f"qty_{row['id']}")
                        if mc3.button("Request", key=f"rqb_{row['id']}"):
                            conn.table("purchase_orders").insert({"job_no": job_id, "item_name": f"SHOP: {req_item}", "specs": req_qty, "status": "Urgent"}).execute()
                            st.toast("Sent to Purchase!"); st.rerun()

                with h2:
                    st.write("**📜 Job Timeline & History**")
                    sub_t1, sub_t2 = st.tabs(["Gates", "Dates"])
                    with sub_t1:
                        if not df_hist.empty: st.table(df_hist[df_hist['job_no'] == job_id].head(3))
                    with sub_t2:
                        if not df_revs.empty: st.table(df_revs[df_revs['job_no'] == job_id].head(3))

                st.divider()

                # --- CONTROL ROW ---
                col1, col2, col3, col4 = st.columns(4)
                new_gate = col1.selectbox("Move Gate", universal_stages, index=prog_idx, key=f"gt_{row['id']}")
                new_limit = col2.number_input("Lead Time (Days/Gate)", min_value=1, value=int(row.get('manual_days_limit', 7)), key=limit_key)
                
                cal_default = pd.to_datetime(current_commitment).date() if current_commitment else practical_eta
                new_promise = col3.date_input("Revise Client Promise", value=cal_default, key=f"dp_{row['id']}")
                new_rem = col4.text_input("Remarks", value=row.get('shortage_details', ""), key=f"rm_{row['id']}")

                if st.button("Sync Status", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    if new_gate != current_stage:
                        conn.table("job_gate_history").insert({"job_no": job_id, "gate_name": current_stage, "days_spent": days_at_gate, "entered_at": updated_at.isoformat()}).execute()
                    
                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate, "manual_days_limit": new_limit, 
                        "revised_dispatch_date": str(new_promise), "shortage_details": new_rem, 
                        "updated_at": datetime.now(IST).isoformat()
                    }).eq("id", row['id']).execute()
                    st.rerun()

# (Tabs 2, 3, 4 remain unchanged)
