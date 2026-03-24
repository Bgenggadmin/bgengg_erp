import streamlit as st
import pandas as pd
from fpdf import FPDF
from datetime import datetime
import pytz
from st_supabase_connection import SupabaseConnection
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import io

# --- 1. SETTINGS & SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Quality ERP", layout="wide", page_icon="🛡️")
conn = st.connection("supabase", type=SupabaseConnection)

GATES = [
    "1. Quality check list", "2. QAP", "3. As Built Drawing", 
    "4. Material Flow Chart", "5. Material Test Reports", 
    "6. Nozzle Flow Chart", "7. Dimensional Inspection Report", 
    "8. Hydro test Report", "9. Calibration Report", 
    "10. Final inspection Report", "11. Guarantee certificate", 
    "12. Customer Feed back"
]

# --- 2. UI LOGIC & DYNAMIC FORMS ---
st.title("🛡️ B&G Quality Integration Hub")

try:
    projs_data = conn.table("anchor_projects").select("*").execute().data
    staff_data = conn.table("master_staff").select("name").execute().data
    inspectors = [s['name'] for s in staff_data]
    sel_job = st.sidebar.selectbox("Select Active Job", [p['job_no'] for p in projs_data])
    job_row = next(p for p in projs_data if p['job_no'] == sel_job)
except Exception as e:
    st.error(f"Database Error: {e}"); st.stop()

tab1, tab2, tab3 = st.tabs(["🏗️ Daily Log Entry", "📊 Readiness Dashboard", "📄 Report Generator"])

with tab1:
    st.subheader(f"Record Shop Floor Data: {sel_job}")
    
    # 1. Gate Selection
    gate = st.selectbox("Select Process Gate / Form", GATES)
    st.divider()

    # 2. Dynamic Form Logic based on PDF headers
    with st.form("inspection_gate", clear_on_submit=True):
        payload = {"job_no": sel_job, "gate_name": gate}
        
        if gate == "4. Material Flow Chart":
            # Matching Headers: Description, Size, MOC, Test Report No, Heat No 
            c1, c2, c3 = st.columns(3)
            payload["description"] = c1.text_input("Component Description (e.g. Shell)")
            payload["size"] = c1.text_input("Size (e.g. ID2750X8THK)")
            payload["moc"] = c2.selectbox("MOC", ["SS304", "SS316L", "Carbon Steel"], index=0)
            payload["mtr_no"] = c2.text_input("Test Report No")
            payload["heat_no"] = c3.text_input("Heat Number")

        elif gate == "6. Nozzle Flow Chart":
            # Matching Headers: Nozzle No, Description, Qty, Size(NB), MOC, Projection [cite: 69, 576]
            c1, c2, c3 = st.columns(3)
            payload["nozzle_no"] = c1.text_input("Nozzle Mark (e.g. N1)")
            payload["description"] = c1.text_input("Description (e.g. Drain)")
            payload["qty"] = c2.number_input("Quantity", min_value=1, step=1)
            payload["size_nb"] = c2.text_input("Size (NB)")
            payload["projection"] = c3.text_input("Projection (mm)", value="150")
            payload["moc"] = c3.text_input("MOC", value="SS304")

        elif gate == "7. Dimensional Inspection Report":
            # Matching Headers: Description, Specified, Measured, MOC 
            c1, c2 = st.columns(2)
            payload["description"] = c1.text_input("Inspection Parameter (e.g. Shell ID)")
            payload["spec_dim"] = c1.text_input("Specified Dimension")
            payload["meas_dim"] = c2.text_input("Measured Dimension")
            payload["moc"] = c2.text_input("MOC", value="SS304")

        elif gate == "8. Hydro test Report":
            # Matching Headers: Test Pressure, Duration, Fluid, Temp 
            c1, c2 = st.columns(2)
            payload["test_pressure"] = c1.text_input("Test Pressure (e.g. 1.0 kg/cm2)")
            payload["duration"] = c1.text_input("Duration (e.g. 1 Hr)")
            payload["test_fluid"] = c2.selectbox("Test Fluid", ["WATER", "OIL", "AIR"])
            payload["temperature"] = c2.text_input("Temperature", value="ATMP.")

        elif gate == "9. Calibration Report":
            # Matching Headers: Instrument, Sr No, Make, Range, Least Count 
            c1, c2 = st.columns(2)
            payload["instr_desc"] = c1.text_input("Instrument Description")
            payload["sr_no"] = c1.text_input("Serial Number")
            payload["make"] = c2.text_input("Make (e.g. Baumer)")
            payload["range_val"] = c2.text_input("Range (e.g. 0-7 kg/cm2)")

        else:
            # General Entry for other forms
            c1, c2 = st.columns(2)
            payload["notes"] = c1.text_area("General Observations")
            payload["remarks"] = c2.text_input("Remarks")

        st.divider()
        c_sig1, c_sig2 = st.columns([2, 1])
        with c_sig1:
            st.write("🖋️ Inspector Digital Signature")
            canvas = st_canvas(stroke_width=2, stroke_color="#000", height=120, width=400, key="sig_pad")
        with c_sig2:
            payload["inspector_name"] = st.selectbox("Select Inspector", inspectors)
            payload["quality_status"] = st.segmented_control("Result", ["✅ Pass", "❌ Reject"], default="✅ Pass")

        if st.form_submit_button("🚀 Submit Section Record"):
            # The payload now contains specific keys matching the PDF form selected
            conn.table("quality_inspection_logs").insert(payload).execute()
            st.success(f"Form '{gate}' successfully saved with specific field data.")
            st.rerun()

# --- TAB 2 & 3 (DASHBOARD & GENERATOR) remains similar, but now filters by specific keys ---

# --- TAB 2: READINESS DASHBOARD ---
with tab2:
    logs = conn.table("quality_inspection_logs").select("*").eq("job_no", sel_job).execute().data
    logged_gates = [l['gate_name'] for l in logs]
    
    st.subheader("12-Form Readiness Status")
    cols = st.columns(2)
    for i, g in enumerate(GATES):
        col = cols[0] if i < 6 else cols[1]
        if g in logged_gates:
            col.success(f"✅ {g} - Data Logged")
        else:
            col.error(f"⬜ {g} - Missing")

# --- TAB 3: REPORT GENERATOR ---
with tab3:
    st.subheader("Final Pharma Documentation")
    signatory = st.selectbox("Select Signatory for Certificate", inspectors)
    if st.button("🚀 Generate Full Package", type="primary", use_container_width=True):
        if logs:
            pdf_bytes = generate_full_package(job_row, logs, signatory)
            st.download_button("📥 Download Rich PDF Package", pdf_bytes, f"BG_{sel_job}_Full_Quality.pdf")
        else:
            st.warning("No entries found. Please log data in Tab 1 first.")
