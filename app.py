import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd

# --- 1. PAGE CONFIG ---
st.set_page_config(
    page_title="BGEngg ERP",
    page_icon="🏗️",
    layout="wide"
)

# --- 2. DATABASE CONNECTION ---
# This initializes the connection to your Supabase backend
conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. MASTER DATA LOADER ---
@st.cache_data(ttl=60)
def fetch_all_master_data():
    """Fetches centralized resource lists from Supabase."""
    try:
        staff = conn.table("master_staff").select("name").order("name").execute()
        workers = conn.table("master_workers").select("name").order("name").execute()
        machines = conn.table("master_machines").select("name").order("name").execute()
        vehicles = conn.table("master_vehicles").select("reg_no").order("reg_no").execute()
        gates = conn.table("production_gates").select("gate_name").order("step_order").execute()
        
        return {
            "staff": [s['name'] for s in staff.data],
            "workers": [w['name'] for w in workers.data],
            "machines": [m['name'] for m in machines.data],
            "vehicles": [v['reg_no'] for v in vehicles.data],
            "gates": [g['gate_name'] for g in gates.data]
        }
    except Exception as e:
        # If tables don't exist yet, return empty lists to prevent app crash
        return {"staff": [], "workers": [], "machines": [], "vehicles": [], "gates": []}

# --- 4. INITIALIZE SESSION STATE ---
# This stores the data globally so sidebar pages can access it instantly
if "master_data" not in st.session_state:
    st.session_state.master_data = fetch_all_master_data()

# --- 5. LOGO / HEADER ---
st.title("🏭 BGEngg Unified ERP System")
st.markdown("---")

# --- 6. DASHBOARD SUMMARY ---
st.subheader("Welcome to the Central Portal")
st.info("👈 **Please select a module from the sidebar** to access specific department tools.")

# --- 7. LIVE METRICS ---
# These are currently placeholders but are now ready to be linked to st.session_state.master_data
c1, c2, c3 = st.columns(3)
c1.metric("API Projects", "Active", "Ammu")
c2.metric("ZLD Projects", "Active", "Kishore")
c3.metric("Shopfloor", "Online", f"{len(st.session_state.master_data['machines'])} Machines")

st.divider()

# --- 8. FOOTER / SESSION INFO ---
col_f1, col_f2 = st.columns(2)
with col_f1:
    st.write(f"🟢 System Status: **Connected to Supabase**")
    st.write(f"👤 Current User Session: **Admin Portal**")
with col_f2:
    if st.button("🔄 Refresh Master Data"):
        st.cache_data.clear()
        st.session_state.master_data = fetch_all_master_data()
        st.rerun()
