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
OVERHEAD_CODES = {'GENERAL', 'ACCOUNTS', 'PURCHASE', '5S', 'MAINTENANCE',
                  'CLIENT_CALLS', 'ESTIMATIONS', 'QUOTATIONS', 'PROD_PLAN'}

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
    try:
        fn()
        if success_msg:
            st.success(success_msg)
        return True
    except Exception as e:
        st.error(f"{error_prefix}: {e}")
        return False

# ============================================================
# 3. DATA LOADERS  (all cached)
# ============================================================

@st.cache_data(ttl=30)
def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return [s['name'] for s in res.data] if res.data else ["Admin", "Staff Member"]
    except Exception:
        return ["Admin", "Staff Member"]

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

@st.cache_data(ttl=120)
def get_leave_requests():
    try:
        res = conn.table("leave_requests").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

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

@st.cache_data(ttl=60)
def get_missed_punchouts(employee_name, today_str):
    """Attendance rows with punch_in but no punch_out, on days before today."""
    try:
        res = conn.table("attendance_logs").select("*") \
            .eq("employee_name", employee_name) \
            .lt("work_date", today_str) \
            .is_("punch_out", "null") \
            .order("work_date", desc=True).limit(10).execute().data
        return res if res else []
    except Exception:
        return []

@st.cache_data(ttl=60)
def get_all_missed_punchouts(today_str):
    """Admin view — all staff with open punch-ins from any previous day."""
    try:
        res = conn.table("attendance_logs").select("*") \
            .lt("work_date", today_str) \
            .is_("punch_out", "null") \
            .order("work_date", desc=True).execute().data
        return res if res else []
    except Exception:
        return []

# FIX [Critical #3]: Cache live per-employee queries that were firing on every rerun
@st.cache_data(ttl=15)
def get_today_attendance(employee_name, today_str):
    try:
        res = conn.table("attendance_logs").select("*") \
            .eq("employee_name", employee_name).eq("work_date", today_str).execute().data
        return res
    except Exception:
        return []

@st.cache_data(ttl=15)
def get_today_founder_messages(employee_name, today_str):
    try:
        res = conn.table("founder_interaction").select("*") \
            .or_(f"target_user.eq.{employee_name},sender_name.eq.{employee_name}") \
            .gte("created_at", f"{today_str}T00:00:00") \
            .order("created_at", desc=True).execute().data
        return res if res else []
    except Exception:
        return []

@st.cache_data(ttl=15)
def get_active_movement(employee_name, today_str):
    try:
        res = conn.table("movement_logs").select("*") \
            .eq("employee_name", employee_name).is_("return_time", "null").execute().data
        return [m for m in res if m['exit_time'][:10] == today_str] if res else []
    except Exception:
        return []

def is_log_due(employee_name):
    if st.session_state.get('snooze_until') and get_now_ist() < st.session_state['snooze_until']:
        return None
    now_t = get_now_ist().strftime("%H:%M")
    past_slots = [s for s in LOG_SLOTS if s <= now_t]
    if not past_slots:
        return None
    latest_slot = past_slots[-1]
    last_log_ts = get_latest_work_log(employee_name, str(date.today()))
    if not last_log_ts:
        return latest_slot
    last_log_t = pd.to_datetime(last_log_ts).tz_convert(IST).strftime("%H:%M")
    return latest_slot if last_log_t < latest_slot else None

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
                    # FIX [Improvement]: Clear stale cache on login too
                    st.cache_data.clear()
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

    # FIX [Critical #2 + Warning #3]: Logout clears ALL relevant session state,
    # including promise_confirmed so it can't leak to the next user.
    if st.button("🔓 Logout / Switch User"):
        st.session_state["authenticated_user"] = None
        st.session_state["admin_authenticated"] = False
        st.session_state.pop("promise_confirmed", None)
        st.session_state.pop("snooze_until", None)
        st.session_state.pop("short_shift_ack", None)
        st.cache_data.clear()
        st.rerun()

    st.divider()

    # ── MISSED PUNCH-OUT ALERT ────────────────────────────────
    missed = get_missed_punchouts(att_user, today)
    if missed:
        st.error(
            f"🚨 **Missed Punch-Out Detected!** You have **{len(missed)} day(s)** with no punch-out recorded. "
            f"Please contact HR to correct your attendance record."
        )
        with st.expander("📋 View affected days", expanded=True):
            for m in missed:
                punch_in_ist = pd.to_datetime(m['punch_in']).tz_convert(IST).strftime('%d %b %Y, %I:%M %p') \
                    if m.get('punch_in') else "—"
                st.markdown(
                    f"<div style='padding:8px 12px; margin-bottom:6px; border-left:4px solid #dc3545; "
                    f"background:#fff5f5; border-radius:4px;'>"
                    f"📅 <b>{m['work_date']}</b> &nbsp;|&nbsp; Punched in at {punch_in_ist} &nbsp;|&nbsp; "
                    f"<span style='color:#dc3545;'>No punch-out recorded</span></div>",
                    unsafe_allow_html=True
                )
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
                                # Single batch insert — atomic, not N separate round-trips
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
                                        # FIX [Critical #1]: Capture r['id'] now, not at call time
                                        rid = r['id']
                                        safe_db_write(
                                            lambda rid=rid, a_rep=a_rep: conn.table("founder_interaction")
                                                .update({"reply_content": a_rep, "is_read": True})
                                                .eq("id", rid).execute(),
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
        # --- Employee message feed ---
        st.markdown(f"#### 📥 Message Feed for {att_user}")
        # FIX [Critical #3]: Use cached helper instead of raw query on every rerun
        emp_msgs = get_today_founder_messages(att_user, today)

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
                                    # FIX [Critical #1]: Capture loop variable by default arg
                                    mid = m['id']
                                    safe_db_write(
                                        lambda mid=mid, r_text=r_text: conn.table("founder_interaction").update({
                                            "is_read": True,
                                            "reply_content": r_text or "Acknowledged",
                                            "replied_at": get_now_ist().isoformat()
                                        }).eq("id", mid).execute(),
                                        error_prefix="Reply Error"
                                    )
                                    st.cache_data.clear()
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
                        st.cache_data.clear()
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
                    # FIX [Critical #1]: Capture p['id'] at definition time, not call time
                    pid = p['id']
                    if bc.button("✅ Done", key=f"p_done_{pid}"):
                        safe_db_write(
                            lambda pid=pid: conn.table("work_plans").update({"status": "Completed"})
                                .eq("id", pid).execute(),
                            error_prefix="Plan Update Error"
                        )
                        st.rerun()
                else:
                    tc.success(f"✔️ ~~**[{p['job_no']}]** {p['planned_task']}~~")
        else:
            st.caption("No pending plans noted.")

    st.divider()

    # --- Core Data & Metrics ---
    # FIX [Critical #3]: Use cached helper — no raw query on every rerun
    emp_summ_res = get_today_attendance(att_user, today)
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
            # Seed session state from DB on first load — this handles page refreshes and
            # re-logins: if the employee already confirmed today, system_promise is True in DB.
            if "promise_confirmed" not in st.session_state:
                st.session_state["promise_confirmed"] = bool(log_data.get('system_promise', False))

            if not st.session_state["promise_confirmed"]:
                with st.container(border=True):
                    st.markdown(
                        '<div style="background-color:#f8f9fb; padding:10px; border-left: 5px solid #007bff;">'
                        '<b>"I am dedicated to B&G\'s systems. Following the system today is my path to precision."</b>'
                        '</div>',
                        unsafe_allow_html=True
                    )
                    if st.checkbox("🛡️ I acknowledge and commit to the above statement.", key="temp_promise_check"):
                        # FIX: Write to DB immediately — do NOT wait until punch-out.
                        # Previously, system_promise was only saved at punch-out, so the checkbox
                        # would reappear on every rerun until end of day. Now it's persisted
                        # instantly, so seeding from DB on next load will correctly skip the prompt.
                        ok = safe_db_write(
                            lambda: conn.table("attendance_logs")
                                .update({"system_promise": True})
                                .eq("id", log_data['id']).execute(),
                            error_prefix="Promise Save Error"
                        )
                        if ok:
                            st.session_state["promise_confirmed"] = True
                            st.cache_data.clear()  # flush so next load reads updated system_promise
                            st.rerun()
            else:
                st.success("🙏 Thank you for your commitment to B&G systems!")

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
                    st.cache_data.clear()
                    st.rerun()
            else:
                if not log_data.get('punch_out'):
                    # ── Live short-shift calculation ──────────────────────
                    REQUIRED_MINS = 510  # 8h 30m
                    punch_in_live = pd.to_datetime(log_data.get('punch_in')).tz_convert(IST) \
                        if log_data.get('punch_in') else None
                    elapsed_mins  = int((get_now_ist() - punch_in_live).total_seconds() // 60) \
                        if punch_in_live else 0
                    short_shift = elapsed_mins < REQUIRED_MINS

                    if short_shift and punch_in_live:
                        still_needed = REQUIRED_MINS - elapsed_mins
                        st.warning(
                            f"⏳ Only **{elapsed_mins // 60}h {elapsed_mins % 60}m** logged. "
                            f"Full shift needs **8h 30m** — {still_needed // 60}h {still_needed % 60}m remaining."
                        )

                    st.markdown("**Productivity Rating**")
                    work_sat = st.feedback("stars", key="prod_stars_fb")

                    # FIX: Persist checkbox acknowledgement in session_state so it
                    # survives the rerun that happens when the checkbox is ticked.
                    # Previously the checkbox reset to False on every rerun, making
                    # the button permanently disabled for short shifts.
                    if short_shift:
                        if not st.session_state.get("short_shift_ack"):
                            st.checkbox(
                                "⚠️ I understand I am punching out before completing the required 8h 30m shift.",
                                key="short_shift_ack"
                            )
                        else:
                            st.checkbox(
                                "⚠️ I understand I am punching out before completing the required 8h 30m shift.",
                                key="short_shift_ack",
                                value=True
                            )
                        allow_punchout = bool(st.session_state.get("short_shift_ack", False))
                    else:
                        allow_punchout = True

                    # FIX: Capture all closure variables explicitly to avoid
                    # stale reference bugs in the lambda
                    rec_id     = log_data['id']
                    is_short   = short_shift

                    if st.button("🏁 PUNCH OUT", use_container_width=True, type="primary",
                                 disabled=not allow_punchout):
                        safe_work_sat = work_sat if work_sat is not None else 0
                        safe_db_write(
                            lambda rid=rec_id, ss=is_short, ws=safe_work_sat:
                                conn.table("attendance_logs").update({
                                    "punch_out": get_now_ist().isoformat(),
                                    "work_satisfaction": ws,
                                    "short_shift": ss,
                                }).eq("id", rid).execute(),
                            error_prefix="Punch Out Error"
                        )
                        # Clear short shift ack so it doesn't bleed into next session
                        st.session_state.pop("short_shift_ack", None)
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.success("Shift Completed")

        with cb:
            st.markdown("### 🚶 Movement")
            now_str = get_now_ist().strftime("%Y-%m-%d")
            # FIX [Critical #3]: Use cached movement helper
            active_move = get_active_movement(att_user, now_str)

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
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("Enter Destination")
            else:
                current = active_move[0]
                st.warning(f"📍 Currently at {current['destination']}")
                # FIX [Critical #1]: Capture current['id'] at definition time
                move_id = current['id']
                if st.button("📥 LOG TIME IN", use_container_width=True, type="primary", key="btn_move_in"):
                    safe_db_write(
                        lambda move_id=move_id: conn.table("movement_logs").update({
                            "return_time": get_now_ist().isoformat()
                        }).eq("id", move_id).execute(),
                        error_prefix="Movement Return Error"
                    )
                    st.cache_data.clear()
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

    # ── TODAY'S SHIFT SUMMARY ──────────────────────────────────
    st.divider()
    st.markdown("### 📊 Today's Summary")

    if emp_summ_res:
        rec = emp_summ_res[0]
        punch_in_dt  = pd.to_datetime(rec.get('punch_in')).tz_convert(IST)  if rec.get('punch_in')  else None
        punch_out_dt = pd.to_datetime(rec.get('punch_out')).tz_convert(IST) if rec.get('punch_out') else None

        punch_in_str  = punch_in_dt.strftime("%I:%M %p")  if punch_in_dt  else "—"
        punch_out_str = punch_out_dt.strftime("%I:%M %p") if punch_out_dt else "Still In"

        if punch_in_dt and punch_out_dt:
            duration_mins = int((punch_out_dt - punch_in_dt).total_seconds() // 60)
            duration_str  = f"{duration_mins // 60}h {duration_mins % 60}m"
            is_short      = duration_mins < 510  # under 8h 30m
            shift_status  = "⚠️ Short Shift" if is_short else "✅ Completed"
        elif punch_in_dt:
            duration_mins = int((get_now_ist() - punch_in_dt).total_seconds() // 60)
            duration_str  = f"{duration_mins // 60}h {duration_mins % 60}m (live)"
            is_short      = False
            shift_status  = "🟢 Active"
        else:
            duration_str = "—"
            is_short     = False
            shift_status = "⚪ Not started"

        is_late = punch_in_dt.time() > LATE_THRESHOLD if punch_in_dt else False

        st.markdown("#### 🏢 Shift")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Punch In",  punch_in_str + (" 🔴 Late" if is_late else ""))
        s2.metric("Punch Out", punch_out_str)
        s3.metric("Duration",  duration_str)
        s4.metric("Status",    shift_status)

        if is_short and punch_out_dt:
            shortfall = 510 - duration_mins
            st.error(
                f"🔴 **Short shift recorded.** Today's shift was "
                f"**{duration_mins // 60}h {duration_mins % 60}m** — "
                f"{shortfall // 60}h {shortfall % 60}m below the required 8h 30m. "
                f"This will be visible to HR."
            )
    else:
        st.info("No punch-in recorded yet today.")

    st.divider()

    # ── TODAY'S WORK LOG SUMMARY ─────────────────────────────
    st.markdown("#### 📝 Work Log Summary")
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
            st.metric("Logs Today",   len(df_wlog))
            st.metric("Hours Logged", f"{total_hours:.1f}h")
    else:
        st.info("No work logs posted today.")

    st.divider()

    # ── TODAY'S MOVEMENT SUMMARY ─────────────────────────────
    st.markdown("#### 🚶 Movement Summary")
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
            exit_dt   = pd.to_datetime(mv['exit_time']).tz_convert(IST)   if mv.get('exit_time')   else None
            return_dt = pd.to_datetime(mv['return_time']).tz_convert(IST) if mv.get('return_time') else None
            exit_str   = exit_dt.strftime("%I:%M %p")   if exit_dt   else "—"
            return_str = return_dt.strftime("%I:%M %p") if return_dt else "Still Out"
            if exit_dt and return_dt:
                dur_m = int((return_dt - exit_dt).total_seconds() // 60)
                total_out_mins += dur_m
                dur_str, badge_color = f"{dur_m}m", "#28a745"
            else:
                dur_str, badge_color = "ongoing", "#ffc107"
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
# TAB 1: STAFF DATA HISTORY
# ============================================================
with tabs[1]:
    require_auth()
    att_user = st.session_state["authenticated_user"]
    today = str(date.today())

    st.subheader(f"📊 Personal History: {att_user}")
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
                    rid = r['id']
                    if r['status'] == 'Pending' and col_c.button("Withdraw", key=f"wd_{rid}"):
                        safe_db_write(
                            lambda rid=rid: conn.table("leave_requests").delete().eq("id", rid).execute(),
                            error_prefix="Withdraw Error"
                        )
                        st.cache_data.clear()
                        st.rerun()
                    # Show admin remarks if present
                    if r.get('admin_remarks') and str(r['admin_remarks']).strip():
                        st.caption(f"💬 HR Remarks: {r['admin_remarks']}")

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
    # FIX [Critical #2]: Gate Tab 4 with the same session-based auth used everywhere else.
    # Admins who authenticated via Tab 0 get in automatically.
    # No redundant password input; no inconsistent auth systems.
    require_auth()
    if not st.session_state.get("admin_authenticated"):
        st.error("🔒 This panel is restricted to Admin users only.")
        st.stop()

    # FIX [Improvement]: Remove st.secrets fallback — fail loudly if secret is missing in prod
    # To use: add admin_password = "your_password" to .streamlit/secrets.toml
    # The admin panel no longer needs a second password since session auth is trusted.

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

    admin_tabs = st.tabs(["📈 Performance", "📜 Leave", "🕒 Logs", "📬 Approvals", "🚨 Missed P/O", "🔐 Keys"])

    # --- Performance ---
    with admin_tabs[0]:
        st.subheader(f"📊 Performance Overview — {sr} to {er}")
        t_att, t_work, t_plan = get_admin_performance_data(sr, er)

        if not t_att:
            st.info("No attendance data found for this period.")
        else:
            df_att  = pd.DataFrame(t_att)
            df_work = pd.DataFrame(t_work) if t_work else pd.DataFrame(
                columns=['employee_name', 'hours_spent', 'task_description', 'work_date', 'created_at'])
            df_plan = pd.DataFrame(t_plan) if t_plan else pd.DataFrame(
                columns=['employee_name', 'status', 'planned_hours', 'planned_task', 'job_no', 'plan_date'])

            # ── Common date/time derivations ──────────────────────
            df_att['punch_dt']     = pd.to_datetime(df_att['punch_in'],  errors='coerce').dt.tz_convert(IST)
            df_att['punch_out_dt'] = pd.to_datetime(df_att['punch_out'], errors='coerce').dt.tz_convert(IST)
            df_att['p_in_t']       = df_att['punch_dt'].dt.time
            df_att['shift_mins']   = (
                (df_att['punch_out_dt'] - df_att['punch_dt']).dt.total_seconds() // 60
            ).where(df_att['punch_out_dt'].notna())

            # Extract job code from task_description — stored as "[JOB] @slot: details"
            if not df_work.empty and 'task_description' in df_work.columns:
                df_work['job_code'] = df_work['task_description'].str.extract(r'^\[([^\]]+)\]')
                df_work['log_time'] = pd.to_datetime(
                    df_work['created_at'], errors='coerce').dt.tz_convert(IST)

            # ── Scope to selected employee ─────────────────────────
            staff_scope = get_staff_list() if s_name == "All Staff" else [s_name]
            df_att_f  = df_att[df_att['employee_name'].isin(staff_scope)]
            df_work_f = df_work[df_work['employee_name'].isin(staff_scope)] if not df_work.empty else df_work
            df_plan_f = df_plan[df_plan['employee_name'].isin(staff_scope)] if not df_plan.empty else df_plan

            # ── Core KPIs ─────────────────────────────────────────
            total_days   = len(df_att_f)
            late_days    = int((df_att_f['p_in_t'] > LATE_THRESHOLD).sum())
            short_days   = int((df_att_f['shift_mins'] < 510).sum())
            missed_days  = int(df_att_f['punch_out_dt'].isna().sum())
            avg_shift_h  = df_att_f['shift_mins'].dropna().mean() / 60 if total_days else 0
            total_shift_h = df_att_f['shift_mins'].dropna().sum() / 60

            # Plan KPIs
            total_planned    = len(df_plan_f)
            done_tasks       = int((df_plan_f['status'] == 'Completed').sum()) if not df_plan_f.empty else 0
            pending_tasks    = total_planned - done_tasks
            planned_hrs_tot  = df_plan_f['planned_hours'].sum() if not df_plan_f.empty else 0
            planned_hrs_done = df_plan_f[df_plan_f['status'] == 'Completed']['planned_hours'].sum() \
                               if not df_plan_f.empty else 0
            task_efficiency  = (done_tasks / total_planned * 100) if total_planned else 0

            # Work log KPIs
            total_logs      = len(df_work_f)
            logged_hrs_tot  = df_work_f['hours_spent'].sum() if not df_work_f.empty else 0
            avg_logs_per_day = (total_logs / total_days) if total_days else 0

            avg_sat = df_att_f['work_satisfaction'].dropna().mean() \
                if 'work_satisfaction' in df_att_f.columns else 0

            # ── Grade (single employee only) ───────────────────────
            if s_name != "All Staff":
                if task_efficiency >= 90 and late_days == 0 and short_days == 0 and missed_days == 0:
                    grade, gcolor, gnote = "A+", "#28a745", "Excellent Performance"
                elif task_efficiency >= 75 and late_days <= 2 and short_days <= 1 and missed_days == 0:
                    grade, gcolor, gnote = "A",  "#17a2b8", "Strong Contributor"
                elif task_efficiency >= 60:
                    grade, gcolor, gnote = "B",  "#ffc107", "Meeting Expectations"
                else:
                    grade, gcolor, gnote = "C",  "#dc3545", "Review Required"
                st.markdown(
                    f'<div style="background-color:{gcolor}; padding:16px 24px; border-radius:12px; '
                    f'text-align:center; color:white; margin-bottom:16px;">'
                    f'<h1 style="margin:0; font-size:2rem;">Grade: {grade}</h1>'
                    f'<p style="margin:4px 0 0; font-weight:500;">{gnote}</p></div>',
                    unsafe_allow_html=True
                )

            # ══════════════════════════════════════════════════════
            # SECTION 1 — ATTENDANCE
            # ══════════════════════════════════════════════════════
            st.markdown("#### 🏢 Attendance")
            a1, a2, a3, a4, a5, a6 = st.columns(6)
            a1.metric("Days Present",     total_days)
            a2.metric("Late Arrivals",    late_days,   delta_color="inverse")
            a3.metric("Short Shifts",     short_days,  delta_color="inverse",
                      help="Shifts under 8h 30m")
            a4.metric("Missed Punch-Out", missed_days, delta_color="inverse")
            a5.metric("Avg Shift",        f"{avg_shift_h:.1f}h")
            a6.metric("Total Hours In",   f"{total_shift_h:.1f}h")

            if s_name != "All Staff" and short_days > 0:
                short_rows = df_att_f[df_att_f['shift_mins'] < 510][['work_date', 'shift_mins']].copy()
                short_rows['Duration'] = short_rows['shift_mins'].apply(
                    lambda m: f"{int(m)//60}h {int(m)%60}m" if pd.notna(m) else "No punch-out")
                short_rows['Shortfall'] = short_rows['shift_mins'].apply(
                    lambda m: f"−{int(510-m)//60}h {int(510-m)%60}m" if pd.notna(m) else "—")
                short_rows = short_rows.rename(columns={"work_date": "Date"}).drop(columns="shift_mins")
                with st.expander("🔴 Short shift breakdown"):
                    st.dataframe(short_rows, use_container_width=True, hide_index=True)

            st.divider()

            # ══════════════════════════════════════════════════════
            # SECTION 2 — PLANNED vs ACTUAL (the Monday review core)
            # ══════════════════════════════════════════════════════
            st.markdown("#### 📋 Planned vs Actual — Task Execution")

            p1c, p2c, p3c, p4c, p5c, p6c = st.columns(6)
            p1c.metric("Tasks Planned",   total_planned)
            p2c.metric("Tasks Completed", done_tasks,
                       delta=f"{task_efficiency:.0f}%",
                       delta_color="normal" if task_efficiency >= 75 else "inverse")
            p3c.metric("Still Pending",   pending_tasks,  delta_color="inverse")
            p4c.metric("Planned Hrs (all)",  f"{planned_hrs_tot:.1f}h",
                       help="Sum of estimated hours across all planned tasks")
            p5c.metric("Planned Hrs (done)", f"{planned_hrs_done:.1f}h",
                       help="Estimated hours for completed tasks only")
            p6c.metric("Completion Rate",    f"{task_efficiency:.1f}%")

            # ── Per-employee planned vs actual table (All Staff view) ──
            if s_name == "All Staff" and not df_plan_f.empty:
                st.markdown("##### Staff-wise breakdown")
                grp = df_plan_f.groupby('employee_name').apply(lambda g: pd.Series({
                    'Planned Tasks':   len(g),
                    'Completed':       int((g['status'] == 'Completed').sum()),
                    'Pending':         int((g['status'] == 'Pending').sum()),
                    'Planned Hrs':     round(g['planned_hours'].sum(), 1),
                    'Done Hrs (est)':  round(g[g['status'] == 'Completed']['planned_hours'].sum(), 1),
                })).reset_index().rename(columns={'employee_name': 'Employee'})
                grp['Completion %'] = (grp['Completed'] / grp['Planned Tasks'] * 100).round(1)
                grp['Status'] = grp['Completion %'].apply(
                    lambda v: '🟢 On Track' if v >= 90 else '🟡 Partial' if v >= 60 else '🔴 Low')
                grp['Completion %'] = grp['Completion %'].astype(str) + '%'

                st.dataframe(grp, use_container_width=True, hide_index=True)

            # ── Day-wise plan detail (single employee) ──
            if s_name != "All Staff" and not df_plan_f.empty:
                with st.expander("📅 Day-wise task detail"):
                    day_plan = df_plan_f[['plan_date','job_no','planned_task',
                                          'planned_hours','status']].copy()
                    day_plan = day_plan.rename(columns={
                        'plan_date': 'Date', 'job_no': 'Job',
                        'planned_task': 'Task', 'planned_hours': 'Est Hrs', 'status': 'Status'
                    }).sort_values('Date', ascending=False)
                    st.dataframe(day_plan, use_container_width=True, hide_index=True)

            st.divider()

            # ══════════════════════════════════════════════════════
            # SECTION 3 — WORK LOGS & PRODUCTIVITY
            # ══════════════════════════════════════════════════════
            st.markdown("#### 📝 Work Logs & Productivity")

            w1, w2, w3, w4, w5 = st.columns(5)
            w1.metric("Total Logs Posted", total_logs)
            w2.metric("Logged Hours",      f"{logged_hrs_tot:.1f}h",
                      help="Sum of hours_spent across all work log entries")
            w3.metric("Avg Logs / Day",    f"{avg_logs_per_day:.1f}",
                      help="Work log entries per working day — target: ≥6 per day")
            w4.metric("Hours In Office",   f"{total_shift_h:.1f}h",
                      help="Total shift hours (punch-in to punch-out)")
            w5.metric("Self-Rating",       f"{avg_sat:.1f} ⭐" if avg_sat else "No data",
                      help="Average self-reported productivity star rating at punch-out")

            # ── Job-code time split (how they actually spent time) ──
            if not df_work_f.empty and 'job_code' in df_work_f.columns:
                st.markdown("##### ⏱️ Time by Job Code")
                job_grp = df_work_f.groupby('job_code')['hours_spent'].sum().reset_index()
                job_grp.columns = ['Job Code', 'Hours']
                job_grp = job_grp.sort_values('Hours', ascending=False)
                job_grp['% of Logged Time'] = (
                    job_grp['Hours'] / job_grp['Hours'].sum() * 100
                ).round(1).astype(str) + '%'
                job_grp['Hours'] = job_grp['Hours'].round(2)

                # Compute productive/overhead totals directly from raw job_code — not from Type col
                productive_hrs = df_work_f[
                    ~df_work_f['job_code'].str.upper().isin(OVERHEAD_CODES)
                ]['hours_spent'].sum() if not df_work_f.empty else 0
                overhead_hrs   = df_work_f[
                    df_work_f['job_code'].str.upper().isin(OVERHEAD_CODES)
                ]['hours_spent'].sum() if not df_work_f.empty else 0
                productive_pct = (productive_hrs / logged_hrs_tot * 100) if logged_hrs_tot else 0

                pt1, pt2, pt3 = st.columns(3)
                pt1.metric("Project Work Hrs",   f"{productive_hrs:.1f}h",
                           help="Hours logged against actual project job codes")
                pt2.metric("Overhead Hrs",        f"{overhead_hrs:.1f}h",
                           help="Hours on GENERAL, ACCOUNTS, PURCHASE etc.")
                pt3.metric("Productivity Index",  f"{productive_pct:.1f}%",
                           delta="target ≥ 60%",
                           delta_color="normal" if productive_pct >= 60 else "inverse")

                job_grp['Type'] = job_grp['Job Code'].apply(
                    lambda c: '🟢 Project Work' if str(c).upper() not in OVERHEAD_CODES else '🟡 Overhead'
                )

                st.dataframe(job_grp, use_container_width=True, hide_index=True)

            # ── Day-wise log count heatmap (single employee) ──
            if s_name != "All Staff" and not df_work_f.empty:
                with st.expander("📅 Day-wise log count"):
                    day_logs = df_work_f.groupby('work_date').agg(
                        Logs=('id', 'count'),
                        Hours=('hours_spent', 'sum')
                    ).reset_index().rename(columns={'work_date': 'Date'})
                    day_logs['Hours'] = day_logs['Hours'].round(1)
                    day_logs['Logs OK?'] = day_logs['Logs'].apply(
                        lambda n: '✅' if n >= 6 else '⚠️' if n >= 3 else '🔴')
                    day_logs = day_logs.sort_values('Date', ascending=False)
                    st.dataframe(day_logs, use_container_width=True, hide_index=True)

            # ── All-staff log frequency table (All Staff view) ──
            if s_name == "All Staff" and not df_work_f.empty:
                st.markdown("##### Staff-wise log activity")
                log_grp = df_work_f.groupby('employee_name').agg(
                    Total_Logs=('id', 'count'),
                    Logged_Hrs=('hours_spent', 'sum'),
                ).reset_index().rename(columns={
                    'employee_name': 'Employee',
                    'Total_Logs': 'Total Logs',
                    'Logged_Hrs': 'Logged Hrs'
                })
                # Merge with attendance day count
                att_days = df_att_f.groupby('employee_name').size().reset_index(
                    name='Days').rename(columns={'employee_name': 'Employee'})
                log_grp = log_grp.merge(att_days, on='Employee', how='left')
                log_grp['Avg Logs/Day'] = (log_grp['Total Logs'] / log_grp['Days']).round(1)
                log_grp['Logged Hrs']   = log_grp['Logged Hrs'].round(1)
                log_grp['Activity']     = log_grp['Avg Logs/Day'].apply(
                    lambda v: '✅ Active' if v >= 6 else '⚠️ Low' if v >= 3 else '🔴 Poor')
                st.dataframe(log_grp, use_container_width=True, hide_index=True)

            st.divider()

            # ══════════════════════════════════════════════════════
            # SECTION 4 — MONDAY REVIEW EXPORT
            # ══════════════════════════════════════════════════════
            st.markdown("#### 📤 Monday Review Export")
            st.caption("One-click export of the full review sheet for the selected period.")

            # Build a consolidated summary per employee
            all_staff_names = df_att_f['employee_name'].unique()
            review_rows = []
            for emp in all_staff_names:
                ea = df_att_f[df_att_f['employee_name'] == emp]
                ew = df_work_f[df_work_f['employee_name'] == emp] if not df_work_f.empty else pd.DataFrame()
                ep = df_plan_f[df_plan_f['employee_name'] == emp] if not df_plan_f.empty else pd.DataFrame()

                e_shift_h   = ea['shift_mins'].dropna().sum() / 60
                e_logs      = len(ew)
                e_logged_h  = ew['hours_spent'].sum() if not ew.empty else 0
                e_planned   = len(ep)
                e_done      = int((ep['status'] == 'Completed').sum()) if not ep.empty else 0
                e_planned_h = ep['planned_hours'].sum() if not ep.empty else 0
                e_done_h    = ep[ep['status'] == 'Completed']['planned_hours'].sum() \
                              if not ep.empty else 0
                e_eff       = round(e_done / e_planned * 100, 1) if e_planned else 0
                e_late      = int((ea['p_in_t'] > LATE_THRESHOLD).sum())
                e_short     = int((ea['shift_mins'] < 510).sum())
                e_missed    = int(ea['punch_out_dt'].isna().sum())
                e_sat       = round(ea['work_satisfaction'].dropna().mean(), 1) \
                              if 'work_satisfaction' in ea.columns else 0

                # Productivity index
                if not ew.empty and 'job_code' in ew.columns:
                    proj_h = ew[~ew['job_code'].str.upper().isin(OVERHEAD_CODES)]['hours_spent'].sum()
                    e_prod_idx = round(proj_h / e_logged_h * 100, 1) if e_logged_h else 0
                else:
                    e_prod_idx = 0

                review_rows.append({
                    'Employee':          emp,
                    'Days Present':      len(ea),
                    'Total Shift Hrs':   round(e_shift_h, 1),
                    'Late Arrivals':     e_late,
                    'Short Shifts':      e_short,
                    'Missed Punch-Out':  e_missed,
                    'Tasks Planned':     e_planned,
                    'Tasks Done':        e_done,
                    'Pending Tasks':     e_planned - e_done,
                    'Planned Hrs (all)': round(e_planned_h, 1),
                    'Planned Hrs (done)':round(e_done_h, 1),
                    'Completion %':      e_eff,
                    'Work Logs':         e_logs,
                    'Logged Hrs':        round(e_logged_h, 1),
                    'Avg Logs/Day':      round(e_logs / len(ea), 1) if len(ea) else 0,
                    'Productivity Index':e_prod_idx,
                    'Self-Rating ⭐':    e_sat,
                })

            df_review = pd.DataFrame(review_rows)
            st.dataframe(df_review, use_container_width=True, hide_index=True)
            st.download_button(
                label="📥 Download Monday Review Sheet (CSV)",
                data=convert_df(df_review),
                file_name=f"BG_Monday_Review_{sr}_to_{er}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True
            )

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

            # ── Pending requests ───────────────────────────────
            to_decide = pend[pend['status'] == 'Pending']
            if not to_decide.empty:
                st.markdown(f"#### 📬 Pending Requests ({len(to_decide)})")
                for _, row in to_decide.iterrows():
                    rid = row['id']
                    with st.container(border=True):
                        # Row 1 — employee info
                        i1, i2, i3 = st.columns([2, 3, 3])
                        i1.markdown(f"**{row['employee_name']}**")
                        i2.markdown(f"📅 {row['start_date']} → {row['end_date']}")
                        days = (pd.to_datetime(row['end_date']) -
                                pd.to_datetime(row['start_date'])).days + 1
                        i3.caption(f"{days} day(s) · {row.get('leave_type','Casual Leave')}")

                        if row.get('reason'):
                            st.caption(f"Reason: {row['reason']}")

                        # Row 2 — remarks input + action buttons
                        # Remarks stored in session state keyed by rid so they
                        # survive the rerun triggered by button click
                        remarks_key = f"remarks_{rid}"
                        st.text_input(
                            "Admin remarks (optional)",
                            key=remarks_key,
                            placeholder="Add a note — visible to employee on their leave tab"
                        )

                        b1, b2, b3 = st.columns([2, 2, 4])
                        if b1.button("✅ Approve", key=f"ap_{rid}", type="primary"):
                            remarks = st.session_state.get(remarks_key, "")
                            safe_db_write(
                                lambda rid=rid, rm=remarks: conn.table("leave_requests")
                                    .update({"status": "Approved", "admin_remarks": rm})
                                    .eq("id", rid).execute(),
                                success_msg="✅ Approved.",
                                error_prefix="Approve Error"
                            )
                            st.cache_data.clear()
                            st.rerun()

                        if b2.button("❌ Reject", key=f"rj_{rid}"):
                            remarks = st.session_state.get(remarks_key, "")
                            if not remarks.strip():
                                b3.warning("Please add a remark before rejecting.")
                            else:
                                safe_db_write(
                                    lambda rid=rid, rm=remarks: conn.table("leave_requests")
                                        .update({"status": "Rejected", "admin_remarks": rm})
                                        .eq("id", rid).execute(),
                                    success_msg="❌ Rejected.",
                                    error_prefix="Reject Error"
                                )
                                st.cache_data.clear()
                                st.rerun()
            else:
                st.success("✅ No pending approvals.")

            # ── Decision history ────────────────────────────────
            decided = pend[pend['status'].isin(['Approved', 'Rejected'])].copy()
            if not decided.empty:
                st.divider()
                st.markdown("#### 📋 Decision History")
                decided['Days'] = (
                    pd.to_datetime(decided['end_date']) -
                    pd.to_datetime(decided['start_date'])
                ).dt.days + 1
                decided['Status'] = decided['status'].apply(
                    lambda s: '✅ Approved' if s == 'Approved' else '❌ Rejected'
                )
                display_cols = ['employee_name', 'start_date', 'end_date',
                                'Days', 'reason', 'Status', 'admin_remarks']
                # Only show columns that exist
                display_cols = [c for c in display_cols if c in decided.columns]
                st.dataframe(
                    decided[display_cols].rename(columns={
                        'employee_name': 'Employee',
                        'start_date': 'From',
                        'end_date': 'To',
                        'reason': 'Reason',
                        'admin_remarks': 'Admin Remarks'
                    }).sort_values('From', ascending=False),
                    use_container_width=True, hide_index=True
                )
        else:
            st.info("No leave requests found.")

    # --- Missed Punch-Outs ---
    with admin_tabs[4]:
        st.subheader("🚨 Missed Punch-Outs")
        all_missed = get_all_missed_punchouts(str(date.today()))

        if all_missed:
            st.error(f"**{len(all_missed)} open shift(s)** with no punch-out recorded across all staff.")
            st.caption("Use the correction tool below to set the punch-out time for any affected record.")

            for m in all_missed:
                punch_in_ist = pd.to_datetime(m['punch_in']).tz_convert(IST) if m.get('punch_in') else None
                punch_in_str = punch_in_ist.strftime('%d %b %Y, %I:%M %p') if punch_in_ist else "—"

                with st.container(border=True):
                    mc1, mc2, mc3 = st.columns([2, 3, 3])
                    mc1.markdown(f"**{m['employee_name']}**")
                    mc2.markdown(f"📅 `{m['work_date']}` &nbsp; Punched in: **{punch_in_str}**")

                    # Manual punch-out correction form
                    mid = m['id']
                    with mc3:
                        with st.form(key=f"fix_po_{mid}"):
                            fix_time = st.time_input(
                                "Set punch-out time",
                                value=time(18, 30),
                                key=f"fix_t_{mid}"
                            )
                            if st.form_submit_button("🔧 Apply Correction"):
                                # Combine the work_date with the corrected time in IST
                                corrected_dt = IST.localize(
                                    datetime.combine(
                                        date.fromisoformat(m['work_date']), fix_time
                                    )
                                )
                                safe_db_write(
                                    lambda mid=mid, corrected_dt=corrected_dt: conn.table("attendance_logs")
                                        .update({
                                            "punch_out": corrected_dt.isoformat(),
                                            "short_shift": (corrected_dt - punch_in_ist).total_seconds() < 30600
                                        })
                                        .eq("id", mid).execute(),
                                    success_msg="✅ Punch-out corrected.",
                                    error_prefix="Correction Error"
                                )
                                st.cache_data.clear()
                                st.rerun()
        else:
            st.success("✅ No missed punch-outs — all shifts are properly closed.")

    # --- Access Keys ---
    with admin_tabs[5]:
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
