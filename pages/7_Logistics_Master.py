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

# --- 2. DATA UTILITIES (Optimized) ---
@st.cache_data(ttl=60) # Increased TTL to 1 min; use refresh button for manual sync
def load_data():
    try:
        # Fetching only necessary columns to keep the payload small
        res = conn.table("logistics_logs").select("*").order("timestamp", desc=True).execute()
        if res.data:
            return pd.DataFrame(res.data)
    except Exception as e:
        st.error(f"Data Fetch Error: {e}")
    return pd.DataFrame()

df = load_data()

# Sidebar Tools
with st.sidebar:
    st.title("🚛 Fleet Control")
    if st.button("🔄 Sync Cloud Data"):
        st.cache_data.clear()
        st.rerun()
    
    # SENIOR DEV ADDITION: CSV Export
    if not df.empty:
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Export Logistics CSV", data=csv, file_name=f"logistics_export_{datetime.now().date()}.csv")

# --- 3. INPUT FORM ---
with st.form("logistics_form", clear_on_submit=True):
    st.subheader("📝 Log Vehicle Movement & Fuel")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        vehicle = st.selectbox("Vehicle", ["Ashok Leyland", "Mahindra", "Other"])
        driver = st.selectbox("Driver Name", ["Brahmiah", "Driver", "Other"])
        purpose = st.selectbox("Purpose", ["Inter-Unit (500m)", "Pickup", "Site Delivery", "Fueling"])

    with col2:
        start_km = st.number_input("Start KM Reading", min_value=0, step=1)
        end_km = st.number_input("End KM Reading", min_value=0, step=1)
        fuel_qty = st.number_input("Fuel Added (Litres)", min_value=0.0, step=0.1)

    with col3:
        auth_by = st.text_input("Authorized By (Required)", placeholder="Manager Name")
        location = st.text_input("Location (Required)", placeholder="e.g. Unit 2")

    items = st.text_area("Item Details / Remarks")
    cam_photo = st.camera_input("Capture Bill / Odometer Photo")

    if st.form_submit_button("🚀 SUBMIT LOG"):
        if end_km < start_km and end_km != 0:
            st.error("❌ End KM cannot be less than Start KM!")
        elif not auth_by or not location:
            st.error("❌ Authorization and Location are mandatory.")
        else:
            photo_filename = ""
            if cam_photo:
                # Efficient Image Compression
                img = Image.open(cam_photo)
                img.thumbnail((600, 600)) # Slightly better res for bills
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=50, optimize=True) # Quality 50 is sweet spot
                
                photo_filename = f"log_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}.jpg"
                
                try:
                    conn.client.storage.from_("logistics-photos").upload(
                        path=photo_filename,
                        file=buf.getvalue(),
                        file_options={"content-type": "image/jpeg"}
                    )
                except Exception as e:
                    st.warning(f"Photo upload failed: {e}")

            trip_distance = end_km - start_km if end_km > start_km else 0

            new_entry = {
                "timestamp": datetime.now(IST).strftime('%Y-%m-%d %H:%M'),
                "vehicle": vehicle, 
                "driver": driver, 
                "authorized_by": auth_by.upper(),
                "start_km": start_km, 
                "end_km": end_km, 
                "distance": trip_distance,
                "fuel_ltrs": fuel_qty, 
                "purpose": purpose, 
                "location": location.upper(), 
                "items": items.upper(), 
                "photo_path": photo_filename
            }
            
            try:
                conn.table("logistics_logs").insert(new_entry).execute()
                st.cache_data.clear() 
                st.success("✅ Entry Saved Successfully!")
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
