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
st.set_page_config(page_title="B&G Quality Portal", layout="wide", page_icon="🔍")
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

def proj_get(proj, key, default='N/A'):
    """Safe getter for both dict and pandas Series."""
    try:
        v = proj[key]
        return default if (v is None or (isinstance(v, float) and pd.isna(v))) else v
    except (KeyError, IndexError):
        return default


def clean_rows(rows: list) -> list:
    """
    Strip NaN/inf floats from data_editor rows before JSON serialisation.
    Supabase rejects NaN with "Out of range float values are not JSON compliant".
    """
    import math
    result = []
    for row in rows:
        cleaned = {}
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                cleaned[k] = None
            elif k in ('Sl', 'Sl_No', 'QTY') and v is not None:
                try:    cleaned[k] = int(v)
                except: cleaned[k] = v
            else:
                cleaned[k] = v
        # drop phantom empty rows
        non_empty = [vv for kk, vv in cleaned.items()
                     if kk not in ('Sl', 'Sl_No') and vv not in (None, '', 'None')]
        if non_empty:
            result.append(cleaned)
    return result

# ============================================================
# 3. PHOTO COMPRESSION — 60 KB MAX, PASSPORT SIZE (400x500 px)
# ============================================================
PHOTO_MAX_BYTES  = 60 * 1024
PHOTO_MAX_PX     = (400, 500)
PHOTO_QUALITY_HI = 60
PHOTO_QUALITY_LO = 40

def compress_photo(uploaded_file) -> bytes:
    img = Image.open(uploaded_file)
    if img.mode in ("P", "RGBA", "LA"):
        img = img.convert("RGB")
    img.thumbnail(PHOTO_MAX_PX, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=PHOTO_QUALITY_HI, optimize=True)
    if buf.tell() > PHOTO_MAX_BYTES:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=PHOTO_QUALITY_LO, optimize=True)
    return buf.getvalue()

def upload_photos(photos, job_no, gate_name) -> list:
    urls = []
    for i, photo_file in enumerate(photos[:4]):
        try:
            compressed = compress_photo(photo_file)
            ts        = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_job  = str(job_no).replace('/', '-')
            safe_gate = str(gate_name).replace(' ', '_')
            file_name = f"{safe_job}/{safe_gate}_{ts}_{i}.jpg"
            conn.client.storage.from_("quality-photos").upload(
                path=file_name, file=compressed,
                file_options={"content-type": "image/jpeg"}
            )
            url = conn.client.storage.from_("quality-photos").get_public_url(file_name)
            urls.append(url)
        except Exception as e:
            st.warning(f"Photo {i+1} upload failed: {e}")
    return urls

# ============================================================
# 4. PDF UTILITIES
# ============================================================
def _pdf_safe(text: str) -> str:
    """Map unicode/emoji to ASCII equivalents safe for FPDF latin-1 fonts."""
    replacements = {
        "✅": "PASS", "❌": "FAIL", "⚠️": "WARN", "⚠": "WARN",
        "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2022": "*", "\u00b2": "2",
        "\u00b3": "3", "\u00b0": "deg", "\u2264": "<=", "\u2265": ">=",
        "\u00d7": "x", "\u00f7": "/", "\u2212": "-", "\u00e9": "e",
        "\u2026": "...", "\u00a0": " ", "\u2192": "->", "\u2190": "<-",
    }
    for ch, sub in replacements.items():
        text = text.replace(ch, sub)
    return text.encode("latin-1", errors="ignore").decode("latin-1")

def _row_band(pdf, i):
    """Alternate white / light-grey row background."""
    if i % 2 == 0:
        pdf.set_fill_color(245, 245, 245)
    else:
        pdf.set_fill_color(255, 255, 255)

# ============================================================
# 5. MASTER DATA BOOK PDF GENERATOR — FULL COVERAGE
# ============================================================
def generate_master_data_book(job_no, project_info, df_plan):
    if not PDF_AVAILABLE:
        raise RuntimeError("fpdf2 and pypdf are not installed.")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    MARGIN = 10
    PAGE_W = 190  # usable width

    # Asset loading
    logo_path = stamp_path = None
    try:
        for fname, attr in [("logo.png", "logo"), ("round_stamp.png", "stamp")]:
            data = conn.client.storage.from_("progress-photos").download(fname)
            if data:
                with NamedTemporaryFile(delete=False, suffix=".png") as t:
                    t.write(data)
                    if attr == "logo":
                        logo_path = t.name
                    else:
                        stamp_path = t.name
    except Exception:
        pass

    def add_section_header(title):
        pdf.add_page()
        pdf.set_fill_color(0, 51, 102)
        pdf.rect(MARGIN, 8, PAGE_W, 12, 'F')
        if logo_path:
            try:
                pdf.image(logo_path, x=MARGIN + 1, y=9, h=10)
            except Exception:
                pass
        pdf.set_font("Arial", 'B', 10)
        pdf.set_text_color(255, 255, 255)
        # Start company name after logo (logo is ~20mm wide from x=11)
        pdf.set_xy(32, 9)
        pdf.cell(PAGE_W - 82, 10, "B&G ENGINEERING INDUSTRIES", align='L', ln=0)
        pdf.cell(60, 10, f"JOB: {_pdf_safe(str(job_no))}", align='R', ln=1)
        pdf.set_text_color(0, 51, 102)
        pdf.set_font("Arial", 'B', 11)
        pdf.set_xy(MARGIN, 24)
        pdf.cell(PAGE_W, 8, _pdf_safe(title), align='C', ln=1)
        pdf.set_draw_color(0, 51, 102)
        pdf.set_line_width(0.5)
        pdf.line(MARGIN, 33, MARGIN + PAGE_W, 33)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(5)

    def table_header(cols):
        pdf.set_fill_color(0, 51, 102)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", 'B', 8)
        for label, w in cols:
            pdf.cell(w, 7, _pdf_safe(label), border=1, align='C', fill=True, ln=0)
        pdf.ln()
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", '', 8)

    def kv_row(label, value, label_w=55):
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(label_w, 7, _pdf_safe(label + ":"), border="B", ln=0)
        pdf.set_font("Arial", '', 9)
        pdf.cell(PAGE_W - label_w, 7, _pdf_safe(str(value)), border="B", ln=1)

    # COVER PAGE
    pdf.add_page()
    pdf.set_draw_color(0, 51, 102)
    pdf.set_line_width(2)
    pdf.rect(5, 5, 200, 287)
    pdf.set_line_width(0.5)
    pdf.rect(7, 7, 196, 283)
    if logo_path:
        try:
            pdf.image(logo_path, x=70, y=25, w=70)
        except Exception:
            pass
    pdf.set_text_color(0, 51, 102)
    pdf.set_font("Arial", 'B', 28)
    pdf.set_y(105)
    pdf.cell(0, 14, "QUALITY DATA BOOK", align='C', ln=1)
    pdf.set_font("Arial", 'B', 13)
    pdf.cell(0, 10, "PRODUCT BIRTH CERTIFICATE", align='C', ln=1)
    pdf.set_y(150)
    pdf.set_text_color(0, 0, 0)
    cover_rows = [
        ("Job Number",     _pdf_safe(str(job_no))),
        ("Client",         _pdf_safe(str(proj_get(project_info, 'client_name')))),
        ("PO Reference",   _pdf_safe(str(proj_get(project_info, 'po_no')))),
        ("PO Date",        fmt_date(proj_get(project_info, 'po_date', ''))),
        ("Equipment",      _pdf_safe(str(
            next((r.get("equipment_name","") for r in
                  (conn.table("quality_check_list").select("item_name")
                   .eq("job_no",job_no).order("created_at",desc=True).limit(1).execute().data or [{}])),
                 proj_get(project_info,"equipment_type",""))
        ))),
        ("Report Date",    datetime.now().strftime('%d-%m-%Y')),
    ]
    for i, (k, v) in enumerate(cover_rows):
        if i % 2 == 0:
            pdf.set_fill_color(230, 238, 250)
        else:
            pdf.set_fill_color(255, 255, 255)
        pdf.set_font("Arial", 'B', 11)
        pdf.cell(70, 9, f"  {k}", border=1, fill=True, ln=0)
        pdf.set_font("Arial", '', 11)
        pdf.cell(120, 9, f"  {v}", border=1, fill=True, ln=1)
    if stamp_path:
        try:
            pdf.image(stamp_path, x=148, y=238, w=45)
        except Exception:
            pass
    pdf.set_xy(148, 283)
    pdf.set_font("Arial", 'B', 7)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(50, 5, "AUTHORIZED SIGNATORY", align='C', ln=1)

    # TABLE OF CONTENTS
    pdf.add_page()
    pdf.set_text_color(0, 51, 102)
    pdf.set_font("Arial", 'B', 14)
    pdf.set_y(20)
    pdf.cell(0, 12, "TABLE OF CONTENTS", align='C', ln=1)
    pdf.set_draw_color(0, 51, 102)
    pdf.line(MARGIN, 33, MARGIN + PAGE_W, 33)
    pdf.ln(4)
    toc = [
        "1.  Quality Check List",
        "2.  Quality Assurance Plan (QAP)",
        "3.  Material Flow Chart & Traceability",
        "4.  Nozzle Flow Chart",
        "5.  Dimensional Inspection Report (DIR)",
        "6.  Hydrostatic Test Report",
        "7.  Final Inspection Report (FIR)",
        "8.  Guarantee Certificate",
        "9.  Manufacturing Evidence Photo Log",
        "10. Material Test Certificates (MTC) -- Appended",
    ]
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", '', 11)
    for item in toc:
        pdf.cell(0, 10, f"   {item}", border="B", ln=1)

    # SECTION 1: QUALITY CHECK LIST
    try:
        qcl_res = conn.table("quality_check_list").select("*") \
            .eq("job_no", job_no).order("created_at", desc=True).limit(1).execute()
        if qcl_res.data:
            add_section_header("1. QUALITY CHECK LIST")
            q = qcl_res.data[0]
            kv_row("Item / Description",  q.get('item_name', 'N/A'))
            kv_row("Drawing Number",      q.get('drawing_no', 'N/A'))
            kv_row("QAP Reference No.",   q.get('qap_no', 'N/A'))
            kv_row("Equipment ID",        q.get('equipment_id_no', 'N/A'))
            kv_row("Quantity",            q.get('qty', 'N/A'))
            kv_row("Inspection Date",     fmt_date(q.get('inspection_date')))
            kv_row("Inspected By",        q.get('inspected_by', 'N/A'))
            pdf.ln(4)
            chk_cols = [("Check Point", 90), ("Verification", 35), ("Remarks", 65)]
            table_header(chk_cols)
            checkpoints = [
                ("Material Certification (Flow Chart)", q.get('mat_cert_status', '-'), ""),
                ("Fit-up Examination",                  q.get('fit_up_status', '-'),   ""),
                ("Dimensions & Visual Exam",             q.get('visual_status', '-'),   ""),
                ("PT of all Welds",                      q.get('pt_weld_status', '-'),  ""),
                ("Hydro / Vacuum Test",                  q.get('hydro_status', '-'),    ""),
                ("Final Inspection before Dispatch",     q.get('final_status', '-'),    ""),
                ("Identification Punching",              q.get('punching_status', '-'), ""),
                ("NCR (if any)",                         q.get('ncr_status', '-'),      ""),
            ]
            for i, (cp, verif, rem) in enumerate(checkpoints):
                _row_band(pdf, i)
                pdf.cell(90, 6, _pdf_safe(cp),    border=1, fill=True, ln=0)
                pdf.cell(35, 6, _pdf_safe(verif), border=1, align='C', fill=True, ln=0)
                pdf.cell(65, 6, _pdf_safe(rem),   border=1, fill=True, ln=1)
            if q.get('technical_notes'):
                pdf.ln(3)
                pdf.set_font("Arial", 'B', 9)
                pdf.cell(0, 6, "Technical Notes / Deviations:", ln=1)
                pdf.set_font("Arial", '', 9)
                pdf.multi_cell(0, 5, _pdf_safe(str(q.get('technical_notes', ''))))
    except Exception as e:
        st.warning(f"QCL section skipped: {e}")

    # SECTION 2: QAP
    try:
        qap_res = conn.table("nozzle_flow_charts").select("*") \
            .eq("job_no", job_no).order("created_at", desc=True).execute()
        qap_data = None
        for rec in (qap_res.data or []):
            if str(rec.get('nozzle_mark', '')).startswith('BGEI'):
                qap_data = rec
                break
        if qap_data:
            add_section_header("2. QUALITY ASSURANCE PLAN (QAP)")
            kv_row("QAP Document No.", qap_data.get('nozzle_mark', 'N/A'))
            kv_row("Equipment Name",   qap_data.get('equipment_name', 'N/A'))
            kv_row("Prepared By",      qap_data.get('verified_by', 'N/A'))
            pdf.ln(3)
            qap_cols = [("Sl", 8), ("Activity", 58), ("Class.", 20),
                        ("Type of Check", 35), ("Quantum", 18), ("QA", 12), ("B&G", 12), ("Ref Doc", 27)]
            table_header(qap_cols)
            for i, row in enumerate(qap_data.get('traceability_data', [])):
                _row_band(pdf, i)
                pdf.cell(8,  6, str(row.get('Sl', '')),                           border=1, align='C', fill=True, ln=0)
                pdf.cell(58, 6, _pdf_safe(str(row.get('Activity', '')))[:38],     border=1, fill=True, ln=0)
                pdf.cell(20, 6, _pdf_safe(str(row.get('Classification', '')))[:14], border=1, align='C', fill=True, ln=0)
                pdf.cell(35, 6, _pdf_safe(str(row.get('Type_of_Check', '')))[:24], border=1, fill=True, ln=0)
                pdf.cell(18, 6, _pdf_safe(str(row.get('Quantum', ''))),            border=1, align='C', fill=True, ln=0)
                pdf.cell(12, 6, _pdf_safe(str(row.get('QA', ''))),                border=1, align='C', fill=True, ln=0)
                pdf.cell(12, 6, _pdf_safe(str(row.get('BG', ''))),                border=1, align='C', fill=True, ln=0)
                pdf.cell(27, 6, _pdf_safe(str(row.get('Ref_Document', '')))[:18], border=1, fill=True, ln=1)
    except Exception as e:
        st.warning(f"QAP section skipped: {e}")

    # SECTION 3: MATERIAL FLOW CHART
    try:
        mfc_res = conn.table("material_flow_charts").select("*") \
            .eq("job_no", job_no).order("created_at", desc=True).limit(1).execute()
        if mfc_res.data:
            add_section_header("3. MATERIAL FLOW CHART & TRACEABILITY")
            m = mfc_res.data[0]
            kv_row("Equipment",   m.get('item_name', 'N/A'))
            kv_row("Quantity",    m.get('qty', 'N/A'))
            kv_row("Verified By", m.get('verified_by', 'N/A'))
            pdf.ln(3)
            mfc_cols = [("Sl", 10), ("Description", 52), ("Size", 38),
                        ("MOC", 18), ("Test Report No.", 38), ("Heat No.", 34)]
            table_header(mfc_cols)
            for i, row in enumerate(m.get('traceability_data', [])):
                _row_band(pdf, i)
                pdf.cell(10, 6, str(row.get('Sl', '')),                          border=1, align='C', fill=True, ln=0)
                pdf.cell(52, 6, _pdf_safe(str(row.get('Description', '')))[:30], border=1, fill=True, ln=0)
                pdf.cell(38, 6, _pdf_safe(str(row.get('Size', '')))[:22],        border=1, fill=True, ln=0)
                pdf.cell(18, 6, _pdf_safe(str(row.get('MOC', ''))),              border=1, align='C', fill=True, ln=0)
                pdf.cell(38, 6, _pdf_safe(str(row.get('Test_Report_No', '')))[:22], border=1, fill=True, ln=0)
                pdf.cell(34, 6, _pdf_safe(str(row.get('Heat_No', '')))[:20],     border=1, fill=True, ln=1)
            if m.get('remarks'):
                pdf.ln(3)
                pdf.set_font("Arial", 'I', 8)
                pdf.multi_cell(0, 5, _pdf_safe(f"Remarks: {m['remarks']}"))
    except Exception as e:
        st.warning(f"MFC section skipped: {e}")

    # SECTION 4: NOZZLE FLOW CHART
    try:
        nfc_res = conn.table("nozzle_flow_charts").select("*") \
            .eq("job_no", job_no).order("created_at", desc=True).execute()
        nfc_data = None
        for rec in (nfc_res.data or []):
            if not str(rec.get('nozzle_mark', '')).startswith('BGEI'):
                nfc_data = rec
                break
        if nfc_data:
            add_section_header("4. NOZZLE FLOW CHART & TRACEABILITY")
            kv_row("Equipment",    nfc_data.get('equipment_name', 'N/A'))
            kv_row("DWG / Mark",   nfc_data.get('nozzle_mark', 'N/A'))
            kv_row("Inspected By", nfc_data.get('verified_by', 'N/A'))
            pdf.ln(3)
            nfc_cols = [("Nozzle", 18), ("Description", 48), ("Qty", 10),
                        ("Size NB", 25), ("MOC", 15), ("Test Report No.", 38), ("Heat No.", 36)]
            tdata = nfc_data.get('traceability_data', {})
            for section_title, rows in [("Flanges", tdata.get('flanges', [])),
                                         ("Pipes",   tdata.get('pipes', []))]:
                if rows:
                    pdf.set_font("Arial", 'B', 9)
                    pdf.set_text_color(0, 51, 102)
                    pdf.cell(0, 6, section_title, ln=1)
                    pdf.set_text_color(0, 0, 0)
                    table_header(nfc_cols)
                    for i, row in enumerate(rows):
                        _row_band(pdf, i)
                        pdf.cell(18, 6, _pdf_safe(str(row.get('Nozzle_No', ''))),      border=1, align='C', fill=True, ln=0)
                        pdf.cell(48, 6, _pdf_safe(str(row.get('Description', '')))[:28], border=1, fill=True, ln=0)
                        pdf.cell(10, 6, str(row.get('QTY', '')),                        border=1, align='C', fill=True, ln=0)
                        pdf.cell(25, 6, _pdf_safe(str(row.get('Size_NB', ''))),          border=1, fill=True, ln=0)
                        pdf.cell(15, 6, _pdf_safe(str(row.get('MOC', ''))),              border=1, align='C', fill=True, ln=0)
                        pdf.cell(38, 6, _pdf_safe(str(row.get('Test_Report_No', '')))[:22], border=1, fill=True, ln=0)
                        pdf.cell(36, 6, _pdf_safe(str(row.get('Heat_No', '')))[:20],    border=1, fill=True, ln=1)
                    pdf.ln(2)
    except Exception as e:
        st.warning(f"NFC section skipped: {e}")

    # SECTION 5: DIMENSIONAL INSPECTION REPORT
    try:
        dim_res = conn.table("dimensional_reports").select("*") \
            .eq("job_no", job_no).order("created_at", desc=True).limit(1).execute()
        if dim_res.data:
            add_section_header("5. DIMENSIONAL INSPECTION REPORT (DIR)")
            d = dim_res.data[0]
            kv_row("Drawing No.",     d.get('drawing_no', 'N/A'))
            kv_row("Inspection Date", fmt_date(d.get('inspection_date')))
            kv_row("Inspected By",    d.get('inspected_by', 'N/A'))
            pdf.ln(3)
            dir_cols = [("Sl", 10), ("Description", 55), ("Specified Dimension", 55),
                        ("Measured Dimension", 55), ("MOC", 15)]
            table_header(dir_cols)
            for i, row in enumerate(d.get('dim_grid_data', [])):
                _row_band(pdf, i)
                pdf.cell(10, 6, str(row.get('Sl_No', '')),                              border=1, align='C', fill=True, ln=0)
                pdf.cell(55, 6, _pdf_safe(str(row.get('Description', '')))[:32],        border=1, fill=True, ln=0)
                pdf.cell(55, 6, _pdf_safe(str(row.get('Specified_Dimension', '')))[:28], border=1, fill=True, ln=0)
                pdf.cell(55, 6, _pdf_safe(str(row.get('Measured_Dimension', '')))[:28], border=1, fill=True, ln=0)
                pdf.cell(15, 6, _pdf_safe(str(row.get('MOC', ''))),                     border=1, align='C', fill=True, ln=1)
    except Exception as e:
        st.warning(f"DIR section skipped: {e}")

    # SECTION 6: HYDRO TEST REPORT
    try:
        hydro_res = conn.table("hydro_test_reports").select("*") \
            .eq("job_no", job_no).order("created_at", desc=True).execute()
        if hydro_res.data:
            add_section_header("6. HYDROSTATIC / PNEUMATIC TEST REPORT")
            for idx, report in enumerate(hydro_res.data):
                if idx > 0:
                    pdf.ln(5)
                    pdf.set_draw_color(180, 180, 180)
                    pdf.line(MARGIN, pdf.get_y(), MARGIN + PAGE_W, pdf.get_y())
                    pdf.ln(3)
                kv_row("Equipment",       report.get('equipment_name', 'N/A'))
                kv_row("Test Pressure",   f"{report.get('test_pressure', 'N/A')} Kg/cm2")
                kv_row("Design Pressure", f"{report.get('design_pressure', 'N/A')} Kg/cm2")
                kv_row("Holding Time",    report.get('holding_time', 'N/A'))
                kv_row("Test Medium",     report.get('test_medium', 'N/A'))
                kv_row("Gauge No(s)",     report.get('gauge_nos', 'N/A'))
                kv_row("Inspected By",    report.get('inspected_by', 'N/A'))
                # Handle both column name variants
                witnessed = report.get('witnessed_by') or report.get('witness_name', 'N/A')
                kv_row("Witnessed By",    witnessed)
                kv_row("Observations",   report.get('inspection_notes', 'No leakages found.'))
    except Exception as e:
        st.warning(f"Hydro section skipped: {e}")

    # SECTION 7: FINAL INSPECTION REPORT
    try:
        fir_res = conn.table("final_inspection_reports").select("*") \
            .eq("job_no", job_no).order("created_at", desc=True).limit(1).execute()
        if fir_res.data:
            add_section_header("7. FINAL INSPECTION REPORT (FIR)")
            f = fir_res.data[0]
            kv_row("Equipment",           f.get('equipment_name', 'N/A'))
            kv_row("Tag / Equipment No.", f.get('tag_no', 'N/A'))
            kv_row("Ordered Qty",         f.get('ordered_qty', 'N/A'))
            kv_row("Offered for Insp.",   f.get('offered_qty', 'N/A'))
            kv_row("Accepted Qty",        f.get('accepted_qty', 'N/A'))
            kv_row("Inspection Result",   f.get('inspection_status', 'N/A'))
            kv_row("Inspected By",        f.get('inspected_by', 'N/A'))
            kv_row("Witnessed By",        f.get('witnessed_by', 'N/A'))
            if f.get('remarks'):
                pdf.ln(3)
                pdf.set_font("Arial", 'B', 9)
                pdf.cell(0, 6, "Final Observations:", ln=1)
                pdf.set_font("Arial", '', 9)
                pdf.multi_cell(0, 5, _pdf_safe(str(f['remarks'])))
    except Exception as e:
        st.warning(f"FIR section skipped: {e}")

    # SECTION 8: GUARANTEE CERTIFICATE
    try:
        gc_res = conn.table("guarantee_certificates").select("*") \
            .eq("job_no", job_no).order("created_at", desc=True).limit(1).execute()
        if gc_res.data:
            add_section_header("8. GUARANTEE CERTIFICATE")
            g = gc_res.data[0]
            kv_row("Equipment",        g.get('equipment_name', 'N/A'))
            kv_row("Serial / Tag No.", g.get('serial_no', 'N/A'))
            kv_row("Invoice / Ref",    g.get('invoice_ref', 'N/A'))
            kv_row("Certified By",     g.get('certified_by', 'N/A'))
            kv_row("Date of Issue",    fmt_date(g.get('created_at')))
            pdf.ln(4)
            pdf.set_font("Arial", 'B', 9)
            pdf.cell(0, 6, "Guarantee Terms:", ln=1)
            pdf.set_font("Arial", '', 9)
            pdf.multi_cell(0, 5, _pdf_safe(str(g.get('guarantee_period', ''))))
            if g.get('remarks'):
                pdf.ln(2)
                pdf.multi_cell(0, 5, _pdf_safe(str(g['remarks'])))
            pdf.ln(10)
            pdf.set_draw_color(0, 51, 102)
            box_y = pdf.get_y()
            pdf.rect(MARGIN, box_y, PAGE_W, 25)
            pdf.set_y(box_y + 3)
            pdf.set_font("Arial", 'B', 9)
            pdf.cell(PAGE_W, 6, "For B&G Engineering Industries", align='C', ln=1)
            if stamp_path:
                try:
                    pdf.image(stamp_path, x=MARGIN + PAGE_W - 38, y=box_y - 2, w=35)
                except Exception:
                    pass
            pdf.ln(12)
            pdf.set_font("Arial", '', 8)
            pdf.cell(PAGE_W, 5, f"Authorised Signatory: {_pdf_safe(str(g.get('certified_by', '')))}",
                     align='C', ln=1)
    except Exception as e:
        st.warning(f"Guarantee section skipped: {e}")

    # SECTION 9: MANUFACTURING EVIDENCE PHOTO LOG
    job_photos = (
        df_plan[df_plan['job_no'].astype(str) == str(job_no)]
        .dropna(subset=['quality_updated_at'])
        .sort_values('quality_updated_at')
    )
    if not job_photos.empty:
        add_section_header("9. MANUFACTURING EVIDENCE PHOTO LOG")
        for _, row in job_photos.iterrows():
            gate   = _pdf_safe(str(row.get('gate_name', 'N/A')))
            result = _pdf_safe(str(row.get('quality_status', 'N/A')))
            insp   = _pdf_safe(str(row.get('quality_by', 'N/A')))
            notes  = _pdf_safe(str(row.get('quality_notes') or 'N/A'))
            upd    = fmt_date(row['quality_updated_at'])

            if pdf.get_y() > 235:
                add_section_header("9. MANUFACTURING EVIDENCE PHOTO LOG (CONT.)")

            pdf.set_fill_color(0, 51, 102)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Arial", 'B', 9)
            pdf.cell(PAGE_W, 7, f"  {gate}  |  {upd}  |  Result: {result}",
                     fill=True, border=0, ln=1)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Arial", '', 8)
            pdf.cell(30, 5, "Inspector:", border=0, ln=0)
            pdf.cell(PAGE_W - 30, 5, insp, border=0, ln=1)
            pdf.set_font("Arial", 'I', 8)
            pdf.multi_cell(PAGE_W, 5, f"Remarks: {notes}")
            pdf.ln(1)

            urls = row.get('quality_photo_url', [])
            if isinstance(urls, list) and len(urls) > 0:
                if pdf.get_y() > 210:
                    add_section_header("9. MANUFACTURING EVIDENCE PHOTO LOG (CONT.)")
                img_y   = pdf.get_y()
                img_w   = 58
                img_h   = 44
                placed  = 0
                for url in urls[:3]:
                    try:
                        r = requests.get(url, timeout=10)
                        if r.status_code == 200:
                            with NamedTemporaryFile(delete=False, suffix=".jpg") as t:
                                t.write(r.content)
                                tmp = t.name
                            pdf.image(tmp, x=MARGIN + placed * 65, y=img_y,
                                      w=img_w, h=img_h)
                            os.unlink(tmp)
                            placed += 1
                    except Exception:
                        continue
                if placed > 0:
                    pdf.set_y(img_y + img_h + 3)

            pdf.set_draw_color(180, 180, 180)
            pdf.line(MARGIN, pdf.get_y(), MARGIN + PAGE_W, pdf.get_y())
            pdf.ln(4)

    # STITCH + APPEND MTCs and Calibration Certificates
    report_buf = io.BytesIO(bytes(pdf.output()))
    report_buf.seek(0)
    merger = PdfWriter()
    merger.append(PdfReader(report_buf))
    for _cert_type in ["Material Test Certificate (MTC)", "Calibration Certificate"]:
        try:
            _cert_res = conn.table("project_certificates").select("file_url, file_name") \
                .eq("job_no", job_no).eq("cert_type", _cert_type).execute()
            for doc in (_cert_res.data or []):
                try:
                    r = requests.get(doc['file_url'], timeout=15)
                    if r.status_code == 200:
                        merger.append(PdfReader(io.BytesIO(r.content)))
                except Exception:
                    continue
        except Exception:
            pass

    for p in [logo_path, stamp_path]:
        if p:
            try: os.unlink(p)
            except Exception: pass

    final_out = io.BytesIO()
    merger.write(final_out)
    data = final_out.getvalue()
    merger.close()
    return data

# ============================================================
# 6. DATA LOADERS
# ============================================================
@st.cache_data(ttl=60)
def get_quality_context():
    plan_res = conn.table("job_planning").select("*").execute()
    df_plan  = pd.DataFrame(plan_res.data or [])
    # Ensure quality_photo_url column always exists as list
    if 'quality_photo_url' not in df_plan.columns:
        df_plan['quality_photo_url'] = [[] for _ in range(len(df_plan))]
    else:
        df_plan['quality_photo_url'] = df_plan['quality_photo_url'].apply(
            lambda x: x if isinstance(x, list) else [])

    anchor_res    = conn.table("anchor_projects").select(
        "job_no, client_name, po_no, po_date, equipment_type").execute()
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

def job_header(proj, last_saved=None, record_count=None):
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
        c1.write(f"**Client:** {proj_get(proj, 'client_name')}")
        c2.write(f"**PO No:** {proj_get(proj, 'po_no')}")
        c3.write(f"**PO Date:** {fmt_date(proj_get(proj, 'po_date', ''))}")
        if last_saved:
            c4.success(f"Last saved: {fmt_date(last_saved)}")
        elif record_count is not None:
            c4.info(f"{record_count} record(s) saved")

# ============================================================
# 7. INITIALISE
# ============================================================
df_plan, df_anchor, inspectors = get_quality_context()
job_list = (sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
            if not df_anchor.empty else [])

# ============================================================
# 8. NAVIGATION HEADER
# ============================================================
st.markdown("""
<div style="background:#003366;color:white;padding:0.6rem 1rem;
            border-radius:8px;margin-bottom:1rem;">
  <b style="font-size:18px;">B&G Engineering — Quality Assurance Portal</b>
</div>
""", unsafe_allow_html=True)

main_tabs = st.tabs([
    "Process Gate", "Quality Checklist", "QAP",
    "Material Flow Chart", "Nozzle Flow Chart", "Dimensional Report",
    "Hydro Test", "Calibration", "Final Inspection",
    "Guarantee Certificate", "Customer Feedback",
    "Trial Run", "Document Vault", "Master Data Book", "Config",
])

# ============================================================
# TAB 0: PROCESS GATE
# ============================================================
with main_tabs[0]:
    st.subheader("Process Gate — Inspection & Evidence")
    gate_subtab, timeline_subtab, gallery_subtab = st.tabs([
        "Record Inspection", "Live Timeline", "Photo Gallery & Management"
    ])

    with gate_subtab:
        if not df_plan.empty:
            gc1, gc2 = st.columns(2)
            active_jobs = sorted(
                df_plan[df_plan['current_status'].str.upper().ne('PENDING')]
                ['job_no'].dropna().astype(str).unique().tolist()
            ) if 'current_status' in df_plan.columns else sorted(
                df_plan['job_no'].dropna().astype(str).unique().tolist()
            )
            sel_job = gc1.selectbox("Select Job", ["-- Select --"] + active_jobs, key="pg_insp_job")

            if sel_job != "-- Select --":
                job_stages   = df_plan[df_plan['job_no'].astype(str) == str(sel_job)]
                stage_names  = job_stages['gate_name'].dropna().tolist()
                sel_gate     = gc2.selectbox("Select Gate / Process Stage", stage_names, key="pg_insp_gate")
                stage_record = job_stages[job_stages['gate_name'] == sel_gate].iloc[0]
                st.divider()

                with st.form("inspection_entry_form", clear_on_submit=True):
                    st.markdown(f"#### Inspection: **{sel_job}** — **{sel_gate}**")
                    f1, f2 = st.columns(2)
                    with f1:
                        q_result  = st.selectbox("Inspection Result", ["Pass","Rework","Reject"], key="pg_result")
                        inspector = st.selectbox("Authorized Inspector", ["-- Select --"] + inspectors, key="pg_inspector")
                        q_notes   = st.text_area("Technical Observations",
                                                  placeholder="Record findings, measurements, deviations…")
                    with f2:
                        st.markdown("**Upload Evidence Photos** (max 4, auto-compressed to 60 KB passport size)")
                        q_photos = st.file_uploader("Photos", type=['png','jpg','jpeg'],
                                                    accept_multiple_files=True, key="pg_photos",
                                                    label_visibility="collapsed")
                        if q_photos:
                            for ph in q_photos[:4]:
                                st.caption(f"{ph.name} — {round(ph.size/1024,1)} KB raw")
                        if len(q_photos) > 4:
                            st.warning("Only the first 4 photos will be uploaded.")

                    if st.form_submit_button("Submit Inspection Record", use_container_width=True):
                        if inspector == "-- Select --":
                            st.error("Please select an authorized inspector.")
                        else:
                            with st.spinner("Compressing photos and saving…"):
                                try:
                                    all_urls  = upload_photos(q_photos[:4], sel_job, sel_gate) if q_photos else []
                                    record_id = int(stage_record['id'])
                                    conn.table("job_planning").update({
                                        "quality_status":     q_result,
                                        "quality_notes":      f"{get_now_ist().strftime('%d/%m %H:%M')}: {q_notes}",
                                        "quality_by":         inspector,
                                        "quality_photo_url":  all_urls,
                                        "quality_updated_at": get_now_ist().isoformat()
                                    }).eq("id", record_id).execute()
                                    st.success(f"Inspection saved for {sel_gate} with {len(all_urls)} photo(s).")
                                    st.cache_data.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Submission error: {e}")
        else:
            st.error("No planning data available.")

    with timeline_subtab:
        if not df_plan.empty:
            unique_jobs = sorted(df_plan['job_no'].dropna().astype(str).unique().tolist())
            sel_job_tl  = st.selectbox("Select Job", ["-- Select --"] + unique_jobs, key="pg_timeline_job")
            if sel_job_tl != "-- Select --":
                p_data = (df_plan[df_plan['job_no'].astype(str) == str(sel_job_tl)]
                          .sort_values('quality_updated_at', na_position='last'))
                if not p_data.empty:
                    st.info(f"Evidence for **{sel_job_tl}**. Final stamped report -> Master Data Book tab.")
                    for _, row in p_data.iterrows():
                        update_date = (fmt_date(row.get('quality_updated_at'))
                                       if pd.notna(row.get('quality_updated_at')) else "Pending")
                        with st.container(border=True):
                            c1, c2 = st.columns([1, 3])
                            status = str(row.get('quality_status', '')).upper()
                            if any(w in status for w in ['PASS', 'ACCEPT', 'OK']):
                                c1.success(f"PASS — {row['gate_name']}")
                            elif any(w in status for w in ['REWORK', 'REJECT', 'FAIL']):
                                c1.error(f"FAIL — {row['gate_name']}")
                            elif status and status not in ['', 'NONE', 'NAN']:
                                c1.warning(f"WARN — {row['gate_name']}")
                            else:
                                c1.info(f"Pending — {row['gate_name']}")
                            c2.write(f"**Date:** {update_date} | **Inspector:** {row.get('quality_by','—')}")
                            c2.write(f"**Remarks:** {row.get('quality_notes') or 'No remarks'}")
                            urls = row.get('quality_photo_url', [])
                            if isinstance(urls, list) and urls:
                                cols = st.columns(min(4, len(urls)))
                                for i, url in enumerate(urls[:4]):
                                    try:    cols[i].image(url, use_container_width=True, caption=f"Evidence {i+1}")
                                    except: cols[i].caption(f"Photo {i+1}")
                else:
                    st.warning("No quality records found for this job yet.")

    with gallery_subtab:
        if not df_plan.empty:
            inspected_df = df_plan.dropna(subset=['quality_status']).sort_values('quality_updated_at', ascending=False)
            if not inspected_df.empty:
                photo_rows = inspected_df[inspected_df['quality_photo_url'].apply(
                    lambda x: isinstance(x, list) and len(x) > 0)]
                if not photo_rows.empty:
                    sel_idx = st.selectbox(
                        "Select record to manage", photo_rows.index,
                        format_func=lambda x: (
                            f"{photo_rows.loc[x,'job_no']} — "
                            f"{photo_rows.loc[x,'gate_name']} "
                            f"({fmt_date(photo_rows.loc[x,'quality_updated_at'])})"
                        ), key="gallery_sel"
                    )
                    current_urls = photo_rows.loc[sel_idx, 'quality_photo_url']
                    record_id    = photo_rows.loc[sel_idx, 'id']
                    st.caption(f"{len(current_urls)} photo(s) — all 60 KB / passport size")
                    cols = st.columns(4)
                    for i, url in enumerate(current_urls):
                        with cols[i % 4]:
                            try: st.image(url, use_container_width=True, caption=f"Photo {i+1}")
                            except: st.caption(f"Photo {i+1}")
                            if st.button("Remove", key=f"del_{record_id}_{i}"):
                                try:
                                    file_name = "/".join(url.split("/")[-2:])
                                    conn.client.storage.from_("quality-photos").remove([file_name])
                                    updated = [u for u in current_urls if u != url]
                                    conn.table("job_planning").update(
                                        {"quality_photo_url": updated}).eq("id", record_id).execute()
                                    st.toast("Photo removed.")
                                    st.cache_data.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Delete failed: {e}")
                else:
                    st.info("No photos uploaded yet.")
            else:
                st.info("No inspections recorded yet.")

# ============================================================
# TAB 1: QUALITY CHECK LIST
# ============================================================
with main_tabs[1]:
    st.subheader("Quality Check List")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="qcl_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            _qcl_prev = {}
            try:
                existing = conn.table("quality_check_list").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(5).execute()
                if existing.data:
                    _qcl_prev = existing.data[0]
            except Exception: pass
            job_header(proj, last_saved=_qcl_prev.get("created_at") if _qcl_prev else None)
            if existing.data:
                with st.expander(f"{len(existing.data)} saved record(s) — click to review"):
                    df_ex     = pd.DataFrame(existing.data)
                    cols_show = [c for c in ['inspection_date','item_name','drawing_no',
                                              'mat_cert_status','fit_up_status','inspected_by']
                                 if c in df_ex.columns]
                    st.dataframe(df_ex[cols_show], use_container_width=True, hide_index=True)

            # ── Equipment Details (outside form so checkpoint buttons work) ──
            st.markdown("#### Equipment Details")
            r1, r2, r3 = st.columns(3)
            item_n   = r1.text_input("Name of Item / Description",
                          value=_qcl_prev.get("item_name","30KL SS304 OIL HOLDING TANK"), key="qcl_item")
            drg_n    = r2.text_input("Drawing Number",
                          value=_qcl_prev.get("drawing_no","3050101710"), key="qcl_drg")
            qap_n    = r3.text_input("QAP Reference No.",
                          value=_qcl_prev.get("qap_no","BGEI/2025-26/1500"), key="qcl_qap")
            r4, r5, r6 = st.columns(3)
            e_id     = r4.text_input("Equipment ID No.",
                          value=_qcl_prev.get("equipment_id_no",""), key="qcl_eid")
            qty_val  = r5.text_input("Quantity",
                          value=_qcl_prev.get("qty","1 No."), key="qcl_qty")
            ins_date = r6.date_input("Inspection Date", value=get_now_ist().date(), key="qcl_date")

            # ── Inspection Check Points ──────────────────────────────────
            st.markdown("#### Inspection Check Points")
            st.caption("W = Witnessed | V = Verified | R = Review | NIL = Not Applicable")

            _ck_key = f"qcl_checkpoints_{sel_job}"
            _default_checkpoints = [
                {"checkpoint": "Material Certification — Material Flow Chart",   "extent": "100%",            "format": "Material Flow Chart"},
                {"checkpoint": "Material Certification — Mat Test Certificates", "extent": "100%",            "format": "Mat Test Certificates"},
                {"checkpoint": "Fit-up Exam",                                    "extent": "100%",            "format": "Inspection Report"},
                {"checkpoint": "Dimensions & Visual Exam",                       "extent": "100%",            "format": "Inspection Report"},
                {"checkpoint": "PT of all Welds",                                "extent": "As per QAP/Dwg", "format": "LPI Report"},
                {"checkpoint": "Hydro Test / Vacuum Test Shell Side",            "extent": "100%",            "format": "Hydro Test Report"},
                {"checkpoint": "Final Inspection before Dispatch",               "extent": "100%",            "format": "Inspection Report"},
                {"checkpoint": "Identification Punching",                        "extent": "",                "format": "Punching"},
                {"checkpoint": "NCR If any",                                     "extent": "",                "format": "NC Report"},
            ]
            if _ck_key not in st.session_state:
                _saved_checks = _qcl_prev.get("checklist_data") if _qcl_prev else None
                if _saved_checks and isinstance(_saved_checks, list) and len(_saved_checks) > 0:
                    # Ensure verification/docs have valid option strings
                    _v_valid = {"W","V","R","NIL","P"}
                    _d_valid = {"Yes","No","NA"}
                    for _row in _saved_checks:
                        if _row.get("verification") not in _v_valid:
                            _row["verification"] = "W"
                        if _row.get("docs") not in _d_valid:
                            _row["docs"] = "Yes"
                    st.session_state[_ck_key] = _saved_checks
                else:
                    st.session_state[_ck_key] = [dict(r) for r in _default_checkpoints]

            # Add / Reset / Delete buttons — must be OUTSIDE any form
            _ba, _bb, _ = st.columns([1, 1, 6])
            if _ba.button("+ Add Row", key="qcl_add_row"):
                st.session_state[_ck_key].append(
                    {"checkpoint": "", "extent": "100%", "format": "Inspection Report"})
                st.rerun()
            if _bb.button("Reset Defaults", key="qcl_reset"):
                st.session_state[_ck_key] = [dict(r) for r in _default_checkpoints]
                st.rerun()

            # Column headers
            hcols = st.columns([4, 2, 2, 2, 2, 2, 1])
            for _h, _col in zip(["Check Point","Extent","Format",
                                  "Verification","Docs","Remarks",""], hcols):
                _col.markdown(f"**{_h}**")

            check_results = []
            _del_idx = None
            for i, row in enumerate(st.session_state[_ck_key]):
                gc = st.columns([4, 2, 2, 2, 2, 2, 1])
                cp     = gc[0].text_input("", value=row.get("checkpoint",""), key=f"qcl_cp_{i}", label_visibility="collapsed")
                ext    = gc[1].text_input("", value=row.get("extent",""),     key=f"qcl_ex_{i}", label_visibility="collapsed")
                fmt    = gc[2].text_input("", value=row.get("format",""),     key=f"qcl_fm_{i}", label_visibility="collapsed")
                _v_opts = ["W","V","R","NIL","P"]
                _d_opts = ["Yes","No","NA"]
                _sv = row.get("verification","W")
                _sd = row.get("docs","Yes")
                verif  = gc[3].selectbox("", _v_opts, key=f"qcl_v_{i}",
                           index=_v_opts.index(_sv) if _sv in _v_opts else 0,
                           label_visibility="collapsed")
                docs   = gc[4].selectbox("", _d_opts, key=f"qcl_d_{i}",
                           index=_d_opts.index(_sd) if _sd in _d_opts else 0,
                           label_visibility="collapsed")
                remark = gc[5].text_input("", value=row.get("remarks",""),
                           key=f"qcl_r_{i}", label_visibility="collapsed")
                if gc[6].button("🗑", key=f"qcl_del_{i}"):
                    _del_idx = i
                check_results.append({"checkpoint": cp, "extent": ext, "format": fmt,
                                      "verification": verif, "docs": docs, "remarks": remark})

            if _del_idx is not None:
                st.session_state[_ck_key].pop(_del_idx)
                st.rerun()

            # ── Authorization + Save (only these need to be in a form) ──
            st.markdown("#### Authorization")
            with st.form("qcl_form", clear_on_submit=False):
                _qcl_pi = _qcl_prev.get("inspected_by","")
                insp_by    = st.selectbox("Quality Inspector", inspectors, key="qcl_insp",
                               index=inspectors.index(_qcl_pi) if _qcl_pi in inspectors else 0)
                tech_notes = st.text_area("Technical Notes / Deviations",
                               value=_qcl_prev.get("technical_notes",""))

                if st.form_submit_button("Save Quality Check List", use_container_width=True):
                    def _get_verif(name_fragment):
                        for r in check_results:
                            if name_fragment.lower() in r["checkpoint"].lower():
                                return r["verification"]
                        return check_results[0]["verification"] if check_results else "W"
                    payload = {
                        "job_no":          sel_job,
                        "client_name":     proj_get(proj, 'client_name'),
                        "po_no":           proj_get(proj, 'po_no'),
                        "po_date":         str(proj_get(proj, 'po_date', '')),
                        "item_name":       item_n,
                        "drawing_no":      drg_n,
                        "qap_no":          qap_n,
                        "equipment_id_no": e_id,
                        "qty":             qty_val,
                        "mat_cert_status": _get_verif("flow chart"),
                        "fit_up_status":   _get_verif("fit-up"),
                        "visual_status":   _get_verif("visual"),
                        "pt_weld_status":  _get_verif("pt of all"),
                        "hydro_status":    _get_verif("hydro"),
                        "final_status":    _get_verif("final insp"),
                        "punching_status": _get_verif("punching"),
                        "ncr_status":      _get_verif("ncr"),
                        "checklist_data":  clean_rows(check_results) if check_results else [],
                        "technical_notes": tech_notes,
                        "inspected_by":    insp_by,
                        "inspection_date": str(ins_date),
                    }
                    ok = safe_write(
                        lambda: conn.table("quality_check_list").insert(payload).execute(),
                        success_msg=f"Quality Check List for {sel_job} saved!"
                    )
                    if ok:
                        # Update session state with what was just saved
                        st.session_state[_ck_key] = check_results
                        st.cache_data.clear()

# ============================================================
# TAB 2: QAP
# ============================================================
with main_tabs[2]:
    st.subheader("Quality Assurance Plan (QAP)")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="qap_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            _qap_prev = {}
            try:
                _r = conn.table("nozzle_flow_charts").select("*")\
                    .eq("job_no",sel_job).order("created_at",desc=True).execute()
                for _rec in (_r.data or []):
                    if str(_rec.get("nozzle_mark","")).startswith("BGEI"):
                        _qap_prev = _rec; break
            except Exception: pass
            job_header(proj, last_saved=_qap_prev.get("created_at") if _qap_prev else None)
            with st.form("qap_form", clear_on_submit=False):
                st.markdown("#### QAP Header")
                h1, h2, h3 = st.columns(3)
                qap_no     = h1.text_input("QAP Document No.",
                               value=_qap_prev.get("nozzle_mark", f"BGEI/2025-26/{sel_job}"))
                equip_name = h2.text_input("Equipment Name",
                               value=_qap_prev.get("equipment_name",""))
                _qv = _qap_prev.get("verified_by","")
                prep_by    = h3.selectbox("Prepared By", inspectors, key="qap_prep",
                               index=inspectors.index(_qv) if _qv in inspectors else 0)
                drg_no_qap = h1.text_input("Drawing No.", value=_qap_prev.get("drawing_no",""))
                h2.text_input("Client Name", value=proj_get(proj, 'client_name'))
                h3.text_input("PO No & Date",
                              value=f"{proj_get(proj,'po_no')} & {fmt_date(proj_get(proj,'po_date',''))}")

                st.markdown("#### Inspection Activity Grid")
                st.caption("W = Witness | R = Review | P = Perform | H = Hold Point")
                qap_template = pd.DataFrame([
                    {"Sl": 1, "Activity": "Plates - Material ID & TC Verification",
                     "Classification": "Major", "Type_of_Check": "Visual & TC Verification",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Mill/Lab T.Cs", "QA": "W", "BG": "W"},
                    {"Sl": 2, "Activity": "Nozzle pipes & Flanges - Material ID & TC",
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
                # Load saved grid rows; fallback to template
                _qap_grid_key = f"qap_grid_{sel_job}"
                if _qap_grid_key not in st.session_state:
                    _saved_td = _qap_prev.get("traceability_data")
                    if _saved_td and isinstance(_saved_td, list) and len(_saved_td) > 0:
                        _qap_df = pd.DataFrame(_saved_td)
                        # Ensure SelectboxColumn cols have valid string values
                        for _col, _def in [("Classification","Major"),("QA","W"),("BG","W")]:
                            if _col in _qap_df.columns:
                                _qap_df[_col] = _qap_df[_col].fillna(_def).astype(str)
                        st.session_state[_qap_grid_key] = _qap_df
                    else:
                        st.session_state[_qap_grid_key] = qap_template
                qap_grid = st.data_editor(st.session_state[_qap_grid_key], num_rows="dynamic",
                    use_container_width=True, hide_index=True, key=f"qap_editor_{sel_job}",
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
                    })
                note_qap = st.text_area("Notes / Legend", value=_qap_prev.get("remarks",""))
                if st.form_submit_button("Save QAP", use_container_width=True):
                    payload = {
                        "job_no":            sel_job,
                        "equipment_name":    equip_name,
                        "nozzle_mark":       qap_no,
                        "drawing_no":        drg_no_qap,
                        "traceability_data": clean_rows(qap_grid.to_dict('records')),
                        "verified_by":       prep_by,
                        "remarks":           note_qap,
                        "created_at":        get_now_ist().isoformat()
                    }
                    _qok = safe_write(
                        lambda: conn.table("nozzle_flow_charts").insert(payload).execute(),
                        success_msg=f"QAP for {sel_job} saved!"
                    )
                    if _qok:
                        st.session_state[_qap_grid_key] = pd.DataFrame(qap_grid.to_dict("records"))
                        st.cache_data.clear()

# ============================================================
# TAB 3: MATERIAL FLOW CHART
# ============================================================
with main_tabs[3]:
    st.subheader("Material Flow Chart & Traceability")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="mfc_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            # Pre-load last MFC record
            _mfc_prev = {}
            try:
                _mr = conn.table("material_flow_charts").select("*")\
                    .eq("job_no",sel_job).order("created_at",desc=True).limit(1).execute()
                if _mr.data: _mfc_prev = _mr.data[0]
            except Exception: pass
            job_header(proj, last_saved=_mfc_prev.get("created_at") if _mfc_prev else None)

            c1, c2 = st.columns(2)
            item_desc = c1.text_input("Equipment Description",
                          value=_mfc_prev.get("item_name",""))
            total_qty = c2.text_input("Quantity",
                          value=_mfc_prev.get("qty",""))

            st.markdown("#### Material Identification Matrix")
            mfc_template = pd.DataFrame([
                {"Sl": 1, "Description": "SHELL",            "Size": "ID2750X5100LX8THK",    "MOC": "SS304", "Test_Report_No": "2268648", "Heat_No": "50227B06C"},
                {"Sl": 2, "Description": "TOP DISH",          "Size": "ID2750X10THKX10%TORI", "MOC": "SS304", "Test_Report_No": "2265157", "Heat_No": "41204F12"},
                {"Sl": 3, "Description": "BOTTOM DISH",       "Size": "ID2750X10THKX10%TORI", "MOC": "SS304", "Test_Report_No": "2265157", "Heat_No": "41204F12"},
                {"Sl": 4, "Description": "BOTTOM LUGS",       "Size": "300CX1140LX8THK",       "MOC": "SS304", "Test_Report_No": "2268648", "Heat_No": "50227B06C"},
                {"Sl": 5, "Description": "LIFTING HOOKS",     "Size": "25THK",                 "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Sl": 6, "Description": "RF PADS",           "Size": "8THK",                  "MOC": "SS304", "Test_Report_No": "2268648", "Heat_No": "50227B06C"},
                {"Sl": 7, "Description": "BOTTOM BASE PLATE", "Size": "450LX450WX20THK",       "MOC": "SS304", "Test_Report_No": "2408309", "Heat_No": "50424B02C"},
                {"Sl": 8, "Description": "LADDER",            "Size": "32 & 25NB PIPE",        "MOC": "SS304", "Test_Report_No": "",        "Heat_No": ""},
                {"Sl": 9, "Description": "RAILING",           "Size": "32 & 25NB PIPE",        "MOC": "SS304", "Test_Report_No": "",        "Heat_No": ""},
            ])
            mfc_key = f"mfc_grid_{sel_job}"
            if mfc_key not in st.session_state:
                if _mfc_prev.get("traceability_data"):
                    _mfc_df = pd.DataFrame(_mfc_prev["traceability_data"])
                    # Fill NaN in string cols to prevent display issues
                    for _col in ["Description","Size","MOC","Test_Report_No","Heat_No"]:
                        if _col in _mfc_df.columns:
                            _mfc_df[_col] = _mfc_df[_col].fillna("").astype(str)
                    st.session_state[mfc_key] = _mfc_df
                else:
                    st.session_state[mfc_key] = mfc_template
            mfc_grid = st.data_editor(st.session_state[mfc_key], num_rows="dynamic",
                use_container_width=True, hide_index=True, key=f"mfc_editor_{sel_job}",
                column_config={
                    "Sl":             st.column_config.NumberColumn("Sl", width="small"),
                    "Description":    st.column_config.TextColumn("Description", width="large"),
                    "Size":           st.column_config.TextColumn("Size", width="medium"),
                    "MOC":            st.column_config.TextColumn("MOC", width="small"),
                    "Test_Report_No": st.column_config.TextColumn("Test Report No.", width="medium"),
                    "Heat_No":        st.column_config.TextColumn("Heat No.", width="medium"),
                })

            with st.form("mfc_form", clear_on_submit=False):
                _mv = _mfc_prev.get("verified_by","")
                verifier = st.selectbox("Verified By (QC)", inspectors, key="mfc_verifier",
                             index=inspectors.index(_mv) if _mv in inspectors else 0)
                mfc_rem  = st.text_area("Observations / Traceability Notes",
                             value=_mfc_prev.get("remarks",""))
                if st.form_submit_button("Save Material Flow Chart", use_container_width=True):
                    final_rows = clean_rows([{**r, "Sl": i+1} for i, r in enumerate(mfc_grid.to_dict('records'))])
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
                        success_msg=f"Material Flow Chart for {sel_job} saved!"
                    )
                    if ok:
                        st.session_state[mfc_key] = pd.DataFrame(final_rows)
                        st.cache_data.clear()

# ============================================================
# TAB 4: NOZZLE FLOW CHART
# ============================================================
with main_tabs[4]:
    st.subheader("Nozzle Flow Chart & Traceability")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="nfc_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            _nfc_prev = {}
            try:
                _nr = conn.table("nozzle_flow_charts").select("*")\
                    .eq("job_no",sel_job).order("created_at",desc=True).execute()
                for _rec in (_nr.data or []):
                    if not str(_rec.get("nozzle_mark","")).startswith("BGEI"):
                        _nfc_prev = _rec; break
            except Exception: pass
            job_header(proj, last_saved=_nfc_prev.get("created_at") if _nfc_prev else None)
            c1, c2 = st.columns(2)
            equip_name_nfc = c1.text_input("Equipment Name",
                               value=_nfc_prev.get("equipment_name",""))
            dwg_no_nfc     = c2.text_input("DWG No.",
                               value=_nfc_prev.get("nozzle_mark",""))
            nfc_col_cfg = {
                "Nozzle_No":      st.column_config.TextColumn("Nozzle No",      width="small"),
                "Description":    st.column_config.TextColumn("Description",     width="large"),
                "QTY":            st.column_config.NumberColumn("Qty",           width="small"),
                "Size_NB":        st.column_config.TextColumn("Size (NB)",       width="medium"),
                "MOC":            st.column_config.TextColumn("MOC",             width="small"),
                "Test_Report_No": st.column_config.TextColumn("Test Report No.", width="medium"),
                "Heat_No":        st.column_config.TextColumn("Heat No.",        width="medium"),
            }
            _nfc_td = _nfc_prev.get("traceability_data", {}) if _nfc_prev else {}
            _def_fl = [
                {"Nozzle_No":"N1","Description":"DRAIN","QTY":1,"Size_NB":"40NB","MOC":"SS304","Test_Report_No":"1846912","Heat_No":"40308B20"},
                {"Nozzle_No":"N2","Description":"OIL OUTLET","QTY":1,"Size_NB":"50NB","MOC":"SS304","Test_Report_No":"1846912","Heat_No":"40308B20"},
                {"Nozzle_No":"N3","Description":"OIL INLET","QTY":1,"Size_NB":"80X50NB","MOC":"SS304","Test_Report_No":"1846912","Heat_No":"40308B20"},
                {"Nozzle_No":"N6","Description":"MANHOLE","QTY":1,"Size_NB":"450NB","MOC":"SS304","Test_Report_No":"1846912","Heat_No":"40308B20"},
                {"Nozzle_No":"N17","Description":"OVER FLOW","QTY":1,"Size_NB":"100NB","MOC":"SS304","Test_Report_No":"1846912","Heat_No":"40308B20"},
            ]
            _def_pi = [
                {"Nozzle_No":"N1","Description":"DRAIN","QTY":1,"Size_NB":"40NB","MOC":"SS304","Test_Report_No":"WYYK8937","Heat_No":"K972180"},
                {"Nozzle_No":"N2","Description":"OIL OUTLET","QTY":1,"Size_NB":"50NB","MOC":"SS304","Test_Report_No":"WYYK8735","Heat_No":"F936215"},
                {"Nozzle_No":"N17","Description":"OVER FLOW","QTY":1,"Size_NB":"100NB","MOC":"SS304","Test_Report_No":"","Heat_No":""},
            ]
            _nfc_fl_key = f"nfc_flange_data_{sel_job}"
            _nfc_pi_key = f"nfc_pipe_data_{sel_job}"
            def _clean_nfc_df(rows):
                df = pd.DataFrame(rows)
                for _c in ["Nozzle_No","Description","Size_NB","MOC","Test_Report_No","Heat_No"]:
                    if _c in df.columns:
                        df[_c] = df[_c].fillna("").astype(str)
                return df
            if _nfc_fl_key not in st.session_state:
                _fl_saved = _nfc_td.get("flanges") if isinstance(_nfc_td, dict) else None
                st.session_state[_nfc_fl_key] = _clean_nfc_df(_fl_saved if _fl_saved else _def_fl)
            if _nfc_pi_key not in st.session_state:
                _pi_saved = _nfc_td.get("pipes") if isinstance(_nfc_td, dict) else None
                st.session_state[_nfc_pi_key] = _clean_nfc_df(_pi_saved if _pi_saved else _def_pi)

            st.markdown("#### Flanges Traceability")
            flange_grid = st.data_editor(st.session_state[_nfc_fl_key],
                num_rows="dynamic", use_container_width=True, hide_index=True,
                key=f"nfc_flange_{sel_job}", column_config=nfc_col_cfg)

            st.markdown("#### Pipes Traceability")
            pipe_grid = st.data_editor(st.session_state[_nfc_pi_key],
                num_rows="dynamic", use_container_width=True, hide_index=True,
                key=f"nfc_pipe_{sel_job}", column_config=nfc_col_cfg)

            with st.form("nfc_form", clear_on_submit=False):
                _nfc_pv = _nfc_prev.get("verified_by","")
                nfc_verifier = st.selectbox("Inspected By", inspectors, key="nfc_verifier",
                                index=inspectors.index(_nfc_pv) if _nfc_pv in inspectors else 0)
                nfc_remarks  = st.text_area("Orientation / Fit-up Remarks",
                                value=_nfc_prev.get("remarks",""))
                if st.form_submit_button("Save Nozzle Flow Chart"):
                    payload = {
                        "job_no":            sel_job,
                        "equipment_name":    equip_name_nfc,
                        "nozzle_mark":       dwg_no_nfc,
                        "traceability_data": {"flanges": clean_rows(flange_grid.to_dict('records')),
                                              "pipes":   clean_rows(pipe_grid.to_dict('records'))},
                        "verified_by":       nfc_verifier,
                        "remarks":           nfc_remarks,
                        "created_at":        get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("nozzle_flow_charts").insert(payload).execute(),
                        success_msg=f"Nozzle Flow Chart for {sel_job} saved!"
                    )
                    if ok:
                        st.session_state[_nfc_fl_key] = pd.DataFrame(flange_grid.to_dict("records"))
                        st.session_state[_nfc_pi_key] = pd.DataFrame(pipe_grid.to_dict("records"))
                        st.cache_data.clear()

# ============================================================
# TAB 5: DIMENSIONAL INSPECTION REPORT
# ============================================================
with main_tabs[5]:
    st.subheader("Dimensional Inspection Report (DIR)")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="dir_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            # Pre-load last DIR record
            _dir_prev = {}
            try:
                _dr = conn.table("dimensional_reports").select("*")\
                    .eq("job_no",sel_job).order("created_at",desc=True).limit(1).execute()
                if _dr.data: _dir_prev = _dr.data[0]
            except Exception: pass

            job_header(proj, last_saved=_dir_prev.get("created_at") if _dir_prev else None)
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Customer:** {proj_get(proj,'client_name')}")
                drg_no_dir  = c2.text_input("Drawing No.",
                               value=_dir_prev.get("drawing_no","3050101710"), key="dir_drg")
                _dir_date = get_now_ist().date()
                try:
                    if _dir_prev.get("inspection_date"):
                        _dir_date = pd.to_datetime(_dir_prev["inspection_date"]).date()
                except Exception: pass
                report_date = c3.date_input("Date", value=_dir_date, key="dir_date")
            st.caption(f"Report No: **BG/QA/DIR-{sel_job}**")

            options_desc = get_config("Dimensional Descriptions") or \
                ["Shell","Top Dish","Bottom Dish","Bottom Lugs","Ladder","Railing",
                 "Lifting Hooks","Nozzle Pipes","Nozzle Flanges","Overall weld Visual",
                 "Surface finish Inside","Surface finish Outside"]
            options_moc = get_config("MOC List") or ["SS304","SS316L","SS316","MS","CS","Duplex"]

            dir_key = f"dir_data_{sel_job}"
            if dir_key not in st.session_state:
                try:
                    if _dir_prev.get("dim_grid_data") and len(_dir_prev["dim_grid_data"]) > 0:
                        _dir_df = pd.DataFrame(_dir_prev["dim_grid_data"])
                        # Ensure SelectboxColumn cols have valid strings
                        for _col in ["Description","MOC"]:
                            if _col in _dir_df.columns:
                                _dir_df[_col] = _dir_df[_col].fillna("").astype(str)
                        st.session_state[dir_key] = _dir_df
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
                    "Description":         st.column_config.TextColumn("Description", width="large"),
                    "Specified_Dimension": st.column_config.TextColumn("Specified Dimension", width="large"),
                    "Measured_Dimension":  st.column_config.TextColumn("Measured Dimension",  width="large"),
                    "MOC":                 st.column_config.TextColumn("MOC", width="small"),
                })

            st.markdown("#### Acceptance Status")
            acc_cols = st.columns(4)
            acc1 = acc_cols[0].checkbox("Part accepted.",
                      value=bool(_dir_prev.get("part_accepted", False)))
            acc2 = acc_cols[1].checkbox("To be reworked.",
                      value=bool(_dir_prev.get("to_be_reworked", False)))
            acc3 = acc_cols[2].checkbox("Rejected (NCR enclosed)",
                      value=bool(_dir_prev.get("rejected", False)))
            acc4 = acc_cols[3].text_input("Deviation accepted reason",
                      value=str(_dir_prev.get("deviation_reason","") or ""))

            f1, f2, f3 = st.columns(3)
            _dpi = _dir_prev.get("inspected_by","")
            dir_insp = f1.selectbox("Executive (QA)", inspectors, key="dir_insp",
                         index=inspectors.index(_dpi) if _dpi in inspectors else 0)
            f2.text_input("TPI Name")
            f3.text_input("Customer Representative")

            if st.button("Save DIR Report", type="primary", use_container_width=True):
                final_rows = clean_rows([{**r, "Sl_No": i+1} for i, r in enumerate(dim_grid.to_dict('records'))])
                payload = {
                    "job_no":          sel_job,
                    "drawing_no":      drg_no_dir,
                    "inspection_date": str(report_date),
                    "dim_grid_data":   final_rows,
                    "inspected_by":    dir_insp,
                    "part_accepted":   bool(acc1),
                    "to_be_reworked":  bool(acc2),
                    "rejected":        bool(acc3),
                    "deviation_reason": str(acc4) if acc4 else "",
                    "created_at":      get_now_ist().isoformat()
                }
                ok = safe_write(
                    lambda: conn.table("dimensional_reports").insert(payload).execute(),
                    success_msg=f"DIR saved with {len(final_rows)} items!"
                )
                if ok:
                    st.session_state[dir_key] = pd.DataFrame(final_rows)
                    st.rerun()

# ============================================================
# TAB 6: HYDRO TEST REPORT
# ============================================================
with main_tabs[6]:
    st.subheader("Hydrostatic / Pneumatic Test Report")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="hydro_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            # Pre-load last hydro record for this job
            _hp = {}
            try:
                _hr = conn.table("hydro_test_reports").select("*")\
                    .eq("job_no",sel_job).order("created_at",desc=True).limit(1).execute()
                if _hr.data: _hp = _hr.data[0]
            except Exception: pass
            job_header(proj, last_saved=_hp.get("created_at") if _hp else None)

            with st.form("hydro_form", clear_on_submit=False):
                st.markdown("#### Report References")
                r1, r2, r3 = st.columns(3)
                report_no_h = r1.text_input("Test Report No.",    value=_hp.get("report_no", f"BG/QA/HTR-{sel_job}"))
                r2.text_input("FIR No.",                           value=f"BG/QA/FIR-{sel_job}")
                r3.text_input("Reference Document",                value="ASME SEC VIII DIVI.1 UG-99")
                e_name_h   = r1.text_input("Equipment Description", value=_hp.get("equipment_name",""))
                equip_no_h = r2.text_input("Equipment No.",          value=_hp.get("equip_no",""))
                drg_no_h   = r3.text_input("Drawing No.",            value=_hp.get("drawing_no",""))

                st.markdown("#### Test Parameters")
                p1, p2, p3 = st.columns(3)
                t_pressure    = p1.text_input("Test Pressure (Kg/cm2)",         value=_hp.get("test_pressure",""))
                d_pressure    = p2.text_input("Design Pressure (Kg/cm2)",        value=_hp.get("design_pressure",""))
                h_time        = p3.text_input("Holding Duration",                value=_hp.get("holding_time",""))
                p1b, p2b, p3b = st.columns(3)
                shell_pressure  = p1b.text_input("Shell Side Test Pressure (Kg/cm2)",  value=_hp.get("shell_pressure",""))
                jacket_pressure = p2b.text_input("Jacket Side Test Pressure (Kg/cm2)", value=_hp.get("jacket_pressure",""))
                p3b.text_input("Temperature", value="ATMP.")
                p4, p5, p6 = st.columns(3)
                _mo = ["Potable Water","WATER","Hydraulic Oil","Compressed Air","Nitrogen"]
                _mp = _hp.get("test_medium","Potable Water")
                medium = p4.selectbox("Test Medium", _mo, index=_mo.index(_mp) if _mp in _mo else 0)
                g_nos  = p5.text_input("Pressure Gauge ID(s)", value=_hp.get("gauge_nos",""))
                h_remarks = st.text_area("Observations",
                              value=_hp.get("inspection_notes","No leakages found during the test period."))

                st.markdown("#### Authorization")
                w1, w2, w3 = st.columns(3)
                _hpi = _hp.get("inspected_by","")
                insp_h = w1.selectbox("Executive (QA)", inspectors, key="hydro_insp",
                           index=inspectors.index(_hpi) if _hpi in inspectors else 0)
                wit_h  = w2.text_input("Customer / TPI Witness", value=_hp.get("witnessed_by",""))
                w3.text_input("Production I/C")

                if st.form_submit_button("Save Hydro Test Report", use_container_width=True):
                    payload = {
                        "job_no":           sel_job,
                        "equipment_name":   e_name_h,
                        "equip_no":         equip_no_h,
                        "drawing_no":       drg_no_h,
                        "report_no":        report_no_h,
                        "test_pressure":    t_pressure,
                        "design_pressure":  d_pressure,
                        "shell_pressure":   shell_pressure,
                        "jacket_pressure":  jacket_pressure,
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
                        success_msg=f"Hydro Test Report {report_no_h} saved!"
                    )
                    if ok:
                        st.cache_data.clear()

# ============================================================
# TAB 7: CALIBRATION CERTIFICATE
# ============================================================
with main_tabs[7]:
    st.subheader("Calibration Certificate — Upload & View")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="cal_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)
            # Pre-load last calibration record
            _cal_prev = {}
            try:
                _cr = conn.table("quality_inspection_logs").select("*")\
                    .eq("job_no",sel_job).eq("quality_status","Calibrated")\
                    .order("created_at",desc=True).limit(1).execute()
                if _cr.data: _cal_prev = _cr.data[0]
            except Exception: pass
            job_header(proj, last_saved=_cal_prev.get("created_at") if _cal_prev else None)
            with st.form("cal_form", clear_on_submit=False):
                st.markdown("#### Calibration Details")
                c1, c2, c3 = st.columns(3)
                cal_report_no = c1.text_input("Report No.",   value=_cal_prev.get("gauge_id",""))
                instrument    = c2.text_input("Instrument",   value=_cal_prev.get("moc_type",""))
                make          = c3.text_input("Make",         value=_cal_prev.get("specified_val",""))
                sr_no         = c1.text_input("Sr. No.",      value=_cal_prev.get("measured_val",""))
                range_val     = c2.text_input("Range",        value=_cal_prev.get("gauge_cal_due",""))
                least_count   = c3.text_input("Least Count",  placeholder="e.g. 0.1 kg/cm2")
                c4, c5 = st.columns(2)
                c4.date_input("Date of Calibration", value=get_now_ist().date())
                _cal_due = get_now_ist().date()
                try:
                    if _cal_prev.get("gauge_cal_due"):
                        _cal_due = pd.to_datetime(_cal_prev["gauge_cal_due"]).date()
                except Exception: pass
                cal_due_date = c5.date_input("Calibration Due Date", value=_cal_due)
                _prev_notes = _cal_prev.get("quality_notes","")
                _prev_rem = _prev_notes.split(" | ")[-1] if " | " in _prev_notes else _prev_notes
                cal_remarks  = st.text_area("Calibration Remarks",
                    value=_prev_rem or "The Instrument is Satisfactory with respect to the Specified limits.")
                _prev_cal_by = _cal_prev.get("inspector_name","")
                cal_by = st.text_input("Calibrated By", value=_prev_cal_by)
                st.markdown("#### Upload Certificate (PDF / Image)")
                cal_file = st.file_uploader("Upload scanned certificate",
                                            type=['pdf','jpg','png'], key="cal_upload")
                if st.form_submit_button("Save & Upload Calibration Record"):
                    if cal_file:
                        try:
                            ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
                            file_path = f"{sel_job}/CAL_{ts}_{cal_file.name}"
                            conn.client.storage.from_("project-certificates").upload(
                                file_path, cal_file.getvalue())
                            file_url = conn.client.storage.from_("project-certificates") \
                                           .get_public_url(file_path)
                            conn.table("project_certificates").insert({
                                "job_no": sel_job, "cert_type": "Calibration Certificate",
                                "file_name": cal_file.name, "file_url": file_url,
                                "uploaded_by": "QC Staff",
                                "created_at":  get_now_ist().isoformat()
                            }).execute()
                            st.success(f"Certificate uploaded: {cal_file.name}")
                        except Exception as e:
                            st.error(f"Upload error: {e}")
                    payload = {
                        "job_no": sel_job, "gate_name": "Calibration",
                        "gauge_id": sr_no, "gauge_cal_due": str(cal_due_date),
                        "moc_type": make, "specified_val": range_val,
                        "measured_val": least_count,
                        "quality_notes": f"Report: {cal_report_no} | Instrument: {instrument} | {cal_remarks}",
                        "inspector_name": cal_by, "quality_status": "Calibrated",
                        "created_at": get_now_ist().isoformat()
                    }
                    safe_write(
                        lambda: conn.table("quality_inspection_logs").insert(payload).execute(),
                        success_msg="Calibration record saved!"
                    )
            st.divider()
            st.markdown("#### Existing Calibration Records")
            try:
                cal_docs = conn.table("project_certificates").select("*") \
                    .eq("job_no", sel_job).eq("cert_type", "Calibration Certificate").execute()
                if cal_docs.data:
                    for doc in cal_docs.data:
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([3, 2, 1])
                            c1.write(f"**{doc['file_name']}**")
                            c2.caption(f"Uploaded: {fmt_date(doc['created_at'])}")
                            c3.link_button("View", doc['file_url'])
                else:
                    st.info("No calibration certificates uploaded yet.")
            except Exception as e:
                st.error(f"Load error: {e}")

# ============================================================
# TAB 8: FINAL INSPECTION REPORT
# ============================================================
with main_tabs[8]:
    st.subheader("Final Inspection Report (FIR)")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="fir_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            # Pre-load last FIR record — single DB call
            _fp = {}
            try:
                _fr = conn.table("final_inspection_reports").select("*")\
                    .eq("job_no",sel_job).order("created_at",desc=True).limit(1).execute()
                if _fr.data: _fp = _fr.data[0]
            except Exception: pass
            job_header(proj, last_saved=_fp.get("created_at") if _fp else None)
            with st.container(border=True):
                r1, r2, r3 = st.columns(3)
                fir_no    = r1.text_input("FIR No.",
                               value=_fp.get("tag_no", f"FIR/{sel_job}"))
                r2.date_input("Date", value=get_now_ist().date())
                r1.write(f"**Customer:** {proj_get(proj,'client_name')}")
                r1.write(f"**PO No & Date:** {proj_get(proj,'po_no')} & {fmt_date(proj_get(proj,'po_date',''))}")
                fir_equip = r2.text_input("Equipment",
                               value=_fp.get("equipment_name",""))
                r3.selectbox("Type", ["VERTICAL","HORIZONTAL","OTHER"])
                fir_iwo   = r1.text_input("IWO No. / Equipment No.",
                               value=_fp.get("tag_no",""))
                r2.text_input("GA Drg. No.")
                r3.text_input("MOC", value="SS304")

            with st.form("fir_form", clear_on_submit=False):
                st.markdown("#### Quantity & Clearance")
                q1, q2, q3 = st.columns(3)
                ord_qty = q1.text_input("Ordered Qty",       value=_fp.get("ordered_qty","1 No."))
                off_qty = q2.text_input("Offered for Insp.", value=_fp.get("offered_qty","1 No."))
                acc_qty = q3.text_input("Accepted Qty",      value=_fp.get("accepted_qty","1 No."))

                st.markdown("#### Final Verdict & Authorization")
                fv1, fv2 = st.columns(2)
                _fso = ["Accepted","Rejected","Rework Required"]
                _fsp = _fp.get("inspection_status","Accepted")
                fir_status    = fv1.selectbox("Inspection Result", _fso,
                                  index=_fso.index(_fsp) if _fsp in _fso else 0)
                _fpi = _fp.get("inspected_by","")
                fir_inspector = fv2.selectbox("Quality Inspector", inspectors, key="fir_insp",
                                  index=inspectors.index(_fpi) if _fpi in inspectors else 0)
                fir_witness   = fv1.text_input("Customer / TPI Representative",
                                  value=_fp.get("witnessed_by",""))
                fv2.text_input("Production I/C")
                fir_remarks   = st.text_area("Final Observations / Notes",
                    value=_fp.get("remarks",
                        "Notes:\n1. Entries marked with * are for Customer representative.\n"
                        "2. Please quote FIR No. & date in all correspondences."))

                if st.form_submit_button("Finalize & Save FIR", use_container_width=True):
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
                        success_msg=f"FIR {fir_no} for {sel_job} saved!"
                    )
                    if ok:
                        st.cache_data.clear()

# ============================================================
# TAB 9: GUARANTEE CERTIFICATE
# ============================================================
with main_tabs[9]:
    st.subheader("Guarantee Certificate")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="gc_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            # Pre-load last GC record
            _gp_hdr = {}
            try:
                _gpr = conn.table("guarantee_certificates").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute()
                if _gpr.data: _gp_hdr = _gpr.data[0]
            except Exception: pass
            job_header(proj, last_saved=_gp_hdr.get("created_at") if _gp_hdr else None)
            if _gp_hdr:
                with st.expander("Last saved Guarantee Certificate"):
                    st.write(f"**Equipment:** {_gp_hdr.get('equipment_name','')}")
                    st.write(f"**Certified By:** {_gp_hdr.get('certified_by','')}")
                    st.write(f"**Date:** {fmt_date(_gp_hdr.get('created_at',''))}")

            with st.form("gc_form", clear_on_submit=False):
                g1, g2, g3 = st.columns(3)
                _gc_last_equip, _gc_last_drg, _gc_last_eno = "", "", ""
                try:
                    _r = conn.table("guarantee_certificates").select("equipment_name,serial_no")                        .eq("job_no",sel_job).order("created_at",desc=True).limit(1).execute()
                    if _r.data:
                        _raw = _r.data[0].get("equipment_name","")
                        if " | DRG: " in _raw:
                            _gc_last_equip, _gc_last_drg = _raw.split(" | DRG: ", 1)
                        else:
                            _gc_last_equip = _raw
                        _gc_last_eno = _r.data[0].get("serial_no","")
                except Exception: pass
                gc_equip    = g1.text_input("Equipment Description", value=_gc_last_equip)
                gc_drg      = g2.text_input("DRG. No.", value=_gc_last_drg)
                gc_equip_no = g3.text_input("Equipment No.", value=_gc_last_eno)
                _gp = _gp_hdr  # reuse pre-loaded record
                _fref = _gp.get("invoice_ref","")
                _gcfd = _fref.split(" | INV: ")[0].replace("FIR: ","") if _fref else f"QA/FIR/{sel_job}"
                _gcid = _fref.split(" | INV: ")[1] if " | INV: " in _fref else ""
                gc_fir_no   = g1.text_input("FIR No.", value=_gcfd)
                g2.date_input("Date of Issue", value=get_now_ist().date())
                inv_ref     = g3.text_input("Invoice / Dispatch Ref No.", value=_gcid)

                _dg = (
                    "B&G Engineering Industries guarantee the above equipment for 12 months "
                    "from the date of supply against any manufacturing defectives. "
                    "In this duration any defectives found the same will be rectified or "
                    "replaced if necessary.\n\nGuarantee will NOT apply for:\n"
                    "1. Any mishandling of equipment.\n"
                    "2. Using equipment beyond specified operating conditions.\n"
                    "3. Any Misalignment of equipment in plant.\n"
                    "4. Corrosion and erosion.\n5. Repairs by unauthorised persons."
                )
                g_period = st.text_area("Guarantee Terms", height=180,
                    value=_gp.get("guarantee_period", _dg))
                _gc_pc = _gp.get("certified_by","")
                certifier  = st.selectbox("Authorised Signatory", inspectors, key="gc_certifier",
                               index=inspectors.index(_gc_pc) if _gc_pc in inspectors else 0)
                gc_remarks = st.text_area("Additional Terms / Remarks",
                               value=_gp.get("remarks",""))

                if st.form_submit_button("Generate & Save Guarantee Certificate", use_container_width=True):
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
                        success_msg=f"Guarantee Certificate for {sel_job} saved!"
                    )
                    if ok:
                        st.cache_data.clear()

# ============================================================
# TAB 10: CUSTOMER FEEDBACK
# ============================================================
with main_tabs[10]:
    st.subheader("Customer Feedback")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="fb_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Customer:** {proj_get(proj,'client_name')}")
                c2.write(f"**PO:** {proj_get(proj,'po_no')} | {fmt_date(proj_get(proj,'po_date',''))}")
                c3.write(f"**Job No:** {sel_job}")

            with st.form("fb_form", clear_on_submit=True):
                f1, f2 = st.columns(2)
                c_person = f1.text_input("Name of Customer Contact Person")
                c_desig  = f2.text_input("Designation")
                st.markdown("#### Feedback Parameters")
                st.caption("Rate each: Excellent | Very Good | Good | Bad | Other")
                rating_options = ["Excellent","Very Good","Good","Bad","Other"]
                params = [
                    ("Conformity with Specs",       "spec"),
                    ("Quality",                      "quality"),
                    ("Delivery",                     "delivery"),
                    ("Responsiveness to Queries",    "response"),
                    ("Courtesy",                     "courtesy"),
                    ("Responsiveness to Complaints", "complaints"),
                ]
                fb_ratings = {}
                for label, key in params:
                    col1, col2 = st.columns([2, 3])
                    col1.write(f"**{label}**")
                    fb_ratings[key] = col2.radio(label, rating_options, horizontal=True,
                                                  key=f"fb_{key}", label_visibility="collapsed")

                rating_map  = {"Excellent": 5,"Very Good": 4,"Good": 3,"Bad": 2,"Other": 1}
                suggestions = st.text_area("Suggestions for Improvement")
                reviewed_by = st.text_input("Reviewed By (B&G Staff)")

                if st.form_submit_button("Submit Customer Feedback", use_container_width=True):
                    payload = {
                        "job_no":                   sel_job,
                        "customer_name":            proj_get(proj,'client_name'),
                        "contact_person":           f"{c_person} ({c_desig})",
                        "rating_quality":           rating_map.get(fb_ratings.get('quality','Good'),3),
                        "rating_delivery":          rating_map.get(fb_ratings.get('delivery','Good'),3),
                        "rating_response":          rating_map.get(fb_ratings.get('response','Good'),3),
                        "rating_technical_support": rating_map.get(fb_ratings.get('courtesy','Good'),3),
                        "rating_documentation":     rating_map.get(fb_ratings.get('complaints','Good'),3),
                        "suggestions":              suggestions,
                        "recommend_bg":             reviewed_by,
                        "created_at":               get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("customer_feedback").insert(payload).execute(),
                        success_msg="Customer Feedback recorded!"
                    )
                    if ok:
                        st.cache_data.clear()

# ============================================================
# TAB 11: TRIAL RUN REPORT
# ============================================================
with main_tabs[11]:
    st.subheader("Trial Run Report")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="tr_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            # Pre-load last trial run record
            _tr_prev = {}
            try:
                _trr = conn.table("trial_run_reports").select("*")\
                    .eq("job_no",sel_job).order("created_at",desc=True).limit(1).execute()
                if _trr.data: _tr_prev = _trr.data[0]
            except Exception: pass
            job_header(proj, last_saved=_tr_prev.get("created_at") if _tr_prev else None)

            # Header fields
            with st.container(border=True):
                h1, h2, h3 = st.columns(3)
                tr_report_no  = h1.text_input("Test Report No.",
                                  value=_tr_prev.get("report_no", f"BG/QA/TRR/{sel_job}"))
                tr_equip      = h2.text_input("Equipment",
                                  value=_tr_prev.get("equipment_name",""))
                tr_drg        = h3.text_input("Drawing No.",
                                  value=_tr_prev.get("drawing_no",""))
                h4, h5, h6 = st.columns(3)
                tr_motor_sr   = h4.text_input("Motor Serial No.",
                                  value=_tr_prev.get("motor_serial_no",""))
                tr_gearbox_sr = h5.text_input("Gearbox Serial No.",
                                  value=_tr_prev.get("gearbox_serial_no",""))
                tr_date       = h6.date_input("Test Date",
                                  value=get_now_ist().date())

            st.markdown("#### Trial Run Data")
            _tr_grid_key = f"tr_grid_{sel_job}"
            _tr_default = pd.DataFrame([
                {"Description": "Trial run with load",    "Current_R": "", "Current_Y": "", "Current_B": "",
                 "Duration": "1 Hour", "RPM_Actual": "", "RPM_Dwg": "", "Noise_dba": "",
                 "Medium": "WATER", "Run_out_mm": ""},
                {"Description": "Trial run with No load", "Current_R": "", "Current_Y": "", "Current_B": "",
                 "Duration": "1 Hour", "RPM_Actual": "", "RPM_Dwg": "", "Noise_dba": "",
                 "Medium": "——", "Run_out_mm": ""},
            ])
            if _tr_grid_key not in st.session_state:
                _tr_saved = _tr_prev.get("trial_data")
                if _tr_saved and isinstance(_tr_saved, list) and len(_tr_saved) > 0:
                    _tr_df = pd.DataFrame(_tr_saved)
                    for _c in _tr_df.columns:
                        _tr_df[_c] = _tr_df[_c].fillna("").astype(str)
                    st.session_state[_tr_grid_key] = _tr_df
                else:
                    st.session_state[_tr_grid_key] = _tr_default

            tr_grid = st.data_editor(
                st.session_state[_tr_grid_key], num_rows="dynamic",
                use_container_width=True, hide_index=True,
                key=f"tr_editor_{sel_job}",
                column_config={
                    "Description":  st.column_config.TextColumn("Description",         width="large"),
                    "Current_R":    st.column_config.TextColumn("Current R (A)",        width="small"),
                    "Current_Y":    st.column_config.TextColumn("Current Y (A)",        width="small"),
                    "Current_B":    st.column_config.TextColumn("Current B (A)",        width="small"),
                    "Duration":     st.column_config.TextColumn("Duration",             width="small"),
                    "RPM_Actual":   st.column_config.TextColumn("RPM Actual",           width="small"),
                    "RPM_Dwg":      st.column_config.TextColumn("RPM As per Dwg",       width="small"),
                    "Noise_dba":    st.column_config.TextColumn("Noise Level (dBa)",    width="small"),
                    "Medium":       st.column_config.TextColumn("Medium",               width="small"),
                    "Run_out_mm":   st.column_config.TextColumn("Run Out (mm)",          width="small"),
                }
            )

            with st.form("tr_form", clear_on_submit=False):
                tr_observation = st.text_area("Observation",
                    value=_tr_prev.get("observation",
                          "Found smooth operating without any abnormal sounds during test duration."))
                st.markdown("#### Authorization")
                a1, a2, a3, a4 = st.columns(4)
                a1.text_input("Production", key="tr_prod")
                _tr_qc = _tr_prev.get("inspected_by","")
                tr_inspector = a2.selectbox("Quality", inspectors, key="tr_insp",
                                 index=inspectors.index(_tr_qc) if _tr_qc in inspectors else 0)
                tr_tpi      = a3.text_input("TPI", value=_tr_prev.get("tpi_name",""))
                tr_customer = a4.text_input("Customer", value=_tr_prev.get("customer_rep",""))

                if st.form_submit_button("Save Trial Run Report", use_container_width=True):
                    final_tr = clean_rows(tr_grid.to_dict("records"))
                    payload = {
                        "job_no":           sel_job,
                        "report_no":        tr_report_no,
                        "equipment_name":   tr_equip,
                        "drawing_no":       tr_drg,
                        "motor_serial_no":  tr_motor_sr,
                        "gearbox_serial_no":tr_gearbox_sr,
                        "test_date":        str(tr_date),
                        "trial_data":       final_tr,
                        "observation":      tr_observation,
                        "inspected_by":     tr_inspector,
                        "tpi_name":         tr_tpi,
                        "customer_rep":     tr_customer,
                        "created_at":       get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("trial_run_reports").insert(payload).execute(),
                        success_msg=f"Trial Run Report {tr_report_no} saved!"
                    )
                    if ok:
                        st.session_state[_tr_grid_key] = pd.DataFrame(final_tr)
                        st.cache_data.clear()

# ============================================================
# TAB 12: DOCUMENT VAULT
# ============================================================
with main_tabs[12]:
    st.subheader("MTC & Document Upload Vault")
    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="vault_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            st.info(f"Vault for: **{proj_get(proj,'client_name')}** | Job: **{sel_job}**")
            with st.form("vault_upload_form", clear_on_submit=True):
                u1, u2 = st.columns(2)
                c_type   = u1.selectbox("Document Type", [
                    "Material Test Certificate (MTC)", "Calibration Certificate",
                    "NDT Report", "As Built Drawing", "Guarantee Certificate",
                    "Final Inspection Report", "Invoice", "Other"
                ])
                up_files = u2.file_uploader("Upload PDF / Image", accept_multiple_files=True,
                                            type=['pdf','jpg','jpeg','png'])
                st.text_input("Document Label / Description")
                if st.form_submit_button("Upload to Vault"):
                    if up_files:
                        for uf in up_files:
                            try:
                                ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
                                file_path = f"{sel_job}/{c_type.split()[0]}_{ts}_{uf.name}"
                                conn.client.storage.from_("project-certificates").upload(
                                    file_path, uf.getvalue())
                                file_url = conn.client.storage.from_("project-certificates") \
                                               .get_public_url(file_path)
                                conn.table("project_certificates").insert({
                                    "job_no": sel_job, "cert_type": c_type,
                                    "file_name": uf.name, "file_url": file_url,
                                    "uploaded_by": "QC Staff",
                                    "created_at":  get_now_ist().isoformat()
                                }).execute()
                                st.success(f"Uploaded: {uf.name}")
                            except Exception as e:
                                st.error(f"Error uploading {uf.name}: {e}")
                    else:
                        st.warning("Please select files first.")

            st.divider()
            st.markdown("### Existing Project Documents")
            try:
                docs_res = conn.table("project_certificates").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).execute()
                if docs_res.data:
                    df_docs = pd.DataFrame(docs_res.data)
                    for cert_type_grp, group in df_docs.groupby('cert_type'):
                        st.markdown(f"**{cert_type_grp}** ({len(group)})")
                        for _, doc in group.iterrows():
                            with st.container(border=True):
                                d1, d2, d3, d4 = st.columns([3, 2, 2, 1])
                                d1.write(f"{doc['file_name']}")
                                d2.caption(doc['cert_type'])
                                d3.caption(fmt_date(doc['created_at']))
                                d4.link_button("View", doc['file_url'])
                else:
                    st.info("No documents uploaded yet.")
            except Exception as e:
                st.error(f"Vault load error: {e}")

# ============================================================
# TAB 13: MASTER DATA BOOK
# ============================================================
with main_tabs[13]:
    st.header("Master Data Book Generator")
    st.info("Compiles all quality documents into a single stamped PDF — the B&G Product Birth Certificate.")

    if not PDF_AVAILABLE:
        st.warning("PDF generation requires fpdf2 and pypdf.\nAdd to requirements.txt: fpdf2, pypdf, requests, Pillow")

    if not df_anchor.empty:
        target = st.selectbox("Select Job Number", ["-- Select --"] + job_list, key="mdb_job_sel")
        if target != "-- Select --":
            proj = get_proj(df_anchor, target)
            if proj is not None:
                job_header(proj)
                st.markdown("#### Document Completion Status")
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
                        res    = conn.table(table).select("id").eq("job_no", target).limit(1).execute()
                        exists = bool(res.data)
                    except Exception:
                        exists = False
                    doc_checks[label] = exists
                    with cols[i % 4]:
                        if exists: st.success(f"Done — {label}")
                        else:      st.error(f"Missing — {label}")

                job_rows = df_plan[df_plan['job_no'].astype(str) == str(target)]
                total_photos     = job_rows['quality_photo_url'].apply(
                    lambda x: len(x) if isinstance(x, list) else 0).sum()
                completed_stages = int(job_rows['quality_status'].notna().sum())
                total_stages     = len(job_rows)

                col_a, col_b = st.columns(2)
                col_a.metric("Process Gates Inspected", f"{completed_stages} / {total_stages}")
                col_b.metric("Evidence Photos (all 60 KB)", f"{int(total_photos)}")

                try:
                    mtc_res   = conn.table("project_certificates").select("id") \
                        .eq("job_no", target).eq("cert_type", "Material Test Certificate (MTC)").execute()
                    mtc_count = len(mtc_res.data) if mtc_res.data else 0
                    st.info(f"{mtc_count} MTC(s) uploaded — will be appended to the Data Book")
                except Exception:
                    mtc_count = 0

                completed = sum(doc_checks.values())
                st.progress(completed / max(len(doc_checks), 1))
                st.caption(f"{completed} of {len(doc_checks)} quality documents completed")
                st.divider()

                if st.button("COMPILE MASTER DATA BOOK", type="primary",
                              use_container_width=True, disabled=not PDF_AVAILABLE):
                    with st.spinner("Fetching all data, embedding photos, appending MTCs…"):
                        try:
                            final_pdf = generate_master_data_book(target, proj, df_plan)
                            st.success("Master Quality Data Book compiled successfully!")
                            st.download_button(
                                label="Download Data Book PDF",
                                data=final_pdf,
                                file_name=f"BGE_DataBook_{target}.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                        except Exception as e:
                            st.error(f"Compilation error: {e}")

# ============================================================
# TAB 14: CONFIG
# ============================================================
with main_tabs[14]:
    st.header("Portal Configuration & Master Data")
    config_mode = st.radio("Configure:", ["Inspection Parameters","Staff & Inspectors"], horizontal=True)

    if config_mode == "Inspection Parameters":
        report_cat = st.selectbox("Select List to Configure",
                                   ["Dimensional Descriptions","MOC List","Technical Checklist","Inspection Checkpoints"])
        try:
            conf_res = conn.table("quality_config").select("*").eq("category", report_cat).execute()
            df_conf  = pd.DataFrame(conf_res.data) if conf_res.data else \
                pd.DataFrame(columns=["parameter_name","equipment_type","default_design_value"])
        except Exception:
            df_conf = pd.DataFrame(columns=["parameter_name","equipment_type","default_design_value"])

        edited_conf = st.data_editor(df_conf, num_rows="dynamic", use_container_width=True,
            key=f"config_editor_{report_cat}", hide_index=True,
            column_config={
                "parameter_name": st.column_config.TextColumn("Parameter Name", required=True),
                "equipment_type": st.column_config.SelectboxColumn("Applicability",
                    options=["General","Reactor","Storage Tank","Heat Exchanger","Receiver"],
                    default="General"),
                "default_design_value": st.column_config.TextColumn("Default / Standard Ref."),
                "category": None, "id": None, "created_at": None
            })

        if st.button(f"Sync {report_cat}", type="primary"):
            try:
                cleaned = [
                    {"category": report_cat,
                     "parameter_name":       str(r.get('parameter_name','')).strip(),
                     "equipment_type":       r.get('equipment_type','General'),
                     "default_design_value": r.get('default_design_value','')}
                    for r in edited_conf.to_dict('records')
                    if str(r.get('parameter_name','')).strip() not in ['','None','nan']
                ]
                conn.table("quality_config").delete().eq("category", report_cat).execute()
                if cleaned:
                    conn.table("quality_config").insert(cleaned).execute()
                st.success(f"{report_cat} updated with {len(cleaned)} items!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Sync Error: {e}")
    else:
        st.subheader("Master Staff / Inspectors")
        st.write("**Current Inspectors:**", ", ".join(inspectors))
        st.divider()
        with st.form("add_staff_form", clear_on_submit=True):
            s1, s2   = st.columns(2)
            new_name = s1.text_input("Name")
            new_role = s2.selectbox("Role",
                ["QC Inspector","Production I/C","QA Engineer","Manager","Other"])
            if st.form_submit_button("Add Staff"):
                if new_name:
                    safe_write(
                        lambda: conn.table("master_staff").insert({
                            "name":       new_name.strip().title(),
                            "role":       new_role,
                            "created_at": get_now_ist().isoformat()
                        }).execute(),
                        success_msg=f"{new_name} added!",
                        error_prefix="Staff Add Error"
                    )
                    st.cache_data.clear()
                    st.rerun()
