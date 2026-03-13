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
    # Updated to include worker field
    prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
    pur_res = conn.table("purchase_orders").select("*").execute()
    gate_res = conn.table("production_gates").select("*").order("step_order").execute()
    
    return (pd.DataFrame(plan_res.data or []), pd.DataFrame(prod_res.data or []), 
            pd.DataFrame(pur_res.data or []), pd.DataFrame(gate_res.data or []))

df_plan, df_logs, df_pur, df_gates = get_master_data()
universal_stages = df_gates['gate_name'].tolist() if not df_gates.empty else ["Stage 1"]

# --- 3. TAB NAVIGATION (Updated Headings) ---
tab_plan, tab_entry, tab_reports, tab_masters = st.tabs([
    "🏗️ Production Planning", "🛠️ Shop Floor Log", "📊 Performance Reports", "⚙️ System Masters"
])

# --- TAB 1: PRODUCTION PLANNING (Fulfillment & Gates) ---
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
            practical_eta = (datetime.now(IST) + timedelta(days=int(live_limit) + (future_gates * 7))).date()

            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                
                po_date = row.get('customer_po_date')
                revised_disp = row.get('revised_dispatch_date')
                current_commitment = revised_disp if revised_disp else row.get('promised_dispatch_date')
                
                c2.metric("PO Date", str(po_date) if po_date else "N/A")
                updated_at = pd.to_datetime(row.get('updated_at', datetime.now(IST)))
                days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
                c3.metric("Days @ Gate", f"{days_at_gate}d", delta=f"Limit: {live_limit}d", delta_color="inverse" if days_at_gate > live_limit else "normal")
                c4.metric("Practical ETA", str(practical_eta), delta="Target")
                
                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                st.divider()
                st.markdown("**📦 Fulfillment Status & Material Requests**")
                
                # Purchase Inline List
                job_pur = df_pur[df_pur['job_no'] == job_id] if not df_pur.empty else pd.DataFrame()
                if not job_pur.empty:
                    st.dataframe(job_pur[['item_name', 'status', 'purchase_reply']], hide_index=True, height=100, use_container_width=True)
                
                # Request Form
                r1, r2, r3 = st.columns([3, 2, 1])
                req_item = r1.text_input("Material", key=f"req_name_{db_id}", label_visibility="collapsed", placeholder="Enter Material Required...")
                req_qty = r2.text_input("Spec", key=f"req_qty_{db_id}", label_visibility="collapsed", placeholder="Quantity / Specs...")
                if r3.button("Request", key=f"req_btn_{db_id}", use_container_width=True):
                    if req_item:
                        conn.table("purchase_orders").insert({"job_no": job_id, "item_name": req_item, "specs": req_qty, "status": "Urgent"}).execute()
                        st.rerun()

                st.divider()
                # Production Controls
                ctrl1, ctrl2, ctrl3, ctrl4 = st.columns(4)
                new_gate = ctrl1.selectbox("Move Gate", universal_stages, index=prog_idx, key=f"gt_sel_{db_id}")
                new_limit = ctrl2.number_input("Gate Limit", min_value=1, value=int(row.get('manual_days_limit', 7)), key=limit_key)
                new_promise = ctrl3.date_input("Commitment", value=pd.to_datetime(current_commitment).date() if current_commitment else practical_eta, key=f"dt_prom_{db_id}")
                new_rem = ctrl4.text_input("Shortage/Notes", value=row.get('shortage_details', ""), key=f"txt_rem_{db_id}")

                if st.button("Sync Job Status", key=f"sync_{db_id}", type="primary", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate, "manual_days_limit": new_limit, 
                        "revised_dispatch_date": str(new_promise), "shortage_details": new_rem, 
                        "updated_at": datetime.now(IST).isoformat()
                    }).eq("id", db_id).execute()
                    st.rerun()

# --- TAB 2: SHOP FLOOR LOG (Worker Productivity Entry) ---
with tab_entry:
    st.subheader("⚙️ Worker Daily Output Entry")
    with st.form("worker_log_form", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        w_job = f1.selectbox("Job Number", df_plan['job_no'].unique() if not df_plan.empty else ["None"])
        w_gate = f2.selectbox("Operation/Gate", universal_stages)
        w_name = f3.text_input("Worker Name/ID", placeholder="e.g., Rajesh Kumar")
        
        f4, f5 = st.columns([1, 3])
        w_qty = f4.number_input("Quantity Produced", min_value=1, step=1)
        w_notes = f5.text_input("Process Remarks", placeholder="e.g., Fabrication Complete")
        
        if st.form_submit_button("Submit Production Log", use_container_width=True):
            if w_name:
                conn.table("production").insert({
                    "job_no": w_job, "gate": w_gate, "worker_name": w_name, 
                    "qty": w_qty, "notes": w_notes, "created_at": datetime.now(IST).isoformat()
                }).execute()
                st.success(f"Log saved for {w_name}")
                st.rerun()
            else:
                st.error("Please enter a Worker Name.")

    st.markdown("### 🕒 Recent Activity")
    if not df_logs.empty:
        st.dataframe(df_logs[['created_at', 'job_no', 'worker_name', 'gate', 'qty', 'notes']].head(20), use_container_width=True, hide_index=True)

# --- TAB 3: PERFORMANCE REPORTS (Analytics) ---
with tab_reports:
    st.subheader("📊 Operational Analytics")
    if not df_logs.empty:
        rep1, rep2 = st.columns(2)
        
        # Worker-wise Output
        worker_out = df_logs.groupby('worker_name')['qty'].sum().reset_index()
        fig_worker = px.bar(worker_out, x='worker_name', y='qty', title="Worker-wise Total Output", color='qty')
        rep1.plotly_chart(fig_worker, use_container_width=True)
        
        # Job-wise Output
        job_out = df_logs.groupby(['job_no', 'gate'])['qty'].sum().reset_index()
        fig_job = px.bar(job_out, x='job_no', y='qty', color='gate', title="Job-wise Gate Completion")
        rep2.plotly_chart(fig_job, use_container_width=True)
        
        st.markdown("### 📑 Detailed Output Report")
        st.dataframe(df_logs, use_container_width=True)
    else:
        st.info("No production data available to generate reports.")

# --- TAB 4: SYSTEM MASTERS ---
with tab_masters:
    st.subheader("🛠️ Production Configuration")
    m1, m2 = st.columns(2)
    with m1:
        st.write("**Current Production Gates**")
        st.table(df_gates)
    with m2:
        new_gate = st.text_input("Add New Gate")
        if st.button("Save New Gate"):
            conn.table("production_gates").insert({"gate_name": new_gate, "step_order": len(universal_stages)+1}).execute()
            st.rerun()
