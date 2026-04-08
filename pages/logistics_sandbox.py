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
    st.subheader("📋 Complete Booking History")
    status_data = conn.table("logistics_requests").select("*").order("created_at", desc=True).execute().data
    if status_data:
        df_history = pd.DataFrame(status_data)
        # ADD THIS LINE: Convert UTC to IST for display
        df_history['req_date'] = pd.to_datetime(df_history['created_at']).dt.tz_convert('Asia/Kolkata').dt.strftime('%d %b, %I:%M %p')
        st.dataframe(df_history[['requested_by', 'destination', 'req_date', 'assigned_vehicle', 'status']], use_container_width=True, hide_index=True)

# --- TAB 2: BRAHMIAH'S DESK (MODIFIED WITH TIMESTAMP) ---
with tabs[1]:
    st.subheader("👨‍✈️ Operations & Manual Controls")
    
    all_res = conn.table("logistics_requests").select("*").order("created_at", desc=True).execute().data
    ardf = pd.DataFrame(all_res) if all_res else pd.DataFrame()

    if not ardf.empty:
        m1, m2, m3 = st.columns(3)
        m1.metric("Pending Approval", len(ardf[ardf['status'] == 'Pending']))
        m2.metric("In-Trip (Assigned)", len(ardf[ardf['status'] == 'Assigned']))
        m3.metric("Closed Today", len(ardf[(ardf['status'] == 'Trip Closed') & (ardf['req_date'] == str(date.today()))]))

    # SECTION 1: APPROVALS
    st.markdown("### 📬 Pending Approvals")
    pending = ardf[ardf['status'] == 'Pending'] if not ardf.empty else pd.DataFrame()
    if not pending.empty:
        for _, r in pending.iterrows():
            with st.expander(f"🚩 APPROVE: {r['requested_by']} to {r['destination']}"):
                v_assign = st.selectbox("Assign Vehicle", vehicle_list, key=f"v{r['id']}")
                if st.button("Confirm Assignment", key=f"btn{r['id']}"):
                    conn.table("logistics_requests").update({"status": "Assigned", "assigned_vehicle": v_assign}).eq("id", r['id']).execute()
                    st.rerun()
    else: st.info("No pending requests.")

    st.divider()

    # SECTION 2: LIVE & RECENTLY CLOSED TRIPS
    st.markdown("### 🚚 Live Trips & Activity Switch")
    # We show both Assigned and Closed to ensure Brahmiah sees the status "Switch"
    activity_filter = ardf[ardf['status'].isin(['Assigned', 'Trip Closed'])].head(20) 
    
    if not activity_filter.empty:
        for _, r in activity_filter.iterrows():
            # Adjusting columns to accommodate the timestamp [Info, Status, Time, Action]
            c1, c2, c3, c4 = st.columns([3, 1.5, 1.5, 1])
            
            status_color = "🟢" if r['status'] == "Assigned" else "✅"
            c1.write(f"{status_color} **{r['assigned_vehicle']}** | {r['requested_by']} ➔ {r['destination']}")
            
            c2.write(f"**{r['status']}**")
            
            # --- TIMESTAMP LOGIC ---
            # Extracting just the time/date from created_at
            try:
                raw_ts = r.get('created_at', '')
                clean_ts = pd.to_datetime(raw_ts).strftime('%d %b, %H:%M') if raw_ts else "N/A"
            except:
                clean_ts = "N/A"
            c3.write(f"🕒 {clean_ts}")
            
            # Show "Close Trip" button ONLY if it is still Assigned
            if r['status'] == "Assigned":
                if c4.button("Close", key=f"close_br{r['id']}", use_container_width=True):
                    conn.table("logistics_requests").update({"status": "Trip Closed"}).eq("id", r['id']).execute()
                    st.toast(f"Trip for {r['assigned_vehicle']} is now CLOSED.")
                    st.rerun()
            else:
                c4.write("Done")
    else: st.info("No recent trip activity.")

# --- TAB 3: TRIP LOGGER (WITH TIMESTAMP) ---
with tabs[2]:
    st.subheader("📝 Driver Log & Trip Closure")
    
    # Updated query to include 'created_at' for the timestamp
    active_trips_res = conn.table("logistics_requests")\
        .select("assigned_vehicle, destination, requested_by, created_at")\
        .eq("status", "Assigned")\
        .execute()
    
    if active_trips_res.data:
        st.write("**Vehicles currently out:**")
        active_df = pd.DataFrame(active_trips_res.data)
        
        # Clean up the timestamp for display
        active_df['assigned_at'] = pd.to_datetime(active_df['created_at']).dt.strftime('%H:%M (%d %b)')
        
        # Reorder and display relevant columns
        st.dataframe(
            active_df[['assigned_vehicle', 'destination', 'requested_by', 'assigned_at']], 
            use_container_width=True, 
            hide_index=True
        )

    with st.form("logistics_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            vehicle = st.selectbox("Vehicle", vehicle_list, key="log_veh")
            driver = st.selectbox("Driver Name", staff_list, key="log_driver")
        with col2:
            # get_last_km(vehicle, df) ensures continuity in odometer readings
            start_km = st.number_input("Start KM", min_value=0, value=get_last_km(vehicle, df), step=1)
            end_km = st.number_input("End KM", min_value=0, step=1)
        with col3:
            fuel_qty = st.number_input("Fuel Added (Ltrs)", min_value=0.0)
            auth_by = st.selectbox("Authorized By", staff_list, key="log_auth")
      
        location = st.text_input("Current Location / Final Destination")
        st.camera_input("Capture Odometer Reading")

        if st.form_submit_button("🚀 SUBMIT LOG & CLOSE TRIP"):
            if end_km > start_km and location:
                # We record the exact completion time here
                finish_time = datetime.now(IST).strftime('%Y-%m-%d %H:%M')
                
                new_entry = {
                    "timestamp": finish_time, 
                    "vehicle": vehicle, 
                    "driver": driver, 
                    "start_km": start_km, 
                    "end_km": end_km, 
                    "distance": end_km - start_km, 
                    "fuel_ltrs": fuel_qty, 
                    "location": location.upper()
                }
                
                try:
                    conn.table("logistics_logs").insert(new_entry).execute()
                    # Closing the request status
                    conn.table("logistics_requests").update({"status": "Trip Closed"}).eq("assigned_vehicle", vehicle).eq("status", "Assigned").execute()
                    st.cache_data.clear()
                    st.success(f"✅ Logged at {finish_time} & Trip Closed!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving log: {e}")
            else:
                st.warning("Please ensure End KM is greater than Start KM and Location is entered.")

# --- TAB 4: 
with tabs[3]:
    st.subheader("📊 Fleet Performance")
    if not df.empty:
        st.metric("Total KM Covered", f"{df['distance'].sum():,}")
        st.dataframe(df[['timestamp', 'vehicle', 'driver', 'distance', 'location']], use_container_width=True, hide_index=True)

# --- TAB 5: EXPORT & REPORTS (FIXED & IST ENABLED) ---
with tabs[4]:
    st.subheader("📥 Export Reports")
    
    target = st.radio(
        "Select Data to Export", 
        ["Full Trip Logs", "All Booking Requests"], 
        horizontal=True, 
        key="export_data_selector"
    )
    
    # 1. FIXED MAPPING: 
    # If your logistics_logs table also uses 'created_at', change s_col below to "created_at"
    if target == "Full Trip Logs":
        t_name = "logistics_logs"
        s_col = "timestamp"   # <--- IF ERROR PERSISTS, CHANGE THIS TO "created_at"
    else:
        t_name = "logistics_requests"
        s_col = "created_at" 

    try:
        res_exp = conn.table(t_name).select("*").order(s_col, desc=True).execute()
        
        if res_exp.data:
            export_df = pd.DataFrame(res_exp.data)
            
            # 2. IST TIME CONVERSION (Indian Time Fix)
            if s_col in export_df.columns:
                try:
                    # Convert to datetime, localize to UTC, then convert to IST
                    export_df[s_col] = pd.to_datetime(export_df[s_col]).dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata').dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    # Fallback if already localized or format is different
                    export_df[s_col] = pd.to_datetime(export_df[s_col]).dt.strftime('%Y-%m-%d %H:%M:%S')
    
            st.write(f"📊 Previewing {len(export_df)} records from {t_name} (Indian Standard Time):")
            st.dataframe(export_df, use_container_width=True, hide_index=True)
            
            # 3. CSV Download Trigger
            csv_data = export_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label=f"💾 Download {target} (CSV)",
                data=csv_data,
                file_name=f"BG_Logistics_{t_name}_{date.today()}.csv",
                mime='text/csv',
                key="final_export_button"
            )
        else:
            st.info(f"📭 No data found in the '{t_name}' table yet.")
            
    except Exception as e:
        # Check if the error is specifically about the 'timestamp' column
        st.error(f"❌ Database Sync Error: The column '{s_col}' was not found in table '{t_name}'.")
        st.info("💡 Tip: Check your Supabase table. If the column is named 'created_at', we need to update the mapping in the code.")
