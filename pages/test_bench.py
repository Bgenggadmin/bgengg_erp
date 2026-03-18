import streamlit as st

# --- SYSTEM CONFIGURATION ---
st.set_page_config(page_title="B&G Test Bench", layout="centered")

# --- DATA INTAKE (THE MANIFOLD) ---
st.title("⚙️ Engineering Test Bench Session")
st.header("Sub-System: The Import")

# --- THE SENSOR CHECK ---
# We are checking if the 'Streamlit' valve is pressurized and flowing
status = "SYSTEM ACTIVE"

# --- THE OUTPUT GAUGE ---
st.metric(label="Manifold Status", value=status)

if st.button("Initialize System"):
    st.success("The 'Import' protocol is stable. Resources are flowing.")
else:
    st.warning("System on Standby. Awaiting operator input.")
