import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime
from fpdf import FPDF
import requests
from io import BytesIO
from PIL import Image
import tempfile
import os

# --- 1. CONNECTION (Removed st.set_page_config to avoid Navigation Error) ---
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

# --- PDF ENGINE (WITH PROGRESS BARS) ---
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
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        if logo_path: pdf.image(logo_path, x=12, y=5, h=15)
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 5); pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 10); pdf.set_xy(70, 14); pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 1, "L")
        pdf.ln(2)
        
        # Grid Fields
        pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1] if i+1 < len(HEADER_FIELDS) else None
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,''))}", 1, 0, 'L')
            if f2:
                pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
                pdf.cell(65, 7, f" {str(log.get(f2,''))}", 1, 1, 'L')
            else: pdf.ln(7)

        # --- VISUAL OVERALL PROGRESS BAR ---
        pdf.ln(5)
        ov_p = int(log.get('overall_progress', 0))
        pdf.set_font("Arial", "B", 10)
        pdf.cell(50, 8, f"Overall Completion: {ov_p}%", 0, 0, 'L')
        pdf.set_fill_color(230, 230, 230); pdf.rect(60, pdf.get_y() + 2, 130, 4, 'F')
        if ov_p > 0:
            pdf.set_fill_color(0, 82, 164); pdf.rect(60, pdf.get_y() + 2, (ov_p / 100) * 130, 4, 'F')
        pdf.ln(10)

        # Milestone Table Header
        pdf.set_font("Arial", "B", 9); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 8, " Milestone Item", 1, 0, 'L', True); pdf.cell(30, 8, " Status", 1, 0, 'C', True)
        pdf.cell(30, 8, " Progress", 1, 0, 'C', True); pdf.cell(80, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            pk = f"{s_key}_prog"
            m_p = int(log.get(pk, 0))
            pdf.cell(50, 10, f" {label}", 1)
            pdf.cell(30, 10, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            
            # Mini Bar logic
            cx, cy = pdf.get_x(), pdf.get_y()
            pdf.cell(30, 10, "", 1, 0)
            pdf.set_fill_color(240, 240, 240); pdf.rect(cx + 3, cy + 4, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76); pdf.rect(cx + 3, cy + 4, (m_p / 100) * 24, 2, 'F')
            pdf.set_xy(cx + 30, cy)
            pdf.cell(80, 10, f" {str(log.get(n_key,'-'))}", 1, 1)

    if logo_path: os.unlink(logo_path)
    return bytes(pdf.output())

# --- DATA FETCHING ---
@st.cache_data(ttl=600)
def get_master_data():
    try:
        c_res = conn.table("customer_master").select("name").execute()
        j_res = conn.table("job_master").select("job_code").execute()
        return sorted([d['name'] for d in c_res.data]), sorted([d['job_code'] for d in j_res.data])
    except: return [], []

customers, jobs = get_master_data()

# --- APP TABS ---
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

with tab1:
    st.subheader("📋 Select Project")
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_lookup")
    last_data = {}
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res and res.data:
            last_data = res.data[0]
            st.toast(f"Autofilled from Job: {f_job}", icon="🔄")

    with st.form("main_entry_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        f_cust = c1.selectbox("Customer", [""] + customers, index=customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0)
        c2.text_input("Selected Job", value=f_job, disabled=True)
        f_eq = c3.text_input("Equipment Name", value=last_data.get('equipment', ""))
        
        c4, c5, c6 = st.columns(3)
        f_po_n = c4.text_input("PO Number", value=last_data.get('po_no', ""))
        def safe_date(field):
            val = last_data.get(field)
            try: return datetime.strptime(val, "%Y-%m-%d") if val else datetime.now()
            except: return datetime.now()

        f_po_d = c5.date_input("PO Date", value=safe_date('po_date'))
        f_eng = c6.text_input("Responsible Engineer", value=last_data.get('engineer', ""))
        
        c7, c8 = st.columns(2)
        f_p_del = c7.date_input("PO Delivery Date", value=safe_date('po_delivery_date'))
        f_r_del = c8.date_input("Revised Dispatch Date", value=safe_date('exp_dispatch_date'))

        st.divider()
        st.subheader("📊 Milestone Tracking")
        m_responses = {}
        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"
            col_stat, col_prog, col_note = st.columns([1.5, 1, 2])
            opts = ["Pending", "NA", "In-Progress", "Submitted", "Approved", "Ordered", "Received", "Hold", "Completed", "Planning", "Scheduled"]
            prev_status = last_data.get(skey, "Pending")
            default_idx = opts.index(prev_status) if prev_status in opts else 0
            
            m_responses[skey] = col_stat.selectbox(label, opts, index=default_idx, key=f"{f_job}_{skey}")
            m_responses[pk] = col_prog.slider("Prog %", 0, 100, value=int(last_data.get(pk, 0)), key=f"{f_job}_{pk}")
            m_responses[nkey] = col_note.text_input(f"Remarks for {label}", value=last_data.get(nkey, ""), key=f"{f_job}_{nkey}")

        st.divider()
        f_progress = st.slider("📈 Overall Completion %", 0, 100, value=int(last_data.get('overall_progress') or 0))
        cam_photo = st.camera_input("📸 Take Progress Photo")

        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job: st.error("Select Job and Customer!")
            else:
                payload = {"customer": f_cust, "job_code": f_job, "equipment": f_eq, "po_no": f_po_n, "po_date": str(f_po_d), "engineer": f_eng, "po_delivery_date": str(f_p_del), "exp_dispatch_date": str(f_r_del), "overall_progress": f_progress, **m_responses}
                res = conn.table("progress_logs").insert(payload).execute()
                if cam_photo and res.data:
                    conn.client.storage.from_("progress-photos").upload(f"{res.data[0]['id']}.jpg", cam_photo.getvalue())
                st.success("✅ Saved!"); st.cache_data.clear(); st.rerun()

with tab2:
    st.subheader("📂 Report Archive")
    res = conn.table("progress_logs").select("*").order("id", desc=True).execute()
    data = res.data if res else []
    if data:
        st.download_button("📥 Download PDF", data=generate_pdf(data), file_name="BG_Report.pdf", mime="application/pdf")
        for log in data:
            with st.expander(f"📦 Job: {log.get('job_code')} | {log.get('customer')}"):
                ov_p = int(log.get('overall_progress') or 0)
                st.progress(ov_p / 100); st.write(f"**Overall: {ov_p}%**")
                for label, skey, nkey in MILESTONE_MAP:
                    pk = f"{skey}_prog"
                    m_prog = int(log.get(pk, 0))
                    c1, c2, c3 = st.columns([1.5, 1, 1.5])
                    c1.write(f"**{label}:** {log.get(skey)}")
                    with c2: st.progress(m_prog / 100); st.caption(f"{m_prog}%")
                    c3.write(f"_{log.get(nkey, '-')}_")

with tab3:
    st.header("🛠️ Master Data")
    c1, c2 = st.columns(2)
    with c1:
        nc = st.text_input("New Customer")
        if st.button("Add Customer"): conn.table("customer_master").insert({"name": nc}).execute(); st.rerun()
    with c2:
        nj = st.text_input("New Job Code")
        if st.button("Add Job"): conn.table("job_master").insert({"job_code": nj}).execute(); st.rerun()
