import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP & CONSTANTS ---
IST = pytz.timezone('Asia/Kolkata')
LOG_SLOTS = ["10:00", "11:00", "12:00", "13:00", "14:30", "15:30", "16:30", "17:30"]
LATE_THRESHOLD = time(9, 15)

st.set_page_config(page_title="B&G HR | ERP System", layout="wide", page_icon="📅")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SMART UTILITIES ---
def to_ist(series):
    if series is None or (isinstance(series, pd.Series) and series.empty):
        return series
    dt = pd.to_datetime(series)
    if dt.dt.tz is None:
        dt = dt.dt.tz_localize('UTC')
    return dt.dt.tz_convert(IST)

def format_ts(ts):
    """Converts raw DB timestamp to B&G Standard: DD-MM-YYYY HH:MM AM/PM"""
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

    # --- NEW: EMPLOYEE TODAY SUMMARY ---
    st.markdown("### 📊 Your Today's Status")
    p_att = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
    p_work = conn.table("work_logs").select("hours_spent").eq("employee_name", att_user).eq("work_date", today).execute().data
    
    sc1, sc2, sc3 = st.columns(3)
    if p_att:
        p_in = pd.to_datetime(p_att[0]['punch_in']).tz_convert(IST)
        p_out = pd.to_datetime(p_att[0]['punch_out']).tz_convert(IST) if p_att[0].get('punch_out') else get_now_ist()
        actual_shift = (p_out - p_in).total_seconds() / 3600
        actual_logs = sum([float(w['hours_spent']) for w in p_work]) if p_work else 0.0
        
        sc1.metric("Punch In", p_in.strftime('%I:%M %p'))
        sc2.metric("Shift Duration", f"{actual_shift:.2f} hrs")
        sc3.metric("Logged Work", f"{actual_logs:.2f} hrs", delta=f"{int((actual_logs/actual_shift)*100) if actual_shift > 0.1 else 0}% Eff.")
    else:
        st.info("Punch record not found for today.")
    st.divider()

    due_slot = is_log_due(att_user)
    if due_slot:
        st.warning(f"🔔 **MANDATORY UPDATE:** It is past {due_slot}. Please log your activity to unlock the system.")
        with st.form("mandatory_log_form", clear_on_submit=True):
            slot_time = st.selectbox("Reporting for Slot", LOG_SLOTS, index=LOG_SLOTS.index(due_slot))
            job_code = st.selectbox("Job Number (Optional)", get_job_codes())
            task_desc = st.text_area(f"Work detail for {slot_time}")
            c1, c2 = st.columns(2)
            if c1.form_submit_button("✅ Submit & Unlock"):
                if task_desc:
                    conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_code}] @{slot_time}: {task_desc}", "hours_spent": 1.0, "work_date": today}).execute()
                    st.rerun()
                else: st.error("Details required.")
            if c2.form_submit_button("🕒 Snooze (10 Mins)"):
                st.session_state['snooze_until'] = get_now_ist() + timedelta(minutes=10)
                st.rerun()
        st.stop()

    col_a, col_b, col_c = st.columns([1.5, 1.5, 2.5])
    with col_a:
        st.markdown("### 🏢 Shift Punch")
        att_data = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
        if not att_data:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute(); st.rerun()
        else:
            log = att_data[0]
            p_in_time = to_ist(pd.Series([log['punch_in']])).dt.time.iloc[0]
            st.success(f"✅ In: {p_in_time.strftime('%I:%M %p')}")
            if not log.get('punch_out') and st.button("🏁 PUNCH OUT", use_container_width=True):
                conn.table("attendance_logs").update({"punch_out": get_now_ist().isoformat()}).eq("id", log['id']).execute(); st.rerun()

    with col_b:
        st.markdown("### 🚶 Movement")
        active_move = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        if not active_move:
            with st.form("move_form", clear_on_submit=True):
                reason = st.selectbox("Category", ["Inter-Unit Transfer", "Site Delivery", "Vendor Visit", "Lunch", "Personal"])
                detail = st.text_input("Detailed Purpose")
                dest = st.text_input("Destination")
                if st.form_submit_button("📤 TIME OUT"):
                    if dest and detail:
                        conn.table("movement_logs").insert({"employee_name": att_user, "reason": f"{reason}: {detail}", "destination": dest.upper(), "exit_time": get_now_ist().isoformat()}).execute(); st.rerun()
        else:
            m_log = active_move[0]
            st.warning(f"⚠️ At **{m_log['destination']}**")
            if st.button("📥 LOG TIME IN", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", m_log['id']).execute(); st.rerun()

    with col_c:
        st.markdown("### 📝 Work log")
        with st.form("manual_work_log", clear_on_submit=True):
            slot_t = st.selectbox("Time Slot", LOG_SLOTS)
            job_c = st.selectbox("Job Number (Optional)", get_job_codes(), key="manual_job")
            task = st.text_area("Update Task")
            if st.form_submit_button("Post Log"):
                if task:
                    conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_c}] @{slot_t}: {task}", "hours_spent": 1.0, "work_date": today}).execute(); st.rerun()

# --- TAB 2: LEAVE APPLICATION ---
with tabs[1]:
    st.subheader("New Leave Application")
    with st.form("leave_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        emp_name_l = col1.selectbox("Employee Name", get_staff_list(), key="l_emp")
        l_type = col2.selectbox("Type", ["Casual Leave", "Sick Leave", "Earned Leave", "Loss of Pay"])
        d1, d2 = st.columns(2)
        s_date = d1.date_input("Start", min_value=date.today())
        e_date = d2.date_input("End", min_value=date.today())
        reason_l = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": emp_name_l, "leave_type": l_type, "start_date": str(s_date), "end_date": str(e_date), "reason": reason_l, "status": "Pending"}).execute()
            st.success("✅ Submitted."); st.cache_data.clear(); st.rerun()

# --- TAB 3: MY BALANCE ---
with tabs[2]:
    st.subheader("Leave Balance & History")
    df_leaves = get_leave_requests()
    user_sel_bal = st.selectbox("View Records for:", get_staff_list(), key="bal_user")
    if not df_leaves.empty:
        user_df = df_leaves[df_leaves['employee_name'] == user_sel_bal].copy()
        for _, r in user_df.head(10).iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                c1.write(f"**{r['leave_type']}**")
                c2.write(f"{r['start_date']} to {r['end_date']}")
                color = "orange" if r['status'] == 'Pending' else "green" if r['status'] == 'Approved' else "red"
                c3.markdown(f":{color}[{r['status']}]")
                if r['status'] == "Pending" and c4.button("Withdraw", key=f"wd_{r['id']}"):
                    conn.table("leave_requests").delete().eq("id", r['id']).execute(); st.cache_data.clear(); st.rerun()
                if r.get('reject_reason'): st.caption(f"Reason: {r['reject_reason']}")

# --- TAB 4: HR ADMIN PANEL ---
with tabs[3]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        today_str = str(date.today())
        admin_tabs = st.tabs(["📈 Operations Analytics", "🕒 Detailed Logs", "📬 Leave Approvals"])

        # --- ADMIN SUB-TAB 1: ANALYTICS (RE-DESIGNED) ---
        with admin_tabs[0]:
            st.subheader("🏢 Operational Performance Tracking")
            t_att = conn.table("attendance_logs").select("*").eq("work_date", today_str).execute().data
            t_work = conn.table("work_logs").select("*").eq("work_date", today_str).execute().data
            
            if t_att:
                df_att = pd.DataFrame(t_att)
                df_work = pd.DataFrame(t_work) if t_work else pd.DataFrame(columns=['employee_name', 'hours_spent'])
                
                # 1. Late Comers (> 9:15 AM)
                df_att['p_in_dt'] = pd.to_datetime(df_att['punch_in']).dt.tz_convert(IST)
                late_df = df_att[df_att['p_in_dt'].dt.time > LATE_THRESHOLD]
                
                # 2. Log Performance
                log_sum = df_work.groupby('employee_name')['hours_spent'].sum().reset_index() if not df_work.empty else pd.DataFrame(columns=['employee_name', 'hours_spent'])
                low_logs = log_sum[log_sum['hours_spent'] < 4.0]
                high_logs = log_sum[log_sum['hours_spent'] > 7.5]

                ac1, ac2, ac3 = st.columns(3)
                ac1.error(f"⌛ Late Comers ({len(late_df)})")
                if not late_df.empty: ac1.dataframe(late_df[['employee_name', 'p_in_dt']].assign(Time=late_df['p_in_dt'].dt.strftime('%I:%M %p'))[['employee_name', 'Time']], hide_index=True)
                
                ac2.warning(f"📉 Low Work Logs (<4h)")
                if not low_logs.empty: ac2.dataframe(low_logs, hide_index=True)
                
                ac3.success(f"🚀 High Work Logs (>7.5h)")
                if not high_logs.empty: ac3.dataframe(high_logs, hide_index=True)

            st.divider()
            st.markdown("##### 🏢 Today's Performance Snapshot")
            if t_att:
                tdf = pd.DataFrame(t_att)
                def get_summary_logic(row):
                    start = pd.to_datetime(row['punch_in']).tz_convert(IST)
                    end = (pd.to_datetime(row['punch_out']).tz_convert(IST) if pd.notnull(row['punch_out']) else get_now_ist())
                    # Precise shift duration subtraction
                    shift = (end - start).total_seconds() / 3600
                    task_h = pd.DataFrame(t_work)[pd.DataFrame(t_work)['employee_name'] == row['employee_name']]['hours_spent'].sum() if t_work else 0
                    eff = int(min(100, (task_h/shift)*100)) if shift > 0.1 else 0
                    return f"{shift:.2f}h", f"{task_h:.2f}h", f"{eff}%"

                tdf[['Shift Dur.', 'Logged Hrs', 'Efficiency']] = tdf.apply(get_summary_logic, axis=1, result_type='expand')
                st.dataframe(tdf[['employee_name', 'Shift Dur.', 'Logged Hrs', 'Efficiency']], use_container_width=True, hide_index=True)

        # --- ADMIN SUB-TAB 2: DETAILED LOGS (WITH NAME FILTER) ---
        with admin_tabs[1]:
            st.subheader("📜 Complete Activity Stream")
            search_name = st.selectbox("🔍 Filter Results by Staff Name", ["All Staff"] + get_staff_list(), key="admin_name_filter")
            log_type = st.radio("Select Category", ["Work Logs", "Movement History", "Attendance Timeline"], horizontal=True)
            
            if log_type == "Work Logs":
                res = conn.table("work_logs").select("*").eq("work_date", today_str).order("created_at", desc=True).execute().data
                if res:
                    df_w = pd.DataFrame(res)
                    if search_name != "All Staff": df_w = df_w[df_w['employee_name'] == search_name]
                    df_w['Time Recorded'] = df_w['created_at'].apply(format_ts)
                    st.dataframe(df_w[['Time Recorded', 'employee_name', 'task_description', 'hours_spent']], use_container_width=True, hide_index=True)
            
            elif log_type == "Movement History":
                res = conn.table("movement_logs").select("*").gte("exit_time", f"{today_str}T00:00:00").execute().data
                if res:
                    df_m = pd.DataFrame(res)
                    if search_name != "All Staff": df_m = df_m[df_m['employee_name'] == search_name]
                    df_m['Out Time'] = df_m['exit_time'].apply(format_ts)
                    df_m['Return Time'] = df_m['return_time'].apply(format_ts)
                    st.dataframe(df_m[['employee_name', 'destination', 'reason', 'Out Time', 'Return Time']], use_container_width=True, hide_index=True)
            
            elif log_type == "Attendance Timeline":
                res = conn.table("attendance_logs").select("*").eq("work_date", today_str).execute().data
                if res:
                    df_a = pd.DataFrame(res)
                    if search_name != "All Staff": df_a = df_a[df_a['employee_name'] == search_name]
                    df_a['Punch In'] = df_a['punch_in'].apply(format_ts)
                    df_a['Punch Out'] = df_a['punch_out'].apply(format_ts)
                    st.dataframe(df_a[['employee_name', 'work_date', 'Punch In', 'Punch Out']], use_container_width=True, hide_index=True)

        # --- ADMIN SUB-TAB 3: LEAVE APPROVALS ---
        with admin_tabs[2]:
            st.subheader("📬 Pending Leave Requests")
            df_all = get_leave_requests()
            if not df_all.empty:
                pending = df_all[df_all['status'] == 'Pending']
                if pending.empty:
                    st.success("No pending leave requests!")
                else:
                    for _, row in pending.iterrows():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([2, 2, 2])
                            c1.write(f"**{row['employee_name']}** | {row['leave_type']}")
                            c1.caption(f"Dates: {row['start_date']} to {row['end_date']}")
                            c2.write(f"**Reason:** {row['reason']}")
                            if c3.button("✅ Approve", key=f"ap_{row['id']}"):
                                conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute()
                                st.rerun()
                            with c3.popover("❌ Reject"):
                                rej_reason = st.text_input("Reason", key=f"rej_text_{row['id']}")
                                if st.button("Confirm Reject", key=f"rej_btn_{row['id']}"):
                                    conn.table("leave_requests").update({"status": "Rejected", "reject_reason": rej_reason}).eq("id", row['id']).execute()
                                    st.rerun()
