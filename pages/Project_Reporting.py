import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, timedelta
from fpdf import FPDF
from io import BytesIO

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

# 2. MASTER MAPPING (Status, Note, and Manual Progress Key)
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
        
        # 1. Blue Header
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 20, 'F')
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 14)
        pdf.set_xy(10, 5); pdf.cell(0, 10, "B&G ENGINEERING INDUSTRIES - PROGRESS REPORT", 0, 1, "L")
        
        # 2. Job Info Grid
        pdf.set_xy(10, 25); pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            pdf.cell(30, 6, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 6, f" {str(log.get(f1,''))}", 1, 0, 'L')
            pdf.cell(30, 6, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 6, f" {str(log.get(f2,''))}", 1, 1, 'L')

        # 3. Milestone Table
        pdf.ln(5); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 7, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(30, 7, " Status", 1, 0, 'C', True)
        pdf.cell(20, 7, " Done %", 1, 0, 'C', True)
        pdf.cell(90, 7, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key, p_key in MILESTONE_MAP:
            pdf.cell(50, 6, f" {label}", 1)
            pdf.cell(30, 6, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            pdf.cell(20, 6, f" {str(log.get(p_key, 0))}%", 1, 0, 'C')
            pdf.cell(90, 6, f" {str(log.get(n_key,'-'))}", 1, 1)

        # 4. Photo Logic (Keeps it on the same page)
        try:
            photo_data = conn.client.storage.from_("progress-photos").download(f"{log['id']}.jpg")
            if photo_data:
                if pdf.get_y() > 210: pdf.add_page()
                pdf.ln(5); pdf.set_font("Arial", "B", 10); pdf.cell(0, 6, "Progress Verification Photo:", 0, 1)
                pdf.image(BytesIO(photo_data), x=10, h=60) 
        except: pass

    return bytes(pdf.output(dest='S'))

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
            st.info(f"🔄 Data loaded for {f_job}. Update completion percentages below.")

    with st.form("main_entry_form", clear_on_submit=True):
        st.subheader("📋 Project Details")
        c1, c2, c3 = st.columns(3)
        default_cust_idx = customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0
        f_cust = c1.selectbox("Customer", [""] + customers, index=default_cust_idx)
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

        st.divider(); st.subheader("📊 Milestone Tracking (Individual Manual Control)")
        m_responses = {}
        for label, skey, nkey, pkey in MILESTONE_MAP:
            col_stat, col_note, col_prog = st.columns([1.2, 2, 1.2])
            
            # Restored Status Options Logic
            if label == "Drawing Submission": opts = ["Pending", "NA", "In-Progress", "Submitted"]
            elif label == "Drawing Approval": opts = ["Pending", "NA", "In-Progress", "Approved"]
            elif label == "RM Status": opts = ["Pending", "Ordered", "In-Progress", "NA", "Received", "Hold"]
            else: opts = ["Pending", "In-Progress", "Completed", "NA", "Hold"]

            prev_status = last_data.get(skey, "Pending")
            def_idx = opts.index(prev_status) if prev_status in opts else 0
            
            m_responses[skey] = col_stat.selectbox(label, opts, index=def_idx, key=f"s_{skey}")
            m_responses[nkey] = col_note.text_input(f"Remarks ({label})", value=last_data.get(nkey, ""), key=f"n_{nkey}")
            m_responses[pkey] = col_prog.slider(f"{label} %", 0, 100, value=int(last_data.get(pkey, 0)), key=f"p_{pkey}")
            st.write("---")

        st.divider(); cam_photo = st.camera_input("📸 Take Progress Photo")
        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job: st.error("Select Job Code first!")
            else:
                try:
                    payload = {
                        "customer": f_cust, "job_code": f_job, "equipment": f_eq,
                        "po_no": f_po_n, "po_date": str(f_po_d), "engineer": f_eng,
                        "po_delivery_date": str(f_p_del), "exp_dispatch_date": str(f_r_del),
                        **m_responses
                    }
                    res = conn.table("progress_logs").insert(payload).execute()
                    if cam_photo and res.data:
                        conn.client.storage.from_("progress-photos").upload(f"{res.data[0]['id']}.jpg", cam_photo.getvalue())
                    st.success("✅ Saved!"); st.rerun()
                except Exception as e: st.error(f"Error: {e}")

with tab2:
    st.subheader("📂 Report Archive")
    f_cust_search = st.selectbox("🔍 Filter by Customer", ["All"] + customers)
    query = conn.table("progress_logs").select("*").order("created_at", desc=True)
    if f_cust_search != "All": query = query.eq("customer", f_cust_search)
    
    archive_data = query.execute().data
    if archive_data:
        for row in archive_data:
            with st.expander(f"📦 {row['job_code']} | {row['customer']} | {row['created_at'][:10]}"):
                pdf_bytes = generate_pdf([row])
                st.download_button("📩 Download PDF", pdf_bytes, f"Report_{row['job_code']}.pdf", "application/pdf", key=f"dl_{row['id']}")

with tab3:
    st.header("🛠️ Masters")
    c_a, c_b = st.columns(2)
    with c_a:
        nc = st.text_input("New Customer")
        if st.button("Add Customer"): conn.table("customer_master").insert({"name": nc}).execute(); st.rerun()
    with c_b:
        nj = st.text_input("New Job Code")
        if st.button("Add Job"): conn.table("job_master").insert({"job_code": nj}).execute(); st.rerun()
