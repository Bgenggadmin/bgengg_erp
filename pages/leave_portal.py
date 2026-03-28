import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz
import plotly.express as px

# --- 1. SETUP & STYLE ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G HR | Leave & Attendance", layout="wide", page_icon="📅")

conn = st.connection("supabase", type=SupabaseConnection)

def get_now_ist():
    return datetime.now(IST)

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    div.stButton > button { border-radius: 50px; font-weight: 600; }
    .metric-card { background-color: #ffffff; padding: 15px; border-radius: 10px; border: 1px solid #eee; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=5)
def get_leave_requests():
    res = conn.table("leave_requests").select("*").order("created_at", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return [s['name'] for s in res.data] if res.data else ["Admin", "Staff Member"]
    except:
        return ["Admin", "Staff Member"]

# --- 3. NAVIGATION ---
tabs = st.tabs(["📝 Leave Application", "📊 My Balance", "🕒 Attendance & Movement", "🔐 HR Admin Panel"])

# --- TAB 1: LEAVE APPLICATION ---
with tabs[0]:
    st.subheader("Employee Leave Application")
    with st.form("leave_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        emp_name = col1.selectbox("Employee Name", get_staff_list())
        l_type = col2.selectbox("Leave Type", ["Casual Leave", "Sick Leave", "Earned Leave", "Loss of Pay"])
        
        d1, d2 = st.columns(2)
        s_date = d1.date_input("Start Date", min_value=date.today())
        e_date = d2.date_input("End Date", min_value=date.today())
        reason = st.text_area("Reason for Leave")
        
        if st.form_submit_button("Submit Application"):
            if s_date > e_date:
                st.error("Error: End Date cannot be before Start Date.")
            else:
                payload = {"employee_name": emp_name, "leave_type": l_type, "start_date": str(s_date), "end_date": str(e_date), "reason": reason, "status": "Pending"}
                conn.table("leave_requests").insert(payload).execute()
                st.success("✅ Application submitted.")
                st.cache_data.clear()
                st.rerun()

# --- TAB 2: MY BALANCE ---
with tabs[1]:
    df_leaves = get_leave_requests()
    user_sel = st.selectbox("View Records for:", get_staff_list(), key="balance_user")
    if not df_leaves.empty:
        user_df = df_leaves[df_leaves['employee_name'] == user_sel].copy()
        app_df = user_df[user_df['status'] == 'Approved'].copy()
        total_taken = 0
        if not app_df.empty:
            app_df['start_date'] = pd.to_datetime(app_df['start_date'])
            app_df['end_date'] = pd.to_datetime(app_df['end_date'])
            app_df['days_count'] = (app_df['end_date'] - app_df['start_date']).dt.days + 1
            total_taken = app_df['days_count'].sum()

        m1, m2 = st.columns(2)
        m1.metric("Days Taken (2026)", f"{total_taken} Days")
        m2.metric("Remaining Balance", f"{max(0, 24 - total_taken)} Days")
        st.dataframe(user_df[['created_at', 'leave_type', 'status']], use_container_width=True)

# --- TAB 3: ATTENDANCE & MOVEMENT (UPDATED) ---
with tabs[2]:
    st.subheader("🕒 Daily Time Office")
    att_user = st.selectbox("Identify Yourself", get_staff_list(), key="att_user")
    today = str(date.today())
    
    # Office Configuration
    OFFICE_START = "09:00 AM"
    GRACE_TIME = "09:15 AM"
    OFFICE_END = "05:30 PM"
    
    col_a, col_b = st.columns(2)
    
    # --- A. Daily Punch Logic ---
    with col_a:
        st.markdown(f"### 🏢 Daily Punch (Shift: {OFFICE_START} - {OFFICE_END})")
        att_data = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
        
        if not att_data:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                now = get_now_ist()
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute()
                st.rerun()
        else:
            log = att_data[0]
            p_in_dt = pd.to_datetime(log['punch_in']).astimezone(IST)
            p_in_time = p_in_dt.strftime('%I:%M %p')
            
            # Late Entry Check
            is_late = p_in_dt.time() > datetime.strptime(GRACE_TIME, "%I:%M %p").time()
            if is_late:
                st.error(f"🚩 Late Entry: {p_in_time}")
            else:
                st.success(f"✅ On Time: {p_in_time}")
            
            if not log.get('punch_out'):
                if st.button("🏁 PUNCH OUT", use_container_width=True):
                    conn.table("attendance_logs").update({"punch_out": get_now_ist().isoformat()}).eq("id", log['id']).execute()
                    st.rerun()
            else:
                p_out_time = pd.to_datetime(log['punch_out']).astimezone(IST).strftime('%I:%M %p')
                st.info(f"🏁 Punched Out: {p_out_time}")

    # --- B. Movement Logic (Same as before) ---
    with col_b:
        st.markdown("### 🚶 Movement Tracker")
        move_data = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        
        if not move_data:
            with st.form("move_form", clear_on_submit=True):
                m_reason = st.selectbox("Reason", ["Site Visit", "Vendor Visit", "Lunch", "Personal"])
                m_dest = st.text_input("Destination")
                if st.form_submit_button("📤 Log Exit"):
                    conn.table("movement_logs").insert({"employee_name": att_user, "reason": m_reason, "destination": m_dest}).execute()
                    st.rerun()
        else:
            m_log = move_data[0]
            st.warning(f"⚠️ Currently OUT for: {m_log['reason']}")
            if st.button("📥 Log Return", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", m_log['id']).execute()
                st.rerun()

# --- TAB 4: HR ADMIN PANEL ---
with tabs[3]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        df_all = get_leave_requests()
        st.subheader("📬 Pending Leave Approvals")
        if not df_all.empty and 'status' in df_all.columns:
            pending = df_all[df_all['status'] == 'Pending']
            if not pending.empty:
                for _, row in pending.iterrows():
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 2, 1])
                        c1.write(f"**{row['employee_name']}** ({row['leave_type']})")
                        c2.write(f"Reason: {row['reason']}")
                        if c3.button("Approve", key=f"app_{row['id']}"):
                            conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute()
                            st.rerun()
            else: st.success("No pending leaves.")
