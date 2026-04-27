"""
bg_estimation_costing.utils.totals
──────────────────────────────────
Roll-up calculations from line-level data into headline totals.
Pure functions — only read from session state via the state module.
"""
from __future__ import annotations
from typing import Dict, List, Tuple

from bg_estimation_costing.utils.state import S


# Daily rates used for man-hour costing (₹/day)
HOD_RATE_PER_DAY = 12000
MGR_RATE_PER_DAY = 8000
ENG_RATE_PER_DAY = 4000


# ─────────────────────────────────────────────────────────────────────────────
# LINE-LEVEL TOTALS
# ─────────────────────────────────────────────────────────────────────────────
def total_equipment_cost() -> float:
    return sum((l.get("qty", 0) or 0) * (l.get("unit_cost", 0) or 0)
               for l in S("equipment_lines", []) or [])


def total_eia_cost() -> float:
    return sum((l.get("qty", 0) or 0) * (l.get("unit_cost", 0) or 0)
               for l in S("eia_lines", []) or [])


def total_pipeline_cost() -> float:
    return sum(l.get("total", 0) or 0
               for l in S("pipeline_lines", []) or [])


def total_manhours() -> Tuple[List[Dict], float]:
    """Return (per-row breakdown with cost+days, grand-total cost)."""
    out = []
    for l in S("manhour_lines", []) or []:
        days = (l.get("hod") or 0) + (l.get("mgr") or 0) + (l.get("eng") or 0)
        cost = ((l.get("hod") or 0) * HOD_RATE_PER_DAY +
                (l.get("mgr") or 0) * MGR_RATE_PER_DAY +
                (l.get("eng") or 0) * ENG_RATE_PER_DAY)
        out.append({**l, "days": days, "cost": cost})
    return out, sum(x["cost"] for x in out)


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY / SECTION / ITEM-TYPE ROLL-UPS
# ─────────────────────────────────────────────────────────────────────────────
def cost_summary_by(field: str) -> Dict[str, float]:
    """Group equipment cost by any field (category / section / item_type)."""
    out: Dict[str, float] = {}
    for l in S("equipment_lines", []) or []:
        k = l.get(field, "Other") or "Other"
        out[k] = out.get(k, 0.0) + (l.get("qty", 0) or 0) * (l.get("unit_cost", 0) or 0)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PRICE SUMMARY (the key roll-up — drives the metrics bar + Price Summary tab)
# ─────────────────────────────────────────────────────────────────────────────
def price_summary() -> Dict:
    eqp  = total_equipment_cost()
    eia  = total_eia_cost()
    pipe = total_pipeline_cost()
    cat  = cost_summary_by("category")
    op   = eqp + eia + pipe

    def of(p):
        return op * p / 100

    inspection   = of(S("inspection_pct"))
    packing      = of(S("packing_pct"))
    risk         = of(S("risk_pct"))
    overhead     = of(S("overhead_pct"))
    engg_trav    = S("engg_travel_amt", 0) or 0
    transport    = S("transport_amt", 0) or 0
    bo_margin    = (cat.get("B.O-Local", 0) + cat.get("B.O-Imported", 0)) * \
                   S("bo_margin_pct") / 100
    mat_handling = of(S("material_handling_pct"))
    contingency  = of(S("contingency_pct"))

    soft = (inspection + packing + risk + overhead + engg_trav + transport +
            bo_margin + mat_handling)
    supply = op + soft + contingency

    def tier(p):
        return supply / (1 - p / 100) if p < 100 else supply * 1.25

    return dict(
        op_cost=op, eqp=eqp, eia=eia, pipe=pipe,
        inspection=inspection, packing=packing, risk=risk,
        overhead=overhead, engg_trav=engg_trav, transport=transport,
        bo_margin=bo_margin, mat_handling=mat_handling, contingency=contingency,
        soft_cost=soft, supply_cost=supply,
        quote_price=tier(S("bg_margin_pct")),
        best_price=tier(S("best_price_pct")),
        target_price=tier(S("target_price_pct")),
        no_regret_price=tier(S("no_regret_price_pct")),
        category=cat,
    )
