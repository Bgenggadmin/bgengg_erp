"""
bg_estimation_costing.utils.templates
─────────────────────────────────────
Skeleton templates used as a fallback when no upstream process-design
project is linked. The user can also load these to scaffold a new costing.
"""
from __future__ import annotations
from typing import Dict, List


def mee_skeleton() -> List[Dict]:
    """Standard 150 KLD MEE+Stripper+ATFD package skeleton."""
    rows: List[Dict] = []

    def E(section, sub, eqp, desc="", moc="SS316L", qty=0, unit=0,
          cat="B&G-MFG", typ="MECH_EQP"):
        rows.append({
            "section": section, "sub_section": sub, "equipment": eqp,
            "description": desc, "moc": moc, "qty": qty, "unit_cost": unit,
            "category": cat, "item_type": typ,
            "calc_source": "Template", "design_payload": "",
        })

    # Evaporator
    for i in range(1, 5):
        E("Evaporator", "HEAT EXCHANGER", f"FORCED CIRCULATION-Effect_{i:02d}",
          "HTA — m²", "Ti, Gr2", 0, 0)
    for i in range(1, 5):
        E("Evaporator", "HEAT EXCHANGER", f"PRE HEATER-Effect_{i:02d}",
          "HTA 6 m²", "SS316Ti, 1.65 thk", 0, 0)
    E("Evaporator", "HEAT EXCHANGER", "MEE CONDENSER", "HTA — m²",
      "SS304, 1.65 thk", 0, 0)
    for i in range(1, 5):
        E("Evaporator", "SEPARATORS", f"VLS-{i}", "", "SS316L", 0, 0)
    E("Evaporator", "TANK", "MEE_FEED TANK", "2.5 KL", "SS316L", 0, 0)
    E("Evaporator", "TANK", "MEE_PROCESS CONDENSATE TANK", "1.5 KL", "SS304", 0, 0)
    for nm, sp in [("Feed Pump", "SS316L 8 m³/h × 60 m"),
                   ("RCP-1 (1+1)", "SS316 150 m³/h × 12 m"),
                   ("RCP-2 (1+1)", "SS316 225 m³/h × 12 m"),
                   ("Process Cond Pump", "SS304 2 m³/h × 15 m"),
                   ("Product Pump", "SS316 0.5 m³/h × 15 m")]:
        E("Evaporator", "PUMP", "CENTRIFUGAL PUMP", nm, sp, 0, 0,
          cat="B.O-Local")

    # Stripper
    E("Stripper", "STRIPPER COLUMN_TRAY TYPE", "Stripper Column",
      "850Ø × 20m", "SS316L", 0, 0)
    E("Stripper", "STRIPPER REBOILER", "Re-Boiler", "HTA 25 m²",
      "SS304 / Ti tubes", 0, 0)
    E("Stripper", "STRIPPER CONDENSER", "Stripper Condenser", "HTA 30 m²",
      "SS304 / Ti tubes", 0, 0)
    E("Stripper", "TANK", "STRIPPER FEED TANK", "5 KL", "SS316L", 0, 0)
    E("Stripper", "TANK", "STRIPPER STEAM CONDENSATE TANK", "2 KL", "SS304", 0, 0)

    # Dryer (ATFD)
    E("Dryer", "ATFD-Body", "ATFD", "HTA 15 m²", "Duplex 2205", 0, 0)
    E("Dryer", "ATFD-Drive", "ATFD Gearbox + Motor", "", "Std", 0, 0,
      cat="B.O-Local")
    E("Dryer", "TANK", "ATFD FEED TANK", "0.5 KL", "SS316L", 0, 0)
    E("Dryer", "TANK", "ATFD CONDENSATE TANK", "0.1 KL", "SS304", 0, 0)

    # Common
    E("Common", "VALIDATION", "Documentation & Validation", "DQ/IQ/OQ",
      "NA", 1, 100000, cat="B&G-Service", typ="SERVICE")
    E("Common", "STRUCTURE", "MS Support Structure", "Tubular framing",
      "MS", 0, 0, typ="STRUC")
    return rows


def eia_skeleton() -> List[Dict]:
    """Standard EIA instrument list — mirrors reference EIA COST sheet."""
    return [
        {"section": "Stripper", "equipment": "STRIPPER COLUMN_TRAY TYPE",
         "instrument": "Temperature Transmitter",
         "description": "Column Top & Bottom",
         "moc": "FLP", "qty": 2, "unit_cost": 5000},
        {"section": "Stripper", "equipment": "STRIPPER COLUMN_TRAY TYPE",
         "instrument": "Level Transmitter",
         "description": "Column Bottom",
         "moc": "FLP", "qty": 1, "unit_cost": 100000},
        {"section": "Stripper", "equipment": "STRIPPER REBOILER",
         "instrument": "Steam Control Valve",
         "description": "Reboiler Steam Line",
         "moc": "FLP", "qty": 1, "unit_cost": 75000},
        {"section": "Stripper", "equipment": "STRIPPER REBOILER",
         "instrument": "Vortex Flow meter",
         "description": "Reboiler Steam Line",
         "moc": "FLP", "qty": 1, "unit_cost": 150000},
        {"section": "Stripper", "equipment": "STRIPPER CONDENSER",
         "instrument": "Temperature Transmitter",
         "description": "CW Header Inlet+Outlet",
         "moc": "FLP", "qty": 2, "unit_cost": 5000},
        {"section": "Evaporator", "equipment": "FORCED CIRCULATION",
         "instrument": "Temperature Transmitter",
         "description": "Each Effect",
         "moc": "FLP", "qty": 4, "unit_cost": 5000},
        {"section": "Evaporator", "equipment": "MEE CONDENSER",
         "instrument": "Vacuum Transmitter",
         "description": "Vapor Line",
         "moc": "FLP", "qty": 1, "unit_cost": 35000},
        {"section": "Common", "equipment": "PLC PANEL",
         "instrument": "PLC + HMI Panel",
         "description": "Allen-Bradley / Siemens",
         "moc": "NA", "qty": 1, "unit_cost": 1500000},
        {"section": "Common", "equipment": "MCC PANEL",
         "instrument": "Motor Control Centre",
         "description": "VFD + DOL Starters",
         "moc": "NA", "qty": 1, "unit_cost": 1200000},
        {"section": "Common", "equipment": "FIELD WIRING",
         "instrument": "Cabling + Cable Tray",
         "description": "Lump-sum",
         "moc": "NA", "qty": 1, "unit_cost": 700000},
    ]
