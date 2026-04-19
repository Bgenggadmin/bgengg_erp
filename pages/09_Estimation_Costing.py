import streamlit as st
from st_supabase_connection import SupabaseConnection
from database_utils import fetch_all_master_data
import json, math, io
from datetime import date, datetime
import pandas as pd
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

st.set_page_config(
    page_title="Estimation & Costing | BGEngg ERP",
    page_icon="📐",
    layout="wide",
)

conn = st.connection("supabase", type=SupabaseConnection)
if "master_data" not in st.session_state:
    st.session_state.master_data = fetch_all_master_data(conn)

# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def sb_fetch(table, select="*", order=None, filters=None):
    try:
        q = conn.table(table).select(select)
        if order:
            q = q.order(order)
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        return q.execute().data or []
    except Exception as e:
        st.error(f"DB read error ({table}): {e}")
        return []

def sb_insert(table, row):
    try:
        conn.table(table).insert(row).execute()
        return True
    except Exception as e:
        st.error(f"DB insert error ({table}): {e}")
        return False

def sb_update(table, row, match_col, match_val):
    try:
        conn.table(table).update(row).eq(match_col, match_val).execute()
        return True
    except Exception as e:
        st.error(f"DB update error ({table}): {e}")
        return False

# ─────────────────────────────────────────────────────────────────────────────
# GEOMETRY ENGINE
# ─────────────────────────────────────────────────────────────────────────────
PI = math.pi

DENSITY = {
    "SS316L": 8000, "SS304": 8000, "MS": 7850,
    "EN8": 7800, "Ti": 4500, "C22": 8690, "Hastelloy": 8890,
}

def _m(mm):
    return mm / 1000.0

def geom_cylindrical_shell(id_mm, ht_mm, thk_mm, density=8000, scrap=0.05):
    return PI * _m(id_mm) * _m(ht_mm) * _m(thk_mm) * density * (1 + scrap)

def geom_dish_end(shell_id_mm, thk_mm, density=8000, scrap=0.15):
    r = _m(shell_id_mm * 1.167) / 2
    area = 1.09 * PI * r * r
    return area * _m(thk_mm) * density * (1 + scrap)

def geom_annular_plate(od_mm, id_mm, thk_mm, density=8000, scrap=0.05):
    area = (PI / 4.0) * (_m(od_mm) ** 2 - _m(id_mm) ** 2)
    return area * _m(thk_mm) * density * (1 + scrap)

def geom_solid_round(dia_mm, length_mm, density=8000, scrap=0.15):
    return (PI / 4.0) * _m(dia_mm) ** 2 * _m(length_mm) * density * (1 + scrap)

def geom_flat_rect(w_mm, h_mm, thk_mm, density=8000, scrap=0.05):
    return _m(w_mm) * _m(h_mm) * _m(thk_mm) * density * (1 + scrap)

def geom_stiffener_ring(shell_id_mm, shell_thk_mm, shell_ht_mm,
                        pitch_mm, bar_w_mm, bar_thk_mm, density=8000, scrap=0.05):
    shell_od_mm = shell_id_mm + 2.0 * shell_thk_mm
    circ_m      = PI * _m(shell_od_mm)
    n_rings     = _m(shell_ht_mm) / _m(pitch_mm) if pitch_mm > 0 else 0.0
    wt_per_ring = circ_m * _m(bar_w_mm) * _m(bar_thk_mm) * density * (1 + scrap)
    total_wt    = wt_per_ring * n_rings
    return wt_per_ring, n_rings, total_wt

def geom_cone(large_id_mm, small_id_mm, ht_mm, thk_mm, density=8000, scrap=0.05):
    R1 = _m(large_id_mm) / 2
    R2 = _m(small_id_mm) / 2
    slant = math.sqrt(_m(ht_mm) ** 2 + (R1 - R2) ** 2)
    return PI * (R1 + R2) * slant * _m(thk_mm) * density * (1 + scrap)

def geom_rect_plate(length_mm, width_mm, thk_mm, density=8000, scrap=0.05):
    return _m(length_mm) * _m(width_mm) * _m(thk_mm) * density * (1 + scrap)

def geom_tube_bundle(tube_od_mm, tube_thk_mm, tube_length_mm, n_tubes, density=8000, scrap=0.05):
    mid_r = (_m(tube_od_mm) / 2) - (_m(tube_thk_mm) / 2)
    wt_per = PI * 2 * mid_r * _m(tube_length_mm) * _m(tube_thk_mm) * density
    return wt_per * n_tubes * (1 + scrap)

PART_TYPES = {
    "Cylindrical shell": {
        "fields": [("id_mm","Shell ID (mm)"),("ht_mm","Height (mm)"),("thk_mm","Thickness (mm)")],
        "fn": "shell",
    },
    "Dish end (torispherical)": {
        "fields": [("shell_id_mm","Shell ID (mm)"),("thk_mm","Thickness (mm)")],
        "fn": "dish",
    },
    "Annular plate / flange": {
        "fields": [("od_mm","Outer Dia OD (mm)"),("id_mm","Inner Dia ID (mm)"),("thk_mm","Thickness (mm)")],
        "fn": "annular",
    },
    "Solid round (shaft / bush)": {
        "fields": [("dia_mm","Diameter (mm)"),("length_mm","Length (mm)")],
        "fn": "solid",
    },
    "Flat rectangle (blade / pad / gusset)": {
        "fields": [("w_mm","Width (mm)"),("h_mm","Height (mm)"),("thk_mm","Thickness (mm)")],
        "fn": "flat",
    },
    "Stiffener rings (flat bar on shell OD)": {
        "fields": [
            ("shell_id_mm","Shell ID (mm)"),("shell_thk_mm","Shell Thickness (mm)"),
            ("shell_ht_mm","Shell Height (mm)"),("pitch_mm","Ring Pitch (mm)"),
            ("bar_w_mm","Bar Width (mm)"),("thk_mm","Bar Thickness (mm)"),
        ],
        "fn": "stiff",
        "qty_derived": True,
    },
    "Cone / reducer": {
        "fields": [
            ("large_id_mm","Large End ID (mm)"),("small_id_mm","Small End ID (mm)"),
            ("ht_mm","Height (mm)"),("thk_mm","Thickness (mm)"),
        ],
        "fn": "cone",
    },
    "Rectangular plate": {
        "fields": [("length_mm","Length (mm)"),("width_mm","Width (mm)"),("thk_mm","Thickness (mm)")],
        "fn": "rect",
    },
    "Tube bundle": {
        "fields": [
            ("tube_od_mm","Tube OD (mm)"),("tube_thk_mm","Tube Thickness (mm)"),
            ("tube_length_mm","Tube Length (mm)"),("n_tubes","Number of Tubes"),
        ],
        "fn": "tube",
    },
}

def calc_weight(fn, dims, density, qty):
    d = dims
    used_qty = qty
    wt = 0.0
    try:
        if fn == "shell":
            wt = geom_cylindrical_shell(d["id_mm"], d["ht_mm"], d["thk_mm"], density)
        elif fn == "dish":
            wt = geom_dish_end(d["shell_id_mm"], d["thk_mm"], density)
        elif fn == "annular":
            wt = geom_annular_plate(d["od_mm"], d["id_mm"], d["thk_mm"], density)
        elif fn == "solid":
            wt = geom_solid_round(d["dia_mm"], d["length_mm"], density)
        elif fn == "flat":
            wt = geom_flat_rect(d["w_mm"], d["h_mm"], d["thk_mm"], density)
        elif fn == "stiff":
            wt, used_qty, total = geom_stiffener_ring(
                d.get("shell_id_mm",0), d.get("shell_thk_mm",0), d.get("shell_ht_mm",0),
                d.get("pitch_mm",100), d.get("bar_w_mm",0), d.get("thk_mm",0), density,
            )
            return round(wt, 3), round(total, 3), round(used_qty, 2)
        elif fn == "cone":
            wt = geom_cone(d["large_id_mm"], d["small_id_mm"], d["ht_mm"], d["thk_mm"], density)
        elif fn == "rect":
            wt = geom_rect_plate(d["length_mm"], d["width_mm"], d["thk_mm"], density)
        elif fn == "tube":
            wt = geom_tube_bundle(d["tube_od_mm"], d["tube_thk_mm"], d["tube_length_mm"], d["n_tubes"], density)
        else:
            wt = 0.0
    except Exception as e:
        st.warning(f"Weight calc error ({fn}): {e} | dims: {dims}")
        wt = 0.0
    return round(wt, 3), round(wt * used_qty, 3), used_qty

# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT TYPES
# ─────────────────────────────────────────────────────────────────────────────
EQUIPMENT_TYPES = {
    "SSR — Stainless Steel Reactor":        {"icon":"⚗️",  "category":"Reactor",        "margin_hint":(12,18), "labour_norm":"High",      "description":"SS316L reactor with jacket, agitator, mechanical seal"},
    "RCVD — Receiver cum Decanter":         {"icon":"🧪",  "category":"Reactor",        "margin_hint":(12,16), "labour_norm":"Medium",    "description":"SS316L receiver cum decanter, no agitator"},
    "ANFD — Agitated Nutsche Filter Dryer": {"icon":"🔩",  "category":"Filter",         "margin_hint":(14,20), "labour_norm":"Very High", "description":"ANFD with filter plate, agitator, jacket"},
    "VST — Vertical Storage Tank":          {"icon":"🛢️",  "category":"Storage",        "margin_hint":(10,15), "labour_norm":"Low",       "description":"Plain vertical storage tank"},
    "HST — Horizontal Storage Tank":        {"icon":"🛢️",  "category":"Storage",        "margin_hint":(10,15), "labour_norm":"Low",       "description":"Horizontal tank with saddle supports"},
    "PNF — Plain Nutsche Filter":           {"icon":"🔲",  "category":"Filter",         "margin_hint":(10,15), "labour_norm":"Medium",    "description":"Plain nutsche filter, no agitator"},
    "Leaf Filter":                          {"icon":"🍃",  "category":"Filter",         "margin_hint":(12,18), "labour_norm":"High",      "description":"Leaf filter vessel with filter leaves"},
    "Condenser":                            {"icon":"❄️",  "category":"Heat Exchanger", "margin_hint":(12,18), "labour_norm":"High",      "description":"Shell and tube condenser"},
    "Reboiler":                             {"icon":"♨️",  "category":"Heat Exchanger", "margin_hint":(12,18), "labour_norm":"High",      "description":"Kettle / thermosyphon reboiler"},
    "Tray Dryer":                           {"icon":"📦",  "category":"Dryer",          "margin_hint":(14,20), "labour_norm":"High",      "description":"SS316L tray dryer with trays"},
    "Octagonal Blender":                    {"icon":"🔷",  "category":"Mixer",          "margin_hint":(15,22), "labour_norm":"Very High", "description":"Octagonal blender / V-blender"},
    "Multi Miller":                         {"icon":"⚙️",  "category":"Powder",         "margin_hint":(15,22), "labour_norm":"Very High", "description":"Multi mill / sifter"},
    "Distillation Column":                  {"icon":"🏛️",  "category":"Column",         "margin_hint":(14,20), "labour_norm":"High",      "description":"Distillation column with trays or packing"},
    "ATFD — Agitated Thin Film Dryer":      {"icon":"🌀",  "category":"Dryer",          "margin_hint":(18,25), "labour_norm":"Very High", "description":"ATFD / thin film evaporator"},
    "MEE — Multiple Effect Evaporator":     {"icon":"💧",  "category":"Evaporator",     "margin_hint":(16,22), "labour_norm":"Very High", "description":"Multiple effect evaporator package"},
    "Rectangular Tank":                     {"icon":"📐",  "category":"Storage",        "margin_hint":(10,15), "labour_norm":"Low",       "description":"Rectangular / sump tank"},
    "Skid / Package":                       {"icon":"🏗️",  "category":"Package",        "margin_hint":(14,20), "labour_norm":"High",      "description":"Multi-equipment skid package"},
    "Custom Equipment":                     {"icon":"🔧",  "category":"Custom",         "margin_hint":(10,20), "labour_norm":"Medium",    "description":"User-defined — all fields manual"},
}
EQUIPMENT_NAMES = list(EQUIPMENT_TYPES.keys())

# ─────────────────────────────────────────────────────────────────────────────
# COST ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def calc_shell_area(dia_mm, ht_mm):
    return PI * _m(dia_mm) * _m(ht_mm)

def calc_dish_area(shell_id_mm):
    r = _m(shell_id_mm * 1.167) / 2
    return 1.09 * PI * r * r

def calc_shell_volume_ltrs(dia_mm, ht_mm):
    return PI * (_m(dia_mm) / 2) ** 2 * _m(ht_mm) * 1000

def calc_totals(parts, pipes, flanges, bo_items, oh_items,
                profit_pct, contingency_pct, packing, freight, gst_pct, engg_design):
    tot_plates  = sum(p.get("amount", 0) for p in parts)
    tot_pipes   = sum(p.get("amount", 0) for p in pipes)
    tot_flanges = sum(p.get("amount", 0) for p in flanges)
    tot_rm      = tot_plates + tot_pipes + tot_flanges
    tot_bo      = sum(p.get("amount", 0) for p in bo_items)
    tot_lab     = sum(o.get("amount", 0) for o in oh_items if o.get("oh_type") in ("LABOUR","LABOUR_BUFF"))
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
# DOCX GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
def _shd(cell, hex_color):
    s = OxmlElement("w:shd")
    s.set(qn("w:val"),"clear"); s.set(qn("w:color"),"auto"); s.set(qn("w:fill"),hex_color)
    cell._tc.get_or_add_tcPr().append(s)

def _run(para, text, bold=False, size=9, color=None):
    r = para.add_run(text)
    r.font.size = Pt(size); r.font.name = "Arial"; r.font.bold = bold
    if color:
        r.font.color.rgb = RGBColor(*color)
    return r

def _kv_table(doc, rows):
    t = doc.add_table(rows=0, cols=2); t.style = "Table Grid"
    for i, (k, v) in enumerate(rows):
        row = t.add_row()
        for j, txt in enumerate([k, v]):
            c = row.cells[j]; c.text = ""
            _run(c.paragraphs[0], str(txt), bold=(j==0), size=9)
            _shd(c, ("D6E4F7" if i%2==0 else "F2F2F2") if j==0 else ("FFFFFF" if i%2==0 else "EFF5FB"))

def generate_docx(est, customer, totals):
    doc = Document()
    for sec in doc.sections:
        sec.top_margin=Cm(1.8); sec.bottom_margin=Cm(1.8)
        sec.left_margin=Cm(2.0); sec.right_margin=Cm(2.0)

    def banner():
        t = doc.add_table(rows=1, cols=1); t.style="Table Grid"
        c = t.rows[0].cells[0]; _shd(c,"1B3A6B"); c.paragraphs[0].clear()
        p = c.paragraphs[0]; p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before=Pt(8); p.paragraph_format.space_after=Pt(8)
        _run(p,"B&G Engineering Industries\n",bold=True,size=15,color=(255,255,255))
        _run(p,"TECHNICAL & COMMERCIAL OFFER\n",bold=True,size=12,color=(204,221,255))
        _run(p,est.get("equipment_desc",""),bold=True,size=10,color=(255,255,255))

    def sec_head(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before=Pt(10); p.paragraph_format.space_after=Pt(2)
        _run(p,text,bold=True,size=12,color=(27,58,107))
        pBdr=OxmlElement("w:pBdr"); bot=OxmlElement("w:bottom")
        bot.set(qn("w:val"),"single"); bot.set(qn("w:sz"),"6"); bot.set(qn("w:space"),"1"); bot.set(qn("w:color"),"2E75B6")
        pBdr.append(bot); p._p.get_or_add_pPr().append(pBdr)

    def body(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before=Pt(2); p.paragraph_format.space_after=Pt(2)
        _run(p,text,size=9,color=(68,68,68))

    fmt = lambda n: f"₹{n:,.0f}"
    cust = customer or {}

    banner(); doc.add_paragraph()
    sec_head("SECTION 1 — OFFER & CUSTOMER DETAILS")
    _kv_table(doc,[
        ("Offer Reference",est.get("qtn_number","")),("Revision",est.get("revision","R0")),
        ("Date",date.today().strftime("%d %B %Y")),("Equipment Type",est.get("equipment_type","")),
        ("Prepared By",est.get("prepared_by","")),("Checked By",est.get("checked_by","")),
        ("Customer Name",cust.get("name","")),("Address",cust.get("address","")),
        ("GSTIN",cust.get("gstin","")),("Contact",cust.get("contact_person","")),
        ("Phone / Email",f"{cust.get('phone','') or ''} / {cust.get('email','') or ''}"),
    ])
    doc.add_paragraph()
    sec_head("SECTION 2 — TECHNICAL DESIGN BASIS")
    _kv_table(doc,[
        ("Equipment",est.get("equipment_desc","")),("Tag Number",est.get("tag_number","")),
        ("Capacity",f"{est.get('capacity_ltrs','')} Ltrs"),("Design Code",est.get("design_code","ASME Sec VIII Div 1")),
        ("Design Pressure",est.get("design_pressure","")),("Design Temp",est.get("design_temp","")),
        ("Shell ID",f"{est.get('shell_dia_mm','')} mm"),("Shell Ht",f"{est.get('shell_ht_mm','')} mm"),
        ("Shell Thk",f"{est.get('shell_thk_mm','')} mm"),("Dish Thk",f"{est.get('dish_thk_mm','')} mm"),
        ("Jacket Type",est.get("jacket_type","")),("Agitator Type",est.get("agitator_type","")),
        ("MOC — Shell",est.get("moc_shell","SS316L")),("MOC — Jacket",est.get("moc_jacket","SS304")),
    ])
    doc.add_paragraph()
    sec_head("SECTION 3 — MANUFACTURING APPROACH & QA")
    body("Manufactured under controlled engineering and quality systems ensuring ASME compliance and API/pharma service requirements.")
    for item in ["GA drawing submission and approval","Raw material verification against MTC",
                 "CNC cutting / controlled plate rolling","Qualified WPS/PQR and qualified welders",
                 "Radiography / DP / PT as per code","Internal grinding/buffing as specified",
                 "Hydrostatic testing as per ASME","Final dimensional and visual inspection before dispatch"]:
        p = doc.add_paragraph(item,style="List Bullet")
        for r in p.runs: r.font.size=Pt(9); r.font.name="Arial"
    doc.add_paragraph()
    sec_head("SECTION 4 — SCOPE OF SUPPLY & DOCUMENTATION")
    body("Engineering: GA Drawing, Nozzle Orientation, Fabrication Drawings, BOM, As-built Drawings.")
    body("Quality: MTC, NDT Reports (RT/PT/DP), Hydrostatic Test Report, Surface Finish Record, Inspection Release Note.")
    doc.add_paragraph()
    sec_head("SECTION 5 — COMMERCIAL SUMMARY")
    price_rows=[
        ("Raw Material (Plates, Pipes, Flanges)",fmt(totals["tot_rm"])),
        ("Bought-Out Items (Drive, Seal, BRG etc.)",fmt(totals["tot_bo"])),
        ("Fabrication & Services",fmt(totals["tot_oh"])),
        ("Engineering & ASME Design",fmt(totals["engg_design"])),
        ("Contingency",fmt(totals["cont_amt"])),("Operating Margin",fmt(totals["profit_amt"])),
        ("Packing & Forwarding",fmt(totals["packing"])),("Ex-Works Price",fmt(totals["ex_works"])),
        (f"GST @ {est.get('gst_pct',18):.0f}%",fmt(totals["gst_amt"])),("FINAL FOR PRICE",fmt(totals["for_price"])),
    ]
    t_price=doc.add_table(rows=0,cols=2); t_price.style="Table Grid"
    for i,(k,v) in enumerate(price_rows):
        row=t_price.add_row(); is_key=k in("Ex-Works Price","FINAL FOR PRICE")
        for j,txt in enumerate([k,v]):
            c=row.cells[j]; c.text=""
            _run(c.paragraphs[0],txt,bold=is_key,size=9,color=(255,255,255) if is_key else (26,26,26))
            _shd(c,"1B3A6B" if is_key else("FFFFFF" if i%2==0 else"EFF5FB"))
            if j==1: c.paragraphs[0].alignment=WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph()
    _kv_table(doc,[
        ("Price Basis","Ex-Works, Hyderabad. Packing included. Freight/insurance excluded."),
        ("Taxes","GST as applicable at time of dispatch."),
        ("Payment Terms","40% advance with PO | 50% inspection/dispatch | 10% on delivery."),
        ("Delivery","To be confirmed at order — from receipt of clear PO + advance."),
        ("Validity","7 days from date of offer."),
        ("Warranty","12 months from date of supply against manufacturing defects."),
        ("Exclusions","Civil works, E&I, erection & commissioning, DQ/IQ/OQ."),
    ])
    doc.add_paragraph()
    sec_head("SECTION 6 — SIGN-OFF")
    t_sign=doc.add_table(rows=2,cols=2); t_sign.style="Table Grid"
    for j,lbl in enumerate(["Prepared By","Checked By"]):
        c=t_sign.rows[0].cells[j]; c.text=""; _run(c.paragraphs[0],lbl,bold=True,size=9); _shd(c,"D6E4F7")
    for j,name in enumerate([est.get("prepared_by",""),est.get("checked_by","")]):
        c=t_sign.rows[1].cells[j]; c.text=""; _run(c.paragraphs[0],name,size=9)
    buf=io.BytesIO(); doc.save(buf); buf.seek(0)
    return buf

# ─────────────────────────────────────────────────────────────────────────────
# MASTER LOADERS
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
    return sb_fetch("master_clients", order="name")

@st.cache_data(ttl=60)
def load_anchor_qtns():
    return sb_fetch("anchor_projects", select="quote_ref,project_description,client_name", order="created_at")

@st.cache_data(ttl=30)
def load_all_estimations():
    return sb_fetch("estimations", order="updated_at")

# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────────────────
def _blank_hdr():
    return dict(
        qtn_number="", revision="R0", customer_name="", customer_id=None,
        equipment_type=EQUIPMENT_NAMES[0], equipment_desc="", tag_number="",
        capacity_ltrs=2000.0, shell_dia_mm=1300.0, shell_ht_mm=1500.0,
        shell_thk_mm=8.0, dish_thk_mm=10.0,
        jacket_type="SS304 Half-pipe Jacket with Insulation Jacket",
        agitator_type="Anchor", design_code="ASME Sec VIII Div 1",
        design_pressure="FV to 4.5 Bar", design_temp="-50 to 250°C",
        moc_shell="SS316L", moc_jacket="SS304", status="Draft",
        prepared_by="", checked_by="",
        profit_margin_pct=10.0, contingency_pct=0.0,
        packing_amt=5000.0, freight_amt=10000.0,
        gst_pct=18.0, engg_design_amt=25000.0, notes="",
    )

def _reset_form():
    for k in ["est_hdr","est_parts","est_pipes","est_flanges","est_bo","est_oh","est_edit_id","edit_part_idx"]:
        st.session_state.pop(k, None)

def _load_est_into_form(est):
    h = _blank_hdr()
    for k in h:
        if k in est and est[k] is not None:
            h[k] = est[k]
    st.session_state.est_hdr     = h
    st.session_state.est_parts   = json.loads(est.get("parts_json")   or "[]")
    st.session_state.est_pipes   = json.loads(est.get("pipes_json")   or "[]")
    st.session_state.est_flanges = json.loads(est.get("flanges_json") or "[]")
    st.session_state.est_bo      = json.loads(est.get("bo_json")      or "[]")
    st.session_state.est_oh      = json.loads(est.get("oh_json")      or "[]")
    st.session_state.est_edit_id = est.get("id")

for key, default in [
    ("est_hdr",       _blank_hdr()),
    ("est_parts",     []),
    ("est_pipes",     []),
    ("est_flanges",   []),
    ("est_bo",        []),
    ("est_oh",        []),
    ("est_edit_id",   None),
    ("edit_part_idx", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ─────────────────────────────────────────────────────────────────────────────
# PAGE
# ─────────────────────────────────────────────────────────────────────────────
st.title("📐 Estimation & Costing")
if st.session_state.est_edit_id:
    st.info(f"✏️ Editing: **{st.session_state.est_hdr.get('qtn_number','...')}** — go to ➕ New / Edit tab to continue.")
st.markdown("---")

TAB_LIST, TAB_NEW, TAB_SIMILAR, TAB_MASTERS = st.tabs([
    "📋 Register", "➕ New / Edit", "🔍 Similar Equipment", "📊 Masters",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB: REGISTER
# ══════════════════════════════════════════════════════════════════════════════
with TAB_LIST:
    st.subheader("Estimations Register")

    col_f1,col_f2,col_f3,col_f4 = st.columns(4)
    f_status   = col_f1.selectbox("Status",    ["All","Draft","Issued","Won","Lost","On Hold"])
    f_equip    = col_f2.selectbox("Equipment", ["All"]+EQUIPMENT_NAMES)
    f_customer = col_f3.text_input("Customer")
    f_search   = col_f4.text_input("QTN / Tag")

    all_est = load_all_estimations()
    if f_status != "All":
        all_est = [e for e in all_est if e.get("status")==f_status]
    if f_equip != "All":
        all_est = [e for e in all_est if e.get("equipment_type")==f_equip]
    if f_customer:
        all_est = [e for e in all_est if f_customer.lower() in (e.get("customer_name","") or "").lower()]
    if f_search:
        all_est = [e for e in all_est if
                   f_search.lower() in (e.get("qtn_number","") or "").lower() or
                   f_search.lower() in (e.get("tag_number","") or "").lower()]

    m1,m2,m3,m4 = st.columns(4)
    m1.metric("Total", len(all_est))
    m2.metric("Draft",  sum(1 for e in all_est if e.get("status")=="Draft"))
    m3.metric("Issued", sum(1 for e in all_est if e.get("status")=="Issued"))
    m4.metric("Won",    sum(1 for e in all_est if e.get("status")=="Won"))
    st.divider()

    if not all_est:
        st.info("No estimations yet. Use ➕ New / Edit tab to create one.")
    else:
        summary_rows = []
        for est in reversed(all_est):
            eq_info = EQUIPMENT_TYPES.get(est.get("equipment_type",""),{})
            status_icon = {"Draft":"🟡","Issued":"🔵","Won":"🟢","Lost":"🔴","On Hold":"⚪"}.get(est.get("status",""),"🟡")
            summary_rows.append({
                "":           f"{status_icon} {eq_info.get('icon','🔧')}",
                "QTN No":     est.get("qtn_number",""),
                "Customer":   est.get("customer_name",""),
                "Equipment":  est.get("equipment_desc",""),
                "Cap (L)":    est.get("capacity_ltrs",""),
                "Status":     est.get("status",""),
                "Prepared By":est.get("prepared_by",""),
                "Updated":    str(est.get("updated_at",""))[:10],
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        st.markdown("#### Select a quotation to view details and actions")
        qtn_opts = ["— select —"] + [e.get("qtn_number","") for e in reversed(all_est) if e.get("qtn_number")]
        selected_qtn = st.selectbox("Quotation Number", qtn_opts, label_visibility="collapsed")

        if selected_qtn != "— select —":
            est = next((e for e in all_est if e.get("qtn_number")==selected_qtn), None)
            if est:
                parts   = json.loads(est.get("parts_json")   or "[]")
                pipes   = json.loads(est.get("pipes_json")   or "[]")
                flanges = json.loads(est.get("flanges_json") or "[]")
                bo      = json.loads(est.get("bo_json")      or "[]")
                oh      = json.loads(est.get("oh_json")      or "[]")
                T = calc_totals(
                    parts,pipes,flanges,bo,oh,
                    float(est.get("profit_margin_pct") or 10),float(est.get("contingency_pct") or 0),
                    float(est.get("packing_amt") or 0),float(est.get("freight_amt") or 0),
                    float(est.get("gst_pct") or 18),float(est.get("engg_design_amt") or 0),
                )
                st.markdown("---")
                d1,d2,d3 = st.columns(3)
                d1.write(f"**Type:** {est.get('equipment_type','')}")
                d1.write(f"**Tag:** {est.get('tag_number','-')}")
                d2.write(f"**Revision:** {est.get('revision','R0')}")
                d2.write(f"**Prepared By:** {est.get('prepared_by','-')}")
                d3.write(f"**Status:** {est.get('status','')}")
                d3.write(f"**Updated:** {str(est.get('updated_at',''))[:10]}")

                k1,k2,k3,k4 = st.columns(4)
                k1.metric("Raw Material",f"₹{T['tot_rm']:,.0f}")
                k2.metric("Mfg Cost",    f"₹{T['tot_mfg']:,.0f}")
                k3.metric("Ex-Works",    f"₹{T['ex_works']:,.0f}")
                k4.metric("FOR Price",   f"₹{T['for_price']:,.0f}")

                st.markdown("**Actions**")
                a1,a2,a3,a4 = st.columns(4)

                if a1.button("✏️ Edit Estimation", use_container_width=True, type="primary"):
                    _load_est_into_form(est)
                    st.success("Loaded — click ➕ New / Edit tab to continue editing.")

                if a2.button("📋 Clone to New", use_container_width=True):
                    _load_est_into_form(est)
                    st.session_state.est_hdr["qtn_number"] = ""
                    st.session_state.est_hdr["revision"]   = "R0"
                    st.session_state.est_hdr["status"]     = "Draft"
                    st.session_state.est_hdr["notes"]      = f"Cloned from {est.get('qtn_number','')}"
                    st.session_state.est_edit_id           = None
                    st.success("Cloned — go to ➕ New / Edit tab and enter new QTN number.")

                cust_rows = sb_fetch("master_clients", filters={"name": est.get("customer_name","")})
                cust_data = cust_rows[0] if cust_rows else {}
                docx_buf  = generate_docx(est, cust_data, T)
                a3.download_button(
                    "📄 Download Quotation",
                    docx_buf,
                    file_name=f"{est.get('qtn_number','QTN')}_{est.get('revision','R0')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    key=f"dl_{est.get('id')}",
                )

                new_status = a4.selectbox(
                    "Change Status",
                    ["Draft","Issued","Won","Lost","On Hold"],
                    index=["Draft","Issued","Won","Lost","On Hold"].index(est.get("status","Draft")),
                    key=f"st_{est.get('id')}",
                )
                if new_status != est.get("status"):
                    if a4.button("✅ Apply Status", key=f"ap_{est.get('id')}", use_container_width=True):
                        sb_update("estimations",{"status":new_status,"updated_at":datetime.now().isoformat()},"id",est.get("id"))
                        st.cache_data.clear(); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB: NEW / EDIT
# ══════════════════════════════════════════════════════════════════════════════
with TAB_NEW:
    edit_id = st.session_state.est_edit_id
    st.subheader(f"✏️ Editing: {st.session_state.est_hdr.get('qtn_number','...')}" if edit_id else "➕ New Estimation")

    rm_master   = load_rm_master()
    oh_master   = load_oh_master()
    clients     = load_clients_full()
    anchor_qtns = load_anchor_qtns()

    client_names = [c["name"] for c in clients]
    oh_codes     = list(oh_master.keys())
    plate_rm     = [k for k,v in rm_master.items() if v.get("category")=="RM"]
    pipe_rm      = [k for k,v in rm_master.items() if v.get("rm_type")=="Pipe"]
    flg_rm       = [k for k,v in rm_master.items() if v.get("rm_type")=="FLG"]
    bo_rm        = [k for k,v in rm_master.items() if v.get("category")=="BO"]

    all_groups = sorted({
        "SHELL","DISH_ENDS","JACKET","INS_JACKET","AGITATOR","BAFFLES",
        "LUGS","STIFFNERS","MANHOLE","NOZZLES","RM_MISC","BODY_FL",
        "TUBE_BUNDLE","TUBE_SHEET","FILTER_PLATE","TRAYS","FRAME","OTHER"
    })

    f1,f2,f3,f4,f5 = st.tabs([
        "1️⃣ Header","2️⃣ Plates & Parts","3️⃣ Pipes & Flanges","4️⃣ Bought-Out & OH","5️⃣ Summary & Save",
    ])
    h = st.session_state.est_hdr

    # ── F1: HEADER ─────────────────────────────────────────────────────────────
    with f1:
        st.markdown("##### Equipment Type")
        prev_type = h.get("equipment_type",EQUIPMENT_NAMES[0])
        if prev_type not in EQUIPMENT_NAMES:
            prev_type = EQUIPMENT_NAMES[0]
        eq_c1,eq_c2 = st.columns([4,1])
        h["equipment_type"] = eq_c1.selectbox(
            "Equipment Type", EQUIPMENT_NAMES,
            index=EQUIPMENT_NAMES.index(prev_type),
            format_func=lambda x: f"{EQUIPMENT_TYPES[x]['icon']}  {x}",
            label_visibility="collapsed",
        )
        eq_info = EQUIPMENT_TYPES[h["equipment_type"]]
        eq_c2.metric("Category", eq_info["category"])
        st.caption(f"_{eq_info['description']}_  •  Margin: **{eq_info['margin_hint'][0]}–{eq_info['margin_hint'][1]}%**  •  Labour: **{eq_info['labour_norm']}**")
        st.divider()

        st.markdown("##### Pull from Anchor Portal  _(optional — auto-fills QTN & customer)_")
        anc_options = ["— type QTN manually —"] + [
            f"{a.get('quote_ref','')}  |  {a.get('client_name','')}  |  {a.get('project_description','')}"
            for a in anchor_qtns
        ]
        anc_sel = st.selectbox("Anchor Portal", anc_options, label_visibility="collapsed")
        if anc_sel != "— type QTN manually —":
            chosen = anchor_qtns[anc_options.index(anc_sel)-1]
            h["qtn_number"]    = chosen.get("quote_ref","")
            h["customer_name"] = chosen.get("client_name","")
            st.success(f"Auto-filled — QTN: **{h['qtn_number']}**  |  Customer: **{h['customer_name']}**")
        st.divider()

        st.markdown("##### Offer Details")
        c1,c2,c3 = st.columns(3)
        h["qtn_number"] = c1.text_input("Quotation Number  *", value=h["qtn_number"], placeholder="e.g. B&G/MAITHRI/2026/2922")
        h["revision"]   = c2.selectbox("Revision", ["R0","R1","R2","R3","R4","R5"],
                                        index=["R0","R1","R2","R3","R4","R5"].index(h.get("revision","R0")))
        h["status"]     = c3.selectbox("Status", ["Draft","Issued","Won","Lost","On Hold"],
                                        index=["Draft","Issued","Won","Lost","On Hold"].index(h.get("status","Draft")))
        st.divider()

        st.markdown("##### Customer")
        cust_opts = ["— select —"] + client_names
        cust_idx  = cust_opts.index(h["customer_name"]) if h["customer_name"] in cust_opts else 0
        sel_cust  = st.selectbox("Customer", cust_opts, index=cust_idx, label_visibility="collapsed")
        if sel_cust != "— select —":
            h["customer_name"] = sel_cust
            cd = next((c for c in clients if c["name"]==sel_cust), {})
            cc = st.columns(4)
            cc[0].caption(f"📍 {cd.get('address','—')}")
            cc[1].caption(f"🏷️ GSTIN: {cd.get('gstin','—')}")
            cc[2].caption(f"👤 {cd.get('contact_person','—')}")
            cc[3].caption(f"📞 {cd.get('phone','—')}")
        st.divider()

        st.markdown("##### Equipment Parameters")
        c1,c2 = st.columns(2)
        h["equipment_desc"] = c1.text_input("Description  (e.g. 2000 Ltrs SS316L Reactor)", value=h["equipment_desc"])
        h["tag_number"]     = c2.text_input("Tag Number  (e.g. R-505)", value=h["tag_number"])

        c1,c2,c3,c4,c5 = st.columns(5)
        h["capacity_ltrs"] = c1.number_input("Capacity (Ltrs)", value=float(h["capacity_ltrs"]), min_value=0.0, step=100.0)
        h["shell_dia_mm"]  = c2.number_input("Shell ID (mm)",   value=float(h["shell_dia_mm"]),  min_value=0.0, step=50.0)
        h["shell_ht_mm"]   = c3.number_input("Shell Ht (mm)",   value=float(h["shell_ht_mm"]),   min_value=0.0, step=100.0)
        h["shell_thk_mm"]  = c4.number_input("Shell Thk (mm)",  value=float(h["shell_thk_mm"]),  min_value=0.0, step=1.0)
        h["dish_thk_mm"]   = c5.number_input("Dish Thk (mm)",   value=float(h["dish_thk_mm"]),   min_value=0.0, step=1.0)

        g1,g2,g3 = st.columns(3)
        g1.metric("Shell Area (m²)",  f"{calc_shell_area(h['shell_dia_mm'],h['shell_ht_mm']):.3f}")
        g2.metric("Dish Area (m²)",   f"{calc_dish_area(h['shell_dia_mm']):.3f}")
        g3.metric("Shell Vol (Ltrs)", f"{calc_shell_volume_ltrs(h['shell_dia_mm'],h['shell_ht_mm']):.0f}")

        c1,c2 = st.columns(2)
        h["jacket_type"]   = c1.text_input("Jacket Type",   value=h["jacket_type"])
        h["agitator_type"] = c2.text_input("Agitator Type", value=h["agitator_type"])
        c1,c2,c3 = st.columns(3)
        h["design_code"]     = c1.text_input("Design Code",     value=h["design_code"])
        h["design_pressure"] = c2.text_input("Design Pressure", value=h["design_pressure"])
        h["design_temp"]     = c3.text_input("Design Temp",     value=h["design_temp"])
        c1,c2 = st.columns(2)
        h["moc_shell"]  = c1.text_input("MOC – Shell",  value=h["moc_shell"])
        h["moc_jacket"] = c2.text_input("MOC – Jacket", value=h["moc_jacket"])
        st.divider()

        st.markdown("##### Prepared By / Checked By")
        staff_list = [""]+st.session_state.master_data.get("staff",[])
        c1,c2 = st.columns(2)
        pb_idx = staff_list.index(h["prepared_by"]) if h["prepared_by"] in staff_list else 0
        cb_idx = staff_list.index(h["checked_by"])  if h["checked_by"]  in staff_list else 0
        h["prepared_by"] = c1.selectbox("Prepared By", staff_list, index=pb_idx)
        h["checked_by"]  = c2.selectbox("Checked By",  staff_list, index=cb_idx)
        h["notes"]       = st.text_area("Internal Notes", value=h["notes"], height=70)
        st.caption("✅ Done here? Go to **2️⃣ Plates & Parts** tab.")

    # ── F2: PLATES & PARTS ─────────────────────────────────────────────────────
    with f2:
        st.markdown("##### Add / Edit Fabricated Parts")
        st.caption("Select Part Type → only the required dimension inputs appear → click **Add Part** button.")

        edit_pidx    = st.session_state.get("edit_part_idx")
        editing_part = st.session_state.est_parts[edit_pidx] if (edit_pidx is not None and edit_pidx < len(st.session_state.est_parts)) else None

        with st.container(border=True):
            if editing_part:
                st.info(f"Editing row {edit_pidx+1}: **{editing_part.get('name','')}** — update values and click **Update Part**")

            rc1,rc2,rc3 = st.columns(3)
            pt_keys = list(PART_TYPES.keys())
            def_pt  = editing_part.get("part_type", pt_keys[0]) if editing_part else pt_keys[0]
            if def_pt not in pt_keys:
                def_pt = pt_keys[0]
            p_name  = rc1.text_input("Part Name", value=editing_part.get("name","") if editing_part else "", placeholder="e.g. Main Shell", key="pn")
            p_type  = rc2.selectbox("Part Type", pt_keys, index=pt_keys.index(def_pt), key="pt")
            p_group = rc3.selectbox("Group", all_groups,
                                    index=all_groups.index(editing_part.get("group","SHELL")) if editing_part and editing_part.get("group","SHELL") in all_groups else 0,
                                    key="pg")

            rc4,rc5,rc6 = st.columns(3)
            mat_list  = list(DENSITY.keys())
            def_mat   = editing_part.get("material","SS316L") if editing_part else "SS316L"
            p_material = rc4.selectbox("Material", mat_list, index=mat_list.index(def_mat) if def_mat in mat_list else 0, key="pm")
            p_code     = rc5.selectbox("RM Code (for rate)", plate_rm or ["—"],
                                       index=plate_rm.index(editing_part.get("item_code","")) if editing_part and editing_part.get("item_code","") in plate_rm else 0,
                                       key="pc")
            p_rate_ov  = rc6.number_input("Rate Override ₹/kg  (0 = use master)", value=0.0, min_value=0.0, key="pr")

            pt_info    = PART_TYPES[p_type]
            is_derived = pt_info.get("qty_derived", False)
            if is_derived:
                st.info("Qty is auto-calculated from geometry (shell height ÷ pitch). No manual entry needed.")
                p_qty = 1.0
            else:
                p_qty = st.number_input("Qty", value=float(editing_part.get("qty",1)) if editing_part else 1.0, min_value=1.0, step=1.0, key="pq")

            needed   = pt_info["fields"]
            dim_cols = st.columns(len(needed))
            dims     = {}
            for i,(field,label) in enumerate(needed):
                def_val = float(editing_part.get("dims",{}).get(field,0.0)) if editing_part else 0.0
                dims[field] = dim_cols[i].number_input(label, value=def_val, min_value=0.0, step=1.0, key=f"d_{p_type}_{field}")

            btn_c1,btn_c2 = st.columns([3,1])
            add_btn    = btn_c1.button("➕ Add Part" if not editing_part else "✅ Update Part", type="primary", use_container_width=True)
            cancel_btn = btn_c2.button("✖ Cancel", use_container_width=True) if editing_part else False

            if cancel_btn:
                st.session_state.edit_part_idx = None
                st.rerun()

            if add_btn:
                density = DENSITY.get(p_material, 8000)
                fn      = pt_info["fn"]
                rm      = rm_master.get(p_code, {})
                rate    = p_rate_ov if p_rate_ov > 0 else rm.get("rate",0)
                wt, total_wt, used_qty = calc_weight(fn, dims, density, p_qty)
                if wt == 0:
                    st.warning("⚠️ Weight is zero — please check all dimension inputs are filled correctly.")
                new_part = dict(
                    name=p_name, part_type=p_type, group=p_group,
                    material=p_material, item_code=p_code, dims=dims,
                    qty=used_qty, net_wt_kg=wt, total_wt_kg=total_wt,
                    rate=rate, amount=round(total_wt*rate, 2),
                )
                if editing_part is not None and edit_pidx is not None:
                    st.session_state.est_parts[edit_pidx] = new_part
                    st.session_state.edit_part_idx = None
                    st.success(f"✅ Updated: {p_name}")
                else:
                    st.session_state.est_parts.append(new_part)
                    st.success(f"✅ Added: {p_name}  |  {total_wt:.2f} kg  |  ₹{total_wt*rate:,.0f}")
                st.rerun()

        if st.session_state.est_parts:
            st.markdown("---")
            st.markdown("**Parts list — click ✏️ on any row to edit it**")
            for idx, p in enumerate(st.session_state.est_parts):
                c1,c2,c3,c4,c5,c6,c7,c8 = st.columns([3,2,1.5,1,1,1.5,2,0.7])
                c1.write(p.get("name",""))
                c2.write(p.get("part_type","")[:22])
                c3.write(p.get("group",""))
                c4.write(p.get("material",""))
                c5.write(f"{p.get('qty',1):.1f}")
                c6.write(f"{p.get('total_wt_kg',0):.1f} kg")
                c7.write(f"₹{p.get('amount',0):,.0f}")
                if c8.button("✏️", key=f"ep_{idx}", help=f"Edit {p.get('name','')}"):
                    st.session_state.edit_part_idx = idx
                    st.rerun()

            tot_wt  = sum(p.get("total_wt_kg",0) for p in st.session_state.est_parts)
            tot_amt = sum(p.get("amount",0) for p in st.session_state.est_parts)
            st.success(f"**Total — Weight: {tot_wt:,.1f} kg  |  Amount: ₹{tot_amt:,.0f}**")

            dc1,dc2 = st.columns([3,1])
            del_idx = dc1.number_input("Row number to delete", min_value=1, max_value=len(st.session_state.est_parts), value=1, step=1)
            if dc2.button("🗑️ Delete Row", use_container_width=True):
                removed = st.session_state.est_parts.pop(int(del_idx)-1)
                st.session_state.edit_part_idx = None
                st.rerun()
            if st.button("🗑️ Clear All Parts"):
                st.session_state.est_parts = []
                st.session_state.edit_part_idx = None
                st.rerun()

    # ── F3: PIPES & FLANGES ────────────────────────────────────────────────────
    with f3:
        st.markdown("##### Nozzle Pipes")
        with st.container(border=True):
            pc1,pc2,pc3,pc4,pc5 = st.columns(5)
            pp_name = pc1.text_input("Description", placeholder='e.g. 2" Nozzle', key="pp_name")
            pp_code = pc2.selectbox("Pipe Size", pipe_rm or ["—"], key="pp_code")
            pp_len  = pc3.number_input("Length (m)", value=0.2, min_value=0.0, step=0.1, key="pp_len")
            pp_qty  = pc4.number_input("Qty", value=1, min_value=1, step=1, key="pp_qty")
            pp_rate = pc5.number_input("Rate Override (0=master)", value=0.0, min_value=0.0, key="pp_rate")
            if pipe_rm:
                rm = rm_master.get(pp_code, {})
                st.caption(f"Selected: {rm.get('description','')} | {rm.get('unit_wt_kg_per_m',0)} kg/m | Rate: ₹{rm.get('rate',0)}/kg")
            if st.button("➕ Add Pipe", type="primary", key="add_pipe"):
                rm   = rm_master.get(pp_code, {})
                rate = pp_rate if pp_rate>0 else rm.get("rate",0)
                wpm  = rm.get("unit_wt_kg_per_m") or 0
                wt   = wpm * pp_len * 1.05 * pp_qty
                st.session_state.est_pipes.append(dict(
                    name=pp_name, item_code=pp_code, length_m=pp_len,
                    qty=pp_qty, wt_per_m=wpm, total_wt_kg=round(wt,3),
                    rate=rate, amount=round(wt*rate,2),
                ))
                st.rerun()
        if st.session_state.est_pipes:
            df = pd.DataFrame(st.session_state.est_pipes)[["name","item_code","length_m","qty","total_wt_kg","rate","amount"]]
            df.columns = ["Description","Code","Length(m)","Qty","Wt(kg)","Rate","Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"Total Pipes: ₹{sum(p['amount'] for p in st.session_state.est_pipes):,.0f}")
            if st.button("🗑️ Clear Pipes"): st.session_state.est_pipes=[]; st.rerun()

        st.divider()
        st.markdown("##### Flanges & Fittings")
        with st.container(border=True):
            fl1,fl2,fl3,fl4 = st.columns(4)
            fl_name = fl1.text_input("Description", placeholder='e.g. 4" #150 Flange', key="fl_name")
            fl_code = fl2.selectbox("Flange Size", flg_rm or ["—"], key="fl_code")
            fl_qty  = fl3.number_input("Qty", value=1, min_value=1, step=1, key="fl_qty")
            fl_rate = fl4.number_input("Rate Override (0=master)", value=0.0, min_value=0.0, key="fl_rate")
            if st.button("➕ Add Flange", type="primary", key="add_flange"):
                rm   = rm_master.get(fl_code, {})
                rate = fl_rate if fl_rate>0 else rm.get("rate",0)
                wt   = ((rm.get("unit_wt_kg_per_m") or 0)*1.15)*fl_qty
                st.session_state.est_flanges.append(dict(
                    name=fl_name, item_code=fl_code, qty=fl_qty,
                    total_wt_kg=round(wt,3), rate=rate, amount=round(wt*rate,2),
                ))
                st.rerun()
        if st.session_state.est_flanges:
            df = pd.DataFrame(st.session_state.est_flanges)[["name","item_code","qty","total_wt_kg","rate","amount"]]
            df.columns = ["Description","Code","Qty","Wt(kg)","Rate","Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"Total Flanges: ₹{sum(p['amount'] for p in st.session_state.est_flanges):,.0f}")
            if st.button("🗑️ Clear Flanges"): st.session_state.est_flanges=[]; st.rerun()

    # ── F4: BO & OH ────────────────────────────────────────────────────────────
    with f4:
        st.markdown("##### Bought-Out Items  _(Motor, Gearbox, Seal, Fasteners, Insulation, etc.)_")
        with st.container(border=True):
            b1,b2,b3,b4,b5 = st.columns(5)
            bo_desc  = b1.text_input("Description", placeholder="e.g. 7.5HP Motor", key="bo_d")
            bo_code  = b2.selectbox("BO Code", bo_rm or ["—"], key="bo_c")
            bo_qty   = b3.number_input("Qty", value=1, min_value=1, step=1, key="bo_q")
            bo_rate  = b4.number_input("Rate Override (0=master)", value=0.0, min_value=0.0, key="bo_r")
            bo_group = b5.selectbox("Group", ["BO","FASTENERS","INSULATION","OTHER"], key="bo_g")
            if bo_rm:
                rm = rm_master.get(bo_code, {})
                st.caption(f"Selected: {rm.get('description','')} | Rate: ₹{rm.get('rate',0):,.0f} | UOM: {rm.get('uom','')}")
            if st.button("➕ Add BO Item", type="primary", key="add_bo"):
                rm   = rm_master.get(bo_code, {})
                rate = bo_rate if bo_rate>0 else rm.get("rate",0)
                st.session_state.est_bo.append(dict(
                    name=bo_desc or rm.get("description",""), item_code=bo_code,
                    qty=bo_qty, rate=rate, amount=round(rate*bo_qty,2), group=bo_group,
                ))
                st.rerun()
        if st.session_state.est_bo:
            df = pd.DataFrame(st.session_state.est_bo)[["name","item_code","qty","rate","amount","group"]]
            df.columns = ["Description","Code","Qty","Rate","Amount(₹)","Group"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"Total Bought-Out: ₹{sum(b['amount'] for b in st.session_state.est_bo):,.0f}")
            if st.button("🗑️ Clear BO"): st.session_state.est_bo=[]; st.rerun()

        st.divider()
        st.markdown("##### Overheads  _(Labour, Consumables %, Testing, Packing, Transport, etc.)_")
        with st.container(border=True):
            o1,o2,o3,o4 = st.columns(4)
            oh_sel = o1.selectbox("OH Code", oh_codes or ["—"], key="oh_sel")
            oh_qty = o2.number_input("Qty / Hours / Area (m²)", value=1.0, min_value=0.0, step=1.0, key="oh_q")
            oh_rov = o3.number_input("Rate Override (0=master)", value=0.0, min_value=0.0, key="oh_r")
            oh_dov = o4.text_input("Description override  (optional)", key="oh_d")
            oh_inf = oh_master.get(oh_sel, {})
            st.caption(f"Selected: **{oh_inf.get('description','')}** | Type: {oh_inf.get('oh_type','')} | UOM: {oh_inf.get('uom','')} | Master Rate: ₹{oh_inf.get('rate',0):,.0f}")
            if st.button("➕ Add Overhead", type="primary", key="add_oh"):
                rate = oh_rov if oh_rov>0 else oh_inf.get("rate",0)
                uom  = oh_inf.get("uom","")
                desc = oh_dov or oh_inf.get("description","")
                if uom == "%":
                    base = (sum(p.get("amount",0) for p in st.session_state.est_parts) +
                            sum(p.get("amount",0) for p in st.session_state.est_pipes) +
                            sum(p.get("amount",0) for p in st.session_state.est_flanges))
                    amount = base * rate / 100
                else:
                    amount = rate * oh_qty
                st.session_state.est_oh.append(dict(
                    oh_code=oh_sel, description=desc, oh_type=oh_inf.get("oh_type",""),
                    uom=uom, qty=oh_qty, rate=rate, amount=round(amount,2),
                ))
                st.rerun()
        if st.session_state.est_oh:
            df = pd.DataFrame(st.session_state.est_oh)[["description","oh_type","uom","qty","rate","amount"]]
            df.columns = ["Description","Type","UOM","Qty","Rate","Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"Total OH: ₹{sum(o['amount'] for o in st.session_state.est_oh):,.0f}")
            if st.button("🗑️ Clear OH"): st.session_state.est_oh=[]; st.rerun()

    # ── F5: SUMMARY & SAVE ─────────────────────────────────────────────────────
    with f5:
        eq_info = EQUIPMENT_TYPES.get(h["equipment_type"],{})
        lo,hi   = eq_info.get("margin_hint",(10,18))
        st.info(f"Suggested margin for **{h['equipment_type']}**: {lo}–{hi}%  |  Labour: **{eq_info.get('labour_norm','Medium')}**")

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
            h["packing_amt"], h["freight_amt"], h["gst_pct"], h["engg_design_amt"],
        )

        left,right = st.columns([3,2])
        with left:
            st.markdown("**Cost Breakup**")
            cost_df = pd.DataFrame([
                ("Plates & Parts",          T["tot_plates"]),
                ("Pipes",                   T["tot_pipes"]),
                ("Flanges",                 T["tot_flanges"]),
                ("Bought-Out Items",        T["tot_bo"]),
                ("Labour",                  T["tot_lab"]),
                ("Consumables & Other OH",  T["tot_cons"]+T["tot_other"]),
                ("Engg & ASME Design",      T["engg_design"]),
                ("Contingency",             T["cont_amt"]),
                ("Profit",                  T["profit_amt"]),
                ("Packing & Freight",       T["packing"]+T["freight"]),
                ("Ex-Works Price",          T["ex_works"]),
                ("GST",                     T["gst_amt"]),
                ("FOR Price",               T["for_price"]),
            ], columns=["Component","Amount (₹)"])
            cost_df["Amount (₹)"] = cost_df["Amount (₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(cost_df, use_container_width=True, hide_index=True)

        with right:
            st.markdown("**Margin Health**")
            for label,val,lo_t,hi_t in [
                ("RM %",    T["rm_pct"],          45, 60),
                ("Labour %",T["lab_pct"],          15, 25),
                ("OH %",    T["oh_pct"],            8, 15),
                ("Profit %",T["profit_pct_actual"],12, 20),
            ]:
                icon = "✅" if lo_t<=val<=hi_t else "⚠️"
                st.write(f"{icon} **{label}** {val:.1f}%  _(target {lo_t}–{hi_t}%)_")
            for iss in margin_issues(T):
                st.warning(iss)
            if not margin_issues(T):
                st.success("All margins healthy!")
            st.markdown("**What-If Price Table**")
            st.dataframe(pd.DataFrame([{
                "Margin":f"{m}%",
                "Ex-Works (₹)":f"₹{(T['cbm']*(1+m/100)+T['packing']+T['freight']):,.0f}",
            } for m in [8,10,12,15,18,20]]), hide_index=True, use_container_width=True)

        st.divider()
        k1,k2,k3,k4,k5 = st.columns(5)
        k1.metric("Raw Material",f"₹{T['tot_rm']:,.0f}")
        k2.metric("Total Mfg",   f"₹{T['tot_mfg']:,.0f}")
        k3.metric("Ex-Works",    f"₹{T['ex_works']:,.0f}")
        k4.metric("GST",         f"₹{T['gst_amt']:,.0f}")
        k5.metric("FOR Price",   f"₹{T['for_price']:,.0f}")
        st.divider()

        if not h["qtn_number"]:
            st.error("⚠️ Quotation Number is required. Please fill it in Tab 1️⃣ Header.")

        b1,b2,b3 = st.columns(3)
        if b1.button("💾 Save to Supabase", type="primary", use_container_width=True, disabled=not h["qtn_number"]):
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
                ok  = sb_update("estimations", row, "id", edit_id)
                msg = f"Updated {h['qtn_number']}"
            else:
                row["created_at"] = datetime.now().isoformat()
                ok  = sb_insert("estimations", row)
                msg = f"Saved {h['qtn_number']}"
            if ok:
                st.success(f"✅ {msg}")
                st.cache_data.clear()
                _reset_form()
                st.rerun()

        if b2.button("🔄 Reset / New", use_container_width=True):
            _reset_form(); st.rerun()

        cust_data = next((c for c in clients if c["name"]==h.get("customer_name","")), {})
        b3.download_button(
            "📄 Download Quotation DOCX",
            generate_docx(h, cust_data, T),
            file_name=f"{h.get('qtn_number','QTN')}_{h.get('revision','R0')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

# ══════════════════════════════════════════════════════════════════════════════
# TAB: SIMILAR EQUIPMENT
# ══════════════════════════════════════════════════════════════════════════════
with TAB_SIMILAR:
    st.subheader("🔍 Similar Equipment — Price Benchmark")
    st.caption("Find past estimations by type and capacity range to benchmark your price.")
    sc1,sc2,sc3 = st.columns(3)
    s_equip  = sc1.selectbox("Equipment Type", ["All"]+EQUIPMENT_NAMES, key="sim_eq")
    s_cap_lo = sc2.number_input("Capacity from (Ltrs)", value=0.0, min_value=0.0, key="sim_lo")
    s_cap_hi = sc3.number_input("Capacity to (Ltrs)",   value=99999.0, min_value=0.0, key="sim_hi")
    s_cust   = st.text_input("Customer contains (optional)", key="sim_cu")

    results = []
    for est in load_all_estimations():
        if s_equip!="All" and est.get("equipment_type")!=s_equip: continue
        cap = float(est.get("capacity_ltrs") or 0)
        if not (s_cap_lo<=cap<=s_cap_hi): continue
        if s_cust and s_cust.lower() not in (est.get("customer_name","") or "").lower(): continue
        T = calc_totals(
            json.loads(est.get("parts_json") or "[]"), json.loads(est.get("pipes_json") or "[]"),
            json.loads(est.get("flanges_json") or "[]"), json.loads(est.get("bo_json") or "[]"),
            json.loads(est.get("oh_json") or "[]"),
            float(est.get("profit_margin_pct") or 10), float(est.get("contingency_pct") or 0),
            float(est.get("packing_amt") or 0), float(est.get("freight_amt") or 0),
            float(est.get("gst_pct") or 18), float(est.get("engg_design_amt") or 0),
        )
        results.append({
            "QTN":      est.get("qtn_number",""), "Customer": est.get("customer_name",""),
            "Equipment":est.get("equipment_desc",""), "Type": est.get("equipment_type",""),
            "Cap (L)":  cap, "Status": est.get("status",""),
            "Ex-Works": f"₹{T['ex_works']:,.0f}", "FOR Price": f"₹{T['for_price']:,.0f}",
            "Margin %": f"{T['profit_pct_actual']:.1f}%", "Date": str(est.get("updated_at",""))[:10],
        })
    if results:
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
        st.caption(f"{len(results)} estimations found.")
    else:
        st.info("No matching estimations. Adjust filters above.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: MASTERS
# ══════════════════════════════════════════════════════════════════════════════
with TAB_MASTERS:
    mt1,mt2 = st.tabs(["🔩 RM & BO Master","⚙️ OH Master"])

    with mt1:
        st.subheader("Raw Material & Bought-Out Master")
        df_rm = pd.DataFrame(sb_fetch("est_rm_master", order="category"))
        if not df_rm.empty:
            st.dataframe(df_rm[["ref_code","description","category","material","spec","size","uom","rate","unit_wt_kg_per_m","active"]],
                         use_container_width=True, hide_index=True)
        with st.expander("➕ Add / Update Item"):
            with st.form("rm_add_form", clear_on_submit=True):
                c1,c2 = st.columns(2)
                rc=c1.text_input("Ref Code (unique)"); desc=c2.text_input("Description")
                c1,c2,c3 = st.columns(3)
                cat=c1.selectbox("Category",["RM","BO"]); rmt=c2.text_input("Type"); mat=c3.text_input("Material")
                c1,c2,c3,c4 = st.columns(4)
                spec=c1.text_input("Spec"); sz=c2.text_input("Size")
                uom=c3.selectbox("UOM",["Kg","Nos","Set","LS","Sq.M"]); rate=c4.number_input("Rate ₹",min_value=0.0)
                uwt=st.number_input("Unit Wt kg/m (pipes only)",min_value=0.0)
                if st.form_submit_button("Save"):
                    if sb_insert("est_rm_master",dict(ref_code=rc,description=desc,category=cat,rm_type=rmt,
                                                      material=mat,spec=spec,size=sz,uom=uom,rate=rate,
                                                      unit_wt_kg_per_m=uwt if uwt>0 else None,active="Yes")):
                        st.cache_data.clear(); st.success(f"Saved {rc}"); st.rerun()

    with mt2:
        st.subheader("Overhead Master")
        df_oh = pd.DataFrame(sb_fetch("est_oh_master", order="oh_type"))
        if not df_oh.empty:
            st.dataframe(df_oh[["oh_code","description","oh_type","uom","rate","source"]],
                         use_container_width=True, hide_index=True)
        with st.expander("➕ Add / Update OH"):
            with st.form("oh_add_form", clear_on_submit=True):
                c1,c2,c3,c4,c5 = st.columns(5)
                oc=c1.text_input("OH Code"); od=c2.text_input("Description")
                ot=c3.selectbox("Type",["LABOUR","LABOUR_BUFF","CONSUMABLES","TESTING","DOCS","PACKING","TRANSPORT","MISC","ELECTRO_POLISH"])
                ou=c4.selectbox("UOM",["Hr","Sq.M","%","LS"]); or_=c5.number_input("Rate",min_value=0.0)
                if st.form_submit_button("Save"):
                    if sb_insert("est_oh_master",dict(oh_code=oc,description=od,oh_type=ot,uom=ou,rate=or_,source="Internal")):
                        st.cache_data.clear(); st.success(f"Saved {oc}"); st.rerun()
