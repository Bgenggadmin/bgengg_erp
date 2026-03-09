import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Founder Analytics | BGEngg ERP", layout="wide", page_icon="📈")

# --- 0. PASSWORD PROTECTION ---
def check_password():
    """Returns True if the user had the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if st.session_state["password_correct"]:
        return True

    # Show input for password
    st.title("🔐 Founder Access Only")
    placeholder = st.empty()
    with placeholder.form("login_form"):
        pwd = st.text_input("Enter Access Code", type="password")
        if st.form_submit_button("Unlock Dashboard"):
            if pwd == "9025":
                st.session_state["password_correct"] = True
                placeholder.empty() # Clear the form
                st.rerun()
            else:
                st.error("🚫 Incorrect Code. Access Denied.")
    return False

if not check_password():
    st.stop()  # Do not run the rest of the page if password isn't correct

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

def get_all_data():
    res = conn.table("anchor_projects").select("*").execute()
    if not res.data:
        return pd.DataFrame()
    return pd.DataFrame(res.data)

df_all = get_all_data()

# --- 2. REST OF THE DASHBOARD ---
st.title("📈 Founder's Strategic Dashboard")
st.markdown("---")

if not df_all.empty:
    # DATA PRE-PROCESSING & AGING LOGIC
    today = pd.to_datetime(datetime.now().date())
    df_all['enquiry_date'] = pd.to_datetime(df_all['enquiry_date'])
    df_all['quote_date'] = pd.to_datetime(df_all['quote_date'])
    df_all['drawing_submit_date'] = pd.to_datetime(df_all['drawing_submit_date'])

    # Historical Lead Times
    df_all['quote_lead_time'] = (df_all['quote_date'] - df_all['enquiry_date']).dt.days
    df_all['drawing_lead_time'] = (df_all['drawing_submit_date'] - df_all['enquiry_date']).dt.days

    # Live Aging
    df_all['aging_days'] = df_all.apply(
        lambda x: (today - x['enquiry_date']).days if x['status'] not in ['Won', 'Lost'] else None, 
        axis=1
    )

    # EXECUTIVE KPIs
    total_value = df_all['estimated_value'].sum()
    won_projects = df_all[df_all['status'] == 'Won']
    conversion_rate = (len(won_projects) / len(df_all)) * 100 if len(df_all) > 0 else 0
    avg_aging = df_all['aging_days'].mean() if not df_all['aging_days'].dropna().empty else 0
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Pipeline Value", f"₹{total_value:,.0f}")
    m2.metric("Orders Won", len(won_projects))
    m3.metric("Conversion Rate", f"{conversion_rate:.1f}%")
    m4.metric("Avg. Open Enquiry Age", f"{avg_aging:.1f} Days")

    st.divider()

    # MASTER SUMMARY TABLE
    st.subheader("👥 Anchor Performance & Efficiency Summary")
    
    founder_summary = df_all.groupby('anchor_person').agg(
        Total_Enquiries=('id', 'count'),
        Won_Orders=('status', lambda x: (x == 'Won').sum()),
        Total_Value=('estimated_value', 'sum'),
        Avg_Days_to_Quote=('quote_lead_time', 'mean'),
        Avg_Days_to_Drawing=('drawing_lead_time', 'mean'),
        Current_Avg_Aging=('aging_days', 'mean')
    ).reset_index()

    founder_summary['Avg_Days_to_Quote'] = founder_summary['Avg_Days_to_Quote'].fillna(0).round(1)
    founder_summary['Avg_Days_to_Drawing'] = founder_summary['Avg_Days_to_Drawing'].fillna(0).round(1)
    founder_summary['Current_Avg_Aging'] = founder_summary['Current_Avg_Aging'].fillna(0).round(1)
    founder_summary['Total_Value'] = founder_summary['Total_Value'].apply(lambda x: f"₹{x:,.0f}")

    st.table(founder_summary)

    # VISUALS
    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("Revenue Contribution")
        fig_rev = px.pie(df_all, values='estimated_value', names='anchor_person', hole=0.4)
        st.plotly_chart(fig_rev, use_container_width=True)

    with col_right:
        st.subheader("Live Aging Distribution")
        fig_age = px.histogram(df_all[df_all['aging_days'].notnull()], x="aging_days", color="anchor_person", nbins=10)
        st.plotly_chart(fig_age, use_container_width=True)

    # PRIORITY LIST
    st.divider()
    st.subheader("🚨 Priority Procurement List")
    critical_df = df_all[(df_all['purchase_trigger'] == True) & (df_all['purchase_status'] != 'Received')]
    if not critical_df.empty:
        st.dataframe(critical_df[['job_no', 'client_name', 'anchor_person', 'critical_materials', 'purchase_status']], 
                     use_container_width=True, hide_index=True)

else:
    st.warning("No project data found.")
