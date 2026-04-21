"""
Page 11 — B&G Offer Generator

Generates branded techno-commercial offer DOCX documents.
Password-gated. Reads logo from Supabase storage bucket.
Optionally links to process design projects via pd_project_id.

Tables written to:
  offers  (offer_data stored as JSONB)
"""
# Ensure repo root is on sys.path so sibling modules import correctly
import sys, os
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
# Ensure repo root is on sys.path so sibling modules import correctly
import sys, os
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
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
# CLIENT + PROJECT PICKERS (customer_master + pd_projects)
# ---------------------------------------------------------------------
def _get_raw_client():
    return conn.client if hasattr(conn, "client") else conn


@st.cache_data(ttl=300)
def _load_clients():
    try:
        res = _get_raw_client().table("customer_master").select("id, name").order("name").execute()
        return res.data or []
    except Exception:
        return []


@st.cache_data(ttl=300)
def _load_pd_projects():
    try:
        res = _get_raw_client().table("pd_projects").select("id, project_code, project_name, client_id, capacity_kld").order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


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

    # Client picker from customer_master
    clients = _load_clients()
    if clients:
        names = ["— select client —"] + [f"{c['name']} (id={c['id']})" for c in clients]
        sel = st.selectbox("Client", names, key="og_client_sel")
        if sel != "— select client —":
            chosen = clients[names.index(sel) - 1]
            d["_client_id"] = chosen["id"]
            cov["submitted_to"] = f"M/s. {chosen['name']}"
    else:
        st.warning("No clients in customer_master. Add via ERP first.")

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


# ---------- Tab 4: Economics ----------
with tabs[3]:
    st.subheader("PART IV — Economics / OPEX")
    econ = d["economics"]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Conventional**")
        econ["conventional_steam_kgh"] = st.number_input("Steam kg/h", value=int(econ["conventional_steam_kgh"]), key="e_c_s")
        econ["conventional_annual_steam_tons"] = st.number_input("Annual t/yr", value=int(econ["conventional_annual_steam_tons"]), key="e_c_a")
        econ["conventional_annual_cost_cr"] = st.number_input("Cost Cr/yr", value=float(econ["conventional_annual_cost_cr"]), step=0.01, key="e_c_c")
    with c2:
        st.markdown("**ECOX-ZLD**")
        econ["ecox_steam_kgh"] = st.number_input("Steam kg/h", value=int(econ["ecox_steam_kgh"]), key="e_e_s")
        econ["ecox_annual_steam_tons"] = st.number_input("Annual t/yr", value=int(econ["ecox_annual_steam_tons"]), key="e_e_a")
        econ["ecox_annual_cost_cr"] = st.number_input("Cost Cr/yr", value=float(econ["ecox_annual_cost_cr"]), step=0.01, key="e_e_c")
    with c3:
        st.markdown("**Savings**")
        econ["steam_reduction_pct"] = st.number_input("Reduction %", value=int(econ["steam_reduction_pct"]), key="e_r")
        econ["annual_steam_savings_tons"] = st.number_input("Savings t/yr", value=int(econ["annual_steam_savings_tons"]), key="e_s_t")
        econ["annual_savings_lakhs"] = st.number_input("Savings Lakhs/yr", value=int(econ["annual_savings_lakhs"]), key="e_s_l")


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
                        logo_path=logo_bytes,       # now accepts bytes
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
                        # Build the JSON from Supabase
                        from bg_process_design.utils.export_utils import build_full_project_export
                        process_json = build_full_project_export(conn, chosen_proj["id"])
                        new_data = bridge_to_offer_data(process_json, existing_data=d)
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
                    st.session_state.og_offer_data = new_data
                    st.success("✅ Imported from JSON")
                    st.rerun()
            except Exception as e:
                st.error(f"Parse failed: {e}")
