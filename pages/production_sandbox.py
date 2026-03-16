import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Production Sandbox | B&G", layout="wide", page_icon="🧪")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=2)
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

if not df_gates.empty:
    universal_stages = df_gates['gate_name'].tolist()
else:
    universal_stages = all_activities

all_jobs = sorted(df_plan['job_no'].astype(str).unique().tolist()) if not df_plan.empty else []
all_workers = sorted(df_logs['Worker'].unique().tolist()) if not df_logs.empty else []

# --- 4. NAVIGATION ---
tab_plan, tab_entry, tab_analytics = st.tabs(["🏗️ Planning", "👷 Daily Entry", "📊 Analytics"])

# --- TAB 1: PLANNING (With Aging Logic) ---
with tab_plan:
    st.subheader("🚀 Shop Floor Control (Sandbox)")
    if not df_plan.empty:
        hrs_sum = df_logs.groupby('Job_Code')['Hours'].sum().to_dict() if not df_logs.empty else {}

        for index, row in df_plan.iterrows():
            job_id = str(row['job_no']).strip().upper()
            actual_hrs = hrs_sum.get(job_id, 0)
            
            # Date Parsing for Aging
            updated_at_raw = row.get('updated_at')
            updated_at = pd.to_datetime(updated_at_raw or datetime.now(IST))
            if updated_at.tzinfo is None: updated_at = updated_at.replace(tzinfo=pytz.UTC)
            updated_at = updated_at.astimezone(IST)

            days_at_gate = (datetime.now(IST).date() - updated_at.date()).days
            manual_limit = row.get('manual_days_limit', 7) 
            current_gate = row.get('drawing_status', universal_stages[0])
            
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.subheader(f"Job {job_id} | {row['client_name']}")
                c2.metric("Man-Hours", f"{actual_hrs} Hrs")
                
                is_slow = days_at_gate > manual_limit
                c3.metric("Aging", f"{days_at_gate} Days", 
                          delta=f"Limit: {manual_limit}d" if is_slow else "OK", 
                          delta_color="inverse" if is_slow else "normal")
                
                # Update UI
                u1, u2, u3 = st.columns(3)
                new_gate = u1.selectbox("Move Gate", universal_stages, 
                                        index=universal_stages.index(current_gate) if current_gate in universal_stages else 0, 
                                        key=f"gt_{row['id']}")
                new_limit = u2.number_input("Limit (Days)", 1, 30, int(manual_limit), key=f"lim_{row['id']}")
                
                if u3.button("💾 Save Update", key=f"btn_{row['id']}", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "drawing_status": new_gate,
                        "manual_days_limit": new_limit,
                        "updated_at": datetime.now(IST).isoformat()
                    }).eq("id", row['id']).execute()
                    st.cache_data.clear()
                    st.rerun()

# --- TAB 3: ANALYTICS (Charts Added) ---
with tab_analytics:
    if not df_logs.empty:
        st.subheader("📊 Man-Hour Distribution")
        df_logs['Hours'] = pd.to_numeric(df_logs['Hours'], errors='coerce')
        fig = px.pie(df_logs, values='Hours', names='Activity', hole=0.4, 
                     title="Total Work Hours by Activity Type")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No logs available for charts yet.")
