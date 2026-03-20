import streamlit as st

st.title("Session 2: Tank Level Monitor")

# --- 1. THE LEAKY TANK (Standard Variable) ---
# This resets to 0 every time the script re-runs
leaky_tank = 0
leaky_tank += 1 

# --- 2. THE ACCUMULATOR (Session State) ---
# We check if the 'accumulator' exists; if not, we 'weld' it into place
if 'accumulator' not in st.session_state:
    st.session_state.accumulator = 0

if st.button("Pump Fluid (Add 10 Units)"):
    st.session_state.accumulator += 10

# --- 3. THE GAUGES (Output) ---
col1, col2 = st.columns(2)

with col1:
    st.metric("Leaky Tank (Standard Var)", leaky_tank)
    st.caption("Resets every run")

with col2:
    st.metric("Accumulator (Session State)", st.session_state.accumulator)
    st.caption("Stays pressurized")
