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
    .status-pending { color: #f39c12; font-weight: bold; }
    .status-approved { color: #27ae60; font-weight: bold; }
    .status-rejected { color: #e74c3c; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=10)
def get_leave_requests():
    res = conn.table("leave_requests").select("*").order("applied_on", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def get_staff_list():
    res = conn.table("master_staff").select("name").execute()
    return [s['name'] for s in res.data] if res.data else ["Select Employee"]

# --- 3. NAVIGATION ---
tab_apply, tab_status, tab_admin = st.tabs(["📝 Apply for Leave", "📋 My Request Status", "🔐 HR Admin Panel"])

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
                    "employee_name": emp_name,
                    "leave_type": l_type,
                    "start_date": str(s_date),
                    "end_date": str(e_date),
                    "reason": reason,
                    "status": "Pending"
                }
                conn.table("leave_requests").insert(payload).execute()
                st.success("✅ Application submitted successfully. Awaiting HR approval.")
                st.cache_data.clear()

# --- TAB 2: PERSONAL STATUS ---
with tab_status:
    st.subheader("Recent Applications")
    df_leaves = get_leave_requests()
    if not df_leaves.empty:
        # Filter for non-admin view (Simple summary)
        st.dataframe(
            df_leaves[['applied_on', 'leave_type', 'start_date', 'end_date', 'status']].head(10),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No leave history found.")

# --- TAB 3: HR ADMIN PANEL ---
with tab_admin:
    st.subheader("Leave Approvals (Admin Only)")
    admin_pass = st.text_input("Enter Admin Password", type="password")
    
    if admin_pass == "bgadmin":  # Simple password protection
        df_admin = get_leave_requests()
        pending_leaves = df_admin[df_admin['status'] == 'Pending']
        
        if not pending_leaves.empty:
            for _, row in pending_leaves.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 2, 1])
                    c1.write(f"**{row['employee_name']}**")
                    c1.caption(f"Type: {row['leave_type']}")
                    c2.write(f"📅 {row['start_date']} to {row['end_date']}")
                    c2.caption(f"Reason: {row['reason']}")
                    
                    # Approval Buttons
                    if c3.button("✅ Approve", key=f"app_{row['id']}"):
                        conn.table("leave_requests").update({"status": "Approved"}).eq("id", row['id']).execute()
                        st.rerun()
                    if c3.button("❌ Reject", key=f"rej_{row['id']}"):
                        conn.table("leave_requests").update({"status": "Rejected"}).eq("id", row['id']).execute()
                        st.rerun()
        else:
            st.success("All pending requests have been processed.")
            
        st.divider()
        st.markdown("### 📊 Leave History Report")
        st.dataframe(df_admin, use_container_width=True, hide_index=True)
    elif admin_pass:
        st.error("Incorrect Admin Password")
