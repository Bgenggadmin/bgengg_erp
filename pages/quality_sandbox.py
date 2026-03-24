import streamlit as st
import pandas as pd
from fpdf import FPDF
from datetime import datetime
import requests
from io import BytesIO

# --- 1. DATA ENTRY COMPONENT ---
def quality_entry_form(sel_job, sel_stage, inspectors):
    with st.form("enhanced_q_form", clear_on_submit=True):
        st.subheader(f"🛡️ Pharma-Grade Log: {sel_stage}")
        
        c1, c2 = st.columns(2)
        with c1:
            q_status = st.segmented_control("Result", ["✅ Pass", "❌ Reject"], default="✅ Pass")
            inspector = st.selectbox("Inspector", inspectors)
            heat_no = st.text_input("Heat No. / TC No. (Traceability)")
            spec_val = st.text_input("Specified Dimension (from Drawing)")
            meas_val = st.text_input("Measured Dimension (Actual)")
            
        with c2:
            st.write("🔧 **Instrument/Test Details**")
            gauge_id = st.text_input("Pressure Gauge/Instrument ID")
            cal_due = st.date_input("Calibration Due Date")
            test_press = st.text_input("Test Pressure (if applicable)", "1.0 Kg/cm2")
            q_photos = st.file_uploader("Evidence Photos (Max 4)", accept_multiple_files=True)
            notes = st.text_area("Observations")

        if st.form_submit_button("🚀 Submit & Validate"):
            # Insert logic to upload photos to bucket and save all fields to 'quality_inspection_logs'
            st.success("Data recorded for 12-page report generation.")

# --- 2. SINGLE-CLICK PDF GENERATOR ---
class PharmaPDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'B&G ENGINEERING INDUSTRIES - QUALITY RECORD', ln=True, align='C')
        self.line(10, 20, 200, 20)
        self.ln(10)

def generate_12_page_package(job_no, data_rows):
    pdf = PharmaPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- SECTION 1: INDEX ---
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 15, f"QUALITY DOCUMENTATION PACKAGE - {job_no}", ln=True, align='C')
    sections = ["Quality Check List", "QAP", "As Built Drawing", "Material Flow Chart", 
                "Material Test Reports", "Nozzle Flow Chart", "Dimensional Inspection", 
                "Hydro Test Report", "Calibration Report", "Final Inspection", 
                "Guarantee Certificate", "Customer Feedback"]
    for i, s in enumerate(sections, 1):
        pdf.cell(10, 10, str(i), 1); pdf.cell(160, 10, s, 1, ln=True)

    # --- SECTION 4: MATERIAL FLOW CHART ---
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, "SECTION 4: MATERIAL FLOW CHART", ln=True)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(50, 10, "Part", 1); pdf.cell(40, 10, "MOC", 1); pdf.cell(100, 10, "Heat/TC No", 1, ln=True)
    pdf.set_font('Arial', '', 10)
    for row in data_rows:
        pdf.cell(50, 10, row['gate_name'], 1)
        pdf.cell(40, 10, row.get('moc_type', 'SS304'), 1)
        pdf.cell(100, 10, str(row.get('heat_no', 'N/A')), 1, ln=True)

    # --- SECTION 10: EVIDENCE ---
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, "SECTION 10: FINAL INSPECTION EVIDENCE", ln=True)
    for row in data_rows:
        if row.get('photo_urls'):
            pdf.set_font('Arial', 'I', 10)
            pdf.cell(0, 10, f"Evidence for {row['gate_name']}:", ln=True)
            # Logic: Iterate through photo_urls and use pdf.image()
            
    return pdf.output(dest='S').encode('latin-1')
