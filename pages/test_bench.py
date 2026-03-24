import streamlit as st

# --- 1. THE PYTHON CORE (Processing 3 Outputs) ---
def calculate_material_data(length_mm, width_mm, thickness_mm, material_type):
    # Volume calculation
    volume_cm3 = (length_mm/10) * (width_mm/10) * (thickness_mm/10)
    
    # Logic for Density, Symbol, and Rate per kg
    if material_type == "Stainless Steel (SS304)":
        density = 7.93 / 1000
        symbol = "🔘"
        rate_per_kg = 280  # Example price in ₹
    else:
        density = 7.85 / 1000
        symbol = "🔲"
        rate_per_kg = 85   # Example price in ₹
        
    weight_kg = volume_cm3 * density
    total_cost = weight_kg * rate_per_kg
    
    # THE TRIPLE RETURN (Number, String, Number)
    return round(weight_kg, 2), symbol, round(total_cost, 2)

# --- 2. THE STREAMLIT INTERFACE ---
st.title("B&G Engineering: Commercial Lab")

mat_choice = st.selectbox("Select Material", ["Mild Steel (MS)", "Stainless Steel (SS304)"])

col1, col2, col3 = st.columns(3)
with col1: l = st.number_input("Length", value=1000)
with col2: w = st.number_input("Width", value=500)
with col3: t = st.number_input("Thickness", value=10)

# --- 3. THE PIPING (UNPACKING 3 VARIABLES) ---
# Order matters: Weight first, then Symbol, then Cost
final_weight, mat_symbol, est_cost = calculate_material_data(l, w, t, mat_choice)

st.divider()

# --- 4. THE OUTPUT GAUGE ---
c_res1, c_res2 = st.columns([3,1])

with c_res1:
    st.metric(label=f"{mat_symbol} Total Weight", value=f"{final_weight} kg")

with c_res2:
    # Adding a Delta (Difference) to see the 'Value' of the material
    st.metric(label="Estimated Material Cost", value=f"₹{est_cost:,}")

if final_weight > 100:
    st.warning("⚠️ Use Crane for Loading.")
