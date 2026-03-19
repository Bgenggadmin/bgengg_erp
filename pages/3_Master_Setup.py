import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd

# 1. Page Configuration
st.set_page_config(page_title="Admin Setup", layout="wide")
st.title("⚙️ Master Data Management")

conn = st.connection("supabase", type=SupabaseConnection)

def refresh_data():
    st.cache_data.clear()

# --- 2. DATA FETCHING ---
# Aligned with "Golden Hub" Schema: staff, workers, machines, and clients use 'name'
# Vehicles use 'reg_no'
try:
    staff_df = pd.DataFrame(conn.table("master_staff").select("*").order("name").execute().data or [])
    worker_df = pd.DataFrame(conn.table("master_workers").select("*").order("name").execute().data or [])
    machine_df = pd.DataFrame(conn.table("master_machines").select("*").order("name").execute().data or [])
    vehicle_df = pd.DataFrame(conn.table("master_vehicles").select("*").order("reg_no").execute().data or [])
    client_df = pd.DataFrame(conn.table("master_clients").select("*").order("name").execute().data or [])
except Exception as e:
    st.error(f"Error loading master tables: {e}")
    staff_df = worker_df = machine_df = vehicle_df = client_df = pd.DataFrame()

# --- 3. THE HARVESTER (Sync from Anchor Projects) ---
with st.sidebar:
    st.header("📥 Data Harvester")
    st.info("Pull existing data from Anchor Projects into Master Lists.")
    
    if st.button("Sync Clients & Staff", use_container_width=True):
        try:
            # Sync Clients from anchor_projects.client_name
            c_data = conn.table("anchor_projects").select("client_name").execute()
            c_names = list(set([r['client_name'] for r in c_data.data if r['client_name']]))
            for name in c_names:
                conn.table("master_clients").upsert({"name": name}, on_conflict="name").execute()
            
            # Sync Staff from anchor_projects.anchor_person
            s_data = conn.table("anchor_projects").select("anchor_person").execute()
            s_names = list(set([r['anchor_person'] for r in s_data.data if r['anchor_person']]))
            for name in s_names:
                conn.table("master_staff").upsert({"name": name}, on_conflict="name").execute()
                
            st.success("Sync Complete!")
            st.rerun()
        except Exception as e:
            st.error(f"Sync failed: {e}")

# --- 4. RENDER UTILITY ---
def render_section(df, table_name, col_name, label, id_col="id"):
    with st.form(f"add_{table_name}", clear_on_submit=True):
        new_val = st.text_input(f"Add New {label}")
        if st.form_submit_button(f"➕ Save {label}") and new_val:
            conn.table(table_name).insert({col_name: new_val.strip()}).execute()
            refresh_data()
            st.rerun()
    
    st.divider()
    search = st.text_input(f"🔍 Search {label}...", key=f"search_{table_name}")
    
    filtered_df = df
    if search and not df.empty:
        filtered_df = df[df[col_name].astype(str).str.contains(search, case=False, na=False)]

    if not filtered_df.empty:
        for _, row in filtered_df.iterrows():
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{row[col_name]}**")
            if c2.button("🗑️", key=f"del_{table_name}_{row[id_col]}"):
                conn.table(table_name).delete().eq(id_col, row[id_col]).execute()
                refresh_data()
                st.rerun()
    else:
        st.info(f"No {label} entries found.")

# --- 5. UI TABS ---
t1, t2, t3, t4, t5 = st.tabs(["👔 Staff", "👷 Workers", "🚜 Machines", "🚛 Vehicles", "🏢 Clients"])

with t1: render_section(staff_df, "master_staff", "name", "Staff")
with t2: render_section(worker_df, "master_workers", "name", "Worker")
with t3: render_section(machine_df, "master_machines", "name", "Machine")
with t4: render_section(vehicle_df, "master_vehicles", "reg_no", "Vehicle")
with t5: render_section(client_df, "master_clients", "name", "Client")
