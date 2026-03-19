import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import io

# 1. Setup & Style
st.set_page_config(page_title="B&G ERP BETA", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

st.markdown("""<style>div.stButton > button { border-radius: 50px; font-weight: 600; }</style>""", unsafe_allow_html=True)

if 'hub' not in st.session_state:
    st.session_state.hub = "Machining Hub"

# --- HUB SELECTION ---
c1, c2, _ = st.columns([1, 1, 2])
if c1.button("⚙️ MACHINING HUB", use_container_width=True, type="primary" if st.session_state.hub == "Machining Hub" else "secondary"):
    st.session_state.hub = "Machining Hub"; st.rerun()
if c2.button("✨ BUFFING HUB", use_container_width=True, type="primary" if st.session_state.hub == "Buffing Hub" else "secondary"):
    st.session_state.hub = "Buffing Hub"; st.rerun()

# --- CONFIGURATION & HUB LOGIC ---
if st.session_state.hub == "Machining Hub":
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_machining_logs", "beta_machine_master", "machine_name", "Machine"
    ACTIVITIES = ["Turning", "Drilling", "Milling", "Keyway", "Dishbending"]
    IS_BUFFING = False
else:
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_buffing_logs", "beta_buffing_station_master", "station_name", "Buffing Station"
    ACTIVITIES = ["Rough Buffing", "Mirror Polishing", "Satin Finish", "RA Value Check"]
    IS_BUFFING = True

OP_MASTER = "operator_master"
VN_MASTER = "vendor_master"
VH_MASTER = "vehicle_master"

# 2. Data Fetching & Sanitization
def get_all_data():
    try:
        m_data = conn.table(MASTER_TABLE).select(MASTER_COL).execute().data or []
        o_data = conn.table(OP_MASTER).select("operator_name").execute().data or []
        v_data = conn.table(VN_MASTER).select("vendor_name").execute().data or []
        
        # AUDIT FIX: Validated Job Codes + Client Names from anchor_projects
        anchor_data = conn.table("anchor_projects").select("job_no, client_name").execute().data or []
        client_map = {str(a['job_no']): a['client_name'] for a in anchor_data}
        anchor_list = sorted(list(client_map.keys()))

        vh_list = []
        if not IS_BUFFING:
            vh_data = conn.table(VH_MASTER).select("vehicle_number").execute().data or []
            vh_list = [vh['vehicle_number'] for vh in vh_data]

        logs = conn.table(DB_TABLE).select("*").order("created_at", desc=True).execute().data or []
        df = pd.DataFrame(logs)
        
        return [r[MASTER_COL] for r in m_data], [o['operator_name'] for o in o_data], \
               [v['vendor_name'] for v in v_data], vh_list, anchor_list, client_map, df
    except Exception as e:
        st.error(f"Data Sync Error: {e}")
        return [], [], [], [], [], {}, pd.DataFrame()

resource_list, operator_list, vendor_list, vehicle_list, anchor_list, client_map, df_main = get_all_data()

tabs = st.tabs(["📝 Production Request", "👨‍💻 Incharge Entry Desk", "📊 Executive Analytics", "🛠️ Masters"])

# --- TAB 1: PRODUCTION REQUEST & LIVE SUMMARY ---
with tabs[0]:
    st.subheader(f"New {st.session_state.hub} Entry")
    with st.form("req_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", [1, 2, 3])
        # AUDIT FIX: Searchable dropdown instead of text input
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

    st.divider()
    st.subheader("🚦 Live Summary Table")
    if not df_main.empty:
        temp_df = df_main.copy()
        temp_df['required_date_dt'] = pd.to_datetime(temp_df['required_date'], errors='coerce')
        today_ts = pd.Timestamp(date.today())
        temp_df['Days Left'] = (temp_df['required_date_dt'] - today_ts).dt.days
        temp_df['required_date'] = temp_df['required_date_dt'].dt.strftime('%d-%m-%Y')
        temp_df['request_date'] = pd.to_datetime(temp_df['request_date'], errors='coerce').dt.strftime('%d-%m-%Y')
        
        unit_filter = st.radio("Filter by Unit", [1, 2, 3], horizontal=True, key="unit_summary_filter")
        summary_cols = ['job_code', 'part_name', 'status', 'priority', 'request_date', 'required_date', 'Days Left', 'special_notes']
        st.dataframe(temp_df[temp_df['unit_no'] == unit_filter][summary_cols], use_container_width=True, hide_index=True)

# --- TAB 2: INCHARGE ENTRY DESK ---
with tabs[1]:
    if not df_main.empty:
        today = date.today()
        active_df = df_main[df_main['status'] != "Finished"].copy()
        # AUDIT FIX: Calculate overdue days for triage sorting
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
        
        overdue_tag = ""
        if req_date_obj and req_date_obj < today:
            overdue_tag = f" 🔴 OVERDUE {job['overdue_days']}D"

        # AUDIT FIX: Expander Title now includes Client and Overdue Status
        with st.expander(f"📌 {job['job_code']} | {c_name} | {job['part_name']} {overdue_tag}"):
            st.info(f"📅 **Req. Date:** {disp_req} | 📝 **Notes:** {job['special_notes']}")
            
            c_del, c_int = st.columns(2)
            d_r = c_del.text_input("Delay Reason", value=job['delay_reason'] or '', key=f"dr_{job['id']}")
            i_n = c_int.text_area("Incharge Note", value=job['intervention_note'] or '', key=f"in_{job['id']}")
            
            if job['status'] == "Pending":
                outsource_label = "Contract Manpower" if IS_BUFFING else "Outsource"
                mode = st.radio("Allotment", ["In-House", outsource_label], key=f"m_{job['id']}", horizontal=True)
                
                if mode == "In-House":
                    c1, c2 = st.columns(2)
                    m = c1.selectbox(f"Assign {RES_LABEL}", resource_list, key=f"m_sel_{job['id']}")
                    o = c2.selectbox("Assign Operator", operator_list, key=f"o_sel_{job['id']}")
                    if st.button("🚀 Start In-House", key=f"b_ih_{job['id']}", use_container_width=True):
                        conn.table(DB_TABLE).update({"status": "In-House", "machine_id": m, "operator_id": o, "delay_reason": d_r, "intervention_note": i_n}).eq("id", job['id']).execute(); st.rerun()
                
                elif mode == "Contract Manpower" and IS_BUFFING:
                    c1, c2 = st.columns(2)
                    v_n = c1.selectbox("Contractor Agency", vendor_list, key=f"v_buff_{job['id']}")
                    c_worker = c2.text_input("Specific Worker Name", key=f"worker_{job['id']}")
                    if st.button("🤝 Assign Contractor", key=f"b_buff_{job['id']}", use_container_width=True):
                        conn.table(DB_TABLE).update({"status": "Outsourced", "vendor_id": v_n, "contractor_name": c_worker, "delay_reason": d_r, "intervention_note": i_n}).eq("id", job['id']).execute(); st.rerun()
                
                else: # Outsource Machining
                    c1, c2, c3 = st.columns(3)
                    v = c1.selectbox("Vendor", vendor_list, key=f"v_sel_{job['id']}")
                    vh = c2.selectbox("Vehicle", vehicle_list, key=f"vh_sel_{job['id']}")
                    gp = c3.text_input("Gatepass No", key=f"gp_{job['id']}")
                    if st.button("🚚 Dispatch Outward", key=f"b_os_{job['id']}", use_container_width=True):
                        conn.table(DB_TABLE).update({"status": "Outsourced", "vendor_id": v, "vehicle_no": vh, "gatepass_no": gp, "delay_reason": d_r, "intervention_note": i_n}).eq("id", job['id']).execute(); st.rerun()
            
            elif job['status'] == "Outsourced":
                wb = st.text_input("Return Waybill / DC No", key=f"wb_{job['id']}")
                if st.button("✅ Mark Received & Finished", key=f"b_rc_{job['id']}", use_container_width=True):
                    conn.table(DB_TABLE).update({"status": "Finished", "waybill_no": wb, "delay_reason": d_r, "intervention_note": i_n}).eq("id", job['id']).execute(); st.rerun()
            
            else: # In-House
                if st.button("🏁 Mark Finished", key=f"b_fi_{job['id']}", use_container_width=True):
                    conn.table(DB_TABLE).update({"status": "Finished", "delay_reason": d_r, "intervention_note": i_n}).eq("id", job['id']).execute(); st.rerun()

# --- TAB 3: EXECUTIVE ANALYTICS ---
with tabs[2]:
    if not df_main.empty:
        st.write(f"### 🌍 {st.session_state.hub} Shop Floor Overview")
        cols = ['job_code', 'part_name', 'status', 'priority', 'request_date', 'required_date']
        cols += ['vendor_id', 'contractor_name'] if IS_BUFFING else ['machine_id', 'operator_id', 'vendor_id', 'vehicle_no', 'gatepass_no']
        st.dataframe(df_main[cols], use_container_width=True, hide_index=True)

# --- TAB 4: MASTERS ---
with tabs[3]:
    st.markdown("### 🛠️ System Master Registry")
    master_options = {MASTER_TABLE: MASTER_COL, OP_MASTER: "operator_name", VN_MASTER: "vendor_name"}
    if not IS_BUFFING: master_options[VH_MASTER] = "vehicle_number"
    
    selected_cat = st.segmented_control("Choose Registry", options=list(master_options.keys()), 
                                       format_func=lambda x: x.replace('_', ' ').replace('beta ', '').title(), default=MASTER_TABLE)
    st.divider()
    col_view, col_add = st.columns([2, 1], gap="large")
    with col_view:
        res = conn.table(selected_cat).select("*").execute().data
        if res:
            master_df = pd.DataFrame(res)
            st.dataframe(master_df[[master_options[selected_cat]]], use_container_width=True, hide_index=True, height=350)
    with col_add:
        with st.container(border=True):
            field_name = master_options[selected_cat].replace('_', ' ').title()
            new_val = st.text_input(f"New {field_name}")
            if st.button("Register Entry", use_container_width=True, type="primary"):
                if new_val.strip():
                    conn.table(selected_cat).insert({master_options[selected_cat]: new_val.strip()}).execute()
                    st.success(f"Registered: {new_val}"); st.rerun()
