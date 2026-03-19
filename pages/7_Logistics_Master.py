import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz
from io import BytesIO
from PIL import Image
import urllib.parse

# --- 1. SETUP & UTILITIES ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Logistics | Fleet Tracker", layout="wide")

try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception as e:
    st.error("❌ Supabase Connection Failed!"); st.stop()

# --- 2. FUNCTIONS (Must be at the TOP) ---

@st.cache_data(ttl=600)
def get_staff_master():
    try:
        res = conn.table("master_staff").select("name").order("name").execute()
        return [item['name'] for item in res.data] if res.data else ["Admin"]
    except: return ["Admin", "Staff"]

@st.cache_data(ttl=600)
def get_vehicle_master():
    try:
        res = conn.table("master_vehicles").select("reg_no").order("reg_no").execute()
        return [item['reg_no'] for item in res.data] if res.data else ["AP07-XXXX"]
    except: return ["AP07-XXXX", "TS09-XXXX"]

@st.cache_data(ttl=60)
def load_logistics_data():
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

# Initialize Global Data
staff_list = get_staff_master()
vehicle_list = get_vehicle_master()
df = load_logistics_data()
purpose_list = ["Site Delivery", "Material pickup","Material droping","Material Pickup & Drop","Inter-Unit Transfer", "Client Pickup & Drop", "Vendor Visit", "Fueling", "Maintenance", "Other"]

# --- 3. UI LAYOUT ---
st.title("🚛 B&G Logistics Management System")

with st.sidebar:
    if st.button("🔄 Sync Master Data"):
        st.cache_data.clear()
        st.rerun()

tabs = st.tabs(["📅 Staff Booking", "👨‍✈️ Brahmiah's Desk", "📝 Trip Logger", "📊 Analytics", "📥 Export & Reports"])

# --- TAB 1: STAFF BOOKING ---
with tabs[0]:
    # 1. Booking Form
    with st.form("request_form", clear_on_submit=True):
        st.subheader("Request Vehicle for Work")
        c1, c2 = st.columns(2)
        req_by = c1.selectbox("Staff Name", staff_list, key="bk_staff")
        req_veh = c1.selectbox("Preferred Vehicle", vehicle_list, key="bk_veh")
        dest = c1.text_input("Destination / Site")
        r_date = c2.date_input("Required Date", min_value=date.today())
        r_time = c2.text_input("Required Time (e.g. 9:00 AM)")
        req_purpose = c2.selectbox("Purpose", purpose_list, key="bk_purpose")
        
        if st.form_submit_button("Submit Request"):
            if dest:
                new_req = {
                    "requested_by": req_by, 
                    "destination": dest.upper(), 
                    "req_date": str(r_date), 
                    "req_time": r_time, 
                    "purpose": req_purpose, 
                    "assigned_vehicle": req_veh, 
                    "status": "Pending"
                }
                conn.table("logistics_requests").insert(new_req).execute()
                st.success("Request logged!"); st.rerun()
            else:
                st.error("Please provide a destination.")

    # 2. ADDED: Status Summary Table (Below the form)
    st.divider()
    st.subheader("📋 Your Recent Request Status")
    try:
        # Fetching last 10 requests to keep it fast
        status_data = conn.table("logistics_requests").select(
            "requested_by, destination, purpose, req_date, req_time, assigned_vehicle, status"
        ).order("created_at", desc=True).limit(10).execute().data
        
        if status_data:
            status_df = pd.DataFrame(status_data)
            
            # Apply styling for better readability
            def color_status(val):
                color = '#FFA500' if val == 'Pending' else '#008000'
                return f'color: {color}; font-weight: bold'

            st.dataframe(
                status_df.style.applymap(color_status, subset=['status']),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No recent requests found.")
    except Exception as e:
        st.error(f"Status Load Error: {e}")

# --- TAB 2: BRAHMIAH'S DESK ---
with tabs[1]:
    st.subheader("📬 Pending Approvals")
    req_data = conn.table("logistics_requests").select("*").ilike("status", "Pending").execute().data
    if req_data:
        for r in req_data:
            with st.expander(f"🚩 {r['requested_by']} to {r['destination']}"):
                v_assign = st.selectbox("Assign Vehicle", vehicle_list, key=f"v{r['id']}")
                if st.button("Approve & Assign", key=f"btn{r['id']}"):
                    conn.table("logistics_requests").update({"status": "Assigned", "assigned_vehicle": v_assign}).eq("id", r['id']).execute()
                    st.rerun()
    else: st.info("No pending requests.")

# --- TAB 3: TRIP LOGGER ---
with tabs[2]:
    with st.form("logistics_form", clear_on_submit=True):
        st.subheader("📝 Log Actual Movement")
        col1, col2, col3 = st.columns(3)
        with col1:
            vehicle = st.selectbox("Vehicle", vehicle_list, key="log_veh")
            driver = st.selectbox("Driver Name", staff_list, key="log_driver")
        with col2:
            start_km = st.number_input("Start KM", min_value=0, value=get_last_km(vehicle, df), step=1)
            end_km = st.number_input("End KM", min_value=0, step=1)
        with col3:
            fuel_qty = st.number_input("Fuel Added", min_value=0.0)
            auth_by = st.selectbox("Authorized By", staff_list, key="log_auth")
        
        location = st.text_input("Location / Site")
        cam_photo = st.camera_input("Capture Odometer/Bill")

        if st.form_submit_button("🚀 SUBMIT LOG"):
            if end_km > start_km and location:
                # Logic for photo upload and Supabase insert (Standard Golden Master logic)
                new_entry = {"timestamp": datetime.now(IST).strftime('%Y-%m-%d %H:%M'), "vehicle": vehicle, "driver": driver, "start_km": start_km, "end_km": end_km, "distance": end_km-start_km, "fuel_ltrs": fuel_qty, "location": location.upper()}
                conn.table("logistics_logs").insert(new_entry).execute()
                st.cache_data.clear(); st.success("✅ Logged!"); st.rerun()

# --- TAB 4: ANALYTICS ---
with tabs[3]:
    if not df.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total KM", f"{df['distance'].sum():,}")
        c2.metric("Total Fuel", f"{df['fuel_ltrs'].sum():,} L")
        c3.metric("Logs Count", len(df))
        st.dataframe(df.head(20), use_container_width=True, hide_index=True)

# --- TAB 5: EXPORT & REPORTS ---
with tabs[4]:
    st.subheader("📥 Data Export")
    target = st.radio("Select Table", ["Trip Logs", "Vehicle Requests"], horizontal=True)
    export_table = "logistics_logs" if target == "Trip Logs" else "logistics_requests"
    
    export_df = pd.DataFrame(conn.table(export_table).select("*").execute().data)
    if not export_df.empty:
        st.dataframe(export_df.head(10), use_container_width=True)
        st.download_button("💾 Download CSV", export_df.to_csv(index=False).encode('utf-8'), f"bg_{export_table}.csv", "text/csv")
