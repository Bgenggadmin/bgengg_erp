"""
Default Offer Data Structure

Provides a pre-populated dict matching the 150 KLD ZLD offer template
(based on Quote BG/ECOX-ZLD/26-27/2930 R2 — MSN LS-1).
Trainee engineers can start from these defaults and tweak only what
varies for their specific client.

Schema expansion (May 2026):
- feed_parameters: added specific_gravity
- technical_specs: each unit (stripper/mee/atfd) now has per-unit utility
  fields (steam, power, cooling water, compressed air)
- economics: added power_cost_inr_kwh, cooling_water_cost_inr_m3,
  effluent_treatment_cost_inr_kl, plant-wide totals
"""
from datetime import date
from bg_offer_generator.utils.brand import (
    EXECUTIVE_SUMMARY_DEFAULT,
    STRIPPER_DESCRIPTION_DEFAULT,
    MEE_DESCRIPTION_DEFAULT,
    ATFD_DESCRIPTION_DEFAULT,
    PERFORMANCE_GUARANTEE,
    PAYMENT_TERMS_DEFAULT,
    DELIVERY_TIMELINE_DEFAULT,
    PRICE_VALIDITY_DAYS_DEFAULT,
)


def default_offer_data() -> dict:
    """Return default 150 KLD ZLD offer template data."""
    return {
        # ----- Cover Page -----
        "cover": {
            "quote_ref": "BG/ECOX-ZLD/26-27/XXXX R0",
            "quote_date": date.today().isoformat(),
            "submitted_to": "M/s. Client Name Ltd",
            "location": "City",
            "prepared_by": "Engineer Name",
            "contact_details": "9154971801 / 9959477028",
            "email": "evs@bgengineeringind.com",
            "kind_attn": "Mr. Name, Designation",
            "subject": "Proposal for 150 KLD STRIPPER, MEE & ATFD System",
            "discussion_date": "",
            "capacity_kld": 150,
        },

        # ----- PART I: Executive Summary -----
        "executive_summary": EXECUTIVE_SUMMARY_DEFAULT,

        # ----- PART II: Process Description -----
        "process_description": {
            "stripper": STRIPPER_DESCRIPTION_DEFAULT,
            "mee": MEE_DESCRIPTION_DEFAULT,
            "atfd": ATFD_DESCRIPTION_DEFAULT,
            "n_effects": 4,
        },

        # ----- PART IV: Economics & OPEX -----
        # User-input keys are listed first; the rest are computed live by
        # _recalc_economics() in pages/11_Offer_Generator.py.
        "economics": {
            # --- User inputs: overall parameters ---
            "operating_hours_day": 20,
            "operating_days_year": 300,
            "steam_cost_inr_kg": 2.0,
            "power_cost_inr_kwh": 9.0,
            "cooling_water_cost_inr_m3": 90.0,
            "effluent_treatment_cost_inr_kl": 1185.0,
            # --- User inputs: steam consumption for advantage table ---
            "conventional_steam_kgh": 1590,
            "ecox_steam_kgh": 1286,
            # --- Computed steam comparison (overwritten by _recalc_economics) ---
            "conventional_annual_steam_tons": 9540,
            "conventional_annual_cost_cr": 1.91,
            "ecox_annual_steam_tons": 7716,
            "ecox_annual_cost_cr": 1.54,
            "steam_reduction_pct": 19.12,
            "annual_steam_savings_tons": 1824,
            "annual_savings_lakhs": 36.48,
            # --- Computed annual operational cost ---
            "annual_operational_cost_inr": 53325000,
        },

        # ----- PART V: Feed Parameters -----
        "feed_parameters": {
            "capacity_kld": 150,
            "feed_ph": "6.5 - 8.0",
            "specific_gravity": "1.0",
            "total_cod_ppm": 200000,
            "volatile_organic_solvents_ppm": 100000,
            "total_solids_pct": "5-10%",
            "suspended_solids_ppm": "<500",
            "feed_temp_c": 30,
            "total_hardness_ppm": "<1000",
            "silica_ppm": "<20",
            "free_chloride_ppm": "Nil",
            "feed_nature": "Non-Foaming",
        },

        # ----- PART V: Technical Specifications (per unit, including utilities) -----
        "technical_specs": {
            "stripper": {
                "type": "Tray Type Column",
                "feed_kgh": 7500,
                "distillate_kgh": 1050,
                "distillate_composition": "70% Solvents, 30% Water",
                "bottoms_kgh": 6450,
                "reflux_kgh": 1315,
                # Per-unit utilities
                "steam_kgh": 1035,
                "steam_pressure": "1.5 Bar-g",
                "power_kwh": 9,
                "cooling_water_m3h": 105,
                "cooling_water_tr": 220,
                "cooling_water_temps": "In/Out: 32 / 38 °C",
                "compressed_air_nm3h": "8",
                "compressed_air_pressure": "6 Bar-g",
            },
            "mee": {
                "type": "4-Effect Multiple Effect Evaporator",
                "configuration": "Forced Circulation Type",
                "feed_kgh": 6450,
                "feed_solids_pct": "5.8 - 11.6",
                "evaporation_kgh": 5515,
                "concentrate_kgh": 1870,
                "concentrate_solids_pct": 40,
                # Per-unit utilities
                "steam_kgh": 1286,
                "steam_pressure": "1.5 Bar-g",
                "steam_economy": 4.3,
                "power_kwh": 45,
                "cooling_water_m3h": 130,
                "cooling_water_tr": 270,
                "cooling_water_temps": "In/Out: 32 / 38 °C",
                "compressed_air_nm3h": "8-10",
                "compressed_air_pressure": "6 Bar-g",
            },
            "atfd": {
                "type": "Agitated Thin Film Dryer",
                "feed_kgh": 1870,
                "feed_solids_pct": 40,
                "evaporation_kgh": 1055,
                "product_kgh": 815,
                "product_moisture_pct": "8-10",
                # Per-unit utilities
                "steam_kgh": 1320,
                "steam_pressure": "1.5 Bar-g",
                "power_kwh": 65,
                "cooling_water_m3h": 60,
                "cooling_water_tr": 120,
                "cooling_water_temps": "In/Out: 32 / 38 °C",
                "compressed_air_nm3h": "8",
                "compressed_air_pressure": "6 Bar-g",
            },
        },

        # ----- Plant-wide utility totals (computed; can also be entered manually) -----
        "utilities": {
            # Legacy per-unit steam blocks (kept for backward compatibility
            # with anything else reading from here; mirrors technical_specs)
            "stripper_steam": {"param": "1.5 Bar-g, >96% dryness", "value_kgh": 1035},
            "mee_steam":      {"param": "1.5 Bar-g, >96% dryness", "value_kgh": 1286, "steam_economy": 4.3},
            "atfd_steam":     {"param": "1.5 Bar-g, >96% dryness", "value_kgh": 1320},
            # Plant-wide totals (overwritten by _recalc_economics)
            "total_steam_kgh": 3641,
            "total_power_kwh": 119,
            "total_cooling_water_m3h": 295,
            "total_cooling_water_tr": 610,
            # Legacy keys kept so docx_generator and any historic readers don't break
            "power_consumption_kwh": 119,
            "power_installed_kw": 180,
            "cooling_water_m3h": 295,
            "cooling_water_temps": "In/Out: 32 / 38 Deg. C",
            "seal_water": "DDE",
            "compressed_air_nm3h": "8-10",
            "compressed_air_pressure": "6 Bar-g",
            "cip_solutions": "1.5% HNO3 Solution / 3.0% Caustic Solution 1 Bar, 75-85 Deg.C",
        },

        "performance_guarantee": list(PERFORMANCE_GUARANTEE),

        # ----- PART VI: Scope of Supply -----
        "scope_stripper": _default_stripper_scope(),
        "scope_mee": _default_mee_scope(),
        "scope_atfd": _default_atfd_scope(),
        "instruments": _default_instruments(),

        # ----- PART VII: Battery Limits -----
        "battery_limits": [
            "Feed at the inlet of MEE Feed Balance Tank.",
            "Steam at required pressure at the inlet of equipment nozzles along with IBR standard Piping, Bypass valve, isolation valves & steam traps.",
            "Cooling water at 2.5 Bar-g at the inlet of condenser nozzles as required.",
            "Seal water make-up at the Seal water tanks within battery limit.",
            "Soft water for Cooling Tower make-up at inlet of CT basin.",
            "Power at inlet of consumption point within battery limit.",
            "Service water at one point of MEE area within battery limit.",
            "Instrument air at one point of MEE area within battery limit.",
            "Any chemicals for CIP solution preparation in customer scope.",
            "Process Condensate handling from process condensate pumps.",
            "Steam condensate from system outlet nozzles.",
            "Dry product handling from ATFD bottom.",
        ],

        # ----- PART VIII: Scope Matrix -----
        "scope_matrix": _default_scope_matrix(),

        # ----- PART X: Pricing -----
        "pricing": {
            "option1_moc": "Titanium & Duplex 2205",
            "option2_moc": "SS 316Ti & SS 316L",
            "option1_equipment_price_cr": 5.00,
            "option2_equipment_price_cr": 4.85,
            "option1_install_lakhs": 25,
            "option2_install_lakhs": 25,
            "option1_total_cr": 5.25,
            "option2_total_cr": 5.10,
            "payment_terms": list(PAYMENT_TERMS_DEFAULT),
            "delivery_timeline": dict(DELIVERY_TIMELINE_DEFAULT),
            "price_validity_days": PRICE_VALIDITY_DAYS_DEFAULT,
            "location_dap": "Hyderabad",
        },
    }


def _default_stripper_scope():
    return [
        {"equipment": "Stripper Column (Tray Type)",
         "specification": "Dia: 600 mm, Total Ht: 18-20 Mtr\nColumn Shell: SS 316L\nTrays: SS 316L\nBody Flange: MS with SS Cladding",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Stripper Re-Boiler (FC Type) — Option 1",
         "specification": "HTA: 12 M²\nShell: SS 304\nTube: 0.9 mm Thk, Titanium Gr2, Seamless\nTube Sheet: Duplex 2205\nTop & Bottom Bonnet: Duplex 2205\nBody Flange: MS with Duplex Cladding",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Stripper Re-Boiler (FC Type) — Option 2",
         "specification": "Shell: SS 304\nTube: 38.1mm, 1.65 mm Thk, SS 316Ti\nTube Sheet: SS 316L\nTop & Bottom Bonnet: SS 316L\nBody Flange: SS 316L",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Stripper Condenser",
         "specification": "HTA: 25 M²\nShell: SS 316L\nTube: 25.4 mm, 1.6 mm, SS 316L\nTube Sheet: SS 316L\nTop & Bottom Bonnet: SS 316L\nBody Flange: SS 316L",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Feed Pump",
         "specification": "Flow: ~5 m³/h\nType: Centrifugal, FLP, IE3\nSingle Mechanical Seal\nContact Parts: SS 316, Base Frame: MS",
         "qty": "1W", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Re-Boiler Re-Circulation Pump",
         "specification": "Flow: ~100 m³/h\nType: Centrifugal, FLP, IE3\nDouble Mechanical Seal\nContact Parts: SS 316, Base Frame: MS",
         "qty": "1W+1SB", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Re-Flux cum Condensate Pump",
         "specification": "Flow: ~1 m³/h\nType: Centrifugal, FLP, IE3\nSingle Mechanical Seal\nContact Parts: SS 316, Base Frame: MS",
         "qty": "1W", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Feed Balance Tank",
         "specification": "Capacity: 1.5 KL\nContact Parts: SS 316L\nNon-Contact Parts: SS 304/MS",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Reflux cum Condensate Tank",
         "specification": "Capacity: 0.5 KL\nContact Parts: SS 316L\nNon-Contact Parts: SS 304/MS",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Product Piping, Vapor Duct, Process Condensate Piping",
         "specification": "Contact Parts: SS 316L/SS 304\nUp to 50 NB: SCH 10\n50-250 NB: SCH 5\nAbove 250 NB: Fabricated",
         "qty": "1 Lot", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Cooling Water Piping",
         "specification": "Contact Parts: MS",
         "qty": "1 Lot", "bg_scope": False, "buyer_scope": True},
        {"equipment": "Steam / IBR Piping with IBR Certification",
         "specification": "MS – Class C",
         "qty": "1 Lot", "bg_scope": False, "buyer_scope": True},
    ]


def _default_mee_scope():
    return [
        {"equipment": "Calandria (FC Type) — Option 1",
         "specification": "Total HTA: 325 M²\nShell: SS 316L\nTube: 0.9 mm, Titanium Gr2, Seamless\nTube Sheet: Duplex 2205\nBonnet: Duplex 2205",
         "qty": "4 Nos", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Calandria (FC Type) — Option 2",
         "specification": "Total HTA: 295 M²\nShell: SS 316L\nTube: 38.1 mm, 1.6 mm Thk, SS 316Ti\nTube Sheet: SS 316L\nBonnet: SS 316L",
         "qty": "4 Nos", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Pre-Heater",
         "specification": "HTA: DDE\nShell: SS 316L\nTube: 25.4 mm, 1.6 mm Thk, SS 316Ti (Option 2) or 0.9mm Titanium (Option 1)",
         "qty": "4 Nos", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Surface Condenser",
         "specification": "HTA: 60 M²\nShell: SS 316L\nTubes: 25.4 mm, 1.6 mm, SS 316L\nTube Sheet: SS 316L",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Vapor Liquid Separator",
         "specification": "VLS-1: ~1 KL, VLS-2: ~2.5 KL\nVLS-3: ~3 KL, VLS-4: ~4 KL\nContact Parts: SS 316L",
         "qty": "4 Nos", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Recirculation Pumps",
         "specification": "Type: Centrifugal, IE3, NFLP\nDouble Mechanical Seal\nContact Parts: SS 316\nBase Frame: MS",
         "qty": "4W+2SSB", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Concentrate Discharge Pump",
         "specification": "Flow: 1 m³/h\nType: Centrifugal, IE3, NFLP\nDouble Mechanical Seal\nContact Parts: SS 316",
         "qty": "1W", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Process Condensate Pump",
         "specification": "Flow: 4 m³/h\nType: Centrifugal, IE3, NFLP\nDouble Mechanical Seal\nContact Parts: SS 316",
         "qty": "1W", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Vacuum Pump",
         "specification": "Model: VWS 150\nType: Water Ring\nImpeller: SS 316, Housing: MS",
         "qty": "1W+1SB", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Process Condensate Tank",
         "specification": "Capacity: 1.0 KL\nContact Parts: SS 304",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
    ]


def _default_atfd_scope():
    return [
        {"equipment": "Agitated Thin Film Dryer (22 m²)",
         "specification": "Steam Jacket: MS\nInner Shell & Blades: SS 316L\nRotor & Shaft: SS 316L\nMotor: Crompton, NFLP\nGear Box: Bonfiglioli, Inline",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
        {"equipment": "ATFD Condenser",
         "specification": "HTA: 30 M²\nShell: SS 316L\nTube: 25.4 mm, 1.6 mm, SS 316L\nTube Sheet: SS 316L",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Scrubber Column",
         "specification": "Contact Parts: SS 316L\nNon-Contact parts: SS 304",
         "qty": "1 Set", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Feed Pump",
         "specification": "Flow: 1 m³/h\nType: Centrifugal/Screw, IE3, NFLP\nSingle Mechanical Seal\nContact Parts: SS 316",
         "qty": "1W", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Process Condensate Pump",
         "specification": "Flow: 1 m³/h\nType: Centrifugal, IE3, NFLP\nSingle Mechanical Seal\nContact Parts: SS 316",
         "qty": "1W", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Centrifugal Blower",
         "specification": "610 CFM\nType: Centrifugal ID Fan\nCasing & Impeller: SS 304",
         "qty": "1W", "bg_scope": True, "buyer_scope": False},
        {"equipment": "Feed Tank with Agitator",
         "specification": "Capacity: 0.5 KL\nContact Parts: SS 316L",
         "qty": "1 No", "bg_scope": True, "buyer_scope": False},
    ]


def _default_instruments():
    return [
        {"item": "Level Control Valve", "qty": "2 No", "scope": "B&G"},
        {"item": "Magnetic Flow Meter", "qty": "4 No", "scope": "B&G"},
        {"item": "Temperature Transmitter", "qty": "1 Lot", "scope": "B&G"},
        {"item": "Pressure Transmitter", "qty": "3 No", "scope": "B&G"},
        {"item": "Level Transmitter", "qty": "2 No", "scope": "B&G"},
        {"item": "Vacuum Transmitter", "qty": "5 No", "scope": "B&G"},
        {"item": "Rota-meter", "qty": "2 No", "scope": "B&G"},
        {"item": "Pressure Gauges / Temperature Gauges / Vacuum Gauges", "qty": "1 Lot each", "scope": "B&G"},
        {"item": "Control Panel: PLC with SCADA", "qty": "1 Set", "scope": "B&G"},
        {"item": "MCC / Electrical Panel (NFLP)", "qty": "1 Set", "scope": "B&G"},
        {"item": "Instrument Cables", "qty": "1 Lot", "scope": "B&G"},
        {"item": "Power / Control / Data Cables between Motors / MCC / PLC", "qty": "1 Lot", "scope": "Customer"},
        {"item": "Cable laying, Trays, Supports, Junction Boxes", "qty": "1 Lot", "scope": "Customer"},
    ]


def _default_scope_matrix():
    bg = True
    cust = False
    return [
        {"description": "Design, Engineering, Manufacturing, Supply, Installation and Commissioning as mentioned in scope of supply.", "bg": bg, "client": cust},
        {"description": "Unloading & Safe Storage of supplied material at site.", "bg": cust, "client": bg},
        {"description": "Supply of Pipes, fittings, valves within battery limits.", "bg": bg, "client": cust},
        {"description": "Fabrication & Installation of Pipes, fittings, valves within battery limits.", "bg": bg, "client": cust},
        {"description": "Insulation & Cladding of Stripper, MEE & ATFD system as required.", "bg": cust, "client": bg},
        {"description": "Supply of Pumps with Motors as mentioned in scope of supply.", "bg": bg, "client": cust},
        {"description": "Supply and Installation of MCC panel with Incoming/Outgoing Feeders, Busbars, Wiring, Starters, Drivers, Energy meters.", "bg": bg, "client": cust},
        {"description": "Supply & Installation of Instruments, Cables, PLC Panel with SCADA based Automation.", "bg": bg, "client": cust},
        {"description": "Electrical/Power Cables, Cable trays & Supports between MCC, PLC and Motors.", "bg": cust, "client": bg},
        {"description": "Cable trays, Cable laying between panel, instruments and valves.", "bg": cust, "client": bg},
        {"description": "Any civil related work (RCC tank, building, foundation, Platforms).", "bg": cust, "client": bg},
        {"description": "MS/Civil Structure with Platforms, Support Beams, Stair case, Handrails.", "bg": cust, "client": bg},
        {"description": "Plant shade roofing/sheeting, Louvers, Purlins, Foundation bolts.", "bg": cust, "client": bg},
        {"description": "Structure Load data, GA diagram, foundation drawings of plant.", "bg": bg, "client": cust},
        {"description": "Cooling tower with pumps & pipeline.", "bg": cust, "client": bg},
        {"description": "CIP system with CIP tank & pump, dosing tanks & pumps.", "bg": cust, "client": bg},
        {"description": "Seal water cooling system with Tank, PHE and pumps.", "bg": bg, "client": cust},
        {"description": "CIP/Effluent drain handling through pump, drain pit.", "bg": cust, "client": bg},
        {"description": "Any statutory approval, government and local authority approval.", "bg": cust, "client": bg},
        {"description": "HAZOP analysis, if required.", "bg": cust, "client": bg},
        {"description": "Plant lightning and any internal works.", "bg": cust, "client": bg},
        {"description": "Item/Service not mentioned in above scope of supply.", "bg": cust, "client": bg},
    ]
