"""
B&G Engineering Brand Constants and Boilerplate

Centralized color palette, fonts, and all reusable text blocks
from the standard offer template.
"""

# ---------------------------------------------------------------------
# BRAND COLORS (extracted from B&G logo and offer styling)
# ---------------------------------------------------------------------
BRAND = {
    "primary_red":   "#C7203E",   # Deep red from logo
    "accent_pink":   "#E91E63",   # Pink from logo
    "dark_text":     "#2C2C2C",
    "light_bg":      "#F8F8F8",
    "water_blue":    "#2E75B6",   # "Responsible towards water"
    "table_header":  "#C7203E",
    "table_row_alt": "#FDECEF",   # Light tint for alternating rows
    "success_green": "#2E7D32",
    "white":         "#FFFFFF",
}

# DOCX color hex strings (no '#' prefix)
DOCX_COLORS = {
    "primary_red":   "C7203E",
    "accent_pink":   "E91E63",
    "water_blue":    "2E75B6",
    "table_header":  "C7203E",
    "table_row_alt": "FDECEF",
    "white":         "FFFFFF",
    "border_gray":   "CCCCCC",
    "dark_text":     "2C2C2C",
}

# Fonts
FONT_PRIMARY = "Calibri"
FONT_HEADING = "Calibri"


# ---------------------------------------------------------------------
# COMPANY METADATA
# ---------------------------------------------------------------------
COMPANY = {
    "name": "B&G Engineering Industries",
    "address": "207, Phase – III, Industrial Park, Pashamylaram, Patancheru Mandal, Hyderabad, India",
    "managing_partner": "N S HARIBABU",
    "managing_partner_title": "Managing Partner",
    "tagline": "Responsible towards water",
    "email_default": "evs@bgengineeringind.com",
    "contact_default": "9154971801 / 9959477028",
    "website": "www.bgengineeringind.com",
}


# ---------------------------------------------------------------------
# BOILERPLATE TEXT (all editable per client)
# ---------------------------------------------------------------------
EXECUTIVE_SUMMARY_DEFAULT = """B&G Engineering Industries is an established Indian engineering company specializing in the design, manufacture, and supply of process equipment and turnkey solutions for the chemical, pharmaceutical, food, agro-processing, and wastewater treatment industries. B&G has built a strong reputation in critical separation and thermal systems such as evaporators, dryers, heat exchangers, distillation columns, solvent recovery system, and Zero Liquid Discharge (ZLD) plants. With in-house fabrication, testing, and quality control, B&G delivers customized, high-reliability solutions aligned with stringent industrial and environmental standards.

B&G's core strength lies in its process engineering capability optimizing energy efficiency, recovery of valuable by-products, and compliance with increasingly strict pollution norms. Our solutions are widely used in effluent concentration, solvent recovery, and product purification applications. Supported by an experienced engineering team and a growing domestic and export footprint, B&G Engineering Industries positions itself as a cost-effective and technically competent alternative to global OEMs, particularly for mid-scale and large industrial process plants."""

STRIPPER_DESCRIPTION_DEFAULT = """High COD stream effluent is fed to the MEE preheater where it is preheated and is fed to Stripper column. Heat required for stripper reboiler will be provided through steam. Solvent and Water mixed Vapour from top of the column is condensed in condenser(s).

Total Condensate is collected in reflux tank and Fraction of the condensate is fed back as reflux while remaining condensate is taken out as distillate and column bottom is pumped to Evaporation system for further process."""

MEE_DESCRIPTION_DEFAULT = """The Feed from Stripper bottom is fed to MEE, where Evaporation will be concentrated in {n_effects}-effect evaporator plant. Feed will flow in forward feed manner in evaporators. All effects shall be of Shell & Tube Forced Circulation type.

Live dry saturated steam shall be fed to first effect shell side. The system will be subjected to vacuum and the Vapours generated in the first effect & vapour generated from ATFD shall be condensed on the shell side of second effect; vapours generated in the second effect shall be condensed on the shell side of third effect; Vapour generated in the third effect shall be condensed on the fourth effect; Vapours generated in the last effect shall be condensed on the shell side of surface condenser which is circulated with cooling water on tube side.

The total condensate shall be collected in condensate tank from surface condenser and will be treated further. Concentrated product after water evaporation shall be transferred to ATFD for further drying."""

ATFD_DESCRIPTION_DEFAULT = """MEE Concentrate shall be stored in ATFD Feed Tank. ATFD Feed Tank shall be provided with low rpm agitator. Effluent from ATFD Feed Tank will be fed to the top of ATFD through ATFD Feed Pump or fed directly to ATFD through concentrate discharge pump.

Dry & saturated steam will be supplied in the ATFD Jacket which will heat the surface. ATFD is the vertical jacketed vessel fitted with rotating blades. Specially designed feed distribution system will form the thin film of Effluent along the inner wall of ATFD shell. Heat transfer from ATFD jacket to effluent film results in evaporation of film. Due to evaporation dry powder will form which will be scraped out by rotating blades.

The vapor evaporated from the ATFD will have significant amount of energy, that energy shall be recovered by utilizing the ATFD vapor in the evaporation system as heating medium. This energy recovery will save fresh steam consumption in evaporation system. This will also lead to lower the carbon foot print.

Continuous scraping of powder by rotating blades from ATFD shell will helps to create new heat transfer area for further evaporation. Dry product will be collected at the bottom of ATFD."""


# ---------------------------------------------------------------------
# COVER LETTER
# ---------------------------------------------------------------------
COVER_LETTER_INTRO = """Dear Sir,

This is with reference to discussions dated {discussion_date}, we are pleased to submit our offer for Design, Engineering, Manufacturing, Supply, Installation and Commissioning of {capacity} KLD STRIPPER, MEE and ATFD systems.

Please find our proposal for your kind perusal, we hope our offer is in line with your requirement.

Please feel free to contact us for in further information/clarification, if required."""


# ---------------------------------------------------------------------
# PERFORMANCE GUARANTEE BULLETS
# ---------------------------------------------------------------------
PERFORMANCE_GUARANTEE = [
    "System Performance shall be Guaranteed for below parameters with 10% tolerance:",
    "Stripper: Top Distillate Outlet Flow as mentioned in above table",
    "Evaporator: Water Evaporation Rate as mentioned in above table",
    "ATFD: Water Evaporation rate as mentioned in above table",
    "Steam consumption as mentioned in above table",
    "Power consumption as mentioned in above table",
    "System shall be cleaned as suggested by supplier during commissioning process.",
    "Above mentioned energy consumption and performance are based on timely CIP of system.",
    "Any change in feed parameters and utility shall impact the system performance.",
    "Plant performance will depend on regular CIP and maintenance as per plant operation manual.",
    "In case of variation in initial solids of feed on lower side, ATFD feed will be reduced, thereby vapor generation in ATFD will also be reduced. In such case ATFD vapor which is being used in evaporator as a heating medium shall be reduced and fresh steam consumption will increase.",
]


# ---------------------------------------------------------------------
# PAYMENT TERMS DEFAULT
# ---------------------------------------------------------------------
PAYMENT_TERMS_DEFAULT = [
    "30% Advance of Basic order value.",
    "65% of order value with applicable taxes & duties on Prorata basis against submission of proforma invoice after readiness of material but prior to dispatch.",
    "5% remaining order value with applicable taxes & duties within 15 days after commissioning. In case of any delay in commissioning for reason not attributed to B&G Engineering, remaining amount shall be paid within 60 days from the date of last major supply.",
]

DELIVERY_TIMELINE_DEFAULT = {
    "supply_option1": "6-7 Month from the date of PO and receipt of advance payment.",
    "supply_option2": "3-4 Month from the date of PO and receipt of advance payment.",
    "installation": "1.5 Month (Subject to site readiness).",
    "commissioning": "15-20 Days.",
}

PRICE_VALIDITY_DAYS_DEFAULT = 15


# ---------------------------------------------------------------------
# TABLE OF CONTENTS (11 parts)
# ---------------------------------------------------------------------
OFFER_TOC = [
    ("PART I",    "EXECUTIVE SUMMARY"),
    ("PART II",   "PROCESS DESCRIPTION"),
    ("PART III",  "PROCESS FLOW DIAGRAM"),
    ("PART IV",   "ESTIMATED PLANT ECONOMICS & OPEX"),
    ("PART V",    "TECHNICAL DETAILS & UTILITIES"),
    ("PART VI",   "SCOPE OF SUPPLY"),
    ("PART VII",  "BATTERY LIMITS"),
    ("PART VIII", "SCOPE MATRIX"),
    ("PART IX",   "BASIS OF COMMISSIONING / TAKE-OVER"),
    ("PART X",    "PRICE AND COMMERCIAL TERMS & CONDITIONS"),
    ("PART XI",   "GENERAL TERMS & CONDITIONS"),
]
