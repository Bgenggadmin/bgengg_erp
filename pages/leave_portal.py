import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time
import pytz
import plotly.express as px

# --- 1. SETUP & STYLE ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G HR | Leave & Attendance", layout="wide", page_icon="📅")

conn = st.connection("supabase", type=SupabaseConnection)

# Office Timings
OFFICE_IN = time(9, 0)      # 9:00 AM
GRACE_IN = time(9, 15)     # 9:15 AM
OFFICE_OUT = time(17, 30)   # 5:30 PM

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
tabs = st.tabs(["📝 Leave Application", "📊 My Balance", "🕒 Attendance & Movement Register", "🔐 HR Admin Panel"])

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

# --- TAB 3: ATTENDANCE & MOVEMENT ---
with tabs[2]:
    st.subheader("🕒 Daily Time Office & Movement Register")
    att_user = st.selectbox("Identify Yourself", get_staff_list(), key="att_user")
    today = str(date.today())
    
    col_a, col_b = st.columns(2)
    
    # --- A. Daily Punch (Shift 9 AM - 5:30 PM) ---
    with col_a:
        st.markdown("### 🏢 Shift Punch")
        att_data = conn.table("attendance_logs").select("*").eq("employee_name", att_user).eq("work_date", today).execute().data
        
        if not att_data:
            if st.button("🚀 PUNCH IN", use_container_width=True, type="primary"):
                conn.table("attendance_logs").insert({"employee_name": att_user, "work_date": today}).execute()
                st.rerun()
        else:
            log = att_data[0]
            p_in = pd.to_datetime(log['punch_in']).astimezone(IST)
            
            # Late Logic
            if p_in.time() > GRACE_IN:
                st.error(f"🚩 Late Entry: {p_in.strftime('%I:%M %p')}")
            else:
                st.success(f"✅ On Time: {p_in.strftime('%I:%M %p')}")
            
            if not log.get('punch_out'):
                if st.button("🏁 PUNCH OUT", use_container_width=True):
                    now = get_now_ist()
                    conn.table("attendance_logs").update({"punch_out": now.isoformat()}).eq("id", log['id']).execute()
                    st.rerun()
            else:
                p_out = pd.to_datetime(log['punch_out']).astimezone(IST)
                # Early Out Logic
                if p_out.time() < OFFICE_OUT:
                    st.warning(f"⚠️ Early Departure: {p_out.strftime('%I:%M %p')}")
                else:
                    st.success(f"🏁 Shift Ended: {p_out.strftime('%I:%M %p')}")

    # --- B. Movement Register (Time Out / Time In) ---
    with col_b:
        st.markdown("### 🚶 Movement Register")
        active_move = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        
        if not active_move:
            with st.form("movement_form", clear_on_submit=True):
                m_reason = st.selectbox("Reason", ["Inter-Unit Transfer", "Site Delivery", "Vendor Visit", "Lunch", "Personal"])
                m_dest = st.text_input("Destination / Target Unit")
                if st.form_submit_button("📤 LOG TIME OUT"):
                    if m_dest:
                        conn.table("movement_logs").insert({
                            "employee_name": att_user, "reason": m_reason, 
                            "destination": m_dest.upper(), "exit_time": get_now_ist().isoformat()
                        }).execute()
                        st.rerun()
                    else: st.error("Specify destination.")
        else:
            m_log = active_move[0]
            out_t = pd.to_datetime(m_log['exit_time']).astimezone(IST)
            st.warning(f"⚠️ At **{m_log['destination']}** since {out_t.strftime('%I:%M %p')}")
            if st.button("📥 LOG TIME IN", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", m_log['id']).execute()
                st.rerun()

# --- TAB 4: HR ADMIN PANEL ---
with tabs[3]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        st.subheader("📊 Daily Discipline Summary")
        
        # --- FIXED HR ADMIN LOGIC ---
        today_att = conn.table("attendance_logs").select("*").eq("work_date", today).execute().data
        if today_att:
            tdf = pd.DataFrame(today_att)
            
            # Convert Punch In (Localize to UTC first, then convert to IST)
            tdf['in_time'] = pd.to_datetime(tdf['punch_in']).dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata').dt.time
            
            # Convert Punch Out safely (Handling potential Nulls/NaNs)
            tdf['out_time'] = pd.to_datetime(tdf['punch_out']).apply(
                lambda x: x.tz_localize('UTC').tz_convert('Asia/Kolkata').time() if pd.notnull(x) else None
            )
            
            # Status Logic
            tdf['Status'] = tdf['in_time'].apply(lambda x: "🚩 LATE" if x > GRACE_IN else "✅ OK")
            
            st.markdown("#### 📑 Today's Attendance Sheet")
            st.table(tdf[['employee_name', 'in_time', 'out_time', 'Status']])
        
        st.divider()
        st.subheader("📬 Pending Leaves")
        df_all = get_leave_requests()
        if not df_all.empty and 'status' in df_all.columns:
            pending = df_all[df_all['status'] == 'Pending']
            for _, row in pending.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 2, 1])
                    c1.write(f"**{row['employee_name']}**")
                    c2.write(f"Reason: {row['reason']}")
                    if c3.button("Approve", key=f"app_{row['id']}"):
                        conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute()
                        st.rerun()
