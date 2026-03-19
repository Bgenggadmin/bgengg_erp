import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz
from io import BytesIO
from PIL import Image
import streamlit.components.v1 as components

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Logistics | Fleet Tracker", layout="wide")

# Initialize Supabase Connection
try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception as e:
    st.error("❌ Supabase Connection Failed. Check your Secrets!")
    st.stop()

# --- 2. DATA UTILITIES (Updated for Auto-KM & Financials) ---

@st.cache_data(ttl=60)
def load_data():
    try:
        # Fetching all columns, ordered by timestamp DESC
        # This order is CRITICAL for the get_last_km function to work correctly
        res = conn.table("logistics_logs").select("*").order("timestamp", desc=True).execute()
        
        if res.data:
            _df = pd.DataFrame(res.data)
            
            # Defensive check: Ensure numeric columns are actually numeric
            # This prevents math errors in the Analytics cards
            numeric_cols = ['distance', 'fuel_ltrs', 'fuel_rate', 'total_fuel_cost', 'start_km', 'end_km']
            for col in numeric_cols:
                if col in _df.columns:
                    _df[col] = pd.to_numeric(_df[col], errors='coerce').fillna(0)
            
            return _df
    except Exception as e:
        st.error(f"Cloud Sync Error: {e}")
    
    # Return empty DF with expected columns if fetch fails to prevent UI crashes
    return pd.DataFrame(columns=["timestamp", "vehicle", "end_km", "distance", "fuel_ltrs"])

# Load data once at the start
df = load_data()

# Sidebar Tools
with st.sidebar:
    st.title("🚛 Fleet Control")
    
    # Force refresh button
    if st.button("🔄 Sync Cloud Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    st.divider()
    
    # Export Utility
    if not df.empty:
        st.subheader("Data Export")
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Export Logistics CSV",
            data=csv,
            file_name=f"B&G_Logistics_{datetime.now().strftime('%Y-%m-%d')}.csv",
            mime="text/csv",
            use_container_width=True
        )
        st.caption("Includes fuel costs and distances.")

# --- 3. INPUT FORM ---

# Helper function to get last KM (Must be defined before the form)
def get_last_km(veh_name, dataframe):
    if not dataframe.empty and 'vehicle' in dataframe.columns:
        # Filter logs for this vehicle and get the most recent 'end_km'
        veh_logs = dataframe[dataframe['vehicle'] == veh_name]
        if not veh_logs.empty:
            return int(veh_logs.iloc[0]['end_km'])
    return 0

with st.form("logistics_form", clear_on_submit=True):
    st.subheader("📝 Log Vehicle Movement & Fuel")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        vehicle = st.selectbox("Vehicle", ["Ashok Leyland", "Mahindra", "Other"])
        driver = st.selectbox("Driver Name", ["Brahmiah", "Driver", "Other"])
        purpose = st.selectbox("Purpose", ["Inter-Unit (500m)", "Pickup", "Site Delivery", "Fueling"])

    with col2:
        # AUTOMATION: Pulls last End KM from database based on the selection in col1
        last_recorded = get_last_km(vehicle, df)
        
        start_km = st.number_input("Start KM Reading", min_value=0, value=last_recorded, step=1)
        end_km = st.number_input("End KM Reading", min_value=0, step=1)
        fuel_qty = st.number_input("Fuel Added (Litres)", min_value=0.0, step=0.1)
        # Default fuel rate for Hyderabad/Telangana area
        fuel_rate = st.number_input("Fuel Rate (₹/Litre)", min_value=0.0, value=94.5, step=0.1)

    with col3:
        auth_by = st.text_input("Authorized By (Required)", placeholder="Manager Name")
        location = st.text_input("Location (Required)", placeholder="e.g. Unit 2")
        
        # UI Financial Calculation
        total_fuel_cost = round(fuel_qty * fuel_rate, 2)
        if fuel_qty > 0:
            st.info(f"💰 Fuel Cost: ₹{total_fuel_cost}")

    items = st.text_area("Item Details / Remarks")
    cam_photo = st.camera_input("Capture Bill / Odometer Photo")

    if st.form_submit_button("🚀 SUBMIT LOG"):
        # VALIDATION LOGIC
        if end_km != 0 and end_km < start_km:
            st.error("❌ Error: End KM cannot be less than Start KM!")
        elif not auth_by or not location:
            st.error("❌ Error: Authorization and Location are mandatory.")
        elif end_km == 0 and fuel_qty == 0:
            st.error("❌ Error: You must enter either End KM or Fuel Quantity.")
        else:
            # 1. Image Processing
            photo_filename = ""
            if cam_photo:
                try:
                    img = Image.open(cam_photo)
                    img.thumbnail((600, 600)) 
                    buf = BytesIO()
                    img.save(buf, format="JPEG", quality=50, optimize=True)
                    
                    photo_filename = f"log_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}.jpg"
                    
                    conn.client.storage.from_("logistics-photos").upload(
                        path=photo_filename,
                        file=buf.getvalue(),
                        file_options={"content-type": "image/jpeg"}
                    )
                except Exception as e:
                    st.warning(f"Photo upload failed, but saving log: {e}")

            # 2. Distance Calculation
            trip_distance = end_km - start_km if end_km > start_km else 0

            # 3. Data Preparation
            new_entry = {
                "timestamp": datetime.now(IST).strftime('%Y-%m-%d %H:%M'),
                "vehicle": vehicle, 
                "driver": driver, 
                "authorized_by": auth_by.upper(),
                "start_km": start_km, 
                "end_km": end_km, 
                "distance": trip_distance,
                "fuel_ltrs": fuel_qty, 
                "fuel_rate": fuel_rate,
                "total_fuel_cost": total_fuel_cost,
                "purpose": purpose, 
                "location": location.upper(), 
                "items": items.upper(), 
                "photo_path": photo_filename
            }
            
            # 4. Database Insert
            try:
                conn.table("logistics_logs").insert(new_entry).execute()
                st.cache_data.clear() 
                st.success(f"✅ Logged {trip_distance} KM trip for {vehicle}!")
                st.rerun()
            except Exception as e:
                st.error(f"Database Error: {e}")

# --- 4. ANALYTICS & HISTORY ---
if not df.empty:
    st.subheader("📊 Fleet Summary")
    c1, c2, c3 = st.columns(3)
    # Using 'fill_na' to prevent math errors on empty logs
    dist = df['distance'].fillna(0).sum()
    fuel = df['fuel_ltrs'].fillna(0).sum()
    
    c1.metric("Total Distance", f"{dist:,} KM")
    c2.metric("Total Fuel", f"{fuel:,} L")
    c3.metric("Avg Mileage", f"{(dist/fuel):.2f} KM/L" if fuel > 0 else "N/A")

    st.divider()
    
    # UI LEDGER: Clean table view
    st.subheader("📜 Recent Movement History")
    view_cols = ["timestamp", "vehicle", "driver", "authorized_by", "fuel_ltrs", "distance", "items", "photo_path"]
    # Show status emoji for photos
    display_df = df[view_cols].copy()
    display_df['photo_path'] = display_df['photo_path'].apply(lambda x: "✅" if x else "❌")
    
    st.dataframe(display_df.head(20), use_container_width=True, hide_index=True)

    # --- 5. PHOTO VIEWER ---
    st.write("---")
    st.subheader("🔍 Inspection: Bill / Odometer Gallery")
    photo_df = df[df["photo_path"].str.len() > 0].head(10)
    
    if not photo_df.empty:
        selection = st.selectbox("Select trip to view photo:", 
                                 photo_df.index, 
                                 format_func=lambda x: f"{photo_df.loc[x, 'timestamp']} | {photo_df.loc[x, 'vehicle']} | {photo_df.loc[x, 'driver']}")
        
        file_path = photo_df.loc[selection, "photo_path"]
        img_url = conn.client.storage.from_("logistics-photos").get_public_url(file_path)
        st.image(img_url, width=500, caption=f"Evidence: {file_path}")
