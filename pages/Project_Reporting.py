import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, timedelta
from fpdf import FPDF
from io import BytesIO

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# 2. UPDATED MASTER MAPPING (Status, Remarks, and % Progress)
MILESTONE_MAP = [
    ("Drawing Submission", "draw_sub", "draw_sub_note", "draw_sub_prog"),
    ("Drawing Approval", "draw_app", "draw_app_note", "draw_app_prog"),
    ("RM Status", "rm_status", "rm_note", "rm_prog"),
    ("Sub-deliveries", "sub_del", "sub_del_note", "sub_del_prog"),
    ("Fabrication Status", "fab_status", "remarks", "fab_prog"),
    ("Buffing Status", "buff_stat", "buff_note", "buff_prog"),
    ("Testing Status", "testing", "test_note", "test_prog"),
    ("Dispatch Status", "qc_stat", "qc_note", "qc_prog"),
    ("FAT Status", "fat_stat", "fat_note", "fat_prog")
]

HEADER_FIELDS = ["customer", "job_code", "equipment", "po_no", "po_date", "engineer", "po_delivery_date", "exp_dispatch_date"]

# --- DATA FETCHING ---
customers = sorted([d['name'] for d in conn.table("customer_master").select("name").execute().data])
jobs = sorted([d['job_code'] for d in conn.table("job_master").select("job_code").execute().data])

# --- STABLE PDF ENGINE ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=10)
    for log in logs:
        pdf.add_page()
        
        # Header
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 20, 'F')
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 12)
        pdf.set_xy(10, 6); pdf.cell(0, 8, f"JOB: {log.get('job_code','')} - PROGRESS REPORT")
        
        # Header Details
        pdf.set_xy(10, 25); pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            pdf.cell(30, 6, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 6, f" {str(log.get(f1,''))}", 1, 0, 'L')
            pdf.cell(30, 6, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 6, f" {str(log.get(f2,''))}", 1, 1, 'L')

        # Milestone Table with Progress Column
        pdf.ln(5); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(55, 7, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(25, 7, " Status", 1, 0, 'C', True)
        pdf.cell(20, 7, " Done %", 1, 0, 'C', True) # NEW COLUMN
        pdf.cell(90, 7, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key, p_key in MILESTONE_MAP:
            pdf.cell(55, 6, f" {label}", 1)
            pdf.cell(25, 6, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            pdf.cell(20, 6, f" {str(log.get(p_key, 0))}%", 1, 0, 'C') # SHOW INDIVIDUAL %
            pdf.cell(90, 6, f" {str(log.get(n_key,'-'))}", 1, 1)

        # Photo - Kept on same page if possible
        try:
            photo_data = conn.client.storage.from_("progress-photos").download(f"{log['id']}.jpg")
            if photo_data:
                if pdf.get_y() > 210: pdf.add_page()
                pdf.ln(5); pdf.set_font("Arial", "B", 10); pdf.cell(0, 6, "Progress Verification Photo:", 0, 1)
                pdf.image(BytesIO(photo_data), x=10, w=75) 
        except: pass

    return bytes(pdf.output(dest='S'))

# --- UI TABS ---
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

with tab1:
    st.subheader("📋 Select Project")
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_sel")
    last_data = {}
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res.data: last_data = res.data[0]

    with st.form("main_form_v2", clear_on_submit=True):
        st.subheader("📋 Project Details")
        c1, c2 = st.columns(2)
        f_cust = c1.selectbox("Customer", [""] + customers)
        f_eng = c2.text_input("Engineer", value=last_data.get('engineer', ""))

        st.divider(); st.subheader("📊 Milestone Tracking (Manual Control)")
        m_responses = {}
        
        for label, skey, nkey, pkey in MILESTONE_MAP:
            # --- THREE COLUMNS PER MILESTONE ---
            col_stat, col_note, col_prog = st.columns([1.2, 2, 1.2])
            
            m_responses[skey] = col_stat.selectbox(label, ["Pending", "In-Progress", "Completed", "NA", "Hold"], key=f"s_{skey}")
            m_responses[nkey] = col_note.text_input(f"Remarks for {label}", value=last_data.get(nkey, ""), key=f"n_{nkey}")
            
            # THE INDIVIDUAL SLIDER FOR THE ENGINEER
            m_responses[pkey] = col_prog.slider(f"{label} %", 0, 100, value=int(last_data.get(pkey, 0)), key=f"p_{pkey}")
            st.write("---")

        st.divider(); cam = st.camera_input("Take Photo")
        
        if st.form_submit_button("🚀 SUBMIT UPDATE"):
            if not f_job: st.error("Please select a Job Code")
            else:
                payload = {"job_code": f_job, "customer": f_cust, "engineer": f_eng, **m_responses}
                res = conn.table("progress_logs").insert(payload).execute()
                if cam and res.data:
                    conn.client.storage.from_("progress-photos").upload(f"{res.data[0]['id']}.jpg", cam.getvalue())
                st.success("Entry Saved Successfully!"); st.rerun()

with tab2:
    st.subheader("📂 Report Archive")
    # Restore Filter logic
    f_cust_filter = st.selectbox("Filter by Customer", ["All"] + customers)
    query = conn.table("progress_logs").select("*").order("created_at", desc=True)
    if f_cust_filter != "All": query = query.eq("customer", f_cust_filter)
    
    archive_data = query.execute().data
    if archive_data:
        for row in archive_data:
            with st.expander(f"📦 Job: {row['job_code']} | Date: {row['created_at'][:10]}"):
                pdf_bytes = generate_pdf([row])
                st.download_button("📩 Download This PDF", data=pdf_bytes, file_name=f"Report_{row['job_code']}.pdf", mime="application/pdf", key=f"dl_{row['id']}")

with tab3:
    st.header("🛠️ Masters Management")
    # Simple masters logic
    new_c = st.text_input("Add Customer")
    if st.button("Add"): conn.table("customer_master").insert({"name": new_c}).execute(); st.rerun()
