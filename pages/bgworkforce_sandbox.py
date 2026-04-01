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

# --- 4. RATING DIALOG LOGIC ---
@st.dialog("Shift Rating & Feedback")
def show_rating_dialog(log_id):
    st.write("Please rate your productivity and quality of work for this shift.")
    # Unique keys prevent the dialog from closing prematurely
    rating = st.feedback("stars", key="final_shift_stars")
    remarks = st.text_area("Final Work Summary / Accomplishments", key="final_shift_remarks")
    
    if st.button("Confirm Final Punch Out", type="primary"):
        conn.table("attendance_logs").update({
            "punch_out": get_now_ist().isoformat(),
            "rating": rating,
            "punch_out_remarks": remarks
        }).eq("id", log_id).execute()
        # Reset the trigger
        st.session_state.show_rating_screen = False
        st.success("Shift ended. Great work!")
        st.rerun()

# --- 5. NAVIGATION ---
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
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{job_code}] @{slot_time}: {task_desc}", "hours_spent": 1.0, "work_date": today}).execute(); st.rerun()
            if cf2.form_submit_button("🕒 Snooze (10 Mins)"):
                st.session_state['snooze_until'] = get_now_ist() + timedelta(minutes=10); st.rerun()
        st.stop()

    ca, cb, cc = st.columns([1.5, 1.5, 2.5])
    with ca:
        st.markdown("### 🏢 Shift Control")
        if not emp_summ_res:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute(); st.rerun()
        else:
            if not emp_summ_res[0].get('punch_out'):
                # LOGIC: Set a session state flag to show the dialog
                if st.button("🏁 PUNCH OUT", use_container_width=True):
                    st.session_state.show_rating_screen = True
                    st.rerun()
                
                # Check the flag to show dialog
                if st.session_state.get('show_rating_screen'):
                    show_rating_dialog(emp_summ_res[0]['id'])
            else:
                st.success("Shift Completed")
                r_val = emp_summ_res[0].get('rating')
                if r_val is not None:
                    st.markdown(f"**My Rating:** {'⭐' * int(r_val)}")
                if emp_summ_res[0].get('punch_out_remarks'):
                    st.caption(f"**Notes:** {emp_summ_res[0]['punch_out_remarks']}")

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

# --- TAB 1: HISTORY ---
with tabs[1]:
    st.subheader(f"📊 Personal History: {att_user}")
    h_col1, h_col2 = st.columns([1, 2])
    with h_col1:
        hist_type = st.radio("Select View", ["My Work Logs", "My Attendance History", "My Work Plans"], horizontal=True)
        hist_range = st.date_input("Select Date Range", [date.today() - timedelta(days=7), date.today()])
    if len(hist_range) == 2:
        sd_h, ed_h = hist_range
        table, col = ("work_logs", "work_date") if hist_type == "My Work Logs" else ("attendance_logs", "work_date") if hist_type == "My Attendance History" else ("work_plans", "plan_date")
        h_data = conn.table(table).select("*").eq("employee_name", att_user).gte(col, str(sd_h)).lte(col, str(ed_h)).order(col, desc=True).execute().data
        if h_data:
            df_h = pd.DataFrame(h_data)
            st.dataframe(df_h, use_container_width=True, hide_index=True)
            st.download_button(f"📥 Download {hist_type}", data=convert_df(df_h), file_name=f"history.csv")

# --- TAB 2: LEAVE ---
with tabs[2]:
    st.subheader("New Leave Application")
    with st.form("leave_form"):
        l_nm = st.selectbox("Confirm Name", get_staff_list(), index=get_staff_list().index(att_user) if att_user in get_staff_list() else 0)
        l_sd, l_ed = st.date_input("Start"), st.date_input("End")
        l_rs = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": l_nm, "leave_type": "Casual Leave", "start_date": str(l_sd), "end_date": str(l_ed), "reason": l_rs, "status": "Pending"}).execute()
            st.success("Submitted"); st.rerun()

# --- TAB 3: BALANCE ---
with tabs[3]:
    st.subheader("📊 Your Balance")
    df_l = get_leave_requests()
    if not df_l.empty:
        u_df = df_l[(df_l['employee_name'] == att_user) & (df_l['status'] == 'Approved')].copy()
        used = ((pd.to_datetime(u_df['end_date']) - pd.to_datetime(u_df['start_date'])).dt.days + 1).sum() if not u_df.empty else 0
        st.metric("Casual Leave Balance", f"{int(12 - used)} Left", f"Used: {int(used)}")

# --- TAB 4: HR ADMIN ---
with tabs[4]:
    if st.text_input("Admin Password", type="password") == "bgadmin":
        st.markdown("### ⚙️ Admin Controls")
        a_t1, a_t2 = st.tabs(["📈 Efficiency", "📬 Approvals"])
        with a_t1:
            t_a = conn.table("attendance_logs").select("*").execute().data
            t_w = conn.table("work_logs").select("*").execute().data
            if t_a and t_w:
                df_a, df_w = pd.DataFrame(t_a), pd.DataFrame(t_w)
                df_a['pi'] = pd.to_datetime(df_a['punch_in']).dt.tz_convert(IST)
                df_a['po'] = pd.to_datetime(df_a['punch_out']).dt.tz_convert(IST).fillna(get_now_ist())
                df_a['pres'] = (df_a['po'] - df_a['pi']).dt.total_seconds() / 3600
                eff = df_a.groupby('employee_name')['pres'].sum().reset_index()
                work = df_w.groupby('employee_name')['hours_spent'].sum().reset_index()
                merged = pd.merge(eff, work, on='employee_name', how='left').fillna(0)
                merged['Eff %'] = (merged['hours_spent'] / merged['pres'] * 100).round(1)
                st.dataframe(merged.sort_values('Eff %', ascending=False), use_container_width=True, hide_index=True)
        with a_t2:
            df_all = get_leave_requests()
            if not df_all.empty:
                pend = df_all[df_all['status'] == 'Pending']
                for _, r in pend.iterrows():
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 2])
                        c1.write(f"**{r['employee_name']}**")
                        c2.write(f"📅 {r['start_date']} to {r['end_date']}")
                        if c3.button("✅ Approve", key=f"adm_ap_{r['id']}"):
                            conn.table("leave_requests").update({"status": "Approved"}).eq("id", r['id']).execute(); st.rerun()
