import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, timedelta
from fpdf import FPDF
from io import BytesIO
from PIL import Image
import tempfile
import os

# ──────────────────────────────────────────────
# 1. SETUP & CONSTANTS
# ──────────────────────────────────────────────
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection, ttl=60)

HEADER_FIELDS = [
    "customer",         "job_code",
    "equipment",        "po_no",
    "po_date",          "actual_po_date",       # actual_po_date NEW
    "engineer",         "po_delivery_date",
    "exp_dispatch_date","draw_app_date",         # draw_app_date NEW
]

MILESTONE_MAP = [
    ("Drawing Submission",  "draw_sub",  "draw_sub_note"),
    ("Drawing Approval",    "draw_app",  "draw_app_note"),
    ("RM Status",           "rm_status", "rm_note"),
    ("Sub-deliveries",      "sub_del",   "sub_del_note"),
    ("Fabrication Status",  "fab_status","remarks"),
    ("Buffing Status",      "buff_stat", "buff_note"),
    ("Testing Status",      "testing",   "test_note"),
    ("Dispatch Status",     "qc_stat",   "qc_note"),
    ("FAT Status",          "fat_stat",  "fat_note"),
]

# ──────────────────────────────────────────────
# 2. ENGINE
# ──────────────────────────────────────────────
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


def format_field_label(field: str) -> str:
    """Human-readable label for header fields used in PDF."""
    labels = {
        "customer":         "Customer",
        "job_code":         "Job Code",
        "equipment":        "Equipment",
        "po_no":            "PO Number",
        "po_date":          "PO Date (Printed)",
        "actual_po_date":   "Actual PO Received",   # NEW
        "engineer":         "Engineer",
        "po_delivery_date": "PO Delivery Date",
        "exp_dispatch_date":"Exp. Dispatch Date",
        "draw_app_date":    "Drawing Approval Date", # NEW
    }
    return labels.get(field, field.replace("_", " ").title())


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
    except:
        pass

    for log in logs:
        pdf.add_page()
        report_date = datetime.now().strftime('%d-%m-%Y')

        # ── Header banner ──
        pdf.set_fill_color(0, 51, 102)
        pdf.rect(0, 0, 210, 25, 'F')
        if logo_path:
            pdf.image(logo_path, x=12, y=5, h=15)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 5)
        pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 10)
        pdf.set_xy(70, 14)
        pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")

        # ── Job / Date row ──
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','N/A')} | ID: {log.get('id','N/A')}", "B", 0, "L")
        pdf.set_xy(10, 30)
        pdf.cell(0, 8, f"Report Date: {report_date} ", 0, 1, "R")

        # ── Header fields table (2-column layout) ──
        pdf.ln(2)
        pdf.set_font("Arial", "B", 8)
        pdf.set_fill_color(240, 240, 240)

        for i in range(0, len(HEADER_FIELDS), 2):
            f1 = HEADER_FIELDS[i]
            f2 = HEADER_FIELDS[i + 1] if i + 1 < len(HEADER_FIELDS) else None

            pdf.cell(35, 7, f" {format_field_label(f1)}", 1, 0, 'L', True)
            pdf.cell(60, 7, f" {str(log.get(f1, '-'))}", 1, 0, 'L')
            if f2:
                pdf.cell(35, 7, f" {format_field_label(f2)}", 1, 0, 'L', True)
                pdf.cell(60, 7, f" {str(log.get(f2, '-'))}", 1, 1, 'L')
            else:
                pdf.ln(7)

        # ── Overall progress bar ──
        pdf.ln(5)
        ov_p = int(log.get('overall_progress', 0) or 0)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(50, 8, f"Overall Completion: {ov_p}%", 0, 0, 'L')
        pdf.set_fill_color(230, 230, 230)
        pdf.rect(60, pdf.get_y() + 2, 130, 4, 'F')
        if ov_p > 0:
            pdf.set_fill_color(0, 82, 164)
            pdf.rect(60, pdf.get_y() + 2, (ov_p / 100) * 130, 4, 'F')
        pdf.ln(10)

        # ── Milestone table header ──
        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(0, 51, 102)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 8, " Milestone Item",  1, 0, 'L', True)
        pdf.cell(30, 8, " Status",          1, 0, 'C', True)
        pdf.cell(30, 8, " Progress",        1, 0, 'C', True)
        pdf.cell(80, 8, " Remarks",         1, 1, 'L', True)

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "", 8)

        for label, s_key, n_key in MILESTONE_MAP:
            pk = f"{s_key}_prog"
            m_p = int(log.get(pk, 0) or 0)
            remark_text = f" {str(log.get(n_key, '-'))}"

            curr_x = pdf.get_x()
            curr_y = pdf.get_y()

            line_height = 5
            nb_lines = len(pdf.multi_cell(80, line_height, remark_text, split_only=True))
            row_height = max(10, nb_lines * line_height)

            pdf.set_xy(curr_x, curr_y)
            pdf.cell(50, row_height, f" {label}", 1)
            pdf.cell(30, row_height, f" {str(log.get(s_key, 'Pending'))}", 1, 0, 'C')

            prog_x = pdf.get_x()
            pdf.cell(30, row_height, "", 1, 0)
            bar_offset_y = (row_height / 2) - 1
            pdf.set_fill_color(240, 240, 240)
            pdf.rect(prog_x + 3, curr_y + bar_offset_y, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76)
                pdf.rect(prog_x + 3, curr_y + bar_offset_y, (min(m_p, 100) / 100) * 24, 2, 'F')

            pdf.set_xy(prog_x + 30, curr_y)
            pdf.multi_cell(80, (row_height / nb_lines) if nb_lines > 0 else row_height, remark_text, 1, 'L')
            pdf.set_xy(curr_x, curr_y + row_height)

        # ── Photos ──
        pdf.ln(10)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, "Progress Documentation Photos:", 0, 1, "L")

        if pdf.get_y() > 230:
            pdf.add_page()

        start_y = pdf.get_y()
        img_x = 10

        for i in range(4):
            try:
                img_path = f"{log.get('id')}_{i}.jpg"
                img_data = conn.client.storage.from_("progress-photos").download(img_path)
                if img_data:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                        tmp_img.write(img_data)
                        tmp_img.flush()
                        pdf.image(tmp_img.name, x=img_x, y=start_y, w=45)
                        img_x += 48
                        t_name = tmp_img.name
                        os.unlink(t_name)
            except:
                continue

    if logo_path and os.path.exists(logo_path):
        os.unlink(logo_path)

    output = pdf.output(dest='S')
    return output if isinstance(output, bytes) else bytes(output, encoding='latin-1')


# ──────────────────────────────────────────────
# 3. DATA FETCH
# ──────────────────────────────────────────────
@st.cache_data(ttl=60)
def get_master_data():
    try:
        res = conn.table("anchor_projects").select("client_name, job_no").execute()
        if res.data:
            c_list = list(set([d['client_name'] for d in res.data if d.get('client_name')]))
            j_list = list(set([d['job_no']     for d in res.data if d.get('job_no')]))
            return sorted(c_list), sorted(j_list)
        return [], []
    except:
        return [], []


customers, jobs = get_master_data()

# ──────────────────────────────────────────────
# 4. HELPER
# ──────────────────────────────────────────────
def safe_date(field, data=None):
    """Parse a date string from data dict; fall back to today."""
    src = data if data is not None else {}
    val = src.get(field)
    try:
        return datetime.strptime(val, "%Y-%m-%d") if val else datetime.now()
    except:
        return datetime.now()


# ──────────────────────────────────────────────
# 5. MAIN UI
# ──────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🧬 System Schema"])

# ══════════════════════════════════════════════
# TAB 1 — NEW ENTRY
# ══════════════════════════════════════════════
with tab1:
    st.subheader("📋 Project Update")

    if "form_reset" not in st.session_state:
        st.session_state.form_reset = False

    c_top1, c_top2 = st.columns([3, 1])
    f_job = c_top1.selectbox("Job Code", [""] + jobs, key="job_lookup")

    if c_top2.button("🧹 Clear Form", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    last_data = {}

    if f_job:
        res = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        has_valid_history = res and res.data and res.data[0].get('customer') is not None

        if has_valid_history:
            last_data = res.data[0]
            st.toast(f"🔄 Loaded latest report for {f_job}")
        else:
            anchor_res = conn.table("anchor_projects").select("*").eq("job_no", f_job).limit(1).execute()
            if anchor_res and anchor_res.data:
                a_info = anchor_res.data[0]
                last_data = {
                    "customer":         a_info.get("client_name"),
                    "equipment":        a_info.get("project_description"),
                    "po_no":            a_info.get("po_no"),
                    "po_date":          a_info.get("po_date"),
                    "actual_po_date":   a_info.get("actual_po_date"),   # NEW — pull from anchor if available
                    "draw_app_date":    a_info.get("draw_app_date"),    # NEW — pull from anchor if available
                    "engineer":         a_info.get("anchor_person"),
                    "po_delivery_date": a_info.get("po_delivery_date"),
                    "exp_dispatch_date":a_info.get("revised_delivery_date"),
                }
                st.toast("✨ New Job: Pulled from Anchor Portal")

    # ── THE FORM ──
    with st.form("main_form", clear_on_submit=True):

        # Row 1 — Customer / Equipment
        c1, c2 = st.columns(2)
        try:
            c_idx = customers.index(last_data['customer']) + 1 if last_data.get('customer') in customers else 0
        except:
            c_idx = 0

        f_cust = c1.selectbox("Customer", [""] + customers, index=c_idx)
        f_eq   = c2.text_input("Equipment", value=str(last_data.get('equipment') or ""))

        # Row 2 — PO Number / PO Date (printed) / Actual PO Received Date
        c3, c4, c5 = st.columns(3)
        f_po_n        = c3.text_input("PO Number",              value=str(last_data.get('po_no') or ""))
        f_po_d        = c4.date_input("PO Date (Printed)",      value=safe_date('po_date',        last_data))
        f_actual_po_d = c5.date_input("Actual PO Received Date",value=safe_date('actual_po_date', last_data))  # ← NEW

        # Row 3 — Engineer / PO Delivery Date / Expected Dispatch Date
        c6, c7, c8 = st.columns(3)
        f_eng     = c6.text_input("Responsible Engineer",   value=str(last_data.get('engineer') or ""))
        f_po_del  = c7.date_input("PO Delivery Date",       value=safe_date('po_delivery_date',  last_data))
        f_exp_disp= c8.date_input("Expected Dispatch Date", value=safe_date('exp_dispatch_date', last_data))

        # Row 4 — Drawing Approval Date (standalone, prominent)
        st.markdown("---")
        col_da1, col_da2, col_da3 = st.columns([1, 1, 2])
        f_draw_app_d = col_da1.date_input(                                                          # ← NEW
            "📐 Drawing Approval Date",
            value=safe_date('draw_app_date', last_data),
            help="Date when customer officially approved the drawing. "
                 "Saved to both progress_logs and optionally anchor_projects."
        )
        col_da2.markdown("<br>", unsafe_allow_html=True)  # vertical spacer
        col_da3.info(
            "💡 Drawing Approval Date and Actual PO Received Date are stored in **progress_logs** "
            "and can optionally be synced back to **anchor_projects** for cross-app visibility."
        )

        st.divider()

        # ── Milestone Tracking ──
        st.subheader("📊 Milestone Tracking")
        m_responses = {}
        opts = [
            "Pending", "NA", "In-Progress", "Submitted", "Approved",
            "Ordered", "Received", "Hold", "Completed", "Planning", "Scheduled"
        ]
        job_suffix = str(f_job) if f_job else "initial"

        for label, skey, nkey in MILESTONE_MAP:
            pk = f"{skey}_prog"
            col1, col2, col3 = st.columns([1.5, 1, 2])
            prev_status = str(last_data.get(skey) or "Pending")
            def_idx     = opts.index(prev_status) if prev_status in opts else 0
            prev_prog   = int(last_data.get(pk, 0) or 0)
            prev_note   = str(last_data.get(nkey) or "")

            m_responses[skey] = col1.selectbox(label, opts, index=def_idx, key=f"s_{skey}_{job_suffix}")
            m_responses[pk]   = col2.slider("Prog %", 0, 100, value=prev_prog, key=f"p_{skey}_{job_suffix}")
            m_responses[nkey] = col3.text_input("Remarks", value=prev_note, key=f"n_{skey}_{job_suffix}")

            # ── If this is the Drawing Approval row, show the date inline for easy reference ──
            if skey == "draw_app":
                col1.caption(f"📅 Approval date: {f_draw_app_d}")

        st.divider()
        f_progress = st.slider(
            "📈 Overall Completion %", 0, 100,
            value=int(last_data.get('overall_progress', 0) or 0),
            key=f"ov_{job_suffix}"
        )

        st.subheader("📸 Progress Documentation")
        uploaded_photos = st.file_uploader(
            "Upload Photos (Max 4)", accept_multiple_files=True, type=['jpg', 'png']
        )

        # ── Submit ──
        if st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True):
            if not f_cust or not f_job:
                st.error("Please select Customer and Job Code")
            else:
                payload = {
                    "customer":         f_cust,
                    "job_code":         f_job,
                    "equipment":        f_eq,
                    "po_no":            f_po_n,
                    "po_date":          str(f_po_d),
                    "actual_po_date":   str(f_actual_po_d),   # ← NEW
                    "draw_app_date":    str(f_draw_app_d),    # ← NEW
                    "engineer":         f_eng,
                    "po_delivery_date": str(f_po_del),
                    "exp_dispatch_date":str(f_exp_disp),
                    "overall_progress": f_progress,
                    **m_responses,
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

                st.success("✅ Update Recorded Successfully!")
                st.cache_data.clear()
                st.rerun()


# ══════════════════════════════════════════════
# TAB 2 — ARCHIVE
# ══════════════════════════════════════════════
with tab2:
    st.subheader("📂 Report Archive")

    f1, f2, f3 = st.columns(3)
    sel_c       = f1.selectbox("Filter Customer", ["All"] + customers)
    report_type = f2.selectbox("📅 Period", ["All Time", "Current Week", "Current Month", "Custom Range"])

    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if sel_c != "All":
        query = query.eq("customer", sel_c)

    res  = query.execute()
    data = res.data if res.data else []

    if data:
        if st.button("📥 Prepare PDF for Download", use_container_width=True):
            with st.spinner("Generating PDF..."):
                pdf_bytes = generate_pdf(data)
                if pdf_bytes:
                    st.download_button(
                        label="✅ Click here to Save PDF",
                        data=pdf_bytes,
                        file_name="BG_Report.pdf",
                        mime="application/pdf"
                    )

        for log in data:
            with st.expander(f"📦 {log.get('job_code')} — {log.get('customer')}"):
                col_a, col_b, col_c, col_d = st.columns(4)
                col_a.metric("Overall", f"{log.get('overall_progress', 0)}%")
                col_b.metric("PO Date (Printed)",     log.get('po_date',          '—'))
                col_c.metric("Actual PO Received",    log.get('actual_po_date',   '—'))  # ← NEW
                col_d.metric("Drawing Approval Date", log.get('draw_app_date',    '—'))  # ← NEW

                st.progress(int(log.get('overall_progress') or 0) / 100)

                # milestone summary
                ms_cols = st.columns(3)
                for idx, (label, skey, _) in enumerate(MILESTONE_MAP):
                    ms_cols[idx % 3].markdown(
                        f"**{label}:** {log.get(skey, 'Pending')}"
                    )
    else:
        st.info("No records found for the selected filter.")


# ══════════════════════════════════════════════
# TAB 3 — SYSTEM SCHEMA
# ══════════════════════════════════════════════
with tab3:
    st.subheader("🧬 System Database Mapping")
    st.info("This tab shows which Supabase resources power this application.")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### 📊 Active Tables")
        st.code("""
1. anchor_projects
   - Purpose: Source for Job Codes, Customers, PO dates.
   - Primary Key: job_no
   - NEW columns:
       actual_po_date  DATE
       draw_app_date   DATE

2. progress_logs
   - Purpose: Stores every progress update & milestone.
   - Used for: PDFs and history.
   - NEW columns:
       actual_po_date  DATE
       draw_app_date   DATE
        """)

    with col_b:
        st.markdown("### ☁️ Storage & Assets")
        st.code("""
1. Bucket: 'progress-photos'
   - logo.png          : PDF Header logo.
   - {id}_{index}.jpg  : Project photos.
        """)

    st.divider()
    st.markdown("### 🗄️ SQL — Run in Supabase SQL Editor")
    st.code("""
-- anchor_projects
ALTER TABLE anchor_projects
  ADD COLUMN IF NOT EXISTS actual_po_date DATE,
  ADD COLUMN IF NOT EXISTS draw_app_date  DATE;

-- progress_logs
ALTER TABLE progress_logs
  ADD COLUMN IF NOT EXISTS actual_po_date DATE,
  ADD COLUMN IF NOT EXISTS draw_app_date  DATE;
    """, language="sql")

    st.divider()
    st.markdown("### 🔄 Logic Flow")
    st.write("1. **Job Selection:** App queries `anchor_projects` to populate dropdown.")
    st.write("2. **Form Autofill:** Checks `progress_logs` for history; falls back to `anchor_projects` (now including `actual_po_date` and `draw_app_date`).")
    st.write("3. **New Fields:** `actual_po_date` (real date PO was received) and `draw_app_date` (date drawings were formally approved) are captured on every submission.")
    st.write("4. **Submission:** All data saved to `progress_logs`; images uploaded to storage bucket.")
    st.write("5. **PDF:** Both new date fields appear in the header table of every report.")
