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

# Aligned with Anchor Portal (job_master) columns
HEADER_FIELDS = [
    "customer", "job_code", "equipment", "po_no", 
    "po_date", "engineer", "po_delivery_date", "revised_delivery_date"
]

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

        # Header Setup
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        if logo_path: pdf.image(logo_path, x=12, y=5, h=15)
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 5); pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 10); pdf.set_xy(70, 14); pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','N/A')} | ID: {log.get('id','N/A')}", "B", 0, "L")
        pdf.cell(0, 8, f"Report Date: {report_date} ", 0, 1, "R")
        
        pdf.ln(2); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        
        # Header Data Table
        for i in range(0, len(HEADER_FIELDS), 2):
            f1 = HEADER_FIELDS[i]
            f2 = HEADER_FIELDS[i+1] if i+1 < len(HEADER_FIELDS) else None
            
            pdf.cell(35, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            val1 = log.get(f1)
            txt1 = str(val1) if val1 not in [None, "", "None"] else "-"
            pdf.cell(60, 7, f" {txt1}", 1, 0, 'L')
            
            if f2:
                pdf.cell(35, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
                val2 = log.get(f2)
                txt2 = str(val2) if val2 not in [None, "", "None"] else "-"
                pdf.cell(60, 7, f" {txt2}", 1, 1, 'L')
            else: 
                pdf.ln(7)

        # Overall Progress Bar
        pdf.ln(5); ov_p = int(log.get('overall_progress', 0) or 0)
        pdf.set_font("Arial", "B", 10); pdf.cell(50, 8, f"Overall Completion: {ov_p}%", 0, 0, 'L')
        pdf.set_fill_color(230, 230, 230); pdf.rect(60, pdf.get_y() + 2, 130, 4, 'F')
        if ov_p > 0:
            pdf.set_fill_color(0, 82, 164)
            pdf.rect(60, pdf.get_y() + 2, (min(ov_p, 100) / 100) * 130, 4, 'F')
        pdf.ln(10)

        # Milestone Table
        pdf.set_font("Arial", "B", 9); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 8, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(30, 8, " Status", 1, 0, 'C', True)
        pdf.cell(30, 8, " Progress", 1, 0, 'C', True) 
        pdf.cell(80, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            pk = f"{s_key}_prog"
            m_p = int(log.get(pk, 0) or 0)
            s_val = log.get(s_key)
            s_txt = str(s_val) if s_val not in [None, "", "None"] else "Pending"
            
            pdf.cell(50, 10, f" {label}", 1)
            pdf.cell(30, 10, f" {s_txt}", 1, 0, 'C')
            
            curr_x, curr_y = pdf.get_x(), pdf.get_y()
            pdf.cell(30, 10, "", 1, 0) 
            pdf.set_fill_color(240, 240, 240); pdf.rect(curr_x + 3, curr_y + 4, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76); pdf.rect(curr_x + 3, curr_y + 4, (min(m_p, 100) / 100) * 24, 2, 'F')
            
            pdf.set_xy(curr_x + 30, curr_y)
            n_val = log.get(n_key)
            n_txt = str(n_val) if n_val not in [None, "", "None"] else "-"
            pdf.cell(80, 10, f" {n_txt}", 1, 1)

        # Photos Section
        pdf.ln(5); pdf.set_font("Arial", "B", 10); pdf.cell(0, 10, "Progress Photos:", 0, 1, "L")
        start_y = pdf.get_y(); img_x = 10; photo_count = 0
        for i in range(4):
            try:
                img_path = f"{log.get('id')}_{i}.jpg"
                img_data = conn.client.storage.from_("progress-photos").download(img_path)
                if img_data:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                        tmp_img.write(img_data)
                        tmp_img.flush()
                        pdf.image(tmp_img.name, x=img_x, y=start_y, w=45)
                        img_x += 48; photo_count += 1
                        os.unlink(tmp_img.name)
            except: continue
        if photo_count == 0:
            pdf.set_font("Arial", "I", 8); pdf.cell(0, 5, "No photos uploaded.", 0, 1)

    if logo_path and os.path.exists(logo_path): os.unlink(logo_path)
    return bytes(pdf.output(dest='S'), encoding='latin-1')

# --- 3. DATA FETCH (ANCHOR PORTAL) ---
@st.cache_data(ttl=300)
def get_anchor_data():
    try:
        j_res = conn.table("job_master").select("job_code").execute()
        c_res = conn.table("customer_master").select("name").execute()
        return sorted([d['job_code'] for d in j_res.data]), sorted([d['name'] for d in c_res.data])
    except: return [], []

jobs, customers = get_anchor_data()

# --- 4. MAIN UI ---
tab1, tab2 = st.tabs(["📝 New Entry", "📂 Archive"])

with tab1:
    st.subheader("📋 Project Update")
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_selector")

    if f_job and st.session_state.get('last_selected_job') != f_job:
        m_query = conn.table("job_master").select("*").eq("job_code", f_job).execute()
        l_query = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        master_info = m_query.data[0] if m_query.data else {}
        latest_log = l_query.data[0] if l_query.data else {}

        # Merge Logic
        new_data = {**latest_log} 
        for f in HEADER_FIELDS:
            if f in master_info and master_info[f] not in [None, "", "None"]:
                new_data[f] = master_info[f]
        
        st.session_state.form_data = new_data
        st.session_state.last_selected_job = f_job
        st.rerun()

    if not f_job:
        st.info("Select a Job Code to load Anchor Portal data.")
        st.stop()

    current_data = st.session_state.get('form_data', {})

    def safe_date(field):
        d = current_data.get(field)
        if not d: return datetime.now()
        try: return datetime.strptime(str(d)[:10], "%Y-%m-%d")
        except: return datetime.now()

    with st.form(key=f"form_{f_job}"):
        c1, c2 = st.columns(2)
        c_val = current_data.get('customer', "")
        c_idx = customers.index(c_val) + 1 if c_val in customers else 0
        f_cust = c1.selectbox("Customer", [""] + customers, index=c_idx)
        f_eq = c2.text_input("Equipment", value=current_data.get('equipment', ""))
        
        c3, c4, c5 = st.columns(3)
        f_po_n = c3.text_input("PO Number", value=current_data.get('po_no', ""))
        f_po_d = c4.date_input("PO Date", value=safe_date('po_date'))
        f_eng = c5.text_input("Engineer", value=current_data.get('engineer', ""))
        
        c6, c7 = st.columns(2)
        f_po_del = c6.date_input("PO Del. Date", value=safe_date('po_delivery_date'))
        f_rev_del = c7.date_input("Revised Del. Date", value=safe_date('revised_delivery_date'))
        
        st.divider()
        st.subheader("📊 Milestone Tracking")
        m_responses = {}
        opts = ["Pending", "NA", "In-Progress", "Submitted", "Approved", "Ordered", "Received", "Hold", "Completed", "Planning", "Scheduled"]

        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"
            r1, r2, r3 = st.columns([1.5, 1, 2])
            cur_status = current_data.get(skey, "Pending")
            s_idx = opts.index(cur_status) if cur_status in opts else 0
            
            m_responses[skey] = r1.selectbox(label, opts, index=s_idx, key=f"s_{skey}")
            m_responses[pk] = r2.slider("Prog %", 0, 100, value=int(current_data.get(pk, 0) or 0), key=f"p_{skey}")
            m_responses[nkey] = r3.text_input("Remarks", value=current_data.get(nkey, ""), key=f"n_{skey}")

        st.divider()
        f_progress = st.slider("📈 Overall %", 0, 100, value=int(current_data.get('overall_progress', 0) or 0))
        
        if st.form_submit_button("🚀 SAVE UPDATE", use_container_width=True):
            payload = {
                "customer": f_cust, "job_code": f_job, "equipment": f_eq,
                "po_no": f_po_n, "po_date": str(f_po_d), "engineer": f_eng,
                "po_delivery_date": str(f_po_del), "revised_delivery_date": str(f_rev_del),
                "overall_progress": f_progress, **m_responses
            }
            conn.table("progress_logs").insert(payload).execute()
            st.success("✅ Saved!"); st.cache_data.clear(); st.rerun()

with tab2:
    st.subheader("📂 Report Archive")
    f1, f2, f3 = st.columns(3)
    sel_c = f1.selectbox("Filter Customer", ["All"] + customers)
    report_type = f2.selectbox("📅 Period", ["All Time", "Current Week", "Current Month", "Custom Range"])
    
    start_date, end_date = None, None
    if report_type == "Custom Range":
        dates = f3.date_input("Select Range", [datetime.now(), datetime.now()])
        if len(dates) == 2: start_date, end_date = dates[0], dates[1]
    elif report_type == "Current Week":
        start_date = (datetime.now() - timedelta(days=datetime.now().weekday())).date()
    elif report_type == "Current Month":
        start_date = datetime.now().replace(day=1).date()

    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if sel_c != "All": query = query.eq("customer", sel_c)
    
    res = query.execute()
    data = res.data if res.data else []

    # Apply date filters manually on retrieved data
    if start_date:
        filtered_data = []
        for d in data:
            try:
                d_date = datetime.strptime(d.get('created_at', "")[:10], "%Y-%m-%d").date()
                if end_date:
                    if start_date <= d_date <= end_date: filtered_data.append(d)
                else:
                    if d_date >= start_date: filtered_data.append(d)
            except: filtered_data.append(d)
        data = filtered_data

    if data:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Logs", len(data))
        m2.metric("Completed Jobs", len([d for d in data if int(d.get('overall_progress', 0) or 0) == 100]))
        m3.metric("Latest Update", data[0].get('job_code'))
        
        st.divider()
        if st.button("📥 Prepare PDF for Download", use_container_width=True):
            with st.spinner("Generating PDF..."):
                pdf_bytes = generate_pdf(data)
                st.download_button("✅ Click to Save PDF", pdf_bytes, f"BG_Report_{datetime.now().strftime('%Y%m%d')}.pdf", "application/pdf", use_container_width=True)

        for log in data:
            with st.expander(f"📦 {log.get('job_code')} | {log.get('customer')} | {log.get('created_at','')[:16]}"):
                p = int(log.get('overall_progress', 0) or 0)
                st.progress(p / 100, text=f"Completion: {p}%")
                st.write(f"**Equipment:** {log.get('equipment')} | **PO:** {log.get('po_no')}")
                st.write(f"**Remarks:** {log.get('remarks') or '-'}")
    else:
        st.info("No records found for the selected filters.")
