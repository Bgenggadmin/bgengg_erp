import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import datetime
import pytz
import urllib.parse

# --- 1. CONFIGURATION & HELPERS ---
IST = pytz.timezone('Asia/Kolkata')

def get_today_ist():
    return datetime.datetime.now(IST).date()

def generate_wa_link(job_code, part_name, days_overdue):
    """Creates a free wa.me link to nudge the incharge."""
    mobile = "919848993939" # Your Incharge Mobile Number
    message = (f"🚩 *B&G OVERDUE ALERT*\n\n"
               f"*Job:* {job_code}\n"
               f"*Part:* {part_name}\n"
               f"*Status:* OVERDUE by {days_overdue} days.\n"
               f"Please update the status in ERP.")
    encoded_msg = urllib.parse.quote(message)
    return f"https://wa.me/{mobile}?text={encoded_msg}"

# --- 2. SETUP & STYLE ---
st.set_page_config(page_title="B&G ERP BETA", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

st.markdown("""
<style>
    div.stButton > button { border-radius: 50px; font-weight: 600; }
    .overdue-text { color: #FF4B4B; font-weight: bold; }
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

if st.session_state.hub == "Machining Hub":
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_machining_logs", "master_machines", "name", "Machine"
    ACTIVITIES = ["Turning", "Drilling", "Milling", "Keyway", "Dishbending"]
    IS_BUFFING = False
else:
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_buffing_logs", "master_machines", "name", "Buffing Station"
    ACTIVITIES = ["Rough Buffing", "Mirror Polishing", "Satin Finish", "RA Value Check"]
    IS_BUFFING = True

OP_MASTER, VN_MASTER, VH_MASTER = "master_workers", "beta_vendor_master", "master_vehicles"

# --- 3. DATA FETCHING ---
def get_all_data():
    try:
        m_data = conn.table(MASTER_TABLE).select(MASTER_COL).execute().data or []
        o_data = conn.table(OP_MASTER).select("name").execute().data or []
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

# --- TAB 1: PRODUCTION REQUEST ---
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

# --- TAB 2: INCHARGE ENTRY DESK ---
with tabs[1]:
    active = df_main[df_main['status'] != "Finished"].to_dict('records') if not df_main.empty else []
    if not active:
        st.info("No active production requests found.")
    
    for job in active:
        prio_emoji = "🔴" if job.get('priority') == "URGENT" else "🟡" if job.get('priority') == "High" else "📌"
        with st.expander(f"{prio_emoji} {job['job_code']} | {job['part_name']} ({job['status']})"):
            due_dt = job.get('required_date', 'N/A')
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**📅 Requested:** {job.get('request_date', 'N/A')}")
            c2.markdown(f"**🎯 Required:** {due_dt}")
            
            if due_dt != 'N/A':
                days_left = (pd.to_datetime(due_dt).date() - get_today_ist()).days
                if days_left < 0:
                    c3.error(f"⚠️ {abs(days_left)} Days Overdue")
                else:
                    c3.success(f"⏳ {days_left} Days Remaining")
            
            st.divider()
            cx, cy = st.columns(2)
            dr = cx.text_input("Delay Reason", value=job.get('delay_reason') or '', key=f"dr_{job['id']}")
            inote = cy.text_area("Incharge Note", value=job.get('intervention_note') or '', key=f"in_{job['id']}")
            
            if job['status'] == "Pending":
                mode = st.radio("Allotment", ["In-House", "Outsource"], key=f"rad_{job['id']}", horizontal=True)
                if mode == "In-House":
                    m = st.selectbox(f"Assign {RES_LABEL}", res_list, key=f"sel_{job['id']}")
                    o = st.multiselect("Assign Operators", op_list, key=f"o_{job['id']}") if IS_BUFFING else st.selectbox("Assign Operator", op_list, key=f"o_{job['id']}")
                    if st.button("🚀 Start Production", key=f"btn_{job['id']}", use_container_width=True):
                        operator_val = ", ".join(o) if isinstance(o, list) else o
                        conn.table(DB_TABLE).update({"status": "In-House", "machine_id": m, "operator_id": operator_val, "delay_reason": dr, "intervention_note": inote}).eq("id", job['id']).execute()
                        st.rerun()
                else: 
                    v = st.selectbox("Select Vendor", vendor_list, key=f"v_{job['id']}")
                    gp_no = st.text_input("Gate Pass No.", key=f"gp_{job['id']}")
                    if st.button("🚚 Dispatch to Vendor", key=f"d_{job['id']}", use_container_width=True):
                        conn.table(DB_TABLE).update({"status": "Outsourced", "vendor_id": v, "delay_reason": dr, "gate_pass_no": gp_no, "intervention_note": inote}).eq("id", job['id']).execute()
                        st.rerun()
            elif job['status'] in ["In-House", "Outsourced"]:
                if st.button("🏁 Mark as Finished", key=f"f_{job['id']}", use_container_width=True, type="primary"):
                    conn.table(DB_TABLE).update({"status": "Finished", "delay_reason": dr, "intervention_note": inote}).eq("id", job['id']).execute()
                    st.rerun()

# --- TAB 3: EXECUTIVE ANALYTICS ---
with tabs[2]:
    st.subheader(f"📊 {st.session_state.hub} Executive Dashboard")
    if not df_main.empty:
        df_ana = df_main.copy()
        df_ana['required_date'] = pd.to_datetime(df_ana['required_date'], errors='coerce').dt.date
        today = get_today_ist()
        
        # Health Logic
        df_ana['Health'] = df_ana.apply(lambda r: "🚩 DELAYED" if r['status'] != "Finished" and r['required_date'] < today else "✅ On Track", axis=1)
        delayed_df = df_ana[df_ana['Health'] == "🚩 DELAYED"]

        m1, m2, m3 = st.columns(3)
        m1.metric("Active Work Orders", len(df_ana[df_ana['status'] != "Finished"]))
        m2.metric("Critical Delays", len(delayed_df))
        m3.metric("On Track", len(df_ana[df_ana['status'] != "Finished"]) - len(delayed_df))

        # FREE WHATSAPP NUDGE SECTION
        if not delayed_df.empty:
            st.divider()
            st.markdown("#### 📲 Manual WhatsApp Nudge (Free)")
            for _, row in delayed_df.iterrows():
                days_ov = abs((row['required_date'] - today).days)
                wa_url = generate_wa_link(row['job_code'], row['part_name'], days_ov)
                st.link_button(f"Nudge Incharge for {row['job_code']} ({days_ov} Days Overdue)", wa_url, use_container_width=True)

        st.divider()
        st.dataframe(df_ana, use_container_width=True, hide_index=True)
    else:
        st.info("No data available.")

# --- TAB 4: MASTERS ---
with tabs[3]:
    m_opt = {MASTER_TABLE: "Machine/Station", OP_MASTER: "Operator", VN_MASTER: "Vendor"}
    if not IS_BUFFING: m_opt[VH_MASTER] = "Vehicle"
    sel = st.segmented_control("Registry", options=list(m_opt.keys()), format_func=lambda x: m_opt[x], default=MASTER_TABLE)
    col_name = "vendor_name" if sel == VN_MASTER else "reg_no" if sel == VH_MASTER else "name"
    
    v_col, a_col = st.columns([2, 1])
    with v_col:
        r = conn.table(sel).select("*").execute().data
        if r: st.dataframe(pd.DataFrame(r)[[col_name]], use_container_width=True)
    with a_col:
        new_v = st.text_input(f"Add New {m_opt[sel]}")
        if st.button("Register") and new_v:
            conn.table(sel).insert({col_name: new_v}).execute(); st.rerun()
