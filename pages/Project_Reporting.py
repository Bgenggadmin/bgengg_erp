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
    pdf.set_auto_page_break(auto=True, margin=10)
    for log in logs:
        pdf.add_page()
        
        # 1. Header Blue Strip
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 20, 'F')
        try:
            logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
            if logo_data: pdf.image(BytesIO(logo_data), x=10, y=3, h=14) 
        except: pass

        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 14); pdf.set_xy(60, 3); pdf.cell(140, 8, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 9); pdf.set_xy(60, 10); pdf.cell(140, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        # 2. Manual Progress Bar in PDF
        manual_p = log.get("overall_progress", 0)
        pdf.set_xy(10, 25)
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10)
        pdf.cell(40, 8, f"JOB: {log.get('job_code','')}")
        
        # Draw Progress Bar Graphic
        pdf.set_draw_color(0, 51, 102); pdf.rect(130, 26, 60, 5) # Outline
        pdf.set_fill_color(0, 200, 0); pdf.rect(130, 26, (manual_p/100)*60, 5, 'F') # Fill
        pdf.set_xy(130, 21); pdf.set_font("Arial", "B", 8); pdf.cell(60, 5, f"Completion: {manual_p}%", 0, 0, 'R')

        # 3. Header Info Grid
        pdf.set_xy(10, 35); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            pdf.cell(25, 6, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(70, 6, f" {str(log.get(f1,''))}", 1, 0, 'L')
            pdf.cell(25, 6, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(70, 6, f" {str(log.get(f2,''))}", 1, 1, 'L')

        # 4. Milestone Table
        pdf.ln(3); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(55, 7, " Milestone Item", 1, 0, 'L', True); pdf.cell(30, 7, " Status", 1, 0, 'C', True); pdf.cell(105, 7, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 7)
        for label, s_key, n_key in MILESTONE_MAP:
            status = str(log.get(s_key, 'Pending'))
            pdf.cell(55, 6, f" {label}", 1); pdf.cell(30, 6, f" {status}", 1, 0, 'C'); pdf.cell(105, 6, f" {str(log.get(n_key,'-'))}", 1, 1)

        # 5. Photo - Scaled to fit on same page
        try:
            photo_data = conn.client.storage.from_("progress-photos").download(f"{log['id']}.jpg")
            if photo_data:
                pdf.ln(5)
                pdf.set_font("Arial", "B", 9); pdf.cell(0, 6, "Progress Photo:", 0, 1)
                pdf.image(BytesIO(photo_data), x=10, w=70) # Reduced width to prevent page break
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
            st.info(f"🔄 Latest Job Info Loaded.")

    with st.form("main_entry_form", clear_on_submit=True):
        # MANUAL PROGRESS SLIDER
        st.subheader("📊 Overall Project Completion")
        f_manual_p = st.slider("Set % Progress Manually", 0, 100, value=int(last_data.get('overall_progress', 0)))
        
        st.divider()
        st.subheader("📋 Project Details")
        c1, c2, c3 = st.columns(3)
        default_cust_idx = customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0
        f_cust = c1.selectbox("Customer", [""] + customers, index=default_cust_idx)
        c2.text_input("Selected Job", value=f_job, disabled=True)
        f_eq = c3.text_input("Equipment Name", value=last_data.get('equipment', ""))
        
        # Dates and Header info
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
        m_responses = {}
        for label, skey, nkey in MILESTONE_MAP:
            col_stat, col_note = st.columns([1, 2])
            # Options setup
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

        st.divider(); cam_photo = st.camera_input("📸 Take Progress Photo")
        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job: st.error("Select Job & Customer!")
            else:
                try:
                    entry_payload = {
                        "customer": f_cust, "job_code": f_job, "equipment": f_eq, "po_no": f_po_n, 
                        "po_date": str(f_po_d), "engineer": f_eng, "po_delivery_date": str(f_p_del), 
                        "exp_dispatch_date": str(f_r_del), "overall_progress": f_manual_p, **m_responses
                    }
                    res = conn.table("progress_logs").insert(entry_payload).execute()
                    if cam_photo and res.data:
                        conn.client.storage.from_("progress-photos").upload(f"{res.data[0]['id']}.jpg", cam_photo.getvalue())
                    st.success("✅ Update Saved!"); st.rerun()
                except Exception as e: st.error(f"Error: {e}")

with tab2:
    # RESTORED ARCHIVE
    st.subheader("📂 Report Archive")
    c1, c2 = st.columns(2)
    f_cust_search = c1.selectbox("🔍 Customer", ["All"] + customers)
    f_time = c2.selectbox("📅 Duration", ["All Time", "Last 7 Days", "Last 30 Days"])

    query = conn.table("progress_logs").select("*").order("created_at", desc=True)
    if f_cust_search != "All": query = query.eq("customer", f_cust_search)
    if f_time == "Last 7 Days": query = query.gte("created_at", (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"))
    elif f_time == "Last 30 Days": query = query.gte("created_at", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))

    archive_data = query.execute().data
    if archive_data:
        pdf_all = generate_pdf(archive_data)
        st.download_button("📥 Download Filtered PDF Report", pdf_all, "Filtered_Report.pdf", "application/pdf", use_container_width=True)
        for row in archive_data:
            with st.expander(f"📦 {row['job_code']} | Progress: {row.get('overall_progress',0)}%"):
                st.write(f"**Customer:** {row['customer']} | **Engineer:** {row['engineer']}")
                pdf_row = generate_pdf([row])
                st.download_button("📩 Download PDF", pdf_row, f"{row['job_code']}.pdf", key=f"dl_{row['id']}")

with tab3:
    st.header("🛠️ Masters")
    col_cust, col_job = st.columns(2)
    with col_cust:
        new_cust = st.text_input("New Customer")
        if st.button("➕ Add Customer"): 
            conn.table("customer_master").insert({"name": new_cust}).execute(); st.rerun()
    with col_job:
        new_job = st.text_input("New Job")
        if st.button("➕ Add Job"):
            conn.table("job_master").insert({"job_code": new_job}).execute(); st.rerun()
