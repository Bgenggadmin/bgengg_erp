import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz

# --- 1. SETUP & CONSTANTS ---
IST = pytz.timezone('Asia/Kolkata')
LOG_SLOTS = ["10:00", "11:00", "12:00", "13:00", "14:30", "15:30", "16:30", "17:30"]

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

    # PERSONAL SUMMARY (Fixed logic for exact duration)
    st.markdown("### 📊 Your Today's Status")
    p_att = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
    p_work = conn.table("work_logs").select("hours_spent").eq("employee_name", att_user).eq("work_date", today).execute().data
    
    sc1, sc2, sc3 = st.columns(3)
    if p_att:
        p_in = pd.to_datetime(p_att[0]['punch_in']).tz_convert(IST)
        p_out = pd.to_datetime(p_att[0]['punch_out']).tz_convert(IST) if p_att[0].get('punch_out') else get_now_ist()
        s_dur = (p_out - p_in).total_seconds() / 3600
        w_logs = sum([float(w['hours_spent']) for w in p_work]) if p_work else 0.0
        sc1.metric("Punch In", p_in.strftime('%I:%M %p'))
        sc2.metric("Shift Duration", f"{s_dur:.2f} hrs")
        sc3.metric("Log Efficiency", f"{int((w_logs/s_dur)*100) if s_dur > 0.1 else 0}%")
    else:
        st.info("No punch record for today.")

    st.divider()
    due_slot = is_log_due(att_user)
    if due_slot:
        st.warning(f"🔔 **MANDATORY UPDATE:** It is past {due_slot}. Please log your activity.")
        with st.form("mandatory_log_form"):
            slot_time = st.selectbox("Slot", LOG_SLOTS, index=LOG_SLOTS.index(due_slot))
            job_code = st.selectbox("Job No", get_job_codes())
            task_desc = st.text_area(f"Detail for {slot_time}")
            if st.form_submit_button("✅ Submit"):
                if task_desc:
                    conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_code}] @{slot_time}: {task_desc}", "hours_spent": 1.0, "work_date": today}).execute()
                    st.rerun()
        st.stop()

    col_a, col_b, col_c = st.columns([1.5, 1.5, 2.5])
    with col_a:
        st.markdown("### 🏢 Shift Punch")
        if not p_att:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute(); st.rerun()
        else:
            st.success(f"✅ In: {pd.to_datetime(p_att[0]['punch_in']).tz_convert(IST).strftime('%I:%M %p')}")
            if not p_att[0].get('punch_out') and st.button("🏁 PUNCH OUT", use_container_width=True):
                conn.table("attendance_logs").update({"punch_out": get_now_ist().isoformat()}).eq("id", p_att[0]['id']).execute(); st.rerun()

    with col_b:
        st.markdown("### 🚶 Movement")
        active_move = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        if not active_move:
            with st.form("move_form", clear_on_submit=True):
                reason = st.selectbox("Category", ["Inter-Unit Transfer", "Site Delivery", "Vendor Visit", "Lunch", "Personal"])
                dest = st.text_input("Destination")
                if st.form_submit_button("📤 TIME OUT"):
                    if dest: conn.table("movement_logs").insert({"employee_name": att_user, "reason": reason, "destination": dest.upper(), "exit_time": get_now_ist().isoformat()}).execute(); st.rerun()
        else:
            st.warning(f"⚠️ At **{active_move[0]['destination']}**")
            if st.button("📥 LOG TIME IN", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", active_move[0]['id']).execute(); st.rerun()

    with col_c:
        st.markdown("### 📝 Work log")
        with st.form("manual_work_log", clear_on_submit=True):
            slot_t = st.selectbox("Time Slot", LOG_SLOTS)
            job_c = st.selectbox("Job Number", get_job_codes())
            task = st.text_area("Update Task")
            if st.form_submit_button("Post Log"):
                if task: conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_c}] @{slot_t}: {task}", "hours_spent": 1.0, "work_date": today}).execute(); st.rerun()

# --- TAB 2 & 3: LEAVE & BALANCE ---
with tabs[1]:
    st.subheader("New Leave Application")
    with st.form("leave_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        emp_name_l = col1.selectbox("Employee Name", get_staff_list())
        l_type = col2.selectbox("Type", ["Casual Leave", "Sick Leave", "Earned Leave", "Loss of Pay"])
        s_date, e_date = st.columns(2)
        start_d = s_date.date_input("Start", min_value=date.today())
        end_d = e_date.date_input("End", min_value=date.today())
        reason_l = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": emp_name_l, "leave_type": l_type, "start_date": str(start_d), "end_date": str(end_d), "reason": reason_l, "status": "Pending"}).execute()
            st.success("✅ Submitted."); st.cache_data.clear(); st.rerun()

with tabs[2]:
    st.subheader("Leave Balance & History")
    df_leaves = get_leave_requests()
    user_sel_bal = st.selectbox("View Records for:", get_staff_list())
    if not df_leaves.empty:
        user_df = df_leaves[df_leaves['employee_name'] == user_sel_bal].copy()
        for _, r in user_df.head(10).iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.write(f"**{r['leave_type']}** | {r['start_date']} to {r['end_date']}")
                c2.write(f"Status: {r['status']}")
                if r['status'] == "Pending" and c3.button("Withdraw", key=f"wd_{r['id']}"):
                    conn.table("leave_requests").delete().eq("id", r['id']).execute(); st.cache_data.clear(); st.rerun()

# --- TAB 4: HR ADMIN PANEL (CLEANED - ONLY 2 TABS) ---
with tabs[3]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        today_str = str(date.today())
        # Operational Analytics and Master Staff tabs are GONE.
        admin_tabs = st.tabs(["🕒 Detailed Logs", "📬 Leave Approvals"])

        # TAB 1: DETAILED LOGS (WITH STAFF FILTER)
        with admin_tabs[0]:
            st.subheader("📜 Filtered Activity Stream")
            search_name = st.selectbox("🔍 Filter Results by Staff Name", ["All Staff"] + get_staff_list())
            log_type = st.radio("Select Category", ["Work Logs", "Movement History", "Attendance Timeline"], horizontal=True)
            
            if log_type == "Work Logs":
                res = conn.table("work_logs").select("*").eq("work_date", today_str).order("created_at", desc=True).execute().data
                if res:
                    df = pd.DataFrame(res)
                    if search_name != "All Staff": df = df[df['employee_name'] == search_name]
                    df['Time Recorded'] = df['created_at'].apply(format_ts)
                    st.dataframe(df[['Time Recorded', 'employee_name', 'task_description', 'hours_spent']], use_container_width=True, hide_index=True)
            elif log_type == "Movement History":
                res = conn.table("movement_logs").select("*").gte("exit_time", f"{today_str}T00:00:00").execute().data
                if res:
                    df = pd.DataFrame(res)
                    if search_name != "All Staff": df = df[df['employee_name'] == search_name]
                    df['Out Time'] = df['exit_time'].apply(format_ts); df['Return Time'] = df['return_time'].apply(format_ts)
                    st.dataframe(df[['employee_name', 'destination', 'reason', 'Out Time', 'Return Time']], use_container_width=True, hide_index=True)
            elif log_type == "Attendance Timeline":
                res = conn.table("attendance_logs").select("*").eq("work_date", today_str).execute().data
                if res:
                    df = pd.DataFrame(res)
                    if search_name != "All Staff": df = df[df['employee_name'] == search_name]
                    df['Punch In'] = df['punch_in'].apply(format_ts); df['Punch Out'] = df['punch_out'].apply(format_ts)
                    st.dataframe(df[['employee_name', 'work_date', 'Punch In', 'Punch Out']], use_container_width=True, hide_index=True)

        # TAB 2: LEAVE APPROVALS
        with admin_tabs[1]:
            st.subheader("📬 Pending Leave Requests")
            df_all = get_leave_requests()
            if not df_all.empty:
                pending = df_all[df_all['status'] == 'Pending']
                for _, row in pending.iterrows():
                    with st.container(border=True):
                        c1, c2 = st.columns([4, 1])
                        c1.write(f"**{row['employee_name']}** | {row['leave_type']} ({row['start_date']} to {row['end_date']})")
                        if c2.button("✅ Approve", key=f"ap_{row['id']}"):
                            conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute(); st.rerun()
