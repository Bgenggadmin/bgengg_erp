import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Founder Analytics | BGEngg", layout="wide", page_icon="📈")

conn = st.connection("supabase", type=SupabaseConnection)

def get_all_data():
    res = conn.table("anchor_projects").select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_all = get_all_data()

st.title("📈 Founder's Strategic Analytics")
st.markdown("---")

if not df_all.empty:
    # --- ROW 1: REVENUE & PIPELINE HEALTH ---
    col1, col2, col3 = st.columns(3)
    total_val = df_all['estimated_value'].sum()
    won_val = df_all[df_all['status'] == 'Won']['estimated_value'].sum()
    
    col1.metric("Total Pipeline Value", f"₹{total_val:,.0f}")
    col2.metric("Orders Secured", f"₹{won_val:,.0f}")
    col3.metric("Conversion Efficiency", f"{(won_val/total_val*100 if total_val > 0 else 0):.1f}%")

    st.divider()

    # --- ROW 2: ANCHOR COMPARISON ---
    st.subheader("Anchor Performance (Ammu vs Kishore)")
    left, right = st.columns(2)
    
    # Projects by Anchor
    fig_count = px.bar(df_all.groupby('anchor_person').size().reset_index(name='count'), 
                       x='anchor_person', y='count', title="Volume of Projects",
                       color='anchor_person', color_discrete_sequence=px.colors.qualitative.Pastel)
    left.plotly_chart(fig_count, use_container_width=True)

    # Conversion by Anchor
    conv_data = df_all.groupby(['anchor_person', 'status']).size().reset_index(name='count')
    fig_status = px.bar(conv_data, x='anchor_person', y='count', color='status', 
                        title="Project Stage Breakdown", barmode='stack')
    right.plotly_chart(fig_status, use_container_width=True)

    # --- ROW 3: PURCHASE DEPARTMENT EFFICIENCY ---
    st.divider()
    st.subheader("🛒 Purchase Department Response Time")
    
    p_data = df_all[df_all['purchase_trigger'] == True]
    if not p_data.empty:
        fig_p = px.pie(p_data, names='purchase_status', title="Procurement Status (Overall)",
                       hole=0.4, color_discrete_sequence=px.colors.sequential.RdBu)
        st.plotly_chart(fig_p, use_container_width=True)
    else:
        st.info("No purchase data available for analytics yet.")

else:
    st.warning("No data found in Supabase to generate analytics.")
