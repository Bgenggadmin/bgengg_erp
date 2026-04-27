"""
bg_estimation_costing
─────────────────────
B&G Engineering — MEE Vertical · Estimation & Costing module.

Package layout (mirrors bg_process_design and bg_offer_generator):

    bg_estimation_costing/
    ├── __init__.py
    ├── db.py                       — Supabase CRUD for costings + lines
    ├── modules/
    │   ├── __init__.py
    │   └── qps_calculators.py      — parametric cost engines
    ├── ui/
    │   ├── __init__.py
    │   ├── header.py               — page header / metrics bar
    │   ├── tab_register.py         — saved-costings register
    │   ├── tab_cover.py            — cover page + design import
    │   ├── tab_equipment.py        — equipment lines + calculators
    │   ├── tab_eia.py              — EIA lines
    │   ├── tab_pipeline.py         — pipeline lines
    │   ├── tab_manhour.py          — man-hour breakdown
    │   ├── tab_summary.py          — price summary + cash flow
    │   └── tab_save.py             — save / issue / hand-off
    ├── utils/
    │   ├── __init__.py
    │   ├── state.py                — session-state init & accessors
    │   ├── totals.py               — roll-up calculations
    │   └── templates.py            — skeleton templates
    └── assets/
        └── (currently empty)

The Streamlit page lives at  pages/10_MEE_Estimation_Costing.py
and just imports from this package.
"""
__version__ = "1.0.0"
