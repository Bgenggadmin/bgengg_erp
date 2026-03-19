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

# --- 2. MASTER & PROGRESS UTILITIES ---

@st.cache_data(ttl=600) # High Speed: Cache staff list for 10 mins
def get_staff_master():
    """Pulls staff names from your existing Master Setup table"""
    try:
        # Assumes table 'master_setup' and column 'staff_name'
        res = conn.table("master_setup").select("staff_name").order("staff_name").execute()
        if res.data:
            return [item['staff_name'] for item in res.data]
    except: pass
    return ["Brahmiah", "Admin", "Other"] # Fallback

def get_latest_progress():
    """Pulls the single most recent entry from progress_logs for a quick status view"""
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

# Initialize Global Data
df = load_data()
staff_list = get_staff_master()
last_update = get_latest_progress()

# --- 3. UI LAYOUT ---
st.title("🚛 B&G Logistics Management System")

# Minimal Change: Quick Status Bar
if last_update:
    st.caption(f"📢 **Last Progress:** {last_update.get('status_update')} | **By:** {last_update.get('staff_name')} | {last_update.get('created_at')[:16]}")

tabs = st.tabs(["📅 Staff Booking", "👨‍✈️ Brahmiah's Desk", "📝 Trip Logger", "📊 Analytics"])

# --- TAB 1: STAFF BOOKING ---
with tabs[0]:
    with st.form("request_form", clear_on_submit=True):
        st.subheader("Request Vehicle for Work")
        c1, c2 = st.columns(2)
        # UPDATED: Pulls from Master Setup
        req_by = c1.selectbox("Staff Name", staff_list)
        dest = c1.text_input("Destination / Site")
        r_date = c2.date_input("Required Date", min_value=date.today())
        r_time = c2.text_input("Required Time (e.g., 9:00 AM)")
        reason = st.text_area("Purpose of Visit")
        
        if st.form_submit_button("Submit Request"):
            if dest:
                new_req = {"requested_by": req_by, "destination": dest.upper(), "req_date": str(r_date), "req_time": r_time, "purpose": reason, "status": "Pending"}
                conn.table("logistics_requests").insert(new_req).execute()
                wa_msg = f"🚚 *New Request*\nStaff: {req_by}\nTo: {dest}\nDate: {r_date}\nTime: {r_time}"
                st.success("Request sent!"); st.link_button("📲 WhatsApp Brahmiah", f"https://wa.me/919848993939?text={urllib.parse.quote(wa_msg)}")

# --- TAB 2: BRAHMIAH'S DESK ---
with tabs[1]:
    st.subheader("Manage Active Requests")
    req_data = conn.table("logistics_requests").select("*").eq("status", "Pending").execute().data
    if req_data:
        for r in req_data:
            with st.expander(f"🚩 {r['requested_by']} to {r['destination']}"):
                v_assign = st.selectbox("Assign Vehicle", ["Ashok Leyland", "Mahindra", "Other"], key=f"v{r['id']}")
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
            vehicle = st.selectbox("Vehicle", ["Ashok Leyland", "Mahindra", "Other"])
            # UPDATED: Pulls from Master Setup
            driver = st.selectbox("Driver Name", staff_list)
            purpose = st.selectbox("Purpose", ["Inter-Unit (500m)", "Pickup", "Site Delivery", "Fueling"])
        with col2:
            start_km = st.number_input("Start KM Reading", min_value=0, value=get_last_km(vehicle, df), step=1)
            end_km = st.number_input("End KM Reading", min_value=0, step=1)
            fuel_qty = st.number_input("Fuel Added (Litres)", min_value=0.0, step=0.1)
        with col3:
            fuel_rate = st.number_input("Fuel Rate (₹/Litre)", min_value=0.0, value=94.5, step=0.1)
            # UPDATED: Pulls from Master Setup
            auth_by = st.selectbox("Authorized By", staff_list)
            location = st.text_input("Location (Required)", placeholder="e.g. Unit 2")
            total_fuel_cost = round(fuel_qty * fuel_rate, 2)
            if fuel_qty > 0: st.info(f"💰 Fuel Cost: ₹{total_fuel_cost}")

        items = st.text_area("Item Details / Remarks")
        cam_photo = st.camera_input("Capture Bill / Odometer Photo")

        if st.form_submit_button("🚀 SUBMIT LOG"):
            if end_km != 0 and end_km < start_km: st.error("❌ Error: End KM < Start KM!")
            elif not location: st.error("❌ Error: Location is mandatory.")
            else:
                photo_fn = ""
                if cam_photo:
                    try:
                        img = Image.open(cam_photo); img.thumbnail((600, 600))
                        buf = BytesIO(); img.save(buf, format="JPEG", quality=50, optimize=True)
                        photo_fn = f"log_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}.jpg"
                        conn.client.storage.from_("logistics-photos").upload(path=photo_fn, file=buf.getvalue(), file_options={"content-type": "image/jpeg"})
                    except: st.warning("Photo failed, saving data only.")
                
                trip_dist = end_km - start_km if end_km > start_km else 0
                new_entry = {
                    "timestamp": datetime.now(IST).strftime('%Y-%m-%d %H:%M'), "vehicle": vehicle, "driver": driver, 
                    "authorized_by": auth_by, "start_km": start_km, "end_km": end_km, "distance": trip_dist,
                    "fuel_ltrs": fuel_qty, "fuel_rate": fuel_rate, "total_fuel_cost": total_fuel_cost,
                    "purpose": purpose, "location": location.upper(), "items": items.upper(), "photo_path": photo_fn
                }
                conn.table("logistics_logs").insert(new_entry).execute()
                st.cache_data.clear(); st.success("✅ Log Saved!"); st.rerun()

# --- TAB 4: ANALYTICS ---
with tabs[3]:
    if not df.empty:
        c1, c2, c3 = st.columns(3)
        d_sum, f_sum = df['distance'].sum(), df['fuel_ltrs'].sum()
        c1.metric("Total Distance", f"{d_sum:,} KM")
        c2.metric("Total Fuel Spend", f"₹{df['total_fuel_cost'].sum():,}")
        c3.metric("Avg Mileage", f"{(d_sum/f_sum):.2f} KM/L" if f_sum > 0 else "0")
        st.divider()
        st.subheader("📜 Recent History")
        view_df = df[["timestamp", "vehicle", "driver", "authorized_by", "fuel_ltrs", "distance", "items", "photo_path"]].copy()
        view_df['photo_path'] = view_df['photo_path'].apply(lambda x: "✅" if x else "❌")
        st.dataframe(view_df.head(20), use_container_width=True, hide_index=True)
