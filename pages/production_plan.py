import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz

# --- 1. SETTINGS & THEME ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G ERP | Production", layout="wide")

# Professional Industrial Styling
st.markdown("""
    <style>
    .main { background-color: #f4f7f6; }
    .stMetric { background-color: white; border-radius: 10px; padding: 15px; border: 1px solid #e0e0e0; }
    .job-card { background-color: white; padding: 20px; border-radius: 10px; border-left: 6px solid #1f77b4; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .worker-tag { color: #2c3e50; font-weight: bold; background: #ecf0f1; padding: 2px 8px; border-radius: 4px; }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA ORCHESTRATION ---
@st.cache_data(ttl=2)
def load_erp_data():
    # Only fetch what is strictly necessary
    jobs = conn.table("anchor_projects").select("*").eq("status", "Won").order("job_no").execute()
    logs = conn.table("production").select("*").order("created_at", desc=True).execute()
    items = conn.table("purchase_orders").select("*").execute()
    gates = conn.table("production_gates").select("*").order("step_order").execute()
    return pd.DataFrame(jobs.data or []), pd.DataFrame(logs.data or []), pd.DataFrame(items.data or []), pd.DataFrame(gates.data or [])

df_jobs, df_logs, df_items, df_gates = load_erp_data()
gate_list = df_gates['gate_name'].tolist() if not df_gates.empty else ["Stage 1"]

# --- 3. TOP LEVEL NAVIGATION ---
tab_prod, tab_fulfillment, tab_workforce = st.tabs(["🏗️ PRODUCTION CONTROL", "📦 FULFILLMENT CENTER", "📊 WORKFORCE REPORTS"])

# --- TAB 1: PRODUCTION CONTROL (Simplified & Clean) ---
with tab_prod:
    st.subheader("Active Production Pipeline")
    if not df_jobs.empty:
        for _, job in df_jobs.iterrows():
            with st.container():
                st.markdown(f"""<div class='job-card'>
                    <h3>JOB: {job['job_no']} | {job['client_name']}</h3>
                    <p>Current Stage: <b>{job['drawing_status']}</b></p>
                </div>""", unsafe_allow_html=True)
                
                c1, c2, c3 = st.columns([1, 1, 2])
                
                # Move Gate
                new_g = c1.selectbox("Shift Stage", gate_list, 
                                     index=gate_list.index(job['drawing_status']) if job['drawing_status'] in gate_list else 0,
                                     key=f"g_{job['id']}")
                
                # Worker Entry (Integrated Output Logic)
                w_name = c2.text_input("Worker Name", placeholder="Who worked on this?", key=f"w_{job['id']}")
                w_qty = c2.number_input("Qty Done", min_value=0, key=f"q_{job['id']}")
                
                # Save Action
                if c3.button("Confirm Work & Update Stage", key=f"btn_{job['id']}", use_container_width=True, type="primary"):
                    # Update Main Job Status
                    conn.table("anchor_projects").update({"drawing_status": new_g, "updated_at": "now()"}).eq("id", job['id']).execute()
                    
                    # Log Worker Output (Only if name provided)
                    if w_name and w_qty > 0:
                        conn.table("production").insert({
                            "job_no": job['job_no'], "worker_name": w_name, "qty": w_qty, "gate": new_g
                        }).execute()
                    st.rerun()
                st.divider()

# --- TAB 2: FULFILLMENT CENTER (Vertical Stacked Layout) ---
with tab_fulfillment:
    st.subheader("Purchase & Material Fulfillment")
    if not df_jobs.empty:
        for _, job in df_jobs.iterrows():
            job_no = job['job_no']
            relevant_items = df_items[df_items['job_no'] == job_no] if not df_items.empty else pd.DataFrame()
            
            with st.expander(f"📦 MATERIAL REQUESTS: {job_no} ({len(relevant_items)} Items)", expanded=True):
                # 1. Anchor Context
                st.info(f"**Anchor Notes:** {job.get('critical_materials', 'None')}")
                
                # 2. Item Fulfillment List
                if not relevant_items.empty:
                    for i, item in relevant_items.iterrows():
                        ik = f"item_{item['id']}_{i}"
                        with st.container(border=True):
                            r1, r2, r3, r4 = st.columns([1.5, 2, 1, 0.8])
                            r1.write(f"**{item['item_name']}**\n{item.get('specs', '')}")
                            
                            # Vertical Input Fields
                            new_reply = r2.text_input("Purchase Action", value=item.get('purchase_reply', ""), key=f"rep_{ik}")
                            new_stat = r3.selectbox("Status", ["Triggered", "Ordered", "Received"], index=0, key=f"st_{ik}")
                            
                            if r4.button("Update", key=f"upd_{ik}"):
                                conn.table("purchase_orders").update({"purchase_reply": new_reply, "status": new_stat}).eq("id", item['id']).execute()
                                st.rerun()

# --- TAB 3: WORKFORCE REPORTS (Worker Wise / Job Wise) ---
with tab_workforce:
    st.subheader("Worker Productivity Report")
    if not df_logs.empty:
        # Grouping for Worker Performance
        worker_perf = df_logs.groupby('worker_name')['qty'].sum().reset_index()
        st.bar_chart(data=worker_perf, x='worker_name', y='qty')
        
        st.markdown("### Daily Work Log")
        st.dataframe(df_logs[['created_at', 'worker_name', 'job_no', 'qty', 'gate']], use_container_width=True, hide_index=True)
    else:
        st.info("No worker output recorded yet.")
