import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz
import base64
from io import BytesIO
from PIL import Image

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Maintenance Master", layout="wide")

try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception as e:
    st.error("❌ Supabase Connection Failed!"); st.stop()

# --- 2. DYNAMIC MASTER DATA (Mapped to your Schema) ---

@st.cache_data(ttl=600)
def get_mdm_list(table, col):
    try:
        res = conn.table(table).select(col).order(col).execute()
        return [item[col] for item in res.data] if res.data else []
    except: return []

# Pulling from your specific schema tables
machine_list = get_mdm_list("master_machines", "name")
staff_list = get_mdm_list("master_staff", "name")

# --- 3. MAINTENANCE FORM ---
st.title("🔧 B&G Maintenance Master")

with st.form("maint_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        equipment = st.selectbox("Select Machine", machine_list if machine_list else ["No Machines Found"])
        technician = st.selectbox("Technician", staff_list if staff_list else ["Select Staff"])
    with col2:
        m_type = st.selectbox("Type", ["Breakdown Repair", "Preventive (PM)", "Spare Replacement"])
        status = st.radio("Machine Status", ["🟢 Operational", "🔴 Down"], horizontal=True)
    
    remarks = st.text_area("Work Details / Spares Used")
    cam_photo = st.camera_input("Capture Proof")

    if st.form_submit_button("🚀 Submit Log"):
        if equipment and remarks:
            img_str = ""
            if cam_photo:
                img = Image.open(cam_photo)
                img.thumbnail((400, 400))
                buf = BytesIO(); img.save(buf, format="JPEG", quality=50)
                img_str = base64.b64encode(buf.getvalue()).decode()

            # Mapping to maintenance_logs table
            new_row = {
                "equipment": equipment,
                "technician": technician,
                "m_type": m_type,
                "status": status,
                "remarks": remarks,
                "photo": img_str
            }
            conn.table("maintenance_logs").insert(new_row).execute()
            st.cache_data.clear(); st.success("Log Saved!"); st.rerun()

# --- 4. VIEW LOGS ---
st.divider()
try:
    log_data = conn.table("maintenance_logs").select("*").order("created_at", desc=True).limit(20).execute().data
    if log_data:
        st.subheader("Recent Maintenance Activity")
        view_df = pd.DataFrame(log_data)
        st.dataframe(view_df.drop(columns=["photo", "id"]), use_container_width=True, hide_index=True)
except:
    st.info("Start logging to see history.")
