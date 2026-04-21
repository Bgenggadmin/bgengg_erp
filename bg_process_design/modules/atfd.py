"""
Agitated Thin Film Dryer (ATFD) Calculation Engine
Based on: ATFD_40C_100KLD_LEE.xlsx

Calculates:
  - Mass balance (dry solids target)
  - Dryer HTA, steam consumption
  - Condenser, blower sizing
  - Motor rating selection from standard HTA chart
"""
import math
from bg_process_design.utils.steam_table import (
    latent_heat_at_temp, temp_at_pressure,
    pressure_at_temp, specific_volume_at_temp
)


# Standard ATFD motor ratings from Excel (HTA m² -> Motor HP)
MOTOR_RATINGS = [
    (1,   10), (3,   12.5), (5,   15), (7.5, 20),
    (10,  20), (12.5, 30), (15,  40), (20,  40),
    (25,  50), (30,  50), (40,  60), (45,  60),
    (50,  75),
]

# Power consumption kWh/h per HTA m² (modified, from Excel)
POWER_PER_HTA_KWH = {
    1: 6, 3: 8, 5: 10, 7.5: 12, 10: 14, 12.5: 18, 15: 22,
    20: 26, 25: 30, 30: 34, 40: 38, 45: 42, 50: 46,
}


def calc_atfd(inputs: dict) -> dict:
    """
    ATFD calculation.

    inputs keys:
      feed_rate_kgh, feed_ts_pct, feed_temp_c,
      product_ts_pct, shell_temp_c,
      boiling_point_elevation_c, steam_pressure_bar,
      cw_in_c, cw_out_c, subcooling_c, U_dryer,
      air_inleak_pct (for blower sizing)
    """
    F = inputs.get("feed_rate_kgh", 860.0)
    feed_ts = inputs.get("feed_ts_pct", 0.40)  # 40% from MEE outlet
    product_ts = inputs.get("product_ts_pct", 0.90)
    feed_temp = inputs.get("feed_temp_c", 55.0)
    shell_temp = inputs.get("shell_temp_c", 170.0)
    BPE = inputs.get("boiling_point_elevation_c", 10.0)
    steam_p = inputs.get("steam_pressure_bar", 8.0)
    cw_in = inputs.get("cw_in_c", 32.0)
    cw_out = inputs.get("cw_out_c", 38.0)
    subcool = inputs.get("subcooling_c", 40.0)
    U = inputs.get("U_dryer", 230.0)
    cp_feed = inputs.get("sp_heat_feed", 0.80)
    air_inleak_pct = inputs.get("air_inleak_pct", 0.20)  # 20% of vapor
    margin = inputs.get("blower_margin_pct", 0.10)
    blower_dp_mmwc = inputs.get("blower_dp_mmwc", 200)
    blower_eff = inputs.get("blower_efficiency", 0.40)

    # --- Mass Balance ---
    solids = F * feed_ts
    water_in = F - solids
    product_kgh = solids / product_ts
    water_in_product = product_kgh - solids
    water_evap = water_in - water_in_product

    # --- Heat Balance ---
    boiling_sat = 100.0  # atmospheric
    elevated_T = boiling_sat + BPE

    # Sensible heat to raise feed
    Q_sensible = F * cp_feed * (elevated_T - feed_temp)
    lt_vap = latent_heat_at_temp(elevated_T)
    Q_latent_req = water_evap * lt_vap
    Q_total = Q_sensible + Q_latent_req

    # Steam side (shell)
    shell_lt = latent_heat_at_temp(shell_temp)
    steam_consumption = Q_total / shell_lt

    # --- HTA ---
    LMTD = shell_temp - elevated_T
    HTA_calc = (Q_total * 1.163) / (U * LMTD) if LMTD > 0 else 0
    HTA_sel = math.ceil(HTA_calc / 1) * 1
    # Round to nearest standard size
    std_sizes = [1, 3, 5, 7.5, 10, 12.5, 15, 20, 25, 30, 40, 45, 50]
    HTA_std = next((s for s in std_sizes if s >= HTA_calc), 50)

    # --- Motor Selection ---
    motor_hp = 25
    for hta_thresh, hp in MOTOR_RATINGS:
        if HTA_std <= hta_thresh:
            motor_hp = hp
            break

    # Power consumption (actual)
    power_kwh = POWER_PER_HTA_KWH.get(HTA_std, 30)
    connected_load_kw = power_kwh * 1.2  # 20% margin

    # --- Condenser ---
    inert_in = water_evap * air_inleak_pct
    # Subcooled temp after condensation
    cp_air = 0.24
    cp_vap_heat = 0.44
    avg_cp = (cp_air * inert_in + cp_vap_heat * water_evap) / (inert_in + water_evap)

    Q_cond_sensible = (inert_in * cp_air + water_evap * cp_vap_heat) * subcool
    Q_cond_latent = water_evap * lt_vap
    Q_cond_total = Q_cond_sensible + Q_cond_latent

    cond_vap_temp = 100
    LMTD_c = _lmtd(cond_vap_temp, cond_vap_temp - subcool, cw_in, cw_out)
    U_c = 500
    HTA_cond_calc = (Q_cond_total * 1.163) / (U_c * LMTD_c) if LMTD_c > 0 else 0
    HTA_cond_sel = math.ceil(HTA_cond_calc / 5) * 5

    cw_flow = Q_cond_total / (1000 * (cw_out - cw_in))

    # --- Blower ---
    vapor_temp_blower = 97  # Post-condenser slightly subcooled
    sp_vol = specific_volume_at_temp(vapor_temp_blower)
    vapor_vol_m3h = (water_evap + inert_in) * sp_vol * (1 + margin)
    vapor_vol_cfm = vapor_vol_m3h * 0.5886  # m³/h to CFM

    # Power: P = (Q * dP) / (eta * 3600 * 1000) kW; dP mmWC -> Pa: *9.81
    dp_pa = blower_dp_mmwc * 9.81
    Q_m3s = vapor_vol_m3h / 3600.0
    blower_power_kw = (Q_m3s * dp_pa) / (blower_eff * 1000)
    blower_motor_hp = math.ceil(blower_power_kw * 1.341 * 1.5)  # 50% margin

    # --- Condenser tube geometry & Pumps ---
    from bg_process_design.utils.equipment_sizing import size_tube_bundle, size_pump, PUMP_DEFAULTS

    cond_tubes = size_tube_bundle(
        hta_selected_m2=HTA_cond_sel, tube_od_mm=25.4, tube_thk_mm=1.65,
        tube_length_m=3.0, n_passes=6, target_velocity_ms=1.6,
        fluid_flow_m3h=cw_flow,
    )

    pumps = {}
    # ATFD feed pump
    fp_d = PUMP_DEFAULTS["atfd_feed_pump"]
    pumps["feed_pump"] = size_pump(
        flow_kgh=F, head_mlc=fp_d["head_mlc"],
        fluid_density_kgm3=fp_d["density_kgm3"],
        efficiency=fp_d["efficiency"], service="ATFD Feed Pump"
    )
    # Condensate pump
    cp_d = PUMP_DEFAULTS["atfd_cond_pump"]
    pumps["condensate_pump"] = size_pump(
        flow_kgh=water_evap, head_mlc=cp_d["head_mlc"],
        fluid_density_kgm3=cp_d["density_kgm3"],
        efficiency=cp_d["efficiency"], service="ATFD Condensate Pump"
    )
    # CW pump
    cwp_d = PUMP_DEFAULTS["atfd_cw_pump"]
    pumps["cw_pump"] = size_pump(
        flow_kgh=cw_flow * 1000, head_mlc=cwp_d["head_mlc"],
        fluid_density_kgm3=cwp_d["density_kgm3"],
        efficiency=cwp_d["efficiency"], service="ATFD CW Pump"
    )

    # --- Feed Characterization Propagation ---
    feed_char = inputs.get("feed_characterization")
    dry_product_feed_char = None
    if feed_char:
        from bg_process_design.utils.feed_characterization import propagate_feed_through_evaporation
        dry_product_feed_char = propagate_feed_through_evaporation(
            feed_char, F, water_evap
        )

    return {
        # Mass balance
        "feed_kgh": F,
        "feed_ts_pct": feed_ts * 100,
        "product_ts_pct": product_ts * 100,
        "solids_kgh": solids,
        "water_in_kgh": water_in,
        "product_kgh": product_kgh,
        "water_evap_kgh": water_evap,
        "pumps": pumps,

        # Feed characterization
        "feed_characterization": feed_char,
        "dry_product_feed_characterization": dry_product_feed_char,

        # Heat balance
        "shell_temp_c": shell_temp,
        "shell_pressure_bar": steam_p,
        "boiling_temp_c": elevated_T,
        "bpe_c": BPE,
        "lmtd_c": LMTD,
        "Q_sensible_kcalh": Q_sensible,
        "Q_latent_kcalh": Q_latent_req,
        "Q_total_kcalh": Q_total,
        "steam_consumption_kgh": steam_consumption,

        # HTA
        "U_dryer": U,
        "HTA_calc_m2": HTA_calc,
        "HTA_selected_m2": HTA_std,
        "motor_hp": motor_hp,
        "power_consumed_kwh": power_kwh,
        "connected_load_kw": connected_load_kw,

        # Condenser
        "condenser": {
            "vapor_in_kgh": water_evap,
            "inert_in_kgh": inert_in,
            "heat_load_kcalh": Q_cond_total,
            "lmtd_c": LMTD_c,
            "HTA_calc_m2": HTA_cond_calc,
            "HTA_selected_m2": HTA_cond_sel,
            "cw_flow_m3h": cw_flow,
            "cw_in_c": cw_in,
            "cw_out_c": cw_out,
            "tubes": cond_tubes,
        },

        # Blower
        "blower": {
            "vapor_vol_m3h": vapor_vol_m3h,
            "vapor_vol_cfm": vapor_vol_cfm,
            "pressure_drop_mmwc": blower_dp_mmwc,
            "efficiency": blower_eff,
            "power_kw": blower_power_kw,
            "motor_hp": blower_motor_hp,
        },
    }


def _lmtd(T1_in, T1_out, T2_in, T2_out):
    dT1 = T1_in - T2_out
    dT2 = T1_out - T2_in
    if dT1 <= 0 or dT2 <= 0:
        return 1e-6
    if abs(dT1 - dT2) < 0.01:
        return dT1
    return (dT1 - dT2) / math.log(dT1 / dT2)
