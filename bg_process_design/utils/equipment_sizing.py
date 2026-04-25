"""
Equipment Sizing Utilities

Centralized sizing calculations for:
  - Vapor-Liquid Separators (VLS) — cyclonic/gravity separators atop calandrias
  - Heat Exchanger tube geometry (count, passes, velocity, bundle diameter)
  - Pump sizing (centrifugal pumps for liquid handling)

Based on B&G ECOX methodology from the Excel design sheets.
"""
import math


# ---------------------------------------------------------------------
# VAPOR-LIQUID SEPARATOR (VLS)
# ---------------------------------------------------------------------
def size_vls(vapor_flow_kgh: float, vapor_density_kgm3: float,
             liquid_density_kgm3: float = 1050.0,
             k_factor: float = 0.05,
             l_over_d_ratio: float = 2.5) -> dict:
    """
    Size a vertical Vapor-Liquid Separator (VLS / vapor disengagement drum).

    Uses Souders-Brown equation:
        V_term = k × sqrt((ρ_L - ρ_V) / ρ_V)

    k_factor: 0.03–0.05 m/s without demister, 0.1 with demister
      (0.05 is B&G standard for MEE VLS without mesh pad)

    l_over_d_ratio: height/diameter ratio (typical 2.0–3.0 for vertical VLS)

    Returns:
      vapor_vol_m3h, terminal_velocity_ms, vessel_dia_calc_m,
      vessel_dia_selected_m, vessel_height_m, holdup_volume_m3, ...
    """
    if vapor_flow_kgh <= 0 or vapor_density_kgm3 <= 0:
        return _empty_vls()

    # Volumetric flow
    vapor_vol_m3h = vapor_flow_kgh / vapor_density_kgm3
    vapor_vol_m3s = vapor_vol_m3h / 3600.0

    # Souders-Brown terminal velocity
    v_term = k_factor * math.sqrt(
        (liquid_density_kgm3 - vapor_density_kgm3) / vapor_density_kgm3
    )

    # Cross-sectional area needed
    area_m2 = vapor_vol_m3s / v_term if v_term > 0 else 0
    dia_calc_m = math.sqrt(4 * area_m2 / math.pi)

    # Round up to nearest 100 mm (standard vessel diameter)
    dia_sel_m = math.ceil(dia_calc_m * 10) / 10.0

    # Vessel height (tangent-to-tangent) from L/D ratio
    height_m = dia_sel_m * l_over_d_ratio

    # Holdup volume (cylindrical portion, excluding heads)
    holdup_m3 = (math.pi / 4) * (dia_sel_m ** 2) * height_m

    return {
        "vapor_flow_kgh": vapor_flow_kgh,
        "vapor_density_kgm3": vapor_density_kgm3,
        "vapor_vol_m3h": vapor_vol_m3h,
        "k_factor": k_factor,
        "terminal_velocity_ms": v_term,
        "cross_sect_area_m2": area_m2,
        "vessel_dia_calc_m": dia_calc_m,
        "vessel_dia_selected_m": dia_sel_m,
        "l_over_d_ratio": l_over_d_ratio,
        "vessel_height_m": height_m,
        "holdup_volume_m3": holdup_m3,
    }


def _empty_vls():
    return {
        "vapor_flow_kgh": 0, "vapor_density_kgm3": 0, "vapor_vol_m3h": 0,
        "k_factor": 0, "terminal_velocity_ms": 0, "cross_sect_area_m2": 0,
        "vessel_dia_calc_m": 0, "vessel_dia_selected_m": 0, "l_over_d_ratio": 0,
        "vessel_height_m": 0, "holdup_volume_m3": 0,
    }


# ---------------------------------------------------------------------
# HEAT EXCHANGER TUBE GEOMETRY
# ---------------------------------------------------------------------
# Standard tube sizes (OD x thickness in mm)
STANDARD_TUBES = [
    {"od_mm": 19.05, "thk_mm": 1.65, "id_mm": 15.75},   # 3/4" × 1.65
    {"od_mm": 25.40, "thk_mm": 1.65, "id_mm": 22.10},   # 1" × 1.65 (most common for condensers)
    {"od_mm": 25.40, "thk_mm": 1.20, "id_mm": 23.00},   # 1" × 1.2 (thin wall)
    {"od_mm": 25.40, "thk_mm": 2.00, "id_mm": 21.40},   # 1" × 2.0 (thicker)
    {"od_mm": 31.75, "thk_mm": 1.65, "id_mm": 28.45},   # 1-1/4" × 1.65
    {"od_mm": 38.10, "thk_mm": 1.65, "id_mm": 34.80},   # 1-1/2" × 1.65 (reboilers)
    {"od_mm": 50.80, "thk_mm": 2.00, "id_mm": 46.80},   # 2" × 2.0 (calandrias)
]


def size_tube_bundle(hta_selected_m2: float, tube_od_mm: float = 25.4,
                      tube_thk_mm: float = 1.65, tube_length_m: float = 3.0,
                      n_passes: int = 4, target_velocity_ms: float = 1.5,
                      fluid_flow_m3h: float = None) -> dict:
    """
    Calculate tube count, passes, and bundle geometry given HTA.

    Args:
      hta_selected_m2: selected HTA
      tube_od_mm, tube_thk_mm, tube_length_m: tube dimensions
      n_passes: number of tube-side passes (typical 2-8)
      target_velocity_ms: desired tube-side velocity (typical 1-2 m/s for liquid)
      fluid_flow_m3h: actual tube-side flow (used to size velocity if provided)

    Returns dict with tube count, tubes per pass, velocity, pitch, bundle dia, etc.
    """
    if hta_selected_m2 <= 0 or tube_od_mm <= 0 or tube_length_m <= 0:
        return _empty_tube()

    tube_id_mm = tube_od_mm - 2 * tube_thk_mm
    tube_od_m = tube_od_mm / 1000.0
    tube_id_m = tube_id_mm / 1000.0

    # Surface area per tube (OD basis)
    sa_per_tube = math.pi * tube_od_m * tube_length_m
    # X-sectional area per tube (ID basis, for velocity)
    xs_per_tube = math.pi * (tube_id_m ** 2) / 4.0

    # Total tubes required
    total_tubes = math.ceil(hta_selected_m2 / sa_per_tube) if sa_per_tube > 0 else 0

    # Tubes per pass
    tubes_per_pass = math.ceil(total_tubes / n_passes) if n_passes > 0 else total_tubes
    # Adjust total to fit passes evenly
    total_tubes = tubes_per_pass * n_passes
    # Re-compute actual HTA
    actual_hta = total_tubes * sa_per_tube

    # Cross-sectional area per pass
    xs_per_pass = xs_per_tube * tubes_per_pass

    # Velocity (if fluid_flow_m3h given)
    if fluid_flow_m3h and xs_per_pass > 0:
        velocity_calc = (fluid_flow_m3h / 3600.0) / xs_per_pass
    else:
        velocity_calc = target_velocity_ms
        # Back-calculate required flow
        fluid_flow_m3h = velocity_calc * xs_per_pass * 3600.0

    # Tube pitch (typical 1.25 × OD for triangular pitch)
    pitch_mm = 1.25 * tube_od_mm
    # Bundle diameter (empirical: ~1.1 × sqrt(total_tubes × pitch²) for triangular)
    bundle_dia_m = 1.1 * math.sqrt(total_tubes * (pitch_mm / 1000.0) ** 2)
    # Shell ID: bundle + clearance ~50 mm
    shell_id_m = bundle_dia_m + 0.05
    # Round to nearest 50 mm
    shell_id_sel_m = math.ceil(shell_id_m * 20) / 20.0

    return {
        "hta_design_m2": hta_selected_m2,
        "tube_od_mm": tube_od_mm,
        "tube_thk_mm": tube_thk_mm,
        "tube_id_mm": tube_id_mm,
        "tube_length_m": tube_length_m,
        "surface_area_per_tube_m2": sa_per_tube,
        "xs_area_per_tube_m2": xs_per_tube,
        "total_tubes": total_tubes,
        "n_passes": n_passes,
        "tubes_per_pass": tubes_per_pass,
        "actual_hta_m2": actual_hta,
        "tube_velocity_ms": velocity_calc,
        "fluid_flow_m3h": fluid_flow_m3h,
        "pitch_mm": pitch_mm,
        "bundle_dia_m": bundle_dia_m,
        "shell_id_calc_m": shell_id_m,
        "shell_id_selected_m": shell_id_sel_m,
    }


def _empty_tube():
    return {k: 0 for k in [
        "hta_design_m2", "tube_od_mm", "tube_thk_mm", "tube_id_mm", "tube_length_m",
        "surface_area_per_tube_m2", "xs_area_per_tube_m2", "total_tubes",
        "n_passes", "tubes_per_pass", "actual_hta_m2", "tube_velocity_ms",
        "fluid_flow_m3h", "pitch_mm", "bundle_dia_m", "shell_id_calc_m",
        "shell_id_selected_m",
    ]}


# ---------------------------------------------------------------------
# PUMP SIZING
# ---------------------------------------------------------------------
def size_pump(flow_kgh: float, head_mlc: float, fluid_density_kgm3: float,
              efficiency: float = 0.60, service: str = "Process") -> dict:
    """
    Centrifugal pump sizing.

    BKW = (Q × H × ρ × g) / (3600 × 1000 × η)

    Returns brake kW, motor kW with safety margin, motor HP selected from
    standard sizes.
    """
    if flow_kgh <= 0 or fluid_density_kgm3 <= 0 or efficiency <= 0:
        return _empty_pump(service)

    flow_m3h = flow_kgh / fluid_density_kgm3
    flow_m3s = flow_m3h / 3600.0

    # Hydraulic power (kW)
    hyd_power_kw = (flow_m3s * head_mlc * fluid_density_kgm3 * 9.81) / 1000.0

    # Brake power (kW) — at pump shaft
    bkw = hyd_power_kw / efficiency

    # Motor kW with 20% margin
    motor_kw = bkw * 1.20

    # Select from standard motor HP sizes
    motor_hp_calc = motor_kw * 1.341  # kW to HP
    std_motor_hp = _select_standard_motor_hp(motor_hp_calc)
    motor_kw_sel = std_motor_hp / 1.341

    return {
        "service": service,
        "flow_kgh": flow_kgh,
        "flow_m3h": flow_m3h,
        "head_mlc": head_mlc,
        "fluid_density_kgm3": fluid_density_kgm3,
        "efficiency": efficiency,
        "hydraulic_power_kw": hyd_power_kw,
        "brake_power_kw": bkw,
        "motor_power_kw_required": motor_kw,
        "motor_hp_calculated": motor_hp_calc,
        "motor_hp_selected": std_motor_hp,
        "motor_kw_selected": motor_kw_sel,
    }


def _empty_pump(service=""):
    return {
        "service": service, "flow_kgh": 0, "flow_m3h": 0, "head_mlc": 0,
        "fluid_density_kgm3": 0, "efficiency": 0, "hydraulic_power_kw": 0,
        "brake_power_kw": 0, "motor_power_kw_required": 0,
        "motor_hp_calculated": 0, "motor_hp_selected": 0, "motor_kw_selected": 0,
    }


# Standard motor HP ratings (IEC / NEMA)
STANDARD_MOTOR_HP = [
    0.5, 1, 1.5, 2, 3, 5, 7.5, 10, 12.5, 15, 20, 25, 30, 40, 50, 60, 75,
    100, 125, 150, 200, 250, 300, 400,
]


def _select_standard_motor_hp(calc_hp: float) -> float:
    """Pick next-higher standard motor HP size."""
    for hp in STANDARD_MOTOR_HP:
        if hp >= calc_hp:
            return hp
    return STANDARD_MOTOR_HP[-1]


# ---------------------------------------------------------------------
# TYPICAL PARAMETERS (sensible defaults for MEE/ATFD/Stripper pumps)
# ---------------------------------------------------------------------
# Based on Excel Line Sizing + typical ZLD plant data

PUMP_DEFAULTS = {
    # Stripper section
    "stripper_feed_pump":      {"head_mlc": 30, "efficiency": 0.60, "density_kgm3": 1020},
    "stripper_rcp":            {"head_mlc": 10, "efficiency": 0.60, "density_kgm3": 1020},
    "stripper_reflux_pump":    {"head_mlc": 30, "efficiency": 0.25, "density_kgm3": 800},
    "stripper_steam_cond_pump":{"head_mlc": 20, "efficiency": 0.50, "density_kgm3": 1000},

    # MEE section
    "mee_feed_pump":           {"head_mlc": 25, "efficiency": 0.60, "density_kgm3": 1050},
    "mee_rcp":                 {"head_mlc": 10, "efficiency": 0.60},  # density per effect
    "mee_product_pump":        {"head_mlc": 30, "efficiency": 0.55, "density_kgm3": 1230},
    "mee_cond_pump":           {"head_mlc": 20, "efficiency": 0.55, "density_kgm3": 1000},
    "mee_cw_pump":             {"head_mlc": 25, "efficiency": 0.70, "density_kgm3": 1000},
    "mee_vacuum_pump":         {"head_mlc": 0,  "efficiency": 0.50, "density_kgm3": 1.2},  # power est. separately

    # ATFD section
    "atfd_feed_pump":          {"head_mlc": 20, "efficiency": 0.55, "density_kgm3": 1230},
    "atfd_cond_pump":          {"head_mlc": 20, "efficiency": 0.55, "density_kgm3": 1000},
    "atfd_cw_pump":            {"head_mlc": 20, "efficiency": 0.70, "density_kgm3": 1000},
}


# ---------------------------------------------------------------------
# HX SERVICE PRESETS (v7) — tube geometry defaults per HX service type
# ---------------------------------------------------------------------
# These are the same hardcoded defaults that were in stripper.py/mee.py/atfd.py
# previously, just centralised here so they can be overridden per project / per HX
# from the UI. Each engine module looks up its preset, then applies project-level
# overrides, then per-HX overrides — see resolve_hx_specs() below.

SERVICE_PRESETS = {
    "REBOILER":       {"od_mm": 38.1, "thk_mm": 1.65, "length_m": 3.0, "passes": 2, "velocity_ms": 1.5},
    "CONDENSER_CW":   {"od_mm": 25.4, "thk_mm": 1.65, "length_m": 3.0, "passes": 6, "velocity_ms": 1.8},
    "CONDENSER_CHW":  {"od_mm": 25.4, "thk_mm": 1.20, "length_m": 3.0, "passes": 4, "velocity_ms": 1.7},
    "CALANDRIA":      {"od_mm": 50.8, "thk_mm": 2.00, "length_m": 6.0, "passes": 1, "velocity_ms": 1.5},
    "PREHEATER":      {"od_mm": 25.4, "thk_mm": 1.60, "length_m": 6.0, "passes": 5, "velocity_ms": 1.5},
    "MEE_CONDENSER":  {"od_mm": 25.4, "thk_mm": 1.60, "length_m": 6.0, "passes": 4, "velocity_ms": 1.55},
    "ATFD_CONDENSER": {"od_mm": 25.4, "thk_mm": 1.65, "length_m": 3.0, "passes": 6, "velocity_ms": 1.6},
}

# Standard tube OD values offered in the UI dropdown (mm).
# 'Custom' means the designer typed a non-standard value.
STANDARD_TUBE_OD_MM = [19.05, 25.40, 31.75, 38.10, 50.80]

# Standard pass counts offered in the UI dropdown.
STANDARD_PASS_COUNTS = [1, 2, 4, 6, 8]


def resolve_hx_specs(inputs: dict, hx_key: str, service: str) -> dict:
    """
    Resolve tube specs for a single HX with this lookup order:

        1. inputs['hx_specs'][hx_key]  — designer's per-HX override (most specific)
        2. inputs['hx_specs']['_project_default']  — designer's project-wide default
        3. SERVICE_PRESETS[service]    — hardcoded default for this service type

    Args:
      inputs: the full inputs dict passed to calc_stripper / calc_mee / calc_atfd.
      hx_key: stable identifier for this HX (e.g. 'reboiler', 'condenser1',
              'condenser2', 'calandria_1', 'calandria_2', 'preheater_1',
              'mee_condenser', 'atfd_condenser').
      service: SERVICE_PRESETS key — chooses the safe default ('REBOILER',
               'CONDENSER_CW', 'CALANDRIA', 'PREHEATER', etc.)

    Returns dict with keys:  od_mm, thk_mm, length_m, passes, velocity_ms
    """
    # Start with the service-level preset
    base = dict(SERVICE_PRESETS.get(service, SERVICE_PRESETS["CONDENSER_CW"]))

    hx_specs_in = inputs.get("hx_specs") or {}

    # Apply project-wide override (if present)
    proj_default = hx_specs_in.get("_project_default") or {}
    for k, v in proj_default.items():
        if v is not None:
            base[k] = v

    # Apply per-HX override (if present)
    per_hx = hx_specs_in.get(hx_key) or {}
    for k, v in per_hx.items():
        if v is not None:
            base[k] = v

    return base


def build_default_hx_specs() -> dict:
    """
    Build a default hx_specs dict (all HX types pre-populated with their
    service presets). Useful for initialising the UI for a new project.

    Returns the full nested structure that will be stored in inputs['hx_specs'].
    """
    return {
        "_project_default": {},  # empty = use service presets
        # Stripper HX
        "reboiler":       dict(SERVICE_PRESETS["REBOILER"]),
        "condenser1":     dict(SERVICE_PRESETS["CONDENSER_CW"]),
        "condenser2":     dict(SERVICE_PRESETS["CONDENSER_CHW"]),
        # MEE HX (per-effect)
        "calandria_1":    dict(SERVICE_PRESETS["CALANDRIA"]),
        "calandria_2":    dict(SERVICE_PRESETS["CALANDRIA"]),
        "calandria_3":    dict(SERVICE_PRESETS["CALANDRIA"]),
        "calandria_4":    dict(SERVICE_PRESETS["CALANDRIA"]),
        "preheater_1":    dict(SERVICE_PRESETS["PREHEATER"]),
        "preheater_2":    dict(SERVICE_PRESETS["PREHEATER"]),
        "preheater_3":    dict(SERVICE_PRESETS["PREHEATER"]),
        "preheater_4":    dict(SERVICE_PRESETS["PREHEATER"]),
        "preheater_c":    dict(SERVICE_PRESETS["PREHEATER"]),
        "mee_condenser":  dict(SERVICE_PRESETS["MEE_CONDENSER"]),
        # ATFD HX
        "atfd_condenser": dict(SERVICE_PRESETS["ATFD_CONDENSER"]),
    }

