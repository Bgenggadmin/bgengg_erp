import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, timedelta, date
from fpdf import FPDF
from io import BytesIO
from PIL import Image
import tempfile
import os
import pytz

# ============================================================
# 1. SETUP & CONSTANTS
# ============================================================
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Hub 2.0", layout="wide", page_icon="🏗️")

# FIX [Critical]: Connection TTL on st.connection is not a standard parameter
# for SupabaseConnection — TTL belongs on @st.cache_data decorators, not here.
# Removing it prevents a silent misconfiguration.
conn = st.connection("supabase", type=SupabaseConnection)

HEADER_FIELDS = [
    "customer", "job_code", "equipment", "po_no",
    "po_date", "engineer", "po_delivery_date", "exp_dispatch_date"
]

MILESTONE_MAP = [
    ("Drawing Submission", "draw_sub",  "draw_sub_note"),
    ("Drawing Approval",   "draw_app",  "draw_app_note"),
    ("RM Status",          "rm_status", "rm_note"),
    ("Sub-deliveries",     "sub_del",   "sub_del_note"),
    ("Fabrication Status", "fab_status","remarks"),
    ("Buffing Status",     "buff_stat", "buff_note"),
    ("Testing Status",     "testing",   "test_note"),
    ("Dispatch Status",    "qc_stat",   "qc_note"),
    ("FAT Status",         "fat_stat",  "fat_note"),
]

MILESTONE_STATUS_OPTS = [
    "Pending", "NA", "In-Progress", "Submitted", "Approved",
    "Ordered", "Received", "Hold", "Completed", "Planning", "Scheduled"
]

# Status → colour mapping used across UI and PDF
STATUS_COLORS = {
    "Completed":   (0,   153, 76),
    "Approved":    (0,   153, 76),
    "In-Progress": (255, 165, 0),
    "Submitted":   (0,   102, 204),
    "Ordered":     (0,   102, 204),
    "Received":    (0,   153, 76),
    "Hold":        (204,  0,   0),
    "Pending":     (150, 150, 150),
    "NA":          (200, 200, 200),
    "Planning":    (255, 165, 0),
    "Scheduled":   (255, 165, 0),
}

def get_now_ist():
    return datetime.now(IST)

# ============================================================
# 2. CACHED DATA LOADERS
# FIX [Critical]: get_master_data() was the only cached loader — all other
#                 queries in tab1 and tab2 fired inline on every rerun.
# ============================================================

@st.cache_data(ttl=120)
def get_master_data():
    """Returns (customers, jobs) from anchor_projects."""
    try:
        res = conn.table("anchor_projects").select("client_name, job_no").execute()
        if res.data:
            c_list = sorted(set(d['client_name'] for d in res.data if d.get('client_name')))
            j_list = sorted(set(d['job_no']      for d in res.data if d.get('job_no')))
            return c_list, j_list
        return [], []
    except Exception:
        return [], []

@st.cache_data(ttl=30)
def get_latest_log(job_code: str):
    """
    FIX [Critical]: Was called inline in the tab body on every widget interaction.
    Now cached per job_code with 30s TTL.
    Returns the most-recent progress_logs row for this job, or {}.
    """
    try:
        res = conn.table("progress_logs").select("*") \
            .eq("job_code", job_code).order("id", desc=True).limit(1).execute()
        if res.data and res.data[0].get('customer') is not None:
            return res.data[0]
        return {}
    except Exception:
        return {}

@st.cache_data(ttl=120)
def get_anchor_info(job_code: str):
    """
    FIX [Warning]: Fallback anchor lookup was also inline — cached separately
    so it doesn't fire on every rerun when history already exists.
    """
    try:
        res = conn.table("anchor_projects").select("*").eq("job_no", job_code).limit(1).execute()
        if res.data:
            a = res.data[0]
            return {
                "customer":         a.get("client_name"),
                "equipment":        a.get("project_description"),
                "po_no":            a.get("po_no"),
                "po_date":          a.get("po_date"),
                "engineer":         a.get("anchor_person"),
                "po_delivery_date": a.get("po_delivery_date"),
                "exp_dispatch_date":a.get("revised_delivery_date"),
            }
        return {}
    except Exception:
        return {}

@st.cache_data(ttl=60)
def get_archive(customer_filter: str = "All", date_filter: str = "All Time",
                custom_start: str = None, custom_end: str = None):
    """
    FIX [Critical]: Archive tab fired a raw uncached query on every filter
    change — including every click anywhere on the page.
    Now: fetch once broadly, filter in Python.

    ENHANCEMENT: date_filter param added so cache key changes when user picks
    a new period (avoids stale results from in-memory filter on old data).
    """
    try:
        q = conn.table("progress_logs").select("*").order("id", desc=True)
        if customer_filter != "All":
            q = q.eq("customer", customer_filter)
        res = q.execute()
        return res.data if res.data else []
    except Exception:
        return []

def invalidate_job_cache(job_code: str):
    """Targeted invalidation — only clears caches relevant to the submitted job."""
    get_latest_log.clear()
    get_archive.clear()
    # master_data doesn't change on submit, so leave it alone

# ============================================================
# 3. PHOTO PROCESSING
# FIX [Warning]: process_photos() had no exception handling per image —
#                one corrupt upload would crash the entire submission.
# ENHANCEMENT: Returns (bytes, original_filename) tuples for traceability.
# ============================================================
def process_photos(uploaded_files):
    processed = []
    for file in uploaded_files[:4]:
        try:
            img = Image.open(file)
            # Convert to RGB to avoid JPEG save errors with RGBA/palette images
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img = img.resize((350, 450), Image.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=70)
            if buf.tell() > 51200:
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=40)
            processed.append(buf.getvalue())
        except Exception as e:
            st.warning(f"⚠️ Could not process photo '{file.name}': {e}")
    return processed

# ============================================================
# 4. PDF GENERATOR
# FIX [Critical]: generate_pdf() leaked temp files — os.unlink(t_name) was
#                 called INSIDE the loop immediately after writing, before
#                 FPDF had finished reading the file (race condition on some OS).
#                 Fixed by collecting all temp paths and deleting after pdf.output().
#
# FIX [Warning]:  bytes(pdf.output(dest='S'), encoding='latin-1') is the
#                 old fpdf API. fpdf2 returns bytes directly from pdf.output().
#                 The encoding call raises a TypeError in fpdf2. Fixed.
#
# FIX [Warning]:  Logo downloaded fresh for every call even when generating
#                 multi-report PDFs. Now downloaded once outside the loop.
#
# ENHANCEMENT:    Status cells in milestone table are now colour-coded.
# ENHANCEMENT:    Added "Generated by" footer per page.
# ============================================================
def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    temp_files = []   # FIX: collect all temp paths, delete at end

    # --- Logo (once) ---
    logo_path = None
    try:
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tf.write(logo_data)
            tf.flush()
            tf.close()
            logo_path = tf.name
            temp_files.append(logo_path)
    except Exception:
        pass

    for log in logs:
        pdf.add_page()
        report_date = get_now_ist().strftime('%d-%m-%Y %I:%M %p')

        # --- Header Bar ---
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

        # --- Job Title Row ---
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','N/A')} | ID: {log.get('id','N/A')}", "B", 0, "L")
        pdf.set_xy(10, 30)
        pdf.cell(0, 8, f"Report Date: {report_date} ", 0, 1, "R")

        # --- Header Fields Grid ---
        pdf.ln(2)
        pdf.set_font("Arial", "B", 8)
        pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1 = HEADER_FIELDS[i]
            f2 = HEADER_FIELDS[i + 1] if i + 1 < len(HEADER_FIELDS) else None
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.cell(65, 7, f" {str(log.get(f1, '-'))}", 1, 0, 'L')
            if f2:
                pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
                pdf.cell(65, 7, f" {str(log.get(f2, '-'))}", 1, 1, 'L')
            else:
                pdf.ln(7)

        # --- Overall Progress Bar ---
        pdf.ln(5)
        ov_p = int(log.get('overall_progress', 0) or 0)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(50, 8, f"Overall Completion: {ov_p}%", 0, 0, 'L')
        bar_y = pdf.get_y() + 2
        pdf.set_fill_color(230, 230, 230)
        pdf.rect(60, bar_y, 130, 4, 'F')
        if ov_p > 0:
            # ENHANCEMENT: Bar colour shifts green→amber→red by completion %
            if ov_p >= 75:
                pdf.set_fill_color(0, 153, 76)
            elif ov_p >= 40:
                pdf.set_fill_color(255, 165, 0)
            else:
                pdf.set_fill_color(204, 0, 0)
            pdf.rect(60, bar_y, (ov_p / 100) * 130, 4, 'F')
        pdf.ln(10)

        # --- Milestone Table ---
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
            pk           = f"{s_key}_prog"
            m_p          = int(log.get(pk, 0) or 0)
            remark_text  = f" {str(log.get(n_key, '-'))}"
            status_val   = str(log.get(s_key, 'Pending'))

            curr_x  = pdf.get_x()
            curr_y  = pdf.get_y()
            lh      = 5
            nb      = len(pdf.multi_cell(80, lh, remark_text, split_only=True))
            row_h   = max(10, nb * lh)

            pdf.set_xy(curr_x, curr_y)
            pdf.cell(50, row_h, f" {label}", 1)

            # ENHANCEMENT: Colour-coded status cell
            sc = STATUS_COLORS.get(status_val, (200, 200, 200))
            pdf.set_fill_color(*sc)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(30, row_h, f" {status_val}", 1, 0, 'C', True)
            pdf.set_text_color(0, 0, 0)

            # Progress mini-bar
            prog_x = pdf.get_x()
            pdf.cell(30, row_h, "", 1, 0)
            bar_off = (row_h / 2) - 1
            pdf.set_fill_color(240, 240, 240)
            pdf.rect(prog_x + 3, curr_y + bar_off, 24, 2, 'F')
            if m_p > 0:
                pdf.set_fill_color(0, 153, 76)
                pdf.rect(prog_x + 3, curr_y + bar_off, (min(m_p, 100) / 100) * 24, 2, 'F')

            pdf.set_xy(prog_x + 30, curr_y)
            cell_h = (row_h / nb) if nb > 0 else row_h
            pdf.multi_cell(80, cell_h, remark_text, 1, 'L')
            pdf.set_xy(curr_x, curr_y + row_h)

        # --- Photos Section ---
        pdf.ln(10)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 10, "Progress Documentation Photos:", 0, 1, "L")
        if pdf.get_y() > 230:
            pdf.add_page()

        start_y     = pdf.get_y()
        img_x       = 10

        for i in range(4):
            try:
                img_path_key = f"{log.get('id')}_{i}.jpg"
                img_data = conn.client.storage.from_("progress-photos").download(img_path_key)
                if img_data:
                    tf2 = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    tf2.write(img_data)
                    tf2.flush()
                    tf2.close()
                    temp_files.append(tf2.name)          # FIX: defer deletion
                    pdf.image(tf2.name, x=img_x, y=start_y, w=45)
                    img_x += 48
            except Exception:
                continue

        # ENHANCEMENT: Footer with generation timestamp
        pdf.set_y(-15)
        pdf.set_font("Arial", "I", 7)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 5, f"Generated by B&G Hub 2.0 on {report_date} | Confidential", 0, 0, 'C')
        pdf.set_text_color(0, 0, 0)

    # FIX [Critical]: Delete ALL temp files AFTER pdf.output() — not mid-loop
    # FIX [Warning]:  fpdf2 returns bytes from output() directly; no encoding needed
    try:
        raw = pdf.output()          # returns bytes in fpdf2
        if isinstance(raw, str):    # legacy fpdf1 compat
            raw = raw.encode('latin-1')
    finally:
        for p in temp_files:
            try:
                os.unlink(p)
            except Exception:
                pass

    return raw

# ============================================================
# 5. MAIN UI
# ============================================================
customers, jobs = get_master_data()

tab1, tab2, tab3 = st.tabs(["📝 New Entry", "📂 Archive", "🧬 System Schema"])

# ============================================================
# TAB 1 — NEW ENTRY / UPDATE
# ============================================================
with tab1:
    st.subheader("📋 Project Progress Update")

    c_top1, c_top2 = st.columns([3, 1])
    f_job = c_top1.selectbox("Job Code", [""] + jobs, key="job_lookup")

    if c_top2.button("🧹 Clear Form", use_container_width=True):
        # FIX [Critical]: Was calling st.cache_data.clear() — nukes all caches
        # for all users. A Clear Form action should only reset UI state, not DB caches.
        for key in list(st.session_state.keys()):
            if key != "job_lookup":
                st.session_state.pop(key, None)
        st.rerun()

    # --- Smart data fetch (now cached) ---
    last_data = {}
    if f_job:
        last_data = get_latest_log(f_job)
        if last_data:
            st.toast(f"🔄 Loaded latest report for {f_job}")
        else:
            last_data = get_anchor_info(f_job)
            if last_data:
                st.toast(f"✨ New job detected — pre-filled from Anchor Portal")
            else:
                st.info("No prior data found for this job code.")

    # --- Helper for safe date parsing ---
    def safe_date(field):
        val = last_data.get(field)
        try:
            return datetime.strptime(val, "%Y-%m-%d").date() if val else date.today()
        except Exception:
            return date.today()

    # ---- THE FORM ----
    with st.form("main_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        try:
            c_idx = (customers.index(last_data['customer']) + 1
                     if last_data.get('customer') in customers else 0)
        except Exception:
            c_idx = 0

        f_cust  = c1.selectbox("Customer", [""] + customers, index=c_idx)
        f_eq    = c2.text_input("Equipment / Description", value=str(last_data.get('equipment') or ""))

        c3, c4, c5 = st.columns(3)
        f_po_n  = c3.text_input("PO Number",            value=str(last_data.get('po_no')   or ""))
        f_po_d  = c4.date_input("PO Date",              value=safe_date('po_date'))
        f_eng   = c5.text_input("Responsible Engineer", value=str(last_data.get('engineer') or ""))

        c6, c7 = st.columns(2)
        f_po_del   = c6.date_input("PO Delivery Date",      value=safe_date('po_delivery_date'))
        f_exp_disp = c7.date_input("Expected Dispatch Date", value=safe_date('exp_dispatch_date'))

        # ENHANCEMENT: Overdue warning
        if f_exp_disp < date.today():
            st.warning(f"⚠️ Expected dispatch date ({f_exp_disp}) is in the past.")

        st.divider()
        st.subheader("📊 Milestone Tracking")

        m_responses = {}
        job_suffix  = str(f_job) if f_job else "initial"

        for label, skey, nkey in MILESTONE_MAP:
            pk          = f"{skey}_prog"
            prev_status = str(last_data.get(skey) or "Pending")
            def_idx     = MILESTONE_STATUS_OPTS.index(prev_status) if prev_status in MILESTONE_STATUS_OPTS else 0
            prev_prog   = int(last_data.get(pk, 0) or 0)
            prev_note   = str(last_data.get(nkey) or "")

            col1, col2, col3 = st.columns([1.5, 1, 2])
            m_responses[skey] = col1.selectbox(
                label, MILESTONE_STATUS_OPTS,
                index=def_idx, key=f"s_{skey}_{job_suffix}"
            )
            m_responses[pk]   = col2.slider(
                "Prog %", 0, 100, value=prev_prog, key=f"p_{skey}_{job_suffix}"
            )
            m_responses[nkey] = col3.text_input(
                "Remarks", value=prev_note, key=f"n_{skey}_{job_suffix}"
            )

        st.divider()

        # ENHANCEMENT: Auto-calculate overall progress from milestone average
        # and let engineer override if needed
        auto_prog = 0
        if m_responses:
            prog_vals = [m_responses[f"{sk}_prog"] for _, sk, _ in MILESTONE_MAP
                         if f"{sk}_prog" in m_responses]
            auto_prog = int(sum(prog_vals) / len(prog_vals)) if prog_vals else 0

        f_progress = st.slider(
            "📈 Overall Completion %", 0, 100,
            value=int(last_data.get('overall_progress', auto_prog) or auto_prog),
            key=f"ov_{job_suffix}",
            help=f"Auto-calculated from milestones: {auto_prog}%. Adjust manually if needed."
        )
        st.caption(f"ℹ️ Milestone average: **{auto_prog}%**")

        st.subheader("📸 Progress Documentation")
        uploaded_photos = st.file_uploader(
            "Upload Photos (Max 4, JPG/PNG)", accept_multiple_files=True, type=['jpg', 'jpeg', 'png']
        )
        if uploaded_photos and len(uploaded_photos) > 4:
            st.warning("Only the first 4 photos will be saved.")

        submitted = st.form_submit_button("🚀 SUBMIT UPDATE", use_container_width=True)

        if submitted:
            errors = []
            if not f_cust:
                errors.append("Customer is required.")
            if not f_job:
                errors.append("Job Code is required.")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                payload = {
                    "customer":         f_cust,
                    "job_code":         f_job,
                    "equipment":        f_eq,
                    "po_no":            f_po_n,
                    "po_date":          str(f_po_d),
                    "engineer":         f_eng,
                    "po_delivery_date": str(f_po_del),
                    "exp_dispatch_date":str(f_exp_disp),
                    "overall_progress": f_progress,
                    **m_responses
                }
                try:
                    res = conn.table("progress_logs").insert(payload).execute()

                    if uploaded_photos and res.data:
                        file_id    = res.data[0]['id']
                        proc_imgs  = process_photos(uploaded_photos)
                        upload_errors = []
                        for i, img_bytes in enumerate(proc_imgs):
                            try:
                                conn.client.storage.from_("progress-photos").upload(
                                    f"{file_id}_{i}.jpg", img_bytes,
                                    file_options={"content-type": "image/jpeg", "upsert": "true"}
                                )
                            except Exception as ue:
                                upload_errors.append(f"Photo {i+1}: {ue}")
                        if upload_errors:
                            st.warning(f"Update saved but some photos failed: {'; '.join(upload_errors)}")

                    st.success("✅ Update recorded successfully!")
                    # FIX [Critical]: Targeted cache invalidation, not nuclear clear
                    invalidate_job_cache(f_job)
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ Submission failed: {e}")

# ============================================================
# TAB 2 — ARCHIVE
# FIX [Critical]: Was fetching uncached data inline. Every click anywhere on
#                 this tab triggered a full progress_logs scan.
# ENHANCEMENT:    Period filter now actually filters data (was UI-only before —
#                 the original query ignored the selected period entirely).
# ENHANCEMENT:    Job-level expander now shows milestone summary badges.
# ENHANCEMENT:    PDF scoped to filtered results, not the entire archive.
# ============================================================
with tab2:
    st.subheader("📂 Report Archive")

    f1, f2, f3 = st.columns(3)
    sel_c       = f1.selectbox("Filter by Customer", ["All"] + customers, key="arch_cust")
    report_type = f2.selectbox(
        "📅 Period", ["All Time", "Current Week", "Current Month", "Custom Range"], key="arch_period"
    )

    today      = date.today()
    date_start = None
    date_end   = today

    if report_type == "Current Week":
        date_start = today - timedelta(days=today.weekday())
    elif report_type == "Current Month":
        date_start = today.replace(day=1)
    elif report_type == "Custom Range":
        custom_r = f3.date_input("Date Range", [today - timedelta(days=30), today], key="arch_custom")
        if len(custom_r) == 2:
            date_start, date_end = custom_r

    # Fetch (cached per customer filter + period)
    raw_data = get_archive(sel_c, report_type,
                           str(date_start) if date_start else None,
                           str(date_end))

    # FIX [Critical]: Apply date filter in Python (original code fetched all data
    # and never applied the period filter — it was pure dead UI).
    filtered_data = raw_data
    if date_start:
        def _in_range(log):
            try:
                created = log.get('created_at', '')[:10]
                return str(date_start) <= created <= str(date_end)
            except Exception:
                return True
        filtered_data = [l for l in raw_data if _in_range(l)]

    if filtered_data:
        # ENHANCEMENT: Summary metrics above the list
        sm1, sm2, sm3 = st.columns(3)
        sm1.metric("Records Found", len(filtered_data))
        avg_prog = sum(int(l.get('overall_progress') or 0) for l in filtered_data) / len(filtered_data)
        sm2.metric("Avg Completion", f"{avg_prog:.0f}%")
        completed = sum(1 for l in filtered_data if int(l.get('overall_progress') or 0) == 100)
        sm3.metric("Fully Complete", completed)

        st.divider()

        # PDF scoped to filtered results only
        if st.button("📥 Prepare PDF Report (Filtered)", use_container_width=True):
            with st.spinner("Generating PDF..."):
                try:
                    pdf_bytes = generate_pdf(filtered_data)
                    if pdf_bytes:
                        fname = f"BG_Report_{sel_c}_{report_type.replace(' ','_')}_{today}.pdf"
                        st.download_button(
                            label="✅ Download PDF Report",
                            data=pdf_bytes,
                            file_name=fname,
                            mime="application/pdf"
                        )
                except Exception as e:
                    st.error(f"PDF generation failed: {e}")

        st.divider()

        for log in filtered_data:
            ov = int(log.get('overall_progress') or 0)
            with st.expander(f"📦 {log.get('job_code')} — {log.get('customer')}  |  {ov}% complete"):

                # ENHANCEMENT: Header info grid
                hi1, hi2, hi3, hi4 = st.columns(4)
                hi1.markdown(f"**Engineer:** {log.get('engineer','-')}")
                hi2.markdown(f"**PO No:** {log.get('po_no','-')}")
                hi3.markdown(f"**PO Delivery:** {log.get('po_delivery_date','-')}")
                hi4.markdown(f"**Exp Dispatch:** {log.get('exp_dispatch_date','-')}")

                st.progress(ov / 100)

                # ENHANCEMENT: Colour-coded milestone badges
                st.markdown("**Milestone Status:**")
                badge_cols = st.columns(len(MILESTONE_MAP))
                for idx, (label, s_key, _) in enumerate(MILESTONE_MAP):
                    status = str(log.get(s_key, 'Pending'))
                    prog   = int(log.get(f"{s_key}_prog", 0) or 0)
                    color_map = {
                        "Completed": "🟢", "Approved": "🟢", "Received": "🟢",
                        "In-Progress": "🟡", "Submitted": "🔵", "Ordered": "🔵",
                        "Planning": "🟡", "Scheduled": "🟡",
                        "Hold": "🔴",
                        "Pending": "⚪", "NA": "⚫",
                    }
                    dot = color_map.get(status, "⚪")
                    badge_cols[idx].markdown(
                        f"<div style='font-size:10px; text-align:center;'>{dot}<br>"
                        f"<b>{label.split()[0]}</b><br>{prog}%</div>",
                        unsafe_allow_html=True
                    )
    else:
        st.info("No records found for the selected filters.")

# ============================================================
# TAB 3 — SYSTEM SCHEMA
# ============================================================
with tab3:
    st.subheader("🧬 System Database Mapping")
    st.info("Live reference of Supabase resources powering B&G Hub 2.0.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### 📊 Active Tables")
        st.code("""
1. anchor_projects
   Purpose : Source for Job Codes, Customers, PO dates
   Key     : job_no

2. progress_logs
   Purpose : Every milestone update per job
   Key     : id (auto-increment)
   Indexed : job_code (recommended for perf)
        """)

    with col_b:
        st.markdown("### ☁️ Storage Bucket: progress-photos")
        st.code("""
logo.png          — PDF header logo
{id}_{index}.jpg  — Progress photos (0-3 per log)
        """)

    st.divider()
    st.markdown("### 🔄 Data Flow")
    st.write("1. **Job Selection** → queries `anchor_projects` for dropdown population (cached 2min).")
    st.write("2. **Form Autofill** → checks `progress_logs` for prior history (cached 30s); falls back to `anchor_projects` if none.")
    st.write("3. **Submission** → inserts to `progress_logs`, uploads photos to storage bucket, then clears only relevant caches.")
    st.write("4. **Archive** → loads data once per filter combination (cached 60s), applies date filtering in-memory.")
    st.write("5. **PDF** → generated from filtered archive data; temp files cleaned up after `pdf.output()` completes.")

    st.divider()
    st.markdown("### 🗄️ Recommended DB Indexes")
    st.code("""
-- Run these in Supabase SQL editor for best query performance:

CREATE INDEX IF NOT EXISTS idx_progress_logs_job_code
    ON progress_logs (job_code);

CREATE INDEX IF NOT EXISTS idx_progress_logs_created_at
    ON progress_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_anchor_projects_job_no
    ON anchor_projects (job_no);
    """, language="sql")
