import streamlit as st
from st_supabase_connection import SupabaseConnection
from database_utils import fetch_all_master_data
import pandas as pd

st.set_page_config(page_title="Admin Setup", layout="wide")
st.title("⚙️ Master Data Management")

conn = st.connection("supabase", type=SupabaseConnection)

def refresh_data():
    st.cache_data.clear()
    # Fetching fresh data into session state
    st.session_state.master_data = fetch_all_master_data(conn)

# --- 1. FETCH FULL DATA ---
# Using 'or []' ensures we don't crash on empty tables
staff_df = pd.DataFrame(conn.table("master_staff").select("*").order("name").execute().data or [])
worker_df = pd.DataFrame(conn.table("master_workers").select("*").order("name").execute().data or [])
machine_df = pd.DataFrame(conn.table("master_machines").select("*").order("name").execute().data or [])
vehicle_df = pd.DataFrame(conn.table("master_vehicles").select("*").order("reg_no").execute().data or [])
client_df = pd.DataFrame(conn.table("master_clients").select("*").order("name").execute().data or [])

# --- 2. THE SYNC FEATURE (Fixes your "Missing Names" issue) ---
with st.sidebar:
    st.header("🔄 Database Sync")
    st.write("Pull names from existing production logs into Master Lists.")
    if st.button("Sync Workers from Logs"):
        # This SQL-like logic gathers names from your log tables
        # Adjust table names 'bg_machining_logs' if different
        res = conn.table("bg_machining_logs").select("worker_name").execute()
        names = list(set([r['worker_name'] for r in res.data if r['worker_name']]))
        for name in names:
            conn.table("master_workers").upsert({"name": name}, on_conflict="name").execute()
        st.success("Sync Complete!")
        st.rerun()

# --- 3. SEARCH & RENDER UTILITY ---
def render_section(df, table_name, col_name, label, id_col="id"):
    # Add Form
    with st.form(f"add_{table_name}", clear_on_submit=True):
        new_val = st.text_input(f"Add New {label}")
        if st.form_submit_button(f"➕ Save {label}") and new_val:
            conn.table(table_name).insert({col_name: new_val}).execute()
            refresh_data()
            st.rerun()
    
    st.divider()
    
    # Search Bar
    search = st.text_input(f"🔍 Search {label}...", key=f"search_{table_name}")
    
    # Real-time Filter
    filtered_df = df
    if search and not df.empty:
        # Fixed potential crash: case-insensitive search
        filtered_df = df[df[col_name].astype(str).str.contains(search, case=False, na=False)]

    # Display Table with Delete Buttons
    if not filtered_df.empty:
        for _, row in filtered_df.iterrows():
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{row[col_name]}**")
            if c2.button("🗑️", key=f"del_{table_name}_{row[id_col]}"):
                conn.table(table_name).delete().eq(id_col, row[id_col]).execute()
                refresh_data()
                st.rerun()
    else:
        st.info(f"No {label} records found.")

# --- 4. UI TABS ---
t1, t2, t3, t4, t5 = st.tabs(["👔 Staff", "👷 Workers", "🚜 Machines", "🚛 Vehicles", "🏢 Clients"])

with t1: render_section(staff_df, "master_staff", "name", "Staff")
with t2: render_section(worker_df, "master_workers", "name", "Worker")
with t3: render_section(machine_df, "master_machines", "name", "Machine")
with t4: render_section(vehicle_df, "master_vehicles", "reg_no", "Vehicle")
with t5: render_section(client_df, "master_clients", "name", "Client")
