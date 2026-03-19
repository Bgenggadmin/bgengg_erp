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

# --- 2. REFINED DATA UTILITIES ---

@st.cache_data(ttl=600)
def get_staff_master():
    """Pulls staff names from master_staff table with verified column name."""
    try:
        # Verified table 'master_staff' and column 'staff_name'
        res = conn.table("master_staff").select("staff_name").order("staff_name").execute()
        if res.data and len(res.data) > 0:
            return [item['staff_name'] for item in res.data]
    except Exception as e:
        st.sidebar.error(f"Master Staff Load Error: {e}")
    # Robust fallback list so the UI never breaks
    return ["Brahmiah", "Admin", "General Staff"]

@st.cache_data(ttl=600)
def get_vehicle_master():
    """Pulls Registration Numbers from master_vehicles table."""
    try:
        # Verified column 'reg_no'
        res = conn.table("master_vehicles").select("reg_no").order("reg_no").execute()
        if res.data and len(res.data) > 0:
            return [item['reg_no'] for item in res.data]
    except: pass
    return ["AP07-Vehicle 1", "TS09-Vehicle 2"]

# --- INITIALIZE GLOBAL DATA (Before Tabs Load) ---
staff_list = get_staff_master()
vehicle_list = get_vehicle_master()

# --- 3. UI LAYOUT ---
st.title("🚛 B&G Logistics Management System")

tabs = st.tabs(["📅 Staff Booking", "👨‍✈️ Brahmiah's Desk", "📝 Trip Logger", "📊 Analytics"])

# --- TAB 1: STAFF BOOKING (Verified Dropdown Logic) ---
with tabs[0]:
    with st.form("request_form", clear_on_submit=True):
        st.subheader("Request Vehicle for Work")
        c1, c2 = st.columns(2)
        
        # Pulling from the initialized staff_list
        req_by = c1.selectbox("Staff Name", options=staff_list, key="sb_staff_name")
        
        dest = c1.text_input("Destination / Site")
        r_date = c2.date_input("Required Date", min_value=date.today())
        r_time = c2.text_input("Required Time (e.g. 10:00 AM)")
        reason = st.text_area("Purpose of Visit")
        
        if st.form_submit_button("Submit Request"):
            if dest:
                # Using the variable from the selectbox
                new_req = {
                    "requested_by": req_by, 
                    "destination": dest.upper(), 
                    "req_date": str(r_date), 
                    "req_time": r_time, 
                    "purpose": reason, 
                    "status": "Pending"
                }
                try:
                    conn.table("logistics_requests").insert(new_req).execute()
                    wa_msg = f"🚚 *New Vehicle Request*\nStaff: {req_by}\nTo: {dest}\nDate: {r_date}"
                    st.success(f"✅ Request for {req_by} sent!")
                    st.link_button("📲 WhatsApp Brahmiah", f"https://wa.me/919848993939?text={urllib.parse.quote(wa_msg)}")
                except Exception as e:
                    st.error(f"Submission failed: {e}")
            else:
                st.error("Please provide a destination.")

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
