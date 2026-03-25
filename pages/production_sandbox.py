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
@st.cache_data(ttl=300)
def get_master_data():
    try:
        plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        pur_res = conn.table("purchase_orders").select("*").execute()
        gate_res = conn.table("production_gates").select("*").order("step_order").execute()
        
        return (pd.DataFrame(plan_res.data or []), 
                pd.DataFrame(prod_res.data or []), 
                pd.DataFrame(pur_res.data or []),
                pd.DataFrame(gate_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_plan, df_logs, df_pur, df_gates = get_master_data()

# --- 3. DYNAMIC MAPPING ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
all_activities = ["Cutting", "Fitting", "Welding", "Grinding", "Painting", "Assembly", "Buffing", "Others"]

universal_stages = df_gates['gate_name'].tolist() if not df_gates.empty else all_activities

if not df_logs.empty:
    df_logs['Job_Code'] = df_logs['Job_Code'].astype(str).str.strip().str.upper()
    all_workers = sorted(df_logs['Worker'].unique().tolist())
else:
    all_workers = []

all_jobs = sorted(df_plan['job_no'].astype(str).unique().tolist()) if not df_plan.empty else []

# --- 4. NAVIGATION TABS ---
tab_plan, tab_entry, tab_analytics, tab_masters = st.tabs([
    "🏗️ Production Planning", "👷 Daily Work Entry", "📊 Analytics & Shift Report", "🛠️ Manage Masters"
])

# --- TAB 1: PRODUCTION PLANNING ---
with tab_plan:
    st.subheader("🚀 Shop Floor Control Center")
    if not df_plan.empty:
        # Optimization: Pre-calculate man-hours
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for index, row in df_plan.iterrows():
            job_id = str(row['job_no']).strip().upper()
            actual_hrs = hrs_sum.get(job_id, 0)
            
            # Date Parsing Logic
            try:
                updated_at_raw = row.get('updated_at')
                if pd.isna(updated_at_raw):
                    updated_at = datetime.now(IST)
                else:
                    updated_at = pd.to_datetime(updated_at_raw)
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=pytz.UTC)
                    updated_at = updated_at.astimezone(IST)
            except:
                updated_at = datetime.now(IST)

            days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
            manual_limit = row.get('manual_days_limit', 7) 
            current_gate = row.get('drawing_status', universal_stages[0])
            
            prog_idx = universal_stages.index(current_gate) if current_gate in universal_stages else 0
            future_gates_count = len(universal_stages) - (prog_idx + 1)

            with st.container(border=True):
                # UI Layout: Header
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c1.caption(f"🛠️ {row['project_description']}")
                c2.metric("Man-Hours", f"{actual_hrs} Hrs")
                
                is_slow = days_at_gate > manual_limit
                c3.metric("Gate Aging", f"{days_at_gate} Days", 
                          delta=f"Limit: {manual_limit}d" if is_slow else "OK", delta_color="inverse" if is_slow else "normal")
                
                total_days_offset = int(manual_limit) + (future_gates_count * 1) 
                est_completion_date = (datetime.now(IST) + timedelta(days=total_days_offset)).strftime("%d %b %Y")
                c4.metric("Est. Completion", est_completion_date, delta=f"{total_days_offset}d Lead")

                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                # Controls Row
                col1, col2, col3, col4 = st.columns(4)
                new_gate = col1.selectbox("Move Gate", universal_stages, index=prog_idx, key=f"gt_{row['id']}")
                new_limit = col2.number_input("Allowed Days/Gate", min_value=1, value=int(manual_limit), key=f"lim_{row['id']}")
                new_short = col3.toggle("Shortage", value=row.get('material_shortage', False), key=f"sh_{row['id']}")
                new_rem = col4.text_input("Remarks", value=row.get('shortage_details', ""), key=f"rm_{row['id']}")

                st.divider()

                # Materials & Queries Section
                p_col1, p_col2 = st.columns([1, 2]) 
                with p_col1:
                    with st.expander("🛒 New Material Request"):
                        t_item = st.text_input("Item Name", key=f"titem_{row['id']}")
                        t_spec = st.text_input("Specs / Size", key=f"tspec_{row['id']}")
                        if st.button("Send Request", key=f"tbtn_{row['id']}", use_container_width=True):
                            if t_item:
                                conn.table("purchase_orders").insert({
                                    "job_no": job_id, "item_name": t_item, "specs": t_spec, "status": "Triggered"
                                }).execute()
                                conn.table("anchor_projects").update({"purchase_trigger": True}).eq("id", row['id']).execute()
                                st.toast("Request Sent!")
                                st.cache_data.clear(); st.rerun()
                
                with p_col2:
                    st.markdown("**📋 Queries Pending (Job + Anchors)**")
                    if not df_pur.empty:
                        clean_job = str(job_id).strip().upper().replace(".0", "")
                        combined_queries = df_pur[
                            (df_pur['job_no'].astype(str).str.strip().str.upper().replace(".0", "").isin([clean_job, "ANCHORS"])) & 
                            (df_pur['status'] != "Received")
                        ].copy()
                        
                        if not combined_queries.empty:
                            st.dataframe(combined_queries[['item_name', 'status', 'purchase_reply']], height=120, use_container_width=True, hide_index=True)
                        else:
                            st.caption(f"✅ All materials received.")

                if st.button("💾 Save All Changes", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    update_data = {
                        "drawing_status": new_gate,
                        "material_shortage": new_short,
                        "updated_at": datetime.now(IST).isoformat(),
                        "manual_days_limit": new_limit,
                        "shortage_details": new_rem
                    }
                    conn.table("anchor_projects").update(update_data).eq("id", row['id']).execute()
                    st.cache_data.clear(); st.rerun()
