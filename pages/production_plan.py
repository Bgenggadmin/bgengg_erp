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
                                st.rerun()
                
                with p_col2:
                    st.markdown("**📋 Queries Pending (Job + Anchors)**")
                    if not df_pur.empty:
                        current_id = str(job_id).strip().upper().replace(".0", "")
                        combined_queries = df_pur[
                            (df_pur['job_no'].astype(str).str.strip().str.upper().replace(".0", "").isin([current_id, "ANCHORS"])) & 
                            (df_pur['status'] != "Received")
                        ].copy()
                        
                        if not combined_queries.empty:
                            combined_queries['Source'] = combined_queries['job_no'].apply(
                                lambda x: "⚓ ANCHOR" if str(x).strip().upper() == "ANCHORS" else f"🏗️ {current_id}"
                            )
                            combined_queries['purchase_reply'] = combined_queries['purchase_reply'].fillna("⏳ Awaiting Update")
                            
                            st.dataframe(
                                combined_queries[['Source', 'item_name', 'status', 'purchase_reply']],
                                column_config={
                                    "Source": st.column_config.TextColumn("Origin", width="small"),
                                    "item_name": st.column_config.TextColumn("Item Name", width="medium"),
                                    "status": st.column_config.TextColumn("Status", width="small"),
                                    "purchase_reply": st.column_config.TextColumn("Purchase Reply", width="large"),
                                },
                                hide_index=True,
                                use_container_width=True,
                                height=150
                            )
                        else:
                            st.caption(f"✅ No pending queries for {current_id} or Anchors.")

                st.write("") 
                if st.button("💾 Update Master Status", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    try:
                        update_data = {
                            "drawing_status": new_gate,
                            "material_shortage": new_short,
                            "updated_at": datetime.now(IST).isoformat()
                        }
                        if 'manual_days_limit' in df_plan.columns:
                            update_data["manual_days_limit"] = new_limit
                        if 'shortage_details' in df_plan.columns:
                            update_data["shortage_details"] = new_rem

                        conn.table("anchor_projects").update(update_data).eq("id", row['id']).execute()
                        st.cache_data.clear()
                        st.success("Updated!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update Failed: {e}")

# --- TAB 2: DAILY WORK ENTRY ---
with tab_entry:
    st.subheader("👷 Labor Output Entry")
    
    unit_map = {
        "Welding": "MTs", 
        "Buffing": "Sq.Ft", 
        "Painting": "Sq.Ft",
        "Cutting": "Nos", 
        "Fitting": "Nos", 
        "Grinding": "Nos",
        "Assembly": "Nos", 
        "Others": "Nos"
    }

    f_act = st.selectbox("🎯 Select Current Activity", all_activities, key="act_main")
    current_unit = unit_map.get(f_act, "Nos")

    with st.form("prod_form", clear_on_submit=True):
        st.markdown(f"Logging work for: **{f_act}** | Target Unit: **{current_unit}**")
        
        f1, f2, f3 = st.columns(3)
        f_sup = f1.selectbox("Supervisor", base_supervisors)
        f_wrk = f1.selectbox("Worker/Engineer", ["-- Select --"] + all_workers)
        
        f_job = f2.selectbox("Job Code", ["-- Select --"] + all_jobs)
        f2.caption(f"Unit type: {current_unit}")
        
        f_hrs = f3.number_input("Hours Spent", min_value=0.0, step=0.5, format="%.1f")
        f_out = f3.number_input(f"Total Output ({current_unit})", min_value=0.0, format="%.2f")
        
        f_nts = st.text_area("Task Details / Remarks", placeholder="Enter specific details here...")

        if st.form_submit_button("🚀 Log Productivity", use_container_width=True):
            if f_act == "Others" and not f_nts.strip():
                st.error("⚠️ Please provide details in 'Task Details' for 'Others'.")
            elif "-- Select --" in [f_wrk, f_job]:
                st.error("❌ Selection Missing: Please select both Worker and Job Code.")
            elif f_hrs <= 0:
                st.error("❌ Invalid Hours: Must be greater than 0.")
            else:
                try:
                    conn.table("production").insert({
                        "Supervisor": f_sup, 
                        "Worker": f_wrk, 
                        "Job_Code": f_job,
                        "Activity": f_act, 
                        "Hours": f_hrs, 
                        "Output": f_out, 
                        "Unit": current_unit,
                        "Notes": f_nts,
                        "created_at": datetime.now(IST).isoformat()
                    }).execute()
                    
                    st.cache_data.clear()
                    st.success(f"✅ Success! {f_out} {current_unit} recorded.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Database Error: {e}")

# --- TAB 3: ANALYTICS ---
with tab_analytics:
    st.subheader("📅 Production Shift Report")
    
    a1, a2 = st.columns([1, 3])
    with a1:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    with a2:
        report_date = st.date_input("Select Report Date", datetime.now(IST).date())

    if not df_logs.empty and 'created_at' in df_logs.columns:
        df_logs['created_at'] = pd.to_datetime(df_logs['created_at'], errors='coerce')
        df_logs = df_logs.dropna(subset=['created_at']).copy()
        
        if df_logs['created_at'].dt.tz is None:
            df_logs['created_at'] = df_logs['created_at'].dt.tz_localize('UTC')
        
        df_logs['ist_time'] = df_logs['created_at'].dt.tz_convert(IST)
        filtered_logs = df_logs[df_logs['ist_time'].dt.date == report_date].copy()
        
        if not filtered_logs.empty:
            filtered_logs['Logged At'] = filtered_logs['ist_time'].dt.strftime('%I:%M %p')
            filtered_logs = filtered_logs.sort_values('ist_time', ascending=False)
            
            st.dataframe(
                filtered_logs[['Logged At', 'Worker', 'Job_Code', 'Activity', 'Hours', 'Output', 'Unit', 'Notes']], 
                hide_index=True,
                use_container_width=True
            )
            
            m1, m2 = st.columns(2)
            m1.metric("Total Man-Hours", f"{filtered_logs['Hours'].sum():.1f} Hrs")
            m2.metric("Total Entries", len(filtered_logs))
        else:
            st.info(f"No entries found for {report_date.strftime('%d %b %Y')}.")
    else:
        st.warning("No logs found in the database.")

# --- TAB 4: MANAGE MASTERS ---
with tab_masters:
    st.subheader("🛠️ Master Registration")
    m1, m2 = st.columns(2)
    with m1:
        new_w = st.text_input("Register Worker")
        if st.button("Add Person") and new_w:
            conn.table("production").insert({"Worker": new_w, "Notes": "SYSTEM_NEW_ITEM", "Hours": 0, "Activity": "N/A", "Job_Code": "N/A"}).execute()
            st.cache_data.clear()
            st.rerun()
    with m2:
        if not df_gates.empty:
            st.write("Production Gates:")
            st.dataframe(df_gates[['step_order', 'gate_name']], hide_index=True)
