import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime
from fpdf import FPDF
import requests
from io import BytesIO
from PIL import Image
import tempfile
import os

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")

# Set TTL globally to keep data fresh
conn = st.connection("supabase", type=SupabaseConnection, ttl=60)

# 2. THE MASTER MAPPING
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
@st.cache_data(ttl=600)
def get_master_data():
    try:
        c_res = conn.table("customer_master").select("name").execute()
        cust_list = sorted([d['name'] for d in c_res.data]) if c_res and c_res.data else []
 
        j_res = conn.table("job_master").select("job_code").execute()
        job_list = sorted([d['job_code'] for d in j_res.data]) if j_res and j_res.data else []
 
        return cust_list, job_list
    except Exception:
        return [], []

customers, jobs = get_master_data()

# --- PDF ENGINE ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
 
    # Handle Logo via Temp File to bypass FPDF AttributeError
    logo_path = None
    try:
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_logo:
                tmp_logo.write(logo_data)
                logo_path = tmp_logo.name
    except:
        pass

    for log in logs:
        pdf.add_page()
 
        # 1. Blue Header Strip
        pdf.set_fill_color(0, 51, 102)
        pdf.rect(0, 0, 210, 25, 'F')
 
        if logo_path:
            pdf.image(logo_path, x=12, y=5, h=15)

        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 5)
        pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
 
        pdf.set_font("Arial", "I", 10)
        pdf.set_xy(70, 14)
        pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        pdf.set_text_color(0, 0, 0)

        # 2. Job Header
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 1, "L")
        pdf.ln(2)
 
        # 3. Field Grid
        pdf.set_font("Arial", "B", 8)
        pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1 = HEADER_FIELDS[i]
            f2 = HEADER_FIELDS[i+1] if i+1 < len(HEADER_FIELDS) else None
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,''))}", 1, 0, 'L')
            if f2:
                pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
                pdf.cell(65, 7, f" {str(log.get(f2,''))}", 1, 1, 'L')
            else:
                pdf.ln(7)

        pdf.ln(5)

        # 4. Milestone Table
        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(60, 8, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(35, 8, " Status", 1, 0, 'C', True)
        pdf.cell(95, 8, " Remarks", 1, 1, 'L', True)
 
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            status = str(log.get(s_key, 'Pending'))
            if status in ["Completed", "Approved", "Submitted"]:
                pdf.set_fill_color(144, 238, 144)
            elif status in ["In-Progress", "Hold", "Ordered", "Received", "Planning", "Scheduled"]:
                pdf.set_fill_color(255, 255, 204)
            else:
                pdf.set_fill_color(255, 255, 255)
 
            pdf.cell(60, 7, f" {label}", 1)
            pdf.cell(35, 7, f" {status}", 1, 0, 'C', True)
            pdf.cell(95, 7, f" {str(log.get(n_key,'-'))}", 1, 1)

        # 5. Progress Photo via Temp File
        try:
            img_url = conn.client.storage.from_("progress-photos").get_public_url(f"{log['id']}.jpg")
            img_res = requests.get(img_url, timeout=5)
            if img_res.status_code == 200:
                img = Image.open(BytesIO(img_res.content)).convert('RGB')
                img.thumbnail((300, 300))
 
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                    img.save(tmp_img.name, format="JPEG", quality=75)
                    pdf.image(tmp_img.name, x=75, y=pdf.get_y()+10, w=60)
                    tmp_img_name = tmp_img.name
                os.unlink(tmp_img_name) # Clean up photo temp file
        except:
            pass

    if logo_path:
        os.unlink(logo_path) # Clean up logo temp file
 
    return pdf.output(dest='S').encode('latin-1', 'replace')

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
        st.subheader("📋 Project Details")
        c1, c2, c3 = st.columns(3)
 
        f_cust = c1.selectbox("Customer", [""] + customers,
                             index=customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0)
        c2.text_input("Selected Job", value=f_job, disabled=True)
        f_eq = c3.text_input("Equipment Name", value=last_data.get('equipment', ""))
 
        c4, c5, c6 = st.columns(3)
        f_po_n = c4.text_input("PO Number", value=last_data.get('po_no', ""))
 
        def safe_date(field):
            val = last_data.get(field)
            try:
                return datetime.strptime(val, "%Y-%m-%d") if val else datetime.now()
            except:
                return datetime.now()

        f_po_d = c5.date_input("PO Date", value=safe_date('po_date'))
        f_eng = c6.text_input("Responsible Engineer", value=last_data.get('engineer', ""))
 
        c7, c8 = st.columns(2)
        f_p_del = c7.date_input("PO Delivery Date", value=safe_date('po_delivery_date'))
        f_r_del = c8.date_input("Revised Dispatch Date", value=safe_date('exp_dispatch_date'))

        st.divider()
        st.subheader("📊 Milestone Tracking")
        m_responses = {}
 
        for label, skey, nkey in MILESTONE_MAP:
            col_stat, col_note = st.columns([1, 2])
            opts = ["Pending", "NA", "In-Progress", "Submitted", "Approved", "Ordered", "Received", "Hold", "Completed", "Planning", "Scheduled"]
            prev_status = last_data.get(skey, "Pending")
            default_idx = opts.index(prev_status) if prev_status in opts else 0
 
            m_responses[skey] = col_stat.selectbox(label, opts, index=default_idx, key=f"{f_job}_{skey}")
            m_responses[nkey] = col_note.text_input(f"Remarks for {label}", value=last_data.get(nkey, ""), key=f"{f_job}_{nkey}")

        st.divider()
        st.subheader("📈 Overall Progress")
        f_progress = st.slider("Completion %", 0, 100, value=int(last_data.get('overall_progress') or 0))

        st.divider()
        st.subheader("📸 Progress Capture")
        cam_photo = st.camera_input("Take Progress Photo")

        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job:
                st.error("Select a Job Code and Customer first!")
            else:
                try:
                    entry_payload = {
                        "customer": f_cust, "job_code": f_job, "equipment": f_eq,
                        "po_no": f_po_n, "po_date": str(f_po_d), "engineer": f_eng,
                        "po_delivery_date": str(f_p_del), "exp_dispatch_date": str(f_r_del),
                        "overall_progress": f_progress,
                        **m_responses
                    }
                    res = conn.table("progress_logs").insert(entry_payload).execute()
                    if cam_photo and res and res.data:
                        file_path = f"{res.data[0]['id']}.jpg"
                        conn.client.storage.from_("progress-photos").upload(file_path, cam_photo.getvalue())
                    st.success("✅ Update Saved!")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

with tab2:
    st.subheader("📂 Report Archive")
    filter_c1, filter_c2, filter_c3 = st.columns(3)
    cust_list = ["All Customers"] + customers
    selected_cust = filter_c1.selectbox("🔍 Filter by Customer", cust_list, key="arch_cust_sel")
    report_type = filter_c2.selectbox("📅 Report Duration", ["All Time", "Current Week", "Current Month", "Custom Range"], key="arch_dur_sel")
 
    start_date, end_date = None, None
    if report_type == "Custom Range":
        c_date = filter_c3.date_input("Select Range", [datetime.now().date(), datetime.now().date()])
        if isinstance(c_date, list) and len(c_date) == 2:
            start_date, end_date = c_date

    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if selected_cust != "All Customers":
        query = query.eq("customer", selected_cust)
 
    res = query.execute()
    data = res.data if res else []

    filtered_data = []
    today = datetime.now().date()
 
    if data:
        for log in data:
            try:
                raw_date = log.get('created_at') or log.get('po_date')
                if not raw_date: continue
                log_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
                if report_type == "Current Week":
                    if log_date.isocalendar()[1] == today.isocalendar()[1] and log_date.year == today.year: filtered_data.append(log)
                elif report_type == "Current Month":
                    if log_date.month == today.month and log_date.year == today.year: filtered_data.append(log)
                elif report_type == "Custom Range" and start_date and end_date:
                    if start_date <= log_date <= end_date: filtered_data.append(log)
                elif report_type == "All Time": filtered_data.append(log)
            except: continue
 
        if filtered_data:
            with st.spinner("🛠️ Generating Report..."):
                pdf_data = generate_pdf(filtered_data)
                st.download_button(label="📥 Download Filtered PDF Report", data=pdf_data, file_name=f"BG_Report.pdf", mime="application/pdf", use_container_width=True)
 
            for log in filtered_data:
                with st.expander(f"📦 Job: {log.get('job_code','N/A')} | {log.get('customer','Unknown')}"):
                    p_val = int(log.get('overall_progress') or 0)
                    st.write(f"**Overall Progress: {p_val}%**")
                    st.progress(p_val / 100)
                    st.write(f"### Status Details for Job {log.get('job_code')}")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Engineer", log.get('engineer', 'N/A'))
                    c2.metric("PO No", log.get('po_no', 'N/A'))
                    c3.metric("Dispatch", log.get('exp_dispatch_date', 'N/A'))
                    st.markdown("---")
                    for label, skey, nkey in MILESTONE_MAP:
                        cs, cr = st.columns([1, 2])
                        cs.write(f"**{label}:** {log.get(skey, 'Pending')}")
                        cr.write(f"_{log.get(nkey, '-')}_")
 
                    photo_name = f"{log.get('id')}.jpg"
                    photo_url = conn.client.storage.from_("progress-photos").get_public_url(photo_name)
                    st.image(photo_url, caption=f"Job: {log.get('job_code')}", width=160)
        else:
            st.warning("No records found.")

with tab3:
    st.header("🛠️ Master Data Management")
    col_cust, col_job = st.columns(2)
    with col_cust:
        new_cust = st.text_input("New Customer Name", key="add_cust_master")
        if st.button("➕ Add Customer"):
            if new_cust:
                conn.table("customer_master").insert({"name": new_cust}).execute()
                st.cache_data.clear()
                st.rerun()
    with col_job:
        new_job = st.text_input("New Job Code", key="add_job_master")
        if st.button("➕ Add Job Code"):
            if new_job:
                conn.table("job_master").insert({"job_code": new_job}).execute()
                st.cache_data.clear()
                st.rerun()
