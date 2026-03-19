import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import io

# 1. SETUP & STYLE
st.set_page_config(page_title="B&G Hub: Machining & Buffing", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection, ttl=60)

# Custom Styling to match your B&G Enterprise look
st.markdown("""
    <style>
    div.stButton > button { border-radius: 10px; font-weight: 600; height: 3em; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { 
        background-color: #f0f2f6; 
        border-radius: 5px 5px 0px 0px; 
        padding: 10px 20px;
    }
    </style>
    """, unsafe_allow_html=True)

if 'hub' not in st.session_state:
    st.session_state.hub = "Machining Hub"

# --- HUB SELECTION ---
c1, c2, _ = st.columns([1, 1, 2])
if c1.button("⚙️ MACHINING HUB", use_container_width=True, type="primary" if st.session_state.hub == "Machining Hub" else "secondary"):
    st.session_state.hub = "Machining Hub"; st.rerun()
if c2.button("✨ BUFFING HUB", use_container_width=True, type="primary" if st.session_state.hub == "Buffing Hub" else "secondary"):
    st.session_state.hub = "Buffing Hub"; st.rerun()

# --- DYNAMIC CONFIGURATION ---
if st.session_state.hub == "Machining Hub":
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_machining_logs", "beta_machine_master", "machine_name", "Machine"
    ACTIVITIES = ["Turning", "Drilling", "Milling", "Keyway", "Dishbending"]
    IS_BUFFING = False
else:
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_buffing_logs", "beta_buffing_station_master", "station_name", "Buffing Station"
    ACTIVITIES = ["Rough Buffing", "Mirror Polishing", "Satin Finish", "RA Value Check"]
    IS_BUFFING = True

# 2. DATA ENGINE
@st.cache_data(ttl=300)
def get_hub_masters():
    try:
        # Fetch shared masters
        ops = conn.table("operator_master").select("operator_name").execute().data or []
        vnds = conn.table("vendor_master").select("vendor_name").execute().data or []
        
        # Fetch Hub-specific masters
        res = conn.table(MASTER_TABLE).select(MASTER_COL).execute().data or []
        
        # Pull Job Codes from Anchor Projects for consistency
        anchors = conn.table("anchor_projects").select("job_no, client_name").execute().data or []
        job_list = [f"{a['job_no']} | {a['client_name']}" for a in anchors]
        
        vh_list = []
        if not IS_BUFFING:
            vh_data = conn.table("vehicle_master").select("vehicle_number").execute().data or []
            vh_list = [vh['vehicle_number'] for vh in vh_data]

        return {
            "resources": sorted([r[MASTER_COL] for r in res]),
            "operators": sorted([o['operator_name'] for o in ops]),
            "vendors": sorted([v['vendor_name'] for v in vnds]),
            "vehicles": sorted(vh_list),
            "jobs": sorted(job_list)
        }
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return {"resources": [], "operators": [], "vendors": [], "vehicles": [], "jobs": []}

masters = get_hub_masters()

def get_logs():
    res = conn.table(DB_TABLE).select("*").order("created_at", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_logs = get_logs()

# --- UI TABS ---
tabs = st.tabs(["📝 Production Request", "👨‍💻 Entry Desk", "📊 Analytics", "🛠️ Masters"])

# --- TAB 1: PRODUCTION REQUEST ---
with tabs[0]:
    st.subheader(f"New {st.session_state.hub} Ticket")
    with st.form("req_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", [1, 2, 3])
        # Searchable Job Code linked to Anchor Portal
        f_job_full = c1.selectbox("Job Code", [""] + masters['jobs'])
        f_job = f_job_full.split(" | ")[0] if f_job_full else ""
        
        part = c2.text_input("Part Name / Drawing No")
        act = c2.selectbox("Activity", ACTIVITIES)
        
        req_d = c3.date_input("Required Date", min_value=date.today())
        prio = c3.selectbox("Priority", ["Low", "Medium", "High", "URGENT"])
        
        notes = st.text_area("Production Instructions / Notes")
        
        if st.form_submit_button("🚀 Create Production Request", use_container_width=True):
            if f_job and part:
                payload = {
                    "unit_no": u_no, "job_code": f_job, "part_name": part, 
                    "activity_type": act, "required_date": str(req_d), 
                    "request_date": str(date.today()), 
                    "status": "Pending", "priority": prio, "special_notes": notes
                }
                conn.table(DB_TABLE).insert(payload).execute()
                st.success("Request Logged!"); st.cache_data.clear(); st.rerun()
            else:
                st.error("Job Code and Part Name are mandatory")

# --- TAB 2: INCHARGE ENTRY DESK ---
with tabs[1]:
    if df_logs.empty:
        st.info("No active production logs found.")
    else:
        active_df = df_logs[df_logs['status'] != "Finished"]
        
        for _, job in active_df.iterrows():
            # Color coding for priority
            prio_color = "🔴" if job['priority'] == "URGENT" else "🟡" if job['priority'] == "High" else "⚪"
            
            with st.expander(f"{prio_color} {job['job_code']} | {job['part_name']} | {job['activity_type']}"):
                col_a, col_b = st.columns(2)
                col_a.write(f"**Unit:** {job['unit_no']} | **Requested:** {job['request_date']}")
                col_b.write(f"**Required By:** {job['required_date']}")
                st.caption(f"Note: {job['special_notes']}")
                
                # Feedback fields
                d_r = st.text_input("Delay Reason (if any)", value=job.get('delay_reason') or '', key=f"dr_{job['id']}")
                i_n = st.text_area("Incharge Comments", value=job.get('intervention_note') or '', key=f"in_{job['id']}")
                
                if job['status'] == "Pending":
                    mode = st.radio("Assignment Mode", ["In-House", "Outsource"], horizontal=True, key=f"mode_{job['id']}")
                    
                    if mode == "In-House":
                        c1, c2 = st.columns(2)
                        m = c1.selectbox(f"Select {RES_LABEL}", masters['resources'], key=f"r_{job['id']}")
                        o = c2.selectbox("Select Operator", masters['operators'], key=f"o_{job['id']}")
                        if st.button("▶️ Start Fabrication", key=f"btn_s_{job['id']}", use_container_width=True):
                            conn.table(DB_TABLE).update({
                                "status": "In-House", "machine_id": m, "operator_id": o,
                                "delay_reason": d_r, "intervention_note": i_n
                            }).eq("id", job['id']).execute()
                            st.cache_data.clear(); st.rerun()
                    else:
                        c1, c2, c3 = st.columns(3)
                        v = c1.selectbox("Vendor", masters['vendors'], key=f"v_{job['id']}")
                        if not IS_BUFFING:
                            vh = c2.selectbox("Vehicle", masters['vehicles'], key=f"vh_{job['id']}")
                            gp = c3.text_input("Gatepass", key=f"gp_{job['id']}")
                        else:
                            vh, gp = None, None
                            
                        if st.button("🚚 Dispatch to Vendor", key=f"btn_d_{job['id']}", use_container_width=True):
                            conn.table(DB_TABLE).update({
                                "status": "Outsourced", "vendor_id": v, "vehicle_no": vh,
                                "gatepass_no": gp, "delay_reason": d_r, "intervention_note": i_n
                            }).eq("id", job['id']).execute()
                            st.cache_data.clear(); st.rerun()
                
                elif job['status'] == "Outsourced":
                    wb = st.text_input("Return DC / Waybill No", key=f"wb_{job['id']}")
                    if st.button("✅ Mark Received & Closed", key=f"btn_f_{job['id']}", use_container_width=True):
                        conn.table(DB_TABLE).update({
                            "status": "Finished", "waybill_no": wb, "delay_reason": d_r, "intervention_note": i_n
                        }).eq("id", job['id']).execute()
                        st.cache_data.clear(); st.rerun()
                
                else: # In-House
                    if st.button("🏁 Mark Job Finished", key=f"btn_done_{job['id']}", use_container_width=True):
                        conn.table(DB_TABLE).update({
                            "status": "Finished", "delay_reason": d_r, "intervention_note": i_n
                        }).eq("id", job['id']).execute()
                        st.cache_data.clear(); st.rerun()

# --- TAB 3: ANALYTICS ---
with tabs[2]:
    if not df_logs.empty:
        st.subheader("Executive Overview")
        # Visualizing load per machine/station
        st.write(f"Current {RES_LABEL} Load")
        load_chart = df_logs[df_logs['status'] != "Finished"].groupby('status').size()
        st.bar_chart(load_chart)
        
        st.dataframe(df_logs, use_container_width=True, hide_index=True)

# --- TAB 4: MASTERS ---
with tabs[3]:
    st.subheader("System Configuration")
    m_tabs = st.tabs(["Personnel", "Equipment", "Logistics"])
    
    with m_tabs[0]: # Personnel
        with st.form("add_op"):
            new_op = st.text_input("New Operator Name")
            if st.form_submit_button("Register Operator") and new_op:
                conn.table("operator_master").insert({"operator_name": new_op}).execute()
                st.cache_data.clear(); st.rerun()
                
    with m_tabs[1]: # Equipment
        with st.form("add_res"):
            new_res = st.text_input(f"New {RES_LABEL} Name")
            if st.form_submit_button("Register Equipment") and new_res:
                conn.table(MASTER_TABLE).insert({MASTER_COL: new_res}).execute()
                st.cache_data.clear(); st.rerun()
