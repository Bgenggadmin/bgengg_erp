import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Founder Analytics | BGEngg ERP", layout="wide", page_icon="📈")

# --- 0. PASSWORD PROTECTION ---
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if st.session_state["password_correct"]:
        return True

    st.title("🔐 Founder Access Only")
    placeholder = st.empty()
    with placeholder.form("login_form"):
        pwd = st.text_input("Enter Access Code", type="password")
        if st.form_submit_button("Unlock Dashboard"):
            if pwd == "9025":
                st.session_state["password_correct"] = True
                placeholder.empty()
                st.rerun()
            else:
                st.error("🚫 Incorrect Code. Access Denied.")
    return False

if not check_password():
    st.stop()

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=10)
def get_all_data():
    res = conn.table("anchor_projects").select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_all = get_all_data()

# --- 2. DASHBOARD START ---
st.title("📈 Founder's Strategic Dashboard")
st.markdown("---")

if not df_all.empty:
    # DATA PRE-PROCESSING
    today = pd.to_datetime(datetime.now().date())
    df_all['enquiry_date'] = pd.to_datetime(df_all['enquiry_date']).dt.tz_localize(None)
    df_all['quote_date'] = pd.to_datetime(df_all['quote_date']).dt.tz_localize(None)
    df_all['drawing_submit_date'] = pd.to_datetime(df_all['drawing_submit_date']).dt.tz_localize(None)

    # Metrics
    df_all['quote_lead_time'] = (df_all['quote_date'] - df_all['enquiry_date']).dt.days
    df_all['drawing_lead_time'] = (df_all['drawing_submit_date'] - df_all['enquiry_date']).dt.days
    df_all['aging_days'] = df_all.apply(
        lambda x: (today - x['enquiry_date']).days if x['status'] not in ['Won', 'Lost'] else None, axis=1
    )

    # EXECUTIVE KPIs
    won_mask = df_all['status'] == 'Won'
    total_pipeline = df_all['estimated_value'].sum()
    actual_won_val = df_all[won_mask]['estimated_value'].sum()
    conversion_rate = (len(df_all[won_mask]) / len(df_all)) * 100 if len(df_all) > 0 else 0
    avg_aging = df_all['aging_days'].mean() if not df_all['aging_days'].dropna().empty else 0
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Pipeline", f"₹{total_pipeline:,.0f}")
    m2.metric("Orders Won", len(df_all[won_mask]), f"₹{actual_won_val:,.0f}")
    m3.metric("Conversion Rate", f"{conversion_rate:.1f}%")
    m4.metric("Avg. Open Age", f"{avg_aging:.1f} Days")

    st.divider()

    # MASTER SUMMARY TABLE (PERFORMANCE & EFFICIENCY)
    st.subheader("👥 Anchor Performance & Efficiency Summary")
    
    summary_list = []
    for anchor in df_all['anchor_person'].unique():
        pdf = df_all[df_all['anchor_person'] == anchor]
        won_pdf = pdf[pdf['status'] == 'Won']
        
        q_val = pdf['estimated_value'].sum()
        w_val = won_pdf['estimated_value'].sum()
        
        summary_list.append({
            "Anchor": anchor,
            "Enquiries": len(pdf),
            "Won": len(won_pdf),
            "Quoted Value": q_val,
            "Won Value": w_val,
            "Value Win %": (w_val / q_val * 100) if q_val > 0 else 0,
            "Avg Quote Lead": pdf['quote_lead_time'].mean(),
            "Live Aging": pdf['aging_days'].mean()
        })

    founder_summary = pd.DataFrame(summary_list)
    
    # Formatting for display
    styled_df = founder_summary.copy()
    styled_df['Quoted Value'] = styled_df['Quoted Value'].apply(lambda x: f"₹{x:,.0f}")
    styled_df['Won Value'] = styled_df['Won Value'].apply(lambda x: f"₹{x:,.0f}")
    styled_df['Value Win %'] = styled_df['Value Win %'].map("{:.1f}%".format)
    styled_df[['Avg Quote Lead', 'Live Aging']] = styled_df[['Avg Quote Lead', 'Live Aging']].fillna(0).round(1)

    st.table(styled_df)

    # VISUALS
    col_left, col_right = st.columns(2)
    with col_left:
        st.subheader("Actual Revenue Contribution (WON)")
        # Filter for WON only so Founder sees real money, not just quotes
        fig_rev = px.pie(df_all[won_mask], values='estimated_value', names='anchor_person', hole=0.4)
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
    st.warning("No data found in Supabase.")
