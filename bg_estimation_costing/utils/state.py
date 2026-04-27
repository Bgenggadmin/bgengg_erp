"""
bg_estimation_costing.utils.state
─────────────────────────────────
Session-state initialisation and namespaced accessors.

All keys live under the `qps_*` prefix to avoid collision with other
modules (bg_process_design, bg_offer_generator) sharing the same
Streamlit session.

Material rates load from `est_rm_master` (RM category) and labour
rates from `est_oh_master` (LABOUR oh_type) — the same masters used
by the Pharma estimation module. Hardcoded defaults from
`qps_calculators.DEFAULT_RM_RATES` are used as a fallback for
materials that don't appear in the DB.
"""
from __future__ import annotations
from datetime import date
from typing import Any, Dict, List

import streamlit as st

from bg_estimation_costing import db
from bg_estimation_costing.modules import qps_calculators as qc


# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT STATE BUILDERS
# ─────────────────────────────────────────────────────────────────────────────
def new_eqp_line() -> Dict:
    return dict(
        section="Evaporator", sub_section="HEAT EXCHANGER",
        equipment="", description="", moc="SS316L",
        qty=1, unit_cost=0.0,
        category="B&G-MFG", item_type="MECH_EQP",
        calc_source="Manual", design_payload="",
    )


def default_manhour_lines() -> List[Dict]:
    return [
        dict(department="Project Management",     hod=0, mgr=15, eng=20),
        dict(department="Process Engineering",     hod=0, mgr=10, eng=25),
        dict(department="Mechanical Engineering",  hod=0, mgr=10, eng=30),
        dict(department="EIA Engineering",         hod=0, mgr=6,  eng=15),
        dict(department="Drafting",                hod=0, mgr=0,  eng=20),
        dict(department="Erection",                hod=0, mgr=4,  eng=60),
        dict(department="Commissioning-Process",   hod=0, mgr=2,  eng=15),
        dict(department="Commissioning-EIA",       hod=0, mgr=2,  eng=2),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# RATE LOADERS — DB-first, fallback to hardcoded defaults
# ─────────────────────────────────────────────────────────────────────────────
def load_rm_rates_with_fallback() -> Dict[str, float]:
    """
    Merge DB rates from est_rm_master with hardcoded defaults.
    DB values take precedence — defaults fill in any missing materials.
    """
    rates = dict(qc.DEFAULT_RM_RATES)   # start from hardcoded baseline
    try:
        db_rates = db.rm_rate_lookup()
        rates.update(db_rates)          # DB overrides where available
    except Exception:
        pass                            # silent fallback if DB is unavailable
    return rates


def load_lab_rates_with_fallback() -> Dict[str, float]:
    """Same pattern — DB labour rates from est_oh_master, fallback to defaults."""
    rates = dict(qc.DEFAULT_LABOUR_RATES)
    try:
        db_rates = db.labour_rate_lookup()
        rates.update(db_rates)
    except Exception:
        pass
    return rates


def blank_state() -> Dict:
    return dict(
        # Identity
        costing_id=None,
        revision="R0",
        status="Draft",
        # Linked process-design project
        project_id=None,
        # Cover Page
        qps_no=f"QPS_{date.today().year}/1.1",
        client_name="",
        project_name="",
        project_no="",
        location="Hyderabad",
        capacity="",
        plant_type="MEE",
        costing_date=date.today(),
        prepared_by="",
        approved_by="",
        scope_summary="Supply of MEE / Stripper / ATFD package — as per Process Design",
        # Lines
        equipment_lines=[],
        eia_lines=[],
        pipeline_lines=[],
        manhour_lines=default_manhour_lines(),
        # Soft-cost percentages
        inspection_pct=0.3, packing_pct=0.3, risk_pct=0.3,
        overhead_pct=5.0, contingency_pct=3.0,
        material_handling_pct=0.3,
        engg_travel_amt=1403100, transport_amt=200000,
        bo_margin_pct=0.0,
        # Pricing tiers
        bg_margin_pct=25.0, best_price_pct=20.0,
        target_price_pct=15.0, no_regret_price_pct=10.0,
        # Cash flow
        cashflow_pattern={
            "Advance":          0.20,
            "After Engg":       0.00,
            "Lot-1":            0.00,
            "Lot-2":            0.30,
            "Lot-3":            0.20,
            "Lot-4":            0.20,
            "On Completion-1":  0.05,
            "On Completion-2":  0.05,
        },
        # Material rates — loaded from est_rm_master / est_oh_master
        # (with hardcoded fallback for materials not yet in DB)
        rm_rates=load_rm_rates_with_fallback(),
        lab_rates=load_lab_rates_with_fallback(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# STATE INIT  (idempotent — safe to call on every page render)
# ─────────────────────────────────────────────────────────────────────────────
def init_state():
    """Populate session state with defaults if not already set."""
    for k, v in blank_state().items():
        st.session_state.setdefault(f"qps_{k}", v)


def reset_state():
    """Reset all qps_* keys back to defaults — start a fresh costing."""
    for k, v in blank_state().items():
        st.session_state[f"qps_{k}"] = v


# ─────────────────────────────────────────────────────────────────────────────
# ACCESSORS
# ─────────────────────────────────────────────────────────────────────────────
def S(k: str, default: Any = None) -> Any:
    """Read a qps_* state value."""
    return st.session_state.get(f"qps_{k}", default)


def setS(k: str, v: Any) -> None:
    """Write a qps_* state value."""
    st.session_state[f"qps_{k}"] = v
