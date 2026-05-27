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

    Returns the six canonical keys used everywhere in the offer generator.
    Missing values fall back to whatever is already in `fallback`.

    Override priority (first hit wins per field):
        1. process_json["economics"][<key>]
        2. process_json["plant_wide"]["economics"][<key>]
        3. process_json["project"]["operating"][<key>]
        4. process_json["operating_parameters"][<key>]
        5. process_json["project"][<key>]
        6. fallback[<key>]
    """
    sources = []
    sources.append(process_json.get("economics") or {})
    plant_wide = process_json.get("plant_wide") or {}
    sources.append(plant_wide.get("economics") or {})
    proj = process_json.get("project") or {}
    sources.append(proj.get("operating") or {})
    sources.append(process_json.get("operating_parameters") or {})
    sources.append(proj)

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
        "power_cost_inr_kwh": [
            "power_cost_inr_kwh", "power_cost_rs_per_kwh", "power_cost",
            "electricity_cost", "power_rate",
        ],
        "cooling_water_cost_inr_m3": [
            "cooling_water_cost_inr_m3", "cooling_water_cost_rs_per_m3",
            "cooling_water_cost", "cw_cost", "cooling_water_rate",
        ],
        "effluent_treatment_cost_inr_kl": [
            "effluent_treatment_cost_inr_kl", "effluent_treatment_cost",
            "effluent_cost_per_kl", "etp_cost_per_kl",
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
    def _safe_float(v, default):
        try: return float(v)
        except (TypeError, ValueError): return float(default)
    def _safe_int(v, default):
        try: return int(v)
        except (TypeError, ValueError): return int(default)

    out["operating_hours_day"]            = _safe_float(out["operating_hours_day"], fallback.get("operating_hours_day", 20))
    out["operating_days_year"]            = _safe_int(out["operating_days_year"], fallback.get("operating_days_year", 300))
    out["steam_cost_inr_kg"]              = _safe_float(out["steam_cost_inr_kg"], fallback.get("steam_cost_inr_kg", 2.0))
    out["power_cost_inr_kwh"]             = _safe_float(out["power_cost_inr_kwh"], fallback.get("power_cost_inr_kwh", 9.0))
    out["cooling_water_cost_inr_m3"]      = _safe_float(out["cooling_water_cost_inr_m3"], fallback.get("cooling_water_cost_inr_m3", 90.0))
    out["effluent_treatment_cost_inr_kl"] = _safe_float(out["effluent_treatment_cost_inr_kl"], fallback.get("effluent_treatment_cost_inr_kl", 1185.0))
    return out


def _recalc_economics_inplace(offer: dict) -> None:
    """
    Compute derived economics + plant-wide utility totals.

    Mirrors _recalc_economics() in pages/11_Offer_Generator.py so a freshly
    bridged offer has correct derived values before the user opens Tab 4 or 5.
    """
    econ = offer.get("economics", {})
    ts = offer.get("technical_specs", {})
    ut = offer.setdefault("utilities", {})
    cap = float(offer.get("cover", {}).get("capacity_kld", 0) or 0)

    hours = float(econ.get("operating_hours_day", 20) or 0)
    days  = float(econ.get("operating_days_year", 300) or 0)
    steam_cost = float(econ.get("steam_cost_inr_kg", 2.0) or 0)

    # Steam comparison
    conv_kgh = float(econ.get("conventional_steam_kgh", 0) or 0)
    ecox_kgh = float(econ.get("ecox_steam_kgh", 0) or 0)
    conv_annual_t = (conv_kgh * hours * days) / 1000.0
    ecox_annual_t = (ecox_kgh * hours * days) / 1000.0
    conv_cost_cr = (conv_annual_t * steam_cost) / 10000.0
    ecox_cost_cr = (ecox_annual_t * steam_cost) / 10000.0
    reduction_pct = ((conv_kgh - ecox_kgh) / conv_kgh * 100.0) if conv_kgh > 0 else 0.0

    econ["conventional_annual_steam_tons"] = round(conv_annual_t, 2)
    econ["conventional_annual_cost_cr"]    = round(conv_cost_cr, 4)
    econ["ecox_annual_steam_tons"]         = round(ecox_annual_t, 2)
    econ["ecox_annual_cost_cr"]            = round(ecox_cost_cr, 4)
    econ["steam_reduction_pct"]            = round(reduction_pct, 2)
    econ["annual_steam_savings_tons"]      = round(conv_annual_t - ecox_annual_t, 2)
    econ["annual_savings_lakhs"]           = round((conv_cost_cr - ecox_cost_cr) * 100.0, 2)

    # Plant-wide totals
    def _f(v):
        try: return float(v)
        except (TypeError, ValueError): return 0.0

    units = ["stripper", "mee", "atfd"]
    total_steam = sum(_f(ts.get(u, {}).get("steam_kgh", 0)) for u in units)
    total_power = sum(_f(ts.get(u, {}).get("power_kwh", 0)) for u in units)
    total_cw_m3 = sum(_f(ts.get(u, {}).get("cooling_water_m3h", 0)) for u in units)
    total_cw_tr = sum(_f(ts.get(u, {}).get("cooling_water_tr", 0)) for u in units)

    ut["total_steam_kgh"]         = round(total_steam)
    ut["total_power_kwh"]         = round(total_power)
    ut["total_cooling_water_m3h"] = round(total_cw_m3)
    ut["total_cooling_water_tr"]  = round(total_cw_tr)
    ut["power_consumption_kwh"]   = round(total_power)
    ut["cooling_water_m3h"]       = round(total_cw_m3)

    # Annual operational cost
    eff_cost = float(econ.get("effluent_treatment_cost_inr_kl", 0) or 0)
    econ["annual_operational_cost_inr"] = round(eff_cost * cap * days)


def _bridge_unit_utilities(unit_results: dict, target_unit: dict) -> None:
    """Copy steam/power/cooling water/CA from a process_design unit's
    results dict into the offer's technical_specs[unit] dict."""
    if not unit_results:
        return

    # Steam
    if unit_results.get("steam_consumption_kgh") is not None:
        target_unit["steam_kgh"] = round(float(unit_results["steam_consumption_kgh"]))
    if unit_results.get("steam_pressure_barg") is not None:
        target_unit["steam_pressure"] = f"{unit_results['steam_pressure_barg']} Bar-g"
    elif unit_results.get("steam_pressure"):
        target_unit["steam_pressure"] = str(unit_results["steam_pressure"])

    # Power
    for key in ("power_kw", "power_consumption_kw", "power_kwh"):
        if unit_results.get(key) is not None:
            target_unit["power_kwh"] = round(float(unit_results[key]))
            break

    # Cooling water
    for key in ("cw_m3h", "cooling_water_m3h"):
        if unit_results.get(key) is not None:
            target_unit["cooling_water_m3h"] = round(float(unit_results[key]))
            break
    for key in ("cw_tr", "cooling_water_tr"):
        if unit_results.get(key) is not None:
            target_unit["cooling_water_tr"] = round(float(unit_results[key]))
            break

    # Compressed air
    for key in ("compressed_air_nm3h", "ca_nm3h"):
        if unit_results.get(key) is not None:
            target_unit["compressed_air_nm3h"] = str(unit_results[key])
            break


def bridge_to_offer_data(process_json: dict, existing_data: dict = None) -> dict:
    """
    Convert process design export JSON into offer data structure.

    Strategy: Start with sensible defaults (or existing_data if provided),
    overlay numeric specs from the process design JSON, leave commercial
    terms untouched.

    Returns: complete offer data dict ready for DOCX generation.
    """
    offer = existing_data if existing_data else default_offer_data()

    project = process_json.get("project", {})

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
        cap = project["capacity_kld"]
        offer["cover"]["subject"] = f"Proposal for {cap} KLD STRIPPER, MEE & ATFD System"
    if project.get("scheme"):
        import re
        m = re.search(r'(\d+)[\-\s]*(effect|MEE|eff)', project["scheme"], re.IGNORECASE)
        if m:
            offer["process_description"]["n_effects"] = int(m.group(1))

    # --- Feed Parameters (if process design provides them) ---
    feed_src = process_json.get("feed") or process_json.get("feed_parameters") or {}
    if feed_src:
        fp = offer["feed_parameters"]
        for src_key, dst_key in [
            ("ph", "feed_ph"), ("feed_ph", "feed_ph"),
            ("specific_gravity", "specific_gravity"), ("sg", "specific_gravity"),
            ("cod_ppm", "total_cod_ppm"), ("total_cod_ppm", "total_cod_ppm"),
            ("vos_ppm", "volatile_organic_solvents_ppm"),
            ("total_solids_pct", "total_solids_pct"), ("ts_pct", "total_solids_pct"),
            ("suspended_solids_ppm", "suspended_solids_ppm"),
            ("feed_temp_c", "feed_temp_c"), ("temperature_c", "feed_temp_c"),
            ("total_hardness_ppm", "total_hardness_ppm"),
            ("silica_ppm", "silica_ppm"),
            ("free_chloride_ppm", "free_chloride_ppm"),
            ("feed_nature", "feed_nature"), ("nature", "feed_nature"),
        ]:
            if src_key in feed_src and feed_src[src_key] not in (None, ""):
                fp[dst_key] = feed_src[src_key]

    # --- Stripper section ---
    stripper = process_json.get("stripper", {})
    if stripper.get("status") == "designed":
        s_res = stripper.get("results", {})
        sp = offer["technical_specs"]["stripper"]
        if s_res.get("feed_kgh"):
            sp["feed_kgh"] = round(s_res["feed_kgh"])
        if s_res.get("distillate_kgh"):
            sp["distillate_kgh"] = round(s_res["distillate_kgh"])
        if s_res.get("bottoms_kgh"):
            sp["bottoms_kgh"] = round(s_res["bottoms_kgh"])
        if s_res.get("reflux_kgh"):
            sp["reflux_kgh"] = round(s_res["reflux_kgh"])
        _bridge_unit_utilities(s_res, sp)
        # Legacy utilities mirror
        if sp.get("steam_kgh"):
            offer["utilities"]["stripper_steam"]["value_kgh"] = sp["steam_kgh"]

    # --- MEE section ---
    mee = process_json.get("mee", {})
    if mee.get("status") == "designed":
        m_res = mee.get("results", {})
        mp = offer["technical_specs"]["mee"]
        if m_res.get("n_effects"):
            n = m_res["n_effects"]
            offer["process_description"]["n_effects"] = n
            mp["type"] = f"{n}-Effect Multiple Effect Evaporator"
        if m_res.get("feed_kgh"):
            mp["feed_kgh"] = round(m_res["feed_kgh"])
        if m_res.get("feed_ts_pct") is not None:
            mp["feed_solids_pct"] = round(m_res["feed_ts_pct"], 2)
        if m_res.get("total_evap_kgh"):
            mp["evaporation_kgh"] = round(m_res["total_evap_kgh"])
        if m_res.get("final_concentrate_kgh"):
            mp["concentrate_kgh"] = round(m_res["final_concentrate_kgh"])
        if m_res.get("outlet_ts_pct"):
            mp["concentrate_solids_pct"] = round(m_res["outlet_ts_pct"])
        if m_res.get("steam_economy"):
            mp["steam_economy"] = round(m_res["steam_economy"], 1)
        _bridge_unit_utilities(m_res, mp)
        # Legacy utilities mirror
        if mp.get("steam_kgh"):
            offer["utilities"]["mee_steam"]["value_kgh"] = mp["steam_kgh"]
        if mp.get("steam_economy"):
            offer["utilities"]["mee_steam"]["steam_economy"] = mp["steam_economy"]

    # --- ATFD section ---
    atfd = process_json.get("atfd", {})
    if atfd.get("status") == "designed":
        a_res = atfd.get("results", {})
        ap = offer["technical_specs"]["atfd"]
        if a_res.get("feed_kgh"):
            ap["feed_kgh"] = round(a_res["feed_kgh"])
        if a_res.get("feed_ts_pct") is not None:
            ap["feed_solids_pct"] = round(a_res["feed_ts_pct"])
        if a_res.get("water_evap_kgh"):
            ap["evaporation_kgh"] = round(a_res["water_evap_kgh"])
        if a_res.get("product_kgh"):
            ap["product_kgh"] = round(a_res["product_kgh"])
        _bridge_unit_utilities(a_res, ap)
        # Legacy utilities mirror
        if ap.get("steam_kgh"):
            offer["utilities"]["atfd_steam"]["value_kgh"] = ap["steam_kgh"]

    # --- Economics overall parameters ---
    econ = offer.setdefault("economics", {})
    overall = _extract_economics_overall(process_json, fallback=econ)
    for k, v in overall.items():
        econ[k] = v

    # --- Steam comparison (kg/h) — driven by MEE design results ---
    mee_res = mee.get("results", {}) if mee else {}
    if mee_res.get("steam_consumption_kgh") is not None:
        ecox_steam = float(mee_res["steam_consumption_kgh"])
        # Conventional baseline = total water evaporation (steam economy = 1.0)
        if mee_res.get("total_evap_kgh"):
            conv_steam = float(mee_res["total_evap_kgh"])
        else:
            ecox_se = float(mee_res.get("steam_economy") or 4.0)
            conv_steam = ecox_steam * ecox_se
        econ["conventional_steam_kgh"] = round(conv_steam)
        econ["ecox_steam_kgh"]         = round(ecox_steam)

    # --- Derived fields (annual tons, costs, savings, totals, OPEX) ---
    _recalc_economics_inplace(offer)

    return offer


def summarize_bridge_result(process_json: dict, offer: dict) -> list:
    """Return a list of markdown lines describing what was imported."""
    lines = []
    project = process_json.get("project", {})
    if project.get("project_name"):
        lines.append(f"✅ Project: {project['project_name']}")
    if project.get("buyer"):
        lines.append(f"✅ Client: {project['buyer']}")
    if project.get("capacity_kld"):
        lines.append(f"✅ Capacity: {project['capacity_kld']} KLD")

    for unit in ["stripper", "mee", "atfd"]:
        u = process_json.get(unit, {})
        if u.get("status") == "designed":
            ts = offer["technical_specs"].get(unit, {})
            steam = ts.get("steam_kgh", 0)
            power = ts.get("power_kwh", 0)
            cw    = ts.get("cooling_water_m3h", 0)
            lines.append(
                f"✅ {unit.upper()} — steam {steam} kg/h, power {power} kWh, CW {cw} m³/h"
            )
        else:
            lines.append(f"⚠️ {unit.upper()} — no design in source JSON, using defaults")

    econ = offer.get("economics", {})
    ut = offer.get("utilities", {})
    if econ.get("conventional_steam_kgh") and econ.get("ecox_steam_kgh"):
        lines.append(
            f"✅ Steam Advantage: {econ['conventional_steam_kgh']} → {econ['ecox_steam_kgh']} kg/h "
            f"({econ.get('steam_reduction_pct', 0):.1f}% reduction, "
            f"₹{econ.get('annual_savings_lakhs', 0):.1f} Lakhs/yr savings)"
        )
    if ut.get("total_steam_kgh"):
        lines.append(
            f"✅ Plant-wide totals: steam {ut['total_steam_kgh']} kg/h, "
            f"power {ut.get('total_power_kwh', 0)} kWh, "
            f"CW {ut.get('total_cooling_water_m3h', 0)} m³/h"
        )

    lines.append("")
    lines.append("👉 Now review the form, edit commercial terms (pricing, "
                 "payment, delivery), then click 'Generate DOCX'.")
    return lines
