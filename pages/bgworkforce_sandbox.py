import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz

# --- 1. SETUP & CONSTANTS ---
IST = pytz.timezone('Asia/Kolkata')
# 9:00 AM start + 5 minute grace period
LATE_THRESHOLD = time(9, 5) 
# 24-hour cycle for production flexibility
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
    
    # 1. THE IDENTITY SELECTOR
    selected_user = st.selectbox("Identify Yourself", get_staff_list(), key="user_select_main")
    
    # 2. THE SECURITY GATE
    if "authenticated_user" not in st.session_state:
        st.session_state["authenticated_user"] = None

    if st.session_state["authenticated_user"] != selected_user:
        st.info(f"🔐 Please verify access for {selected_user}")
        input_pw = st.text_input("Enter your Access Key", type="password", key=f"pw_gate_{selected_user}")
        
        if st.button("Unlock My Dashboard", use_container_width=True):
            auth_res = conn.table("employee_auth").select("access_key").eq("employee_name", selected_user).execute().data
            if auth_res and input_pw == auth_res[0]['access_key']:
                st.session_state["authenticated_user"] = selected_user
                if selected_user == "Admin":
                    st.session_state["admin_authenticated"] = True
                st.success("Access Granted!"); st.rerun()
            else:
                st.error("Invalid Access Key. Please check with B&G Admin.")
        st.stop()

    att_user = st.session_state["authenticated_user"]
    today = str(date.today())
    
    if st.button("🔓 Logout / Switch User"):
        st.session_state["authenticated_user"] = None
        st.session_state["admin_authenticated"] = False
        st.rerun()

    st.divider()

    # --- 3. FOUNDER'S DESK (Preserving ALL Interaction Logic) ---
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
                                payload = [{"sender_name": "Founder", "content": m_text, "target_user": s, "is_read": False} for s in targets]
                                conn.table("founder_interaction").insert(payload).execute()
                            else:
                                conn.table("founder_interaction").insert({"sender_name": "Founder", "content": m_text, "target_user": m_target, "is_read": False}).execute()
                            st.success("Sent!"); st.rerun()
                        except Exception as e: st.error(f"Post Error: {e}")

        # TABBED VIEW FOR ADMIN (Fixed Scrolling)
        t_active, t_history = st.tabs(["💬 Today's Interactions", "📜 Search History"])
        with t_active:
            st.markdown('<div style="height:250px; overflow-y:auto; border:1px solid #e6e9ef; border-radius:10px; padding:15px; background-color:#ffffff; margin-bottom:10px;">', unsafe_allow_html=True)
            today_msgs = conn.table("founder_interaction").select("*").gte("created_at", f"{today}T00:00:00").order("created_at", desc=True).execute().data
            if today_msgs:
                for r in today_msgs:
                    # Convert the database UTC time to IST for the display
                    msg_ist = pd.to_datetime(r['created_at']).tz_convert(IST).strftime("%I:%M %p")
                    st.caption(f"**{r['sender_name']}** to **{r['target_user']}** | {msg_ist}")
                    st.write(r['content'])
                    if r.get('reply_content'): st.info(f"Reply: {r['reply_content']}")
                    st.divider()
            else: st.write("No interactions yet today.")
            st.markdown('</div>', unsafe_allow_html=True)
        with t_history:
            search_staff = st.selectbox("Filter History by Staff Name", ["-- Select --"] + get_staff_list())
            if search_staff != "-- Select --":
                h_data = conn.table("founder_interaction").select("*").or_(f"target_user.eq.{search_staff},sender_name.eq.{search_staff}").order("created_at", desc=True).limit(20).execute().data
                if h_data:
                    for h in h_data:
                        with st.expander(f"📅 {h['created_at'][:10]} | {h['sender_name']}"):
                            st.write(h['content'])
                            st.caption(f"Reply: {h.get('reply_content', 'Pending')}")
    else:
        # EMPLOYEE VIEW: Interactive Reply Logic
        msg_res = conn.table("founder_interaction").select("*").or_(f"target_user.eq.{att_user},sender_name.eq.{att_user}").order("created_at", desc=True).limit(1).execute().data
        if msg_res:
            m = msg_res[0]
            with st.container(border=True):
                if m['sender_name'] == att_user:
                    st.write(f"📤 **My Message:** {m['content']}")
                    if m.get('reply_content'): st.info(f"🏁 **Founder:** {m['reply_content']}")
                else:
                    st.info(f"**From Founder:** {m['content']}")
                    if not m.get('is_read'):
                        c_rep, c_btn = st.columns([3, 1])
                        rep = c_rep.text_input("Acknowledge/Reply", key=f"rep_{m['id']}")
                        if c_btn.button("✔️ Send", key=f"btn_{m['id']}"):
                            conn.table("founder_interaction").update({"is_read": True, "reply_content": rep or "Acknowledged", "replied_at": datetime.now(IST).isoformat()}).eq("id", m['id']).execute(); st.rerun()

    st.divider()

    # --- 4. MY WORK PLAN (Pending Tasks Carry-over) ---
    st.markdown("### 🏗️ My Work Plan & Pending Tasks")
    p1, p2 = st.columns([1.5, 2.5])
    with p1:
        with st.form("plan_form", clear_on_submit=True):
            p_job = st.selectbox("Job No", get_job_codes(), key="p_job_main")
            p_task = st.text_input("Task/Work")
            p_hrs = st.number_input("Est. Hrs", 0.5, 12.0, 1.0, 0.5)
            if st.form_submit_button("📌 Add to Plan"):
                if p_task:
                    conn.table("work_plans").insert({"employee_name": att_user, "job_no": p_job, "planned_task": p_task, "planned_hours": p_hrs, "plan_date": today, "status": "Pending"}).execute(); st.rerun()
    with p2:
        my_plans = conn.table("work_plans").select("*").eq("employee_name", att_user).or_(f"plan_date.eq.{today},status.eq.Pending").order("plan_date").execute().data
        if my_plans:
            for p in my_plans:
                tc, bc = st.columns([4, 1.2])
                if p['status'] == 'Pending':
                    tc.info(f"📍 **[{p['job_no']}]** {p['planned_task']} ({p['planned_hours']}h)")
                    if bc.button("✅ Done", key=f"p_done_{p['id']}"):
                        conn.table("work_plans").update({"status": "Completed"}).eq("id", p['id']).execute(); st.rerun()
                else: tc.success(f"✔️ ~~**[{p['job_no']}]** {p['planned_task']}~~")
        else: st.caption("No pending plans noted.")

    st.divider()

    # --- 5. CORE DATA & METRICS ---
    emp_summ_res = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
    log_data = emp_summ_res[0] if emp_summ_res else {}
    work_summ_res = conn.table("work_logs").select("*").eq("employee_name", att_user).eq("work_date", today).order("created_at").execute().data
    move_summ_res = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data

    # --- 6. MANDATORY SNOOZE LOGS (Fixed for Blank Tab issue) ---
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
                conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{m_job}] {m_task}", "hours_spent": 1.0, "work_date": today}).execute()
                st.session_state.pop('snooze_until', None); st.rerun()
            if cf2.form_submit_button("🕒 Snooze (10m)"):
                st.session_state['snooze_until'] = get_now_ist() + timedelta(minutes=10); st.rerun()
        show_shift_controls = False

    if show_shift_controls:
        # --- 7. COMMITMENT BANNER (Persistence Fix) ---
        if log_data and not log_data.get('punch_out'):
            if "promise_confirmed" not in st.session_state:
                st.session_state["promise_confirmed"] = log_data.get('system_promise', False)

            if not st.session_state["promise_confirmed"]:
                with st.container(border=True):
                    st.markdown('<div style="background-color:#f8f9fb; padding:10px; border-left: 5px solid #007bff;">'
                                '<b>"I am dedicated to B&G’s systems. Following the system today is my path to precision."</b></div>', unsafe_allow_html=True)
                    if st.checkbox("🛡️ I acknowledge and commit to the above statement.", key="temp_promise_check"):
                        st.session_state["promise_confirmed"] = True; st.rerun()
            else: st.success("🙏 Thank you for your commitment to B&G systems!")

        # --- 8. SHIFT CONTROLS (Punch Out Database fix) ---
        ca, cb, cc = st.columns([1.8, 1.5, 2.5])
        # --- SHIFT CONTROLS ROW ---
        ca, cb, cc = st.columns([1.8, 1.5, 2.5])
        
        with ca:
            st.markdown("### 🏢 Shift")
            if not emp_summ_res:
                if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                    conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today, "punch_in": get_now_ist().isoformat()}).execute()
                    st.rerun()
            else:
                if not log_data.get('punch_out'):
                    st.markdown("**Productivity Rating**")
                    work_sat = st.feedback("stars", key="prod_stars_fb") 
                    if st.button("🏁 PUNCH OUT", use_container_width=True, type="primary"):
                        conn.table("attendance_logs").update({
                            "punch_out": get_now_ist().isoformat(), 
                            "work_satisfaction": work_sat,
                            "system_promise": st.session_state.get("promise_confirmed", False)
                        }).eq("id", log_data['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.success("Shift Completed")
                    if log_data.get('work_satisfaction'): 
                        st.write(f"Rating: {'⭐' * int(log_data['work_satisfaction'])}")

        # --- MOVEMENT COLUMN (cb) ---
        with cb:
            st.markdown("### 🚶 Movement")
            
            # 1. Fetch active moves ONLY for today to prevent old logs from blocking the UI
            now_str = get_now_ist().strftime("%Y-%m-%d")
            active_move_res = conn.table("movement_logs").select("*")\
                .eq("employee_name", att_user)\
                .is_("return_time", "null")\
                .execute().data
            
            # Filter in Python to ensure it's a 'Today' movement
            active_move = [m for m in active_move_res if m['exit_time'][:10] == now_str]

            if not active_move:
                # Use a unique key for the form and widgets to ensure they render
                with st.form("move_out_form", clear_on_submit=True):
                    reason = st.selectbox(
                        "Category", 
                        ["Meeting", "Work Review", "Material", "Inspection", "Vendor Visit", "Lunch", "Personal"],
                        key="selectbox_move_reason" # Unique Key
                    )
                    dest = st.text_input("Destination", key="input_move_dest") # Unique Key
                    
                    submit_out = st.form_submit_button("📤 TIME OUT", use_container_width=True)
                    
                    if submit_out:
                        if dest:
                            conn.table("movement_logs").insert({
                                "employee_name": att_user, 
                                "reason": reason, 
                                "destination": dest.upper(), 
                                "exit_time": get_now_ist().isoformat()
                            }).execute()
                            st.rerun()
                        else:
                            st.error("Enter Destination")
            else:
                # Show status if currently out
                current = active_move[0]
                st.warning(f"📍 Currently at {current['destination']}")
                if st.button("📥 LOG TIME IN", use_container_width=True, type="primary", key="btn_move_in"):
                    conn.table("movement_logs").update({
                        "return_time": get_now_ist().isoformat()
                    }).eq("id", current['id']).execute()
                    st.rerun()

        # --- WORK LOG COLUMN (cc) ---
        with cc:
            st.markdown("### 📝 Work log")
            with st.form("manual_work_log_form", clear_on_submit=True):
                slot_t = st.selectbox(
                    "Slot", 
                    LOG_SLOTS, 
                    format_func=get_ampm_label, 
                    key="selectbox_work_slot" # Unique Key
                )
                job_c = st.selectbox(
                    "Job", 
                    get_job_codes(), 
                    key="selectbox_work_job" # Unique Key
                )
                task = st.text_area("Update", key="input_work_details") # Unique Key
                
                if st.form_submit_button("Post Log", use_container_width=True):
                    if task:
                        conn.table("work_logs").insert({
                            "employee_name": att_user, 
                            "task_description": f"[{job_c}] @{slot_t}: {task}", 
                            "hours_spent": 1.0, 
                            "work_date": today
                        }).execute()
                        st.rerun()
                    else:
                        st.error("Please enter details")
# --- TAB 1: STAFF DATA HISTORY (UPDATED) ---
with tabs[1]:
    st.subheader(f"📊 Personal History: {att_user}")
    h_col1, h_col2 = st.columns([1, 2])
    
    with h_col1:
        # Added "My Movements" to the selection
        hist_type = st.radio(
            "Select View", 
            ["My Work Logs", "My Attendance History", "My Work Plans", "My Movements"], 
            horizontal=True,
            key="hist_type_selector"
        )
        hist_range = st.date_input("Select Date Range", [date.today() - timedelta(days=7), date.today()], key="hist_date_range")
    
    if len(hist_range) == 2:
        start_d, end_d = hist_range
        
        # Table Mapping
        mapping = {
            "My Work Logs": ("work_logs", "work_date"),
            "My Attendance History": ("attendance_logs", "work_date"),
            "My Work Plans": ("work_plans", "plan_date"),
            "My Movements": ("movement_logs", "exit_time") # Added mapping
        }
        
        table_name, date_col = mapping[hist_type]
        
        # Database Query
        hist_res = conn.table(table_name).select("*")\
            .eq("employee_name", att_user)\
            .gte(date_col, str(start_d))\
            .lte(date_col, str(end_d))\
            .order(date_col, desc=True).execute().data
        
        if hist_res:
            df_hist = pd.DataFrame(hist_res)
            
            # FIX: Convert to IST before formatting for display
            time_cols = ['punch_in', 'punch_out', 'exit_time', 'return_time', 'created_at']
            for col in time_cols:
                if col in df_hist.columns:
                    df_hist[col] = pd.to_datetime(df_hist[col], errors='coerce') \
                                     .dt.tz_convert(IST) \
                                     .dt.strftime('%d-%m %I:%M %p')
            
            st.dataframe(df_hist, use_container_width=True, hide_index=True)
            
            # Professional download button
            st.download_button(
                label=f"📥 Download {hist_type} (CSV)", 
                data=convert_df(df_hist), 
                file_name=f"{att_user}_{hist_type.replace(' ', '_')}.csv",
                mime="text/csv"
            )
        else:
            st.info(f"No records found for {hist_type} in this date range.")

# --- TAB 2: LEAVE APPLICATION & STATUS (INTEGRATED & SECURED) ---
with tabs[2]:
    st.subheader("New Leave Application")
    with st.form("leave_form", clear_on_submit=True):
        l_emp = st.selectbox("Confirm Your Name", get_staff_list(), 
                             index=get_staff_list().index(att_user) if att_user in get_staff_list() else 0)
        
        c1, c2 = st.columns(2)
        sd = c1.date_input("Start date", key="leave_sd")
        ed = c2.date_input("End date", key="leave_ed")
        
        reason_l = st.text_area("Reason for Leave")
        
        submit_leave = st.form_submit_button("🚀 Submit Application", use_container_width=True)
        
        if submit_leave:
            if ed < sd:
                st.error("❌ Error: End date cannot be before Start date.")
            elif not reason_l:
                st.warning("⚠️ Please provide a reason.")
            else:
                try:
                    conn.table("leave_requests").insert({
                        "employee_name": l_emp, 
                        "leave_type": "Casual Leave", 
                        "start_date": str(sd), 
                        "end_date": str(ed), 
                        "reason": reason_l, 
                        "status": "Pending"
                    }).execute()
                    st.success("✅ Application Submitted Successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Database Error: {e}")

    st.divider()
    st.subheader("📜 Your Recent Requests & Status")
    df_l_all = get_leave_requests() # Uses the cached function from setup
    
    if not df_l_all.empty:
        # Use att_user to ensure privacy
        my_requests = df_l_all[df_l_all['employee_name'] == att_user].copy()
        
        if not my_requests.empty:
            for _, r in my_requests.head(10).iterrows():
                with st.container(border=True):
                    col_a, col_b, col_c = st.columns([3, 2, 1])
                    
                    # Date Range display
                    col_a.write(f"📅 **{r['start_date']} to {r['end_date']}**")
                    col_a.caption(f"Reason: {r['reason']}")
                    
                    # Status Coloring Logic
                    s_color = "orange" if r['status'] == 'Pending' else "green" if r['status'] == 'Approved' else "red"
                    col_b.markdown(f"Status: **:{s_color}[{r['status']}]**")
                    if r.get('reject_reason'): 
                        col_b.caption(f"Note: {r['reject_reason']}")
                    
                    # Withdrawal Logic
                    if r['status'] == 'Pending':
                        if col_c.button("Withdraw", key=f"wd_{r['id']}", use_container_width=True):
                            conn.table("leave_requests").delete().eq("id", r['id']).execute()
                            st.rerun()
        else:
            st.info("No leave applications found for your account.")

# --- TAB 3: BALANCE (STABLE & VISUAL) ---
with tabs[3]:
    st.subheader("📊 Leave Balance & Usage")
    
    # 1. Fetch Fresh Data
    df_l = get_leave_requests()
    
    # 2. Select User (Default to the logged-in user for convenience)
    staff_list = get_staff_list()
    default_idx = staff_list.index(att_user) if att_user in staff_list else 0
    u_sel = st.selectbox("Check balance for:", staff_list, index=default_idx, key="bal_u_final")
    
    if not df_l.empty:
        # 3. Filter for Approved Leaves of the selected user
        u_df = df_l[(df_l['employee_name'] == u_sel) & (df_l['status'] == 'Approved')].copy()
        
        if not u_df.empty:
            try:
                # 4. Secure Calculation: Convert to datetime and calculate days
                u_df['start_date'] = pd.to_datetime(u_df['start_date'])
                u_df['end_date'] = pd.to_datetime(u_df['end_date'])
                u_df['day_count'] = (u_df['end_date'] - u_df['start_date']).dt.days + 1
                used = u_df['day_count'].sum()
            except Exception as e:
                st.error("Error calculating balance. Please check date formats in database.")
                used = 0
        else:
            used = 0
        
        # 5. Metrics Display
        quota = LEAVE_QUOTA.get("Casual Leave", 12)
        remaining = max(0, quota - used)
        
        c1, c2 = st.columns(2)
        c1.metric("Available Balance", f"{int(remaining)} Days", delta=f"{int(used)} Used", delta_color="inverse")
        
        # 6. Visual Progress Bar
        usage_percent = min(100, int((used / quota) * 100))
        st.write(f"**Leave Consumption ({usage_percent}%)**")
        st.progress(usage_percent / 100)
        
        if usage_percent >= 80:
            st.warning("⚠️ Note: You have utilized more than 80% of your leave quota.")
            
    else:
        st.info("No leave records found in the system.")
        st.metric("Casual Leave Balance", "12 Days", "0 Used")
        
# --- TAB 4: HR ADMIN PANEL ---
with tabs[4]:
    admin_pass = st.text_input("Admin Password", type="password", key="hr_panel_pass")
    if admin_pass == "bgadmin":
        # TOP LEVEL FILTERS
        ac1, ac2 = st.columns(2)
        s_name = ac1.selectbox("Filter Staff", ["All Staff"] + get_staff_list(), key="adm_filt_main")
        export_mode = ac2.selectbox("Range", ["Weekly", "Monthly", "Custom Date"], key="adm_range")
        
        if export_mode == "Weekly": sr, er = date.today() - timedelta(days=7), date.today()
        elif export_mode == "Monthly": sr, er = date.today() - timedelta(days=30), date.today()
        else:
            c_date1, c_date2 = st.columns(2)
            sr = c_date1.date_input("From date", key="adm_sr")
            er = c_date2.date_input("To date", key="adm_er")
        
        # SUB-NAVIGATION TABS
        admin_tabs = st.tabs(["📈 Performance Analytics", "📜 Leave Position", "🕒 Detailed Logs", "📬 Approvals", "🔐 Access Keys"])
        
        # --- SUB-TAB 0: PERFORMANCE ANALYTICS & GRADING ---
        with admin_tabs[0]:
            st.subheader(f"📊 Performance Overview ({sr} to {er})")
            
            # Fetch Data
            t_att = conn.table("attendance_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
            t_work = conn.table("work_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
            t_plan = conn.table("work_plans").select("*").gte("plan_date", str(sr)).lte("plan_date", str(er)).execute().data

            if t_att:
                df_att = pd.DataFrame(t_att)
                df_work = pd.DataFrame(t_work) if t_work else pd.DataFrame(columns=['employee_name','hours_spent'])
                df_plan = pd.DataFrame(t_plan) if t_plan else pd.DataFrame(columns=['employee_name', 'status'])
                
                if s_name != "All Staff":
                    df_att = df_att[df_att['employee_name'] == s_name]
                    df_work = df_work[df_work['employee_name'] == s_name]
                    df_plan = df_plan[df_plan['employee_name'] == s_name]

                # 1. Punctuality Logic
                # 1. Punctuality Logic
                # Use 'errors=coerce' to prevent crashes if a punch_in is missing
                # Ensure we convert UTC to IST before extracting .time
                df_att['punch_dt'] = pd.to_datetime(df_att['punch_in'], errors='coerce').dt.tz_convert(IST)

                # EXTRACT TIME: Crucial to use .time for comparison against LATE_THRESHOLD
                df_att['p_in_t'] = df_att['punch_dt'].dt.time

                # FILTER & COUNT: Only those AFTER 09:05 AM
                # Note: 6:00 AM production staff will be 'False' (Not Late) because 06:00 < 09:05
                late_days = len(df_att[df_att['p_in_t'] > LATE_THRESHOLD])
                total_days = len(df_att)
                
                # 2. Efficiency Logic (Planned vs Done)
                total_tasks = len(df_plan)
                done_tasks = len(df_plan[df_plan['status'] == 'Completed'])
                efficiency = (done_tasks / total_tasks * 100) if total_tasks > 0 else 0
                
                # 3. Satisfaction/Morale
                avg_sat = df_att['work_satisfaction'].mean() if 'work_satisfaction' in df_att.columns else 0
                # 4. Count of Work Logs in range
                work_log_count = len(df_work)

                # 5. Count of Productivity Rating Logs (where satisfaction was actually given)
                # This checks how many days they actually gave a star rating during Punch Out
                prod_rating_count = df_att['work_satisfaction'].notnull().sum()

                # 6. Count of Commitment Logs (System Promise acknowledged)
                commitment_count = df_att['system_promise'].sum() if 'system_promise' in df_att.columns else 0

                # --- B&G GRADING DISPLAY ---
                if s_name != "All Staff":
                    if efficiency >= 90 and late_days == 0: grade, color, note = "A+", "#28a745", "Excellent Performance"
                    elif efficiency >= 75 and late_days <= 2: grade, color, note = "A", "#17a2b8", "Strong Contributor"
                    elif efficiency >= 60: grade, color, note = "B", "#ffc107", "Meeting Expectations"
                    else: grade, color, note = "C", "#dc3545", "Review Required"

                    st.markdown(f"""
                        <div style="background-color:{color}; padding:20px; border-radius:15px; text-align:center; color:white;">
                            <h1 style="margin:0;">Grade: {grade}</h1>
                            <p style="margin:0; font-weight:bold;">{note}</p>
                        </div>
                    """, unsafe_allow_html=True)

                # Summary Metrics
                # First Row of Metrics
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Days Worked", total_days)
                m2.metric("Late Comings", f"{late_days} Days", delta_color="inverse")
                m3.metric("Task Efficiency", f"{efficiency:.1f}%")
                m4.metric("Avg Satisfaction", f"{avg_sat:.1f} ⭐")

                st.divider()

                # Second Row of Metrics (New Features)
                m5, m6, m7 = st.columns(3)
                m5.metric("Total Work Logs", f"{work_log_count} Posts")
                m6.metric("Commitment Acks", f"{int(commitment_count)} Logs")
                m7.metric("Rating Logs", f"{int(prod_rating_count)} Days")

        # --- SUB-TAB 1: LEAVE POSITION ---
        with admin_tabs[1]:
            st.subheader("📜 Staff Leave Balance Summary")
            all_l_raw = get_leave_requests()
            if not all_l_raw.empty:
                app_l = all_l_raw[all_l_raw['status'] == 'Approved'].copy()
                if not app_l.empty:
                    app_l['days'] = (pd.to_datetime(app_l['end_date']) - pd.to_datetime(app_l['start_date'])).dt.days + 1
                    leave_sum = app_l.groupby('employee_name')['days'].sum().reset_index()
                    leave_sum.columns = ['Employee Name', 'Used Days']
                    leave_sum['Balance'] = 12 - leave_sum['Used Days']
                    if s_name != "All Staff": leave_sum = leave_sum[leave_sum['Employee Name'] == s_name]
                    st.dataframe(leave_sum, use_container_width=True, hide_index=True)

        # --- SUB-TAB 2: DETAILED LOGS ---
        with admin_tabs[2]:
            st.markdown("#### 🕒 Raw Activity Logs")
            l_type = st.radio("Category", ["Attendance", "Work Logs", "Movement", "Plans"], horizontal=True, key="log_cat_adm")
            tbl_map = {"Attendance": "attendance_logs", "Work Logs": "work_logs", "Movement": "movement_logs", "Plans": "work_plans"}
            date_col_map = {"Attendance": "work_date", "Work Logs": "work_date", "Movement": "exit_time", "Plans": "plan_date"}
    
            res = conn.table(tbl_map[l_type]).select("*").gte(date_col_map[l_type], str(sr)).lte(date_col_map[l_type], str(er)).execute().data
            if res:
                df_v = pd.DataFrame(res)
                if s_name != "All Staff": 
                    df_v = df_v[df_v['employee_name'] == s_name]
        
                # --- FIX STARTS HERE: Force IST Conversion before display/export ---
                time_cols = ['punch_in', 'punch_out', 'exit_time', 'return_time', 'created_at']
                for col in time_cols:
                    if col in df_v.columns:
                        # Convert UTC string to IST and format as readable string
                        df_v[col] = pd.to_datetime(df_v[col], errors='coerce').dt.tz_convert(IST).dt.strftime('%d-%m %I:%M %p')
        
                df_v = df_v.fillna("None") # Clean up empty values
                # --- FIX ENDS HERE ---

                st.dataframe(df_v, hide_index=True, use_container_width=True)
                st.download_button("📥 Export CSV", data=convert_df(df_v), file_name=f"Admin_{l_type}_IST.csv")
        # --- SUB-TAB 3: APPROVALS ---
        with admin_tabs[3]:
            pend = get_leave_requests()
            if not pend.empty:
                to_approve = pend[pend['status'] == 'Pending']
                if not to_approve.empty:
                    for _, row in to_approve.iterrows():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([2, 3, 2])
                            c1.write(f"**{row['employee_name']}**")
                            c2.write(f"📅 {row['start_date']} to {row['end_date']}\n{row['reason']}")
                            if c3.button("✅ Approve", key=f"ap_{row['id']}"):
                                conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute(); st.rerun()
                            with c3.popover("❌ Reject"):
                                rn = st.text_input("Reason", key=f"rn_{row['id']}")
                                if st.button("Confirm Reject", key=f"rb_{row['id']}"):
                                    conn.table("leave_requests").update({"status": "Rejected", "reject_reason": rn}).eq("id", row['id']).execute(); st.rerun()
                else: st.success("No pending approvals.")

        # --- SUB-TAB 4: ACCESS KEYS ---
        with admin_tabs[4]:
            st.subheader("🔐 Manage Staff Access Keys")
            with st.form("key_mgmt"):
                target_emp = st.selectbox("Staff", get_staff_list(), key="adm_key_sel")
                new_key = st.text_input("Set New Access Key", type="password")
                if st.form_submit_button("Update Access Key"):
                    if new_key:
                        conn.table("employee_auth").upsert({"employee_name": target_emp, "access_key": new_key}).execute()
                        st.success(f"Key updated for {target_emp}!"); st.rerun()
