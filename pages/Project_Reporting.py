import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, timedelta
from fpdf import FPDF
from io import BytesIO

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# 2. THE MASTER MAPPING (Restored from your original)
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

# --- PDF ENGINE (RE-WRITTEN TO BE STABLE) ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=10)
    for log in logs:
        pdf.add_page()
        
        # Blue Header Strip
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 20, 'F')
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 14)
        pdf.set_xy(10, 5); pdf.cell(0, 8, "B&G ENGINEERING INDUSTRIES - PROGRESS REPORT")
        
        # Manual Progress Bar Logic
        p_val = log.get("overall_progress", 0)
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10)
        pdf.set_xy(140, 22); pdf.cell(60, 5, f"Overall Progress: {p_val}%", 0, 1, 'R')
        pdf.set_draw_color(0, 51, 102); pdf.rect(140, 27, 60, 4)
        pdf.set_fill_color(0, 200, 0); pdf.rect(140, 27, (p_val/100)*60, 4, 'F')

        # Header Details
        pdf.set_xy(10, 35); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(230, 230, 230)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            pdf.cell(30, 6, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 6, f" {str(log.get(f1,''))}", 1, 0, 'L')
            pdf.cell(30, 6, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 6, f" {str(log.get(f2,''))}", 1, 1, 'L')

        # Milestones
        pdf.ln(5); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(60, 7, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(35, 7, " Status", 1, 0, 'C', True)
        pdf.cell(95, 7, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            pdf.cell(60, 6, f" {label}", 1)
            pdf.cell(35, 6, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            pdf.cell(95, 6, f" {str(log.get(n_key,'-'))}", 1, 1)

        # Photo (Check if enough space exists on same page)
        try:
            photo_data = conn.client.storage.from_("progress-photos").download(f"{log['id']}.jpg")
            if photo_data:
                # Force photo to fit on the same page by reducing current Y
                if pdf.get_y() > 200: pdf.add_page() 
                pdf.ln(5); pdf.set_font("Arial", "B", 10); pdf.cell(0, 6, "Progress Photo:", 0, 1)
                pdf.image(BytesIO(photo_data), x=10, w=80) 
        except: pass

    # STABLE BYTE OUTPUT
    return bytes(pdf.output(dest='S'))

# --- UI TABS ---
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

with tab1:
    st.subheader("📋 Select Project")
    f_job = st.selectbox("Job Code", [""] + jobs)
    last_data = {}
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res.data: last_data = res.data[0]

    # ENGINEER CONTROL LOGIC (Manual Progress)
    st.info("Reporting Engineer: Update overall completion before submitting.")
    f_manual_p = st.slider("Completion %", 0, 100, value=int(last_data.get('overall_progress', 0)))

    with st.form("main_form", clear_on_submit=True):
        st.subheader("📋 Project Details")
        c1, c2 = st.columns(2)
        f_cust = c1.selectbox("Customer", [""] + customers)
        f_eq = c2.text_input("Equipment Name", value=last_data.get('equipment', ""))
        
        # Form inputs for all fields...
        c3, c4 = st.columns(2); f_po_n = c3.text_input("PO No", value=last_data.get('po_no', ""))
        f_eng = c4.text_input("Engineer", value=last_data.get('engineer', ""))

        st.divider(); m_responses = {}
        for label, skey, nkey in MILESTONE_MAP:
            ca, cb = st.columns([1, 2])
            m_responses[skey] = ca.selectbox(label, ["Pending", "In-Progress", "Completed", "NA", "Hold", "Approved"])
            m_responses[nkey] = cb.text_input(f"Remarks ({label})", value=last_data.get(nkey, ""))

        st.divider(); cam = st.camera_input("Take Photo")
        if st.form_submit_button("SUBMIT"):
            payload = {"job_code": f_job, "customer": f_cust, "equipment": f_eq, "po_no": f_po_n, "engineer": f_eng, "overall_progress": f_manual_p, **m_responses}
            res = conn.table("progress_logs").insert(payload).execute()
            if cam and res.data:
                conn.client.storage.from_("progress-photos").upload(f"{res.data[0]['id']}.jpg", cam.getvalue())
            st.success("Saved!"); st.rerun()

with tab2:
    st.subheader("📂 Report Archive")
    archive_data = conn.table("progress_logs").select("*").order("created_at", desc=True).execute().data
    if archive_data:
        for row in archive_data:
            with st.expander(f"📦 {row['job_code']} | Progress: {row.get('overall_progress',0)}%"):
                # Byte conversion inside the loop to ensure clean data for st.download_button
                try:
                    pdf_bytes = generate_pdf([row])
                    st.download_button(
                        label="📩 Download PDF Report",
                        data=pdf_bytes,
                        file_name=f"{row['job_code']}_report.pdf",
                        mime="application/pdf",
                        key=f"btn_{row['id']}"
                    )
                except Exception as e:
                    st.error("PDF Error")

with tab3:
    st.header("🛠️ Masters")
    # (Simplified Masters)
    st.text_input("New Customer")
