import streamlit as st

# --- 1. THE PYTHON CORE (Updated with Material Logic) ---
def calculate_steel_weight(length_mm, width_mm, thickness_mm, material_type):
    # Convert mm to cm
    volume_cm3 = (length_mm/10) * (width_mm/10) * (thickness_mm/10)
    
    # Logic: Set density and symbol based on material choice
    if material_type == "Stainless Steel (SS304/316)":
        density = 7.93 / 1000  # kg/cm3
        symbol = "🔘"
    else:  # Default to Mild Steel
        density = 7.85 / 1000  # kg/cm3
        symbol = "🔲"
        
    weight_kg = volume_cm3 * density
    return round(weight_kg, 2), symbol

# --- 2. THE STREAMLIT INTERFACE ---
st.title("B&G Engineering: Material Lab")

# NEW: Material Selector
mat_choice = st.selectbox("Select Material Grade", 
                          ["Mild Steel (MS)", "Stainless Steel (SS304/316)"])

st.subheader("Input Plate Dimensions (mm)")
col1, col2, col3 = st.columns(3)

with col1: l = st.number_input("Length", value=1000)
with col2: w = st.number_input("Width", value=500)
with col3: t = st.number_input("Thickness", value=10)

# --- 3. THE PIPING ---
# Now passing 'mat_choice' into the engine
final_weight, mat_symbol = calculate_steel_weight(l, w, t, mat_choice)

st.divider()

# --- 4. THE OUTPUT GAUGE ---
# Using the dynamic symbol in the label
st.metric(label=f"{mat_symbol} Estimated {mat_choice} Weight", value=f"{final_weight} kg")

if final_weight > 100:
    st.warning("⚠️ Manual lifting prohibited. Use the Overhead Crane.")
else:
    st.success("✅ Safe for manual handling.")
