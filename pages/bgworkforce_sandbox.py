import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz

# --- 1. SETUP & CONSTANTS ---
IST = pytz.timezone('Asia/Kolkata')
LATE_THRESHOLD = time(9, 01) # B&G Standard
LOG_SLOTS = [f"{str(h).zfill(2)}:00" for h in range(24)]
LEAVE_QUOTA = {"Casual Leave": 12}

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
    selected_user = st.selectbox("Identify Yourself", get_staff_list(), key="user_select_main")
    
    if "authenticated_user" not in st.session_state:
        st.session_state["authenticated_user"] = None

    if st.session_state["authenticated_user"] != selected_user:
        st.info(f"🔐 Please verify access for {selected_user}")
        input_pw = st.text_input("Enter your Access Key", type="password", key=f"pw_gate_{selected_user}")
        if st.button("Unlock My Dashboard", use_container_width=True):
            auth_res = conn.table("employee_auth").select("access_key").eq("employee_name", selected_user).execute().data
            if auth_res and input_pw == auth_res[0]['access_key']:
                st.session_state["authenticated_user"] = selected_user
                if selected_user == "Admin": st.session_state["admin_authenticated"] = True
                st.success("Access Granted!"); st.rerun()
            else: st.error("Invalid Access Key.")
        st.stop()

    att_user = st.session_state["authenticated_user"]
    today = str(date.today())
    
    if st.button("🔓 Logout / Switch User"):
        st.session_state["authenticated_user"] = None
        st.session_state["admin_authenticated"] = False
        st.rerun()

    st.divider()

    # --- FOUNDER'S DESK ---
    st.markdown("### 📢 Founder's Desk")
    if att_user == "Admin":
        with st.expander("✉️ Post New Instruction", expanded=False):
            with st.form("founder_msg_form", clear_on_submit=True):
                m_target = st.selectbox("Target Employee", ["All"] + get_staff_list())
                m_text = st.text_area("Instruction Content")
                if st.form_submit_button("🚀 Broadcast"):
                    if m_text:
                        if m_target == "All":
                            targets = [s for s in get_staff_list() if s != "Admin"]
                            payload = [{"sender_name": "Founder", "content": m_text, "target_user": s, "is_read": False} for s in targets]
                            conn.table("founder_interaction").insert(payload).execute()
                        else:
                            conn.table("founder_interaction").insert({"sender_name": "Founder", "content": m_text, "target_user": m_target, "is_read": False}).execute()
                        st.success("Sent!"); st.rerun()

        st.markdown(f"**📥 Today's Messages ({today})**")
        st.markdown('<div style="height:250px; overflow-y:auto; border:1px solid #e6e9ef; border-radius:10px; padding:15px; background-color:#ffffff;">', unsafe_allow_html=True)
        today_msgs = conn.table("founder_interaction").select("*").gte("created_at", f"{today}T00:00:00").order("created_at", desc=True).execute().data
        if today_msgs:
            for r in today_msgs:
                st.caption(f"**{r['sender_name']}** to {r['target_user']} | {r['created_at'][11:16]}")
                st.write(r['content'])
                if r.get('reply_content'): st.info(f"Reply: {r['reply_content']}")
                st.divider()
        else: st.write("No interactions yet today.")
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        msg_res = conn.table("founder_interaction").select("*").or_(f"target_user.eq.{att_user},sender_name.eq.{att_user}").order("created_at", desc=True).limit(1).execute().data
        if msg_res:
            m = msg_res[0]
            with st.container(border=True):
                st.info(f"**Founder Instruction:** {m['content']}")
                if not m.get('is_read'):
                    c_rep, c_btn = st.columns([3, 1])
                    rep = c_rep.text_input("Reply...", key=f"rep_{m['id']}")
                    if c_btn.button("✔️ Send", key=f"btn_{m['id']}"):
                        conn.table("founder_interaction").update({"is_read": True, "reply_content": rep or "Acknowledged"}).eq("id", m['id']).execute(); st.rerun()

    st.divider()

    # --- MY WORK PLAN ---
    st.markdown("### 🏗️ My Work Plan & Pending Tasks")
    p1, p2 = st.columns([1.5, 2.5])
    with p1:
        with st.form("plan_form", clear_on_submit=True):
            p_job = st.selectbox("Job No", get_job_codes())
            p_task = st.text_input("Task Description")
            p_hrs = st.number_input("Est. Hrs", 0.5, 12.0, 1.0, 0.5)
            if st.form_submit_button("📌 Add"):
                conn.table("work_plans").insert({"employee_name": att_user, "job_no": p_job, "planned_task": p_task, "planned_hours": p_hrs, "plan_date": today, "status": "Pending"}).execute(); st.rerun()
    with p2:
        my_plans = conn.table("work_plans").select("*").eq("employee_name", att_user).or_(f"plan_date.eq.{today},status.eq.Pending").execute().data
        if my_plans:
            for p in my_plans:
                tc, bc = st.columns([4, 1.2])
                if p['status'] == 'Pending':
                    tc.info(f"📍 **[{p['job_no']}]** {p['planned_task']} ({p['planned_hours']}h)")
                    if bc.button("✅ Done", key=f"p_done_{p['id']}"):
                        conn.table("work_plans").update({"status": "Completed"}).eq("id", p['id']).execute(); st.rerun()
                else: tc.success(f"✔️ ~~**[{p['job_no']}]** {p['planned_task']}~~")

    st.divider()

    # --- CORE DATA FETCH ---
    emp_summ_res = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
    log_data = emp_summ_res[0] if emp_summ_res else {}

    # --- SNOOZE LOGIC (Local Flag to prevent Blank Tabs) ---
    due_slot = is_log_due(att_user)
    now_ist = get_now_ist()
    is_snoozed = "snooze_until" in st.session_state and now_ist < st.session_state["snooze_until"]
    
    show_tab0_content = True

    if due_slot and not is_snoozed:
        st.warning(f"🔔 MANDATORY UPDATE: Past {get_ampm_label(due_slot)}")
        with st.form("mandatory_form"):
            m_job = st.selectbox("Job No", get_job_codes(), key="m_j_s")
            m_task = st.text_area("Last hour update?")
            cf1, cf2 = st.columns(2)
            if cf1.form_submit_button("✅ Post Log"):
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{m_job}] {m_task}", "hours_spent": 1.0, "work_date": today}).execute()
                st.session_state.pop('snooze_until', None)
                st.rerun()
            if cf2.form_submit_button("🕒 Snooze (10m)"):
                st.session_state['snooze_until'] = now_ist + timedelta(minutes=10)
                st.rerun()
        show_tab0_content = False
    
    if show_tab0_content:
        # --- COMMITMENT BANNER ---
        if log_data and not log_data.get('punch_out'):
            if "promise_confirmed" not in st.session_state:
                st.session_state["promise_confirmed"] = log_data.get('system_promise', False)

            if not st.session_state["promise_confirmed"]:
                with st.container(border=True):
                    st.markdown('<div style="background-color:#f8f9fb; padding:10px; border-left: 5px solid #007bff;">'
                                '<b>"I am dedicated to B&G’s systems. Following the system today is my path to precision."</b></div>', unsafe_allow_html=True)
                    if st.checkbox("🛡️ I acknowledge and commit...", key="temp_promise_check"):
                        st.session_state["promise_confirmed"] = True
                        st.rerun()
            else: st.success("🙏 System Commitment Acknowledged.")

        # --- SHIFT CONTROLS ---
        ca, cb, cc = st.columns([1.8, 1.5, 2.5])
        with ca:
            st.markdown("### 🏢 Shift")
            if not emp_summ_res:
                if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                    conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today, "punch_in": get_now_ist().isoformat()}).execute(); st.rerun()
            else:
                if not log_data.get('punch_out'):
                    st.markdown("**Productivity Rating**")
                    work_sat = st.feedback("stars", key="prod_stars_fb") 
                    if st.button("🏁 PUNCH OUT", use_container_width=True, type="primary"):
                        conn.table("attendance_logs").update({
                            "punch_out": get_now_ist().isoformat(), 
                            "work_satisfaction": work_sat,
                            "system_promise": st.session_state.get("promise_confirmed", False)
                        }).eq("id", log_data['id']).execute(); st.cache_data.clear(); st.rerun()
                else: st.success("Shift Completed")
        
        with cb:
            st.markdown("### 🚶 Move")
            move_res = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
            if not move_res:
                with st.form("m_form"):
                    d = st.text_input("Destination")
                    if st.form_submit_button("📤 OUT") and d:
                        conn.table("movement_logs").insert({"employee_name": att_user, "destination": d.upper(), "exit_time": get_now_ist().isoformat()}).execute(); st.rerun()
            else:
                if st.button("📥 IN", type="primary"):
                    conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", move_res[0]['id']).execute(); st.rerun()
        
        with cc:
            st.markdown("### 📝 Log")
            with st.form("w_form"):
                j = st.selectbox("Job", get_job_codes(), key="log_j")
                t = st.text_area("Task Update")
                if st.form_submit_button("Post Work Log"):
                    conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{j}] {t}", "hours_spent": 1.0, "work_date": today}).execute(); st.rerun()

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
        sd, ed = st.date_input("Start date"), st.date_input("End date")
        reason_l = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": l_emp, "leave_type": "Casual Leave", "start_date": str(sd), "end_date": str(ed), "reason": reason_l, "status": "Pending"}).execute()
            st.success("Submitted"); st.rerun()

    st.divider()
    st.subheader("📜 Recent Requests")
    df_l_all = get_leave_requests()
    if not df_l_all.empty:
        my_req = df_l_all[df_l_all['employee_name'] == l_emp].head(10)
        for _, r in my_req.iterrows():
            with st.container(border=True):
                st.write(f"📅 **{r['start_date']} to {r['end_date']}** | Status: {r['status']}")
                if r['status'] == 'Pending':
                    if st.button("Withdraw", key=f"wd_{r['id']}"):
                        conn.table("leave_requests").delete().eq("id", r['id']).execute(); st.rerun()

# --- TAB 3: BALANCE ---
with tabs[3]:
    st.subheader("📊 Your Leave Balance")
    u_sel = st.selectbox("Check Balance for:", get_staff_list(), key="bal_u")
    df_l = get_leave_requests()
    if not df_l.empty:
        app_df = df_l[(df_l['employee_name'] == u_sel) & (df_l['status'] == 'Approved')]
        used = ((pd.to_datetime(app_df['end_date']) - pd.to_datetime(app_df['start_date'])).dt.days + 1).sum() if not app_df.empty else 0
        st.metric("Casual Leave Balance", f"{int(12 - used)} Left", f"Used: {int(used)}")

# --- TAB 4: HR ADMIN PANEL (Analytics & Keys) ---
with tabs[4]:
    admin_pass = st.text_input("Admin Password", type="password", key="hr_final_pw")
    if admin_pass == "bgadmin":
        hr_tabs = st.tabs(["📈 Analytics & Grading", "📊 Raw Logs", "📬 Approvals", "🔐 Access Keys"])
        
        with hr_tabs[0]:
            st.subheader("Employee Performance Dashboard")
            c1, c2 = st.columns(2)
            target_emp = c1.selectbox("Select Staff", get_staff_list(), key="hr_sel")
            report_period = c2.selectbox("Period", ["Last 7 Days", "This Month", "Year to Date"])
            
            er = date.today()
            sr = er - timedelta(days=7) if report_period == "Last 7 Days" else er.replace(day=1) if report_period == "This Month" else er.replace(month=1, day=1)
            
            if st.button("Generate Performance Report"):
                att_res = conn.table("attendance_logs").select("*").eq("employee_name", target_emp).gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
                plan_res = conn.table("work_plans").select("*").eq("employee_name", target_emp).gte("plan_date", str(sr)).lte("plan_date", str(er)).execute().data
                
                if att_res:
                    df_att = pd.DataFrame(att_res)
                    total_days = len(df_att)
                    df_att['p_in_t'] = pd.to_datetime(df_att['punch_in']).dt.tz_convert(IST).dt.time
                    late_days = len(df_att[df_att['p_in_t'] > LATE_THRESHOLD])
                    
                    df_plan = pd.DataFrame(plan_res) if plan_res else pd.DataFrame()
                    comp_tasks = len(df_plan[df_plan['status'] == 'Completed']) if not df_plan.empty else 0
                    total_tasks = len(df_plan) if not df_plan.empty else 0
                    efficiency = (comp_tasks / total_tasks * 100) if total_tasks > 0 else 0
                    avg_rating = df_att['work_satisfaction'].mean() if 'work_satisfaction' in df_att.columns else 0

                    if efficiency >= 90 and late_days == 0: grade, color = "A+", "#28a745"
                    elif efficiency >= 75: grade, color = "B", "#ffc107"
                    else: grade, color = "C", "#dc3545"

                    st.markdown(f'<div style="background-color:{color}; padding:20px; border-radius:15px; text-align:center; color:white;"><h1>{grade}</h1></div>', unsafe_allow_html=True)
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Punctuality", f"{total_days-late_days}/{total_days} Days")
                    m2.metric("Efficiency", f"{efficiency:.0f}%")
                    m3.metric("Avg Stars", f"{avg_rating:.1f} ⭐")

        with hr_tabs[1]:
            st.subheader("💾 System Audit Export")
            raw_int = conn.table("founder_interaction").select("*").execute().data
            if raw_int: st.download_button("📥 Export Communication CSV", data=convert_df(pd.DataFrame(raw_int)), file_name="audit.csv")

        with hr_tabs[2]: # Leave Approvals
            pend = get_leave_requests()
            if not pend.empty:
                to_app = pend[pend['status'] == 'Pending']
                for _, r in to_app.iterrows():
                    with st.container(border=True):
                        st.write(f"**{r['employee_name']}**: {r['start_date']} to {r['end_date']}")
                        if st.button("Approve", key=f"appr_{r['id']}"):
                            conn.table("leave_requests").update({"status": "Approved"}).eq("id", r['id']).execute(); st.rerun()

        with hr_tabs[3]: # Access Key Management
            st.subheader("Set Access Keys")
            with st.form("key_update"):
                t_e = st.selectbox("Staff", get_staff_list())
                n_k = st.text_input("New Key", type="password")
                if st.form_submit_button("Update"):
                    conn.table("employee_auth").upsert({"employee_name": t_e, "access_key": n_k}).execute(); st.success("Updated")
