"""
Page 11 — B&G Offer Generator

Generates branded techno-commercial offer DOCX documents.
Password-gated. Reads logo from Supabase storage bucket.
Optionally links to process design projects via pd_project_id.

Tables written to:
  offers           (offer_data stored as JSONB)
  customer_master  (when adding new clients inline)
"""
# Ensure repo root is on sys.path so sibling modules import correctly
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
def _recalc_economics(econ: dict) -> dict:
    """
    Recalculate annual tonnage, cost, and savings from raw inputs.

    Inputs (user-entered):
        operating_hours_day, operating_days_year, steam_cost_inr_kg
        conventional_steam_kgh, ecox_steam_kgh

    Outputs (computed, written back into the same dict):
        conventional_annual_steam_tons, conventional_annual_cost_cr
        ecox_annual_steam_tons,         ecox_annual_cost_cr
        steam_reduction_pct, annual_steam_savings_tons, annual_savings_lakhs

    Formulas:
        Annual (t/yr)      = (kg/h × h/day × days/yr) / 1000
        Cost (Cr/yr)       = (Annual t/yr × ₹/kg) / 10000
        Reduction %        = ((conv_kgh - ecox_kgh) / conv_kgh) × 100
        Savings (t/yr)     = conv_annual - ecox_annual
        Savings (Lakhs/yr) = (conv_cost_cr - ecox_cost_cr) × 100
    """
    hours = float(econ.get("operating_hours_day", 20) or 0)
    days  = float(econ.get("operating_days_year", 300) or 0)
    cost_per_kg = float(econ.get("steam_cost_inr_kg", 2.0) or 0)

    conv_kgh = float(econ.get("conventional_steam_kgh", 0) or 0)
    ecox_kgh = float(econ.get("ecox_steam_kgh", 0) or 0)

    conv_annual_t = (conv_kgh * hours * days) / 1000.0
    ecox_annual_t = (ecox_kgh * hours * days) / 1000.0

    conv_cost_cr = (conv_annual_t * cost_per_kg) / 10000.0
    ecox_cost_cr = (ecox_annual_t * cost_per_kg) / 10000.0

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
    """Insert new client into customer_master. Returns new row dict or None."""
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
    """Save offer to `offers` table, return new offer ID."""
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

# Top bar: logout
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

    # ----- Client picker from customer_master -----
    clients = _load_clients()
    if clients:
        names = ["— select client —"] + [f"{c['name']} (id={c['id']})" for c in clients]

        # If a freshly-added client should be auto-selected, prefer it
        default_idx = 0
        new_id = st.session_state.pop("og_new_client_id", None)
        if new_id is not None:
            for i, c in enumerate(clients):
                if c["id"] == new_id:
                    default_idx = i + 1  # +1 for the "— select —" placeholder
                    break

        sel = st.selectbox("Client", names, index=default_idx, key="og_client_sel")
        if sel != "— select client —":
            chosen = clients[names.index(sel) - 1]
            d["_client_id"] = chosen["id"]
            cov["submitted_to"] = f"M/s. {chosen['name']}"
            # Auto-populate contact fields from master (only if currently blank)
            if chosen.get("address") and not cov.get("location"):
                cov["location"] = chosen["address"]
            if chosen.get("contact") and not cov.get("contact_details"):
                cov["contact_details"] = chosen["contact"]
            if chosen.get("email") and not cov.get("email"):
                cov["email"] = chosen["email"]
    else:
        st.info("No clients in customer_master yet. Add one below.")

    # ----- Inline "Add new client" form -----
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
                        st.cache_data.clear()  # refresh client list
                        st.session_state.og_new_client_id = new_row["id"]
                        st.success(f"✅ Added '{new_row['name']}' (id={new_row['id']})")
                        st.rerun()

    st.divider()

    # ----- Existing cover fields -----
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

    # Backfill defaults for older offer_data dicts that may be missing keys
    econ.setdefault("operating_hours_day", 20)
    econ.setdefault("operating_days_year", 300)
    econ.setdefault("steam_cost_inr_kg", 2.0)
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
        econ["steam_cost_inr_kg"] = st.number_input(
            "Steam Cost (₹/kg)",
            value=float(econ["steam_cost_inr_kg"]),
            min_value=0.0, step=0.1, format="%.2f",
            key="og_e_rate",
        )

    st.divider()

    # ----- Steam Inputs -----
    st.markdown("### Steam Consumption (only Steam kg/h is user input)")
    si1, si2 = st.columns(2)
    with si1:
        econ["conventional_steam_kgh"] = st.number_input(
            "Conventional — Steam (kg/h)",
            value=float(econ.get("conventional_steam_kgh", 0) or 0),
            min_value=0.0, step=10.0,
            key="og_e_conv_kgh",
        )
    with si2:
        econ["ecox_steam_kgh"] = st.number_input(
            "ECOX-ZLD — Steam (kg/h)",
            value=float(econ.get("ecox_steam_kgh", 0) or 0),
            min_value=0.0, step=10.0,
            key="og_e_ecox_kgh",
        )

    # Live recalculation
    econ = _recalc_economics(econ)
    d["economics"] = econ  # write back

    st.divider()

    # ----- Computed Outputs (read-only metrics) -----
    st.markdown("### Calculated Results")
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

    with st.expander("ℹ️ Formula reference", expanded=False):
        st.markdown("""
- **Annual (t/yr)** = (Steam kg/h × Operating hours × Days per year) ÷ 1000
- **Cost (Cr/yr)** = (Annual t/yr × Steam Cost ₹/kg) ÷ 10,000
- **Reduction %** = ((Conv. steam − ECOX steam) ÷ Conv. steam) × 100
- **Savings (t/yr)** = Conv. annual − ECOX annual
- **Savings (Lakhs/yr)** = (Conv. cost Cr − ECOX cost Cr) × 100
""")


# ---------- Tab 5: Technical ----------
with tabs[4]:
    st.subheader("PART V — Technical Details & Utilities")
    with st.expander("Feed Parameters", expanded=True):
        fp = d["feed_parameters"]
        c1, c2 = st.columns(2)
        fp["capacity_kld"] = c1.number_input("Capacity KLD", value=int(fp["capacity_kld"]), key="t_cap")
        fp["feed_ph"] = c1.text_input("pH", value=str(fp["feed_ph"]), key="t_ph")
        fp["total_cod_ppm"] = c1.number_input("COD ppm", value=int(fp["total_cod_ppm"]), key="t_cod")
        fp["total_solids_pct"] = c2.number_input("TS %", value=float(fp["total_solids_pct"]), step=0.1, key="t_ts")
        fp["feed_temp_c"] = c2.number_input("Temp °C", value=int(fp["feed_temp_c"]), key="t_T")
        fp["feed_nature"] = c2.text_input("Nature", value=fp["feed_nature"], key="t_nat")


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
            d["economics"] = _recalc_economics(d["economics"])
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
            d["economics"] = _recalc_economics(d["economics"])
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
                        new_data["economics"] = _recalc_economics(new_data["economics"])
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
                    new_data["economics"] = _recalc_economics(new_data["economics"])
                    st.session_state.og_offer_data = new_data
                    st.success("✅ Imported from JSON")
                    st.rerun()
            except Exception as e:
                st.error(f"Parse failed: {e}")
