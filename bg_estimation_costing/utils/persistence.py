"""
bg_estimation_costing.utils.persistence
───────────────────────────────────────
Glue between session state and the DB layer:
  • serialise current state → mee_qps_costings row
  • write costing + lines atomically
  • load a saved costing back into session state
  • import equipment from a process-design project
"""
from __future__ import annotations
import json
from datetime import date, datetime
from typing import Dict, Optional

import streamlit as st

from bg_estimation_costing import db
from bg_estimation_costing.utils.state import (
    S, setS, blank_state, new_eqp_line,
)
from bg_estimation_costing.utils.totals import price_summary


# ─────────────────────────────────────────────────────────────────────────────
# IMPORT FROM process_design — converts mee_design_equipment → equipment_lines
# ─────────────────────────────────────────────────────────────────────────────
def import_design_equipment(project_id) -> int:
    """Pull design equipment for a project and seed equipment_lines.
    Returns count of imported lines."""
    rows = db.get_design_equipment(project_id)
    imported = []
    for r in rows:
        line = new_eqp_line()
        line.update({
            "section":     r.get("section",     line["section"]),
            "sub_section": r.get("sub_section", line["sub_section"]),
            "equipment":   r.get("equipment",   ""),
            "description": r.get("description", ""),
            "moc":         r.get("moc",         "SS316L"),
            "qty":         r.get("qty", 1) or 1,
            "unit_cost":   r.get("unit_cost", 0) or 0,
            "category":    r.get("category",    "B&G-MFG"),
            "item_type":   r.get("item_type",   "MECH_EQP"),
            "calc_source": "process_design",
            "design_payload": json.dumps({
                k: r.get(k) for k in (
                    "hta_m2", "shell_dia_mm", "shell_height_m", "shell_length_m",
                    "tube_length_m", "tube_od_mm", "tube_thk_mm", "n_tubes",
                    "capacity_kl", "L_over_D", "h_over_d", "gross_volume_m3",
                    "n_blades",
                ) if r.get(k) is not None
            }),
        })
        imported.append(line)
    if imported:
        setS("equipment_lines", imported)
    return len(imported)


# ─────────────────────────────────────────────────────────────────────────────
# SERIALISE STATE → DB ROW
# ─────────────────────────────────────────────────────────────────────────────
def serialise_state_for_db() -> Dict:
    """Convert qps_* session state into a dict ready for mee_qps_costings."""
    cd = S("costing_date")
    if isinstance(cd, (date, datetime)):
        cd = cd.isoformat()

    ps = price_summary()

    state_keys = (
        "equipment_lines", "eia_lines", "pipeline_lines", "manhour_lines",
        "inspection_pct", "packing_pct", "risk_pct", "overhead_pct",
        "contingency_pct", "material_handling_pct",
        "engg_travel_amt", "transport_amt", "bo_margin_pct",
        "bg_margin_pct", "best_price_pct", "target_price_pct",
        "no_regret_price_pct", "cashflow_pattern",
        "rm_rates", "lab_rates",
    )
    state_snapshot = {k: S(k) for k in state_keys}

    return dict(
        project_id   = S("project_id"),
        qps_no       = S("qps_no"),
        revision     = S("revision"),
        status       = S("status"),
        client_name  = S("client_name"),
        project_name = S("project_name"),
        project_no   = S("project_no"),
        location     = S("location"),
        capacity     = S("capacity"),
        plant_type   = S("plant_type"),
        costing_date = cd,
        prepared_by  = S("prepared_by"),
        approved_by  = S("approved_by"),
        scope_summary= S("scope_summary"),
        state_json   = json.dumps(state_snapshot, default=str),
        op_cost      = ps["op_cost"],
        soft_cost    = ps["soft_cost"],
        supply_cost  = ps["supply_cost"],
        quote_price  = ps["quote_price"],
        target_price = ps["target_price"],
        updated_at   = datetime.utcnow().isoformat(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SAVE
# ─────────────────────────────────────────────────────────────────────────────
def save_costing(*, mark_issued: bool = False) -> bool:
    """Insert or update the costing header + replace child lines."""
    if not db.is_connected():
        st.error("Supabase is not configured — costing cannot be persisted.")
        return False

    if mark_issued:
        setS("status", "Issued")

    row = serialise_state_for_db()
    cid = db.upsert_costing(row, costing_id=S("costing_id"))
    if not cid:
        return False

    setS("costing_id", cid)
    db.replace_costing_lines(cid, S("equipment_lines", []) or [])
    return True


# ─────────────────────────────────────────────────────────────────────────────
# LOAD
# ─────────────────────────────────────────────────────────────────────────────
def load_costing(costing_id) -> bool:
    """Fetch a saved costing + lines into session state."""
    h = db.get_costing(costing_id)
    if not h:
        st.error(f"Costing #{costing_id} not found.")
        return False

    # Header fields
    setS("costing_id",   h.get("id"))
    setS("project_id",   h.get("project_id"))
    setS("qps_no",       h.get("qps_no", ""))
    setS("revision",     h.get("revision", "R0"))
    setS("status",       h.get("status", "Draft"))
    setS("client_name",  h.get("client_name", ""))
    setS("project_name", h.get("project_name", ""))
    setS("project_no",   h.get("project_no", ""))
    setS("location",     h.get("location", ""))
    setS("capacity",     h.get("capacity", ""))
    setS("plant_type",   h.get("plant_type", "MEE"))
    cd = h.get("costing_date")
    if isinstance(cd, str):
        try:
            cd = datetime.fromisoformat(cd).date()
        except Exception:
            cd = date.today()
    setS("costing_date", cd or date.today())
    setS("prepared_by",  h.get("prepared_by", ""))
    setS("approved_by",  h.get("approved_by", ""))
    setS("scope_summary",h.get("scope_summary", ""))

    # State snapshot — restores all the line lists, percentages, rates
    try:
        state = json.loads(h.get("state_json") or "{}")
        for k, v in state.items():
            setS(k, v)
    except Exception as e:
        st.warning(f"Could not parse state snapshot: {e}")

    # Pull child lines (DB is the source of truth — overrides snapshot)
    lines = db.get_costing_lines(costing_id)
    if lines:
        clean = []
        for r in lines:
            d = {k: v for k, v in r.items()
                 if k not in ("id", "costing_id", "line_no",
                              "created_at", "updated_at")}
            clean.append(d)
        setS("equipment_lines", clean)

    return True
