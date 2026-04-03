import streamlit as st
from st_supabase_connection import SupabaseConnection
import datetime
import pandas as pd

# 1. Setup
st.set_page_config(page_title="Cut & Weld Hub", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# --- SIDEBAR UTILITIES ---
st.sidebar.title("🎯 Shop Floor Select")
hub_choice = st.sidebar.radio("Active Hub:", ["Cutting Hub", "Welding Hub"])

st.sidebar.divider()
st.sidebar.subheader("📅 Export Filter")
# Senior Dev Tip: Default to the last 30 days to keep the app fast
today = datetime.date.today()
start_of_month = today.replace(day=1)
date_range = st.sidebar.date_input("Select Range:", [start_of_month, today])

DB_TABLE = "fabrication_logs" 
OP_MASTER = "master_workers"
MACH_MASTER = "master_machines"

# --- DYNAMIC CONFIG ---
if hub_choice == "Cutting Hub":
    RES_LABEL, ACTIVITIES = "CNC/Cutting Machine", ["Laser Cutting", "Plasma Cutting", "Oxygen Cutting", "Cnc cutting"]
else:
    RES_LABEL, ACTIVITIES = "Welding Bay/Station", ["TIG Welding", "MIG Welding", "ARC Welding", "Grinding"]

# --- 2. Data Fetching (UPDATED TO PULL ANCHOR JOBS) ---
@st.cache_data(ttl=300)
def get_master_data():
    try:
        # Fetch Machines
        m_data = conn.table(MACH_MASTER).select("name").execute().data or []
        # Fetch Workers
        o_data = conn.table(OP_MASTER).select("name").execute().data or []
        # FIX: Fetch Job Numbers from anchor_projects
        a_data = conn.table("anchor_projects").select("job_no").execute().data or []
        
        machines = [r['name'] for r in m_data] or ["None"]
        workers = [o['name'] for o in o_data] or ["None"]
        # Standardize and sort the job list
        anchor_jobs = sorted(list(set([str(j['job_no']) for j in a_data if j.get('job_no')])))
        
        return machines, workers, anchor_jobs
    except Exception as e:
        st.error(f"Error fetching master data: {e}")
        return ["Error"], ["Error"], []

def get_logs():
    query = conn.table(DB_TABLE).select("*").eq("hub_name", hub_choice)
    if len(date_range) == 2:
        query = query.gte("request_date", str(date_range[0])).lte("request_date", str(date_range[1]))
    return query.order("created_at", desc=True).execute().data or []

# Update call to receive the third list
resource_list, operator_list, anchor_job_list = get_master_data()
df_main = pd.DataFrame(get_logs())

# 3. UI Layout
st.title(f"⚡ {hub_choice.upper()}")
tabs = st.tabs(["📝 New Request", "👨‍🏭 Incharge Desk", "📊 Live Board", "⚙️ Registry View"])

# --- TAB 1: PRODUCTION REQUEST & RECENT ENTRIES ---
with tabs[0]:
    with st.form("cut_weld_req", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", ["1", "2", "3"])
        
        # FIX: Changed text_input to selectbox to pull from anchor_projects
        j_no = c1.selectbox("Job Number (Required)", ["-- Select --"] + anchor_job_list)
        
        part = c2.text_input("Part Name")
        act = c2.selectbox("Activity", ACTIVITIES)
        req_d = c3.date_input("Required Date")
        prio = c3.selectbox("Priority", ["Normal", "Urgent", "Critical"])
        notes = st.text_area("Special Notes / Dimensions")
        
        # Updated validation for selectbox
        if st.form_submit_button("Submit to Shop Floor"):
            if j_no == "-- Select --" or not part:
                st.error("Please select a Job Number and enter a Part Name.")
            else:
                conn.table(DB_TABLE).insert({
                    "hub_name": hub_choice, "unit_no": u_no, "part_name": part, 
                    "required_date": str(req_d), "job_no": j_no, "activity_type": act, 
                    "priority": prio, "special_notes": notes, 
                    "status": "Pending", "request_date": str(datetime.date.today())
                }).execute()
                st.success(f"Request for {j_no} submitted!")
                st.rerun()
# --- TAB 2: INCHARGE DESK ---
with tabs[1]:
    if not df_main.empty:
        # Filter for anything that isn't finished (Pending or In-Progress)
        active_df = df_main[df_main['status'] != "Finished"]
        
        if active_df.empty:
            st.info(f"✅ All {hub_choice} tasks are currently completed.")
        else:
            # Senior Dev Tip: Using iterrows() for clean row access
            for _, job in active_df.iterrows():
                # Display Job No, Part Name, and Unit for quick identification
                job_label = f"📦 {job.get('job_no', 'N/A')} - {job.get('part_name', 'Unnamed')} | Unit {job.get('unit_no', '?')}"
                
                with st.expander(job_label):
                    # --- STATE 1: PENDING (Assignment) ---
                    if job['status'] == "Pending":
                        c1, c2 = st.columns(2)
                        # Assignment fields
                        m = c1.selectbox(f"Select {RES_LABEL}", resource_list, key=f"m_{job['id']}")
                        o = c2.selectbox("Assign Personnel", operator_list, key=f"o_{job['id']}")
                        
                        if st.button("🚀 Start Task", key=f"go_{job['id']}", use_container_width=True):
                            # Minimal change: only update essential fields
                            conn.table(DB_TABLE).update({
                                "status": "In-Progress", 
                                "machine_id": m, 
                                "operator_name": o
                            }).eq("id", job['id']).execute()
                            st.rerun()
                    
                    # --- STATE 2: IN-PROGRESS (Completion) ---
                    elif job['status'] == "In-Progress":
                        # Visual confirmation of who is working where
                        st.success(f"⚡ Work in Progress: **{job.get('machine_id')}** | Operator: **{job.get('operator_name')}**")
                        
                        dr = st.text_input("Reason for Delay (if any)", key=f"dr_{job['id']}", placeholder="Enter reason only if delayed...")
                        
                        if st.button("🏁 Mark as Finished", key=f"f_{job['id']}", use_container_width=True):
                            # Close out the task
                            conn.table(DB_TABLE).update({
                                "status": "Finished", 
                                "delay_reason": dr
                            }).eq("id", job['id']).execute()
                            st.rerun()
    else:
        st.info("No records found for the selected date range.")

# --- TAB 3: LIVE BOARD ---
with tabs[2]:
    if not df_main.empty:
        df_viz = df_main.copy()
        # Convert dates safely
        df_viz['required_date'] = pd.to_datetime(df_viz['required_date'], errors='coerce')
        today = pd.to_datetime(datetime.date.today())
        df_viz['Days Left'] = (df_viz['required_date'] - today).dt.days
        
        # Display with proper column names
        cols = ["job_no", "part_name", "status", "priority", "Days Left", "machine_id", "operator_name", "special_notes"]
        existing_cols = [c for c in cols if c in df_viz.columns]
        st.dataframe(df_viz[existing_cols], use_container_width=True, hide_index=True)
    else:
        st.info("No records found.")

# --- TAB 4: REGISTRY VIEW ---
with tabs[3]:
    st.caption("Resources are managed in the Master Setup page.")
    col_a, col_b = st.columns(2)
    col_a.write(f"**Current {RES_LABEL}s:**")
    col_a.dataframe(pd.DataFrame(resource_list, columns=["Machine Name"]), hide_index=True)
    col_b.write("**Current Operators:**")
    col_b.dataframe(pd.DataFrame(operator_list, columns=["Worker Name"]), hide_index=True)
