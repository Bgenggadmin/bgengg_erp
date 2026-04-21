"""
Line Sizing Calculations - Liquid and Vapor
Based on: ATFD_40C_100KLD_LEE.xlsx "Line Sizing" sheet
"""
import math


# Standard pipe sizes (NPS in mm ID approximate)
STD_PIPE_ID_MM = [
    15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200,
    250, 300, 350, 400, 450, 500, 550, 600,
]


def calc_line_size_liquid(flow_kgh: float, density_kgm3: float, velocity_ms: float):
    """
    Calculate liquid line size.
    Typical velocities:
      Pump suction / gravity: 0.9 m/s
      Pump discharge: 1.5 m/s
    """
    if flow_kgh <= 0 or velocity_ms <= 0:
        return {"flow_m3h": 0, "id_calc_mm": 0, "id_selected_mm": 0}

    flow_m3h = flow_kgh / density_kgm3
    flow_m3s = flow_m3h / 3600.0
    area_m2 = flow_m3s / velocity_ms
    id_m = math.sqrt(4 * area_m2 / math.pi)
    id_mm = id_m * 1000

    id_sel = next((s for s in STD_PIPE_ID_MM if s >= id_mm), STD_PIPE_ID_MM[-1])

    return {
        "flow_kgh": flow_kgh,
        "density_kgm3": density_kgm3,
        "velocity_ms": velocity_ms,
        "flow_m3h": flow_m3h,
        "id_calc_mm": id_mm,
        "id_selected_mm": id_sel,
    }


def calc_line_size_vapor(flow_kgh: float, density_kgm3: float, velocity_ms: float = 15.0):
    """
    Calculate vapor line size. Typical vapor velocity: 10-20 m/s.
    """
    if flow_kgh <= 0 or velocity_ms <= 0 or density_kgm3 <= 0:
        return {"flow_m3h": 0, "id_calc_mm": 0, "id_selected_mm": 0}

    flow_m3h = flow_kgh / density_kgm3
    flow_m3s = flow_m3h / 3600.0
    area_m2 = flow_m3s / velocity_ms
    id_m = math.sqrt(4 * area_m2 / math.pi)
    id_mm = id_m * 1000

    id_sel = next((s for s in STD_PIPE_ID_MM if s >= id_mm), STD_PIPE_ID_MM[-1])

    return {
        "flow_kgh": flow_kgh,
        "density_kgm3": density_kgm3,
        "velocity_ms": velocity_ms,
        "flow_m3h": flow_m3h,
        "id_calc_mm": id_mm,
        "id_selected_mm": id_sel,
    }


# Predefined line lists for each unit
STRIPPER_LINES = [
    ("Process: Feed Tank → Feed Pump Suction",       "suction",  0.9),
    ("Process: Feed Pump Discharge → PH-1",           "discharge", 1.5),
    ("Process: PH-1..5 → STP Column Top",             "suction",  0.9),
    ("Process: STP Column Bottom → RCP Suction",      "suction",  0.9),
    ("Process: RCP Discharge → Reboiler",             "discharge", 1.5),
    ("Process: Reboiler → STP Column",                "suction",  0.9),
    ("Steam Cond: Reboiler Shell → SC Tank",          "suction",  0.9),
    ("Steam Cond: SCP Delivery → Collection",         "discharge", 1.5),
    ("Process Cond: STP Primary Cond → Reflux Tank",  "suction",  0.9),
    ("Process Cond: Reflux Tank → RP Suction",        "suction",  0.9),
    ("Process Cond: RP Discharge → STP Column",       "discharge", 1.5),
]

MEE_LINES_TEMPLATE = [
    ("Process: VLS-{i} Bottom → RCP.{i} Suction",     "suction",  0.9),
    ("Process: RCP.{i} Discharge → CAL.{i} Bottom",   "discharge", 1.5),
    ("Process: CAL.{i} Top → VLS.{i}",                "suction",  0.9),
    ("Process: VLS.{i} Feed out → RCP.{next} Suction", "suction",  0.9),
    ("Process Cond: CAL.{i} Condensate → CAL.{next} Shell", "suction", 0.9),
]
