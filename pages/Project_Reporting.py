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

# 2. MASTER MAPPING
HEADER_FIELDS = ["customer", "job_code", "equipment", "po_no", "po_date", "engineer", "po_delivery_date", "exp_dispatch_date"]

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

# --- DATA FETCHING ---
customers = sorted([d['name'] for d in conn.table("customer_master").select("name").execute().data])
jobs = sorted([d['job_code'] for d in conn.table("job_master").select("job_code").execute().data])

# --- PDF ENGINE ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Download logo once
    logo_bytes = None
    try:
        logo_raw = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_raw:
            logo_bytes = BytesIO(logo_raw)
    except:
        pass

    for log in logs:
        pdf.add_page()
        
        # Header Strip
        pdf.set_fill_color(0, 51, 102) 
        pdf.rect(0, 0, 210, 25, 'F')
        
        if logo_bytes:
            logo_bytes.seek(0)
            pdf.image(logo_bytes, x=12, y=5, h=15)

        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(70, 5) 
        pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_xy(70, 14)
        pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        pdf.set_text_color(0, 0, 0)
        pdf.set_xy(10, 30)
        pdf.set_font("Helvetica", "B", 10)
        job_id = f" JOB: {log.get('job_code','-')} | ID: {log.get('id','-')}"
        pdf.cell(0, 8, job_id, "B", 1, "L")
        pdf.ln(2)
        
        # Grid Data
        pdf.set_font("Helvetica", "B", 8)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            pdf.set_fill_color(240, 240, 240)
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(65, 7, f" {str(log.get(f1,'-'))}", 1, 0, 'L')
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(65, 7, f" {str(log.get(f2,'-'))}", 1, 1, 'L')

        pdf.ln(5)

        # Milestone Table
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(60, 8, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(35, 8, " Status", 1, 0, 'C', True)
        pdf.cell(95, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Helvetica", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            status = str(log.get(s_key, 'Pending'))
            if status in ["Completed", "Approved", "Submitted"]: pdf.set_fill_color(144, 238, 144)
            elif status in ["In-Progress", "Hold", "Ordered"]: pdf.set_fill_color(255, 255, 204)
            else: pdf.set_fill_color(255, 255, 255)
            
            pdf.cell(60, 7, f" {label}", 1)
            pdf.cell(35, 7, f" {status}", 1, 0, 'C', True)
            pdf.cell(95, 7, f" {str(log.get(n_key,'-'))}", 1, 1)

    return pdf.output()

# --- APP TABS ---
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

with tab2:
    st.subheader("📂 Report Archive")
    c1, c2 = st.columns(2)
    sel_cust = c1.selectbox("Filter Customer", ["All"] + customers)
    sel_dur = c2.selectbox("Duration", ["All Time", "Current Week", "Current Month"])

    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if sel_cust != "All": query = query.eq("customer", sel_cust)
    
    res = query.execute()
    data = res.data if res.data else []

    if data:
        pdf_data = generate_pdf(data)
        st.download_button("📥 Download PDF Report", data=pdf_data, file_name="Report.pdf", mime="application/pdf", use_container_width=True)
        
        for log in data:
            with st.expander(f"Job: {log.get('job_code','-')} | {log.get('customer','-')}"):
                st.write(f"**Equipment:** {log.get('equipment','-')}")
                st.write(f"**Engineer:** {log.get('engineer','-')}")
    else:
        st.warning("No records found.")

# Note: Tab 1 and Tab 3 code remains as per your working version
