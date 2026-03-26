import streamlit as st
import pandas as pd

# --- 1. THE CONTROL PANEL (User Inputs) ---
st.sidebar.header("⚙️ Factory Settings")
# A slider to adjust how 'efficient' the shop is today
efficiency = st.sidebar.slider("Operator Efficiency (%)", 50, 100, 85) / 100
shift_limit = 8 # Total hours in a shift

# --- 2. THE DATA ---
raw_data = [
    {"machine_id": "VMC-01", "hours": 6},
    {"machine_id": "Lathe-02", "hours": 7},
]
df = pd.DataFrame(raw_data)

# --- 3. THE CALCULATION ENGINE ---
# Effective Capacity = What we can ACTUALLY finish
effective_capacity = shift_limit * efficiency

st.title("B&G Capacity Planner")
st.info(f"💡 At {efficiency*100}% efficiency, your actual capacity is **{effective_capacity} hrs** per machine.")

# --- 4. THE OUTPUT (The Alert System) ---
for index, row in df.iterrows():
    load = row['hours']
    machine = row['machine_id']
    
    if load > effective_capacity:
        st.error(f"🚨 {machine} OVERLOADED: Needs {load}h, but can only do {effective_capacity}h today.")
    else:
        st.success(f"✅ {machine} OK: Load is {load}h.")
