import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz
from io import BytesIO
from PIL import Image
import urllib.parse

# --- 1. SETUP & UTILITIES (Must be at the TOP to avoid NameError) ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Logistics | Fleet Tracker", layout="wide")

try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception as e:
    st.error("❌ Supabase Connection Failed!"); st.stop()

# --- 2. FUNCTIONS (Defined BEFORE use) ---

@st.cache_data(ttl=600)
def get_staff_master():
    """Pulls staff names from master_staff using confirmed 'name' column."""
    try:
        # UPDATED: Changed 'staff_name' to 'name' based on your SQL audit
        res = conn.table("master_staff").select("name").order("name").execute()
        if res.data:
            return [item['name'] for item in res.data]
    except Exception as e:
        st.sidebar.error(f"Staff Load Error: {e}")
    return ["Brahmiah", "Admin", "Other"]

@st.cache_data(ttl=600)
def get_vehicle_master():
    """Pulls Registration Numbers from master_vehicles."""
    try:
        res = conn.table("master_vehicles").select("reg_no").order("reg_no").execute()
        if res.data:
            return [item['reg_no'] for item in res.data]
    except: pass
    return ["AP07-XXXX", "TS09-XXXX"]

@st.cache_data(ttl=60)
def load_data():
    """Loads previous logistics logs."""
    try:
        res = conn.table("logistics_logs").select("*").order("timestamp", desc=True).execute()
        if res.data:
            _df = pd.DataFrame(res.data)
            num_cols = ['distance', 'fuel_ltrs', 'fuel_rate', 'total_fuel_cost', 'start_km', 'end_km']
            for col in num_cols:
                if col in _df.columns:
                    _df[col] = pd.to_numeric(_df[col], errors='coerce').fillna(0)
            return _df
    except: pass
    return pd.DataFrame(columns=["timestamp", "vehicle", "end_km", "distance", "fuel_ltrs"])

def get_last_km(veh_name, dataframe):
    """Predicts next Start KM based on last End KM."""
    if not dataframe.empty and 'vehicle' in dataframe.columns:
        veh_logs = dataframe[dataframe['vehicle'] == veh_name]
        if not veh_logs.empty: 
            return int(veh_logs.iloc[0]['end_km'])
    return 0

# --- 3. INITIALIZE DATA ---
# Calling functions now is safe because they are defined above.
df = load_data()
staff_list = get_staff_master()
vehicle_list = get_vehicle_master()

# --- 4. UI LAYOUT ---
st.title("🚛 B&G Logistics Management System")

with st.sidebar:
    if st.button("🔄 Sync Master Setup"):
        st.cache_data.clear()
        st.rerun()

tabs = st.tabs(["📅 Staff Booking", "👨‍✈️ Brahmiah's Desk", "📝 Trip Logger", "📊 Analytics"])

# --- TAB 1: STAFF BOOKING ---
with tabs[0]:
    with st.form("request_form", clear_on_submit=True):
        st.subheader("Request Vehicle for Work")
        c1, c2 = st.columns(2)
        req_by = c1.selectbox("Staff Name", staff_list, key="sb_name")
        dest = c1.text_input("Destination / Site")
        r_date = c2.date_input("Required Date", min_value=date.today())
        r_time = c2.text_input("Required Time")
        
        if st.form_submit_button("Submit Request"):
            if dest:
                new_req = {"requested_by": req_by, "destination": dest.upper(), "req_date": str(r_date), "req_time": r_time, "status": "Pending"}
                conn.table("logistics_requests").insert(new_req).execute()
                st.success(f"Request for {req_by} sent!")
                # Add WhatsApp link logic here if needed

# --- TAB 3: TRIP LOGGER ---
with tabs[2]:
    with st.form("logistics_form", clear_on_submit=True):
        st.subheader("📝 Log Actual Movement & Fuel")
        col1, col2, col3 = st.columns(3)
        with col1:
            vehicle = st.selectbox("Vehicle", vehicle_list)
            driver = st.selectbox("Driver Name", staff_list)
        with col2:
            # This will no longer cause a NameError because get_last_km is defined at the top
            start_km = st.number_input("Start KM", min_value=0, value=get_last_km(vehicle, df), step=1)
            end_km = st.number_input("End KM", min_value=0, step=1)
        with col3:
            auth_by = st.selectbox("Authorized By", staff_list)
            location = st.text_input("Location")

        if st.form_submit_button("🚀 SUBMIT LOG"):
            # Insert logic here
            pass
