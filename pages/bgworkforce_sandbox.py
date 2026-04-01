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
    st.subheader("🕒 Daily Tracker")
    att_user = st.selectbox("Identify Yourself", get_staff_list(), key="att_user")
    
    if att_user == FREELANCER_NAME:
        f_key = st.text_input("Freelancer Access Key", type="password")
        if f_key != "abhi2026":
            st.warning("Please enter valid key."); st.stop()
            
    today = str(date.today())

    st.markdown("### 🏗️ My Work Plan")
    plan_col1, plan_col2 = st.columns([1.5, 2.5])
    with plan_col1:
        with st.form("quick_plan_form", clear_on_submit=True):
            p_job = st.selectbox("Job No", get_job_codes(), key="quick_p_job")
            p_task = st.text_input("Task/Pending Work")
            p_hrs = st.number_input("Est. Hours", min_value=0.5, value=1.0, step=0.5)
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
                    t_col.info(f"📍 **[{p['job_no']}]** {p['planned_task']}")
                    if b_col.button("✅ Done", key=f"done_{p['id']}"):
                        conn.table("work_plans").update({"status": "Completed"}).eq("id", p['id']).execute(); st.rerun()
                else: t_col.success(f"✔️ ~~{p['planned_task']}~~")

    st.divider()
    emp_summ_res = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
    work_summ_res = conn.table("work_logs").select("*").eq("employee_name", att_user).eq("work_date", today).order("created_at").execute().data
    
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
            if st.form_submit_button("✅ Submit"):
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_code}] @{slot_time}: {task_desc}", "hours_spent": 1.0, "work_date": today}).execute(); st.rerun()
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
                        st.cache_data.clear(); st.rerun()
            else: st.success("Shift Completed")

    with cb:
        st.markdown("### 🚶 Movement")
        active_move = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        if not active_move:
            with st.form("move_form"):
                reason = st.selectbox("Category", ["Meeting", "Inspection", "Material", "Lunch", "Personal"])
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
            job_c = st.selectbox("Job", get_job_codes())
            task = st.text_area("Update")
            if st.form_submit_button("Post Log") and task:
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_c}] @{slot_t}: {task}", "hours_spent": 1.0, "work_date": today}).execute(); st.rerun()

# --- TAB 1: HISTORY ---
with tabs[1]:
    st.subheader(f"📊 Personal History")
    h_type = st.radio("View", ["Attendance", "Work Logs", "Plans"], horizontal=True)
    h_range = st.date_input("Select Range", [date.today() - timedelta(days=7), date.today()], key="pers_h_range")
    if len(h_range) == 2:
        sd, ed = h_range
        table, d_col = ("attendance_logs", "work_date") if h_type == "Attendance" else ("work_logs", "work_date") if h_type == "Work Logs" else ("work_plans", "plan_date")
        h_res = conn.table(table).select("*").eq("employee_name", att_user).gte(d_col, str(sd)).lte(d_col, str(ed)).order(d_col, desc=True).execute().data
        if h_res:
            df_h = pd.DataFrame(h_res)
            st.dataframe(df_h, use_container_width=True, hide_index=True)
            st.download_button(f"📥 Download {h_type} CSV", data=convert_df(df_h), file_name=f"history.csv")

# --- TAB 2 & 3 ---
with tabs[2]:
    st.subheader("Leave Application")
    with st.form("leave_form"):
        l_nm = st.selectbox("Name", get_staff_list(), index=get_staff_list().index(att_user) if att_user in get_staff_list() else 0)
        l_s, l_e = st.date_input("Start"), st.date_input("End")
        l_r = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": l_nm, "start_date": str(l_s), "end_date": str(l_e), "reason": l_r, "status": "Pending"}).execute()
            st.success("Submitted"); st.rerun()

with tabs[3]:
    st.subheader("Balance")
    u_sel = st.selectbox("Check:", get_staff_list(), key="bal_u")
    ldf = get_leave_requests()
    if not ldf.empty:
        app = ldf[(ldf['employee_name'] == u_sel) & (ldf['status'] == 'Approved')].copy()
        used = ((pd.to_datetime(app['end_date']) - pd.to_datetime(app['start_date'])).dt.days + 1).sum() if not app.empty else 0
        st.metric("Casual Leave", f"{int(12 - used)} Left")

# --- TAB 4: HR ADMIN PANEL (REPAIRED) ---
with tabs[4]:
    if st.text_input("Admin Password", type="password") == "bgadmin":
        ac1, ac2 = st.columns(2)
        s_filt = ac1.selectbox("Filter Staff", ["All Staff"] + get_staff_list())
        r_filt = ac2.selectbox("Range", ["Today", "Weekly", "Monthly"])
        
        if r_filt == "Today": sr, er = date.today(), date.today()
        elif r_filt == "Weekly": sr, er = date.today() - timedelta(days=7), date.today()
        else: sr, er = date.today() - timedelta(days=30), date.today()
        
        adm_tabs = st.tabs(["📈 Analytics", "📜 Leave Position", "🕒 Master Logs", "📬 Leave Approvals"])
        
        with adm_tabs[0]: # Analytics
            res_a = conn.table("attendance_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
            if res_a:
                df_a = pd.DataFrame(res_a)
                st.markdown("#### ⌛ Late Comers (Today)")
                df_a['pi_t'] = pd.to_datetime(df_a['punch_in']).dt.tz_convert(IST).dt.time
                late = df_a[(df_a['work_date'] == str(date.today())) & (df_a['pi_t'] > LATE_THRESHOLD)]
                st.dataframe(late[['employee_name', 'pi_t']], use_container_width=True)

        with adm_tabs[2]: # Master Logs (Standardized Fix)
            cat = st.radio("Log Category", ["Attendance", "Work Logs", "Movement"], horizontal=True)
            tbl_n = "attendance_logs" if cat == "Attendance" else "work_logs" if cat == "Work Logs" else "movement_logs"
            # standardized date filtering column
            date_col_n = "work_date" if cat != "Movement" else "exit_time"
            res_logs = conn.table(tbl_n).select("*").gte(date_col_n, str(sr)).execute().data
            if res_logs:
                df_logs = pd.DataFrame(res_logs)
                st.dataframe(df_logs, use_container_width=True)
                st.download_button(f"📥 Export {cat} CSV", convert_df(df_logs), f"{cat}_export.csv")

        with adm_tabs[3]: # Leave Approvals (Restored)
            fresh_req = conn.table("leave_requests").select("*").eq("status", "Pending").execute().data
            if fresh_req:
                for req in fresh_req:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        c1.write(f"**{req['employee_name']}**")
                        c2.write(f"📅 {req['start_date']} to {req['end_date']}\n{req['reason']}")
                        if c3.button("✅ Approve", key=f"ap_{req['id']}"):
                            conn.table("leave_requests").update({"status": "Approved"}).eq("id", req['id']).execute()
                            st.cache_data.clear(); st.rerun()
            else: st.info("No pending requests.")
