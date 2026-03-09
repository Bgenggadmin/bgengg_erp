import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px

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
    # --- 2. DATA PRE-PROCESSING (Calculations for Efficiency) ---
    # Ensure all date columns are in datetime format
    df_all['enquiry_date'] = pd.to_datetime(df_all['enquiry_date'])
    df_all['quote_date'] = pd.to_datetime(df_all['quote_date'])
    df_all['drawing_submit_date'] = pd.to_datetime(df_all['drawing_submit_date'])

    # Calculate Time Taken (Days)
    # Quote Time: From Enquiry Date to Date Quote was sent
    df_all['quote_time'] = (df_all['quote_date'] - df_all['enquiry_date']).dt.days
    
    # Drawing Time: From Enquiry Date to Date Drawing was Approved/Submitted
    df_all['drawing_time'] = (df_all['drawing_submit_date'] - df_all['enquiry_date']).dt.days

    # --- 3. EXECUTIVE KPIs ---
    total_value = df_all['estimated_value'].sum()
    won_projects = df_all[df_all['status'] == 'Won']
    conversion_rate = (len(won_projects) / len(df_all)) * 100
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Pipeline Value", f"₹{total_value:,.0f}")
    m2.metric("Orders Won", len(won_projects))
    m3.metric("Conversion Rate", f"{conversion_rate:.1f}%")
    m4.metric("Avg. Quote Lead Time", f"{df_all['quote_time'].mean():.1f} Days")

    st.divider()

    # --- 4. FOUNDER'S MASTER SUMMARY TABLE ---
    st.subheader("👥 Anchor Performance & Efficiency Summary")
    
    # Aggregating data per Anchor including the new time calculations
    founder_summary = df_all.groupby('anchor_person').agg(
        Total_Enquiries=('id', 'count'),
        Won_Orders=('status', lambda x: (x == 'Won').sum()),
        Total_Value=('estimated_value', 'sum'),
        Avg_Days_to_Quote=('quote_time', 'mean'),
        Avg_Days_to_Drawing=('drawing_time', 'mean'),
        Material_Triggers=('purchase_trigger', 'sum')
    ).reset_index()

    # Format the numbers for cleaner display
    founder_summary['Avg_Days_to_Quote'] = founder_summary['Avg_Days_to_Quote'].round(1)
    founder_summary['Avg_Days_to_Drawing'] = founder_summary['Avg_Days_to_Drawing'].round(1)
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
        st.subheader("Purchase Bottlenecks")
        p_data = df_all[df_all['purchase_trigger'] == True]
        if not p_data.empty:
            fig_p = px.bar(p_data, x='purchase_status', color='anchor_person',
                           title="Procurement Load by Status", barmode='group')
            st.plotly_chart(fig_p, use_container_width=True)
        else:
            st.info("No active purchase data to visualize.")

    # --- 6. TOP CRITICAL ITEMS (URGENT VIEW) ---
    st.divider()
    st.subheader("🚨 Priority Procurement List")
    critical_df = df_all[(df_all['purchase_trigger'] == True) & (df_all['purchase_status'] != 'Received')]
    if not critical_df.empty:
        # Displaying with Job No for clear shop floor identification
        st.dataframe(critical_df[['job_no', 'client_name', 'anchor_person', 'critical_materials', 'purchase_status']], 
                     use_container_width=True, hide_index=True)
    else:
        st.success("No pending critical materials. All clear!")

else:
    st.warning("No project data found. Ask Ammu and Kishore to log their enquiries.")
