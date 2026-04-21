"""
Project / Design Export Utilities

Produces structured JSON files that capture complete design data
for downstream use (PPT generation, client reporting, handoff).

The JSON schema is carefully designed to be self-describing so that
Claude can later read this file and produce a professional PPT
without needing the original conversation context.
"""
import json
from datetime import datetime


def export_stripper_design(project: dict, results: dict, inputs: dict) -> dict:
    """Build a structured export dict for a single stripper design."""
    return {
        "export_metadata": {
            "export_type": "stripper_design",
            "exported_at": datetime.now().isoformat(),
            "export_version": "1.0",
            "app_name": "B&G Process Design",
            "app_version": "1.0",
            "intended_use": "Input for PPT generation, client presentation",
        },
        "project": _clean_project(project),
        "unit": "Stripper Column",
        "inputs": inputs,
        "results": _clean(results),
    }


def export_mee_design(project: dict, results: dict, inputs: dict) -> dict:
    """Build a structured export dict for a single MEE design."""
    return {
        "export_metadata": {
            "export_type": "mee_design",
            "exported_at": datetime.now().isoformat(),
            "export_version": "1.0",
            "app_name": "B&G Process Design",
            "app_version": "1.0",
            "intended_use": "Input for PPT generation, client presentation",
        },
        "project": _clean_project(project),
        "unit": f"{results.get('n_effects', 4)}-Effect MEE with Vapor Integration",
        "inputs": inputs,
        "results": _clean(results),
    }


def export_atfd_design(project: dict, results: dict, inputs: dict) -> dict:
    """Build a structured export dict for a single ATFD design."""
    return {
        "export_metadata": {
            "export_type": "atfd_design",
            "exported_at": datetime.now().isoformat(),
            "export_version": "1.0",
            "app_name": "B&G Process Design",
            "app_version": "1.0",
            "intended_use": "Input for PPT generation, client presentation",
        },
        "project": _clean_project(project),
        "unit": "Agitated Thin Film Dryer (ATFD)",
        "inputs": inputs,
        "results": _clean(results),
    }


def export_full_project(project: dict, stripper_result: dict = None,
                         mee_result: dict = None, atfd_result: dict = None,
                         stripper_inputs: dict = None, mee_inputs: dict = None,
                         atfd_inputs: dict = None) -> dict:
    """
    Build a complete plant-wide export for the project.
    This is the primary file you'd attach when asking Claude to build a PPT.
    """
    export = {
        "export_metadata": {
            "export_type": "full_project",
            "exported_at": datetime.now().isoformat(),
            "export_version": "1.0",
            "app_name": "B&G Process Design",
            "app_version": "1.0",
            "intended_use": "Input for PPT generation, client presentation",
            "ppt_guidance": {
                "suggested_slides": [
                    "Title slide: Project name, buyer, capacity, scheme, design date",
                    "Executive Summary: Key highlights — capacity, steam economy, footprint",
                    "Process Flow Diagram: Stripper → MEE → ATFD overview",
                    "Mass Balance: Feed, intermediates, products, recovery",
                    "Stripper Design: column dia, trays, HTAs, pumps",
                    "MEE Design: N-effect layout, evaporation per effect, steam economy",
                    "MEE Equipment List: Calandrias, VLS, pre-heaters, condenser, pumps",
                    "ATFD Design: HTA, motor, blower, dry product specs",
                    "Feed Characterization: parameter traceability through the plant",
                    "Salt Routing: crystallization estimate for solids disposal",
                    "Utilities Summary: steam, power, cooling water across plant",
                    "Economics: OPEX per day/year, cost per KL treated",
                    "Equipment List: Consolidated pump list with motor HP totals",
                    "Next Steps: vendor engagement, detailed engineering",
                ],
                "tone": "Professional, quantitative, client-facing (B&G Engineering)",
                "avoid": "Internal calculation details, marginal notes, approximations flags",
            },
        },
        "project": _clean_project(project),
        "plant_overview": _build_plant_overview(
            stripper_result, mee_result, atfd_result
        ),
        "stripper": _build_unit_section("Stripper", stripper_result, stripper_inputs),
        "mee": _build_unit_section("MEE", mee_result, mee_inputs),
        "atfd": _build_unit_section("ATFD", atfd_result, atfd_inputs),
        "plant_wide": _build_plant_wide_summary(
            stripper_result, mee_result, atfd_result
        ),
    }
    return export


def _build_plant_overview(s, m, a) -> dict:
    """High-level plant summary for the first PPT slide."""
    overview = {
        "process_scheme": "Stripper → Multi-Effect Evaporator → Agitated Thin Film Dryer",
        "process_flow": "Effluent feed → solvent recovery → water removal → dry solids",
    }
    if s:
        overview["stripper_capacity_kgh"] = s.get("feed_kgh")
        overview["solvent_recovered_kgh"] = s.get("solvent_recovered_kgh")
    if m:
        overview["mee_capacity_kgh"] = m.get("feed_kgh")
        overview["mee_n_effects"] = m.get("n_effects")
        overview["mee_steam_economy"] = m.get("steam_economy")
        overview["mee_total_evaporation_kgh"] = m.get("total_evap_kgh")
    if a:
        overview["atfd_dry_product_kgh"] = a.get("product_kgh")
        overview["atfd_product_ts_pct"] = a.get("product_ts_pct")
    return overview


def _build_unit_section(name, result, inputs) -> dict:
    if not result:
        return {"status": "not_designed", "note": f"{name} unit has no design yet"}
    return {
        "status": "designed",
        "inputs": inputs or {},
        "results": _clean(result),
    }


def _build_plant_wide_summary(s, m, a) -> dict:
    """Consolidated utilities, economics, equipment for plant-wide slides."""
    summary = {}

    # Utilities summary
    utils = {"steam_kgh": 0, "power_kw": 0, "cw_m3h": 0}
    if s:
        utils["steam_kgh"] += s.get("steam_consumption_kgh", 0) or 0
        utils["power_kw"] += s.get("total_power_kwh", 0) or 0
        utils["cw_m3h"] += s.get("cw_flow_m3h", 0) or 0
    if m:
        utils["steam_kgh"] += m.get("steam_consumption_kgh", 0) or 0
        utils["power_kw"] += (m.get("utilities", {}).get("power_kw", 0) or 0)
        utils["cw_m3h"] += (m.get("condenser", {}).get("cw_flow_m3h", 0) or 0)
    if a:
        utils["steam_kgh"] += a.get("steam_consumption_kgh", 0) or 0
        utils["power_kw"] += a.get("connected_load_kw", 0) or 0
        utils["cw_m3h"] += (a.get("condenser", {}).get("cw_flow_m3h", 0) or 0)
    summary["total_utilities"] = utils

    # Consolidated pump list
    all_pumps = []
    for unit_name, res in [("Stripper", s), ("MEE", m), ("ATFD", a)]:
        if res and res.get("pumps"):
            for pump_id, pump in res["pumps"].items():
                all_pumps.append({
                    "unit": unit_name,
                    "pump_id": pump_id,
                    "service": pump.get("service", pump_id),
                    "flow_m3h": pump.get("flow_m3h"),
                    "head_mlc": pump.get("head_mlc"),
                    "motor_hp_selected": pump.get("motor_hp_selected"),
                    "brake_power_kw": pump.get("brake_power_kw"),
                })
    summary["consolidated_pump_list"] = all_pumps
    summary["total_pumps_count"] = len(all_pumps)
    summary["total_motor_hp"] = sum(
        (p.get("motor_hp_selected") or 0) for p in all_pumps
    )

    # Feed characterization traceability
    traceability = []
    if s and s.get("feed_characterization"):
        traceability.append({
            "stage": "1. Raw Effluent Feed",
            "characterization": s["feed_characterization"],
        })
    if s and s.get("bottoms_feed_characterization"):
        traceability.append({
            "stage": "2. Stripper Bottoms (→ MEE feed)",
            "characterization": s["bottoms_feed_characterization"],
        })
    if m and m.get("concentrate_feed_characterization"):
        traceability.append({
            "stage": "3. MEE Concentrate (→ ATFD feed)",
            "characterization": m["concentrate_feed_characterization"],
        })
    if a and a.get("dry_product_feed_characterization"):
        traceability.append({
            "stage": "4. ATFD Dry Product (Final)",
            "characterization": a["dry_product_feed_characterization"],
        })
    summary["feed_characterization_traceability"] = traceability

    # Salt routing (from MEE only)
    if m and m.get("salt_routing"):
        summary["salt_routing"] = m["salt_routing"]

    # Economics (from MEE, since it dominates OPEX)
    if m and m.get("economics"):
        summary["economics"] = m["economics"]

    # Equipment count summary
    eq_count = {
        "stripper_column": 1 if s else 0,
        "mee_effects": (m.get("n_effects", 0) if m else 0),
        "mee_vls": (len(m["effects"]) if m else 0),
        "mee_preheaters": (len(m["preheaters"]) if m else 0),
        "heat_exchangers_total": 0,
        "pumps_total": len(all_pumps),
    }
    # Count HEX (reboiler + condensers per unit)
    if s:
        eq_count["heat_exchangers_total"] += 2  # reboiler + cond-1
        if s.get("condenser2_tubes"):
            eq_count["heat_exchangers_total"] += 1
    if m:
        eq_count["heat_exchangers_total"] += (
            m.get("n_effects", 0)  # calandrias
            + len(m.get("preheaters", []))  # pre-heaters
            + 1  # condenser
        )
    if a:
        eq_count["heat_exchangers_total"] += 2  # dryer + condenser
    summary["equipment_count"] = eq_count

    return summary


def _clean_project(project: dict) -> dict:
    """Clean project dict for export (remove timestamps, ids etc if not wanted)."""
    if not project:
        return {}
    return {
        "project_code": project.get("project_code"),
        "project_name": project.get("project_name"),
        "buyer": project.get("buyer"),
        "plant_location": project.get("plant_location"),
        "capacity_kld": project.get("capacity_kld"),
        "scheme": project.get("scheme"),
        "designed_by": project.get("designed_by"),
        "checked_by": project.get("checked_by"),
        "approved_by": project.get("approved_by"),
        "design_date": project.get("design_date"),
        "revision_no": project.get("revision_no"),
        "notes": project.get("notes"),
    }


def _clean(obj):
    """Recursively clean result dicts — convert non-serializable types."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    # Handle numpy or other numeric types
    try:
        return float(obj)
    except (TypeError, ValueError):
        return str(obj)


def to_json_string(export_dict: dict, indent: int = 2) -> str:
    """Serialize export dict to pretty-printed JSON string."""
    return json.dumps(export_dict, indent=indent, default=str, ensure_ascii=False)


def generate_filename(project: dict, export_type: str) -> str:
    """Generate a clean filename for the export."""
    code = (project.get("project_code") or "project").replace(" ", "_").replace("/", "-")
    rev = project.get("revision_no", 0)
    date = datetime.now().strftime("%Y%m%d")
    return f"{code}_Rev{rev}_{export_type}_{date}.json"


# =====================================================================
# BUILD FULL PROJECT EXPORT (convenience wrapper for ERP pages)
# =====================================================================
def build_full_project_export(conn, project_id) -> dict:
    """
    Load project + all designs from Supabase and return a single export dict.
    Called by the ERP's Process Design page Export tab.
    """
    from bg_process_design.db import get_project, list_designs

    project = get_project(conn, project_id)
    if not project:
        return {}

    # Grab most recent design for each module (if any)
    stripper_list = list_designs(conn, "stripper", project_id)
    mee_list = list_designs(conn, "mee", project_id)
    atfd_list = list_designs(conn, "atfd", project_id)

    def _latest(items):
        return items[0] if items else None

    s = _latest(stripper_list)
    m = _latest(mee_list)
    a = _latest(atfd_list)

    stripper_result = s.get("results") if s else None
    stripper_inputs = s.get("inputs") if s else None
    mee_result = m.get("results") if m else None
    mee_inputs = m.get("inputs") if m else None
    atfd_result = a.get("results") if a else None
    atfd_inputs = a.get("inputs") if a else None

    return export_full_project(
        project,
        stripper_result=stripper_result,
        stripper_inputs=stripper_inputs,
        mee_result=mee_result,
        mee_inputs=mee_inputs,
        atfd_result=atfd_result,
        atfd_inputs=atfd_inputs,
    )
