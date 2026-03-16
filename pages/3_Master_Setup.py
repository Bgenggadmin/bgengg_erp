import streamlit as st
from st_supabase_connection import SupabaseConnection
from database_utils import fetch_all_master_data
import pandas as pd

st.set_page_config(page_title="Admin Setup", layout="wide")
st.title("⚙️ Master Data Management")

conn = st.connection("supabase", type=SupabaseConnection)

def refresh_data():
    st.cache_data.clear()
    st.session_state.master_data = fetch_all_master_data(conn)

# --- 1. FETCH FULL DATA (Updated to include Clients) ---
staff_df = pd.DataFrame(conn.table("master_staff").select("*").order("name").execute().data or [])
worker_df = pd.DataFrame(conn.table("master_workers").select("*").order("name").execute().data or [])
machine_df = pd.DataFrame(conn.table("master_machines").select("*").order("name").execute().data or [])
vehicle_df = pd.DataFrame(conn.table("master_vehicles").select("*").order("reg_no").execute().data or [])
client_df = pd.DataFrame(conn.table("master_clients").select("*").order("name").execute().data or []) # 👈 NEW

# --- 2. SEARCH & RENDER UTILITY ---
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
    
    # Filter DataFrame based on search
    filtered_df = df
    if search and not df.empty:
        filtered_df = df[df[col_name].str.contains(search, case=False, na=False)]

    # Display Table
    if not filtered_df.empty:
        for _, row in filtered_df.iterrows():
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{row[col_name]}**")
            if c2.button("🗑️", key=f"del_{table_name}_{row[id_col]}"):
                conn.table(table_name).delete().eq(id_col, row[id_col]).execute()
                refresh_data()
                st.rerun()
    else:
        st.info("No matching records found.")

# --- 3. UI TABS (Added 5th Tab for Clients) ---
t1, t2, t3, t4, t5 = st.tabs(["👔 Staff", "👷 Workers", "🚜 Machines", "🚛 Vehicles", "🏢 Clients"])

with t1: render_section(staff_df, "master_staff", "name", "Staff")
with t2: render_section(worker_df, "master_workers", "name", "Worker")
with t3: render_section(machine_df, "master_machines", "name", "Machine")
with t4: render_section(vehicle_df, "master_vehicles", "reg_no", "Vehicle")
with t5: render_section(client_df, "master_clients", "name", "Client") # 👈 NEW
