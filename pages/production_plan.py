import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production & Purchase Master | B&G", layout="wide", page_icon="🏭")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS (Full Fetch) ---
@st.cache_data(ttl=2)
def get_unified_data():
    plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
    prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
    pur_res = conn.table("purchase_orders").select("*").execute()
    gate_res = conn.table("production_gates").select("*").order("step_order").execute()
    
    return (pd.DataFrame(plan_res.data or []), pd.DataFrame(prod_res.data or []), 
            pd.DataFrame(pur_res.data or []), pd.DataFrame(gate_res.data or []))

df_plan, df_logs, df_pur, df_gates = get_unified_data()
universal_stages = df_gates['gate_name'].tolist() if not df_gates.empty else ["Stage 1"]

# --- 3. NAVIGATION ---
tab_prod, tab_fulfillment, tab_workforce, tab_masters = st.tabs([
    "🏗️ Production Control", "🛒 Purchase Fulfillment", "📊 Performance Reports", "⚙️ System Masters"
])

# --- TAB 1: PRODUCTION CONTROL (With Integrated Worker Output) ---
with tab_prod:
    if not df_plan.empty:
        for index, row in df_plan.iterrows():
            db_id = row['id']
            job_id = str(row.get('job_no', 'N/A')).strip().upper()
            
            with st.container(border=True):
                # Header Section
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.subheader(f"Job {job_id} | {row.get('client_name', 'Client')}")
                
                # Progress Logic
                curr_stage = row.get('drawing_status', 'Stage 1')
                prog_idx = universal_stages.index(curr_stage) if curr_stage in universal_stages else 0
                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                # Input Section: Worker & Gate
                st.markdown("**🛠️ Shop Floor Progress Update**")
                col_a, col_b, col_c, col_d = st.columns([1.5, 1.5, 1, 1])
                
                w_name = col_a.text_input("Worker Name", key=f"wn_{db_id}", placeholder="Worker Identity")
                w_qty = col_b.number_input("Qty Processed", min_value=0, key=f"wq_{db_id}")
                new_gate = col_c.selectbox("Next Gate", universal_stages, index=prog_idx, key=f"ng_{db_id}")
                
                # Material Request (Integrated)
                with st.expander("➕ Need Material? (Production Request)"):
                    r1, r2, r3 = st.columns([2, 1, 1])
                    req_item = r1.text_input("Item Name", key=f"ri_{db_id}")
                    req_qty = r2.text_input("Qty/Spec", key=f"rq_{db_id}")
                    if r3.button("Send Request", key=f"rb_{db_id}"):
                        if req_item:
                            conn.table("purchase_orders").insert({"job_no": job_id, "item_name": f"SHOP-FLOOR: {req_item}", "specs": req_qty, "status": "Urgent"}).execute()
                            st.toast("Request Sent to Purchase")

                # Sync Button
                if st.button("Save Progress & Work Log", key=f"sync_{db_id}", type="primary", use_container_width=True):
                    # 1. Update Job Master
                    conn.table("anchor_projects").update({"drawing_status": new_gate, "updated_at": "now()"}).eq("id", db_id).execute()
                    # 2. Log Worker Output
                    if w_name and w_qty > 0:
                        conn.table("production").insert({"job_no": job_id, "worker_name": w_name, "qty": w_qty, "gate": curr_stage}).execute()
                    st.rerun()

# --- TAB 2: PURCHASE FULFILLMENT (Vertical Stacked Layout) ---
with tab_fulfillment:
    st.subheader("🛒 Procurement Action Center")
    if not df_plan.empty:
        for _, job in df_plan.iterrows():
            job_no = job['job_no']
            job_items = df_items[df_items['job_no'] == job_no] if not df_items.empty else pd.DataFrame()
            
            with st.expander(f"📦 Job: {job_no} | {job.get('client_name')} ({len(job_items)} Items)", expanded=True):
                st.write(f"**Anchor Context:** {job.get('critical_materials', 'None')}")
                
                for i, item in job_items.reset_index().iterrows():
                    k = f"pur_{item['id']}_{i}"
                    with st.container(border=True):
                        ic1, ic2, ic3, ic4 = st.columns([1.5, 2, 1, 0.8])
                        
                        # Source Tagging
                        tag = "🏗️ PROD" if "SHOP-FLOOR" in str(item['item_name']) else "⚓ ANCHOR"
                        ic1.markdown(f"**{tag}**\n{item['item_name']}")
                        
                        i_reply = ic2.text_area("Purchase Reply", value=item.get('purchase_reply', ""), key=f"rep_{k}", height=65)
                        i_stat = ic3.selectbox("Status", ["Triggered", "Ordered", "Received", "Urgent"], 
                                              index=0, key=f"st_{k}")
                        
                        if ic4.button("Update", key=f"up_{k}"):
                            conn.table("purchase_orders").update({"purchase_reply": i_reply, "status": i_stat}).eq("id", item['id']).execute()
                            st.rerun()

# --- TAB 3: PERFORMANCE REPORTS ---
with tab_reports:
    st.subheader("📊 Operational Analytics")
    if not df_logs.empty:
        c1, c2 = st.columns(2)
        # Worker Output
        w_perf = df_logs.groupby('worker_name')['qty'].sum().reset_index()
        c1.plotly_chart(px.bar(w_perf, x='worker_name', y='qty', title="Total Output per Worker"), use_container_width=True)
        # Job Output
        j_perf = df_logs.groupby('job_no')['qty'].sum().reset_index()
        c2.plotly_chart(px.bar(j_perf, x='job_no', y='qty', title="Units Completed per Job"), use_container_width=True)
        
        st.markdown("### 📋 Daily Activity Log")
        st.dataframe(df_logs, use_container_width=True, hide_index=True)

# --- TAB 4: SYSTEM MASTERS ---
with tab_masters:
    st.subheader("⚙️ System Configuration")
    m1, m2 = st.columns(2)
    with m1:
        st.write("Current Gates")
        st.dataframe(df_gates, use_container_width=True)
    with m2:
        new_g = st.text_input("New Gate Name")
        if st.button("Add Gate"):
            conn.table("production_gates").insert({"gate_name": new_g, "step_order": len(universal_stages)+1}).execute()
            st.rerun()
