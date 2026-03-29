import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz
import plotly.express as px

# --- 1. SETUP & CONSTANTS ---
IST = pytz.timezone('Asia/Kolkata')
OFFICE_IN = time(9, 0)
GRACE_IN = time(9, 15)
OFFICE_OUT = time(17, 30)

st.set_page_config(page_title="B&G HR | ERP System", layout="wide", page_icon="📅")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SMART TIME UTILITY ---
def to_ist(series):
    if series is None or (isinstance(series, pd.Series) and series.empty):
        return series
    dt = pd.to_datetime(series)
    if dt.dt.tz is None:
        dt = dt.dt.tz_localize('UTC')
    return dt.dt.tz_convert(IST)

def get_now_ist():
    return datetime.now(IST)

# --- 3. DATA LOADERS ---
@st.cache_data(ttl=5)
def get_leave_requests():
    res = conn.table("leave_requests").select("*").order("created_at", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return [s['name'] for s in res.data] if res.data else ["Admin", "Staff Member"]
    except: return ["Admin", "Staff Member"]

# --- 4. NAVIGATION ---
tabs = st.tabs(["🕒 Attendance & Productivity", "📝 Leave Application", "📊 My Balance", "🔐 HR Admin Panel"])

# --- TAB 1: ATTENDANCE, MOVEMENT & WORK LOGS ---
with tabs[0]:
    st.subheader("🕒 Daily Time Office & Productivity Tracker")
    att_user = st.selectbox("Identify Yourself", get_staff_list(), key="att_user")
    today = str(date.today())
    
    col_a, col_b, col_c = st.columns([1.5, 1.5, 2.5])
    
    # A. SHIFT PUNCH
    with col_a:
        st.markdown("### 🏢 Shift Punch")
        att_data = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
        if not att_data:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute()
                st.rerun()
        else:
            log = att_data[0]
            p_in = to_ist(pd.Series([log['punch_in']])).dt.time.iloc[0]
            if p_in > GRACE_IN: st.error(f"🚩 Late Entry: {p_in.strftime('%I:%M %p')}")
            else: st.success(f"✅ On Time: {p_in.strftime('%I:%M %p')}")
            
            if not log.get('punch_out'):
                if st.button("🏁 PUNCH OUT", use_container_width=True):
                    conn.table("attendance_logs").update({"punch_out": get_now_ist().isoformat()}).eq("id", log['id']).execute()
                    st.rerun()
            else:
                p_out = to_ist(pd.Series([log['punch_out']])).dt.time.iloc[0]
                if p_out < OFFICE_OUT: st.warning(f"⚠️ Early Departure: {p_out.strftime('%I:%M %p')}")
                else: st.success(f"🏁 Shift Ended: {p_out.strftime('%I:%M %p')}")

    # B. MOVEMENT REGISTER
    with col_b:
        st.markdown("### 🚶 Movement")
        active_move = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        if not active_move:
            with st.form("move_form", clear_on_submit=True):
                reason = st.selectbox("Category", ["Inter-Unit Transfer", "Site Delivery", "Vendor Visit", "Lunch", "Personal"])
                detail = st.text_input("Detailed Purpose (e.g. Drawing Discussion)")
                dest = st.text_input("Destination")
                if st.form_submit_button("📤 TIME OUT"):
                    if dest and detail:
                        conn.table("movement_logs").insert({"employee_name": att_user, "reason": f"{reason}: {detail}", "destination": dest.upper(), "exit_time": get_now_ist().isoformat()}).execute()
                        st.rerun()
                    else: st.error("Purpose & Destination required.")
        else:
            m_log = active_move[0]
            st.warning(f"⚠️ At **{m_log['destination']}** for **{m_log['reason']}**")
            if st.button("📥 TIME IN", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", m_log['id']).execute()
                st.rerun()

    # C. HOURLY WORK REPORT
    with col_c:
        st.markdown("### 📝 Daily Work Log")
        with st.form("work_log_form", clear_on_submit=True):
            project = st.selectbox("Project (Optional)", ["General", "Maintenance", "Drawing", "Client: Tata", "Client: JSW", "Client: Hetero"])
            task = st.text_area("What did you do?", placeholder="e.g., 10 AM - 12 PM: Milling machine maintenance")
            duration = st.number_input("Hours", min_value=0.5, max_value=8.0, value=1.0, step=0.5)
            if st.form_submit_button("Post Update"):
                if task:
                    conn.table("work_logs").insert({"employee_name": att_user, "task_description": f"[{project}] {task}", "hours_spent": duration, "work_date": today}).execute()
                    st.success("Log saved!"); st.rerun()

    # --- HISTORICAL SUMMARIES ---
    st.divider()
    h1, h2 = st.columns(2)
    with h1:
        st.markdown("#### 📜 Last 5 Shifts")
        hist_data = conn.table("attendance_logs").select("*").eq("employee_name", att_user).order("work_date", desc=True).limit(5).execute().data
        if hist_data:
            hdf = pd.DataFrame(hist_data)
            hdf['In'] = to_ist(hdf['punch_in']).dt.strftime('%I:%M %p')
            hdf['Out'] = to_ist(hdf['punch_out']).dt.strftime('%I:%M %p').fillna("Active")
            st.dataframe(hdf[['work_date', 'In', 'Out']], use_container_width=True, hide_index=True)
    with h2:
        st.markdown("#### 🛠️ Today's Work Updates")
        work_data = conn.table("work_logs").select("*").eq("employee_name", att_user).eq("work_date", today).order("created_at", desc=True).execute().data
        if work_data:
            st.dataframe(pd.DataFrame(work_data)[['task_description', 'hours_spent']], use_container_width=True, hide_index=True)

# --- TAB 2: LEAVE APPLICATION ---
with tabs[1]:
    st.subheader("New Leave Application")
    with st.form("leave_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        emp_name_l = col1.selectbox("Employee Name", get_staff_list(), key="l_emp")
        l_type = col2.selectbox("Type", ["Casual Leave", "Sick Leave", "Earned Leave", "Loss of Pay"])
        d1, d2 = st.columns(2)
        s_date = d1.date_input("Start", min_value=date.today())
        e_date = d2.date_input("End", min_value=date.today())
        reason_l = st.text_area("Reason")
        if st.form_submit_button("Submit"):
            conn.table("leave_requests").insert({"employee_name": emp_name_l, "leave_type": l_type, "start_date": str(s_date), "end_date": str(e_date), "reason": reason_l, "status": "Pending"}).execute()
            st.success("✅ Submitted."); st.cache_data.clear(); st.rerun()

# --- TAB 3: MY BALANCE ---
with tabs[2]:
    st.subheader("Leave Balance & History")
    df_leaves = get_leave_requests()
    user_sel_bal = st.selectbox("View Records for:", get_staff_list(), key="bal_user")
    if not df_leaves.empty:
        user_df = df_leaves[df_leaves['employee_name'] == user_sel_bal].copy()
        app_df = user_df[user_df['status'] == 'Approved'].copy()
        total_t = ((pd.to_datetime(app_df['end_date']) - pd.to_datetime(app_df['start_date'])).dt.days + 1).sum() if not app_df.empty else 0
        st.metric("Total Days Taken", f"{total_t} Days")
        for _, r in user_df.head(5).iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                c1.write(f"**{r['leave_type']}**"); c2.write(f"{r['start_date']} to {r['end_date']}"); c3.write(r['status'])
                if r['status'] == "Pending" and c4.button("Withdraw", key=f"wd_{r['id']}"):
                    conn.table("leave_requests").delete().eq("id", r['id']).execute(); st.cache_data.clear(); st.rerun()

# --- TAB 4: HR ADMIN PANEL ---
with tabs[3]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        st.subheader("📊 Today's Productivity Dashboard")
        t_att = conn.table("attendance_logs").select("*").eq("work_date", today).execute().data
        t_move = conn.table("movement_logs").select("*").gte("exit_time", f"{today}T00:00:00").execute().data
        t_work = conn.table("work_logs").select("*").eq("work_date", today).execute().data
        
        if t_att:
            tdf = pd.DataFrame(t_att)
            def calc_productivity(row):
                # Net Shift Hours
                start = pd.to_datetime(row['punch_in'])
                end = pd.to_datetime(row['punch_out']) if pd.notnull(row['punch_out']) else get_now_ist()
                shift = (end - start).total_seconds() / 3600
                # Subtract Lunch/Personal
                breaks = 0
                if t_move:
                    mdf = pd.DataFrame(t_move)
                    u_b = mdf[(mdf['employee_name'] == row['employee_name']) & (mdf['reason'].str.contains('Lunch|Personal')) & (mdf['return_time'].notnull())]
                    breaks = (pd.to_datetime(u_b['return_time']) - pd.to_datetime(u_b['exit_time'])).dt.total_seconds().sum() / 3600
                final_s = max(0.1, shift - breaks)
                # Task Hours
                task_h = pd.DataFrame(t_work)[pd.DataFrame(t_work)['employee_name'] == row['employee_name']]['hours_spent'].sum() if t_work else 0
                return f"{final_s:.2f}h", f"{task_h:.2f}h", f"{int(min(100, (task_h/final_s)*100))}%"

            tdf[['Net Shift', 'Logged Tasks', 'Efficiency']] = tdf.apply(calc_productivity, axis=1, result_type='expand')
            st.table(tdf[['employee_name', 'Net Shift', 'Logged Tasks', 'Efficiency']])
            
            if t_work:
                st.markdown("### 🏗️ Project Distribution")
                wdf = pd.DataFrame(t_work)
                wdf['Project'] = wdf['task_description'].str.extract(r'\[(.*?)\]').fillna("General")
                fig = px.pie(wdf, values='hours_spent', names='Project', hole=0.4)
                st.plotly_chart(fig, use_container_width=True)
        
        st.divider()
        st.subheader("📬 Pending Approvals")
        df_all = get_leave_requests()
        if not df_all.empty:
            pending = df_all[df_all['status'] == 'Pending']
            for _, row in pending.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 2, 1])
                    c1.write(f"**{row['employee_name']}**"); c2.write(row['reason'])
                    if c3.button("Approve", key=f"ap_{row['id']}"):
                        conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute(); st.rerun()
