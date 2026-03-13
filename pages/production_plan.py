import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. CONFIGURATION ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Master | B&G", layout="wide", page_icon="🏭")

st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .section-header { background-color: #ffffff; padding: 12px; border-radius: 8px; border-left: 6px solid #1f77b4; margin-bottom: 15px; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .tag-anchor { background-color: #e7f3ff; color: #007bff; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 11px; text-transform: uppercase; }
    .tag-prod { background-color: #f0fff4; color: #28a745; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 11px; text-transform: uppercase; }
    .stMetric { border: 1px solid #eef0f2; padding: 15px; border-radius: 10px; background: white; }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA ORCHESTRATION ---
@st.cache_data(ttl=2)
def get_all_data():
    try:
        plan = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        logs = conn.table("production").select("*").order("created_at", desc=True).execute()
        pur = conn.table("purchase_orders").select("*").execute()
        gates = conn.table("production_gates").select("*").order("step_order").execute()
        return (pd.DataFrame(plan.data or []), pd.DataFrame(logs.data or []), 
                pd.DataFrame(pur.data or []), pd.DataFrame(gates.data or []))
    except Exception as e:
        st.error(f"Database Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_plan, df_logs, df_pur, df_gates = get_all_data()
universal_stages = df_gates['gate_name'].tolist() if not df_gates.empty else ["Stage 1"]

# --- 3. NAVIGATION ---
tab_plan, tab_fulfillment, tab_reports, tab_masters = st.tabs([
    "🏗️ PRODUCTION PLANNING", "🛒 PURCHASE FULFILLMENT", "📊 PERFORMANCE REPORTS", "⚙️ SYSTEM MASTERS"
])

# --- TAB 1: PRODUCTION PLANNING (Metric & Log Logic) ---
with tab_plan:
    if df_plan.empty:
        st.info("No active 'Won' projects found.")
    else:
        for idx, row in df_plan.iterrows():
            db_id = row['id']
            job_id = str(row.get('job_no', 'N/A')).strip().upper()
            
            # --- AGING & ETA LOGIC ---
            live_limit = row.get('manual_days_limit', 7)
            curr_stage = row.get('drawing_status', 'Stage 1')
            prog_idx = universal_stages.index(curr_stage) if curr_stage in universal_stages else 0
            
            gates_left = len(universal_stages) - (prog_idx + 1)
            eta_days = int(live_limit) + (gates_left * 7)
            practical_eta = (datetime.now(IST) + timedelta(days=eta_days)).date()
            
            updated_at = pd.to_datetime(row.get('updated_at', datetime.now(IST)))
            days_spent = (datetime.now(IST).date() - updated_at.date()).days

            with st.container(border=True):
                m1, m2, m3, m4 = st.columns([2, 1, 1, 1])
                m1.subheader(f"JOB {job_id} | {row.get('client_name', 'Client')}")
                m2.metric("PO Date", str(row.get('customer_po_date', 'N/A')))
                m3.metric("Days @ Gate", f"{days_spent}d", delta=f"Limit: {live_limit}d", delta_color="inverse" if days_spent > live_limit else "normal")
                m4.metric("Practical ETA", str(practical_eta), delta=f"{eta_days}d Rem.")
                
                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                # --- WORKER ENTRY ---
                c1, c2, c3, c4 = st.columns([1.5, 1, 1.5, 1])
                w_name = c1.text_input("Worker Name", key=f"plan_w_{db_id}_{idx}")
                w_qty = c2.number_input("Qty Done", min_value=0, step=1, key=f"plan_q_{db_id}_{idx}")
                new_gate = c3.selectbox("Move to Stage", universal_stages, index=prog_idx, key=f"plan_g_{db_id}_{idx}")
                
                if c4.button("Sync Job", key=f"plan_b_{db_id}_{idx}", type="primary", use_container_width=True):
                    # Update Main Project Stage
                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate, "updated_at": "now()"
                    }).eq("id", db_id).execute()
                    
                    # Log the production effort
                    if w_name and w_qty > 0:
                        conn.table("production").insert({
                            "job_no": job_id, "worker_name": w_name, "qty": w_qty, "gate": curr_stage
                        }).execute()
                    st.rerun()

# --- TAB 2: PURCHASE FULFILLMENT (Vertical Layout) ---
with tab_fulfillment:
    if not df_plan.empty:
        for p_idx, p_row in df_plan.iterrows():
            job_no = p_row['job_no']
            items = df_pur[df_pur['job_no'] == job_no] if not df_pur.empty else pd.DataFrame()
            
            with st.expander(f"📦 {job_no} | {p_row.get('client_name')} ({len(items)} Items)", expanded=True):
                st.markdown('<div class="section-header">🚩 Procurement Context</div>', unsafe_allow_html=True)
                st.write(f"**Anchor Notes:** {p_row.get('critical_materials', 'No notes.')}")
                
                if not items.empty:
                    for i, i_row in items.reset_index().iterrows():
                        k = f"ful_{p_idx}_{i_row['id']}_{i}"
                        with st.container(border=True):
                            ic1, ic2, ic3, ic4 = st.columns([1.5, 2, 1, 0.8])
                            
                            is_shop = "PROD:" in str(i_row['item_name'])
                            ic1.markdown(f"<span class='tag-{'prod' if is_shop else 'anchor'}'>{'🏗️ PROD' if is_shop else '⚓ ANCHOR'}</span>", unsafe_allow_html=True)
                            ic1.write(f"**{i_row['item_name']}**")
                            
                            # FIXED: Added height and clear labels to the reply area
                            p_reply = ic2.text_area("Reply", value=i_row.get('purchase_reply', "") or "", key=f"rep_{k}", height=68, label_visibility="collapsed")
                            
                            p_opts = ["Triggered", "Ordered", "Received", "Shortage"]
                            curr_v = i_row.get('status', "Triggered")
                            v_idx = p_opts.index(curr_v) if curr_v in p_opts else 0
                            p_status = ic3.selectbox("Status", p_opts, index=v_idx, key=f"stat_{k}", label_visibility="collapsed")
                            
                            if ic4.button("Update", key=f"upd_{k}", use_container_width=True):
                                conn.table("purchase_orders").update({
                                    "purchase_reply": p_reply, "status": p_status
                                }).eq("id", i_row['id']).execute()
                                st.rerun()

# --- TAB 3: REPORTS (Anti-Crash Logic) ---
with tab_reports:
    if not df_logs.empty and 'worker_name' in df_logs.columns:
        rep1, rep2 = st.columns(2)
        # Worker Output
        w_out = df_logs.groupby('worker_name')['qty'].sum().reset_index()
        rep1.plotly_chart(px.bar(w_out, x='worker_name', y='qty', title="Worker Productivity", color_discrete_sequence=['#28a745']), use_container_width=True)
        # Job Output
        j_out = df_logs.groupby('job_no')['qty'].sum().reset_index()
        rep2.plotly_chart(px.bar(j_out, x='job_no', y='qty', title="Job Completion Units", color_discrete_sequence=['#1f77b4']), use_container_width=True)
        
        st.dataframe(df_logs, use_container_width=True, hide_index=True)
    else:
        st.info("Sync some work in Tab 1 to see performance charts.")

# --- TAB 4: MASTERS ---
with tab_masters:
    m1, m2 = st.columns(2)
    m1.dataframe(df_gates[['gate_name', 'step_order']] if not df_gates.empty else [])
    new_g = m2.text_input("New Gate Name")
    if m2.button("Add Gate"):
        if new_g:
            conn.table("production_gates").insert({"gate_name": new_g, "step_order": len(universal_stages)+1}).execute()
            st.rerun()
