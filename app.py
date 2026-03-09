import streamlit as st

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="BGEngg ERP",
    page_icon="🏗️",
    layout="wide"
)

# --- LOGO / HEADER ---
st.title("🏭 BGEngg Unified ERP System")
st.markdown("---")

# --- DASHBOARD SUMMARY ---
st.subheader("Welcome to the Central Portal")
st.info("👈 **Please select a module from the sidebar** to access specific department tools.")

# Example Metrics (We can link these to Supabase later)
c1, c2, c3 = st.columns(3)
c1.metric("API Projects", "Active", "Ammu")
c2.metric("ZLD Projects", "Active", "Kishore")
c3.metric("Shopfloor", "Online", "Machining/Welding")

st.divider()
st.write("Current User Session: Admin Portal")
