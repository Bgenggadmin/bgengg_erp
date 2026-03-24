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

# Define the 12 Gates/Sections for Workflow
GATES = [
    "Material Receiving", "Shell Fit-up", "Dish Fit-up", "Shell Welding", 
    "Nozzle Orientation", "Nozzle Welding", "Internal Grinding", 
    "Dimensional Check", "Hydro Test", "Pneumatic Test", "Pickling & Passivation", "Final Inspection"
]

# --- 2. PDF GENERATOR CLASS ---
class PharmaPDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'B&G ENGINEERING INDUSTRIES', ln=True, align='C')
        self.set_font('Arial', 'I', 8)
        self.cell(0, 5, 'Plot no. 207, Industrial park, Pashamylaram, Hyderabad', ln=True, align='C')
        self.line(10, 27, 200, 27)
        self.ln(12)

# --- 3. CORE LOGIC FUNCTIONS ---
def save_signature(canvas_data, job_no):
    if canvas_data is not None:
        img = Image.fromarray(canvas_data.astype('uint8'), 'RGBA')
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        file_name = f"sig_{job_no}_{datetime.now().strftime('%H%M%S')}.png"
        conn.client.storage.from_("quality-photos").upload(file_name, buf.getvalue())
        return conn.client.storage.from_("quality-photos").get_public_url(file_name)
    return None

def generate_full_package(job_row, logs, signatory):
    pdf = PharmaPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # PAGE 1: COVER
    pdf.add_page()
    pdf.ln(30); pdf.set_font('Arial', 'B', 22); pdf.cell(0, 20, "QUALITY DOCUMENTATION PACKAGE", ln=True, align='C')
    pdf.ln(10); pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, f"ITEM: {job_row.get('part_name', 'Process Equipment')}", ln=True, align='C')
    pdf.ln(10)
    pdf.set_font('Arial', '', 12)
    fields = [["CLIENT", job_row.get('client_name')], ["JOB NO", job_row['job_no']], ["PO NO", job_row.get('po_no')], ["DRAWING", job_row.get('drawing_no')]]
    for f in fields:
        pdf.cell(50, 10, f[0], 0); pdf.cell(0, 10, f": {f[1]}", 0, ln=True)

    # PAGE 4: MATERIAL FLOW (TRACEABILITY)
    pdf.add_page()
    pdf.set_font('Arial', 'B', 14); pdf.cell(0, 10, "SECTION 4: MATERIAL FLOW CHART", ln=True)
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(50, 10, "Component", 1); pdf.cell(70, 10, "Heat Number", 1); pdf.cell(70, 10, "Status", 1, ln=True)
    pdf.set_font('Arial', '', 10)
    for log in logs:
        pdf.cell(50, 10, log['gate_name'], 1)
        pdf.cell(70, 10, str(log.get('heat_no', 'N/A')), 1)
        pdf.cell(70, 10, log['quality_status'], 1, ln=True)

    # PAGE 11: GUARANTEE
    pdf.add_page()
    pdf.set_font('Arial', 'B', 16); pdf.cell(0, 20, "GUARANTEE CERTIFICATE", ln=True, align='C')
    pdf.set_font('Arial', '', 12)
    pdf.multi_cell(0, 10, f"The equipment under Job {job_row['job_no']} is guaranteed for 12 months from dispatch against manufacturing defects.")
    pdf.ln(20); pdf.cell(0, 10, "For B&G ENGINEERING INDUSTRIES", ln=True, align='R')
    pdf.ln(5); pdf.cell(0, 10, f"({signatory.upper()})", ln=True, align='R')
    
    return pdf.output(dest='S').encode('latin-1')

# --- 4. APP UI ---
st.title("🛡️ B&G Quality & Documentation Hub")

try:
    projs = conn.table("anchor_projects").select("*").execute().data
    staff = conn.table("master_staff").select("name").execute().data
    inspector_list = [s['name'] for s in staff]
    sel_job = st.sidebar.selectbox("Select Active Job", [p['job_no'] for p in projs])
    job_row = next(item for item in projs if item["job_no"] == sel_job)
except:
    st.error("Database Connection Failed."); st.stop()

t1, t2, t3 = st.tabs(["🏗️ Daily Inspection", "📂 Material MTR Archive", "📄 Report Generator"])

# TAB 1: DAILY INSPECTION
with t1:
    st.subheader(f"Log Work for {sel_job}")
    with st.form("gate_entry"):
        c1, c2 = st.columns(2)
        gate = c1.selectbox("Select Gate", GATES)
        heat = c1.text_input("Heat No / Plate No")
        spec = c1.text_input("Specified Value")
        meas = c2.text_input("Measured Value")
        inspt = c2.selectbox("Inspector", inspector_list)
        stat = c2.segmented_control("Result", ["✅ Pass", "❌ Reject"])
        
        st.write("🖋️ Sign to Authorize")
        canvas_result = st_canvas(stroke_width=2, stroke_color="#000", background_color="#fff", height=100, width=300, key="canvas")
        
        if st.form_submit_button("Record Gate Entry"):
            sig_url = save_signature(canvas_result.image_data, sel_job)
            payload = {
                "job_no": sel_job, "gate_name": gate, "heat_no": heat, 
                "specified_val": spec, "measured_val": meas, 
                "inspector_name": inspt, "quality_status": stat, "signature_url": sig_url
            }
            conn.table("quality_inspection_logs").insert(payload).execute()
            st.success("Entry Recorded and Signed.")

# TAB 2: MATERIAL ARCHIVE
with t2:
    st.subheader("Global MTR Vault")
    with st.expander("Upload New Vendor Certificate"):
        h_no = st.text_input("Heat Number Lookup")
        mtr_f = st.file_uploader("Upload TC PDF")
        if st.button("Archive MTR"):
            st.info("MTR Archiving Logic Triggered")

# TAB 3: REPORT GENERATOR
with t3:
    st.subheader("Pharma Package Status")
    logs = conn.table("quality_inspection_logs").eq("job_no", sel_job).execute().data
    log_df = pd.DataFrame(logs)
    
    if not log_df.empty:
        # Show Readiness Metrics
        done_gates = log_df['gate_name'].unique()
        st.write(f"Completed Gates: {len(done_gates)} / {len(GATES)}")
        st.progress(len(done_gates)/len(GATES))
        
        signatory = st.selectbox("Authorised Signatory for Report", inspector_list)
        if st.button("🚀 Generate 12-Page Rich Bundle"):
            pdf_bytes = generate_full_package(job_row, logs, signatory)
            st.download_button("📥 Download Final Documentation", pdf_bytes, f"BG_{sel_job}_Quality.pdf")
    else:
        st.warning("No daily logs found. Complete inspections to generate reports.")
