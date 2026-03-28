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

st.set_page_config(page_title="B&G HR | Leave & Attendance", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SMART TIME UTILITY ---
def to_ist(series):
    """Universal converter: Handles both TZ-aware and Naive timestamps safely."""
    if series is None or len(series) == 0:
        return series
    dt = pd.to_datetime(series)
    # If Supabase sends naive (no TZ), assume UTC and localize
    if dt.dt.tz is None:
        dt = dt.dt.tz_localize('UTC')
    # Convert to Kolkata and return only the Time object
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
        return [s['name'] for s in res.data] if res.data else ["Admin", "Staff"]
    except: return ["Admin", "Staff"]

# --- 4. NAVIGATION ---
tabs = st.tabs(["📝 Leave Application", "📊 My Balance", "🕒 Attendance & Movement", "🔐 HR Admin Panel"])

# --- TAB 1 & 2 (Leave Logic remains same as previous working versions) ---

# --- TAB 3: ATTENDANCE & MOVEMENT ---
with tabs[2]:
    st.subheader("🕒 Daily Time Office")
    att_user = st.selectbox("Identify Yourself", get_staff_list(), key="att_user")
    today = str(date.today())
    
    col_a, col_b = st.columns(2)
    
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
            # Use the Smart Time Utility
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

    # B. MOVEMENT REGISTER
    with col_b:
        st.markdown("### 🚶 Movement Register")
        active_move = conn.table("movement_logs").select("*").eq("employee_name", att_user).is_("return_time", "null").execute().data
        
        if not active_move:
            with st.form("move_form", clear_on_submit=True):
                reason = st.selectbox("Reason", ["Inter-Unit Transfer", "Site Delivery", "Lunch", "Personal"])
                dest = st.text_input("Destination")
                if st.form_submit_button("📤 TIME OUT"):
                    conn.table("movement_logs").insert({"employee_name": att_user, "reason": reason, "destination": dest.upper(), "exit_time": get_now_ist().isoformat()}).execute()
                    st.rerun()
        else:
            m_log = active_move[0]
            st.warning(f"⚠️ Currently at **{m_log['destination']}**")
            if st.button("📥 TIME IN", use_container_width=True, type="primary"):
                conn.table("movement_logs").update({"return_time": get_now_ist().isoformat()}).eq("id", m_log['id']).execute()
                st.rerun()

# --- TAB 4: HR ADMIN PANEL ---
with tabs[3]:
    admin_pass = st.text_input("Admin Password", type="password")
    if admin_pass == "bgadmin":
        st.subheader("📊 Today's Discipline Summary")
        
        # 1. Fetch Today's Attendance
        today_att = conn.table("attendance_logs").select("*").eq("work_date", today).execute().data
        if today_att:
            tdf = pd.DataFrame(today_att)
            # Apply Smart Time Utility to whole columns
            tdf['In Time'] = to_ist(tdf['punch_in'])
            tdf['Out Time'] = to_ist(tdf['punch_out'])
            
            tdf['Status'] = tdf['In Time'].apply(lambda x: "🚩 LATE" if x > GRACE_IN else "✅ OK")
            
            # WORK HOURS CALCULATION
            def calc_hours(row):
                if pd.notnull(row['punch_out']):
                    # Convert to full datetime for subtraction
                    start = pd.to_datetime(row['punch_in'])
                    end = pd.to_datetime(row['punch_out'])
                    diff = (end - start).total_seconds() / 3600
                    return f"{diff:.2f} hrs"
                return "Active"
            
            tdf['Work Duration'] = tdf.apply(calc_hours, axis=1)
            
            st.table(tdf[['employee_name', 'In Time', 'Out Time', 'Status', 'Work Duration']])
        else:
            st.info("No attendance logs for today.")
