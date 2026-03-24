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

# The 12 Official Gates/Sections
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
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'B&G ENGINEERING INDUSTRIES', ln=True, align='C')
        self.set_font('Arial', 'I', 8)
        self.cell(0, 5, 'Chemical Process Equipment Company | Hyderabad', ln=True, align='C')
        self.line(10, 27, 200, 27)
        self.ln(12)

def generate_pdf(job_row, logs, signatory):
    pdf = PharmaPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # PAGE 1: COVER
    pdf.add_page()
    pdf.ln(30)
    pdf.set_font('Arial', 'B', 22)
    pdf.cell(0, 20, "QUALITY DOCUMENTATION PACKAGE", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, f"ITEM: {job_row.get('part_name', 'Equipment')}", ln=True, align='C')
    pdf.ln(15)
    
    pdf.set_font('Arial', '', 12)
    details = [
        ["CLIENT NAME", job_row.get('client_name')],
        ["JOB NUMBER", job_row['job_no']],
        ["PO NO & DATE", job_row.get('po_no')],
        ["DRAWING NO", job_row.get('drawing_no')]
    ]
    for label, val in details:
        pdf.cell(50, 12, label, 0); pdf.cell(0, 12, f": {val}", 0, ln=True)

    # PAGE 4: MATERIAL FLOW CHART
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, "SECTION 4: MATERIAL FLOW CHART", ln=True)
    pdf.ln(5)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(60, 10, "Gate/Component", 1); pdf.cell(60, 10, "Heat No", 1); pdf.cell(60, 10, "Result", 1, ln=True)
    pdf.set_font('Arial', '', 10)
    for l in logs:
        pdf.cell(60, 10, l['gate_name'], 1)
        pdf.cell(60, 10, str(l.get('heat_no', 'N/A')), 1)
        pdf.cell(60, 10, l.get('quality_status', 'Pass'), 1, ln=True)

    return pdf.output(dest='S').encode('latin-1')

# --- 3. UI LOGIC ---
st.title("🛡️ B&G Quality Integration Hub")

# Data Loading with Fixed .eq() Syntax
try:
    # Use .select() before any filters
    projs_data = conn.table("anchor_projects").select("*").execute().data
    staff_data = conn.table("master_staff").select("name").execute().data
    
    inspectors = [s['name'] for s in staff_data]
    sel_job = st.sidebar.selectbox("Select Active Job", [p['job_no'] for p in projs_data])
    job_row = next(p for p in projs_data if p['job_no'] == sel_job)
except Exception as e:
    st.error(f"Database Error: {e}")
    st.stop()

tab1, tab2, tab3 = st.tabs(["🏗️ Daily Log Entry", "📊 Readiness Dashboard", "📄 Report Generator"])

# --- TAB 1: DAILY WORKFLOW ---
with tab1:
    st.subheader(f"Record Shop Floor Data: {sel_job}")
    with st.form("inspection_gate", clear_on_submit=True):
        c1, c2 = st.columns(2)
        gate = c1.selectbox("Select Process Gate", GATES)
        heat = c1.text_input("Heat No / Plate No")
        spec = c1.text_input("Specified Dim")
        
        meas = c2.text_input("Measured Dim")
        inspt = c2.selectbox("Inspector", inspectors)
        res = c2.segmented_control("Result", ["✅ Pass", "❌ Reject"], default="✅ Pass")
        
        st.write("🖋️ Inspector Digital Signature")
        canvas = st_canvas(stroke_width=2, stroke_color="#000", height=100, width=300, key="sig_pad")
        
        if st.form_submit_button("Submit Record"):
            # FIX: Ensure we use .insert() and execute
            payload = {
                "job_no": sel_job, "gate_name": gate, "heat_no": heat,
                "specified_val": spec, "measured_val": meas, 
                "inspector_name": inspt, "quality_status": res
            }
            conn.table("quality_inspection_logs").insert(payload).execute()
            st.success(f"Log for {gate} successfully saved.")
            st.rerun()

# --- TAB 2: READINESS DASHBOARD ---
with tab2:
    st.subheader("12-Section Readiness Tracker")
    # FIX: Use .select() before .eq()
    logs = conn.table("quality_inspection_logs").select("*").eq("job_no", sel_job).execute().data
    logged_gate_names = [l['gate_name'] for l in logs]
    
    cols = st.columns(2)
    for i, g in enumerate(GATES):
        col = cols[0] if i < 6 else cols[1]
        if g in logged_gate_names:
            col.success(f"✅ {g}")
        else:
            col.error(f"⬜ {g} (Missing Data)")

# --- TAB 3: RICH REPORT GENERATOR ---
with tab3:
    st.subheader("Generate Pharma Package")
    signatory = st.selectbox("Authorised Signatory for Guarantee", inspectors)
    
    if st.button("🚀 Generate Final 12-Page Bundle", type="primary"):
        if logs:
            pdf_bytes = generate_pdf(job_row, logs, signatory)
            st.download_button(
                label="📥 Download Rich Documentation",
                data=pdf_bytes,
                file_name=f"BGE_Quality_{sel_job}.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("No logs found. Please complete shop floor entries first.")
