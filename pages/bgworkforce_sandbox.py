import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz

# --- 1. SETUP & CONSTANTS ---
IST = pytz.timezone('Asia/Kolkata')
LATE_THRESHOLD = time(9, 15)
LOG_SLOTS = [f"{str(h).zfill(2)}:00" for h in range(24)]
LEAVE_QUOTA = {"Casual Leave": 12}

# --- DEFINE FREELANCER HERE ---
FREELANCER_NAME = "Freelancer" 

st.set_page_config(page_title="B&G HR | ERP System", layout="wide", page_icon="📅")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SMART UTILITIES ---
def convert_df(df):
    return df.to_csv(index=False).encode('utf-8')

def get_ampm_label(slot_str):
    h = int(slot_str.split(":")[0])
    return datetime.now().replace(hour=h, minute=0).strftime("%I:00 %p")

def get_now_ist():
    return datetime.now(IST)

# --- 3. DATA LOADERS ---
@st.cache_data(ttl=2) # Reduced TTL to ensure columns show up immediately
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
        return ["GENERAL", "ACCOUNTS", "PURCHASE", "PROD_PLAN","CLIENT_CALLS","ESTIMATIONS","QUOTATIONS","5S", "MAINTENANCE"] + sorted(list(set(jobs)))
    except: return ["GENERAL"]

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
tabs = st.tabs(["🕒 Attendance & Productivity", "📜 My Past Data", "📝 Leave Application", "📊 My Balance", "🔐 HR Admin Panel"])

# --- TAB 0: ATTENDANCE & WORK LOGS ---
with tabs[0]:
    st.subheader("🕒 Daily Time Office & Productivity Tracker")
    att_user = st.selectbox("Identify Yourself", get_staff_list(), key="att_user")
    
    if att_user == FREELANCER_NAME:
        f_key = st.text_input("Freelancer Access Key", type="password")
        if f_key != "abhi2026":
            st.warning("Please enter valid key.")
            st.stop()
            
    today = str(date.today())

    st.markdown("### 🏗️ My Work Plan & Pending Tasks")
    plan_col1, plan_col2 = st.columns([1.5, 2.5])
    with plan_col1:
        with st.form("quick_plan_form", clear_on_submit=True):
            p_job = st.selectbox("Job No", get_job_codes(), key="quick_p_job")
            p_task = st.text_input("Task/Pending Work")
            p_hrs = st.number_input("Est. Hours", min_value=0.5, max_value=12.0, value=1.0, step=0.5)
            if st.form_submit_button("📌 Add to Plan"):
                if p_task:
                    conn.table("work_plans").insert({"employee_name": att_user, "job_no": p_job, "planned_task": p_task, "planned_hours": p_hrs, "plan_date": today, "status": "Pending"}).execute()
                    st.cache_data.clear()
                    st.rerun()
    with plan_col2:
        my_plans = conn.table("work_plans").select("*").eq("employee_name", att_user).or_(f"plan_date.eq.{today},status.eq.Pending").execute().data
        if my_plans:
            for p in my_plans:
                t_col, b_col = st.columns([4, 1.2])
                if p['status'] == 'Pending':
                    t_col.info(f"📍 **[{p['job_no']}]** {p['planned_task']} — ({p['planned_hours']}h)")
                    if b_col.button("✅ Done", key=f"done_{p['id']}"):
                        conn.table("work_plans").update({"status": "Completed"}).eq("id", p['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
                else: t_col.success(f"✔️ ~~**[{p['job_no']}]** {p['planned_task']}~~")
        else: st.caption("No plans noted for today yet.")

    st.divider()
    emp_summ_res = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
    work_summ_res = conn.table("work_logs").select("*").eq("employee_name", att_user).eq("work_date", today).order("created_at").execute().data
    move_summ_res = conn.table("movement_logs").select("*").eq("employee_name", att_user).gte("exit_time", f"{today}T00:00:00").execute().data
    
    if emp_summ_res:
        log_data = emp_summ_res[0]
        start_t = pd.to_datetime(log_data['punch_in']).tz_convert(IST)
        end_t = pd.to_datetime(log_data['punch_out']).tz_convert(IST) if log_data.get('punch_out') else get_now_ist()
        dur = max(0.01, (end_t - start_t).total_seconds() / 3600)
        logged_hours = sum([float(w['hours_spent']) for w in work_summ_res]) if work_summ_res else 0.0
        c1, c2, c3 = st.columns(3)
        c1.metric("Punch In", start_t.strftime('%I:%M %p'))
        c2.metric("Shift Duration", f"{dur:.2f} hrs")
        c3.metric("Logged Work", f"{logged_hours:.2f} hrs", delta=f"{int((logged_hours/dur)*100)}% Eff.")
        
        st.write("#### 📑 Activity Summaries")
        sl, sr = st.columns(2)
        with sl:
            with st.expander(f"Today's Work Logs ({len(work_summ_res)})"):
                for w in work_summ_res: st.caption(f"✅ {w['task_description']} ({w['hours_spent']}h)")
        with sr:
            with st.expander(f"Today's Movements ({len(move_summ_res)})"):
                for m in move_summ_res:
                    out_t = pd.to_datetime(m['exit_time']).tz_convert(IST).strftime('%I:%M %p')
                    st.caption(f"🚶 {out_t} | {m['destination']}")

    st.divider()
    due_slot = is_log_due(att_user)
    if due_slot:
        st.warning(f"🔔 MANDATORY UPDATE: Past {get_ampm_label(due_slot)}")
        with st.form("mandatory_log_form"):
            slot_time = st.selectbox("Slot", LOG_SLOTS, index=LOG_SLOTS.index(due_slot), format_func=get_ampm_label)
            job_code = st.selectbox("Job No", get_job_codes())
            task_desc = st.text_area("Detail")
            cf1, cf2 = st.columns(2)
            if cf1.form_submit_button("✅ Submit"):
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_code}] @{slot_time}: {task_desc}", "hours_spent": 1.0, "work_date": today}).execute()
                st.cache_data.clear()
                st.rerun()
            if cf2.form_submit_button("🕒 Snooze (10 Mins)"):
                st.session_state['snooze_until'] = get_now_ist() + timedelta(minutes=10); st.rerun()
        st.stop()

    ca, cb, cc = st.columns([1.8, 1.4, 2.5]) # Adjusted widths for new fields
    with ca:
        st.markdown("### 🏢 Shift")
        if not emp_summ_res:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute()
                st.cache_data.clear()
                st.rerun()
        else:
            if not emp_summ_res[0].get('punch_out'):
                # --- NEW COMMITMENT & RATING COLUMNS ---
                with st.container(border=True):
                    st.markdown("**🛡️ System Commitment**")
                    sys_promise = st.checkbox("I am dedicated to B&G’s systems. Following the system today is my path to precision.", key="sys_promise")
                    
                    st.markdown("**🌟 Growth Rating**")
                    work_sat = st.feedback("stars", key="work_satisfaction_stars")
                    st.caption("I am working at my 100% potential. My growth fuels B&G’s growth.")
                    
                    if st.button("🏁 PUNCH OUT", use_container_width=True):
                        conn.table("attendance_logs").update({
                            "punch_out": get_now_ist().isoformat(),
                            "system_promise": sys_promise,
                            "work_satisfaction": work_sat
                        }).eq("id", emp_summ_res[0]['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
            else:
                st.success("Shift Completed")
                if emp_summ_res[0].get('work_satisfaction'):
                    st.write(f"My Potential Rating: {'⭐' * int(emp_summ_res[0]['work_satisfaction'])}")

    with cb:
        st.markdown("### 🚶 Movement")
        active_move = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        if not active_move:
            with st.form("move_form"):
                reason = st.selectbox("Category", ["Meeting", "Work Review", "Material", "Inspection", "Vendor Visit", "Lunch", "Personal"])
                dest = st.text_input("Destination")
                if st.form_submit_button("📤 TIME OUT") and dest:
                    conn.table("movement_logs").insert({"employee_name": att_user, "reason": reason, "destination": dest.upper(), "exit_time": get_now_ist().isoformat()}).execute()
                    st.cache_data.clear()
                    st.rerun()
        else:
            if st.button("📥 LOG TIME IN", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", active_move[0]['id']).execute()
                st.cache_data.clear()
                st.rerun()
    with cc:
        st.markdown("### 📝 Work log")
        with st.form("manual_work_log"):
            slot_t = st.selectbox("Slot", LOG_SLOTS, format_func=get_ampm_label)
            job_c = st.selectbox("Job", get_job_codes(), key="man_log_job")
            task = st.text_area("Update")
            if st.form_submit_button("Post Log") and task:
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_c}] @{slot_t}: {task}", "hours_spent": 1.0, "work_date": today}).execute()
                st.cache_data.clear()
                st.rerun()

# --- TAB 1: STAFF DATA HISTORY ---
with tabs[1]:
    st.subheader(f"📊 Personal History: {att_user}")
    h_col1, h_col2 = st.columns([1, 2])
    with h_col1:
        hist_type = st.radio("Select View", ["My Work Logs", "My Attendance History", "My Work Plans"], horizontal=True)
        hist_range = st.date_input("Select Date Range", [date.today() - timedelta(days=7), date.today()])
    if len(hist_range) == 2:
        start_d, end_d = hist_range
        table_name, date_col = ("work_logs", "work_date") if hist_type == "My Work Logs" else ("attendance_logs", "work_date") if hist_type == "My Attendance History" else ("work_plans", "plan_date")
        hist_res = conn.table(table_name).select("*").eq("employee_name", att_user).gte(date_col, str(start_d)).lte(date_col, str(end_d)).order(date_col, desc=True).execute().data
        if hist_res:
            df_hist = pd.DataFrame(hist_res)
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
            st.download_button(f"📥 Download {hist_type}", data=convert_df(df_hist), file_name=f"history.csv")

# --- TAB 2: LEAVE APPLICATION ---
with tabs[2]:
    st.subheader("New Leave Application")
    with st.form("leave_form"):
        l_emp = st.selectbox("Confirm Your Name", get_staff_list(), index=get_staff_list().index(att_user) if att_user in get_staff_list() else 0)
        sd, ed = st.date_input("Start"), st.date_input("End")
        reason_l = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": l_emp, "leave_type": "Casual Leave", "start_date": str(sd), "end_date": str(ed), "reason": reason_l, "status": "Pending"}).execute()
            st.cache_data.clear()
            st.success("Submitted"); st.rerun()

    st.divider()
    st.subheader("📜 Your Recent Requests & Status")
    df_l_all = get_leave_requests()
    if not df_l_all.empty:
        my_requests = df_l_all[df_l_all['employee_name'] == l_emp].copy()
        if not my_requests.empty:
            for _, r in my_requests.head(10).iterrows():
                with st.container(border=True):
                    col_a, col_b, col_c = st.columns([3, 2, 1])
                    col_a.write(f"📅 **{r['start_date']} to {r['end_date']}**")
                    col_a.caption(f"Reason: {r['reason']}")
                    s_color = "orange" if r['status'] == 'Pending' else "green" if r['status'] == 'Approved' else "red"
                    col_b.markdown(f"Status: **:{s_color}[{r['status']}]**")
                    if r.get('reject_reason'):
                        col_b.caption(f"Note: {r['reject_reason']}")
                    if r['status'] == 'Pending':
                        if col_c.button("Withdraw", key=f"wd_{r['id']}"):
                            conn.table("leave_requests").delete().eq("id", r['id']).execute()
                            st.cache_data.clear()
                            st.rerun()

# --- TAB 3: BALANCE ---
with tabs[3]:
    st.subheader("📊 Your Leave Balance")
    df_l = get_leave_requests()
    u_sel = st.selectbox("View Records for:", get_staff_list(), key="bal_u")
    if not df_l.empty:
        u_df = df_l[df_l['employee_name'] == u_sel].copy()
        app_df = u_df[u_df['status'] == 'Approved'].copy()
        used = ((pd.to_datetime(app_df['end_date']) - pd.to_datetime(app_df['start_date'])).dt.days + 1).sum() if not app_df.empty else 0
        st.metric("Casual Leave Balance", f"{int(12 - used)} Left", f"Used: {int(used)}")

# --- TAB 4: HR ADMIN PANEL ---
with tabs[4]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        st.markdown("### ⚙️ Admin Controls")
        ac1, ac2 = st.columns(2)
        s_name = ac1.selectbox("Filter Staff", ["All Staff"] + get_staff_list(), key="adm_filt")
        export_mode = ac2.selectbox("Range", ["Weekly", "Monthly", "Custom Date"])
        if export_mode == "Weekly": sr, er = date.today() - timedelta(days=7), date.today()
        elif export_mode == "Monthly": sr, er = date.today() - timedelta(days=30), date.today()
        else: sr, er = st.date_input("From"), st.date_input("To")
        
        admin_tabs = st.tabs(["📈 Analytics & Efficiency", "📜 Staff Leave Position", "🕒 Detailed Logs", "📬 Leave Approvals"])
        
        with admin_tabs[0]: # ANALYTICS
            st.subheader(f"🏢 Operational Data tracking ({sr} to {er})")
            t_att = conn.table("attendance_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
            t_work = conn.table("work_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
            if t_att:
                df_att = pd.DataFrame(t_att)
                df_work = pd.DataFrame(t_work) if t_work else pd.DataFrame(columns=['employee_name','hours_spent', 'task_description'])
                if s_name == "All Staff":
                    df_att = df_att[df_att['employee_name'] != FREELANCER_NAME]
                    df_work = df_work[df_work['employee_name'] != FREELANCER_NAME]
                else:
                    df_att = df_att[df_att['employee_name'] == s_name]
                    df_work = df_work[df_work['employee_name'] == s_name]

                st.markdown("#### ⌛ 1. Late Comers List")
                df_att['p_in_t'] = pd.to_datetime(df_att['punch_in']).dt.tz_convert(IST).dt.time
                late = df_att[df_att['p_in_t'] > LATE_THRESHOLD][['work_date', 'employee_name', 'p_in_t']]
                st.dataframe(late.sort_values('work_date', ascending=False), use_container_width=True, hide_index=True)

                st.markdown("#### 🚀 2. Workforce Efficiency Index")
                df_att['pi_dt'] = pd.to_datetime(df_att['punch_in']).dt.tz_convert(IST)
                df_att['po_dt'] = pd.to_datetime(df_att['punch_out']).dt.tz_convert(IST).fillna(get_now_ist())
                df_att['presence_hrs'] = (df_att['po_dt'] - df_att['pi_dt']).dt.total_seconds() / 3600
                att_sum = df_att.groupby('employee_name')['presence_hrs'].sum().reset_index()
                work_sum = df_work.groupby('employee_name')['hours_spent'].sum().reset_index()
                eff = pd.merge(att_sum, work_sum, on='employee_name', how='left').fillna(0)
                eff.columns = ['Employee', 'Total Presence (Hrs)', 'Total Work (Hrs)']
                eff['Eff %'] = (eff['Total Work (Hrs)'] / eff['Total Presence (Hrs)'] * 100).round(1)
                st.dataframe(eff.sort_values('Eff %', ascending=False), use_container_width=True, hide_index=True)
            else: st.info("No records found.")
