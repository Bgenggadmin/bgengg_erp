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
        pdf.set_xy(70, 7); pdf.cell(130, 10, "B&G PROJECT REPORT", 0, 1, "L")
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 1, "L")
        
        # Grid Fields (Master logic restored)
        pdf.ln(2); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1] if i+1 < len(HEADER_FIELDS) else None
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,''))}", 1, 0, 'L')
            if f2:
                pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
                pdf.cell(65, 7, f" {str(log.get(f2,''))}", 1, 1, 'L')
            else: pdf.ln(7)

        # Overall Progress Bar
        pdf.ln(5); ov_p = int(log.get('overall_progress', 0))
        pdf.set_font("Arial", "B", 10); pdf.cell(50, 8, f"Overall Progress: {ov_p}%")
        pdf.set_fill_color(230, 230, 230); pdf.rect(65, pdf.get_y() + 2, 120, 4, 'F')
        if ov_p > 0:
            pdf.set_fill_color(0, 102, 204); pdf.rect(65, pdf.get_y() + 2, (ov_p/100)*120, 4, 'F')
        
        # Milestone Table
        pdf.ln(10); pdf.set_font("Arial", "B", 9); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 8, " Milestone Item", 1, 0, 'L', True); pdf.cell(30, 8, " Status", 1, 0, 'C', True)
        pdf.cell(30, 8, " Progress", 1, 0, 'C', True); pdf.cell(80, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            pk = f"{s_key}_prog"
            m_p = int(log.get(pk, 0))
            pdf.cell(50, 8, f" {label}", 1); pdf.cell(30, 8, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            cx, cy = pdf.get_x(), pdf.get_y()
            pdf.cell(30, 8, "", 1, 0); pdf.set_fill_color(240, 240, 240); pdf.rect(cx+3, cy+3, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76); pdf.rect(cx+3, cy+3, (m_p/100)*24, 2, 'F')
            pdf.set_xy(cx+30, cy); pdf.cell(80, 8, f" {str(log.get(n_key,'-'))}", 1, 1)

        # --- PHOTO ROW IN PDF (PASSPORT SIZE: 35x45mm) ---
        pdf.ln(10); pdf.set_font("Arial", "B", 10); pdf.cell(0, 10, "Progress Photos:", 0, 1)
        x_start, y_pos = 10, pdf.get_y()
        for i in range(4):
            try:
                photo_name = f"{log['id']}_{i}.jpg"
                img_data = conn.client.storage.from_("progress-photos").download(photo_name)
                if img_data:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(img_data); pdf.image(tmp.name, x=x_start + (i * 48), y=y_pos, w=45, h=35)
                        os.unlink(tmp.name)
            except: pass

    if logo_path:
        try: os.unlink(logo_path)
        except: pass
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- DATA FETCH ---
customers, jobs = [], []
try:
    c_res = conn.table("customer_master").select("name").execute()
    j_res = conn.table("job_master").select("job_code").execute()
    customers, jobs = sorted([d['name'] for d in c_res.data]), sorted([d['job_code'] for d in j_res.data])
except: pass

tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

# --- TAB 1: NEW ENTRY (WITH PASSPORT COMPRESSION) ---
with tab1:
    st.subheader("📋 Project Update")
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_lookup")
    last_data = {}
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res and res.data: last_data = res.data[0]; st.toast("🔄 Autofilled")

    with st.form("main_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_cust = c1.selectbox("Customer", [""] + customers)
        f_eq = c2.text_input("Equipment", value=last_data.get('equipment', ""))
        st.divider()
        m_responses = {}
        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"
            col1, col2, col3 = st.columns([1.5, 1, 2])
            m_responses[skey] = col1.selectbox(label, ["Pending", "NA", "In-Progress", "Completed", "Hold", "Approved", "Scheduled"], key=f"s_{skey}")
            m_responses[pk] = col2.slider("Prog %", 0, 100, value=int(last_data.get(pk, 0)), key=f"p_{skey}")
            m_responses[nkey] = col3.text_input("Remarks", value=last_data.get(nkey, ""), key=f"n_{skey}")

        f_progress = st.slider("📈 Overall Completion %", 0, 100, value=int(last_data.get('overall_progress', 0)))
        uploaded_photos = st.file_uploader("Upload Photos (0-4)", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

        if st.form_submit_button("🚀 SUBMIT UPDATE"):
            payload = {"customer": f_cust, "job_code": f_job, "equipment": f_eq, "overall_progress": f_progress, **m_responses}
            res = conn.table("progress_logs").insert(payload).execute()
            if res.data and uploaded_photos:
                log_id = res.data[0]['id']
                for idx, photo in enumerate(uploaded_photos[:4]):
                    img = Image.open(photo); img.thumbnail((400, 400)) # PASSPORT SCALE
                    buf = io.BytesIO(); img.save(buf, format="JPEG", quality=50) # 50KB LIMIT COMPRESSION
                    conn.client.storage.from_("progress-photos").upload(f"{log_id}_{idx}.jpg", buf.getvalue())
            st.success("✅ Saved!"); st.rerun()

# --- TAB 2: ARCHIVE (RESTORED FILTERS & MILESTONE DETAILS) ---
with tab2:
    st.subheader("📂 Report Archive")
    af1, af2, af3 = st.columns(3)
    sel_c = af1.selectbox("Filter Customer", ["All"] + customers, key="arch_cust")
    report_type = af2.selectbox("📅 Report Duration", ["All Time", "Current Week", "Current Month", "Custom Range"], key="arch_dur")
    
    start_date, end_date = None, None
    if report_type == "Custom Range":
        c_date = af3.date_input("Select Range", [datetime.now().date(), datetime.now().date()])
        if isinstance(c_date, list) and len(c_date) == 2: start_date, end_date = c_date

    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if sel_c != "All": query = query.eq("customer", sel_c)
    res = query.execute()
    data = res.data if res else []
    
    # Filter by Date logic restored
    today = datetime.now().date()
    filtered_data = []
    for log in data:
        try:
            raw_date = log.get('created_at') or log.get('po_date')
            log_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
            if report_type == "Current Week" and log_date.isocalendar()[1] != today.isocalendar()[1]: continue
            if report_type == "Current Month" and log_date.month != today.month: continue
            if report_type == "Custom Range" and not (start_date <= log_date <= end_date): continue
            filtered_data.append(log)
        except: continue

    if filtered_data:
        st.download_button("📥 Download Combined PDF", data=generate_pdf(filtered_data), file_name="BG_Archive.pdf", mime="application/pdf")
        for log in filtered_data:
            with st.expander(f"📦 {log['job_code']} - {log['customer']}"):
                ov_p = int(log.get('overall_progress', 0))
                st.progress(ov_p/100); st.write(f"**Overall Progress: {ov_p}%**")
                
                # Restore Milestone Progress Preview
                for label, skey, nkey in MILESTONE_MAP:
                    pk = f"{skey}_prog"
                    mp = int(log.get(pk, 0))
                    c1, c2, c3 = st.columns([1.5, 1, 1.5])
                    c1.write(f"**{label}**"); c1.caption(f"Status: {log.get(skey)}")
                    with c2: st.progress(mp/100); st.caption(f"{mp}%")
                    c3.write(f"_{log.get(nkey, '-')}_")

                # Photo Row Preview
                cols = st.columns(4)
                for i in range(4):
                    try:
                        p_url = conn.client.storage.from_("progress-photos").get_public_url(f"{log['id']}_{i}.jpg")
                        cols[i].image(p_url, use_container_width=True)
                    except: pass

# --- TAB 3: MASTERS (RESTORED) ---
with tab3:
    st.subheader("🛠️ Master Management")
    mc1, mc2 = st.columns(2)
    with mc1:
        with st.form("add_cust"):
            nc = st.text_input("New Customer")
            if st.form_submit_button("Add Customer") and nc:
                conn.table("customer_master").insert({"name": nc}).execute(); st.cache_data.clear(); st.rerun()
    with mc2:
        with st.form("add_job"):
            nj = st.text_input("New Job Code")
            if st.form_submit_button("Add Job Code") and nj:
                conn.table("job_master").insert({"job_code": nj}).execute(); st.cache_data.clear(); st.rerun()
