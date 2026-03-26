import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import datetime
import pytz
import requests

def send_whatsapp_alert(job_code, part_name, days_overdue):
    # Example using a generic WhatsApp API Gateway
    instance_id = "your_instance_id"
    token = "your_token"
    mobile = "919848993939" # Incharge Mobile Number
    
    message = f"🚨 *OVERDUE ALERT: B&G ERP*\n\n" \
              f"Job: {job_code}\n" \
              f"Part: {part_name}\n" \
              f"Status: OVERDUE by {days_overdue} days.\n" \
              f"Please update the Incharge Desk."
    
    url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
    payload = {"token": token, "to": mobile, "body": message}
    
    try:
        requests.post(url, data=payload)
        return True
    except:
        return False

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

# --- TAB 2: INCHARGE ENTRY DESK (UPDATED) ---
with tabs[1]:
    # Filter for jobs that are not Finished
    active = df_main[df_main['status'] != "Finished"].to_dict('records') if not df_main.empty else []
    
    if not active:
        st.info("No active production requests found.")
    
    for job in active:
        # Use a status-based emoji for the expander label
        prio_emoji = "🔴" if job.get('priority') == "URGENT" else "🟡" if job.get('priority') == "High" else "📌"
        
        with st.expander(f"{prio_emoji} {job['job_code']} | {job['part_name']} ({job['status']})"):
            # --- DATE DISPLAY SECTION ---
            # Formatting dates for better readability
            req_dt = job.get('request_date', 'N/A')
            due_dt = job.get('required_date', 'N/A')
            
            d_col1, d_col2, d_col3 = st.columns(3)
            d_col1.markdown(f"**📅 Requested:** {req_dt}")
            d_col2.markdown(f"**🎯 Required:** {due_dt}")
            
            # Add a small countdown/overdue badge
            if due_dt != 'N/A':
                days_left = (pd.to_datetime(due_dt).date() - get_today_ist()).days
                if days_left < 0:
                    d_col3.error(f"⚠️ {abs(days_left)} Days Overdue")
                else:
                    d_col3.success(f"⏳ {days_left} Days Remaining")
            
            st.divider()

            # --- ENTRY SECTION ---
            c1, c2 = st.columns(2)
            dr = c1.text_input("Delay Reason", value=job.get('delay_reason') or '', key=f"dr_{job['id']}")
            inote = c2.text_area("Incharge Note", value=job.get('intervention_note') or '', key=f"in_{job['id']}")
            
            if job['status'] == "Pending":
                mode = st.radio("Allotment", ["In-House", "Outsource"], key=f"rad_{job['id']}", horizontal=True)
                if mode == "In-House":
                    m = st.selectbox(f"Assign {RES_LABEL}", res_list, key=f"sel_{job['id']}")
                    # Toggle multiselect for Buffing Hub, single select for Machining
                    o = st.multiselect("Assign Operators", op_list, key=f"o_{job['id']}") if IS_BUFFING else st.selectbox("Assign Operator", op_list, key=f"o_{job['id']}")
                    
                    if st.button("🚀 Start Production", key=f"btn_{job['id']}", use_container_width=True):
                        operator_val = ", ".join(o) if isinstance(o, list) else o
                        conn.table(DB_TABLE).update({
                            "status": "In-House", 
                            "machine_id": m, 
                            "operator_id": operator_val, 
                            "delay_reason": dr, 
                            "intervention_note": inote
                        }).eq("id", job['id']).execute()
                        st.rerun()
                else: 
                    v = st.selectbox("Select Vendor", vendor_list, key=f"v_{job['id']}")
                    st.markdown("---")
                    c_gp, c_bn = st.columns(2)
                    gp_no = c_gp.text_input("Gate Pass No.", value=job.get('gate_pass_no') or '', key=f"gp_{job['id']}")
                    bill_no = c_bn.text_input("Bill No.", value=job.get('bill_no') or '', key=f"bn_{job['id']}")
                    
                    if st.button("🚚 Dispatch to Vendor", key=f"d_{job['id']}", use_container_width=True):
                        if not gp_no: 
                            st.warning("Please enter Gate Pass No.")
                        else:
                            conn.table(DB_TABLE).update({
                                "status": "Outsourced", 
                                "vendor_id": v, 
                                "delay_reason": dr, 
                                "intervention_note": inote, 
                                "gate_pass_no": gp_no, 
                                "bill_no": bill_no
                            }).eq("id", job['id']).execute()
                            st.rerun()
            
            # Allow "Finish" for any job already in progress (In-House or Outsourced)
            elif job['status'] in ["In-House", "Outsourced"]:
                if st.button("🏁 Mark as Finished", key=f"f_{job['id']}", use_container_width=True, type="primary"):
                    conn.table(DB_TABLE).update({
                        "status": "Finished", 
                        "delay_reason": dr, 
                        "intervention_note": inote
                    }).eq("id", job['id']).execute()
                    st.rerun()

# --- TAB 3: EXECUTIVE ANALYTICS ---
with tabs[2]:
    st.subheader(f"📊 {st.session_state.hub} Executive Dashboard")
    if not df_main.empty:
        df_ana = df_main.copy()
        df_ana['required_date'] = pd.to_datetime(df_ana['required_date'], errors='coerce').dt.date
        today = get_today_ist()

        # 1. Health Logic
        def check_delay(row):
            if row['status'] != "Finished" and row['required_date'] and row['required_date'] < today:
                return "🚩 DELAYED"
            return "✅ On Track"
        df_ana['Health'] = df_ana.apply(check_delay, axis=1)

        # 2. Top-Level Metrics
        total_active = len(df_ana[df_ana['status'] != "Finished"])
        delayed_df = df_ana[df_ana['Health'] == "🚩 DELAYED"]
        delayed_count = len(delayed_df)
        ontrack_count = total_active - delayed_count

        m1, m2, m3 = st.columns(3)
        m1.metric("Active Work Orders", total_active)
        m2.metric("Critical Delays", delayed_count, delta=f"{delayed_count} overdue", delta_color="inverse")
        m3.metric("Healthy Jobs", ontrack_count)

        # --- WHATSAPP NOTIFICATION TRIGGER ---
        if delayed_count > 0:
            if st.button(f"📢 Send {delayed_count} Overdue Alerts via WhatsApp", use_container_width=True):
                success_count = 0
                for _, row in delayed_df.iterrows():
                    # Calculate days overdue
                    days_ov = abs((pd.to_datetime(row['required_date']).date() - today).days)
                    
                    if send_whatsapp_alert(row['job_code'], row['part_name'], days_ov):
                        success_count += 1
                
                if success_count > 0:
                    st.success(f"✅ {success_count} Notifications sent successfully!")
                else:
                    st.error("🚨 Failed to send notifications. Check API credentials.")
        st.divider()

        # 3. Unit-wise Summary Section
        st.markdown("#### 🏢 Unit-wise Overdue Analysis")
        if delayed_count > 0:
            unit_delay = delayed_df.groupby('unit_no').size().reset_index(name='Count')
            # Ensure all units 1, 2, 3 are present for the chart
            all_units = pd.DataFrame({'unit_no': [1, 2, 3]})
            unit_delay = all_units.merge(unit_delay, on='unit_no', how='left').fillna(0)
            
            st.bar_chart(unit_delay.set_index('unit_no'), height=200, color="#FF4B4B")
        else:
            st.success("🎉 All units are currently on track!")

        st.divider()

        # 4. Advanced Filtering
        c_f1, c_f2 = st.columns(2)
        search_q = c_f1.text_input("🔍 Search Job/Part", "").lower()
        status_f = c_f2.multiselect("Filter by Status", sorted(df_ana['status'].unique()))

        if search_q:
            df_ana = df_ana[df_ana['job_code'].str.lower().str.contains(search_q) | df_ana['part_name'].str.lower().str.contains(search_q)]
        if status_f:
            df_ana = df_ana[df_ana['status'].isin(status_f)]

        # 5. UI: Table Rendering
        display_cols = ['Health', 'unit_no', 'job_code', 'part_name', 'activity_type', 'operator_id', 'status', 'priority', 'required_date', 'intervention_note', 'delay_reason']
        existing_cols = [c for c in display_cols if c in df_ana.columns]
        
        st.dataframe(
            df_ana[existing_cols], 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Health": st.column_config.TextColumn("Status Health"),
                "unit_no": "Unit", "job_code": "Job Code", "part_name": "Part Name",
                "activity_type": "Process", "operator_id": "Operators", "status": "Status",
                "priority": "Priority", "required_date": "Target Date",
                "intervention_note": "Incharge Remarks", "delay_reason": "Delay Reason"
            }
        )
        st.download_button("📥 Export CSV", df_ana[existing_cols].to_csv(index=False).encode('utf-8'), "BG_ERP_Report.csv", "text/csv")
    else: st.info("No data available.")

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
        new_v = st.text_input(f"New {m_opt[sel]}")
        if st.button("Register") and new_v:
            conn.table(sel).insert({col_name: new_v}).execute(); st.rerun()
