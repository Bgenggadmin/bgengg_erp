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
# --- PASSWORD PROTECTION ---
def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == "1234": # You can change this!
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct.
        return True

if not check_password():
    st.stop()  # Do not run the rest of the app if password isn't correct
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

def get_prev_photos(log_id):
    images = []
    try:
        for i in range(4):
            img_data = conn.client.storage.from_("progress-photos").download(f"{log_id}_{i}.jpg")
            if img_data: images.append(img_data)
    except: pass
    return images

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
        # Lock the current report date in IST
        report_date = datetime.now(IST).strftime('%d-%m-%Y')

        # Blue Header Bar
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        if logo_path: pdf.image(logo_path, x=12, y=5, h=15)
    
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 5); pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 10); pdf.set_xy(70, 14); pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
    
    # --- JOB ID & REPORT DATE BAR ---
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
    
    # 1. Left Aligned Job Info (Note: ln=0 keeps us on the same line)
    pdf.cell(0, 8, f" JOB: {log.get('job_code','N/A')} | ID: {log.get('id','N/A')}", "B", 0, "L")
    
    # 2. Right Aligned Report Date (Reset X and use 'R' alignment)
    pdf.set_xy(10, 30)
    pdf.cell(0, 8, f"Report Date: {report_date} ", 0, 1, "R")
    
    # Resume Standard Layout
    pdf.ln(2); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        
        for i in range(0, len(HEADER_FIELDS), 2):
            f1 = HEADER_FIELDS[i]; f2 = HEADER_FIELDS[i+1] if i+1 < len(HEADER_FIELDS) else None
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,'-'))}", 1, 0, 'L')
            if f2:
                pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
                pdf.cell(65, 7, f" {str(log.get(f2,'-'))}", 1, 1, 'L')
            else: pdf.ln(7)

        pdf.ln(5); ov_p = int(log.get('overall_progress', 0) or 0)
        pdf.set_font("Arial", "B", 10); pdf.cell(50, 8, f"Overall Completion: {ov_p}%", 0, 0, 'L')
        pdf.set_fill_color(230, 230, 230); pdf.rect(60, pdf.get_y() + 2, 130, 4, 'F')
        if ov_p > 0:
            pdf.set_fill_color(0, 82, 164)
            pdf.rect(60, pdf.get_y() + 2, (ov_p / 100) * 130, 4, 'F')
        pdf.ln(10)

        pdf.set_font("Arial", "B", 9); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 8, " Milestone Item", 1, 0, 'L', True); pdf.cell(30, 8, " Status", 1, 0, 'C', True)
        pdf.cell(30, 8, " Progress", 1, 0, 'C', True); pdf.cell(80, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            pk = f"{s_key}_prog"
            m_p = int(log.get(pk, 0) or 0)
            pdf.cell(50, 10, f" {label}", 1)
            pdf.cell(30, 10, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')
            curr_x, curr_y = pdf.get_x(), pdf.get_y()
            pdf.cell(30, 10, "", 1, 0) 
            pdf.set_fill_color(240, 240, 240); pdf.rect(curr_x + 3, curr_y + 4, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76); pdf.rect(curr_x + 3, curr_y + 4, (min(m_p, 100) / 100) * 24, 2, 'F')
            pdf.set_xy(curr_x + 30, curr_y)
            pdf.cell(80, 10, f" {str(log.get(n_key,'-'))}", 1, 1)

        pdf.ln(10); pdf.set_font("Arial", "B", 10); pdf.cell(0, 10, "Progress Documentation Photos:", 0, 1, "L")
        start_y, img_x, photo_count = pdf.get_y(), 10, 0
        for i in range(4):
            try:
                img_data = conn.client.storage.from_("progress-photos").download(f"{log.get('id')}_{i}.jpg")
                if img_data:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                        tmp_img.write(img_data); tmp_img.flush()
                        pdf.image(tmp_img.name, x=img_x, y=start_y, w=45)
                        img_x += 48; photo_count += 1; t_name = tmp_img.name
                    os.unlink(t_name)
            except: continue
        pdf.set_y(start_y + 55) if photo_count > 0 else pdf.cell(0, 10, "No progress photos available.", 0, 1, "L")

    if logo_path and os.path.exists(logo_path): os.unlink(logo_path)
    return bytes(pdf.output(dest='S'), encoding='latin-1')

# --- 3. DATA FETCH ---
@st.cache_data(ttl=600)
def get_master_data():
    try:
        # PULLING DIRECTLY FROM ANCHOR PORTAL (Single Source of Truth)
        res = conn.table("anchor_projects").select("job_no, client_name, project_description").order("job_no").execute()
        if res.data:
            j_map = {d['job_no']: {"display": f"{d['job_no']} | {d.get('client_name', 'N/A')}", 
                                  "desc": d.get('project_description', 'No description')} for d in res.data}
            return j_map
    except: pass
    return {}

def get_anchor_details(job_code):
    try:
        res = conn.table("anchor_projects").select("*").eq("job_no", job_code).limit(1).execute()
        return res.data[0] if res.data else {}
    except: return {}

job_map = get_master_data()

# --- 4. MAIN UI ---
tab1, tab2 = st.tabs(["📝 New Entry", "📂 Archive"])

with tab1:
    st.subheader("📋 Project Update")
    job_display_list = [v["display"] for v in job_map.values()]
    f_job_display = st.selectbox("Search Job Code or Customer", [""] + job_display_list, key="job_lookup")
    f_job = f_job_display.split(" | ")[0] if f_job_display else ""
    
    anchor_data, last_log = {}, {}
    
    if f_job:
        anchor_data = get_anchor_details(f_job)
        log_res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        
        c1, c2 = st.columns([2, 1])
        with c1: st.info(f"📝 **Description:** {anchor_data.get('project_description', 'N/A')}")
        with c2:
            if log_res.data:
                last_log = log_res.data[0]
                ts = datetime.strptime(last_log['created_at'][:16], "%Y-%m-%dT%H:%M").strftime("%d %b, %I:%M %p")
                st.warning(f"🕒 **Last Update:** {ts} ({last_log.get('overall_progress', 0)}%)")
                if st.button("🖼️ View Last Photos"):
                    imgs = get_prev_photos(last_log['id'])
                    if imgs:
                        icols = st.columns(len(imgs))
                        for idx, im in enumerate(imgs): icols[idx].image(im, use_container_width=True)
            else: st.success("🆕 **Status:** New Project")

    with st.form("main_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        f_cust = c1.text_input("Customer", value=anchor_data.get('client_name', last_log.get('customer', "")))
        f_eq = c2.text_input("Equipment", value=last_log.get('equipment', ""))
        
        c3, c4, c5 = st.columns(3)
        f_po_n = c3.text_input("PO Number", value=anchor_data.get('po_no', last_log.get('po_no', "")))
        
        def safe_dt(val):
            try: return datetime.strptime(val[:10], "%Y-%m-%d") if val else datetime.now()
            except: return datetime.now()

        f_po_d = c4.date_input("PO Date", value=safe_dt(anchor_data.get('po_date') or last_log.get('po_date')))
        f_eng = c5.text_input("Responsible Engineer", value=last_log.get('engineer', ""))

        d1, d2 = st.columns(2)
        f_p_del = d1.date_input("po_delivery_date", value=safe_dt(anchor_data.get('po_delivery_date')))
        f_e_disp = d2.date_input("Exp Dispatch", value=safe_dt(anchor_data.get('revised_delivery_date') or last_log.get('exp_dispatch_date')))

        st.divider(); st.subheader("📊 Milestone Tracking")
        m_responses, opts = {}, ["Pending", "NA", "In-Progress", "Submitted", "Approved", "Ordered", "Received", "Hold", "Completed", "Planning", "Scheduled"]
        js = str(f_job) if f_job else "init"
        
        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"
            col1, col2, col3 = st.columns([1.5, 1, 2])
            m_responses[skey] = col1.selectbox(label, opts, index=opts.index(last_log.get(skey, "Pending")) if last_log.get(skey) in opts else 0, key=f"s_{skey}_{js}")
            m_responses[pk] = col2.slider("Prog %", 0, 100, value=int(last_log.get(pk, 0) or 0), key=f"p_{skey}_{js}")
            m_responses[nkey] = col3.text_input("Remarks", value=last_log.get(nkey, "") or "", key=f"n_{skey}_{js}")

        st.divider()
        f_progress = st.slider("📈 Overall Completion %", 0, 100, value=int(last_log.get('overall_progress', 0) or 0), key=f"ov_{js}")
        uploaded_photos = st.file_uploader("Upload Progress Photos", accept_multiple_files=True, type=['jpg', 'jpeg', 'png'])

        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job: st.error("Missing Job/Customer Data")
            else:
                payload = {
                    "customer": f_cust, "job_code": f_job, "equipment": f_eq, "po_no": f_po_n, 
                    "po_date": str(f_po_d), "engineer": f_eng, "po_delivery_date": str(f_p_del),
                    "exp_dispatch_date": str(f_e_disp), "overall_progress": f_progress, **m_responses
                }
                res = conn.table("progress_logs").insert(payload).execute()
                if uploaded_photos and res.data:
                    f_id = res.data[0]['id']
                    imgs = process_photos(uploaded_photos)
                    for i, d in enumerate(imgs):
                        conn.client.storage.from_("progress-photos").upload(f"{f_id}_{i}.jpg", d, file_options={"content-type":"image/jpeg"})
                st.success("✅ Saved!"); st.cache_data.clear(); st.rerun()

with tab2:
    st.subheader("📂 Report Archive")
    # Fetch list of unique customers from logs for filtering
    log_cust_res = conn.table("progress_logs").select("customer").execute()
    log_customers = sorted(list(set([d['customer'] for d in log_cust_res.data]))) if log_cust_res.data else []
    
    f1, f2, f3 = st.columns(3)
    sel_c = f1.selectbox("Filter Customer", ["All"] + log_customers)
    report_type = f2.selectbox("📅 Period", ["All Time", "Current Week", "Current Month", "Custom Range"])
    
    start_date, end_date, now = None, None, datetime.now()
    if report_type == "Current Week": start_date = (now - timedelta(days=now.weekday())).date()
    elif report_type == "Current Month": start_date = now.replace(day=1).date()
    elif report_type == "Custom Range":
        dates = f3.date_input("Select Range", [now, now])
        if len(dates) == 2: start_date, end_date = dates[0], dates[1]

    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if sel_c != "All": query = query.eq("customer", sel_c)
    res = query.execute()
    data = [d for d in res.data if not start_date or (start_date <= datetime.strptime(d.get('created_at', d.get('po_date'))[:10], "%Y-%m-%d").date() <= (end_date or datetime.now().date()))] if res.data else []

    if data:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Reports", len(data))
        m2.metric("Completed", len([d for d in data if int(d.get('overall_progress', 0) or 0) == 100]))
        st.divider()
        if st.button("📥 Prepare PDF for Download", use_container_width=True):
            pdf_bytes = generate_pdf(data)
            st.download_button(label="✅ Click here to Save PDF", data=pdf_bytes, file_name=f"BG_Report_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf", use_container_width=True)
        
        for log in data:
            with st.expander(f"📦 {log.get('job_code')} - {log.get('customer')}"):
                st.write(f"**Progress: {log.get('overall_progress')}%**")
                st.progress(int(log.get('overall_progress', 0))/100)
    else: st.info("No records found.")
