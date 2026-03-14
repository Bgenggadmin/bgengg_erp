import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime
from fpdf import FPDF
import requests
from io import BytesIO
from PIL import Image

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# 2. THE MASTER MAPPING & WEIGHTED LOGIC
# Define how much EACH milestone contributes to the 100% total
MILESTONE_WEIGHTS = {
    "draw_sub": 0.05, 
    "draw_app": 0.05,
    "rm_status": 0.20,
    "sub_del": 0.05,
    "fab_status": 0.30,
    "buff_stat": 0.10,
    "testing": 0.10,
    "qc_stat": 0.10,
    "fat_stat": 0.05
}

# Define how much each STATUS within a milestone is worth (0.0 to 1.0)
STATUS_MULTIPLIER = {
    "Completed": 1.0, "Approved": 1.0, "Submitted": 1.0, "Received": 1.0, "NA": 1.0,
    "In-Progress": 0.5, "Ordered": 0.4, "Scheduled": 0.2, "Planning": 0.1,
    "Pending": 0.0, "Hold": 0.0
}

MILESTONE_MAP = [
    ("Drawing Submission", "draw_sub", "draw_sub_note"),
    ("Drawing Approval", "draw_app", "draw_app_note"),
    ("RM Status", "rm_status", "rm_note"),
    ("Sub-deliveries", "sub_del", "sub_del_note"),
    ("Fabrication Status", "fab_status", "remarks"),
    ("Buffing Status", "buff_stat", "buff_note"),
    ("Testing Status", "testing", "test_note"),
    ("Dispatch Status", "qc_stat", "qc_note"),
    ("FAT Status", "fat_stat", "fat_note")
]

# --- PDF ENGINE ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    for log in logs:
        pdf.add_page()
        
        # Calculate Weighted Progress
        total_weighted_progress = 0
        for skey, weight in MILESTONE_WEIGHTS.items():
            status = log.get(skey, "Pending")
            total_weighted_progress += (STATUS_MULTIPLIER.get(status, 0) * weight)
        overall_pct = int(total_weighted_progress * 100)

        # 1. HEADER (Blue Strip & Logo)
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        try:
            logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
            if logo_data: pdf.image(BytesIO(logo_data), x=12, y=5, h=15)
        except: pass

        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 16); pdf.set_xy(70, 5); pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 10); pdf.set_xy(70, 14); pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        # 2. JOB HEADER & OVERALL PROGRESS
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
        pdf.cell(140, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 0, "L")
        pdf.set_text_color(0, 51, 102); pdf.cell(50, 8, f"WEIGHTED PROGRESS: {overall_pct}%", "B", 1, "R")
        
        # 3. FIELD GRID (Header Details)
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        fields = ["customer", "job_code", "equipment", "po_no", "po_date", "engineer", "po_delivery_date", "exp_dispatch_date"]
        for i in range(0, len(fields), 2):
            f1, f2 = fields[i], fields[i+1]
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,''))}", 1, 0, 'L')
            pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f2,''))}", 1, 1, 'L')

        # 4. MILESTONE TABLE
        pdf.ln(5); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 9)
        pdf.cell(65, 8, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(20, 8, " Weight", 1, 0, 'C', True)
        pdf.cell(35, 8, " Status", 1, 0, 'C', True)
        pdf.cell(70, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, skey, nkey in MILESTONE_MAP:
            status = str(log.get(skey, 'Pending'))
            weight_label = f"{int(MILESTONE_WEIGHTS[skey]*100)}%"
            
            # Row coloring based on completion
            if STATUS_MULTIPLIER.get(status) == 1.0: pdf.set_fill_color(144, 238, 144)
            elif STATUS_MULTIPLIER.get(status, 0) > 0: pdf.set_fill_color(255, 255, 204)
            else: pdf.set_fill_color(255, 255, 255)
            
            pdf.cell(65, 7, f" {label}", 1)
            pdf.cell(20, 7, f" {weight_label}", 1, 0, 'C')
            pdf.cell(35, 7, f" {status}", 1, 0, 'C', True)
            pdf.cell(70, 7, f" {str(log.get(nkey,'-'))}", 1, 1)

    raw_pdf = pdf.output()
    return bytes(raw_pdf) if isinstance(raw_pdf, (bytes, bytearray)) else raw_pdf.encode('latin-1')

# --- TAB 1: ENTRY FORM ---
with st.sidebar:
    st.header("⚙️ App Settings")
    st.caption("Weights are pre-configured to prioritize Fabrication (30%) and RM Status (20%).")

# (Data fetching for customers/jobs remains as before)
customers = sorted([d['name'] for d in conn.table("customer_master").select("name").execute().data])
jobs = sorted([d['job_code'] for d in conn.table("job_master").select("job_code").execute().data])

tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

with tab1:
    f_job = st.selectbox("Select Job Code", [""] + jobs, key="job_lookup")
    last_data = {}
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res.data: last_data = res.data[0]

    with st.form("entry_form"):
        # (Project details section remains same as previous code)
        # ...
        
        st.subheader("📊 Weighted Milestone Tracking")
        total_progress_bar = st.empty()
        m_responses = {}
        calc_progress = 0
        
        for label, skey, nkey in MILESTONE_MAP:
            col_stat, col_note, col_info = st.columns([1.5, 2, 1])
            
            # Logic for dropdown options
            if "Drawing" in label: opts = ["Pending", "NA", "In-Progress", "Submitted", "Approved"]
            elif "RM" in label: opts = ["Pending", "Ordered", "Received", "NA", "Hold"]
            else: opts = ["Pending", "Planning", "In-Progress", "Scheduled", "Completed", "NA"]
            
            prev_status = last_data.get(skey, "Pending")
            status_val = col_stat.selectbox(label, opts, index=opts.index(prev_status) if prev_status in opts else 0, key=f"s_{skey}")
            m_responses[skey] = status_val
            m_responses[nkey] = col_note.text_input("Remarks", value=last_data.get(nkey, ""), key=f"n_{nkey}")
            
            # Show individual weight contribution
            w_contrib = MILESTONE_WEIGHTS[skey]
            current_contrib = STATUS_MULTIPLIER.get(status_val, 0) * w_contrib
            calc_progress += current_contrib
            col_info.write(f"Weight: {int(w_contrib*100)}%")
            col_info.progress(STATUS_MULTIPLIER.get(status_val, 0))

        # Final Overall Bar
        final_pct = int(calc_progress * 100)
        total_progress_bar.markdown(f"### 🎯 Total Project Completion: {final_pct}%")
        total_progress_bar.progress(calc_progress)

        if st.form_submit_button("🚀 SAVE UPDATE"):
            # (Save logic remains same as previous code)
            pass
