import streamlit as st
import pandas as pd
from fpdf import FPDF
from datetime import datetime
import pytz
from st_supabase_connection import SupabaseConnection
from streamlit_drawable_canvas import st_canvas
from PIL import Image
import io

# --- 1. SETUP & THEME ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Quality ERP", layout="wide", page_icon="🛡️")
conn = st.connection("supabase", type=SupabaseConnection)

# The 12 Official Dropdown Options (Form Identifiers)
GATES = [
    "1. Quality check list", "2. QAP", "3. As Built Drawing", 
    "4. Material Flow Chart", "5. Material Test Reports", 
    "6. Nozzle Flow Chart", "7. Dimensional Inspection Report", 
    "8. Hydro test Report", "9. Calibration Report", 
    "10. Final inspection Report", "11. Guarantee certificate", 
    "12. Customer Feed back"
]

# --- 2. ENHANCED PDF ENGINE (Matches PDF Columns/Headers) ---
class PharmaPDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'B&G ENGINEERING INDUSTRIES', ln=True, align='C')
        self.set_font('Arial', 'I', 8)
        self.cell(0, 5, 'Chemical Process Equipment Company | Hyderabad', ln=True, align='C')
        self.line(10, 27, 200, 27)
        self.ln(12)

    def draw_table_header(self, cols, widths):
        self.set_font('Arial', 'B', 10)
        for i, col in enumerate(cols):
            self.cell(widths[i], 10, col, 1, align='C')
        self.ln()

def generate_full_package(job_row, logs, signatory):
    pdf = PharmaPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # --- PAGE 1: COVER PAGE ---
    pdf.add_page()
    pdf.ln(30)
    pdf.set_font('Arial', 'B', 22)
    pdf.cell(0, 20, "QUALITY DOCUMENTATION PACKAGE", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font('Arial', 'B', 14)
    pdf.cell(0, 10, f"ITEM: {job_row.get('part_name', '30KL SS304 OIL HOLDING TANK')}", ln=True, align='C')
    pdf.ln(15)
    
    pdf.set_font('Arial', '', 12)
    details = [
        ["CLIENT NAME", f": {job_row.get('client_name', 'NEOTRAFO SOLUTIONS')}"],
        ["PO NO & DATE", f": {job_row.get('po_no', '80')} & {job_row.get('po_date', '29-12-2025')}"],
        ["JOB NUMBER", f": {job_row['job_no']}"],
        ["DRAWING NO", f": {job_row.get('drawing_no', '3050101710')}"],
        ["QAP NUMBER", f": {job_row.get('qap_no', 'BGE/QAP/1500')}"]
    ]
    for label, val in details:
        pdf.cell(50, 12, label, 0); pdf.cell(0, 12, val, 0, ln=True)

    # --- SECTION 4: MATERIAL FLOW CHART ---
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, "SECTION 4: MATERIAL FLOW CHART", ln=True)
    pdf.ln(5)
    headers = ["Description", "Size", "MOC", "TC No.", "Heat No."]
    widths = [45, 35, 25, 40, 45]
    pdf.draw_table_header(headers, widths)
    pdf.set_font('Arial', '', 10)
    for l in [log for log in logs if "4." in log['gate_name']]:
        pdf.cell(widths[0], 10, l.get('component', 'Shell'), 1)
        pdf.cell(widths[1], 10, l.get('size', '8THK'), 1)
        pdf.cell(widths[2], 10, "SS304", 1)
        pdf.cell(widths[3], 10, str(l.get('mtr_no', '-')), 1)
        pdf.cell(widths[4], 10, str(l.get('heat_no', 'N/A')), 1, ln=True)

    # --- SECTION 7: DIMENSIONAL INSPECTION (DIR) ---
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, "SECTION 7: DIMENSIONAL INSPECTION REPORT", ln=True)
    pdf.ln(5)
    headers = ["Description", "Specified Dim", "Measured Dim", "MOC"]
    widths = [60, 45, 45, 40]
    pdf.draw_table_header(headers, widths)
    pdf.set_font('Arial', '', 10)
    for l in [log for log in logs if "7." in log['gate_name']]:
        pdf.cell(widths[0], 10, l.get('component', 'Shell ID'), 1)
        pdf.cell(widths[1], 10, l.get('specified_val', '-'), 1)
        pdf.cell(widths[2], 10, l.get('measured_val', '-'), 1)
        pdf.cell(widths[3], 10, "SS304", 1, ln=True)

    # --- SECTION 11: GUARANTEE CERTIFICATE ---
    pdf.add_page()
    pdf.ln(20)
    pdf.set_font('Arial', 'B', 16); pdf.cell(0, 15, "GUARANTEE CERTIFICATE", ln=True, align='C')
    pdf.ln(10); pdf.set_font('Arial', '', 12)
    pdf.multi_cell(0, 10, f"This is to certify that the equipment Job No {job_row['job_no']} is guaranteed for 12 months from the date of supply against manufacturing defectives.")
    pdf.ln(30); pdf.cell(0, 10, f"Authorized Signatory: {signatory}", ln=True, align='R')

    return pdf.output(dest='S').encode('latin-1')

# --- 3. UI LOGIC & DASHBOARD ---
st.title("🛡️ B&G Quality Integration Portal")

try:
    projs_data = conn.table("anchor_projects").select("*").execute().data
    staff_data = conn.table("master_staff").select("name").execute().data
    inspectors = [s['name'] for s in staff_data]
    sel_job = st.sidebar.selectbox("Select Active Job", [p['job_no'] for p in projs_data])
    job_row = next(p for p in projs_data if p['job_no'] == sel_job)
except Exception as e:
    st.error(f"Setup Error: {e}"); st.stop()

tab1, tab2, tab3 = st.tabs(["🏗️ Daily Work Entry", "📊 Readiness Dashboard", "📄 Report Generator"])

# --- TAB 1: WORKFLOW ENTRY ---
with tab1:
    st.subheader(f"Log Data for {sel_job}")
    with st.form("inspection_gate", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        gate = c1.selectbox("Select Form Section", GATES)
        comp = c1.text_input("Component Name (e.g., Top Dish)")
        size = c1.text_input("Size/THK")
        
        heat = c2.text_input("Heat No / MTR No")
        spec = c2.text_input("Specified Dim (from Drawing)")
        meas = c2.text_input("Measured Dim (Actual)")
        
        inspt = c3.selectbox("Inspector", inspectors)
        res = c3.segmented_control("Result", ["✅ Pass", "❌ Reject"], default="✅ Pass")
        
        st.write("🖋️ Authorized Signatory Pad")
        canvas = st_canvas(stroke_width=2, stroke_color="#000", height=100, width=300, key="sig_pad")
        
        if st.form_submit_button("Submit & Record Entry"):
            payload = {
                "job_no": sel_job, "gate_name": gate, "component": comp, "size": size,
                "heat_no": heat, "specified_val": spec, "measured_val": meas, 
                "inspector_name": inspt, "quality_status": res
            }
            conn.table("quality_inspection_logs").insert(payload).execute()
            st.success("Record saved to database.")

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
