import streamlit as st
from st_supabase_connection import SupabaseConnection
import datetime
import pandas as pd

# 1. Setup
st.set_page_config(page_title="Cut & Weld Hub", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# Custom UI styling
st.markdown("""<style>div.stButton > button { border-radius: 50px; font-weight: 600; }</style>""", unsafe_allow_html=True)

# --- HUB SELECTION ---
st.sidebar.title("🎯 Shop Floor Select")
hub_choice = st.sidebar.radio("Active Hub:", ["Cutting Hub", "Welding Hub"])

DB_TABLE = "fabrication_logs" 
OP_MASTER = "master_workers"
MACH_MASTER = "master_machines"

if hub_choice == "Cutting Hub":
    RES_LABEL, ACTIVITIES = "CNC/Cutting Machine", ["Laser Cutting", "Plasma Cutting", "Oxygen Cutting", "Waterjet"]
else:
    RES_LABEL, ACTIVITIES = "Welding Bay/Station", ["TIG Welding", "MIG Welding", "ARC Welding", "Grinding"]

# 2. Data Fetching
@st.cache_data(ttl=300)
def get_master_data():
    try:
        m_data = conn.table(MACH_MASTER).select("name").execute().data or []
        o_data = conn.table(OP_MASTER).select("name").execute().data or []
        return [r['name'] for r in m_data] or ["None"], [o['name'] for o in o_data] or ["None"]
    except:
        return ["Error"], ["Error"]

def get_logs():
    # Only fetch records for the active hub to keep things fast
    return conn.table(DB_TABLE).select("*").eq("hub_name", hub_choice).order("created_at", desc=True).execute().data or []

resource_list, operator_list = get_master_data()
df_main = pd.DataFrame(get_logs())

# 3. UI Layout
st.title(f"⚡ {hub_choice.upper()}")
tabs = st.tabs(["📝 New Request", "👨‍🏭 Incharge Desk", "📊 Live Board", "⚙️ Registry View"])

# --- TAB 1: PRODUCTION REQUEST ---
with tabs[0]:
    with st.form("cut_weld_req", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", ["1", "2", "3"]) # Using strings to match your DB 'text' type
        j_no = c1.text_input("Job Number (Required)") # Refined variable name
        part = c2.text_input("Part Name")
        act = c2.selectbox("Activity", ACTIVITIES)
        req_d = c3.date_input("Required Date")
        prio = c3.selectbox("Priority", ["Normal", "Urgent", "Critical"])
        notes = st.text_area("Special Notes / Dimensions")
        
        if st.form_submit_button("Submit to Shop Floor") and j_no and part:
            conn.table(DB_TABLE).insert({
                "hub_name": hub_choice, 
                "unit_no": u_no, 
                "part_name": part, 
                "required_date": str(req_d), 
                "job_no": j_no,  # FIX: Matches DB column
                "activity_type": act, 
                "priority": prio, 
                "special_notes": notes, 
                "status": "Pending", 
                "request_date": str(datetime.date.today())
            }).execute()
            st.rerun()

    st.divider()
    if not df_main.empty:
        st.subheader("📋 Recent Production Entries")
        
        # Pulling the specific columns you requested
        display_cols = [
            "job_no", "unit_no", "request_date", 
            "required_date", "priority", "status", "special_notes"
        ]
        
        # Verify columns exist to prevent KeyError
        existing_display = [c for c in display_cols if c in df_main.columns]
        st.dataframe(df_main[existing_display].head(10), use_container_width=True, hide_index=True)

        # --- CSV DOWNLOAD LOGIC ---
        st.markdown("### 📥 Export Logs")
        c1, c2 = st.columns(2)
        
        # 1. Quick Download (Current View)
        csv_data = df_main.to_csv(index=False).encode('utf-8')
        c1.download_button(
            label="Download Current Hub CSV",
            data=csv_data,
            file_name=f"{hub_choice}_logs_{datetime.date.today()}.csv",
            mime="text/csv",
        )
        
        # 2. Filtered Export (Senior Dev Touch: Search by Job)
        search_job = c2.text_input("Filter by Job No for Export", placeholder="Enter Job Code...")
        if search_job:
            filtered_df = df_main[df_main['job_no'].str.contains(search_job, case=False, na=False)]
            if not filtered_df.empty:
                c2.download_button(
                    label=f"Download Job {search_job} CSV",
                    data=filtered_df.to_csv(index=False).encode('utf-8'),
                    file_name=f"Job_{search_job}_Report.csv",
                    mime="text/csv",
                )

# --- TAB 2: INCHARGE DESK ---
with tabs[1]:
    if not df_main.empty:
        active_df = df_main[df_main['status'] != "Finished"]
        if active_df.empty:
            st.info(f"All {hub_choice} tasks are completed.")
        else:
            for _, job in active_df.iterrows():
                with st.expander(f"📦 {job['job_no']} - {job['part_name']} | Unit {job['unit_no']}"):
                    if job['status'] == "Pending":
                        c1, c2 = st.columns(2)
                        m = c1.selectbox(f"Select {RES_LABEL}", resource_list, key=f"m_{job['id']}")
                        o = c2.selectbox("Assign Personnel", operator_list, key=f"o_{job['id']}")
                        if st.button("🚀 Start Task", key=f"go_{job['id']}", use_container_width=True):
                            conn.table(DB_TABLE).update({"status": "In-Progress", "machine_id": m, "operator_name": o}).eq("id", job['id']).execute()
                            st.rerun()
                    
                    elif job['status'] == "In-Progress":
                        st.success(f"Work in Progress: {job.get('machine_id')} | Operator: {job.get('operator_name')}")
                        dr = st.text_input("Reason for Delay (if any)", key=f"dr_{job['id']}")
                        if st.button("🏁 Mark as Finished", key=f"f_{job['id']}", use_container_width=True):
                            conn.table(DB_TABLE).update({"status": "Finished", "delay_reason": dr}).eq("id", job['id']).execute()
                            st.rerun()
    else:
        st.info("No active tasks.")

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
