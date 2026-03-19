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

# --- 2. DYNAMIC MASTER UTILITIES ---

@st.cache_data(ttl=600)
def get_staff_master():
    """Pulls staff names from master_staff table."""
    try:
        res = conn.table("master_staff").select("staff_name").order("staff_name").execute()
        if res.data:
            return [item['staff_name'] for item in res.data]
    except: pass
    return ["Brahmiah", "Admin", "Other"]

@st.cache_data(ttl=600)
def get_vehicle_master():
    """UPDATED: Pulls Registration Numbers from master_vehicles table."""
    try:
        # Using 'reg_no' based on your SQL audit
        res = conn.table("master_vehicles").select("reg_no").order("reg_no").execute()
        if res.data:
            return [item['reg_no'] for item in res.data]
    except: pass
    return ["AP07-XXXX", "TS09-XXXX", "Other"]

def get_latest_progress():
    """Pulls latest entry from progress_logs."""
    try:
        res = conn.table("progress_logs").select("*").order("created_at", desc=True).limit(1).execute()
        return res.data[0] if res.data else None
    except: return None

@st.cache_data(ttl=60)
def load_data():
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
    if not dataframe.empty and 'vehicle' in dataframe.columns:
        veh_logs = dataframe[dataframe['vehicle'] == veh_name]
        if not veh_logs.empty: return int(veh_logs.iloc[0]['end_km'])
    return 0

# --- INITIALIZE DATA ---
df = load_data()
staff_list = get_staff_master()
vehicle_list = get_vehicle_master()
last_update = get_latest_progress()

# --- 3. UI LAYOUT ---
st.title("🚛 B&G Logistics Management System")

# Sidebar: Control Center
with st.sidebar:
    st.header("⚙️ App Controls")
    if st.button("🔄 Sync Master Setup"):
        st.cache_data.clear()
        st.rerun()
    st.divider()
    if last_update:
        st.subheader("📍 Factory Status")
        st.info(f"**{last_update.get('status_update')}**\n\nBy: {last_update.get('staff_name')}")

tabs = st.tabs(["📅 Staff Booking", "👨‍✈️ Brahmiah's Desk", "📝 Trip Logger", "📊 Analytics"])

# --- TAB 1: STAFF BOOKING ---
with tabs[0]:
    with st.form("request_form", clear_on_submit=True):
        st.subheader("Request Vehicle for Work")
        c1, c2 = st.columns(2)
        req_by = c1.selectbox("Staff Name", staff_list)
        dest = c1.text_input("Destination / Site")
        r_date = c2.date_input("Required Date", min_value=date.today())
        r_time = c2.text_input("Required Time")
        reason = st.text_area("Purpose")
        
        if st.form_submit_button("Submit Request"):
            if dest:
                new_req = {"requested_by": req_by, "destination": dest.upper(), "req_date": str(r_date), "req_time": r_time, "purpose": reason, "status": "Pending"}
                conn.table("logistics_requests").insert(new_req).execute()
                wa_msg = f"🚚 *New Vehicle Request*\nStaff: {req_by}\nTo: {dest}"
                st.success("Request sent!"); st.link_button("📲 WhatsApp Brahmiah", f"https://wa.me/919848993939?text={urllib.parse.quote(wa_msg)}")

# --- TAB 2: BRAHMIAH'S DESK ---
with tabs[1]:
    st.subheader("Pending Requests")
    req_data = conn.table("logistics_requests").select("*").eq("status", "Pending").execute().data
    if req_data:
        for r in req_data:
            with st.expander(f"🚩 {r['requested_by']} -> {r['destination']}"):
                v_assign = st.selectbox("Assign Vehicle", vehicle_list, key=f"v{r['id']}")
                if st.button("Approve & Assign", key=f"btn{r['id']}"):
                    conn.table("logistics_requests").update({"status": "Assigned", "assigned_vehicle": v_assign}).eq("id", r['id']).execute()
                    st.rerun()
    else: st.info("No pending requests.")

# --- TAB 3: TRIP LOGGER ---
with tabs[2]:
    with st.form("logistics_form", clear_on_submit=True):
        st.subheader("📝 Log Actual Movement & Fuel")
        col1, col2, col3 = st.columns(3)
        with col1:
            vehicle = st.selectbox("Vehicle (Reg No)", vehicle_list)
            driver = st.selectbox("Driver Name", staff_list)
            purpose = st.selectbox("Purpose", ["Inter-Unit", "Pickup", "Delivery", "Fueling"])
        with col2:
            start_km = st.number_input("Start KM", min_value=0, value=get_last_km(vehicle, df), step=1)
            end_km = st.number_input("End KM", min_value=0, step=1)
            fuel_qty = st.number_input("Fuel Added (Ltrs)", min_value=0.0, step=0.1)
        with col3:
            fuel_rate = st.number_input("Rate (₹/Litre)", min_value=0.0, value=94.5)
            auth_by = st.selectbox("Authorized By", staff_list)
            location = st.text_input("Location")

        # ... (Rest of Submit logic remains as per Golden Master) ...
        if st.form_submit_button("🚀 SUBMIT LOG"):
             pass
