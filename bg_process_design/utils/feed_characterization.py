"""
Feed Characterization Utilities

Central module for handling comprehensive feed parameters across all units:
  - TS (Total Solids), TDS (Total Dissolved Solids), TSS (Total Suspended Solids)
  - COD (Chemical Oxygen Demand), BOD (Biochemical Oxygen Demand)
  - Crystalline / Non-crystalline salt split
  - Chlorides, Sulphates (for material selection hints)

Also provides:
  - BPR auto-calculation from TS using Dühring-type correlation
  - Mass-balance tracking of parameters through unit operations
  - Validation (sum checks, range warnings)
"""
import math


def default_feed_characterization():
    """Return a default feed characterization dict matching typical ZLD feed."""
    return {
        "ts_pct": 2.2,              # Total Solids %
        "tds_pct": 2.2,             # Total Dissolved Solids %
        "tss_pct": 0.0,             # Total Suspended Solids %
        "cod_mgl": 8000.0,          # Chemical Oxygen Demand mg/L
        "bod_mgl": 2500.0,          # Biochemical Oxygen Demand mg/L
        "crystalline_salt_pct": 90.0,    # % of TDS that is crystalline
        "non_crystalline_salt_pct": 10.0,
        "chlorides_mgl": 3500.0,
        "sulphates_mgl": 1200.0,
        "ph": 7.2,
    }


def validate_feed_characterization(feed: dict) -> list:
    """Check feed dict for consistency. Returns list of warnings (empty if clean)."""
    warnings = []

    ts = feed.get("ts_pct", 0)
    tds = feed.get("tds_pct", 0)
    tss = feed.get("tss_pct", 0)

    # TS should equal TDS + TSS (within 5% tolerance)
    if ts > 0 and abs(ts - (tds + tss)) / ts > 0.05:
        warnings.append(
            f"TS ({ts:.2f}%) ≠ TDS + TSS ({tds + tss:.2f}%). "
            f"Difference: {abs(ts - (tds + tss)):.2f}%"
        )

    # Crystalline + Non-crystalline should sum to ~100%
    crys = feed.get("crystalline_salt_pct", 0)
    non_crys = feed.get("non_crystalline_salt_pct", 0)
    if abs(crys + non_crys - 100) > 2:
        warnings.append(
            f"Crystalline ({crys:.1f}%) + Non-crystalline ({non_crys:.1f}%) "
            f"= {crys + non_crys:.1f}% (should be 100%)"
        )

    # BOD should be less than COD
    cod = feed.get("cod_mgl", 0)
    bod = feed.get("bod_mgl", 0)
    if bod > cod:
        warnings.append(f"BOD ({bod:.0f} mg/L) > COD ({cod:.0f} mg/L) — typically BOD < COD")

    # pH range check
    ph = feed.get("ph", 7.0)
    if ph < 2 or ph > 13:
        warnings.append(f"pH {ph:.1f} out of typical range 2–13")

    return warnings


def calc_bpr_from_ts(ts_fraction: float) -> float:
    """
    Calculate Boiling Point Rise from Total Solids concentration.

    Correlation: BPR = 0.5 + 0.5 × exp(4 × (TS - 0.10))
    Clipped to [0.5, 15] °C for reasonable engineering range.

    At TS = 2%:   BPR ≈ 0.83 °C
    At TS = 10%:  BPR ≈ 1.0 °C
    At TS = 20%:  BPR ≈ 1.6 °C
    At TS = 35%:  BPR ≈ 3.1 °C
    At TS = 50%:  BPR ≈ 5.6 °C
    At TS = 65%:  BPR ≈ 10.0 °C
    """
    if ts_fraction <= 0:
        return 0.5
    bpr = 0.5 + 0.5 * math.exp(4.0 * (ts_fraction - 0.10))
    return max(0.5, min(15.0, bpr))


def propagate_feed_through_evaporation(feed_char: dict, feed_kgh: float,
                                         evap_kgh: float) -> dict:
    """
    Given inlet feed characterization and evaporation rate, compute outlet stream.
    Assumes:
      - TDS, TSS, solids stay with liquid (non-volatile)
      - COD stays with liquid (non-volatile organics; aligns with Excel assumption)
      - BOD stays with liquid
      - Concentrated stream = feed - evaporated water

    Returns outlet feed characterization for the concentrated stream.
    """
    if feed_kgh <= 0:
        return dict(feed_char)

    outlet_kgh = feed_kgh - evap_kgh
    if outlet_kgh <= 0:
        return dict(feed_char)

    # Concentration factor for non-volatile species
    conc_factor = feed_kgh / outlet_kgh

    out = dict(feed_char)
    # Mass-based % concentrations (TS, TDS, TSS) scale by conc_factor
    out["ts_pct"] = min(100.0, feed_char.get("ts_pct", 0) * conc_factor)
    out["tds_pct"] = min(100.0, feed_char.get("tds_pct", 0) * conc_factor)
    out["tss_pct"] = min(100.0, feed_char.get("tss_pct", 0) * conc_factor)

    # mg/L-based parameters also concentrate (assuming density ~constant)
    out["cod_mgl"] = feed_char.get("cod_mgl", 0) * conc_factor
    out["bod_mgl"] = feed_char.get("bod_mgl", 0) * conc_factor
    out["chlorides_mgl"] = feed_char.get("chlorides_mgl", 0) * conc_factor
    out["sulphates_mgl"] = feed_char.get("sulphates_mgl", 0) * conc_factor

    # Crystalline/non-crystalline fractions don't change (they're fractions of TDS)
    out["crystalline_salt_pct"] = feed_char.get("crystalline_salt_pct", 0)
    out["non_crystalline_salt_pct"] = feed_char.get("non_crystalline_salt_pct", 0)

    # pH: weakly concentration-dependent; leave unchanged (design assumption)
    out["ph"] = feed_char.get("ph", 7.0)

    return out


def propagate_feed_through_stripper(feed_char: dict, feed_kgh: float,
                                      distillate_kgh: float,
                                      distillate_is_solvent_water: bool = True) -> dict:
    """
    Stripper propagation: distillate carries organic solvent + water only.
    Non-volatile species (TDS, TSS, salts, COD) stay in bottoms.
    BOD — most stays in bottoms, small fraction (~10%) may volatilize with solvent.
    """
    if feed_kgh <= 0:
        return dict(feed_char)

    bottoms_kgh = feed_kgh - distillate_kgh
    if bottoms_kgh <= 0:
        return dict(feed_char)

    conc_factor = feed_kgh / bottoms_kgh

    out = dict(feed_char)
    out["ts_pct"] = min(100.0, feed_char.get("ts_pct", 0) * conc_factor)
    out["tds_pct"] = min(100.0, feed_char.get("tds_pct", 0) * conc_factor)
    out["tss_pct"] = min(100.0, feed_char.get("tss_pct", 0) * conc_factor)
    out["cod_mgl"] = feed_char.get("cod_mgl", 0) * conc_factor
    # 10% of BOD is volatile (rough assumption for solvent-like organics)
    vol_frac = 0.10 if distillate_is_solvent_water else 0.0
    out["bod_mgl"] = feed_char.get("bod_mgl", 0) * conc_factor * (1 - vol_frac)
    out["chlorides_mgl"] = feed_char.get("chlorides_mgl", 0) * conc_factor
    out["sulphates_mgl"] = feed_char.get("sulphates_mgl", 0) * conc_factor
    out["crystalline_salt_pct"] = feed_char.get("crystalline_salt_pct", 0)
    out["non_crystalline_salt_pct"] = feed_char.get("non_crystalline_salt_pct", 0)
    out["ph"] = feed_char.get("ph", 7.0)
    return out


def calc_salt_routing(feed_char: dict, feed_kgh: float, mee_outlet_ts_pct: float) -> dict:
    """
    Estimate salt routing through MEE/ATFD system.

    Based on Excel OVERALL MASS BALANCE logic:
      - Crystalline salts precipitate at saturation point (~36% typically)
      - Non-crystalline salts stay dissolved / in mother liquor
      - Settler / pusher centrifuge efficiency splits solids vs ML
    """
    ts_fraction = feed_char.get("ts_pct", 2.2) / 100.0
    total_solids_kgh = feed_kgh * ts_fraction

    crys_pct = feed_char.get("crystalline_salt_pct", 90.0) / 100.0
    non_crys_pct = feed_char.get("non_crystalline_salt_pct", 10.0) / 100.0

    crys_salt_kgh = total_solids_kgh * crys_pct
    non_crys_salt_kgh = total_solids_kgh * non_crys_pct

    # Saturation point for crystallization (typical for sodium salts)
    crys_saturation_pct = 36.0
    # At MEE outlet conc., what fraction of crystalline salts have precipitated?
    if mee_outlet_ts_pct > crys_saturation_pct:
        # Excess over saturation crystallizes
        precipitated_pct = (mee_outlet_ts_pct - crys_saturation_pct) / mee_outlet_ts_pct
        precipitated_kgh = crys_salt_kgh * min(1.0, precipitated_pct)
    else:
        precipitated_kgh = 0

    remaining_in_ml = total_solids_kgh - precipitated_kgh

    return {
        "total_solids_kgh": total_solids_kgh,
        "crystalline_salt_kgh": crys_salt_kgh,
        "non_crystalline_salt_kgh": non_crys_salt_kgh,
        "precipitated_salt_kgh": precipitated_kgh,
        "remaining_in_ml_kgh": remaining_in_ml,
        "crystallization_saturation_pct": crys_saturation_pct,
        "mee_outlet_ts_pct": mee_outlet_ts_pct,
    }


def feed_char_to_display_rows(feed_char: dict, label: str = "Feed") -> list:
    """Convert feed characterization dict to list of (param, value) display rows."""
    return [
        (f"{label} — TS", f"{feed_char.get('ts_pct', 0):.2f} %"),
        (f"{label} — TDS", f"{feed_char.get('tds_pct', 0):.2f} %"),
        (f"{label} — TSS", f"{feed_char.get('tss_pct', 0):.2f} %"),
        (f"{label} — COD", f"{feed_char.get('cod_mgl', 0):,.0f} mg/L"),
        (f"{label} — BOD", f"{feed_char.get('bod_mgl', 0):,.0f} mg/L"),
        (f"{label} — Chlorides", f"{feed_char.get('chlorides_mgl', 0):,.0f} mg/L"),
        (f"{label} — Sulphates", f"{feed_char.get('sulphates_mgl', 0):,.0f} mg/L"),
        (f"{label} — Crystalline salt fraction", f"{feed_char.get('crystalline_salt_pct', 0):.1f} %"),
        (f"{label} — pH", f"{feed_char.get('ph', 7.0):.1f}"),
    ]
