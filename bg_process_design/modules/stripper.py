"""
Stripper Column Design Calculations
Based on: B&G ECOX Stripper-MEB Design Sheet (File 1)

Calculates:
  - Column diameter (Flooding velocity method, Fair's correlation)
  - Tray hydraulics & pressure drop
  - Reboiler (Forced Circulation) HTA
  - Condenser-1 (CW) & Condenser-2 (CHW) HTA
  - Steam, CW, CHW, Power consumption
"""
import math
from bg_process_design.utils.steam_table import (
    latent_heat_at_temp, temp_at_pressure,
    pressure_at_temp, vapor_density_at_temp
)
from bg_process_design.utils.solvents import calc_mixture_properties


def calc_stripper(inputs: dict) -> dict:
    """
    Main stripper calculation.

    inputs keys:
      feed_rate_kgh, solvent_frac, solids_frac, water_frac,
      solvent_mix (dict name->weight), feed_temp_c,
      steam_pressure_bar, approach_c, tray_spacing_m, tray_hole_dia_mm,
      weir_height_mm, no_of_trays, reflux_ratio,
      cw_in_c, cw_out_c, chw_in_c, chw_out_c,
      sp_heat_solvent, sp_heat_water, liquid_density_kgm3,
      solvent_recovery, subcooling_c
    """

    # --- Unpack with defaults matching Excel ---
    F = inputs.get("feed_rate_kgh", 5000.0)
    solv_frac = inputs.get("solvent_frac", 0.07)
    solids_frac = inputs.get("solids_frac", 0.07)
    water_frac = inputs.get("water_frac", 0.86)
    solvent_mix = inputs.get("solvent_mix", {"Methanol": 0.60, "Ethanol": 0.10,
                                              "Acetone": 0.10, "Toluene": 0.10, "IPA": 0.10})
    feed_temp = inputs.get("feed_temp_c", 85.0)
    steam_p = inputs.get("steam_pressure_bar", 3.0)
    approach = inputs.get("approach_c", 35.0)
    tray_spacing = inputs.get("tray_spacing_m", 0.45)
    hole_dia = inputs.get("tray_hole_dia_mm", 6.5)
    weir_height = inputs.get("weir_height_mm", 50.8)
    n_trays = inputs.get("no_of_trays", 25)
    R = inputs.get("reflux_ratio", 0.25)
    cw_in = inputs.get("cw_in_c", 32.0)
    cw_out = inputs.get("cw_out_c", 37.0)
    chw_in = inputs.get("chw_in_c", 10.0)
    chw_out = inputs.get("chw_out_c", 15.0)
    cp_solv = inputs.get("sp_heat_solvent", 2.14)  # kJ/kg.K ~ 0.51 kcal/kg.K but Excel uses 2.14
    cp_water = inputs.get("sp_heat_water", 1.0)
    rho_L = inputs.get("liquid_density_kgm3", 900.0)
    recov = inputs.get("solvent_recovery", 0.98)
    subcool = inputs.get("subcooling_c", 30.0)

    # Normalize solvent mixture to sum = solv_frac
    mix_sum = sum(solvent_mix.values())
    if mix_sum > 0:
        solvent_mix = {k: v / mix_sum for k, v in solvent_mix.items()}

    # --- Mass Balance ---
    solvent_in_kgh = F * solv_frac
    solids_in_kgh = F * solids_frac
    water_in_kgh = F * water_frac

    distillate_solvent = solvent_in_kgh * recov
    distillate_water_frac = 0.30  # Typical for stripper: 70% solvent / 30% water in distillate
    # Distillate rate from fractions: solv / 0.70
    D = distillate_solvent / 0.70
    distillate_water = D - distillate_solvent

    B = F - D
    bottom_solids = solids_in_kgh
    bottom_solvent = solvent_in_kgh - distillate_solvent
    bottom_water = water_in_kgh - distillate_water

    # --- Solvent mixture properties ---
    weighted_mix = {k: v * solvent_in_kgh for k, v in solvent_mix.items()}
    props = calc_mixture_properties(weighted_mix)
    avg_mw_solv = props["avg_mw"]
    avg_bp_solv = props["avg_bp"]

    # Vapor in column (top): L = R*D, V = L + D = (R+1)*D
    L = R * D
    V_kgh = (R + 1) * D

    # Top composition (mirror distillate): 70% solvent / 30% water by weight
    # Avg MW at top
    top_water_moles = 0.30 / 18.0
    top_solv_moles = 0.70 / avg_mw_solv
    top_avg_mw = 1.0 / (top_water_moles + top_solv_moles)

    # Vapor density at top of column at ~85°C
    T_top = 85.0
    # Ideal gas: rho = P*MW/(R*T), at atm pressure
    rho_V = (101.325 * top_avg_mw) / (8.314 * (T_top + 273.15))  # kg/m³

    # --- Column Diameter (Fair's correlation) ---
    V_kgs = V_kgh / 3600.0
    L_kgh = L + F  # Reflux + feed going down
    L_kgs = L_kgh / 3600.0

    FLV = (L_kgs / V_kgs) * math.sqrt(rho_V / rho_L) if V_kgs > 0 else 0
    # K from Fair's chart (simplified correlation vs FLV at tray spacing 0.45m)
    # Excel shows K ≈ 0.0355 at FLV ≈ 0.27
    K = 0.0283 + 0.0275 * math.exp(-FLV * 2.5)
    UF = K * math.sqrt((rho_L - rho_V) / rho_V)  # Flooding velocity
    U_design = 0.65 * UF  # 65% flooding (Excel default)

    bubbling_area = V_kgs / (rho_V * U_design) if U_design > 0 else 0
    column_area = bubbling_area / 0.65
    col_dia_calc = math.sqrt(4 * column_area / math.pi)
    col_dia_sel = math.ceil(col_dia_calc * 20) / 20.0  # Round up to nearest 0.05 m

    # --- Tray Pressure Drop ---
    hole_area_ratio = 0.10  # 10% of bubbling area
    hole_velocity = V_kgs / (rho_V * bubbling_area * hole_area_ratio) if bubbling_area > 0 else 0
    Cd = 0.72
    hd = 51.0 * (hole_velocity ** 2 / (2 * 9.81)) * (rho_V / rho_L) * (1 / Cd ** 2)  # mm liquid
    Lw = 0.77 * col_dia_sel  # Weir length (77% of dia)
    Q_L_m3min = L_kgh / rho_L / 60.0
    how = 664 * (Q_L_m3min / Lw) ** (2.0 / 3.0) if Lw > 0 else 0
    hl = 0.5 * (weir_height + how) + hd * 0.4
    ht = hd + hl
    # Froth height (Zc) = 2 * ht typically
    Zc = 2 * ht
    Z_downcomer = 2 * Zc
    dp_per_tray = hd + hl  # mm liquid
    dp_total_mm = dp_per_tray * n_trays
    dp_total_bar = dp_total_mm * rho_L * 9.81 / 1e8

    # --- Reboiler Design ---
    reboiler_shell_T = temp_at_pressure(steam_p)
    lt_heat_shell = latent_heat_at_temp(reboiler_shell_T)
    # Sensible heat: feed from MEE-PH inlet -> column bottom temp
    avg_cp = solv_frac * cp_solv + water_frac * cp_water + solids_frac * 0.85
    reboiler_inlet_T = feed_temp + 10  # Typical rise
    reboiler_outlet_T = reboiler_inlet_T + 3
    Q_sensible = F * avg_cp * (reboiler_outlet_T - feed_temp)  # kcal/h

    lt_heat_solv = 260.0  # kcal/kg avg for solvent mix
    lt_heat_water_vap = latent_heat_at_temp(reboiler_outlet_T)
    # Heat for evaporation
    Q_evap = (distillate_solvent * lt_heat_solv + distillate_water * lt_heat_water_vap)
    Q_reb_total = Q_sensible + Q_evap

    steam_consumption = Q_reb_total / lt_heat_shell

    LMTD_reb = _lmtd(reboiler_shell_T, reboiler_shell_T, reboiler_inlet_T, reboiler_outlet_T)
    U_reb = inputs.get("U_reboiler", 700)  # W/m2.K for FC reboiler (v7: was hardcoded)
    HTA_reb = (Q_reb_total * 1.163) / (U_reb * LMTD_reb)  # kcal->W: *1.163
    HTA_reb_sel = math.ceil(HTA_reb / 2) * 2

    # --- Condenser-1 (CW) ---
    # Heat load from vapor condensation
    Q_cond_solv = distillate_solvent * lt_heat_solv
    Q_cond_water = distillate_water * latent_heat_at_temp(T_top)
    Q_cond1 = Q_cond_solv + Q_cond_water
    LMTD_c1 = _lmtd(T_top, T_top, cw_in, cw_out)
    U_c1 = inputs.get("U_cond1", 200)  # v7: was hardcoded
    HTA_c1 = (Q_cond1 * 1.163) / (U_c1 * LMTD_c1)
    HTA_c1_sel = math.ceil(HTA_c1 / 5) * 5

    cw_flow_m3h = Q_cond1 / (1000 * (cw_out - cw_in))

    # --- Condenser-2 (CHW) - subcooling ---
    # For very light solvents; mostly zero unless needed
    Q_cond2 = 0
    HTA_c2_sel = 0
    chw_flow_m3h = 0
    if inputs.get("use_condenser2", False):
        condenser2_load = distillate_solvent * 0.1 * lt_heat_solv  # Trap 10%
        LMTD_c2 = _lmtd(T_top, T_top - subcool, chw_in, chw_out)
        U_c2 = inputs.get("U_cond2", 150)  # v7: was hardcoded
        Q_cond2 = condenser2_load
        HTA_c2 = (Q_cond2 * 1.163) / (U_c2 * LMTD_c2)
        HTA_c2_sel = math.ceil(HTA_c2 / 2) * 2
        chw_flow_m3h = Q_cond2 / (1000 * (chw_out - chw_in))

    # --- Full Pump Sizing (Stripper) ---
    from bg_process_design.utils.equipment_sizing import size_pump, size_tube_bundle, PUMP_DEFAULTS

    pumps = {}
    # Feed pump
    feed_d = PUMP_DEFAULTS["stripper_feed_pump"]
    pumps["feed_pump"] = size_pump(
        flow_kgh=F, head_mlc=feed_d["head_mlc"],
        fluid_density_kgm3=feed_d["density_kgm3"],
        efficiency=feed_d["efficiency"], service="Stripper Feed Pump"
    )
    # Reboiler RCP (18x recirculation)
    rcp_d = PUMP_DEFAULTS["stripper_rcp"]
    pumps["rcp"] = size_pump(
        flow_kgh=F * 18.0, head_mlc=rcp_d["head_mlc"],
        fluid_density_kgm3=rcp_d["density_kgm3"],
        efficiency=rcp_d["efficiency"], service="Stripper Reboiler RCP"
    )
    # Reflux pump
    rfx_d = PUMP_DEFAULTS["stripper_reflux_pump"]
    pumps["reflux_pump"] = size_pump(
        flow_kgh=D, head_mlc=rfx_d["head_mlc"],
        fluid_density_kgm3=rfx_d["density_kgm3"],
        efficiency=rfx_d["efficiency"], service="Stripper Reflux Pump"
    )
    # Steam condensate pump
    sc_d = PUMP_DEFAULTS["stripper_steam_cond_pump"]
    pumps["steam_cond_pump"] = size_pump(
        flow_kgh=steam_consumption, head_mlc=sc_d["head_mlc"],
        fluid_density_kgm3=sc_d["density_kgm3"],
        efficiency=sc_d["efficiency"], service="Stripper Steam Condensate Pump"
    )

    # Legacy keys for backward compat
    rcp_flow = pumps["rcp"]["flow_m3h"]
    rcp_bkw = pumps["rcp"]["brake_power_kw"]
    rp_flow = pumps["reflux_pump"]["flow_m3h"]
    rp_bkw = pumps["reflux_pump"]["brake_power_kw"]
    total_power = sum(p["brake_power_kw"] for p in pumps.values())

    # --- Tube Bundle Geometry ---
    # v7: tube specs resolved from inputs['hx_specs'] with fallback to SERVICE_PRESETS
    from bg_process_design.utils.equipment_sizing import resolve_hx_specs

    reb_specs = resolve_hx_specs(inputs, "reboiler", "REBOILER")
    reboiler_tubes = size_tube_bundle(
        hta_selected_m2=HTA_reb_sel,
        tube_od_mm=reb_specs["od_mm"], tube_thk_mm=reb_specs["thk_mm"],
        tube_length_m=reb_specs["length_m"], n_passes=reb_specs["passes"],
        target_velocity_ms=reb_specs["velocity_ms"],
        fluid_flow_m3h=rcp_flow * 0.85,  # ~85% of RCP flow through tubes
    )
    c1_specs = resolve_hx_specs(inputs, "condenser1", "CONDENSER_CW")
    cond1_tubes = size_tube_bundle(
        hta_selected_m2=HTA_c1_sel,
        tube_od_mm=c1_specs["od_mm"], tube_thk_mm=c1_specs["thk_mm"],
        tube_length_m=c1_specs["length_m"], n_passes=c1_specs["passes"],
        target_velocity_ms=c1_specs["velocity_ms"],
        fluid_flow_m3h=cw_flow_m3h,
    )
    cond2_tubes = None
    if inputs.get("use_condenser2", False):
        c2_specs = resolve_hx_specs(inputs, "condenser2", "CONDENSER_CHW")
        cond2_tubes = size_tube_bundle(
            hta_selected_m2=HTA_c2_sel,
            tube_od_mm=c2_specs["od_mm"], tube_thk_mm=c2_specs["thk_mm"],
            tube_length_m=c2_specs["length_m"], n_passes=c2_specs["passes"],
            target_velocity_ms=c2_specs["velocity_ms"],
            fluid_flow_m3h=chw_flow_m3h,
        )

    # --- Feed Characterization Propagation (optional) ---
    feed_char = inputs.get("feed_characterization")
    bottoms_feed_char = None
    if feed_char:
        from bg_process_design.utils.feed_characterization import propagate_feed_through_stripper
        bottoms_feed_char = propagate_feed_through_stripper(
            feed_char, F, D, distillate_is_solvent_water=True
        )

    # --- Package results ---
    return {
        # Mass balance
        "feed_kgh": F,
        "distillate_kgh": D,
        "bottoms_kgh": B,
        "solvent_in_kgh": solvent_in_kgh,
        "solvent_recovered_kgh": distillate_solvent,
        "water_evap_kgh": distillate_water,
        "avg_solvent_mw": avg_mw_solv,
        "avg_solvent_bp": avg_bp_solv,

        # Feed characterization
        "feed_characterization": feed_char,
        "bottoms_feed_characterization": bottoms_feed_char,

        # Column hydraulics
        "vapor_flow_kgh": V_kgh,
        "liquid_flow_kgh": L_kgh,
        "vapor_density": rho_V,
        "liquid_density": rho_L,
        "FLV": FLV,
        "K_factor": K,
        "flooding_velocity_ms": UF,
        "design_velocity_ms": U_design,
        "bubbling_area_m2": bubbling_area,
        "column_area_m2": column_area,
        "column_dia_calc_m": col_dia_calc,
        "column_dia_selected_m": col_dia_sel,

        # Tray hydraulics
        "no_of_trays": n_trays,
        "tray_spacing_m": tray_spacing,
        "hole_dia_mm": hole_dia,
        "weir_length_m": Lw,
        "weir_height_mm": weir_height,
        "hd_mm": hd,
        "how_mm": how,
        "hl_mm": hl,
        "ht_mm": ht,
        "froth_height_mm": Zc,
        "downcomer_height_mm": Z_downcomer,
        "dp_per_tray_mm": dp_per_tray,
        "dp_total_mm": dp_total_mm,
        "dp_total_bar": dp_total_bar,

        # Reboiler
        "reboiler_shell_temp": reboiler_shell_T,
        "reboiler_inlet_temp": reboiler_inlet_T,
        "reboiler_outlet_temp": reboiler_outlet_T,
        "reboiler_heat_load_kcalh": Q_reb_total,
        "reboiler_sensible_kcalh": Q_sensible,
        "reboiler_evap_kcalh": Q_evap,
        "reboiler_lmtd": LMTD_reb,
        "reboiler_U": U_reb,
        "reboiler_HTA_calc": HTA_reb,
        "reboiler_HTA_selected": HTA_reb_sel,
        "steam_consumption_kgh": steam_consumption,

        # Condensers
        "condenser1_heat_load_kcalh": Q_cond1,
        "condenser1_lmtd": LMTD_c1,
        "condenser1_U": U_c1,
        "condenser1_HTA_calc": HTA_c1,
        "condenser1_HTA_selected": HTA_c1_sel,
        "cw_flow_m3h": cw_flow_m3h,
        "condenser2_heat_load_kcalh": Q_cond2,
        "condenser2_HTA_selected": HTA_c2_sel,
        "chw_flow_m3h": chw_flow_m3h,

        # Pumps (legacy keys)
        "rcp_flow_m3h": rcp_flow,
        "rcp_bkw": rcp_bkw,
        "reflux_pump_flow_m3h": rp_flow,
        "reflux_pump_bkw": rp_bkw,
        "total_power_kwh": total_power,

        # Full pump table
        "pumps": pumps,

        # Tube geometry
        "reboiler_tubes": reboiler_tubes,
        "condenser1_tubes": cond1_tubes,
        "condenser2_tubes": cond2_tubes,
    }


def _lmtd(T1_hot_in, T1_hot_out, T2_cold_in, T2_cold_out):
    """Log Mean Temperature Difference, countercurrent."""
    dT1 = T1_hot_in - T2_cold_out
    dT2 = T1_hot_out - T2_cold_in
    if dT1 <= 0 or dT2 <= 0:
        return 1e-6
    if abs(dT1 - dT2) < 0.01:
        return dT1
    return (dT1 - dT2) / math.log(dT1 / dT2)
