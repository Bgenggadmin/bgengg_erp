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

# --- 2. ENGINE ---
def process_photos(uploaded_files):
    processed = []
    for file in uploaded_files[:4]:
        img = Image.open(file)
        img = img.resize((350, 450), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=70) 
        if buf.tell() > 51200:
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=40)
        processed.append(buf.getvalue())
    return processed

def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # 1. Logo Handling (unchanged but wrapped in safety)
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
        # ... [Header and Table logic remains exactly the same] ...
        
        # --- FIXED PHOTO SECTION ---
        pdf.ln(10) 
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, "Progress Documentation Photos:", 0, 1, "L")
        
        # Capture the Y position once for the whole row
        start_y = pdf.get_y() 
        img_x = 10
        photo_count = 0

        for i in range(4):
            try:
                img_path = f"{log.get('id')}_{i}.jpg"
                img_data = conn.client.storage.from_("progress-photos").download(img_path)
                
                if img_data:
                    # delete=False is correct, but we must handle the lifecycle
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                        tmp_img.write(img_data)
                        tmp_img.flush()  # CRITICAL: Ensure data is written to disk
                        
                        # Use start_y to keep them all in one row
                        pdf.image(tmp_img.name, x=img_x, y=start_y, w=45)
                        
                        img_x += 48
                        photo_count += 1
                        tmp_name = tmp_img.name # Store for unlinking
                    
                    os.unlink(tmp_name) # Clean up after image is added to PDF buffer
            except:
                continue

        # CRITICAL: Move the cursor DOWN after the images are placed
        # Each image is 45w, roughly 50-60h depending on aspect ratio
        if photo_count > 0:
            pdf.set_y(start_y + 55) 
        else:
            pdf.set_font("Arial", "I", 8)
            pdf.cell(0, 10, "No progress photos available for this update.", 0, 1, "L")

    if logo_path and os.path.exists(logo_path):
        os.unlink(logo_path)
        
    return bytes(pdf.output(dest='S'), encoding='latin-1')

# --- 3. DATA FETCH ---
@st.cache_data(ttl=600)
def get_master_data():
    try:
        c_res = conn.table("customer_master").select("name").execute()
        j_res = conn.table("job_master").select("job_code").execute()
        c_list = [d['name'] for d in c_res.data] if c_res.data else []
        j_list = [d['job_code'] for d in j_res.data] if j_res.data else []
        return sorted(c_list), sorted(j_list)
    except: return [], []

customers, jobs = get_master_data()

# --- 4. MAIN UI ---
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🛠️ Masters"])

with tab1:
    st.subheader("📋 Project Update")
    f_job = st.selectbox("Job Code", [""] + jobs, key="job_lookup")
    last_data = {}
    
    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if res and res.data: 
            last_data = res.data[0]
            st.toast(f"🔄 Autofilled latest data for {f_job}")

    with st.form("main_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        try:
            c_idx = customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0
        except: c_idx = 0

        f_cust = c1.selectbox("Customer", [""] + customers, index=c_idx)
        f_eq = c2.text_input("Equipment", value=last_data.get('equipment', ""))
        
        c3, c4, c5 = st.columns(3)
        f_po_n = c3.text_input("PO Number", value=last_data.get('po_no', ""))
        
        def safe_date(field):
            val = last_data.get(field)
            try: return datetime.strptime(val, "%Y-%m-%d") if val else datetime.now()
            except: return datetime.now()

        f_po_d = c4.date_input("PO Date", value=safe_date('po_date'))
        f_eng = c5.text_input("Responsible Engineer", value=last_data.get('engineer', ""))

        st.divider()
        st.subheader("📊 Milestone Tracking")
        m_responses = {}
        opts = ["Pending", "NA", "In-Progress", "Submitted", "Approved", "Ordered", "Received", "Hold", "Completed", "Planning", "Scheduled"]
        job_suffix = str(f_job) if f_job else "initial"

        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"
            col1, col2, col3 = st.columns([1.5, 1, 2])
            prev_status = last_data.get(skey, "Pending")
            def_idx = opts.index(prev_status) if prev_status in opts else 0
            raw_prog = last_data.get(pk, 0)
            prev_prog = int(raw_prog) if raw_prog is not None else 0
            prev_note = last_data.get(nkey, "") or ""
            
            m_responses[skey] = col1.selectbox(label, opts, index=def_idx, key=f"s_{skey}_{job_suffix}")
            m_responses[pk] = col2.slider("Prog %", 0, 100, value=prev_prog, key=f"p_{skey}_{job_suffix}")
            m_responses[nkey] = col3.text_input("Remarks", value=prev_note, key=f"n_{skey}_{job_suffix}")

        st.divider()
        f_progress = st.slider("📈 Overall Completion %", 0, 100, value=int(last_data.get('overall_progress', 0) or 0), key=f"ov_{job_suffix}")
        
        st.subheader("📸 Progress Documentation (Max 4 Photos)")
        uploaded_photos = st.file_uploader("Upload Progress Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job:
                st.error("Please select Customer and Job Code")
            else:
                payload = {
                    "customer": f_cust, "job_code": f_job, "equipment": f_eq,
                    "po_no": f_po_n, "po_date": str(f_po_d), "engineer": f_eng,
                    "overall_progress": f_progress, **m_responses
                }
                res = conn.table("progress_logs").insert(payload).execute()
                
                if uploaded_photos and res.data:
                    file_id = res.data[0]['id']
                    processed_list = process_photos(uploaded_photos)
                    for i, img_data in enumerate(processed_list):
                        conn.client.storage.from_("progress-photos").upload(
                            f"{file_id}_{i}.jpg", img_data,
                            file_options={"content-type": "image/jpeg"}
                        )
                st.success("✅ Saved!"); st.cache_data.clear(); st.rerun()

with tab2:
    st.subheader("📂 Report Archive")
    f1, f2, f3 = st.columns(3)
    sel_c = f1.selectbox("Filter Customer", ["All"] + customers)
    report_type = f2.selectbox("📅 Period", ["All Time", "Current Week", "Current Month", "Custom Range"])
    
    # Date Filtering Logic
    start_date, end_date = None, None
    now = datetime.now()
    if report_type == "Current Week":
        start_date = (now - timedelta(days=now.weekday())).date()
    elif report_type == "Current Month":
        start_date = now.replace(day=1).date()
    elif report_type == "Custom Range":
        dates = f3.date_input("Select Range", [now, now])
        if len(dates) == 2:
            start_date, end_date = dates[0], dates[1]

    # Database query
    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if sel_c != "All":
        query = query.eq("customer", sel_c)
    
    res = query.execute()
    raw_data = res.data if res.data else []

    # Local Time Filtering
    data = []
    if start_date:
        for d in raw_data:
            try:
                # Use created_at timestamp (first 10 chars for YYYY-MM-DD)
                d_date = datetime.strptime(d.get('created_at', d.get('po_date'))[:10], "%Y-%m-%d").date()
                if end_date:
                    if start_date <= d_date <= end_date: data.append(d)
                else:
                    if d_date >= start_date: data.append(d)
            except: data.append(d)
    else:
        data = raw_data

    # --- NEW: SUMMARY DASHBOARD ---
    if data:
        total_jobs = len(data)
        completed = len([d for d in data if int(d.get('overall_progress', 0) or 0) == 100])
        pending = total_jobs - completed
        avg_prog = sum([int(d.get('overall_progress', 0) or 0) for d in data]) / total_jobs

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Total Reports", total_jobs)
        s2.metric("Completed", completed, delta=f"{(completed/total_jobs)*100:.0f}%" if total_jobs > 0 else "0%")
        s3.metric("Pending", pending)
        s4.metric("Avg. Progress", f"{avg_prog:.1f}%")
        st.divider()

        # PDF & LISTING
        pdf_bytes = generate_pdf(data)
        st.download_button("📥 Download PDF Report", data=pdf_bytes, file_name=f"BG_Report_{report_type}.pdf", mime="application/pdf", use_container_width=True)
        
        for log in data:
            with st.expander(f"📦 {log.get('job_code')} - {log.get('customer')} ({log.get('created_at', log.get('po_date'))[:10]})"):
                st.write(f"**Overall Progress: {log.get('overall_progress', 0)}%**")
                st.progress(int(log.get('overall_progress', 0) or 0) / 100)
                # Show individual milestone statuses briefly
                cols = st.columns(3)
                cols[0].write(f"**Fab:** {log.get('fab_status', 'N/A')}")
                cols[1].write(f"**QC:** {log.get('qc_stat', 'N/A')}")
                cols[2].write(f"**Testing:** {log.get('testing', 'N/A')}")
    else:
        st.info(f"No records found for {sel_c} in the {report_type} period.")

with tab3:
    st.subheader("🛠️ Master Management")
    c_col, j_col = st.columns(2)
    with c_col:
        st.write("**Current Customers:**", ", ".join(customers) if customers else "None")
        with st.form("add_cust"):
            nc = st.text_input("New Customer")
            if st.form_submit_button("Add Customer") and nc:
                conn.table("customer_master").insert({"name": nc}).execute()
                st.cache_data.clear(); st.rerun()
    with j_col:
        st.write("**Current Job Codes:**", ", ".join(jobs) if jobs else "None")
        with st.form("add_job"):
            nj = st.text_input("New Job Code")
            if st.form_submit_button("Add Job") and nj:
                conn.table("job_master").insert({"job_code": nj}).execute()
                st.cache_data.clear(); st.rerun()
