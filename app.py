import streamlit as st
from st_supabase_connection import SupabaseConnection
from database_utils import fetch_all_master_data  # ✅ This is the correct one

# --- 1. PAGE CONFIG ---
st.set_page_config(
    page_title="BGEngg ERP",
    page_icon="🏗️",
    layout="wide"
)

# --- 2. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. INITIALIZE SESSION STATE ---
# Only use the imported function. Remove the locally defined one below.
if "master_data" not in st.session_state:
    st.session_state.master_data = fetch_all_master_data(conn)

# --- 4. LOGO / HEADER ---
st.title("🏭 BGEngg Unified ERP System")
st.markdown("---")

# --- 5. DASHBOARD SUMMARY ---
st.subheader("Welcome to the Central Portal")
st.info("👈 **Please select a module from the sidebar** to access specific department tools.")

# --- 6. LIVE METRICS ---
c1, c2, c3, c4 = st.columns(4) # Added a 4th column for Clients
c1.metric("API Projects", "Active", "Ammu")
c2.metric("ZLD Projects", "Active", "Kishore")
c3.metric("Shopfloor", "Online", f"{len(st.session_state.master_data.get('machines', []))} Machines")
# 👈 NEW: Shows your harvested client count
c4.metric("Clients", "Master", f"{len(st.session_state.master_data.get('clients', []))}") 

st.divider()

# --- 7. FOOTER / SESSION INFO ---
col_f1, col_f2 = st.columns(2)
with col_f1:
    st.write(f"🟢 System Status: **Connected to Supabase**")
    st.write(f"👤 Current User Session: **Admin Portal**")
with col_f2:
    if st.button("🔄 Refresh Master Data"):
        st.cache_data.clear()
        # Ensure we pass 'conn' to the function
        st.session_state.master_data = fetch_all_master_data(conn)
        st.success("Master data refreshed across all pages!")
        st.rerun()
