import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime
from fpdf import FPDF
import requests
from io import BytesIO
from PIL import Image

# NOTE: st.set_page_config is removed here because it's managed by the main_dashboard.py
st.header("📋 Project Progress & PDF Reporting")

# 1. DATABASE CONNECTION
conn = st.connection("supabase", type=SupabaseConnection)

# 2. MASTER MAPPING & CONSTANTS
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

# --- DATA FETCHING (Using caching for speed) ---
@st.cache_data(ttl=60)
def fetch_masters():
    cust_data = conn.table("customer_master").select("name").execute()
    job_data = conn.table("job_master").select("job_code").execute()
    return (
        sorted([d['name'] for d in cust_data.data or []]),
        sorted([d['job_code'] for d in job_data.data or []])
    )

customers, jobs = fetch_masters()

# --- PDF GENERATION ENGINE ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    for log in logs:
        pdf.add_page()
        # Header Blue Strip
        pdf.set_fill_color(0, 51, 102) 
        pdf.rect(0, 0, 210, 25, 'F')
        
        # Logo Logic
        try:
            logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
            if logo_data:
                pdf.image(BytesIO(logo_data), x=12, y=5, h=15) 
        except: pass

        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 5) 
        pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        
        pdf.set_font("Arial", "I", 10)
        pdf.set_xy(70, 14) 
        pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 1, "L")
        pdf.ln(2)
        
        # Field Grid
        pdf.set_font("Arial", "B", 8)
        pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,''))}", 1, 0, 'L')
            pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f2,''))}", 1, 1, 'L')

        # Milestone Table
        pdf.ln(5)
        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(60, 8, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(35, 8, " Status", 1, 0, 'C', True)
        pdf.cell(95, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            status = str(log.get(s_key, 'Pending'))
            if status in ["Completed", "Approved", "Submitted"]: pdf.set_fill_color(144, 238, 144)
            elif status in ["In-Progress", "Ordered", "Received"]: pdf.set_fill_color(255, 255, 204)
            else: pdf.set_fill_color(255, 255, 255)
            
            pdf.cell(60, 7, f" {label}", 1)
            pdf.cell(35, 7, f" {status}", 1, 0, 'C', True)
            pdf.cell(95, 7, f" {str(log.get(n_key,'-'))}", 1, 1)

        # Photo Integration
        try:
            img_url = conn.client.storage.from_("progress-photos").get_public_url(f"{log['id']}.jpg")
            img_res = requests.get(img_url)
            if img_res.status_code == 200:
                img = Image.open(BytesIO(img_res.content)).convert('RGB')
                img.thumbnail((300, 300))
                buf = BytesIO(); img.save(buf, format="JPEG")
                pdf.image(buf, x=75, y=pdf.get_y()+10, w=60)
        except: pass

    return bytes(pdf.output())

# --- UI TABS ---
tab1, tab2, tab3 = st.tabs(["📝 New Update", "📂 Report Archive", "🛠️ Masters"])

with tab1:
    st.subheader("Project Status Update")
    f_job = st.selectbox("Search Job Code", [""] + jobs, key="job_lookup")
    
    last_data = {}
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res.data: last_data = res.data[0]

    with st.form("progress_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_cust = c1.selectbox("Customer", [""] + customers, index=customers.index(last_data['customer'])+1 if last_data.get('customer') in customers else 0)
        f_eq = c2.text_input("Equipment Name", value=last_data.get('equipment', ""))
        
        st.divider()
        m_responses = {}
        for label, skey, nkey in MILESTONE_MAP:
            col1, col2 = st.columns([1, 2])
            opts = ["Pending", "In-Progress", "Completed", "NA", "Hold"] # Simplified for ERP
            prev_status = last_data.get(skey, "Pending")
            def_idx = opts.index(prev_status) if prev_status in opts else 0
            m_responses[skey] = col1.selectbox(label, opts, index=def_idx)
            m_responses[nkey] = col2.text_input(f"Remarks ({label})", value=last_data.get(nkey, ""))
        
        cam_photo = st.camera_input("Capture Progress Photo")
        
        if st.form_submit_button("💾 Save Progress Update", use_container_width=True):
            if f_job and f_cust:
                payload = {"customer": f_cust, "job_code": f_job, "equipment": f_eq, **m_responses}
                res = conn.table("progress_logs").insert(payload).execute()
                if cam_photo and res.data:
                    conn.client.storage.from_("progress-photos").upload(f"{res.data[0]['id']}.jpg", cam_photo.getvalue())
                st.success("Success!")
                st.rerun()

with tab2:
    st.subheader("Search & PDF Export")
    # ... Your Archive logic from the original code fits here ...
    # Be sure to keep the filter logic to pass the 'filtered_data' to generate_pdf()
    st.info("Select a customer and date range to generate the PDF report.")

with tab3:
    st.info("Manage Customer and Job Master lists below.")
    # ... Your Master Data UI from tab3 fits here ...
