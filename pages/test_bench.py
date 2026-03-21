import streamlit as st

st.title("Week 2: Control Logic")
st.header("Sub-system: Pressure Monitor")

# --- 1. THE SENSOR (Input) ---
# We simulate a pressure gauge from 0 to 150 PSI
pressure_reading = st.slider("Current System Pressure (PSI)", 0, 150, 85)

st.divider()

# --- 2. THE CHECK VALVE (Logic) ---
if pressure_reading > 120:
    # CRITICAL CONDITION
    st.error("🚨 CRITICAL FAULT: Pressure exceeds safety limit!")
    st.button("Activate Emergency Vent")
    
elif pressure_reading < 30:
    # LOW FLOW CONDITION
    st.warning("⚠️ LOW PRESSURE: System in Standby Mode.")
    
else:
    # NOMINAL OPERATION
    st.success("✅ NOMINAL: System operating within design parameters.")
    st.info(f"Flow Rate: {pressure_reading * 0.8} m³/h") 
    st.metric(label="Calculated Flow Rate", value=f"{flow_rate} m³/h")
    
    st.info("System optimized for continuous flow.")
