import streamlit as st
from st_supabase_connection import SupabaseConnection
from database_utils import fetch_all_master_data
import json, math, io
from datetime import date, datetime
import pandas as pd
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# ─────────────────────────────────────────────────────────────────────────────
# 1. PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Estimation & Costing | BGEngg ERP",
    page_icon="📐",
    layout="wide"
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. SUPABASE CONNECTION  (same pattern as all other pages)
# ─────────────────────────────────────────────────────────────────────────────
conn = st.connection("supabase", type=SupabaseConnection)

if "master_data" not in st.session_state:
    st.session_state.master_data = fetch_all_master_data(conn)

# ─────────────────────────────────────────────────────────────────────────────
# 3. SUPABASE HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def sb_fetch(table, select="*", order=None, filters=None):
    """Generic Supabase SELECT — returns list of dicts."""
    try:
        q = conn.table(table).select(select)
        if order:
            q = q.order(order)
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        r = q.execute()
        return r.data or []
    except Exception as e:
        st.error(f"DB read error ({table}): {e}")
        return []

def sb_insert(table, row: dict):
    try:
        conn.table(table).insert(row).execute()
        return True
    except Exception as e:
        st.error(f"DB insert error ({table}): {e}")
        return False

def sb_update(table, row: dict, match_col: str, match_val):
    try:
        conn.table(table).update(row).eq(match_col, match_val).execute()
        return True
    except Exception as e:
        st.error(f"DB update error ({table}): {e}")
        return False

# ─────────────────────────────────────────────────────────────────────────────
# 4. CALCULATION ENGINE  (mirrors your Excel formulas exactly)
# ─────────────────────────────────────────────────────────────────────────────
PI = math.pi

def calc_shell_area(dia_mm, ht_mm):
    return PI * (dia_mm / 1000) * (ht_mm / 1000)

def calc_dish_area(dia_mm):
    r = (dia_mm / 1000) / 2
    return 1.09 * PI * r * r          # torispherical approximation

def calc_plate_weight(area_m2, thk_mm, density=8000, scrap_pct=0.05):
    return area_m2 * (thk_mm / 1000) * density * (1 + scrap_pct)

def calc_dish_weight(dia_mm, thk_mm, density=8000, scrap_pct=0.15):
    return calc_dish_area(dia_mm) * (thk_mm / 1000) * density * (1 + scrap_pct)

def calc_shell_volume_ltrs(dia_mm, ht_mm):
    r = (dia_mm / 1000) / 2
    return PI * r * r * (ht_mm / 1000) * 1000

def calc_totals(parts, pipes, flanges, bo_items, oh_items,
                profit_pct, contingency_pct, packing, freight, gst_pct, engg_design):
    tot_plates  = sum(p.get("amount", 0) for p in parts)
    tot_pipes   = sum(p.get("amount", 0) for p in pipes)
    tot_flanges = sum(p.get("amount", 0) for p in flanges)
    tot_rm      = tot_plates + tot_pipes + tot_flanges
    tot_bo      = sum(p.get("amount", 0) for p in bo_items)
    tot_lab     = sum(o.get("amount", 0) for o in oh_items if o.get("oh_type") in ("LABOUR", "LABOUR_BUFF"))
    tot_cons    = sum(o.get("amount", 0) for o in oh_items if o.get("oh_type") == "CONSUMABLES")
    tot_other   = sum(o.get("amount", 0) for o in oh_items if o.get("oh_type") not in ("LABOUR","LABOUR_BUFF","CONSUMABLES"))
    tot_oh      = tot_lab + tot_cons + tot_other
    tot_mfg     = tot_rm + tot_bo + tot_oh + engg_design
    cont_amt    = tot_mfg * contingency_pct / 100
    cbm         = tot_mfg + cont_amt
    profit_amt  = cbm * profit_pct / 100
    ex_works    = cbm + profit_amt + packing + freight
    gst_amt     = ex_works * gst_pct / 100
    for_price   = ex_works + gst_amt
    safe        = ex_works if ex_works else 1
    return dict(
        tot_plates=tot_plates, tot_pipes=tot_pipes, tot_flanges=tot_flanges,
        tot_rm=tot_rm, tot_bo=tot_bo, tot_lab=tot_lab,
        tot_cons=tot_cons, tot_other=tot_other, tot_oh=tot_oh,
        engg_design=engg_design, tot_mfg=tot_mfg, cont_amt=cont_amt,
        cbm=cbm, profit_amt=profit_amt, packing=packing, freight=freight,
        ex_works=ex_works, gst_amt=gst_amt, for_price=for_price,
        rm_pct=tot_rm/safe*100, lab_pct=tot_lab/safe*100,
        oh_pct=(tot_cons+tot_other)/safe*100,
        profit_pct_actual=profit_amt/safe*100,
    )

def margin_issues(t):
    out = []
    if not (45 <= t["rm_pct"]  <= 60): out.append(f"RM {t['rm_pct']:.1f}% — target 45–60%")
    if not (15 <= t["lab_pct"] <= 25): out.append(f"Labour {t['lab_pct']:.1f}% — target 15–25%")
    if not (8  <= t["oh_pct"]  <= 15): out.append(f"OH {t['oh_pct']:.1f}% — target 8–15%")
    if t["profit_pct_actual"] < 12:    out.append(f"Profit {t['profit_pct_actual']:.1f}% — min 12%")
    return out

# ─────────────────────────────────────────────────────────────────────────────
# 5. DOCX QUOTATION GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
def _shd(cell, hex_color):
    tc = cell._tc; pr = tc.get_or_add_tcPr()
    s = OxmlElement("w:shd")
    s.set(qn("w:val"), "clear"); s.set(qn("w:color"), "auto"); s.set(qn("w:fill"), hex_color)
    pr.append(s)

def _run(para, text, bold=False, size=9, color=None, italic=False):
    r = para.add_run(text)
    r.font.size = Pt(size); r.font.name = "Arial"; r.font.bold = bold; r.font.italic = italic
    if color: r.font.color.rgb = RGBColor(*color)
    return r

def _kv_table(doc, rows, col_widths=(5.5, 11.5)):
    t = doc.add_table(rows=0, cols=2); t.style = "Table Grid"
    for i, (k, v) in enumerate(rows):
        row = t.add_row()
        for j, (txt, cm) in enumerate(zip([k, v], col_widths)):
            c = row.cells[j]; c.text = ""; c.width = Cm(cm)
            p = c.paragraphs[0]
            _run(p, str(txt), bold=(j==0), size=9)
            _shd(c, ("D6E4F7" if i%2==0 else "F2F2F2") if j==0 else ("FFFFFF" if i%2==0 else "EFF5FB"))
    return t

def generate_docx(est, customer, totals):
    doc = Document()
    for sec in doc.sections:
        sec.top_margin=Cm(1.8); sec.bottom_margin=Cm(1.8)
        sec.left_margin=Cm(2.0); sec.right_margin=Cm(2.0)

    def banner(lines):          # blue header block
        t = doc.add_table(rows=1, cols=1); t.style = "Table Grid"
        c = t.rows[0].cells[0]; _shd(c, "1B3A6B")
        c.paragraphs[0].clear()
        p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(8); p.paragraph_format.space_after = Pt(8)
        for text, sz, col in lines:
            _run(p, text+"\n", bold=True, size=sz, color=col)

    def sec_head(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before=Pt(10); p.paragraph_format.space_after=Pt(2)
        _run(p, text, bold=True, size=12, color=(27,58,107))
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bot = OxmlElement("w:bottom")
        bot.set(qn("w:val"),"single"); bot.set(qn("w:sz"),"6")
        bot.set(qn("w:space"),"1"); bot.set(qn("w:color"),"2E75B6")
        pBdr.append(bot); pPr.append(pBdr)

    def body(text):
        p = doc.add_paragraph(); p.paragraph_format.space_before=Pt(2); p.paragraph_format.space_after=Pt(2)
        _run(p, text, size=9, color=(68,68,68))

    fmt = lambda n: f"₹{n:,.0f}"

    # Banner
    banner([
        ("B&G Engineering Industries", 15, (255,255,255)),
        ("TECHNICAL & COMMERCIAL OFFER", 12, (204,221,255)),
        (est.get("equipment_desc",""), 10, (255,255,255)),
    ])
    doc.add_paragraph()

    # S1 Offer & Customer
    sec_head("SECTION 1 — OFFER & CUSTOMER DETAILS")
    cust_name = customer.get("name","") if customer else ""
    _kv_table(doc, [
        ("Offer Reference",  est.get("qtn_number","")),
        ("Revision",         est.get("revision","R0")),
        ("Date",             date.today().strftime("%d %B %Y")),
        ("Prepared By",      est.get("prepared_by","")),
        ("Checked By",       est.get("checked_by","")),
        ("Customer Name",    cust_name),
        ("Customer Address", customer.get("address","") if customer else ""),
        ("GSTIN",            customer.get("gstin","") if customer else ""),
        ("Contact Person",   customer.get("contact_person","") if customer else ""),
        ("Phone / Email",    f"{customer.get('phone','') or ''} / {customer.get('email','') or ''}" if customer else ""),
    ])

    doc.add_paragraph()
    sec_head("SECTION 2 — TECHNICAL DESIGN BASIS")
    _kv_table(doc, [
        ("Equipment",          est.get("equipment_desc","")),
        ("Tag Number",         est.get("tag_number","")),
        ("Capacity",           f"{est.get('capacity_ltrs','')} Ltrs"),
        ("Design Code",        est.get("design_code","ASME Sec VIII Div 1")),
        ("Design Pressure",    est.get("design_pressure","FV to 4.5 Bar")),
        ("Design Temperature", est.get("design_temp","-50 to 250°C")),
        ("Shell ID",           f"{est.get('shell_dia_mm','')} mm"),
        ("Shell Thickness",    f"{est.get('shell_thk_mm','')} mm"),
        ("Shell Height",       f"{est.get('shell_ht_mm','')} mm"),
        ("Dish Thickness",     f"{est.get('dish_thk_mm','')} mm"),
        ("Jacket Type",        est.get("jacket_type","")),
        ("Agitator Type",      est.get("agitator_type","")),
        ("MOC — Shell/Vessel", est.get("moc_shell","SS316L")),
        ("MOC — Jacket",       est.get("moc_jacket","SS304")),
    ])

    doc.add_paragraph()
    sec_head("SECTION 3 — MANUFACTURING APPROACH & QA")
    body("Manufactured under controlled engineering and quality systems ensuring compliance with ASME, applicable codes, and API service requirements.")
    for item in ["GA drawing submission and approval","Raw material verification against MTC",
                 "CNC cutting / controlled plate rolling","Qualified WPS/PQR and qualified welders",
                 "Radiography / DP / PT as per code","Internal grinding/buffing as specified",
                 "Hydrostatic testing as per ASME","Final dimensional and visual inspection before dispatch"]:
        p = doc.add_paragraph(item, style="List Bullet")
        for r in p.runs: r.font.size=Pt(9); r.font.name="Arial"

    doc.add_paragraph()
    sec_head("SECTION 4 — SCOPE OF SUPPLY & DOCUMENTATION")
    body("Engineering: GA Drawing, Nozzle Orientation, Fabrication Drawings, BOM, As-built Drawings.")
    body("Quality: MTC, NDT Reports (RT/PT/DP), Hydrostatic Test Report, Surface Finish Record, Inspection Release Note.")

    doc.add_paragraph()
    sec_head("SECTION 5 — COMMERCIAL SUMMARY")
    price_rows = [
        ("Raw Material (Plates, Pipes, Flanges)", fmt(totals["tot_rm"])),
        ("Bought-Out Items (Drive, Seal, BRG etc.)", fmt(totals["tot_bo"])),
        ("Fabrication & Services", fmt(totals["tot_oh"])),
        ("Engineering & ASME Design", fmt(totals["engg_design"])),
        ("Contingency", fmt(totals["cont_amt"])),
        ("Operating Margin", fmt(totals["profit_amt"])),
        ("Packing & Forwarding", fmt(totals["packing"])),
        ("Ex-Works Price", fmt(totals["ex_works"])),
        (f"GST @ {est.get('gst_pct',18):.0f}%", fmt(totals["gst_amt"])),
        ("FINAL FOR PRICE", fmt(totals["for_price"])),
    ]
    t_price = doc.add_table(rows=0, cols=2); t_price.style = "Table Grid"
    for i,(k,v) in enumerate(price_rows):
        row = t_price.add_row()
        is_key = k in ("Ex-Works Price","FINAL FOR PRICE")
        for j,txt in enumerate([k,v]):
            c = row.cells[j]; c.text = ""; p = c.paragraphs[0]
            _run(p, txt, bold=is_key, size=9,
                 color=(255,255,255) if is_key else (26,26,26))
            _shd(c, "1B3A6B" if is_key else ("FFFFFF" if i%2==0 else "EFF5FB"))
            if j==1: p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    doc.add_paragraph()
    _kv_table(doc, [
        ("Price Basis",    "Ex-Works, Hyderabad. Packing included. Freight/insurance excluded."),
        ("Taxes",          "GST as applicable at time of dispatch."),
        ("Payment Terms",  "40% advance with PO | 50% inspection/dispatch | 10% on delivery."),
        ("Delivery",       "To be confirmed at order — from receipt of clear PO + advance."),
        ("Validity",       "7 days from date of offer."),
        ("Warranty",       "12 months from date of supply against manufacturing defects."),
        ("Exclusions",     "Civil works, E&I, erection & commissioning, DQ/IQ/OQ."),
    ])

    doc.add_paragraph()
    sec_head("SECTION 6 — SIGN-OFF")
    t_sign = doc.add_table(rows=2, cols=2); t_sign.style = "Table Grid"
    for j,lbl in enumerate(["Prepared By","Checked By"]):
        c = t_sign.rows[0].cells[j]; c.text=""
        _run(c.paragraphs[0], lbl, bold=True, size=9); _shd(c,"D6E4F7")
    for j,name in enumerate([est.get("prepared_by",""), est.get("checked_by","")]):
        c = t_sign.rows[1].cells[j]; c.text=""
        _run(c.paragraphs[0], name, size=9)

    buf = io.BytesIO()
    doc.save(buf); buf.seek(0)
    return buf

# ─────────────────────────────────────────────────────────────────────────────
# 6. RM / OH MASTER LOADERS  (cached — pulls from Supabase)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_rm_master():
    rows = sb_fetch("est_rm_master", order="category")
    for r in rows:
        r["rate"] = float(r["rate"]) if r.get("rate") else 0.0
        r["unit_wt_kg_per_m"] = float(r["unit_wt_kg_per_m"]) if r.get("unit_wt_kg_per_m") else None
    return {r["ref_code"]: r for r in rows}

@st.cache_data(ttl=300)
def load_oh_master():
    rows = sb_fetch("est_oh_master", order="oh_type")
    for r in rows:
        r["rate"] = float(r["rate"]) if r.get("rate") else 0.0
    return {r["oh_code"]: r for r in rows}

@st.cache_data(ttl=60)
def load_clients_full():
    """Full client rows from master_clients (already in your DB)."""
    return sb_fetch("master_clients", order="name")

@st.cache_data(ttl=60)
def load_anchor_qtns():
    """Pull quotation numbers from Anchor Portal table."""
    rows = sb_fetch("anchor_projects", select="quote_ref,project_description,client_name", order="created_at")
    return rows  # list of dicts

# ─────────────────────────────────────────────────────────────────────────────
# 7. SESSION STATE INIT
# ─────────────────────────────────────────────────────────────────────────────
def _blank_hdr():
    return dict(
        qtn_number="", revision="R0", customer_name="", customer_id=None,
        equipment_desc="", tag_number="", capacity_ltrs=2000.0,
        shell_dia_mm=1300.0, shell_ht_mm=1500.0, shell_thk_mm=8.0, dish_thk_mm=10.0,
        jacket_type="SS304 Half-pipe Jacket with Insulation Jacket",
        agitator_type="Anchor", design_code="ASME Sec VIII Div 1",
        design_pressure="FV to 4.5 Bar", design_temp="-50 to 250°C",
        moc_shell="SS316L", moc_jacket="SS304", status="Draft",
        prepared_by="", checked_by="",
        profit_margin_pct=10.0, contingency_pct=0.0,
        packing_amt=5000.0, freight_amt=10000.0,
        gst_pct=18.0, engg_design_amt=25000.0, notes="",
    )

for key, default in [
    ("est_hdr",     _blank_hdr()),
    ("est_parts",   []),
    ("est_pipes",   []),
    ("est_flanges", []),
    ("est_bo",      []),
    ("est_oh",      []),
    ("est_edit_id", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ─────────────────────────────────────────────────────────────────────────────
# 8. PAGE HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.title("📐 Estimation & Costing")
st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# 9. MAIN TABS
# ─────────────────────────────────────────────────────────────────────────────
TAB_LIST, TAB_NEW, TAB_MASTERS = st.tabs([
    "📋 Estimations Register",
    "➕ New / Edit Estimation",
    "📊 RM · OH · Masters",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB A — REGISTER
# ══════════════════════════════════════════════════════════════════════════════
with TAB_LIST:
    st.subheader("All Estimations")

    col_f1, col_f2, col_f3 = st.columns(3)
    f_status   = col_f1.selectbox("Filter Status", ["All","Draft","Issued","Won","Lost","On Hold"])
    f_customer = col_f2.text_input("Filter Customer")
    f_search   = col_f3.text_input("Search QTN / Equipment")

    all_est = sb_fetch("estimations", order="updated_at")

    # Apply filters
    if f_status != "All":
        all_est = [e for e in all_est if e.get("status") == f_status]
    if f_customer:
        all_est = [e for e in all_est if f_customer.lower() in (e.get("customer_name","") or "").lower()]
    if f_search:
        all_est = [e for e in all_est if
                   f_search.lower() in (e.get("qtn_number","") or "").lower() or
                   f_search.lower() in (e.get("equipment_desc","") or "").lower()]

    if not all_est:
        st.info("No estimations found. Click **➕ New / Edit Estimation** tab to start.")
    else:
        # Summary metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Estimations", len(all_est))
        m2.metric("Draft", sum(1 for e in all_est if e.get("status")=="Draft"))
        m3.metric("Issued", sum(1 for e in all_est if e.get("status")=="Issued"))
        m4.metric("Won", sum(1 for e in all_est if e.get("status")=="Won"))
        st.divider()

        for est in reversed(all_est):
            parts   = json.loads(est.get("parts_json")   or "[]")
            pipes   = json.loads(est.get("pipes_json")   or "[]")
            flanges = json.loads(est.get("flanges_json") or "[]")
            bo      = json.loads(est.get("bo_json")      or "[]")
            oh      = json.loads(est.get("oh_json")      or "[]")
            T = calc_totals(parts, pipes, flanges, bo, oh,
                            est.get("profit_margin_pct",10), est.get("contingency_pct",0),
                            est.get("packing_amt",0), est.get("freight_amt",0),
                            est.get("gst_pct",18), est.get("engg_design_amt",0))

            status_icon = {"Draft":"🟡","Issued":"🔵","Won":"🟢","Lost":"🔴","On Hold":"⚪"}.get(est.get("status","Draft"),"🟡")
            with st.expander(f"{status_icon} **{est.get('qtn_number','')}** — {est.get('customer_name','')} | {est.get('equipment_desc','')} | {est.get('status','')}"):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Revision:** {est.get('revision','R0')}")
                c1.write(f"**Tag No:** {est.get('tag_number','-')}")
                c2.write(f"**Prepared By:** {est.get('prepared_by','-')}")
                c2.write(f"**Updated:** {str(est.get('updated_at',''))[:10]}")
                c3.write(f"**Status:** {est.get('status','')}")

                k1,k2,k3,k4 = st.columns(4)
                k1.metric("Raw Material",  f"₹{T['tot_rm']:,.0f}")
                k2.metric("Mfg Cost",      f"₹{T['tot_mfg']:,.0f}")
                k3.metric("Ex-Works",      f"₹{T['ex_works']:,.0f}")
                k4.metric("FOR Price",     f"₹{T['for_price']:,.0f}")

                ba, bb, bc = st.columns(3)

                # Edit button — loads into form tab
                if ba.button("✏️ Edit", key=f"edit_{est.get('id')}"):
                    h = _blank_hdr()
                    for k in h:
                        if k in est: h[k] = est[k]
                    st.session_state.est_hdr     = h
                    st.session_state.est_parts   = parts
                    st.session_state.est_pipes   = pipes
                    st.session_state.est_flanges = flanges
                    st.session_state.est_bo      = bo
                    st.session_state.est_oh      = oh
                    st.session_state.est_edit_id = est.get("id")
                    st.info("Switched to ➕ New / Edit Estimation tab to continue editing.")

                # Status update
                new_status = bb.selectbox("Change Status", ["Draft","Issued","Won","Lost","On Hold"],
                    index=["Draft","Issued","Won","Lost","On Hold"].index(est.get("status","Draft")),
                    key=f"status_{est.get('id')}")
                if new_status != est.get("status"):
                    if bb.button("✅ Apply", key=f"apply_{est.get('id')}"):
                        sb_update("estimations", {"status": new_status, "updated_at": datetime.now().isoformat()},
                                  "id", est.get("id"))
                        st.cache_data.clear(); st.rerun()

                # Download quotation DOCX
                cust_rows = sb_fetch("master_clients", filters={"name": est.get("customer_name","")})
                cust_data = cust_rows[0] if cust_rows else {}
                docx_buf = generate_docx(est, cust_data, T)
                bc.download_button(
                    "📄 Download Quotation",
                    docx_buf,
                    file_name=f"{est.get('qtn_number','QTN')}_{est.get('revision','R0')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"dl_{est.get('id')}",
                )

# ══════════════════════════════════════════════════════════════════════════════
# TAB B — NEW / EDIT ESTIMATION
# ══════════════════════════════════════════════════════════════════════════════
with TAB_NEW:
    edit_id = st.session_state.est_edit_id
    st.subheader("✏️ Edit Estimation" if edit_id else "➕ New Estimation")

    rm_master = load_rm_master()
    oh_master = load_oh_master()
    clients   = load_clients_full()
    anchor_qtns = load_anchor_qtns()

    client_names = [c["name"] for c in clients]
    rm_codes  = list(rm_master.keys())
    oh_codes  = list(oh_master.keys())
    plate_rm  = [k for k,v in rm_master.items() if v.get("category")=="RM"]
    pipe_rm   = [k for k,v in rm_master.items() if v.get("rm_type")=="Pipe"]
    flg_rm    = [k for k,v in rm_master.items() if v.get("rm_type")=="FLG"]
    bo_rm     = [k for k,v in rm_master.items() if v.get("category")=="BO"]

    f1, f2, f3, f4, f5 = st.tabs([
        "1️⃣ Header", "2️⃣ Plates & Parts",
        "3️⃣ Pipes & Flanges", "4️⃣ Bought-Out & OH",
        "5️⃣ Summary & Save"
    ])
    h = st.session_state.est_hdr

    # ── F1: HEADER ────────────────────────────────────────────────────────────
    with f1:
        st.markdown("#### Offer Details")

        # ── Anchor QTN pull ──────────────────────────────────────────────────
        anc_options = ["— type manually —"] + [
            f"{a.get('quote_ref','')}  |  {a.get('client_name','')}  |  {a.get('project_description','')}"
            for a in anchor_qtns
        ]
        anc_sel = st.selectbox("🔗 Pull QTN from Anchor Portal", anc_options,
                               help="Select a quotation number created in Anchor Portal to auto-fill")
        if anc_sel != "— type manually —":
            chosen = anchor_qtns[anc_options.index(anc_sel) - 1]
            h["qtn_number"]    = chosen.get("quote_ref", "")
            h["customer_name"] = chosen.get("client_name", "")
            st.success(f"Auto-filled QTN **{h['qtn_number']}** and customer **{h['customer_name']}**")

        c1, c2, c3 = st.columns(3)
        h["qtn_number"] = c1.text_input("Quotation Number *", h["qtn_number"])
        h["revision"]   = c2.selectbox("Revision", ["R0","R1","R2","R3","R4","R5"],
                                        index=["R0","R1","R2","R3","R4","R5"].index(h.get("revision","R0")))
        h["status"]     = c3.selectbox("Status", ["Draft","Issued","Won","Lost","On Hold"],
                                        index=["Draft","Issued","Won","Lost","On Hold"].index(h.get("status","Draft")))

        st.markdown("#### Customer")
        # Dropdown from master_clients (already in your ERP)
        cust_opts = ["— select —"] + client_names
        cust_idx = cust_opts.index(h["customer_name"]) if h["customer_name"] in cust_opts else 0
        sel_cust = st.selectbox("Customer (from Master Clients)", cust_opts, index=cust_idx)
        if sel_cust != "— select —":
            h["customer_name"] = sel_cust
            cust_detail = next((c for c in clients if c["name"]==sel_cust), {})
            cols = st.columns(4)
            cols[0].caption(f"📍 {cust_detail.get('address','—')}")
            cols[1].caption(f"🏷️ GSTIN: {cust_detail.get('gstin','—')}")
            cols[2].caption(f"👤 {cust_detail.get('contact_person','—')}")
            cols[3].caption(f"📞 {cust_detail.get('phone','—')}")

        st.markdown("#### Equipment Details")
        c1, c2 = st.columns(2)
        h["equipment_desc"] = c1.text_input("Equipment Description", h["equipment_desc"])
        h["tag_number"]     = c2.text_input("Tag Number", h["tag_number"])

        c1,c2,c3,c4,c5 = st.columns(5)
        h["capacity_ltrs"] = c1.number_input("Capacity (Ltrs)", value=float(h["capacity_ltrs"]), min_value=0.0)
        h["shell_dia_mm"]  = c2.number_input("Shell ID (mm)",   value=float(h["shell_dia_mm"]),  min_value=0.0)
        h["shell_ht_mm"]   = c3.number_input("Shell Ht (mm)",   value=float(h["shell_ht_mm"]),   min_value=0.0)
        h["shell_thk_mm"]  = c4.number_input("Shell Thk (mm)",  value=float(h["shell_thk_mm"]),  min_value=0.0)
        h["dish_thk_mm"]   = c5.number_input("Dish Thk (mm)",   value=float(h["dish_thk_mm"]),   min_value=0.0)

        # Live geometry
        s_area = calc_shell_area(h["shell_dia_mm"], h["shell_ht_mm"])
        d_area = calc_dish_area(h["shell_dia_mm"])
        vol    = calc_shell_volume_ltrs(h["shell_dia_mm"], h["shell_ht_mm"])
        g1,g2,g3 = st.columns(3)
        g1.metric("Shell Area (m²)", f"{s_area:.3f}")
        g2.metric("Dish Area (m²)",  f"{d_area:.3f}")
        g3.metric("Shell Vol (Ltrs)",f"{vol:.0f}")

        c1,c2 = st.columns(2)
        h["jacket_type"]   = c1.text_input("Jacket Type",   h["jacket_type"])
        h["agitator_type"] = c2.text_input("Agitator Type", h["agitator_type"])

        c1,c2,c3 = st.columns(3)
        h["design_code"]     = c1.text_input("Design Code",     h["design_code"])
        h["design_pressure"] = c2.text_input("Design Pressure", h["design_pressure"])
        h["design_temp"]     = c3.text_input("Design Temp",     h["design_temp"])

        c1,c2 = st.columns(2)
        h["moc_shell"]  = c1.text_input("MOC – Shell",  h["moc_shell"])
        h["moc_jacket"] = c2.text_input("MOC – Jacket", h["moc_jacket"])

        st.markdown("#### Prepared By / Checked By")
        staff_list = [""] + st.session_state.master_data.get("staff", [])
        c1, c2 = st.columns(2)
        pb_idx = staff_list.index(h["prepared_by"]) if h["prepared_by"] in staff_list else 0
        cb_idx = staff_list.index(h["checked_by"])  if h["checked_by"]  in staff_list else 0
        h["prepared_by"] = c1.selectbox("Prepared By (Staff Master)", staff_list, index=pb_idx)
        h["checked_by"]  = c2.selectbox("Checked By (Staff Master)",  staff_list, index=cb_idx)
        h["notes"]       = st.text_area("Internal Notes", h["notes"], height=70)

    # ── F2: PLATES & PARTS ────────────────────────────────────────────────────
    with f2:
        st.markdown("#### Plates & Fabricated Parts")
        st.caption("Shell, dishes, jacket, stiffeners, agitator, lugs, manhole, etc.")

        with st.form("form_parts", clear_on_submit=True):
            c1,c2,c3 = st.columns(3)
            p_name  = c1.text_input("Part Name", placeholder="Main Shell")
            p_group = c2.selectbox("Group", ["SHELL","DISH_ENDS","JACKET","INS_JACKET","AGITATOR",
                                              "BAFFLES","LUGS","STIFFNERS","MANHOLE","RM_MISC","BODY_FL"])
            p_code  = c3.selectbox("RM Code", plate_rm or ["—"])

            c1,c2,c3,c4,c5 = st.columns(5)
            p_dia   = c1.number_input("Dia (mm)",    value=0.0, min_value=0.0)
            p_ht    = c2.number_input("Ht/Len (mm)", value=0.0, min_value=0.0)
            p_thk   = c3.number_input("Thk (mm)",    value=0.0, min_value=0.0)
            p_qty   = c4.number_input("Qty",          value=1.0, min_value=0.0)
            p_scrap = c5.number_input("Scrap %",      value=5.0, min_value=0.0, max_value=50.0)

            p_rate_ov = st.number_input("Rate Override ₹/kg  (0 = use master)", value=0.0, min_value=0.0)
            p_is_dish = st.checkbox("Is Dish/End (torispherical area formula)")

            if st.form_submit_button("➕ Add Part"):
                rm  = rm_master.get(p_code, {})
                rate = p_rate_ov if p_rate_ov > 0 else (rm.get("rate") or 0)
                wt   = calc_dish_weight(p_dia, p_thk, 8000, p_scrap/100) if p_is_dish \
                       else calc_plate_weight(calc_shell_area(p_dia, p_ht), p_thk, 8000, p_scrap/100)
                total_wt = wt * p_qty
                st.session_state.est_parts.append(dict(
                    name=p_name, group=p_group, item_code=p_code,
                    dia_mm=p_dia, ht_mm=p_ht, thk_mm=p_thk, qty=p_qty,
                    scrap_pct=p_scrap, net_wt_kg=round(wt,3),
                    total_wt_kg=round(total_wt,3), rate=rate,
                    amount=round(total_wt*rate,2), is_dish=p_is_dish
                ))
                st.rerun()

        if st.session_state.est_parts:
            df = pd.DataFrame(st.session_state.est_parts)[
                ["name","group","dia_mm","ht_mm","thk_mm","qty","total_wt_kg","rate","amount"]]
            df.columns = ["Part","Group","Dia","Ht","Thk","Qty","Wt(kg)","Rate","Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"**Total Plates & Parts: ₹{sum(p['amount'] for p in st.session_state.est_parts):,.0f}**")
            if st.button("🗑️ Clear All Parts"): st.session_state.est_parts=[]; st.rerun()

    # ── F3: PIPES & FLANGES ───────────────────────────────────────────────────
    with f3:
        st.markdown("#### Nozzle Pipes")
        with st.form("form_pipes", clear_on_submit=True):
            c1,c2,c3,c4 = st.columns(4)
            pp_name = c1.text_input("Description", placeholder="2\" Nozzle Pipe")
            pp_code = c2.selectbox("Pipe Code", pipe_rm or ["—"])
            pp_len  = c3.number_input("Length (m)", value=0.2, min_value=0.0)
            pp_qty  = c4.number_input("Qty", value=1.0, min_value=0.0)
            pp_rate = st.number_input("Rate Override (0=master)", value=0.0, min_value=0.0)
            if st.form_submit_button("➕ Add Pipe"):
                rm   = rm_master.get(pp_code, {})
                rate = pp_rate if pp_rate > 0 else (rm.get("rate") or 0)
                wpm  = rm.get("unit_wt_kg_per_m") or 0
                wt   = wpm * pp_len * 1.05 * pp_qty
                st.session_state.est_pipes.append(dict(
                    name=pp_name, item_code=pp_code, length_m=pp_len,
                    qty=pp_qty, wt_per_m=wpm, total_wt_kg=round(wt,3),
                    rate=rate, amount=round(wt*rate,2)
                ))
                st.rerun()
        if st.session_state.est_pipes:
            df = pd.DataFrame(st.session_state.est_pipes)[["name","item_code","length_m","qty","total_wt_kg","rate","amount"]]
            df.columns=["Desc","Code","Len(m)","Qty","Wt(kg)","Rate","Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"**Total Pipes: ₹{sum(p['amount'] for p in st.session_state.est_pipes):,.0f}**")
            if st.button("🗑️ Clear Pipes"): st.session_state.est_pipes=[]; st.rerun()

        st.markdown("#### Flanges & Fittings")
        with st.form("form_flanges", clear_on_submit=True):
            c1,c2,c3,c4 = st.columns(4)
            fl_name = c1.text_input("Description", placeholder="4\" #150 Blind Flange")
            fl_code = c2.selectbox("Flange Code", flg_rm or ["—"])
            fl_qty  = c3.number_input("Qty", value=1.0, min_value=0.0)
            fl_rate = c4.number_input("Rate Override (0=master)", value=0.0, min_value=0.0)
            if st.form_submit_button("➕ Add Flange"):
                rm   = rm_master.get(fl_code, {})
                rate = fl_rate if fl_rate > 0 else (rm.get("rate") or 0)
                wt   = ((rm.get("unit_wt_kg_per_m") or 0) * 1.15) * fl_qty
                st.session_state.est_flanges.append(dict(
                    name=fl_name, item_code=fl_code, qty=fl_qty,
                    total_wt_kg=round(wt,3), rate=rate, amount=round(wt*rate,2)
                ))
                st.rerun()
        if st.session_state.est_flanges:
            df = pd.DataFrame(st.session_state.est_flanges)[["name","item_code","qty","total_wt_kg","rate","amount"]]
            df.columns=["Desc","Code","Qty","Wt(kg)","Rate","Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"**Total Flanges: ₹{sum(p['amount'] for p in st.session_state.est_flanges):,.0f}**")
            if st.button("🗑️ Clear Flanges"): st.session_state.est_flanges=[]; st.rerun()

    # ── F4: BOUGHT-OUT & OH ───────────────────────────────────────────────────
    with f4:
        st.markdown("#### Bought-Out Items")
        with st.form("form_bo", clear_on_submit=True):
            c1,c2,c3,c4,c5 = st.columns(5)
            bo_desc  = c1.text_input("Description")
            bo_code  = c2.selectbox("BO Code", bo_rm or ["—"])
            bo_qty   = c3.number_input("Qty", value=1.0, min_value=0.0)
            bo_rate  = c4.number_input("Rate Override (0=master)", value=0.0, min_value=0.0)
            bo_group = c5.selectbox("Group", ["BO","FASTENERS","INSULATION","OTHER"])
            if st.form_submit_button("➕ Add"):
                rm   = rm_master.get(bo_code, {})
                rate = bo_rate if bo_rate > 0 else (rm.get("rate") or 0)
                st.session_state.est_bo.append(dict(
                    name=bo_desc or rm.get("description",""), item_code=bo_code,
                    qty=bo_qty, rate=rate, amount=round(rate*bo_qty,2), group=bo_group
                ))
                st.rerun()
        if st.session_state.est_bo:
            df = pd.DataFrame(st.session_state.est_bo)[["name","item_code","qty","rate","amount","group"]]
            df.columns=["Desc","Code","Qty","Rate","Amount(₹)","Group"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"**Total Bought-Out: ₹{sum(b['amount'] for b in st.session_state.est_bo):,.0f}**")
            if st.button("🗑️ Clear BO"): st.session_state.est_bo=[]; st.rerun()

        st.markdown("#### Overheads (Labour · Consumables · Testing · Packing)")
        with st.form("form_oh", clear_on_submit=True):
            c1,c2,c3,c4 = st.columns(4)
            oh_code_sel = c1.selectbox("OH Code", oh_codes or ["—"])
            oh_qty      = c2.number_input("Qty / Hrs / m²", value=1.0, min_value=0.0)
            oh_rate_ov  = c3.number_input("Rate Override (0=master)", value=0.0, min_value=0.0)
            oh_desc_ov  = c4.text_input("Description override (optional)")
            if st.form_submit_button("➕ Add OH"):
                oh   = oh_master.get(oh_code_sel, {})
                rate = oh_rate_ov if oh_rate_ov > 0 else (oh.get("rate") or 0)
                uom  = oh.get("uom","")
                desc = oh_desc_ov or oh.get("description","")
                if uom == "%":   # consumables on RM
                    base = (sum(p["amount"] for p in st.session_state.est_parts) +
                            sum(p["amount"] for p in st.session_state.est_pipes) +
                            sum(p["amount"] for p in st.session_state.est_flanges))
                    amount = base * rate / 100
                else:
                    amount = rate * oh_qty
                st.session_state.est_oh.append(dict(
                    oh_code=oh_code_sel, description=desc,
                    oh_type=oh.get("oh_type",""), uom=uom,
                    qty=oh_qty, rate=rate, amount=round(amount,2)
                ))
                st.rerun()
        if st.session_state.est_oh:
            df = pd.DataFrame(st.session_state.est_oh)[["description","oh_type","uom","qty","rate","amount"]]
            df.columns=["Description","Type","UOM","Qty","Rate","Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"**Total OH: ₹{sum(o['amount'] for o in st.session_state.est_oh):,.0f}**")
            if st.button("🗑️ Clear OH"): st.session_state.est_oh=[]; st.rerun()

    # ── F5: SUMMARY & SAVE ────────────────────────────────────────────────────
    with f5:
        st.markdown("#### Margin & Price Settings")
        s1,s2,s3,s4,s5,s6 = st.columns(6)
        h["profit_margin_pct"] = s1.number_input("Profit %",      value=float(h["profit_margin_pct"]), min_value=0.0, max_value=60.0, step=0.5)
        h["contingency_pct"]   = s2.number_input("Contingency %", value=float(h["contingency_pct"]),   min_value=0.0, max_value=20.0, step=0.5)
        h["engg_design_amt"]   = s3.number_input("Engg & ASME ₹", value=float(h["engg_design_amt"]),   min_value=0.0, step=1000.0)
        h["packing_amt"]       = s4.number_input("Packing ₹",     value=float(h["packing_amt"]),       min_value=0.0, step=500.0)
        h["freight_amt"]       = s5.number_input("Freight ₹",     value=float(h["freight_amt"]),       min_value=0.0, step=500.0)
        h["gst_pct"]           = s6.number_input("GST %",         value=float(h["gst_pct"]),           min_value=0.0, max_value=28.0, step=0.5)

        T = calc_totals(
            st.session_state.est_parts, st.session_state.est_pipes,
            st.session_state.est_flanges, st.session_state.est_bo, st.session_state.est_oh,
            h["profit_margin_pct"], h["contingency_pct"],
            h["packing_amt"], h["freight_amt"], h["gst_pct"], h["engg_design_amt"]
        )

        left, right = st.columns([3, 2])
        with left:
            st.markdown("#### Cost Breakup")
            cost_df = pd.DataFrame({
                "Component": [
                    "Plates & Fabricated Parts","Pipes","Flanges","Bought-Out Items",
                    "Labour","Consumables & Other OH","Engg & ASME Design",
                    "Contingency","Profit","Packing & Freight",
                    "─────────","Ex-Works Price","GST","FOR Price"
                ],
                "Amount (₹)": [
                    T["tot_plates"], T["tot_pipes"], T["tot_flanges"], T["tot_bo"],
                    T["tot_lab"], T["tot_cons"]+T["tot_other"], T["engg_design"],
                    T["cont_amt"], T["profit_amt"], T["packing"]+T["freight"],
                    0, T["ex_works"], T["gst_amt"], T["for_price"]
                ]
            })
            cost_df["Amount (₹)"] = cost_df["Amount (₹)"].map(
                lambda x: "─────────" if x==0 and "─" in str(x) else f"₹{x:,.0f}")
            st.dataframe(cost_df, use_container_width=True, hide_index=True)

        with right:
            st.markdown("#### Margin Health Check")
            checks = [
                ("RM %",     T["rm_pct"],           45, 60),
                ("Labour %", T["lab_pct"],           15, 25),
                ("OH %",     T["oh_pct"],             8, 15),
                ("Profit %", T["profit_pct_actual"], 12, 20),
            ]
            for label, val, lo, hi in checks:
                ok = lo <= val <= hi
                icon = "✅" if ok else ("⚠️" if val > 0 else "🔴")
                st.write(f"{icon} **{label}:** {val:.1f}%  _(target {lo}–{hi}%)_")

            issues = margin_issues(T)
            if not issues: st.success("All margins within healthy range!")
            else:
                for iss in issues: st.warning(iss)

            st.markdown("#### What-If Price Table")
            wi = pd.DataFrame([{
                "Margin": f"{m}%",
                "Ex-Works (₹)": f"₹{(T['cbm']*(1+m/100)+T['packing']+T['freight']):,.0f}"
            } for m in [8,10,12,15,18,20]])
            st.dataframe(wi, hide_index=True, use_container_width=True)

        # Key metrics
        st.divider()
        k1,k2,k3,k4,k5 = st.columns(5)
        k1.metric("Raw Material",  f"₹{T['tot_rm']:,.0f}")
        k2.metric("Total Mfg",     f"₹{T['tot_mfg']:,.0f}")
        k3.metric("Ex-Works",      f"₹{T['ex_works']:,.0f}")
        k4.metric("GST",           f"₹{T['gst_amt']:,.0f}")
        k5.metric("FOR Price",     f"₹{T['for_price']:,.0f}")
        st.divider()

        b1, b2, b3 = st.columns(3)

        # SAVE
        if b1.button("💾 Save to Supabase", type="primary", use_container_width=True):
            if not h["qtn_number"]:
                st.error("Quotation Number is required before saving.")
            else:
                row = {
                    **{k: h[k] for k in h},
                    "parts_json":   json.dumps(st.session_state.est_parts),
                    "pipes_json":   json.dumps(st.session_state.est_pipes),
                    "flanges_json": json.dumps(st.session_state.est_flanges),
                    "bo_json":      json.dumps(st.session_state.est_bo),
                    "oh_json":      json.dumps(st.session_state.est_oh),
                    "updated_at":   datetime.now().isoformat(),
                }
                if edit_id:
                    ok = sb_update("estimations", row, "id", edit_id)
                    if ok: st.success(f"✅ Updated **{h['qtn_number']}** in Supabase.")
                else:
                    row["created_at"] = datetime.now().isoformat()
                    ok = sb_insert("estimations", row)
                    if ok: st.success(f"✅ Saved **{h['qtn_number']}** to Supabase.")
                if ok:
                    st.cache_data.clear()
                    for k in ["est_hdr","est_parts","est_pipes","est_flanges","est_bo","est_oh","est_edit_id"]:
                        if k in st.session_state: del st.session_state[k]
                    st.rerun()

        # RESET
        if b2.button("🔄 Reset Form", use_container_width=True):
            for k in ["est_hdr","est_parts","est_pipes","est_flanges","est_bo","est_oh","est_edit_id"]:
                if k in st.session_state: del st.session_state[k]
            st.rerun()

        # DOWNLOAD DOCX (without saving)
        cust_data = next((c for c in clients if c["name"]==h.get("customer_name","")), {})
        docx_buf = generate_docx(h, cust_data, T)
        b3.download_button(
            "📄 Generate Quotation DOCX",
            docx_buf,
            file_name=f"{h.get('qtn_number','QTN')}_{h.get('revision','R0')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )

# ══════════════════════════════════════════════════════════════════════════════
# TAB C — MASTERS
# ══════════════════════════════════════════════════════════════════════════════
with TAB_MASTERS:
    mt1, mt2 = st.tabs(["🔩 RM & BO Master", "⚙️ OH Master"])

    with mt1:
        st.subheader("Raw Material & Bought-Out Master")
        df_rm = pd.DataFrame(sb_fetch("est_rm_master", order="category"))
        if not df_rm.empty:
            st.dataframe(df_rm[["ref_code","description","category","material","spec",
                                 "size","uom","rate","unit_wt_kg_per_m","active"]],
                         use_container_width=True, hide_index=True)
        with st.expander("➕ Add / Update Item"):
            with st.form("rm_add_form", clear_on_submit=True):
                c1,c2 = st.columns(2)
                rc=c1.text_input("Ref Code (unique)"); desc=c2.text_input("Description")
                c1,c2,c3=st.columns(3)
                cat=c1.selectbox("Category",["RM","BO"])
                rmt=c2.text_input("Type (Plate/Pipe/FLG/etc)")
                mat=c3.text_input("Material (SS316L/SS304/MS)")
                c1,c2,c3,c4=st.columns(4)
                spec=c1.text_input("Spec"); sz=c2.text_input("Size")
                uom=c3.selectbox("UOM",["Kg","Nos","Set","LS","Sq.M"])
                rate=c4.number_input("Rate ₹",min_value=0.0)
                uwt=st.number_input("Unit Wt kg/m (pipes only)",min_value=0.0)
                if st.form_submit_button("Save"):
                    ok = sb_insert("est_rm_master", dict(
                        ref_code=rc, description=desc, category=cat, rm_type=rmt,
                        material=mat, spec=spec, size=sz, uom=uom, rate=rate,
                        unit_wt_kg_per_m=uwt if uwt>0 else None, active="Yes"
                    ))
                    if ok: st.cache_data.clear(); st.success(f"Saved {rc}"); st.rerun()

    with mt2:
        st.subheader("Overhead Master")
        df_oh = pd.DataFrame(sb_fetch("est_oh_master", order="oh_type"))
        if not df_oh.empty:
            st.dataframe(df_oh[["oh_code","description","oh_type","uom","rate","source"]],
                         use_container_width=True, hide_index=True)
        with st.expander("➕ Add / Update OH"):
            with st.form("oh_add_form", clear_on_submit=True):
                c1,c2,c3,c4,c5=st.columns(5)
                oc=c1.text_input("OH Code"); od=c2.text_input("Description")
                ot=c3.selectbox("Type",["LABOUR","LABOUR_BUFF","CONSUMABLES","TESTING",
                                        "DOCS","PACKING","TRANSPORT","MISC","ELECTRO_POLISH"])
                ou=c4.selectbox("UOM",["Hr","Sq.M","%","LS"])
                or_=c5.number_input("Rate",min_value=0.0)
                if st.form_submit_button("Save"):
                    ok = sb_insert("est_oh_master", dict(
                        oh_code=oc, description=od, oh_type=ot, uom=ou, rate=or_, source="Internal"
                    ))
                    if ok: st.cache_data.clear(); st.success(f"Saved {oc}"); st.rerun()
