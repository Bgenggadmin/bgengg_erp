import streamlit as st

# --- 1. THE PYTHON CORE (The Engine) ---
# This is a standard Python function. No 'st.' prefix.
def calculate_steel_weight(length_mm, width_mm, thickness_mm):
    # Convert mm to cm for the calculation (10mm = 1cm)
    volume_cm3 = (length_mm/10) * (width_mm/10) * (thickness_mm/10)
    density_steel = 7.85 / 1000 # kg/cm3
    weight_kg = volume_cm3 * density_steel
    return round(weight_kg, 2)

# --- 2. THE STREAMLIT INTERFACE (The Dashboard) ---
st.title("B&G Engineering: Material Calculator")

st.subheader("Input Plate Dimensions (mm)")
col1, col2, col3 = st.columns(3)

with col1:
    l = st.number_input("Length", value=1000)
with col2:
    w = st.number_input("Width", value=500)
with col3:
    t = st.number_input("Thickness", value=10)

# --- 3. THE PIPING (Connecting Engine to Dashboard) ---
# We take the values from the Streamlit 'valves' (l, w, t) 
# and 'pipe' them into our Python Engine.
final_weight = calculate_steel_weight(l, w, t)

st.divider()

# --- 4. THE OUTPUT GAUGE (Streamlit Library) ---
st.metric(label="Estimated Plate Weight", value=f"{final_weight} kg")

if final_weight > 100:
    st.warning("⚠️ Manual lifting prohibited. Use the Overhead Crane.")
else:
    st.success("✅ Safe for manual handling (Two-person lift).")
