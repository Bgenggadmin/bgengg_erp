import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, date, timedelta
from fpdf import FPDF
from io import BytesIO

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# 2. MASTER MAPPING
HEADER_FIELDS = ["customer", "job_code", "equipment", "po_no", "po_date", "engineer", "po_delivery_date", "exp_dispatch_date"]

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

# --- DATA FETCHING ---
customers = sorted([d['name'] for d in conn.table("customer_master").select("name").execute().data])
jobs = sorted([d['job_code'] for d in conn.table("job_master").select("job_code").execute().data])

# --- PDF ENGINE (RE-VERIFIED) ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    for log in logs:
        pdf.add_page()
        # Header Branding
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        try:
            logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
            if logo_data: pdf.image(BytesIO(logo_data), x=12, y=5, h=15)
        except: pass
        
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 16); pdf.set_xy(70, 5); pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 10); pdf.set_xy(70, 14); pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        # Project Info
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 35)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','')} | REPORT DATE: {log.get('created_at',' ')[:10]}", "B", 1, "L")
        
        pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,''))}", 1, 0, 'L')
            pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f2,''))}", 1, 1, 'L')

        # Milestone Table
        pdf.ln(5); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(55, 8, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(30, 8, " Status", 1, 0, 'C', True)
        pdf.cell(15, 8, " %", 1, 0, 'C', True)
        pdf.cell(90, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key, p_key in MILESTONE_MAP:
            status = str(log.get(s_key, 'Pending'))
            if status in ["Completed", "Approved", "Submitted"]: pdf.set_fill_color(144, 238, 144)
            elif status in ["In-Progress", "Ordered", "Received", "Planning"]: pdf.set_fill_color(255, 255, 204)
            else: pdf.set_fill_color(255, 255, 255)
            pdf.cell(55, 7, f" {label}", 1)
            pdf.cell(30, 7, f" {status}", 1, 0, 'C', True)
            pdf.cell(15, 7, f" {log.get(p_key, 0)}%", 1, 0, 'C')
            pdf.cell(90, 7, f" {str(log.get(n_key,'-'))}", 1, 1)

    # Reliable Byte Output
    return pdf.output(dest='S').encode('latin-1')

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
            st.info(f"🔄 Auto-filled fields from Job {f_job}")

    with st.form("main_entry_form", clear_on_submit=True):
        st.subheader("📋 Project Details")
        c1, c2, c3 = st.columns(3)
        def_cust_idx = customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0
        f_cust = c1.selectbox("Customer", [""] + customers, index=def_cust_idx)
        c2.text_input("Selected Job", value=f_job, disabled=True)
        f_eq = c3.text_input("Equipment Name", value=last_data.get('equipment', ""))
        
        c4, c5, c6 = st.columns(3)
        f_po_n = c4.text_input("PO Number", value=last_data.get('po_no', ""))
        def safe_date(field):
            val = last_data.get(field)
            try: return datetime.strptime(val, "%Y-%m-%d").date()
            except: return date.today()
        f_po_d = c5.date_input("PO Date", value=safe_date('po_date'))
        f_eng = c6.text_input("Responsible Engineer", value=last_data.get('engineer', ""))
        
        c7, c8 = st.columns(2)
        f_p_del = c7.date_input("PO Delivery Date", value=safe_date('po_delivery_date'))
        f_r_del = c8.date_input("Revised Dispatch Date", value=safe_date('exp_dispatch_date'))

        st.divider(); st.subheader("📊 Milestone Tracking")
        m_responses = {}
        for label, skey, nkey, pkey in MILESTONE_MAP:
            col_stat, col_note, col_prog = st.columns([1.2, 2, 1.2])
            opts = ["Pending", "NA", "In-Progress", "Completed", "Submitted", "Approved", "Ordered", "Received"]
            p_status = last_data.get(skey, "Pending")
            m_responses[skey] = col_stat.selectbox(label, opts, index=opts.index(p_status) if p_status in opts else 0, key=f"s_{skey}")
            m_responses[nkey] = col_note.text_input(f"Remarks ({label})", value=last_data.get(nkey, ""), key=f"n_{nkey}")
            m_responses[pkey] = col_prog.slider(f"{label} %", 0, 100, value=int(last_data.get(pkey, 0)), key=f"p_{pkey}")

        st.divider(); cam = st.camera_input("📸 Take Progress Photo")
        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job: st.error("Select Job & Customer!")
            else:
                payload = {"customer": f_cust, "job_code": f_job, "equipment": f_eq, "po_no": f_po_n, "po_date": str(f_po_d), "engineer": f_eng, "po_delivery_date": str(f_p_del), "exp_dispatch_date": str(f_r_del), **m_responses}
                res = conn.table("progress_logs").insert(payload).execute()
                if cam and res.data: conn.client.storage.from_("progress-photos").upload(f"{res.data[0]['id']}.jpg", cam.getvalue())
                st.success("Saved!"); st.rerun()

with tab2:
    st.subheader("📂 Report Archive")
    c1, c2 = st.columns(2)
    f_cust_search = c1.selectbox("Filter by Customer", ["All"] + customers, key="arch_cust")
    duration = c2.selectbox("Report Duration", ["All Time", "This Week", "This Month", "Last 30 Days"], key="arch_dur")
    
    # Date Logic
    start_date = date(2020, 1, 1)
    if duration == "This Week": start_date = date.today() - timedelta(days=date.today().weekday())
    elif duration == "This Month": start_date = date.today().replace(day=1)
    elif duration == "Last 30 Days": start_date = date.today() - timedelta(days=30)

    query = conn.table("progress_logs").select("*").gte("created_at", start_date)
    if f_cust_search != "All": query = query.eq("customer", f_cust_search)
    
    archive_data = query.order("created_at", desc=True).execute().data
    
    if archive_data:
        for row in archive_data:
            with st.expander(f"📦 {row['job_code']} | {row['customer']} | {row['created_at'][:10]}"):
                # CRITICAL: PDF Download Button Restored
                pdf_output = generate_pdf([row])
                st.download_button(
                    label="📩 Download PDF Report",
                    data=pdf_output,
                    file_name=f"Report_{row['job_code']}_{row['created_at'][:10]}.pdf",
                    mime="application/pdf",
                    key=f"dl_{row['id']}"
                )
    else:
        st.warning("No reports found.")

with tab3:
    st.header("🛠️ Masters")
    c_a, c_b = st.columns(2)
    with c_a:
        nc = st.text_input("New Customer")
        if st.button("Add Customer"): conn.table("customer_master").insert({"name": nc}).execute(); st.rerun()
    with c_b:
        nj = st.text_input("New Job Code")
        if st.button("Add Job"): conn.table("job_master").insert({"job_code": nj}).execute(); st.rerun()
