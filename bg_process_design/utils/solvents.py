"""
Solvent property database
Extracted from STR-MEB_100KLD_LEE.xlsx COLUMN DIA sheet
"""

# (name, mol_weight, boiling_point_C, has_azeotrope_with_water)
SOLVENTS = {
    "Ethyl Acetate (EA)":        {"mw": 88.11,  "bp": 77.0,  "azeotrope": True},
    "THF":                        {"mw": 72.00,  "bp": 66.0,  "azeotrope": True},
    "n-Butanol":                  {"mw": 74.12,  "bp": 117.7, "azeotrope": False},
    "Cyclohexene":                {"mw": 84.16,  "bp": 80.75, "azeotrope": False},
    "Acetonitrile":               {"mw": 41.05,  "bp": 76.5,  "azeotrope": True},
    "Methyl Dichloride (MDC)":    {"mw": 84.93,  "bp": 39.0,  "azeotrope": False},
    "Di-Iso propyl Ether (DIPE)": {"mw": 102.28, "bp": 69.0,  "azeotrope": False},
    "MTBE":                       {"mw": 88.15,  "bp": 55.0,  "azeotrope": True},
    "Heptane":                    {"mw": 100.21, "bp": 98.4,  "azeotrope": False},
    "Chloroform":                 {"mw": 119.30, "bp": 61.2,  "azeotrope": False},
    "DMF":                        {"mw": 73.09,  "bp": 153.0, "azeotrope": False},
    "1,4-Dioxane":                {"mw": 88.11,  "bp": 101.0, "azeotrope": False},
    "n-Heptane":                  {"mw": 100.21, "bp": 98.4,  "azeotrope": False},
    "DMSO":                       {"mw": 78.13,  "bp": 189.0, "azeotrope": True},
    "n-Propanol":                 {"mw": 60.00,  "bp": 97.0,  "azeotrope": False},
    "1,2-Dichloroethane (EDC)":   {"mw": 98.96,  "bp": 84.0,  "azeotrope": False},
    "Methanol":                   {"mw": 32.04,  "bp": 64.7,  "azeotrope": False},
    "Ethanol":                    {"mw": 46.07,  "bp": 78.37, "azeotrope": False},
    "Acetone":                    {"mw": 58.08,  "bp": 56.0,  "azeotrope": False},
    "Toluene":                    {"mw": 92.14,  "bp": 84.1,  "azeotrope": True},
    "IPA":                        {"mw": 60.01,  "bp": 75.9,  "azeotrope": True},
    "Hexane":                     {"mw": 86.17,  "bp": 68.7,  "azeotrope": False},
    "Ammonia":                    {"mw": 17.03,  "bp": -33.3, "azeotrope": False},
}


def list_solvent_names():
    return list(SOLVENTS.keys())


def get_solvent(name: str):
    return SOLVENTS.get(name)


def calc_mixture_properties(solvent_fractions: dict, water_temp: float = 85.0):
    """
    Given {solvent_name: weight_fraction}, compute avg MW, avg BP, weighted properties.
    Weight fractions should sum <= 1 (rest is assumed water).
    """
    total_solvent_wt = sum(solvent_fractions.values())
    if total_solvent_wt == 0:
        return {"avg_mw": 18.02, "avg_bp": 100.0, "total_solvent_wt": 0}

    moles_total = 0
    mw_weighted = 0
    bp_weighted = 0
    for name, wt in solvent_fractions.items():
        if name not in SOLVENTS:
            continue
        mw = SOLVENTS[name]["mw"]
        bp = SOLVENTS[name]["bp"]
        moles = wt / mw
        moles_total += moles
        mw_weighted += wt
        bp_weighted += bp * wt

    avg_mw = mw_weighted / moles_total if moles_total > 0 else 18.02
    avg_bp = bp_weighted / total_solvent_wt if total_solvent_wt > 0 else 100.0

    return {
        "avg_mw": avg_mw,
        "avg_bp": avg_bp,
        "total_solvent_wt": total_solvent_wt,
        "moles_total": moles_total,
    }
