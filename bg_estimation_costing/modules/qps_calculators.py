"""
qps_calculators.py
──────────────────
Equipment-level costing engines for the QPS (Quote Price Sheet) module.

Each engine mirrors the calculation logic of one reference workbook
provided by B&G Engineering Industries:

  • stripper_column_cost   ← 1__Stripper_Column_Costing.xlsx
  • heat_exchanger_cost    ← 2__Reboiler / 3__StripperCondenser / 5__Calandria /
                              8__SurfaceCondenser / 11__ATFDCondenser
  • vls_cost               ← 9__VLS_Costing.xlsx
  • tank_cost              ← 12__Tank_Costing.xlsx
  • atfd_cost              ← 10__ATFD_Costing__duplex.xlsx (parametric variant)

All engines:
  - Take a clean dict of inputs (no Streamlit dependency)
  - Return a dict with: weight breakup, RM cost, labour cost, total cost,
    line-items list (for QPS roll-up), and full computation trace

Dependencies: pure Python + math. Importable from any Streamlit page.
"""
from __future__ import annotations
import math
from typing import Dict, List, Tuple, Optional

PI = math.pi

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT MATERIAL RATES (Rs/kg) — editable by user in UI
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_RM_RATES: Dict[str, float] = {
    "MS":               75.0,
    "SS304":            250.0,
    "SS316":            420.0,
    "SS316L":           425.0,
    "SS316Ti":          550.0,
    "Duplex 2205":      550.0,
    "Duplex 2507":      750.0,
    "Super Duplex":     710.0,
    "Hastelloy":        1600.0,
    "Hastelloy C22":    1600.0,
    "Ti Gr2":           3000.0,
    "Other":            1.0,
}

DEFAULT_LABOUR_RATES: Dict[str, float] = {
    "MS":              35.0,
    "SS304":           50.0,
    "SS316":           50.0,
    "SS316L":          50.0,
    "SS316Ti":         80.0,
    "Duplex 2205":     100.0,
    "Duplex 2507":     120.0,
    "Super Duplex":    120.0,
    "Hastelloy":       150.0,
    "Hastelloy C22":   150.0,
    "Ti Gr2":          120.0,
    "Other":           50.0,
}

# Tube rates (Rs/kg) — ERW vs Seamless
DEFAULT_TUBE_RATES: Dict[str, Dict[str, float]] = {
    "MS":          {"ERW": 150, "SMLS": 180},
    "SS304":       {"ERW": 300, "SMLS": 450},
    "SS316":       {"ERW": 400, "SMLS": 500},
    "SS316Ti":     {"ERW": 550, "SMLS": 650},
    "SS316L":      {"ERW": 400, "SMLS": 500},
    "Duplex 2205": {"ERW": 700, "SMLS": 800},
    "Duplex 2507": {"ERW": 760, "SMLS": 860},
    "Ti Gr2":      {"ERW": 0,   "SMLS": 3000},
}

DENSITY: Dict[str, float] = {
    "SS304": 8000, "SS316": 8000, "SS316L": 8000, "SS316Ti": 8000,
    "Duplex 2205": 7800, "Duplex 2507": 7800, "Super Duplex": 7800,
    "MS": 7850, "Hastelloy": 8690, "Hastelloy C22": 8690,
    "Ti Gr2": 4500, "Other": 8000,
}

# ─────────────────────────────────────────────────────────────────────────────
# SHELL-THICKNESS LOOKUP — extracted from "1. Stripper Column_Costing" Sheet2
# ─────────────────────────────────────────────────────────────────────────────
SHELL_THK_TABLE: List[Tuple[int, int]] = [
    (100,3),(200,3),(300,3),(400,3),(500,4),(600,4),(700,4),(800,5),
    (900,5),(1000,6),(1100,6),(1200,6),(1300,6),(1400,6),(1500,8),
    (1600,8),(1700,8),(1800,8),(1900,8),(2000,10),(2100,10),(2200,10),
    (2300,10),(2400,10),(2500,12),(2600,12),(2700,12),(2800,12),(2900,12),
    (3000,12),(3200,14),(3400,14),(3600,16),(3800,16),(4000,18),(4500,20),
]

def lookup_shell_thk(dia_mm: float) -> int:
    """Return calculated minimum shell thickness for a given dia (mm)."""
    last = SHELL_THK_TABLE[0][1]
    for d, t in SHELL_THK_TABLE:
        if dia_mm <= d:
            return t
        last = t
    return last

# ─────────────────────────────────────────────────────────────────────────────
# GEOMETRY HELPERS  (kg = volume m³ × density kg/m³)
# ─────────────────────────────────────────────────────────────────────────────
def cyl_shell_wt(id_mm: float, ht_mm: float, thk_mm: float, density: float = 8000) -> float:
    """Cylindrical shell weight, kg.  Centre-line dia = id + thk."""
    if not all((id_mm, ht_mm, thk_mm)):
        return 0.0
    dia_m = (id_mm + thk_mm) / 1000.0
    return PI * dia_m * (thk_mm / 1000.0) * (ht_mm / 1000.0) * density

def dish_wt(shell_id_mm: float, thk_mm: float, density: float = 8000) -> float:
    """Standard 2:1 ellipsoidal/torispherical dish weight, kg."""
    if not all((shell_id_mm, thk_mm)):
        return 0.0
    blank_dia_m = shell_id_mm * 1.20 / 1000.0   # blank dia ≈ 1.2 × shell ID
    area = PI * (blank_dia_m / 2) ** 2
    return area * (thk_mm / 1000.0) * density

def annular_wt(od_mm: float, id_mm: float, thk_mm: float, density: float = 8000) -> float:
    """Annular plate weight, kg."""
    if od_mm <= id_mm:
        return 0.0
    area = PI / 4 * ((od_mm / 1000) ** 2 - (id_mm / 1000) ** 2)
    return area * (thk_mm / 1000) * density

def disc_wt(dia_mm: float, thk_mm: float, density: float = 8000) -> float:
    """Solid disc / blind plate weight, kg."""
    return PI / 4 * (dia_mm / 1000) ** 2 * (thk_mm / 1000) * density

def tube_bundle_wt(tube_od_mm: float, tube_thk_mm: float, length_m: float,
                   n_tubes: int, density: float = 8000) -> float:
    """Tube-bundle total weight, kg."""
    if not all((tube_od_mm, tube_thk_mm, length_m, n_tubes)):
        return 0.0
    od = tube_od_mm / 1000
    id_ = (tube_od_mm - 2 * tube_thk_mm) / 1000
    area = PI / 4 * (od ** 2 - id_ ** 2)
    return area * length_m * n_tubes * density

def cone_wt(d_large_mm: float, d_small_mm: float, ht_mm: float,
            thk_mm: float, density: float = 8000) -> float:
    """Cone frustum weight, kg."""
    if not all((d_large_mm, ht_mm, thk_mm)):
        return 0.0
    r1, r2 = d_large_mm / 2000, d_small_mm / 2000
    slant = math.hypot(r1 - r2, ht_mm / 1000)
    area  = PI * (r1 + r2) * slant
    return area * (thk_mm / 1000) * density

def rect_plate_wt(L_mm: float, W_mm: float, thk_mm: float, density: float = 8000) -> float:
    return (L_mm / 1000) * (W_mm / 1000) * (thk_mm / 1000) * density

# ─────────────────────────────────────────────────────────────────────────────
# 1️⃣  STRIPPER COLUMN
# ─────────────────────────────────────────────────────────────────────────────
def stripper_column_cost(
    *, column_dia_mm: float, column_height_m: float, packing_height_m: float,
    column_type: str = "Tray Type",            # "Packed Bed Type" | "Tray Type"
    moc_shell: str = "SS316L", moc_trays: str = "SS316L",
    moc_packing: str = "SS316L",
    shell_thk_mm: Optional[float] = None,      # None → auto-lookup
    dish_thk_mm: float = 6.0,
    tray_thk_mm: float = 4.0,
    tray_spacing_mm: int = 450,
    weir_height_m: float = 0.05,
    nozzle_factor: float = 0.15,
    support_factor: float = 0.05,
    scrap_factor: float = 0.05,
    rm_rates: Optional[Dict[str, float]] = None,
    lab_rates: Optional[Dict[str, float]] = None,
    contingency_pct: float = 0.20,
    round_to: int = 1000,
) -> Dict:
    """Stripper Column costing — closely mirrors `1. Stripper Column_Costing.xlsx`."""
    R = rm_rates or DEFAULT_RM_RATES
    L = lab_rates or DEFAULT_LABOUR_RATES
    rm_rate  = R.get(moc_shell, 425)
    lab_rate = L.get(moc_shell, 50)
    rm_tray  = R.get(moc_trays, 425)
    lab_tray = L.get(moc_trays, 50)
    density  = DENSITY.get(moc_shell, 8000)

    if shell_thk_mm is None:
        thk_calc = lookup_shell_thk(column_dia_mm)
        shell_thk_mm = thk_calc + 1     # selected = calc + 1 mm CA

    # === A. PACKINGS / TRAYS ===
    packing_cost = 0.0
    trays_no = 0
    total_tray_wgt = 0.0
    if column_type == "Tray Type":
        trays_no = packing_height_m / (tray_spacing_mm / 1000) if tray_spacing_mm else 0
        tray_dia = column_dia_mm / 1000
        # Tray plate weight (one tray)
        tray_plate_wt = (PI / 4) * tray_dia ** 2 * (tray_thk_mm / 1000) * density
        # Downcomers
        downcomer_w = 0.255 * tray_dia
        downcomer_h = 0.30
        downcomer_wt = downcomer_w * downcomer_h * (tray_thk_mm / 1000) * density
        n_downcomers = trays_no - 1
        total_dcm_wt = downcomer_wt * n_downcomers if n_downcomers > 0 else 0
        # Weirs
        weir_len = tray_dia
        weir_wt = weir_len * weir_height_m * (tray_thk_mm / 1000) * density
        total_weir_wt = weir_wt * trays_no
        # Total tray units
        total_tray_wgt = (tray_plate_wt + downcomer_wt + weir_wt) * trays_no * 1.10
        packing_cost = total_tray_wgt * (rm_tray + lab_tray)
    else:
        # Packed bed (random packings — provided by user as kg/m3 if non-zero)
        packing_cost = 0.0

    # === B. BODY DATA ===
    main_shell_wt = cyl_shell_wt(column_dia_mm, column_height_m * 1000, shell_thk_mm, density)
    top_dish_wt   = dish_wt(column_dia_mm, dish_thk_mm, density)
    main_body_wt  = main_shell_wt + top_dish_wt
    # Flash vessel at bottom (1.25 × column dia)
    fv_dia_mm     = column_dia_mm * 1.25
    fv_ht_mm      = fv_dia_mm * 1.20
    fv_shell_wt   = cyl_shell_wt(fv_dia_mm, fv_ht_mm, shell_thk_mm, density)
    fv_dish_wt    = dish_wt(fv_dia_mm, dish_thk_mm, density)
    fv_total_wt   = fv_shell_wt + fv_dish_wt
    total_body_wt = main_body_wt + fv_total_wt
    body_cost     = total_body_wt * rm_rate

    # === C. BODY FLANGES (MS+SS sandwich) ===
    bf_id_mm  = column_dia_mm
    bf_od_mm  = column_dia_mm + 150
    bf_qty    = 10
    bf_thk_ss = 5
    bf_thk_ms = 30
    ss_bf_wt  = annular_wt(bf_od_mm, bf_id_mm, bf_thk_ss, density) * bf_qty
    ms_bf_wt  = annular_wt(bf_od_mm, bf_id_mm, bf_thk_ms, 7850)    * bf_qty
    ss_bf_cost = ss_bf_wt * rm_rate
    ms_bf_cost = ms_bf_wt * R["MS"]

    # === D. MISC. ===
    nozzle_wt  = total_body_wt * nozzle_factor
    support_wt = total_body_wt * support_factor
    scrap_wt   = total_body_wt * scrap_factor
    misc_wt    = nozzle_wt + support_wt + scrap_wt
    misc_cost  = misc_wt * rm_rate

    # === Totals ===
    total_ss_wt  = total_body_wt + ss_bf_wt + misc_wt
    total_ss_cost = total_ss_wt * rm_rate
    total_ms_wt  = ms_bf_wt
    total_ms_cost = ms_bf_wt * R["MS"]

    total_rm_cost = total_ss_cost + total_ms_cost
    # Labour cost as per Table.2  (fab cost based on tray weight and body weight)
    total_lab_cost = (total_body_wt * lab_rate) + (ms_bf_wt * L["MS"]) + (total_tray_wgt * lab_tray)
    factory_cost  = total_rm_cost + total_lab_cost
    final_cost    = factory_cost * (1 + contingency_pct) + packing_cost
    rounded_cost  = math.ceil(final_cost / round_to) * round_to if round_to else final_cost

    return dict(
        equipment="Stripper Column",
        inputs=dict(column_dia_mm=column_dia_mm, column_height_m=column_height_m,
                    packing_height_m=packing_height_m, column_type=column_type,
                    moc_shell=moc_shell, shell_thk_mm=shell_thk_mm,
                    dish_thk_mm=dish_thk_mm, trays_no=trays_no),
        weights=dict(
            main_shell=main_shell_wt, top_dish=top_dish_wt,
            flash_vessel=fv_total_wt, ss_body_flange=ss_bf_wt,
            ms_body_flange=ms_bf_wt, misc=misc_wt,
            trays=total_tray_wgt,
            total_ss=total_ss_wt, total_ms=total_ms_wt,
        ),
        costs=dict(
            packing_or_trays=packing_cost,
            body=body_cost,
            ss_body_flange=ss_bf_cost,
            ms_body_flange=ms_bf_cost,
            misc=misc_cost,
            total_rm=total_rm_cost,
            total_labour=total_lab_cost,
            factory=factory_cost,
            contingency_amt=factory_cost * contingency_pct,
            final=final_cost,
            rounded=rounded_cost,
        ),
    )

# ─────────────────────────────────────────────────────────────────────────────
# 2️⃣  HEAT EXCHANGER  (Reboiler / Calandria / Condenser)
# ─────────────────────────────────────────────────────────────────────────────
def heat_exchanger_cost(
    *, hta_m2: float, tube_length_m: float = 6.0,
    tube_od_mm: float = 25.4, tube_thk_mm: float = 0.9,
    pitch_factor: float = 1.5, n_passes: int = 1,
    moc_shell: str = "SS304", moc_dishend: str = "Duplex 2205",
    moc_tubesheet: str = "SS316L", moc_tubes: str = "Ti Gr2",
    moc_bonnet: str = "Duplex 2205", moc_partition: str = "Duplex 2205",
    moc_tierod: str = "SS304", moc_baffles: str = "SS304",
    moc_body_flange: str = "SS316L",
    moc_bf_cladding: str = "None",   # "SS with Duplex Lining" / "SS with Ti Cladding" / etc.
    bonding_thk_mm: float = 5.0,
    bonding_rate_per_m2: float = 20000.0,
    rm_rates: Optional[Dict[str, float]] = None,
    lab_rates: Optional[Dict[str, float]] = None,
    tube_rates: Optional[Dict[str, Dict[str, float]]] = None,
    tube_grade: str = "SMLS",       # "ERW" | "SMLS"
    contingency_pct: float = 0.15,
    equipment_label: str = "Heat Exchanger",
) -> Dict:
    """
    Generic shell-and-tube heat exchanger costing.
    Mirrors logic of 2__Reboiler / 3__Stripper Condenser / 5__Calandria /
    8__Surface Condenser / 11__ATFD Condenser cost sheets.
    """
    R = rm_rates or DEFAULT_RM_RATES
    L = lab_rates or DEFAULT_LABOUR_RATES
    T = tube_rates or DEFAULT_TUBE_RATES

    # SA per tube and total tubes count
    sa_per_tube = PI * (tube_od_mm / 1000) * tube_length_m
    n_tubes     = math.ceil(hta_m2 / sa_per_tube) if sa_per_tube else 0

    # Shell ID (estimated): based on bundle dia
    pitch       = pitch_factor * tube_od_mm
    bundle_dia  = math.sqrt(n_tubes) * pitch * 1.05 + 10
    shell_id_mm = max(150, math.ceil(bundle_dia / 10) * 10)

    # Auto thicknesses (mm)
    shell_thk    = max(3, lookup_shell_thk(shell_id_mm) - 1)   # less stiff than column
    dishend_thk  = max(3, shell_thk + 2)
    bf_thk       = max(20, int(shell_id_mm / 18))
    ts_thk       = max(20, int(shell_id_mm / 18) - 3)
    bonnet_thk   = max(3, shell_thk + 1)
    partition_thk = 5
    tierod_dia   = 10
    n_tierod     = max(4, int(shell_id_mm / 100))
    bf_od        = shell_id_mm + 105

    # === Component weights ===
    shell_wt    = cyl_shell_wt(shell_id_mm, tube_length_m * 1000, shell_thk,
                               DENSITY.get(moc_shell, 8000))
    bonnet_wt   = PI * (shell_id_mm / 1000) * 0.30 * (bonnet_thk / 1000) * \
                  DENSITY.get(moc_bonnet, 8000) * 2          # 2 bonnets
    tubesheet_wt = ((PI / 4) * (bf_od / 1000) ** 2 * (ts_thk / 1000) *
                    DENSITY.get(moc_tubesheet, 8000) * 2) * 1.3
    tubes_wt    = tube_bundle_wt(tube_od_mm, tube_thk_mm, tube_length_m, n_tubes,
                                  DENSITY.get(moc_tubes, 8000))
    dishend_wt  = dish_wt(shell_id_mm, dishend_thk, DENSITY.get(moc_dishend, 8000)) * 2
    # Partition plate: strip ~300 mm wide × shell_id long × 6 faces
    partition_wt = (shell_id_mm * 300 / 1e6) * (partition_thk / 1000) * \
                    DENSITY.get(moc_partition, 8000) * 6
    tierod_wt   = ((PI / 4) * (tierod_dia / 1000) ** 2) * tube_length_m * n_tierod * \
                   DENSITY.get(moc_tierod, 8000)
    baffles_wt  = ((PI / 4) * (shell_id_mm / 1000) ** 2) * 0.004 * 8 * \
                   DENSITY.get(moc_baffles, 8000)            # 8 baffles, 4 mm thk
    bf_wt       = annular_wt(bf_od, shell_id_mm, bf_thk,
                              DENSITY.get(moc_body_flange, 8000)) * 2

    # === Cost per row ===
    rows = []
    def add(item, moc, wt, override_rate=None):
        rate = override_rate if override_rate is not None else R.get(moc, 0)
        lr   = L.get(moc, 50)
        rmc  = wt * rate
        lab  = wt * lr
        rows.append(dict(item=item, moc=moc, wt=wt, rate=rate,
                         rmc=rmc, lab_rate=lr, lab=lab))
        return rmc, lab

    add("Shell",                moc_shell,       shell_wt)
    add("Bonnet",               moc_bonnet,      bonnet_wt)
    add("Tubesheet",            moc_tubesheet,   tubesheet_wt)

    # Tubes — from tube-rate table (ERW/SMLS)
    tube_rate = T.get(moc_tubes, {}).get(tube_grade, R.get(moc_tubes, 0))
    add("Tubes", moc_tubes, tubes_wt, override_rate=tube_rate)
    rows[-1]["lab_rate"] = 120  # tube fab is intensive
    rows[-1]["lab"] = tubes_wt * 120

    add("Dishend (×2)",         moc_dishend,     dishend_wt)
    add("Partition Plate",      moc_partition,   partition_wt)
    add("Tie Rod",              moc_tierod,      tierod_wt)
    add("Baffles",              moc_baffles,     baffles_wt)
    add("Body Flange (T+B)",    moc_body_flange, bf_wt)

    # Cladding / Lining for BF + TS (per-m2 cost, additive)
    cladding_cost = 0.0
    cladding_lab  = 0.0
    cladding_wt   = 0.0
    if moc_bf_cladding != "None":
        # Bonding area = π/4 * (BF_OD)² * 2 sides
        ts_area_m2 = (PI / 4 * (bf_od / 1000) ** 2) * 2
        # Lining material weight & cost
        lining_density = {
            "SS with Duplex Lining":      DENSITY["Duplex 2205"],
            "SS with Super Duplex Lining": DENSITY["Super Duplex"],
            "MS with SS Lining":          DENSITY["SS304"],
            "SS with Ti Cladding":        DENSITY["Ti Gr2"],
        }.get(moc_bf_cladding, 8000)
        lining_rate = {
            "SS with Duplex Lining":      R["Duplex 2205"],
            "SS with Super Duplex Lining": R["Super Duplex"],
            "MS with SS Lining":          R["SS304"],
            "SS with Ti Cladding":        R["Ti Gr2"],
        }.get(moc_bf_cladding, 0)
        cladding_wt   = ts_area_m2 * (bonding_thk_mm / 1000) * lining_density
        cladding_cost = cladding_wt * lining_rate + ts_area_m2 * bonding_rate_per_m2
        cladding_lab  = ts_area_m2 * 1000  # arbitrary fab labour for lining
        rows.append(dict(item=f"Cladding/Lining: {moc_bf_cladding}",
                         moc=moc_bf_cladding, wt=cladding_wt,
                         rate=lining_rate, rmc=cladding_cost,
                         lab_rate=0, lab=cladding_lab))

    total_wt    = sum(r["wt"]  for r in rows)
    total_rmc   = sum(r["rmc"] for r in rows)
    total_lab   = sum(r["lab"] for r in rows)
    contingency = total_rmc * contingency_pct
    final_cost  = total_rmc + contingency + total_lab
    cost_per_m2 = final_cost / hta_m2 if hta_m2 else 0

    return dict(
        equipment=equipment_label,
        inputs=dict(hta_m2=hta_m2, tube_length_m=tube_length_m,
                    tube_od_mm=tube_od_mm, n_tubes=n_tubes,
                    shell_id_mm=shell_id_mm, shell_thk=shell_thk,
                    moc_shell=moc_shell, moc_tubes=moc_tubes,
                    moc_tubesheet=moc_tubesheet, moc_bf_cladding=moc_bf_cladding),
        rows=rows,
        weights=dict(total=total_wt),
        costs=dict(total_rm=total_rmc, contingency_amt=contingency,
                   total_labour=total_lab, final=final_cost,
                   cost_per_m2=cost_per_m2),
    )

# ─────────────────────────────────────────────────────────────────────────────
# 3️⃣  VLS — VAPOR LIQUID SEPARATOR
# ─────────────────────────────────────────────────────────────────────────────
def vls_cost(
    *, gross_volume_m3: float,
    selected_id_mm: Optional[float] = None,
    h_over_d: float = 2.0,
    moc: str = "SS316L",
    shell_thk_mm: Optional[float] = None,
    rm_rates: Optional[Dict[str, float]] = None,
    lab_rates: Optional[Dict[str, float]] = None,
    scrap_factor: float = 0.05,
    contingency_pct: float = 0.20,
    round_to: int = 50000,
) -> Dict:
    """VLS costing — mirrors `9. VLS_Costing.xlsx`."""
    R = rm_rates or DEFAULT_RM_RATES
    L = lab_rates or DEFAULT_LABOUR_RATES
    rm_rate, lab_rate = R.get(moc, 425), L.get(moc, 50)
    density  = DENSITY.get(moc, 8000)

    # Calculated ID from volume & H/D, ID = (4·V / π·HoD)^(1/3) × 1000
    if not selected_id_mm:
        calc_id_mm = ((4 * gross_volume_m3 / (PI * h_over_d)) ** (1/3)) * 1000
        # Round up to nearest 50 mm
        selected_id_mm = math.ceil(calc_id_mm / 50) * 50

    height_mm = selected_id_mm * h_over_d
    if shell_thk_mm is None:
        shell_thk_mm = lookup_shell_thk(selected_id_mm)
    top_thk     = shell_thk_mm + 1
    bottom_thk  = shell_thk_mm
    conical_thk = shell_thk_mm

    # Surface area  (m2): cylinder + top dish + cone(45°)
    sa_cyl   = PI * (selected_id_mm / 1000) * (height_mm / 1000)
    sa_top   = 1.09 * PI * ((selected_id_mm * 1.167 / 2000) ** 2)
    sa_cone  = PI * (selected_id_mm / 2000) ** 2 / math.cos(math.radians(45))
    surf_area = sa_cyl + sa_top + sa_cone

    # Weights
    shell_w   = cyl_shell_wt(selected_id_mm, height_mm, shell_thk_mm, density)
    top_w     = dish_wt(selected_id_mm, top_thk, density)
    inverted_w = dish_wt(selected_id_mm, bottom_thk, density) * 0.8
    cone_w    = cone_wt(selected_id_mm, selected_id_mm * 0.4,
                        selected_id_mm / 2, conical_thk, density)
    entry_w   = 85 + max(0, (selected_id_mm - 1050) * 0.075)   # entry baffle
    curb_angle_w = surf_area * 1.2                              # curb angle MS

    # Stiffeners
    n_stiff   = max(1, int((selected_id_mm - 750) / 400) + 1)
    stiff_wt  = n_stiff * 5 * (height_mm / 1000)               # kg/m × m

    ss_wt = shell_w + top_w + inverted_w + cone_w + entry_w + stiff_wt
    ss_wt *= (1 + scrap_factor)
    ms_wt = curb_angle_w * (1 + scrap_factor)

    ss_cost  = ss_wt * rm_rate
    ms_cost  = ms_wt * R["MS"]
    lab_cost = (ss_wt * lab_rate) + (ms_wt * L["MS"])
    mfg_cost = ss_cost + ms_cost + lab_cost
    final    = mfg_cost * (1 + contingency_pct)
    rounded  = math.ceil(final / round_to) * round_to if round_to else final

    return dict(
        equipment="VLS",
        inputs=dict(gross_volume_m3=gross_volume_m3,
                    selected_id_mm=selected_id_mm,
                    height_mm=height_mm, h_over_d=h_over_d,
                    moc=moc, shell_thk_mm=shell_thk_mm),
        weights=dict(shell=shell_w, top=top_w, inverted=inverted_w,
                     cone=cone_w, entry=entry_w, stiff=stiff_wt,
                     curb_angle=curb_angle_w,
                     total_ss=ss_wt, total_ms=ms_wt),
        costs=dict(ss=ss_cost, ms=ms_cost, labour=lab_cost,
                   mfg=mfg_cost, final=final, rounded=rounded,
                   surf_area_m2=surf_area),
    )

# ─────────────────────────────────────────────────────────────────────────────
# 4️⃣  TANK
# ─────────────────────────────────────────────────────────────────────────────
def tank_cost(
    *, capacity_kl: float,
    L_over_D: float = 1.25,
    moc: str = "SS316L",
    shell_thk_mm: Optional[float] = None,
    top_dish_thk_mm: Optional[float] = None,
    bottom_dish_thk_mm: Optional[float] = None,
    cone_bottom: bool = True,
    cone_angle_deg: float = 15.0,
    n_manholes: int = 1,
    n_flanges: int = 6,
    additional_items: Optional[List[Dict]] = None,
    rm_rates: Optional[Dict[str, float]] = None,
    lab_rates: Optional[Dict[str, float]] = None,
    margin_on_rm: float = 1.10,
    supplier_margin: float = 0.05,
    moh_pct: float = 0.10,
    round_to: int = 1000,
) -> Dict:
    """Tank costing — mirrors `12. Tank_Costing.xlsx`."""
    R = rm_rates or DEFAULT_RM_RATES
    L = lab_rates or DEFAULT_LABOUR_RATES
    rm_rate, lab_rate = R.get(moc, 425), L.get(moc, 50)
    density  = DENSITY.get(moc, 8000)

    # Geometry from capacity (KL → m³)
    volume_m3 = capacity_kl
    dia_m  = (4 * volume_m3 / (PI * L_over_D)) ** (1/3)
    dia_m  = round(dia_m * 10) / 10   # nearest 0.1 m
    ht_m   = L_over_D * dia_m

    if shell_thk_mm       is None: shell_thk_mm       = max(4, lookup_shell_thk(dia_m * 1000))
    if top_dish_thk_mm    is None: top_dish_thk_mm    = max(4, shell_thk_mm)
    if bottom_dish_thk_mm is None: bottom_dish_thk_mm = max(5, shell_thk_mm + 1)

    # Component weights (with margin on RM)
    shell_w   = cyl_shell_wt(dia_m * 1000, ht_m * 1000, shell_thk_mm, density) * margin_on_rm
    top_radius = dia_m / 2 + 0.05
    top_h_m    = top_radius - math.sqrt(max(0, top_radius**2 - (dia_m/2)**2))   # cap height
    top_w     = (PI * top_radius * top_h_m * 2) * (top_dish_thk_mm / 1000) * density * margin_on_rm
    bottom_w  = disc_wt(dia_m * 1000, bottom_dish_thk_mm, density) * margin_on_rm
    manhole_w = 33.158 * n_manholes        # std manhole ≈ 33 kg
    flange_circ_m = PI * dia_m * 1.0       # one flange ring circumference
    flange_w  = flange_circ_m * 0.05 * 25 / 1000 * density * n_flanges * margin_on_rm / 6
    stiff_w   = 0.13 * (ht_m + 0.07) * 6 / 1000 * density * margin_on_rm

    total_ss_wt = shell_w + top_w + bottom_w + manhole_w + flange_w + stiff_w
    rm_cost     = total_ss_wt * rm_rate
    lab_cost    = total_ss_wt * lab_rate

    # Additional items
    add_cost = 0.0
    add_items_clean = []
    for ai in (additional_items or []):
        amt = (ai.get("qty", 0) or 0) * (ai.get("unit_rate", 0) or 0)
        add_cost += amt
        add_items_clean.append({**ai, "amount": amt})

    nozzle_flange_default = 17300
    misc_default          = 10000
    add_cost += nozzle_flange_default + misc_default + 5000   # +sight glass

    total_cost = rm_cost + lab_cost + add_cost
    supplier_cost = total_cost * supplier_margin
    moh_cost      = total_cost * moh_pct
    tank_cost     = total_cost + supplier_cost + moh_cost
    rounded_cost  = math.ceil(tank_cost / round_to) * round_to if round_to else tank_cost

    return dict(
        equipment="Tank",
        inputs=dict(capacity_kl=capacity_kl, dia_m=dia_m, ht_m=ht_m,
                    moc=moc, shell_thk_mm=shell_thk_mm,
                    top_dish_thk_mm=top_dish_thk_mm,
                    bottom_dish_thk_mm=bottom_dish_thk_mm),
        weights=dict(shell=shell_w, top=top_w, bottom=bottom_w,
                     manholes=manhole_w, flanges=flange_w, stiff=stiff_w,
                     total=total_ss_wt),
        costs=dict(rm=rm_cost, labour=lab_cost,
                   additional=add_cost, additional_items=add_items_clean,
                   supplier=supplier_cost, moh=moh_cost,
                   total=total_cost, final=tank_cost,
                   rounded=rounded_cost),
    )

# ─────────────────────────────────────────────────────────────────────────────
# 5️⃣  ATFD — AGITATED THIN FILM DRYER
# ─────────────────────────────────────────────────────────────────────────────
def atfd_cost(
    *, hta_m2: float, shell_dia_mm: float = 600,
    shell_length_m: float = 2.5,
    moc: str = "Duplex 2205",
    moc_shell: Optional[str] = None,
    moc_jacket: str = "SS304",
    moc_rotor: str = "Duplex 2205",
    shell_thk_mm: float = 8.0,
    jacket_thk_mm: float = 4.0,
    n_blades: int = 4,
    rm_rates: Optional[Dict[str, float]] = None,
    lab_rates: Optional[Dict[str, float]] = None,
    contingency_pct: float = 0.20,
    bo_items_cost: float = 0.0,         # gearbox, motor, mech seal, instr
    round_to: int = 50000,
) -> Dict:
    """ATFD parametric costing — adapted from `10. ATFD_Costing  duplex.xlsx`."""
    R = rm_rates or DEFAULT_RM_RATES
    L = lab_rates or DEFAULT_LABOUR_RATES
    moc_shell = moc_shell or moc
    rm_rate   = R.get(moc_shell, 550)
    rm_jacket = R.get(moc_jacket, 250)
    rm_rotor  = R.get(moc_rotor, 550)
    lab_rate  = L.get(moc_shell, 100)
    density_s = DENSITY.get(moc_shell, 7800)
    density_j = DENSITY.get(moc_jacket, 8000)
    density_r = DENSITY.get(moc_rotor, 7800)

    # Body shell
    shell_wt   = cyl_shell_wt(shell_dia_mm, shell_length_m * 1000, shell_thk_mm, density_s)
    # Two dish-end heads (top & bottom)
    head_wt    = dish_wt(shell_dia_mm, shell_thk_mm + 2, density_s) * 2
    # Jacket — concentric outer cyl, dia + 100mm gap each side
    jacket_id  = shell_dia_mm + 200
    jacket_wt  = cyl_shell_wt(jacket_id, shell_length_m * 1000, jacket_thk_mm, density_j)
    jacket_head_wt = dish_wt(jacket_id, jacket_thk_mm, density_j) * 2
    # Rotor (solid shaft + blades + hub)
    rotor_dia  = shell_dia_mm * 0.8
    shaft_dia  = max(80, shell_dia_mm * 0.15)
    shaft_wt   = (PI / 4) * (shaft_dia / 1000) ** 2 * \
                 (shell_length_m + 0.5) * density_r
    blade_wt   = (rect_plate_wt(shell_length_m * 1000, 80, 8, density_r) * n_blades * 1.2)
    hub_wt     = 25 * n_blades   # rough hub & boss
    rotor_wt   = shaft_wt + blade_wt + hub_wt

    total_wt   = shell_wt + head_wt + jacket_wt + jacket_head_wt + rotor_wt

    rm_cost = (
        (shell_wt + head_wt) * rm_rate +
        (jacket_wt + jacket_head_wt) * rm_jacket +
        rotor_wt * rm_rotor
    )
    lab_cost = total_wt * lab_rate * 1.20  # ATFD high labour content
    contingency = rm_cost * contingency_pct
    final = rm_cost + lab_cost + contingency + bo_items_cost
    rounded = math.ceil(final / round_to) * round_to if round_to else final

    return dict(
        equipment="ATFD",
        inputs=dict(hta_m2=hta_m2, shell_dia_mm=shell_dia_mm,
                    shell_length_m=shell_length_m, moc=moc_shell,
                    moc_jacket=moc_jacket, moc_rotor=moc_rotor),
        weights=dict(shell=shell_wt, heads=head_wt, jacket=jacket_wt,
                     jacket_heads=jacket_head_wt, rotor=rotor_wt,
                     total=total_wt),
        costs=dict(rm=rm_cost, labour=lab_cost,
                   contingency_amt=contingency,
                   bo_items=bo_items_cost,
                   final=final, rounded=rounded),
    )

# ─────────────────────────────────────────────────────────────────────────────
# 6️⃣  GENERIC PIPELINE COSTING (per-line basis)
# ─────────────────────────────────────────────────────────────────────────────
PIPE_KG_PER_M_SCH40: Dict[int, float] = {
    # Approximate kg/m for SCH40 pipe (used in QPS PIPELINE COST sheet)
    15:  1.27, 20:  1.69, 25: 2.50, 32: 3.39, 40: 4.05,
    50:  5.44, 65:  8.63, 80: 11.29, 100: 16.07, 125: 20.39,
    150: 28.26, 200: 42.55, 250: 60.29, 300: 86.20, 350: 81.33,
    400: 106.13, 450: 117.15, 500: 130.20,
}
PIPE_RM_RATES: Dict[str, float] = {
    "MS": 100, "SS304": 250, "SS316L": 450, "SS2205": 650, "SS2507": 800,
}
PIPE_LAB_RATES: Dict[str, float] = {
    "MS": 150, "SS304": 350, "SS316L": 550, "SS2205": 700, "SS2507": 850,
}

def pipeline_line_cost(*, nb: int, length_m: float, qty: int = 1,
                       moc: str = "SS316L") -> Dict:
    """Cost a single pipeline (one row of QPS PIPELINE COST sheet)."""
    kg_per_m = PIPE_KG_PER_M_SCH40.get(nb, 0)
    tot_wt   = kg_per_m * length_m * qty
    rmc      = tot_wt * PIPE_RM_RATES.get(moc, 450)
    labc     = tot_wt * PIPE_LAB_RATES.get(moc, 550) / 100  # lab rate in Rs/100kg
    return dict(nb=nb, length_m=length_m, qty=qty, moc=moc,
                kg_per_m=kg_per_m, total_wt=tot_wt,
                rm_cost=rmc, lab_cost=labc, total=rmc + labc)
