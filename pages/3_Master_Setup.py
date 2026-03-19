import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date

# 1. Setup & Style
st.set_page_config(page_title="B&G Hub ERP", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# Judicious use of CSS for the "B&G" feel
st.markdown("""<style>div.stButton > button { border-radius: 50px; font-weight: 600; }</style>""", unsafe_allow_html=True)

if 'hub' not in st.session_state:
    st.session_state.hub = "Machining Hub"
if 'last_sync' not in st.session_state:
    st.session_state.last_sync = datetime.now().strftime("%H:%M:%S")

# --- HUB SELECTION ---
c1, c2, _ = st.columns([1, 1, 2])
if c1.button("⚙️ MACHINING HUB", use_container_width=True, type="primary" if st.session_state.hub == "Machining Hub" else "secondary"):
    st.session_state.hub = "Machining Hub"; st.rerun()
if c2.button("✨ BUFFING HUB", use_container_width=True, type="primary" if st.session_state.hub == "Buffing Hub" else "secondary"):
    st.session_state.hub = "Buffing Hub"; st.rerun()

# --- SIDEBAR STATUS & NAVIGATION ---
with st.sidebar:
    st.title("🛰️ System Status")
    st.info(f"📍 **Active:** {st.session_state.hub}")
    st.write(f"🕒 **Last Sync:** `{st.session_state.last_sync}`")
    
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.session_state.last_sync = datetime.now().strftime("%H:%M:%S")
        st.rerun()
    
    st.divider()
    st.write("🔧 **Management**")
    if st.button("⚙️ Master Setup", use_container_width=True):
        st.switch_page("pages/3_Master_Setup.py")

# --- CONFIGURATION & HUB LOGIC ---
if st.session_state.hub == "Machining Hub":
    DB_TABLE, MASTER_TABLE, RES_LABEL = "beta_machining_logs", "master_machines", "Machine"
    ACTIVITIES = ["Turning", "Drilling", "Milling", "Keyway", "Dishbending"]
    IS_BUFFING = False
else:
    DB_TABLE, MASTER_TABLE, RES_LABEL = "beta_buffing_logs", "master_machines", "Buffing Station"
    ACTIVITIES = ["Rough Buffing", "Mirror Polishing", "Satin Finish", "RA Value Check"]
    IS_BUFFING = True

# 2. Data Fetching (Aligned with Master Setup Audit)
def get_all_data():
    try:
        m_data = conn.table(MASTER_TABLE).select("name").execute().data or []
        o_data = conn.table("master_workers").select("name").execute().data or []
        v_data = conn.table("master_clients").select("name").execute().data or []
        
        # Pulling Job No and Client Name from anchor_projects
        anchor_data = conn.table("anchor_projects").select("job_no, client_name").execute().data or []
        client_map = {str(a['job_no']): a['client_name'] for a in anchor_data}
        anchor_list = sorted(list(client_map.keys()))

        vh_list = []
        if not IS_BUFFING:
            # Vehicles use 'reg_no' per Master Setup
            vh_data = conn.table("master_vehicles").select("reg_no").execute().data or []
            vh_list = [vh['reg_no'] for vh in vh_data]

        logs = conn.table(DB_TABLE).select("*").order("created_at", desc=True).execute().data or []
        df = pd.DataFrame(logs)
        
        return [r['name'] for r in m_data], [o['name'] for o in o_data], \
               [v['name'] for v in v_data], vh_list, anchor_list, client_map, df
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return [], [], [], [], [], {}, pd.DataFrame()

resource_list, worker_list, client_list, vehicle_list, anchor_list, client_map, df_main = get_all_data()

tabs = st.tabs(["📝 Production Request", "👨‍💻 Incharge Entry Desk", "📊 Executive Analytics"])

# --- TAB 1: PRODUCTION REQUEST ---
with tabs[0]:
    st.subheader(f"New {st.session_state.hub} Entry")
    with st.form("req_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", [1, 2, 3])
        j_code = c1.selectbox("Job Code", [""] + anchor_list)
        part, act = c2.text_input("Part Name"), c2.selectbox("Activity", ACTIVITIES)
        req_d, prio = c3.date_input("Required Date"), c3.selectbox("Priority", ["Low", "Medium", "High", "URGENT"])
        notes = st.text_area("Special Notes")
        
        if st.form_submit_button("Submit Request"):
            if j_code and part:
                conn.table(DB_TABLE).insert({
                    "unit_no": u_no, "job_code": j_code, "part_name": part, 
                    "activity_type": act, "required_date": str(req_d), 
                    "request_date": str(date.today()), 
                    "status": "Pending", "priority": prio, "special_notes": notes
                }).execute(); st.rerun()

# --- TAB 2: INCHARGE ENTRY DESK ---
with tabs[1]:
    if not df_main.empty:
        today = date.today()
        # Filter out finished and calculate Triage sorting
        active_df = df_main[df_main['status'] != "Finished"].copy()
        active_df['req_date_obj'] = pd.to_datetime(active_df['required_date']).dt.date
        active_df['overdue_days'] = active_df['req_date_obj'].apply(lambda x: (today - x).days if x else -999)
        active_jobs = active_df.sort_values(by="overdue_days", ascending=False).to_dict('records')
    else:
        active_jobs = []
    
    if not active_jobs:
        st.info("No active jobs currently.")
    
    for job in active_jobs:
        req_date_obj = job['req_date_obj']
        disp_req = req_date_obj.strftime('%d-%m-%Y') if req_date_obj else "N/A"
        c_name = client_map.get(str(job['job_code']), "Unknown Client")
        overdue_tag = f" 🔴 OVERDUE {job['overdue_days']}D" if (req_date_obj and req_date_obj < today) else ""

        with st.expander(f"📌 {job['job_code']} | {c_name} | {job['part_name']} {overdue_tag}"):
            st.info(f"📅 **Req. Date:** {disp_req} | 📝 **Notes:** {job['special_notes']}")
            c_del, c_int = st.columns(2)
            d_r = c_del.text_input("Delay Reason", value=job['delay_reason'] or '', key=f"dr_{job['id']}")
            i_n = c_int.text_area("Incharge Note", value=job['intervention_note'] or '', key=f"in_{job['id']}")
            
            if job['status'] == "Pending":
                mode = st.radio("Allotment", ["In-House", "Outsource"], key=f"m_{job['id']}", horizontal=True)
                if mode == "In-House":
                    c1, c2 = st.columns(2)
                    m = c1.selectbox(f"Assign {RES_LABEL}", resource_list, key=f"m_sel_{job['id']}")
                    o = c2.selectbox("Assign Worker", worker_list, key=f"o_sel_{job['id']}")
                    if st.button("🚀 Start In-House", key=f"b_ih_{job['id']}", use_container_width=True):
                        conn.table(DB_TABLE).update({"status": "In-House", "machine_id": m, "operator_id": o, "delay_reason": d_r, "intervention_note": i_n}).eq("id", job['id']).execute(); st.rerun()
                else: 
                    c1, c2, c3 = st.columns(3)
                    v = c1.selectbox("Vendor/Client", client_list, key=f"v_sel_{job['id']}")
                    vh = c2.selectbox("Vehicle", vehicle_list, key=f"vh_sel_{job['id']}") if not IS_BUFFING else "N/A"
                    gp = c3.text_input("Gatepass No", key=f"gp_{job['id']}") if not IS_BUFFING else "N/A"
                    if st.button("🚚 Dispatch Outward", key=f"b_os_{job['id']}", use_container_width=True):
                        conn.table(DB_TABLE).update({"status": "Outsourced", "vendor_id": v, "vehicle_no": vh, "gatepass_no": gp, "delay_reason": d_r, "intervention_note": i_n}).eq("id", job['id']).execute(); st.rerun()
            
            elif job['status'] == "Outsourced":
                wb = st.text_input("Return Waybill / DC No", key=f"wb_{job['id']}")
                if st.button("✅ Mark Received & Finished", key=f"b_rc_{job['id']}", use_container_width=True):
                    conn.table(DB_TABLE).update({"status": "Finished", "waybill_no": wb, "delay_reason": d_r, "intervention_note": i_n}).eq("id", job['id']).execute(); st.rerun()
            else:
                if st.button("🏁 Mark Finished", key=f"b_fi_{job['id']}", use_container_width=True):
                    conn.table(DB_TABLE).update({"status": "Finished", "delay_reason": d_r, "intervention_note": i_n}).eq("id", job['id']).execute(); st.rerun()

# --- TAB 3: EXECUTIVE ANALYTICS ---
with tabs[2]:
    if not df_main.empty:
        st.write(f"### 🌍 {st.session_state.hub} Floor Overview")
        st.dataframe(df_main[['job_code', 'part_name', 'status', 'priority', 'required_date']], use_container_width=True, hide_index=True)
