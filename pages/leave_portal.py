import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz

# --- 1. SETUP & STYLE ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G HR | Leave Portal", layout="centered", page_icon="📅")

conn = st.connection("supabase", type=SupabaseConnection)

# Custom HR Styling
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    div.stButton > button:first-child { background-color: #007bff; color: white; border-radius: 5px; }
    .leave-metric { background-color: #ffffff; padding: 20px; border-radius: 10px; border: 1px solid #e1e4e8; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=10)
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
tab_apply, tab_status, tab_admin = st.tabs(["📝 Apply for Leave", "📊 My Leave Balance", "🔐 HR Admin Panel"])

# --- TAB 1: APPLICATION FORM ---
with tab_apply:
    st.subheader("Employee Leave Application")
    with st.form("leave_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        emp_name = col1.selectbox("Employee Name", get_staff_list())
        l_type = col2.selectbox("Leave Type", ["Casual Leave", "Sick Leave", "Earned Leave", "Maternity/Paternity", "Loss of Pay"])
        
        d1, d2 = st.columns(2)
        s_date = d1.date_input("Start Date", min_value=date.today())
        e_date = d2.date_input("End Date", min_value=date.today())
        
        reason = st.text_area("Reason for Leave", placeholder="Please provide specific details...")
        
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

# --- TAB 2: LEAVE BALANCE & STATUS ---
with tab_status:
    df_leaves = get_leave_requests()
    
    if not df_leaves.empty:
        # Filter for current employee view
        user_sel = st.selectbox("View Balance For:", get_staff_list())
        user_df = df_leaves[df_leaves['employee_name'] == user_sel]
        
        # Calculate Days Taken
        approved_df = user_df[user_df['status'] == 'Approved'].copy()
        if not approved_df.empty:
            approved_df['start_date'] = pd.to_datetime(approved_df['start_date'])
            approved_df['end_date'] = pd.to_datetime(approved_df['end_date'])
            # Calculation: (End - Start) + 1 to include both days
            approved_df['days_count'] = (approved_df['end_date'] - approved_df['start_date']).dt.days + 1
            total_taken = approved_df['days_count'].sum()
        else:
            total_taken = 0

        # Display Metrics
        m1, m2 = st.columns(2)
        with m1:
            st.markdown(f"<div class='leave-metric'><h3>Total Days Taken</h3><h2 style='color:#007bff;'>{total_taken}</h2></div>", unsafe_allow_html=True)
        with m2:
            # Assuming a standard 24 days annual leave for B&G Engineering
            remaining = max(0, 24 - total_taken)
            st.markdown(f"<div class='leave-metric'><h3>Remaining Balance</h3><h2 style='color:#27ae60;'>{remaining}</h2></div>", unsafe_allow_html=True)

        st.divider()
        st.markdown("#### 📋 Recent Application History")
        st.dataframe(user_df[['created_at', 'leave_type', 'start_date', 'end_date', 'status']], use_container_width=True, hide_index=True)
    else:
        st.info("No leave records found in the database.")

# --- TAB 3: HR ADMIN PANEL ---
with tab_admin:
    st.subheader("Admin Approval Desk")
    admin_pass = st.text_input("Admin Password", type="password")
    
    if admin_pass == "bgadmin": 
        df_admin = get_leave_requests()
        pending = df_admin[df_admin['status'] == 'Pending'] if not df_admin.empty else pd.DataFrame()
        
        if not pending.empty:
            for _, row in pending.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 2, 1])
                    c1.write(f"**{row['employee_name']}**")
                    c1.caption(f"{row['leave_type']}")
                    c2.write(f"📅 {row['start_date']} to {row['end_date']}")
                    if c3.button("Approve", key=f"a_{row['id']}"):
                        conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute()
                        st.cache_data.clear(); st.rerun()
                    if c3.button("Reject", key=f"r_{row['id']}"):
                        conn.table("leave_requests").update({"status": "Rejected"}).eq("id", row['id']).execute()
                        st.cache_data.clear(); st.rerun()
        else:
            st.success("No pending approvals.")
        
        st.divider()
        st.dataframe(df_admin, use_container_width=True)
