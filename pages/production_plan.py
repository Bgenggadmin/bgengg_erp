import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETTINGS & STYLING ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master | B&G", layout="wide", page_icon="🏭")

st.markdown("""
    <style>
    .section-header { background-color: #f8f9fa; padding: 12px; border-radius: 8px; border-left: 5px solid #1f77b4; margin: 15px 0; font-weight: bold; font-size: 18px; }
    .tag-anchor { background-color: #e7f3ff; color: #007bff; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 12px; }
    .tag-prod { background-color: #f0fff4; color: #28a745; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 12px; }
    .stMetric { border: 1px solid #eee; padding: 10px; border-radius: 10px; background: #ffffff; }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=2)
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
tab_plan, tab_fulfillment, tab_reports, tab_masters = st.tabs([
    "🏗️ Production Planning", "🛒 Purchase Fulfillment", "📊 Performance Reports", "⚙️ System Masters"
])

# --- TAB 1: PRODUCTION PLANNING (Metric-Driven Layout) ---
with tab_plan:
    if not df_plan.empty:
        for index, row in df_plan.iterrows():
            db_id = row['id']
            job_id = str(row.get('job_no', 'N/A')).strip().upper()
            
            # Stable Lead Time & ETA Math
            live_limit = row.get('manual_days_limit', 7)
            current_stage = row.get('drawing_status', 'Stage 1')
            prog_idx = universal_stages.index(current_stage) if current_stage in universal_stages else 0
            future_gates = len(universal_stages) - (prog_idx + 1)
            total_days_rem = int(live_limit) + (future_gates * 7)
            practical_eta = (datetime.now(IST) + timedelta(days=total_days_rem)).date()

            with st.container(border=True):
                # HEADER: Identification & Metrics
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row.get('client_name')}")
                
                po_date = row.get('customer_po_date')
                c2.metric("PO Date", str(po_date) if po_date else "N/A")
                
                updated_at = pd.to_datetime(row.get('updated_at', datetime.now(IST)))
                days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
                c3.metric("Days @ Gate", f"{days_at_gate}d", delta=f"Limit: {live_limit}d", delta_color="inverse" if days_at_gate > live_limit else "normal")
                
                rev_disp = row.get('revised_dispatch_date')
                target = pd.to_datetime(rev_disp).date() if rev_disp else practical_eta
                c4.metric("Practical ETA", str(practical_eta), delta=f"{total_days_rem}d Rem.", delta_color="inverse" if practical_eta > target else "normal")
                
                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                # SECTION: SHOP FLOOR LOG ENTRY (Worker Output)
                st.markdown("**👷 Daily Work Entry & Output**")
                w1, w2, w3, w4 = st.columns([1.5, 1, 1.5, 1])
                worker = w1.text_input("Worker Name", key=f"wk_{db_id}", placeholder="Worker ID")
                qty = w2.number_input("Qty Done", min_value=0, step=1, key=f"qy_{db_id}")
                new_gate = w3.selectbox("Shift to Gate", universal_stages, index=prog_idx, key=f"gt_{db_id}")
                
                if w4.button("Sync Work", key=f"sc_{db_id}", use_container_width=True, type="primary"):
                    # 1. Update Project Master
                    conn.table("anchor_projects").update({"drawing_status": new_gate, "updated_at": "now()"}).eq("id", db_id).execute()
                    # 2. Record Worker Performance
                    if worker and qty > 0:
                        conn.table("production").insert({"job_no": job_id, "worker_name": worker, "qty": qty, "gate": current_stage}).execute()
                    st.rerun()

                # SECTION: PRODUCTION PURCHASE TRIGGER
                with st.expander("➕ New Production Material Request"):
                    r1, r2, r3 = st.columns([3, 2, 1])
                    req_item = r1.text_input("Item Name / Spec", key=f"ri_{db_id}", placeholder="Enter details...")
                    req_qty = r2.text_input("Qty / Notes", key=f"rq_{db_id}")
                    if r3.button("Send Request", key=f"rb_{db_id}", use_container_width=True):
                        if req_item:
                            conn.table("purchase_orders").insert({"job_no": job_id, "item_name": f"SHOP: {req_item}", "specs": req_qty, "status": "Urgent"}).execute()
                            st.toast("Triggered to Purchase")

# --- TAB 2: PURCHASE FULFILLMENT (Vertical Stacked Layout) ---
with tab_fulfillment:
    st.subheader("🛒 Procurement Action Center")
    if not df_plan.empty:
        for _, p_row in df_plan.iterrows():
            job_no = p_row['job_no']
            job_items = df_pur[df_pur['job_no'] == job_no] if not df_pur.empty else pd.DataFrame()
            
            with st.expander(f"📦 Job: {job_no} | {p_row.get('client_name')} ({len(job_items)} Items)", expanded=True):
                # Context from Anchor
                st.markdown('<div class="section-header">🚩 Procurement Context</div>', unsafe_allow_html=True)
                st.write(f"**Anchor Notes:** {p_row.get('critical_materials', 'N/A')}")
                
                # Itemized Fulfillment
                st.markdown('<div class="section-header">📋 Itemized Fulfillment</div>', unsafe_allow_html=True)
                for i, i_row in job_items.reset_index().iterrows():
                    k = f"pur_{i_row['id']}_{i}"
                    with st.container(border=True):
                        ic1, ic2, ic3, ic4 = st.columns([1.5, 2, 1, 0.8])
                        # Tagging logic
                        is_prod = "SHOP" in str(i_row['item_name']).upper()
                        ic1.markdown(f"<span class='tag-{'prod' if is_prod else 'anchor'}'>{'🏗️ PROD' if is_prod else '⚓ ANCHOR'}</span>", unsafe_allow_html=True)
                        ic1.write(f"**{i_row['item_name']}**")
                        
                        i_reply = ic2.text_area("Purchase Reply", value=i_row.get('purchase_reply', ""), key=f"rep_{k}", height=68)
                        i_stat = ic3.selectbox("Stat", ["Triggered", "Ordered", "In-Transit", "Received"], key=f"st_{k}")
                        
                        if ic4.button("Save", key=f"sv_{k}", use_container_width=True):
                            conn.table("purchase_orders").update({"purchase_reply": i_reply, "status": i_stat}).eq("id", i_row['id']).execute()
                            st.rerun()

# --- TAB 3: PERFORMANCE REPORTS (Worker Output Logic) ---
with tab_reports:
    st.subheader("📊 Performance & Output Reports")
    if not df_logs.empty:
        c1, c2 = st.columns(2)
        # Worker wise Report
        w_df = df_logs.groupby('worker_name')['qty'].sum().reset_index()
        fig1 = px.bar(w_df, x='worker_name', y='qty', title="Worker Output (Total Units)", color_discrete_sequence=['#28a745'])
        c1.plotly_chart(fig1, use_container_width=True)
        
        # Job wise Report
        j_df = df_logs.groupby('job_no')['qty'].sum().reset_index()
        fig2 = px.bar(j_df, x='job_no', y='qty', title="Job Completion Units", color_discrete_sequence=['#1f77b4'])
        c2.plotly_chart(fig2, use_container_width=True)
        
        st.markdown("### 🕒 Live Production Log")
        st.dataframe(df_logs[['created_at', 'worker_name', 'job_no', 'gate', 'qty', 'notes'] if 'notes' in df_logs.columns else ['created_at', 'worker_name', 'job_no', 'gate', 'qty']], use_container_width=True)
    else:
        st.info("No logs recorded yet.")

# --- TAB 4: SYSTEM MASTERS ---
with tab_masters:
    st.subheader("⚙️ System Configuration")
    m1, m2 = st.columns(2)
    with m1:
        st.write("**Production Gates**")
        st.dataframe(df_gates, use_container_width=True, hide_index=True)
    with m2:
        st.write("**Add New Stage**")
        new_gate = st.text_input("Gate Name")
        if st.button("Add Gate"):
            conn.table("production_gates").insert({"gate_name": new_gate, "step_order": len(universal_stages)+1}).execute()
            st.rerun()
