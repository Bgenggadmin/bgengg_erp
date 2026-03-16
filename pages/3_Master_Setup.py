import streamlit as st
from st_supabase_connection import SupabaseConnection
from database_utils import fetch_all_master_data

st.set_page_config(page_title="Admin Setup", layout="wide")
st.title("⚙️ Master Data Management")

conn = st.connection("supabase", type=SupabaseConnection)

# Helper function to refresh global data
def refresh_data():
    st.cache_data.clear()
    st.session_state.master_data = fetch_all_master_data(conn)

# --- UI LAYOUT ---
col1, col2, col3 = st.columns(3)

# 1. STAFF ENTRY
with col1:
    st.subheader("👔 Staff")
    with st.form("staff_form", clear_on_submit=True):
        name = st.text_input("New Staff Name")
        if st.form_submit_button("Add Staff"):
            conn.table("master_staff").insert({"name": name}).execute()
            refresh_data()
            st.success("Staff Added!")
            st.rerun()
    st.write(st.session_state.master_data.get('staff', []))

# 2. WORKER ENTRY
with col2:
    st.subheader("👷 Workers")
    with st.form("worker_form", clear_on_submit=True):
        name = st.text_input("New Worker Name")
        if st.form_submit_button("Add Worker"):
            conn.table("master_workers").insert({"name": name}).execute()
            refresh_data()
            st.success("Worker Added!")
            st.rerun()
    st.write(st.session_state.master_data.get('workers', []))

# 3. MACHINE ENTRY
with col3:
    st.subheader("🚜 Machines")
    with st.form("machine_form", clear_on_submit=True):
        name = st.text_input("Machine ID")
        if st.form_submit_button("Add Machine"):
            conn.table("master_machines").insert({"name": name}).execute()
            refresh_data()
            st.success("Machine Added!")
            st.rerun()
    st.write(st.session_state.master_data.get('machines', []))
