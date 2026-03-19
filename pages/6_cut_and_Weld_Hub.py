import streamlit as st
from st_supabase_connection import SupabaseConnection
import datetime
import pandas as pd

# 1. Setup - Standard Streamlit (Minimal changes)
st.set_page_config(page_title="Cut & Weld Hub", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR: CONTROL & NAVIGATION ---
with st.sidebar:
    st.title("⚙️ Control Panel")
    # Manual trigger to bypass cache for new workers/projects
    if st.button("🔄 Sync Master Data", use_container_width=True):
        st.cache_data.clear()
        st.success("Data Refreshed!")
        st.rerun()
    
    st.divider()
    hub_choice = st.radio("Active Hub:", ["Cutting Hub", "Welding Hub"])

# --- DATABASE CONFIG ---
DB_TABLE = "fabrication_logs" 
OP_MASTER = "master_workers"
MACH_MASTER = "master_machines"

# Dynamic Labels based on Sidebar Selection
if hub_choice == "Cutting Hub":
    RES_LABEL, ACTIVITIES = "CNC/Cutting Machine", ["Laser Cutting", "Plasma Cutting", "Oxygen Cutting", "Waterjet"]
else:
    RES_LABEL, ACTIVITIES = "Welding Bay/Station", ["TIG Welding", "MIG Welding", "ARC Welding", "Grinding"]

# 2. Data Fetching (Cached for Speed, Synced to 'job_no')
@st.cache_data(ttl=600)
def get_all_data(hub):
    try:
        # Logs for the active hub
        logs = conn.table(DB_TABLE).select("*").eq("hub_name", hub).order("created_at", desc=True).execute().data or []
        # Master Lists
        m_data = conn.table(MACH_MASTER).select("name").execute().data or []
        o_data = conn.table(OP_MASTER).select("name").execute().data or []
        # Active Anchor Projects Only
        anchor_data = conn.table("anchor_projects").select("job_no, part_name").neq("status", "Completed").execute().data or []
        
        return pd.DataFrame(logs), [r['name'] for r in m_data], [o['name'] for o in o_data], anchor_data
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
    
    # Searchable Selectbox (Pulls from Anchor Projects)
    job_options = [item['job_no'] for item in anchor_list] if anchor_list else ["No Active Projects Found"]
    sel_job = st.selectbox("🔍 Search Active Job No", options=job_options)

    # Instant Auto-Fill Logic
    default_part = ""
    if anchor_list and sel_job != "No Active Projects Found":
        default_part = next((item['part_name'] for item in anchor_list if item['job_no'] == sel_job), "")

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
                    "required_date": str(req_d), "job_no": sel_job, "activity_type": act, 
                    "priority": prio, "special_notes": notes, 
                    "status": "Pending", "request_date": str(datetime.date.today())
                }).execute()
                st.cache_data.clear() # Clear cache so entry appears immediately
                st.rerun()

# --- TAB 2: INCHARGE DESK ---
with tabs[1]:
    active = df_main[df_main['status'] != "Finished"].to_dict('records') if not df_main.empty else []
    if not active: st.info(f"No pending tasks in {hub_choice}.")
    
    for job in active:
        with st.expander(f"📦 {job.get('job_no', 'N/A')} - {job['part_name']}"):
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
        df_live = df_main[df_main['status'] != "Finished"].copy()
        if not df_live.empty:
            df_live['required_date'] = pd.to_datetime(df_live['required_date'], errors='coerce')
            df_live['Days Left'] = (df_live['required_date'] - pd.Timestamp(datetime.date.today())).dt.days
            cols = ["job_no", "part_name", "status", "priority", "Days Left", "machine_id", "operator_name"]
            st.dataframe(df_live[cols], use_container_width=True, hide_index=True)
        else: st.info("No active jobs.")

# --- TAB 4: JOB HISTORY & DOWNLOAD ---
with tabs[3]:
    if not df_main.empty:
        df_hist = df_main[df_main['status'] == "Finished"].copy()
        if not df_hist.empty:
            c1, c2 = st.columns([3, 1])
            c1.subheader(f"✅ Recently Finished ({hub_choice})")
            
            # Simple CSV Download using standard Pandas
            csv = df_hist.to_csv(index=False).encode('utf-8')
            c2.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=f"{hub_choice}_history_{datetime.date.today()}.csv",
                mime='text/csv',
                use_container_width=True
            )
            
            hist_cols = ["job_no", "part_name", "activity_type", "machine_id", "operator_name", "delay_reason"]
            st.dataframe(df_hist[hist_cols], use_container_width=True, hide_index=True)
        else: st.info("No completed jobs found.")

# --- TAB 5: REGISTRY VIEW ---
with tabs[4]:
    st.caption("Resources are managed in the Master Setup page.")
    c_a, c_b = st.columns(2)
    c_a.write(f"**{RES_LABEL}s:**"); c_a.table(resource_list)
    c_b.write("**Operators:**"); c_b.table(operator_list)
