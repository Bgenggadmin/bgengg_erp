"""
Page 11 — B&G Offer Generator

Generates branded techno-commercial offer DOCX documents.
Password-gated. Reads logo from Supabase storage bucket.
Optionally links to process design projects via pd_project_id.

Tables written to:
  offers           (offer_data stored as JSONB)
  customer_master  (when adding new clients inline)
"""
import sys, os
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import date
import json

# ---------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Offer Generator — BGEngg ERP",
    page_icon="📄",
    layout="wide",
)

# ---------------------------------------------------------------------
# PASSWORD GATE
# ---------------------------------------------------------------------
_TEAM_PASSWORD = "BG@Design2026"

def _password_gate() -> bool:
    if st.session_state.get("og_authenticated"):
        return True
    st.title("🔒 Offer Generator — Restricted")
    st.caption("Enter team password to access the B&G offer generator.")
    pwd = st.text_input("Password", type="password", key="og_pwd_input")
    if st.button("Unlock", type="primary", key="11_Offer_Generator_button_1"):
        if pwd == _TEAM_PASSWORD:
            st.session_state.og_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


if not _password_gate():
    st.stop()


# ---------------------------------------------------------------------
# CONNECTION + MODULE IMPORTS (after auth)
# ---------------------------------------------------------------------
conn = st.connection("supabase", type=SupabaseConnection)

from bg_offer_generator.utils.brand import BRAND, COMPANY, OFFER_TOC
from bg_offer_generator.utils.default_data import default_offer_data
from bg_offer_generator.utils.form_template import generate_form_template_xlsx
from bg_offer_generator.utils.bridge import (
    parse_process_design_json, bridge_to_offer_data, summarize_bridge_result,
)
from bg_offer_generator.utils.assets import load_brand_assets
from bg_offer_generator.modules.docx_generator import generate_offer_docx


# ---------------------------------------------------------------------
# ECONOMICS CALCULATION HELPERS
# ---------------------------------------------------------------------
def _recalc_economics(econ: dict, technical_specs: dict = None,
                      utilities: dict = None, capacity_kld: float = None) -> dict:
    """
    Recalculate annual tonnage, cost, savings, plant-wide totals, and
    annual operational cost from raw inputs.

    User-entered keys:
        operating_hours_day, operating_days_year
        steam_cost_inr_kg, power_cost_inr_kwh, cooling_water_cost_inr_m3
        effluent_treatment_cost_inr_kl
        conventional_steam_kgh, ecox_steam_kgh

    Computed keys:
        conventional_annual_steam_tons, conventional_annual_cost_cr
        ecox_annual_steam_tons, ecox_annual_cost_cr
        steam_reduction_pct, annual_steam_savings_tons, annual_savings_lakhs
        annual_operational_cost_inr

    If technical_specs / utilities / capacity_kld passed, also computes
    plant-wide totals (total_steam_kgh, etc.) by summing per-unit values.
    """
    hours = float(econ.get("operating_hours_day", 20) or 0)
    days  = float(econ.get("operating_days_year", 300) or 0)
    steam_cost = float(econ.get("steam_cost_inr_kg", 2.0) or 0)

    # ----- Steam comparison (Conventional vs ECOX) -----
    conv_kgh = float(econ.get("conventional_steam_kgh", 0) or 0)
    ecox_kgh = float(econ.get("ecox_steam_kgh", 0) or 0)

    conv_annual_t = (conv_kgh * hours * days) / 1000.0
    ecox_annual_t = (ecox_kgh * hours * days) / 1000.0
    conv_cost_cr  = (conv_annual_t * steam_cost) / 10000.0
    ecox_cost_cr  = (ecox_annual_t * steam_cost) / 10000.0
    reduction_pct = ((conv_kgh - ecox_kgh) / conv_kgh * 100.0) if conv_kgh > 0 else 0.0
    savings_tons  = conv_annual_t - ecox_annual_t
    savings_lakhs = (conv_cost_cr - ecox_cost_cr) * 100.0  # 1 Cr = 100 Lakhs

    econ["conventional_annual_steam_tons"] = round(conv_annual_t, 2)
    econ["conventional_annual_cost_cr"]    = round(conv_cost_cr, 4)
    econ["ecox_annual_steam_tons"]         = round(ecox_annual_t, 2)
    econ["ecox_annual_cost_cr"]            = round(ecox_cost_cr, 4)
    econ["steam_reduction_pct"]            = round(reduction_pct, 2)
    econ["annual_steam_savings_tons"]      = round(savings_tons, 2)
    econ["annual_savings_lakhs"]           = round(savings_lakhs, 2)

    # ----- Annual operational cost (₹/year) -----
    # = effluent_cost (₹/KL) × capacity (KLD) × days_per_year
    effluent_cost = float(econ.get("effluent_treatment_cost_inr_kl", 0) or 0)
    cap = float(capacity_kld or 0)
    econ["annual_operational_cost_inr"] = round(effluent_cost * cap * days)

    # ----- Plant-wide utility totals (sum of per-unit) -----
    if technical_specs and utilities is not None:
        def _f(v):
            try: return float(v)
            except (TypeError, ValueError): return 0.0

        units = ["stripper", "mee", "atfd"]
        total_steam = sum(_f(technical_specs.get(u, {}).get("steam_kgh", 0)) for u in units)
        total_power = sum(_f(technical_specs.get(u, {}).get("power_kwh", 0)) for u in units)
        total_cw_m3 = sum(_f(technical_specs.get(u, {}).get("cooling_water_m3h", 0)) for u in units)
        total_cw_tr = sum(_f(technical_specs.get(u, {}).get("cooling_water_tr", 0)) for u in units)

        utilities["total_steam_kgh"]         = round(total_steam)
        utilities["total_power_kwh"]         = round(total_power)
        utilities["total_cooling_water_m3h"] = round(total_cw_m3)
        utilities["total_cooling_water_tr"]  = round(total_cw_tr)

        # Keep legacy keys aligned (used by docx_generator's utilities table)
        utilities["power_consumption_kwh"] = round(total_power)
        utilities["cooling_water_m3h"]     = round(total_cw_m3)

    return econ


# ---------------------------------------------------------------------
# CLIENT + PROJECT PICKERS
# ---------------------------------------------------------------------
def _get_raw_client():
    return conn.client if hasattr(conn, "client") else conn


@st.cache_data(ttl=300)
def _load_clients():
    try:
        res = _get_raw_client().table("customer_master").select(
            "id, name, address, contact, email"
        ).order("name").execute()
        return res.data or []
    except Exception:
        return []


@st.cache_data(ttl=300)
def _load_pd_projects():
    try:
        res = _get_raw_client().table("pd_projects").select(
            "id, project_code, project_name, client_id, capacity_kld"
        ).order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def _insert_new_client(name: str, address: str, contact: str, email: str):
    try:
        payload = {
            "name": name.strip(),
            "address": (address or "").strip() or None,
            "contact": (contact or "").strip() or None,
            "email":   (email or "").strip() or None,
        }
        res = _get_raw_client().table("customer_master").insert(payload).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        st.error(f"Failed to add client: {e}")
    return None


def _save_offer_to_db(data: dict, pd_project_id=None) -> int:
    try:
        cov = data["cover"]
        pr = data["pricing"]
        payload = {
            "quote_ref": cov["quote_ref"],
            "client_id": data.get("_client_id"),
            "pd_project_id": pd_project_id,
            "quote_date": cov["quote_date"],
            "capacity_kld": cov["capacity_kld"],
            "prepared_by": cov["prepared_by"],
            "offer_data": data,
            "option1_total_cr": pr["option1_total_cr"],
            "option2_total_cr": pr["option2_total_cr"],
            "price_validity_days": pr["price_validity_days"],
        }
        res = _get_raw_client().table("offers").insert(payload).execute()
        if res.data:
            return res.data[0]["id"]
    except Exception as e:
        st.error(f"Failed to save offer to DB: {e}")
    return None


# ---------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------
if "og_offer_data" not in st.session_state:
    st.session_state.og_offer_data = default_offer_data()


# ---------------------------------------------------------------------
# BRANDED HEADER
# ---------------------------------------------------------------------
st.markdown(f"""
<style>
    .og-header {{
        background: linear-gradient(135deg, {BRAND['primary_red']} 0%, {BRAND['accent_pink']} 100%);
        padding: 18px 28px;
        border-radius: 8px;
        margin-bottom: 18px;
    }}
    .og-header h1 {{ color: white !important; margin: 0; font-size: 26px; }}
    .og-header p {{ color: rgba(255,255,255,0.9) !important; margin: 4px 0 0 0; font-size: 13px; }}
</style>
<div class="og-header">
    <h1>📄 B&G Offer Generator</h1>
    <p>Techno-Commercial Offer · B&G ECOX-ZLD System · Responsible towards water</p>
</div>
""", unsafe_allow_html=True)

c_logout = st.columns([6, 1])[1]
if c_logout.button("🚪 Logout"):
    st.session_state.og_authenticated = False
    st.rerun()


# ---------------------------------------------------------------------
# TABS
# ---------------------------------------------------------------------
tabs = st.tabs([
    "① Cover & Client",
    "② Executive Summary",
    "③ Process Description",
    "④ Economics / OPEX",
    "⑤ Technical",
    "⑥ Scope of Supply",
    "⑦ Scope Matrix",
    "⑧ Pricing & Terms",
    "🚀 Generate",
    "📥 Import / Bridge",
])

d = st.session_state.og_offer_data


# ---------- Tab 1: Cover & Client ----------
with tabs[0]:
    st.subheader("Cover Page & Client Details")
    cov = d["cover"]

    clients = _load_clients()
    if clients:
        names = ["— select client —"] + [f"{c['name']} (id={c['id']})" for c in clients]
        default_idx = 0
        new_id = st.session_state.pop("og_new_client_id", None)
        if new_id is not None:
            for i, c in enumerate(clients):
                if c["id"] == new_id:
                    default_idx = i + 1
                    break

        sel = st.selectbox("Client", names, index=default_idx, key="og_client_sel")
        if sel != "— select client —":
            chosen = clients[names.index(sel) - 1]
            d["_client_id"] = chosen["id"]
            cov["submitted_to"] = f"M/s. {chosen['name']}"
            if chosen.get("address") and not cov.get("location"):
                cov["location"] = chosen["address"]
            if chosen.get("contact") and not cov.get("contact_details"):
                cov["contact_details"] = chosen["contact"]
            if chosen.get("email") and not cov.get("email"):
                cov["email"] = chosen["email"]
    else:
        st.info("No clients in customer_master yet. Add one below.")

    with st.expander("➕ Add new client", expanded=not clients):
        with st.form("og_new_client_form", clear_on_submit=True):
            nc_name = st.text_input("Client Name *", key="og_nc_name")
            nc_address = st.text_area("Address", key="og_nc_address", height=80)
            c1, c2 = st.columns(2)
            nc_contact = c1.text_input("Contact (phone)", key="og_nc_contact")
            nc_email = c2.text_input("Email", key="og_nc_email")
            submitted = st.form_submit_button("💾 Save client", type="primary")
            if submitted:
                if not nc_name.strip():
                    st.error("Client Name is required.")
                else:
                    new_row = _insert_new_client(nc_name, nc_address, nc_contact, nc_email)
                    if new_row:
                        st.cache_data.clear()
                        st.session_state.og_new_client_id = new_row["id"]
                        st.success(f"✅ Added '{new_row['name']}' (id={new_row['id']})")
                        st.rerun()

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        cov["quote_ref"] = st.text_input("Quote Reference", value=cov["quote_ref"], key="11_Offer_Generator_text_input_2")
        cov["quote_date"] = st.text_input("Quote Date (YYYY-MM-DD)", value=str(cov["quote_date"]), key="11_Offer_Generator_text_input_3")
        cov["submitted_to"] = st.text_input("Submitted to", value=cov["submitted_to"], key="11_Offer_Generator_text_input_4")
        cov["location"] = st.text_input("Location", value=cov["location"], key="11_Offer_Generator_text_input_5")
        cov["capacity_kld"] = st.number_input("Capacity (KLD)", value=int(cov["capacity_kld"]), min_value=1, max_value=5000, step=10, key="11_Offer_Generator_number_input_6")
    with c2:
        cov["prepared_by"] = st.text_input("Prepared By", value=cov["prepared_by"], key="11_Offer_Generator_text_input_7")
        cov["contact_details"] = st.text_input("Contact", value=cov["contact_details"], key="11_Offer_Generator_text_input_8")
        cov["email"] = st.text_input("E-mail", value=cov["email"], key="11_Offer_Generator_text_input_9")
        cov["kind_attn"] = st.text_input("Kind Attention", value=cov["kind_attn"], key="11_Offer_Generator_text_input_10")
        cov["discussion_date"] = st.text_input("Discussion Date", value=cov["discussion_date"], key="11_Offer_Generator_text_input_11")

    cov["subject"] = st.text_input("Subject Line", value=cov["subject"], key="11_Offer_Generator_text_input_12")


# ---------- Tab 2: Executive Summary ----------
with tabs[1]:
    st.subheader("PART I — Executive Summary")
    d["executive_summary"] = st.text_area("Editable text", value=d["executive_summary"], height=400, key="11_Offer_Generator_text_area_13")


# ---------- Tab 3: Process Description ----------
with tabs[2]:
    st.subheader("PART II — Process Description")
    pd_data = d["process_description"]
    pd_data["n_effects"] = st.slider("MEE Effects", 2, 7, value=int(pd_data.get("n_effects", 4)), key="11_Offer_Generator_slider_14")
    with st.expander("Stripper", expanded=True):
        pd_data["stripper"] = st.text_area("", value=pd_data["stripper"], height=200, key="og_pd_strip")
    with st.expander("MEE"):
        pd_data["mee"] = st.text_area("use {n_effects}", value=pd_data["mee"], height=300, key="og_pd_mee")
    with st.expander("ATFD"):
        pd_data["atfd"] = st.text_area("", value=pd_data["atfd"], height=300, key="og_pd_atfd")


# ---------- Tab 4: Economics / OPEX ----------
with tabs[3]:
    st.subheader("PART IV — Economics / OPEX")
    econ = d["economics"]

    # Backfill defaults for older offer_data dicts
    econ.setdefault("operating_hours_day", 20)
    econ.setdefault("operating_days_year", 300)
    econ.setdefault("steam_cost_inr_kg", 2.0)
    econ.setdefault("power_cost_inr_kwh", 9.0)
    econ.setdefault("cooling_water_cost_inr_m3", 90.0)
    econ.setdefault("effluent_treatment_cost_inr_kl", 1185.0)
    econ.setdefault("conventional_steam_kgh", 0)
    econ.setdefault("ecox_steam_kgh", 0)

    # ----- Overall Parameters -----
    st.markdown("### Overall Parameters")
    op1, op2, op3 = st.columns(3)
    with op1:
        econ["operating_hours_day"] = st.number_input(
            "Operating Hours per Day (h)",
            value=float(econ["operating_hours_day"]),
            min_value=1.0, max_value=24.0, step=1.0,
            key="og_e_ophrs",
        )
    with op2:
        econ["operating_days_year"] = st.number_input(
            "Days of Operation per Year",
            value=int(econ["operating_days_year"]),
            min_value=1, max_value=365, step=1,
            key="og_e_days",
        )
    with op3:
        econ["effluent_treatment_cost_inr_kl"] = st.number_input(
            "Effluent Treatment Cost (₹/KL)",
            value=float(econ["effluent_treatment_cost_inr_kl"]),
            min_value=0.0, step=10.0, format="%.2f",
            key="og_e_eff_cost",
        )

    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        econ["steam_cost_inr_kg"] = st.number_input(
            "Steam Cost (₹/kg)",
            value=float(econ["steam_cost_inr_kg"]),
            min_value=0.0, step=0.1, format="%.2f",
            key="og_e_steam_rate",
        )
    with cc2:
        econ["power_cost_inr_kwh"] = st.number_input(
            "Power Cost (₹/kWh)",
            value=float(econ["power_cost_inr_kwh"]),
            min_value=0.0, step=0.5, format="%.2f",
            key="og_e_pwr_rate",
        )
    with cc3:
        econ["cooling_water_cost_inr_m3"] = st.number_input(
            "Cooling Water Cost (₹/m³)",
            value=float(econ["cooling_water_cost_inr_m3"]),
            min_value=0.0, step=1.0, format="%.2f",
            key="og_e_cw_rate",
        )

    st.divider()

    # ----- Steam Comparison (Conventional vs ECOX) -----
    st.markdown("### Steam Comparison — BG ECOX-ZLD Advantage")
    st.caption("Enter MEE steam consumption for conventional and ECOX-ZLD systems. Annual usage, cost, and savings are calculated automatically.")
    si1, si2 = st.columns(2)
    with si1:
        econ["conventional_steam_kgh"] = st.number_input(
            "Conventional — MEE Steam (kg/h)",
            value=float(econ.get("conventional_steam_kgh", 0) or 0),
            min_value=0.0, step=10.0,
            key="og_e_conv_kgh",
        )
    with si2:
        econ["ecox_steam_kgh"] = st.number_input(
            "ECOX-ZLD — MEE Steam (kg/h)",
            value=float(econ.get("ecox_steam_kgh", 0) or 0),
            min_value=0.0, step=10.0,
            key="og_e_ecox_kgh",
        )

    # Live recalculation (also fills plant-wide totals from per-unit specs)
    _recalc_economics(econ, technical_specs=d.get("technical_specs"),
                      utilities=d.get("utilities"),
                      capacity_kld=d["cover"].get("capacity_kld"))

    st.divider()
    st.markdown("### Calculated Results — Steam Advantage")
    res_c1, res_c2, res_c3 = st.columns(3)
    with res_c1:
        st.markdown("**Conventional**")
        st.metric("Annual Steam (t/yr)", f"{econ['conventional_annual_steam_tons']:,.2f}")
        st.metric("Annual Cost (Cr/yr)", f"₹{econ['conventional_annual_cost_cr']:.4f}")
    with res_c2:
        st.markdown("**ECOX-ZLD**")
        st.metric("Annual Steam (t/yr)", f"{econ['ecox_annual_steam_tons']:,.2f}")
        st.metric("Annual Cost (Cr/yr)", f"₹{econ['ecox_annual_cost_cr']:.4f}")
    with res_c3:
        st.markdown("**Savings**")
        st.metric("Steam Reduction (%)", f"{econ['steam_reduction_pct']:.2f}%")
        st.metric("Steam Savings (t/yr)", f"{econ['annual_steam_savings_tons']:,.2f}")
        st.metric("Cost Savings (Lakhs/yr)", f"₹{econ['annual_savings_lakhs']:.2f}")

    st.divider()
    st.markdown("### Overall System Operational Cost")
    ut = d.get("utilities", {})
    cap = d["cover"].get("capacity_kld", 0)
    osc1, osc2, osc3, osc4 = st.columns(4)
    osc1.metric("Plant Capacity", f"{cap} KLD")
    osc2.metric("Total Steam", f"{ut.get('total_steam_kgh', 0)} kg/h")
    osc3.metric("Total Power", f"{ut.get('total_power_kwh', 0)} kWh")
    osc4.metric("Total CW",
                f"{ut.get('total_cooling_water_m3h', 0)} m³/h",
                f"{ut.get('total_cooling_water_tr', 0)} TR")
    osc5, osc6 = st.columns(2)
    osc5.metric("Effluent Treatment Cost",
                f"₹{econ['effluent_treatment_cost_inr_kl']:,.0f}/KL")
    osc6.metric("Annual Operational Cost",
                f"₹{econ['annual_operational_cost_inr']:,.0f}/yr")

    with st.expander("ℹ️ Formula reference", expanded=False):
        st.markdown("""
**Steam comparison:**
- Annual (t/yr) = (Steam kg/h × Operating hours × Days per year) ÷ 1000
- Cost (Cr/yr) = (Annual t/yr × Steam Cost ₹/kg) ÷ 10,000
- Reduction % = ((Conv. steam − ECOX steam) ÷ Conv. steam) × 100
- Savings (t/yr) = Conv. annual − ECOX annual
- Savings (Lakhs/yr) = (Conv. cost Cr − ECOX cost Cr) × 100

**Plant-wide totals** are summed from per-unit values in Tab ⑤ Technical.

**Annual Operational Cost (₹/yr)** = Effluent Treatment Cost (₹/KL) × Capacity (KLD) × Days/year
""")


# ---------- Tab 5: Technical ----------
with tabs[4]:
    st.subheader("PART V — Technical Details & Utilities")

    # Backfill defaults for older offer_data
    fp = d["feed_parameters"]
    fp.setdefault("specific_gravity", "1.0")

    ts = d["technical_specs"]
    for u in ("stripper", "mee", "atfd"):
        ts.setdefault(u, {})
        unit_defaults = {
            "steam_kgh": 0, "steam_pressure": "1.5 Bar-g",
            "power_kwh": 0,
            "cooling_water_m3h": 0, "cooling_water_tr": 0,
            "cooling_water_temps": "In/Out: 32 / 38 °C",
            "compressed_air_nm3h": "8", "compressed_air_pressure": "6 Bar-g",
        }
        for k, v in unit_defaults.items():
            ts[u].setdefault(k, v)
    ts["stripper"].setdefault("reflux_kgh", 0)
    ts["mee"].setdefault("steam_economy", 4.3)

    # ---------- Feed Parameters ----------
    with st.expander("📋 Feed Parameters", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            fp["capacity_kld"] = st.number_input("Feed / Capacity (KLD)",
                value=int(fp["capacity_kld"]), min_value=1, max_value=5000, step=10, key="t_cap")
            fp["feed_ph"] = st.text_input("Feed pH", value=str(fp["feed_ph"]), key="t_ph")
            fp["specific_gravity"] = st.text_input("Specific Gravity",
                value=str(fp.get("specific_gravity", "1.0")), key="t_sg")
            fp["total_cod_ppm"] = st.number_input("Total COD (PPM)",
                value=int(fp["total_cod_ppm"]), step=1000, key="t_cod")
            fp["volatile_organic_solvents_ppm"] = st.number_input(
                "Volatile Organic Solvents (PPM)",
                value=int(fp.get("volatile_organic_solvents_ppm", 0)),
                step=1000, key="t_vos")
            fp["total_solids_pct"] = st.text_input(
                "Total Solids (% w/w)",
                value=str(fp["total_solids_pct"]), key="t_ts")
        with c2:
            fp["suspended_solids_ppm"] = st.text_input("Suspended Solids (PPM)",
                value=str(fp.get("suspended_solids_ppm", "")), key="t_ss")
            fp["feed_temp_c"] = st.number_input("Feed Temperature (°C)",
                value=int(fp["feed_temp_c"]), key="t_T")
            fp["total_hardness_ppm"] = st.text_input("Total Hardness (PPM)",
                value=str(fp.get("total_hardness_ppm", "")), key="t_th")
            fp["silica_ppm"] = st.text_input("Silica (PPM)",
                value=str(fp.get("silica_ppm", "")), key="t_si")
            fp["free_chloride_ppm"] = st.text_input("Free Chloride (PPM)",
                value=str(fp.get("free_chloride_ppm", "")), key="t_cl")
            fp["feed_nature"] = st.text_input("Feed Nature",
                value=fp["feed_nature"], key="t_nat")

    # ---------- Stripper System ----------
    with st.expander("⚙️ Stripper System", expanded=True):
        s = ts["stripper"]
        s["type"] = st.text_input("Type", value=s.get("type", "Tray Type Column"), key="ts_s_type")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Process Flows**")
            s["feed_kgh"] = st.number_input("Inlet Feed Rate (kg/h)",
                value=int(s.get("feed_kgh", 0)), step=10, key="ts_s_feed")
            s["distillate_kgh"] = st.number_input("Top Distillate Out (kg/h)",
                value=int(s.get("distillate_kgh", 0)), step=10, key="ts_s_dist")
            s["distillate_composition"] = st.text_input("Distillate Composition",
                value=s.get("distillate_composition", ""), key="ts_s_dc")
            s["bottoms_kgh"] = st.number_input("Stripper Bottom Out (kg/h)",
                value=int(s.get("bottoms_kgh", 0)), step=10, key="ts_s_bot")
            s["reflux_kgh"] = st.number_input("Reflux Rate (kg/h)",
                value=int(s.get("reflux_kgh", 0)), step=10, key="ts_s_ref")
        with c2:
            st.markdown("**Utilities**")
            s["steam_pressure"] = st.text_input("Steam Pressure", value=s.get("steam_pressure", "1.5 Bar-g"), key="ts_s_sp")
            s["steam_kgh"] = st.number_input("Dry & Saturated Steam (kg/h)",
                value=int(s.get("steam_kgh", 0)), step=10, key="ts_s_st")
            s["power_kwh"] = st.number_input("Power Consumption (kWh)",
                value=int(s.get("power_kwh", 0)), step=1, key="ts_s_pw")
            cc1, cc2 = st.columns(2)
            s["cooling_water_m3h"] = cc1.number_input("Cooling Water (m³/h)",
                value=int(s.get("cooling_water_m3h", 0)), step=5, key="ts_s_cw")
            s["cooling_water_tr"] = cc2.number_input("Cooling Water (TR)",
                value=int(s.get("cooling_water_tr", 0)), step=10, key="ts_s_cw_tr")
            s["cooling_water_temps"] = st.text_input("Cooling Water Temps",
                value=s.get("cooling_water_temps", "In/Out: 32 / 38 °C"), key="ts_s_cwt")
            cc3, cc4 = st.columns(2)
            s["compressed_air_nm3h"] = cc3.text_input("Compressed Air (Nm³/h)",
                value=str(s.get("compressed_air_nm3h", "8")), key="ts_s_ca")
            s["compressed_air_pressure"] = cc4.text_input("CA Pressure",
                value=s.get("compressed_air_pressure", "6 Bar-g"), key="ts_s_cap")

    # ---------- MEE System ----------
    with st.expander("⚙️ Multiple Effect Evaporator System", expanded=True):
        m = ts["mee"]
        c0a, c0b = st.columns(2)
        m["type"] = c0a.text_input("Type", value=m.get("type", "4-Effect Multiple Effect Evaporator"), key="ts_m_type")
        m["configuration"] = c0b.text_input("Configuration",
            value=m.get("configuration", "Forced Circulation Type"), key="ts_m_cfg")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Process Flows**")
            m["feed_kgh"] = st.number_input("Feed Inlet — Stripper Bottom (kg/h)",
                value=int(m.get("feed_kgh", 0)), step=10, key="ts_m_feed")
            m["feed_solids_pct"] = st.text_input("Feed Solids (%)",
                value=str(m.get("feed_solids_pct", "")), key="ts_m_fs")
            m["evaporation_kgh"] = st.number_input("Water Evaporation Rate (kg/h)",
                value=int(m.get("evaporation_kgh", 0)), step=10, key="ts_m_evap")
            m["concentrate_kgh"] = st.number_input("MEE Concentrate Out (kg/h)",
                value=int(m.get("concentrate_kgh", 0)), step=10, key="ts_m_conc")
            m["concentrate_solids_pct"] = st.number_input("Concentrate Out (%)",
                value=int(m.get("concentrate_solids_pct", 40)), min_value=0, max_value=100, key="ts_m_cs")
        with c2:
            st.markdown("**Utilities**")
            m["steam_pressure"] = st.text_input("Steam Pressure", value=m.get("steam_pressure", "1.5 Bar-g"), key="ts_m_sp")
            m["steam_kgh"] = st.number_input("Dry & Saturated Steam (kg/h)",
                value=int(m.get("steam_kgh", 0)), step=10, key="ts_m_st")
            m["steam_economy"] = st.number_input("Steam Economy (kg/kg)",
                value=float(m.get("steam_economy", 4.3)), min_value=0.0, step=0.1, format="%.2f", key="ts_m_se")
            m["power_kwh"] = st.number_input("Power Consumption (kWh)",
                value=int(m.get("power_kwh", 0)), step=1, key="ts_m_pw")
            cc1, cc2 = st.columns(2)
            m["cooling_water_m3h"] = cc1.number_input("Cooling Water (m³/h)",
                value=int(m.get("cooling_water_m3h", 0)), step=5, key="ts_m_cw")
            m["cooling_water_tr"] = cc2.number_input("Cooling Water (TR)",
                value=int(m.get("cooling_water_tr", 0)), step=10, key="ts_m_cw_tr")
            m["cooling_water_temps"] = st.text_input("Cooling Water Temps",
                value=m.get("cooling_water_temps", "In/Out: 32 / 38 °C"), key="ts_m_cwt")
            cc3, cc4 = st.columns(2)
            m["compressed_air_nm3h"] = cc3.text_input("Compressed Air (Nm³/h)",
                value=str(m.get("compressed_air_nm3h", "8-10")), key="ts_m_ca")
            m["compressed_air_pressure"] = cc4.text_input("CA Pressure",
                value=m.get("compressed_air_pressure", "6 Bar-g"), key="ts_m_cap")

    # ---------- ATFD ----------
    with st.expander("⚙️ Agitated Thin Film Dryer (ATFD)", expanded=True):
        a = ts["atfd"]
        a["type"] = st.text_input("Type", value=a.get("type", "Agitated Thin Film Dryer"), key="ts_a_type")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Process Flows**")
            a["feed_kgh"] = st.number_input("Feed Inlet — MEE Concentrate (kg/h)",
                value=int(a.get("feed_kgh", 0)), step=10, key="ts_a_feed")
            a["feed_solids_pct"] = st.number_input("Feed Solids (%)",
                value=int(a.get("feed_solids_pct", 40)), min_value=0, max_value=100, key="ts_a_fs")
            a["evaporation_kgh"] = st.number_input("Water Evaporation Rate (kg/h)",
                value=int(a.get("evaporation_kgh", 0)), step=10, key="ts_a_evap")
            a["product_kgh"] = st.number_input("ATFD Product Out (kg/h)",
                value=int(a.get("product_kgh", 0)), step=10, key="ts_a_prod")
            a["product_moisture_pct"] = st.text_input("Moisture in ATFD Product (%)",
                value=str(a.get("product_moisture_pct", "8-10")), key="ts_a_pm")
        with c2:
            st.markdown("**Utilities**")
            a["steam_pressure"] = st.text_input("Steam Pressure", value=a.get("steam_pressure", "1.5 Bar-g"), key="ts_a_sp")
            a["steam_kgh"] = st.number_input("Dry & Saturated Steam (kg/h)",
                value=int(a.get("steam_kgh", 0)), step=10, key="ts_a_st")
            a["power_kwh"] = st.number_input("Power Consumption (kWh)",
                value=int(a.get("power_kwh", 0)), step=1, key="ts_a_pw")
            cc1, cc2 = st.columns(2)
            a["cooling_water_m3h"] = cc1.number_input("Cooling Water (m³/h)",
                value=int(a.get("cooling_water_m3h", 0)), step=5, key="ts_a_cw")
            a["cooling_water_tr"] = cc2.number_input("Cooling Water (TR)",
                value=int(a.get("cooling_water_tr", 0)), step=10, key="ts_a_cw_tr")
            a["cooling_water_temps"] = st.text_input("Cooling Water Temps",
                value=a.get("cooling_water_temps", "In/Out: 32 / 38 °C"), key="ts_a_cwt")
            cc3, cc4 = st.columns(2)
            a["compressed_air_nm3h"] = cc3.text_input("Compressed Air (Nm³/h)",
                value=str(a.get("compressed_air_nm3h", "8")), key="ts_a_ca")
            a["compressed_air_pressure"] = cc4.text_input("CA Pressure",
                value=a.get("compressed_air_pressure", "6 Bar-g"), key="ts_a_cap")

    # Mirror per-unit steam values into the legacy `utilities` block so the
    # existing DOCX generator (which reads from utilities.{stripper,mee,atfd}_steam)
    # continues to render the correct numbers.
    ut = d["utilities"]
    ut["stripper_steam"] = {
        "param": f"{ts['stripper']['steam_pressure']}, >96% dryness",
        "value_kgh": ts["stripper"]["steam_kgh"],
    }
    ut["mee_steam"] = {
        "param": f"{ts['mee']['steam_pressure']}, >96% dryness",
        "value_kgh": ts["mee"]["steam_kgh"],
        "steam_economy": ts["mee"]["steam_economy"],
    }
    ut["atfd_steam"] = {
        "param": f"{ts['atfd']['steam_pressure']}, >96% dryness",
        "value_kgh": ts["atfd"]["steam_kgh"],
    }

    # Recompute totals + economics in case the user changed per-unit values
    _recalc_economics(d["economics"], technical_specs=ts, utilities=ut,
                      capacity_kld=d["cover"].get("capacity_kld"))

    # ---------- Plant-Wide Totals (read-only display) ----------
    st.divider()
    st.markdown("### Plant-Wide Totals (computed from per-unit values above)")
    tc1, tc2, tc3 = st.columns(3)
    tc1.metric("Total Steam Consumption", f"{ut['total_steam_kgh']} kg/h",
               help="Stripper + MEE + ATFD")
    tc2.metric("Total Power Consumption", f"{ut['total_power_kwh']} kWh",
               help="Sum of per-unit power")
    tc3.metric("Total Cooling Water",
               f"{ut['total_cooling_water_m3h']} m³/h",
               f"{ut['total_cooling_water_tr']} TR")

    # ---------- Performance Guarantee ----------
    with st.expander("🎯 Performance Guarantee (bullet points)", expanded=False):
        txt = "\n".join(d.get("performance_guarantee", []))
        new_pg = st.text_area("One bullet per line", value=txt, height=120, key="og_pg")
        d["performance_guarantee"] = [l.strip() for l in new_pg.split("\n") if l.strip()]


# ---------- Tab 6: Scope of Supply ----------
with tabs[5]:
    import pandas as pd
    st.subheader("PART VI — Scope of Supply")
    sub = st.tabs(["Stripper", "MEE", "ATFD", "Instruments"])
    with sub[0]:
        df = pd.DataFrame(d["scope_stripper"])
        d["scope_stripper"] = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="og_sc_s").to_dict("records")
    with sub[1]:
        df = pd.DataFrame(d["scope_mee"])
        d["scope_mee"] = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="og_sc_m").to_dict("records")
    with sub[2]:
        df = pd.DataFrame(d["scope_atfd"])
        d["scope_atfd"] = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="og_sc_a").to_dict("records")
    with sub[3]:
        df = pd.DataFrame(d["instruments"])
        d["instruments"] = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="og_sc_i").to_dict("records")


# ---------- Tab 7: Scope Matrix ----------
with tabs[6]:
    import pandas as pd
    st.subheader("PART VII & VIII")
    with st.expander("Battery Limits", expanded=True):
        txt = "\n".join(d["battery_limits"])
        new = st.text_area("One item per line", value=txt, height=300, key="og_bl")
        d["battery_limits"] = [l.strip() for l in new.split("\n") if l.strip()]
    with st.expander("Scope Matrix", expanded=True):
        df = pd.DataFrame(d["scope_matrix"])
        d["scope_matrix"] = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="og_sm").to_dict("records")


# ---------- Tab 8: Pricing ----------
with tabs[7]:
    st.subheader("PART X — Price & Terms")
    pr = d["pricing"]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Option 1**")
        pr["option1_moc"] = st.text_input("MOC", value=pr["option1_moc"], key="og_p1m")
        pr["option1_equipment_price_cr"] = st.number_input("Equipment Cr", value=float(pr["option1_equipment_price_cr"]), step=0.01, key="og_p1e")
        pr["option1_install_lakhs"] = st.number_input("Install Lakhs", value=float(pr["option1_install_lakhs"]), step=1.0, key="og_p1i")
        pr["option1_total_cr"] = st.number_input("Total Cr", value=float(pr["option1_total_cr"]), step=0.01, key="og_p1t")
    with c2:
        st.markdown("**Option 2**")
        pr["option2_moc"] = st.text_input("MOC", value=pr["option2_moc"], key="og_p2m")
        pr["option2_equipment_price_cr"] = st.number_input("Equipment Cr", value=float(pr["option2_equipment_price_cr"]), step=0.01, key="og_p2e")
        pr["option2_install_lakhs"] = st.number_input("Install Lakhs", value=float(pr["option2_install_lakhs"]), step=1.0, key="og_p2i")
        pr["option2_total_cr"] = st.number_input("Total Cr", value=float(pr["option2_total_cr"]), step=0.01, key="og_p2t")

    c1, c2 = st.columns(2)
    pr["location_dap"] = c1.text_input("Location DAP", value=pr["location_dap"], key="og_ploc")
    pr["price_validity_days"] = c2.number_input("Validity Days", value=int(pr["price_validity_days"]), min_value=1, max_value=365, key="og_pval")

    st.markdown("**Payment Terms**")
    txt = "\n".join(pr["payment_terms"])
    new = st.text_area("One per line", value=txt, height=180, key="og_pt")
    pr["payment_terms"] = [l.strip() for l in new.split("\n") if l.strip()]


# ---------- Tab 9: Generate ----------
with tabs[8]:
    st.subheader("🚀 Generate Offer DOCX")
    c1, c2, c3 = st.columns(3)
    c1.metric("Client", d["cover"]["submitted_to"])
    c2.metric("Capacity", f"{d['cover']['capacity_kld']} KLD")
    c3.metric("Total", f"₹{d['pricing']['option1_total_cr']:.2f} Cr")
    st.divider()

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        if st.button("🔨 Generate Offer DOCX", type="primary", use_container_width=True, key="11_Offer_Generator_button_15"):
            _recalc_economics(d["economics"],
                              technical_specs=d.get("technical_specs"),
                              utilities=d.get("utilities"),
                              capacity_kld=d["cover"].get("capacity_kld"))
            with st.spinner("Loading brand assets from Supabase..."):
                logo_bytes, tagline_bytes, hero_bytes = load_brand_assets()
            if logo_bytes:
                st.success("✅ Logo loaded from Supabase")
            else:
                st.info("Logo not found — DOCX will render text-only header")
            with st.spinner("Building DOCX..."):
                try:
                    docx_bytes = generate_offer_docx(
                        d,
                        logo_path=logo_bytes,
                        tagline_path=tagline_bytes,
                        hero_path=hero_bytes,
                    )
                    st.session_state.og_generated_docx = docx_bytes
                    st.success(f"✅ DOCX generated: {len(docx_bytes)/1024:.1f} KB")
                except Exception as e:
                    st.error(f"Generation failed: {e}")
                    import traceback
                    st.code(traceback.format_exc())

    with col2:
        if st.button("💾 Save to DB", use_container_width=True, key="11_Offer_Generator_button_16"):
            _recalc_economics(d["economics"],
                              technical_specs=d.get("technical_specs"),
                              utilities=d.get("utilities"),
                              capacity_kld=d["cover"].get("capacity_kld"))
            offer_id = _save_offer_to_db(d)
            if offer_id:
                st.success(f"Saved offer #{offer_id}")

    with col3:
        if st.button("🔄 Reset", use_container_width=True, key="11_Offer_Generator_button_17"):
            st.session_state.og_offer_data = default_offer_data()
            st.rerun()

    if "og_generated_docx" in st.session_state:
        st.download_button(
            label="📥 Download Offer DOCX",
            data=st.session_state.og_generated_docx,
            file_name=f"Quote_{d['cover']['quote_ref'].replace('/', '_')}_{d['cover']['capacity_kld']}KLD.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True, key="11_Offer_Generator_download_button_18")


# ---------- Tab 10: Import / Bridge ----------
with tabs[9]:
    st.subheader("📥 Templates & Process Design Bridge")

    with st.expander("📋 Excel Form Template (for offline data collection)", expanded=True):
        if st.button("Generate Excel Template", key="og_gen_xlsx"):
            st.session_state.og_xlsx = generate_form_template_xlsx()
        if "og_xlsx" in st.session_state:
            st.download_button(
                "📥 Download Template",
                st.session_state.og_xlsx,
                "BG_Offer_Form_Template.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="11_Offer_Generator_download_button_19")

    with st.expander("🔗 Import from bg_process_design Project", expanded=True):
        pd_projects = _load_pd_projects()
        if not pd_projects:
            st.info("No process design projects yet. Create one on the Process Design page first.")
        else:
            names = ["— select a project —"] + [f"{p['project_code']} · {p['project_name']} ({p.get('capacity_kld','?')} KLD)" for p in pd_projects]
            sel = st.selectbox("Linked Process Design Project", names, key="og_pd_sel")
            if sel != "— select a project —":
                chosen_proj = pd_projects[names.index(sel) - 1]
                if st.button("🔀 Import technical specs from this project", type="primary", key="og_bridge_btn"):
                    try:
                        from bg_process_design.utils.export_utils import build_full_project_export
                        process_json = build_full_project_export(conn, chosen_proj["id"])
                        new_data = bridge_to_offer_data(process_json, existing_data=d)
                        _recalc_economics(new_data["economics"],
                                          technical_specs=new_data.get("technical_specs"),
                                          utilities=new_data.get("utilities"),
                                          capacity_kld=new_data["cover"].get("capacity_kld"))
                        st.session_state.og_offer_data = new_data
                        st.session_state.og_linked_pd_id = chosen_proj["id"]
                        st.success("✅ Imported from process design project")
                        for line in summarize_bridge_result(process_json, new_data):
                            st.markdown(line)
                    except Exception as e:
                        st.error(f"Bridge failed: {e}")
                        import traceback
                        st.code(traceback.format_exc())

    with st.expander("📤 Upload full_project.json (alternative)", expanded=False):
        uploaded = st.file_uploader("Upload JSON export", type=["json"], key="og_json_up")
        if uploaded:
            try:
                content = uploaded.read().decode("utf-8")
                process_json = parse_process_design_json(content)
                if st.button("🔀 Import", key="og_up_btn"):
                    new_data = bridge_to_offer_data(process_json, existing_data=d)
                    _recalc_economics(new_data["economics"],
                                      technical_specs=new_data.get("technical_specs"),
                                      utilities=new_data.get("utilities"),
                                      capacity_kld=new_data["cover"].get("capacity_kld"))
                    st.session_state.og_offer_data = new_data
                    st.success("✅ Imported from JSON")
                    st.rerun()
            except Exception as e:
                st.error(f"Parse failed: {e}")
