import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')

def get_today_ist():
    return datetime.datetime.now(IST).date()
    
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

# --- CONFIGURATION ---
if st.session_state.hub == "Machining Hub":
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_machining_logs", "master_machines", "name", "Machine"
    ACTIVITIES = ["Turning", "Drilling", "Milling", "Keyway", "Dishbending"]
    IS_BUFFING = False
else:
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_buffing_logs", "master_machines", "name", "Buffing Station"
    ACTIVITIES = ["Rough Buffing", "Mirror Polishing", "Satin Finish", "RA Value Check"]
    IS_BUFFING = True

OP_MASTER, VN_MASTER, VH_MASTER = "master_workers", "beta_vendor_master", "master_vehicles"

# --- 2. Data Fetching ---
def get_all_data():
    try:
        m_data = conn.table(MASTER_TABLE).select(MASTER_COL).execute().data or []
        o_data = conn.table(OP_MASTER).select("name").execute().data or []
        
        # FIX 1: Access the dictionary using 'vendor_name'
        v_raw = conn.table(VN_MASTER).select("vendor_name").execute().data or []
        v_list = [v['vendor_name'] for v in v_raw]
        
        j_master = conn.table("anchor_projects").select("job_no").execute().data or []
        job_list = sorted(list(set([j['job_no'] for j in j_master if j.get('job_no')])))
        vh_list = [v['reg_no'] for v in (conn.table(VH_MASTER).select("reg_no").execute().data or [])] if not IS_BUFFING else []
        logs = conn.table(DB_TABLE).select("*").order("created_at", desc=True).execute().data or []
        df = pd.DataFrame(logs)
        
        return [r[MASTER_COL] for r in m_data], [o['name'] for o in o_data], v_list, vh_list, df, job_list
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return [], [], [], [], pd.DataFrame(), []

res_list, op_list, vendor_list, vh_list, df_main, master_jobs = get_all_data()
tabs = st.tabs(["📝 Production Request", "👨‍💻 Incharge Entry Desk", "📊 Executive Analytics", "🛠️ Masters"])

# --- TAB 1: REQUEST ---
with tabs[0]:
    st.subheader(f"New {st.session_state.hub} Entry")
    with st.form("req_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", [1, 2, 3])
        j_code = c1.selectbox("Job Code", [""] + master_jobs) 
        part = c2.text_input("Part Name")
        act = c2.selectbox("Activity", ACTIVITIES)
        req_d = c3.date_input("Required Date")
        prio = c3.selectbox("Priority", ["Low", "Medium", "High", "URGENT"])
        
        if st.form_submit_button("Submit Request"):
            if not j_code or not part:
                st.error("🚨 Selection Required: Job Code and Part Name are mandatory.")
            else:
                payload = {
                    "unit_no": u_no, "job_code": j_code, "part_name": part, "activity_type": act, 
                    "required_date": req_d.isoformat(), "request_date": get_today_ist().isoformat(),
                    "status": "Pending", "priority": prio
                }
                conn.table(DB_TABLE).insert(payload).execute()
                st.success(f"✅ Request Logged: {j_code}")
                st.rerun()

    st.divider()
    if not df_main.empty:
        df_sum = df_main.copy()
        df_sum['required_date'] = pd.to_datetime(df_sum['required_date'], errors='coerce')
        df_sum['Days Left'] = (df_sum['required_date'] - pd.Timestamp(get_today_ist())).dt.days
        u_filt = st.radio("Unit Filter", [1, 2, 3], horizontal=True)
        st.dataframe(df_sum[df_sum['unit_no'] == u_filt][['job_code', 'part_name', 'status', 'priority', 'required_date', 'Days Left']], use_container_width=True, hide_index=True)

# --- TAB 2: INCHARGE ENTRY DESK ---
with tabs[1]:
    active = df_main[df_main['status'] != "Finished"].to_dict('records') if not df_main.empty else []
    for job in active:
        with st.expander(f"📌 {job['job_code']} | {job['part_name']} ({job['status']})"):
            c1, c2 = st.columns(2)
            dr = c1.text_input("Delay Reason", value=job.get('delay_reason') or '', key=f"dr_{job['id']}")
            inote = c2.text_area("Incharge Note", value=job.get('intervention_note') or '', key=f"in_{job['id']}")
            
            if job['status'] == "Pending":
                mode = st.radio("Allotment", ["In-House", "Outsource"], key=f"rad_{job['id']}", horizontal=True)
                
                if mode == "In-House":
                    m = st.selectbox(f"Assign {RES_LABEL}", res_list, key=f"sel_{job['id']}")
                    
                    # CHANGED: selectbox -> multiselect for multiple operators
                    o = st.multiselect("Assign Operators (Multiple)", op_list, key=f"o_{job['id']}")
                    
                    if st.button("🚀 Start", key=f"btn_{job['id']}"):
                        if not o:
                            st.warning("Please assign at least one operator.")
                        else:
                            # Join names with a comma to store in a single text column
                            ops_string = ", ".join(o)
                            
                            update_payload = {
                                "status": "In-House", 
                                "machine_id": m, 
                                "operator_id": ops_string, # Now stores "Name 1, Name 2"
                                "delay_reason": dr, 
                                "intervention_note": inote
                            }
                            
                            conn.table(DB_TABLE).update(update_payload).eq("id", job['id']).execute()
                            st.success(f"Started with: {ops_string}")
                            st.rerun()
                else: 
                    v = st.selectbox("Select Vendor", vendor_list, key=f"v_{job['id']}")
                    st.markdown("---")
                    c_gp, c_bn = st.columns(2)
                    gp_no = c_gp.text_input("Gate Pass No.", value=job.get('gate_pass_no') or '', key=f"gp_{job['id']}")
                    bill_no = c_bn.text_input("Bill No.", value=job.get('bill_no') or '', key=f"bn_{job['id']}")
                    
                    if st.button("🚚 Dispatch", key=f"d_{job['id']}", use_container_width=True):
                        if not gp_no:
                            st.warning("Please enter Gate Pass No.")
                        else:
                            conn.table(DB_TABLE).update({
                                "status": "Outsourced", "vendor_id": v, "delay_reason": dr, 
                                "intervention_note": inote, "gate_pass_no": gp_no, "bill_no": bill_no
                            }).eq("id", job['id']).execute()
                            st.rerun()
            
            elif st.button("🏁 Finish", key=f"f_{job['id']}", use_container_width=True):
                conn.table(DB_TABLE).update({"status": "Finished", "delay_reason": dr, "intervention_note": inote}).eq("id", job['id']).execute()
                st.rerun()

# --- TAB 3: ANALYTICS ---
with tabs[2]:
    if not df_main.empty:
        st.dataframe(df_main[['job_code', 'part_name', 'status', 'priority', 'required_date']], use_container_width=True, hide_index=True)

# --- TAB 4: MASTERS ---
with tabs[3]:
    # Labels for the UI
    m_opt = {MASTER_TABLE: "Machine/Station", OP_MASTER: "Operator", VN_MASTER: "Vendor"}
    if not IS_BUFFING: m_opt[VH_MASTER] = "Vehicle"
    
    sel = st.segmented_control("Registry", options=list(m_opt.keys()), format_func=lambda x: m_opt[x], default=MASTER_TABLE)
    
    # FIX 2: Define dynamic column names based on the selected registry
    if sel == VN_MASTER:
        col_name = "vendor_name"
    elif sel == VH_MASTER:
        col_name = "reg_no"
    else:
        col_name = "name"

    v_col, a_col = st.columns([2, 1])
    with v_col:
        r = conn.table(sel).select("*").execute().data
        if r:
            st.dataframe(pd.DataFrame(r)[[col_name]], use_container_width=True)
    with a_col:
        new_v = st.text_input(f"New {m_opt[sel]}")
        if st.button("Register") and new_v:
            conn.table(sel).insert({col_name: new_v}).execute()
            st.rerun()
