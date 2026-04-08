import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd

# 1. Page Configuration
st.set_page_config(page_title="B&G Admin Setup", layout="wide", page_icon="⚙️")

# --- PASSWORD PROTECTION ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown("<h2 style='text-align: center;'>🏗️ B&G ENGINEERING</h2>", unsafe_allow_html=True)
        pwd = st.text_input("🔑 Enter Master Password", type="password")
        if st.button("Access System"):
            if pwd == "1234":
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("😕 Password incorrect")
        return False
    return True

if not check_password():
    st.stop()

st.title("⚙️ Master Data Management")

conn = st.connection("supabase", type=SupabaseConnection)

def refresh_data():
    st.cache_data.clear()

# --- 2. DATA FETCHING ---
try:
    staff_df = pd.DataFrame(conn.table("master_staff").select("*").order("name").execute().data or [])
    worker_df = pd.DataFrame(conn.table("master_workers").select("*").order("name").execute().data or [])
    machine_df = pd.DataFrame(conn.table("master_machines").select("*").order("name").execute().data or [])
    vehicle_df = pd.DataFrame(conn.table("master_vehicles").select("*").order("reg_no").execute().data or [])
    client_df = pd.DataFrame(conn.table("master_clients").select("*").order("name").execute().data or [])
    # NEW: Vendor Data Fetch
    vendor_df = pd.DataFrame(conn.table("master_vendors").select("*").order("name").execute().data or [])
except Exception as e:
    st.error(f"Error loading master tables: {e}")
    staff_df = worker_df = machine_df = vehicle_df = client_df = vendor_df = pd.DataFrame()

# --- 3. THE HARVESTER (Sync from Anchor Projects) ---
with st.sidebar:
    st.header("📥 Data Harvester")
    st.info("Sync data from Anchor Projects.")
    
    if st.button("Sync Clients & Staff", use_container_width=True):
        try:
            c_data = conn.table("anchor_projects").select("client_name").execute()
            c_names = list(set([r['client_name'] for r in c_data.data if r['client_name']]))
            for name in c_names:
                conn.table("master_clients").upsert({"name": name}, on_conflict="name").execute()
            
            s_data = conn.table("anchor_projects").select("anchor_person").execute()
            s_names = list(set([r['anchor_person'] for r in s_data.data if r['anchor_person']]))
            for name in s_names:
                conn.table("master_staff").upsert({"name": name}, on_conflict="name").execute()
                
            st.success("Sync Complete!")
            refresh_data()
            st.rerun()
        except Exception as e:
            st.error(f"Sync failed: {e}")

# --- 4. RENDER UTILITIES ---

# Generic Section (Staff, Workers, Machines, Clients, Vehicles)
def render_section(df, table_name, col_name, label, id_col="id"):
    with st.form(f"add_{table_name}", clear_on_submit=True):
        new_val = st.text_input(f"Add New {label}")
        if st.form_submit_button(f"➕ Save {label}") and new_val:
            conn.table(table_name).insert({col_name: new_val.strip().upper()}).execute()
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

# Specialized Section for Vendor Management
def render_vendor_section(df):
    with st.form("add_vendor", clear_on_submit=True):
        v1, v2 = st.columns(2)
        v_name = v1.text_input("Vendor Company Name*")
        v_cat = v2.selectbox("Category", ["Steel", "Hardware", "Electrical", "Consumables", "Services", "Machining", "General"])
        
        v3, v4 = st.columns(2)
        v_phone = v3.text_input("WhatsApp Number", help="Format: 919876543210")
        v_email = v4.text_input("Email Address")
        
        if st.form_submit_button("🤝 Save Vendor") and v_name:
            payload = {
                "name": v_name.strip().upper(),
                "category": v_cat,
                "phone_number": v_phone.strip(),
                "email": v_email.strip().lower()
            }
            conn.table("master_vendors").insert(payload).execute()
            refresh_data()
            st.rerun()
    
    st.divider()
    v_search = st.text_input("🔍 Search Vendors (Name or Category)...", key="search_vendors")
    filtered_v = df
    if v_search and not df.empty:
        filtered_v = df[
            df['name'].str.contains(v_search, case=False, na=False) | 
            df['category'].str.contains(v_search, case=False, na=False)
        ]

    if not filtered_v.empty:
        for _, row in filtered_v.iterrows():
            with st.container(border=True):
                vc1, vc2, vc3 = st.columns([2, 2, 0.5])
                vc1.write(f"**{row['name']}**")
                vc1.caption(f"📁 {row['category']}")
                vc2.write(f"📞 {row.get('phone_number', 'N/A')}")
                vc2.write(f"📧 {row.get('email', 'N/A')}")
                if vc3.button("🗑️", key=f"del_v_{row['id']}"):
                    conn.table("master_vendors").delete().eq("id", row['id']).execute()
                    refresh_data()
                    st.rerun()
    else:
        st.info("No vendors found.")

# --- 5. UI TABS ---
tabs = st.tabs(["👔 Staff", "👷 Workers", "🚜 Machines", "🚛 Vehicles", "🏢 Clients", "🤝 Vendor Master"])

with tabs[0]: render_section(staff_df, "master_staff", "name", "Staff")
with tabs[1]: render_section(worker_df, "master_workers", "name", "Worker")
with tabs[2]: render_section(machine_df, "master_machines", "name", "Machine")
with tabs[3]: render_section(vehicle_df, "master_vehicles", "reg_no", "Vehicle")
with tabs[4]: render_section(client_df, "master_clients", "name", "Client")
with tabs[5]: render_vendor_section(vendor_df)
