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
    econ = plant_wide.get("economics", {})
    if econ:
        if econ.get("operating_hours_day"):
            offer["economics"]["operating_hours_day"] = econ["operating_hours_day"]
        if econ.get("operating_days_year"):
            offer["economics"]["operating_days_year"] = econ["operating_days_year"]
        # Compute conventional vs ECOX comparison (conventional SE ~ 1.0, ECOX uses actual)
        mee_res = mee.get("results", {})
        if mee_res.get("steam_consumption_kgh"):
            ecox_steam = mee_res["steam_consumption_kgh"]
            ecox_se = mee_res.get("steam_economy", 4.0)
            conventional_steam = mee_res.get("total_evap_kgh", ecox_steam * ecox_se)  # SE=1 conventional
            offer["economics"]["conventional_steam_kgh"] = round(conventional_steam)
            offer["economics"]["ecox_steam_kgh"] = round(ecox_steam)
            if conventional_steam > 0:
                offer["economics"]["steam_reduction_pct"] = round(
                    (conventional_steam - ecox_steam) / conventional_steam * 100
                )
            # Annual comparisons
            hours_year = offer["economics"]["operating_hours_day"] * offer["economics"]["operating_days_year"]
            conv_annual_tons = round(conventional_steam * hours_year / 1000)
            ecox_annual_tons = round(ecox_steam * hours_year / 1000)
            offer["economics"]["conventional_annual_steam_tons"] = conv_annual_tons
            offer["economics"]["ecox_annual_steam_tons"] = ecox_annual_tons
            offer["economics"]["annual_steam_savings_tons"] = conv_annual_tons - ecox_annual_tons
            # Cost savings
            steam_cost = offer["economics"]["steam_cost_inr_kg"]
            offer["economics"]["conventional_annual_cost_cr"] = round(
                conv_annual_tons * 1000 * steam_cost / 1e7, 2
            )
            offer["economics"]["ecox_annual_cost_cr"] = round(
                ecox_annual_tons * 1000 * steam_cost / 1e7, 2
            )
            savings_cr = (offer["economics"]["conventional_annual_cost_cr"]
                           - offer["economics"]["ecox_annual_cost_cr"])
            offer["economics"]["annual_savings_lakhs"] = round(savings_cr * 100)

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

    lines.append("")
    lines.append("👉 Now review the form below, edit commercial terms (pricing, "
                  "payment, delivery), then click 'Generate DOCX'.")
    return lines
