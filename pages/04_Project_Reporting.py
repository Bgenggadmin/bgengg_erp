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
if 'page_config_set' not in st.session_state:
    st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
    st.session_state.page_config_set = True

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

# --- 🏎️ PERFORMANCE & AUTOFILL LOGIC ---
def sync_job_data():
    """Callback to fetch last project data when Job Code changes"""
    job = st.session_state.job_lookup
    if job:
        res = conn.table("progress_logs").select("*").eq("job_code", job).order("id", desc=True).limit(1).execute()
        if res.data:
            st.session_state['last_entry_data'] = res.data[0]
        else:
            st.session_state['last_entry_data'] = {}
    else:
        st.session_state['last_entry_data'] = {}

# --- PDF ENGINE ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    logo_path = None
    try:
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_logo:
                tmp_logo.write(logo_data); logo_path = tmp_logo.name
    except: pass

    for log in logs:
        pdf.add_page()
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        if logo_path: pdf.image(logo_path, x=12, y=5, h=15)
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 7); pdf.cell(130, 10, "B&G PROJECT REPORT", 0, 1, "L")
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 1, "L")
        
        pdf.ln(2); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1 = HEADER_FIELDS[i]; f2 = HEADER_FIELDS[i+1] if i+1 < len(HEADER_FIELDS) else None
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,''))}", 1, 0, 'L')
            if f2:
                pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
                pdf.cell(65, 7, f" {str(log.get(f2,''))}", 1, 1, 'L')
            else: pdf.ln(7)

        pdf.ln(5); ov_p = int(log.get('overall_progress', 0))
        pdf.set_font("Arial", "B", 10); pdf.cell(50, 8, f"Overall Completion: {ov_p}%")
        pdf.set_fill_color(230, 230, 230); pdf.rect(65, pdf.get_y() + 2, 120, 4, 'F')
        if ov_p > 0:
            pdf.set_fill_color(0, 82, 164); pdf.rect(65, pdf.get_y() + 2, (ov_p/100)*120, 4, 'F')
        
        pdf.ln(10); pdf.set_font("Arial", "B", 9); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 8, " Milestone", 1, 0, 'L', True); pdf.cell(30, 8, " Status", 1, 0, 'C', True)
        pdf.cell(30, 8, " Progress", 1, 0, 'C', True); pdf.cell(80, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            pk = f"{s_key}_prog"; m_p = int(log.get(pk, 0))
            pdf.cell(50, 8, f" {label}", 1); pdf.cell(30, 8, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            cx, cy = pdf.get_x(), pdf.get_y()
            pdf.cell(30, 8, "", 1, 0); pdf.set_fill_color(240, 240, 240); pdf.rect(cx+3, cy+3, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76); pdf.rect(cx+3, cy+3, (m_p/100)*24, 2, 'F')
            pdf.set_xy(cx+30, cy); pdf.cell(80, 8, f" {str(log.get(n_key,'-'))}", 1, 1)

        pdf.ln(5); x_start, y_pos = 10, pdf.get_y()
        for i in range(4):
            try:
                photo_data = conn.client.storage.from_("progress-photos").download(f"{log['id']}_{i}.jpg")
                if photo_data:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(photo_data); pdf.image(tmp.name, x=x_start + (i * 48), y=y_pos, w=45, h=35); os.unlink(tmp.name)
            except: pass

    if logo_path:
        try: os.unlink(logo_path)
        except: pass
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- DATA FETCH ---
@st.cache_data(ttl=600)
def get_master_data():
    try:
        c_res = conn.table("customer_master").select("name").execute()
        j_res = conn.table("job_master").select("job_code").execute()
        return sorted([d['name'] for d in c_res.data]), sorted([d['job_code'] for d in j_res.data])
    except: return [], []

customers, jobs = get_master_data()
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

# --- TAB 1: NEW ENTRY ---
with tab1:
    st.subheader("📋 Project Update")
    # THE FIX: Added on_change callback to trigger autofill immediately
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_lookup", on_change=sync_job_data)
    
    last_data = st.session_state.get('last_entry_data', {})

    with st.form("main_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        try: c_idx = customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0
        except: c_idx = 0

        f_cust = c1.selectbox("Customer", [""] + customers, index=c_idx)
        f_eq = c2.text_input("Equipment", value=last_data.get('equipment', ""))
        
        c3, c4, c5 = st.columns(3)
        f_po_n = c3.text_input("PO Number", value=last_data.get('po_no', ""))
        def safe_date(field):
            val = last_data.get(field)
            try: return datetime.strptime(val, "%Y-%m-%d") if val else datetime.now()
            except: return datetime.now()
        f_po_d = c4.date_input("PO Date", value=safe_date('po_date'))
        f_eng = c5.text_input("Engineer", value=last_data.get('engineer', ""))

        st.divider(); m_responses = {}
        opts = ["Pending", "NA", "In-Progress", "Submitted", "Approved", "Ordered", "Received", "Hold", "Completed"]
        
        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"; col1, col2, col3 = st.columns([1.5, 1, 2])
            prev_stat = last_data.get(skey, "Pending")
            def_idx = opts.index(prev_stat) if prev_stat in opts else 0
            
            m_responses[skey] = col1.selectbox(label, opts, index=def_idx, key=f"s_{skey}")
            m_responses[pk] = col2.slider("Prog %", 0, 100, value=int(last_data.get(pk, 0)), key=f"p_{skey}")
            m_responses[nkey] = col3.text_input("Remarks", value=last_data.get(nkey, "") or "", key=f"n_{skey}")

        f_progress = st.slider("📈 Overall Completion %", 0, 100, value=int(last_data.get('overall_progress', 0)))
        uploaded_photos = st.file_uploader("📸 Upload Photos (Max 4)", accept_multiple_files=True, type=['jpg','png'])

        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_job: st.error("Please select a Job Code")
            else:
                payload = {
                    "customer": f_cust, "job_code": f_job, "equipment": f_eq, "po_no": f_po_n, 
                    "po_date": str(f_po_d), "engineer": f_eng, "overall_progress": f_progress, **m_responses
                }
                res = conn.table("progress_logs").insert(payload).execute()
                if res.data and uploaded_photos:
                    log_id = res.data[0]['id']
                    for idx, photo in enumerate(uploaded_photos[:4]):
                        img = Image.open(photo); img.thumbnail((400, 400)); buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=50)
                        conn.client.storage.from_("progress-photos").upload(f"{log_id}_{idx}.jpg", buf.getvalue())
                st.success("✅ Saved!"); st.cache_data.clear(); st.rerun()

# Archive & Masters remain identical to your working old script
# (Logic for Tab 2 and Tab 3 follows here...)
