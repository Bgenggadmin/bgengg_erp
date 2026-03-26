import streamlit as st
import pandas as pd # The 'Engine' for tables

# --- 1. THE DATA ENGINE (Simulating B&G Shop Floor) ---
# Imagine this is the data coming from your 'res' variable
raw_data = [
    {"job_code": "PRO-001", "machine_id": "VMC-01", "status": "In-House", "priority": "URGENT"},
    {"job_code": "PRO-002", "machine_id": "VMC-01", "status": "In-House", "priority": "Standard"},
    {"job_code": "PRO-003", "machine_id": "Lathe-02", "status": "In-House", "priority": "Standard"},
    {"job_code": "PRO-004", "machine_id": "VMC-01", "status": "Outsourced", "priority": "Standard"},
    {"job_code": "PRO-005", "machine_id": "Buffing-A", "status": "In-House", "priority": "URGENT"},
]
df = pd.DataFrame(raw_data)

# --- 2. THE ANALYTICS DASHBOARD ---
st.title("B&G Analytics: Test Bench")

# ROW 1: The Triple Unpack (4:2:2 Ratio)
c1, c2, c3 = st.columns([4, 2, 2])

# Logic for Metrics
total_active = len(df[df['status'] != "Finished"])
urgent_count = len(df[df['priority'] == "URGENT"])
in_house_count = len(df[df['status'] == "In-House"])

with c1: st.metric("Total Active", total_active)
with c2: st.metric("Urgent ⚠️", urgent_count, delta="Action Required", delta_color="inverse")
with c3: st.metric("In-House", in_house_count)

st.divider()

# ROW 2: The Load Balancer (Chart vs Alerts)
col_chart, col_alerts = st.columns([3, 2])

with col_chart:
    st.subheader("🏗️ Machine Load")
    # THE GROUPBY: Filter for In-House and count
    load_stats = df[df['status'] == "In-House"].groupby('machine_id')['job_code'].count().reset_index()
    
    # The Visual Output
    st.bar_chart(data=load_stats, x='machine_id', y='job_code')

with col_alerts:
    st.subheader("🚨 Priority List")
    # Only show URGENT jobs here
    urgent_df = df[df['priority'] == "URGENT"]
    st.dataframe(urgent_df[['job_code', 'machine_id']])
