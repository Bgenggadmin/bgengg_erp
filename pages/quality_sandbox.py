import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz
import io
import requests
from tempfile import NamedTemporaryFile
import os
from PIL import Image

# fpdf2 + pypdf are optional — only needed for Master Data Book PDF generation
try:
    from fpdf import FPDF
    from pypdf import PdfWriter, PdfReader
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# ============================================================
# 1. SETUP
# ============================================================
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(
    page_title="B&G Quality Portal",
    layout="wide",
    page_icon="🔍"
)
conn = st.connection("supabase", type=SupabaseConnection)

# ============================================================
# 2. UTILITIES
# ============================================================
def get_now_ist():
    return datetime.now(IST)

def safe_write(fn, success_msg="Saved!", error_prefix="DB Error"):
    try:
        fn()
        st.success(success_msg)
        return True
    except Exception as e:
        st.error(f"{error_prefix}: {e}")
        return False

def fmt_date(d):
    try:
        return pd.to_datetime(d).strftime('%d-%m-%Y')
    except Exception:
        return str(d) if d else 'N/A'

# ============================================================
# 3. PHOTO COMPRESSION — 60 KB MAX, PASSPORT SIZE (400×500 px)
# ============================================================
PHOTO_MAX_BYTES   = 60 * 1024   # 60 KB hard limit
PHOTO_MAX_PX      = (400, 500)  # width × height — passport aspect ratio
PHOTO_QUALITY_HI  = 60          # first attempt
PHOTO_QUALITY_LO  = 40          # fallback if still over limit

def compress_photo(uploaded_file) -> bytes:
    """
    Resize to passport dimensions (≤400×500 px) and compress to ≤60 KB.
    Returns JPEG bytes ready for upload.
    """
    img = Image.open(uploaded_file)

    # Convert palette / RGBA → RGB so JPEG encoder works
    if img.mode in ("P", "RGBA", "LA"):
        img = img.convert("RGB")

    # Resize — thumbnail preserves aspect ratio within the bounding box
    img.thumbnail(PHOTO_MAX_PX, Image.LANCZOS)

    # First compression pass
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=PHOTO_QUALITY_HI, optimize=True)

    # Second pass if still over limit
    if buf.tell() > PHOTO_MAX_BYTES:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=PHOTO_QUALITY_LO, optimize=True)

    return buf.getvalue()

def upload_photos(photos, job_no, gate_name) -> list[str]:
    """
    Compress and upload up to 4 photos.
    Returns list of public URLs.
    """
    urls = []
    for i, photo_file in enumerate(photos[:4]):
        compressed = compress_photo(photo_file)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        safe_job = str(job_no).replace('/', '-')
        safe_gate = str(gate_name).replace(' ', '_')
        file_name = f"{safe_job}/{safe_gate}_{ts}_{i}.jpg"
        conn.client.storage.from_("quality-photos").upload(
            path=file_name,
            file=compressed,
            file_options={"content-type": "image/jpeg"}
        )
        url = conn.client.storage.from_("quality-photos").get_public_url(file_name)
        urls.append(url)
    return urls

# ============================================================
# 4. MASTER DATA BOOK PDF GENERATOR
# ============================================================
def generate_master_data_book(job_no, project_info, df_plan):
    """
    Stitches Technical Reports, MTCs, and Photo Logs into one stamped PDF.
    Requires: fpdf2, pypdf, requests, Pillow
    """
    if not PDF_AVAILABLE:
        raise RuntimeError(
            "fpdf2 and pypdf are not installed. "
            "Add them to requirements.txt and redeploy."
        )

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- Load logo / stamp from storage ---
    logo_path, stamp_path = None, None
    try:
        l_data = conn.client.storage.from_("progress-photos").download("logo.png")
        s_data = conn.client.storage.from_("progress-photos").download("round_stamp.png")
        if l_data:
            with NamedTemporaryFile(delete=False, suffix=".png") as t:
                t.write(l_data); logo_path = t.name
        if s_data:
            with NamedTemporaryFile(delete=False, suffix=".png") as t:
                t.write(s_data); stamp_path = t.name
    except Exception:
        pass

    # ---- Cover page ----
    pdf.add_page()
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(1.5)
    pdf.rect(5, 5, 200, 287)

    if logo_path:
        pdf.image(logo_path, x=75, y=30, w=60)

    pdf.set_text_color(0, 51, 102)
    pdf.set_font("Arial", 'B', 26)
    pdf.set_y(100)
    pdf.cell(0, 15, "QUALITY DATA BOOK", ln=True, align='C')
    pdf.set_font("Arial", '', 14)
    pdf.cell(0, 10, "COMPLETE PRODUCT BIRTH CERTIFICATE", ln=True, align='C')

    pdf.set_y(160)
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", 'B', 11)
    client_name = (
        project_info.get('client_name')
        if not callable(getattr(project_info, 'get', None))
        else project_info.get('client_name', 'N/A')
    )
    details = [
        f"  JOB NUMBER: {job_no}",
        f"  CLIENT: {client_name}",
        f"  PO REF: {project_info.get('po_no', 'N/A')}",
        f"  DATE: {datetime.now().strftime('%d-%m-%Y')}"
    ]
    for line in details:
        fill = ("JOB" in line or "PO" in line)
        pdf.cell(0, 10, line, ln=True, fill=fill)

    if stamp_path:
        pdf.image(stamp_path, x=150, y=235, w=38)
        pdf.set_xy(150, 275)
        pdf.set_font("Arial", 'B', 7)
        pdf.cell(38, 5, "AUTHORIZED SIGNATORY", align='C')

    # ---- Table of contents ----
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 20, "TABLE OF CONTENTS", ln=True)
    sections = [
        "1. Technical Checklist",
        "2. Dimensional Reports",
        "3. Hydro Test Data",
        "4. Material Certificates (MTC)",
        "5. Manufacturing Photo Evidence Log",
    ]
    pdf.set_font("Arial", '', 11)
    for s in sections:
        pdf.cell(0, 12, s, border="B", ln=True)

    def add_section_header(title):
        pdf.add_page()
        if logo_path:
            pdf.image(logo_path, x=10, y=8, h=10)
        pdf.set_font("Arial", 'B', 10)
        pdf.set_xy(120, 10)
        pdf.cell(80, 10, f"JOB: {job_no} | {title}", align='R', ln=True)
        pdf.line(10, 22, 200, 22)
        pdf.ln(10)

    # ---- Dimensional data ----
    try:
        dim_res = conn.table("dimensional_reports").select("*").eq("job_no", job_no).execute()
        if dim_res.data:
            add_section_header("DIMENSIONAL INSPECTION")
            pdf.set_font("Arial", 'B', 9)
            for col, w in [("Sl", 12), ("Description", 80), ("Specified", 48), ("Measured", 48)]:
                pdf.cell(w, 8, col, 1)
            pdf.ln()
            pdf.set_font("Arial", '', 9)
            for report in dim_res.data:
                for row in report.get('dim_grid_data', []):
                    pdf.cell(12, 7, str(row.get('Sl_No', '')), 1)
                    pdf.cell(80, 7, str(row.get('Description', ''))[:30], 1)
                    pdf.cell(48, 7, str(row.get('Specified_Dimension', ''))[:20], 1)
                    pdf.cell(48, 7, str(row.get('Measured_Dimension', ''))[:20], 1)
                    pdf.ln()
    except Exception:
        pass

    # ---- Hydro test data ----
    try:
        hydro_res = conn.table("hydro_test_reports").select("*").eq("job_no", job_no).execute()
        if hydro_res.data:
            add_section_header("HYDRO TEST REPORT")
            pdf.set_font("Arial", '', 10)
            for report in hydro_res.data:
                pdf.set_font("Arial", 'B', 10)
                pdf.cell(0, 8, f"Equipment: {report.get('equipment_name', 'N/A')}", ln=True)
                pdf.set_font("Arial", '', 10)
                pdf.cell(0, 7, f"Test Pressure: {report.get('test_pressure', 'N/A')} Kg/cm²", ln=True)
                pdf.cell(0, 7, f"Test Medium: {report.get('test_medium', 'N/A')}", ln=True)
                pdf.cell(0, 7, f"Holding Time: {report.get('holding_time', 'N/A')}", ln=True)
                pdf.cell(0, 7, f"Inspected By: {report.get('inspected_by', 'N/A')}", ln=True)
                pdf.cell(0, 7, f"Observations: {report.get('inspection_notes', 'N/A')}", ln=True)
                pdf.ln(4)
    except Exception:
        pass

    # ---- Manufacturing evidence / photo log ----
    job_photos = (
        df_plan[df_plan['job_no'].astype(str) == str(job_no)]
        .dropna(subset=['quality_updated_at'])
        .sort_values('quality_updated_at')
    )

    if not job_photos.empty:
        add_section_header("MANUFACTURING EVIDENCE LOG")
        for _, row in job_photos.iterrows():
            if pdf.get_y() > 230:
                add_section_header("MANUFACTURING EVIDENCE LOG (CONT.)")

            pdf.set_font("Arial", 'B', 10)
            pdf.set_fill_color(240, 240, 240)
            upd = pd.to_datetime(row['quality_updated_at']).strftime('%d-%m-%Y')
            stage_title = f" Stage: {row['gate_name']} | Date: {upd}"
            pdf.cell(0, 8, stage_title, ln=True, fill=True, border="T")

            pdf.set_font("Arial", '', 9)
            pdf.multi_cell(
                0, 6,
                f" Inspector: {row.get('quality_by', '—')} | "
                f"Result: {row.get('quality_status', '—')} | "
                f"Remarks: {row.get('quality_notes') or 'N/A'}",
                border="B"
            )
            pdf.ln(2)

            urls = row.get('quality_photo_url', [])
            if isinstance(urls, list) and len(urls) > 0:
                if pdf.get_y() > 200:
                    add_section_header("MANUFACTURING EVIDENCE LOG (CONT.)")

                img_y   = pdf.get_y()
                img_w   = 60
                img_h   = 45

                for i, url in enumerate(urls[:3]):
                    try:
                        r = requests.get(url, timeout=10)
                        if r.status_code == 200:
                            with NamedTemporaryFile(delete=False, suffix=".jpg") as t:
                                t.write(r.content)
                                tmp = t.name
                            img_x = 10 + (i * 65)
                            pdf.image(tmp, x=img_x, y=img_y, w=img_w, h=img_h)
                            os.unlink(tmp)
                    except Exception:
                        continue

                pdf.set_y(img_y + img_h + 5)

            pdf.ln(5)

    # ---- Stitch MTCs ----
    report_buf = io.BytesIO()
    pdf_bytes  = pdf.output(dest='S').encode('latin-1', 'ignore')
    report_buf.write(pdf_bytes)
    report_buf.seek(0)

    merger = PdfWriter()
    merger.append(PdfReader(report_buf))

    try:
        mtc_res = conn.table("project_certificates").select("file_url") \
            .eq("job_no", job_no).eq("cert_type", "Material Test Certificate (MTC)").execute()
        for doc in (mtc_res.data or []):
            try:
                r = requests.get(doc['file_url'], timeout=15)
                if r.status_code == 200:
                    merger.append(PdfReader(io.BytesIO(r.content)))
            except Exception:
                continue
    except Exception:
        pass

    # Cleanup temp files
    if logo_path:
        os.unlink(logo_path)
    if stamp_path:
        os.unlink(stamp_path)

    final_out = io.BytesIO()
    merger.write(final_out)
    data = final_out.getvalue()
    merger.close()
    return data

# ============================================================
# 5. DATA LOADERS
# ============================================================
@st.cache_data(ttl=10)
def get_quality_context():
    """
    Single combined loader — replaces the scattered @st.cache_data functions.
    Returns planning df, anchor df, and staff list.
    """
    plan_res = conn.table("job_planning").select("*").execute()
    df_plan  = pd.DataFrame(plan_res.data or [])

    anchor_res = conn.table("anchor_projects").select(
        "job_no, client_name, po_no, po_date, equipment_type"
    ).execute()
    df_anchor_raw = pd.DataFrame(anchor_res.data or [])
    if not df_anchor_raw.empty:
        df_anchor = df_anchor_raw[
            df_anchor_raw['job_no'].notna() &
            (df_anchor_raw['job_no'].astype(str).str.strip() != '')
        ].copy()
        df_anchor['job_no'] = df_anchor['job_no'].astype(str).str.strip().str.upper()
        df_anchor = df_anchor.drop_duplicates(subset=['job_no'])
    else:
        df_anchor = pd.DataFrame()

    try:
        staff_res  = conn.table("master_staff").select("name").execute()
        staff_list = sorted([s['name'] for s in staff_res.data]) if staff_res.data else ["QC Inspector"]
    except Exception:
        staff_list = ["QC Inspector"]

    return df_plan, df_anchor, staff_list

@st.cache_data(ttl=60)
def get_config(category):
    try:
        res = conn.table("quality_config").select("parameter_name") \
            .eq("category", category).execute()
        return [r['parameter_name'] for r in res.data] if res.data else []
    except Exception:
        return []

def get_proj(df_anchor, job_no):
    match = df_anchor[df_anchor['job_no'].astype(str) == str(job_no)]
    return match.iloc[0] if not match.empty else None

def job_header(proj):
    """Standard 4-column project info header."""
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"**Client:** {proj.get('client_name', 'N/A')}")
        c2.write(f"**PO No:** {proj.get('po_no', 'N/A')}")
        c3.write(f"**PO Date:** {fmt_date(proj.get('po_date'))}")
        c4.write(f"**Equipment:** {proj.get('equipment_type', 'N/A')}")

# ============================================================
# 6. INITIALISE MASTER DATA
# ============================================================
df_plan, df_anchor, inspectors = get_quality_context()
job_list = (
    sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
    if not df_anchor.empty else []
)

# ============================================================
# 7. NAVIGATION
# ============================================================
st.markdown("""
<div style="background:#003366; color:white; padding:0.6rem 1rem;
            border-radius:8px; margin-bottom:1rem;">
  <b style="font-size:18px;">🔍 B&G Engineering — Quality Assurance Portal</b>
</div>
""", unsafe_allow_html=True)

main_tabs = st.tabs([
    "🚪 Process Gate",          # 0  — live timeline + inspection entry + photo mgmt
    "📋 Quality Checklist",     # 1
    "📜 QAP",                   # 2
    "📉 Material Flow Chart",   # 3
    "🔧 Nozzle Flow Chart",     # 4
    "📐 Dimensional Report",    # 5
    "💧 Hydro Test",            # 6
    "📏 Calibration",           # 7
    "🏁 Final Inspection",      # 8
    "🛡️ Guarantee Certificate", # 9
    "⭐ Customer Feedback",     # 10
    "📂 Document Vault",        # 11
    "📑 Master Data Book",      # 12
    "⚙️ Config",                # 13
])

# ============================================================
# TAB 0: PROCESS GATE — Inspection Entry + Live Evidence + Photo Mgmt
# ============================================================
with main_tabs[0]:
    st.subheader("🚪 Process Gate — Inspection & Evidence")

    gate_subtab, timeline_subtab, gallery_subtab = st.tabs([
        "📝 Record Inspection",
        "🗓️ Live Timeline",
        "🖼️ Photo Gallery & Management",
    ])

    # ── Sub-tab A: Record Inspection ──────────────────────────
    with gate_subtab:
        if not df_plan.empty:
            gc1, gc2 = st.columns(2)

            # Only show jobs that have active / completed stages (skip pure-pending)
            active_jobs = sorted(
                df_plan[df_plan['current_status'].str.upper().ne('PENDING')]
                ['job_no'].dropna().astype(str).unique().tolist()
            ) if 'current_status' in df_plan.columns else sorted(
                df_plan['job_no'].dropna().astype(str).unique().tolist()
            )

            sel_job = gc1.selectbox(
                "🏗️ Select Job", ["-- Select --"] + active_jobs, key="pg_insp_job"
            )

            if sel_job != "-- Select --":
                job_stages = df_plan[df_plan['job_no'].astype(str) == str(sel_job)]
                stage_names = job_stages['gate_name'].dropna().tolist()
                sel_gate = gc2.selectbox(
                    "🚪 Select Gate / Process Stage", stage_names, key="pg_insp_gate"
                )
                stage_record = job_stages[job_stages['gate_name'] == sel_gate].iloc[0]

                st.divider()

                with st.form("inspection_entry_form", clear_on_submit=True):
                    st.markdown(f"#### Inspection: **{sel_job}** → **{sel_gate}**")
                    f1, f2 = st.columns(2)

                    with f1:
                        q_result = st.segmented_control(
                            "Inspection Result",
                            ["✅ Pass", "❌ Reject", "⚠️ Rework"],
                            default="✅ Pass",
                            key="pg_result"
                        )
                        inspector = st.selectbox(
                            "Authorized Inspector",
                            ["-- Select --"] + inspectors,
                            key="pg_inspector"
                        )
                        q_notes = st.text_area(
                            "Technical Observations",
                            placeholder="Record findings, measurements, deviations…"
                        )

                    with f2:
                        st.markdown("**Upload Evidence Photos** (max 4)")
                        st.caption(
                            "📐 Auto-resized to passport size (400×500 px) | "
                            "📦 Compressed to ≤60 KB"
                        )
                        q_photos = st.file_uploader(
                            "Choose photos",
                            type=['png', 'jpg', 'jpeg'],
                            accept_multiple_files=True,
                            key="pg_photos",
                            label_visibility="collapsed"
                        )
                        if q_photos:
                            for ph in q_photos[:4]:
                                st.caption(
                                    f"📷 {ph.name} — "
                                    f"{round(ph.size / 1024, 1)} KB raw "
                                    f"(will be compressed)"
                                )
                        if len(q_photos) > 4:
                            st.warning("Only the first 4 photos will be uploaded.")

                    if st.form_submit_button("🚀 Submit Inspection Record", use_container_width=True):
                        if inspector == "-- Select --":
                            st.error("Please select an authorized inspector.")
                        else:
                            with st.spinner("Compressing photos and saving record…"):
                                try:
                                    all_urls = []
                                    if q_photos:
                                        all_urls = upload_photos(
                                            q_photos[:4], sel_job, sel_gate
                                        )

                                    conn.table("job_planning").update({
                                        "quality_status":     q_result,
                                        "quality_notes":      (
                                            f"{get_now_ist().strftime('%d/%m %H:%M')}: "
                                            f"{q_notes}"
                                        ),
                                        "quality_by":         inspector,
                                        "quality_photo_url":  all_urls,
                                        "quality_updated_at": get_now_ist().isoformat()
                                    }).eq("id", int(stage_record['id'])).execute()

                                    st.success(
                                        f"✅ Inspection recorded for {sel_gate} "
                                        f"with {len(all_urls)} photo(s)."
                                    )
                                    st.cache_data.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Submission error: {e}")
        else:
            st.error("No planning data available. Check the Production Portal.")

    # ── Sub-tab B: Live Timeline ───────────────────────────────
    with timeline_subtab:
        if not df_plan.empty:
            unique_jobs = sorted(df_plan['job_no'].dropna().astype(str).unique().tolist())
            sel_job_tl = st.selectbox(
                "Select Job", ["-- Select --"] + unique_jobs, key="pg_timeline_job"
            )

            if sel_job_tl != "-- Select --":
                p_data = (
                    df_plan[df_plan['job_no'].astype(str) == str(sel_job_tl)]
                    .sort_values('quality_updated_at', na_position='last')
                )

                if not p_data.empty:
                    st.info(
                        f"Manufacturing evidence for **{sel_job_tl}**. "
                        "For the final stamped report → Master Data Book tab."
                    )
                    for _, row in p_data.iterrows():
                        update_date = (
                            fmt_date(row.get('quality_updated_at'))
                            if pd.notna(row.get('quality_updated_at'))
                            else "Pending"
                        )
                        with st.container(border=True):
                            c1, c2 = st.columns([1, 3])
                            status = str(row.get('quality_status', '')).upper()
                            if any(w in status for w in ['PASS', 'ACCEPT', 'OK']):
                                c1.success(f"✅ {row['gate_name']}")
                            elif any(w in status for w in ['REWORK', 'REJECT', 'FAIL']):
                                c1.error(f"❌ {row['gate_name']}")
                            elif status and status not in ['', 'NONE', 'NAN']:
                                c1.warning(f"⚠️ {row['gate_name']}")
                            else:
                                c1.info(f"🔹 {row['gate_name']}")

                            c2.write(
                                f"**Date:** {update_date} | "
                                f"**Inspector:** {row.get('quality_by', '—')}"
                            )
                            c2.write(
                                f"**Remarks:** {row.get('quality_notes') or 'No remarks'}"
                            )
                            if row.get('final_remarks'):
                                c2.caption(f"Final: {row['final_remarks']}")

                            urls = row.get('quality_photo_url', [])
                            if isinstance(urls, list) and len(urls) > 0:
                                cols = st.columns(min(4, len(urls)))
                                for i, url in enumerate(urls[:4]):
                                    try:
                                        cols[i].image(
                                            url,
                                            use_container_width=True,
                                            caption=f"Evidence {i+1}"
                                        )
                                    except Exception:
                                        cols[i].caption(f"📎 Photo {i+1}")
                else:
                    st.warning("No quality records found for this job yet.")
        else:
            st.error("No planning data available.")

    # ── Sub-tab C: Photo Gallery & Management ─────────────────
    with gallery_subtab:
        if not df_plan.empty:
            inspected_df = (
                df_plan.dropna(subset=['quality_status'])
                .sort_values('quality_updated_at', ascending=False)
            )

            if not inspected_df.empty:
                photo_rows = inspected_df[
                    inspected_df['quality_photo_url'].apply(
                        lambda x: isinstance(x, list) and len(x) > 0
                    )
                ]

                if not photo_rows.empty:
                    sel_idx = st.selectbox(
                        "Select record to manage",
                        photo_rows.index,
                        format_func=lambda x: (
                            f"{photo_rows.loc[x, 'job_no']} — "
                            f"{photo_rows.loc[x, 'gate_name']} "
                            f"({fmt_date(photo_rows.loc[x, 'quality_updated_at'])})"
                        ),
                        key="gallery_sel"
                    )

                    current_urls = photo_rows.loc[sel_idx, 'quality_photo_url']
                    record_id    = photo_rows.loc[sel_idx, 'id']

                    st.caption(
                        f"{len(current_urls)} photo(s) — "
                        "all compressed to ≤60 KB / passport size at upload time"
                    )
                    cols = st.columns(4)
                    for i, url in enumerate(current_urls):
                        with cols[i % 4]:
                            st.image(url, use_container_width=True, caption=f"Photo {i+1}")
                            if st.button(f"🗑️ Remove", key=f"del_{record_id}_{i}"):
                                try:
                                    # Extract filename from URL (last path segment)
                                    file_name = "/".join(url.split("/")[-2:])
                                    conn.client.storage.from_("quality-photos").remove([file_name])
                                    updated = [u for u in current_urls if u != url]
                                    conn.table("job_planning").update({
                                        "quality_photo_url": updated
                                    }).eq("id", record_id).execute()
                                    st.toast("Photo removed.")
                                    st.cache_data.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Delete failed: {e}")
                else:
                    st.info("No photos uploaded yet for any inspection.")
            else:
                st.info("No inspections recorded yet.")
        else:
            st.warning("No planning data found.")

# ============================================================
# TAB 1: QUALITY CHECK LIST
# ============================================================
with main_tabs[1]:
    st.subheader("📋 Quality Check List")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="qcl_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)
            e_type = proj.get('equipment_type', 'Storage Tank')

            try:
                existing = conn.table("quality_check_list").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(5).execute()
                if existing.data:
                    with st.expander(f"📂 {len(existing.data)} existing record(s)"):
                        df_ex = pd.DataFrame(existing.data)
                        cols_show = [c for c in [
                            'inspection_date','item_name','drawing_no',
                            'mat_cert_status','fit_up_status','visual_status',
                            'pt_weld_status','hydro_status','final_status',
                            'punching_status','ncr_status','inspected_by'
                        ] if c in df_ex.columns]
                        st.dataframe(df_ex[cols_show], use_container_width=True, hide_index=True)
            except Exception:
                pass

            with st.form("qcl_form", clear_on_submit=True):
                st.markdown("#### 📏 Equipment Details")
                r1, r2, r3 = st.columns(3)
                item_n   = r1.text_input("Name of Item / Description",
                                         value="30KL SS304 OIL HOLDING TANK")
                drg_n    = r2.text_input("Drawing Number", value="3050101710")
                qap_n    = r3.text_input("QAP Reference No.", value="BGEI/2025-26/1500")
                r4, r5, r6 = st.columns(3)
                e_id     = r4.text_input("Equipment ID No.")
                qty_val  = r5.text_input("Quantity", value="1 No.")
                ins_date = r6.date_input("Inspection Date", value=get_now_ist().date())

                st.markdown("#### 🔍 Inspection Check Points")
                st.caption("W = Witnessed | V = Verified | R = Review | NIL = Not Applicable | √ = Enclosed | X = Not Enclosed")

                checklist_data = [
                    {"Check Point": "Material Certification — Material Flow Chart",      "Extent": "100%",           "Format": "Material Flow Chart"},
                    {"Check Point": "Material Certification — Mat Test Certificates",    "Extent": "100%",           "Format": "Mat Test Certificates"},
                    {"Check Point": "Fit-up Exam",                                       "Extent": "100%",           "Format": "Inspection Report"},
                    {"Check Point": "Dimensions & Visual Exam",                          "Extent": "100%",           "Format": "Inspection Report"},
                    {"Check Point": "PT of all Welds",                                   "Extent": "As per QAP/Dwg", "Format": "LPI Report"},
                    {"Check Point": "Hydro Test / Vacuum Test Shell Side",               "Extent": "100%",           "Format": "Hydro Test Report"},
                    {"Check Point": "Final Inspection before Dispatch",                  "Extent": "100%",           "Format": "Inspection Report"},
                    {"Check Point": "Identification Punching",                           "Extent": "",               "Format": "Punching"},
                    {"Check Point": "NCR If any",                                        "Extent": "",               "Format": "NC Report"},
                ]

                grid_cols = st.columns([3, 1, 2, 2, 1, 2])
                for h, col in zip(
                    ["Check Point","Extent","Format of Record","Cust/Insp Verification","Docs Enclosed","Remarks"],
                    grid_cols
                ):
                    col.markdown(f"**{h}**")

                check_results = []
                for i, row in enumerate(checklist_data):
                    gc = st.columns([3, 1, 2, 2, 1, 2])
                    gc[0].caption(row["Check Point"])
                    gc[1].caption(row["Extent"])
                    gc[2].caption(row["Format"])
                    verif  = gc[3].selectbox("", ["W","V","R","NIL","P"],
                                             key=f"qcl_v_{i}", label_visibility="collapsed")
                    docs   = gc[4].selectbox("", ["√","X","NA"],
                                             key=f"qcl_d_{i}", label_visibility="collapsed")
                    remark = gc[5].text_input("", key=f"qcl_r_{i}", label_visibility="collapsed")
                    check_results.append({
                        "checkpoint": row["Check Point"], "extent": row["Extent"],
                        "format": row["Format"], "verification": verif,
                        "docs_enclosed": docs, "remarks": remark
                    })

                if e_type == "Reactor":
                    st.markdown("#### ⚛️ Reactor Specific")
                    r1, r2 = st.columns(2)
                    r1.text_input("Agitator Run Test", value="NA")
                    r2.text_input("Jacket Hydro Test",  value="NA")
                if e_type == "Storage Tank":
                    st.markdown("#### 🛢️ Tank Specific")
                    t1, t2 = st.columns(2)
                    t1.text_input("Roof Structure Fit-up", value="NA")
                    t2.text_input("Curb Angle Inspection",  value="NA")

                st.markdown("#### ✍️ Authorization")
                f1, f2 = st.columns(2)
                insp_by    = f1.selectbox("Quality Inspector", inspectors, key="qcl_insp")
                tech_notes = st.text_area("Technical Notes / Deviations")

                if st.form_submit_button("🚀 Save Quality Check List", use_container_width=True):
                    payload = {
                        "job_no":          sel_job,
                        "client_name":     proj.get('client_name'),
                        "po_no":           proj.get('po_no'),
                        "po_date":         str(proj.get('po_date')) if proj.get('po_date') else None,
                        "item_name":       item_n,
                        "drawing_no":      drg_n,
                        "qap_no":          qap_n,
                        "equipment_id_no": e_id,
                        "qty":             qty_val,
                        "mat_cert_status": check_results[0]['verification'],
                        "fit_up_status":   check_results[2]['verification'],
                        "visual_status":   check_results[3]['verification'],
                        "pt_weld_status":  check_results[4]['verification'],
                        "hydro_status":    check_results[5]['verification'],
                        "final_status":    check_results[6]['verification'],
                        "punching_status": check_results[7]['verification'],
                        "ncr_status":      check_results[8]['verification'],
                        "technical_notes": tech_notes,
                        "inspected_by":    insp_by,
                        "inspection_date": str(ins_date),
                    }
                    safe_write(
                        lambda: conn.table("quality_check_list").insert(payload).execute(),
                        success_msg=f"✅ Quality Check List for {sel_job} saved!"
                    )
                    st.cache_data.clear()

# ============================================================
# TAB 2: QAP — Quality Assurance Plan
# ============================================================
with main_tabs[2]:
    st.subheader("📜 Quality Assurance Plan (QAP)")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="qap_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            with st.form("qap_form"):
                st.markdown("#### QAP Header")
                h1, h2, h3 = st.columns(3)
                qap_no     = h1.text_input("QAP Document No.", value=f"BGEI/2025-26/{sel_job}")
                equip_name = h2.text_input("Equipment Name")
                prep_by    = h3.selectbox("Prepared By", inspectors, key="qap_prep")
                drg_no_qap = h1.text_input("Drawing No.")
                h2.text_input("Client Name", value=proj.get('client_name', ''))
                h3.text_input(
                    "PO No & Date",
                    value=f"{proj.get('po_no','')} & {fmt_date(proj.get('po_date'))}"
                )

                st.markdown("#### 📋 Inspection Activity Grid")
                st.caption("W = Witness | R = Review | P = Perform | H = Hold Point")

                qap_template = pd.DataFrame([
                    {"Sl": 1, "Activity": "Plates — Material ID & TC Verification",
                     "Classification": "Major", "Type_of_Check": "Visual & TC Verification",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Mill/Lab T.Cs", "QA": "W", "BG": "W"},
                    {"Sl": 2, "Activity": "Nozzle pipes & Flanges — Material ID & TC",
                     "Classification": "Major", "Type_of_Check": "Visual & TC Verification",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Mill/Lab T.Cs", "QA": "W", "BG": "W"},
                    {"Sl": 3, "Activity": "L & C-Seam Fit up",
                     "Classification": "Major", "Type_of_Check": "Measurement & Visual",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Stage Inspection Report", "QA": "R", "BG": "R"},
                    {"Sl": 4, "Activity": "Nozzles Fit up",
                     "Classification": "Major", "Type_of_Check": "Dimensional & Visual",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Stage Inspection Report", "QA": "R", "BG": "R"},
                    {"Sl": 5, "Activity": "Hydrotest",
                     "Classification": "Critical", "Type_of_Check": "Pneumatic/Hydraulic",
                     "Quantum": "100%", "Ref_Document": "ASME SEC VIII-DIV1-UG-99.",
                     "Formats_Records": "Hydro Test Report", "QA": "P", "BG": "R"},
                    {"Sl": 6, "Activity": "240 Grit MATT Finish",
                     "Classification": "Major", "Type_of_Check": "Visual Check",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Stage Inspection Report", "QA": "R", "BG": "R"},
                    {"Sl": 7, "Activity": "Documentation Review",
                     "Classification": "Major", "Type_of_Check": "Visual Check",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Stage Inspection Report", "QA": "R", "BG": "R"},
                    {"Sl": 8, "Activity": "Final Stamping and Clearance for Dispatch",
                     "Classification": "Major", "Type_of_Check": "Visual check",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Release note", "QA": "W", "BG": "W"},
                ])

                qap_grid = st.data_editor(
                    qap_template, num_rows="dynamic",
                    use_container_width=True, hide_index=True, key="qap_grid",
                    column_config={
                        "Sl": st.column_config.NumberColumn("Sl", width="small", disabled=True),
                        "Activity": st.column_config.TextColumn("Activity Description", width="large"),
                        "Classification": st.column_config.SelectboxColumn(
                            "Classification", options=["Major","Minor","Critical"], width="small"),
                        "Type_of_Check": st.column_config.TextColumn("Type of Check", width="medium"),
                        "Quantum": st.column_config.TextColumn("Quantum", width="small"),
                        "Ref_Document": st.column_config.TextColumn("Ref. Document", width="medium"),
                        "Formats_Records": st.column_config.TextColumn("Formats/Records", width="medium"),
                        "QA": st.column_config.SelectboxColumn("QA", options=["W","R","P","H",""], width="small"),
                        "BG": st.column_config.SelectboxColumn("B&G", options=["W","R","P","H",""], width="small"),
                    }
                )

                note_qap = st.text_area("Notes / Legend")

                if st.form_submit_button("💾 Save QAP", use_container_width=True):
                    payload = {
                        "job_no":            sel_job,
                        "equipment_name":    equip_name,
                        "nozzle_mark":       qap_no,
                        "traceability_data": qap_grid.to_dict('records'),
                        "verified_by":       prep_by,
                        "remarks":           note_qap,
                        "created_at":        get_now_ist().isoformat()
                    }
                    safe_write(
                        lambda: conn.table("nozzle_flow_charts").insert(payload).execute(),
                        success_msg=f"✅ QAP for {sel_job} saved!"
                    )

# ============================================================
# TAB 3: MATERIAL FLOW CHART
# ============================================================
with main_tabs[3]:
    st.subheader("📉 Material Flow Chart & Traceability")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="mfc_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            try:
                existing_mfc = conn.table("material_flow_charts").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute()
                if existing_mfc.data:
                    with st.expander("📂 Load last saved record"):
                        rec = existing_mfc.data[0]
                        st.caption(f"Saved: {fmt_date(rec.get('created_at'))} | By: {rec.get('verified_by')}")
                        if rec.get('traceability_data'):
                            st.dataframe(pd.DataFrame(rec['traceability_data']),
                                         use_container_width=True, hide_index=True)
            except Exception:
                pass

            c1, c2 = st.columns(2)
            item_desc = c1.text_input("Equipment Description", placeholder="e.g. 30KL SS304 OIL HOLDING TANK")
            total_qty = c2.text_input("Quantity", placeholder="e.g. 1 No.")

            st.markdown("#### 🔍 Material Identification Matrix")

            mfc_template = pd.DataFrame([
                {"Sl": 1, "Description": "SHELL",            "Size": "ID2750X5100LX8THK",     "MOC": "SS304", "Test_Report_No": "2268648", "Heat_No": "50227B06C"},
                {"Sl": 2, "Description": "TOP DISH",          "Size": "ID2750X10THKX10%TORI",  "MOC": "SS304", "Test_Report_No": "2265157", "Heat_No": "41204F12"},
                {"Sl": 3, "Description": "BOTTOM DISH",       "Size": "ID2750X10THKX10%TORI",  "MOC": "SS304", "Test_Report_No": "2265157", "Heat_No": "41204F12"},
                {"Sl": 4, "Description": "BOTTOM LUGS",       "Size": "300CX1140LX8THK",        "MOC": "SS304", "Test_Report_No": "2268648", "Heat_No": "50227B06C"},
                {"Sl": 5, "Description": "LIFTING HOOKS",     "Size": "25THK",                  "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Sl": 6, "Description": "RF PADS",           "Size": "8THK",                   "MOC": "SS304", "Test_Report_No": "2268648", "Heat_No": "50227B06C"},
                {"Sl": 7, "Description": "BOTTOM BASE PLATE", "Size": "450LX450WX20THK",        "MOC": "SS304", "Test_Report_No": "2408309", "Heat_No": "50424B02C"},
                {"Sl": 8, "Description": "LADDER",            "Size": "32 & 25NB PIPE",         "MOC": "SS304", "Test_Report_No": "",        "Heat_No": ""},
                {"Sl": 9, "Description": "RAILING",           "Size": "32 & 25NB PIPE",         "MOC": "SS304", "Test_Report_No": "",        "Heat_No": ""},
            ])

            mfc_key = f"mfc_grid_{sel_job}"
            if mfc_key not in st.session_state:
                st.session_state[mfc_key] = mfc_template

            mfc_grid = st.data_editor(
                st.session_state[mfc_key], num_rows="dynamic",
                use_container_width=True, hide_index=True,
                key=f"mfc_editor_{sel_job}",
                column_config={
                    "Sl": st.column_config.NumberColumn("Sl", width="small"),
                    "Description": st.column_config.TextColumn("Description", width="large"),
                    "Size": st.column_config.TextColumn("Size", width="medium"),
                    "MOC": st.column_config.TextColumn("MOC", width="small"),
                    "Test_Report_No": st.column_config.TextColumn("Test Report No.", width="medium"),
                    "Heat_No": st.column_config.TextColumn("Heat No.", width="medium"),
                }
            )

            with st.form("mfc_form", clear_on_submit=False):
                f1, _ = st.columns(2)
                verifier  = f1.selectbox("Verified By (QC)", inspectors, key="mfc_verifier")
                mfc_rem   = st.text_area("Observations / Traceability Notes")
                if st.form_submit_button("🚀 Save Material Flow Chart", use_container_width=True):
                    final_rows = [{**r, "Sl": i+1} for i, r in enumerate(mfc_grid.to_dict('records'))]
                    payload = {
                        "job_no":            sel_job,
                        "item_name":         item_desc,
                        "qty":               total_qty,
                        "traceability_data": final_rows,
                        "verified_by":       verifier,
                        "remarks":           mfc_rem,
                        "created_at":        get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("material_flow_charts").insert(payload).execute(),
                        success_msg=f"✅ Material Flow Chart for {sel_job} saved!"
                    )
                    if ok:
                        st.balloons()

# ============================================================
# TAB 4: NOZZLE FLOW CHART
# ============================================================
with main_tabs[4]:
    st.subheader("🔧 Nozzle Flow Chart & Traceability")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="nfc_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            c1, c2 = st.columns(2)
            equip_name_nfc = c1.text_input("Equipment Name", placeholder="e.g. 30KL SS304 OIL HOLDING TANK")
            dwg_no_nfc     = c2.text_input("DWG No.", placeholder="e.g. 3050101710")

            nfc_col_cfg = {
                "Nozzle_No":      st.column_config.TextColumn("Nozzle No", width="small"),
                "Description":    st.column_config.TextColumn("Description", width="large"),
                "QTY":            st.column_config.NumberColumn("Qty", width="small"),
                "Size_NB":        st.column_config.TextColumn("Size (NB)", width="medium"),
                "MOC":            st.column_config.TextColumn("MOC", width="small"),
                "Test_Report_No": st.column_config.TextColumn("Test Report No.", width="medium"),
                "Heat_No":        st.column_config.TextColumn("Heat No.", width="medium"),
            }

            st.markdown("#### 🔩 Flanges Traceability")
            flange_template = pd.DataFrame([
                {"Nozzle_No": "N1",  "Description": "DRAIN",                "QTY": 1, "Size_NB": "40NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N2",  "Description": "OIL OUTLET",           "QTY": 1, "Size_NB": "50NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N3",  "Description": "OIL INLET",            "QTY": 1, "Size_NB": "80X50NB", "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N6",  "Description": "MANHOLE",              "QTY": 1, "Size_NB": "450NB",   "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N17", "Description": "OVER FLOW",            "QTY": 1, "Size_NB": "100NB",   "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
            ])
            flange_grid = st.data_editor(
                flange_template, num_rows="dynamic",
                use_container_width=True, hide_index=True,
                key=f"nfc_flange_{sel_job}", column_config=nfc_col_cfg
            )

            st.markdown("#### 🔧 Pipes Traceability")
            pipe_template = pd.DataFrame([
                {"Nozzle_No": "N1",  "Description": "DRAIN",     "QTY": 1, "Size_NB": "40NB",  "MOC": "SS304", "Test_Report_No": "WYYK8937", "Heat_No": "K972180"},
                {"Nozzle_No": "N2",  "Description": "OIL OUTLET","QTY": 1, "Size_NB": "50NB",  "MOC": "SS304", "Test_Report_No": "WYYK8735", "Heat_No": "F936215"},
                {"Nozzle_No": "N17", "Description": "OVER FLOW", "QTY": 1, "Size_NB": "100NB", "MOC": "SS304", "Test_Report_No": "",         "Heat_No": ""},
            ])
            pipe_grid = st.data_editor(
                pipe_template, num_rows="dynamic",
                use_container_width=True, hide_index=True,
                key=f"nfc_pipe_{sel_job}", column_config=nfc_col_cfg
            )

            with st.form("nfc_form", clear_on_submit=True):
                f1, _ = st.columns(2)
                nfc_verifier = f1.selectbox("Inspected By", inspectors, key="nfc_verifier")
                nfc_remarks  = st.text_area("Orientation / Fit-up Remarks")
                if st.form_submit_button("🚀 Save Nozzle Flow Chart"):
                    combined = {
                        "flanges": flange_grid.to_dict('records'),
                        "pipes":   pipe_grid.to_dict('records'),
                    }
                    payload = {
                        "job_no":            sel_job,
                        "equipment_name":    equip_name_nfc,
                        "nozzle_mark":       dwg_no_nfc,
                        "traceability_data": combined,
                        "verified_by":       nfc_verifier,
                        "remarks":           nfc_remarks,
                        "created_at":        get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("nozzle_flow_charts").insert(payload).execute(),
                        success_msg=f"✅ Nozzle Flow Chart for {sel_job} saved!"
                    )
                    if ok:
                        st.balloons()

# ============================================================
# TAB 5: DIMENSIONAL INSPECTION REPORT
# ============================================================
with main_tabs[5]:
    st.subheader("📐 Dimensional Inspection Report (DIR)")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="dir_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Customer:** {proj.get('client_name','N/A')}")
                drg_no_dir  = c2.text_input("Drawing No.", value="3050101710", key="dir_drg")
                report_date = c3.date_input("Date", value=get_now_ist().date(), key="dir_date")

            report_no = f"BG/QA/DIR-{sel_job}"
            st.caption(f"Report No: **{report_no}**")

            options_desc = get_config("Dimensional Descriptions") or \
                ["Shell","Top Dish","Bottom Dish","Bottom Lugs","Ladder","Railing",
                 "Lifting Hooks","Nozzle Pipes","Nozzle Flanges","Overall weld Visual",
                 "Surface finish Inside","Surface finish Outside"]
            options_moc  = get_config("MOC List") or ["SS304","SS316L","SS316","MS","CS","Duplex"]

            dir_key = f"dir_data_{sel_job}"
            if dir_key not in st.session_state:
                try:
                    existing_dir = conn.table("dimensional_reports").select("*") \
                        .eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute()
                    if existing_dir.data:
                        report = existing_dir.data[0]
                        st.session_state[dir_key] = pd.DataFrame(report.get('dim_grid_data', []))
                        st.info(f"✅ Loaded record from {fmt_date(report['created_at'])}")
                    else:
                        st.session_state[dir_key] = pd.DataFrame([
                            {"Sl_No": 1,  "Description": "Shell",                "Specified_Dimension": "ID2750X5100HX8THK",   "Measured_Dimension": "ID2750X5100HX8THK",   "MOC": "SS304"},
                            {"Sl_No": 2,  "Description": "Top Dish",             "Specified_Dimension": "ID2750X10THK",         "Measured_Dimension": "ID2750X10THK",         "MOC": "SS304"},
                            {"Sl_No": 3,  "Description": "Bottom Dish",          "Specified_Dimension": "ID2750X10THK",         "Measured_Dimension": "ID2750X10THK",         "MOC": "SS304"},
                            {"Sl_No": 4,  "Description": "Bottom Lugs",          "Specified_Dimension": "300CX1140LX8THK",      "Measured_Dimension": "300CX1140LX8THK",      "MOC": "SS304"},
                            {"Sl_No": 5,  "Description": "Ladder",               "Specified_Dimension": "32NB & 25NB",          "Measured_Dimension": "32NB & 25NB",          "MOC": "SS304"},
                            {"Sl_No": 6,  "Description": "Railing",              "Specified_Dimension": "32NB & 25NB",          "Measured_Dimension": "32NB & 25NB",          "MOC": "SS304"},
                            {"Sl_No": 7,  "Description": "Lifting Hooks",        "Specified_Dimension": "25THK",                "Measured_Dimension": "25THK",                "MOC": "SS304"},
                            {"Sl_No": 8,  "Description": "Nozzle Pipes",         "Specified_Dimension": "SCH40, ERW, 150 PROJ", "Measured_Dimension": "SCH40, ERW, 150 PROJ", "MOC": "SS304"},
                            {"Sl_No": 9,  "Description": "Nozzle Flanges",       "Specified_Dimension": "ASA150THK, PCD",       "Measured_Dimension": "ASA150THK, PCD",       "MOC": "SS304"},
                            {"Sl_No": 10, "Description": "Overall weld Visual",  "Specified_Dimension": "",                     "Measured_Dimension": "Found ok",             "MOC": "-"},
                            {"Sl_No": 11, "Description": "Surface finish Inside", "Specified_Dimension": "MATT",                "Measured_Dimension": "MATT",                 "MOC": "SS"},
                            {"Sl_No": 12, "Description": "Surface finish Outside","Specified_Dimension": "MATT",                "Measured_Dimension": "MATT",                 "MOC": "SS"},
                        ])
                except Exception as e:
                    st.error(f"Load error: {e}")

            dim_grid = st.data_editor(
                st.session_state.get(dir_key, pd.DataFrame()),
                num_rows="dynamic", use_container_width=True,
                hide_index=True, key=f"dir_editor_{sel_job}",
                column_config={
                    "Sl_No":               st.column_config.NumberColumn("Sl", width="small", disabled=True),
                    "Description":         st.column_config.SelectboxColumn("Description", options=options_desc, width="large"),
                    "Specified_Dimension": st.column_config.TextColumn("Specified Dimension", width="large"),
                    "Measured_Dimension":  st.column_config.TextColumn("Measured Dimension", width="large"),
                    "MOC":                 st.column_config.SelectboxColumn("MOC", options=options_moc, width="small"),
                }
            )

            st.markdown("#### Acceptance Status")
            acc_cols = st.columns(4)
            acc1 = acc_cols[0].checkbox("1. Part accepted.")
            acc2 = acc_cols[1].checkbox("2. To be reworked.")
            acc3 = acc_cols[2].checkbox("3. Rejected (NCR enclosed)")
            acc4 = acc_cols[3].text_input("4. Deviation accepted reason")

            f1, f2, f3 = st.columns(3)
            dir_insp = f1.selectbox("Executive (QA)", inspectors, key="dir_insp")
            dir_tpi  = f2.text_input("TPI Name")
            f3.text_input("Customer Representative")

            if st.button("🚀 Save DIR Report", type="primary", use_container_width=True):
                final_rows = [{**r, "Sl_No": i+1} for i, r in enumerate(dim_grid.to_dict('records'))]
                acceptance = {
                    "part_accepted": acc1, "to_be_reworked": acc2,
                    "rejected": acc3, "deviation_reason": acc4
                }
                payload = {
                    "job_no":          sel_job,
                    "drawing_no":      drg_no_dir,
                    "inspection_date": str(report_date),
                    "dim_grid_data":   final_rows,
                    "inspected_by":    dir_insp,
                    "remarks":         str(acceptance),
                    "created_at":      get_now_ist().isoformat()
                }
                ok = safe_write(
                    lambda: conn.table("dimensional_reports").insert(payload).execute(),
                    success_msg=f"✅ DIR saved with {len(final_rows)} items!"
                )
                if ok:
                    st.session_state[dir_key] = pd.DataFrame(final_rows)
                    st.rerun()

# ============================================================
# TAB 6: HYDRO TEST REPORT
# ============================================================
with main_tabs[6]:
    st.subheader("💧 Hydrostatic / Pneumatic Test Report")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="hydro_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            try:
                ex_hydro = conn.table("hydro_test_reports").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(3).execute()
                if ex_hydro.data:
                    with st.expander(f"📂 {len(ex_hydro.data)} existing hydro report(s)"):
                        df_ex = pd.DataFrame(ex_hydro.data)
                        cols_show = [c for c in ['created_at','equipment_name','test_pressure',
                                                  'holding_time','test_medium','inspected_by']
                                     if c in df_ex.columns]
                        st.dataframe(df_ex[cols_show], use_container_width=True, hide_index=True)
            except Exception:
                pass

            with st.form("hydro_form", clear_on_submit=True):
                st.markdown("#### Report References")
                r1, r2, r3 = st.columns(3)
                report_no_h = r1.text_input("Test Report No.",    value=f"BG/QA/HTR-{sel_job}")
                r2.text_input("FIR No.",                           value=f"BG/QA/FIR-{sel_job}")
                r3.text_input("Reference Document",                value="ASME SEC VIII DIVI.1 UG-99")
                e_name_h    = r1.text_input("Equipment Description", placeholder="e.g. 30KL SS304 OIL HOLDING TANK")
                r2.text_input("Equipment No.", placeholder="e.g. 1500")
                r3.text_input("Drawing No.",   placeholder="e.g. 3050101710")

                st.markdown("#### ⏲️ Test Parameters")
                p1, p2, p3 = st.columns(3)
                t_pressure = p1.text_input("Test Pressure (Kg/cm²)",   placeholder="e.g. 1.0")
                p2.text_input("Design Pressure (Kg/cm²)",               placeholder="e.g. 0.5")
                h_time     = p3.text_input("Holding Duration",           placeholder="e.g. 1 Hrs.")

                p4, p5, p6 = st.columns(3)
                medium = p4.selectbox("Test Medium",
                    ["Potable Water","WATER","Hydraulic Oil","Compressed Air","Nitrogen"])
                g_nos  = p5.text_input("Pressure Gauge ID(s)", placeholder="BG/QC/PG-01")
                p6.text_input("Temperature", value="ATMP.")

                h_remarks = st.text_area("Observations",
                                          value="No leakages found during the test period.")

                st.markdown("#### ✍️ Authorization")
                w1, w2, w3 = st.columns(3)
                insp_h = w1.selectbox("Executive (QA)", inspectors, key="hydro_insp")
                wit_h  = w2.text_input("Customer / TPI Witness")
                w3.text_input("Production I/C")

                if st.form_submit_button("🚀 Save Hydro Test Report", use_container_width=True):
                    payload = {
                        "job_no":           sel_job,
                        "equipment_name":   e_name_h,
                        "test_pressure":    t_pressure,
                        "holding_time":     h_time,
                        "test_medium":      medium,
                        "gauge_nos":        g_nos,
                        "inspection_notes": h_remarks,
                        "inspected_by":     insp_h,
                        "witnessed_by":     wit_h,
                        "created_at":       get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("hydro_test_reports").insert(payload).execute(),
                        success_msg=f"✅ Hydro Test Report {report_no_h} saved!"
                    )
                    if ok:
                        st.balloons()
                        st.cache_data.clear()

# ============================================================
# TAB 7: CALIBRATION CERTIFICATE
# ============================================================
with main_tabs[7]:
    st.subheader("📏 Calibration Certificate — Upload & View")
    st.info("Calibration certificates are issued by external labs. Upload the scanned PDF here.")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="cal_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            with st.form("cal_form", clear_on_submit=True):
                st.markdown("#### Calibration Details")
                c1, c2, c3 = st.columns(3)
                cal_report_no = c1.text_input("Report No.",        placeholder="e.g. SCS/PG/3500")
                instrument    = c2.text_input("Instrument / Equipment Under Calibration",
                                              placeholder="e.g. Pressure Gauge")
                make          = c3.text_input("Make", placeholder="e.g. Baumer")
                sr_no         = c1.text_input("Sr. No.", placeholder="e.g. R303.59-03787")
                range_val     = c2.text_input("Range", placeholder="e.g. 0 to 7 kg/cm²")
                least_count   = c3.text_input("Least Count", placeholder="e.g. 0.1kg/cm²")

                c4, c5 = st.columns(2)
                cal_date_val = c4.date_input("Date of Calibration", value=get_now_ist().date())
                cal_due_date = c5.date_input("Calibration Due Date")

                cal_remarks = st.text_area("Calibration Remarks",
                    value="The Instrument is Satisfactory with respect to the Specified limits.")
                cal_by  = st.text_input("Calibrated By")

                st.markdown("#### 📎 Upload Certificate (PDF / Image)")
                cal_file = st.file_uploader("Upload scanned certificate",
                                             type=['pdf','jpg','png'], key="cal_upload")

                if st.form_submit_button("🚀 Save & Upload Calibration Record"):
                    file_url = ""
                    if cal_file:
                        try:
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            file_path = f"{sel_job}/CAL_{timestamp}_{cal_file.name}"
                            conn.client.storage.from_("project-certificates").upload(
                                file_path, cal_file.getvalue()
                            )
                            file_url = conn.client.storage.from_("project-certificates") \
                                           .get_public_url(file_path)
                            conn.table("project_certificates").insert({
                                "job_no":      sel_job,
                                "cert_type":   "Calibration Certificate",
                                "file_name":   cal_file.name,
                                "file_url":    file_url,
                                "uploaded_by": "QC Staff",
                                "created_at":  get_now_ist().isoformat()
                            }).execute()
                            st.success(f"✅ Certificate uploaded: {cal_file.name}")
                        except Exception as e:
                            st.error(f"Upload error: {e}")

                    payload = {
                        "job_no":         sel_job,
                        "gate_name":      "Calibration",
                        "gauge_id":       sr_no,
                        "gauge_cal_due":  str(cal_due_date),
                        "moc_type":       make,
                        "specified_val":  range_val,
                        "measured_val":   least_count,
                        "quality_notes":  f"Report: {cal_report_no} | Instrument: {instrument} | {cal_remarks}",
                        "inspector_name": cal_by,
                        "quality_status": "Calibrated",
                        "created_at":     get_now_ist().isoformat()
                    }
                    safe_write(
                        lambda: conn.table("quality_inspection_logs").insert(payload).execute(),
                        success_msg="✅ Calibration record saved!"
                    )

            st.divider()
            st.markdown("#### 📂 Existing Calibration Records")
            try:
                cal_docs = conn.table("project_certificates").select("*") \
                    .eq("job_no", sel_job).eq("cert_type", "Calibration Certificate").execute()
                if cal_docs.data:
                    for doc in cal_docs.data:
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([3, 2, 1])
                            c1.write(f"📄 **{doc['file_name']}**")
                            c2.caption(f"Uploaded: {fmt_date(doc['created_at'])}")
                            c3.link_button("👁️ View", doc['file_url'])
                else:
                    st.info("No calibration certificates uploaded yet.")
            except Exception as e:
                st.error(f"Load error: {e}")

# ============================================================
# TAB 8: FINAL INSPECTION REPORT
# ============================================================
with main_tabs[8]:
    st.subheader("🏁 Final Inspection Report (FIR)")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="fir_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            with st.container(border=True):
                r1, r2, r3 = st.columns(3)
                fir_no   = r1.text_input("FIR No.", value=f"FIR/{sel_job}")
                r2.date_input("Date", value=get_now_ist().date())
                r1.write(f"**Customer:** {proj.get('client_name','N/A')}")
                r1.write(f"**PO No & Date:** {proj.get('po_no','N/A')} & {fmt_date(proj.get('po_date'))}")
                fir_equip = r2.text_input("Equipment", placeholder="e.g. 30KL SS304 OIL HOLDING TANK")
                fir_type  = r3.selectbox("Type", ["VERTICAL","HORIZONTAL","OTHER"])
                fir_cap   = r1.text_input("Capacity", placeholder="e.g. 30.KL")
                fir_ga    = r2.text_input("GA Drg. No.", placeholder="e.g. 3050101710")
                fir_moc   = r3.text_input("MOC", value="SS304")
                fir_iwo   = r1.text_input("IWO No. / Equipment No.", placeholder="e.g. 1500")

            with st.form("fir_form", clear_on_submit=True):
                st.markdown("#### 📊 Quantity & Clearance")
                q1, q2, q3 = st.columns(3)
                ord_qty = q1.text_input("Ordered Qty",       value="1 No.")
                off_qty = q2.text_input("Offered for Insp.", value="1 No.")
                acc_qty = q3.text_input("Accepted Qty",      value="1 No.")

                st.markdown("#### 🏁 Final Verdict & Authorization")
                fv1, fv2 = st.columns(2)
                fir_status   = fv1.selectbox("Inspection Result",
                    ["✅ Accepted","❌ Rejected","⚠️ Rework Required"])
                fir_inspector= fv2.selectbox("Quality Inspector", inspectors, key="fir_insp")
                fir_witness  = fv1.text_input("Customer / TPI Representative")
                fv2.text_input("Production I/C")
                fir_remarks  = st.text_area("Final Observations / Notes",
                    value="Notes: 1. Entries marked with * are for Customer representative.\n"
                          "2. Please quote FIR No. & date in all correspondences.")

                if st.form_submit_button("🚀 Finalize & Save FIR", use_container_width=True):
                    payload = {
                        "job_no":            sel_job,
                        "equipment_name":    fir_equip,
                        "tag_no":            fir_iwo,
                        "ordered_qty":       ord_qty,
                        "offered_qty":       off_qty,
                        "accepted_qty":      acc_qty,
                        "inspection_status": fir_status,
                        "inspected_by":      fir_inspector,
                        "witnessed_by":      fir_witness,
                        "remarks":           fir_remarks,
                        "created_at":        get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("final_inspection_reports").insert(payload).execute(),
                        success_msg=f"✅ FIR {fir_no} for {sel_job} saved!"
                    )
                    if ok:
                        st.balloons()
                        st.cache_data.clear()

# ============================================================
# TAB 9: GUARANTEE CERTIFICATE
# ============================================================
with main_tabs[9]:
    st.subheader("🛡️ Guarantee Certificate")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="gc_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            try:
                ex_gc = conn.table("guarantee_certificates").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute()
                if ex_gc.data:
                    with st.expander("📂 Existing Guarantee Certificate"):
                        g = ex_gc.data[0]
                        st.write(f"**Equipment:** {g.get('equipment_name')}")
                        st.write(f"**Serial No:** {g.get('serial_no')}")
                        st.write(f"**Certified By:** {g.get('certified_by')}")
                        st.write(f"**Date:** {fmt_date(g.get('created_at'))}")
            except Exception:
                pass

            with st.form("gc_form", clear_on_submit=True):
                g1, g2, g3 = st.columns(3)
                gc_equip    = g1.text_input("Equipment Description",
                                             value=proj.get('project_description',
                                                   '30KL SS304 OIL HOLDING TANK'))
                gc_drg      = g2.text_input("DRG. No.", placeholder="e.g. 3050101710")
                gc_equip_no = g3.text_input("Equipment No.", placeholder="e.g. 1500")
                gc_fir_no   = g1.text_input("FIR No.", value=f"QA/FIR/{sel_job}")
                g2.date_input("Date of Issue", value=get_now_ist().date())
                inv_ref     = g3.text_input("Invoice / Dispatch Ref No.")

                g_period = st.text_area("Guarantee Terms",
                    value=(
                        "B&G Engineering Industries guarantee the above equipment for 12 months "
                        "from the date of supply against any manufacturing defectives. "
                        "In this duration any defectives found the same will be rectified or "
                        "replaced if necessary. The following terms will apply;\n\n"
                        "Guarantee will not apply:\n"
                        "1. Any mishandling of equipment.\n"
                        "2. Using equipment beyond specified operating conditions.\n"
                        "3. Any Misalignment of equipment in plant.\n"
                        "4. The product will not guarantee for corrosion and erosion.\n"
                        "5. Repairs with any unauthorised persons."
                    ), height=200)

                certifier  = st.selectbox("Authorised Signatory", inspectors, key="gc_certifier")
                gc_remarks = st.text_area("Additional Terms / Remarks")

                if st.form_submit_button("🚀 Generate & Save Guarantee Certificate",
                                          use_container_width=True):
                    payload = {
                        "job_no":           sel_job,
                        "equipment_name":   f"{gc_equip} | DRG: {gc_drg}",
                        "serial_no":        gc_equip_no,
                        "guarantee_period": g_period,
                        "invoice_ref":      f"FIR: {gc_fir_no} | INV: {inv_ref}",
                        "certified_by":     certifier,
                        "remarks":          gc_remarks,
                        "created_at":       get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("guarantee_certificates").insert(payload).execute(),
                        success_msg=f"✅ Guarantee Certificate for {sel_job} saved!"
                    )
                    if ok:
                        st.balloons()
                        st.cache_data.clear()

# ============================================================
# TAB 10: CUSTOMER FEEDBACK
# ============================================================
with main_tabs[10]:
    st.subheader("⭐ Customer Feedback")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="fb_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Customer:** {proj.get('client_name','N/A')}")
                c2.write(f"**PO No & Date:** {proj.get('po_no','N/A')} & {fmt_date(proj.get('po_date'))}")
                c3.write(f"**Job No:** {sel_job}")

            with st.form("fb_form", clear_on_submit=True):
                f1, f2 = st.columns(2)
                c_person = f1.text_input("Name of Customer Contact Person")
                c_desig  = f2.text_input("Designation")

                st.markdown("#### Feedback Parameters")
                st.caption("Rate each parameter: Excellent | Very Good | Good | Bad | Other")

                rating_options = ["Excellent", "Very Good", "Good", "Bad", "Other"]
                params = [
                    ("Conformity with Specs",           "spec"),
                    ("Quality",                          "quality"),
                    ("Delivery",                         "delivery"),
                    ("Responsiveness to Queries",        "response"),
                    ("Courtesy",                         "courtesy"),
                    ("Responsiveness to Complaints",     "complaints"),
                ]
                fb_ratings = {}
                for label, key in params:
                    col1, col2 = st.columns([2, 3])
                    col1.write(f"**{label}**")
                    fb_ratings[key] = col2.radio(
                        label, rating_options, horizontal=True,
                        key=f"fb_{key}", label_visibility="collapsed"
                    )

                rating_map   = {"Excellent": 5, "Very Good": 4, "Good": 3, "Bad": 2, "Other": 1}
                suggestions  = st.text_area("Any Suggestions for Improvement")
                reviewed_by  = st.text_input("Reviewed By (B&G Staff)")

                if st.form_submit_button("🚀 Submit Customer Feedback", use_container_width=True):
                    payload = {
                        "job_no":                   sel_job,
                        "customer_name":            proj.get('client_name'),
                        "contact_person":           f"{c_person} ({c_desig})",
                        "rating_quality":           rating_map.get(fb_ratings.get('quality','Good'), 3),
                        "rating_delivery":          rating_map.get(fb_ratings.get('delivery','Good'), 3),
                        "rating_response":          rating_map.get(fb_ratings.get('response','Good'), 3),
                        "rating_technical_support": rating_map.get(fb_ratings.get('courtesy','Good'), 3),
                        "rating_documentation":     rating_map.get(fb_ratings.get('complaints','Good'), 3),
                        "suggestions":              suggestions,
                        "recommend_bg":             reviewed_by,
                        "created_at":               get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("customer_feedback").insert(payload).execute(),
                        success_msg="✅ Customer Feedback recorded!"
                    )
                    if ok:
                        st.balloons()
                        st.cache_data.clear()

# ============================================================
# TAB 11: DOCUMENT VAULT
# ============================================================
with main_tabs[11]:
    st.subheader("📂 MTC & Document Upload Vault")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="vault_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            st.info(f"📂 Vault for: **{proj.get('client_name')}** | Job: **{sel_job}**")

            with st.form("vault_upload_form", clear_on_submit=True):
                u1, u2 = st.columns(2)
                c_type   = u1.selectbox("Document Type", [
                    "Material Test Certificate (MTC)",
                    "Calibration Certificate",
                    "NDT Report",
                    "As Built Drawing",
                    "Guarantee Certificate",
                    "Final Inspection Report",
                    "Invoice",
                    "Other"
                ])
                up_files = u2.file_uploader("Upload PDF / Image",
                                             accept_multiple_files=True,
                                             type=['pdf','jpg','jpeg','png'])
                st.text_input("Document Label / Description")

                if st.form_submit_button("🚀 Upload to Vault"):
                    if up_files:
                        for uploaded_file in up_files:
                            try:
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                file_path = f"{sel_job}/{c_type.split()[0]}_{timestamp}_{uploaded_file.name}"
                                conn.client.storage.from_("project-certificates").upload(
                                    file_path, uploaded_file.getvalue()
                                )
                                file_url = conn.client.storage.from_("project-certificates") \
                                               .get_public_url(file_path)
                                conn.table("project_certificates").insert({
                                    "job_no":      sel_job,
                                    "cert_type":   c_type,
                                    "file_name":   uploaded_file.name,
                                    "file_url":    file_url,
                                    "uploaded_by": "QC Staff",
                                    "created_at":  get_now_ist().isoformat()
                                }).execute()
                                st.success(f"✅ Uploaded: {uploaded_file.name}")
                            except Exception as e:
                                st.error(f"Error uploading {uploaded_file.name}: {e}")
                    else:
                        st.warning("Please select files first.")

            st.divider()
            st.markdown("### 📑 Existing Project Documents")
            try:
                docs_res = conn.table("project_certificates").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).execute()
                if docs_res.data:
                    df_docs = pd.DataFrame(docs_res.data)
                    for cert_type, group in df_docs.groupby('cert_type'):
                        st.markdown(f"**{cert_type}** ({len(group)})")
                        for _, doc in group.iterrows():
                            with st.container(border=True):
                                d1, d2, d3, d4 = st.columns([3, 2, 2, 1])
                                d1.write(f"📄 {doc['file_name']}")
                                d2.caption(doc['cert_type'])
                                d3.caption(fmt_date(doc['created_at']))
                                d4.link_button("👁️ View", doc['file_url'])
                else:
                    st.info("No documents uploaded yet.")
            except Exception as e:
                st.error(f"Vault load error: {e}")

# ============================================================
# TAB 12: MASTER DATA BOOK
# ============================================================
with main_tabs[12]:
    st.header("📑 Master Data Book Generator")
    st.info(
        "Compiles all quality documents into a single stamped PDF — "
        "the B&G Product Birth Certificate."
    )

    if not PDF_AVAILABLE:
        st.warning(
            "PDF generation requires **fpdf2** and **pypdf**. "
            "Add these to `requirements.txt` and redeploy:\n\n"
            "```\nfpdf2\npypdf\nrequests\nPillow\n```"
        )

    if not df_anchor.empty:
        target = st.selectbox("Select Job Number", ["-- Select --"] + job_list,
                               key="mdb_job_sel")

        if target != "-- Select --":
            proj = get_proj(df_anchor, target)
            if proj is not None:
                job_header(proj)

                # Document completion dashboard
                st.markdown("#### 📊 Document Completion Status")
                check_tables = [
                    ("Quality Checklist",     "quality_check_list"),
                    ("Material Flow Chart",   "material_flow_charts"),
                    ("Nozzle Flow Chart",     "nozzle_flow_charts"),
                    ("Dimensional Report",    "dimensional_reports"),
                    ("Hydro Test Report",     "hydro_test_reports"),
                    ("Final Inspection",      "final_inspection_reports"),
                    ("Guarantee Certificate", "guarantee_certificates"),
                    ("Customer Feedback",     "customer_feedback"),
                ]

                doc_checks = {}
                cols = st.columns(4)
                for i, (label, table) in enumerate(check_tables):
                    try:
                        res = conn.table(table).select("id").eq("job_no", target).limit(1).execute()
                        exists = bool(res.data)
                    except Exception:
                        exists = False
                    doc_checks[label] = exists
                    with cols[i % 4]:
                        if exists:
                            st.success(f"✅ {label}")
                        else:
                            st.error(f"❌ {label}")

                # Photo log summary
                job_photo_rows = df_plan[
                    df_plan['job_no'].astype(str) == str(target)
                ]
                total_photos = job_photo_rows['quality_photo_url'].apply(
                    lambda x: len(x) if isinstance(x, list) else 0
                ).sum()

                completed_stages = job_photo_rows['quality_status'].notna().sum()
                total_stages     = len(job_photo_rows)

                col_a, col_b = st.columns(2)
                col_a.metric("Process Gates Inspected",
                             f"{int(completed_stages)} / {int(total_stages)}")
                col_b.metric("Evidence Photos (all ≤60 KB)",
                             f"{int(total_photos)}")

                try:
                    mtc_res = conn.table("project_certificates").select("id") \
                        .eq("job_no", target) \
                        .eq("cert_type", "Material Test Certificate (MTC)").execute()
                    mtc_count = len(mtc_res.data) if mtc_res.data else 0
                    st.info(f"📎 {mtc_count} MTC(s) uploaded — will be appended to the Data Book")
                except Exception:
                    mtc_count = 0

                completed = sum(doc_checks.values())
                st.progress(completed / len(doc_checks))
                st.caption(f"{completed} of {len(doc_checks)} quality documents completed")

                st.divider()

                if st.button("🚀 COMPILE MASTER DATA BOOK", type="primary",
                              use_container_width=True, disabled=not PDF_AVAILABLE):
                    with st.spinner("⚡ Fetching data, stitching photos, appending MTCs…"):
                        try:
                            final_pdf = generate_master_data_book(target, proj, df_plan)
                            st.success("✅ Master Quality Data Book compiled successfully!")
                            st.download_button(
                                label="📥 Download Data Book PDF",
                                data=final_pdf,
                                file_name=f"BGE_DataBook_{target}.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                        except Exception as e:
                            st.error(f"Compilation error: {e}")

# ============================================================
# TAB 13: CONFIG
# ============================================================
with main_tabs[13]:
    st.header("⚙️ Portal Configuration & Master Data")

    config_mode = st.radio(
        "Configure:",
        ["Inspection Parameters", "Staff & Inspectors"],
        horizontal=True
    )

    if config_mode == "Inspection Parameters":
        report_cat = st.selectbox("Select List to Configure", [
            "Dimensional Descriptions",
            "MOC List",
            "Technical Checklist"
        ])

        try:
            conf_res = conn.table("quality_config").select("*") \
                .eq("category", report_cat).execute()
            df_conf = pd.DataFrame(conf_res.data) if conf_res.data else \
                pd.DataFrame(columns=["parameter_name","equipment_type","default_design_value"])
        except Exception:
            df_conf = pd.DataFrame(columns=["parameter_name","equipment_type","default_design_value"])

        col_cfg = {
            "parameter_name": st.column_config.TextColumn("Parameter Name", required=True),
            "equipment_type": st.column_config.SelectboxColumn(
                "Applicability",
                options=["General","Reactor","Storage Tank","Heat Exchanger","Receiver"],
                default="General"
            ),
            "default_design_value": st.column_config.TextColumn("Default / Standard Ref."),
            "category": None, "id": None, "created_at": None
        }

        edited_conf = st.data_editor(
            df_conf, num_rows="dynamic", use_container_width=True,
            key=f"config_editor_{report_cat}", column_config=col_cfg, hide_index=True
        )

        if st.button(f"💾 Sync {report_cat}", type="primary"):
            try:
                cleaned = [
                    {
                        "category":             report_cat,
                        "parameter_name":       str(r.get('parameter_name','')).strip(),
                        "equipment_type":       r.get('equipment_type','General'),
                        "default_design_value": r.get('default_design_value','')
                    }
                    for r in edited_conf.to_dict('records')
                    if str(r.get('parameter_name','')).strip() not in ['','None','nan']
                ]
                conn.table("quality_config").delete().eq("category", report_cat).execute()
                if cleaned:
                    conn.table("quality_config").insert(cleaned).execute()
                st.success(f"✅ {report_cat} updated with {len(cleaned)} items!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Sync Error: {e}")

    else:
        st.subheader("👨‍🔧 Master Staff / Inspectors")
        st.write("**Current Inspectors:**", ", ".join(inspectors))
        st.divider()
        with st.form("add_staff_form", clear_on_submit=True):
            s1, s2 = st.columns(2)
            new_name = s1.text_input("Name")
            new_role = s2.selectbox("Role", [
                "QC Inspector","Production I/C","QA Engineer","Manager","Other"
            ])
            if st.form_submit_button("➕ Add Staff"):
                if new_name:
                    safe_write(
                        lambda: conn.table("master_staff").insert({
                            "name":       new_name.strip().title(),
                            "role":       new_role,
                            "created_at": get_now_ist().isoformat()
                        }).execute(),
                        success_msg=f"✅ {new_name} added!",
                        error_prefix="Staff Add Error"
                    )
                    st.cache_data.clear()
                    st.rerun()
