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
                    st.rerun()
    with plan_col2:
        my_plans = conn.table("work_plans").select("*").eq("employee_name", att_user).or_(f"plan_date.eq.{today},status.eq.Pending").execute().data
        if my_plans:
            for p in my_plans:
                t_col, b_col = st.columns([4, 1.2])
                if p['status'] == 'Pending':
                    t_col.info(f"📍 **[{p['job_no']}]** {p['planned_task']} — ({p['planned_hours']}h)")
                    if b_col.button("✅ Done", key=f"done_{p['id']}"):
                        conn.table("work_plans").update({"status": "Completed"}).eq("id", p['id']).execute(); st.rerun()
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
        c3.metric("Logged Work", f"{logged_hours:.2f} hrs", delta=f"{int((logged_hours/dur)*100 if dur > 0 else 0)}% Eff.")

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
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_code}] @{slot_time}: {task_desc}", "hours_spent": 1.0, "work_date": today}).execute(); st.rerun()
            if cf2.form_submit_button("🕒 Snooze (10 Mins)"):
                st.session_state['snooze_until'] = get_now_ist() + timedelta(minutes=10); st.rerun()
        st.stop()

    ca, cb, cc = st.columns([1.8, 1.5, 2.5])
    with ca:
        st.markdown("### 🏢 Shift")
        if not emp_summ_res:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute(); st.rerun()
        else:
            if not emp_summ_res[0].get('punch_out'):
                with st.container(border=True):
                    st.markdown("**🛡️ System Commitment**")
                    sys_promise = st.checkbox("I am dedicated to B&G’s systems. Following the system today is my path to precision.", key="sys_promise")
                    st.markdown("**🌟 Productivity Self-Rating**")
                    work_sat = st.feedback("stars", key="productivity_stars")
                    st.caption("I am working at my 100% potential. My growth fuels B&G’s growth.")
                    if st.button("🏁 PUNCH OUT", use_container_width=True, type="primary"):
                        conn.table("attendance_logs").update({
                            "punch_out": get_now_ist().isoformat(),
                            "system_promise": sys_promise,
                            "work_satisfaction": work_sat
                        }).eq("id", emp_summ_res[0]['id']).execute()
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
                    conn.table("movement_logs").insert({"employee_name": att_user, "reason": reason, "destination": dest.upper(), "exit_time": get_now_ist().isoformat()}).execute(); st.rerun()
        else:
            if st.button("📥 LOG TIME IN", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", active_move[0]['id']).execute(); st.rerun()
    with cc:
        st.markdown("### 📝 Work log")
        with st.form("manual_work_log"):
            slot_t = st.selectbox("Slot", LOG_SLOTS, format_func=get_ampm_label)
            job_c = st.selectbox("Job", get_job_codes(), key="man_log_job")
            task = st.text_area("Update")
            if st.form_submit_button("Post Log") and task:
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_c}] @{slot_t}: {task}", "hours_spent": 1.0, "work_date": today}).execute(); st.rerun()

# --- TAB 1: STAFF DATA HISTORY (FIXED TO SHOW NEW COLUMNS) ---
with tabs[1]:
    st.subheader(f"📊 Personal History: {att_user}")
    h_col1, h_col2 = st.columns([1, 2])
    with h_col1:
        hist_type = st.radio("Select View", ["My Attendance History", "My Work Logs", "My Work Plans"], horizontal=True)
        hist_range = st.date_input("Select Date Range", [date.today() - timedelta(days=7), date.today()], key="personal_hist_range")
    if len(hist_range) == 2:
        start_d, end_d = hist_range
        table_name, date_col = ("attendance_logs", "work_date") if hist_type == "My Attendance History" else ("work_logs", "work_date") if hist_type == "My Work Logs" else ("work_plans", "plan_date")
        hist_res = conn.table(table_name).select("*").eq("employee_name", att_user).gte(date_col, str(start_d)).lte(date_col, str(end_d)).order(date_col, desc=True).execute().data
        if hist_res:
            df_hist = pd.DataFrame(hist_res)
            # Ensure new columns are included in view
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
            st.download_button(f"📥 Download {hist_type}", data=convert_df(df_hist), file_name=f"my_history.csv")

# --- TAB 2 & 3: LEAVE & BALANCE ---
with tabs[2]:
    st.subheader("New Leave Application")
    with st.form("leave_form"):
        l_emp = st.selectbox("Confirm Your Name", get_staff_list(), index=get_staff_list().index(att_user) if att_user in get_staff_list() else 0)
        ls, le = st.date_input("Start"), st.date_input("End")
        reason_l = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": l_emp, "leave_type": "Casual Leave", "start_date": str(ls), "end_date": str(le), "reason": reason_l, "status": "Pending"}).execute()
            st.success("Submitted"); st.rerun()

with tabs[3]:
    st.subheader("📊 Your Leave Balance")
    df_l = get_leave_requests()
    u_sel = st.selectbox("View Records for:", get_staff_list(), key="bal_u")
    if not df_l.empty:
        u_df = df_l[df_l['employee_name'] == u_sel].copy()
        app_df = u_df[u_df['status'] == 'Approved'].copy()
        used = ((pd.to_datetime(app_df['end_date']) - pd.to_datetime(app_df['start_date'])).dt.days + 1).sum() if not app_df.empty else 0
        st.metric("Casual Leave Balance", f"{int(12 - used)} Left", f"Used: {int(used)}")

# --- TAB 4: HR ADMIN PANEL (FIXED API ERROR & BLANK TABS) ---
with tabs[4]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        st.markdown("### ⚙️ Admin Controls")
        ac1, ac2 = st.columns(2)
        s_name = ac1.selectbox("Filter Staff", ["All Staff"] + get_staff_list(), key="adm_filt")
        export_range = ac2.selectbox("Range", ["Today", "Weekly", "Monthly"])
        
        if export_range == "Today": sr, er = date.today(), date.today()
        elif export_range == "Weekly": sr, er = date.today() - timedelta(days=7), date.today()
        else: sr, er = date.today() - timedelta(days=30), date.today()
        
        admin_tabs = st.tabs(["📈 Analytics & Efficiency", "📜 Staff Leave Position", "🕒 Detailed Logs", "📬 Leave Approvals"])
        
        with admin_tabs[0]: # ANALYTICS
            t_att_raw = conn.table("attendance_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute()
            t_work_raw = conn.table("work_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute()
            
            if t_att_raw.data:
                df_a = pd.DataFrame(t_att_raw.data)
                st.markdown("#### ⌛ Today's Late Comers")
                df_a['p_in_t'] = pd.to_datetime(df_a['punch_in']).dt.tz_convert(IST).dt.time
                late = df_a[(df_a['work_date'] == str(date.today())) & (df_a['p_in_t'] > LATE_THRESHOLD)]
                st.dataframe(late[['employee_name', 'p_in_t']], use_container_width=True, hide_index=True)
                
                st.markdown("#### 🚀 Work Log Efficiency")
                if t_work_raw.data:
                    df_w = pd.DataFrame(t_work_raw.data)
                    w_sum = df_w.groupby('employee_name')['hours_spent'].sum().reset_index().sort_values('hours_spent', ascending=False)
                    st.dataframe(w_sum, use_container_width=True, hide_index=True)

        with admin_tabs[1]: # LEAVE POSITION
            all_l_raw = conn.table("leave_requests").select("*").execute()
            if all_l_raw.data:
                df_all_l = pd.DataFrame(all_l_raw.data)
                app_l = df_all_l[df_all_l['status'] == 'Approved'].copy()
                if not app_l.empty:
                    app_l['days'] = (pd.to_datetime(app_l['end_date']) - pd.to_datetime(app_l['start_date'])).dt.days + 1
                    l_sum = app_l.groupby('employee_name')['days'].sum().reset_index()
                    l_sum['Balance'] = 12 - l_sum['days']
                    st.dataframe(l_sum, use_container_width=True, hide_index=True)

        with admin_tabs[2]: # DETAILED LOGS (FIXED API ERROR)
            l_type = st.radio("Select Log Type", ["Attendance", "Work Logs", "Movement"], horizontal=True)
            tbl_map = {"Attendance": "attendance_logs", "Work Logs": "work_logs", "Movement": "movement_logs"}
            
            # API FIX: standardized date filtering logic
            if l_type == "Movement":
                res_det = conn.table("movement_logs").select("*").gte("exit_time", str(sr)).execute()
            else:
                res_det = conn.table(tbl_map[l_type]).select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute()
            
            if res_det.data:
                df_det = pd.DataFrame(res_det.data)
                st.dataframe(df_det, use_container_width=True)
                st.download_button(f"📥 Export {l_type} CSV", convert_df(df_det), f"{l_type}_export.csv")

        with admin_tabs[3]: # LEAVE APPROVALS
            pend_raw = conn.table("leave_requests").select("*").eq("status", "Pending").execute()
            if pend_raw.data:
                for r in pend_raw.data:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        c1.write(f"**{r['employee_name']}**")
                        c2.write(f"📅 {r['start_date']} to {r['end_date']}\nReason: {r['reason']}")
                        if c3.button("✅ Appr", key=f"adm_ap_{r['id']}"):
                            conn.table("leave_requests").update({"status": "Approved"}).eq("id", r['id']).execute(); st.rerun()
