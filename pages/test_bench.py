import streamlit as st

st.title("Session 2: Tank Level Monitor")

# --- NEW: MATERIAL SPECIFICATION (Variable Initialization) ---
# We define these 'Tanks' at the top so the rest of the script can 'see' them.
material_grade = "SS304"  # This is a String (Text)
plate_thickness = 12.5    # This is a Float (Decimal)
batch_count = 5           # This is an Integer (Whole Number)

# --- 1. THE LEAKY TANK (Standard Variable) ---
leaky_tank = 0
leaky_tank += 1 

# --- 2. THE ACCUMULATOR (Session State) ---
if 'accumulator' not in st.session_state:
    st.session_state.accumulator = 0

if st.button("Pump Fluid (Add 10 Units)"):
    st.session_state.accumulator += 10

# --- 3. THE GAUGES (Output) ---
col1, col2 = st.columns(2)

with col1:
    st.metric("Leaky Tank", leaky_tank)
    st.caption("Resets every run")

with col2:
    st.metric("Accumulator", st.session_state.accumulator)
    st.caption("Stays pressurized")

# --- 4. MATERIAL READOUT ---
st.divider()
st.subheader("Material Log")
# Now the 'Gauge' works because the 'Tank' was defined above
st.write(f"Current Material: **{material_grade}**")
st.write(f"Thickness: {plate_thickness} mm | Batch: {batch_count}")
