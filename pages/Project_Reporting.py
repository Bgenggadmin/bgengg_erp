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

# --- PDF ENGINE (FIXED FOR SINGLE PAGE) ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=5)
    for log in logs:
        pdf.add_page()
        
        # 1. Header
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 20, 'F')
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 14); pdf.set_xy(10, 5); pdf.cell(140, 8, "B&G ENGINEERING INDUSTRIES")
        
        # 2. Manual Progress Bar Graphic
        manual_p = log.get("overall_progress", 0)
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10)
        pdf.set_xy(140, 22); pdf.cell(60, 5, f"Overall Progress: {manual_p}%", 0, 1, 'R')
        pdf.set_draw_color(0, 51, 102); pdf.rect(140, 27, 60, 4) 
        pdf.set_fill_color(0, 200, 0); pdf.rect(140, 27, (manual_p/100)*60, 4, 'F')

        # 3. Header Info Grid (Compact)
        pdf.set_xy(10, 35); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            pdf.cell(25, 6, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(70, 6, f" {str(log.get(f1,''))}", 1, 0, 'L')
            pdf.cell(25, 6, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(70, 6, f" {str(log.get(f2,''))}", 1, 1, 'L')

        # 4. Milestone Table
        pdf.ln(4); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 7, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(30, 7, " Status", 1, 0, 'C', True)
        pdf.cell(110, 7, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 7)
        for label, s_key, n_key in MILESTONE_MAP:
            pdf.cell(50, 6, f" {label}", 1)
            pdf.cell(30, 6, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            pdf.cell(110, 6, f" {str(log.get(n_key,'-'))}", 1, 1)

        # 5. Photo - Positioned to stay on bottom of SAME page
        try:
            photo_data = conn.client.storage.from_("progress-photos").download(f"{log['id']}.jpg")
            if photo_data:
                # Check if there's enough space, else move to a fixed bottom position
                pdf.set_y(210) 
                pdf.set_font("Arial", "B", 9); pdf.cell(0, 5, "Site Progress Photo:", 0, 1)
                pdf.image(BytesIO(photo_data), x=10, h=60) # Scaled by height to stay within bounds
        except: pass

    return pdf.output(dest='S')

# --- APP TABS ---
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

with tab1:
    st.subheader("📋 Select Project")
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_lookup")
    
    last_data = {}
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res.data: last_data = res.data[0]

    # --- ENGINEER CONTROL LOGIC (OUTSIDE FORM FOR LIVE UPDATES) ---
    st.divider()
    c_left, c_right = st.columns([2, 1])
    with c_left:
        f_manual_p = st.slider("Reporting Engineer: Set Completion %", 0, 100, value=int(last_data.get('overall_progress', 0)))
    with c_right:
        st.metric("Final Progress", f"{f_manual_p}%")
        st.progress(f_manual_p / 100)

    with st.form("main_entry_form", clear_on_submit=True):
        st.subheader("📋 Project Details")
        c1, c2, c3 = st.columns(3)
        default_cust_idx = customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0
        f_cust = c1.selectbox("Customer", [""] + customers, index=default_cust_idx)
        c2.text_input("Selected Job", value=f_job, disabled=True)
        f_eq = c3.text_input("Equipment Name", value=last_data.get('equipment', ""))
        
        # ... (Header fields logic remains same)
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
            opts = ["Pending", "In-Progress", "Completed", "NA", "Hold", "Ordered", "Received", "Approved", "Submitted"]
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

# --- ARCHIVE & MASTERS (Logic remains same as your working version) ---
with tab2:
    st.subheader("📂 Report Archive")
    # ... Archive code from your snippet ...
    archive_data = conn.table("progress_logs").select("*").order("created_at", desc=True).execute().data
    if archive_data:
        for row in archive_data:
            with st.expander(f"📦 {row['job_code']} | Progress: {row.get('overall_progress',0)}%"):
                pdf_row = generate_pdf([row])
                st.download_button("📩 Download PDF", pdf_row, f"{row['job_code']}.pdf", key=f"dl_{row['id']}")

with tab3:
    # ... Masters code from your snippet ...
    st.header("🛠️ Masters Management")
