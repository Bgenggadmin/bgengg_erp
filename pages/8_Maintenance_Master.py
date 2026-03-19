import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta
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

# --- 2. DYNAMIC MASTER DATA ---
@st.cache_data(ttl=600)
def get_mdm_list(table, col):
    try:
        res = conn.table(table).select(col).order(col).execute()
        return [item[col] for item in res.data] if res.data else []
    except: return []

machine_list = get_mdm_list("master_machines", "name")
staff_list = get_mdm_list("master_staff", "name")

st.title("🔧 B&G Maintenance Master")

# --- 3. TABS STRUCTURE ---
tab_entry, tab_history = st.tabs(["📝 New Log Entry", "📜 History & Alerts"])

with tab_entry:
    with st.form("maint_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            equipment = st.selectbox("Select Machine", machine_list if machine_list else ["No Machines Found"])
            technician = st.selectbox("Technician", staff_list if staff_list else ["Select Staff"])
        with col2:
            m_type = st.selectbox("Type", ["Breakdown Repair", "Preventive (PM)", "Spare Replacement"])
            status = st.radio("Post-Service Status", ["🟢 Operational", "🔴 Down"], horizontal=True)
        
        remarks = st.text_area("Work Details / Spares Used")
        cam_photo = st.camera_input("Capture Proof")

        if st.form_submit_button("🚀 Submit Log"):
            if equipment and remarks:
                img_str = ""
                if cam_photo:
                    img = Image.open(cam_photo); img.thumbnail((400, 400))
                    buf = BytesIO(); img.save(buf, format="JPEG", quality=50)
                    img_str = base64.b64encode(buf.getvalue()).decode()

                new_row = {
                    "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M'),
                    "equipment": equipment, "technician": technician,
                    "m_type": m_type, "status": status, 
                    "remarks": remarks, "photo": img_str
                }
                conn.table("maintenance_logs").insert(new_row).execute()
                st.cache_data.clear(); st.success("✅ Log Saved!"); st.rerun()

with tab_history:
    try:
        res = conn.table("maintenance_logs").select("*").order("created_at", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df['created_at'] = pd.to_datetime(df['created_at'])

            # --- SMART ALERTS: MAINTENANCE DUE ---
            st.subheader("⚠️ Maintenance Alerts")
            alert_cols = st.columns(1)
            
            pm_data = df[df['m_type'] == 'Preventive (PM)']
            overdue_machines = []
            
            for m in machine_list:
                latest_pm = pm_data[pm_data['equipment'] == m]
                if latest_pm.empty:
                    overdue_machines.append({"Machine": m, "Last PM": "Never", "Days": ">30"})
                else:
                    last_date = latest_pm.iloc[0]['created_at'].replace(tzinfo=None)
                    days_since = (datetime.now() - last_date).days
                    if days_since > 30:
                        overdue_machines.append({"Machine": m, "Last PM": last_date.strftime('%Y-%m-%d'), "Days": days_since})

            if overdue_machines:
                st.warning(f"Found {len(overdue_machines)} machines requiring Preventive Maintenance (30+ days since last PM).")
                st.dataframe(pd.DataFrame(overdue_machines), use_container_width=True, hide_index=True)
            else:
                st.success("All machines have had PM within the last 30 days.")

            # --- SUMMARY METRICS ---
            st.divider()
            st.subheader("📊 Performance Summary")
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Total Records", len(df))
            s2.metric("Breakdowns", len(df[df['m_type'] == 'Breakdown Repair']))
            s3.metric("PMs Done", len(pm_data))
            
            # Current Status logic
            current_down = len(df.sort_values('created_at').groupby('equipment').tail(1).query("status == '🔴 Down'"))
            s4.metric("Currently Down", current_down, delta_color="inverse")

            # --- EXPORT & TABLE ---
            csv = df.drop(columns=['photo', 'id']).to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV Report", csv, "maint_report.csv", "text/csv")
            
            st.dataframe(df.drop(columns=["photo", "id"]), use_container_width=True, hide_index=True)
            
    except Exception as e:
        st.error(f"Error loading history: {e}")
