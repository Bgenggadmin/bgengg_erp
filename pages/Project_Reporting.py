import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, timedelta
from fpdf import FPDF
from io import BytesIO

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# 2. THE MASTER MAPPING
HEADER_FIELDS = ["customer", "job_code", "equipment", "po_no", "po_date", "engineer", "po_delivery_date", "exp_dispatch_date"]

MILESTONE_WEIGHTS = {
    "draw_sub": 0.05, "draw_app": 0.05, "rm_status": 0.20, "sub_del": 0.05,
    "fab_status": 0.30, "buff_stat": 0.10, "testing": 0.10, "qc_stat": 0.10, "fat_stat": 0.05
}
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

# --- DATA FETCHING ---
customers = sorted([d['name'] for d in conn.table("customer_master").select("name").execute().data])
jobs = sorted([d['job_code'] for d in conn.table("job_master").select("job_code").execute().data])

# --- PDF ENGINE WITH PHOTO & COMPLETION ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    for log in logs:
        pdf.add_page()
        
        # Weighted Progress Calculation
        total_p = sum([STATUS_MULTIPLIER.get(log.get(m[1], "Pending"), 0) * MILESTONE_WEIGHTS.get(m[1], 0) for m in MILESTONE_MAP])
        overall_pct = int(total_p * 100)
        
        # Header Blue Strip
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        try:
            logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
            if logo_data: pdf.image(BytesIO(logo_data), x=12, y=5, h=15) 
        except: pass

        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 16); pdf.set_xy(70, 5); pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 10); pdf.set_xy(70, 14); pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        # Job Details Row + Completion Bar in PDF
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
        pdf.cell(140, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 0, "L")
        pdf.set_text_color(0, 51, 102)
        pdf.cell(50, 8, f"COMPLETION: {overall_pct}%", "B", 1, "R")
        
        # Header Info Grid
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,''))}", 1, 0, 'L')
            pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f2,''))}", 1, 1, 'L')

        # Milestone Table
        pdf.ln(5); pdf.set_font("Arial", "B", 9); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(60, 8, " Milestone Item", 1, 0, 'L', True); pdf.cell(35, 8, " Status", 1, 0, 'C', True); pdf.cell(95, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            status = str(log.get(s_key, 'Pending'))
            if status in ["Completed", "Approved", "Submitted"]: pdf.set_fill_color(144, 238, 144)
            elif status in ["In-Progress", "Hold", "Ordered", "Received", "Planning", "Scheduled"]: pdf.set_fill_color(255, 255, 204)
            else: pdf.set_fill_color(255, 255, 255)
            pdf.cell(60, 7, f" {label}", 1); pdf.cell(35, 7, f" {status}", 1, 0, 'C', True); pdf.cell(95, 7, f" {str(log.get(n_key,'-'))}", 1, 1)

        # --- PHOTO AT BOTTOM OF PDF ---
        try:
            photo_data = conn.client.storage.from_("progress-photos").download(f"{log['id']}.jpg")
            if photo_data:
                pdf.ln(10)
                pdf.set_font("Arial", "B", 10); pdf.cell(0, 10, "Progress Verification Photo:", 0, 1)
                pdf.image(BytesIO(photo_data), x=10, w=100) 
        except: pass

    raw_pdf = pdf.output()
    return bytes(raw_pdf) if isinstance(raw_pdf, (bytes, bytearray)) else raw_pdf.encode('latin-1')

# --- APP TABS ---
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

with tab1:
    st.subheader("📋 Select Project")
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_lookup")
    last_data = {}
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res.data:
            last_data = res.data[0]
            st.info(f"🔄 Showing latest data for Job: {f_job}.")

    with st.form("main_entry_form", clear_on_submit=True):
        overall_bar_space = st.empty() 
        
        st.subheader("📋 Project Details")
        c1, c2, c3 = st.columns(3)
        default_cust_idx = customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0
        f_cust = c1.selectbox("Customer", [""] + customers, index=default_cust_idx)
        c2.text_input("Selected Job", value=f_job, disabled=True)
        f_eq = c3.text_input("Equipment Name", value=last_data.get('equipment', ""))
        
        # ... Rest of Header Fields ...
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

        st.divider(); st.subheader("📊 Milestone Tracking")
        m_responses = {}; total_weighted_pct = 0
        
        for label, skey, nkey in MILESTONE_MAP:
            # --- 3 COLUMNS: STATUS | REMARKS | PROGRESS BAR ---
            col_stat, col_note, col_bar = st.columns([1.5, 2.5, 1])
            
            if label == "Drawing Submission": opts = ["Pending", "NA", "In-Progress", "Submitted"]
            elif label == "Drawing Approval": opts = ["Pending", "NA", "In-Progress", "Approved"]
            elif label == "RM Status": opts = ["Pending", "Ordered", "In-Progress", "NA", "Received", "Hold"]
            elif label == "Sub-deliveries": opts = ["Pending", "In-Progress", "NA", "Completed"]
            elif label == "Fabrication Status": opts = ["Planning", "In-Progress", "Hold", "Completed"]
            elif label == "Buffing Status": opts = ["Planning", "In-Progress", "Completed"]
            elif label == "Testing Status": opts = ["Scheduled", "NA", "In-Progress", "Completed"]
            elif label == "Dispatch Status": opts = ["Pending", "Scheduled", "In-Progress", "Completed"]
            elif label == "FAT Status": opts = ["Scheduled", "NA", "In-Progress", "Completed"]
            else: opts = ["Pending", "NA", "Scheduled", "Hold","In-Progress", "Completed"]

            prev_status = last_data.get(skey, "Pending")
            default_idx = opts.index(prev_status) if prev_status in opts else 0
            
            m_responses[skey] = col_stat.selectbox(label, opts, index=default_idx)
            m_responses[nkey] = col_note.text_input(f"Remarks for {label}", value=last_data.get(nkey, ""))
            
            # --- SHOW PROGRESS BAR AGAINST MILESTONE ---
            mult = STATUS_MULTIPLIER.get(m_responses[skey], 0)
            col_bar.write("") # Padding
            col_bar.progress(mult)
            total_weighted_pct += (mult * MILESTONE_WEIGHTS[skey])

        # Top Completion Banner
        final_pct = int(total_weighted_pct * 100)
        overall_bar_space.markdown(f"### 🎯 Overall Completion: {final_pct}%")
        overall_bar_space.progress(total_weighted_pct)

        st.divider(); cam_photo = st.camera_input("📸 Take Progress Photo")
        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job: st.error("Select a Job Code and Customer first!")
            else:
                try:
                    entry_payload = {"customer": f_cust, "job_code": f_job, "equipment": f_eq, "po_no": f_po_n, "po_date": str(f_po_d), "engineer": f_eng, "po_delivery_date": str(f_p_del), "exp_dispatch_date": str(f_r_del), **m_responses}
                    res = conn.table("progress_logs").insert(entry_payload).execute()
                    if cam_photo and res.data:
                        conn.client.storage.from_("progress-photos").upload(f"{res.data[0]['id']}.jpg", cam_photo.getvalue())
                    st.success("✅ Update Saved Successfully!"); st.rerun()
                except Exception as e: st.error(f"Error: {e}")

with tab2:
    # (Restored Archive logic from previous turn with Filter and Photo check)
    st.subheader("📂 Report Archive")
    c1, c2 = st.columns(2)
    f_cust_search = c1.selectbox("🔍 Filter by Customer", ["All"] + customers)
    f_time = c2.selectbox("📅 Report Duration", ["All Time", "Last 7 Days", "Last 30 Days"])

    query = conn.table("progress_logs").select("*").order("created_at", desc=True)
    if f_cust_search != "All": query = query.eq("customer", f_cust_search)
    if f_time == "Last 7 Days": query = query.gte("created_at", (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"))
    elif f_time == "Last 30 Days": query = query.gte("created_at", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))

    archive_data = query.execute().data
    if archive_data:
        pdf_all = generate_pdf(archive_data)
        st.download_button("📥 Download Filtered PDF Report", pdf_all, "Filtered_Report.pdf", "application/pdf", use_container_width=True)
        for row in archive_data:
            with st.expander(f"📦 Job: {row['job_code']} | {row['customer']}"):
                st.subheader(f"Status Details for Job {row['job_code']}")
                col_a, col_b, col_c = st.columns(3)
                col_a.write(f"**Engineer**\n### {row['engineer']}")
                col_b.write(f"**PO No**\n### {row['po_no']}")
                col_c.write(f"**Dispatch**\n### {row['exp_dispatch_date']}")
                st.divider()
                for label, skey, nkey in MILESTONE_MAP:
                    ca, cb = st.columns([1, 2])
                    ca.write(f"**{label}:** {row.get(skey)}")
                    cb.write(f"{row.get(nkey) if row.get(nkey) else '-'}")
                pdf_row = generate_pdf([row])
                st.download_button("📩 Download This Update PDF", pdf_row, f"{row['job_code']}_Update.pdf", key=f"dl_{row['id']}")

with tab3:
    st.header("🛠️ Master Data Management")
    col_cust, col_job = st.columns(2)
    with col_cust:
        st.subheader("👥 Customers")
        new_cust = st.text_input("New Customer Name", key="add_cust_input")
        if st.button("➕ Add Customer"):
            if new_cust: conn.table("customer_master").insert({"name": new_cust}).execute(); st.rerun()
    with col_job:
        st.subheader("🔢 Job Codes")
        new_job = st.text_input("New Job Code", key="add_job_input")
        if st.button("➕ Add Job Code"):
            if new_job: conn.table("job_master").insert({"job_code": new_job}).execute(); st.rerun()
