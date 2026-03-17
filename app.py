import streamlit as st
from st_supabase_connection import SupabaseConnection
from database_utils import fetch_all_master_data

# --- 1. GLOBAL PAGE CONFIG (Only here, remove from sub-pages) ---
st.set_page_config(
    page_title="BGEngg Unified ERP",
    page_icon="🏗️",
    layout="wide"
)

# --- 2. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

# --- 3. INITIALIZE MASTER SESSION STATE ---
if "master_data" not in st.session_state:
    st.session_state.master_data = fetch_all_master_data(conn)

# --- 4. DEFINE NAVIGATION PAGES ---
# Each file in your /pages folder must be defined here
p1 = st.Page("pages/01_Anchor_Portal.py", title="Anchor Portal", icon="⚓")
p2 = st.Page("pages/02_Purchase_Console.py", title="Purchase Console", icon="🛒")
p3 = st.Page("pages/03_Production_Master.py", title="Production Master", icon="🏗️")
p4 = st.Page("pages/04_Project_Reporting.py", title="Project Reporting", icon="📈")

# --- 5. SETUP NAVIGATION ---
pg = st.navigation({
    "Operations": [p1, p2, p3],
    "Client Services": [p4]
})

# --- 6. SHARED SIDEBAR LOGIC ---
with st.sidebar:
    st.title("🏭 BGEngg ERP")
    if st.button("🔄 Refresh Master Data", use_container_width=True):
        st.cache_data.clear()
        st.session_state.master_data = fetch_all_master_data(conn)
        st.success("Refreshed!")
        st.rerun()
    st.divider()
    st.caption(f"🟢 Connected to Supabase")
    st.caption(f"👥 Clients: {len(st.session_state.master_data.get('clients', []))}")

# --- 7. RUN NAVIGATION ---
pg.run()
