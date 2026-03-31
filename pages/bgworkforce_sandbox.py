import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP & CONSTANTS ---
IST = pytz.timezone('Asia/Kolkata')
LATE_THRESHOLD = time(9, 15)
LOG_SLOTS = [f"{str(h).zfill(2)}:00" for h in range(24)]

LEAVE_QUOTA = {"Casual Leave": 12}

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

    # --- NEW: INDIVIDUAL WORK PLAN SECTION ---
    st.markdown("### 🏗️ My Work Plan & Pending Tasks")
    plan_col1, plan_col2 = st.columns([1.5, 2.5])
    
    with plan_col1:
        with st.form("quick_plan_form", clear_on_submit=True):
            p_job = st.selectbox("Job No", get_job_codes(), key="quick_p_job")
            p_task = st.text_input("Task/Pending Work", placeholder="What are you planning to finish?")
            p_hrs = st.number_input("Est. Hours", min_value=0.5, max_value=12.0, value=1.0, step=0.5)
            if st.form_submit_button("📌 Add to Plan"):
                if p_task:
                    conn.table("work_plans").insert({
                        "employee_name": att_user, "job_no": p_job, 
                        "planned_task": p_task, "planned_hours": p_hrs, 
                        "plan_date": today, "status": "Pending"
                    }).execute()
                    st.toast("Task added to your plan!")
                    st.rerun()

    with plan_col2:
        my_plans = conn.table("work_plans").select("*").eq("employee_name", att_user).eq("plan_date", today).execute().data
        if my_plans:
            st.write("**Today's Targets:**")
            for p in my_plans:
                st.info(f"📍 **[{p['job_no']}]** {p['planned_task']} — ({p['planned_hours']}h) [{p['status']}]")
        else:
            st.caption("No plans noted for today yet. Use the form on the left to plan your day.")

    st.divider()

    # --- EMPLOYEE TODAY SUMMARY ---
    st.markdown("### 📊 Your Today's status")
    emp_summ_res = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
    work_summ_res = conn.table("work_logs").select("*").eq("employee_name", att_user).eq("work_date", today).order("created_at").execute().data
    move_summ_res = conn.table("movement_logs").select("*").eq("employee_name", att_user).gte("exit_time", f"{today}T00:00:00").execute().data
    
    c_sum1, c_sum2, c_sum3 = st.columns(3)
    if emp_summ_res:
        log_data = emp_summ_res[0]
        start_t = pd.to_datetime(log_data['punch_in']).tz_convert(IST)
        end_t = pd.to_datetime(log_data['punch_out']).tz_convert(IST) if log_data.get('punch_out') else get_now_ist()
        dur = max(0.01, (end_t - start_t).total_seconds() / 3600)
        logged_hours = sum([float(w['hours_spent']) for w in work_summ_res]) if work_summ_res else 0.0
        c_sum1.metric("Punch In", start_t.strftime('%I:%M %p'))
        c_sum2.metric("Shift Duration", f"{dur:.2f} hrs")
        c_sum3.metric("Logged Work", f"{logged_hours:.2f} hrs", delta=f"{int((logged_hours/dur)*100)}% Eff.")
        
        st.write("#### 📝 Activity Summaries")
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

    # --- MANDATORY LOG LOGIC WITH SNOOZE ---
    due_slot = is_log_due(att_user)
    if due_slot:
        st.warning(f"🔔 **MANDATORY UPDATE:** It is past {get_ampm_label(due_slot)}. Please log activity.")
        with st.form("mandatory_log_form"):
            slot_time = st.selectbox("Slot", LOG_SLOTS, index=LOG_SLOTS.index(due_slot), format_func=get_ampm_label)
            job_code = st.selectbox("Job Number", get_job_codes())
            task_desc = st.text_area("Detail")
            c_f1, c_f2 = st.columns(2)
            if c_f1.form_submit_button("✅ Submit & Unlock"):
                if task_desc:
                    conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_code}] @{slot_time}: {task_desc}", "hours_spent": 1.0, "work_date": today}).execute()
                    st.rerun()
            if c_f2.form_submit_button("🕒 Snooze (10 Mins)"):
                st.session_state['snooze_until'] = get_now_ist() + timedelta(minutes=10)
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
                reason = st.selectbox("Category", ["Site Delivery", "Vendor Visit", "Lunch", "Personal"])
                dest = st.text_input("Destination")
                if st.form_submit_button("📤 TIME OUT") and dest:
                    conn.table("movement_logs").insert({"employee_name": att_user, "reason": reason, "destination": dest.upper(), "exit_time": get_now_ist().isoformat()}).execute(); st.rerun()
        else:
            st.warning(f"⚠️ At **{active_move[0]['destination']}**")
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

# --- TAB 2: LEAVE APPLICATION ---
with tabs[1]:
    st.subheader("New Leave Application")
    with st.form("leave_form"):
        col1, col2 = st.columns(2)
        emp_name_l = col1.selectbox("Employee Name", get_staff_list())
        l_type = col2.selectbox("Type", ["Casual Leave"])
        sd = st.date_input("Start", min_value=date.today())
        ed = st.date_input("End", min_value=date.today())
        reason_l = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": emp_name_l, "leave_type": l_type, "start_date": str(sd), "end_date": str(ed), "reason": reason_l, "status": "Pending"}).execute()
            st.success("✅ Submitted."); st.cache_data.clear(); st.rerun()

# --- TAB 3: MY BALANCE ---
with tabs[2]:
    st.subheader("📊 Your Leave Balance")
    df_leaves = get_leave_requests()
    user_sel_bal = st.selectbox("View Records for:", get_staff_list(), key="bal_user")
    if not df_leaves.empty:
        user_df = df_leaves[df_leaves['employee_name'] == user_sel_bal].copy()
        app_df = user_df[user_df['status'] == 'Approved'].copy()
        val = 0
        if not app_df.empty:
            app_df['s'] = pd.to_datetime(app_df['start_date'])
            app_df['e'] = pd.to_datetime(app_df['end_date'])
            val = ((app_df['e'] - app_df['s']).dt.days + 1).sum()
        
        st.metric("Casual Leave Balance", f"{int(12 - val)} Left", f"Used: {int(val)}")
        st.divider()
        for _, r in user_df.head(10).iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.write(f"📅 {r['start_date']} to {r['end_date']}")
                color = "orange" if r['status'] == 'Pending' else "green" if r['status'] == 'Approved' else "red"
                c2.markdown(f":{color}[{r['status']}]")
                if r['status'] == "Pending" and c3.button("Withdraw", key=f"wd_{r['id']}"):
                    conn.table("leave_requests").delete().eq("id", r['id']).execute(); st.cache_data.clear(); st.rerun()

# --- TAB 4: HR ADMIN PANEL ---
with tabs[3]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        today_str = str(date.today())
        st.markdown("### ⚙️ Admin & Export Controls")
        ac1, ac2 = st.columns(2)
        s_name = ac1.selectbox("Filter Staff", ["All Staff"] + get_staff_list(), key="adm_filt")
        export_mode = ac2.selectbox("Range", ["Weekly", "Monthly", "Custom Date"])
        
        if export_mode == "Weekly": sr, er = date.today() - timedelta(days=7), date.today()
        elif export_mode == "Monthly": sr, er = date.today() - timedelta(days=30), date.today()
        else:
            d_c1, d_c2 = st.columns(2)
            sr, er = d_c1.date_input("From", date.today()-timedelta(7)), d_c2.date_input("To", date.today())

        admin_tabs = st.tabs(["📈 Operations Analytics", "🕒 Detailed Logs", "📬 Leave Approvals"])
        
        with admin_tabs[0]:
            st.subheader("🏢 Operational Performance")
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
                col2.warning("📉 Low Work Logs (<4h)")
                if not work_sums.empty: col2.dataframe(work_sums[work_sums['hours_spent'] < 4.0], hide_index=True)
                col3.success("🚀 High Work Logs (>7.5h)")
                if not work_sums.empty: col3.dataframe(work_sums[work_sums['hours_spent'] > 7.5], hide_index=True)

        with admin_tabs[1]:
            st.subheader("📜 Activity Logs & CSV Export")
            l_type = st.radio("Category", ["Work Logs", "Movement History", "Attendance Timeline", "Work Plans"], horizontal=True)
            if st.button(f"📥 Download CSV for {s_name}"):
                tbl_map = {"Work Logs": "work_logs", "Movement History": "movement_logs", "Attendance Timeline": "attendance_logs", "Work Plans": "work_plans"}
                q = conn.table(tbl_map[l_type]).select("*")
                if s_name != "All Staff": q = q.eq("employee_name", s_name)
                # Export logic
                exp = q.execute().data
                if exp: st.download_button("Download", data=convert_df(pd.DataFrame(exp)), file_name=f"{l_type}.csv")

            res = conn.table("work_logs" if l_type=="Work Logs" else "movement_logs" if l_type=="Movement History" else "work_plans" if l_type=="Work Plans" else "attendance_logs").select("*").eq("work_date" if l_type!="Movement History" and l_type!="Work Plans" else "exit_time" if l_type=="Movement History" else "plan_date", today_str).execute().data
            if res:
                df_v = pd.DataFrame(res)
                if s_name != "All Staff": df_v = df_v[df_v['employee_name'] == s_name]
                st.dataframe(df_v, hide_index=True)

        with admin_tabs[2]:
            st.subheader("📬 Leave Approvals")
            df_all = get_leave_requests()
            if not df_all.empty:
                pend = df_all[df_all['status'] == 'Pending']
                for _, row in pend.iterrows():
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 2, 2])
                        c1.write(f"**{row['employee_name']}**")
                        if c3.button("✅ Approve", key=f"ap_{row['id']}"):
                            conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute(); st.rerun()
                        with c3.popover("❌ Reject"):
                            rn = st.text_input("Reason", key=f"rn_{row['id']}")
                            if st.button("Confirm", key=f"rb_{row['id']}"):
                                conn.table("leave_requests").update({"status": "Rejected", "reject_reason": rn}).eq("id", row['id']).execute(); st.rerun()
