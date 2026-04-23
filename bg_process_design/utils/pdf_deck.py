"""
Branded client-facing PDF deck generator for B&G Process Design projects.

Takes a project export dict (same structure as Export tab JSON download) and
returns PDF bytes ready for st.download_button.

Registers DejaVu TTF fonts bundled inside this repo at bg_process_design/assets/fonts/
so unicode glyphs (₹, m², m³, °C, etc.) render correctly on Streamlit Cloud.

Usage:
    from bg_process_design.utils.pdf_deck import build_client_deck_pdf
    pdf_bytes = build_client_deck_pdf(project_data, logo_bytes=<logo_png>)
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional, Union

from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# -----------------------------------------------------------------
# Font registration (idempotent)
# -----------------------------------------------------------------
_FONTS_REGISTERED = False

def _register_fonts() -> None:
    """Register DejaVu TTF fonts from this package's assets/fonts folder."""
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return

    # assets/fonts lives as sibling to utils/ in the package
    here = Path(__file__).resolve().parent
    font_dir = here.parent / "assets" / "fonts"

    fonts = {
        "DejaVu":        "DejaVuSans.ttf",
        "DejaVu-Bold":   "DejaVuSans-Bold.ttf",
        "DejaVu-Italic": "DejaVuSans-Oblique.ttf",
        "DejaVu-BI":     "DejaVuSans-BoldOblique.ttf",
    }

    for name, filename in fonts.items():
        path = font_dir / filename
        if path.exists():
            pdfmetrics.registerFont(TTFont(name, str(path)))
        else:
            # Fallback: if fonts aren't bundled, silently fall back to Helvetica-like
            # (unicode won't render perfectly, but PDF will still build)
            pass

    _FONTS_REGISTERED = True


# Font aliases — resolve to DejaVu if registered, else Helvetica fallback
def _font(bold: bool = False, italic: bool = False) -> str:
    if _has_dejavu():
        if bold and italic:
            return "DejaVu-BI"
        elif bold:
            return "DejaVu-Bold"
        elif italic:
            return "DejaVu-Italic"
        return "DejaVu"
    else:
        if bold and italic:
            return "Helvetica-BoldOblique"
        elif bold:
            return "Helvetica-Bold"
        elif italic:
            return "Helvetica-Oblique"
        return "Helvetica"


def _has_dejavu() -> bool:
    try:
        pdfmetrics.getFont("DejaVu")
        return True
    except Exception:
        return False


# -----------------------------------------------------------------
# Brand palette
# -----------------------------------------------------------------
RED         = HexColor('#C7203E')
PINK        = HexColor('#E91E63')
CHARCOAL    = HexColor('#1E2A38')
MID_GREY    = HexColor('#4A5568')
LIGHT_GREY  = HexColor('#E2E8F0')
BG_LIGHT    = HexColor('#F7F9FC')
WHITE       = white
BLUE        = HexColor('#0284C7')
GREEN       = HexColor('#059669')
PURPLE      = HexColor('#8E24AA')
MUTED_LIGHT = HexColor('#B0BEC5')
DARK_MUTED  = HexColor('#78909C')
SHADOW_GREY = HexColor('#D0D7DE')

# -----------------------------------------------------------------
# Page dims — 16:9 landscape
# -----------------------------------------------------------------
PAGE_W = 13.33 * inch
PAGE_H = 7.5 * inch

# Logo aspect ratio (1219 × 624 ≈ 1.954)
# Gracefully degrades if user uploads a logo of different proportions
LOGO_AR_DEFAULT = 1.954


# =================================================================
# Main public entry point
# =================================================================
def build_client_deck_pdf(
    data: dict,
    logo_bytes: Optional[bytes] = None,
    prepared_label: Optional[str] = None,
) -> bytes:
    """
    Build a branded 10-slide PDF deck from a Process Design project export dict.

    Args:
      data: project export dict (from build_full_project_export). Must contain
            top-level keys: project, plant_overview, stripper, mee, atfd, plant_wide.
      logo_bytes: optional raster logo (PNG/JPG) to embed on cover and headers.
                  If None, falls back to text wordmark.
      prepared_label: optional string for cover bottom stamp. Defaults to a
                      generic "Techno-Commercial Design Package".

    Returns:
      PDF bytes suitable for st.download_button.
    """
    _register_fonts()

    # Write logo to temp file (reportlab's drawImage needs a path or ImageReader)
    logo_path: Optional[str] = None
    if logo_bytes:
        try:
            # Use BytesIO via ImageReader for in-memory rendering
            from reportlab.lib.utils import ImageReader
            logo_reader: Optional[ImageReader] = ImageReader(io.BytesIO(logo_bytes))
            # Get actual aspect ratio from the image if possible
            try:
                w, h = logo_reader.getSize()
                logo_ar = (w / h) if h else LOGO_AR_DEFAULT
            except Exception:
                logo_ar = LOGO_AR_DEFAULT
        except Exception:
            logo_reader = None
            logo_ar = LOGO_AR_DEFAULT
    else:
        logo_reader = None
        logo_ar = LOGO_AR_DEFAULT

    # ---- Extract project data with safe defaults ----
    proj = data.get('project') or {}
    po   = data.get('plant_overview') or {}
    strip_d = data.get('stripper') or {}
    mee_d   = data.get('mee') or {}
    atfd_d  = data.get('atfd') or {}
    pw   = data.get('plant_wide') or {}

    strip_i = strip_d.get('inputs') or {}
    strip_r = strip_d.get('results') or {}
    mee_i   = mee_d.get('inputs') or {}
    mee_r   = mee_d.get('results') or {}
    atfd_i  = atfd_d.get('inputs') or {}
    atfd_r  = atfd_d.get('results') or {}

    # TS unit convention
    STRIP_SOLIDS_PCT = (strip_i.get('solids_frac') or 0) * 100
    MEE_FEED_TS_PCT  = mee_r.get('feed_ts_pct') or 0
    MEE_OUT_TS_PCT   = mee_r.get('outlet_ts_pct') or 0
    ATFD_FEED_TS_PCT = atfd_r.get('feed_ts_pct') or 0
    ATFD_PROD_TS_PCT = atfd_r.get('product_ts_pct') or 0

    # ---- Canvas ----
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))

    # ---- Drawing helpers (closures over `c`) ----
    def fill(color): c.setFillColor(color)
    def stroke(color, w=0.5):
        c.setStrokeColor(color); c.setLineWidth(w)

    def rect(x, y, w, h, fill_color=None, stroke_color=None, sw=0.5):
        if fill_color:
            fill(fill_color)
            c.setStrokeColor(stroke_color or fill_color)
            c.setLineWidth(sw)
            c.rect(x, y, w, h, fill=1, stroke=1 if stroke_color else 0)
        elif stroke_color:
            stroke(stroke_color, sw)
            c.rect(x, y, w, h, fill=0, stroke=1)

    def text(s, x, y, size=12, color=CHARCOAL, bold=False, italic=False,
             align='left', font=None):
        if font is None:
            font = _font(bold=bold, italic=italic)
        c.setFont(font, size); fill(color)
        if align == 'center':
            c.drawCentredString(x, y, s)
        elif align == 'right':
            c.drawRightString(x, y, s)
        else:
            c.drawString(x, y, s)

    def line(x1, y1, x2, y2, color=LIGHT_GREY, width=0.5, dash=None):
        stroke(color, width)
        if dash: c.setDash(dash, 0)
        c.line(x1, y1, x2, y2)
        c.setDash([], 0)

    def wrap(s, font_name, size, max_w):
        c.setFont(font_name, size)
        words = s.split()
        lines = []; cur = ''
        for w in words:
            t = (cur + ' ' + w).strip()
            if c.stringWidth(t, font_name, size) <= max_w:
                cur = t
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        return lines

    def multi(s, x, y, w, size=11, color=CHARCOAL, leading=None, bold=False, italic=False):
        f = _font(bold=bold, italic=italic)
        lead = leading or size * 1.4
        lines = wrap(s, f, size, w)
        c.setFont(f, size); fill(color)
        cy = y
        for ln in lines:
            c.drawString(x, cy, ln)
            cy -= lead
        return cy

    def draw_logo_header():
        """Draw logo in top-left of content slide header."""
        if logo_reader is not None:
            logo_h = 0.35 * inch
            logo_w = logo_h * logo_ar
            c.drawImage(logo_reader, 0.5*inch, PAGE_H - 0.55*inch,
                        width=logo_w, height=logo_h,
                        preserveAspectRatio=True, mask='auto')
        else:
            # Text fallback
            f_bold = _font(bold=True)
            c.setFont(f_bold, 12)
            fill(RED);      c.drawString(0.5*inch, PAGE_H - 0.45*inch, 'B')
            fill(CHARCOAL); c.drawString(0.5*inch + 9, PAGE_H - 0.45*inch, '&')
            fill(RED);      c.drawString(0.5*inch + 19, PAGE_H - 0.45*inch, 'G')
            fill(CHARCOAL)
            c.setFont(f_bold, 10)
            c.drawString(0.5*inch + 33, PAGE_H - 0.45*inch, 'ENGINEERING')

    def header_bar(page_num, total):
        draw_logo_header()
        c.setFont(_font(italic=True), 10); fill(PINK)
        c.drawRightString(PAGE_W - 0.5*inch, PAGE_H - 0.45*inch, 'Responsible towards water')
        line(0.5*inch, PAGE_H - 0.7*inch, PAGE_W - 0.5*inch, PAGE_H - 0.7*inch, LIGHT_GREY, 0.5)
        c.setFont(_font(), 8); fill(MID_GREY)
        c.drawRightString(PAGE_W - 0.5*inch, 0.35*inch, f'{page_num} / {total}')

    def accent(x, y, h, color=RED):
        fill(color); c.rect(x, y, 0.06*inch, h, fill=1, stroke=0)

    # =============================================================
    # TOTAL & constants
    # =============================================================
    TOTAL = 10
    prep_label = prepared_label or 'Techno-Commercial Design Package'

    # =============================================================
    # SLIDE 1 : COVER
    # =============================================================
    fill(CHARCOAL); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    fill(RED); c.rect(PAGE_W - 2.5*inch, 0, 2.5*inch, PAGE_H, fill=1, stroke=0)
    fill(PINK); c.rect(PAGE_W - 0.8*inch, 0, 0.8*inch, PAGE_H, fill=1, stroke=0)

    if logo_reader is not None:
        logo_target_h = 1.6 * inch
        logo_target_w = logo_target_h * logo_ar
        logo_y_bottom = PAGE_H - 0.9*inch - logo_target_h
        c.drawImage(logo_reader, 0.8*inch, logo_y_bottom,
                    width=logo_target_w, height=logo_target_h,
                    preserveAspectRatio=True, mask='auto')
        tagline_y = logo_y_bottom - 0.35*inch
        c.setFont(_font(italic=True), 16); fill(PINK)
        c.drawString(0.8*inch, tagline_y, 'Responsible towards water')
    else:
        # Text wordmark fallback
        c.setFont(_font(bold=True), 72); fill(WHITE)
        c.drawString(0.8*inch, PAGE_H - 2.0*inch, 'B&G')
        c.setFont(_font(bold=True), 22)
        c.drawString(0.8*inch, PAGE_H - 2.55*inch, 'E N G I N E E R I N G')
        c.setFont(_font(italic=True), 14); fill(PINK)
        c.drawString(0.8*inch, PAGE_H - 2.85*inch, 'Responsible towards water')

    # Project title
    c.setFont(_font(bold=True), 38); fill(WHITE)
    c.drawString(0.8*inch, PAGE_H - 4.4*inch, 'Zero Liquid Discharge System')

    # Subtitle — adapt to actual scheme
    scheme = (proj.get('scheme') or 'Stripper + MEE + ATFD').strip()
    scheme_display = scheme.replace('+', '   •   ')
    c.setFont(_font(), 16); fill(MUTED_LIGHT)
    c.drawString(0.8*inch, PAGE_H - 4.8*inch, scheme_display)

    line(0.8*inch, PAGE_H - 5.55*inch, PAGE_W - 3.3*inch, PAGE_H - 5.55*inch, PINK, 1.2)

    facts = [
        ('PROJECT',  (proj.get('project_code') or '—').upper()),
        ('CAPACITY', f"{proj.get('capacity_kld', '?')} KLD"),
        ('LOCATION', proj.get('plant_location') or '—'),
        ('DESIGNER', (proj.get('designed_by') or '—').upper()),
    ]
    fx = 0.8*inch
    for lbl, val in facts:
        text(lbl, fx, PAGE_H - 5.85*inch, 9, MUTED_LIGHT, bold=True)
        text(str(val), fx, PAGE_H - 6.2*inch, 18, WHITE, bold=True)
        fx += 2.2*inch

    text(prep_label, 0.8*inch, 0.45*inch, 9, DARK_MUTED, italic=True)
    c.showPage()

    # =============================================================
    # SLIDE 2 : EXECUTIVE SUMMARY
    # =============================================================
    fill(BG_LIGHT); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    header_bar(2, TOTAL)
    text('Executive Summary', 0.5*inch, PAGE_H - 1.15*inch, 32, CHARCOAL, bold=True)
    text(f"Project {(proj.get('project_code') or '?').upper()}  •  {proj.get('capacity_kld', '?')} KLD  •  {scheme}",
         0.5*inch, PAGE_H - 1.55*inch, 13, RED, italic=True)

    lx, ly, lw = 0.5*inch, PAGE_H - 2.1*inch, 6.8*inch
    accent(lx, ly - 3.0*inch, 3.0*inch, RED)
    text('ABOUT THIS PROJECT', lx + 0.12*inch, ly - 0.05*inch, 10, RED, bold=True)

    prose = (
        f"B&G Engineering proposes a Zero Liquid Discharge system for treatment of "
        f"{proj.get('capacity_kld', '?')} KLD of industrial effluent at "
        f"{proj.get('plant_location', 'site')}. The plant integrates a solvent stripping "
        f"column, a multi-effect evaporator with vapor integration, and an agitated "
        f"thin-film dryer."
    )
    multi(prose, lx + 0.12*inch, ly - 0.35*inch, lw - 0.15*inch, 12, CHARCOAL, 16)

    se_val = po.get('mee_steam_economy') or 0
    solv_val = po.get('solvent_recovered_kgh') or 0
    prod_ts = po.get('atfd_product_ts_pct') or 0
    prose2 = (
        f"The system achieves a steam economy of {se_val:.2f} : 1 in the MEE, recovers "
        f"{solv_val:.0f} kg/h of solvent from the stripper, and delivers a dry salt "
        f"product at {prod_ts:.0f}% solids — fully meeting zero-liquid-discharge requirements."
    )
    multi(prose2, lx + 0.12*inch, ly - 1.4*inch, lw - 0.15*inch, 12, CHARCOAL, 16)

    # KPI cards
    gx, gy = 7.7*inch, PAGE_H - 2.1*inch
    cardW, cardH = 2.45*inch, 1.35*inch
    daily_opex = (pw.get('economics') or {}).get('total_daily_op_cost_inr') or 0
    daily_cost_lakhs = daily_opex / 100000
    tot_steam = (pw.get('total_utilities') or {}).get('steam_kgh') or 0

    cards = [
        ('CAPACITY',    f"{proj.get('capacity_kld', '?')}",  'KLD',          RED),
        ('STEAM ECON.', f"{se_val:.1f}",                     ': 1 MEE',      PINK),
        ('TOTAL STEAM', f"{tot_steam/1000:.1f}",             'TPH PLANT',    BLUE),
        ('DAILY OPEX',  f"₹ {daily_cost_lakhs:.1f}",         'LAKH / DAY',   GREEN),
    ]
    for i, (lbl, val, unit, col) in enumerate(cards):
        cc = i % 2; rr = i // 2
        cx = gx + cc * (cardW + 0.15*inch)
        cy = gy - rr * (cardH + 0.15*inch) - cardH
        rect(cx, cy, cardW, cardH, WHITE, LIGHT_GREY, 0.75)
        fill(col); c.rect(cx, cy + cardH - 0.06*inch, cardW, 0.06*inch, fill=1, stroke=0)
        text(lbl, cx + 0.15*inch, cy + cardH - 0.35*inch, 9, MID_GREY, bold=True)
        val_size = 26 if '₹' in val else 30
        text(val, cx + 0.15*inch, cy + 0.55*inch, val_size, col, bold=True)
        text(unit, cx + 0.15*inch, cy + 0.25*inch, 9, MID_GREY, bold=True)
    c.showPage()

    # =============================================================
    # SLIDE 3 : PROCESS SCHEME
    # =============================================================
    fill(BG_LIGHT); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    header_bar(3, TOTAL)
    text('Process Scheme', 0.5*inch, PAGE_H - 1.15*inch, 32, CHARCOAL, bold=True)
    text('Three integrated unit operations achieve zero liquid discharge',
         0.5*inch, PAGE_H - 1.55*inch, 13, MID_GREY)

    # Determine which stages to show based on what's designed
    stages_data = []
    strip_feed = strip_r.get('feed_kgh')
    if strip_feed:
        stages_data.append(
            ('1', 'STRIPPER', 'Solvent Recovery', RED,
             f"Feed: {strip_feed:.0f} kg/h",
             f"Distillate: {strip_r.get('distillate_kgh', 0):.0f} kg/h",
             f"Solvent recovered: {po.get('solvent_recovered_kgh', 0):.0f} kg/h")
        )
    mee_feed = mee_r.get('feed_kgh')
    if mee_feed:
        stages_data.append(
            ('2', 'MEE', f"{mee_r.get('n_effects', 4)}-Effect Evaporator", PINK,
             f"Feed: {mee_feed:.0f} kg/h @ {MEE_FEED_TS_PCT:.1f}% TS",
             f"Evaporation: {mee_r.get('total_evap_kgh', 0):.0f} kg/h",
             f"Steam economy: {mee_r.get('steam_economy', 0):.2f} : 1")
        )
    atfd_feed = atfd_r.get('feed_kgh')
    if atfd_feed:
        stages_data.append(
            ('3', 'ATFD', 'Thin-Film Dryer', PURPLE,
             f"Feed: {atfd_feed:.0f} kg/h @ {ATFD_FEED_TS_PCT:.0f}% TS",
             f"Dry product: {atfd_r.get('product_kgh', 0):.0f} kg/h",
             f"Product TS: {ATFD_PROD_TS_PCT:.0f}%")
        )

    if not stages_data:
        # Graceful empty state
        text('(No unit designs saved for this project yet)',
             PAGE_W/2, PAGE_H/2, 14, MID_GREY, italic=True, align='center')
    else:
        blockY = PAGE_H - 4.2*inch
        blockH = 1.7*inch
        blockW = 3.7*inch
        arrowW = 0.35*inch
        n_stages = len(stages_data)
        total_needed = n_stages * blockW + (n_stages - 1) * arrowW
        x0 = (PAGE_W - total_needed) / 2
        cx = x0
        for i, (num, title, subtitle, col, m1, m2, m3) in enumerate(stages_data):
            rect(cx + 3, blockY - 3, blockW, blockH, SHADOW_GREY, None, 0)
            rect(cx, blockY, blockW, blockH, WHITE, LIGHT_GREY, 0.75)
            fill(col); c.rect(cx, blockY + blockH - 0.48*inch, blockW, 0.48*inch, fill=1, stroke=0)
            text(f'STAGE {num}', cx + 0.18*inch, blockY + blockH - 0.3*inch, 10, WHITE, bold=True)
            text(title, cx + 0.18*inch, blockY + blockH - 0.75*inch, 22, CHARCOAL, bold=True)
            text(subtitle, cx + 0.18*inch, blockY + blockH - 1.0*inch, 11, col, italic=True)
            for j, m in enumerate([m1, m2, m3]):
                text(m, cx + 0.18*inch, blockY + 0.55*inch - j*0.25*inch, 10, MID_GREY)
            cx += blockW
            if i < n_stages - 1:
                fill(CHARCOAL)
                mid_y = blockY + blockH/2
                p = c.beginPath()
                p.moveTo(cx + arrowW*0.15, mid_y + 0.15*inch)
                p.lineTo(cx + arrowW*0.85, mid_y)
                p.lineTo(cx + arrowW*0.15, mid_y - 0.15*inch)
                p.close()
                c.drawPath(p, fill=1, stroke=0)
                cx += arrowW

    # Mass balance strip
    bx = 0.5*inch; by = 0.85*inch
    rect(bx, by, PAGE_W - inch, 0.9*inch, WHITE, LIGHT_GREY, 0.75)
    accent(bx, by, 0.9*inch, PINK)
    text('PLANT-WIDE MASS BALANCE', bx + 0.15*inch, by + 0.65*inch, 10, PINK, bold=True)
    bals = [
        ('Raw Feed',  f"{proj.get('capacity_kld', '?')} KLD ({proj.get('capacity_kld', 0)} m³/day)"),
        ('→',         ''),
        ('Stripper',  f"{strip_r.get('feed_kgh', 0):.0f} kg/h" if strip_feed else '—'),
        ('MEE',       f"{mee_r.get('feed_kgh', 0):.0f} kg/h" if mee_feed else '—'),
        ('ATFD',      f"{atfd_r.get('feed_kgh', 0):.0f} kg/h" if atfd_feed else '—'),
        ('Dry Salt',  f"{atfd_r.get('product_kgh', 0):.0f} kg/h" if atfd_feed else '—'),
    ]
    colw = (PAGE_W - inch - 0.3*inch) / len(bals)
    bfx = bx + 0.15*inch
    for lbl, val in bals:
        if lbl == '→':
            text('→', bfx + colw/2, by + 0.3*inch, 18, PINK, bold=True, align='center')
        else:
            text(lbl, bfx + 0.05*inch, by + 0.4*inch, 9, MID_GREY, bold=True)
            text(val, bfx + 0.05*inch, by + 0.15*inch, 11, CHARCOAL, bold=True)
        bfx += colw
    c.showPage()

    # =============================================================
    # SLIDE 4 : STRIPPER DETAIL
    # =============================================================
    fill(BG_LIGHT); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    header_bar(4, TOTAL)
    text('Stage 1 — Stripper Column', 0.5*inch, PAGE_H - 1.15*inch, 32, CHARCOAL, bold=True)
    text('Steam-stripped distillation for solvent recovery',
         0.5*inch, PAGE_H - 1.55*inch, 13, RED, italic=True)

    if not strip_feed:
        text('(No Stripper design saved for this project)',
             PAGE_W/2, PAGE_H/2, 14, MID_GREY, italic=True, align='center')
    else:
        lx_, ly_, lw_ = 0.5*inch, PAGE_H - 2.1*inch, 6.3*inch
        accent(lx_, ly_ - 4.2*inch, 4.2*inch, RED)
        text('FUNCTION', lx_ + 0.12*inch, ly_ - 0.05*inch, 10, RED, bold=True)
        prose = (
            "A tray-type stripping column separates volatile solvents from the aqueous effluent feed. "
            "Live steam is introduced in the reboiler; rising vapor contacts the descending liquid over sieve trays "
            "to strip dissolved solvent into the overhead. The distillate is condensed and recovered as reusable solvent, "
            "while the high-boiling bottoms feed the downstream MEE."
        )
        y_ = multi(prose, lx_ + 0.12*inch, ly_ - 0.35*inch, lw_ - 0.15*inch, 11, CHARCOAL, 15)

        text('MASS BALANCE', lx_ + 0.12*inch, y_ - 0.15*inch, 10, RED, bold=True)
        mb_y = y_ - 0.4*inch
        mb_items = [
            ('Feed rate',             f"{strip_feed:.0f} kg/h  @  {strip_i.get('feed_temp_c', 0):.0f}°C"),
            ('Solvent content',       f"{strip_r.get('solvent_in_kgh', 0):.0f} kg/h  ({STRIP_SOLIDS_PCT:.0f}% w/w)"),
            ('Distillate (overhead)', f"{strip_r.get('distillate_kgh', 0):.0f} kg/h"),
            ('Bottoms (→ MEE)',        f"{strip_r.get('bottoms_kgh', 0):.0f} kg/h"),
            ('Solvent recovery',      f"{(strip_i.get('solvent_recovery') or 0)*100:.0f} %"),
        ]
        for i, (lbl, val) in enumerate(mb_items):
            ry_ = mb_y - i*0.28*inch
            text(lbl, lx_ + 0.12*inch, ry_, 10, MID_GREY)
            text(val, lx_ + 2.3*inch, ry_, 10, CHARCOAL, bold=True)

        # Equipment card
        rx, ry, rw, rh = 7.3*inch, PAGE_H - 2.1*inch, 5.5*inch, 4.2*inch
        rect(rx, ry - rh, rw, rh, WHITE, LIGHT_GREY, 0.75)
        fill(RED); c.rect(rx, ry - 0.06*inch, rw, 0.06*inch, fill=1, stroke=0)
        text('EQUIPMENT & SIZING', rx + 0.25*inch, ry - 0.3*inch, 11, RED, bold=True)

        reb = strip_r.get('reboiler_tubes') or {}
        cond = strip_r.get('condenser1_tubes') or {}
        specs = [
            ('Column diameter (selected)', f"{(strip_r.get('column_dia_selected_m') or 0)*1000:.0f} mm"),
            ('Number of sieve trays',      f"{strip_r.get('no_of_trays', '—')}"),
            ('Tray spacing',               f"{(strip_r.get('tray_spacing_m') or 0)*1000:.0f} mm"),
            ('Reboiler HTA (selected)',    f"{strip_r.get('reboiler_HTA_selected', reb.get('hta_design_m2', 0))} m²"),
            ('Reboiler tubes',             f"{reb.get('total_tubes', '—')} × {reb.get('tube_od_mm', 0):.1f} mm OD × {reb.get('tube_length_m', 0):.1f} m" if reb else '—'),
            ('Reboiler shell ID',          f"{(reb.get('shell_id_selected_m') or 0)*1000:.0f} mm"),
            ('Condenser HTA (selected)',   f"{strip_r.get('condenser1_HTA_selected', cond.get('hta_design_m2', 0))} m²"),
            ('Condenser tubes',            f"{cond.get('total_tubes', '—')} × {cond.get('tube_od_mm', 0):.1f} mm OD × {cond.get('tube_length_m', 0):.1f} m" if cond else '—'),
            ('Steam consumption',          f"{(strip_r.get('reboiler_evap_kcalh') or 0)/540:.0f} kg/h (est.)"),
            ('CW flow',                    f"{strip_r.get('cw_flow_m3h', 0):.1f} m³/h"),
            ('Motor HP (pumps)',           f"{sum((p.get('motor_hp_selected') or 0) for p in (strip_r.get('pumps') or {}).values()):.1f} HP total"),
        ]
        spec_y = ry - 0.65*inch
        for lbl, val in specs:
            text(lbl, rx + 0.25*inch, spec_y, 10, MID_GREY)
            text(str(val), rx + rw - 0.25*inch, spec_y, 10, CHARCOAL, bold=True, align='right')
            line(rx + 0.25*inch, spec_y - 0.08*inch, rx + rw - 0.25*inch, spec_y - 0.08*inch, LIGHT_GREY, 0.3)
            spec_y -= 0.31*inch

    c.showPage()

    # =============================================================
    # SLIDE 5 : MEE DETAIL
    # =============================================================
    fill(BG_LIGHT); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    header_bar(5, TOTAL)
    text('Stage 2 — Multi-Effect Evaporator', 0.5*inch, PAGE_H - 1.15*inch, 32, CHARCOAL, bold=True)
    n_eff = mee_r.get('n_effects', 4)
    text(f"{n_eff}-effect falling-film evaporator  •  Steam economy {mee_r.get('steam_economy', 0):.2f} : 1",
         0.5*inch, PAGE_H - 1.55*inch, 13, PINK, italic=True)

    if not mee_feed:
        text('(No MEE design saved for this project)',
             PAGE_W/2, PAGE_H/2, 14, MID_GREY, italic=True, align='center')
    else:
        lx_, ly_, lw_ = 0.5*inch, PAGE_H - 2.1*inch, 5.5*inch
        accent(lx_, ly_ - 2.0*inch, 2.0*inch, PINK)
        text('FUNCTION', lx_ + 0.12*inch, ly_ - 0.05*inch, 10, PINK, bold=True)
        prose = (
            f"The MEE concentrates stripper bottoms from {MEE_FEED_TS_PCT:.1f}% to "
            f"{MEE_OUT_TS_PCT:.1f}% total solids by evaporating water across {n_eff} effects. "
            f"Vapor from each effect heats the next, reducing live steam demand to roughly "
            f"{mee_r.get('steam_economy', 0):.1f} kg of water evaporated per kg of steam."
        )
        multi(prose, lx_ + 0.12*inch, ly_ - 0.35*inch, lw_ - 0.15*inch, 11, CHARCOAL, 15)

        # Effects table
        tx, ty = 6.4*inch, PAGE_H - 2.1*inch
        tw = 6.4*inch
        rect(tx, ty - 2.6*inch, tw, 2.6*inch, WHITE, LIGHT_GREY, 0.75)
        fill(PINK); c.rect(tx, ty - 0.06*inch, tw, 0.06*inch, fill=1, stroke=0)
        text('EFFECT-BY-EFFECT TEMPERATURE PROFILE', tx + 0.2*inch, ty - 0.3*inch, 11, PINK, bold=True)

        hy = ty - 0.65*inch
        col_xs = [tx + 0.3*inch, tx + 1.7*inch, tx + 3.0*inch, tx + 4.3*inch, tx + 5.5*inch]
        headers = ['Effect', 'Feed (kg/h)', 'Shell Temp (°C)', 'Role', '% of Evap']
        for i, h in enumerate(headers):
            text(h, col_xs[i], hy, 9, MID_GREY, bold=True)
        line(tx + 0.2*inch, hy - 0.08*inch, tx + tw - 0.2*inch, hy - 0.08*inch, LIGHT_GREY, 0.5)

        effects = mee_r.get('effects') or []
        final_conc = mee_r.get('final_concentrate_kgh') or 0
        total_evap = mee_r.get('total_evap_kgh') or 1  # avoid div-0
        evap_per_effect = []
        for i, e in enumerate(effects):
            feed_kgh = e.get('feed_kgh') or 0
            if i < len(effects) - 1:
                next_feed = effects[i+1].get('feed_kgh') or 0
                ev = feed_kgh - next_feed
            else:
                ev = feed_kgh - final_conc
            evap_per_effect.append(ev)
        roles = ['Steam-driven', 'Vapor-driven', 'Vapor-driven', 'Vapor-driven', 'Vacuum']
        for i, e in enumerate(effects):
            ry_ = hy - 0.35*inch - i*0.32*inch
            role = roles[i] if i < len(roles) else 'Vapor-driven'
            if i == len(effects) - 1:
                role = 'Vacuum'
            pct = evap_per_effect[i] / total_evap * 100 if total_evap else 0
            text(f"E-0{e.get('effect_no', i+1)}", col_xs[0], ry_, 11, CHARCOAL, bold=True)
            text(f"{e.get('feed_kgh', 0):,.0f}", col_xs[1], ry_, 11, CHARCOAL)
            text(f"{e.get('shell_temp_c', 0):.1f}", col_xs[2], ry_, 11, CHARCOAL)
            text(role, col_xs[3], ry_, 10, MID_GREY)
            text(f"{pct:.1f} %", col_xs[4], ry_, 11, CHARCOAL, bold=True)

        # Utilities card
        ux, uy, uw, uh = 0.5*inch, 0.85*inch, 5.9*inch, 2.5*inch
        rect(ux, uy, uw, uh, WHITE, LIGHT_GREY, 0.75)
        fill(PINK); c.rect(ux, uy + uh - 0.06*inch, uw, 0.06*inch, fill=1, stroke=0)
        text('UTILITIES & EQUIPMENT', ux + 0.2*inch, uy + uh - 0.3*inch, 11, PINK, bold=True)

        mee_u = mee_r.get('utilities') or {}
        mee_c = mee_r.get('condenser') or {}
        util_items = [
            ('Live steam',             f"{mee_u.get('steam_kgh', 0):.0f} kg/h"),
            ('Power demand',           f"{mee_u.get('power_kw', 0):.1f} kW"),
            ('Cooling water',          f"{mee_u.get('cw_m3h', 0):.0f} m³/h  (makeup {mee_u.get('cw_makeup_m3h', 0):.1f})"),
            ('Final condenser HTA',    f"{mee_c.get('HTA_selected_m2', 0)} m²"),
            ('Vapor to condenser',     f"{mee_c.get('vapor_in_kgh', 0):,.0f} kg/h"),
        ]
        uy_start = uy + uh - 0.65*inch
        for i, (lbl, val) in enumerate(util_items):
            ry_ = uy_start - i*0.32*inch
            text(lbl, ux + 0.2*inch, ry_, 10, MID_GREY)
            text(val, ux + uw - 0.2*inch, ry_, 10, CHARCOAL, bold=True, align='right')

        # Steam economy card
        sx, sy = 6.65*inch, 0.85*inch
        rect(sx, sy, 6.25*inch, 2.5*inch, CHARCOAL, CHARCOAL, 0)
        text('STEAM ECONOMY', sx + 0.3*inch, sy + 2.1*inch, 11, PINK, bold=True)
        text(f"{mee_r.get('steam_economy', 0):.2f}", sx + 0.3*inch, sy + 0.8*inch, 72, WHITE, bold=True)
        text('kg water evaporated per kg of live steam',
             sx + 0.3*inch, sy + 0.45*inch, 11, MUTED_LIGHT)
        text('30-40% lower steam cost vs. single-effect evaporation',
             sx + 0.3*inch, sy + 0.2*inch, 10, WHITE, italic=True)

    c.showPage()

    # =============================================================
    # SLIDE 6 : ATFD DETAIL
    # =============================================================
    fill(BG_LIGHT); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    header_bar(6, TOTAL)
    text('Stage 3 — Agitated Thin Film Dryer', 0.5*inch, PAGE_H - 1.15*inch, 32, CHARCOAL, bold=True)
    text('Final drying stage — closes the zero-discharge loop',
         0.5*inch, PAGE_H - 1.55*inch, 13, PURPLE, italic=True)

    if not atfd_feed:
        text('(No ATFD design saved for this project)',
             PAGE_W/2, PAGE_H/2, 14, MID_GREY, italic=True, align='center')
    else:
        lx_, ly_, lw_ = 0.5*inch, PAGE_H - 2.1*inch, 6.3*inch
        accent(lx_, ly_ - 3.5*inch, 3.5*inch, PURPLE)
        text('FUNCTION', lx_ + 0.12*inch, ly_ - 0.05*inch, 10, PURPLE, bold=True)
        prose = (
            f"The ATFD receives MEE concentrate at {ATFD_FEED_TS_PCT:.0f}% TS and evaporates the remaining water "
            f"against a steam-heated jacket. Rotating wiper blades continuously spread the slurry as a thin film "
            f"across the heat-transfer surface, preventing fouling and enabling rapid drying. "
            f"The dry product discharges at {ATFD_PROD_TS_PCT:.0f}% solids; condensed vapor is recovered as clean water."
        )
        y_ = multi(prose, lx_ + 0.12*inch, ly_ - 0.35*inch, lw_ - 0.15*inch, 11, CHARCOAL, 15)

        text('PROCESS CONDITIONS', lx_ + 0.12*inch, y_ - 0.15*inch, 10, PURPLE, bold=True)
        mb_y = y_ - 0.4*inch
        mb_items = [
            ('Feed rate',          f"{atfd_feed:.0f} kg/h"),
            ('Feed TS',            f"{ATFD_FEED_TS_PCT:.1f} %"),
            ('Water evaporated',   f"{atfd_r.get('water_evap_kgh', 0):.0f} kg/h"),
            ('Dry product output', f"{atfd_r.get('product_kgh', 0):.0f} kg/h  @  {ATFD_PROD_TS_PCT:.0f} % TS"),
            ('Shell temperature',  f"{atfd_r.get('shell_temp_c', 0):.1f} °C"),
            ('Shell pressure',     f"{atfd_r.get('shell_pressure_bar', 0):.2f} bar-a"),
            ('Steam consumption',  f"{atfd_r.get('steam_consumption_kgh', 0):.0f} kg/h"),
        ]
        for i, (lbl, val) in enumerate(mb_items):
            ry_ = mb_y - i*0.27*inch
            text(lbl, lx_ + 0.12*inch, ry_, 10, MID_GREY)
            text(val, lx_ + 2.8*inch, ry_, 10, CHARCOAL, bold=True)

        rx, ry, rw, rh = 7.3*inch, PAGE_H - 2.1*inch, 5.5*inch, 4.2*inch
        rect(rx, ry - rh, rw, rh, WHITE, LIGHT_GREY, 0.75)
        fill(PURPLE); c.rect(rx, ry - 0.06*inch, rw, 0.06*inch, fill=1, stroke=0)
        text('EQUIPMENT & SIZING', rx + 0.25*inch, ry - 0.3*inch, 11, PURPLE, bold=True)

        acond = atfd_r.get('condenser') or {}
        ablow = atfd_r.get('blower') or {}
        specs = [
            ('Heat transfer area (selected)',  f"{atfd_r.get('HTA_selected_m2', 0)} m²"),
            ('Calculated HTA',                 f"{atfd_r.get('HTA_calc_m2', 0):.1f} m²"),
            ('Agitator motor (selected)',      f"{atfd_r.get('motor_hp', 0)} HP"),
            ('Connected load',                 f"{atfd_r.get('connected_load_kw', 0):.1f} kW"),
            ('Total heat load',                f"{atfd_r.get('Q_total_kcalh', 0):,.0f} kcal/h"),
            ('LMTD',                           f"{atfd_r.get('lmtd_c', 0):.1f} °C"),
            ('Condenser HTA',                  f"{acond.get('HTA_selected_m2', '—')} m²"),
            ('Blower motor',                   f"{ablow.get('motor_hp', '—')} HP"),
            ('Solids production rate',         f"{atfd_r.get('solids_kgh', 0):.1f} kg/h"),
        ]
        spec_y = ry - 0.65*inch
        for lbl, val in specs:
            text(lbl, rx + 0.25*inch, spec_y, 10, MID_GREY)
            text(str(val), rx + rw - 0.25*inch, spec_y, 10, CHARCOAL, bold=True, align='right')
            line(rx + 0.25*inch, spec_y - 0.08*inch, rx + rw - 0.25*inch, spec_y - 0.08*inch, LIGHT_GREY, 0.3)
            spec_y -= 0.35*inch

    c.showPage()

    # =============================================================
    # SLIDE 7 : PLANT-WIDE UTILITIES
    # =============================================================
    fill(BG_LIGHT); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    header_bar(7, TOTAL)
    text('Plant-Wide Utilities', 0.5*inch, PAGE_H - 1.15*inch, 32, CHARCOAL, bold=True)
    text('Consolidated steam, power, and cooling water demand',
         0.5*inch, PAGE_H - 1.55*inch, 13, MID_GREY)

    u = pw.get('total_utilities') or {}
    u_cards = [
        ('STEAM',         f"{u.get('steam_kgh', 0):,.0f}", 'kg/h',
         RED,   'Live steam to reboilers and jackets'),
        ('POWER',         f"{u.get('power_kw', 0):.0f}",   'kW',
         BLUE,  f"{pw.get('total_motor_hp', 0):.0f} HP across {pw.get('total_pumps_count', 0)} pumps"),
        ('COOLING WATER', f"{u.get('cw_m3h', 0):,.0f}",    'm³/h',
         GREEN, 'Circulation loop with cooling tower'),
    ]
    ux = 0.5*inch
    uw = (PAGE_W - inch - 2*0.2*inch) / 3
    for i, (lbl, val, unit, col, sub) in enumerate(u_cards):
        cx = ux + i * (uw + 0.2*inch)
        cy = PAGE_H - 4.1*inch
        ch = 2.0*inch
        rect(cx, cy, uw, ch, WHITE, LIGHT_GREY, 0.75)
        fill(col); c.rect(cx, cy + ch - 0.12*inch, uw, 0.12*inch, fill=1, stroke=0)
        text(lbl, cx + 0.25*inch, cy + ch - 0.4*inch, 11, col, bold=True)
        text(val, cx + 0.25*inch, cy + 0.8*inch, 52, CHARCOAL, bold=True)
        text(unit, cx + 0.25*inch, cy + 0.5*inch, 14, MID_GREY, bold=True)
        multi(sub, cx + 0.25*inch, cy + 0.3*inch, uw - 0.4*inch, 10, MID_GREY, 13, italic=True)

    # Pump schedule
    px, py, pw_box = 0.5*inch, 0.85*inch, PAGE_W - inch
    ph = 2.5*inch
    rect(px, py, pw_box, ph, WHITE, LIGHT_GREY, 0.75)
    accent(px, py, ph, RED)
    text('PUMP SCHEDULE  —  CONSOLIDATED', px + 0.2*inch, py + ph - 0.3*inch, 11, RED, bold=True)
    text(f"{pw.get('total_pumps_count', 0)} pumps total  •  {pw.get('total_motor_hp', 0):.1f} motor HP  •  {u.get('power_kw', 0):.1f} kW connected load",
         px + 0.2*inch, py + ph - 0.55*inch, 10, MID_GREY, italic=True)

    pump_list = pw.get('consolidated_pump_list') or []
    by_unit: dict = {}
    for p in pump_list:
        by_unit.setdefault(p.get('unit', 'Other'), []).append(p)

    cols_def = [('Stripper', RED), ('MEE', PINK), ('ATFD', PURPLE)]
    col_w = (pw_box - 0.4*inch) / 3
    gy = py + ph - 0.9*inch
    for i, (unit_name, col) in enumerate(cols_def):
        cx = px + 0.2*inch + i * col_w
        pumps_here = by_unit.get(unit_name, [])
        text(unit_name.upper(), cx, gy, 10, col, bold=True)
        text(f"{len(pumps_here)} pumps  •  {sum((p.get('motor_hp_selected') or 0) for p in pumps_here):.1f} HP",
             cx + col_w - 0.2*inch, gy, 9, MID_GREY, align='right')
        line(cx, gy - 0.1*inch, cx + col_w - 0.2*inch, gy - 0.1*inch, LIGHT_GREY, 0.5)
        for j, p in enumerate(pumps_here):
            ry_ = gy - 0.3*inch - j*0.22*inch
            svc = (p.get('service') or '').replace(unit_name + ' ', '').replace('Re-Circ', 'RC').replace('Condensate', 'Cond.')
            if len(svc) > 22: svc = svc[:20] + '…'
            text(svc, cx, ry_, 9, CHARCOAL)
            text(f"{p.get('motor_hp_selected', 0):.1f} HP", cx + col_w - 0.2*inch, ry_, 9, CHARCOAL, bold=True, align='right')
    c.showPage()

    # =============================================================
    # SLIDE 8 : CHARACTERIZATION TRACE
    # =============================================================
    fill(BG_LIGHT); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    header_bar(8, TOTAL)
    text('Feed Characterization Across Plant', 0.5*inch, PAGE_H - 1.15*inch, 32, CHARCOAL, bold=True)
    text('How composition evolves from raw effluent to dry salt',
         0.5*inch, PAGE_H - 1.55*inch, 13, MID_GREY)

    trace = pw.get('feed_characterization_traceability') or []
    if not trace:
        text('(Feed characterization trace not available)',
             PAGE_W/2, PAGE_H/2, 14, MID_GREY, italic=True, align='center')
    else:
        params = [
            ('pH',           'ph',            '',     2),
            ('Total Solids', 'ts_pct',        '%',    2),
            ('TDS',          'tds_pct',       '%',    2),
            ('COD',          'cod_mgl',       'mg/L', 0),
            ('BOD',          'bod_mgl',       'mg/L', 0),
            ('Chlorides',    'chlorides_mgl', 'mg/L', 0),
            ('Sulphates',    'sulphates_mgl', 'mg/L', 0),
        ]
        tx, ty, tw = 0.5*inch, PAGE_H - 2.2*inch, PAGE_W - inch
        th = 4.5*inch
        rect(tx, ty - th, tw, th, WHITE, LIGHT_GREY, 0.75)

        # Table supports 2–4 stages gracefully
        n_stages = min(len(trace), 4)
        stage_x_positions = [tx + 0.3*inch] + [
            tx + 2.5*inch + (i * 2.5*inch) for i in range(n_stages)
        ]
        # Evenly distribute if fewer stages
        if n_stages < 4:
            available_w = tw - 3.0*inch
            step = available_w / max(n_stages, 1)
            stage_x_positions = [tx + 0.3*inch] + [
                tx + 2.5*inch + i * step for i in range(n_stages)
            ]

        col_hdrs = ['Parameter'] + [t.get('stage', f'Stage {i+1}') for i, t in enumerate(trace[:n_stages])]
        col_cols = [CHARCOAL, CHARCOAL, RED, PINK, PURPLE][:n_stages + 1]

        hy = ty - 0.3*inch
        for x, h, col in zip(stage_x_positions, col_hdrs, col_cols):
            text(h, x, hy, 11, col, bold=True)
        line(tx + 0.3*inch, hy - 0.12*inch, tx + tw - 0.3*inch, hy - 0.12*inch, CHARCOAL, 1)

        for i, (plabel, pkey, unit, places) in enumerate(params):
            ry_ = hy - 0.4*inch - i * 0.5*inch
            text(plabel, stage_x_positions[0], ry_, 11, CHARCOAL, bold=True)
            if unit:
                text(unit, stage_x_positions[0] + c.stringWidth(plabel, _font(bold=True), 11) + 4,
                     ry_, 9, MID_GREY, italic=True)
            for j in range(n_stages):
                ch_ = (trace[j].get('characterization') or {})
                val = ch_.get(pkey)
                if val is not None:
                    vs = f"{val:,.0f}" if places == 0 else f"{val:,.{places}f}"
                else:
                    vs = '—'
                text(vs, stage_x_positions[j+1], ry_, 11, CHARCOAL)
            line(tx + 0.3*inch, ry_ - 0.18*inch, tx + tw - 0.3*inch, ry_ - 0.18*inch, LIGHT_GREY, 0.3)

        sr = pw.get('salt_routing') or {}
        if sr:
            text(
                f"Salt routing: {sr.get('total_solids_kgh', 0):.0f} kg/h total solids  "
                f"•  {sr.get('crystalline_salt_kgh', 0):.0f} kg/h crystallizable  "
                f"•  Saturation {sr.get('crystallization_saturation_pct', 0):.0f}%",
                0.5*inch, 0.5*inch, 10, MID_GREY, italic=True)
    c.showPage()

    # =============================================================
    # SLIDE 9 : ECONOMICS
    # =============================================================
    fill(BG_LIGHT); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    header_bar(9, TOTAL)
    text('Operating Economics', 0.5*inch, PAGE_H - 1.15*inch, 32, CHARCOAL, bold=True)

    e = pw.get('economics') or {}
    text(f"OPEX breakdown  •  {e.get('operating_days_year', '?')} days/year × {e.get('operating_hours_day', '?')} h/day",
         0.5*inch, PAGE_H - 1.55*inch, 13, MID_GREY)

    lx_, ly_ = 0.5*inch, PAGE_H - 4.4*inch
    lh = 2.7*inch
    rect(lx_, ly_, 5.5*inch, lh, CHARCOAL, CHARCOAL, 0)
    text('COST PER KL TREATED', lx_ + 0.3*inch, ly_ + lh - 0.35*inch, 11, PINK, bold=True)
    text(f"₹ {e.get('cost_per_kl_inr', 0):,.0f}", lx_ + 0.3*inch, ly_ + 0.95*inch, 56, WHITE, bold=True)
    text('per kilolitre of effluent', lx_ + 0.3*inch, ly_ + 0.65*inch, 12, MUTED_LIGHT)
    text(f"Daily OPEX: ₹ {e.get('total_daily_op_cost_inr', 0):,.0f}  ({(e.get('total_daily_op_cost_inr', 0))/100000:.2f} lakh/day)",
         lx_ + 0.3*inch, ly_ + 0.3*inch, 11, WHITE, italic=True)

    rx, ry, rw = 6.25*inch, PAGE_H - 4.4*inch, PAGE_W - 6.75*inch
    rh = 2.7*inch
    rect(rx, ry, rw, rh, WHITE, LIGHT_GREY, 0.75)
    text('DAILY OPEX BREAKDOWN', rx + 0.2*inch, ry + rh - 0.3*inch, 11, RED, bold=True)

    opex_items = [
        ('Steam',         e.get('daily_steam_cost_inr', 0), RED),
        ('Power',         e.get('daily_power_cost_inr', 0), BLUE),
        ('Cooling Water', e.get('daily_cw_cost_inr', 0),    GREEN),
    ]
    max_val = max(x[1] for x in opex_items) or 1
    bar_y0 = ry + rh - 0.85*inch
    bar_h = 0.35*inch
    label_w = 1.55*inch
    bar_max_w = rw - label_w - 2.0*inch - 0.4*inch
    total_daily = e.get('total_daily_op_cost_inr', 0) or 1
    for i, (lbl, val, col) in enumerate(opex_items):
        by_ = bar_y0 - i * 0.55*inch
        text(lbl, rx + 0.2*inch, by_ + 0.1*inch, 11, CHARCOAL, bold=True)
        bar_w = bar_max_w * (val / max_val) if max_val else 0
        fill(col)
        c.rect(rx + label_w, by_, bar_w, bar_h, fill=1, stroke=0)
        text(f"₹ {val:,.0f}", rx + rw - 0.2*inch, by_ + 0.1*inch, 11, CHARCOAL, bold=True, align='right')
        pct = val / total_daily * 100
        text(f"{pct:.0f}%", rx + rw - 1.3*inch, by_ + 0.1*inch, 10, MID_GREY, align='right')

    bx, by_box, bw, bh = 0.5*inch, 0.85*inch, PAGE_W - inch, 1.8*inch
    rect(bx, by_box, bw, bh, WHITE, LIGHT_GREY, 0.75)
    accent(bx, by_box, bh, PINK)
    text('ANNUAL OPERATING COST PROJECTION', bx + 0.2*inch, by_box + bh - 0.3*inch, 11, PINK, bold=True)

    cap = proj.get('capacity_kld') or 0
    days = e.get('operating_days_year', 0) or 0
    hours = e.get('operating_hours_day', 0) or 0
    annual_items = [
        ('Annual OPEX',               f"₹ {e.get('annual_op_cost_inr', 0):,.0f}",
         f"{(e.get('annual_op_cost_inr', 0))/10000000:.2f} crore"),
        ('Annual effluent processed', f"{cap * days:,.0f} KL",
         f"{cap * days / 1000:.1f} million L"),
        ('Avg. cost per KL',          f"₹ {e.get('cost_per_kl_inr', 0):,.0f}",
         'steady-state'),
        ('Operating hours / year',    f"{days * hours:,}",
         f"{days} days × {hours} h"),
    ]
    col_w_ = (bw - 0.4*inch) / 4
    for i, (lbl, val, sub) in enumerate(annual_items):
        cx_ = bx + 0.2*inch + i * col_w_
        text(lbl, cx_, by_box + bh - 0.65*inch, 10, MID_GREY, bold=True)
        val_size = 16 if '₹' in val else 20
        text(val, cx_, by_box + bh - 1.05*inch, val_size, CHARCOAL, bold=True)
        text(sub, cx_, by_box + bh - 1.35*inch, 9, MID_GREY, italic=True)
    c.showPage()

    # =============================================================
    # SLIDE 10 : NEXT STEPS
    # =============================================================
    fill(CHARCOAL); c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    fill(RED); c.rect(0, 0, 0.3*inch, PAGE_H, fill=1, stroke=0)
    c.setFont(_font(), 8); fill(DARK_MUTED)
    c.drawRightString(PAGE_W - 0.5*inch, 0.35*inch, f'{TOTAL} / {TOTAL}')

    text('Next Steps', 0.8*inch, PAGE_H - 1.1*inch, 42, WHITE, bold=True)
    text('Path to detailed engineering and delivery', 0.8*inch, PAGE_H - 1.55*inch, 14, PINK, italic=True)

    steps = [
        ('01', 'Client Review',    'Walk-through of design basis, mass balance, and feed characterization. Confirm assumptions.'),
        ('02', 'Detailed Sizing',  'Refine column, MEE, and ATFD sizing against your specific feed data and site conditions.'),
        ('03', 'Commercial Offer', 'Firm pricing across Option 1 / 2 MOC, delivery schedule, payment terms, and warranty scope.'),
        ('04', 'PO & Engineering', 'Detailed engineering, equipment procurement, fabrication, site installation, commissioning.'),
    ]
    tl_y = PAGE_H - 3.5*inch
    step_w = (PAGE_W - 1.6*inch) / 4
    for i, (num, title_, desc) in enumerate(steps):
        sx = 0.8*inch + i * step_w
        fill(PINK)
        c.circle(sx + 0.5*inch, tl_y, 0.45*inch, fill=1, stroke=0)
        text(num, sx + 0.5*inch, tl_y - 0.1*inch, 18, WHITE, bold=True, align='center')
        text(title_, sx + 0.1*inch, tl_y - 0.85*inch, 14, WHITE, bold=True)
        multi(desc, sx + 0.1*inch, tl_y - 1.1*inch, step_w - 0.3*inch, 10, MUTED_LIGHT, 13)
        if i < 3:
            line(sx + 1.0*inch, tl_y, sx + step_w, tl_y, PINK, 1.0, dash=[4, 3])

    cy_ = 1.4*inch
    line(0.8*inch, cy_ + 0.6*inch, PAGE_W - 0.8*inch, cy_ + 0.6*inch, RED, 1.5)
    text('CONTACT', 0.8*inch, cy_ + 0.3*inch, 11, PINK, bold=True)
    contacts = [
        ('Company',     'B&G Engineering Industries'),
        ('Location',    'Hyderabad, Telangana, India'),
        ('Prepared by', (proj.get('designed_by') or '—').upper()),
    ]
    cfx = 0.8*inch
    for lbl, val in contacts:
        text(lbl, cfx, cy_ - 0.05*inch, 10, DARK_MUTED, bold=True)
        text(val, cfx, cy_ - 0.35*inch, 14, WHITE, bold=True)
        cfx += 4.3*inch

    text('Responsible towards water', PAGE_W/2, 0.45*inch, 12, PINK, italic=True, align='center')
    c.showPage()

    c.save()
    return buf.getvalue()
