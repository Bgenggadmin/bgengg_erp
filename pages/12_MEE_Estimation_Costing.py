"""
pages/12_MEE_Estimation_Costing.py
──────────────────────────────────
Streamlit page for the MEE vertical's Estimation & Costing module.

Slots between page 10 (Process Design) and page 11 (Offer Generator) in
the MEE pipeline — but appears after them in the sidebar so the existing
page numbers don't have to be renumbered.

This file is intentionally slim — all logic lives in the
`bg_estimation_costing` package (mirrors the bg_process_design and
bg_offer_generator pattern).
"""
import streamlit as st

# ── Page config (must be the first Streamlit call) ──────────────────────────
st.set_page_config(
    page_title="MEE Estimation & Costing | B&G Engineering",
    page_icon="🧾",
    layout="wide",
)

# ── Init session state ──────────────────────────────────────────────────────
from bg_estimation_costing.utils.state import init_state
init_state()

# ── Render header (title + metrics bar) ─────────────────────────────────────
from bg_estimation_costing.ui import header
header.render()

# ── Tabs ────────────────────────────────────────────────────────────────────
from bg_estimation_costing.ui import (
    tab_register, tab_cover, tab_equipment, tab_eia,
    tab_pipeline, tab_manhour, tab_summary, tab_save,
)

TABS = st.tabs([
    "📋 Register",
    "1️⃣ Cover Page",
    "2️⃣ Equipment",
    "3️⃣ EIA",
    "4️⃣ Pipeline",
    "5️⃣ Man-hours",
    "6️⃣ Price Summary",
    "💾 Save / Issue",
])

with TABS[0]: tab_register.render()
with TABS[1]: tab_cover.render()
with TABS[2]: tab_equipment.render()
with TABS[3]: tab_eia.render()
with TABS[4]: tab_pipeline.render()
with TABS[5]: tab_manhour.render()
with TABS[6]: tab_summary.render()
with TABS[7]: tab_save.render()
