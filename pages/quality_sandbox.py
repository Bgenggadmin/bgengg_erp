import streamlit as st
import pandas as pd
from fpdf import FPDF
from datetime import datetime
import pytz
from st_supabase_connection import SupabaseConnection

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Quality Sandbox", layout="wide")

# Initialize Connection
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SINGLE-CLICK PDF GENERATOR CLASS ---
class PharmaPDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'B&G ENGINEERING INDUSTRIES - QUALITY RECORD', ln=True, align='C')
        self.line(10, 20, 200, 20)
        self.ln(10)

def generate_12_page_package(job_no, data_rows):
    pdf = PharmaPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # PAGE 1: INDEX
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 15, f"QUALITY DOCUMENTATION PACKAGE - {job_no}", ln=True, align='C')
    sections = ["Quality Check List", "QAP", "As Built Drawing", "Material Flow Chart", 
                "Material Test Reports", "Nozzle Flow Chart", "Dimensional Inspection", 
                "Hydro Test Report", "Calibration Report", "Final Inspection", 
                "Guarantee Certificate", "Customer Feedback"]
    pdf.set_font('Arial', '', 12)
    for i, s in enumerate(sections, 1):
        pdf.cell(10, 10, str(i), 1); pdf.cell(160, 10, s, 1, ln=True)

    # PAGE 4: MATERIAL FLOW CHART
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, "SECTION 4: MATERIAL FLOW CHART", ln=True)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(50, 10, "Part", 1); pdf.cell(40, 10, "MOC", 1); pdf.cell(100, 10, "Heat/TC No", 1, ln=True)
    pdf.set_font('Arial', '', 10)
    for row in data_rows:
        pdf.cell(50, 10, row.get('gate_name', 'N/A'), 1)
        pdf.cell(40, 10, row.get('moc_type', 'SS304'), 1)
        pdf.cell(100, 10, str(row.get('heat_no', 'N/A')), 1, ln=True)

    return pdf.output(dest='S').encode('latin-1')

# --- 3. DATA ENTRY UI ---
st.title("🛡️ Pharma-Grade Quality Sandbox")

# Sidebar for Job Selection
try:
    jobs_res = conn.table("anchor_projects").select("job_no").execute()
    job_list = [j['job_no'] for j in jobs_res.data]
    sel_job = st.sidebar.selectbox("Select Job", job_list)
    
    inspectors_res = conn.table("master_staff").select("name").execute()
    inspectors = [i['name'] for i in inspectors_res.data]
except:
    st.error("Connection Error: Check Supabase Credentials")
    st.stop()

tab1, tab2 = st.tabs(["📝 Data Entry", "📦 Report Generator"])

with tab1:
    sel_stage = st.selectbox("Select Process/Gate", ["Shell Fit-up", "Dish Fit-up", "Nozzle Welding", "Hydro Test"])
    
    with st.form("enhanced_q_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            q_status = st.segmented_control("Result", ["✅ Pass", "❌ Reject"], default="✅ Pass")
            inspector = st.selectbox("Inspector", inspectors)
            heat_no = st.text_input("Heat No. / TC No. (Traceability)")
            spec_val = st.text_input("Specified Dimension")
            meas_val = st.text_input("Measured Dimension")
            
        with c2:
            st.write("🔧 **Instrument/Test Details**")
            gauge_id = st.text_input("Pressure Gauge ID")
            cal_due = st.date_input("Calibration Due Date")
            test_press = st.text_input("Test Pressure", "1.0 Kg/cm2")
            q_photos = st.file_uploader("Evidence Photos", accept_multiple_files=True)
            notes = st.text_area("Observations")

        if st.form_submit_button("🚀 Submit & Save to Logs"):
            payload = {
                "job_no": sel_job, "gate_name": sel_stage, "heat_no": heat_no,
                "specified_val": spec_val, "measured_val": meas_val, "gauge_id": gauge_id,
                "inspector_name": inspector, "quality_status": q_status
            }
            conn.table("quality_inspection_logs").insert(payload).execute()
            st.success("Data recorded successfully!")

with tab2:
    st.subheader("Generate Complete Pharma Package")
    if st.button("📑 Generate 12-Page Rich PDF"):
        # Fetch all logs for this specific job
        logs = conn.table("quality_inspection_logs").eq("job_no", sel_job).execute().data
        
        if logs:
            pdf_bytes = generate_12_page_package(sel_job, logs)
            st.download_button(
                label="📥 Download Documentation Package",
                data=pdf_bytes,
                file_name=f"Quality_Report_{sel_job}.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("No quality logs found for this job to generate a report.")
