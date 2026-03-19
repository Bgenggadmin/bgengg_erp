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

# --- 2. DYNAMIC MASTER DATA ---
@st.cache_data(ttl=600)
def get_mdm_list(table, col):
    try:
        res = conn.table(table).select(col).order(col).execute()
        return [item[col] for item in res.data] if res.data else []
    except: return []

@st.cache_data(ttl=60) 
def get_spares_with_stock(machine_name):
    if not machine_name: return []
    try:
        m_res = conn.table("master_machines").select("category").eq("name", machine_name).execute()
        category = m_res.data[0]['category'] if m_res.data else "ALL"
        s_res = conn.table("master_spares").select("part_name, stock_qty")\
            .or_(f"machine_category.eq.{category},machine_category.eq.ALL").execute()
        if s_res.data:
            return [f"{item['part_name']} (Qty: {item['stock_qty']})" if item['stock_qty'] > 0 
                    else f"{item['part_name']} (OUT OF STOCK)" for item in s_res.data]
        return []
    except: return []

# Pre-fetch lists
machine_list = get_mdm_list("master_machines", "name")
staff_list = get_mdm_list("master_staff", "name")

st.title("🔧 B&G Maintenance Master")

# --- 3. TABS STRUCTURE ---
tab_entry, tab_history = st.tabs(["📝 New Log Entry", "📜 History & Alerts"])

# --- 4. TAB: NEW LOG ENTRY ---
with tab_entry:
    with st.form("maint_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            equipment = st.selectbox("Select Machine", machine_list if machine_list else ["No Machines Found"])
            technician = st.selectbox("Technician", staff_list if staff_list else ["Select Staff"])
            
            # Stock-Aware Suggestions
            suggested_spares = get_spares_with_stock(equipment)
            spares_used = st.multiselect("🔧 Select Spares Used", suggested_spares)
            
        with col2:
            m_type = st.selectbox("Type", ["Breakdown Repair", "Preventive (PM)", "Spare Replacement"])
            status = st.radio("Post-Service Status", ["🟢 Operational", "🔴 Down"], horizontal=True)
        
        remarks_input = st.text_area("Work Details / Additional Notes")
        cam_photo = st.camera_input("Capture Proof")

        if st.form_submit_button("🚀 Submit Log"):
            if equipment and (remarks_input or spares_used):
                # 1. Image Processing
                img_str = "" 
                if cam_photo:
                    img = Image.open(cam_photo); img.thumbnail((400, 400))
                    buf = BytesIO(); img.save(buf, format="JPEG", quality=50)
                    img_str = base64.b64encode(buf.getvalue()).decode()

                # 2. Remark Formatting
                clean_spares = [s.split(" (")[0] for s in spares_used]
                final_remarks = f"SPARES: {', '.join(clean_spares)} | NOTES: {remarks_input}"

                # 3. Single Database Insert (FIXED: Removed duplicate logic)
                new_row = {
                    "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M'),
                    "equipment": equipment, 
                    "technician": technician,
                    "m_type": m_type, 
                    "status": status, 
                    "remarks": final_remarks, 
                    "photo": img_str
                }
                
                try:
                    conn.table("maintenance_logs").insert(new_row).execute()
                    st.cache_data.clear()
                    st.success("✅ Log Saved Successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")
            else:
                st.warning("Please provide machine name and work details.")

# --- 5. TAB: HISTORY & ALERTS ---
with tab_history:
    try:
        res = conn.table("maintenance_logs").select("*").order("created_at", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df['created_at'] = pd.to_datetime(df['created_at'])

            # --- ALERTS ---
            st.subheader("⚠️ Maintenance Alerts")
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
                st.warning(f"Found {len(overdue_machines)} machines overdue for PM.")
                st.dataframe(pd.DataFrame(overdue_machines), use_container_width=True, hide_index=True)
            else:
                st.success("All machines are up to date.")

            # --- METRICS ---
            st.divider()
            st.subheader("📊 Performance Summary")
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Total Records", len(df))
            s2.metric("Breakdowns", len(df[df['m_type'] == 'Breakdown Repair']))
            s3.metric("PMs Done", len(pm_data))
            
            # Machine Status Logic
            current_down = len(df.sort_values('created_at').groupby('equipment').tail(1).query("status == '🔴 Down'"))
            s4.metric("Currently Down", current_down, delta_color="inverse")

            # --- EXPORT & TABLE ---
            csv = df.drop(columns=['photo', 'id']).to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV Report", csv, "maint_report.csv", "text/csv")
            st.dataframe(df.drop(columns=["photo", "id"]), use_container_width=True, hide_index=True)
            
        else:
            st.info("No records found.")
    except Exception as e:
        st.error(f"Error loading history: {e}")
