# --- Week 3, Session 3: Capacity Simulator ---
# 1. THE DATA (Adding Time)
raw_data = [
    {"job_code": "PRO-001", "machine_id": "VMC-01", "hours": 4},
    {"job_code": "PRO-002", "machine_id": "VMC-01", "hours": 5}, # VMC-01 total = 9 hrs
    {"job_code": "PRO-003", "machine_id": "Lathe-02", "hours": 3},
    {"job_code": "PRO-004", "machine_id": "Buffing-A", "hours": 6},
]
df = pd.DataFrame(raw_data)

# 2. THE GROUPBY (Summing Hours instead of Counting Jobs)
# .sum() tells us the Total Workload in hours
capacity_df = df.groupby('machine_id')['hours'].sum().reset_index()

# 3. THE TARGET LINE
# We define an 8-hour shift limit
SHIFT_LIMIT = 8

# 4. THE OUTPUT (A Bar Chart with a Goal)
st.subheader("⏳ Shift Capacity vs. Load")

# Streamlit's native bar_chart is simple, 
# but we can use 'st.altair_chart' for the "Red Line" logic later.
# For now, let's use the standard bar chart.
st.bar_chart(data=capacity_df, x='machine_id', y='hours')

# 5. THE DECISION LOGIC (The Safety Interlock)
for index, row in capacity_df.iterrows():
    if row['hours'] > SHIFT_LIMIT:
        st.error(f"🚨 OVERLOAD: {row['machine_id']} requires {row['hours']} hrs (Limit: {SHIFT_LIMIT} hrs)")
