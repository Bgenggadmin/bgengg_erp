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
    st.subheader("📋 My Request Summary")
    status_res = conn.table("logistics_requests").select("requested_by, destination, req_date, req_time, assigned_vehicle, status").order("created_at", desc=True).limit(10).execute()
    if status_res.data:
        st.table(pd.DataFrame(status_res.data))

# --- TAB 2: BRAHMIAH'S DESK ---
with tabs[1]:
    st.subheader("📬 Operations Command Center")
    all_reqs_res = conn.table("logistics_requests").select("*").order("created_at", desc=True).execute()
    ardf = pd.DataFrame(all_reqs_res.data) if all_reqs_res.data else pd.DataFrame()

    if not ardf.empty:
        m1, m2, m3 = st.columns(3)
        m1.metric("Pending Approval", len(ardf[ardf['status'] == 'Pending']))
        m2.metric("Active (In-Trip)", len(ardf[ardf['status'] == 'Assigned']))
        m3.metric("Closed Today", len(ardf[(ardf['status'] == 'Trip Closed') & (ardf['req_date'] == str(date.today()))]))

        st.markdown("#### 📑 Fleet Movement Table")
        # Showing high importance fields for Brahmiah
        st.dataframe(ardf[['requested_by', 'assigned_vehicle', 'destination', 'req_date', 'status']], use_container_width=True, hide_index=True)

    # Action Area for Approvals
    pending_reqs = ardf[ardf['status'] == 'Pending'] if not ardf.empty else []
    if len(pending_reqs) > 0:
        st.divider()
        st.subheader("⚠️ Action Required")
        for _, r in pending_reqs.iterrows():
            with st.expander(f"🚩 APPROVE: {r['requested_by']} to {r['destination']}"):
                v_assign = st.selectbox("Assign Vehicle", vehicle_list, key=f"v{r['id']}")
                if st.button("Confirm & Assign", key=f"btn{r['id']}"):
                    conn.table("logistics_requests").update({"status": "Assigned", "assigned_vehicle": v_assign}).eq("id", r['id']).execute()
                    st.rerun()

# --- TAB 3: TRIP LOGGER ---
with tabs[2]:
    st.subheader("📝 End Trip & Update KMs")
    # Show active trips that need closing
    active_trips_res = conn.table("logistics_requests").select("requested_by, assigned_vehicle, destination").eq("status", "Assigned").execute()
    if active_trips_res.data:
        st.info("💡 Reminder: The following vehicles are currently out on trips.")
        st.table(pd.DataFrame(active_trips_res.data))

    with st.form("logistics_form", clear_on_submit=True):
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
      
        location = st.text_input("Current Location / Final Site")
        st.camera_input("Capture Odometer Reading")

        if st.form_submit_button("🚀 SUBMIT LOG & CLOSE TRIP"):
            if end_km > start_km and location:
                new_entry = {
                    "timestamp": datetime.now(IST).strftime('%Y-%m-%d %H:%M'), 
                    "vehicle": vehicle, "driver": driver, "start_km": start_km, "end_km": end_km, 
                    "distance": end_km-start_km, "fuel_ltrs": fuel_qty, "location": location.upper()
                }
                conn.table("logistics_logs").insert(new_entry).execute()
                conn.table("logistics_requests").update({"status": "Trip Closed"}).eq("assigned_vehicle", vehicle).eq("status", "Assigned").execute()
                st.cache_data.clear(); st.success("✅ Logged & Trip Closed!"); st.rerun()

# --- TAB 4: ANALYTICS ---
with tabs[3]:
    st.subheader("📊 Performance Summary")
    if not df.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Distance", f"{df['distance'].sum():,} KM")
        c2.metric("Total Fuel Consumed", f"{df['fuel_ltrs'].sum():,} L")
        c3.metric("Avg KM per Trip", f"{round(df['distance'].mean(), 2)}")
        
        st.markdown("#### 📑 Detailed Trip History")
        st.dataframe(df[['timestamp', 'vehicle', 'driver', 'distance', 'location']], use_container_width=True, hide_index=True)

# --- TAB 5: EXPORT & REPORTS ---
with tabs[4]:
    st.subheader("📥 Data Export Table")
    target = st.radio("Select View", ["All Trip Logs", "All Booking Requests"], horizontal=True)
    table_name = "logistics_logs" if target == "All Trip Logs" else "logistics_requests"
    export_df = pd.DataFrame(conn.table(table_name).select("*").execute().data)
    
    if not export_df.empty:
        st.dataframe(export_df, use_container_width=True)
        st.download_button("💾 Download CSV", export_df.to_csv(index=False).encode('utf-8'), f"bg_{table_name}.csv")
