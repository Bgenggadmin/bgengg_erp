"""
Offer DOCX Generator — Produces B&G-branded quotation documents.

Uses python-docx for document generation with custom styling
matching B&G brand colors (red/pink), logo, and table formatting.

Structure mirrors the 11-part offer template:
  Cover → TOC → PART I..PART XI
"""
import io
from pathlib import Path
from datetime import datetime

from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsmap
from docx.oxml import OxmlElement

from bg_offer_generator.utils.brand import (
    BRAND, DOCX_COLORS, FONT_PRIMARY, FONT_HEADING, COMPANY,
    COVER_LETTER_INTRO, OFFER_TOC,
)


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------
def _set_cell_bg(cell, hex_color: str):
    """Set table cell background color."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:fill'), hex_color)
    shd.set(qn('w:val'), 'clear')
    tc_pr.append(shd)


def _set_cell_borders(cell, color: str = DOCX_COLORS["border_gray"]):
    """Set cell borders."""
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = OxmlElement('w:tcBorders')
    for border_name in ['top', 'left', 'bottom', 'right']:
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), '4')
        border.set(qn('w:color'), color)
        tc_borders.append(border)
    tc_pr.append(tc_borders)


def _add_paragraph(doc, text: str, bold: bool = False, size: int = 11,
                   color_hex: str = None, alignment=None, space_after: int = 6):
    p = doc.add_paragraph()
    if alignment is not None:
        p.alignment = alignment
    run = p.add_run(text)
    run.font.name = FONT_PRIMARY
    run.font.size = Pt(size)
    run.bold = bold
    if color_hex:
        run.font.color.rgb = RGBColor.from_string(color_hex)
    p.paragraph_format.space_after = Pt(space_after)
    return p


def _add_heading(doc, text: str, level: int = 1):
    """Add a branded heading."""
    h = doc.add_paragraph()
    if level == 1:
        h.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = h.add_run(text)
        run.font.size = Pt(18)
        run.bold = True
        run.font.color.rgb = RGBColor.from_string(DOCX_COLORS["primary_red"])
        run.font.name = FONT_HEADING
        h.paragraph_format.space_before = Pt(18)
        h.paragraph_format.space_after = Pt(12)
    elif level == 2:
        run = h.add_run(text)
        run.font.size = Pt(14)
        run.bold = True
        run.font.color.rgb = RGBColor.from_string(DOCX_COLORS["primary_red"])
        run.font.name = FONT_HEADING
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(6)
    else:
        run = h.add_run(text)
        run.font.size = Pt(12)
        run.bold = True
        run.font.color.rgb = RGBColor.from_string(DOCX_COLORS["dark_text"])
        run.font.name = FONT_HEADING
        h.paragraph_format.space_before = Pt(10)
        h.paragraph_format.space_after = Pt(4)
    return h


def _add_section_title(doc, part_label: str, part_title: str):
    """Big branded part banner."""
    doc.add_page_break()
    # Small label
    p1 = doc.add_paragraph()
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r1 = p1.add_run(part_label)
    r1.font.size = Pt(14)
    r1.bold = True
    r1.font.color.rgb = RGBColor.from_string(DOCX_COLORS["accent_pink"])
    r1.font.name = FONT_HEADING
    # Big title
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r2 = p2.add_run(part_title)
    r2.font.size = Pt(22)
    r2.bold = True
    r2.font.color.rgb = RGBColor.from_string(DOCX_COLORS["primary_red"])
    r2.font.name = FONT_HEADING
    p2.paragraph_format.space_after = Pt(24)
    # Red underline
    _add_horizontal_line(doc, color=DOCX_COLORS["primary_red"])


def _add_horizontal_line(doc, color: str = None):
    """Insert a thin horizontal rule."""
    p = doc.add_paragraph()
    p_pr = p._p.get_or_add_pPr()
    p_bdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '12')
    bottom.set(qn('w:color'), color or DOCX_COLORS["primary_red"])
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def _make_table(doc, data: list, header: list = None, col_widths: list = None):
    """
    Create a table with B&G styling.
    data: list of rows (each row is a list of cell text)
    header: optional header row
    col_widths: optional list of widths in inches
    """
    n_rows = len(data) + (1 if header else 0)
    n_cols = len(data[0]) if data else (len(header) if header else 1)
    table = doc.add_table(rows=n_rows, cols=n_cols)
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    row_idx = 0
    if header:
        for col_idx, h_text in enumerate(header):
            cell = table.cell(0, col_idx)
            _set_cell_bg(cell, DOCX_COLORS["table_header"])
            _set_cell_borders(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            cell.text = ""
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(str(h_text))
            run.font.bold = True
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor.from_string("FFFFFF")
            run.font.name = FONT_PRIMARY
        row_idx = 1

    for r_i, row in enumerate(data):
        alt_bg = (r_i % 2 == 1)
        for col_idx, value in enumerate(row):
            cell = table.cell(row_idx + r_i, col_idx)
            if alt_bg:
                _set_cell_bg(cell, DOCX_COLORS["table_row_alt"])
            _set_cell_borders(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            cell.text = ""
            p = cell.paragraphs[0]
            run = p.add_run(str(value) if value is not None else "")
            run.font.size = Pt(10)
            run.font.name = FONT_PRIMARY

    if col_widths:
        for col_idx, width_in in enumerate(col_widths):
            for row in table.rows:
                row.cells[col_idx].width = Inches(width_in)
    return table




# ---------------------------------------------------------------------
# Image insertion helper — accepts file path OR bytes OR BytesIO
# ---------------------------------------------------------------------
def _add_picture_flexible(run, source, width_inches):
    """Insert a picture from a file path, bytes, or BytesIO object."""
    import io
    if source is None:
        return False
    try:
        if isinstance(source, (bytes, bytearray)):
            run.add_picture(io.BytesIO(source), width=Inches(width_inches))
            return True
        if isinstance(source, io.IOBase) or hasattr(source, "read"):
            run.add_picture(source, width=Inches(width_inches))
            return True
        # Treat as file path
        p = Path(str(source))
        if p.exists():
            run.add_picture(str(p), width=Inches(width_inches))
            return True
    except Exception:
        pass
    return False

# ---------------------------------------------------------------------
# MAIN GENERATOR
# ---------------------------------------------------------------------
def generate_offer_docx(data: dict, logo_path: str = None,
                          tagline_path: str = None,
                          hero_path: str = None) -> bytes:
    """
    Generate a branded offer DOCX and return as bytes.

    data: full offer data dict (see default_data.py for structure)
    logo_path / tagline_path / hero_path: paths to brand assets
    """
    doc = Document()

    # Page setup
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.0)
        section.right_margin = Cm(2.0)

    # Default font
    style = doc.styles['Normal']
    style.font.name = FONT_PRIMARY
    style.font.size = Pt(11)

    # Headers/footers
    _add_header_footer(doc, data, logo_path)

    # ============================================
    # COVER PAGE
    # ============================================
    _build_cover_page(doc, data, logo_path, tagline_path, hero_path)

    # ============================================
    # COVER LETTER
    # ============================================
    _build_cover_letter(doc, data)

    # ============================================
    # TABLE OF CONTENTS (simple bulleted)
    # ============================================
    doc.add_page_break()
    _add_heading(doc, "OFFER INDEX", level=1)
    toc_data = [[toc[0], toc[1]] for toc in OFFER_TOC]
    _make_table(doc, toc_data, header=["PART", "CONTENT"],
                 col_widths=[1.2, 5.0])

    # ============================================
    # PART I: EXECUTIVE SUMMARY
    # ============================================
    _add_section_title(doc, "PART – I", "EXECUTIVE SUMMARY")
    for para in data["executive_summary"].strip().split("\n\n"):
        _add_paragraph(doc, para, size=11)

    # ============================================
    # PART II: PROCESS DESCRIPTION
    # ============================================
    _add_section_title(doc, "PART – II", "PROCESS DESCRIPTION")
    pd_data = data["process_description"]

    _add_heading(doc, "Stripper System", level=2)
    for para in pd_data["stripper"].strip().split("\n\n"):
        _add_paragraph(doc, para)

    _add_heading(doc, "Multi-Effect Evaporator", level=2)
    n_eff = pd_data.get("n_effects", 4)
    for para in pd_data["mee"].format(n_effects=n_eff).strip().split("\n\n"):
        _add_paragraph(doc, para)

    _add_heading(doc, "Agitated Thin Film Dryer (ATFD)", level=2)
    for para in pd_data["atfd"].strip().split("\n\n"):
        _add_paragraph(doc, para)

    # ============================================
    # PART III: PROCESS FLOW DIAGRAM
    # ============================================
    _add_section_title(doc, "PART – III", "PROCESS FLOW DIAGRAM")
    _add_paragraph(doc, "[Process Flow Diagram to be inserted by user]",
                    size=10, color_hex="888888",
                    alignment=WD_ALIGN_PARAGRAPH.CENTER)
    _add_paragraph(doc,
        "Flow: Effluent Feed → Stripper Column → Multi-Effect Evaporator → ATFD → Dry Solids",
        bold=True, alignment=WD_ALIGN_PARAGRAPH.CENTER)

    # ============================================
    # PART IV: PLANT ECONOMICS & OPEX
    # ============================================
    _add_section_title(doc, "PART – IV", "ESTIMATED PLANT ECONOMICS & OPEX")
    _add_heading(doc, "BG ECOX-ZLD SYSTEM ADVANTAGE", level=3)
    econ = data["economics"]
    econ_data = [
        ["MEE Steam Consumption",
         f"{econ['conventional_steam_kgh']} Kg/h",
         f"{econ['ecox_steam_kgh']} Kg/h",
         f"Steam reduction up to ~{econ['steam_reduction_pct']}%"],
        ["Annual Steam Usage",
         f"{econ['conventional_annual_steam_tons']} tons/year",
         f"{econ['ecox_annual_steam_tons']} tons/year",
         f"{econ['annual_steam_savings_tons']} tons/year (Savings)"],
        ["Operating Cost",
         f"₹{econ['conventional_annual_cost_cr']} Cr/year",
         f"₹{econ['ecox_annual_cost_cr']} Cr/year",
         f"~₹{econ['annual_savings_lakhs']} Lakhs/Year (Savings)"],
    ]
    _make_table(doc, econ_data,
                 header=["Method", "Conventional Evaporation", "BG ECOX-ZLD", "Benefit"],
                 col_widths=[1.5, 1.8, 1.5, 2.0])
    _add_paragraph(doc,
        f"Note: The above figures are based on {econ['operating_hours_day']} hrs/Day Operation, "
        f"{econ['operating_days_year']} Days/Year, and Steam cost of ₹{econ['steam_cost_inr_kg']}/Kg. "
        "Figures are tentative and indicative.",
        size=9, color_hex="666666")

    # ============================================
    # PART V: TECHNICAL DETAILS & UTILITIES
    # ============================================
    _add_section_title(doc, "PART – V", "TECHNICAL DETAILS & UTILITIES")

    _add_heading(doc, "Feed Parameters", level=3)
    fp = data["feed_parameters"]
    feed_rows = [
        ["Feed / Capacity", "KLD", fp["capacity_kld"]],
        ["Feed pH", "-", fp["feed_ph"]],
        ["Total COD", "PPM", f"{fp['total_cod_ppm']:,}"],
        ["Volatile Organic Solvents", "PPM", f"{fp['volatile_organic_solvents_ppm']:,}"],
        ["Total Solids", "% w/w", fp["total_solids_pct"]],
        ["Suspended Solids", "PPM", fp["suspended_solids_ppm"]],
        ["Feed Temperature", "°C", fp["feed_temp_c"]],
        ["Total Hardness", "PPM", fp["total_hardness_ppm"]],
        ["Silica", "PPM", fp["silica_ppm"]],
        ["Free Chloride", "PPM", fp["free_chloride_ppm"]],
        ["Feed Nature", "-", fp["feed_nature"]],
    ]
    _make_table(doc, feed_rows, header=["Parameter", "UOM", "Value"],
                 col_widths=[2.8, 1.0, 2.7])

    _add_heading(doc, "System Technical Specifications", level=3)
    ts = data["technical_specs"]
    spec_rows = [
        ["Stripper System", "Type", ts["stripper"]["type"]],
        ["", "Feed Inlet (Kg/h)", ts["stripper"]["feed_kgh"]],
        ["", "Top Distillate Out (Kg/h)",
         f'{ts["stripper"]["distillate_kgh"]} ({ts["stripper"]["distillate_composition"]})'],
        ["", "Stripper Bottom Out (Kg/h)", ts["stripper"]["bottoms_kgh"]],
        ["Evaporator", "Type", f'{ts["mee"]["type"]} ({ts["mee"]["configuration"]})'],
        ["", "Feed Inlet (Kg/h)", ts["mee"]["feed_kgh"]],
        ["", "Feed Solids (%)", ts["mee"]["feed_solids_pct"]],
        ["", "Water Evaporation (Kg/h)", ts["mee"]["evaporation_kgh"]],
        ["", "Concentrate Out (Kg/h)",
         f'{ts["mee"]["concentrate_kgh"]} ({ts["mee"]["concentrate_solids_pct"]}%)'],
        ["ATFD", "Type", ts["atfd"]["type"]],
        ["", "Feed Inlet (Kg/h)", ts["atfd"]["feed_kgh"]],
        ["", "Feed Solids (%)", ts["atfd"]["feed_solids_pct"]],
        ["", "Water Evaporation (Kg/h)", ts["atfd"]["evaporation_kgh"]],
        ["", "ATFD Product Out (Kg/h)", ts["atfd"]["product_kgh"]],
        ["", "Moisture in Product (%)", ts["atfd"]["product_moisture_pct"]],
    ]
    _make_table(doc, spec_rows, header=["Section", "Parameter", "Value"],
                 col_widths=[1.5, 2.5, 2.5])

    _add_heading(doc, "Utilities Specification", level=3)
    ut = data["utilities"]
    util_rows = [
        ["Steam — Stripper", ut["stripper_steam"]["param"], "Kg/h", ut["stripper_steam"]["value_kgh"]],
        ["Steam — MEE", ut["mee_steam"]["param"], "Kg/h", ut["mee_steam"]["value_kgh"]],
        ["Steam Economy for MEE", "", "Kg/Kg", f'~{ut["mee_steam"]["steam_economy"]}'],
        ["Steam — ATFD", ut["atfd_steam"]["param"], "Kg/h", ut["atfd_steam"]["value_kgh"]],
        ["Power Consumption", "415V, 50 Hz, 3 Phase", "kWh", ut["power_consumption_kwh"]],
        ["Power Installed (incl. standby)", "415V, 50 Hz, 3 Phase", "kW", ut["power_installed_kw"]],
        ["Cooling Water (closed loop)", ut["cooling_water_temps"], "m³/h", ut["cooling_water_m3h"]],
        ["Seal Water Re-circulation", "In/Out: 30 / 32 °C", "m³/h", ut["seal_water"]],
        ["Compressed Air", ut["compressed_air_pressure"], "Nm³/h", ut["compressed_air_nm3h"]],
        ["CIP Solutions", ut["cip_solutions"], "m³", "DDE"],
    ]
    _make_table(doc, util_rows,
                 header=["Utility", "Operating Parameter", "Unit", "Consumption"],
                 col_widths=[1.8, 2.2, 0.6, 1.1])

    _add_heading(doc, "Performance Guarantee", level=3)
    for bullet in data["performance_guarantee"]:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(bullet).font.size = Pt(10)

    # ============================================
    # PART VI: SCOPE OF SUPPLY
    # ============================================
    _add_section_title(doc, "PART – VI", "SCOPE OF SUPPLY")
    _add_heading(doc, "I. Electro-Mechanical Items", level=2)

    _add_heading(doc, "Stripper System", level=3)
    _make_scope_table(doc, data["scope_stripper"])

    _add_heading(doc, "Evaporation System (MEE)", level=3)
    _make_scope_table(doc, data["scope_mee"])

    _add_heading(doc, "ATFD System", level=3)
    _make_scope_table(doc, data["scope_atfd"])

    _add_heading(doc, "II. Instruments & Automation Items", level=2)
    inst_rows = [[i["item"], i["qty"], i["scope"]] for i in data["instruments"]]
    _make_table(doc, inst_rows, header=["Item Description", "Quantity", "Scope"],
                 col_widths=[3.8, 1.2, 1.5])

    _add_heading(doc, "III. Engineering & Executive Services", level=2)
    services = [
        "Basic Engineering", "Detail Engineering", "Software development",
        "PFD / P&ID", "GA Drawings and Layout", "3D Drawing of Plant",
        "Project Management", "Installation", "Pre-Commissioning",
        "Commissioning & Training of system operators",
        "Material Test Certificates", "Hydro Test Certificates", "Operating Manual",
    ]
    for s in services:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(s).font.size = Pt(10)

    # ============================================
    # PART VII: BATTERY LIMITS
    # ============================================
    _add_section_title(doc, "PART – VII", "BATTERY LIMITS")
    for i, item in enumerate(data["battery_limits"], 1):
        p = doc.add_paragraph(style='List Number')
        p.add_run(item).font.size = Pt(10)

    # ============================================
    # PART VIII: SCOPE MATRIX
    # ============================================
    _add_section_title(doc, "PART – VIII", "SCOPE MATRIX")
    sm_rows = [[i + 1, item["description"],
                 "✓" if item["bg"] else "✗",
                 "✓" if item["client"] else "✗"]
                for i, item in enumerate(data["scope_matrix"])]
    _make_table(doc, sm_rows,
                 header=["S.No", "Description of Work", "B&G", "CLIENT"],
                 col_widths=[0.5, 4.5, 0.75, 0.75])

    # ============================================
    # PART IX: BASIS OF COMMISSIONING
    # ============================================
    _add_section_title(doc, "PART – IX", "BASIS OF COMMISSIONING / TAKE-OVER")
    commissioning_bullets = [
        "To Carry out the Commissioning and Take-over of the Equipment/Plant, Buyer shall provide Operators/Supervisors, Sufficient quality and quantity of Materials, Utilities and necessary Consumables and continuous supply of Feed.",
        "The Commissioning procedure by which the seller shall demonstrate that the equipment has met the take-over criteria shall be carried out by Buyer under the supervision of seller as per Operation Manuals provided by seller.",
        "Seller shall demonstrate performance trial of Equipment/Plant maximum up to 48 hrs. This is Buyer's responsibility to provide continuous and uninterrupted supply of Feed, Utilities and Consumables.",
        "When the commissioning of Equipment/Plant is completed or demonstrated, the Buyer shall take-over the equipment for the operation and maintenance thereof.",
        "The Seller and the Buyer shall sign the takeover certificate thereafter Buyer shall be solely responsible for the safety, operation, service, maintenance of the equipment.",
        "In the event of delay in completion of commissioning due to reasons not attributed to Seller from the period of 3 months from the date of mechanical completion, the Equipment/Plant shall be deemed to have been commissioned.",
        "In case the performance guarantee doesn't achieve in the performance trial for the reason attributed to seller, allowing tolerance under performance guarantee, the seller shall be liable to pay liquidated damage subject to a maximum of 2.5% of Purchase order / Contract price.",
    ]
    for b in commissioning_bullets:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(b).font.size = Pt(10)

    # ============================================
    # PART X: PRICE & COMMERCIAL TERMS
    # ============================================
    _add_section_title(doc, "PART – X", "PRICE & COMMERCIAL TERMS AND CONDITIONS")
    _add_heading(doc, "Price Summary", level=3)
    pr = data["pricing"]
    _add_paragraph(doc,
        f"Our total price for Design, Engineering, Manufacturing, Supply, Installation "
        f"and Commissioning of Plant as per given Technical Specification and Scope of work "
        f"(DAP, {pr['location_dap']}):",
        size=11)

    price_rows = [
        ["1", "Design, Engineering & Supply of Stripper, MEE & ATFD System",
         f"Rs. {pr['option1_equipment_price_cr']:.2f} Cr",
         f"Rs. {pr['option2_equipment_price_cr']:.2f} Cr"],
        ["2", "Installation & Commissioning",
         f"Rs. {pr['option1_install_lakhs']:.0f} Lakhs",
         f"Rs. {pr['option2_install_lakhs']:.0f} Lakhs"],
        ["", "TOTAL PRICE",
         f"Rs. {pr['option1_total_cr']:.2f} Cr",
         f"Rs. {pr['option2_total_cr']:.2f} Cr"],
    ]
    _make_table(doc, price_rows,
                 header=["S.N", "Item / Equipment / Service",
                         f"Option 1 — {pr['option1_moc']}",
                         f"Option 2 — {pr['option2_moc']}"],
                 col_widths=[0.4, 2.6, 1.9, 1.9])

    _add_paragraph(doc, "", size=6)
    _add_paragraph(doc,
        "Prices are inclusive of Design, Engineering, Manufacturing, Supply, Installation, "
        "Commissioning, Transportation & P&F. Above prices are EXCLUDING Taxes and Duties, "
        "and Transit Insurance (charged extra at the time of dispatch).",
        size=10)
    _add_paragraph(doc,
        f"Our above-mentioned price validity is {pr['price_validity_days']} days from the date of this offer.",
        bold=True, size=11)

    _add_heading(doc, "Terms of Payment", level=3)
    for term in pr["payment_terms"]:
        p = doc.add_paragraph(style='List Bullet')
        p.add_run(term).font.size = Pt(10)

    _add_heading(doc, "Delivery Timeline (INCOTERMS 2020)", level=3)
    delivery = pr["delivery_timeline"]
    delivery_rows = [
        [f"Supply (DAP, {pr['location_dap']}) – Option 1", delivery["supply_option1"]],
        [f"Supply (DAP, {pr['location_dap']}) – Option 2", delivery["supply_option2"]],
        ["Installation", delivery["installation"]],
        ["Commissioning", delivery["commissioning"]],
    ]
    _make_table(doc, delivery_rows, header=["Activity", "Timeline"],
                 col_widths=[3.0, 3.8])

    # ============================================
    # PART XI: GENERAL TERMS & CONDITIONS
    # ============================================
    _add_section_title(doc, "PART – XI", "GENERAL TERMS & CONDITIONS")
    _add_general_terms(doc)

    # Signature
    doc.add_paragraph()
    doc.add_paragraph()
    _add_paragraph(doc, f"For {COMPANY['name']}", bold=True)
    doc.add_paragraph()
    _add_paragraph(doc, COMPANY["managing_partner"], bold=True)
    _add_paragraph(doc, COMPANY["managing_partner_title"], size=10)

    # ---- Save to bytes ----
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


def _make_scope_table(doc, scope_items: list):
    rows = [[i["equipment"], i["specification"], i["qty"],
             "✓" if i["bg_scope"] else "✗",
             "✓" if i["buyer_scope"] else "✗"]
             for i in scope_items]
    _make_table(doc, rows,
                 header=["Equipment", "Specification", "Qty", "B&G Scope", "Buyer Scope"],
                 col_widths=[1.6, 3.0, 0.6, 0.7, 0.7])
    # Note below the table
    _add_paragraph(doc, "Note: W = Working, SB = Working Standby, SSB = Store Standby. "
                         "Motors/Instruments per specification above.",
                    size=9, color_hex="666666")


def _build_cover_page(doc, data: dict, logo_path, tagline_path, hero_path):
    """First page — branded cover with logo, tagline, title, quote table."""
    # Logo (top-left)
    if logo_path:
        p_logo = doc.add_paragraph()
        p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p_logo.add_run()
        _add_picture_flexible(run, logo_path, 2.0)

    # Tagline
    if tagline_path:
        p_tag = doc.add_paragraph()
        p_tag.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p_tag.add_run()
        _add_picture_flexible(run, tagline_path, 3.5)

    # Spacer
    doc.add_paragraph()
    doc.add_paragraph()

    # Title
    _add_paragraph(doc, "TECHNO-COMMERCIAL OFFER", bold=True, size=22,
                   color_hex=DOCX_COLORS["primary_red"],
                   alignment=WD_ALIGN_PARAGRAPH.CENTER)
    _add_paragraph(doc, 'BG "ECOX-ZLD" SYSTEM', bold=True, size=18,
                   color_hex=DOCX_COLORS["accent_pink"],
                   alignment=WD_ALIGN_PARAGRAPH.CENTER)
    _add_paragraph(doc, f"CAPACITY: {data['cover']['capacity_kld']} KLD",
                   bold=True, size=16,
                   color_hex=DOCX_COLORS["dark_text"],
                   alignment=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_paragraph()
    _add_horizontal_line(doc, color=DOCX_COLORS["primary_red"])

    # Hero image (plant photo)
    if hero_path:
        p_hero = doc.add_paragraph()
        p_hero.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p_hero.add_run()
        _add_picture_flexible(run, hero_path, 4.0)

    # Quote info table
    doc.add_paragraph()
    cov = data["cover"]
    info_rows = [
        ["Quote Reference", cov["quote_ref"]],
        ["Quotation Date", cov["quote_date"]],
        ["Submitted to", cov["submitted_to"]],
        ["Location", cov["location"]],
        ["Prepared By", cov["prepared_by"]],
        ["Contact Details", cov["contact_details"]],
        ["E-mail", cov["email"]],
    ]
    _make_table(doc, info_rows, col_widths=[2.0, 4.0])


def _build_cover_letter(doc, data: dict):
    """Page 2 — cover letter with 'To', 'Attn', 'Subject', intro paragraph."""
    doc.add_page_break()
    cov = data["cover"]

    _add_paragraph(doc, "To,", bold=True, size=12)
    _add_paragraph(doc, cov["submitted_to"], bold=True, size=12)
    _add_paragraph(doc, cov["location"], bold=True, size=12)
    doc.add_paragraph()
    _add_paragraph(doc, f"Kind Attn.: {cov['kind_attn']}", bold=True)
    _add_paragraph(doc, f"Subject: {cov['subject']}", bold=True)
    if cov.get("discussion_date"):
        _add_paragraph(doc, f"Reference: As per discussions dated {cov['discussion_date']}",
                       bold=True)
    doc.add_paragraph()

    discussion_date = cov.get("discussion_date") or "recent meetings"
    intro = COVER_LETTER_INTRO.format(
        discussion_date=discussion_date,
        capacity=cov["capacity_kld"]
    )
    for para in intro.split("\n\n"):
        _add_paragraph(doc, para)

    doc.add_paragraph()
    _add_paragraph(doc, f"For, {COMPANY['name']}", bold=True)
    doc.add_paragraph()
    _add_paragraph(doc, COMPANY["managing_partner"], bold=True)
    _add_paragraph(doc, COMPANY["managing_partner_title"], size=10)


def _add_header_footer(doc, data: dict, logo_path: str = None):
    """Add repeating header/footer to all pages."""
    section = doc.sections[0]
    # Header
    header = section.header
    h_para = header.paragraphs[0]
    h_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = h_para.add_run(f"Quote Ref: {data['cover']['quote_ref']}")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor.from_string("888888")

    # Footer
    footer = section.footer
    f_para = footer.paragraphs[0]
    f_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = f_para.add_run(f"{COMPANY['name']} · {COMPANY['address']}")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor.from_string("888888")


def _add_general_terms(doc):
    """Add full text of PART XI general terms (verbatim from offer)."""
    terms = [
        ("Buyer's Responsibilities",
         "The Buyer shall supply all items and materials not specified as the responsibility of the Seller but which are necessary for the Seller to comply with its obligations under the contract. The Buyer shall provide access to the site suitable for the transport of the Equipment. The Seller shall not commence the Installation work unless the civil works are completed by Buyer and facilities like power, water and other essential utilities are made available at the Site by the Buyer. The Buyer shall be responsible for obtaining all licenses, permits, and approvals necessary."),
        ("Contract Price",
         "The contract price quoted is Ex Works and exclusive of packing and forwarding charges, freight and insurance, taxes, duties and/or other levies or charges unless otherwise stated. All taxes, duties, levies and charges shall be billed at the rates in force at the time of dispatch."),
        ("Statutory Variations",
         "Our prices are firm but subject to statutory variations. Any increase in Excise Duty, taxes etc. at the time of delivery shall be charged extra to your account."),
        ("Delivery",
         "Unless otherwise stated, all supplies of the Equipment shall be Ex-works at Seller's works at Hyderabad as per Incoterms 2020. Time of delivery shall start from receipt of final Purchase Order and receipt of downpayment."),
        ("Transportation and Insurance",
         "The Seller may arrange for transportation on 'freight to pay' or 'freight paid' basis. Buyer shall arrange insurance on the Equipment from the time the goods leave the Seller's works until commissioning at Buyer's factory site."),
        ("Mechanical Completion",
         "As soon as the Equipment is substantially erected, the Buyer shall notify in writing to the Seller. Upon completion of demonstration, both parties shall sign the Mechanical Completion Certificate."),
        ("Mechanical Warranty",
         "Each item of Equipment shall be free from defects in design, materials and workmanship for a period of 12 months from date of mechanical completion or 18 months from date of last major supply, whichever is earlier. This warranty is based on normal operation."),
        ("Force Majeure",
         "Force Majeure shall include but not be restricted to Acts of God, action of government, strikes, floods, fires, earthquakes, explosions, accidents, epidemics, civil commotions, war, riots, and any factor beyond reasonable control. If Force Majeure affects performance exceeding 3 months, either party may terminate."),
        ("Terms of Payment",
         "In case of delayed payment, Seller shall be entitled to interest at 15% or as agreed. In event of non-compliance with payment terms, Seller may enforce lien on Equipment already supplied and suspend performance."),
        ("Liability",
         "Seller shall not be liable for loss of use, profits, revenue, contracts, or indirect or consequential losses. Maximum cumulative liability shall not exceed 5% of Contract Price."),
        ("Intellectual Property Rights",
         "Seller shall provide back-up support to defend any lawsuits for alleged infringement of trademark or intellectual property rights with respect to this Offer."),
        ("Confidentiality",
         "All data, information, designs, drawings, process know-how pertaining to the PLANT shall be kept confidential by Buyer. Buyer shall not disclose such information to third parties without written permission from Seller."),
    ]
    for title, body in terms:
        _add_heading(doc, title, level=3)
        _add_paragraph(doc, body, size=10)
