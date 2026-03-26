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
            num_cols = ['distance', 'fuel_ltrs', 'fuel_rate', 'total_fuel_cost', 'start_km', 'end_km']
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
                new_req = {
                    "requested_by": req_by, "destination": dest.upper(), 
                    "req_date": str(r_date), "req_time": r_time, 
                    "purpose": req_purpose, "assigned_vehicle": req_veh, "status": "Pending"
                }
                conn.table("logistics_requests").insert(new_req).execute()
                st.success("Request logged!"); st.rerun()
            else:
                st.error("Please provide a destination.")

    st.divider()
    st.subheader("📋 Your Recent Request Status")
    try:
        status_data = conn.table("logistics_requests").select("*").order("created_at", desc=True).limit(10).execute().data
        if status_data:
            st.dataframe(pd.DataFrame(status_data)[['requested_by', 'destination', 'req_date', 'status']], use_container_width=True, hide_index=True)
    except: pass

# --- TAB 2: BRAHMIAH'S DESK (UPDATED) ---
with tabs[1]:
    st.subheader("👨‍✈️ Fleet Operations Summary")
    
    # 1. FETCH ALL ACTIVE DATA
    try:
        all_reqs_res = conn.table("logistics_requests").select("*").order("created_at", desc=True).execute()
        all_reqs_df = pd.DataFrame(all_reqs_res.data) if all_reqs_res.data else pd.DataFrame()
        
        if not all_reqs_df.empty:
            # Create Status Metrics
            m1, m2, m3 = st.columns(3)
            m1.metric("Pending Approval", len(all_reqs_df[all_reqs_df['status'] == 'Pending']))
            m2.metric("Assigned/In-Trip", len(all_reqs_df[all_reqs_df['status'] == 'Assigned']))
            m3.metric("Completed Today", len(all_reqs_df[(all_reqs_df['status'] == 'Completed') & (all_reqs_df['req_date'] == str(date.today()))]))

            # Summary Table with Style
            st.markdown("#### 📑 Real-time Request Pipeline")
            
            def style_status(val):
                color = '#e67e22' if val == 'Pending' else '#2ecc71' if val == 'Assigned' else '#3498db'
                return f'background-color: {color}; color: white; font-weight: bold; border-radius: 5px;'

            display_cols = ['requested_by', 'destination', 'req_date', 'assigned_vehicle', 'status']
            st.dataframe(
                all_reqs_df[display_cols].style.applymap(style_status, subset=['status']),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No logistics data available.")
    except Exception as e:
        st.error(f"Error loading summary: {e}")

    st.divider()
    st.subheader("📬 Pending Approvals (Action Required)")
    
    # Approval Logic
    pending_data = all_reqs_df[all_reqs_df['status'] == 'Pending'].to_dict('records') if not all_reqs_df.empty else []
    
    if pending_data:
        for r in pending_data:
            with st.expander(f"🚩 APPROVE: {r['requested_by']} ➔ {r['destination']} ({r['req_time']})"):
                c1, c2 = st.columns([2, 1])
                v_assign = c1.selectbox("Confirm/Change Vehicle", vehicle_list, index=vehicle_list.index(r['assigned_vehicle']) if r['assigned_vehicle'] in vehicle_list else 0, key=f"v{r['id']}")
                if c2.button("✅ Approve & Assign", key=f"btn{r['id']}", use_container_width=True):
                    conn.table("logistics_requests").update({"status": "Assigned", "assigned_vehicle": v_assign}).eq("id", r['id']).execute()
                    st.toast(f"Assigned {v_assign} to {r['requested_by']}")
                    st.rerun()
    else: 
        st.success("All clear! No pending approvals.")

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
                new_entry = {"timestamp": datetime.now(IST).strftime('%Y-%m-%d %H:%M'), "vehicle": vehicle, "driver": driver, "start_km": start_km, "end_km": end_km, "distance": end_km-start_km, "fuel_ltrs": fuel_qty, "location": location.upper()}
                conn.table("logistics_logs").insert(new_entry).execute()
                # Update request status to Completed if applicable
                conn.table("logistics_requests").update({"status": "Completed"}).eq("assigned_vehicle", vehicle).eq("status", "Assigned").execute()
                st.cache_data.clear(); st.success("✅ Trip Closed & Logged!"); st.rerun()

# --- TAB 4: ANALYTICS ---
with tabs[3]:
    if not df.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total KM", f"{df['distance'].sum():,}")
        c2.metric("Total Fuel", f"{df['fuel_ltrs'].sum():,} L")
        c3.metric("Logs Count", len(df))
        st.dataframe(df.head(20), use_container_width=True, hide_index=True)

# --- TAB 5: EXPORT ---
with tabs[4]:
    target = st.radio("Select Table", ["Trip Logs", "Vehicle Requests"], horizontal=True)
    export_table = "logistics_logs" if target == "Trip Logs" else "logistics_requests"
    export_df = pd.DataFrame(conn.table(export_table).select("*").execute().data)
    if not export_df.empty:
        st.download_button("💾 Download CSV", export_df.to_csv(index=False).encode('utf-8'), f"bg_{export_table}.csv", "text/csv")
