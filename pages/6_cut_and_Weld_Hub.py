import streamlit as st
from st_supabase_connection import SupabaseConnection
import datetime
import pandas as pd

# 1. Setup
st.set_page_config(page_title="Cut & Weld Hub", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

st.markdown("""<style>div.stButton > button { border-radius: 50px; font-weight: 600; }</style>""", unsafe_allow_html=True)

# --- HUB SELECTION ---
st.sidebar.title("🎯 Shop Floor Select")
hub_choice = st.sidebar.radio("Active Hub:", ["Cutting Hub", "Welding Hub"])

# --- DYNAMIC CONFIG ---
DB_TABLE = "fabrication_logs" 
OP_MASTER = "master_workers"
MACH_MASTER = "master_machines"

if hub_choice == "Cutting Hub":
    RES_LABEL, ACTIVITIES = "CNC/Cutting Machine", ["Laser Cutting", "Plasma Cutting", "Oxygen Cutting", "Waterjet"]
else:
    RES_LABEL, ACTIVITIES = "Welding Bay/Station", ["TIG Welding", "MIG Welding", "ARC Welding", "Grinding"]

# 2. Data Fetching
def get_all_data():
    try:
        logs = conn.table(DB_TABLE).select("*").eq("hub_name", hub_choice).order("created_at", desc=True).execute().data or []
        m_data = conn.table(MACH_MASTER).select("name").execute().data or []
        o_data = conn.table(OP_MASTER).select("name").execute().data or []
        
        # Fallback to prevent Selectbox crashes if Masters are empty
        m_list = [r['name'] for r in m_data] if m_data else ["None Defined"]
        o_list = [o['name'] for o in o_data] if o_data else ["None Defined"]
        
        return pd.DataFrame(logs), m_list, o_list
    except Exception as e:
        st.error(f"Sync Error: {e}"); return pd.DataFrame(), ["Error"], ["Error"]

df_main, resource_list, operator_list = get_all_data()

# 3. UI Layout
st.title(f"⚡ {hub_choice.upper()}")
tabs = st.tabs(["📝 New Request", "👨‍🏭 Incharge Desk", "📊 Live Board", "⚙️ Registry View"])

# --- TAB 1: PRODUCTION REQUEST ---
with tabs[0]:
    with st.form("cut_weld_req", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", [1, 2, 3])
        j_code = c1.text_input("Job Code (Required)")
        part = c2.text_input("Part Name")
        act = c2.selectbox("Activity", ACTIVITIES)
        req_d = c3.date_input("Required Date")
        prio = c3.selectbox("Priority", ["Normal", "Urgent", "Critical"])
        notes = st.text_area("Special Notes / Dimensions")
        
        if st.form_submit_button("Submit to Shop Floor") and j_code and part:
            conn.table(DB_TABLE).insert({
                "hub_name": hub_choice, "unit_no": u_no, "part_name": part, 
                "required_date": str(req_d), "job_code": j_code, "activity_type": act, 
                "priority": prio, "special_notes": notes, 
                "status": "Pending", "request_date": str(datetime.date.today())
            }).execute(); st.rerun()

    st.divider()
    if not df_main.empty:
        st.subheader("Recent Entries")
        st.dataframe(df_main[["job_code", "part_name", "priority", "status"]].head(5), use_container_width=True, hide_index=True)

# --- TAB 2: INCHARGE DESK ---
with tabs[1]:
    active = df_main[df_main['status'] != "Finished"].to_dict('records') if not df_main.empty else []
    if not active: st.info(f"All {hub_choice} tasks are completed.")
    
    for job in active:
        with st.expander(f"📦 {job['job_code']} - {job['part_name']} | Unit {job['unit_no']}"):
            if job['status'] == "Pending":
                c1, c2 = st.columns(2)
                m = c1.selectbox(f"Select {RES_LABEL}", resource_list, key=f"m_{job['id']}")
                o = c2.selectbox("Assign Personnel", operator_list, key=f"o_{job['id']}")
                if st.button("🚀 Start Task", key=f"go_{job['id']}", use_container_width=True):
                    conn.table(DB_TABLE).update({"status": "In-Progress", "machine_id": m, "operator_name": o}).eq("id", job['id']).execute(); st.rerun()
            
            elif job['status'] == "In-Progress":
                st.success(f"Work in Progress: {job['machine_id']} | User: {job['operator_name']}")
                dr = st.text_input("Reason for Delay (if any)", key=f"dr_{job['id']}")
                if st.button("🏁 Mark as Finished", key=f"f_{job['id']}", use_container_width=True):
                    conn.table(DB_TABLE).update({"status": "Finished", "delay_reason": dr}).eq("id", job['id']).execute(); st.rerun()

# --- TAB 3: LIVE BOARD ---
with tabs[2]:
    if not df_main.empty:
        # Optimization: Add 'Days Left' for better executive overview
        df_viz = df_main.copy()
        df_viz['required_date'] = pd.to_datetime(df_viz['required_date'], errors='coerce')
        df_viz['Days Left'] = (df_viz['required_date'] - pd.Timestamp(datetime.date.today())).dt.days
        
        # Display with specific column order
        cols = ["job_code", "part_name", "status", "priority", "Days Left", "machine_id", "operator_name", "special_notes"]
        st.dataframe(df_viz[cols], use_container_width=True, hide_index=True)
    else:
        st.info("No records found.")

# --- TAB 4: REGISTRY VIEW ---
with tabs[3]:
    st.caption("Resources are managed in the Master Setup page.")
    col_a, col_b = st.columns(2)
    col_a.write(f"**Current {RES_LABEL}s:**")
    col_a.table(resource_list)
    col_b.write("**Current Operators:**")
    col_b.table(operator_list)
