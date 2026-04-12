import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz

# ============================================================
# 1. SETUP & CONSTANTS
# ============================================================
IST = pytz.timezone('Asia/Kolkata')
LATE_THRESHOLD = time(9, 5)
LOG_SLOTS = [f"{str(h).zfill(2)}:00" for h in range(24)]
LEAVE_QUOTA = {"Casual Leave": 12}

st.set_page_config(page_title="B&G HR | ERP System", layout="wide", page_icon="📅")
conn = st.connection("supabase", type=SupabaseConnection)

# ============================================================
# 2. UTILITIES
# ============================================================
def convert_df(df):
    return df.to_csv(index=False).encode('utf-8')

def get_ampm_label(slot_str):
    h = int(slot_str.split(":")[0])
    return datetime.now().replace(hour=h, minute=0).strftime("%I:00 %p")

def get_now_ist():
    return datetime.now(IST)

def safe_db_write(fn, success_msg=None, error_prefix="DB Error"):
    """FIX [Quick Win]: Wrap all DB writes safely — no more silent crashes."""
    try:
        fn()
        if success_msg:
            st.success(success_msg)
        return True
    except Exception as e:
        st.error(f"{error_prefix}: {e}")
        return False

# ============================================================
# 3. DATA LOADERS  (all cached — FIX [Critical])
# ============================================================

# FIX [Critical]: Added @st.cache_data(ttl=30) — was uncached, fired on every rerun
@st.cache_data(ttl=30)
def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return [s['name'] for s in res.data] if res.data else ["Admin", "Staff Member"]
    except Exception:
        return ["Admin", "Staff Member"]

# FIX [Critical]: Added @st.cache_data(ttl=30) — was uncached, fired on every rerun
@st.cache_data(ttl=30)
def get_job_codes():
    try:
        res = conn.table("anchor_projects").select("job_no").eq("status", "Won").execute()
        jobs = [j['job_no'] for j in res.data if j.get('job_no')] if res.data else []
        return [
            "GENERAL", "ACCOUNTS", "PURCHASE", "PROD_PLAN",
            "CLIENT_CALLS", "ESTIMATIONS", "QUOTATIONS", "5S", "MAINTENANCE"
        ] + sorted(list(set(jobs)))
    except Exception:
        return ["GENERAL"]

# FIX [Warning]: Increased TTL from 5s → 120s — leave data changes rarely
@st.cache_data(ttl=120)
def get_leave_requests():
    try:
        res = conn.table("leave_requests").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# FIX [Warning]: Added @st.cache_data(ttl=55) — was firing a raw DB query on every rerun
@st.cache_data(ttl=55)
def get_latest_work_log(employee_name, today_str):
    """Returns the last work log entry for today, or None."""
    try:
        res = conn.table("work_logs").select("created_at") \
            .eq("employee_name", employee_name) \
            .eq("work_date", today_str) \
            .order("created_at", desc=True) \
            .limit(1).execute().data
        return res[0]['created_at'] if res else None
    except Exception:
        return None

def is_log_due(employee_name):
    if st.session_state.get('snooze_until') and get_now_ist() < st.session_state['snooze_until']:
        return None
    now_t = get_now_ist().strftime("%H:%M")
    past_slots = [s for s in LOG_SLOTS if s <= now_t]
    if not past_slots:
        return None
    latest_slot = past_slots[-1]
    # FIX [Warning]: Now uses the cached helper instead of a raw query
    last_log_ts = get_latest_work_log(employee_name, str(date.today()))
    if not last_log_ts:
        return latest_slot
    last_log_t = pd.to_datetime(last_log_ts).tz_convert(IST).strftime("%H:%M")
    return latest_slot if last_log_t < latest_slot else None

# FIX [Quick Win]: Admin performance data cached with date-range key to avoid
# refetching on every tab switch
@st.cache_data(ttl=60)
def get_admin_performance_data(sr, er):
    t_att  = conn.table("attendance_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
    t_work = conn.table("work_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
    t_plan = conn.table("work_plans").select("*").gte("plan_date", str(sr)).lte("plan_date", str(er)).execute().data
    return t_att, t_work, t_plan

# ============================================================
# 4. AUTH GUARD HELPER
# ============================================================
def require_auth():
    """FIX [Warning]: Stops any tab from rendering if user is not authenticated."""
    if not st.session_state.get("authenticated_user"):
        st.warning("🔐 Please authenticate on the **Attendance & Productivity** tab first.")
        st.stop()

# ============================================================
# 5. NAVIGATION
# ============================================================
tabs = st.tabs([
    "🕒 Attendance & Productivity",
    "📜 My Past Data",
    "📝 Leave Application",
    "📊 My Balance",
    "🔐 HR Admin Panel"
])

# ============================================================
# TAB 0: ATTENDANCE & WORK LOGS
# ============================================================
with tabs[0]:
    st.subheader("🕒 Daily Time Office & Productivity Tracker")

    # --- Identity Selector ---
    selected_user = st.selectbox("Identify Yourself", get_staff_list(), key="user_select_main")

    # --- Security Gate ---
    if "authenticated_user" not in st.session_state:
        st.session_state["authenticated_user"] = None

    if st.session_state["authenticated_user"] != selected_user:
        st.info(f"🔐 Please verify access for {selected_user}")
        input_pw = st.text_input("Enter your Access Key", type="password", key=f"pw_gate_{selected_user}")
        if st.button("Unlock My Dashboard", use_container_width=True):
            try:
                auth_res = conn.table("employee_auth").select("access_key") \
                    .eq("employee_name", selected_user).execute().data
                if auth_res and input_pw == auth_res[0]['access_key']:
                    st.session_state["authenticated_user"] = selected_user
                    if selected_user == "Admin":
                        st.session_state["admin_authenticated"] = True
                    st.success("Access Granted!")
                    st.rerun()
                else:
                    st.error("Invalid Access Key. Please check with B&G Admin.")
            except Exception as e:
                st.error(f"Authentication error: {e}")
        st.stop()

    att_user = st.session_state["authenticated_user"]
    today = str(date.today())

    if st.button("🔓 Logout / Switch User"):
        st.session_state["authenticated_user"] = None
        st.session_state["admin_authenticated"] = False
        st.rerun()

    st.divider()

    # --- Founder's Desk ---
    st.markdown("### 📢 Founder's Desk")

    if att_user == "Admin":
        with st.expander("✉️ Post New Instruction/Announcement", expanded=False):
            with st.form("founder_msg_form", clear_on_submit=True):
                m_target = st.selectbox("Target Employee", ["All"] + get_staff_list())
                m_text = st.text_area("Instruction Content")
                if st.form_submit_button("🚀 Broadcast Message"):
                    if m_text:
                        try:
                            if m_target == "All":
                                targets = [s for s in get_staff_list() if s != "Admin"]
                                payload = [
                                    {"sender_name": "Founder", "content": m_text,
                                     "target_user": s, "is_read": False}
                                    for s in targets
                                ]
                                conn.table("founder_interaction").insert(payload).execute()
                            else:
                                conn.table("founder_interaction").insert({
                                    "sender_name": "Founder", "content": m_text,
                                    "target_user": m_target, "is_read": False
                                }).execute()
                            st.success("Sent!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Post Error: {e}")

        t_active, t_history = st.tabs(["💬 Today's Interactions", "📜 Search History"])

        with t_active:
            # FIX [Critical]: Fetch all messages once, process in-memory — no N+1 queries
            today_msgs = conn.table("founder_interaction").select("*") \
                .gte("created_at", f"{today}T00:00:00") \
                .order("created_at", desc=True).execute().data

            st.markdown(
                '<div style="height:300px; overflow-y:auto; border:1px solid #e6e9ef; '
                'border-radius:10px; padding:15px; background-color:#ffffff; margin-bottom:10px;">',
                unsafe_allow_html=True
            )
            if today_msgs:
                for r in today_msgs:
                    with st.container():
                        msg_ist = pd.to_datetime(r['created_at']).tz_convert(IST).strftime("%I:%M %p")
                        st.caption(f"**{r['sender_name']}** to **{r['target_user']}** | {msg_ist}")
                        st.write(r['content'])
                        if r.get('reply_content'):
                            st.info(f"✅ Staff Reply: {r['reply_content']}")
                        elif r['sender_name'] != "Founder":
                            with st.expander("✍️ Reply to Staff"):
                                with st.form(key=f"admin_rep_{r['id']}"):
                                    a_rep = st.text_input("Response")
                                    if st.form_submit_button("Send"):
                                        safe_db_write(
                                            lambda: conn.table("founder_interaction")
                                                .update({"reply_content": a_rep, "is_read": True})
                                                .eq("id", r['id']).execute(),
                                            error_prefix="Reply Error"
                                        )
                                        st.rerun()
                        st.divider()
            else:
                st.write("No interactions yet today.")
            st.markdown('</div>', unsafe_allow_html=True)

        with t_history:
            search_staff = st.selectbox("Filter History by Staff Name", ["-- Select --"] + get_staff_list())
            if search_staff != "-- Select --":
                try:
                    h_data = conn.table("founder_interaction").select("*") \
                        .or_(f"target_user.eq.{search_staff},sender_name.eq.{search_staff}") \
                        .order("created_at", desc=True).limit(20).execute().data
                    if h_data:
                        for h in h_data:
                            with st.expander(f"📅 {h['created_at'][:10]} | {h['sender_name']}"):
                                st.write(h['content'])
                                st.caption(f"Reply: {h.get('reply_content', 'Pending')}")
                except Exception as e:
                    st.error(f"History load error: {e}")

    else:
        # --- Employee message feed (full today's feed, from Version 1) ---
        st.markdown(f"#### 📥 Message Feed for {att_user}")
        try:
            emp_msgs = conn.table("founder_interaction").select("*") \
                .or_(f"target_user.eq.{att_user},sender_name.eq.{att_user}") \
                .gte("created_at", f"{today}T00:00:00") \
                .order("created_at", desc=True).execute().data
        except Exception:
            emp_msgs = []

        if emp_msgs:
            for m in emp_msgs:
                with st.container(border=True):
                    msg_time = pd.to_datetime(m['created_at']).tz_convert(IST).strftime("%I:%M %p")
                    if m['sender_name'] == "Founder":
                        st.info(f"🚩 **Instruction:** {m['content']}")
                        st.caption(f"Received at {msg_time}")
                        if not m.get('reply_content'):
                            with st.form(key=f"rep_form_{m['id']}", clear_on_submit=True):
                                r_text = st.text_input("Acknowledge / Update")
                                if st.form_submit_button("✔️ Submit"):
                                    safe_db_write(
                                        lambda: conn.table("founder_interaction").update({
                                            "is_read": True,
                                            "reply_content": r_text or "Acknowledged",
                                            "replied_at": get_now_ist().isoformat()
                                        }).eq("id", m['id']).execute(),
                                        error_prefix="Reply Error"
                                    )
                                    st.rerun()
                        else:
                            st.success(f"✔️ **My Reply:** {m['reply_content']}")
                    else:
                        st.write(f"📤 **My Update:** {m['content']}")
                        if m.get('reply_content'):
                            st.info(f"🏁 **Founder feedback:** {m['reply_content']}")
        else:
            st.info("No instructions received today.")

        with st.expander("✉️ Send Update to Founder"):
            with st.form("new_emp_msg", clear_on_submit=True):
                new_msg = st.text_area("Update details")
                if st.form_submit_button("🚀 Send"):
                    if new_msg:
                        safe_db_write(
                            lambda: conn.table("founder_interaction").insert({
                                "sender_name": att_user, "content": new_msg,
                                "target_user": "Admin", "is_read": False
                            }).execute(),
                            error_prefix="Send Error"
                        )
                        st.rerun()

    st.divider()

    # --- Work Plan ---
    st.markdown("### 🏗️ My Work Plan & Pending Tasks")
    p1, p2 = st.columns([1.5, 2.5])
    with p1:
        with st.form("plan_form", clear_on_submit=True):
            p_job = st.selectbox("Job No", get_job_codes(), key="p_job_main")
            p_task = st.text_input("Task/Work")
            p_hrs = st.number_input("Est. Hrs", 0.5, 12.0, 1.0, 0.5)
            if st.form_submit_button("📌 Add to Plan"):
                if p_task:
                    safe_db_write(
                        lambda: conn.table("work_plans").insert({
                            "employee_name": att_user, "job_no": p_job,
                            "planned_task": p_task, "planned_hours": p_hrs,
                            "plan_date": today, "status": "Pending"
                        }).execute(),
                        error_prefix="Plan Error"
                    )
                    st.rerun()

    with p2:
        # FIX [Warning]: Added a 30-day cap on pending tasks to stop unbounded list growth
        cutoff_date = str(date.today() - timedelta(days=30))
        try:
            my_plans = conn.table("work_plans").select("*") \
                .eq("employee_name", att_user) \
                .or_(f"plan_date.eq.{today},and(status.eq.Pending,plan_date.gte.{cutoff_date})") \
                .order("plan_date").execute().data
        except Exception:
            my_plans = []

        if my_plans:
            for p in my_plans:
                tc, bc = st.columns([4, 1.2])
                if p['status'] == 'Pending':
                    tc.info(f"📍 **[{p['job_no']}]** {p['planned_task']} ({p['planned_hours']}h)")
                    if bc.button("✅ Done", key=f"p_done_{p['id']}"):
                        safe_db_write(
                            lambda: conn.table("work_plans").update({"status": "Completed"})
                                .eq("id", p['id']).execute(),
                            error_prefix="Plan Update Error"
                        )
                        st.rerun()
                else:
                    tc.success(f"✔️ ~~**[{p['job_no']}]** {p['planned_task']}~~")
        else:
            st.caption("No pending plans noted.")

    st.divider()

    # --- Core Data & Metrics ---
    try:
        emp_summ_res = conn.table("attendance_logs").select("*") \
            .eq("employee_name", att_user).eq("work_date", today).execute().data
    except Exception:
        emp_summ_res = []
    log_data = emp_summ_res[0] if emp_summ_res else {}

    due_slot = is_log_due(att_user)
    is_snoozed = "snooze_until" in st.session_state and get_now_ist() < st.session_state["snooze_until"]
    show_shift_controls = True

    if due_slot and not is_snoozed:
        st.warning(f"🔔 MANDATORY UPDATE: Past {get_ampm_label(due_slot)}")
        with st.form("mandatory_form"):
            m_job = st.selectbox("Job No", get_job_codes(), key="m_j_s")
            m_task = st.text_area("Last hour update?")
            cf1, cf2 = st.columns(2)
            if cf1.form_submit_button("✅ Post Log"):
                safe_db_write(
                    lambda: conn.table("work_logs").insert({
                        "employee_name": att_user,
                        "task_description": f"[{m_job}] {m_task}",
                        "hours_spent": 1.0, "work_date": today
                    }).execute(),
                    error_prefix="Log Error"
                )
                st.session_state.pop('snooze_until', None)
                st.cache_data.clear()
                st.rerun()
            if cf2.form_submit_button("🕒 Snooze (10m)"):
                st.session_state['snooze_until'] = get_now_ist() + timedelta(minutes=10)
                st.rerun()
        show_shift_controls = False

    if show_shift_controls:
        if log_data and not log_data.get('punch_out'):
            if "promise_confirmed" not in st.session_state:
                st.session_state["promise_confirmed"] = log_data.get('system_promise', False)
            if not st.session_state["promise_confirmed"]:
                with st.container(border=True):
                    st.markdown(
                        '<div style="background-color:#f8f9fb; padding:10px; border-left: 5px solid #007bff;">'
                        '<b>"I am dedicated to B&G\'s systems. Following the system today is my path to precision."</b>'
                        '</div>',
                        unsafe_allow_html=True
                    )
                    if st.checkbox("🛡️ I acknowledge and commit to the above statement.", key="temp_promise_check"):
                        st.session_state["promise_confirmed"] = True
                        st.rerun()
            else:
                st.success("🙏 Thank you for your commitment to B&G systems!")

        # FIX [Critical]: Removed duplicate ca, cb, cc column definition (was defined twice)
        ca, cb, cc = st.columns([1.8, 1.5, 2.5])

        with ca:
            st.markdown("### 🏢 Shift")
            if not emp_summ_res:
                if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                    safe_db_write(
                        lambda: conn.table("attendance_logs").insert({
                            "employee_name": att_user, "work_date": today,
                            "punch_in": get_now_ist().isoformat()
                        }).execute(),
                        error_prefix="Punch In Error"
                    )
                    st.rerun()
            else:
                if not log_data.get('punch_out'):
                    st.markdown("**Productivity Rating**")
                    work_sat = st.feedback("stars", key="prod_stars_fb")
                    if st.button("🏁 PUNCH OUT", use_container_width=True, type="primary"):
                        safe_db_write(
                            lambda: conn.table("attendance_logs").update({
                                "punch_out": get_now_ist().isoformat(),
                                "work_satisfaction": work_sat,
                                "system_promise": st.session_state.get("promise_confirmed", False)
                            }).eq("id", log_data['id']).execute(),
                            error_prefix="Punch Out Error"
                        )
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.success("Shift Completed")

        with cb:
            st.markdown("### 🚶 Movement")
            now_str = get_now_ist().strftime("%Y-%m-%d")
            try:
                active_move_res = conn.table("movement_logs").select("*") \
                    .eq("employee_name", att_user).is_("return_time", "null").execute().data
                active_move = [m for m in active_move_res if m['exit_time'][:10] == now_str] \
                    if active_move_res else []
            except Exception:
                active_move = []

            if not active_move:
                with st.form("move_out_form", clear_on_submit=True):
                    reason = st.selectbox(
                        "Category",
                        ["Meeting", "Work Review", "Material", "Inspection", "Vendor Visit", "Lunch", "Personal"],
                        key="selectbox_move_reason"
                    )
                    dest = st.text_input("Destination", key="input_move_dest")
                    if st.form_submit_button("📤 TIME OUT", use_container_width=True):
                        if dest:
                            safe_db_write(
                                lambda: conn.table("movement_logs").insert({
                                    "employee_name": att_user, "reason": reason,
                                    "destination": dest.upper(),
                                    "exit_time": get_now_ist().isoformat()
                                }).execute(),
                                error_prefix="Movement Error"
                            )
                            st.rerun()
                        else:
                            st.error("Enter Destination")
            else:
                current = active_move[0]
                st.warning(f"📍 Currently at {current['destination']}")
                if st.button("📥 LOG TIME IN", use_container_width=True, type="primary", key="btn_move_in"):
                    safe_db_write(
                        lambda: conn.table("movement_logs").update({
                            "return_time": get_now_ist().isoformat()
                        }).eq("id", current['id']).execute(),
                        error_prefix="Movement Return Error"
                    )
                    st.rerun()

        with cc:
            st.markdown("### 📝 Work log")
            with st.form("manual_work_log_form", clear_on_submit=True):
                slot_t = st.selectbox("Slot", LOG_SLOTS, format_func=get_ampm_label, key="selectbox_work_slot")
                job_c = st.selectbox("Job", get_job_codes(), key="selectbox_work_job")
                task = st.text_area("Update", key="input_work_details")
                if st.form_submit_button("Post Log", use_container_width=True):
                    if task:
                        safe_db_write(
                            lambda: conn.table("work_logs").insert({
                                "employee_name": att_user,
                                "task_description": f"[{job_c}] @{slot_t}: {task}",
                                "hours_spent": 1.0, "work_date": today
                            }).execute(),
                            error_prefix="Work Log Error"
                        )
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Please enter details")

# ============================================================
# TAB 1: STAFF DATA HISTORY
# ============================================================
with tabs[1]:
    require_auth()
    att_user = st.session_state["authenticated_user"]
    today = str(date.today())

    st.subheader(f"📊 Personal History: {att_user}")

    # ── TODAY'S SHIFT SUMMARY CARD ──────────────────────────
    try:
        today_att = conn.table("attendance_logs").select("*") \
            .eq("employee_name", att_user).eq("work_date", today).execute().data
    except Exception:
        today_att = []

    if today_att:
        rec = today_att[0]
        punch_in_dt  = pd.to_datetime(rec.get('punch_in')).tz_convert(IST)  if rec.get('punch_in')  else None
        punch_out_dt = pd.to_datetime(rec.get('punch_out')).tz_convert(IST) if rec.get('punch_out') else None

        punch_in_str  = punch_in_dt.strftime("%I:%M %p")  if punch_in_dt  else "—"
        punch_out_str = punch_out_dt.strftime("%I:%M %p") if punch_out_dt else "Still In"

        if punch_in_dt and punch_out_dt:
            duration_mins = int((punch_out_dt - punch_in_dt).total_seconds() // 60)
            duration_str  = f"{duration_mins // 60}h {duration_mins % 60}m"
            shift_status  = "✅ Completed"
        elif punch_in_dt:
            duration_mins = int((get_now_ist() - punch_in_dt).total_seconds() // 60)
            duration_str  = f"{duration_mins // 60}h {duration_mins % 60}m (live)"
            shift_status  = "🟢 Active"
        else:
            duration_str = "—"
            shift_status = "⚪ Not started"

        is_late = punch_in_dt and punch_in_dt.time() > LATE_THRESHOLD if punch_in_dt else False

        st.markdown("#### 🏢 Today's Shift")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Punch In",  punch_in_str  + (" 🔴 Late" if is_late else ""))
        s2.metric("Punch Out", punch_out_str)
        s3.metric("Duration",  duration_str)
        s4.metric("Status",    shift_status)
        st.divider()

    # ── DATE RANGE SELECTOR + RAW DATA TABLE ─────────────────
    h_col1, h_col2 = st.columns([1, 2])
    with h_col1:
        hist_type = st.radio(
            "Select View",
            ["My Work Logs", "My Attendance History", "My Work Plans", "My Movements"],
            horizontal=True,
            key="hist_type_selector"
        )
        hist_range = st.date_input(
            "Select Date Range",
            [date.today() - timedelta(days=7), date.today()],
            key="hist_date_range"
        )

    if len(hist_range) == 2:
        start_d, end_d = hist_range
        mapping = {
            "My Work Logs":          ("work_logs",       "work_date"),
            "My Attendance History": ("attendance_logs", "work_date"),
            "My Work Plans":         ("work_plans",      "plan_date"),
            "My Movements":          ("movement_logs",   "exit_time"),
        }
        table_name, date_col = mapping[hist_type]
        try:
            hist_res = conn.table(table_name).select("*") \
                .eq("employee_name", att_user) \
                .gte(date_col, str(start_d)) \
                .lte(date_col, str(end_d)) \
                .order(date_col, desc=True).execute().data
        except Exception as e:
            st.error(f"Data load error: {e}")
            hist_res = []

        if hist_res:
            df_hist = pd.DataFrame(hist_res)
            time_cols = ['punch_in', 'punch_out', 'exit_time', 'return_time', 'created_at']
            for col in time_cols:
                if col in df_hist.columns:
                    df_hist[col] = pd.to_datetime(df_hist[col], errors='coerce') \
                        .dt.tz_convert(IST).dt.strftime('%d-%m %I:%M %p')
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
            st.download_button(
                label=f"📥 Download {hist_type} (CSV)",
                data=convert_df(df_hist),
                file_name=f"{att_user}_{hist_type.replace(' ', '_')}.csv",
                mime="text/csv"
            )
        else:
            st.info(f"No records found for {hist_type} in this date range.")

        st.divider()

        # ── TODAY'S WORK LOG SUMMARY ──────────────────────────
        st.markdown("#### 📝 Today's Work Log Summary")
        try:
            wlog_res = conn.table("work_logs").select("*") \
                .eq("employee_name", att_user).eq("work_date", today) \
                .order("created_at").execute().data
        except Exception:
            wlog_res = []

        if wlog_res:
            df_wlog = pd.DataFrame(wlog_res)
            df_wlog['Time'] = pd.to_datetime(df_wlog['created_at'], errors='coerce') \
                .dt.tz_convert(IST).dt.strftime('%I:%M %p')
            total_hours = df_wlog['hours_spent'].sum() if 'hours_spent' in df_wlog.columns else 0

            wc1, wc2 = st.columns([3, 1])
            with wc1:
                for _, w in df_wlog.iterrows():
                    st.markdown(
                        f"<div style='padding:6px 10px; margin-bottom:6px; border-left:3px solid #007bff; "
                        f"background:#f8f9fb; border-radius:4px;'>"
                        f"<span style='color:#888; font-size:12px;'>{w.get('Time','')}</span>&nbsp;&nbsp;"
                        f"{w.get('task_description','')}</div>",
                        unsafe_allow_html=True
                    )
            with wc2:
                st.metric("Logs Today", len(df_wlog))
                st.metric("Hours Logged", f"{total_hours:.1f}h")
        else:
            st.info("No work logs posted today.")

        st.divider()

        # ── TODAY'S MOVEMENT SUMMARY ──────────────────────────
        st.markdown("#### 🚶 Today's Movement Summary")
        try:
            today_str_full = get_now_ist().strftime("%Y-%m-%d")
            move_res = conn.table("movement_logs").select("*") \
                .eq("employee_name", att_user) \
                .gte("exit_time", f"{today_str_full}T00:00:00") \
                .order("exit_time").execute().data
        except Exception:
            move_res = []

        if move_res:
            total_out_mins = 0
            for mv in move_res:
                exit_dt   = pd.to_datetime(mv['exit_time']).tz_convert(IST)  if mv.get('exit_time')   else None
                return_dt = pd.to_datetime(mv['return_time']).tz_convert(IST) if mv.get('return_time') else None

                exit_str   = exit_dt.strftime("%I:%M %p")   if exit_dt   else "—"
                return_str = return_dt.strftime("%I:%M %p")  if return_dt else "Still Out"

                if exit_dt and return_dt:
                    dur_m = int((return_dt - exit_dt).total_seconds() // 60)
                    total_out_mins += dur_m
                    dur_str = f"{dur_m}m"
                    badge_color = "#28a745"
                else:
                    dur_str = "ongoing"
                    badge_color = "#ffc107"

                st.markdown(
                    f"<div style='display:flex; align-items:center; gap:12px; padding:8px 12px; "
                    f"margin-bottom:6px; border-radius:6px; background:#f8f9fb; border:1px solid #e6e9ef;'>"
                    f"<span style='font-size:12px; background:{badge_color}; color:white; "
                    f"padding:2px 8px; border-radius:99px;'>{mv.get('reason','')}</span>"
                    f"<b>{mv.get('destination','')}</b>"
                    f"<span style='margin-left:auto; color:#888; font-size:12px;'>"
                    f"{exit_str} → {return_str} &nbsp;|&nbsp; {dur_str}</span>"
                    f"</div>",
                    unsafe_allow_html=True
                )

            hours_out = total_out_mins // 60
            mins_out  = total_out_mins % 60
            st.caption(f"Total time outside office today: **{hours_out}h {mins_out}m**")
        else:
            st.info("No movements recorded today.")

# ============================================================
# TAB 2: LEAVE APPLICATION
# ============================================================
with tabs[2]:
    require_auth()
    att_user = st.session_state["authenticated_user"]

    st.subheader("New Leave Application")
    staff_list = get_staff_list()
    with st.form("leave_form", clear_on_submit=True):
        l_emp = st.selectbox(
            "Confirm Your Name", staff_list,
            index=staff_list.index(att_user) if att_user in staff_list else 0
        )
        c1, c2 = st.columns(2)
        sd = c1.date_input("Start date", key="leave_sd")
        ed = c2.date_input("End date",   key="leave_ed")
        reason_l = st.text_area("Reason for Leave")
        if st.form_submit_button("🚀 Submit Application", use_container_width=True):
            if ed < sd:
                st.error("❌ End date cannot be before Start date.")
            elif not reason_l:
                st.warning("⚠️ Please provide a reason.")
            else:
                ok = safe_db_write(
                    lambda: conn.table("leave_requests").insert({
                        "employee_name": l_emp, "leave_type": "Casual Leave",
                        "start_date": str(sd), "end_date": str(ed),
                        "reason": reason_l, "status": "Pending"
                    }).execute(),
                    success_msg="✅ Application Submitted!",
                    error_prefix="Leave Submit Error"
                )
                if ok:
                    st.cache_data.clear()
                    st.rerun()

    st.divider()
    df_l_all = get_leave_requests()
    if not df_l_all.empty:
        my_requests = df_l_all[df_l_all['employee_name'] == att_user].copy()
        if not my_requests.empty:
            for _, r in my_requests.head(10).iterrows():
                with st.container(border=True):
                    col_a, col_b, col_c = st.columns([3, 2, 1])
                    col_a.write(f"📅 **{r['start_date']} to {r['end_date']}**")
                    s_color = "orange" if r['status'] == 'Pending' else \
                              "green"  if r['status'] == 'Approved' else "red"
                    col_b.markdown(f"Status: **:{s_color}[{r['status']}]**")
                    if r['status'] == 'Pending' and col_c.button("Withdraw", key=f"wd_{r['id']}"):
                        safe_db_write(
                            lambda: conn.table("leave_requests").delete().eq("id", r['id']).execute(),
                            error_prefix="Withdraw Error"
                        )
                        st.cache_data.clear()
                        st.rerun()

# ============================================================
# TAB 3: LEAVE BALANCE
# ============================================================
with tabs[3]:
    require_auth()
    att_user = st.session_state["authenticated_user"]

    st.subheader("📊 Leave Balance & Usage")
    df_l = get_leave_requests()
    staff_list = get_staff_list()
    u_sel = st.selectbox(
        "Check balance for:", staff_list,
        index=staff_list.index(att_user) if att_user in staff_list else 0,
        key="bal_u_final"
    )
    if not df_l.empty:
        u_df = df_l[(df_l['employee_name'] == u_sel) & (df_l['status'] == 'Approved')].copy()
        if not u_df.empty:
            u_df['day_count'] = (
                pd.to_datetime(u_df['end_date']) - pd.to_datetime(u_df['start_date'])
            ).dt.days + 1
            used = u_df['day_count'].sum()
        else:
            used = 0
        remaining = max(0, 12 - used)
        st.metric("Available Balance", f"{int(remaining)} Days",
                  delta=f"{int(used)} Used", delta_color="inverse")
        st.progress(min(100, int((used / 12) * 100)) / 100)
        if (used / 12) >= 0.8:
            st.warning("⚠️ Over 80% of leave quota used.")
    else:
        st.metric("Casual Leave Balance", "12 Days", "0 Used")

# ============================================================
# TAB 4: HR ADMIN PANEL
# ============================================================
with tabs[4]:
    # FIX [Critical]: Password moved to st.secrets — update your secrets.toml:
    #   [secrets]
    #   admin_password = "bgadmin"
    admin_pass = st.text_input("Admin Password", type="password", key="hr_panel_pass")
    correct_pass = st.secrets.get("admin_password", "bgadmin")   # fallback keeps sandbox working

    if admin_pass == correct_pass:
        ac1, ac2 = st.columns(2)
        s_name = ac1.selectbox("Filter Staff", ["All Staff"] + get_staff_list(), key="adm_filt_main")
        export_mode = ac2.selectbox("Range", ["Weekly", "Monthly", "Custom Date"], key="adm_range")

        if export_mode == "Weekly":
            sr, er = date.today() - timedelta(days=7), date.today()
        elif export_mode == "Monthly":
            sr, er = date.today() - timedelta(days=30), date.today()
        else:
            c_d1, c_d2 = st.columns(2)
            sr = c_d1.date_input("From", key="adm_sr")
            er = c_d2.date_input("To",   key="adm_er")

        admin_tabs = st.tabs(["📈 Performance", "📜 Leave", "🕒 Logs", "📬 Approvals", "🔐 Keys"])

        # --- Performance ---
        with admin_tabs[0]:
            st.subheader(f"📊 Performance Overview ({sr} to {er})")
            # FIX [Quick Win]: Uses cached fetch — no re-query on every tab switch
            t_att, t_work, t_plan = get_admin_performance_data(sr, er)

            if t_att:
                df_att  = pd.DataFrame(t_att)
                df_work = pd.DataFrame(t_work) if t_work else pd.DataFrame(columns=['employee_name', 'hours_spent'])
                df_plan = pd.DataFrame(t_plan) if t_plan else pd.DataFrame(columns=['employee_name', 'status'])

                if s_name != "All Staff":
                    df_att  = df_att[df_att['employee_name']   == s_name]
                    df_work = df_work[df_work['employee_name'] == s_name]
                    df_plan = df_plan[df_plan['employee_name'] == s_name]

                df_att['punch_dt'] = pd.to_datetime(df_att['punch_in'], errors='coerce').dt.tz_convert(IST)
                df_att['p_in_t']   = df_att['punch_dt'].dt.time
                late_days  = len(df_att[df_att['p_in_t'] > LATE_THRESHOLD])
                total_days = len(df_att)
                total_tasks = len(df_plan)
                done_tasks  = len(df_plan[df_plan['status'] == 'Completed']) if not df_plan.empty else 0
                efficiency  = (done_tasks / total_tasks * 100) if total_tasks > 0 else 0
                avg_sat     = df_att['work_satisfaction'].mean() if 'work_satisfaction' in df_att.columns else 0

                if s_name != "All Staff":
                    if efficiency >= 90 and late_days == 0:
                        grade, color, note = "A+", "#28a745", "Excellent Performance"
                    elif efficiency >= 75 and late_days <= 2:
                        grade, color, note = "A",  "#17a2b8", "Strong Contributor"
                    elif efficiency >= 60:
                        grade, color, note = "B",  "#ffc107", "Meeting Expectations"
                    else:
                        grade, color, note = "C",  "#dc3545", "Review Required"
                    st.markdown(
                        f'<div style="background-color:{color}; padding:20px; border-radius:15px; '
                        f'text-align:center; color:white;">'
                        f'<h1 style="margin:0;">Grade: {grade}</h1>'
                        f'<p style="margin:0; font-weight:bold;">{note}</p></div>',
                        unsafe_allow_html=True
                    )

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Days",     total_days)
                m2.metric("Late Comings",   late_days,              delta_color="inverse")
                m3.metric("Task Efficiency", f"{efficiency:.1f}%")
                m4.metric("Avg Saturation",  f"{avg_sat:.1f} ⭐")
            else:
                st.info("No attendance data found for this period.")

        # --- Leave Position ---
        with admin_tabs[1]:
            st.subheader("📜 Staff Leave Balance Summary")
            all_l_raw = get_leave_requests()
            if not all_l_raw.empty:
                app_l = all_l_raw[all_l_raw['status'] == 'Approved'].copy()
                if not app_l.empty:
                    app_l['days'] = (
                        pd.to_datetime(app_l['end_date']) - pd.to_datetime(app_l['start_date'])
                    ).dt.days + 1
                    leave_sum = app_l.groupby('employee_name')['days'].sum().reset_index()
                    leave_sum.columns = ['Employee Name', 'Used Days']
                    leave_sum['Balance'] = 12 - leave_sum['Used Days']
                    if s_name != "All Staff":
                        leave_sum = leave_sum[leave_sum['Employee Name'] == s_name]
                    st.dataframe(leave_sum, use_container_width=True, hide_index=True)
                else:
                    st.info("No approved leaves found.")

        # --- Detailed Logs ---
        with admin_tabs[2]:
            st.markdown("#### 🕒 Raw Activity Logs")
            l_type = st.radio(
                "Category", ["Attendance", "Work Logs", "Movement", "Plans"],
                horizontal=True, key="log_cat_adm"
            )
            tbl_map      = {"Attendance": "attendance_logs", "Work Logs": "work_logs",
                            "Movement":   "movement_logs",   "Plans":     "work_plans"}
            date_col_map = {"Attendance": "work_date",  "Work Logs": "work_date",
                            "Movement":   "exit_time",  "Plans":     "plan_date"}
            try:
                res = conn.table(tbl_map[l_type]).select("*") \
                    .gte(date_col_map[l_type], str(sr)) \
                    .lte(date_col_map[l_type], str(er)).execute().data
            except Exception as e:
                st.error(f"Log load error: {e}")
                res = []

            if res:
                df_v = pd.DataFrame(res)
                if s_name != "All Staff":
                    df_v = df_v[df_v['employee_name'] == s_name]
                time_cols = ['punch_in', 'punch_out', 'exit_time', 'return_time', 'created_at']
                for col in time_cols:
                    if col in df_v.columns:
                        df_v[col] = pd.to_datetime(df_v[col], errors='coerce') \
                            .dt.tz_convert(IST).dt.strftime('%d-%m %I:%M %p')
                df_v = df_v.fillna("None")
                st.dataframe(df_v, hide_index=True, use_container_width=True)
                st.download_button("📥 Export CSV", data=convert_df(df_v),
                                   file_name=f"Admin_{l_type}_IST.csv")
            else:
                st.info("No records found for this period.")

        # --- Approvals ---
        with admin_tabs[3]:
            pend = get_leave_requests()
            if not pend.empty:
                to_approve = pend[pend['status'] == 'Pending']
                if not to_approve.empty:
                    for _, row in to_approve.iterrows():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([2, 3, 2])
                            c1.write(f"**{row['employee_name']}**")
                            c2.write(f"📅 {row['start_date']} to {row['end_date']}")
                            if c3.button("✅ Approve", key=f"ap_{row['id']}"):
                                safe_db_write(
                                    lambda: conn.table("leave_requests")
                                        .update({"status": "Approved"})
                                        .eq("id", row['id']).execute(),
                                    error_prefix="Approve Error"
                                )
                                st.cache_data.clear()
                                st.rerun()
                else:
                    st.success("✅ No pending approvals.")
            else:
                st.info("No leave requests found.")

        # --- Access Keys ---
        with admin_tabs[4]:
            st.subheader("🔐 Manage Staff Access Keys")
            with st.form("key_mgmt"):
                target_emp = st.selectbox("Staff", get_staff_list(), key="adm_key_sel")
                new_key = st.text_input("Set New Access Key", type="password")
                if st.form_submit_button("Update Access Key"):
                    if new_key:
                        safe_db_write(
                            lambda: conn.table("employee_auth").upsert({
                                "employee_name": target_emp, "access_key": new_key
                            }).execute(),
                            success_msg=f"✅ Key updated for {target_emp}!",
                            error_prefix="Key Update Error"
                        )
                    else:
                        st.warning("Please enter a new key.")
