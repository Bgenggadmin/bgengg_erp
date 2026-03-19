import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz
from io import BytesIO
from PIL import Image
import urllib.parse

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Logistics | Fleet Tracker", layout="wide")

try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception as e:
    st.error("❌ Supabase Connection Failed!"); st.stop()

# --- 2. MASTER & DATA UTILITIES ---

@st.cache_data(ttl=600) # Caches for 10 mins by default
def get_staff_master():
    """Pulls staff names from your master_setup table."""
    try:
        # Senior Dev Tip: Only select the column you need to save bandwidth
        res = conn.table("master_setup").select("staff_name").order("staff_name").execute()
        if res.data:
            return [item['staff_name'] for item in res.data]
    except Exception as e:
        st.sidebar.error(f"Sync Error: {e}")
    return ["Brahmiah", "Admin", "Other"] # Fallback

# --- SIDEBAR FORCE REFRESH ---
with st.sidebar:
    st.header("⚙️ Controls")
    if st.button("🔄 Sync Master Setup"):
        st.cache_data.clear() # This kills the 10-minute wait immediately
        st.success("Master List Updated!")
        st.rerun()
    st.divider()
    st.caption("B&G Engineering Industries v2.1")

@st.cache_data(ttl=60)
def load_data():
    try:
        res = conn.table("logistics_logs").select("*").order("timestamp", desc=True).execute()
        if res.data:
            _df = pd.DataFrame(res.data)
            numeric_cols = ['distance', 'fuel_ltrs', 'fuel_rate', 'total_fuel_cost', 'start_km', 'end_km']
            for col in numeric_cols:
                if col in _df.columns:
                    _df[col] = pd.to_numeric(_df[col], errors='coerce').fillna(0)
            return _df
    except: pass
    return pd.DataFrame(columns=["timestamp", "vehicle", "end_km", "distance", "fuel_ltrs"])

def get_last_km(veh_name, dataframe):
    if not dataframe.empty and 'vehicle' in dataframe.columns:
        veh_logs = dataframe[dataframe['vehicle'] == veh_name]
        if not veh_logs.empty: return int(veh_logs.iloc[0]['end_km'])
    return 0

# Initial Data Pull
df = load_data()
staff_list = get_staff_master()

# --- 3. UI LAYOUT ---
st.title("🚛 B&G Logistics Management System")
tabs = st.tabs(["📅 Staff Booking", "👨‍✈️ Brahmiah's Desk", "📝 Trip Logger", "📊 Analytics"])

# --- TAB 1: STAFF BOOKING ---
with tabs[0]:
    with st.form("request_form", clear_on_submit=True):
        st.subheader("Request Vehicle for Work")
        c1, c2 = st.columns(2)
        # Pulls from Master (Refreshable via Sidebar)
        req_by = c1.selectbox("Staff Name", staff_list)
        dest = c1.text_input("Destination / Site")
        r_date = c2.date_input("Required Date", min_value=date.today())
        r_time = c2.text_input("Required Time")
        reason = st.text_area("Purpose")
        
        if st.form_submit_button("Submit Request"):
            if dest:
                new_req = {"requested_by": req_by, "destination": dest.upper(), "req_date": str(r_date), "req_time": r_time, "purpose": reason, "status": "Pending"}
                conn.table("logistics_requests").insert(new_req).execute()
                st.success("Request sent!")
                # WhatsApp link logic here...

# --- TAB 3: TRIP LOGGER ---
with tabs[2]:
    with st.form("logistics_form", clear_on_submit=True):
        st.subheader("📝 Log Actual Movement & Fuel")
        col1, col2, col3 = st.columns(3)
        with col1:
            vehicle = st.selectbox("Vehicle", ["Ashok Leyland", "Mahindra", "Other"])
            driver = st.selectbox("Driver Name", staff_list) # Dynamic
            purpose = st.selectbox("Purpose", ["Inter-Unit", "Pickup", "Delivery", "Fueling"])
        with col2:
            start_km = st.number_input("Start KM", min_value=0, value=get_last_km(vehicle, df), step=1)
            end_km = st.number_input("End KM", min_value=0, step=1)
            fuel_qty = st.number_input("Fuel Added", min_value=0.0, step=0.1)
        with col3:
            fuel_rate = st.number_input("Rate", min_value=0.0, value=94.5)
            auth_by = st.selectbox("Authorized By", staff_list) # Dynamic
            location = st.text_input("Location")

        if st.form_submit_button("🚀 SUBMIT LOG"):
            # Submission logic here...
            pass
