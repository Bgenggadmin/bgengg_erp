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
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_OK = True
except ImportError:
    OPENPYXL_OK = False

st.set_page_config(
    page_title="Estimation & Costing | BGEngg ERP",
    page_icon="📐",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────────────
# COMPANY CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
BG_NAME    = "B&G Engineering Industries"
BG_TAGLINE = "Evaporation | Mixing | Drying"
BG_GSTIN   = "36AAIFB3357M1Z5"
BG_PAN     = "AAIFB3357M"
BG_ADDRESS = "Plot No.207/B & 208/A, Phase-III Industrial Park, Pashamylaram, Patancheru Mandal, Sangareddy Dist, Hyderabad – 502307"
BG_PHONE   = "+91 7995565800 / +91 9154971801"
BG_EMAIL   = "info@bgengineeringind.com"
BG_WEB     = "www.bgengineeringind.com"

conn = st.connection("supabase", type=SupabaseConnection)
if "master_data" not in st.session_state:
    st.session_state.master_data = fetch_all_master_data(conn)

# ─────────────────────────────────────────────────────────────────────────────
# LOGO — fetch from Supabase storage bucket once per session
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def _fetch_logo_bytes():
    """
    Fetch B&G logo from Supabase storage bucket 'progress-photos'.
    Returns raw bytes or None if not found.
    Try common filenames — change LOGO_FILENAME if yours is different.
    """
    BUCKET = "progress-photos"
    LOGO_FILE = "logo.png"
    try:
        data = conn.client.storage.from_(BUCKET).download(LOGO_FILE)
        if data:
            return data, LOGO_FILE
    except Exception:
        pass
    return None, None

_LOGO_BYTES, _LOGO_FNAME = _fetch_logo_bytes()

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
DENSITY = {"SS316L": 8000, "SS304": 8000, "MS": 7850, "EN8": 7800, "Ti": 4500, "C22": 8690, "Hastelloy": 8890}

def _m(mm):
    return mm / 1000.0

def geom_cylindrical_shell(id_mm, ht_mm, thk_mm, density=8000, scrap=0.05):
    return PI * _m(id_mm) * _m(ht_mm) * _m(thk_mm) * density * (1 + scrap)

def geom_dish_end(shell_id_mm, thk_mm, density=8000, scrap=0.15):
    r = _m(shell_id_mm * 1.167) / 2
    return 1.09 * PI * r * r * _m(thk_mm) * density * (1 + scrap)

def geom_annular_plate(od_mm, id_mm, thk_mm, density=8000, scrap=0.05):
    return (PI / 4.0) * (_m(od_mm) ** 2 - _m(id_mm) ** 2) * _m(thk_mm) * density * (1 + scrap)

def geom_solid_round(dia_mm, length_mm, density=8000, scrap=0.15):
    return (PI / 4.0) * _m(dia_mm) ** 2 * _m(length_mm) * density * (1 + scrap)

def geom_flat_rect(w_mm, h_mm, thk_mm, density=8000, scrap=0.05):
    return _m(w_mm) * _m(h_mm) * _m(thk_mm) * density * (1 + scrap)

def geom_stiffener_ring(shell_id_mm, shell_thk_mm, shell_ht_mm,
                        pitch_mm, bar_w_mm, bar_thk_mm, density=8000, scrap=0.05):
    shell_od_mm = shell_id_mm + 2.0 * shell_thk_mm
    circ_m = PI * _m(shell_od_mm)
    n_rings = _m(shell_ht_mm) / _m(pitch_mm) if pitch_mm > 0 else 0.0
    wt_per_ring = circ_m * _m(bar_w_mm) * _m(bar_thk_mm) * density * (1 + scrap)
    return wt_per_ring, n_rings, wt_per_ring * n_rings

def geom_cone(large_id_mm, small_id_mm, ht_mm, thk_mm, density=8000, scrap=0.05):
    R1 = _m(large_id_mm) / 2
    R2 = _m(small_id_mm) / 2
    slant = math.sqrt(_m(ht_mm) ** 2 + (R1 - R2) ** 2)
    return PI * (R1 + R2) * slant * _m(thk_mm) * density * (1 + scrap)

def geom_rect_plate(length_mm, width_mm, thk_mm, density=8000, scrap=0.05):
    return _m(length_mm) * _m(width_mm) * _m(thk_mm) * density * (1 + scrap)

def geom_tube_bundle(tube_od_mm, tube_thk_mm, tube_length_mm, n_tubes, density=8000, scrap=0.05):
    mid_r = (_m(tube_od_mm) / 2) - (_m(tube_thk_mm) / 2)
    return PI * 2 * mid_r * _m(tube_length_mm) * _m(tube_thk_mm) * density * n_tubes * (1 + scrap)

PART_TYPES = {
    "Cylindrical shell": {
        "fields": [("id_mm", "Shell ID (mm)"), ("ht_mm", "Height (mm)"), ("thk_mm", "Thickness (mm)")],
        "fn": "shell",
    },
    "Dish end (torispherical)": {
        "fields": [("shell_id_mm", "Shell ID (mm)"), ("thk_mm", "Thickness (mm)")],
        "fn": "dish",
    },
    "Annular plate / flange": {
        "fields": [("od_mm", "Outer Dia OD (mm)"), ("id_mm", "Inner Dia ID (mm)"), ("thk_mm", "Thickness (mm)")],
        "fn": "annular",
    },
    "Solid round (shaft / bush)": {
        "fields": [("dia_mm", "Diameter (mm)"), ("length_mm", "Length (mm)")],
        "fn": "solid",
    },
    "Flat rectangle (blade / pad / gusset)": {
        "fields": [("w_mm", "Width (mm)"), ("h_mm", "Height (mm)"), ("thk_mm", "Thickness (mm)")],
        "fn": "flat",
    },
    "Stiffener rings (flat bar on shell OD)": {
        "fields": [
            ("shell_id_mm", "Shell ID (mm)"), ("shell_thk_mm", "Shell Thickness (mm)"),
            ("shell_ht_mm", "Shell Height (mm)"), ("pitch_mm", "Ring Pitch (mm)"),
            ("bar_w_mm", "Bar Width (mm)"), ("thk_mm", "Bar Thickness (mm)"),
        ],
        "fn": "stiff",
        "qty_derived": True,
    },
    "Cone / reducer": {
        "fields": [
            ("large_id_mm", "Large End ID (mm)"), ("small_id_mm", "Small End ID (mm)"),
            ("ht_mm", "Height (mm)"), ("thk_mm", "Thickness (mm)"),
        ],
        "fn": "cone",
    },
    "Rectangular plate": {
        "fields": [("length_mm", "Length (mm)"), ("width_mm", "Width (mm)"), ("thk_mm", "Thickness (mm)")],
        "fn": "rect",
    },
    "Tube bundle": {
        "fields": [
            ("tube_od_mm", "Tube OD (mm)"), ("tube_thk_mm", "Tube Thickness (mm)"),
            ("tube_length_mm", "Tube Length (mm)"), ("n_tubes", "Number of Tubes"),
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
                d.get("shell_id_mm", 0), d.get("shell_thk_mm", 0), d.get("shell_ht_mm", 0),
                d.get("pitch_mm", 100), d.get("bar_w_mm", 0), d.get("thk_mm", 0), density,
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
# FABRICATION SERVICES ENGINE
# ─────────────────────────────────────────────────────────────────────────────
FAB_DEFAULTS = {
    "cutting_pct_on_plates": 2.0,
    "rolling_rate_per_m2": 800.0,
    "tig_weld_rate_per_m": 1200.0,
    "arc_weld_rate_per_m": 600.0,
    "int_grind_rate_per_m2": 350.0,
    "ext_buff_rate_per_m2": 250.0,
    "ep_rate_per_m2": 0.0,
    "hydro_test_lumpsum": 5000.0,
    "dp_test_rate_per_m2": 150.0,
    "assembly_fitting_hrs": 40.0,
    "assembly_rate_per_hr": 350.0,
    "qa_doc_lumpsum": 8000.0,
}

def calc_weld_metres(shell_id_mm, shell_ht_mm, n_nozzles=8, avg_nozzle_od_mm=100,
                     n_dish_ends=2, has_jacket=True, has_agitator=True):
    id_m = _m(shell_id_mm)
    ht_m = _m(shell_ht_mm)
    long_weld = ht_m
    n_courses = max(1, round(ht_m / 1.5))
    circ_weld = PI * id_m * (n_dish_ends + max(0, n_courses - 1))
    nozzle_weld = PI * _m(avg_nozzle_od_mm) * n_nozzles
    jacket_weld = PI * (id_m + 0.02) * 2.0 if has_jacket else 0.0
    agit_weld = PI * 0.25 * 2.0 if has_agitator else 0.0
    return round(long_weld + circ_weld + nozzle_weld + jacket_weld + agit_weld, 2)

def calc_surface_areas(shell_id_mm, shell_ht_mm, n_dish_ends=2):
    id_m = _m(shell_id_mm)
    ht_m = _m(shell_ht_mm)
    shell_area = PI * id_m * ht_m
    dish_area_each = 1.09 * PI * (_m(shell_id_mm * 1.167) / 2) ** 2
    dish_area_total = dish_area_each * n_dish_ends
    internal_area = shell_area + dish_area_total
    external_area = internal_area * 1.05
    return round(shell_area, 3), round(dish_area_total, 3), round(internal_area, 3), round(external_area, 3)

def auto_fab_services(h, fab_rates, parts):
    lines = []
    dia = float(h.get("shell_dia_mm", 0))
    ht = float(h.get("shell_ht_mm", 0))
    has_j = bool(h.get("jacket_type", ""))
    has_a = bool(h.get("agitator_type", ""))
    moc = h.get("moc_shell", "SS316L")
    if dia <= 0 or ht <= 0:
        return []
    shell_a, dish_a, int_a, ext_a = calc_surface_areas(dia, ht)
    weld_m = calc_weld_metres(dia, ht, has_jacket=has_j, has_agitator=has_a)
    plate_rm = sum(p.get("amount", 0) for p in parts)

    cr = fab_rates.get("cutting_pct_on_plates", FAB_DEFAULTS["cutting_pct_on_plates"])
    lines.append({"service": "Plate Cutting & Profiling", "basis": f"{cr}% on plate RM ₹{plate_rm:,.0f}", "qty": 1, "uom": "LS", "rate": plate_rm * cr / 100, "amount": round(plate_rm * cr / 100, 2)})

    rr = fab_rates.get("rolling_rate_per_m2", FAB_DEFAULTS["rolling_rate_per_m2"])
    lines.append({"service": "Plate Rolling / Shell Forming", "basis": f"Shell area {shell_a:.3f} m² × ₹{rr}/m²", "qty": round(shell_a, 3), "uom": "m²", "rate": rr, "amount": round(shell_a * rr, 2)})

    if moc in ("SS316L", "Ti", "C22", "Hastelloy"):
        wr = fab_rates.get("tig_weld_rate_per_m", FAB_DEFAULTS["tig_weld_rate_per_m"])
        wl = "TIG Welding (SS316L)"
    else:
        wr = fab_rates.get("arc_weld_rate_per_m", FAB_DEFAULTS["arc_weld_rate_per_m"])
        wl = "ARC / MIG Welding"
    lines.append({"service": wl, "basis": f"Est. weld {weld_m:.2f} m × ₹{wr}/m", "qty": weld_m, "uom": "m", "rate": wr, "amount": round(weld_m * wr, 2)})

    gr = fab_rates.get("int_grind_rate_per_m2", FAB_DEFAULTS["int_grind_rate_per_m2"])
    lines.append({"service": "Internal Grinding & Buffing (Ra 0.8)", "basis": f"Internal area {int_a:.3f} m² × ₹{gr}/m²", "qty": round(int_a, 3), "uom": "m²", "rate": gr, "amount": round(int_a * gr, 2)})

    er = fab_rates.get("ext_buff_rate_per_m2", FAB_DEFAULTS["ext_buff_rate_per_m2"])
    lines.append({"service": "External Buffing & Finishing", "basis": f"External area {ext_a:.3f} m² × ₹{er}/m²", "qty": round(ext_a, 3), "uom": "m²", "rate": er, "amount": round(ext_a * er, 2)})

    ah = fab_rates.get("assembly_fitting_hrs", FAB_DEFAULTS["assembly_fitting_hrs"])
    ar = fab_rates.get("assembly_rate_per_hr", FAB_DEFAULTS["assembly_rate_per_hr"])
    lines.append({"service": "Assembly, Fitting & Erection", "basis": f"{ah} hrs × ₹{ar}/hr", "qty": ah, "uom": "Hr", "rate": ar, "amount": round(ah * ar, 2)})

    hl = fab_rates.get("hydro_test_lumpsum", FAB_DEFAULTS["hydro_test_lumpsum"])
    lines.append({"service": "Hydrostatic Pressure Testing", "basis": "Lumpsum per ASME", "qty": 1, "uom": "LS", "rate": hl, "amount": round(hl, 2)})

    dr = fab_rates.get("dp_test_rate_per_m2", FAB_DEFAULTS["dp_test_rate_per_m2"])
    lines.append({"service": "Dye Penetration (DP) Testing", "basis": f"Area {ext_a:.3f} m² × ₹{dr}/m²", "qty": round(ext_a, 3), "uom": "m²", "rate": dr, "amount": round(ext_a * dr, 2)})

    ql = fab_rates.get("qa_doc_lumpsum", FAB_DEFAULTS["qa_doc_lumpsum"])
    lines.append({"service": "QA Dossier, MTC, Test Reports & Documentation", "basis": "Lumpsum", "qty": 1, "uom": "LS", "rate": ql, "amount": round(ql, 2)})

    epr = fab_rates.get("ep_rate_per_m2", 0)
    if epr > 0:
        lines.append({"service": "Electropolishing (Ra 0.4)", "basis": f"Internal area {int_a:.3f} m² × ₹{epr}/m²", "qty": round(int_a, 3), "uom": "m²", "rate": epr, "amount": round(int_a * epr, 2)})

    return lines

# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT TYPES
# ─────────────────────────────────────────────────────────────────────────────
EQUIPMENT_TYPES = {
    "SSR — Stainless Steel Reactor":        {"icon": "⚗️",  "category": "Reactor",        "margin_hint": (12, 18), "labour_norm": "High",      "description": "SS316L reactor with jacket, agitator, mechanical seal"},
    "RCVD — Rotary Cone Vacuum Dryer":      {"icon": "🌀",  "category": "Dryer",          "margin_hint": (14, 20), "labour_norm": "High",      "description": "Rotary cone vacuum dryer — jacketed, vacuum operation, integrated condenser"},
    "RD — Receiver / Decanter":            {"icon": "🧪",  "category": "Vessel",         "margin_hint": (10, 15), "labour_norm": "Medium",    "description": "SS316L receiver cum decanter vessel, no agitator"},
    "ANFD — Agitated Nutsche Filter Dryer": {"icon": "🔩",  "category": "Filter",         "margin_hint": (14, 20), "labour_norm": "Very High", "description": "ANFD with filter plate, agitator, jacket"},
    "VST — Vertical Storage Tank":          {"icon": "🛢️",  "category": "Storage",        "margin_hint": (10, 15), "labour_norm": "Low",       "description": "Plain vertical storage tank"},
    "HST — Horizontal Storage Tank":        {"icon": "🛢️",  "category": "Storage",        "margin_hint": (10, 15), "labour_norm": "Low",       "description": "Horizontal tank with saddle supports"},
    "PNF — Plain Nutsche Filter":           {"icon": "🔲",  "category": "Filter",         "margin_hint": (10, 15), "labour_norm": "Medium",    "description": "Plain nutsche filter, no agitator"},
    "Leaf Filter":                          {"icon": "🍃",  "category": "Filter",         "margin_hint": (12, 18), "labour_norm": "High",      "description": "Leaf filter vessel with filter leaves"},
    "Condenser":                            {"icon": "❄️",  "category": "Heat Exchanger", "margin_hint": (12, 18), "labour_norm": "High",      "description": "Shell and tube condenser"},
    "Reboiler":                             {"icon": "♨️",  "category": "Heat Exchanger", "margin_hint": (12, 18), "labour_norm": "High",      "description": "Kettle / thermosyphon reboiler"},
    "Tray Dryer":                           {"icon": "📦",  "category": "Dryer",          "margin_hint": (14, 20), "labour_norm": "High",      "description": "SS316L tray dryer with trays"},
    "Octagonal Blender":                    {"icon": "🔷",  "category": "Mixer",          "margin_hint": (15, 22), "labour_norm": "Very High", "description": "Octagonal blender / V-blender"},
    "Multi Miller":                         {"icon": "⚙️",  "category": "Powder",         "margin_hint": (15, 22), "labour_norm": "Very High", "description": "Multi mill / sifter"},
    "Distillation Column":                  {"icon": "🏛️",  "category": "Column",         "margin_hint": (14, 20), "labour_norm": "High",      "description": "Distillation column with trays or packing"},
    "ATFD — Agitated Thin Film Dryer":      {"icon": "🌀",  "category": "Dryer",          "margin_hint": (18, 25), "labour_norm": "Very High", "description": "ATFD / thin film evaporator"},
    "MEE — Multiple Effect Evaporator":     {"icon": "💧",  "category": "Evaporator",     "margin_hint": (16, 22), "labour_norm": "Very High", "description": "Multiple effect evaporator package"},
    "Rectangular Tank":                     {"icon": "📐",  "category": "Storage",        "margin_hint": (10, 15), "labour_norm": "Low",       "description": "Rectangular / sump tank"},
    "Skid / Package":                       {"icon": "🏗️",  "category": "Package",        "margin_hint": (14, 20), "labour_norm": "High",      "description": "Multi-equipment skid package"},
    "Custom Equipment":                     {"icon": "🔧",  "category": "Custom",         "margin_hint": (10, 20), "labour_norm": "Medium",    "description": "User-defined — all fields manual"},
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

def calc_totals(parts, pipes, flanges, fab_services, bo_items, oh_items,
                profit_pct, contingency_pct, packing, freight, gst_pct, engg_design):
    tot_plates  = sum(p.get("amount", 0) for p in parts)
    tot_pipes   = sum(p.get("amount", 0) for p in pipes)
    tot_flanges = sum(p.get("amount", 0) for p in flanges)
    tot_rm      = tot_plates + tot_pipes + tot_flanges
    tot_fab     = sum(f.get("amount", 0) for f in fab_services)
    tot_bo      = sum(p.get("amount", 0) for p in bo_items)
    tot_lab     = sum(o.get("amount", 0) for o in oh_items if o.get("oh_type") in ("LABOUR", "LABOUR_BUFF"))
    tot_cons    = sum(o.get("amount", 0) for o in oh_items if o.get("oh_type") == "CONSUMABLES")
    tot_other   = sum(o.get("amount", 0) for o in oh_items if o.get("oh_type") not in ("LABOUR", "LABOUR_BUFF", "CONSUMABLES"))
    tot_oh      = tot_lab + tot_cons + tot_other
    tot_mfg     = tot_rm + tot_fab + tot_bo + tot_oh + engg_design
    cont_amt    = tot_mfg * contingency_pct / 100
    cbm         = tot_mfg + cont_amt
    profit_amt  = cbm * profit_pct / 100
    ex_works    = cbm + profit_amt + packing + freight
    gst_amt     = ex_works * gst_pct / 100
    for_price   = ex_works + gst_amt
    safe        = ex_works if ex_works else 1
    return dict(
        tot_plates=tot_plates, tot_pipes=tot_pipes, tot_flanges=tot_flanges,
        tot_rm=tot_rm, tot_fab=tot_fab, tot_bo=tot_bo, tot_lab=tot_lab,
        tot_cons=tot_cons, tot_other=tot_other, tot_oh=tot_oh,
        engg_design=engg_design, tot_mfg=tot_mfg, cont_amt=cont_amt,
        cbm=cbm, profit_amt=profit_amt, packing=packing, freight=freight,
        ex_works=ex_works, gst_amt=gst_amt, for_price=for_price,
        rm_pct=tot_rm / safe * 100, fab_pct=tot_fab / safe * 100,
        lab_pct=tot_lab / safe * 100, oh_pct=(tot_cons + tot_other) / safe * 100,
        profit_pct_actual=profit_amt / safe * 100,
    )

def margin_issues(t):
    out = []
    if not (45 <= t["rm_pct"]  <= 60): out.append(f"RM {t['rm_pct']:.1f}% — target 45–60%")
    if not (15 <= t["fab_pct"] <= 25): out.append(f"Fabrication {t['fab_pct']:.1f}% — target 15–25%")
    if not (8  <= t["oh_pct"]  <= 15): out.append(f"OH {t['oh_pct']:.1f}% — target 8–15%")
    if t["profit_pct_actual"] < 12:    out.append(f"Profit {t['profit_pct_actual']:.1f}% — min 12%")
    return out

# ─────────────────────────────────────────────────────────────────────────────
# DOCX GENERATOR
# ─────────────────────────────────────────────────────────────────────────────
def _shd(cell, hex_color):
    s = OxmlElement("w:shd")
    s.set(qn("w:val"), "clear"); s.set(qn("w:color"), "auto"); s.set(qn("w:fill"), hex_color)
    cell._tc.get_or_add_tcPr().append(s)

def _run(para, text, bold=False, size=9, color=None):
    r = para.add_run(text)
    r.font.size = Pt(size); r.font.name = "Arial"; r.font.bold = bold
    if color:
        r.font.color.rgb = RGBColor(*color)
    return r

def _kv_table(doc, rows):
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for i, (k, v) in enumerate(rows):
        row = t.add_row()
        for j, txt in enumerate([k, v]):
            c = row.cells[j]; c.text = ""
            _run(c.paragraphs[0], str(txt), bold=(j == 0), size=9)
            _shd(c, ("D6E4F7" if i % 2 == 0 else "F2F2F2") if j == 0 else ("FFFFFF" if i % 2 == 0 else "EFF5FB"))

def generate_docx(est, customer, totals, fab_services, show_breakup=False):
    """
    Generate customer-facing quotation DOCX.
    show_breakup=False  →  Clean quote: one price, Ex-Works + GST + FOR only.
    show_breakup=True   →  Scope-based breakup: groups costs into 4 customer-friendly
                           scope heads (NOT internal cost breakdown).
    """
    doc = Document()
    for sec in doc.sections:
        sec.top_margin = Cm(1.8); sec.bottom_margin = Cm(1.8)
        sec.left_margin = Cm(2.0); sec.right_margin = Cm(2.0)

    # ── Helpers ──────────────────────────────────────────────────────────────
    def banner():
        # Two-column banner: logo on left, company name + offer title on right
        if _LOGO_BYTES:
            t = doc.add_table(rows=1, cols=2); t.style = "Table Grid"
            # Left cell — logo
            lc = t.rows[0].cells[0]; _shd(lc, "FFFFFF")
            lc.width = Cm(4)
            lc.paragraphs[0].clear()
            lp = lc.paragraphs[0]; lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            lp.paragraph_format.space_before = Pt(4); lp.paragraph_format.space_after = Pt(4)
            try:
                import io as _bio
                logo_stream = _bio.BytesIO(_LOGO_BYTES)
                run = lp.add_run()
                run.add_picture(logo_stream, width=Cm(3.5))
            except Exception:
                _run(lp, BG_NAME, bold=True, size=12, color=(27,58,107))
            # Right cell — text
            rc = t.rows[0].cells[1]; _shd(rc, "1B3A6B")
            rc.paragraphs[0].clear()
            p = rc.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(6); p.paragraph_format.space_after = Pt(4)
            _run(p, f"{BG_NAME}\n", bold=True, size=14, color=(255,255,255))
            _run(p, f"{BG_TAGLINE}\n", size=10, color=(180,210,255))
            _run(p, "TECHNICAL & COMMERCIAL OFFER\n", bold=True, size=11, color=(204,221,255))
            _run(p, est.get("equipment_desc",""), bold=True, size=10, color=(255,255,255))
        else:
            # No logo — full-width text banner (original)
            t = doc.add_table(rows=1, cols=1); t.style = "Table Grid"
            c = t.rows[0].cells[0]; _shd(c, "1B3A6B"); c.paragraphs[0].clear()
            p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(6); p.paragraph_format.space_after = Pt(4)
            _run(p, f"{BG_NAME}\n", bold=True, size=16, color=(255,255,255))
            _run(p, f"{BG_TAGLINE}\n", size=10, color=(180,210,255))
            _run(p, "TECHNICAL & COMMERCIAL OFFER\n", bold=True, size=12, color=(204,221,255))
            _run(p, est.get("equipment_desc",""), bold=True, size=10, color=(255,255,255))

    def footer_block():
        doc.add_paragraph()
        t = doc.add_table(rows=1, cols=1); t.style = "Table Grid"
        c = t.rows[0].cells[0]; _shd(c, "1B3A6B"); c.paragraphs[0].clear()
        p = c.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4); p.paragraph_format.space_after = Pt(4)
        _run(p, f"{BG_NAME}  |  {BG_TAGLINE}\n", bold=True, size=9, color=(255,255,255))
        _run(p, f"{BG_ADDRESS}\n", size=8, color=(180,210,255))
        _run(p, f"Ph: {BG_PHONE}  |  {BG_EMAIL}  |  {BG_WEB}\n", size=8, color=(180,210,255))
        _run(p, f"GSTIN: {BG_GSTIN}  |  PAN: {BG_PAN}", bold=True, size=8, color=(255,255,255))

    def sec_head(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10); p.paragraph_format.space_after = Pt(2)
        _run(p, text, bold=True, size=12, color=(27,58,107))
        pBdr = OxmlElement("w:pBdr"); bot = OxmlElement("w:bottom")
        bot.set(qn("w:val"),"single"); bot.set(qn("w:sz"),"6")
        bot.set(qn("w:space"),"1"); bot.set(qn("w:color"),"2E75B6")
        pBdr.append(bot); p._p.get_or_add_pPr().append(pBdr)

    def body(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(2); p.paragraph_format.space_after = Pt(2)
        _run(p, text, size=9, color=(68,68,68))

    def bullet(text):
        p = doc.add_paragraph(text, style="List Bullet")
        for r in p.runs: r.font.size = Pt(9); r.font.name = "Arial"

    def price_table(rows_data):
        """rows_data: list of (label, value_str, is_highlight)"""
        t = doc.add_table(rows=0, cols=2); t.style = "Table Grid"
        for i, (label, value, highlight) in enumerate(rows_data):
            row = t.add_row()
            for j, txt in enumerate([label, value]):
                c = row.cells[j]; c.text = ""
                _run(c.paragraphs[0], txt, bold=highlight, size=10 if highlight else 9,
                     color=(255,255,255) if highlight else (26,26,26))
                _shd(c, "1B3A6B" if highlight else ("F7FBFF" if i%2==0 else "FFFFFF"))
                if j == 1:
                    c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

    fmt  = lambda n: f"₹{n:,.0f}"
    cust = customer or {}

    # ── SECTION 1: Offer & Customer ───────────────────────────────────────────
    banner(); doc.add_paragraph()
    sec_head("SECTION 1 — OFFER & CUSTOMER DETAILS")
    _kv_table(doc, [
        ("Offer Reference",  est.get("qtn_number","")),
        ("Revision",         est.get("revision","R0")),
        ("Date",             date.today().strftime("%d %B %Y")),
        ("Equipment Type",   est.get("equipment_type","")),
        ("Prepared By",      est.get("prepared_by","")),
        ("Checked By",       est.get("checked_by","")),
        ("",""),
        ("Customer Name",    cust.get("name","")),
        ("Customer Address", cust.get("address","")),
        ("Customer GSTIN",   cust.get("gstin","")),
        ("Contact Person",   cust.get("contact_person","")),
        ("Phone / Email",    f"{cust.get('phone','') or ''} / {cust.get('email','') or ''}"),
        ("",""),
        ("Supplier",         BG_NAME),
        ("Supplier Address", BG_ADDRESS),
        ("Supplier GSTIN",   BG_GSTIN),
        ("Phone",            BG_PHONE),
        ("Email / Web",      f"{BG_EMAIL}  |  {BG_WEB}"),
    ])

    # ── SECTION 2: Technical ──────────────────────────────────────────────────
    doc.add_paragraph()
    sec_head("SECTION 2 — TECHNICAL DESIGN BASIS")
    _kv_table(doc, [
        ("Equipment Description", est.get("equipment_desc","")),
        ("Tag Number",            est.get("tag_number","—")),
        ("Capacity",              f"{est.get('capacity_ltrs','')} Litres"),
        ("Design Code",           est.get("design_code","ASME Sec VIII Div 1")),
        ("Design Pressure",       est.get("design_pressure","FV to 4.5 Bar")),
        ("Design Temperature",    est.get("design_temp","-50°C to 250°C")),
        ("Shell Internal Dia",    f"{est.get('shell_dia_mm','')} mm"),
        ("Shell Height (T/T)",    f"{est.get('shell_ht_mm','')} mm"),
        ("Shell Thickness",       f"{est.get('shell_thk_mm','')} mm"),
        ("Dish End Thickness",    f"{est.get('dish_thk_mm','')} mm"),
        ("Jacket / Heating",      est.get("jacket_type","") or "Not applicable"),
        ("Agitator / Drive",      est.get("agitator_type","") or "Not applicable"),
        ("MOC — Vessel",          est.get("moc_shell","SS316L")),
        ("MOC — Jacket",          est.get("moc_jacket","SS304")),
        ("Surface Finish",        est.get("surface_finish","Internal: Ra ≤ 0.8 μm  |  External: Buffed")),
    ])

    # ── Helper: split text block to bullets ──────────────────────────────────
    def bullets_from_text(text_block):
        for line in (text_block or "").split("\n"):
            line = line.strip()
            if line:
                bullet(line)

    # ── SECTION 3: Scope ──────────────────────────────────────────────────────
    doc.add_paragraph()
    sec_head("SECTION 3 — SCOPE OF SUPPLY")
    body("Supply of one (1) complete fabricated equipment per the technical basis above:")
    bullets_from_text(est.get("scope_items",
        "Pressure vessel / equipment fabricated as per approved GA drawing\n"
        "All nozzles, manholes and process connections per nozzle schedule\n"
        "Jacket / limpet coil as specified\n"
        "Agitator complete with gearbox, motor and mechanical seal (where applicable)\n"
        "Support structure — lugs, legs or saddles as applicable\n"
        "Internal grinding and buffing to specified Ra surface finish\n"
        "Equipment nameplate with tag number and serial number"
    ))
    excl = (est.get("scope_exclusions","") or "").strip()
    if excl:
        doc.add_paragraph()
        body("Not in scope:")
        bullets_from_text(excl)

    # ── SECTION 4: Quality ────────────────────────────────────────────────────
    doc.add_paragraph()
    sec_head("SECTION 4 — MANUFACTURING & QUALITY ASSURANCE")
    body(est.get("quality_intro",
        "B&G Engineering Industries operates as an engineering-led manufacturer. "
        "Every project is built to ASME Section VIII Division 1 requirements "
        "with full documentation and traceability."
    ))
    bullets_from_text(est.get("quality_points",
        "Raw material procurement with original Mill Test Certificates (MTC) for all pressure parts\n"
        "100% Positive Material Identification (PMI) verification before cutting\n"
        "Heat number and cast number traceability maintained throughout fabrication\n"
        "Qualified welders — WPS / PQR compliant, TIG welding for all SS316L pressure joints\n"
        "Precision plasma / laser cutting and CNC-controlled plate rolling\n"
        "Pharma-grade internal grinding to Ra ≤ 0.8 μm and external mechanical buffing\n"
        "Dimensional inspection against approved GA drawings at each stage\n"
        "Hydrostatic / pneumatic / vacuum leak test as per ASME Sec VIII Div 1\n"
        "Dye Penetrant (DP) testing on all critical welds\n"
        "Complete QA dossier prepared and delivered with equipment\n"
        "Factory Acceptance Test (FAT) support at works on request"
    ))

    # ── SECTION 5: Documentation ──────────────────────────────────────────────
    doc.add_paragraph()
    sec_head("SECTION 5 — DOCUMENTATION DELIVERABLES")
    body("The following documents are included in scope and delivered with the equipment:")
    bullets_from_text(est.get("doc_deliverables",
        "General Arrangement (GA) Drawing — IFC revision\n"
        "Nozzle orientation and schedule drawing\n"
        "Bill of Materials (BOM)\n"
        "Mill Test Certificates (MTC) for all pressure parts\n"
        "PMI verification records\n"
        "Weld map and weld log\n"
        "DP / RT inspection reports\n"
        "Dimensional inspection report\n"
        "Hydrostatic / leak test certificate\n"
        "Surface finish inspection record (Ra measurement)\n"
        "Inspection and Release Note (IRN)\n"
        "Equipment nameplate photograph"
    ))

    # ── SECTION 6: Commercial ─────────────────────────────────────────────────
    doc.add_paragraph()
    sec_head("SECTION 6 — COMMERCIAL OFFER")

    if show_breakup:
        # ── SCOPE-BASED BREAKUP (customer-friendly, not internal cost heads) ──
        # Groups: (1) Pressure Vessel & Structural, (2) Mechanical Drive & Sealing,
        #         (3) Surface Treatment, Testing & Inspection, (4) Engineering & Documentation
        # Percentages are industry-standard allocation of Ex-Works price — not internal costs
        ex = totals["ex_works"]
        # Scope head allocations — adjust to reflect actual content
        vessel_pct  = 0.68   # vessel + jacket + nozzles + structural
        drive_pct   = 0.18   # motor + gearbox + seal + instrumentation
        testing_pct = 0.08   # buffing + EP + hydro + DP + inspection
        engg_pct    = 0.06   # engineering + drawing + documentation + QA dossier

        vessel_amt  = round(ex * vessel_pct,  0)
        drive_amt   = round(ex * drive_pct,   0)
        testing_amt = round(ex * testing_pct, 0)
        engg_amt    = round(ex - vessel_amt - drive_amt - testing_amt, 0)  # balancing

        body("Scope-based price breakup (for your reference):")
        doc.add_paragraph()
        scope_rows = [
            ("A. Pressure Vessel, Jacket, Nozzles & Structural",
             fmt(vessel_amt), False),
            ("B. Mechanical Drive, Seal, Gearbox & Motor Assembly",
             fmt(drive_amt), False),
            ("C. Surface Finishing, Testing & Third-Party Inspection",
             fmt(testing_amt), False),
            ("D. Engineering, Drawings, Documentation & QA Dossier",
             fmt(engg_amt), False),
            ("Ex-Works Price — Hyderabad (A+B+C+D)",
             fmt(totals["ex_works"]), True),
            (f"GST @ {est.get('gst_pct',18):.0f}%",
             fmt(totals["gst_amt"]), False),
            ("FINAL FOR PRICE",
             fmt(totals["for_price"]), True),
        ]
        price_table(scope_rows)
        doc.add_paragraph()
        body("Note: The above scope breakup is provided for procurement allocation purposes. "
             "B&G Engineering supplies the complete equipment as a single integrated scope — "
             "partial scope orders are not accepted.")
    else:
        # ── CLEAN PRICE — single Ex-Works line ───────────────────────────────
        clean_rows = [
            ("Equipment Description",
             est.get("equipment_desc",""), False),
            ("Quantity",
             "1 No.", False),
            ("Ex-Works Price — Hyderabad",
             fmt(totals["ex_works"]), True),
            (f"GST @ {est.get('gst_pct',18):.0f}% (if applicable)",
             fmt(totals["gst_amt"]), False),
            ("FINAL FOR PRICE (inclusive of GST)",
             fmt(totals["for_price"]), True),
        ]
        price_table(clean_rows)

    doc.add_paragraph()

    # ── Commercial terms — all editable per estimation ──────────────────────
    terms_rows = []
    def _add(label, key, fallback):
        val = (est.get(key,"") or "").strip() or fallback
        if val:
            terms_rows.append((label, val))

    _add("Price Basis",          "price_basis",
         "Ex-Works, Pashamylaram, Hyderabad — 502307. Packing in MS crate included. Freight, insurance and unloading at site excluded.")
    _add("GST & Statutory Levies","gst_clause",
         "GST @ 18% (HSN 8419) as applicable at time of invoicing. Any new statutory levy introduced after offer date will be charged additionally.")
    _add("Payment Terms",         "payment_terms",
         "40% advance along with Purchase Order  |  50% against Pro-forma invoice on readiness for dispatch  |  10% on delivery")

    dw = (est.get("delivery_weeks","") or "12–16").strip()
    dn = (est.get("delivery_note","") or "Subject to availability of raw material at time of order.").strip()
    terms_rows.append(("Delivery Period", f"{dw} weeks from date of Purchase Order + advance payment. {dn}"))

    _add("Offer Validity",        "offer_validity",
         "This offer is valid for 7 calendar days from the date above. Prices subject to change if raw material rates move by more than 3%.")
    _add("Warranty",              "warranty_clause",
         "12 months from date of commissioning or 18 months from date of dispatch, whichever is earlier.")
    _add("Inspection Rights",     "inspection_clause",
         "Customer may depute inspector for stage and final inspection at our works. TPI charges, if any, are in customer scope.")

    excl2 = (est.get("scope_exclusions","") or "").strip()
    if excl2:
        excl_inline = "  |  ".join([l.strip() for l in excl2.split("\n") if l.strip()])
        terms_rows.append(("Not in Scope", excl_inline))

    _kv_table(doc, terms_rows)

    sn = (est.get("special_notes","") or "").strip()
    if sn:
        doc.add_paragraph()
        body(f"Additional Notes: {sn}")

    # ── SECTION 7: Sign-off ───────────────────────────────────────────────────
    doc.add_paragraph()
    sec_head("SECTION 7 — ACCEPTANCE & SIGN-OFF")
    body("We thank you for the opportunity to offer our services and look forward to your valued order. "
         "Please feel free to contact us for any technical or commercial clarifications.")
    doc.add_paragraph()

    t_sign = doc.add_table(rows=3, cols=2); t_sign.style = "Table Grid"
    # Header
    for j, lbl in enumerate(["For B&G Engineering Industries", "Customer Acceptance"]):
        c = t_sign.rows[0].cells[j]; c.text = ""
        _run(c.paragraphs[0], lbl, bold=True, size=9, color=(255,255,255)); _shd(c, "1B3A6B")
    # Prepared / authorised by
    for j, name in enumerate([est.get("prepared_by",""), ""]):
        c = t_sign.rows[1].cells[j]; c.text = ""
        _run(c.paragraphs[0], f"{'Authorised Signatory: ' if j==0 else 'Authorised Signatory: '}{name}", size=9)
    # Date / stamp row
    for j, txt in enumerate([f"Date: {date.today().strftime('%d %B %Y')}", "Date & Company Stamp:"]):
        c = t_sign.rows[2].cells[j]; c.text = ""
        _run(c.paragraphs[0], txt, size=9, color=(100,100,100))

    footer_block()
    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    return buf


# ─────────────────────────────────────────────────────────────────────────────
# ESTIMATION FACT SHEET — XLSX
# Internal engineer document. Shows dimensions, formulas used, weights, rates.
# Used to cross-check against Excel estimation sheet.
# ─────────────────────────────────────────────────────────────────────────────
def generate_fact_sheet_xlsx(est, parts, pipes, flanges, fab_services,
                              bo_items, oh_items, fab_rates, totals):
    if not OPENPYXL_OK:
        raise ImportError("openpyxl not installed. Add 'openpyxl' to requirements.txt and redeploy.")
    import io as _io

    wb = openpyxl.Workbook()

    # ── Styles ────────────────────────────────────────────────────────────────
    DARK_BLUE  = "1B3A6B"
    MID_BLUE   = "2E75B6"
    LIGHT_BLUE = "D6E4F7"
    ALT_ROW    = "EFF5FB"
    GREEN_BG   = "E2EFDA"
    AMBER_BG   = "FFF2CC"
    RED_BG     = "FFE0E0"
    WHITE      = "FFFFFF"

    def hdr_style(cell, bg=DARK_BLUE, fg="FFFFFF", sz=10, bold=True):
        cell.font      = Font(name="Arial", bold=bold, size=sz, color=fg)
        cell.fill      = PatternFill("solid", fgColor=bg)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border    = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"),  bottom=Side(style="thin"),
        )

    def data_style(cell, bg=WHITE, bold=False, align="left", sz=9, color="000000"):
        cell.font      = Font(name="Arial", size=sz, bold=bold, color=color)
        cell.fill      = PatternFill("solid", fgColor=bg)
        cell.alignment = Alignment(horizontal=align, vertical="center")
        cell.border    = Border(
            left=Side(style="hair"), right=Side(style="hair"),
            top=Side(style="hair"),  bottom=Side(style="hair"),
        )

    def section_title(ws, row, text, ncols=10):
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        c = ws.cell(row=row, column=1, value=text)
        hdr_style(c, bg=MID_BLUE, sz=11)
        ws.row_dimensions[row].height = 20

    def kv_row(ws, row, label, value, bg=WHITE):
        lc = ws.cell(row=row, column=1, value=label)
        vc = ws.cell(row=row, column=2, value=value)
        data_style(lc, bg=LIGHT_BLUE, bold=True)
        data_style(vc, bg=bg)
        ws.row_dimensions[row].height = 15

    fmt_inr = '#,##0.00'
    fmt_kg  = '#,##0.000'
    fmt_pct = '0.00%'

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 1 — COVER / SUMMARY
    # ══════════════════════════════════════════════════════════════════════════
    ws1 = wb.active; ws1.title = "Summary"
    ws1.column_dimensions["A"].width = 30
    ws1.column_dimensions["B"].width = 40

    r = 1
    ws1.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
    c = ws1.cell(row=r, column=1, value="B&G ENGINEERING INDUSTRIES — ESTIMATION FACT SHEET")
    hdr_style(c, sz=14); ws1.row_dimensions[r].height = 28; r += 1

    ws1.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
    c = ws1.cell(row=r, column=1, value="INTERNAL DOCUMENT — NOT FOR CUSTOMER DISTRIBUTION")
    hdr_style(c, bg=RED_BG, fg="CC0000", sz=9, bold=True); r += 2

    section_title(ws1, r, "OFFER DETAILS", 8); r += 1
    for label, value in [
        ("Quotation Number",  est.get("qtn_number","")),
        ("Revision",          est.get("revision","R0")),
        ("Date",              date.today().strftime("%d-%b-%Y")),
        ("Customer",          est.get("customer_name","")),
        ("Equipment Type",    est.get("equipment_type","")),
        ("Description",       est.get("equipment_desc","")),
        ("Tag Number",        est.get("tag_number","")),
        ("Status",            est.get("status","Draft")),
        ("Prepared By",       est.get("prepared_by","")),
        ("Checked By",        est.get("checked_by","")),
    ]:
        kv_row(ws1, r, label, value); r += 1

    r += 1
    section_title(ws1, r, "EQUIPMENT PARAMETERS", 8); r += 1
    for label, value in [
        ("Shell ID (mm)",        est.get("shell_dia_mm","")),
        ("Shell Height (mm)",    est.get("shell_ht_mm","")),
        ("Shell Thickness (mm)", est.get("shell_thk_mm","")),
        ("Dish Thickness (mm)",  est.get("dish_thk_mm","")),
        ("Capacity (Ltrs)",      est.get("capacity_ltrs","")),
        ("MOC — Shell",          est.get("moc_shell","SS316L")),
        ("MOC — Jacket",         est.get("moc_jacket","SS304")),
        ("Jacket Type",          est.get("jacket_type","")),
        ("Agitator Type",        est.get("agitator_type","")),
        ("Design Code",          est.get("design_code","ASME Sec VIII Div 1")),
        ("Design Pressure",      est.get("design_pressure","")),
        ("Design Temperature",   est.get("design_temp","")),
    ]:
        kv_row(ws1, r, label, value); r += 1

    r += 1
    section_title(ws1, r, "COST SUMMARY", 8); r += 1
    summary_rows = [
        ("Plates & Parts (RM)",            totals["tot_plates"],   WHITE),
        ("Pipes (RM)",                      totals["tot_pipes"],    WHITE),
        ("Flanges (RM)",                    totals["tot_flanges"],  WHITE),
        ("▶ Total Raw Material",            totals["tot_rm"],       LIGHT_BLUE),
        ("Fabrication Services",            totals["tot_fab"],      WHITE),
        ("Bought-Out Items",                totals["tot_bo"],       WHITE),
        ("Additional Overheads",            totals["tot_oh"],       WHITE),
        ("Engineering & ASME Design",       totals["engg_design"],  WHITE),
        ("▶ Total Manufacturing Cost",      totals["tot_mfg"],      LIGHT_BLUE),
        ("Contingency",                     totals["cont_amt"],     WHITE),
        ("Profit / Margin",                 totals["profit_amt"],   WHITE),
        ("Packing",                         totals["packing"],      WHITE),
        ("Freight",                         totals["freight"],      WHITE),
        ("▶ Ex-Works Price",               totals["ex_works"],     GREEN_BG),
        ("GST",                             totals["gst_amt"],      WHITE),
        ("▶ FOR Price",                    totals["for_price"],    GREEN_BG),
    ]
    for label, value, bg in summary_rows:
        lc = ws1.cell(row=r, column=1, value=label)
        vc = ws1.cell(row=r, column=2, value=value)
        bold = "▶" in label
        data_style(lc, bg=LIGHT_BLUE if bold else WHITE, bold=bold)
        data_style(vc, bg=bg, bold=bold, align="right")
        vc.number_format = fmt_inr; r += 1

    r += 1
    section_title(ws1, r, "MARGIN ANALYSIS", 8); r += 1
    safe = totals["ex_works"] if totals["ex_works"] else 1
    for label, val in [
        ("RM %",      totals["tot_rm"]/safe*100),
        ("Fab Svc %", totals["tot_fab"]/safe*100),
        ("OH %",      totals["tot_oh"]/safe*100),
        ("Profit %",  totals["profit_amt"]/safe*100),
    ]:
        lc = ws1.cell(row=r, column=1, value=label)
        vc = ws1.cell(row=r, column=2, value=round(val,2))
        data_style(lc, bg=LIGHT_BLUE, bold=True)
        data_style(vc, bg=AMBER_BG if (val<8 or val>60) else WHITE, align="right")
        vc.number_format = "0.00"; r += 1
        vc.value = str(round(val,2)) + "%"

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 2 — PLATES & PARTS with FORMULAS
    # ══════════════════════════════════════════════════════════════════════════
    ws2 = wb.create_sheet("Plates & Parts")
    headers = [
        "Part Name","Group","Part Type","Material","Density\n(kg/m³)",
        "Formula Used","Key Dimensions","Qty","Net Wt/Unit\n(kg)",
        "Total Wt\n(kg)","Rate\n(₹/kg)","Amount\n(₹)","Scrap %"
    ]
    col_widths = [20,14,22,10,10,38,36,6,12,12,10,14,8]
    for i,(h_txt,w) in enumerate(zip(headers,col_widths),1):
        c = ws2.cell(row=1, column=i, value=h_txt)
        hdr_style(c, sz=9)
        ws2.column_dimensions[get_column_letter(i)].width = w
    ws2.row_dimensions[1].height = 32

    # Formula descriptions per part type
    FORMULA_DESC = {
        "shell":   "π × ID × Ht × Thk × ρ × (1+scrap)",
        "dish":    "1.09 × π × (ID×1.167/2)² × Thk × ρ × (1+scrap)",
        "annular": "(π/4) × (OD²−ID²) × Thk × ρ × (1+scrap)",
        "solid":   "(π/4) × D² × L × ρ × (1+scrap)",
        "flat":    "W × H × Thk × ρ × (1+scrap)",
        "stiff":   "π × (ID+2×ShThk) × BarW × BarThk × ρ × (1+scrap) × (ShHt/Pitch)",
        "cone":    "π × (R1+R2) × slant × Thk × ρ × (1+scrap)",
        "rect":    "L × W × Thk × ρ × (1+scrap)",
        "tube":    "π × (OD−Thk) × Thk × TubeL × ρ × N × (1+scrap)",
    }
    SCRAP_PCT = {
        "shell":"5%","dish":"15%","annular":"5%","solid":"15%",
        "flat":"5%","stiff":"5%","cone":"5%","rect":"5%","tube":"5%",
    }

    def dims_str(fn, dims):
        d = dims or {}
        if fn=="shell":  return f"ID={d.get('id_mm','')} Ht={d.get('ht_mm','')} Thk={d.get('thk_mm','')} mm"
        if fn=="dish":   return f"ShID={d.get('shell_id_mm','')} Thk={d.get('thk_mm','')} mm"
        if fn=="annular":return f"OD={d.get('od_mm','')} ID={d.get('id_mm','')} Thk={d.get('thk_mm','')} mm"
        if fn=="solid":  return f"D={d.get('dia_mm','')} L={d.get('length_mm','')} mm"
        if fn=="flat":   return f"W={d.get('w_mm','')} H={d.get('h_mm','')} Thk={d.get('thk_mm','')} mm"
        if fn=="stiff":  return (f"ShID={d.get('shell_id_mm','')} ShThk={d.get('shell_thk_mm','')} "
                                  f"ShHt={d.get('shell_ht_mm','')} Pitch={d.get('pitch_mm','')} "
                                  f"BarW={d.get('bar_w_mm','')} BarThk={d.get('thk_mm','')} mm")
        if fn=="cone":   return f"LgID={d.get('large_id_mm','')} SmID={d.get('small_id_mm','')} Ht={d.get('ht_mm','')} Thk={d.get('thk_mm','')} mm"
        if fn=="rect":   return f"L={d.get('length_mm','')} W={d.get('width_mm','')} Thk={d.get('thk_mm','')} mm"
        if fn=="tube":   return f"OD={d.get('tube_od_mm','')} Thk={d.get('tube_thk_mm','')} L={d.get('tube_length_mm','')} N={d.get('n_tubes','')} mm"
        return str(dims)

    row_n = 2
    tot_wt = 0; tot_amt = 0
    for i, p in enumerate(parts):
        fn = PART_TYPES.get(p.get("part_type",""),{}).get("fn","")
        bg = WHITE if i%2==0 else ALT_ROW
        vals = [
            p.get("name",""),
            p.get("group",""),
            p.get("part_type",""),
            p.get("material",""),
            DENSITY.get(p.get("material","SS316L"),8000),
            FORMULA_DESC.get(fn,"Manual entry"),
            dims_str(fn, p.get("dims",{})),
            p.get("qty",1),
            p.get("net_wt_kg",0),
            p.get("total_wt_kg",0),
            p.get("rate",0),
            p.get("amount",0),
            SCRAP_PCT.get(fn,"5%"),
        ]
        for col, val in enumerate(vals, 1):
            c = ws2.cell(row=row_n, column=col, value=val)
            align = "right" if col in (5,8,9,10,11,12) else "left"
            data_style(c, bg=bg, align=align)
            if col in (9,10):  c.number_format = fmt_kg
            if col in (11,12): c.number_format = fmt_inr
        tot_wt  += p.get("total_wt_kg",0)
        tot_amt += p.get("amount",0)
        row_n += 1

    # Total row
    for col in range(1,14):
        c = ws2.cell(row=row_n, column=col)
        if col==1: c.value = "TOTAL"
        if col==10: c.value = round(tot_wt,3)
        if col==12: c.value = round(tot_amt,2)
        hdr_style(c, bg=MID_BLUE, sz=9)
        if col in (10,): c.number_format = fmt_kg
        if col in (12,): c.number_format = fmt_inr

    # Freeze header
    ws2.freeze_panes = "A2"

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 3 — PIPES & FLANGES
    # ══════════════════════════════════════════════════════════════════════════
    ws3 = wb.create_sheet("Pipes & Flanges")
    for i, hdr in enumerate(["Description","Item Code","Type","Length(m)","Qty",
                               "Wt/m (kg/m)","Formula","Total Wt (kg)","Rate (₹/kg)","Amount (₹)"],1):
        c = ws3.cell(row=1, column=i, value=hdr); hdr_style(c, sz=9)
    for w, col in zip([22,24,10,10,6,10,32,12,12,14],[1,2,3,4,5,6,7,8,9,10]):
        ws3.column_dimensions[get_column_letter(col)].width = w

    row_n = 2
    for i, p in enumerate(pipes + flanges):
        is_flange = i >= len(pipes)
        bg = WHITE if i%2==0 else ALT_ROW
        formula = "Wt/m × Length × 1.05 (5% fitting allowance) × Qty" if not is_flange else "Wt/m × 1.15 (15% allowance) × Qty"
        vals = [
            p.get("name",""),
            p.get("item_code",""),
            "Flange" if is_flange else "Pipe",
            p.get("length_m","") if not is_flange else "—",
            p.get("qty",1),
            p.get("wt_per_m",0) if not is_flange else p.get("total_wt_kg",0)/max(p.get("qty",1),1),
            formula,
            p.get("total_wt_kg",0),
            p.get("rate",0),
            p.get("amount",0),
        ]
        for col, val in enumerate(vals, 1):
            c = ws3.cell(row=row_n, column=col, value=val)
            data_style(c, bg=bg, align="right" if col in (4,5,6,8,9,10) else "left")
            if col in (8,): c.number_format = fmt_kg
            if col in (9,10): c.number_format = fmt_inr
        row_n += 1
    ws3.freeze_panes = "A2"

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 4 — FABRICATION SERVICES
    # ══════════════════════════════════════════════════════════════════════════
    ws4 = wb.create_sheet("Fabrication Services")
    for i, hdr in enumerate(["Service","Basis / Formula","Qty","UOM","Rate","Amount (₹)"],1):
        c = ws4.cell(row=1, column=i, value=hdr); hdr_style(c, sz=9)
    for w, col in zip([30,50,10,8,14,16],[1,2,3,4,5,6]):
        ws4.column_dimensions[get_column_letter(col)].width = w

    row_n = 2
    for i, fs in enumerate(fab_services):
        bg = WHITE if i%2==0 else ALT_ROW
        for col, val in enumerate([
            fs.get("service",""), fs.get("basis",""),
            fs.get("qty",""), fs.get("uom",""),
            fs.get("rate",0), fs.get("amount",0),
        ], 1):
            c = ws4.cell(row=row_n, column=col, value=val)
            data_style(c, bg=bg, align="right" if col in (3,5,6) else "left")
            if col in (5,6): c.number_format = fmt_inr
        row_n += 1

    # Rates used
    row_n += 2
    ws4.cell(row=row_n, column=1, value="FABRICATION RATES USED")
    hdr_style(ws4.cell(row=row_n, column=1), bg=MID_BLUE); row_n += 1
    for key, val in fab_rates.items():
        lc = ws4.cell(row=row_n, column=1, value=key.replace("_"," ").title())
        vc = ws4.cell(row=row_n, column=2, value=val)
        data_style(lc, bg=LIGHT_BLUE, bold=True)
        data_style(vc, bg=WHITE, align="right")
        row_n += 1
    ws4.freeze_panes = "A2"

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 5 — BOUGHT-OUT & OVERHEADS
    # ══════════════════════════════════════════════════════════════════════════
    ws5 = wb.create_sheet("Bought-Out & OH")
    for i, hdr in enumerate(["Description","Item Code","Group","Qty","Rate","Amount (₹)"],1):
        c = ws5.cell(row=1, column=i, value=hdr); hdr_style(c, sz=9)
    for w, col in zip([28,24,14,8,14,16],[1,2,3,4,5,6]):
        ws5.column_dimensions[get_column_letter(col)].width = w

    row_n = 2
    ws5.cell(row=row_n, column=1, value="── Bought-Out Items ──")
    hdr_style(ws5.cell(row=row_n, column=1), bg=MID_BLUE, sz=9); row_n += 1
    for i, b in enumerate(bo_items):
        bg = WHITE if i%2==0 else ALT_ROW
        for col, val in enumerate([b.get("name",""),b.get("item_code",""),b.get("group",""),b.get("qty",1),b.get("rate",0),b.get("amount",0)],1):
            c = ws5.cell(row=row_n, column=col, value=val)
            data_style(c, bg=bg, align="right" if col in (4,5,6) else "left")
            if col in (5,6): c.number_format = fmt_inr
        row_n += 1

    row_n += 1
    ws5.cell(row=row_n, column=1, value="── Additional Overheads ──")
    hdr_style(ws5.cell(row=row_n, column=1), bg=MID_BLUE, sz=9); row_n += 1
    for i, o in enumerate(oh_items):
        bg = WHITE if i%2==0 else ALT_ROW
        for col, val in enumerate([o.get("description",""),o.get("oh_code",""),o.get("oh_type",""),o.get("qty",1),o.get("rate",0),o.get("amount",0)],1):
            c = ws5.cell(row=row_n, column=col, value=val)
            data_style(c, bg=bg, align="right" if col in (4,5,6) else "left")
            if col in (5,6): c.number_format = fmt_inr
        row_n += 1
    ws5.freeze_panes = "A2"

    # ══════════════════════════════════════════════════════════════════════════
    # SHEET 6 — FORMULA REFERENCE
    # ══════════════════════════════════════════════════════════════════════════
    ws6 = wb.create_sheet("Formula Reference")
    ws6.column_dimensions["A"].width = 28
    ws6.column_dimensions["B"].width = 55
    ws6.column_dimensions["C"].width = 20
    ws6.column_dimensions["D"].width = 20

    r = 1
    ws6.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    c = ws6.cell(row=r, column=1, value="B&G ENGINEERING INDUSTRIES — GEOMETRY FORMULA REFERENCE")
    hdr_style(c, sz=12); ws6.row_dimensions[r].height = 24; r += 2

    formulas = [
        ("CYLINDRICAL SHELL",
         "W = π × ID(m) × Ht(m) × Thk(m) × ρ(kg/m³) × (1 + scrap)",
         "scrap = 5%", "density per MOC"),
        ("DISH END (Torispherical)",
         "Blank dia = ID × 1.167 | Area = 1.09 × π × (blank_dia/2)² | W = Area × Thk(m) × ρ × (1 + scrap)",
         "scrap = 15%", "Crown radius = ID"),
        ("ANNULAR PLATE / FLANGE",
         "W = (π/4) × (OD² − ID²) × Thk(m) × ρ × (1 + scrap)",
         "scrap = 5%", "All dims in metres"),
        ("SOLID ROUND (Shaft / Bush)",
         "W = (π/4) × D(m)² × L(m) × ρ × (1 + scrap)",
         "scrap = 15%", ""),
        ("FLAT RECTANGLE (Blade/Pad/Gusset)",
         "W = W(m) × H(m) × Thk(m) × ρ × (1 + scrap)",
         "scrap = 5%", ""),
        ("STIFFENER RINGS (Flat bar on shell OD)",
         "Shell OD = ID + 2×Thk | Circ = π×OD | N = ShHt/Pitch | Wt/ring = Circ×BarW×BarThk×ρ×(1+scrap) | Total = Wt/ring×N",
         "scrap = 5%", "N rings = derived qty"),
        ("CONE / REDUCER",
         "R1=LargeID/2, R2=SmallID/2 | Slant=√(Ht²+(R1−R2)²) | W=π×(R1+R2)×Slant×Thk×ρ×(1+scrap)",
         "scrap = 5%", ""),
        ("RECTANGULAR PLATE",
         "W = L(m) × W(m) × Thk(m) × ρ × (1 + scrap)",
         "scrap = 5%", ""),
        ("TUBE BUNDLE",
         "Mid_r=(OD−Thk)/2 | Wt/tube=π×2×Mid_r×L×Thk×ρ | Total=Wt/tube×N_tubes×(1+scrap)",
         "scrap = 5%", ""),
    ]

    for i, hdr in enumerate(["Part Type","Formula","Notes","Reference"],1):
        c = ws6.cell(row=r, column=i, value=hdr); hdr_style(c, sz=9)
    r += 1

    for pt, formula, notes, ref in formulas:
        bg = WHITE if formulas.index((pt,formula,notes,ref))%2==0 else ALT_ROW
        for col, val in enumerate([pt, formula, notes, ref], 1):
            c = ws6.cell(row=r, column=col, value=val)
            data_style(c, bg=LIGHT_BLUE if col==1 else bg, bold=(col==1))
            c.alignment = Alignment(wrap_text=True, vertical="top")
        ws6.row_dimensions[r].height = max(15, formula.count("\n")*14 + 14)
        r += 1

    r += 2
    ws6.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    c = ws6.cell(row=r, column=1, value="MATERIAL DENSITY TABLE (kg/m³)")
    hdr_style(c, bg=MID_BLUE, sz=10); r += 1
    for mat, den in DENSITY.items():
        lc = ws6.cell(row=r, column=1, value=mat)
        vc = ws6.cell(row=r, column=2, value=den)
        data_style(lc, bg=LIGHT_BLUE, bold=True)
        data_style(vc, bg=WHITE, align="right")
        r += 1

    # ── Save ──────────────────────────────────────────────────────────────────
    buf = _io.BytesIO()
    wb.save(buf); buf.seek(0)
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
# SESSION STATE HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _blank_hdr():
    return dict(
        # ── Core fields ───────────────────────────────────────────────────────
        qtn_number="", revision="R0", customer_name="",
        equipment_type=EQUIPMENT_NAMES[0], equipment_desc="", tag_number="",
        capacity_ltrs=2000.0, shell_dia_mm=1300.0, shell_ht_mm=1500.0,
        shell_thk_mm=8.0, dish_thk_mm=10.0,
        jacket_type="SS304 Half-pipe Jacket with Insulation Jacket",
        agitator_type="Anchor", design_code="ASME Sec VIII Div 1",
        design_pressure="FV to 4.5 Bar", design_temp="-50 to 250°C",
        moc_shell="SS316L", moc_jacket="SS304", surface_finish="Internal: Ra ≤ 0.8 μm  |  External: Buffed",
        status="Draft", prepared_by="", checked_by="",
        profit_margin_pct=10.0, contingency_pct=0.0,
        packing_amt=5000.0, freight_amt=10000.0,
        gst_pct=18.0, engg_design_amt=25000.0, notes="",

        # ── DOCX customisable sections (editable per estimation) ──────────────
        # Section 3 — Scope of Supply
        scope_items=(
            "Pressure vessel / equipment fabricated as per approved GA drawing\n"
            "All nozzles, manholes, handholes and process connections per nozzle schedule\n"
            "Jacket / limpet coil / half-pipe with insulation jacket (where applicable)\n"
            "Agitator complete with gearbox, motor and mechanical seal (where applicable)\n"
            "Support structure — lugs, legs or saddles as applicable\n"
            "Internal grinding and buffing to specified Ra surface finish\n"
            "Equipment nameplate with tag number and serial number"
        ),
        # Section 3 — Exclusions (appended to scope)
        scope_exclusions=(
            "Civil / structural works\n"
            "Electrical & Instrumentation\n"
            "Erection & commissioning at site\n"
            "DQ / IQ / OQ / PQ validation\n"
            "Freight, insurance and unloading at site\n"
            "Import duties if applicable"
        ),

        # Section 4 — Quality & Manufacturing
        quality_intro=(
            "B&G Engineering Industries operates as an engineering-led manufacturer. "
            "Every project is built to ASME Section VIII Division 1 requirements "
            "with full documentation and traceability."
        ),
        quality_points=(
            "Raw material procurement with original Mill Test Certificates (MTC) for all pressure parts\n"
            "100% Positive Material Identification (PMI) verification before cutting\n"
            "Heat number and cast number traceability maintained throughout fabrication\n"
            "Qualified welders — WPS / PQR compliant, TIG welding for all SS316L pressure joints\n"
            "Precision plasma / laser cutting and CNC-controlled plate rolling\n"
            "Pharma-grade internal grinding to Ra ≤ 0.8 μm and external mechanical buffing\n"
            "Dimensional inspection against approved GA drawings at each stage\n"
            "Hydrostatic / pneumatic / vacuum leak test as per ASME Sec VIII Div 1\n"
            "Dye Penetrant (DP) testing on all critical welds\n"
            "Complete QA dossier prepared and delivered with equipment\n"
            "Factory Acceptance Test (FAT) support at works on request"
        ),

        # Section 5 — Documentation
        doc_deliverables=(
            "General Arrangement (GA) Drawing — IFC revision\n"
            "Nozzle orientation and schedule drawing\n"
            "Bill of Materials (BOM)\n"
            "Mill Test Certificates (MTC) for all pressure parts\n"
            "PMI verification records\n"
            "Weld map and weld log\n"
            "DP / RT inspection reports\n"
            "Dimensional inspection report\n"
            "Hydrostatic / leak test certificate\n"
            "Surface finish inspection record (Ra measurement)\n"
            "Inspection and Release Note (IRN)\n"
            "Equipment nameplate photograph"
        ),

        # Section 6 — Commercial terms
        price_basis="Ex-Works, Pashamylaram, Hyderabad — 502307. Packing in MS crate included. Freight, insurance and unloading at site excluded.",
        gst_clause="GST @ 18% (HSN 8419) as applicable at time of invoicing. Any new statutory levy introduced after offer date will be charged additionally.",
        payment_terms="40% advance along with Purchase Order  |  50% against Pro-forma invoice on readiness for dispatch  |  10% on delivery",
        delivery_weeks="12–16",
        delivery_note="Subject to availability of raw material at time of order.",
        offer_validity="This offer is valid for 7 calendar days from the date above. Prices subject to change if raw material rates move by more than 3%.",
        warranty_clause="12 months from date of commissioning or 18 months from date of dispatch, whichever is earlier. Covers manufacturing defects under normal operating conditions as per design basis.",
        inspection_clause="Customer may depute inspector for stage and final inspection at our works. Third-party inspection (TPI) agency charges, if any, are in customer scope.",
        special_notes="",
    )

def _reset_form():
    for k in ["est_hdr", "est_parts", "est_pipes", "est_flanges", "est_fab",
              "est_bo", "est_oh", "est_edit_id", "edit_part_idx", "fab_rates"]:
        st.session_state.pop(k, None)

def _load_est_into_form(est):
    h = _blank_hdr()
    for k in h:
        if k in est and est[k] is not None:
            h[k] = est[k]
    st.session_state.est_hdr     = h
    st.session_state.est_parts   = json.loads(est.get("parts_json")     or "[]")
    st.session_state.est_pipes   = json.loads(est.get("pipes_json")     or "[]")
    st.session_state.est_flanges = json.loads(est.get("flanges_json")   or "[]")
    st.session_state.est_fab     = json.loads(est.get("fab_json")       or "[]")
    st.session_state.est_bo      = json.loads(est.get("bo_json")        or "[]")
    st.session_state.est_oh      = json.loads(est.get("oh_json")        or "[]")
    st.session_state.fab_rates   = json.loads(est.get("fab_rates_json") or json.dumps(FAB_DEFAULTS))
    st.session_state.est_edit_id = est.get("id")

def _build_save_row(h):
    """Build clean row dict for Supabase — strips keys not in table."""
    skip = {"customer_id"}
    clean = {k: v for k, v in h.items() if k not in skip and v is not None}
    return {
        **clean,
        "parts_json":     json.dumps(st.session_state.est_parts),
        "pipes_json":     json.dumps(st.session_state.est_pipes),
        "flanges_json":   json.dumps(st.session_state.est_flanges),
        "fab_json":       json.dumps(st.session_state.est_fab),
        "bo_json":        json.dumps(st.session_state.est_bo),
        "oh_json":        json.dumps(st.session_state.est_oh),
        "fab_rates_json": json.dumps(st.session_state.fab_rates),
        "updated_at":     datetime.now().isoformat(),
    }

def _do_save(reset_after=False):
    """
    Core save function — always reads from st.session_state directly.
    Works correctly from any tab because it never relies on widget return values.
    If reset_after=True, clears the form after saving (used by Save & Close).
    Returns True if saved successfully.
    """
    h = st.session_state.est_hdr
    edit_id = st.session_state.est_edit_id
    qtn = h.get("qtn_number", "").strip()

    if not qtn:
        st.warning("⚠️ Quotation Number is empty. Enter it in Tab 1️⃣ Header first.")
        return False

    # Duplicate check — only flag if a DIFFERENT record has this QTN
    existing = sb_fetch("estimations", select="id", filters={"qtn_number": qtn})
    if existing and not edit_id:
        st.error(f"❌ QTN **{qtn}** already exists. Load it from the search panel to edit it.")
        return False
    if existing and edit_id:
        if any(str(e.get("id")) != str(edit_id) for e in existing):
            st.error(f"❌ QTN **{qtn}** belongs to a different estimation.")
            return False

    # Build row — strips customer_id and None values
    skip = {"customer_id"}
    clean_h = {k: v for k, v in h.items() if k not in skip and v is not None}
    row = {
        **clean_h,
        "parts_json":     json.dumps(st.session_state.est_parts),
        "pipes_json":     json.dumps(st.session_state.est_pipes),
        "flanges_json":   json.dumps(st.session_state.est_flanges),
        "fab_json":       json.dumps(st.session_state.est_fab),
        "bo_json":        json.dumps(st.session_state.est_bo),
        "oh_json":        json.dumps(st.session_state.est_oh),
        "fab_rates_json": json.dumps(st.session_state.fab_rates),
        "updated_at":     datetime.now().isoformat(),
    }

    if edit_id:
        ok = sb_update("estimations", row, "id", edit_id)
        msg = f"Updated {qtn}"
    else:
        row["created_at"] = datetime.now().isoformat()
        ok = sb_insert("estimations", row)
        msg = f"Saved {qtn}"
        if ok:
            # Capture the new record ID so subsequent saves go to update path
            saved = sb_fetch("estimations", select="id", filters={"qtn_number": qtn})
            if saved:
                st.session_state.est_edit_id = saved[0]["id"]

    if ok:
        n_p = len(st.session_state.est_parts)
        rm  = sum(p.get("amount", 0) for p in st.session_state.est_parts)
        fab = sum(f.get("amount", 0) for f in st.session_state.est_fab)
        st.success(f"✅ {msg}  |  {n_p} parts  |  RM ₹{rm:,.0f}  |  Fab ₹{fab:,.0f}")
        st.cache_data.clear()
        if reset_after:
            _reset_form()
        return True
    return False

# Keep _build_save_row for backward compat (used nowhere else now but keep tidy)
def _build_save_row(h):
    skip = {"customer_id"}
    clean = {k: v for k, v in h.items() if k not in skip and v is not None}
    return {**clean, "parts_json": json.dumps(st.session_state.est_parts),
            "pipes_json": json.dumps(st.session_state.est_pipes),
            "flanges_json": json.dumps(st.session_state.est_flanges),
            "fab_json": json.dumps(st.session_state.est_fab),
            "bo_json": json.dumps(st.session_state.est_bo),
            "oh_json": json.dumps(st.session_state.est_oh),
            "fab_rates_json": json.dumps(st.session_state.fab_rates),
            "updated_at": datetime.now().isoformat()}

def _save_draft_bar(tab_key):
    """
    Save Draft bar — appears at the bottom of every tab.
    Like Ctrl+S in Excel: saves current state without disturbing the form.
    Reads everything from session state — never from widget return values.
    """
    h = st.session_state.est_hdr
    st.divider()
    sb1, sb2, sb3 = st.columns([4, 1, 1])
    qtn  = h.get("qtn_number", "") or "—"
    n_p  = len(st.session_state.est_parts)
    n_pi = len(st.session_state.est_pipes)
    n_f  = len(st.session_state.est_fab)
    n_b  = len(st.session_state.est_bo)
    sb1.caption(f"💾 **{qtn}**  |  {n_p} parts  |  {n_pi} pipes  |  {n_f} fab lines  |  {n_b} BO items")
    if sb2.button("💾 Save Draft", use_container_width=True, type="primary", key=f"sd_{tab_key}"):
        _do_save(reset_after=False)
    if sb3.button("🗑️ Reset / New", use_container_width=True, key=f"rst_{tab_key}"):
        _reset_form()
        st.rerun()

for key, default in [
    ("est_hdr",       _blank_hdr()),
    ("est_parts",     []),
    ("est_pipes",     []),
    ("est_flanges",   []),
    ("est_fab",       []),
    ("est_bo",        []),
    ("est_oh",        []),
    ("est_edit_id",   None),
    ("edit_part_idx", None),
    ("fab_rates",     dict(FAB_DEFAULTS)),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ─────────────────────────────────────────────────────────────────────────────
# PAGE HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.title("📐 Estimation & Costing")
if _LOGO_BYTES:
    st.caption(f"🖼️ Logo loaded from Supabase: `{_LOGO_FNAME}` — will appear in all quotations.")
else:
    st.caption("🖼️ No logo found in `progress-photos` bucket. Upload as `logo.png` to include in quotations.")
_qtn_now = st.session_state.est_hdr.get("qtn_number", "")
_eid_now  = st.session_state.est_edit_id
if _eid_now and _qtn_now:
    st.info(f"✏️ Editing: **{_qtn_now}**  |  {len(st.session_state.est_parts)} parts  |  RM ₹{sum(p.get('amount',0) for p in st.session_state.est_parts):,.0f}")
elif _qtn_now:
    st.info(f"📝 New estimation in progress: **{_qtn_now}**")
st.markdown("---")

TAB_LIST, TAB_NEW, TAB_QUOTE, TAB_SIMILAR, TAB_MASTERS = st.tabs([
    "📋 Register", "➕ New / Edit", "✍️ Quote Editor", "🔍 Similar Equipment", "📊 Masters",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB: REGISTER
# ══════════════════════════════════════════════════════════════════════════════
with TAB_LIST:
    st.subheader("Estimations Register")
    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    f_status   = col_f1.selectbox("Status",    ["All", "Draft", "Issued", "Won", "Lost", "On Hold"])
    f_equip    = col_f2.selectbox("Equipment", ["All"] + EQUIPMENT_NAMES)
    f_customer = col_f3.text_input("Customer")
    f_search   = col_f4.text_input("QTN / Tag")

    all_est = load_all_estimations()
    if f_status != "All":   all_est = [e for e in all_est if e.get("status") == f_status]
    if f_equip != "All":    all_est = [e for e in all_est if e.get("equipment_type") == f_equip]
    if f_customer:          all_est = [e for e in all_est if f_customer.lower() in (e.get("customer_name", "") or "").lower()]
    if f_search:            all_est = [e for e in all_est if f_search.lower() in (e.get("qtn_number", "") or "").lower() or f_search.lower() in (e.get("tag_number", "") or "").lower()]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total",  len(all_est))
    m2.metric("Draft",  sum(1 for e in all_est if e.get("status") == "Draft"))
    m3.metric("Issued", sum(1 for e in all_est if e.get("status") == "Issued"))
    m4.metric("Won",    sum(1 for e in all_est if e.get("status") == "Won"))
    st.divider()

    if not all_est:
        st.info("No estimations yet. Use ➕ New / Edit tab to create one.")
    else:
        summary_rows = []
        for est in reversed(all_est):
            eq_info = EQUIPMENT_TYPES.get(est.get("equipment_type", ""), {})
            si = {"Draft": "🟡", "Issued": "🔵", "Won": "🟢", "Lost": "🔴", "On Hold": "⚪"}.get(est.get("status", ""), "🟡")
            summary_rows.append({
                "":           f"{si} {eq_info.get('icon', '🔧')}",
                "QTN No":     est.get("qtn_number", ""),
                "Customer":   est.get("customer_name", ""),
                "Equipment":  est.get("equipment_desc", ""),
                "Cap (L)":    est.get("capacity_ltrs", ""),
                "Status":     est.get("status", ""),
                "Prepared By": est.get("prepared_by", ""),
                "Updated":    str(est.get("updated_at", ""))[:10],
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        st.markdown("#### Select a quotation to view details and actions")
        qtn_opts = ["— select —"] + [e.get("qtn_number", "") for e in reversed(all_est) if e.get("qtn_number")]
        selected_qtn = st.selectbox("QTN", qtn_opts, label_visibility="collapsed")

        if selected_qtn != "— select —":
            est = next((e for e in all_est if e.get("qtn_number") == selected_qtn), None)
            if est:
                parts   = json.loads(est.get("parts_json")   or "[]")
                pipes   = json.loads(est.get("pipes_json")   or "[]")
                flanges = json.loads(est.get("flanges_json") or "[]")
                fab_s   = json.loads(est.get("fab_json")     or "[]")
                bo      = json.loads(est.get("bo_json")      or "[]")
                oh      = json.loads(est.get("oh_json")      or "[]")
                T = calc_totals(
                    parts, pipes, flanges, fab_s, bo, oh,
                    float(est.get("profit_margin_pct") or 10), float(est.get("contingency_pct") or 0),
                    float(est.get("packing_amt") or 0), float(est.get("freight_amt") or 0),
                    float(est.get("gst_pct") or 18), float(est.get("engg_design_amt") or 0),
                )
                st.markdown("---")
                d1, d2, d3 = st.columns(3)
                d1.write(f"**Type:** {est.get('equipment_type', '')}"); d1.write(f"**Tag:** {est.get('tag_number', '-')}")
                d2.write(f"**Revision:** {est.get('revision', 'R0')}"); d2.write(f"**Prepared By:** {est.get('prepared_by', '-')}")
                d3.write(f"**Status:** {est.get('status', '')}"); d3.write(f"**Updated:** {str(est.get('updated_at', ''))[:10]}")

                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Raw Material", f"₹{T['tot_rm']:,.0f}")
                k2.metric("Fabrication",  f"₹{T['tot_fab']:,.0f}")
                k3.metric("Mfg Cost",     f"₹{T['tot_mfg']:,.0f}")
                k4.metric("Ex-Works",     f"₹{T['ex_works']:,.0f}")
                k5.metric("FOR Price",    f"₹{T['for_price']:,.0f}")

                st.markdown("**Actions**")
                a1, a2, a3, a4 = st.columns(4)
                if a1.button("✏️ Edit", use_container_width=True, type="primary"):
                    fresh = sb_fetch("estimations", filters={"id": est["id"]})
                    _load_est_into_form(fresh[0] if fresh else est)
                    st.success(f"Loaded — {len(st.session_state.est_parts)} parts. Click ➕ New / Edit tab.")
                if a2.button("📋 Clone to New", use_container_width=True):
                    _load_est_into_form(est)
                    st.session_state.est_hdr["qtn_number"] = ""
                    st.session_state.est_hdr["revision"]   = "R0"
                    st.session_state.est_hdr["status"]     = "Draft"
                    st.session_state.est_hdr["notes"]      = f"Cloned from {est.get('qtn_number', '')}"
                    st.session_state.est_edit_id           = None
                    st.success("Cloned — go to ➕ New / Edit and enter new QTN.")
                cust_rows = sb_fetch("master_clients", filters={"name": est.get("customer_name", "")})
                cust_data = cust_rows[0] if cust_rows else {}
                a3.download_button(
                    "📄 Standard Quote",
                    generate_docx(est, cust_data, T, fab_s, show_breakup=False),
                    file_name=f"{est.get('qtn_number','QTN')}_{est.get('revision','R0')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    key=f"dl_{est.get('id')}",
                )
                a4_dl_col = st.columns(4)[3]
                a4_dl_col.download_button(
                    "📋 With Breakup",
                    generate_docx(est, cust_data, T, fab_s, show_breakup=True),
                    file_name=f"{est.get('qtn_number','QTN')}_{est.get('revision','R0')}_breakup.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    key=f"dl_bk_{est.get('id')}",
                )
                new_status = a4.selectbox(
                    "Status",
                    ["Draft", "Issued", "Won", "Lost", "On Hold"],
                    index=["Draft", "Issued", "Won", "Lost", "On Hold"].index(est.get("status", "Draft")),
                    key=f"st_{est.get('id')}",
                )
                if new_status != est.get("status"):
                    if a4.button("✅ Apply", key=f"ap_{est.get('id')}", use_container_width=True):
                        sb_update("estimations", {"status": new_status, "updated_at": datetime.now().isoformat()}, "id", est.get("id"))
                        st.cache_data.clear(); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB: NEW / EDIT
# ══════════════════════════════════════════════════════════════════════════════
with TAB_NEW:
    edit_id  = st.session_state.est_edit_id
    _qtn_hdr = st.session_state.est_hdr.get("qtn_number", "")
    if edit_id and _qtn_hdr:
        st.subheader(f"✏️ Editing: {_qtn_hdr}")
    elif _qtn_hdr:
        st.subheader(f"📝 New Estimation: {_qtn_hdr}")
    else:
        st.subheader("➕ New Estimation")

    rm_master   = load_rm_master()
    oh_master   = load_oh_master()
    clients     = load_clients_full()
    anchor_qtns = load_anchor_qtns()

    client_names = [c["name"] for c in clients]
    oh_codes     = list(oh_master.keys())
    plate_rm     = [k for k, v in rm_master.items() if v.get("category") == "RM"]
    pipe_rm      = [k for k, v in rm_master.items() if v.get("rm_type") == "Pipe"]
    flg_rm       = [k for k, v in rm_master.items() if v.get("rm_type") == "FLG"]
    bo_rm        = [k for k, v in rm_master.items() if v.get("category") == "BO"]
    all_groups   = sorted({"SHELL", "DISH_ENDS", "JACKET", "INS_JACKET", "AGITATOR", "BAFFLES",
                            "LUGS", "STIFFNERS", "MANHOLE", "NOZZLES", "RM_MISC", "BODY_FL",
                            "TUBE_BUNDLE", "TUBE_SHEET", "FILTER_PLATE", "TRAYS", "FRAME", "OTHER"})

    f1, f2, f3, f4, f5, f6 = st.tabs([
        "1️⃣ Header", "2️⃣ Plates & Parts", "3️⃣ Pipes & Flanges",
        "4️⃣ Fabrication Services", "5️⃣ Bought-Out & OH", "6️⃣ Summary & Save",
    ])
    h = st.session_state.est_hdr

    # ── F1: HEADER ─────────────────────────────────────────────────────────────
    with f1:
        # ── SEARCH & LOAD PANEL ────────────────────────────────────────────────
        all_est_list = load_all_estimations()
        all_est_valid = [e for e in all_est_list if e.get("qtn_number")]

        with st.container(border=True):
            if edit_id:
                st.success(f"✏️ **Editing:** {h.get('qtn_number', '')}  |  {h.get('customer_name', '')}  |  {len(st.session_state.est_parts)} parts loaded")
            elif h.get("qtn_number"):
                st.info(f"📝 **Working on new:** {h.get('qtn_number', '')}  |  {h.get('customer_name', '')}  |  {len(st.session_state.est_parts)} parts")
            else:
                st.warning("📄 New estimation — fill details below, or search and load a saved one.")

            st.markdown("**🔍 Search & Load a Saved Estimation**")
            sf1, sf2, sf3, sf4 = st.columns(4)
            srch_qtn  = sf1.text_input("QTN",      placeholder="e.g. B&G/MAITHRI", key="srch_qtn")
            srch_cust = sf2.text_input("Customer",  placeholder="e.g. Neuland",    key="srch_cust")
            srch_eq   = sf3.selectbox("Equipment",  ["All"] + EQUIPMENT_NAMES,     key="srch_eq")
            srch_stat = sf4.selectbox("Status",     ["All", "Draft", "Issued", "Won", "Lost", "On Hold"], key="srch_stat")

            filtered = all_est_valid
            if srch_qtn:           filtered = [e for e in filtered if srch_qtn.lower()  in (e.get("qtn_number", "") or "").lower()]
            if srch_cust:          filtered = [e for e in filtered if srch_cust.lower() in (e.get("customer_name", "") or "").lower()]
            if srch_eq != "All":   filtered = [e for e in filtered if e.get("equipment_type") == srch_eq]
            if srch_stat != "All": filtered = [e for e in filtered if e.get("status") == srch_stat]

            if filtered:
                def _lbl(e):
                    si = {"Draft": "🟡", "Issued": "🔵", "Won": "🟢", "Lost": "🔴", "On Hold": "⚪"}.get(e.get("status", ""), "🟡")
                    return f"{si} {e.get('qtn_number', '')}  |  {e.get('customer_name', '—')}  |  {e.get('equipment_desc', '—')}  |  {e.get('capacity_ltrs', '')}L  |  {e.get('status', '')}"

                opts = ["— select to load —"] + [_lbl(e) for e in filtered]
                ld1, ld2, ld3 = st.columns([5, 1, 1])
                load_sel = ld1.selectbox("Select", opts, key="f1_load_sel", label_visibility="collapsed")

                if ld2.button("📂 Load / Edit", use_container_width=True, type="primary", key="f1_load_btn"):
                    if load_sel != "— select to load —":
                        preview = filtered[opts.index(load_sel) - 1]
                        fresh = sb_fetch("estimations", filters={"id": preview["id"]})
                        match = fresh[0] if fresh else preview
                        _load_est_into_form(match)
                        st.success(f"✅ Loaded **{match.get('qtn_number','')}** — {len(st.session_state.est_parts)} parts, {len(st.session_state.est_pipes)} pipes, {len(st.session_state.est_fab)} fab lines.")
                        st.rerun()

                if ld3.button("📋 Clone", use_container_width=True, key="f1_clone_btn"):
                    if load_sel != "— select to load —":
                        preview = filtered[opts.index(load_sel) - 1]
                        fresh = sb_fetch("estimations", filters={"id": preview["id"]})
                        match = fresh[0] if fresh else preview
                        _load_est_into_form(match)
                        st.session_state.est_hdr["qtn_number"] = ""
                        st.session_state.est_hdr["revision"]   = "R0"
                        st.session_state.est_hdr["status"]     = "Draft"
                        st.session_state.est_hdr["notes"]      = f"Cloned from {match.get('qtn_number', '')}"
                        st.session_state.est_edit_id           = None
                        st.success(f"📋 Cloned from **{match.get('qtn_number', '')}** — enter new QTN number below.")
                        st.rerun()
            else:
                st.caption("No saved estimations match the filters. Fill the form below to create a new one.")

            if st.button("🗑️ Clear / Start Fresh", key="f1_clear_btn"):
                _reset_form(); st.rerun()

        st.divider()

        # ── Equipment type ────────────────────────────────────────────────────
        st.markdown("##### Equipment Type")
        prev_type = h.get("equipment_type", EQUIPMENT_NAMES[0])
        if prev_type not in EQUIPMENT_NAMES:
            prev_type = EQUIPMENT_NAMES[0]
        eq_c1, eq_c2 = st.columns([4, 1])
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

        # ── Anchor portal ─────────────────────────────────────────────────────
        st.markdown("##### Pull from Anchor Portal  _(optional)_")
        anc_options = ["— type QTN manually —"] + [
            f"{a.get('quote_ref', '')}  |  {a.get('client_name', '')}  |  {a.get('project_description', '')}"
            for a in anchor_qtns
        ]
        anc_sel = st.selectbox("Anchor Portal", anc_options, label_visibility="collapsed")
        if anc_sel != "— type QTN manually —":
            chosen = anchor_qtns[anc_options.index(anc_sel) - 1]
            h["qtn_number"]    = chosen.get("quote_ref", "")
            h["customer_name"] = chosen.get("client_name", "")
            st.success(f"Auto-filled — QTN: **{h['qtn_number']}**  |  Customer: **{h['customer_name']}**")
        st.divider()

        # ── Offer details ─────────────────────────────────────────────────────
        st.markdown("##### Offer Details")
        c1, c2, c3 = st.columns(3)
        h["qtn_number"] = c1.text_input("Quotation Number *", value=h["qtn_number"], placeholder="e.g. B&G/MAITHRI/2026/2922")
        h["revision"]   = c2.selectbox("Revision", ["R0", "R1", "R2", "R3", "R4", "R5"],
                                        index=["R0", "R1", "R2", "R3", "R4", "R5"].index(h.get("revision", "R0")))
        h["status"]     = c3.selectbox("Status", ["Draft", "Issued", "Won", "Lost", "On Hold"],
                                        index=["Draft", "Issued", "Won", "Lost", "On Hold"].index(h.get("status", "Draft")))
        st.divider()

        # ── Customer ──────────────────────────────────────────────────────────
        st.markdown("##### Customer")
        cust_opts = ["— select —"] + client_names
        cust_idx  = cust_opts.index(h["customer_name"]) if h["customer_name"] in cust_opts else 0
        sel_cust  = st.selectbox("Customer", cust_opts, index=cust_idx, label_visibility="collapsed")
        if sel_cust != "— select —":
            h["customer_name"] = sel_cust
            cd = next((c for c in clients if c["name"] == sel_cust), {})
            cc = st.columns(4)
            cc[0].caption(f"📍 {cd.get('address', '—')}")
            cc[1].caption(f"🏷️ GSTIN: {cd.get('gstin', '—')}")
            cc[2].caption(f"👤 {cd.get('contact_person', '—')}")
            cc[3].caption(f"📞 {cd.get('phone', '—')}")
        st.divider()

        # ── Equipment parameters ──────────────────────────────────────────────
        st.markdown("##### Equipment Parameters")
        c1, c2 = st.columns(2)
        h["equipment_desc"] = c1.text_input("Description", value=h["equipment_desc"], placeholder="e.g. 2000 Ltrs SS316L Jacketed Reactor")
        h["tag_number"]     = c2.text_input("Tag Number",  value=h["tag_number"],     placeholder="e.g. R-505")

        c1, c2, c3, c4, c5 = st.columns(5)
        h["capacity_ltrs"] = c1.number_input("Capacity (Ltrs)", value=float(h["capacity_ltrs"]), min_value=0.0, step=100.0)
        h["shell_dia_mm"]  = c2.number_input("Shell ID (mm)",   value=float(h["shell_dia_mm"]),  min_value=0.0, step=50.0)
        h["shell_ht_mm"]   = c3.number_input("Shell Ht (mm)",   value=float(h["shell_ht_mm"]),   min_value=0.0, step=100.0)
        h["shell_thk_mm"]  = c4.number_input("Shell Thk (mm)",  value=float(h["shell_thk_mm"]),  min_value=0.0, step=1.0)
        h["dish_thk_mm"]   = c5.number_input("Dish Thk (mm)",   value=float(h["dish_thk_mm"]),   min_value=0.0, step=1.0)

        s_area   = calc_shell_area(h["shell_dia_mm"], h["shell_ht_mm"])
        d_area   = calc_dish_area(h["shell_dia_mm"])
        vol      = calc_shell_volume_ltrs(h["shell_dia_mm"], h["shell_ht_mm"])
        int_area = s_area + d_area * 2
        weld_m   = calc_weld_metres(h["shell_dia_mm"], h["shell_ht_mm"],
                                    has_jacket=bool(h.get("jacket_type", "")),
                                    has_agitator=bool(h.get("agitator_type", "")))
        g1, g2, g3, g4, g5 = st.columns(5)
        g1.metric("Shell Area (m²)",      f"{s_area:.3f}")
        g2.metric("Dish Area (m²)",       f"{d_area:.3f}")
        g3.metric("Total Internal (m²)",  f"{int_area:.3f}")
        g4.metric("Shell Vol (Ltrs)",     f"{vol:.0f}")
        g5.metric("Est. Weld (m)",        f"{weld_m:.1f}")

        c1, c2 = st.columns(2)
        h["jacket_type"]   = c1.text_input("Jacket Type",   value=h["jacket_type"])
        h["agitator_type"] = c2.text_input("Agitator Type", value=h["agitator_type"])

        c1, c2, c3 = st.columns(3)
        h["design_code"]     = c1.text_input("Design Code",     value=h["design_code"])
        h["design_pressure"] = c2.text_input("Design Pressure", value=h["design_pressure"])
        h["design_temp"]     = c3.text_input("Design Temp",     value=h["design_temp"])

        c1, c2 = st.columns(2)
        h["moc_shell"]  = c1.text_input("MOC – Shell",  value=h["moc_shell"])
        h["moc_jacket"] = c2.text_input("MOC – Jacket", value=h["moc_jacket"])
        st.divider()

        st.markdown("##### Prepared By / Checked By")
        staff_list = [""] + st.session_state.master_data.get("staff", [])
        c1, c2 = st.columns(2)
        pb_idx = staff_list.index(h["prepared_by"]) if h["prepared_by"] in staff_list else 0
        cb_idx = staff_list.index(h["checked_by"])  if h["checked_by"]  in staff_list else 0
        h["prepared_by"] = c1.selectbox("Prepared By", staff_list, index=pb_idx)
        h["checked_by"]  = c2.selectbox("Checked By",  staff_list, index=cb_idx)
        h["notes"] = st.text_area("Internal Notes (not printed in quote)", value=h["notes"], height=60)
        st.divider()

        # ── DOCX CUSTOMISATION ────────────────────────────────────────────────
        st.markdown("##### 📝 Quotation Content Customisation")
        st.caption("All sections below print directly into the customer quotation. Edit per client URS / requirements.")

        with st.expander("📦 Section 3 — Scope of Supply & Exclusions", expanded=False):
            st.markdown("**Scope items** — one per line, prints as bullet list")
            h["scope_items"] = st.text_area(
                "Scope items", value=h.get("scope_items",""), height=220,
                help="One item per line. Each line becomes a bullet point in the quotation.",
                label_visibility="collapsed",
            )
            st.markdown("**Exclusions** — one per line")
            h["scope_exclusions"] = st.text_area(
                "Exclusions", value=h.get("scope_exclusions",""), height=150,
                help="One exclusion per line. Printed under 'Not in Scope' in Section 3.",
                label_visibility="collapsed",
            )

        with st.expander("🔬 Section 4 — Manufacturing & Quality", expanded=False):
            st.markdown("**Opening paragraph**")
            h["quality_intro"] = st.text_area(
                "Quality intro", value=h.get("quality_intro",""), height=80,
                label_visibility="collapsed",
            )
            st.markdown("**Quality points** — one per line, prints as bullet list")
            h["quality_points"] = st.text_area(
                "Quality points", value=h.get("quality_points",""), height=280,
                help="One point per line. Add/remove/edit based on equipment type and client URS.",
                label_visibility="collapsed",
            )
            st.caption("💡 Tip — add for ANFD: 'Filter plate flatness inspection per DIN 1685' | for RCVD: 'Vacuum integrity test to -1 bar for 30 min' | for pharma: 'GAMP5 documentation support available on request'")

        with st.expander("📋 Section 5 — Documentation Deliverables", expanded=False):
            st.markdown("**Document list** — one per line")
            h["doc_deliverables"] = st.text_area(
                "Documentation", value=h.get("doc_deliverables",""), height=250,
                help="One document per line. Add client-specific requirements like ASME data report, 3.1 certs, etc.",
                label_visibility="collapsed",
            )
            st.caption("💡 Tip — add for regulated clients: 'ASME U-stamp data report' | 'EN 10204 3.1 material certs' | 'Radiographic (RT) test report' | 'Positive pressure decay test record'")

        with st.expander("💰 Section 6 — Commercial Terms", expanded=False):
            h["surface_finish"]    = st.text_input("Surface Finish (shown in Tech Basis)", value=h.get("surface_finish","Internal: Ra ≤ 0.8 μm  |  External: Buffed"))
            h["price_basis"]       = st.text_area("Price Basis",        value=h.get("price_basis",""),  height=60)
            h["gst_clause"]        = st.text_area("GST / Taxes Clause", value=h.get("gst_clause",""),   height=60)
            h["payment_terms"]     = st.text_area("Payment Terms",      value=h.get("payment_terms",""),height=60)
            c1, c2 = st.columns(2)
            h["delivery_weeks"]    = c1.text_input("Delivery (weeks)",   value=h.get("delivery_weeks","12–16"))
            h["delivery_note"]     = c2.text_input("Delivery note",      value=h.get("delivery_note","Subject to availability of raw material at time of order."))
            h["offer_validity"]    = st.text_area("Offer Validity",      value=h.get("offer_validity",""), height=60)
            h["warranty_clause"]   = st.text_area("Warranty",            value=h.get("warranty_clause",""),height=60)
            h["inspection_clause"] = st.text_area("Inspection Rights",   value=h.get("inspection_clause",""),height=60)
            h["special_notes"]     = st.text_area("Special Notes / Additional Conditions (printed at end of Section 6)", value=h.get("special_notes",""), height=80,
                help="Use for client-specific conditions: GAMP5, ATEX zone, clean room requirements, etc.")

        _save_draft_bar("f1")

    # ── F2: PLATES & PARTS ─────────────────────────────────────────────────────
    with f2:
        # Status banner
        qtn_d = h.get("qtn_number", "") or "New"
        n_p   = len(st.session_state.est_parts)
        rm_t  = sum(p.get("amount", 0) for p in st.session_state.est_parts)
        if n_p > 0:
            st.success(f"**{qtn_d}** — {h.get('customer_name', 'no customer')}  |  {n_p} parts  |  RM ₹{rm_t:,.0f}")
        else:
            st.info(f"**{qtn_d}** — No parts yet. Load from Tab 1️⃣ or add below.")


        # ── ESTIMATION AUDIT ───────────────────────────────────────────────────────
        with st.expander("🔍 Audit Estimation Sheet — Upload CSV to verify weights & amounts", expanded=False):
            st.markdown("""
**How to use:**
1. Export your existing estimation sheet (Excel → Save As CSV)
2. Make sure it has these columns (column names must match exactly):
   `part_name, part_type, material, qty, rate_per_kg, claimed_wt_kg, claimed_amount`
3. Optional dimension columns are used to recalculate weight using B&G formulas
4. Upload below — the app shows where your sheet matches and where it differs
""")

            # ── Audit template download ──────────────────────────────────────
            import io as _io, csv as _csv
            audit_template = [
                ["part_name","part_type","group","material","qty","rate_per_kg",
                 "claimed_wt_kg","claimed_amount",
                 "id_mm","ht_mm","thk_mm",
                 "shell_id_mm","dish_thk_mm",
                 "dia_mm","length_mm",
                 "w_mm","h_mm",
                 "od_mm","id2_mm",
                 "shell_thk_mm","shell_ht_mm","pitch_mm","bar_w_mm","bar_thk_mm",
                 "large_id_mm","small_id_mm",
                 "width_mm",
                 "tube_od_mm","tube_thk_mm","tube_length_mm","n_tubes"],
                ["Main Shell","Cylindrical shell","SHELL","SS316L",1,480,
                 411.7,197616,
                 1300,1500,8,
                 "","",
                 "","",
                 "","",
                 "","",
                 "","","","","",
                 "","",
                 "",
                 "","","",""],
                ["Dish Ends","Dish end (torispherical)","DISH_ENDS","SS316L",2,480,
                 362.5,174000,
                 "","","",
                 1300,10,
                 "","",
                 "","",
                 "","",
                 "","","","","",
                 "","",
                 "",
                 "","","",""],
                ["Bottom Shaft","Solid round (shaft / bush)","AGITATOR","SS316L",1,480,
                 91.4,43872,
                 "","","",
                 "","",
                 85,550,
                 "","",
                 "","",
                 "","","","","",
                 "","",
                 "",
                 "","","",""],
            ]
            buf = _io.StringIO()
            _csv.writer(buf).writerows(audit_template)
            st.download_button(
                "📥 Download Audit Template CSV",
                buf.getvalue().encode(),
                file_name="bgeng_audit_template.csv",
                mime="text/csv",
                use_container_width=True,
            )

            st.markdown("---")

            audit_file = st.file_uploader(
                "Upload your estimation sheet as CSV",
                type=["csv"],
                key="audit_csv_upload",
            )

            if audit_file is not None:
                import io as _io2, csv as _csv2

                TOLERANCE_PCT = 3.0  # within 3% is considered OK

                def _fv(row, col, default=0.0):
                    v = str(row.get(col, "")).strip()
                    try: return float(v) if v else default
                    except: return default

                try:
                    text = audit_file.read().decode("utf-8-sig")
                    reader = _csv2.DictReader(_io2.StringIO(text))
                    rows = list(reader)

                    audit_results = []
                    total_claimed_wt  = 0.0
                    total_calc_wt     = 0.0
                    total_claimed_amt = 0.0
                    total_calc_amt    = 0.0

                    for i, row in enumerate(rows, 1):
                        raw_type = str(row.get("part_type","")).strip()
                        matched_type = None
                        for k in PART_TYPES:
                            if raw_type.lower() in k.lower() or k.lower().startswith(raw_type.lower()[:8]):
                                matched_type = k
                                break

                        part_name      = str(row.get("part_name","")).strip() or f"Row {i}"
                        material       = str(row.get("material","SS316L")).strip() or "SS316L"
                        qty            = max(1.0, _fv(row, "qty", 1.0))
                        rate           = _fv(row, "rate_per_kg", 0.0)
                        claimed_wt     = _fv(row, "claimed_wt_kg", 0.0)
                        claimed_amt    = _fv(row, "claimed_amount", 0.0)

                        calc_wt   = 0.0
                        calc_amt  = 0.0
                        wt_status = "⚠️ No dims"
                        amt_status= "⚠️ No dims"
                        fn        = None
                        dims      = {}

                        if matched_type:
                            fn = PART_TYPES[matched_type]["fn"]
                            density = DENSITY.get(material, 8000)

                            if fn == "shell":
                                dims = {"id_mm":_fv(row,"id_mm"),"ht_mm":_fv(row,"ht_mm"),"thk_mm":_fv(row,"thk_mm")}
                            elif fn == "dish":
                                dims = {"shell_id_mm":_fv(row,"shell_id_mm"),"thk_mm":_fv(row,"dish_thk_mm") or _fv(row,"thk_mm")}
                            elif fn == "annular":
                                dims = {"od_mm":_fv(row,"od_mm"),"id_mm":_fv(row,"id2_mm") or _fv(row,"id_mm"),"thk_mm":_fv(row,"thk_mm")}
                            elif fn == "solid":
                                dims = {"dia_mm":_fv(row,"dia_mm"),"length_mm":_fv(row,"length_mm")}
                            elif fn == "flat":
                                dims = {"w_mm":_fv(row,"w_mm"),"h_mm":_fv(row,"h_mm"),"thk_mm":_fv(row,"thk_mm")}
                            elif fn == "stiff":
                                dims = {"shell_id_mm":_fv(row,"shell_id_mm"),"shell_thk_mm":_fv(row,"shell_thk_mm"),
                                        "shell_ht_mm":_fv(row,"shell_ht_mm"),"pitch_mm":_fv(row,"pitch_mm") or 300,
                                        "bar_w_mm":_fv(row,"bar_w_mm"),"thk_mm":_fv(row,"bar_thk_mm") or _fv(row,"thk_mm")}
                            elif fn == "cone":
                                dims = {"large_id_mm":_fv(row,"large_id_mm"),"small_id_mm":_fv(row,"small_id_mm"),
                                        "ht_mm":_fv(row,"ht_mm"),"thk_mm":_fv(row,"thk_mm")}
                            elif fn == "rect":
                                dims = {"length_mm":_fv(row,"length_mm"),"width_mm":_fv(row,"width_mm") or _fv(row,"w_mm"),"thk_mm":_fv(row,"thk_mm")}
                            elif fn == "tube":
                                dims = {"tube_od_mm":_fv(row,"tube_od_mm"),"tube_thk_mm":_fv(row,"tube_thk_mm"),
                                        "tube_length_mm":_fv(row,"tube_length_mm"),"n_tubes":_fv(row,"n_tubes")}

                            has_dims = any(v > 0 for v in dims.values())
                            if has_dims:
                                net_wt, calc_wt, used_qty = calc_weight(fn, dims, density, qty)
                                calc_amt = round(calc_wt * rate, 2)

                                # Weight check
                                if claimed_wt > 0:
                                    wt_diff_pct = abs(calc_wt - claimed_wt) / claimed_wt * 100
                                    if wt_diff_pct <= TOLERANCE_PCT:
                                        wt_status = f"✅ OK ({wt_diff_pct:.1f}%)"
                                    elif wt_diff_pct <= 10:
                                        wt_status = f"🟡 {wt_diff_pct:.1f}% off"
                                    else:
                                        wt_status = f"🔴 {wt_diff_pct:.1f}% off"
                                else:
                                    wt_status = "— no claim"

                                # Amount check
                                if claimed_amt > 0 and rate > 0:
                                    amt_diff_pct = abs(calc_amt - claimed_amt) / claimed_amt * 100
                                    if amt_diff_pct <= TOLERANCE_PCT:
                                        amt_status = f"✅ OK ({amt_diff_pct:.1f}%)"
                                    elif amt_diff_pct <= 10:
                                        amt_status = f"🟡 {amt_diff_pct:.1f}% off"
                                    else:
                                        amt_status = f"🔴 {amt_diff_pct:.1f}% off"
                                else:
                                    amt_status = "— no rate/claim"
                        else:
                            wt_status = f"⚠️ Unknown type: {raw_type}"
                            amt_status = "—"

                        total_claimed_wt  += claimed_wt
                        total_calc_wt     += calc_wt
                        total_claimed_amt += claimed_amt
                        total_calc_amt    += calc_amt

                        audit_results.append({
                            "Part":           part_name,
                            "Type":           matched_type or raw_type,
                            "Mat":            material,
                            "Qty":            qty,
                            "Rate":           rate,
                            "Claimed Wt (kg)":round(claimed_wt,2),
                            "Calc Wt (kg)":   round(calc_wt,2),
                            "Wt Check":       wt_status,
                            "Claimed ₹":      f"₹{claimed_amt:,.0f}",
                            "Calc ₹":         f"₹{calc_amt:,.0f}",
                            "Amt Check":      amt_status,
                        })

                    # ── Summary metrics ──────────────────────────────────────
                    st.markdown("#### Audit Summary")
                    am1,am2,am3,am4,am5,am6 = st.columns(6)
                    am1.metric("Rows audited", len(audit_results))

                    wt_var = total_calc_wt - total_claimed_wt
                    amt_var = total_calc_amt - total_claimed_amt
                    am2.metric("Claimed total wt",  f"{total_claimed_wt:,.1f} kg")
                    am3.metric("Calc total wt",     f"{total_calc_wt:,.1f} kg",
                               delta=f"{wt_var:+.1f} kg",
                               delta_color="inverse" if abs(wt_var)>total_claimed_wt*0.05 else "off")
                    am4.metric("Claimed total ₹",   f"₹{total_claimed_amt:,.0f}")
                    am5.metric("Calc total ₹",      f"₹{total_calc_amt:,.0f}",
                               delta=f"₹{amt_var:+,.0f}",
                               delta_color="inverse" if abs(amt_var)>total_claimed_amt*0.05 else "off")

                    n_red    = sum(1 for r in audit_results if "🔴" in r["Wt Check"] or "🔴" in r["Amt Check"])
                    n_yellow = sum(1 for r in audit_results if "🟡" in r["Wt Check"] or "🟡" in r["Amt Check"])
                    n_ok     = sum(1 for r in audit_results if "✅" in r["Wt Check"] and "✅" in r["Amt Check"])
                    am6.metric("Issues found", f"🔴 {n_red}  🟡 {n_yellow}  ✅ {n_ok}")

                    if n_red > 0:
                        st.error(f"❌ {n_red} part(s) have errors >10% — review highlighted rows below.")
                    elif n_yellow > 0:
                        st.warning(f"⚠️ {n_yellow} part(s) differ 3–10% from formula — acceptable but worth checking.")
                    else:
                        st.success("✅ All parts within tolerance. Estimation sheet looks correct.")

                    # ── Detail table ─────────────────────────────────────────
                    st.markdown("#### Part-by-Part Audit")
                    df_audit = pd.DataFrame(audit_results)
                    st.dataframe(df_audit, use_container_width=True, hide_index=True)

                    # ── Export audit report ──────────────────────────────────
                    csv_out = _io2.StringIO()
                    df_audit.to_csv(csv_out, index=False)
                    st.download_button(
                        "📤 Download Audit Report CSV",
                        csv_out.getvalue().encode(),
                        file_name=f"bgeng_audit_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                        mime="text/csv",
                        use_container_width=True,
                    )

                    # ── Import audited parts ─────────────────────────────────
                    st.markdown("---")
                    st.markdown("**Import audited parts into current estimation?**")
                    imp1, imp2 = st.columns(2)
                    # Rebuild importable parts from audit rows
                    importable = []
                    for i2, row in enumerate(rows):
                        raw_type = str(row.get("part_type","")).strip()
                        matched_type = None
                        for k in PART_TYPES:
                            if raw_type.lower() in k.lower() or k.lower().startswith(raw_type.lower()[:8]):
                                matched_type = k; break
                        if not matched_type: continue
                        fn2 = PART_TYPES[matched_type]["fn"]
                        material2 = str(row.get("material","SS316L")).strip() or "SS316L"
                        density2  = DENSITY.get(material2,8000)
                        qty2      = max(1.0,_fv(row,"qty",1.0))
                        rate2     = _fv(row,"rate_per_kg",0.0)
                        dims2 = {}
                        if fn2=="shell": dims2={"id_mm":_fv(row,"id_mm"),"ht_mm":_fv(row,"ht_mm"),"thk_mm":_fv(row,"thk_mm")}
                        elif fn2=="dish": dims2={"shell_id_mm":_fv(row,"shell_id_mm"),"thk_mm":_fv(row,"dish_thk_mm") or _fv(row,"thk_mm")}
                        elif fn2=="solid": dims2={"dia_mm":_fv(row,"dia_mm"),"length_mm":_fv(row,"length_mm")}
                        elif fn2=="flat": dims2={"w_mm":_fv(row,"w_mm"),"h_mm":_fv(row,"h_mm"),"thk_mm":_fv(row,"thk_mm")}
                        elif fn2=="stiff": dims2={"shell_id_mm":_fv(row,"shell_id_mm"),"shell_thk_mm":_fv(row,"shell_thk_mm"),"shell_ht_mm":_fv(row,"shell_ht_mm"),"pitch_mm":_fv(row,"pitch_mm") or 300,"bar_w_mm":_fv(row,"bar_w_mm"),"thk_mm":_fv(row,"bar_thk_mm") or _fv(row,"thk_mm")}
                        elif fn2=="cone": dims2={"large_id_mm":_fv(row,"large_id_mm"),"small_id_mm":_fv(row,"small_id_mm"),"ht_mm":_fv(row,"ht_mm"),"thk_mm":_fv(row,"thk_mm")}
                        elif fn2=="rect": dims2={"length_mm":_fv(row,"length_mm"),"width_mm":_fv(row,"width_mm") or _fv(row,"w_mm"),"thk_mm":_fv(row,"thk_mm")}
                        elif fn2=="tube": dims2={"tube_od_mm":_fv(row,"tube_od_mm"),"tube_thk_mm":_fv(row,"tube_thk_mm"),"tube_length_mm":_fv(row,"tube_length_mm"),"n_tubes":_fv(row,"n_tubes")}
                        elif fn2=="annular": dims2={"od_mm":_fv(row,"od_mm"),"id_mm":_fv(row,"id2_mm") or _fv(row,"id_mm"),"thk_mm":_fv(row,"thk_mm")}
                        nwt,twt,uqty = calc_weight(fn2,dims2,density2,qty2)
                        importable.append(dict(name=str(row.get("part_name","")).strip() or matched_type,
                            part_type=matched_type,group=str(row.get("group","OTHER")).strip() or "OTHER",
                            material=material2,item_code="",dims=dims2,qty=uqty,
                            net_wt_kg=nwt,total_wt_kg=twt,rate=rate2,amount=round(twt*rate2,2)))
                    if importable:
                        if imp1.button("➕ Add audited parts to estimation", type="primary", use_container_width=True, key="audit_add"):
                            st.session_state.est_parts.extend(importable)
                            st.success(f"✅ Added {len(importable)} parts from audit sheet.")
                        if imp2.button("🔄 Replace all parts with audited", use_container_width=True, key="audit_replace"):
                            st.session_state.est_parts = importable
                            st.success(f"✅ Replaced with {len(importable)} audited parts.")

                except Exception as ex:
                    st.error(f"CSV parse error: {ex}. Check column names match the template.")

        st.divider()
        st.divider()
        st.markdown("##### Add / Edit Fabricated Parts")
        st.caption("Select Part Type → only the required dimension inputs appear → click Add Part.")

        edit_pidx = st.session_state.get("edit_part_idx")
        if edit_pidx is not None and isinstance(edit_pidx, int) and 0 <= edit_pidx < len(st.session_state.est_parts):
            editing_part = st.session_state.est_parts[edit_pidx]
        else:
            editing_part = None; st.session_state["edit_part_idx"] = None; edit_pidx = None

        ek = f"e{edit_pidx}_" if edit_pidx is not None else "new_"

        with st.container(border=True):
            if edit_pidx is not None and editing_part is not None:
                st.info(f"Editing row {edit_pidx + 1}: **{st.session_state.est_parts[edit_pidx].get('name', '')}** — update values then click Update Part")

            rc1, rc2, rc3 = st.columns(3)
            pt_keys = list(PART_TYPES.keys())
            def_pt  = editing_part.get("part_type", pt_keys[0]) if editing_part else pt_keys[0]
            if def_pt not in pt_keys:
                def_pt = pt_keys[0]
            p_name  = rc1.text_input("Part Name", value=editing_part.get("name", "") if editing_part else "", placeholder="e.g. Main Shell", key=f"{ek}pn")
            p_type  = rc2.selectbox("Part Type",  pt_keys, index=pt_keys.index(def_pt), key=f"{ek}pt")
            p_group = rc3.selectbox("Group",       all_groups,
                                    index=all_groups.index(editing_part.get("group", "SHELL")) if editing_part and editing_part.get("group", "SHELL") in all_groups else 0,
                                    key=f"{ek}pg")

            rc4, rc5, rc6 = st.columns(3)
            mat_list   = list(DENSITY.keys())
            def_mat    = editing_part.get("material", "SS316L") if editing_part else "SS316L"
            p_material = rc4.selectbox("Material", mat_list, index=mat_list.index(def_mat) if def_mat in mat_list else 0, key=f"{ek}pm")
            p_code     = rc5.selectbox("RM Code (for rate)", plate_rm or ["—"],
                                       index=plate_rm.index(editing_part.get("item_code", "")) if editing_part and editing_part.get("item_code", "") in plate_rm else 0,
                                       key=f"{ek}pc")
            p_rate_ov  = rc6.number_input("Rate Override ₹/kg  (0 = use master)", value=0.0, min_value=0.0, key=f"{ek}pr")

            pt_info    = PART_TYPES[p_type]
            is_derived = pt_info.get("qty_derived", False)
            if is_derived:
                st.info("Qty is auto-calculated from geometry (shell height ÷ pitch).")
                p_qty = 1.0
            else:
                p_qty = st.number_input("Qty", value=float(editing_part.get("qty", 1)) if editing_part else 1.0, min_value=1.0, step=1.0, key=f"{ek}pq")

            needed   = pt_info["fields"]
            dim_cols = st.columns(len(needed))
            dims     = {}
            for i, (field, label) in enumerate(needed):
                def_val = float(editing_part.get("dims", {}).get(field, 0.0)) if editing_part else 0.0
                dims[field] = dim_cols[i].number_input(label, value=def_val, min_value=0.0, step=1.0, key=f"{ek}d_{p_type}_{field}")

            btn_c1, btn_c2 = st.columns([3, 1])
            add_btn    = btn_c1.button("➕ Add Part" if not editing_part else "✅ Update Part", type="primary", use_container_width=True)
            cancel_btn = btn_c2.button("✖ Cancel", use_container_width=True) if editing_part else False

            if cancel_btn:
                st.session_state["edit_part_idx"] = None

            if add_btn:
                density  = DENSITY.get(p_material, 8000)
                fn       = pt_info["fn"]
                rm       = rm_master.get(p_code, {})
                rate     = p_rate_ov if p_rate_ov > 0 else rm.get("rate", 0)
                wt, total_wt, used_qty = calc_weight(fn, dims, density, p_qty)
                if wt == 0:
                    st.warning("⚠️ Weight is zero — check all dimension inputs.")
                new_part = dict(
                    name=p_name, part_type=p_type, group=p_group,
                    material=p_material, item_code=p_code, dims=dims,
                    qty=used_qty, net_wt_kg=wt, total_wt_kg=total_wt,
                    rate=rate, amount=round(total_wt * rate, 2),
                )
                if editing_part is not None and edit_pidx is not None:
                    st.session_state.est_parts[edit_pidx] = new_part
                    st.session_state["edit_part_idx"] = None
                    st.success(f"✅ Updated: {p_name}")
                else:
                    st.session_state.est_parts.append(new_part)
                    st.success(f"✅ Added: {p_name}  |  {total_wt:.2f} kg  |  ₹{total_wt * rate:,.0f}")
                st.session_state["edit_part_idx"] = None

        if st.session_state.est_parts:
            st.markdown("---")
            st.markdown("**Parts list — click ✏️ to edit a row**")
            for idx, p in enumerate(st.session_state.est_parts):
                c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([3, 2, 1.5, 1, 1, 1.5, 2, 0.7])
                c1.write(p.get("name", "")); c2.write(p.get("part_type", "")[:22])
                c3.write(p.get("group", "")); c4.write(p.get("material", ""))
                c5.write(f"{p.get('qty', 1):.1f}")
                c6.write(f"{p.get('total_wt_kg', 0):.1f} kg")
                c7.write(f"₹{p.get('amount', 0):,.0f}")
                if c8.button("✏️", key=f"ep_{idx}", help=f"Edit {p.get('name', '')}"):
                    st.session_state["edit_part_idx"] = idx

            tot_wt  = sum(p.get("total_wt_kg", 0) for p in st.session_state.est_parts)
            tot_amt = sum(p.get("amount", 0) for p in st.session_state.est_parts)
            st.success(f"**Total — Weight: {tot_wt:,.1f} kg  |  Amount: ₹{tot_amt:,.0f}**")

            dc1, dc2 = st.columns([3, 1])
            del_idx = dc1.number_input("Row to delete", min_value=1, max_value=len(st.session_state.est_parts), value=1, step=1)
            if dc2.button("🗑️ Delete Row", use_container_width=True):
                st.session_state.est_parts.pop(int(del_idx) - 1)
                st.session_state["edit_part_idx"] = None
            if st.button("🗑️ Clear All Parts"):
                st.session_state.est_parts = []; st.session_state["edit_part_idx"] = None

        _save_draft_bar("f2")

    # ── F3: PIPES & FLANGES ────────────────────────────────────────────────────
    with f3:
        st.markdown("##### Nozzle Pipes")
        with st.container(border=True):
            pc1, pc2, pc3, pc4, pc5 = st.columns(5)
            pp_name = pc1.text_input("Description",           placeholder='e.g. 2" Nozzle', key="pp_name")
            pp_code = pc2.selectbox("Pipe Size", pipe_rm or ["—"],                           key="pp_code")
            pp_len  = pc3.number_input("Length (m)",  value=0.2,  min_value=0.0, step=0.1,  key="pp_len")
            pp_qty  = pc4.number_input("Qty",         value=1,    min_value=1,   step=1,     key="pp_qty")
            pp_rate = pc5.number_input("Rate Override (0=master)", value=0.0, min_value=0.0, key="pp_rate")
            if pipe_rm:
                rm = rm_master.get(pp_code, {})
                st.caption(f"Selected: {rm.get('description', '')} | {rm.get('unit_wt_kg_per_m', 0)} kg/m | Rate: ₹{rm.get('rate', 0)}/kg")
            if st.button("➕ Add Pipe", type="primary", key="add_pipe"):
                rm   = rm_master.get(pp_code, {})
                rate = pp_rate if pp_rate > 0 else rm.get("rate", 0)
                wpm  = rm.get("unit_wt_kg_per_m") or 0
                wt   = wpm * pp_len * 1.05 * pp_qty
                st.session_state.est_pipes.append(dict(name=pp_name, item_code=pp_code, length_m=pp_len, qty=pp_qty, wt_per_m=wpm, total_wt_kg=round(wt, 3), rate=rate, amount=round(wt * rate, 2)))

        if st.session_state.est_pipes:
            df = pd.DataFrame(st.session_state.est_pipes)[["name", "item_code", "length_m", "qty", "total_wt_kg", "rate", "amount"]]
            df.columns = ["Description", "Code", "Length(m)", "Qty", "Wt(kg)", "Rate", "Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"Total Pipes: ₹{sum(p['amount'] for p in st.session_state.est_pipes):,.0f}")
            if st.button("🗑️ Clear Pipes"):
                st.session_state.est_pipes = []

        st.divider()
        st.markdown("##### Flanges & Fittings")
        with st.container(border=True):
            fl1, fl2, fl3, fl4 = st.columns(4)
            fl_name = fl1.text_input("Description",           placeholder='e.g. 4" #150 Flange', key="fl_name")
            fl_code = fl2.selectbox("Flange Size", flg_rm or ["—"],                               key="fl_code")
            fl_qty  = fl3.number_input("Qty", value=1, min_value=1, step=1,                       key="fl_qty")
            fl_rate = fl4.number_input("Rate Override (0=master)", value=0.0, min_value=0.0,       key="fl_rate")
            if st.button("➕ Add Flange", type="primary", key="add_flange"):
                rm   = rm_master.get(fl_code, {})
                rate = fl_rate if fl_rate > 0 else rm.get("rate", 0)
                wt   = ((rm.get("unit_wt_kg_per_m") or 0) * 1.15) * fl_qty
                st.session_state.est_flanges.append(dict(name=fl_name, item_code=fl_code, qty=fl_qty, total_wt_kg=round(wt, 3), rate=rate, amount=round(wt * rate, 2)))

        if st.session_state.est_flanges:
            df = pd.DataFrame(st.session_state.est_flanges)[["name", "item_code", "qty", "total_wt_kg", "rate", "amount"]]
            df.columns = ["Description", "Code", "Qty", "Wt(kg)", "Rate", "Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"Total Flanges: ₹{sum(p['amount'] for p in st.session_state.est_flanges):,.0f}")
            if st.button("🗑️ Clear Flanges"):
                st.session_state.est_flanges = []

        _save_draft_bar("f3")

    # ── F4: FABRICATION SERVICES ───────────────────────────────────────────────
    with f4:
        st.markdown("##### Fabrication Services — Geometry-Driven Cost")
        st.caption("Adjust rates if needed, then click ⚡ Auto-Calculate to generate all line items from shell dimensions in Tab 1.")

        dia = float(h.get("shell_dia_mm", 0))
        ht  = float(h.get("shell_ht_mm", 0))
        if dia > 0 and ht > 0:
            _, _, int_a, ext_a = calc_surface_areas(dia, ht)
            wm_prev = calc_weld_metres(dia, ht, has_jacket=bool(h.get("jacket_type", "")), has_agitator=bool(h.get("agitator_type", "")))
            gp1, gp2, gp3 = st.columns(3)
            gp1.metric("Internal Surface Area", f"{int_a:.3f} m²")
            gp2.metric("External Surface Area", f"{ext_a:.3f} m²")
            gp3.metric("Estimated Weld Length", f"{wm_prev:.1f} m")
        else:
            st.warning("⚠️ Enter Shell ID and Shell Height in Tab 1️⃣ first.")

        fr = st.session_state.fab_rates
        with st.container(border=True):
            st.markdown("**Fabrication Rates**")
            rc1, rc2, rc3 = st.columns(3)
            fr["cutting_pct_on_plates"] = rc1.number_input("Cutting % on plate RM", value=float(fr["cutting_pct_on_plates"]), min_value=0.0, step=0.5)
            fr["rolling_rate_per_m2"]   = rc2.number_input("Rolling ₹/m²",          value=float(fr["rolling_rate_per_m2"]),   min_value=0.0, step=50.0)
            moc = h.get("moc_shell", "SS316L")
            if moc in ("SS316L", "Ti", "C22", "Hastelloy"):
                fr["tig_weld_rate_per_m"] = rc3.number_input("TIG Weld ₹/m", value=float(fr["tig_weld_rate_per_m"]), min_value=0.0, step=50.0)
            else:
                fr["arc_weld_rate_per_m"] = rc3.number_input("ARC Weld ₹/m", value=float(fr["arc_weld_rate_per_m"]), min_value=0.0, step=50.0)

            rc4, rc5, rc6 = st.columns(3)
            fr["int_grind_rate_per_m2"] = rc4.number_input("Int. Grinding ₹/m²", value=float(fr["int_grind_rate_per_m2"]), min_value=0.0, step=50.0)
            fr["ext_buff_rate_per_m2"]  = rc5.number_input("Ext. Buffing ₹/m²",  value=float(fr["ext_buff_rate_per_m2"]),  min_value=0.0, step=50.0)
            fr["ep_rate_per_m2"]        = rc6.number_input("Electropolish ₹/m² (0=skip)", value=float(fr.get("ep_rate_per_m2", 0)), min_value=0.0, step=50.0)

            rc7, rc8, rc9 = st.columns(3)
            fr["assembly_fitting_hrs"]  = rc7.number_input("Assembly Hours",       value=float(fr["assembly_fitting_hrs"]), min_value=0.0, step=5.0)
            fr["assembly_rate_per_hr"]  = rc8.number_input("Assembly ₹/hr",        value=float(fr["assembly_rate_per_hr"]), min_value=0.0, step=50.0)
            fr["hydro_test_lumpsum"]    = rc9.number_input("Hydro Test ₹ (lumpsum)", value=float(fr["hydro_test_lumpsum"]), min_value=0.0, step=500.0)

            rc10, rc11, _ = st.columns(3)
            fr["dp_test_rate_per_m2"]   = rc10.number_input("DP Test ₹/m²",       value=float(fr["dp_test_rate_per_m2"]), min_value=0.0, step=10.0)
            fr["qa_doc_lumpsum"]        = rc11.number_input("QA & Docs ₹ (lumpsum)", value=float(fr["qa_doc_lumpsum"]),   min_value=0.0, step=500.0)

        col_auto, col_clear = st.columns([2, 1])
        if col_auto.button("⚡ Auto-Calculate All Fabrication Services", type="primary", use_container_width=True):
            if dia > 0 and ht > 0:
                st.session_state.est_fab = auto_fab_services(h, fr, st.session_state.est_parts)
                st.success(f"✅ Generated {len(st.session_state.est_fab)} line items  |  Total: ₹{sum(f['amount'] for f in st.session_state.est_fab):,.0f}")
            else:
                st.error("Enter Shell ID and Shell Height in Tab 1️⃣ first.")
        if col_clear.button("🗑️ Clear Fabrication", use_container_width=True):
            st.session_state.est_fab = []

        if st.session_state.est_fab:
            st.markdown("---")
            st.markdown("**Fabrication services — edit amounts if needed**")
            fab_total = 0
            for idx, fs in enumerate(st.session_state.est_fab):
                fc1, fc2, fc3, fc4, fc5 = st.columns([4, 4, 1.5, 2, 1])
                fc1.write(fs.get("service", ""))
                fc2.caption(fs.get("basis", ""))
                fc3.write(f"{fs.get('qty', '')} {fs.get('uom', '')}")
                new_amt = fc4.number_input("₹", value=float(fs.get("amount", 0)), min_value=0.0, step=100.0, label_visibility="collapsed", key=f"fab_amt_{idx}")
                st.session_state.est_fab[idx]["amount"] = new_amt
                fab_total += new_amt
                if fc5.button("🗑️", key=f"fab_del_{idx}", help="Remove"):
                    st.session_state.est_fab.pop(idx)
            st.success(f"**Total Fabrication Services: ₹{fab_total:,.0f}**")

            st.markdown("**➕ Add custom line**")
            with st.container(border=True):
                ma1, ma2, ma3, ma4 = st.columns(4)
                ma_svc   = ma1.text_input("Service description",   key="ma_svc")
                ma_basis = ma2.text_input("Basis / note",           key="ma_basis")
                ma_uom   = ma3.text_input("UOM", value="LS",        key="ma_uom")
                ma_amt   = ma4.number_input("Amount ₹", value=0.0,  key="ma_amt")
                if st.button("➕ Add Line", type="primary"):
                    st.session_state.est_fab.append({"service": ma_svc, "basis": ma_basis, "qty": 1, "uom": ma_uom, "rate": ma_amt, "amount": ma_amt})

        _save_draft_bar("f4")

    # ── F5: BOUGHT-OUT & OH ────────────────────────────────────────────────────
    with f5:
        st.markdown("##### Bought-Out Items  _(Motor, Gearbox, Seal, Fasteners, Insulation, etc.)_")
        with st.container(border=True):
            b1, b2, b3, b4, b5 = st.columns(5)
            bo_desc  = b1.text_input("Description",            placeholder="e.g. 7.5HP Motor", key="bo_d")
            bo_code  = b2.selectbox("BO Code",  bo_rm or ["—"],                                 key="bo_c")
            bo_qty   = b3.number_input("Qty",   value=1, min_value=1, step=1,                   key="bo_q")
            bo_rate  = b4.number_input("Rate Override (0=master)", value=0.0, min_value=0.0,    key="bo_r")
            bo_group = b5.selectbox("Group",    ["BO", "FASTENERS", "INSULATION", "OTHER"],     key="bo_g")
            if bo_rm:
                rm = rm_master.get(bo_code, {})
                st.caption(f"Selected: {rm.get('description', '')} | Rate: ₹{rm.get('rate', 0):,.0f} | UOM: {rm.get('uom', '')}")
            if st.button("➕ Add BO Item", type="primary", key="add_bo"):
                rm   = rm_master.get(bo_code, {})
                rate = bo_rate if bo_rate > 0 else rm.get("rate", 0)
                st.session_state.est_bo.append(dict(name=bo_desc or rm.get("description", ""), item_code=bo_code, qty=bo_qty, rate=rate, amount=round(rate * bo_qty, 2), group=bo_group))

        if st.session_state.est_bo:
            df = pd.DataFrame(st.session_state.est_bo)[["name", "item_code", "qty", "rate", "amount", "group"]]
            df.columns = ["Description", "Code", "Qty", "Rate", "Amount(₹)", "Group"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"Total Bought-Out: ₹{sum(b['amount'] for b in st.session_state.est_bo):,.0f}")
            if st.button("🗑️ Clear BO"):
                st.session_state.est_bo = []

        st.divider()
        st.markdown("##### Additional Overheads  _(any cost not covered above)_")
        with st.container(border=True):
            o1, o2, o3, o4 = st.columns(4)
            oh_sel = o1.selectbox("OH Code",                 oh_codes or ["—"],                 key="oh_sel")
            oh_qty = o2.number_input("Qty / Hours / Area",   value=1.0, min_value=0.0, step=1.0, key="oh_q")
            oh_rov = o3.number_input("Rate Override (0=master)", value=0.0, min_value=0.0,       key="oh_r")
            oh_dov = o4.text_input("Description override (optional)",                            key="oh_d")
            oh_inf = oh_master.get(oh_sel, {})
            st.caption(f"Selected: **{oh_inf.get('description', '')}** | Type: {oh_inf.get('oh_type', '')} | UOM: {oh_inf.get('uom', '')} | Rate: ₹{oh_inf.get('rate', 0):,.0f}")
            if st.button("➕ Add Overhead", type="primary", key="add_oh"):
                rate = oh_rov if oh_rov > 0 else oh_inf.get("rate", 0)
                uom  = oh_inf.get("uom", "")
                desc = oh_dov or oh_inf.get("description", "")
                if uom == "%":
                    base   = sum(p.get("amount", 0) for p in st.session_state.est_parts) + sum(p.get("amount", 0) for p in st.session_state.est_pipes) + sum(p.get("amount", 0) for p in st.session_state.est_flanges)
                    amount = base * rate / 100
                else:
                    amount = rate * oh_qty
                st.session_state.est_oh.append(dict(oh_code=oh_sel, description=desc, oh_type=oh_inf.get("oh_type", ""), uom=uom, qty=oh_qty, rate=rate, amount=round(amount, 2)))

        if st.session_state.est_oh:
            df = pd.DataFrame(st.session_state.est_oh)[["description", "oh_type", "uom", "qty", "rate", "amount"]]
            df.columns = ["Description", "Type", "UOM", "Qty", "Rate", "Amount(₹)"]
            df["Amount(₹)"] = df["Amount(₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.success(f"Total OH: ₹{sum(o['amount'] for o in st.session_state.est_oh):,.0f}")
            if st.button("🗑️ Clear OH"):
                st.session_state.est_oh = []

        _save_draft_bar("f5")

    # ── F6: SUMMARY & SAVE ─────────────────────────────────────────────────────
    with f6:
        eq_info = EQUIPMENT_TYPES.get(h["equipment_type"], {})
        lo, hi  = eq_info.get("margin_hint", (10, 18))
        st.info(f"Suggested margin for **{h['equipment_type']}**: {lo}–{hi}%  |  Labour: **{eq_info.get('labour_norm', 'Medium')}**")

        # Current estimation info bar — read only, set in Tab 1
        qtn_now = h.get("qtn_number","") or ""
        cust_now = h.get("customer_name","") or "no customer"
        rev_now  = h.get("revision","R0")
        stat_now = h.get("status","Draft")
        if qtn_now:
            st.success(f"💾 **{qtn_now}** {rev_now} — {cust_now}  |  Status: {stat_now}  |  {len(st.session_state.est_parts)} parts  |  {len(st.session_state.est_fab)} fab lines")
        else:
            st.warning("⚠️ No Quotation Number set — go to Tab 1️⃣ Header and enter a QTN number before saving.")

        s1, s2, s3, s4, s5, s6 = st.columns(6)
        h["profit_margin_pct"] = s1.number_input("Profit %",      value=float(h["profit_margin_pct"]), min_value=0.0, max_value=60.0, step=0.5)
        h["contingency_pct"]   = s2.number_input("Contingency %", value=float(h["contingency_pct"]),   min_value=0.0, max_value=20.0, step=0.5)
        h["engg_design_amt"]   = s3.number_input("Engg & ASME ₹", value=float(h["engg_design_amt"]),   min_value=0.0, step=1000.0)
        h["packing_amt"]       = s4.number_input("Packing ₹",     value=float(h["packing_amt"]),       min_value=0.0, step=500.0)
        h["freight_amt"]       = s5.number_input("Freight ₹",     value=float(h["freight_amt"]),       min_value=0.0, step=500.0)
        h["gst_pct"]           = s6.number_input("GST %",         value=float(h["gst_pct"]),           min_value=0.0, max_value=28.0, step=0.5)

        T = calc_totals(
            st.session_state.est_parts, st.session_state.est_pipes, st.session_state.est_flanges,
            st.session_state.est_fab, st.session_state.est_bo, st.session_state.est_oh,
            h["profit_margin_pct"], h["contingency_pct"],
            h["packing_amt"], h["freight_amt"], h["gst_pct"], h["engg_design_amt"],
        )

        left, right = st.columns([3, 2])
        with left:
            st.markdown("**Cost Breakup**")
            cost_df = pd.DataFrame([
                ("Plates & Parts",        T["tot_plates"]),
                ("Pipes",                 T["tot_pipes"]),
                ("Flanges",               T["tot_flanges"]),
                ("▶ Total Raw Material",  T["tot_rm"]),
                ("Fabrication Services",  T["tot_fab"]),
                ("Bought-Out Items",      T["tot_bo"]),
                ("Additional Overheads",  T["tot_oh"]),
                ("Engg & ASME Design",    T["engg_design"]),
                ("▶ Total Mfg Cost",      T["tot_mfg"]),
                ("Contingency",           T["cont_amt"]),
                ("Profit",                T["profit_amt"]),
                ("Packing & Freight",     T["packing"] + T["freight"]),
                ("▶ Ex-Works Price",      T["ex_works"]),
                ("GST",                   T["gst_amt"]),
                ("▶ FOR Price",           T["for_price"]),
            ], columns=["Component", "Amount (₹)"])
            cost_df["Amount (₹)"] = cost_df["Amount (₹)"].map(lambda x: f"₹{x:,.0f}")
            st.dataframe(cost_df, use_container_width=True, hide_index=True)

        with right:
            st.markdown("**Margin Health**")
            for label, val, lo_t, hi_t in [
                ("RM %",      T["rm_pct"],           45, 60),
                ("Fab Svc %", T["fab_pct"],           15, 25),
                ("OH %",      T["oh_pct"],             8, 15),
                ("Profit %",  T["profit_pct_actual"], 12, 20),
            ]:
                icon = "✅" if lo_t <= val <= hi_t else "⚠️"
                st.write(f"{icon} **{label}** {val:.1f}%  _(target {lo_t}–{hi_t}%)_")
            for iss in margin_issues(T):
                st.warning(iss)
            if not margin_issues(T):
                st.success("All margins healthy!")
            st.markdown("**What-If: Ex-Works at Different Margins**")
            st.dataframe(pd.DataFrame([{
                "Margin": f"{m}%",
                "Ex-Works (₹)": f"₹{(T['cbm'] * (1 + m / 100) + T['packing'] + T['freight']):,.0f}",
            } for m in [8, 10, 12, 15, 18, 20]]), hide_index=True, use_container_width=True)

        st.divider()
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Raw Material", f"₹{T['tot_rm']:,.0f}")
        k2.metric("Fabrication",  f"₹{T['tot_fab']:,.0f}")
        k3.metric("Total Mfg",   f"₹{T['tot_mfg']:,.0f}")
        k4.metric("Ex-Works",    f"₹{T['ex_works']:,.0f}")
        k5.metric("GST",         f"₹{T['gst_amt']:,.0f}")
        k6.metric("FOR Price",   f"₹{T['for_price']:,.0f}")
        st.divider()

        b1, b2, b3 = st.columns(3)

        if b1.button("💾 Save & Close", type="primary", use_container_width=True, disabled=not h["qtn_number"]):
            if _do_save(reset_after=True):
                st.rerun()

        if b2.button("🔄 Reset / New", use_container_width=True):
            _reset_form(); st.rerun()

        cust_data = next((c for c in clients if c["name"] == h.get("customer_name", "")), {})

        # ── Download options ──────────────────────────────────────────────────
        st.divider()
        st.markdown("**📄 Download Customer Quotation**")
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.caption("**Standard Quote** — clean single price. Use for most customers.")
            dl_col1.download_button(
                "📄 Download Standard Quote",
                generate_docx(h, cust_data, T, st.session_state.est_fab, show_breakup=False),
                file_name=f"{h.get('qtn_number','QTN')}_{h.get('revision','R0')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True, type="primary",
            )
        with dl_col2:
            st.caption("**With Scope Breakup** — use when customer asks for breakup.")
            dl_col2.download_button(
                "📋 Download Quote with Breakup",
                generate_docx(h, cust_data, T, st.session_state.est_fab, show_breakup=True),
                file_name=f"{h.get('qtn_number','QTN')}_{h.get('revision','R0')}_breakup.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )

        st.divider()
        st.markdown("**📊 Download Internal Estimation Fact Sheet** _(for cross-checking against Excel)_")
        st.caption("Shows all dimensions, geometry formulas used, weights, rates and cost summary across 6 sheets. Not for customers.")
        if OPENPYXL_OK:
            st.download_button(
                "📊 Download Estimation Fact Sheet (.xlsx)",
                generate_fact_sheet_xlsx(
                    h, st.session_state.est_parts, st.session_state.est_pipes,
                    st.session_state.est_flanges, st.session_state.est_fab,
                    st.session_state.est_bo, st.session_state.est_oh,
                    st.session_state.fab_rates, T,
                ),
                file_name=f"{h.get('qtn_number','QTN')}_{h.get('revision','R0')}_FactSheet.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.warning("📊 Fact Sheet requires **openpyxl**. Add `openpyxl` to requirements.txt and redeploy.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB: QUOTE EDITOR
# Full control over every word that goes to the customer.
# Engineer edits all sections here before downloading.
# ══════════════════════════════════════════════════════════════════════════════
with TAB_QUOTE:
    h    = st.session_state.est_hdr
    _qno = h.get("qtn_number","") or ""
    _cno = h.get("customer_name","") or ""

    if not _qno:
        st.warning("⚠️ No estimation loaded. Go to ➕ New / Edit → Tab 1 and load or create an estimation first.")
    else:
        st.subheader(f"✍️ Quote Editor — {_qno}  |  {_cno}")
        st.caption("Edit every section below. What you see here is exactly what prints in the customer quotation. Download when ready.")

        # ── helpers ──────────────────────────────────────────────────────────
        def qe_section(label, icon=""):
            st.markdown(f"**{icon} {label}**")

        def qe_box(key, default, height=120, help_text=""):
            """Editable text area that writes back to session state."""
            val = st.text_area(
                key, value=h.get(key, default), height=height,
                label_visibility="collapsed", help=help_text,
                key=f"qe_{key}",
            )
            h[key] = val
            return val

        # ── SECTION 1 — Offer & Customer (read-only, from header) ────────────
        with st.expander("📋 Section 1 — Offer & Customer Details", expanded=True):
            st.caption("Set in Tab 1 Header. Change fields there to update here.")
            si1, si2, si3 = st.columns(3)
            si1.markdown(f"**QTN:** {h.get('qtn_number','')}  |  **Rev:** {h.get('revision','R0')}")
            si2.markdown(f"**Customer:** {h.get('customer_name','')}")
            si3.markdown(f"**Equipment:** {h.get('equipment_desc','')}")
            si1.markdown(f"**Prepared By:** {h.get('prepared_by','')}  |  **Checked By:** {h.get('checked_by','')}")
            si2.markdown(f"**Status:** {h.get('status','Draft')}")
            si3.markdown(f"**Date:** {date.today().strftime('%d %B %Y')}")

        # ── SECTION 2 — Technical Design Basis ───────────────────────────────
        with st.expander("🔧 Section 2 — Technical Design Basis", expanded=False):
            st.caption("Core dimensions come from Tab 1. Edit the surface finish and any additional technical notes here.")
            t2c1, t2c2 = st.columns(2)
            h["surface_finish"] = t2c1.text_input(
                "Surface Finish", value=h.get("surface_finish","Internal: Ra ≤ 0.8 μm  |  External: Buffed"),
                key="qe_sf",
            )
            h["design_code"] = t2c2.text_input(
                "Design Code", value=h.get("design_code","ASME Sec VIII Div 1"),
                key="qe_dc",
            )
            h["design_pressure"] = t2c1.text_input(
                "Design Pressure", value=h.get("design_pressure","FV to 4.5 Bar"),
                key="qe_dp",
            )
            h["design_temp"] = t2c2.text_input(
                "Design Temperature", value=h.get("design_temp","-50 to 250°C"),
                key="qe_dt",
            )
            h["jacket_type"] = t2c1.text_input(
                "Jacket / Heating", value=h.get("jacket_type",""),
                key="qe_jt",
            )
            h["agitator_type"] = t2c2.text_input(
                "Agitator / Drive", value=h.get("agitator_type",""),
                key="qe_at",
            )

        # ── SECTION 3 — Scope of Supply ───────────────────────────────────────
        with st.expander("📦 Section 3 — Scope of Supply", expanded=False):
            qe_section("Scope items — one per line, each becomes a bullet point")
            default_scope = (
                "Pressure vessel / equipment fabricated as per approved GA drawing\n"
                "All nozzles, manholes, handholes and process connections per nozzle schedule\n"
                "Jacket / limpet coil / half-pipe with insulation jacket (where applicable)\n"
                "Agitator complete with gearbox, motor and mechanical seal (where applicable)\n"
                "Support structure — lugs, legs or saddles as applicable\n"
                "Internal grinding and buffing to specified Ra surface finish\n"
                "Equipment nameplate with tag number and serial number"
            )
            qe_box("scope_items", default_scope, height=200,
                   help_text="One item per line → becomes a bullet in the quotation")

            qe_section("Exclusions — one per line")
            default_excl = (
                "Civil / structural works\n"
                "Electrical & Instrumentation\n"
                "Erection & commissioning at site\n"
                "DQ / IQ / OQ / PQ validation\n"
                "Freight, insurance and unloading at site\n"
                "Import duties if applicable"
            )
            qe_box("scope_exclusions", default_excl, height=140,
                   help_text="One exclusion per line")

            st.caption("💡 Add for ANFD: 'Filter plate, filter media and gaskets' | for RCVD: 'Condenser, receiver and vacuum system' | for pharma: 'cGMP compliance documentation'")

        # ── SECTION 4 — Manufacturing & Quality ───────────────────────────────
        with st.expander("🔬 Section 4 — Manufacturing & Quality Assurance", expanded=False):
            qe_section("Opening paragraph")
            default_intro = (
                "B&G Engineering Industries operates as an engineering-led manufacturer. "
                "Every project is built to ASME Section VIII Division 1 requirements "
                "with full documentation and traceability."
            )
            qe_box("quality_intro", default_intro, height=80)

            qe_section("Quality points — one per line, each becomes a bullet point")
            default_qp = (
                "Raw material procurement with original Mill Test Certificates (MTC) for all pressure parts\n"
                "100% Positive Material Identification (PMI) verification before cutting\n"
                "Heat number and cast number traceability maintained throughout fabrication\n"
                "Qualified welders — WPS / PQR compliant, TIG welding for all SS316L pressure joints\n"
                "Precision plasma / laser cutting and CNC-controlled plate rolling\n"
                "Pharma-grade internal grinding to Ra ≤ 0.8 μm and external mechanical buffing\n"
                "Dimensional inspection against approved GA drawings at each stage\n"
                "Hydrostatic / pneumatic / vacuum leak test as per ASME Sec VIII Div 1\n"
                "Dye Penetrant (DP) testing on all critical welds\n"
                "Complete QA dossier prepared and delivered with equipment\n"
                "Factory Acceptance Test (FAT) support at works on request"
            )
            qe_box("quality_points", default_qp, height=300,
                   help_text="One point per line. Add/remove based on equipment type and client URS.")

            st.caption(
                "💡 Equipment-specific points to add:\n"
                "**ANFD** → Filter plate flatness and surface finish inspection | Filter media compatibility test\n"
                "**RCVD** → Vacuum integrity test to -1 bar for 30 min minimum | Cone rotation and discharge test\n"
                "**Condenser** → Tube-to-tubesheet weld DP test | Tube hydraulic test at 1.5x design pressure\n"
                "**Pharma** → GAMP5 documentation support available | 3.1 material certs per EN 10204\n"
                "**ATEX** → ATEX zone compliance — electrical items in customer scope | Earth continuity check"
            )

        # ── SECTION 5 — Documentation ─────────────────────────────────────────
        with st.expander("📋 Section 5 — Documentation Deliverables", expanded=False):
            qe_section("Document list — one per line")
            default_docs = (
                "General Arrangement (GA) Drawing — IFC revision\n"
                "Nozzle orientation and schedule drawing\n"
                "Bill of Materials (BOM)\n"
                "Mill Test Certificates (MTC) for all pressure parts\n"
                "PMI verification records\n"
                "Weld map and weld log\n"
                "DP / RT inspection reports\n"
                "Dimensional inspection report\n"
                "Hydrostatic / leak test certificate\n"
                "Surface finish inspection record (Ra measurement)\n"
                "Inspection and Release Note (IRN)\n"
                "Equipment nameplate photograph"
            )
            qe_box("doc_deliverables", default_docs, height=280,
                   help_text="One document per line. Add client-specific requirements.")

            st.caption(
                "💡 Add for regulated customers:\n"
                "ASME U-stamp data report (if U-stamp required) | EN 10204 3.1 material certs | "
                "Radiographic (RT) test report | Positive pressure decay test record | "
                "Passivation certificate | Calibration certificates for test instruments"
            )

        # ── SECTION 6 — Commercial Terms ─────────────────────────────────────
        with st.expander("💰 Section 6 — Commercial Terms", expanded=False):
            st.markdown("**Payment Terms**")
            h["payment_terms"] = st.text_area(
                "Payment Terms", height=70, label_visibility="collapsed",
                value=h.get("payment_terms","40% advance along with Purchase Order  |  50% against Pro-forma invoice on readiness for dispatch  |  10% on delivery"),
                key="qe_pt",
            )
            c1, c2 = st.columns(2)
            h["delivery_weeks"] = c1.text_input(
                "Delivery (weeks)", value=h.get("delivery_weeks","12–16"), key="qe_dw",
            )
            h["delivery_note"] = c2.text_input(
                "Delivery note", value=h.get("delivery_note","Subject to availability of raw material at time of order."),
                key="qe_dn",
            )
            h["offer_validity"] = st.text_area(
                "Offer Validity", height=60, label_visibility="collapsed",
                value=h.get("offer_validity","This offer is valid for 7 calendar days from the date above. Prices subject to change if raw material rates move by more than 3%."),
                key="qe_ov",
            )
            st.markdown("**Warranty**")
            h["warranty_clause"] = st.text_area(
                "Warranty", height=80, label_visibility="collapsed",
                value=h.get("warranty_clause","12 months from date of commissioning or 18 months from date of dispatch, whichever is earlier. Covers manufacturing defects under normal operating conditions as per design basis."),
                key="qe_wc",
            )
            st.markdown("**Inspection Rights**")
            h["inspection_clause"] = st.text_area(
                "Inspection", height=70, label_visibility="collapsed",
                value=h.get("inspection_clause","Customer may depute inspector for stage and final inspection at our works. Third-party inspection (TPI) agency charges, if any, are in customer scope."),
                key="qe_ic",
            )
            st.markdown("**Price Basis**")
            h["price_basis"] = st.text_area(
                "Price Basis", height=70, label_visibility="collapsed",
                value=h.get("price_basis","Ex-Works, Pashamylaram, Hyderabad — 502307. Packing in MS crate included. Freight, insurance and unloading at site excluded."),
                key="qe_pb",
            )
            st.markdown("**GST / Taxes Clause**")
            h["gst_clause"] = st.text_area(
                "GST Clause", height=60, label_visibility="collapsed",
                value=h.get("gst_clause","GST @ 18% (HSN 8419) as applicable at time of invoicing. Any new statutory levy introduced after offer date will be charged additionally."),
                key="qe_gc",
            )
            st.markdown("**Special Notes / Additional Conditions** _(printed at end of commercial section)_")
            h["special_notes"] = st.text_area(
                "Special Notes", height=100, label_visibility="collapsed",
                value=h.get("special_notes",""),
                help="Add client-specific conditions: GAMP5, ATEX zone, clean room, specific standards, any deviations from URS.",
                key="qe_sn",
            )

        st.divider()

        # ── Download buttons ──────────────────────────────────────────────────
        st.markdown("**📄 Download Final Quotation**")
        st.caption("Edits above are captured in memory. Save Draft to persist, then download.")

        # Recalculate totals for download
        _qe_clients  = load_clients_full()
        _qe_cust     = next((c for c in _qe_clients if c["name"] == h.get("customer_name","")), {})
        _rm_master_qe = load_rm_master()

        _qe_parts   = st.session_state.est_parts
        _qe_pipes   = st.session_state.est_pipes
        _qe_flanges = st.session_state.est_flanges
        _qe_fab     = st.session_state.est_fab
        _qe_bo      = st.session_state.est_bo
        _qe_oh      = st.session_state.est_oh

        _qe_T = calc_totals(
            _qe_parts, _qe_pipes, _qe_flanges, _qe_fab, _qe_bo, _qe_oh,
            float(h.get("profit_margin_pct",10)), float(h.get("contingency_pct",0)),
            float(h.get("packing_amt",5000)), float(h.get("freight_amt",10000)),
            float(h.get("gst_pct",18)), float(h.get("engg_design_amt",25000)),
        )

        qe_dl1, qe_dl2, qe_dl3, qe_dl4 = st.columns(4)
        qe_dl1.download_button(
            "📄 Standard Quote",
            generate_docx(h, _qe_cust, _qe_T, _qe_fab, show_breakup=False),
            file_name=f"{h.get('qtn_number','QTN')}_{h.get('revision','R0')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True, type="primary", key="qe_dl_std",
        )
        qe_dl2.download_button(
            "📋 With Scope Breakup",
            generate_docx(h, _qe_cust, _qe_T, _qe_fab, show_breakup=True),
            file_name=f"{h.get('qtn_number','QTN')}_{h.get('revision','R0')}_breakup.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True, key="qe_dl_bk",
        )
        if OPENPYXL_OK:
            qe_dl3.download_button(
                "📊 Fact Sheet (.xlsx)",
                generate_fact_sheet_xlsx(
                    h, st.session_state.est_parts, st.session_state.est_pipes,
                    st.session_state.est_flanges, _qe_fab,
                    st.session_state.est_bo, st.session_state.est_oh,
                    st.session_state.fab_rates, _qe_T,
                ),
                file_name=f"{h.get('qtn_number','QTN')}_{h.get('revision','R0')}_FactSheet.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True, key="qe_dl_fs",
            )
        else:
            qe_dl3.warning("Add `openpyxl` to requirements.txt")
        if qe_dl4.button("💾 Save Draft", use_container_width=True, type="primary", key="qe_save"):
            _do_save(reset_after=False)


# ══════════════════════════════════════════════════════════════════════════════
# TAB: SIMILAR EQUIPMENT
# ══════════════════════════════════════════════════════════════════════════════
with TAB_SIMILAR:
    st.subheader("🔍 Similar Equipment — Price Benchmark")
    st.caption("Search past estimations by type and capacity range to benchmark your current pricing.")
    sc1, sc2, sc3 = st.columns(3)
    s_equip  = sc1.selectbox("Equipment Type", ["All"] + EQUIPMENT_NAMES, key="sim_eq")
    s_cap_lo = sc2.number_input("Capacity from (Ltrs)", value=0.0,     min_value=0.0, key="sim_lo")
    s_cap_hi = sc3.number_input("Capacity to (Ltrs)",   value=99999.0, min_value=0.0, key="sim_hi")
    s_cust   = st.text_input("Customer contains (optional)", key="sim_cu")

    results = []
    for est in load_all_estimations():
        if s_equip != "All" and est.get("equipment_type") != s_equip: continue
        cap = float(est.get("capacity_ltrs") or 0)
        if not (s_cap_lo <= cap <= s_cap_hi): continue
        if s_cust and s_cust.lower() not in (est.get("customer_name", "") or "").lower(): continue
        T = calc_totals(
            json.loads(est.get("parts_json")   or "[]"), json.loads(est.get("pipes_json")   or "[]"),
            json.loads(est.get("flanges_json") or "[]"), json.loads(est.get("fab_json")     or "[]"),
            json.loads(est.get("bo_json")      or "[]"), json.loads(est.get("oh_json")      or "[]"),
            float(est.get("profit_margin_pct") or 10), float(est.get("contingency_pct") or 0),
            float(est.get("packing_amt") or 0), float(est.get("freight_amt") or 0),
            float(est.get("gst_pct") or 18), float(est.get("engg_design_amt") or 0),
        )
        results.append({
            "QTN":      est.get("qtn_number", ""), "Customer": est.get("customer_name", ""),
            "Equipment": est.get("equipment_desc", ""), "Cap (L)": cap,
            "Status":   est.get("status", ""), "Ex-Works": f"₹{T['ex_works']:,.0f}",
            "FOR Price": f"₹{T['for_price']:,.0f}", "Margin %": f"{T['profit_pct_actual']:.1f}%",
            "Date":     str(est.get("updated_at", ""))[:10],
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
    mt1, mt2 = st.tabs(["🔩 RM & BO Master", "⚙️ OH Master"])

    with mt1:
        st.subheader("Raw Material & Bought-Out Master")
        df_rm = pd.DataFrame(sb_fetch("est_rm_master", order="category"))
        if not df_rm.empty:
            st.dataframe(df_rm[["ref_code", "description", "category", "material", "spec", "size", "uom", "rate", "unit_wt_kg_per_m", "active"]], use_container_width=True, hide_index=True)
        with st.expander("➕ Add / Update Item"):
            with st.form("rm_add_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                rc = c1.text_input("Ref Code (unique)"); desc = c2.text_input("Description")
                c1, c2, c3 = st.columns(3)
                cat = c1.selectbox("Category", ["RM", "BO"]); rmt = c2.text_input("Type"); mat = c3.text_input("Material")
                c1, c2, c3, c4 = st.columns(4)
                spec = c1.text_input("Spec"); sz = c2.text_input("Size")
                uom  = c3.selectbox("UOM", ["Kg", "Nos", "Set", "LS", "Sq.M"])
                rate = c4.number_input("Rate ₹", min_value=0.0)
                uwt  = st.number_input("Unit Wt kg/m (pipes only)", min_value=0.0)
                if st.form_submit_button("Save"):
                    if sb_insert("est_rm_master", dict(ref_code=rc, description=desc, category=cat, rm_type=rmt, material=mat, spec=spec, size=sz, uom=uom, rate=rate, unit_wt_kg_per_m=uwt if uwt > 0 else None, active="Yes")):
                        st.cache_data.clear(); st.success(f"Saved {rc}"); st.rerun()

    with mt2:
        st.subheader("Overhead Master")
        df_oh = pd.DataFrame(sb_fetch("est_oh_master", order="oh_type"))
        if not df_oh.empty:
            st.dataframe(df_oh[["oh_code", "description", "oh_type", "uom", "rate", "source"]], use_container_width=True, hide_index=True)
        with st.expander("➕ Add / Update OH"):
            with st.form("oh_add_form", clear_on_submit=True):
                c1, c2, c3, c4, c5 = st.columns(5)
                oc = c1.text_input("OH Code"); od = c2.text_input("Description")
                ot = c3.selectbox("Type", ["LABOUR", "LABOUR_BUFF", "CONSUMABLES", "TESTING", "DOCS", "PACKING", "TRANSPORT", "MISC", "ELECTRO_POLISH"])
                ou = c4.selectbox("UOM", ["Hr", "Sq.M", "%", "LS"])
                or_ = c5.number_input("Rate", min_value=0.0)
                if st.form_submit_button("Save"):
                    if sb_insert("est_oh_master", dict(oh_code=oc, description=od, oh_type=ot, uom=ou, rate=or_, source="Internal")):
                        st.cache_data.clear(); st.success(f"Saved {oc}"); st.rerun()
