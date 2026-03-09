import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Founder Analytics | BGEngg ERP", layout="wide", page_icon="📈")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

def get_all_data():
    res = conn.table("anchor_projects").select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_all = get_all_data()

st.title("📈 Founder's Strategic Dashboard")
st.markdown("---")

if not df_all.empty:
    # --- 2. EXECUTIVE KPIs ---
    total_value = df_all['estimated_value'].sum()
    won_projects = df_all[df_all['status'] == 'Won']
    conversion_rate = (len(won_projects) / len(df_all)) * 100
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Pipeline Value", f"₹{total_value:,.0f}")
    m2.metric("Orders Won", len(won_projects))
    m3.metric("Conversion Rate", f"{conversion_rate:.1f}%")
    m4.metric("Active Purchase Triggers", len(df_all[df_all['purchase_trigger'] == True]))

    st.divider()

    # --- 3. FOUNDER'S MASTER SUMMARY TABLE ---
    st.subheader("👥 Anchor Performance & Workflow Summary")
    
    # Aggregating data per Anchor for the Founder's Table
    founder_summary = df_all.groupby('anchor_person').agg(
        Total_Enquiries=('id', 'count'),
        Won_Orders=('status', lambda x: (x == 'Won').sum()),
        Total_Value=('estimated_value', 'sum'),
        Pending_Drawings=('drawing_status', lambda x: (x != 'Approved').sum()),
        Material_Triggers=('purchase_trigger', 'sum')
    ).reset_index()

    # Calculate Value per Anchor
    st.table(founder_summary)

    # --- 4. VISUAL ANALYTICS ---
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

    # --- 5. TOP CRITICAL ITEMS (URGENT VIEW) ---
    st.divider()
    st.subheader("🚨 Priority Procurement List")
    critical_df = df_all[(df_all['purchase_trigger'] == True) & (df_all['purchase_status'] != 'Received')]
    if not critical_df.empty:
        st.dataframe(critical_df[['client_name', 'anchor_person', 'critical_materials', 'purchase_status', 'purchase_remarks']], 
                     use_container_width=True, hide_index=True)
    else:
        st.success("No pending critical materials. All clear!")

else:
    st.warning("No project data found. Ask Ammu and Kishore to log their enquiries.")
