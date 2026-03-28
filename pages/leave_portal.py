import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz

# --- 1. SETUP & CONSTANTS ---
IST = pytz.timezone('Asia/Kolkata')
OFFICE_IN = time(9, 0)
GRACE_IN = time(9, 15)
OFFICE_OUT = time(17, 30)

st.set_page_config(page_title="B&G HR | Leave & Attendance", layout="wide", page_icon="📅")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SMART TIME UTILITY ---
def to_ist(series):
    """Universal converter: Handles both TZ-aware and Naive timestamps safely."""
    if series is None or len(series) == 0:
        return series
    dt = pd.to_datetime(series)
    if dt.dt.tz is None:
        dt = dt.dt.tz_localize('UTC')
    return dt.dt.tz_convert(IST).dt.time

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
    except:
        return ["Admin", "Staff Member"]

# --- 4. NAVIGATION ---
tabs = st.tabs(["📝 Leave Application", "📊 My Balance", "🕒 Attendance & Movement", "🔐 HR Admin Panel"])

# --- TAB 1: LEAVE APPLICATION ---
with tabs[0]:
    st.subheader("New Leave Application")
    with st.form("leave_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        emp_name = col1.selectbox("Employee Name", get_staff_list())
        l_type = col2.selectbox("Leave Type", ["Casual Leave", "Sick Leave", "Earned Leave", "Maternity/Paternity", "Loss of Pay"])
        
        d1, d2 = st.columns(2)
        s_date = d1.date_input("Start Date", min_value=date.today())
        e_date = d2.date_input("End Date", min_value=date.today())
        
        reason = st.text_area("Reason for Leave")
        
        if st.form_submit_button("Submit Application"):
            if s_date > e_date:
                st.error("Error: End Date cannot be before Start Date.")
            elif not reason:
                st.warning("Please provide a reason.")
            else:
                payload = {
                    "employee_name": emp_name, "leave_type": l_type,
                    "start_date": str(s_date), "end_date": str(e_date),
                    "reason": reason, "status": "Pending"
                }
                conn.table("leave_requests").insert(payload).execute()
                st.success("✅ Application submitted successfully.")
                st.cache_data.clear()
                st.rerun()

# --- TAB 2: MY BALANCE & WITHDRAWAL ---
with tabs[1]:
    st.subheader("Leave Balance & Request Status")
    df_leaves = get_leave_requests()
    user_sel = st.selectbox("View Records for:", get_staff_list(), key="balance_user")
    
    if not df_leaves.empty:
        user_df = df_leaves[df_leaves['employee_name'] == user_sel].copy()
        
        # Balance Calculation
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

        st.divider()
        st.markdown("#### 📋 Request History")
        
        # Individual Request Display with Withdraw Button
        for _, r in user_df.head(10).iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
                status_color = "🟠" if r['status'] == "Pending" else "🟢" if r['status'] == "Approved" else "🔴"
                c1.write(f"{status_color} **{r['leave_type']}**")
                c2.write(f"📅 {r['start_date']} to {r['end_date']}")
                c3.write(f"**{r['status']}**")
                
                if r['status'] == "Pending":
                    if c4.button("🗑️ Withdraw", key=f"wd_{r['id']}"):
                        conn.table("leave_requests").delete().eq("id", r['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
    else:
        st.info("No leave records found.")

# --- TAB 3: ATTENDANCE & MOVEMENT ---
with tabs[2]:
    st.subheader("🕒 Daily Time Office")
    att_user = st.selectbox("Identify Yourself", get_staff_list(), key="att_user")
    today = str(date.today())
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.markdown("### 🏢 Shift Punch (9:00 AM - 5:30 PM)")
        att_data = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
        
        if not att_data:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute()
                st.rerun()
        else:
            log = att_data[0]
            p_in = to_ist(pd.Series([log['punch_in']]))[0]
            if p_in > GRACE_IN: st.error(f"🚩 Late Entry: {p_in.strftime('%I:%M %p')}")
            else: st.success(f"✅ On Time: {p_in.strftime('%I:%M %p')}")
            
            if not log.get('punch_out'):
                if st.button("🏁 PUNCH OUT", use_container_width=True):
                    conn.table("attendance_logs").update({"punch_out": get_now_ist().isoformat()}).eq("id", log['id']).execute()
                    st.rerun()
            else:
                p_out = to_ist(pd.Series([log['punch_out']]))[0]
                if p_out < OFFICE_OUT: st.warning(f"⚠️ Early Departure: {p_out.strftime('%I:%M %p')}")
                else: st.success(f"🏁 Shift Ended: {p_out.strftime('%I:%M %p')}")

    with col_b:
        st.markdown("### 🚶 Movement Register (Time Out/In)")
        active_move = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        
        if not active_move:
            with st.form("move_form", clear_on_submit=True):
                reason = st.selectbox("Reason", ["Inter-Unit Transfer", "Site Delivery", "Vendor Visit", "Lunch", "Personal"])
                dest = st.text_input("Destination / Target Unit")
                if st.form_submit_button("📤 LOG TIME OUT"):
                    if dest:
                        conn.table("movement_logs").insert({"employee_name": att_user, "reason": reason, "destination": dest.upper(), "exit_time": get_now_ist().isoformat()}).execute()
                        st.rerun()
                    else: st.error("Please enter a destination.")
        else:
            m_log = active_move[0]
            out_t = to_ist(pd.Series([m_log['exit_time']]))[0]
            st.warning(f"⚠️ Currently at **{m_log['destination']}** (Out since {out_t.strftime('%I:%M %p')})")
            if st.button("📥 LOG TIME IN", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", m_log['id']).execute()
                st.rerun()

# --- TAB 4: HR ADMIN PANEL ---
with tabs[3]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        st.subheader("📊 Today's Discipline Summary")
        today_att = conn.table("attendance_logs").select("*").eq("work_date", today).execute().data
        if today_att:
            tdf = pd.DataFrame(today_att)
            tdf['In Time'] = to_ist(tdf['punch_in'])
            tdf['Out Time'] = to_ist(tdf['punch_out'])
            tdf['Status'] = tdf['In Time'].apply(lambda x: "🚩 LATE" if x > GRACE_IN else "✅ OK")
            
            def calc_hours(row):
                if pd.notnull(row['punch_out']):
                    diff = (pd.to_datetime(row['punch_out']) - pd.to_datetime(row['punch_in'])).total_seconds() / 3600
                    return f"{diff:.2f} hrs"
                return "Active"
            tdf['Work Duration'] = tdf.apply(calc_hours, axis=1)
            st.table(tdf[['employee_name', 'In Time', 'Out Time', 'Status', 'Work Duration']])
        
        st.divider()
        st.subheader("📬 Pending Leave Approvals")
        df_all = get_leave_requests()
        if not df_all.empty:
            pending = df_all[df_all['status'] == 'Pending']
            for _, row in pending.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 2, 1])
                    c1.write(f"**{row['employee_name']}** ({row['leave_type']})")
                    c2.write(f"Reason: {row['reason']}")
                    if c3.button("Approve", key=f"app_{row['id']}"):
                        conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute()
                        st.rerun()
