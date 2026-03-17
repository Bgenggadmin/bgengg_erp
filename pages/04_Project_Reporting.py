import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime
from fpdf import FPDF
import tempfile
import os
import pandas as pd
from PIL import Image
import io

# --- 1. SETUP ---
if 'page_config_set' not in st.session_state:
    st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
    st.session_state.page_config_set = True

conn = st.connection("supabase", type=SupabaseConnection, ttl=60)

# --- 2. MASTER MAPPING ---
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

# --- 3. PDF ENGINE ---
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    logo_path = None
    try:
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_logo:
                tmp_logo.write(logo_data); logo_path = tmp_logo.name
    except: pass

    for log in logs:
        pdf.add_page()
        pdf.set_fill_color(0, 51, 102); pdf.rect(0, 0, 210, 25, 'F')
        if logo_path: pdf.image(logo_path, x=12, y=5, h=15)
        pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 7); pdf.cell(130, 10, "B&G PROJECT REPORT", 0, 1, "L")
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "B", 10); pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 1, "L")
        
        pdf.ln(2); pdf.set_font("Arial", "B", 8); pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1 = HEADER_FIELDS[i]; f2 = HEADER_FIELDS[i+1] if i+1 < len(HEADER_FIELDS) else None
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1,''))}", 1, 0, 'L')
            if f2:
                pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
                pdf.cell(65, 7, f" {str(log.get(f2,''))}", 1, 1, 'L')
            else: pdf.ln(7)

        pdf.ln(5); ov_p = int(log.get('overall_progress', 0))
        pdf.set_font("Arial", "B", 10); pdf.cell(50, 8, f"Overall Progress: {ov_p}%")
        pdf.set_fill_color(230, 230, 230); pdf.rect(65, pdf.get_y() + 2, 120, 4, 'F')
        if ov_p > 0:
            pdf.set_fill_color(0, 102, 204); pdf.rect(65, pdf.get_y() + 2, (ov_p/100)*120, 4, 'F')
        
        pdf.ln(10); pdf.set_font("Arial", "B", 9); pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 8, " Milestone", 1, 0, 'L', True); pdf.cell(30, 8, " Status", 1, 0, 'C', True)
        pdf.cell(30, 8, " Progress", 1, 0, 'C', True); pdf.cell(80, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            pk = f"{s_key}_prog"; m_p = int(log.get(pk, 0)); status = str(log.get(s_key, 'Pending'))
            if status in ["Completed", "Approved", "Submitted"]: pdf.set_fill_color(144, 238, 144)
            elif status in ["In-Progress", "Hold", "Ordered"]: pdf.set_fill_color(255, 255, 204)
            else: pdf.set_fill_color(255, 255, 255)

            pdf.cell(50, 8, f" {label}", 1); pdf.cell(30, 8, f" {status}", 1, 0, 'C', True)
            cx, cy = pdf.get_x(), pdf.get_y()
            pdf.cell(30, 8, "", 1, 0); pdf.set_fill_color(240, 240, 240); pdf.rect(cx+3, cy+3, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76); pdf.rect(cx+3, cy+3, (m_p/100)*24, 2, 'F')
            pdf.set_xy(cx+30, cy); pdf.cell(80, 8, f" {str(log.get(n_key,'-'))}", 1, 1)

        pdf.ln(5); x_start, y_pos = 10, pdf.get_y()
        for i in range(4):
            try:
                photo_data = conn.client.storage.from_("progress-photos").download(f"{log['id']}_{i}.jpg")
                if photo_data:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(photo_data); pdf.image(tmp.name, x=x_start + (i * 48), y=y_pos, w=45, h=35); os.unlink(tmp.name)
            except: pass

    if logo_path:
        try: os.unlink(logo_path)
        except: pass
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- 4. DATA FETCH ---
@st.cache_data(ttl=300)
def get_reporting_masters():
    try:
        p_res = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
        return pd.DataFrame(p_res.data or [])
    except: return pd.DataFrame()

df_anchor = get_reporting_masters()
all_job_codes = df_anchor['job_no'].unique().tolist() if not df_anchor.empty else []

tab1, tab2 = st.tabs(["📝 New Entry", "📂 Archive"])

# --- 5. TAB 1: NEW ENTRY (WITH DUAL AUTOFILL) ---
with tab1:
    st.subheader("📋 Project Update")
    f_job = st.selectbox("Select Job Code", [""] + all_job_codes, key="job_lookup")
    
    anchor_row = df_anchor[df_anchor['job_no'] == f_job].iloc[0] if f_job else {}
    last_log = {}
    if f_job:
        l_res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        if l_res.data: 
            last_log = l_res.data[0]
            st.toast("🔄 Autofilled data from last update")

    with st.form("main_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        f_cust = c1.text_input("Customer", value=anchor_row.get('client_name', ""), disabled=True)
        f_eq = c2.text_input("Equipment Name", value=last_log.get('equipment', ""))
        f_eng = c3.text_input("Responsible Engineer", value=last_log.get('engineer') or anchor_row.get('anchor_person', ""))

        c4, c5, c6 = st.columns(3)
        f_po_n = c4.text_input("PO Number", value=anchor_row.get('po_no', ""), disabled=True)
        f_po_d = c5.text_input("PO Date", value=anchor_row.get('po_date', ""), disabled=True)
        f_p_del = c6.text_input("Official Delivery Date", value=anchor_row.get('po_delivery_date', ""), disabled=True)
        
        f_exp_dispatch = st.date_input("Revised Expected Dispatch", value=datetime.now())

        st.divider(); m_responses = {}
        opts = ["Pending", "NA", "In-Progress", "Submitted", "Approved", "Ordered", "Hold", "Completed"]
        
        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"; col1, col2, col3 = st.columns([1.5, 1, 2])
            prev_stat = last_log.get(skey, "Pending")
            def_idx = opts.index(prev_stat) if prev_stat in opts else 0
            m_responses[skey] = col1.selectbox(label, opts, index=def_idx, key=f"s_{skey}")
            m_responses[pk] = col2.slider("Prog %", 0, 100, value=int(last_log.get(pk, 0)), key=f"p_{skey}")
            m_responses[nkey] = col3.text_input("Remarks", value=last_log.get(nkey, ""), key=f"n_{skey}")

        f_progress = st.slider("📈 Overall Completion %", 0, 100, value=int(last_log.get('overall_progress', 0)))
        uploaded_photos = st.file_uploader("📸 Upload Photos (Max 4)", accept_multiple_files=True, type=['jpg','png'])

        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_job: st.error("Please select a Job Code")
            else:
                payload = {
                    "customer": anchor_row['client_name'], "job_code": f_job, "equipment": f_eq,
                    "po_no": anchor_row['po_no'], "po_date": str(anchor_row['po_date']), "engineer": f_eng,
                    "po_delivery_date": str(anchor_row['po_delivery_date']), "exp_dispatch_date": str(f_exp_dispatch),
                    "overall_progress": f_progress, **m_responses
                }
                res = conn.table("progress_logs").insert(payload).execute()
                if res.data and uploaded_photos:
                    for idx, photo in enumerate(uploaded_photos[:4]):
                        img = Image.open(photo); img.thumbnail((400, 400)); buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=50)
                        conn.client.storage.from_("progress-photos").upload(f"{res.data[0]['id']}_{idx}.jpg", buf.getvalue())
                st.success("✅ Update Saved!"); st.cache_data.clear(); st.rerun()

# --- 6. TAB 2: ARCHIVE ---
with tab2:
    st.subheader("📂 Report Archive")
    af1, af2, af3 = st.columns(3)
    sel_c = af1.selectbox("Filter Customer", ["All"] + sorted(df_anchor['client_name'].unique().tolist() if not df_anchor.empty else []))
    report_type = af2.selectbox("📅 Duration", ["All Time", "Current Week", "Current Month", "Custom Range"])
    
    start_d, end_d = None, None
    if report_type == "Custom Range":
        c_date = af3.date_input("Select Range", [datetime.now().date(), datetime.now().date()])
        if isinstance(c_date, list) and len(c_date) == 2: start_d, end_d = c_date

    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if sel_c != "All": query = query.eq("customer", sel_c)
    res = query.execute(); data = res.data if res else []
    
    filtered_data = []
    for log in data:
        try:
            log_date = datetime.strptime((log.get('created_at') or log.get('po_date'))[:10], "%Y-%m-%d").date()
            if report_type == "Current Week" and log_date.isocalendar()[1] != datetime.now().date().isocalendar()[1]: continue
            if report_type == "Current Month" and log_date.month != datetime.now().month: continue
            if report_type == "Custom Range" and not (start_d <= log_date <= end_d): continue
            filtered_data.append(log)
        except: continue

    if filtered_data:
        st.download_button("📥 Download PDF", data=generate_pdf(filtered_data), file_name="BG_Archive.pdf", mime="application/pdf", use_container_width=True)
        for log in filtered_data:
            with st.expander(f"📦 {log['job_code']} - {log['customer']}"):
                ov_p = int(log.get('overall_progress', 0)); st.progress(ov_p/100); st.write(f"**Overall: {ov_p}%**")
                m1, m2, m3 = st.columns(3)
                m1.metric("Engineer", log.get('engineer', 'N/A'))
                m2.metric("PO No", log.get('po_no', 'N/A'))
                m3.metric("Expected Dispatch", log.get('exp_dispatch_date', 'N/A'))
                for label, skey, nkey in MILESTONE_MAP:
                    pk = f"{skey}_prog"; mp = int(log.get(pk, 0)); c1, c2, c3 = st.columns([1.5, 1, 1.5])
                    c1.write(f"**{label}**"); c1.caption(f"Status: {log.get(skey)}"); with c2: st.progress(mp/100); c3.write(f"_{log.get(nkey, '-')}_")
                p_cols = st.columns(4)
                for i in range(4):
                    try:
                        p_url = conn.client.storage.from_("progress-photos").get_public_url(f"{log['id']}_{i}.jpg")
                        p_cols[i].image(p_url, use_container_width=True)
                    except: pass
