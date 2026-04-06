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
                st.error("Invalid Access Key.")
        st.stop()

    att_user = st.session_state["authenticated_user"]
    
    if st.button("🔓 Logout / Switch User"):
        st.session_state["authenticated_user"] = None
        st.session_state["admin_authenticated"] = False
        st.rerun()

    st.divider()

    # --- 1. FOUNDER - EMPLOYEE INTERACTION WINDOW ---
    st.markdown("### 📢 Founder's Desk")
    
    # FIX: For Admin, we put the inbox in a scrollable area to save space
    if att_user == "Admin":
        if not st.session_state.get("admin_authenticated"):
            pw_input = st.text_input("🔑 Admin Access Key", type="password", key="admin_gate_pw")
            if st.button("Unlock Founder Desk"):
                if pw_input == "bg2026":
                    st.session_state["admin_authenticated"] = True
                    st.rerun()
            st.stop()

        # Admin Message Posting
        with st.expander("✉️ Post New Instruction/Announcement", expanded=False):
            with st.form("founder_msg_form"):
                m_target = st.selectbox("Target Employee", ["All"] + get_staff_list())
                m_text = st.text_area("Instruction Content")
                if st.form_submit_button("🚀 Broadcast"):
                    if m_text:
                        # ... (existing broadcast logic) ...
                        st.success("Sent!"); st.rerun()

        # FIX: SCROLLABLE INBOX FOR ADMIN
        st.markdown("**📥 Unified Interaction Inbox** (Scroll to view)")
        # Using a container with fixed height via CSS
        st.markdown('<div style="max-height: 300px; overflow-y: auto; border: 1px solid #ddd; padding: 10px; border-radius: 5px; margin-bottom: 20px;">', unsafe_allow_html=True)
        try:
            all_interactions = conn.table("founder_interaction").select("*").order("created_at", desc=True).limit(30).execute().data
            if all_interactions:
                for r in all_interactions:
                    with st.container():
                        st.caption(f"From: {r['sender_name']} to {r['target_user']} | {r['created_at'][:16]}")
                        st.write(f"💬 {r['content']}")
                        if r.get('reply_content'):
                            st.info(f"Ref: {r['reply_content']}")
                        st.divider()
            else: st.write("No messages.")
        except: st.write("Inbox error.")
        st.markdown('</div>', unsafe_allow_html=True)

    else:
        # User View (Employee View)
        try:
            msg_res = conn.table("founder_interaction").select("*")\
                .or_(f"target_user.eq.{att_user},sender_name.eq.{att_user}")\
                .order("created_at", desc=True).limit(1).execute().data
            if msg_res:
                m = msg_res[0]
                with st.container(border=True):
                    if m['sender_name'] == att_user:
                        st.write(f"📤 **My Message:** {m['content']}")
                        if m.get('reply_content'): st.info(f"🏁 **Response:** {m['reply_content']}")
                    else:
                        st.info(f"**From Founder:** {m['content']}")
                        if not m.get('is_read'):
                            col_txt, col_btn = st.columns([3, 1])
                            emp_reply = col_txt.text_input("Reply...", key=f"rep_{m['id']}")
                            if col_btn.button("✔️ Send", key=f"ack_{m['id']}"):
                                conn.table("founder_interaction").update({"is_read": True, "reply_content": emp_reply or "Acknowledged"}).eq("id", m['id']).execute()
                                st.rerun()
        except: pass

    st.divider()
                
    today = str(date.today())

    # --- 2. WORK PLAN ---
    st.markdown("### 🏗️ My Work Plan")
    # ... (existing Work Plan columns logic) ...

    st.divider()
    
    # 3. FETCH ATTENDANCE DATA EARLY TO PREVENT NameError
    emp_summ_res = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
    work_summ_res = conn.table("work_logs").select("*").eq("employee_name", att_user).eq("work_date", today).order("created_at").execute().data
    
    if emp_summ_res:
        log_data = emp_summ_res[0]
        start_t = pd.to_datetime(log_data.get('punch_in')).tz_convert(IST) if log_data.get('punch_in') else None
        
        # --- FIX: DISAPPEARING COMMITMENT BANNER ---
        if not log_data.get('punch_out'):
            commitment_placeholder = st.empty()
            
            # Use session state to track if they just clicked it
            if not st.session_state.get("sys_promise"):
                with commitment_placeholder.container():
                    st.markdown("""
                        <div style="background-color:#f8f9fb; padding:15px; border-radius:10px; border-left: 5px solid #007bff; margin-bottom:10px;">
                            <p style="font-size:18px; font-weight:bold; color:#1f1f1f; margin:0;">
                                "I am dedicated to B&G’s systems. Following the system today is my path to precision."
                            </p>
                        </div>
                    """, unsafe_allow_html=True)
                    st.checkbox("🛡️ I acknowledge and commit to the above statement for today.", key="sys_promise")
            else:
                # Banner disappears, replaced by this message
                st.success("🙏 Thank you for your commitment! Have a productive shift.")

        # --- METRICS ROW ---
        if start_t and st.session_state.get("sys_promise"):
            c1, c2, c3 = st.columns(3)
            c1.metric("Punch In", start_t.strftime('%I:%M %p'))
            # ... (rest of metrics) ...

    # --- 4. SHIFT CONTROLS ---
    st.divider()
    ca, cb, cc = st.columns([1.8, 1.5, 2.5])
    # ... (existing Punch In/Out, Movement, and Work log logic) ...
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

# --- TAB 2: LEAVE APPLICATION & STATUS ---
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
                    if r.get('reject_reason'): col_b.caption(f"Note: {r['reject_reason']}")
                    if r['status'] == 'Pending':
                        if col_c.button("Withdraw", key=f"wd_{r['id']}"):
                            conn.table("leave_requests").delete().eq("id", r['id']).execute(); st.rerun()

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
        ac1, ac2 = st.columns(2)
        s_name = ac1.selectbox("Filter Staff", ["All Staff"] + get_staff_list(), key="adm_filt")
        export_mode = ac2.selectbox("Range", ["Weekly", "Monthly", "Custom Date"])
        if export_mode == "Weekly": sr, er = date.today() - timedelta(days=7), date.today()
        elif export_mode == "Monthly": sr, er = date.today() - timedelta(days=30), date.today()
        else: sr, er = st.date_input("From date"), st.date_input("To date")
        
        # --- ADDED "🔐 Access Keys" TO THE LIST BELOW ---
        admin_tabs = st.tabs(["📈 Analytics", "📜 Leave Position", "🕒 Detailed Logs", "📬 Approvals", "🔐 Access Keys"])
        
        with admin_tabs[0]: # Analytics Logic
            st.subheader(f"🏢 Operational Data tracking ({sr} to {er})")
            t_att = conn.table("attendance_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
            t_work = conn.table("work_logs").select("*").gte("work_date", str(sr)).lte("work_date", str(er)).execute().data
            if t_att:
                df_att = pd.DataFrame(t_att)
                df_work = pd.DataFrame(t_work) if t_work else pd.DataFrame(columns=['employee_name','hours_spent', 'task_description'])
                if s_name != "All Staff":
                    df_att = df_att[df_att['employee_name'] == s_name]
                    df_work = df_work[df_work['employee_name'] == s_name]
                
                st.markdown("#### ⌛ Late Comers List")
                df_att['p_in_t'] = pd.to_datetime(df_att['punch_in']).dt.tz_convert(IST).dt.time
                late = df_att[df_att['p_in_t'] > LATE_THRESHOLD][['work_date', 'employee_name', 'p_in_t']]
                st.dataframe(late.sort_values('work_date', ascending=False), use_container_width=True, hide_index=True)

                st.markdown("#### 🚀 Workforce Efficiency Ranking")
                df_att['pi_dt'] = pd.to_datetime(df_att['punch_in']).dt.tz_convert(IST)
                df_att['po_dt'] = pd.to_datetime(df_att['punch_out']).dt.tz_convert(IST).fillna(get_now_ist())
                df_att['presence_hrs'] = (df_att['po_dt'] - df_att['pi_dt']).dt.total_seconds() / 3600
                eff = pd.merge(df_att.groupby('employee_name')['presence_hrs'].sum().reset_index(), df_work.groupby('employee_name')['hours_spent'].sum().reset_index(), on='employee_name', how='left').fillna(0)
                eff['Eff %'] = (eff['hours_spent'] / eff['presence_hrs'] * 100).round(1)
                st.dataframe(eff.sort_values('Eff %', ascending=False), use_container_width=True, hide_index=True)

        with admin_tabs[1]: # RESTORED: Staff Leave Position
            st.subheader("📜 Staff Leave Balance Summary")
            all_l_raw = get_leave_requests()
            if not all_l_raw.empty:
                app_l = all_l_raw[all_l_raw['status'] == 'Approved'].copy()
                if not app_l.empty:
                    app_l['days'] = (pd.to_datetime(app_l['end_date']) - pd.to_datetime(app_l['start_date'])).dt.days + 1
                    leave_sum = app_l.groupby('employee_name')['days'].sum().reset_index()
                    leave_sum.columns = ['Employee Name', 'Used Days']
                    leave_sum['Balance'] = 12 - leave_sum['Used Days']
                    
                    if s_name != "All Staff":
                        leave_sum = leave_sum[leave_sum['Employee Name'] == s_name]
                    st.dataframe(leave_sum, use_container_width=True, hide_index=True)
                else:
                    st.info("No approved leave records found.")
            else:
                st.info("No leave records found.")

        with admin_tabs[2]: # Detailed Logs
             st.markdown("#### 🕒 Raw Activity Logs (IST Timezone)")
             l_type = st.radio("Select Log Category", ["Attendance", "Work Logs", "Movement", "Plans"], horizontal=True)
            
             # Configuration mapping
             table_config = {
                 "Attendance": ("attendance_logs", "work_date"),
                 "Work Logs": ("work_logs", "work_date"),
                 "Movement": ("movement_logs", "exit_time"),
                 "Plans": ("work_plans", "plan_date")
             }
            
             tbl, date_col = table_config[l_type]
            
             try:
                 # 1. Fetch Data from Supabase
                 res_query = conn.table(tbl).select("*").gte(date_col, str(sr)).lte(date_col, str(er)).execute()
                
                 if res_query.data:
                     df_v = pd.DataFrame(res_query.data)
                    
                     # Apply Employee Filter
                     if s_name != "All Staff": 
                         df_v = df_v[df_v['employee_name'] == s_name]

                     if not df_v.empty:
                         # --- TIME LOGIC: Convert UTC to IST for Readability ---
                         time_cols = ['punch_in', 'punch_out', 'exit_time', 'return_time', 'created_at']
                         for col in time_cols:
                             if col in df_v.columns:
                                 # Convert strings to datetime, localize to UTC, convert to IST
                                 df_v[col] = pd.to_datetime(df_v[col], errors='coerce').dt.tz_convert(IST).dt.strftime('%d-%m %I:%M %p')
                        
                         # Sort by the first column (usually ID or Date) descending
                         df_v = df_v.sort_values(by=df_v.columns[0], ascending=False)

                         # Display Table
                         st.dataframe(df_v, hide_index=True, use_container_width=True)
                        
                         # Download Button
                         st.download_button(
                             label=f"📥 Export {l_type} (IST)", 
                             data=convert_df(df_v), 
                             file_name=f"Admin_{l_type}_IST_{sr}_to_{er}.csv"
                         )
                     else:
                         st.info("No records match the current filters.")
                 else:
                     st.info("No data found in database for this range.")
                    
             except Exception as e:
                 st.error(f"PostgREST Error: {e}")
                
        with admin_tabs[3]: # Leave Approval logic
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
                                    conn.table("leave_requests").update({"status": "Rejected", "reject_reason": rn}).eq("id", row['id']).execute(); st.cache_data.clear(); st.rerun()
                else:
                    st.success("No pending approval requests.")
        with admin_tabs[4]: 
            st.subheader("🔐 Employee Access Key Management")
            
            with st.form("admin_pw_update_form", clear_on_submit=True):
                target_emp = st.selectbox("Select Employee", get_staff_list())
                new_key = st.text_input("Set New Access Key", type="password")
                
                if st.form_submit_button("Update Access Key"):
                    if new_key:
                        try:
                            # 1. We first check if the user exists in the auth table
                            check = conn.table("employee_auth").select("id").eq("employee_name", target_emp).execute().data
                            
                            if check:
                                # 2. If they exist, we UPDATE their specific row
                                conn.table("employee_auth").update({"access_key": new_key}).eq("employee_name", target_emp).execute()
                                st.success(f"✅ Password for {target_emp} has been updated!")
                            else:
                                # 3. If they are brand new, we INSERT them
                                conn.table("employee_auth").insert({"employee_name": target_emp, "access_key": new_key}).execute()
                                st.success(f"✅ New access record created for {target_emp}!")
                                
                            st.rerun()
                        except Exception as e:
                            st.error(f"Database Error: {e}")
                    else:
                        st.warning("Please enter a key before submitting.")   
