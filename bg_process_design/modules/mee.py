"""
N-Effect MEE with Vapor Integration - Calculation Engine
Based on: ECOX-BG 100KLD MEE-ATFD_INTEGRATION.xlsx (ECOX-BG Ver1.0/2025)

Supports 2 to 7 effects (configurable via n_effects input).

Key methodology (per the Excel sheets):
  - Forward feed arrangement, E-01 hottest, E-N coolest
  - Shell-side of each effect = previous effect's vapor (E-01 uses steam)
  - Each effect's vapor is bled partially into its downstream Pre-Heater (PH)
  - PH-1..PH-N preheat feed progressively; PH-C uses condenser vapor
  - Venting loss = 0.5% of shell vapor supply
  - Flash evaporation from condensate entering next-lower-pressure shell
  - Steam Economy = total evap / steam to E-01
"""
import math
from bg_process_design.utils.steam_table import (
    latent_heat_at_temp, temp_at_pressure,
    vapor_density_at_temp, enthalpy_vapor_at_temp,
)


def calc_mee(inputs: dict) -> dict:
    """
    4-effect MEE with vapor integration.

    Key inputs:
      feed_rate_kgh, feed_ts_pct (fraction), outlet_ts_pct (fraction),
      effect_temps_c (list 4: shell temps E-01..E-04),
      boiling_point_rise_c (list 4),
      steam_pressure_bar,
      stripper_vapor_kgh, stripper_vapor_solvent_pct, stripper_vapor_water_pct,
      U_calandria (list 4), U_preheater,
      feed_inlet_temps (list 5: PH-1..PH-C),
      product_outlet_temps (list 5: PH-1..PH-C),
      cw_in_c, cw_out_c, subcooling_c,
      operating_hours_day, operating_days_year,
      steam_cost_inr_kg, power_cost_inr_kwh, cw_cost_inr_m3
    """
    F = inputs.get("feed_rate_kgh", 18000.0)
    feed_ts = inputs.get("feed_ts_pct", 0.022)
    out_ts = inputs.get("outlet_ts_pct", 0.43)
    n_effects = int(inputs.get("n_effects", 4))
    if n_effects < 2:
        n_effects = 2
    if n_effects > 7:
        n_effects = 7
    steam_p = inputs.get("steam_pressure_bar", 3.0)

    # Feed characterization (optional, for parameter tracking)
    feed_char = inputs.get("feed_characterization")

    # Default effect shell temps: linear progression from ~105°C down to ~50°C
    default_shell_T = _generate_default_shell_temps(n_effects)
    effect_T = inputs.get("effect_temps_c", default_shell_T)
    if len(effect_T) < n_effects:
        effect_T = _extend_list(effect_T, n_effects, default_shell_T)

    # BPR: either user-supplied OR auto-calculate from concentration per effect
    auto_bpr = inputs.get("auto_bpr_from_ts", False)
    default_bpr = _generate_default_bpr(n_effects)
    BPR = inputs.get("boiling_point_rise_c", default_bpr)
    if len(BPR) < n_effects:
        BPR = _extend_list(BPR, n_effects, default_bpr)

    str_vap = inputs.get("stripper_vapor_kgh", 0)
    str_solv_pct = inputs.get("stripper_vapor_solvent_pct", 0.45)
    str_water_pct = inputs.get("stripper_vapor_water_pct", 0.55)

    cw_in = inputs.get("cw_in_c", 32.0)
    cw_out = inputs.get("cw_out_c", 38.0)
    subcool = inputs.get("subcooling_c", 5.0)

    # Default U: declines with effect (more fouling, lower T diff)
    default_U = [max(400, 700 - i * 50) for i in range(n_effects)]
    U_cal = inputs.get("U_calandria", default_U)
    if len(U_cal) < n_effects:
        U_cal = _extend_list(U_cal, n_effects, default_U)
    U_ph = inputs.get("U_preheater", 800)

    # Pre-heaters: one per effect + PH-C (condenser preheater) = n_effects + 1 PHs
    n_ph = n_effects + 1
    default_feed_inlets = _generate_default_feed_inlets(n_ph)
    default_prod_outlets = _generate_default_product_outlets(n_ph)
    feed_inlets = inputs.get("feed_inlet_temps", default_feed_inlets)
    if len(feed_inlets) < n_ph:
        feed_inlets = _extend_list(feed_inlets, n_ph, default_feed_inlets)
    product_outlets = inputs.get("product_outlet_temps", default_prod_outlets)
    if len(product_outlets) < n_ph:
        product_outlets = _extend_list(product_outlets, n_ph, default_prod_outlets)

    cp_fluid = inputs.get("cp_fluid_kcalkgk", 0.95)
    cp_hot = 0.98

    # ----- Overall mass balance -----
    total_solids = F * feed_ts
    final_conc_kgh = total_solids / out_ts
    total_evap = F - final_conc_kgh

    # ----- Plan concentrations (equal evap per effect) -----
    conc_steps = _plan_concentrations_equal_evap(feed_ts, out_ts, n_effects, F)

    # Import feed char helper if needed
    if feed_char and auto_bpr:
        from bg_process_design.utils.feed_characterization import (
            calc_bpr_from_ts, propagate_feed_through_evaporation
        )
    elif feed_char:
        from bg_process_design.utils.feed_characterization import propagate_feed_through_evaporation
    elif auto_bpr:
        from bg_process_design.utils.feed_characterization import calc_bpr_from_ts

    effects = []
    feed_flow = F
    current_conc = feed_ts
    current_feed_char = dict(feed_char) if feed_char else None
    for i in range(n_effects):
        next_conc = conc_steps[i + 1]
        prod_kgh = total_solids / next_conc if next_conc > 0 else feed_flow
        evap_kgh = feed_flow - prod_kgh

        vapor_T = (effect_T[i + 1] if i + 1 < len(effect_T) else 50.0)

        # Auto-calculate BPR from product concentration (post-evap)
        if auto_bpr:
            bpr_effective = calc_bpr_from_ts(next_conc)
            BPR[i] = bpr_effective  # update in-place so LMTD uses it
        else:
            bpr_effective = BPR[i]

        boil_elev = vapor_T + bpr_effective

        # Propagate feed characterization through this effect
        effect_feed_char_in = dict(current_feed_char) if current_feed_char else None
        effect_feed_char_out = None
        if current_feed_char:
            effect_feed_char_out = propagate_feed_through_evaporation(
                current_feed_char, feed_flow, evap_kgh
            )
            current_feed_char = effect_feed_char_out

        effects.append({
            "effect_no": i + 1,
            "feed_kgh": feed_flow,
            "feed_conc": current_conc,
            "product_kgh": prod_kgh,
            "product_conc": next_conc,
            "evap_kgh": evap_kgh,
            "shell_temp_c": effect_T[i],
            "bpr_c": bpr_effective,
            "boiling_temp_elevated_c": boil_elev,
            "vapor_gen_temp_c": vapor_T,
            "feed_characterization_in": effect_feed_char_in,
            "feed_characterization_out": effect_feed_char_out,
        })
        feed_flow = prod_kgh
        current_conc = next_conc

    # ----- Pre-Heater Design (PH-1 .. PH-N, PH-C) -----
    preheaters = []
    for i in range(n_ph):
        if i < n_effects:
            shell_T_ph = effect_T[i]
        else:
            shell_T_ph = effect_T[-1] - BPR[-1]

        feed_in_ph = feed_inlets[i] if i < len(feed_inlets) else 30.0
        feed_out_ph = product_outlets[i] if i < len(product_outlets) else 40.0

        lt_vap_ph = latent_heat_at_temp(shell_T_ph)
        Q_ph = F * cp_hot * (feed_out_ph - feed_in_ph)
        LMTD_ph = _lmtd(shell_T_ph, shell_T_ph, feed_in_ph, feed_out_ph)
        HTA_ph = (Q_ph * 1.163) / (U_ph * LMTD_ph) if LMTD_ph > 0 else 0
        vapor_consumed = Q_ph / lt_vap_ph if lt_vap_ph > 0 else 0

        preheaters.append({
            "ph_name": f"PH-{i+1}" if i < n_effects else "PH-C",
            "shell_temp_c": shell_T_ph,
            "feed_inlet_c": feed_in_ph,
            "feed_outlet_c": feed_out_ph,
            "approach_c": 10.0,
            "Q_kcalh": Q_ph,
            "lmtd_c": LMTD_ph,
            "HTA_calc_m2": HTA_ph,
            "HTA_selected_m2": math.ceil(HTA_ph / 2) * 2,
            "vapor_consumed_kgh": vapor_consumed,
            "lt_heat_kcalkg": lt_vap_ph,
        })

    # ----- Vapor-integrated Heat Balance (iterate) -----
    steam_T = temp_at_pressure(steam_p)
    lt_steam = latent_heat_at_temp(steam_T)

    str_vapor_recoverable = str_vap * 0.9
    str_vapor_usable = str_vapor_recoverable * str_water_pct

    steam_consumption_kgh = 0
    for iteration in range(20):
        steam_prev = steam_consumption_kgh

        for i, eff in enumerate(effects):
            shell_T = eff["shell_temp_c"]
            boil_elev = eff["boiling_temp_elevated_c"]
            vapor_T = eff["vapor_gen_temp_c"]
            feed_T_in = product_outlets[i] if i < len(product_outlets) else boil_elev

            temp_rise = max(0, boil_elev - feed_T_in)
            Q_sensible = eff["feed_kgh"] * cp_fluid * temp_rise
            lt_vap_tube = latent_heat_at_temp(vapor_T)
            Q_evap = eff["evap_kgh"] * lt_vap_tube
            Q_total_req = Q_sensible + Q_evap

            # Flash from previous condensate
            flash_kgh = 0
            if i > 0 and effects[i - 1].get("shell_vapor_supply_kgh"):
                prev_cond_T = effect_T[i - 1]
                curr_shell_T = shell_T
                cp_cond = 1.0
                lh = latent_heat_at_temp(curr_shell_T)
                flash_frac = cp_cond * (prev_cond_T - curr_shell_T) / lh if lh > 0 else 0
                flash_kgh = max(0, effects[i - 1]["shell_vapor_supply_kgh"] * flash_frac)
            eff["flash_evap_kgh"] = flash_kgh

            if i == 0:
                lt_shell = lt_steam
                eff["shell_source"] = f"Steam @ {steam_T:.1f}°C"

                Q_from_stripper = str_vapor_usable * latent_heat_at_temp(80) if str_vap > 0 else 0
                Q_from_steam = max(0, Q_total_req - Q_from_stripper)
                steam_required = Q_from_steam / lt_shell

                eff["shell_vapor_supply_kgh"] = steam_required
                eff["stripper_vapor_used_kgh"] = str_vapor_usable if str_vap > 0 else 0
                steam_consumption_kgh = steam_required
            else:
                prev_evap = effects[i - 1]["evap_kgh"]
                ph_bleed = preheaters[i - 1]["vapor_consumed_kgh"] if i - 1 < len(preheaters) else 0
                venting = prev_evap * 0.005
                available_vapor = prev_evap - ph_bleed - venting + flash_kgh

                lt_shell = latent_heat_at_temp(effect_T[i - 1])
                Q_from_vapor = available_vapor * lt_shell

                eff["shell_source"] = f"Vapor E-0{i} @ {effect_T[i-1]:.1f}°C"
                eff["shell_vapor_supply_kgh"] = available_vapor
                eff["shell_heat_available_kcalh"] = Q_from_vapor

            eff["lt_heat_shell"] = lt_shell
            eff["lt_heat_tube"] = lt_vap_tube
            eff["Q_total_kcalh"] = Q_total_req
            eff["Q_sensible_kcalh"] = Q_sensible
            eff["Q_evap_kcalh"] = Q_evap
            eff["ph_vapor_bleed_kgh"] = (
                preheaters[i]["vapor_consumed_kgh"] if i < len(preheaters) else 0
            )
            eff["venting_kgh"] = eff["evap_kgh"] * 0.005

            LMTD = shell_T - boil_elev
            if LMTD <= 0:
                LMTD = 3.0
            HTA = (Q_total_req * 1.163) / (U_cal[i] * LMTD) if LMTD > 0 else 0
            eff["lmtd_c"] = LMTD
            eff["U_calandria"] = U_cal[i]
            eff["HTA_calc_m2"] = HTA
            eff["HTA_selected_m2"] = math.ceil(HTA / 5) * 5

        if abs(steam_consumption_kgh - steam_prev) < 1.0:
            break

    # ----- VLS & Tube sizing per effect (after heat balance converges) -----
    from bg_process_design.utils.equipment_sizing import size_vls, size_tube_bundle
    from bg_process_design.utils.steam_table import vapor_density_at_temp

    for i, eff in enumerate(effects):
        # VLS sizing: vapor generated at this effect's tube-side T
        vapor_T = eff["vapor_gen_temp_c"]
        rho_V = vapor_density_at_temp(vapor_T)
        # Fluid density: heavier for higher-conc. later effects
        rho_L = 1050 + i * 50  # 1050 kg/m³ for E-1, up to 1200 for E-4
        eff["vls"] = size_vls(
            vapor_flow_kgh=eff["evap_kgh"],
            vapor_density_kgm3=rho_V,
            liquid_density_kgm3=rho_L,
            k_factor=0.05,  # B&G standard for vertical VLS
            l_over_d_ratio=2.5,
        )

        # Calandria tubes: 2" × 2.0 mm tubes, 6 m length for MEE (standard for B&G)
        # RCP flow typical = 20x evap rate, velocity 1.5 m/s
        rcp_flow_m3h = eff["evap_kgh"] * 20.0 / rho_L
        eff["calandria_tubes"] = size_tube_bundle(
            hta_selected_m2=eff["HTA_selected_m2"],
            tube_od_mm=50.8, tube_thk_mm=2.0,
            tube_length_m=6.0, n_passes=1,  # Falling-film or FC: single pass
            target_velocity_ms=1.5,
            fluid_flow_m3h=rcp_flow_m3h,
        )
        eff["rcp_flow_m3h"] = rcp_flow_m3h
        eff["liquid_density_kgm3"] = rho_L

    # Pre-heater tube geometry
    for i, ph in enumerate(preheaters):
        ph["tubes"] = size_tube_bundle(
            hta_selected_m2=ph["HTA_selected_m2"],
            tube_od_mm=25.4, tube_thk_mm=1.6,
            tube_length_m=6.0, n_passes=5,  # Per Excel PH design
            target_velocity_ms=1.5,
            fluid_flow_m3h=F / 1050.0,  # feed flow
        )

    # ----- Condenser -----
    last_evap_avail = (effects[-1]["evap_kgh"]
                       - preheaters[-1]["vapor_consumed_kgh"]
                       - effects[-1]["evap_kgh"] * 0.005)
    last_evap_avail = max(0, last_evap_avail)
    condenser_T = effect_T[-1] - BPR[-1]
    lt_cond = latent_heat_at_temp(condenser_T)
    inert_in = last_evap_avail * 0.005
    cp_air = 0.24
    cp_vap = 0.44

    Q_sensible_c = (inert_in * cp_air + last_evap_avail * cp_vap) * subcool
    Q_latent_c = last_evap_avail * lt_cond
    Q_cond_total = Q_sensible_c + Q_latent_c
    LMTD_c = _lmtd(condenser_T, condenser_T - subcool, cw_in, cw_out)
    U_cond = 600
    HTA_cond = (Q_cond_total * 1.163) / (U_cond * LMTD_c) if LMTD_c > 0 else 0
    HTA_cond_sel = math.ceil(HTA_cond / 5) * 5
    cw_flow_m3h = Q_cond_total / (1000 * (cw_out - cw_in)) if (cw_out - cw_in) > 0 else 0

    # Condenser tube geometry
    condenser_tubes = size_tube_bundle(
        hta_selected_m2=HTA_cond_sel, tube_od_mm=25.4, tube_thk_mm=1.6,
        tube_length_m=6.0, n_passes=4, target_velocity_ms=1.55,
        fluid_flow_m3h=cw_flow_m3h,
    )

    steam_economy = total_evap / steam_consumption_kgh if steam_consumption_kgh > 0 else 0

    # ----- MEE Pump Sizing -----
    from bg_process_design.utils.equipment_sizing import size_pump, PUMP_DEFAULTS
    pumps = {}

    # Feed pump
    fp_d = PUMP_DEFAULTS["mee_feed_pump"]
    pumps["feed_pump"] = size_pump(
        flow_kgh=F, head_mlc=fp_d["head_mlc"],
        fluid_density_kgm3=fp_d["density_kgm3"],
        efficiency=fp_d["efficiency"], service="MEE Feed Pump"
    )
    # Per-effect RCPs
    for i, eff in enumerate(effects):
        rcp_d = PUMP_DEFAULTS["mee_rcp"]
        pumps[f"rcp_e{i+1}"] = size_pump(
            flow_kgh=eff["rcp_flow_m3h"] * eff["liquid_density_kgm3"],
            head_mlc=rcp_d["head_mlc"],
            fluid_density_kgm3=eff["liquid_density_kgm3"],
            efficiency=rcp_d["efficiency"],
            service=f"MEE E-0{i+1} Re-Circ Pump"
        )
    # Product pump
    prod_d = PUMP_DEFAULTS["mee_product_pump"]
    pumps["product_pump"] = size_pump(
        flow_kgh=final_conc_kgh, head_mlc=prod_d["head_mlc"],
        fluid_density_kgm3=prod_d["density_kgm3"],
        efficiency=prod_d["efficiency"], service="MEE Product Pump"
    )
    # Condensate pump
    cp_d = PUMP_DEFAULTS["mee_cond_pump"]
    pumps["condensate_pump"] = size_pump(
        flow_kgh=total_evap, head_mlc=cp_d["head_mlc"],
        fluid_density_kgm3=cp_d["density_kgm3"],
        efficiency=cp_d["efficiency"], service="MEE Condensate Pump"
    )
    # CW pump
    cwp_d = PUMP_DEFAULTS["mee_cw_pump"]
    pumps["cw_pump"] = size_pump(
        flow_kgh=cw_flow_m3h * 1000, head_mlc=cwp_d["head_mlc"],
        fluid_density_kgm3=cwp_d["density_kgm3"],
        efficiency=cwp_d["efficiency"], service="MEE CW Pump"
    )

    # Total power from full pump sizing
    total_power = sum(p["motor_kw_selected"] for p in pumps.values())

    # ----- Economics -----
    op_h_day = inputs.get("operating_hours_day", 20)
    op_d_year = inputs.get("operating_days_year", 300)
    steam_cost = inputs.get("steam_cost_inr_kg", 2.0)
    power_cost = inputs.get("power_cost_inr_kwh", 8.0)
    cw_cost = inputs.get("cw_cost_inr_m3", 90.0)

    daily_steam_cost = steam_consumption_kgh * op_h_day * steam_cost
    daily_power_cost = total_power * op_h_day * power_cost
    daily_cw_cost = cw_flow_m3h * 0.02 * op_h_day * cw_cost
    total_daily_op = daily_steam_cost + daily_power_cost + daily_cw_cost
    annual_op = total_daily_op * op_d_year
    cost_per_kl = total_daily_op / (F * op_h_day / 1000.0) if F > 0 else 0

    # Final concentrate feed characterization + salt routing
    concentrate_feed_char = current_feed_char if feed_char else None
    salt_routing = None
    if feed_char:
        from bg_process_design.utils.feed_characterization import calc_salt_routing
        salt_routing = calc_salt_routing(feed_char, F, out_ts * 100)

    return {
        "feed_kgh": F,
        "feed_ts_pct": feed_ts * 100,
        "outlet_ts_pct": out_ts * 100,
        "n_effects": n_effects,
        "total_evap_kgh": total_evap,
        "final_concentrate_kgh": final_conc_kgh,
        "feed_characterization": feed_char,
        "concentrate_feed_characterization": concentrate_feed_char,
        "salt_routing": salt_routing,
        "auto_bpr_used": auto_bpr,
        "effects": effects,
        "preheaters": preheaters,
        "steam_consumption_kgh": steam_consumption_kgh,
        "steam_economy": steam_economy,
        "stripper_vapor_integrated_kgh": str_vapor_usable if str_vap > 0 else 0,
        "condenser": {
            "vapor_in_kgh": last_evap_avail,
            "heat_load_kcalh": Q_cond_total,
            "lmtd_c": LMTD_c,
            "HTA_calc_m2": HTA_cond,
            "HTA_selected_m2": HTA_cond_sel,
            "cw_flow_m3h": cw_flow_m3h,
            "cw_in_c": cw_in,
            "cw_out_c": cw_out,
            "tubes": condenser_tubes,
        },
        "pumps": pumps,
        "utilities": {
            "steam_kgh": steam_consumption_kgh,
            "power_kw": total_power,
            "cw_m3h": cw_flow_m3h,
            "cw_makeup_m3h": cw_flow_m3h * 0.02,
        },
        "economics": {
            "daily_steam_cost_inr": daily_steam_cost,
            "daily_power_cost_inr": daily_power_cost,
            "daily_cw_cost_inr": daily_cw_cost,
            "total_daily_op_cost_inr": total_daily_op,
            "annual_op_cost_inr": annual_op,
            "cost_per_kl_inr": cost_per_kl,
            "operating_hours_day": op_h_day,
            "operating_days_year": op_d_year,
        },
    }


def _plan_concentrations_equal_evap(feed_conc, final_conc, n_effects, F):
    """Plan concentrations such that evaporation is roughly equal per effect."""
    total_solids = F * feed_conc
    total_evap = F - (total_solids / final_conc)
    evap_per_effect = total_evap / n_effects

    steps = [feed_conc]
    remaining = F
    for i in range(n_effects):
        remaining -= evap_per_effect
        if remaining <= total_solids / final_conc:
            remaining = total_solids / final_conc
        conc = total_solids / remaining
        steps.append(min(conc, final_conc))
    steps[-1] = final_conc
    return steps


def _lmtd(T1_in, T1_out, T2_in, T2_out):
    dT1 = T1_in - T2_out
    dT2 = T1_out - T2_in
    if dT1 <= 0 or dT2 <= 0:
        return 1e-6
    if abs(dT1 - dT2) < 0.01:
        return dT1
    return (dT1 - dT2) / math.log(dT1 / dT2)


def _generate_default_shell_temps(n_effects):
    """Generate linear progression of shell temps from ~105°C (E-1) down to ~60°C (E-N).
    Last effect must be >5°C above condenser temp (which is ~50°C at atm) for LMTD."""
    T_hot = 105.4
    T_cold = 60.0
    if n_effects == 1:
        return [T_hot]
    step = (T_hot - T_cold) / (n_effects - 1) if n_effects > 1 else 0
    return [round(T_hot - i * step, 1) for i in range(n_effects)]


def _generate_default_bpr(n_effects):
    """Boiling Point Rise: increases with effect number (more concentrated → higher BPR)."""
    return [round(1.0 + i * 0.5, 1) for i in range(n_effects)]


def _generate_default_feed_inlets(n_ph):
    """Feed inlet temps to each PH (PH-N is coldest = ambient-ish, PH-1 is hottest)."""
    T_hot = 83.5
    T_cold = 30.0
    if n_ph == 1:
        return [T_hot]
    step = (T_hot - T_cold) / (n_ph - 1)
    return [round(T_hot - i * step, 1) for i in range(n_ph)]


def _generate_default_product_outlets(n_ph):
    """Product outlet temps from each PH (10°C approach to shell temp)."""
    T_hot = 94.8
    T_cold = 40.0
    if n_ph == 1:
        return [T_hot]
    step = (T_hot - T_cold) / (n_ph - 1)
    return [round(T_hot - i * step, 1) for i in range(n_ph)]


def _extend_list(lst, target_len, default):
    """Safely extend a user-provided list to target length, padding from defaults."""
    result = list(lst)
    while len(result) < target_len:
        idx = len(result)
        result.append(default[idx] if idx < len(default) else default[-1])
    return result[:target_len]
