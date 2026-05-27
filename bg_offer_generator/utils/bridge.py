"""
Process Design → Offer Data Bridge

Takes a JSON file exported from the bg_process_design app and maps its
structured output into the offer data dict used by this app.

This saves trainee engineers from retyping technical specs that were
already calculated in the design tool.
"""
import json
from bg_offer_generator.utils.default_data import default_offer_data


def parse_process_design_json(json_content: str) -> dict:
    """Parse uploaded JSON string into a Python dict."""
    return json.loads(json_content)


def _extract_economics_overall(process_json: dict, fallback: dict) -> dict:
    """
    Pull overall economics parameters from the process design JSON.

    Looks in several common locations and accepts multiple field-name aliases
    because the process design schema may evolve over time. Returns the three
    canonical keys used everywhere in the offer generator. Missing values
    fall back to the value already present in `fallback` (i.e. whatever was
    in offer["economics"] before the bridge ran).

    Override priority (first hit wins for each field):
        1. process_json["economics"][<key>]
        2. process_json["plant_wide"]["economics"][<key>]
        3. process_json["project"]["operating"][<key>]
        4. process_json["operating_parameters"][<key>]
        5. process_json["project"][<key>]
        6. fallback[<key>]
    """
    # Candidate source dicts in priority order
    sources = []
    sources.append(process_json.get("economics") or {})
    plant_wide = process_json.get("plant_wide") or {}
    sources.append(plant_wide.get("economics") or {})
    proj = process_json.get("project") or {}
    sources.append(proj.get("operating") or {})
    sources.append(process_json.get("operating_parameters") or {})
    sources.append(proj)

    # Field aliases — process_design might use different names
    aliases = {
        "operating_hours_day": [
            "operating_hours_day", "operating_hours_per_day", "operating_hours",
            "op_hours_per_day", "hours_per_day", "daily_operating_hours",
        ],
        "operating_days_year": [
            "operating_days_year", "operating_days_per_year", "days_per_year",
            "annual_operating_days", "days_of_operation", "operating_days",
        ],
        "steam_cost_inr_kg": [
            "steam_cost_inr_kg", "steam_cost_rs_per_kg", "steam_cost",
            "steam_rate_rs_per_kg", "steam_price_per_kg", "steam_unit_cost",
        ],
    }

    out = {}
    for canonical, alias_list in aliases.items():
        value = None
        for src in sources:
            if not isinstance(src, dict):
                continue
            for alias in alias_list:
                if alias in src and src[alias] not in (None, ""):
                    value = src[alias]
                    break
            if value is not None:
                break
        out[canonical] = value if value is not None else fallback.get(canonical)

    # Coerce types
    try:
        out["operating_hours_day"] = float(out["operating_hours_day"])
    except (TypeError, ValueError):
        out["operating_hours_day"] = float(fallback.get("operating_hours_day", 20))
    try:
        out["operating_days_year"] = int(out["operating_days_year"])
    except (TypeError, ValueError):
        out["operating_days_year"] = int(fallback.get("operating_days_year", 300))
    try:
        out["steam_cost_inr_kg"] = float(out["steam_cost_inr_kg"])
    except (TypeError, ValueError):
        out["steam_cost_inr_kg"] = float(fallback.get("steam_cost_inr_kg", 2.0))

    return out


def _recalc_economics_inplace(econ: dict) -> None:
    """
    Compute derived economics fields from raw inputs, writing back into `econ`.

    Mirrors _recalc_economics() in pages/11_Offer_Generator.py so a freshly
    bridged offer has correct derived values even before the user opens Tab 4.
    """
    hours = float(econ.get("operating_hours_day", 20) or 0)
    days  = float(econ.get("operating_days_year", 300) or 0)
    cost_per_kg = float(econ.get("steam_cost_inr_kg", 2.0) or 0)

    conv_kgh = float(econ.get("conventional_steam_kgh", 0) or 0)
    ecox_kgh = float(econ.get("ecox_steam_kgh", 0) or 0)

    conv_annual_t = (conv_kgh * hours * days) / 1000.0
    ecox_annual_t = (ecox_kgh * hours * days) / 1000.0
    conv_cost_cr = (conv_annual_t * cost_per_kg) / 10000.0
    ecox_cost_cr = (ecox_annual_t * cost_per_kg) / 10000.0
    reduction_pct = ((conv_kgh - ecox_kgh) / conv_kgh * 100.0) if conv_kgh > 0 else 0.0
    savings_tons  = conv_annual_t - ecox_annual_t
    savings_lakhs = (conv_cost_cr - ecox_cost_cr) * 100.0

    econ["conventional_annual_steam_tons"] = round(conv_annual_t, 2)
    econ["conventional_annual_cost_cr"]    = round(conv_cost_cr, 4)
    econ["ecox_annual_steam_tons"]         = round(ecox_annual_t, 2)
    econ["ecox_annual_cost_cr"]            = round(ecox_cost_cr, 4)
    econ["steam_reduction_pct"]            = round(reduction_pct, 2)
    econ["annual_steam_savings_tons"]      = round(savings_tons, 2)
    econ["annual_savings_lakhs"]           = round(savings_lakhs, 2)


def bridge_to_offer_data(process_json: dict, existing_data: dict = None) -> dict:
    """
    Convert process design export JSON into offer data structure.

    Strategy: Start with sensible defaults (or existing_data if provided),
    overlay numeric specs from the process design JSON, leave commercial
    terms untouched.

    Returns: complete offer data dict ready for DOCX generation.
    """
    # Start from existing data or defaults
    offer = existing_data if existing_data else default_offer_data()

    # Pull top-level metadata
    project = process_json.get("project", {})
    plant_overview = process_json.get("plant_overview", {})

    # --- Cover section updates ---
    if project.get("project_code"):
        offer["cover"]["quote_ref"] = f"BG/ECOX-ZLD/{project['project_code']}"
    if project.get("buyer"):
        offer["cover"]["submitted_to"] = f"M/s. {project['buyer']}"
    if project.get("plant_location"):
        offer["cover"]["location"] = project["plant_location"]
    if project.get("designed_by"):
        offer["cover"]["prepared_by"] = project["designed_by"]
    if project.get("capacity_kld"):
        offer["cover"]["capacity_kld"] = project["capacity_kld"]
        offer["feed_parameters"]["capacity_kld"] = project["capacity_kld"]
        # Update subject line
        cap = project["capacity_kld"]
        offer["cover"]["subject"] = f"Proposal for {cap} KLD STRIPPER, MEE & ATFD System"
    if project.get("scheme"):
        # Extract number of effects from scheme if possible
        import re
        m = re.search(r'(\d+)[\-\s]*(effect|MEE|eff)', project["scheme"], re.IGNORECASE)
        if m:
            offer["process_description"]["n_effects"] = int(m.group(1))

    # --- Stripper section ---
    stripper = process_json.get("stripper", {})
    if stripper.get("status") == "designed":
        s_res = stripper.get("results", {})
        if s_res.get("feed_kgh"):
            offer["technical_specs"]["stripper"]["feed_kgh"] = round(s_res["feed_kgh"])
        if s_res.get("distillate_kgh"):
            offer["technical_specs"]["stripper"]["distillate_kgh"] = round(s_res["distillate_kgh"])
        if s_res.get("bottoms_kgh"):
            offer["technical_specs"]["stripper"]["bottoms_kgh"] = round(s_res["bottoms_kgh"])
        if s_res.get("steam_consumption_kgh"):
            offer["utilities"]["stripper_steam"]["value_kgh"] = round(s_res["steam_consumption_kgh"])

    # --- MEE section ---
    mee = process_json.get("mee", {})
    if mee.get("status") == "designed":
        m_res = mee.get("results", {})
        if m_res.get("n_effects"):
            n = m_res["n_effects"]
            offer["process_description"]["n_effects"] = n
            offer["technical_specs"]["mee"]["type"] = f"{n}-Effect Multiple Effect Evaporator"
        if m_res.get("feed_kgh"):
            offer["technical_specs"]["mee"]["feed_kgh"] = round(m_res["feed_kgh"])
        if m_res.get("feed_ts_pct"):
            offer["technical_specs"]["mee"]["feed_solids_pct"] = round(m_res["feed_ts_pct"], 2)
        if m_res.get("total_evap_kgh"):
            offer["technical_specs"]["mee"]["evaporation_kgh"] = round(m_res["total_evap_kgh"])
        if m_res.get("final_concentrate_kgh"):
            offer["technical_specs"]["mee"]["concentrate_kgh"] = round(m_res["final_concentrate_kgh"])
        if m_res.get("outlet_ts_pct"):
            offer["technical_specs"]["mee"]["concentrate_solids_pct"] = round(m_res["outlet_ts_pct"])
        if m_res.get("steam_consumption_kgh"):
            offer["utilities"]["mee_steam"]["value_kgh"] = round(m_res["steam_consumption_kgh"])
        if m_res.get("steam_economy"):
            offer["utilities"]["mee_steam"]["steam_economy"] = round(m_res["steam_economy"], 1)

    # --- ATFD section ---
    atfd = process_json.get("atfd", {})
    if atfd.get("status") == "designed":
        a_res = atfd.get("results", {})
        if a_res.get("feed_kgh"):
            offer["technical_specs"]["atfd"]["feed_kgh"] = round(a_res["feed_kgh"])
        if a_res.get("feed_ts_pct"):
            offer["technical_specs"]["atfd"]["feed_solids_pct"] = round(a_res["feed_ts_pct"])
        if a_res.get("water_evap_kgh"):
            offer["technical_specs"]["atfd"]["evaporation_kgh"] = round(a_res["water_evap_kgh"])
        if a_res.get("product_kgh"):
            offer["technical_specs"]["atfd"]["product_kgh"] = round(a_res["product_kgh"])
        if a_res.get("steam_consumption_kgh"):
            offer["utilities"]["atfd_steam"]["value_kgh"] = round(a_res["steam_consumption_kgh"])

    # --- Plant-wide utilities ---
    plant_wide = process_json.get("plant_wide", {})
    totals = plant_wide.get("total_utilities", {})
    if totals.get("power_kw"):
        offer["utilities"]["power_consumption_kwh"] = round(totals["power_kw"])
        offer["utilities"]["power_installed_kw"] = round(totals["power_kw"] * 1.5)  # ~50% margin for standby
    if totals.get("cw_m3h"):
        offer["utilities"]["cooling_water_m3h"] = round(totals["cw_m3h"])

    # --- Economics ---
    econ = offer.setdefault("economics", {})

    # 1. Overall parameters (operating hours, days, steam cost) — pulled from
    #    process design JSON if available, otherwise keep whatever's already
    #    in the offer (which itself defaults to 20 / 300 / ₹2).
    overall = _extract_economics_overall(process_json, fallback=econ)
    econ["operating_hours_day"] = overall["operating_hours_day"]
    econ["operating_days_year"] = overall["operating_days_year"]
    econ["steam_cost_inr_kg"]   = overall["steam_cost_inr_kg"]

    # 2. Steam consumption (kg/h) — derived from MEE design results.
    #    Conventional steam = total evaporation (assumes steam economy 1.0,
    #    i.e. each kg of water evaporated needs ~1 kg of steam).
    #    ECOX steam = actual MEE steam consumption from the design.
    mee_res = mee.get("results", {}) if mee else {}
    if mee_res.get("steam_consumption_kgh") is not None:
        ecox_steam = float(mee_res["steam_consumption_kgh"])
        # Prefer total_evap_kgh as the conventional baseline; fall back to
        # ecox * steam_economy if total_evap_kgh isn't present.
        if mee_res.get("total_evap_kgh"):
            conv_steam = float(mee_res["total_evap_kgh"])
        else:
            ecox_se = float(mee_res.get("steam_economy") or 4.0)
            conv_steam = ecox_steam * ecox_se
        econ["conventional_steam_kgh"] = round(conv_steam)
        econ["ecox_steam_kgh"]         = round(ecox_steam)

    # 3. Derived fields (annual tons, cost Cr/yr, savings %, t, lakhs).
    #    Single source of truth = _recalc_economics_inplace, which uses the
    #    exact formulas specified by the team.
    _recalc_economics_inplace(econ)

    return offer


def summarize_bridge_result(process_json: dict, offer: dict) -> list:
    """
    Return a list of human-readable lines describing what was imported.
    Used for showing the user what got populated vs what needs manual input.
    """
    lines = []
    project = process_json.get("project", {})
    if project.get("project_name"):
        lines.append(f"✅ Project: {project['project_name']}")
    if project.get("buyer"):
        lines.append(f"✅ Client: {project['buyer']}")
    if project.get("capacity_kld"):
        lines.append(f"✅ Capacity: {project['capacity_kld']} KLD")

    # Unit status
    for unit in ["stripper", "mee", "atfd"]:
        u = process_json.get(unit, {})
        if u.get("status") == "designed":
            lines.append(f"✅ {unit.upper()} design imported")
        else:
            lines.append(f"⚠️ {unit.upper()} — no design in source JSON, using defaults")

    # Economics summary
    econ = offer.get("economics", {})
    if econ.get("conventional_steam_kgh") and econ.get("ecox_steam_kgh"):
        lines.append(
            f"✅ Economics: {econ['conventional_steam_kgh']} → {econ['ecox_steam_kgh']} kg/h steam "
            f"({econ.get('steam_reduction_pct', 0):.1f}% reduction, "
            f"₹{econ.get('annual_savings_lakhs', 0):.1f} Lakhs/yr savings)"
        )

    lines.append("")
    lines.append("👉 Now review the form below, edit commercial terms (pricing, "
                  "payment, delivery), then click 'Generate DOCX'.")
    return lines
