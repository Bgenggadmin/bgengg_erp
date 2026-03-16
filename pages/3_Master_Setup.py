import streamlit as st
from st_supabase_connection import SupabaseConnection
from database_utils import fetch_all_master_data

st.set_page_config(page_title="Admin Setup", layout="wide")
st.title("⚙️ Master Data Management")

conn = st.connection("supabase", type=SupabaseConnection)

def refresh_data():
    st.cache_data.clear()
    st.session_state.master_data = fetch_all_master_data(conn)

# --- UI LAYOUT WITH 4 COLUMNS ---
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.subheader("👔 Staff")
    with st.form("staff_form", clear_on_submit=True):
        name = st.text_input("Staff Name")
        if st.form_submit_button("Add"):
            conn.table("master_staff").insert({"name": name}).execute()
            refresh_data()
            st.rerun()
    st.caption(f"Count: {len(st.session_state.master_data.get('staff', []))}")
    st.write(st.session_state.master_data.get('staff', []))

with c2:
    st.subheader("👷 Workers")
    with st.form("worker_form", clear_on_submit=True):
        name = st.text_input("Worker Name")
        if st.form_submit_button("Add"):
            conn.table("master_workers").insert({"name": name}).execute()
            refresh_data()
            st.rerun()
    st.caption(f"Count: {len(st.session_state.master_data.get('workers', []))}")
    st.write(st.session_state.master_data.get('workers', []))

with c3:
    st.subheader("🚜 Machines")
    with st.form("machine_form", clear_on_submit=True):
        name = st.text_input("Machine ID")
        if st.form_submit_button("Add"):
            conn.table("master_machines").insert({"name": name}).execute()
            refresh_data()
            st.rerun()
    st.caption(f"Count: {len(st.session_state.master_data.get('machines', []))}")
    st.write(st.session_state.master_data.get('machines', []))

# --- THE MISSING VEHICLE SECTION ---
with c4:
    st.subheader("🚛 Vehicles")
    with st.form("vehicle_form", clear_on_submit=True):
        reg_no = st.text_input("Vehicle Reg No (e.g. KA-01-1234)")
        v_type = st.selectbox("Type", ["Crane", "Forklift", "Truck", "Pickup", "Trailer"])
        if st.form_submit_button("Add"):
            conn.table("master_vehicles").insert({"reg_no": reg_no, "vehicle_type": v_type}).execute()
            refresh_data()
            st.rerun()
    st.caption(f"Count: {len(st.session_state.master_data.get('vehicles', []))}")
    st.write(st.session_state.master_data.get('vehicles', []))
