import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Founder Analytics | BGEngg ERP", layout="wide", page_icon="📈")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

def get_all_data():
    res = conn.table("anchor_projects").select("*").execute()
    if not res.data:
        return pd.DataFrame()
    return pd.DataFrame(res.data)

df_all = get_all_data()

st.title("📈 Founder's Strategic Dashboard")
st.markdown("---")

if not df_all.empty:
    # --- 2. DATA PRE-PROCESSING & AGING LOGIC ---
    today = pd.to_datetime(datetime.now().date())
    df_all['enquiry_date'] = pd.to_datetime(df_all['enquiry_date'])
    df_all['quote_date'] = pd.to_datetime(df_all['quote_date'])
    df_all['drawing_submit_date'] = pd.to_datetime(df_all['drawing_submit_date'])

    # A: Historical Lead Times (For completed steps)
    df_all['quote_lead_time'] = (df_all['quote_date'] - df_all['enquiry_date']).dt.days
    df_all['drawing_lead_time'] = (df_all['drawing_submit_date'] - df_all['enquiry_date']).dt.days

    # B: Live Aging (For items currently pending)
    # If project is not Won/Lost, calculate days since it first entered the system
    df_all['aging_days'] = df_all.apply(
        lambda x: (today - x['enquiry_date']).days if x['status'] not in ['Won', 'Lost'] else None, 
        axis=1
    )

    # --- 3. EXECUTIVE KPIs ---
    total_value = df_all['estimated_value'].sum()
    won_projects = df_all[df_all['status'] == 'Won']
    conversion_rate = (len(won_projects) / len(df_all)) * 100 if len(df_all) > 0 else 0
    avg_aging = df_all['aging_days'].mean() if not df_all['aging_days'].dropna().empty else 0
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Pipeline Value", f"₹{total_value:,.0f}")
    m2.metric("Orders Won", len(won_projects))
    m3.metric("Conversion Rate", f"{conversion_rate:.1f}%")
    m4.metric("Avg. Open Enquiry Age", f"{avg_aging:.1f} Days", delta_color="inverse")

    st.divider()

    # --- 4. FOUNDER'S MASTER SUMMARY TABLE ---
    st.subheader("👥 Anchor Performance & Efficiency Summary")
    
    # Aggregating data per Anchor
    founder_summary = df_all.groupby('anchor_person').agg(
        Total_Enquiries=('id', 'count'),
        Won_Orders=('status', lambda x: (x == 'Won').sum()),
        Total_Value=('estimated_value', 'sum'),
        Avg_Days_to_Quote=('quote_lead_time', 'mean'),
        Avg_Days_to_Drawing=('drawing_lead_time', 'mean'),
        Current_Avg_Aging=('aging_days', 'mean') # How old are their current pending items?
    ).reset_index()

    # Formatting for display
    founder_summary['Avg_Days_to_Quote'] = founder_summary['Avg_Days_to_Quote'].fillna(0).round(1)
    founder_summary['Avg_Days_to_Drawing'] = founder_summary['Avg_Days_to_Drawing'].fillna(0).round(1)
    founder_summary['Current_Avg_Aging'] = founder_summary['Current_Avg_Aging'].fillna(0).round(1)
    founder_summary['Total_Value'] = founder_summary['Total_Value'].apply(lambda x: f"₹{x:,.0f}")

    st.table(founder_summary)

    # --- 5. VISUAL ANALYTICS ---
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Revenue Contribution")
        fig_rev = px.pie(df_all, values='estimated_value', names='anchor_person', 
                         title="Value Share by Anchor", hole=0.4,
                         color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig_rev, use_container_width=True)

    with col_right:
        st.subheader("Live Aging Distribution")
        # Visualizing how old the current pending projects are
        fig_age = px.histogram(df_all[df_all['aging_days'].notnull()], x="aging_days", 
                               color="anchor_person", nbins=10,
                               title="Count of Projects by Days Old",
                               labels={'aging_days': 'Days since Enquiry'})
        st.plotly_chart(fig_age, use_container_width=True)

    # --- 6. TOP CRITICAL ITEMS ---
    st.divider()
    st.subheader("🚨 Priority Procurement List")
    critical_df = df_all[(df_all['purchase_trigger'] == True) & (df_all['purchase_status'] != 'Received')]
    if not critical_df.empty:
        st.dataframe(critical_df[['job_no', 'client_name', 'anchor_person', 'critical_materials', 'purchase_status']], 
                     use_container_width=True, hide_index=True)
    else:
        st.success("No pending critical materials. All clear!")

else:
    st.warning("No project data found. Data is required to calculate Aging.")
