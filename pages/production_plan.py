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
@st.cache_data(ttl=300)
def get_master_data():
    try:
        # Fetching all columns to ensure logic works
        plan_res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
        
        # Production logs
        prod_res = conn.table("production").select("*").order("created_at", desc=True).execute()
        
        # Purchase data
        pur_res = conn.table("purchase_orders").select("*").execute()
        
        # Gates/Stages
        gate_res = conn.table("production_gates").select("*").order("step_order").execute()
        
        return (pd.DataFrame(plan_res.data or []), 
                pd.DataFrame(prod_res.data or []), 
                pd.DataFrame(pur_res.data or []),
                pd.DataFrame(gate_res.data or []))
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

df_plan, df_logs, df_pur, df_gates = get_master_data()

# --- 3. DYNAMIC MAPPING & CONSTANTS ---
base_supervisors = ["RamaSai", "Ravindra", "Subodth", "Prasanth", "SUNIL"]
all_activities = ["Cutting", "Fitting", "Welding", "Grinding", "Painting", "Assembly", "Buffing", "Others"]

if not df_gates.empty:
    universal_stages = df_gates['gate_name'].tolist()
else:
    universal_stages = all_activities

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
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for index, row in df_plan.iterrows():
            job_id = str(row['job_no']).strip().upper()
            actual_hrs = hrs_sum.get(job_id, 0)
            
            try:
                updated_at = pd.to_datetime(row.get('updated_at'))
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
                col1, col2, col3, col4 = st.columns(4)
                new_gate = col1.selectbox("Move Gate", universal_stages, index=prog_idx, key=f"gt_{row['id']}")
                new_limit = col2.number_input("Allowed Days/Gate", min_value=1, value=int(manual_limit), key=f"lim_{row['id']}")
                new_short = col3.toggle("Shortage", value=row.get('material_shortage', False), key=f"sh_{row['id']}")
                new_rem = col4.text_input("Remarks", value=row.get('shortage_details', ""), key=f"rm_{row['id']}")

                total_days_offset = new_limit + (future_gates_count * 1) 
                est_completion_date = (datetime.now(IST) + timedelta(days=total_days_offset)).strftime("%d %b %Y")

                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c1.caption(f"🛠️ {row['project_description']}")
                c2.metric("Man-Hours", f"{actual_hrs} Hrs")
                
                is_slow = days_at_gate > manual_limit
                c3.metric("Gate Aging", f"{days_at_gate} Days", 
                          delta=f"Limit: {manual_limit}d" if is_slow else "OK", delta_color="inverse" if is_slow else "normal")
                c4.metric("Est. Completion", est_completion_date, delta=f"{total_days_offset}d Lead")

                st.progress((prog_idx + 1) / len(universal_stages) if universal_stages else 0)

                st.markdown("---")
                p_col1, p_col2 = st.columns([1, 1])
                
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
                                st.toast("Request Sent!"); st.rerun()
                
                with p_col2:
                    st.markdown("**💬 Production Queries**")
                    if not df_pur.empty:
                        # FILTER: Match Job ID and EXCLUDE 'Received' status
                        # This ensures only active bottlenecks are shown
                        job_queries = df_pur[
                            (df_pur['job_no'].astype(str).str.strip().str.upper() == job_id) & 
                            (df_pur['status'] != "Received")
                        ]
                        
                        if not job_queries.empty:
                            # Show top 3 pending queries
                            for _, p_item in job_queries.head(3).iterrows():
                                b_color = "#FF4B4B" if p_item['status'] == "Urgent" else "#FFA500"
                                st.markdown(f"""
                                    <div style="border-left: 4px solid {b_color}; padding-left: 10px; background-color: #fefefe; border: 1px solid #eee; border-radius: 4px; margin-bottom:5px;">
                                        <b style="color:#333;">{p_item['item_name']}</b>: {p_item['status']}<br>
                                        <small style="color:#d32f2f;"><b>Reply:</b> {p_item.get('purchase_reply', 'Pending Action')}</small>
                                    </div>""", unsafe_allow_html=True)
                        else:
                            st.caption("✅ No pending material queries.")
                    else:
                        st.caption("No purchase data available.")

                # --- MOVE GATE / STATUS UPDATE BUTTON ---
                st.write("") 
                if st.button("💾 Update Master Status", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    try:
                        update_data = {
                            "drawing_status": new_gate,
                            "material_shortage": new_short,
                            "updated_at": datetime.now(IST).isoformat()
                        }
                        # Add optional columns safely
                        if 'manual_days_limit' in df_plan.columns:
                            update_data["manual_days_limit"] = new_limit
                        if 'shortage_details' in df_plan.columns:
                            update_data["shortage_details"] = new_rem

                        conn.table("anchor_projects").update(update_data).eq("id", row['id']).execute()
                        st.cache_data.clear()
                        st.toast("✅ Master Status Updated!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update Failed: {e}")
# --- TAB 2: DAILY WORK ENTRY ---
with tab_entry:
    st.subheader("👷 Labor Output Entry")
    unit_map = {
        "Welding": "MTs", "Buffing": "Sq.Ft", "Painting": "Sq.Ft",
        "Cutting": "Nos", "Fitting": "Nos", "Grinding": "Nos",
        "Assembly": "Nos", "Others": "Nos"
    }

    f_act = st.selectbox("Select Activity first", all_activities, key="act_main")
    current_unit = unit_map.get(f_act, "Nos")

    with st.form("prod_form", clear_on_submit=True):
        f1, f2, f3 = st.columns(3)
        f_sup = f1.selectbox("Supervisor", base_supervisors)
        f_wrk = f1.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
        f_job = f2.selectbox("Job Code", ["-- Select --"] + all_jobs)
        f2.info(f"Unit: {current_unit}")
        f_hrs = f3.number_input("Hours Spent", min_value=0.0, step=0.5)
        f_out = f3.number_input(f"Output ({current_unit})", min_value=0.0)
        f_nts = st.text_area("Task Details")

        if st.form_submit_button("🚀 Log Productivity", use_container_width=True):
            if f_act == "Others" and not f_nts.strip():
                st.error("⚠️ Please provide details in 'Task Details' for 'Others'.")
            elif "-- Select --" in [f_wrk, f_job]:
                st.error("❌ Please select Worker and Job Code.")
            else:
                try:
                    conn.table("production").insert({
                        "Supervisor": f_sup, "Worker": f_wrk, "Job_Code": f_job,
                        "Activity": f_act, "Hours": f_hrs, "Output": f_out, 
                        "Notes": f_nts, "Unit": current_unit 
                    }).execute()
                    st.cache_data.clear()
                    st.success(f"✅ Logged {f_out} {current_unit}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Database Error: {e}")

# --- TAB 3: ANALYTICS ---
with tab_analytics:
    if not df_logs.empty and 'created_at' in df_logs.columns:
        st.subheader("📅 Today's Shift Report")
        df_logs['created_at'] = pd.to_datetime(df_logs['created_at'], errors='coerce').dropna()
        
        if df_logs['created_at'].dt.tz is None:
            df_logs['created_at'] = df_logs['created_at'].dt.tz_localize('UTC')
        df_logs['created_at'] = df_logs['created_at'].dt.tz_convert(IST)
        
        today_logs = df_logs[df_logs['created_at'].dt.date == datetime.now(IST).date()]
        if not today_logs.empty:
            st.dataframe(today_logs[['created_at', 'Worker', 'Job_Code', 'Activity', 'Hours', 'Notes']], hide_index=True)
        else:
            st.info("No entries for today.")
    else:
        st.warning("No logs found.")

# --- TAB 4: MANAGE MASTERS ---
with tab_masters:
    st.subheader("🛠️ Master Registration")
    m1, m2 = st.columns(2)
    with m1:
        new_w = st.text_input("Register Worker")
        if st.button("Add Person") and new_w:
            conn.table("production").insert({"Worker": new_w, "Notes": "SYSTEM_NEW_ITEM", "Hours": 0, "Activity": "N/A", "Job_Code": "N/A"}).execute()
            st.cache_data.clear(); st.rerun()
    with m2:
        if not df_gates.empty:
            st.write("Production Gates:")
            st.dataframe(df_gates[['step_order', 'gate_name']], hide_index=True)
