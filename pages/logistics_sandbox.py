import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz

# --- 1. SETUP & UTILITIES ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Logistics | Fleet Tracker", layout="wide")
try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception as e:
    st.error("❌ Supabase Connection Failed!"); st.stop()

# --- 2. FUNCTIONS ---
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
            num_cols = ['distance', 'fuel_ltrs', 'start_km', 'end_km']
            for col in num_cols:
                if col in _df.columns:
                    _df[col] = pd.to_numeric(_df[col], errors='coerce').fillna(0)
            return _df
    except: pass
    return pd.DataFrame(columns=["timestamp", "vehicle", "end_km", "distance", "fuel_ltrs"])

def get_last_km(veh_name, dataframe):
    try:
        if not dataframe.empty and 'vehicle' in dataframe.columns:
            veh_logs = dataframe[dataframe['vehicle'] == veh_name]
            if not veh_logs.empty:
                last_val = veh_logs.iloc[0]['end_km']
                if pd.notnull(last_val):
                    return int(float(last_val)) 
    except: pass
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
                new_req = {"requested_by": req_by, "destination": dest.upper(), "req_date": str(r_date), "req_time": r_time, "purpose": req_purpose, "assigned_vehicle": req_veh, "status": "Pending"}
                conn.table("logistics_requests").insert(new_req).execute()
                st.success("Request logged!"); st.rerun()

    st.divider()
    st.subheader("📋 Recent Status")
    status_data = conn.table("logistics_requests").select("*").order("created_at", desc=True).limit(10).execute().data
    if status_data:
        st.dataframe(pd.DataFrame(status_data)[['requested_by', 'destination', 'assigned_vehicle', 'status']], use_container_width=True, hide_index=True)

# --- TAB 2: BRAHMIAH'S DESK ---
with tabs[1]:
    st.subheader("📬 Approval Queue & Live Trips")
    
    # 1. Summary Metrics
    all_reqs = conn.table("logistics_requests").select("*").execute().data
    if all_reqs:
        ardf = pd.DataFrame(all_reqs)
        m1, m2, m3 = st.columns(3)
        m1.metric("Pending", len(ardf[ardf['status'] == 'Pending']))
        m2.metric("In-Trip (Assigned)", len(ardf[ardf['status'] == 'Assigned']))
        m3.metric("Closed Today", len(ardf[(ardf['status'] == 'Trip Closed') & (ardf['req_date'] == str(date.today()))]))

    # 2. Action Area
    req_data = conn.table("logistics_requests").select("*").eq("status", "Pending").execute().data
    if req_data:
        for r in req_data:
            with st.expander(f"🚩 APPROVE: {r['requested_by']} to {r['destination']}"):
                v_assign = st.selectbox("Assign Vehicle", vehicle_list, key=f"v{r['id']}")
                if st.button("Confirm Assignment", key=f"btn{r['id']}"):
                    conn.table("logistics_requests").update({"status": "Assigned", "assigned_vehicle": v_assign}).eq("id", r['id']).execute()
                    st.rerun()
    else: st.info("No pending requests to approve.")

# --- TAB 3: TRIP LOGGER (WITH TRIP CLOSED LOGIC) ---
with tabs[2]:
    with st.form("logistics_form", clear_on_submit=True):
        st.subheader("📝 End Trip & Log Movement")
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
      
        location = st.text_input("Current Location / Final Destination")
        st.camera_input("Capture Odometer Reading")

        if st.form_submit_button("🚀 SUBMIT LOG & CLOSE TRIP"):
            if end_km > start_km and location:
                # 1. Insert into Logistics Logs (The History)
                new_entry = {
                    "timestamp": datetime.now(IST).strftime('%Y-%m-%d %H:%M'), 
                    "vehicle": vehicle, "driver": driver, 
                    "start_km": start_km, "end_km": end_km, 
                    "distance": end_km-start_km, "fuel_ltrs": fuel_qty, 
                    "location": location.upper()
                }
                conn.table("logistics_logs").insert(new_entry).execute()
                
                # 2. TRIP CLOSED LOGIC: Update the active request
                # We find the most recent 'Assigned' request for this specific vehicle and close it.
                conn.table("logistics_requests").update({"status": "Trip Closed"})\
                    .eq("assigned_vehicle", vehicle)\
                    .eq("status", "Assigned").execute()
                
                st.cache_data.clear()
                st.success(f"✅ Logged! Trip for {vehicle} is now CLOSED.")
                st.rerun()
            else:
                st.error("Invalid Entry: End KM must be greater than Start KM.")

# --- TAB 4 & 5 (Analytics & Export) ---
with tabs[3]:
    if not df.empty:
        st.metric("Total KM Managed", f"{df['distance'].sum():,}")
        st.dataframe(df, use_container_width=True, hide_index=True)

with tabs[4]:
    target = st.radio("Select Table", ["Trip Logs", "Vehicle Requests"], horizontal=True)
    export_table = "logistics_logs" if target == "Trip Logs" else "logistics_requests"
    export_df = pd.DataFrame(conn.table(export_table).select("*").execute().data)
    if not export_df.empty:
        st.download_button("💾 Download CSV", export_df.to_csv(index=False).encode('utf-8'), f"bg_{export_table}.csv")
