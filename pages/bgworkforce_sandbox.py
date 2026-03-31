import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP & CONSTANTS ---
IST = pytz.timezone('Asia/Kolkata')
LATE_THRESHOLD = time(9, 15)
# GENERATE 24 HOUR SLOTS
LOG_SLOTS = [f"{str(h).zfill(2)}:00" for h in range(24)]

LEAVE_QUOTA = {
    "Casual Leave": 12,
    "Sick Leave": 10,
    "Earned Leave": 15,
    "Loss of Pay": 0
}

st.set_page_config(page_title="B&G HR | ERP System", layout="wide", page_icon="📅")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SMART UTILITIES ---
def to_ist(series):
    if series is None or (isinstance(series, pd.Series) and series.empty):
        return series
    dt = pd.to_datetime(series)
    if dt.dt.tz is None: dt = dt.dt.tz_localize('UTC')
    return dt.dt.tz_convert(IST)

def format_ts(ts):
    if not ts: return "-"
    try:
        dt = pd.to_datetime(ts)
        if dt.tzinfo is None: dt = pytz.utc.localize(dt)
        return dt.astimezone(IST).strftime('%d-%m-%Y %I:%M %p')
    except: return str(ts)

def get_now_ist():
    return datetime.now(IST)

def convert_df(df):
    return df.to_csv(index=False).encode('utf-8')

def get_ampm_label(slot_str):
    h = int(slot_str.split(":")[0])
    return datetime.now().replace(hour=h, minute=0).strftime("%I:00 %p")

# --- 3. DATA LOADERS ---
@st.cache_data(ttl=5)
def get_leave_requests():
    try:
        res = conn.table("leave_requests").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except: return pd.DataFrame()

def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return [s['name'] for s in res.data] if res.data else ["Admin", "Staff Member"]
    except: return ["Admin", "Staff Member"]

def get_job_codes():
    try:
        res = conn.table("anchor_projects").select("job_no").eq("status", "Won").execute()
        jobs = [j['job_no'] for j in res.data if j.get('job_no')] if res.data else []
        return ["GENERAL/INTERNAL", "ACCOUNTS", "PURCHASE", "MAINTENANCE"] + sorted(list(set(jobs)))
    except: return ["GENERAL/INTERNAL", "ACCOUNTS", "PURCHASE", "MAINTENANCE"]

def is_log_due(employee_name):
    if st.session_state.get('snooze_until') and get_now_ist() < st.session_state['snooze_until']:
        return None
    now_t = get_now_ist().strftime("%H:%M")
    past_slots = [s for s in LOG_SLOTS if s <= now_t]
    if not past_slots: return None
    latest_slot = past_slots[-1]
    today_str = str(date.today())
    res = conn.table("work_logs").select("*").eq("employee_name", employee_name).eq("work_date", today_str).order("created_at", desc=True).limit(1).execute().data
    if not res: return latest_slot
    last_log_t = pd.to_datetime(res[0]['created_at']).tz_convert(IST).strftime("%H:%M")
    return latest_slot if last_log_t < latest_slot else None

# --- 4. NAVIGATION ---
tabs = st.tabs(["🕒 Attendance & Productivity", "📝 Leave Application", "📊 My Balance", "🔐 HR Admin Panel"])

# --- TAB 1: ATTENDANCE & WORK LOGS ---
with tabs[0]:
    st.subheader("🕒 Daily Time Office & Productivity Tracker")
    att_user = st.selectbox("Identify Yourself", get_staff_list(), key="att_user")
    today = str(date.today())

    st.markdown("### 📊 Your Today's Status")
    emp_summ_res = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
    work_summ_res = conn.table("work_logs").select("*").eq("employee_name", att_user).eq("work_date", today).order("created_at").execute().data
    move_summ_res = conn.table("movement_logs").select("*").eq("employee_name", att_user).gte("exit_time", f"{today}T00:00:00").execute().data
    
    c_sum1, c_sum2, c_sum3 = st.columns(3)
    if emp_summ_res:
        log_data = emp_summ_res[0]
        start_t = pd.to_datetime(log_data['punch_in']).tz_convert(IST)
        end_t = pd.to_datetime(log_data['punch_out']).tz_convert(IST) if log_data.get('punch_out') else get_now_ist()
        dur = (end_t - start_t).total_seconds() / 3600
        logged_hours = sum([float(w['hours_spent']) for w in work_summ_res]) if work_summ_res else 0.0
        c_sum1.metric("Punch In", start_t.strftime('%I:%M %p'))
        c_sum2.metric("Shift Duration", f"{dur:.2f} hrs")
        c_sum3.metric("Logged Work", f"{logged_hours:.2f} hrs", delta=f"{int((logged_hours/dur)*100) if dur > 0.1 else 0}% Eff.")
        
        st.write("#### 📝 Today's Activity Details")
        sl, sr = st.columns(2)
        with sl:
            with st.expander(f"Work Logs ({len(work_summ_res)})"):
                for w in work_summ_res: st.caption(f"✅ {w['task_description']} ({w['hours_spent']}h)")
        with sr:
            with st.expander(f"Movements ({len(move_summ_res)})"):
                for m in move_summ_res:
                    out_t = pd.to_datetime(m['exit_time']).tz_convert(IST).strftime('%I:%M %p')
                    st.caption(f"🚶 {out_t} | {m['destination']}")
    else: st.info("No punch record found for today.")
    
    st.divider()
    due_slot = is_log_due(att_user)
    if due_slot:
        st.warning(f"🔔 **MANDATORY UPDATE:** It is past {get_ampm_label(due_slot)}. Please log activity.")
        with st.form("mandatory_log_form"):
            slot_time = st.selectbox("Slot", LOG_SLOTS, index=LOG_SLOTS.index(due_slot), format_func=get_ampm_label)
            job_code = st.selectbox("Job No", get_job_codes())
            task_desc = st.text_area("Detail")
            if st.form_submit_button("✅ Submit"):
                if task_desc:
                    conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_code}] @{slot_time}: {task_desc}", "hours_spent": 1.0, "work_date": today}).execute()
                    st.rerun()
        st.stop()

    ca, cb, cc = st.columns([1.5, 1.5, 2.5])
    with ca:
        st.markdown("### 🏢 Shift Punch")
        if not emp_summ_res:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute(); st.rerun()
        else:
            log = emp_summ_res[0]
            st.success(f"✅ In: {pd.to_datetime(log['punch_in']).tz_convert(IST).strftime('%I:%M %p')}")
            if not log.get('punch_out') and st.button("🏁 PUNCH OUT", use_container_width=True):
                conn.table("attendance_logs").update({"punch_out": get_now_ist().isoformat()}).eq("id", log['id']).execute(); st.rerun()
    with cb:
        st.markdown("### 🚶 Movement")
        active_move = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        if not active_move:
            with st.form("move_form"):
                reason = st.selectbox("Category", ["Inter-Unit Transfer", "Site Delivery", "Vendor Visit", "Lunch", "Personal"])
                dest = st.text_input("Destination")
                if st.form_submit_button("📤 TIME OUT") and dest:
                    conn.table("movement_logs").insert({"employee_name": att_user, "reason": reason, "destination": dest.upper(), "exit_time": get_now_ist().isoformat()}).execute(); st.rerun()
        else:
            if st.button("📥 LOG TIME IN", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", active_move[0]['id']).execute(); st.rerun()
    with cc:
        st.markdown("### 📝 Work log")
        with st.form("manual_work_log"):
            slot_t = st.selectbox("Slot", LOG_SLOTS, format_func=get_ampm_label)
            job_c = st.selectbox("Job", get_job_codes(), key="man_job")
            task = st.text_area("Update")
            if st.form_submit_button("Post Log") and task:
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_c}] @{slot_t}: {task}", "hours_spent": 1.0, "work_date": today}).execute(); st.rerun()

# --- TAB 2 & 3: LEAVE ---
with tabs[1]:
    st.subheader("New Leave Application")
    with st.form("leave_form"):
        col1, col2 = st.columns(2)
        emp_name_l = col1.selectbox("Employee Name", get_staff_list())
        l_type = col2.selectbox("Type", list(LEAVE_QUOTA.keys()))
        sd = st.date_input("Start", min_value=date.today())
        ed = st.date_input("End", min_value=date.today())
        reason_l = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": emp_name_l, "leave_type": l_type, "start_date": str(sd), "end_date": str(ed), "reason": reason_l, "status": "Pending"}).execute()
            st.success("✅ Submitted."); st.cache_data.clear(); st.rerun()

with tabs[2]:
    st.subheader("📊 Your Leave Balance")
    df_leaves = get_leave_requests()
    user_sel_bal = st.selectbox("View Records for:", get_staff_list(), key="bal_user")
    if not df_leaves.empty:
        user_df = df_leaves[df_leaves['employee_name'] == user_sel_bal].copy()
        app_df = user_df[user_df['status'] == 'Approved'].copy()
        leaves_used = {}
        if not app_df.empty:
            app_df['start_date'] = pd.to_datetime(app_df['start_date'])
            app_df['end_date'] = pd.to_datetime(app_df['end_date'])
            app_df['days_count'] = (app_df['end_date'] - app_df['start_date']).dt.days + 1
            leaves_used = app_df.groupby('leave_type')['days_count'].sum().to_dict()
        m_cols = st.columns(len(LEAVE_QUOTA))
        for i, (l_name, quota) in enumerate(LEAVE_QUOTA.items()):
            used = leaves_used.get(l_name, 0)
            if l_name == "Loss of Pay": m_cols[i].metric(l_name, f"{int(used)} Days")
            else: m_cols[i].metric(l_name, f"{int(quota - used)} Left", f"Used: {int(used)}", delta_color="inverse")

# --- TAB 4: HR ADMIN PANEL (WITH FULL EXPORTS) ---
with tabs[3]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        today_str = str(date.today())
        st.markdown("### ⚙️ Global Admin Filters")
        c1, c2 = st.columns(2)
        s_name = c1.selectbox("Filter Staff Name", ["All Staff"] + get_staff_list(), key="adm_filt")
        export_mode = c2.selectbox("Export Date Range", ["Weekly", "Monthly", "Custom Date"])
        
        if export_mode == "Weekly":
            sr, er = date.today() - timedelta(days=7), date.today()
        elif export_mode == "Monthly":
            sr, er = date.today() - timedelta(days=30), date.today()
        else:
            sr = st.date_input("From", value=date.today() - timedelta(days=7))
            er = st.date_input("To", value=date.today())

        admin_tabs = st.tabs(["📈 Operations Analytics", "🕒 Detailed Logs", "📬 Leave Approvals"])
        
        with admin_tabs[0]:
            t_att = conn.table("attendance_logs").select("*").eq("work_date", today_str).execute().data
            t_work = conn.table("work_logs").select("*").eq("work_date", today_str).execute().data
            if t_att:
                df_att = pd.DataFrame(t_att); df_work = pd.DataFrame(t_work) if t_work else pd.DataFrame(columns=['employee_name','hours_spent'])
                df_att['p_in_dt'] = pd.to_datetime(df_att['punch_in']).dt.tz_convert(IST)
                late_df = df_att[df_att['p_in_dt'].dt.time > LATE_THRESHOLD]
                work_sums = df_work.groupby('employee_name')['hours_spent'].sum().reset_index()
                col1, col2, col3 = st.columns(3)
                col1.error(f"⌛ Late Comers ({len(late_df)})")
                if not late_df.empty: col1.dataframe(late_df[['employee_name', 'p_in_dt']], hide_index=True)
                col2.warning(f"📉 Low Work Logs (<4h)"); col2.dataframe(work_sums[work_sums['hours_spent'] < 4.0], hide_index=True)
                col3.success(f"🚀 High Work Logs (>7.5h)"); col3.dataframe(work_sums[work_sums['hours_spent'] > 7.5], hide_index=True)

        with admin_tabs[1]:
            st.subheader("📜 Activity Logs & CSV Export")
            l_type = st.radio("Select Category", ["Work Logs", "Movement History", "Attendance Timeline"], horizontal=True)
            
            if st.button(f"📥 Generate CSV Export for {s_name}"):
                table = "work_logs" if l_type=="Work Logs" else "movement_logs" if l_type=="Movement History" else "attendance_logs"
                q = conn.table(table).select("*")
                if s_name != "All Staff": q = q.eq("employee_name", s_name)
                if l_type == "Movement History":
                    q = q.gte("exit_time", f"{sr}T00:00:00").lte("exit_time", f"{er}T23:59:59")
                else:
                    q = q.gte("work_date", str(sr)).lte("work_date", str(er))
                
                exp = q.execute().data
                if exp: st.download_button("Download CSV", data=convert_df(pd.DataFrame(exp)), file_name=f"{l_type}_{s_name}.csv")
                else: st.warning("No data found.")

            res = conn.table("work_logs" if l_type=="Work Logs" else "movement_logs" if l_type=="Movement History" else "attendance_logs").select("*").eq("work_date" if l_type!="Movement History" else "exit_time", today_str if l_type!="Movement History" else today_str).execute().data
            if res:
                df_v = pd.DataFrame(res)
                if s_name != "All Staff": df_v = df_v[df_v['employee_name'] == s_name]
                st.dataframe(df_v, hide_index=True)

        with admin_tabs[2]:
            df_all = get_leave_requests()
            if not df_all.empty:
                st.download_button("📥 Export Leave History", data=convert_df(df_all), file_name="Leave_Report.csv")
                pend = df_all[df_all['status'] == 'Pending']
                for _, row in pend.iterrows():
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 2, 2])
                        c1.write(f"**{row['employee_name']}** | {row['leave_type']}")
                        if c3.button("✅ Approve", key=f"ap_{row['id']}"):
                            conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute(); st.rerun()
                        with c3.popover("❌ Reject"):
                            rn = st.text_input("Reason", key=f"rn_{row['id']}")
                            if st.button("Confirm", key=f"rb_{row['id']}"):
                                conn.table("leave_requests").update({"status": "Rejected", "reject_reason": rn}).eq("id", row['id']).execute(); st.rerun()
