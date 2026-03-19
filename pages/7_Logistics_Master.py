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
st.set_page_config(page_title="B&G Logistics | ERP", layout="wide")

try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception as e:
    st.error("❌ Supabase Connection Failed."); st.stop()

# --- 2. DATA UTILITIES ---
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

def send_wa(phone, msg):
    encoded = urllib.parse.quote(msg)
    return f"https://wa.me/{phone}?text={encoded}"

df = load_data()

# --- 3. UI LAYOUT ---
st.title("🚛 B&G Logistics Master")
tabs = st.tabs(["📅 Book Trip", "👨‍✈️ Dispatcher Desk", "📝 Trip Logger", "📊 Analytics"])

# --- TAB 1: STAFF BOOKING ---
with tabs[0]:
    with st.form("request_form", clear_on_submit=True):
        st.subheader("New Vehicle Request")
        c1, c2 = st.columns(2)
        req_by = c1.text_input("Staff Name")
        dest = c1.text_input("Destination")
        r_date = c2.date_input("Date", min_value=date.today())
        r_time = c2.text_input("Time (e.g. 10:30 AM)")
        reason = st.text_area("Purpose")
        
        if st.form_submit_button("Submit Request"):
            if req_by and dest:
                entry = {"requested_by": req_by.upper(), "destination": dest.upper(), 
                         "req_date": str(r_date), "req_time": r_time, "purpose": reason, "status": "Pending"}
                conn.table("logistics_requests").insert(entry).execute()
                
                msg = f"🚚 *New Request*\nFrom: {req_by}\nTo: {dest}\nDate: {r_date}\nPurpose: {reason}"
                st.success("Request Logged!")
                st.link_button("📲 Notify Brahmiah (WhatsApp)", send_wa("919848993939", msg))
            else: st.error("Fill mandatory fields")

# --- TAB 2: DISPATCHER (BRAHMIAH) ---
with tabs[1]:
    st.subheader("Manage Requests")
    reqs = conn.table("logistics_requests").select("*").eq("status", "Pending").execute().data
    if reqs:
        for r in reqs:
            with st.expander(f"🚩 {r['requested_by']} to {r['destination']} ({r['req_date']})"):
                v = st.selectbox("Assign Vehicle", ["Ashok Leyland", "Mahindra"], key=f"v{r['id']}")
                if st.button("Confirm Assignment", key=f"b{r['id']}"):
                    conn.table("logistics_requests").update({"status": "Assigned", "assigned_vehicle": v}).eq("id", r['id']).execute()
                    st.rerun()
    else: st.info("No pending requests.")

# --- TAB 3: TRIP LOGGER (Your Original Working Script) ---
with tabs[2]:
    with st.form("logistics_form", clear_on_submit=True):
        st.subheader("📝 Log Actual Movement & Fuel")
        col1, col2, col3 = st.columns(3)
        with col1:
            vehicle = st.selectbox("Vehicle", ["Ashok Leyland", "Mahindra", "Other"])
            driver = st.selectbox("Driver Name", ["Brahmiah", "Driver", "Other"])
            purpose = st.selectbox("Purpose", ["Inter-Unit", "Pickup", "Delivery", "Fueling"])
        with col2:
            start_km = st.number_input("Start KM", min_value=0, value=get_last_km(vehicle, df), step=1)
            end_km = st.number_input("End KM", min_value=0, step=1)
            fuel_qty = st.number_input("Fuel (Ltrs)", min_value=0.0, step=0.1)
        with col3:
            fuel_rate = st.number_input("Fuel Rate (₹/Litre)", min_value=0.0, value=94.5)
            auth_by = st.text_input("Authorized By", placeholder="Manager Name")
            location = st.text_input("Location", placeholder="e.g. Unit 2")
        
        items = st.text_area("Item Details")
        cam_photo = st.camera_input("Capture Bill/Odometer")

        if st.form_submit_button("🚀 SUBMIT LOG"):
            if end_km > start_km or fuel_qty > 0:
                photo_fn = ""
                if cam_photo:
                    img = Image.open(cam_photo); img.thumbnail((600, 600))
                    buf = BytesIO(); img.save(buf, format="JPEG", quality=50)
                    photo_fn = f"log_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}.jpg"
                    conn.client.storage.from_("logistics-photos").upload(photo_fn, buf.getvalue())

                dist = end_km - start_km if end_km > start_km else 0
                new_entry = {
                    "timestamp": datetime.now(IST).strftime('%Y-%m-%d %H:%M'),
                    "vehicle": vehicle, "driver": driver, "authorized_by": auth_by.upper(),
                    "start_km": start_km, "end_km": end_km, "distance": dist,
                    "fuel_ltrs": fuel_qty, "fuel_rate": fuel_rate, "total_fuel_cost": round(fuel_qty * fuel_rate, 2),
                    "purpose": purpose, "location": location.upper(), "items": items.upper(), "photo_path": photo_fn
                }
                conn.table("logistics_logs").insert(new_entry).execute()
                st.cache_data.clear(); st.success("Entry Saved!"); st.rerun()
            else: st.error("Invalid KM/Fuel entry")

# --- TAB 4: ANALYTICS & HISTORY ---
with tabs[3]:
    if not df.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total KM", f"{df['distance'].sum():,}")
        c2.metric("Total Spend", f"₹{df['total_fuel_cost'].sum():,}")
        c3.metric("Avg Mileage", f"{(df['distance'].sum()/df['fuel_ltrs'].sum()):.2f}" if df['fuel_ltrs'].sum() > 0 else "N/A")
        st.dataframe(df.drop(columns=['id', 'created_at'], errors='ignore').head(20), use_container_width=True)
