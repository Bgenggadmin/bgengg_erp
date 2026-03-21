import streamlit as st

st.title("Week 2, Session 2: The Loop")

# --- 1. THE BATCH (The List) ---
# A list of machines in the B&G shop
workshop_machines = ["CNC Lathe", "Hydraulic Press", "Milling Machine", "Arc Welder"]

st.subheader("Automated Inspection Cycle")

# --- 2. THE ASSEMBLY LINE (The For Loop) ---
# 'machine' is our temporary robotic arm picking up one item at a time
for machine in workshop_machines:
    # Everything indented here happens for EVERY machine in the list
    st.write(f"🔍 Inspecting: **{machine}**...")
    
    # Logic inside the loop: Check if it's the welder to add a safety warning
    if machine == "Arc Welder":
        st.warning(f"  -> Check electrode wear on {machine}")
    else:
        st.success(f"  -> {machine} status: OPERATIONAL")

st.divider()
st.info("✅ Batch Inspection Complete.")
