import streamlit as st
from st_supabase_connection import SupabaseConnection
import datetime
import pandas as pd

# 1. Setup
st.set_page_config(page_title="Cut & Weld Hub", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR: CONTROL & NAVIGATION ---
with st.sidebar:
    st.title("⚙️ Control Panel")
    if st.button("🔄 Sync Master Data", use_container_width=True):
        st.cache_data.clear()
        st.success("Data Refreshed!")
        st.rerun()
    
    st.divider()
    hub_choice = st.radio("Active Hub:", ["Cutting Hub", "Welding Hub"])

# --- DATABASE CONFIG (Mapped to your JSON Schema) ---
# NOTE: Using 'beta_machining_logs' as the primary log table based on your schema
DB_TABLE = "beta_machining_logs" 
OP_MASTER = "beta_operator_master"    # Updated to match schema
MACH_MASTER = "beta_machine_master"   # Updated to match schema

if hub_choice == "Cutting Hub":
    RES_LABEL, ACTIVITIES = "CNC/Cutting Machine", ["Laser Cutting", "Plasma Cutting", "Oxygen Cutting", "Waterjet"]
else:
    RES_LABEL, ACTIVITIES = "Welding Bay/Station", ["TIG Welding", "MIG Welding", "ARC Welding", "Grinding"]

# 2. Data Fetching (Aligned with Schema Headers)
@st.cache_data(ttl=600)
def get_all_data(hub):
    try:
        # Fetch Logs (Table uses 'job_code' per schema)
        logs = conn.table(DB_TABLE).select("*").order("created_at", desc=True).execute().data or []
        # Fetch Masters (Tables use 'machine_name' and 'operator_name')
        m_data = conn.table(MACH_MASTER).select("machine_name").execute().data or []
        o_data = conn.table(OP_MASTER).select("operator_name").execute().data or []
        # Fetch Anchors (Table uses 'job_no')
        anchor_data = conn.table("anchor_projects").select("job_no").neq("status", "Completed").execute().data or []
        
        return pd.DataFrame(logs), [r['machine_name'] for r in m_data], [o['operator_name'] for o in o_data], anchor_data
    except Exception as e:
        st.error(f"Database Sync Error: {e}")
        return pd.DataFrame(), [], [], []

df_main, resource_list, operator_list, anchor_list = get_all_data(hub_choice)

# 3. UI Layout
st.title(f"⚡ {hub_choice.upper()}")
tabs = st.tabs(["📝 New Request", "👨‍🏭 Incharge Desk", "📊 Live Board", "📜 Job History", "⚙️ Registry View"])

# --- TAB 1: PRODUCTION REQUEST ---
with tabs[0]:
    st.subheader(f"New {hub_choice} Request")
    
    # 1. Select Job No from Master Anchor List
    job_options = [item['job_no'] for item in anchor_list] if anchor_list else ["No Active Projects Found"]
    sel_job = st.selectbox("🔍 Select Master Job No", options=job_options)

    # 2. Recent Parts Helper (Safety check for 'job_code' vs 'job_no')
    if not df_main.empty and sel_job != "No Active Projects Found":
        # We look for 'job_code' in the logs dataframe to match schema
        if 'job_code' in df_main.columns:
            recent_parts = df_main[df_main['job_code'] == sel_job]['part_name'].unique()[:5]
            if len(recent_parts) > 0:
                st.caption(f"💡 Recent parts for {sel_job}: " + " | ".join(recent_parts))

    # 3. Submission Form
    with st.form("cut_weld_req", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", [1, 2, 3])
        part = c2.text_input("Part Name / Component", placeholder="Enter specific part name...") 
        act = c2.selectbox("Activity", ACTIVITIES)
        req_d = c3.date_input("Required Date")
        prio = c3.selectbox("Priority", ["Normal", "Urgent", "Critical"])
        notes = st.text_area("Notes / Dimensions / Instructions")
        
        if st.form_submit_button("Submit to Shop Floor"):
            if sel_job != "No Active Projects Found" and part:
                # IMPORTANT: Inserting into 'job_code' to match your logs table
                conn.table(DB_TABLE).insert({
                    "unit_no": u_no, 
                    "part_name": part, 
                    "job_code": sel_job, 
                    "required_date": str(req_d), 
                    "activity_type": act, 
                    "priority": prio, 
                    "special_notes": notes, 
                    "status": "Pending", 
                    "request_date": str(datetime.date.today())
                }).execute()
                st.cache_data.clear()
                st.rerun()

# --- TAB 2: INCHARGE DESK ---
with tabs[1]:
    active = df_main[df_main['status'] != "Finished"].to_dict('records') if not df_main.empty else []
    if not active: st.info(f"No pending tasks in {hub_choice}.")
    
    for job in active:
        # Use job_code for display to match your schema
        with st.expander(f"📦 {job.get('job_code', 'N/A')} - {job.get('part_name', 'Unnamed')}"):
            if job['status'] == "Pending":
                c1, c2 = st.columns(2)
                m = c1.selectbox(f"Select {RES_LABEL}", resource_list, key=f"m_{job['id']}")
                o = c2.selectbox("Assign Personnel", operator_list, key=f"o_{job['id']}")
                if st.button("🚀 Start Task", key=f"go_{job['id']}", use_container_width=True):
                    # Mapping to machine_id and operator_id per schema
                    conn.table(DB_TABLE).update({"status": "In-Progress", "machine_id": m, "operator_id": o}).eq("id", job['id']).execute()
                    st.cache_data.clear(); st.rerun()
            
            elif job['status'] == "In-Progress":
                st.success(f"Ongoing: {job.get('machine_id')} | User: {job.get('operator_id')}")
                dr = st.text_input("Delay Reason (if any)", key=f"dr_{job['id']}")
                if st.button("🏁 Mark Finished", key=f"f_{job['id']}", use_container_width=True):
                    conn.table(DB_TABLE).update({"status": "Finished", "delay_reason": dr}).eq("id", job['id']).execute()
                    st.cache_data.clear(); st.rerun()

# --- TAB 3: LIVE BOARD ---
with tabs[2]:
    if not df_main.empty:
        df_live = df_main[df_main['status'] != "Finished"].copy()
        if not df_live.empty:
            df_live['required_date'] = pd.to_datetime(df_live['required_date'], errors='coerce')
            # Table headers updated to match your schema (job_code, operator_id)
            cols = ["job_code", "part_name", "status", "priority", "machine_id", "operator_id", "special_notes"]
            st.dataframe(df_live[cols], use_container_width=True, hide_index=True)

# --- TAB 4: JOB HISTORY ---
with tabs[3]:
    if not df_main.empty:
        df_hist = df_main[df_main['status'] == "Finished"].copy()
        if not df_hist.empty:
            st.subheader(f"✅ Recently Finished ({hub_choice})")
            hist_cols = ["job_code", "part_name", "activity_type", "machine_id", "operator_id", "request_date", "delay_reason"]
            st.dataframe(df_hist[hist_cols], use_container_width=True, hide_index=True)
