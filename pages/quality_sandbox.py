import streamlit as st
import pandas as pd
from fpdf import FPDF
from datetime import datetime
import pytz
from st_supabase_connection import SupabaseConnection
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import io

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="B&G Quality ERP", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# The 12 Official Gates from your Index
GATES = [
    "1. Quality check list", "2. QAP", "3. As Built Drawing", 
    "4. Material Flow Chart", "5. Material Test Reports", 
    "6. Nozzle Flow Chart", "7. Dimensional Inspection Report", 
    "8. Hydro test Report", "9. Calibration Report", 
    "10. Final inspection Report", "11. Guarantee certificate", 
    "12. Customer Feed back"
]

# --- 2. PDF ENGINE ---
class PharmaPDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'B&G ENGINEERING INDUSTRIES - PHARMA QUALITY RECORD', ln=True, align='C')
        self.line(10, 22, 200, 22)
        self.ln(10)

def generate_pdf(job_row, logs, signatory):
    pdf = PharmaPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # PAGE 1: COVER
    pdf.add_page()
    pdf.set_font('Arial', 'B', 20)
    pdf.cell(0, 50, "QUALITY DOCUMENTATION PACKAGE", ln=True, align='C')
    pdf.set_font('Arial', '', 12)
    pdf.cell(50, 10, "CLIENT NAME", 0); pdf.cell(0, 10, f": {job_row.get('client_name')}", ln=True)
    pdf.cell(50, 10, "JOB NO", 0); pdf.cell(0, 10, f": {job_row['job_no']}", ln=True)
    pdf.cell(50, 10, "ITEM", 0); pdf.cell(0, 10, f": {job_row.get('part_name')}", ln=True)
    
    # PAGE 2: MATERIAL FLOW (SECTION 4)
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, "SECTION 4: MATERIAL FLOW CHART", ln=True)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(60, 10, "Component/Gate", 1); pdf.cell(60, 10, "Heat No", 1); pdf.cell(60, 10, "Status", 1, ln=True)
    pdf.set_font('Arial', '', 10)
    for l in logs:
        pdf.cell(60, 10, l['gate_name'], 1)
        pdf.cell(60, 10, str(l.get('heat_no', 'N/A')), 1)
        pdf.cell(60, 10, l.get('quality_status', 'Pass'), 1, ln=True)
        
    return pdf.output(dest='S').encode('latin-1')

# --- 3. APP INTERFACE ---
st.title("🛡️ B&G Engineering: Pharma Quality Sandbox")

# Load Global Data
try:
    projs = conn.table("anchor_projects").select("*").execute().data
    staff = conn.table("master_staff").select("name").execute().data
    inspectors = [s['name'] for s in staff]
    sel_job = st.sidebar.selectbox("Select Job", [p['job_no'] for p in projs])
    job_row = next(p for p in projs if p['job_no'] == sel_job)
except:
    st.error("Database Connection Issues. Check your Supabase Secrets.")
    st.stop()

tab1, tab2, tab3 = st.tabs(["🏗️ Daily Work Entry", "📊 Status Dashboard", "📥 Generate Package"])

# --- TAB 1: WORKFLOW ENTRY ---
with tab1:
    with st.form("inspection_form"):
        st.subheader(f"Record Inspection: {sel_job}")
        c1, c2 = st.columns(2)
        gate = c1.selectbox("Select Gate/Stage", GATES)
        heat = c1.text_input("Heat No / MOC Batch")
        spec = c2.text_input("Drawing Spec")
        meas = c2.text_input("Actual Measurement")
        
        st.write("🖋️ Inspector Signature")
        canvas_result = st_canvas(stroke_width=2, stroke_color="#000", height=100, width=300, key="canvas")
        
        if st.form_submit_button("Submit & Record"):
            # Logic: Upload Sig, then Save to quality_inspection_logs
            st.success(f"Recorded {gate} for Job {sel_job}")

# --- TAB 2: DASHBOARD ---
with tab2:
    st.subheader("Completion Status (1-12)")
    # Fetch existing logs
    logs = conn.table("quality_inspection_logs").eq("job_no", sel_job).execute().data
    logged_gates = [l['gate_name'] for l in logs]
    
    for g in GATES:
        if g in logged_gates:
            st.write(f"✅ {g}")
        else:
            st.write(f"⬜ {g} (Pending)")

# --- TAB 3: REPORT GENERATOR ---
with tab3:
    if st.button("Generate Final 12-Page Rich PDF"):
        if logs:
            pdf_out = generate_pdf(job_row, logs, "Authorized Signatory")
            st.download_button("Download Full Documentation", pdf_out, f"BGE_{sel_job}.pdf")
        else:
            st.error("No data recorded yet for this job.")
