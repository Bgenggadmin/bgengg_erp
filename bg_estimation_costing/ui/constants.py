"""Reference lists used across UI tabs."""
from bg_estimation_costing.modules import qps_calculators as qc

SECTIONS = ["Evaporator", "Stripper", "Dryer", "Common", "Other"]

SUB_SECTIONS = [
    "HEAT EXCHANGER", "SEPARATORS", "TANK", "PIPING DUCTING FITTING",
    "VALVES", "PUMP", "OTHER", "STRIPPER COLUMN_TRAY TYPE",
    "STRIPPER COLUMN_PACKED TYPE", "STRIPPER REBOILER", "STRIPPER CONDENSER",
    "STRIPPER_FEED TANK", "ATFD-Body", "ATFD-Drive", "ATFD-Aux",
    "STRUCTURE", "VALIDATION", "SOFT COST",
]

CATEGORIES = [
    "B&G-MFG", "Third Party-MFG", "B.O-Local", "B.O-Imported",
    "B&G-Service", "Third Party-Service", "Other",
]

ITEM_TYPES = [
    "MECH_EQP", "MECH_PFV", "INSTRU", "ELEC", "SERVICE",
    "STRUC", "CIVIL", "OTHER",
]

MOC_CHOICES = list(qc.DEFAULT_RM_RATES.keys())

PLANT_TYPES = ["ZLD", "MEE", "Stripping", "Drying", "Distillation", "Other"]

CLADDING_OPTIONS = [
    "None", "SS with Duplex Lining", "SS with Super Duplex Lining",
    "MS with SS Lining", "SS with Ti Cladding",
]

HE_LABELS = [
    "Reboiler", "Stripper Condenser", "MEE Condenser",
    "Surface Condenser", "ATFD Condenser", "Calandria",
    "Pre-Heater", "Heat Exchanger",
]
