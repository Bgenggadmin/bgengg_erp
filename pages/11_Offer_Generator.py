"""
Page 11 — B&G Offer Generator  (fully audited & optimised build)

Fixes applied vs previous version
──────────────────────────────────
1.  _clear_scope_editor_cache defined at MODULE level (was causing NameError).
2.  og_form_version increment + _clear_scope_editor_cache called in EVERY
    load / new-offer path (4 places).
3.  _editor_records uses session_state as source-of-truth → first-edit revert fixed.
4.  _editor_records_sm given the same treatment → Scope Matrix no longer blank.
5.  bg_scope / buyer_scope stored as bool in DB but displayed as ✅/❌ checkbox;
    normalised on load so data_editor receives actual booleans.
6.  Row move-up / move-down buttons added to Scope-of-Supply tabs.
7.  og_client_sel key versioned with fv so it reinitialises on offer load.
8.  "New Offer" button in Tab 9 also clears scope cache & bumps fv.
9.  "Yes, discard and start new" (pending_new path) also bumps fv & clears cache.
10. Tab 7 scope_matrix row-count rebuild guard applied (was always rebuilding).
11. Import/Bridge paths also clear cache after replacing og_offer_data.
12. Redundant double _recalc_economics calls collapsed to one per tab.
"""

import sys, os
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, timezone
import json, copy, math

# ─────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Offer Generator — BGEngg ERP",
    page_icon="📄",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────────
# PASSWORD GATE
# ─────────────────────────────────────────────────────────────────────
_TEAM_PASSWORD = "BG@Design2026"

def _password_gate() -> bool:
    if st.session_state.get("og_authenticated"):
        return True
    st.title("🔒 Offer Generator — Restricted")
    st.caption("Enter team password to access the B&G offer generator.")
    pwd = st.text_input("Password", type="password", key="og_pwd_input")
    if st.button("Unlock", type="primary", key="og_unlock_btn"):
        if pwd == _TEAM_PASSWORD:
            st.session_state.og_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False

if not _password_gate():
    st.stop()

# ─────────────────────────────────────────────────────────────────────
# CONNECTION + MODULE IMPORTS
# ─────────────────────────────────────────────────────────────────────
conn = st.connection("supabase", type=SupabaseConnection)

from bg_offer_generator.utils.brand import BRAND, COMPANY, OFFER_TOC
from bg_offer_generator.utils.default_data import default_offer_data
from bg_offer_generator.utils.form_template import generate_form_template_xlsx
from bg_offer_generator.utils.bridge import (
    parse_process_design_json, bridge_to_offer_data, summarize_bridge_result,
)
from bg_offer_generator.utils.assets import load_brand_assets
from bg_offer_generator.modules.docx_generator import generate_offer_docx


# ─────────────────────────────────────────────────────────────────────
# ECONOMICS CALCULATION
# ─────────────────────────────────────────────────────────────────────
def _recalc_economics(econ: dict, technical_specs: dict = None,
                      utilities: dict = None, capacity_kld: float = None) -> dict:
    hours      = float(econ.get("operating_hours_day", 20) or 0)
    days       = float(econ.get("operating_days_year", 300) or 0)
    steam_cost = float(econ.get("steam_cost_inr_kg", 2.0) or 0)

    conv_kgh      = float(econ.get("conventional_steam_kgh", 0) or 0)
    ecox_kgh      = float(econ.get("ecox_steam_kgh", 0) or 0)
    conv_annual_t = (conv_kgh * hours * days) / 1000.0
    ecox_annual_t = (ecox_kgh * hours * days) / 1000.0
    conv_cost_cr  = (conv_annual_t * steam_cost) / 10000.0
    ecox_cost_cr  = (ecox_annual_t * steam_cost) / 10000.0
    reduction_pct = ((conv_kgh - ecox_kgh) / conv_kgh * 100.0) if conv_kgh > 0 else 0.0

    econ["conventional_annual_steam_tons"] = round(conv_annual_t, 2)
    econ["conventional_annual_cost_cr"]    = round(conv_cost_cr, 4)
    econ["ecox_annual_steam_tons"]         = round(ecox_annual_t, 2)
    econ["ecox_annual_cost_cr"]            = round(ecox_cost_cr, 4)
    econ["steam_reduction_pct"]            = round(reduction_pct, 2)
    econ["annual_steam_savings_tons"]      = round(conv_annual_t - ecox_annual_t, 2)
    econ["annual_savings_lakhs"]           = round((conv_cost_cr - ecox_cost_cr) * 100.0, 2)

    effluent_cost = float(econ.get("effluent_treatment_cost_inr_kl", 0) or 0)
    cap = float(capacity_kld or 0)
    econ["annual_operational_cost_inr"] = round(effluent_cost * cap * days)

    if technical_specs and utilities is not None:
        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
        units = ["stripper", "mee", "atfd"]
        total_steam  = sum(_f(technical_specs.get(u, {}).get("steam_kgh", 0)) for u in units)
        total_power  = sum(_f(technical_specs.get(u, {}).get("power_kwh", 0)) for u in units)
        total_cw_m3  = sum(_f(technical_specs.get(u, {}).get("cooling_water_m3h", 0)) for u in units)
        total_cw_tr  = sum(_f(technical_specs.get(u, {}).get("cooling_water_tr", 0)) for u in units)
        utilities["total_steam_kgh"]         = round(total_steam)
        utilities["total_power_kwh"]         = round(total_power)
        utilities["total_cooling_water_m3h"] = round(total_cw_m3)
        utilities["total_cooling_water_tr"]  = round(total_cw_tr)
        utilities["power_consumption_kwh"]   = round(total_power)
        utilities["cooling_water_m3h"]       = round(total_cw_m3)
    return econ


# ─────────────────────────────────────────────────────────────────────
# JSON SANITISER  (NaN / Inf → None for JSONB)
# ─────────────────────────────────────────────────────────────────────
def _json_safe(obj):
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    try:
        import numpy as np
        if isinstance(obj, np.floating):
            f = float(obj)
            return None if (math.isnan(f) or math.isinf(f)) else f
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
    except Exception:
        pass
    return obj


# ─────────────────────────────────────────────────────────────────────
# SUPABASE HELPERS
# ─────────────────────────────────────────────────────────────────────
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


@st.cache_data(ttl=60)
def _load_offers_list():
    try:
        res = _get_raw_client().table("offers").select(
            "id, quote_ref, client_id, capacity_kld, status, "
            "quote_date, created_at, updated_at, prepared_by, option1_total_cr"
        ).order("updated_at", desc=True).execute()
        return res.data or []
    except Exception as e:
        st.error(f"Failed to load offer list: {e}")
        return []


@st.cache_data(ttl=60)
def _load_anchor_enquiries_for_bridge():
    try:
        res = _get_raw_client().table("anchor_projects").select(
            "id, client_name, project_description, job_no, status, "
            "contact_person, contact_phone, special_notes, enquiry_date, "
            "estimated_value, pd_project_id, offer_id"
        ).eq("anchor_person", "Ammu").not_.is_(
            "pd_project_id", "null"
        ).is_("offer_id", "null").order("enquiry_date", desc=True).execute()
        return res.data or []
    except Exception as e:
        st.warning(f"Could not load anchor enquiries: {e}")
        return []


@st.cache_data(ttl=60)
def _load_anchor_enquiries_already_linked():
    try:
        res = _get_raw_client().table("anchor_projects").select(
            "id, client_name, project_description, job_no, enquiry_date, "
            "pd_project_id, offer_id"
        ).eq("anchor_person", "Ammu").not_.is_(
            "offer_id", "null"
        ).order("enquiry_date", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def _load_offer_by_id(offer_id: int):
    try:
        res = _get_raw_client().table("offers").select("*").eq("id", offer_id).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        st.error(f"Failed to load offer #{offer_id}: {e}")
    return None


def _delete_offer(offer_id: int) -> bool:
    try:
        _get_raw_client().table("offers").delete().eq("id", offer_id).execute()
        _load_offers_list.clear()
        _load_anchor_enquiries_for_bridge.clear()
        _load_anchor_enquiries_already_linked.clear()
        return True
    except Exception as e:
        st.error(f"Failed to delete offer #{offer_id}: {e}")
        return False


def _insert_new_client(name: str, address: str, contact: str, email: str):
    try:
        payload = {
            "name":    name.strip(),
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


def _link_anchor_to_offer(anchor_id: int, offer_id: int) -> bool:
    try:
        _get_raw_client().table("anchor_projects").update(
            {"offer_id": offer_id}
        ).eq("id", anchor_id).execute()
        _load_anchor_enquiries_for_bridge.clear()
        _load_anchor_enquiries_already_linked.clear()
        return True
    except Exception as e:
        st.warning(f"Created offer but couldn't link back to anchor entry: {e}")
        return False


def _save_offer_to_db(data: dict, status: str = "final",
                      offer_id: int = None, pd_project_id=None):
    """Smart upsert. Returns (offer_id, was_insert) or (None, None) on failure."""
    try:
        data = _json_safe(copy.deepcopy(data))
        cov  = data["cover"]
        pr   = data["pricing"]

        qref = (cov.get("quote_ref") or "").strip()
        if (not qref) or ("XXXX" in qref.upper()):
            st.error(
                "❌ Please set a real **Quote Reference** in Tab ① before saving. "
                "It still contains the placeholder `XXXX`."
            )
            return (None, None)

        payload = {
            "quote_ref":        qref,
            "client_id":        data.get("_client_id"),
            "pd_project_id":    pd_project_id or data.get("_pd_project_id"),
            "quote_date":       cov["quote_date"],
            "capacity_kld":     cov["capacity_kld"],
            "prepared_by":      cov["prepared_by"],
            "offer_data":       data,
            "option1_total_cr": pr["option1_total_cr"],
            "option2_total_cr": pr["option2_total_cr"],
            "price_validity_days": pr["price_validity_days"],
            "status":           status,
        }

        if offer_id:
            res = _get_raw_client().table("offers").update(payload).eq("id", offer_id).execute()
            if res.data:
                _load_offers_list.clear()
                return (offer_id, False)
        else:
            existing = _get_raw_client().table("offers").select("id").eq(
                "quote_ref", qref
            ).execute()
            if existing.data:
                existing_id = existing.data[0]["id"]
                res = _get_raw_client().table("offers").update(payload).eq(
                    "id", existing_id
                ).execute()
                if res.data:
                    _load_offers_list.clear()
                    st.info(
                        f"ℹ️ Found existing offer (id={existing_id}) with this "
                        f"reference and updated it."
                    )
                    anchor_id = data.get("_anchor_id")
                    if anchor_id:
                        _link_anchor_to_offer(anchor_id, existing_id)
                    return (existing_id, False)
                return (None, None)
            res = _get_raw_client().table("offers").insert(payload).execute()
            if res.data:
                _load_offers_list.clear()
                anchor_id = data.get("_anchor_id")
                if anchor_id:
                    _link_anchor_to_offer(anchor_id, res.data[0]["id"])
                return (res.data[0]["id"], True)
    except Exception as e:
        st.error(f"Failed to save offer to DB: {e}")
    return (None, None)


# ─────────────────────────────────────────────────────────────────────
# DIRTY-TRACKING
# ─────────────────────────────────────────────────────────────────────
_COMPUTED_PATHS = {
    ("economics", "conventional_annual_steam_tons"),
    ("economics", "conventional_annual_cost_cr"),
    ("economics", "ecox_annual_steam_tons"),
    ("economics", "ecox_annual_cost_cr"),
    ("economics", "steam_reduction_pct"),
    ("economics", "annual_steam_savings_tons"),
    ("economics", "annual_savings_lakhs"),
    ("economics", "annual_operational_cost_inr"),
    ("utilities", "total_steam_kgh"),
    ("utilities", "total_power_kwh"),
    ("utilities", "total_cooling_water_m3h"),
    ("utilities", "total_cooling_water_tr"),
    ("utilities", "power_consumption_kwh"),
    ("utilities", "cooling_water_m3h"),
}

def _snapshot_for_dirty_check(data: dict) -> str:
    d2 = copy.deepcopy(data)
    for section, key in _COMPUTED_PATHS:
        if section in d2 and isinstance(d2[section], dict):
            d2[section].pop(key, None)
    try:
        return json.dumps(d2, sort_keys=True, default=str)
    except Exception:
        return ""

def _mark_clean(data: dict):
    st.session_state.og_saved_snapshot = _snapshot_for_dirty_check(data)
    st.session_state.og_last_saved_at  = datetime.now(timezone.utc)

def _is_dirty(data: dict) -> bool:
    baseline = st.session_state.get("og_saved_snapshot")
    if baseline is None:
        return False
    return _snapshot_for_dirty_check(data) != baseline

def _time_since(dt: datetime) -> str:
    if not dt:
        return "never"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((now - dt).total_seconds())
    if secs < 5:   return "just now"
    if secs < 60:  return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:  return f"{mins} min ago"
    hrs = mins // 60
    if hrs < 24:   return f"{hrs} h {mins % 60} min ago"
    days = hrs // 24
    return f"{days} day{'s' if days > 1 else ''} ago"


# ─────────────────────────────────────────────────────────────────────
# SCOPE EDITOR CACHE  (fix for first-edit revert in data_editor)
# ─────────────────────────────────────────────────────────────────────
_SCOPE_CACHE_KEYS = [
    "_df_src_og_sc_s",
    "_df_src_og_sc_m",
    "_df_src_og_sc_a",
    "_df_src_og_sc_i",
    "_df_src_og_sm",
]

def _clear_scope_editor_cache():
    """Call whenever og_offer_data is replaced wholesale."""
    for k in _SCOPE_CACHE_KEYS:
        st.session_state.pop(k, None)


# ─────────────────────────────────────────────────────────────────────
# LOAD OFFER HELPER  (single point that does all 4 side-effects)
# ─────────────────────────────────────────────────────────────────────
def _apply_loaded_offer(row: dict):
    """Replace session state with a freshly-loaded offer row."""
    st.session_state.og_offer_data      = row["offer_data"]
    st.session_state.og_loaded_offer_id = row["id"]
    st.session_state.og_form_version   += 1
    _clear_scope_editor_cache()
    _mark_clean(row["offer_data"])

def _apply_new_offer():
    """Reset to a blank offer."""
    st.session_state.og_offer_data      = default_offer_data()
    st.session_state.og_loaded_offer_id = None
    st.session_state.og_form_version   += 1
    st.session_state.og_last_saved_at   = None
    _clear_scope_editor_cache()
    _mark_clean(st.session_state.og_offer_data)


# ─────────────────────────────────────────────────────────────────────
# ANCHOR → OFFER BRIDGE
# ─────────────────────────────────────────────────────────────────────
def build_full_project_export_from_offer_side(pd_id: int):
    from bg_process_design.utils.export_utils import build_full_project_export
    return build_full_project_export(conn, pd_id)

def _spawn_offer_from_anchor(anchor_row: dict) -> bool:
    pd_id = anchor_row.get("pd_project_id")
    if not pd_id:
        st.error("This anchor entry has no linked process-design project.")
        return False
    try:
        process_json = build_full_project_export_from_offer_side(pd_id)
    except Exception as e:
        st.error(f"Could not load process design export: {e}")
        return False

    new_data = bridge_to_offer_data(process_json, existing_data=default_offer_data())
    new_data["_anchor_id"]    = anchor_row["id"]
    new_data["_pd_project_id"] = pd_id

    cov = new_data["cover"]
    if anchor_row.get("client_name"):
        cov["submitted_to"] = f"M/s. {anchor_row['client_name']}"
    if anchor_row.get("contact_person"):
        cov["kind_attn"] = f"Mr. {anchor_row['contact_person']}"
    if anchor_row.get("contact_phone"):
        cov["contact_details"] = anchor_row["contact_phone"]
    job    = str(anchor_row.get("job_no") or "").strip()
    suffix = job if job else f"ANC{anchor_row['id']}"
    cov["quote_ref"] = f"BG/ECOX-ZLD/26-27/{suffix} R0"

    _recalc_economics(new_data["economics"],
                      technical_specs=new_data.get("technical_specs"),
                      utilities=new_data.get("utilities"),
                      capacity_kld=new_data["cover"].get("capacity_kld"))

    st.session_state.og_offer_data      = new_data
    st.session_state.og_loaded_offer_id = None
    st.session_state.og_form_version   += 1
    st.session_state.og_last_saved_at   = None
    _clear_scope_editor_cache()
    _mark_clean(new_data)
    return True


# ─────────────────────────────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────────────────────────────
if "og_offer_data"      not in st.session_state:
    st.session_state.og_offer_data = default_offer_data()
if "og_form_version"    not in st.session_state:
    st.session_state.og_form_version = 0
if "og_loaded_offer_id" not in st.session_state:
    st.session_state.og_loaded_offer_id = None
if "og_last_saved_at"   not in st.session_state:
    st.session_state.og_last_saved_at = None
if "og_saved_snapshot"  not in st.session_state:
    st.session_state.og_saved_snapshot = _snapshot_for_dirty_check(
        st.session_state.og_offer_data
    )


# ─────────────────────────────────────────────────────────────────────
# BRANDED HEADER
# ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
    .og-header {{
        background: linear-gradient(135deg, {BRAND['primary_red']} 0%, {BRAND['accent_pink']} 100%);
        padding: 18px 28px; border-radius: 8px; margin-bottom: 18px;
    }}
    .og-header h1 {{ color: white !important; margin: 0; font-size: 26px; }}
    .og-header p  {{ color: rgba(255,255,255,0.9) !important; margin: 4px 0 0 0; font-size: 13px; }}
</style>
<div class="og-header">
    <h1>📄 B&amp;G Offer Generator</h1>
    <p>Techno-Commercial Offer · B&amp;G ECOX-ZLD System · Responsible towards water</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────
# SCHEMA BACKFILL  (before any tab renders)
# ─────────────────────────────────────────────────────────────────────
d = st.session_state.og_offer_data

d.setdefault("cover", {})
d["cover"].setdefault("capacity_kld", 150)

for k, v in {
    "operating_hours_day": 20,
    "operating_days_year": 300,
    "steam_cost_inr_kg": 2.0,
    "power_cost_inr_kwh": 9.0,
    "cooling_water_cost_inr_m3": 90.0,
    "effluent_treatment_cost_inr_kl": 1185.0,
    "conventional_steam_kgh": 0,
    "ecox_steam_kgh": 0,
}.items():
    d.setdefault("economics", {})
    d["economics"].setdefault(k, v)

d.setdefault("feed_parameters", {})
d["feed_parameters"].setdefault("specific_gravity", "1.0")

d.setdefault("technical_specs", {})
for unit in ("stripper", "mee", "atfd"):
    d["technical_specs"].setdefault(unit, {})
    for k, v in {
        "steam_kgh": 0, "steam_pressure": "1.5 Bar-g",
        "power_kwh": 0,
        "cooling_water_m3h": 0, "cooling_water_tr": 0,
        "cooling_water_temps": "In/Out: 32 / 38 °C",
        "compressed_air_nm3h": "8", "compressed_air_pressure": "6 Bar-g",
    }.items():
        d["technical_specs"][unit].setdefault(k, v)
d["technical_specs"]["stripper"].setdefault("reflux_kgh", 0)
d["technical_specs"]["mee"].setdefault("steam_economy", 4.3)
d.setdefault("utilities", {})

# Normalise bool columns in scope tables (DB may return "True"/"False" strings)
def _norm_bool(records: list, bool_cols: list) -> list:
    out = []
    for row in records:
        r = dict(row)
        for col in bool_cols:
            v = r.get(col)
            if isinstance(v, str):
                r[col] = v.strip().lower() not in ("false", "0", "no", "")
            elif v is None:
                r[col] = False
        out.append(r)
    return out

for key in ("scope_stripper", "scope_mee", "scope_atfd"):
    if key in d:
        d[key] = _norm_bool(d[key], ["bg_scope", "buyer_scope"])

_recalc_economics(
    d["economics"],
    technical_specs=d["technical_specs"],
    utilities=d["utilities"],
    capacity_kld=d["cover"].get("capacity_kld"),
)


# ─────────────────────────────────────────────────────────────────────
# TOP STATUS BAR
# ─────────────────────────────────────────────────────────────────────
dirty     = _is_dirty(d)
loaded_id = st.session_state.og_loaded_offer_id
last_saved = st.session_state.og_last_saved_at

bar_c1, bar_c2, bar_c3, bar_c4 = st.columns([3, 2, 2, 1])
with bar_c1:
    if loaded_id:
        st.markdown(f"📂 **Editing offer #{loaded_id}** — `{d['cover'].get('quote_ref', '')}`")
    elif d.get("_anchor_id"):
        st.markdown(f"🔗 **New offer from anchor #{d['_anchor_id']}** — not yet saved")
    else:
        st.markdown("📝 **New offer** (not yet saved)")
with bar_c2:
    label = _time_since(last_saved) if last_saved else "never"
    st.markdown(f"💾 Last saved: **{label}**")
with bar_c3:
    if dirty:
        if st.button("💾 Save Draft", type="primary", use_container_width=True,
                     key="og_save_draft_top"):
            new_id, was_insert = _save_offer_to_db(
                d, status="draft", offer_id=st.session_state.og_loaded_offer_id)
            if new_id:
                st.session_state.og_loaded_offer_id = new_id
                _mark_clean(d)
                st.success(f"✅ Draft {'created' if was_insert else 'updated'} (id={new_id})")
                st.rerun()
    else:
        st.button("✅ All saved", disabled=True, use_container_width=True,
                  key="og_save_draft_top_disabled")
with bar_c4:
    if st.button("🚪 Logout", use_container_width=True, key="og_logout_btn"):
        st.session_state.og_authenticated = False
        st.rerun()

if dirty:
    st.warning(
        "⚠️ **You have unsaved changes.** Click 💾 **Save Draft** above to preserve "
        "your work. Refreshing the page or closing the tab will lose unsaved edits."
    )


# ─────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────
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

fv = st.session_state.og_form_version  # version prefix for all versioned widget keys


# ══════════════════════════════════════════════════════════════════════
# TAB 1 — Cover & Client
# ══════════════════════════════════════════════════════════════════════
with tabs[0]:
    d   = st.session_state.og_offer_data
    cov = d["cover"]

    # ── Open Existing Offer ──────────────────────────────────────────
    with st.expander("📂 Open Existing Offer",
                     expanded=not loaded_id and not d.get("_anchor_id")):
        offers_list = _load_offers_list()
        clients_map = {c["id"]: c["name"] for c in _load_clients()}

        if not offers_list:
            st.info("No saved offers yet. Fill in the form and click 💾 Save Draft.")
        else:
            def _fmt_offer(o):
                cname      = clients_map.get(o.get("client_id"), "—") if o.get("client_id") else "—"
                emoji      = "📝" if o.get("status") == "draft" else "✅"
                updated    = str(o.get("updated_at") or o.get("created_at") or "")[:16].replace("T", " ")
                price      = o.get("option1_total_cr")
                price_str  = f" · ₹{price:.2f}Cr" if price else ""
                return f"{emoji} #{o['id']} · {o['quote_ref']} · {cname} · {o.get('capacity_kld','?')} KLD{price_str} · {updated}"

            options = ["— select an offer to open —"] + [_fmt_offer(o) for o in offers_list]
            sel_idx = st.selectbox(
                f"Saved offers ({len(offers_list)} total · newest first)",
                range(len(options)),
                format_func=lambda i: options[i],
                key="og_load_sel",
            )

            cols = st.columns([1, 1, 1, 3])
            with cols[0]:
                if st.button("📂 Open", type="primary", disabled=(sel_idx == 0),
                             key="og_load_open_btn", use_container_width=True):
                    if dirty:
                        st.session_state.og_pending_load_id = offers_list[sel_idx - 1]["id"]
                        st.rerun()
                    else:
                        row = _load_offer_by_id(offers_list[sel_idx - 1]["id"])
                        if row and row.get("offer_data"):
                            _apply_loaded_offer(row)
                            st.success(f"✅ Opened offer #{row['id']}")
                            st.rerun()
                        else:
                            st.error("Could not load this offer.")

            with cols[1]:
                if loaded_id or d.get("_anchor_id"):
                    if st.button("🆕 New Offer", use_container_width=True,
                                 key="og_new_offer_btn"):
                        if dirty:
                            st.session_state.og_pending_new = True
                            st.rerun()
                        else:
                            _apply_new_offer()
                            st.rerun()

            with cols[2]:
                with st.popover("🗑️ Delete", disabled=(sel_idx == 0),
                                use_container_width=True):
                    if sel_idx != 0:
                        target = offers_list[sel_idx - 1]
                        st.warning(
                            f"Permanently delete offer **#{target['id']}** "
                            f"(`{target['quote_ref']}`)? This cannot be undone."
                        )
                        if st.button("⚠️ Yes, delete permanently",
                                     type="primary", key="og_delete_confirm_btn"):
                            del_id = target["id"]
                            if _delete_offer(del_id):
                                if st.session_state.og_loaded_offer_id == del_id:
                                    _apply_new_offer()
                                st.success(f"🗑️ Deleted offer #{del_id}")
                                st.rerun()

            # Pending-load (dirty guard)
            if st.session_state.get("og_pending_load_id"):
                pid = st.session_state.og_pending_load_id
                st.warning(f"⚠️ You have unsaved changes. Opening offer #{pid} will discard them. Continue?")
                pc1, pc2 = st.columns(2)
                if pc1.button("✅ Yes, discard and open", key="og_pending_yes"):
                    row = _load_offer_by_id(pid)
                    if row and row.get("offer_data"):
                        _apply_loaded_offer(row)
                    st.session_state.pop("og_pending_load_id", None)
                    st.rerun()
                if pc2.button("❌ Cancel", key="og_pending_no"):
                    st.session_state.pop("og_pending_load_id", None)
                    st.rerun()

            # Pending-new (dirty guard)
            if st.session_state.get("og_pending_new"):
                st.warning("⚠️ You have unsaved changes. Starting a new offer will discard them. Continue?")
                pn1, pn2 = st.columns(2)
                if pn1.button("✅ Yes, discard and start new", key="og_new_yes"):
                    _apply_new_offer()
                    st.session_state.pop("og_pending_new", None)
                    st.rerun()
                if pn2.button("❌ Cancel", key="og_new_no"):
                    st.session_state.pop("og_pending_new", None)
                    st.rerun()

    # ── Spawn from Anchor ────────────────────────────────────────────
    with st.expander("🔗 Spawn Offer from Anchor Enquiry (Ammu · MEE projects)",
                     expanded=False):
        st.caption(
            "Shows Ammu's anchor enquiries that have a Process Design linked "
            "but no offer yet."
        )
        anchor_bridge_rows = _load_anchor_enquiries_for_bridge()
        if not anchor_bridge_rows:
            st.info("No anchor enquiries ready to bridge.")
        else:
            def _fmt_anchor(r):
                return (
                    f"Anchor #{r['id']} · {r.get('client_name','?')} · "
                    f"{(r.get('project_description') or '')[:40]} · "
                    f"Job {r.get('job_no','—')} · pd #{r['pd_project_id']} · "
                    f"{str(r.get('enquiry_date',''))[:10]}"
                )
            opts    = ["— select an enquiry —"] + [_fmt_anchor(r) for r in anchor_bridge_rows]
            anc_sel = st.selectbox(
                f"Ammu's enquiries ready to bridge ({len(anchor_bridge_rows)} found)",
                range(len(opts)), format_func=lambda i: opts[i],
                key="og_anchor_bridge_sel",
            )
            if st.button("🔀 Bridge to Offer", type="primary",
                         disabled=(anc_sel == 0), key="og_anchor_bridge_btn"):
                if dirty:
                    st.warning("⚠️ Save your current changes first.")
                else:
                    chosen = anchor_bridge_rows[anc_sel - 1]
                    if _spawn_offer_from_anchor(chosen):
                        st.success(
                            f"✅ Bridged anchor #{chosen['id']} → pd_project "
                            f"#{chosen['pd_project_id']} into new offer."
                        )
                        st.rerun()

        linked_rows = _load_anchor_enquiries_already_linked()
        if linked_rows:
            st.divider()
            st.markdown("**↩️ Already generated an offer? Re-open your saved work:**")
            def _fmt_linked(r):
                return (
                    f"Anchor #{r['id']} · {r.get('client_name','?')} · "
                    f"{(r.get('project_description') or '')[:35]} · "
                    f"→ offer #{r['offer_id']}"
                )
            lopts = ["— select —"] + [_fmt_linked(r) for r in linked_rows]
            lsel  = st.selectbox(
                f"Linked offers ({len(linked_rows)})",
                range(len(lopts)), format_func=lambda i: lopts[i],
                key="og_anchor_linked_sel",
            )
            if st.button("📂 Open Saved Offer", disabled=(lsel == 0),
                         key="og_anchor_linked_open"):
                if dirty:
                    st.warning("⚠️ Save or discard current changes first.")
                else:
                    target = linked_rows[lsel - 1]
                    row    = _load_offer_by_id(target["offer_id"])
                    if row and row.get("offer_data"):
                        _apply_loaded_offer(row)
                        st.success(f"✅ Opened saved offer #{row['id']}")
                        st.rerun()
                    else:
                        st.error(f"Could not load offer #{target['offer_id']}.")

    st.divider()

    # ── Cover & Client fields ────────────────────────────────────────
    st.subheader("Cover Page & Client Details")
    cov = d["cover"]

    clients = _load_clients()
    if clients:
        names       = ["— select client —"] + [f"{c['name']} (id={c['id']})" for c in clients]
        default_idx = 0
        new_cid     = st.session_state.pop("og_new_client_id", None)
        if new_cid is not None:
            for i, c in enumerate(clients):
                if c["id"] == new_cid:
                    default_idx = i + 1
                    break
        elif d.get("_client_id"):
            for i, c in enumerate(clients):
                if c["id"] == d["_client_id"]:
                    default_idx = i + 1
                    break

        sel = st.selectbox("Client", names, index=default_idx,
                           key=f"og_client_sel_{fv}")
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
            nc_name    = st.text_input("Client Name *", key="og_nc_name")
            nc_address = st.text_area("Address", key="og_nc_address", height=80)
            c1, c2     = st.columns(2)
            nc_contact = c1.text_input("Contact (phone)", key="og_nc_contact")
            nc_email   = c2.text_input("Email", key="og_nc_email")
            if st.form_submit_button("💾 Save client", type="primary"):
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
        cov["quote_ref"]     = st.text_input("Quote Reference",       value=cov.get("quote_ref", ""),     key=f"og_cov_qr_{fv}")
        cov["quote_date"]    = st.text_input("Quote Date (YYYY-MM-DD)", value=str(cov.get("quote_date", "")), key=f"og_cov_qd_{fv}")
        cov["submitted_to"]  = st.text_input("Submitted to",          value=cov.get("submitted_to", ""),  key=f"og_cov_st_{fv}")
        cov["location"]      = st.text_input("Location",              value=cov.get("location", ""),      key=f"og_cov_loc_{fv}")
        cov["capacity_kld"]  = st.number_input("Capacity (KLD)",      value=int(cov.get("capacity_kld", 150)),
                                               min_value=1, max_value=5000, step=1, key=f"og_cov_cap_{fv}")
    with c2:
        cov["prepared_by"]    = st.text_input("Prepared By",    value=cov.get("prepared_by", ""),    key=f"og_cov_pb_{fv}")
        cov["contact_details"]= st.text_input("Contact",        value=cov.get("contact_details", ""),key=f"og_cov_cd_{fv}")
        cov["email"]          = st.text_input("E-mail",         value=cov.get("email", ""),          key=f"og_cov_em_{fv}")
        cov["kind_attn"]      = st.text_input("Kind Attention", value=cov.get("kind_attn", ""),      key=f"og_cov_ka_{fv}")
        cov["discussion_date"]= st.text_input("Discussion Date",value=cov.get("discussion_date", ""),key=f"og_cov_dd_{fv}")

    cov["subject"] = st.text_input("Subject Line", value=cov.get("subject", ""), key=f"og_cov_sub_{fv}")


# ══════════════════════════════════════════════════════════════════════
# TAB 2 — Executive Summary
# ══════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.subheader("PART I — Executive Summary")
    d["executive_summary"] = st.text_area(
        "Editable text", value=d.get("executive_summary", ""),
        height=400, key="og_exec_sum")


# ══════════════════════════════════════════════════════════════════════
# TAB 3 — Process Description
# ══════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.subheader("PART II — Process Description")
    pd_data = d["process_description"]
    pd_data["n_effects"] = st.slider("MEE Effects", 2, 7,
                                     value=int(pd_data.get("n_effects", 4)),
                                     key="og_pd_effects")
    with st.expander("Stripper", expanded=True):
        pd_data["stripper"] = st.text_area("", value=pd_data.get("stripper", ""),
                                           height=200, key="og_pd_strip")
    with st.expander("MEE"):
        pd_data["mee"] = st.text_area("use {n_effects}", value=pd_data.get("mee", ""),
                                      height=300, key="og_pd_mee")
    with st.expander("ATFD"):
        pd_data["atfd"] = st.text_area("", value=pd_data.get("atfd", ""),
                                       height=300, key="og_pd_atfd")


# ══════════════════════════════════════════════════════════════════════
# TAB 4 — Economics / OPEX
# ══════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.subheader("PART IV — Economics / OPEX")
    econ = d["economics"]

    st.markdown("### Overall Parameters")
    op1, op2, op3 = st.columns(3)
    with op1:
        econ["operating_hours_day"] = st.number_input(
            "Operating Hours per Day (h)",
            value=float(econ["operating_hours_day"]),
            min_value=1.0, max_value=24.0, step=1.0, key="og_e_ophrs")
    with op2:
        econ["operating_days_year"] = st.number_input(
            "Days of Operation per Year",
            value=int(econ["operating_days_year"]),
            min_value=1, max_value=365, step=1, key="og_e_days")
    with op3:
        econ["effluent_treatment_cost_inr_kl"] = st.number_input(
            "Effluent Treatment Cost (₹/KL)",
            value=float(econ["effluent_treatment_cost_inr_kl"]),
            min_value=0.0, step=1.0, format="%.2f", key="og_e_eff_cost")

    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        econ["steam_cost_inr_kg"] = st.number_input(
            "Steam Cost (₹/kg)", value=float(econ["steam_cost_inr_kg"]),
            min_value=0.0, step=0.1, format="%.2f", key="og_e_steam_rate")
    with cc2:
        econ["power_cost_inr_kwh"] = st.number_input(
            "Power Cost (₹/kWh)", value=float(econ["power_cost_inr_kwh"]),
            min_value=0.0, step=0.5, format="%.2f", key="og_e_pwr_rate")
    with cc3:
        econ["cooling_water_cost_inr_m3"] = st.number_input(
            "Cooling Water Cost (₹/m³)",
            value=float(econ["cooling_water_cost_inr_m3"]),
            min_value=0.0, step=1.0, format="%.2f", key="og_e_cw_rate")

    st.divider()
    st.markdown("### Steam Comparison — BG ECOX-ZLD Advantage")
    si1, si2 = st.columns(2)
    with si1:
        econ["conventional_steam_kgh"] = st.number_input(
            "Conventional — MEE Steam (kg/h)",
            value=float(econ.get("conventional_steam_kgh", 0) or 0),
            min_value=0.0, step=1.0, key="og_e_conv_kgh")
    with si2:
        econ["ecox_steam_kgh"] = st.number_input(
            "ECOX-ZLD — MEE Steam (kg/h)",
            value=float(econ.get("ecox_steam_kgh", 0) or 0),
            min_value=0.0, step=1.0, key="og_e_ecox_kgh")

    _recalc_economics(econ, technical_specs=d["technical_specs"],
                      utilities=d["utilities"],
                      capacity_kld=d["cover"].get("capacity_kld"))

    st.divider()
    st.markdown("### Calculated Results — Steam Advantage")
    rc1, rc2, rc3 = st.columns(3)
    with rc1:
        st.markdown("**Conventional**")
        st.metric("Annual Steam (t/yr)", f"{econ['conventional_annual_steam_tons']:,.2f}")
        st.metric("Annual Cost (Cr/yr)", f"₹{econ['conventional_annual_cost_cr']:.4f}")
    with rc2:
        st.markdown("**ECOX-ZLD**")
        st.metric("Annual Steam (t/yr)", f"{econ['ecox_annual_steam_tons']:,.2f}")
        st.metric("Annual Cost (Cr/yr)", f"₹{econ['ecox_annual_cost_cr']:.4f}")
    with rc3:
        st.markdown("**Savings**")
        st.metric("Steam Reduction (%)",   f"{econ['steam_reduction_pct']:.2f}%")
        st.metric("Steam Savings (t/yr)", f"{econ['annual_steam_savings_tons']:,.2f}")
        st.metric("Cost Savings (Lakhs/yr)", f"₹{econ['annual_savings_lakhs']:.2f}")

    st.info("💡 Total Steam/Power/CW and Annual Operational Cost are at the bottom of Tab ⑤ Technical.")


# ══════════════════════════════════════════════════════════════════════
# TAB 5 — Technical
# ══════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.subheader("PART V — Technical Details & Utilities")
    fp = d["feed_parameters"]
    ts = d["technical_specs"]

    with st.expander("📋 Feed Parameters", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            fp["capacity_kld"]               = st.number_input("Feed / Capacity (KLD)", value=int(fp.get("capacity_kld", 150)), min_value=1, max_value=5000, step=1, key="t_cap")
            fp["feed_ph"]                    = st.text_input("Feed pH", value=str(fp.get("feed_ph", "")), key="t_ph")
            fp["specific_gravity"]           = st.text_input("Specific Gravity", value=str(fp.get("specific_gravity", "1.0")), key="t_sg")
            fp["total_cod_ppm"]              = st.number_input("Total COD (PPM)", value=int(fp.get("total_cod_ppm", 0)), step=1, key="t_cod")
            fp["volatile_organic_solvents_ppm"] = st.number_input("Volatile Organic Solvents (PPM)", value=int(fp.get("volatile_organic_solvents_ppm", 0)), step=1, key="t_vos")
            fp["total_solids_pct"]           = st.text_input("Total Solids (% w/w)", value=str(fp.get("total_solids_pct", "")), key="t_ts")
        with c2:
            fp["suspended_solids_ppm"]  = st.text_input("Suspended Solids (PPM)", value=str(fp.get("suspended_solids_ppm", "")), key="t_ss")
            fp["feed_temp_c"]           = st.number_input("Feed Temperature (°C)", value=int(fp.get("feed_temp_c", 30)), step=1, key="t_T")
            fp["total_hardness_ppm"]    = st.text_input("Total Hardness (PPM)", value=str(fp.get("total_hardness_ppm", "")), key="t_th")
            fp["silica_ppm"]            = st.text_input("Silica (PPM)", value=str(fp.get("silica_ppm", "")), key="t_si")
            fp["free_chloride_ppm"]     = st.text_input("Free Chloride (PPM)", value=str(fp.get("free_chloride_ppm", "")), key="t_cl")
            fp["feed_nature"]           = st.text_input("Feed Nature", value=fp.get("feed_nature", ""), key="t_nat")

    def _unit_expander(label: str, u: dict, pfx: str, default_type: str):
        with st.expander(label, expanded=True):
            u["type"] = st.text_input("Type", value=u.get("type", default_type), key=f"{pfx}_type")
            c1, c2    = st.columns(2)
            with c1:
                st.markdown("**Process Flows**")
                u["feed_kgh"]       = st.number_input("Inlet Feed Rate (kg/h)",        value=int(u.get("feed_kgh", 0)),       step=1, key=f"{pfx}_feed")
                u["distillate_kgh"] = st.number_input("Top Distillate Out (kg/h)",     value=int(u.get("distillate_kgh", 0)), step=1, key=f"{pfx}_dist")
                if pfx == "ts_s":
                    u["distillate_composition"] = st.text_input("Distillate Composition", value=u.get("distillate_composition", ""), key=f"{pfx}_dc")
                u["bottoms_kgh"]    = st.number_input("Stripper Bottom Out (kg/h)" if pfx == "ts_s" else "Concentrate Out (kg/h)",
                                                      value=int(u.get("bottoms_kgh", u.get("concentrate_kgh", 0))), step=1, key=f"{pfx}_bot")
                if pfx == "ts_s":
                    u["reflux_kgh"] = st.number_input("Reflux Rate (kg/h)", value=int(u.get("reflux_kgh", 0)), step=1, key=f"{pfx}_ref")
                if pfx in ("ts_m", "ts_a"):
                    u["feed_solids_pct"]    = st.text_input("Feed Solids (%)", value=str(u.get("feed_solids_pct", "")), key=f"{pfx}_fs")
                    u["evaporation_kgh"]    = st.number_input("Water Evaporation Rate (kg/h)", value=int(u.get("evaporation_kgh", 0)), step=1, key=f"{pfx}_evap")
                    u["concentrate_kgh"]    = st.number_input("Concentrate Out (kg/h)", value=int(u.get("concentrate_kgh", 0)), step=1, key=f"{pfx}_conc")
                    if pfx == "ts_m":
                        u["concentrate_solids_pct"] = st.number_input("Concentrate Out (%)", value=int(u.get("concentrate_solids_pct", 40)), min_value=0, max_value=100, step=1, key=f"{pfx}_cs")
                    if pfx == "ts_a":
                        u["product_kgh"]            = st.number_input("ATFD Product Out (kg/h)", value=int(u.get("product_kgh", 0)), step=1, key=f"{pfx}_prod")
                        u["product_moisture_pct"]   = st.text_input("Moisture in ATFD Product (%)", value=str(u.get("product_moisture_pct", "8-10")), key=f"{pfx}_pm")
            with c2:
                st.markdown("**Utilities**")
                u["steam_pressure"]         = st.text_input("Steam Pressure", value=u.get("steam_pressure", "1.5 Bar-g"), key=f"{pfx}_sp")
                u["steam_kgh"]              = st.number_input("Steam (kg/h)", value=int(u.get("steam_kgh", 0)), step=1, key=f"{pfx}_st")
                if pfx == "ts_m":
                    u["steam_economy"]      = st.number_input("Steam Economy (kg/kg)", value=float(u.get("steam_economy", 4.3)), min_value=0.0, step=0.1, format="%.2f", key=f"{pfx}_se")
                u["power_kwh"]              = st.number_input("Power (kWh)", value=int(u.get("power_kwh", 0)), step=1, key=f"{pfx}_pw")
                cw1, cw2 = st.columns(2)
                u["cooling_water_m3h"]      = cw1.number_input("CW (m³/h)", value=int(u.get("cooling_water_m3h", 0)), step=1, key=f"{pfx}_cw")
                u["cooling_water_tr"]       = cw2.number_input("CW (TR)", value=int(u.get("cooling_water_tr", 0)), step=1, key=f"{pfx}_cwtr")
                u["cooling_water_temps"]    = st.text_input("CW Temps", value=u.get("cooling_water_temps", "In/Out: 32 / 38 °C"), key=f"{pfx}_cwt")
                ca1, ca2 = st.columns(2)
                u["compressed_air_nm3h"]    = ca1.text_input("CA (Nm³/h)", value=str(u.get("compressed_air_nm3h", "8")), key=f"{pfx}_ca")
                u["compressed_air_pressure"]= ca2.text_input("CA Pressure", value=u.get("compressed_air_pressure", "6 Bar-g"), key=f"{pfx}_cap")

    _unit_expander("⚙️ Stripper System",                ts["stripper"], "ts_s", "Tray Type Column")
    _unit_expander("⚙️ Multiple Effect Evaporator System", ts["mee"],  "ts_m", "4-Effect Forced Circulation")
    _unit_expander("⚙️ Agitated Thin Film Dryer (ATFD)",  ts["atfd"], "ts_a", "Agitated Thin Film Dryer")

    ut = d["utilities"]
    ut["stripper_steam"] = {"param": f"{ts['stripper']['steam_pressure']}, >96% dryness", "value_kgh": ts["stripper"]["steam_kgh"]}
    ut["mee_steam"]      = {"param": f"{ts['mee']['steam_pressure']}, >96% dryness",      "value_kgh": ts["mee"]["steam_kgh"], "steam_economy": ts["mee"]["steam_economy"]}
    ut["atfd_steam"]     = {"param": f"{ts['atfd']['steam_pressure']}, >96% dryness",     "value_kgh": ts["atfd"]["steam_kgh"]}

    _recalc_economics(d["economics"], technical_specs=ts, utilities=ut,
                      capacity_kld=d["cover"].get("capacity_kld"))

    st.divider()
    st.markdown("### Plant-Wide Totals")
    tc1, tc2, tc3 = st.columns(3)
    tc1.metric("Total Steam",        f"{ut['total_steam_kgh']} kg/h",      help="Stripper + MEE + ATFD")
    tc2.metric("Total Power",        f"{ut['total_power_kwh']} kWh")
    tc3.metric("Total Cooling Water",f"{ut['total_cooling_water_m3h']} m³/h", f"{ut['total_cooling_water_tr']} TR")

    st.markdown("### Overall System Operational Cost")
    cap = d["cover"].get("capacity_kld", 0)
    e   = d["economics"]
    o1, o2, o3, o4 = st.columns(4)
    o1.metric("Plant Capacity", f"{cap} KLD")
    o2.metric("Total Steam",    f"{ut['total_steam_kgh']} kg/h")
    o3.metric("Total Power",    f"{ut['total_power_kwh']} kWh")
    o4.metric("Total CW",       f"{ut['total_cooling_water_m3h']} m³/h", f"{ut['total_cooling_water_tr']} TR")
    o5, o6 = st.columns(2)
    o5.metric("Effluent Treatment Cost",  f"₹{e['effluent_treatment_cost_inr_kl']:,.0f}/KL")
    o6.metric("Annual Operational Cost",  f"₹{e['annual_operational_cost_inr']:,.0f}/yr")

    with st.expander("🎯 Performance Guarantee", expanded=False):
        pg_txt = "\n".join(d.get("performance_guarantee", []))
        new_pg = st.text_area("One bullet per line", value=pg_txt, height=120, key="og_pg")
        d["performance_guarantee"] = [l.strip() for l in new_pg.split("\n") if l.strip()]


# ══════════════════════════════════════════════════════════════════════
# TAB 6 — Scope of Supply
# ══════════════════════════════════════════════════════════════════════
with tabs[5]:
    import pandas as pd
    st.subheader("PART VI — Scope of Supply")

    _SCOPE_COLS = ["equipment", "specification", "qty", "bg_scope", "buyer_scope"]
    _INSTR_COLS = ["item", "qty", "scope"]

    def _build_df(records: list, col_order: list) -> pd.DataFrame:
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=col_order)
        for c in col_order:
            if c not in df.columns:
                df[c] = False if c in ("bg_scope", "buyer_scope") else ""
        # Ensure bool columns are actual booleans
        for c in ("bg_scope", "buyer_scope"):
            if c in col_order and c in df.columns:
                df[c] = df[c].apply(
                    lambda v: False if (v in (None, "", "False", "false")) else bool(v)
                )
        return df[col_order].reset_index(drop=True)

    def _editor_records(records: list, ss_key_base: str, col_order: list):
        """
        Stable data_editor that does NOT rebuild from records on every rerun.
        This prevents the first-edit revert bug.
        Cache is keyed to ss_key_base and cleared when a new offer is loaded.
        """
        ss_key = f"_df_src_{ss_key_base}"
        if ss_key not in st.session_state:
            # First render: build from records
            st.session_state[ss_key] = _build_df(records, col_order)
        else:
            existing = st.session_state[ss_key]
            if len(existing) != len(records):
                # Row count changed (new offer loaded) → rebuild
                st.session_state[ss_key] = _build_df(records, col_order)

        edited  = st.data_editor(
            st.session_state[ss_key],
            use_container_width=True,
            num_rows="dynamic",
            key=ss_key_base,
            column_config={
                "bg_scope":    st.column_config.CheckboxColumn("B&G", default=True),
                "buyer_scope": st.column_config.CheckboxColumn("Buyer", default=False),
            } if "bg_scope" in col_order else {},
        )
        cleaned = edited.where(pd.notnull(edited), "")
        # Keep bool columns as booleans after where() call
        for c in ("bg_scope", "buyer_scope"):
            if c in col_order and c in cleaned.columns:
                cleaned[c] = cleaned[c].astype(bool)
        st.session_state[ss_key] = cleaned.reset_index(drop=True)
        return cleaned.to_dict("records")

    def _scope_tab_with_move(data_key: str, ss_key_base: str, col_order: list):
        """Renders editor + ↑↓ move row buttons for a scope sub-tab."""
        records = d.get(data_key, [])
        ss_key  = f"_df_src_{ss_key_base}"

        # Move buttons above the editor
        if ss_key in st.session_state and len(st.session_state[ss_key]) > 1:
            df_cur = st.session_state[ss_key]
            n = len(df_cur)
            mv_col1, mv_col2, mv_col3 = st.columns([1, 1, 6])
            sel_row = mv_col1.number_input("Row #", min_value=1, max_value=n, step=1,
                                           key=f"mv_row_{ss_key_base}", label_visibility="collapsed")
            with mv_col1:
                pass
            b1, b2 = mv_col2.columns(2)
            if b1.button("↑", key=f"mv_up_{ss_key_base}",
                         disabled=(sel_row <= 1), help="Move row up"):
                idx = int(sel_row) - 1
                rows = df_cur.to_dict("records")
                rows[idx - 1], rows[idx] = rows[idx], rows[idx - 1]
                st.session_state[ss_key] = pd.DataFrame(rows).reset_index(drop=True)
                st.rerun()
            if b2.button("↓", key=f"mv_dn_{ss_key_base}",
                         disabled=(sel_row >= n), help="Move row down"):
                idx = int(sel_row) - 1
                rows = df_cur.to_dict("records")
                rows[idx], rows[idx + 1] = rows[idx + 1], rows[idx]
                st.session_state[ss_key] = pd.DataFrame(rows).reset_index(drop=True)
                st.rerun()
            mv_col3.caption(f"Select row number and use ↑ ↓ to reorder  ({n} rows total)")

        d[data_key] = _editor_records(records, ss_key_base, col_order)

    sub = st.tabs(["Stripper", "MEE", "ATFD", "Instruments"])
    with sub[0]:
        _scope_tab_with_move("scope_stripper", "og_sc_s", _SCOPE_COLS)
    with sub[1]:
        _scope_tab_with_move("scope_mee",      "og_sc_m", _SCOPE_COLS)
    with sub[2]:
        _scope_tab_with_move("scope_atfd",     "og_sc_a", _SCOPE_COLS)
    with sub[3]:
        _scope_tab_with_move("instruments",    "og_sc_i", _INSTR_COLS)


# ══════════════════════════════════════════════════════════════════════
# TAB 7 — Scope Matrix
# ══════════════════════════════════════════════════════════════════════
with tabs[6]:
    import pandas as pd
    st.subheader("PART VII & VIII — Battery Limits & Scope Matrix")

    _MATRIX_COLS = ["description", "bg", "client"]

    def _editor_records_sm(records: list, ss_key_base: str, col_order: list):
        ss_key = f"_df_src_{ss_key_base}"
        if ss_key not in st.session_state:
            st.session_state[ss_key] = _build_df(records, col_order)
        else:
            existing = st.session_state[ss_key]
            if len(existing) != len(records):
                st.session_state[ss_key] = _build_df(records, col_order)

        edited  = st.data_editor(
            st.session_state[ss_key],
            use_container_width=True,
            num_rows="dynamic",
            key=ss_key_base,
            column_config={
                "bg":     st.column_config.CheckboxColumn("B&G", default=False),
                "client": st.column_config.CheckboxColumn("Client", default=False),
            } if "bg" in col_order else {},
        )
        cleaned = edited.where(pd.notnull(edited), "")
        st.session_state[ss_key] = cleaned.reset_index(drop=True)
        return cleaned.to_dict("records")

    with st.expander("Battery Limits", expanded=True):
        bl_txt = "\n".join(d.get("battery_limits", []))
        new_bl = st.text_area("One item per line", value=bl_txt, height=300, key="og_bl")
        d["battery_limits"] = [l.strip() for l in new_bl.split("\n") if l.strip()]

    with st.expander("Scope Matrix", expanded=True):
        d["scope_matrix"] = _editor_records_sm(
            d.get("scope_matrix", []), "og_sm", _MATRIX_COLS)


# ══════════════════════════════════════════════════════════════════════
# TAB 8 — Pricing & Terms
# ══════════════════════════════════════════════════════════════════════
with tabs[7]:
    st.subheader("PART X — Price & Terms")
    pr = d["pricing"]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Option 1**")
        pr["option1_moc"]                 = st.text_input("MOC", value=pr.get("option1_moc", ""), key="og_p1m")
        pr["option1_equipment_price_cr"]  = st.number_input("Equipment Cr", value=float(pr.get("option1_equipment_price_cr", 0)), step=0.01, key="og_p1e")
        pr["option1_install_lakhs"]       = st.number_input("Install Lakhs", value=float(pr.get("option1_install_lakhs", 0)), step=1.0, key="og_p1i")
        pr["option1_total_cr"]            = st.number_input("Total Cr", value=float(pr.get("option1_total_cr", 0)), step=0.01, key="og_p1t")
    with c2:
        st.markdown("**Option 2**")
        pr["option2_moc"]                 = st.text_input("MOC", value=pr.get("option2_moc", ""), key="og_p2m")
        pr["option2_equipment_price_cr"]  = st.number_input("Equipment Cr", value=float(pr.get("option2_equipment_price_cr", 0)), step=0.01, key="og_p2e")
        pr["option2_install_lakhs"]       = st.number_input("Install Lakhs", value=float(pr.get("option2_install_lakhs", 0)), step=1.0, key="og_p2i")
        pr["option2_total_cr"]            = st.number_input("Total Cr", value=float(pr.get("option2_total_cr", 0)), step=0.01, key="og_p2t")

    c1, c2 = st.columns(2)
    pr["location_dap"]        = c1.text_input("Location DAP", value=pr.get("location_dap", ""), key="og_ploc")
    pr["price_validity_days"] = c2.number_input("Validity Days", value=int(pr.get("price_validity_days", 15)),
                                                min_value=1, max_value=365, key="og_pval")

    st.markdown("**Payment Terms**")
    pt_txt = "\n".join(pr.get("payment_terms", []))
    new_pt = st.text_area("One per line", value=pt_txt, height=180, key="og_pt")
    pr["payment_terms"] = [l.strip() for l in new_pt.split("\n") if l.strip()]

    st.markdown("**Delivery Terms**")
    dt_txt = "\n".join(pr.get("delivery_terms", []))
    new_dt = st.text_area("One per line", value=dt_txt, height=120, key="og_dt")
    pr["delivery_terms"] = [l.strip() for l in new_dt.split("\n") if l.strip()]

    st.markdown("**Delivery Timeline**")
    tl = pr.get("delivery_timeline", {})
    tl1, tl2, tl3 = st.columns(3)
    tl["supply"]        = tl1.text_input("Supply (DAP)",    value=tl.get("supply", ""),        key="og_tl_sup")
    tl["installation"]  = tl2.text_input("Installation",    value=tl.get("installation", ""),  key="og_tl_inst")
    tl["commissioning"] = tl3.text_input("Commissioning",   value=tl.get("commissioning", ""), key="og_tl_comm")
    pr["delivery_timeline"] = tl
    


# ══════════════════════════════════════════════════════════════════════
# TAB 9 — Generate
# ══════════════════════════════════════════════════════════════════════
with tabs[8]:
    st.subheader("🚀 Generate Offer DOCX")
    m1, m2, m3 = st.columns(3)
    m1.metric("Client",   d["cover"].get("submitted_to", "—"))
    m2.metric("Capacity", f"{d['cover'].get('capacity_kld', '?')} KLD")
    m3.metric("Total",    f"₹{d['pricing'].get('option1_total_cr', 0):.2f} Cr")
    st.divider()

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        if st.button("🔨 Generate Offer DOCX", type="primary",
                     use_container_width=True, key="og_gen_docx_btn"):
            _recalc_economics(d["economics"], technical_specs=d.get("technical_specs"),
                              utilities=d.get("utilities"),
                              capacity_kld=d["cover"].get("capacity_kld"))
            with st.spinner("Loading brand assets…"):
                logo_bytes, tagline_bytes, hero_bytes = load_brand_assets()
            st.success("✅ Logo loaded") if logo_bytes else st.info("Logo not found — text-only header")
            with st.spinner("Building DOCX…"):
                try:
                    docx_bytes = generate_offer_docx(
                        d, logo_path=logo_bytes,
                        tagline_path=tagline_bytes, hero_path=hero_bytes)
                    st.session_state.og_generated_docx = docx_bytes
                    st.success(f"✅ DOCX generated: {len(docx_bytes)/1024:.1f} KB")
                except Exception as e:
                    st.error(f"Generation failed: {e}")
                    import traceback; st.code(traceback.format_exc())

    with col2:
        if st.button("💾 Save Final to DB", use_container_width=True,
                     key="og_save_final_btn"):
            _recalc_economics(d["economics"], technical_specs=d.get("technical_specs"),
                              utilities=d.get("utilities"),
                              capacity_kld=d["cover"].get("capacity_kld"))
            new_id, was_insert = _save_offer_to_db(
                d, status="final",
                offer_id=st.session_state.og_loaded_offer_id)
            if new_id:
                st.session_state.og_loaded_offer_id = new_id
                _mark_clean(d)
                st.success(f"✅ Offer {'created' if was_insert else 'updated'} as FINAL (id={new_id})")
                st.rerun()

    with col3:
        if st.button("🔄 New Offer", use_container_width=True, key="og_new_offer_gen_btn"):
            if dirty:
                st.session_state.og_pending_new = True
                st.rerun()
            else:
                _apply_new_offer()
                st.rerun()

    if "og_generated_docx" in st.session_state:
        qref = d["cover"].get("quote_ref", "offer").replace("/", "_")
        cap  = d["cover"].get("capacity_kld", "")
        st.download_button(
            label="📥 Download Offer DOCX",
            data=st.session_state.og_generated_docx,
            file_name=f"Quote_{qref}_{cap}KLD.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True, key="og_dl_docx")


# ══════════════════════════════════════════════════════════════════════
# TAB 10 — Import / Bridge
# ══════════════════════════════════════════════════════════════════════
with tabs[9]:
    st.subheader("📥 Templates & Process Design Bridge")

    with st.expander("📋 Excel Form Template", expanded=True):
        if st.button("Generate Excel Template", key="og_gen_xlsx"):
            st.session_state.og_xlsx = generate_form_template_xlsx()
        if "og_xlsx" in st.session_state:
            st.download_button(
                "📥 Download Template", st.session_state.og_xlsx,
                "BG_Offer_Form_Template.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="og_dl_xlsx")

    with st.expander("🔗 Import from bg_process_design Project", expanded=True):
        pd_projects = _load_pd_projects()
        if not pd_projects:
            st.info("No process design projects yet.")
        else:
            pd_names = ["— select a project —"] + [
                f"{p['project_code']} · {p['project_name']} ({p.get('capacity_kld','?')} KLD)"
                for p in pd_projects
            ]
            pd_sel = st.selectbox("Linked Process Design Project", pd_names, key="og_pd_sel")
            if pd_sel != "— select a project —":
                chosen_proj = pd_projects[pd_names.index(pd_sel) - 1]
                if st.button("🔀 Import technical specs", type="primary", key="og_bridge_btn"):
                    try:
                        from bg_process_design.utils.export_utils import build_full_project_export
                        process_json = build_full_project_export(conn, chosen_proj["id"])
                        new_data     = bridge_to_offer_data(process_json, existing_data=d)
                        _recalc_economics(new_data["economics"],
                                          technical_specs=new_data.get("technical_specs"),
                                          utilities=new_data.get("utilities"),
                                          capacity_kld=new_data["cover"].get("capacity_kld"))
                        st.session_state.og_offer_data    = new_data
                        st.session_state.og_linked_pd_id  = chosen_proj["id"]
                        st.session_state.og_form_version += 1
                        _clear_scope_editor_cache()
                        st.success("✅ Imported from process design project")
                        for line in summarize_bridge_result(process_json, new_data):
                            st.markdown(line)
                    except Exception as e:
                        st.error(f"Bridge failed: {e}")
                        import traceback; st.code(traceback.format_exc())

    with st.expander("📤 Upload full_project.json", expanded=False):
        uploaded = st.file_uploader("Upload JSON export", type=["json"], key="og_json_up")
        if uploaded:
            try:
                process_json = parse_process_design_json(uploaded.read().decode("utf-8"))
                if st.button("🔀 Import", key="og_up_btn"):
                    new_data = bridge_to_offer_data(process_json, existing_data=d)
                    _recalc_economics(new_data["economics"],
                                      technical_specs=new_data.get("technical_specs"),
                                      utilities=new_data.get("utilities"),
                                      capacity_kld=new_data["cover"].get("capacity_kld"))
                    st.session_state.og_offer_data    = new_data
                    st.session_state.og_form_version += 1
                    _clear_scope_editor_cache()
                    st.success("✅ Imported from JSON")
                    st.rerun()
            except Exception as e:
                st.error(f"Parse failed: {e}")
