import streamlit as st
from st_supabase_connection import SupabaseConnection
import datetime
import pandas as pd

# 1. Setup
st.set_page_config(page_title="Cut & Weld Hub", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR: REFRESH & HUB SELECTION ---
with st.sidebar:
    st.title("⚙️ Control Panel")
    if st.button("🔄 Sync Master Data", use_container_width=True):
        st.cache_data.clear()
        st.success("Data Refreshed!")
        st.rerun()
    
    st.divider()
    st.title("🎯 Shop Floor Select")
    hub_choice = st.sidebar.radio("Active Hub:", ["Cutting Hub", "Welding Hub"])

# --- DYNAMIC CONFIG ---
DB_TABLE = "fabrication_logs" 
OP_MASTER = "master_workers"
MACH_MASTER = "master_machines"

if hub_choice == "Cutting Hub":
    RES_LABEL, ACTIVITIES = "CNC/Cutting Machine", ["Laser Cutting", "Plasma Cutting", "Oxygen Cutting", "Waterjet"]
else:
    RES_LABEL, ACTIVITIES = "Welding Bay/Station", ["TIG Welding", "MIG Welding", "ARC Welding", "Grinding"]

# 2. Data Fetching (With Caching for Speed)
@st.cache_data(ttl=600) # Caches for 10 minutes unless manual sync button is pressed
def get_all_data(hub):
    try:
        logs = conn.table(DB_TABLE).select("*").eq("hub_name", hub).order("created_at", desc=True).execute().data or []
        m_data = conn.table(MACH_MASTER).select("name").execute().data or []
        o_data = conn.table(OP_MASTER).select("name").execute().data or []
        
        # Pull ONLY "Ongoing" or "Active" projects from Anchor Projects
        anchor_data = conn.table("anchor_projects").select("job_code, part_name").neq("status", "Completed").execute().data or []
        
        return pd.DataFrame(logs), [r['name'] for r in m_data], [o['name'] for o in o_data], anchor_data
    except Exception as e:
        st.error(f"Sync Error: {e}"); return pd.DataFrame(), ["Error"], ["Error"], []

df_main, resource_list, operator_list, anchor_list = get_all_data(hub_choice)

# 3. UI Layout
st.title(f"⚡ {hub_choice.upper()}")
tabs = st.tabs(["📝 New Request", "👨‍🏭 Incharge Desk", "📊 Live Board", "⚙️ Registry View"])

# --- TAB 1: PRODUCTION REQUEST ---
with tabs[0]:
    st.subheader(f"New {hub_choice} Request")
    
    # LIVE PICKER (Pulls from filtered Anchor list)
    job_options = [item['job_code'] for item in anchor_list] if anchor_list else ["No Active Projects Found"]
    sel_job = st.selectbox("🔍 Search Active Job Code", options=job_options)

    # Auto-Fill Logic
    default_part = ""
    if anchor_list and sel_job != "No Active Projects Found":
        default_part = next((item['part_name'] for item in anchor_list if item['job_code'] == sel_job), "")

    with st.form("cut_weld_req", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", [1, 2, 3])
        part = c2.text_input("Part Name", value=default_part) 
        act = c2.selectbox("Activity", ACTIVITIES)
        req_d = c3.date_input("Required Date")
        prio = c3.selectbox("Priority", ["Normal", "Urgent", "Critical"])
        notes = st.text_area("Special Notes / Dimensions")
        
        if st.form_submit_button("Submit to Shop Floor"):
            if sel_job != "No Active Projects Found" and part:
                conn.table(DB_TABLE).insert({
                    "hub_name": hub_choice, "unit_no": u_no, "part_name": part, 
                    "required_date": str(req_d), "job_code": sel_job, "activity_type": act, 
                    "priority": prio, "special_notes": notes, 
                    "status": "Pending", "request_date": str(datetime.date.today())
                }).execute()
                st.cache_data.clear() # Clear cache so new entry shows up
                st.rerun()

# --- TAB 2: INCHARGE DESK ---
with tabs[1]:
    active = df_main[df_main['status'] != "Finished"].to_dict('records') if not df_main.empty else []
    if not active: st.info(f"All {hub_choice} tasks are completed.")
    
    for job in active:
        with st.expander(f"📦 {job['job_code']} - {job['part_name']}"):
            if job['status'] == "Pending":
                c1, c2 = st.columns(2)
                m = c1.selectbox(f"Select {RES_LABEL}", resource_list, key=f"m_{job['id']}")
                o = c2.selectbox("Assign Personnel", operator_list, key=f"o_{job['id']}")
                if st.button("🚀 Start Task", key=f"go_{job['id']}", use_container_width=True):
                    conn.table(DB_TABLE).update({"status": "In-Progress", "machine_id": m, "operator_name": o}).eq("id", job['id']).execute()
                    st.cache_data.clear(); st.rerun()
            
            elif job['status'] == "In-Progress":
                st.success(f"Ongoing: {job['machine_id']} | User: {job['operator_name']}")
                dr = st.text_input("Delay Reason", key=f"dr_{job['id']}")
                if st.button("🏁 Mark Finished", key=f"f_{job['id']}", use_container_width=True):
                    conn.table(DB_TABLE).update({"status": "Finished", "delay_reason": dr}).eq("id", job['id']).execute()
                    st.cache_data.clear(); st.rerun()

# --- TAB 3: LIVE BOARD ---
with tabs[2]:
    if not df_main.empty:
        df_viz = df_main.copy()
        df_viz['required_date'] = pd.to_datetime(df_viz['required_date'], errors='coerce')
        df_viz['Days Left'] = (df_viz['required_date'] - pd.Timestamp(datetime.date.today())).dt.days
        cols = ["job_code", "part_name", "status", "priority", "Days Left", "machine_id", "operator_name"]
        st.dataframe(df_viz[cols], use_container_width=True, hide_index=True)

# --- TAB 4: REGISTRY VIEW ---
with tabs[3]:
    st.caption("Resources are managed in the Master Setup page.")
    c_a, c_b = st.columns(2)
    c_a.write(f"**{RES_LABEL}s:**"); c_a.table(resource_list)
    c_b.write("**Operators:**"); c_b.table(operator_list)
