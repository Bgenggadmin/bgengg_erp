import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz

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
    
    return (pd.DataFrame(plan_res.data or []), pd.DataFrame(prod_res.data or []), 
            pd.DataFrame(pur_res.data or []), pd.DataFrame(gate_res.data or []))

df_plan, df_logs, df_pur, df_gates = get_master_data()
universal_stages = df_gates['gate_name'].tolist() if not df_gates.empty else ["Stage 1"]

# --- 3. TAB NAVIGATION ---
tab_plan, tab_entry, tab_analytics, tab_masters = st.tabs([
    "🏗️ Production Planning", "👷 Daily Work Entry", "📊 Analytics", "🛠️ Masters"
])

# --- TAB 1: PRODUCTION PLANNING (Simplified & Aligned) ---
with tab_plan:
    if not df_plan.empty:
        for index, row in df_plan.iterrows():
            db_id = row['id']
            job_id = str(row['job_no']).strip().upper()
            
            # --- LIVE LEAD TIME & STABLE ETA ---
            limit_key = f"ld_lim_{db_id}"
            live_limit = st.session_state.get(limit_key, row.get('manual_days_limit', 7))
            
            current_stage = row['drawing_status']
            prog_idx = universal_stages.index(current_stage) if current_stage in universal_stages else 0
            future_gates = len(universal_stages) - (prog_idx + 1)
            
            # Stable Math: 1 day change = 1 day shift
            total_days_rem = int(live_limit) + (future_gates * 7)
            practical_eta = (datetime.now(IST) + timedelta(days=total_days_rem)).date()

            with st.container(border=True):
                # --- HEADER: IDENTIFICATION & METRICS ---
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                
                po_date = row.get('customer_po_date')
                orig_disp = row.get('promised_dispatch_date')
                revised_disp = row.get('revised_dispatch_date')
                current_commitment = revised_disp if revised_disp else orig_disp
                
                c2.metric("PO Date", str(po_date) if po_date else "N/A")
                
                updated_at = pd.to_datetime(row.get('updated_at', datetime.now(IST)))
                days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
                aging_color = "normal" if days_at_gate <= live_limit else "inverse"
                c3.metric("Days @ Gate", f"{days_at_gate}d", delta=f"Limit: {live_limit}d", delta_color=aging_color)
                
                is_late = current_commitment and practical_eta > pd.to_datetime(current_commitment).date()
                c4.metric("Practical ETA", str(practical_eta), 
                          delta=f"{total_days_rem}d Remaining", 
                          delta_color="inverse" if is_late else "normal")
                
                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                st.divider()

                # --- PURCHASE SECTION (Wider & Better Aligned) ---
                st.markdown("**📦 Purchase Status & New Material Requests**")
                
                # Show existing requests
                job_pur = df_pur[df_pur['job_no'] == job_id] if not df_pur.empty else pd.DataFrame()
                safe_cols = [c for c in ['item_name', 'status', 'eta', 'purchase_reply', 'vendor_name'] if c in job_pur.columns]
                
                if not job_pur.empty:
                    st.dataframe(job_pur[safe_cols], hide_index=True, height=120, use_container_width=True)
                
                # Simple Request Line (Well Aligned)
                r1, r2, r3 = st.columns([3, 2, 1])
                req_item = r1.text_input("Item Name / Specification", key=f"req_name_{db_id}", label_visibility="collapsed", placeholder="Enter Item Required...")
                req_qty = r2.text_input("Qty / Notes", key=f"req_qty_{db_id}", label_visibility="collapsed", placeholder="Quantity or Spec...")
                if r3.button("Request Item", key=f"req_btn_{db_id}", use_container_width=True, type="secondary"):
                    if req_item:
                        conn.table("purchase_orders").insert({
                            "job_no": job_id, 
                            "item_name": req_item, 
                            "specs": req_qty,
                            "status": "Urgent"
                        }).execute()
                        st.rerun()

                st.divider()

                # --- PRODUCTION CONTROLS ---
                ctrl1, ctrl2, ctrl3, ctrl4 = st.columns(4)
                new_gate = ctrl1.selectbox("Move Gate", universal_stages, index=prog_idx, key=f"gt_sel_{db_id}")
                new_limit = ctrl2.number_input("Gate Lead Time (Days)", min_value=1, value=int(row.get('manual_days_limit', 7)), key=limit_key)
                
                cal_default = pd.to_datetime(current_commitment).date() if current_commitment else practical_eta
                new_promise = ctrl3.date_input("Client Commitment", value=cal_default, key=f"dt_prom_{db_id}")
                new_rem = ctrl4.text_input("Shortage / Remarks", value=row.get('shortage_details', ""), key=f"txt_rem_{db_id}")

                if st.button("Update Job Status", key=f"sync_{db_id}", type="primary", use_container_width=True):
                    # History check for gate change
                    if new_gate != current_stage:
                        conn.table("job_gate_history").insert({
                            "job_no": job_id, "gate_name": current_stage, 
                            "days_spent": days_at_gate, "entered_at": updated_at.isoformat()
                        }).execute()
                    
                    # Master update
                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate, 
                        "manual_days_limit": new_limit, 
                        "revised_dispatch_date": str(new_promise), 
                        "shortage_details": new_rem, 
                        "updated_at": datetime.now(IST).isoformat()
                    }).eq("id", db_id).execute()
                    st.rerun()
