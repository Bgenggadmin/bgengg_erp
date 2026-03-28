import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz
import plotly.express as px

# --- 1. SETUP & STYLE ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G HR | Leave Portal", layout="centered", page_icon="📅")

conn = st.connection("supabase", type=SupabaseConnection)

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

# --- TAB 1: APPLICATION FORM (Same as before) ---
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
            else:
                payload = {
                    "employee_name": emp_name, "leave_type": l_type,
                    "start_date": str(s_date), "end_date": str(e_date),
                    "reason": reason, "status": "Pending"
                }
                conn.table("leave_requests").insert(payload).execute()
                st.success("✅ Application submitted.")
                st.cache_data.clear()
                st.rerun()

# --- TAB 2: LEAVE BALANCE & PERSONAL CHART ---
with tab_status:
    df_leaves = get_leave_requests()
    if not df_leaves.empty:
        user_sel = st.selectbox("View Records for:", get_staff_list())
        user_df = df_leaves[df_leaves['employee_name'] == user_sel].copy()
        
        # Calculate consumption
        app_df = user_df[user_df['status'] == 'Approved'].copy()
        if not app_df.empty:
            app_df['start_date'] = pd.to_datetime(app_df['start_date'])
            app_df['end_date'] = pd.to_datetime(app_df['end_date'])
            app_df['days_count'] = (app_df['end_date'] - app_df['start_date']).dt.days + 1
            app_df['Month'] = app_df['start_date'].dt.strftime('%b')
            total_taken = app_df['days_count'].sum()
        else:
            total_taken = 0

        m1, m2 = st.columns(2)
        m1.metric("Days Taken (2026)", f"{total_taken} Days")
        m2.metric("Remaining Balance", f"{max(0, 24 - total_taken)} Days")

        if total_taken > 0:
            st.markdown("#### 📈 Your Monthly Leave Trend")
            month_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            fig = px.bar(app_df.groupby('Month')['days_count'].sum().reindex(month_order).reset_index(), 
                         x='Month', y='days_count', text_auto=True, color_discrete_sequence=['#007bff'])
            st.plotly_chart(fig, use_container_width=True)

        st.dataframe(user_df[['created_at', 'leave_type', 'status']], use_container_width=True)

# --- TAB 3: HR ADMIN PANEL ---
with tab_admin:
    st.subheader("HR Management Console")
    admin_pass = st.text_input("Admin Password", type="password")
    
    if admin_pass == "bgadmin": 
        df_all = get_leave_requests()
        
        # FIX: Check if the dataframe is empty or missing the 'status' column
        if not df_all.empty and 'status' in df_all.columns:
            
            # 📊 GLOBAL ANALYTICS SECTION
            st.markdown("### 🏢 Company-wide Leave Insights")
            approved_all = df_all[df_all['status'] == 'Approved'].copy()
            
            if not approved_all.empty:
                # ... rest of your charting code ...
                st.plotly_chart(fig_global, use_container_width=True)
            
            st.divider()
            st.subheader("📬 Pending Approvals")
            pending = df_all[df_all['status'] == 'Pending']
            
            if not pending.empty:
                for _, row in pending.iterrows():
                    with st.container(border=True):
                        st.write(f"**{row['employee_name']}** ({row['leave_type']})")
                        # ... rest of approval buttons ...
            else:
                st.success("No pending requests.")
        else:
            st.warning("⚠️ No data found in 'leave_requests' table. Please submit a leave request first.")
