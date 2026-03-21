import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, timedelta
from fpdf import FPDF
from io import BytesIO
from PIL import Image
import tempfile
import os

# 1. SETUP & CONSTANTS
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection, ttl=60)

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

# --- 2. ENGINE ---
def process_photos(uploaded_files):
    processed = []
    for file in uploaded_files[:4]:
        img = Image.open(file)
        img = img.resize((350, 450), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=70) 
        if buf.tell() > 51200:
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=40)
        processed.append(buf.getvalue())
    return processed

def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
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
        report_date = datetime.now().strftime('%d-%m-%Y')

        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        if logo_path: pdf.image(logo_path, x=12, y=5, h=15)
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 5); pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 10); pdf.set_xy(70, 14); pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','N/A')} | ID: {log.get('id','N/A')}", "B", 0, "L")
        pdf.set_xy(10, 30)
        pdf.cell(0, 8, f"Report Date: {report_date} ", 0, 1, "R")
        
        pdf.ln(2); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        
        for i in range(0, len(HEADER_FIELDS), 2):
            f1 = HEADER_FIELDS[i]; f2 = HEADER_FIELDS[i+1] if i+1 < len(HEADER_FIELDS) else None
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,'-'))}", 1, 0, 'L')
            if f2:
                pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
                pdf.cell(65, 7, f" {str(log.get(f2,'-'))}", 1, 1, 'L')
            else: pdf.ln(7)

        pdf.ln(5); ov_p = int(log.get('overall_progress', 0) or 0)
        pdf.set_font("Arial", "B", 10); pdf.cell(50, 8, f"Overall Completion: {ov_p}%", 0, 0, 'L')
        pdf.set_fill_color(230, 230, 230); pdf.rect(60, pdf.get_y() + 2, 130, 4, 'F')
        if ov_p > 0:
            pdf.set_fill_color(0, 82, 164)
            pdf.rect(60, pdf.get_y() + 2, (ov_p / 100) * 130, 4, 'F')
        pdf.ln(10)

        pdf.set_font("Arial", "B", 9); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 8, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(30, 8, " Status", 1, 0, 'C', True)
        pdf.cell(30, 8, " Progress", 1, 0, 'C', True) 
        pdf.cell(80, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            pk = f"{s_key}_prog"
            m_p = int(log.get(pk, 0) or 0)
            pdf.cell(50, 10, f" {label}", 1)
            pdf.cell(30, 10, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            curr_x, curr_y = pdf.get_x(), pdf.get_y()
            pdf.cell(30, 10, "", 1, 0) 
            pdf.set_fill_color(240, 240, 240); pdf.rect(curr_x + 3, curr_y + 4, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76); pdf.rect(curr_x + 3, curr_y + 4, (min(m_p, 100) / 100) * 24, 2, 'F')
            pdf.set_xy(curr_x + 30, curr_y)
            pdf.cell(80, 10, f" {str(log.get(n_key,'-'))}", 1, 1)

        pdf.ln(10) 
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, "Progress Documentation Photos:", 0, 1, "L")
        
        start_y = pdf.get_y() 
        img_x = 10
        photo_count = 0

        for i in range(4):
            try:
                img_path = f"{log.get('id')}_{i}.jpg"
                img_data = conn.client.storage.from_("progress-photos").download(img_path)
                if img_data:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                        tmp_img.write(img_data)
                        tmp_img.flush()
                        pdf.image(tmp_img.name, x=img_x, y=start_y, w=45)
                        img_x += 48
                        photo_count += 1
                        t_name = tmp_img.name
                    os.unlink(t_name)
            except: continue

    if logo_path and os.path.exists(logo_path):
        os.unlink(logo_path)
    return bytes(pdf.output(dest='S'), encoding='latin-1')

# --- 3. DATA FETCH ---
@st.cache_data(ttl=60)
def get_master_data():
    try:
        res = conn.table("anchor_projects").select("client_name, job_no").execute()
        if res.data:
            c_list = list(set([d['client_name'] for d in res.data if d.get('client_name')]))
            j_list = list(set([d['job_no'] for d in res.data if d.get('job_no')]))
            return sorted(c_list), sorted(j_list)
        return [], []
    except: return [], []

customers, jobs = get_master_data()

# --- 4. MAIN UI ---
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🧬 System Schema"])

with tab1:
    st.subheader("📋 Project Update")
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_lookup")
    last_data = {}
    
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res and res.data: 
            last_data = res.data[0]
            st.toast(f"🔄 Autofilled latest data for {f_job}")
        else:
            anchor_res = conn.table("anchor_projects").select("*").eq("job_no", f_job).limit(1).execute()
            if anchor_res and anchor_res.data:
                a_info = anchor_res.data[0]
                last_data = {
                    "customer": a_info.get("client_name"),
                    "equipment": a_info.get("project_description"),
                    "po_no": a_info.get("po_no"),
                    "po_date": a_info.get("po_date"),
                    "engineer": a_info.get("anchor_person"),
                    "po_delivery_date": a_info.get("po_delivery_date"),
                    "exp_dispatch_date": a_info.get("revised_delivery_date")
                }
                st.toast(f"✨ New Job: Pulled from Anchor Portal")

    with st.form("main_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        try:
            c_idx = customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0
        except: c_idx = 0

        f_cust = c1.selectbox("Customer", [""] + customers, index=c_idx)
        f_eq = c2.text_input("Equipment", value=str(last_data.get('equipment') or ""))
        
        c3, c4, c5 = st.columns(3)
        f_po_n = c3.text_input("PO Number", value=str(last_data.get('po_no') or ""))
        
        def safe_date(field):
            val = last_data.get(field)
            try: return datetime.strptime(val, "%Y-%m-%d") if val else datetime.now()
            except: return datetime.now()

        f_po_d = c4.date_input("PO Date", value=safe_date('po_date'))
        f_eng = c5.text_input("Responsible Engineer", value=str(last_data.get('engineer') or ""))

        c6, c7 = st.columns(2)
        f_po_del = c6.date_input("PO Delivery Date", value=safe_date('po_delivery_date'))
        f_exp_disp = c7.date_input("Expected Dispatch Date", value=safe_date('exp_dispatch_date'))

        st.divider()
        st.subheader("📊 Milestone Tracking")
        m_responses = {}
        opts = ["Pending", "NA", "In-Progress", "Submitted", "Approved", "Ordered", "Received", "Hold", "Completed", "Planning", "Scheduled"]
        job_suffix = str(f_job) if f_job else "initial"

        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"
            col1, col2, col3 = st.columns([1.5, 1, 2])
            prev_status = str(last_data.get(skey) or "Pending")
            def_idx = opts.index(prev_status) if prev_status in opts else 0
            prev_prog = int(last_data.get(pk, 0) or 0)
            prev_note = str(last_data.get(nkey) or "")
            
            m_responses[skey] = col1.selectbox(label, opts, index=def_idx, key=f"s_{skey}_{job_suffix}")
            m_responses[pk] = col2.slider("Prog %", 0, 100, value=prev_prog, key=f"p_{skey}_{job_suffix}")
            m_responses[nkey] = col3.text_input("Remarks", value=prev_note, key=f"n_{skey}_{job_suffix}")

        st.divider()
        f_progress = st.slider("📈 Overall Completion %", 0, 100, value=int(last_data.get('overall_progress', 0) or 0), key=f"ov_{job_suffix}")
        
        uploaded_photos = st.file_uploader("Upload Progress Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job:
                st.error("Please select Customer and Job Code")
            else:
                payload = {
                    "customer": f_cust, "job_code": f_job, "equipment": f_eq,
                    "po_no": f_po_n, "po_date": str(f_po_d), "engineer": f_eng,
                    "po_delivery_date": str(f_po_del), "exp_dispatch_date": str(f_exp_disp),
                    "overall_progress": f_progress, **m_responses
                }
                res = conn.table("progress_logs").insert(payload).execute()
                
                if uploaded_photos and res.data:
                    file_id = res.data[0]['id']
                    processed_list = process_photos(uploaded_photos)
                    for i, img_data in enumerate(processed_list):
                        conn.client.storage.from_("progress-photos").upload(
                            f"{file_id}_{i}.jpg", img_data,
                            file_options={"content-type": "image/jpeg"}
                        )
                st.success("✅ Saved!"); st.cache_data.clear(); st.rerun()

with tab2:
    st.subheader("📂 Report Archive")
    f1, f2, f3 = st.columns(3)
    sel_c = f1.selectbox("Filter Customer", ["All"] + customers)
    report_type = f2.selectbox("📅 Period", ["All Time", "Current Week", "Current Month", "Custom Range"])
    
    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if sel_c != "All":
        query = query.eq("customer", sel_c)
    
    res = query.execute()
    data = res.data if res.data else []

    if data:
        if st.button("📥 Prepare PDF for Download", use_container_width=True):
            with st.spinner("Generating PDF..."):
                pdf_bytes = generate_pdf(data)
                if pdf_bytes:
                    st.download_button(label="✅ Click here to Save PDF", data=pdf_bytes, file_name=f"BG_Report.pdf", mime="application/pdf")
        
        for log in data:
            with st.expander(f"📦 {log.get('job_code')} - {log.get('customer')}"):
                st.write(f"**Overall: {log.get('overall_progress')}%**")
                st.progress(int(log.get('overall_progress') or 0) / 100)

with tab3:
    st.subheader("🧬 System Database Mapping")
    st.info("This tab shows which Supabase resources are currently powering this application.")
    
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.markdown("### 📊 Active Tables")
        st.code("""
1. anchor_projects
   - Purpose: Source for Job Codes, Customers, and PO dates.
   - Primary Key: job_no

2. progress_logs
   - Purpose: Stores every progress update and milestone.
   - Used for: Generating PDFs and history.
        """)
        
    with col_b:
        st.markdown("### ☁️ Storage & Assets")
        st.code("""
1. Bucket: 'progress-photos'
   - logo.png: Used for PDF Header.
   - {id}_{index}.jpg: Project photos.
        """)
    
    st.divider()
    st.markdown("### 🔄 Logic Flow")
    st.write("1. **Job Selection:** App queries `anchor_projects` to populate dropdown.")
    st.write("2. **Form Autofill:** App checks `progress_logs` for history; if empty, it pulls baseline data from `anchor_projects`.")
    st.write("3. **Submission:** Data is saved to `progress_logs`, and images are uploaded to the storage bucket.")
