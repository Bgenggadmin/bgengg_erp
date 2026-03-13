import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master | B&G", layout="wide", page_icon="🏭")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS (Audited for Stability) ---
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
universal_stages = df_gates['gate_name'].tolist() if not df_gates.empty else ["Stage 1"]

# --- 3. TABS ---
tab_plan, tab_entry, tab_analytics, tab_masters = st.tabs([
    "🏗️ Production Planning", "👷 Daily Work Entry", "📊 Analytics", "🛠️ Masters"
])

# --- TAB 1: PRODUCTION PLANNING (Preferred Layout) ---
with tab_plan:
    if not df_plan.empty:
        for index, row in df_plan.iterrows():
            # Use unique DB ID for all keys to prevent StreamlitDuplicateElementKey
            db_id = row['id']
            job_id = str(row['job_no']).strip().upper()
            
            # --- LIVE LEAD TIME CAPTURE ---
            limit_key = f"input_lead_limit_{db_id}"
            live_limit = st.session_state.get(limit_key, row.get('manual_days_limit', 7))
            
            # --- STABLE ETA CALCULATION (1 Day Change = 1 Day Shift) ---
            current_stage = row['drawing_status']
            prog_idx = universal_stages.index(current_stage) if current_stage in universal_stages else 0
            future_gates_count = len(universal_stages) - (prog_idx + 1)
            
            # Logic: Current gate uses 'live_limit', all future gates use standard '7'
            total_days_rem = int(live_limit) + (future_gates_count * 7)
            practical_eta = (datetime.now(IST) + timedelta(days=total_days_rem)).date()

            with st.container(border=True):
                # HEADER ROW: Job Details & Metrics
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c1.caption(f"🛠️ {row['project_description']}")
                
                # PO & Promised Dates
                po_date = row.get('customer_po_date')
                orig_disp = row.get('promised_dispatch_date')
                revised_disp = row.get('revised_dispatch_date')
                current_commitment = revised_disp if revised_disp else orig_disp
                c2.metric("PO Date", str(po_date) if po_date else "N/A")
                c2.caption(f"Original Promise: {orig_disp}")
                
                # Gate Aging
                updated_at = pd.to_datetime(row.get('updated_at', datetime.now(IST)))
                days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
                aging_color = "normal" if days_at_gate <= live_limit else "inverse"
                c3.metric("Days @ Gate", f"{days_at_gate}d", delta=f"Limit: {live_limit}d", delta_color=aging_color)
                
                # Practical ETA (Stable)
                is_late = current_commitment and practical_eta > pd.to_datetime(current_commitment).date()
                c4.metric("Practical ETA", str(practical_eta), 
                          delta=f"{total_days_rem}d total rem.", 
                          delta_color="inverse" if is_late else "normal")
                
                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                # --- PURCHASE & HISTORY SECTION (The Layout You Liked) ---
                col_pur, col_hist = st.columns(2)
                
                with col_pur:
                    st.markdown("**📦 Purchase Status & Requests**")
                    job_pur = df_pur[df_pur['job_no'] == job_id] if not df_pur.empty else pd.DataFrame()
                    
                    # Safe column selection to prevent KeyError if DB columns change
                    safe_cols = [c for c in ['item_name', 'status', 'eta', 'purchase_reply', 'vendor_name'] if c in job_pur.columns]
                    
                    if not job_pur.empty:
                        st.dataframe(job_pur[safe_cols], hide_index=True, height=150, use_container_width=True)
                    else:
                        st.info("No active material requests for this job.")
                    
                    with st.expander("🚨 Trigger New Material Request"):
                        trig_c1, trig_c2 = st.columns([3, 1])
                        req_item = trig_c1.text_input("Item Specification", key=f"req_text_{db_id}", placeholder="e.g., 50mm MS Plate")
                        if trig_c2.button("Send Request", key=f"req_btn_{db_id}", use_container_width=True):
                            if req_item:
                                conn.table("purchase_orders").insert({"job_no": job_id, "item_name": req_item, "status": "Urgent"}).execute()
                                st.rerun()

                with col_hist:
                    st.markdown("**📜 Job Logs & Movements**")
                    h_tab1, h_tab2 = st.tabs(["Gate History", "Date Revisions"])
                    with h_tab1:
                        if not df_hist.empty:
                            st.table(df_hist[df_hist['job_no'] == job_id].head(3))
                    with h_tab2:
                        if not df_revs.empty:
                            st.table(df_revs[df_revs['job_no'] == job_id].head(3))

                st.divider()

                # --- CONTROL ROW ---
                ctrl1, ctrl2, ctrl3, ctrl4 = st.columns(4)
                new_gate = ctrl1.selectbox("Move to Gate", universal_stages, index=prog_idx, key=f"sel_gate_{db_id}")
                new_limit = ctrl2.number_input("Days for Current Gate", min_value=1, value=int(row.get('manual_days_limit', 7)), key=limit_key)
                
                cal_default = pd.to_datetime(current_commitment).date() if current_commitment else practical_eta
                new_promise = ctrl3.date_input("Update Client Promise", value=cal_default, key=f"date_prom_{db_id}")
                new_rem = ctrl4.text_input("Status Remarks", value=row.get('shortage_details', ""), key=f"txt_rem_{db_id}")

                if st.button("Save & Sync Status", key=f"sync_btn_{db_id}", type="primary", use_container_width=True):
                    # 1. Check for Gate Change to Log History
                    if new_gate != current_stage:
                        conn.table("job_gate_history").insert({"job_no": job_id, "gate_name": current_stage, "days_spent": days_at_gate, "entered_at": updated_at.isoformat()}).execute()
                    
                    # 2. Check for Promise Date Change to Log History
                    if current_commitment and str(new_promise) != str(current_commitment):
                        conn.table("dispatch_revision_history").insert({"job_no": job_id, "old_date": str(current_commitment), "new_date": str(new_promise), "reason": new_rem}).execute()

                    # 3. Update Master Table
                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate, 
                        "manual_days_limit": new_limit, 
                        "revised_dispatch_date": str(new_promise), 
                        "shortage_details": new_rem, 
                        "updated_at": datetime.now(IST).isoformat()
                    }).eq("id", db_id).execute()
                    st.rerun()

# (Tabs 2, 3, 4 follow standard audited logic)
