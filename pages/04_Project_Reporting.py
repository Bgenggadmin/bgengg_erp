import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime
from fpdf import FPDF
import tempfile
import os
import pandas as pd
from PIL import Image
import io

# 1. SETUP
conn = st.connection("supabase", type=SupabaseConnection, ttl=60)

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

# --- PDF ENGINE (MULTIPLE PASSPORT PHOTOS IN ONE ROW) ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Logo fetching logic preserved
    logo_path = None
    try:
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_logo:
                tmp_logo.write(logo_data)
                logo_path = tmp_logo.name
    except: pass

    for log in logs:
        pdf.add_page()
        # Header logic preserved
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        if logo_path: pdf.image(logo_path, x=12, y=5, h=15)
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 5); pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        
        # Grid Info logic preserved
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 1, "L")
        
        # Overall Progress Bar logic preserved
        pdf.ln(5)
        ov_p = int(log.get('overall_progress', 0))
        pdf.set_font("Arial", "B", 10); pdf.cell(50, 8, f"Overall Completion: {ov_p}%", 0, 0, 'L')
        pdf.set_fill_color(230, 230, 230); pdf.rect(65, pdf.get_y() + 2, 120, 4, 'F')
        if ov_p > 0:
            pdf.set_fill_color(0, 102, 204); pdf.rect(65, pdf.get_y() + 2, (ov_p/100)*120, 4, 'F')
        
        # Milestone Table logic preserved
        pdf.ln(10)
        pdf.set_font("Arial", "B", 9); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 8, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(30, 8, " Status", 1, 0, 'C', True)
        pdf.cell(30, 8, " Progress", 1, 0, 'C', True)
        pdf.cell(80, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            pk = f"{skey}_prog"
            m_p = int(log.get(pk, 0))
            pdf.cell(50, 8, f" {label}", 1)
            pdf.cell(30, 8, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            
            cx, cy = pdf.get_x(), pdf.get_y()
            pdf.cell(30, 8, "", 1, 0)
            pdf.set_fill_color(240, 240, 240); pdf.rect(cx+3, cy+3, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76); pdf.rect(cx+3, cy+3, (m_p/100)*24, 2, 'F')
            pdf.set_xy(cx+30, cy)
            pdf.cell(80, 8, f" {str(log.get(n_key,'-'))}", 1, 1)

        # --- NEW PHOTO ROW LOGIC (PASSPORT SIZE) ---
        pdf.ln(5)
        pdf.set_font("Arial", "B", 10); pdf.cell(0, 10, "Progress Photos:", 0, 1)
        
        x_start = 10
        y_pos = pdf.get_y()
        photo_w = 45 # Passport width in mm
        photo_h = 35 # Adjusted height
        
        for i in range(4): # Loop for 4 possible photos
            try:
                photo_name = f"{log['id']}_{i}.jpg"
                img_data = conn.client.storage.from_("progress-photos").download(photo_name)
                if img_data:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(img_data)
                        pdf.image(tmp.name, x=x_start + (i * 48), y=y_pos, w=photo_w, h=photo_h)
                        os.unlink(tmp.name)
            except: pass

    if logo_path:
        try: os.unlink(logo_path)
        except: pass
    
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- DATA FETCH ---
customers, jobs = [], [] # Standard fetch logic remains same
try:
    c_res = conn.table("customer_master").select("name").execute()
    j_res = conn.table("job_master").select("job_code").execute()
    customers, jobs = sorted([d['name'] for d in c_res.data]), sorted([d['job_code'] for d in j_res.data])
except: pass

tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

# --- TAB 1: NEW ENTRY ---
with tab1:
    st.subheader("📋 Project Update")
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_lookup")
    last_data = {}
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res and res.data: last_data = res.data[0]

    with st.form("main_form", clear_on_submit=True):
        # Header info preserved
        c1, c2 = st.columns(2)
        f_cust = c1.selectbox("Customer", [""] + customers)
        f_eq = c2.text_input("Equipment", value=last_data.get('equipment', ""))
        
        # Milestone grid preserved
        st.divider()
        m_responses = {}
        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"
            col1, col2, col3 = st.columns([1.5, 1, 2])
            m_responses[skey] = col1.selectbox(label, ["Pending", "NA", "In-Progress", "Completed"], key=f"s_{skey}")
            m_responses[pk] = col2.slider("Prog %", 0, 100, value=int(last_data.get(pk, 0)), key=f"p_{skey}")
            m_responses[nkey] = col3.text_input("Remarks", value=last_data.get(nkey, ""), key=f"n_{skey}")

        f_progress = st.slider("📈 Overall Completion %", 0, 100, value=int(last_data.get('overall_progress', 0)))
        
        # --- NEW PHOTO UPLOADER (0-4 PHOTOS) ---
        st.info("📸 Upload up to 4 Photos (Passport size, Max 50KB each)")
        uploaded_photos = st.file_uploader("Choose Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

        if st.form_submit_button("🚀 SUBMIT UPDATE"):
            payload = {"customer": f_cust, "job_code": f_job, "equipment": f_eq, "overall_progress": f_progress, **m_responses}
            res = conn.table("progress_logs").insert(payload).execute()
            
            if res.data and uploaded_photos:
                log_id = res.data[0]['id']
                for idx, photo in enumerate(uploaded_photos[:4]): # Limit to 4
                    # Resize/Compress toPassport Size and under 50KB
                    img = Image.open(photo)
                    img.thumbnail((300, 300)) # Small size
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=50) # Compression
                    conn.client.storage.from_("progress-photos").upload(f"{log_id}_{idx}.jpg", buf.getvalue())
            
            st.success("✅ Saved!"); st.rerun()

# Archive & Masters remain as per your existing logic
