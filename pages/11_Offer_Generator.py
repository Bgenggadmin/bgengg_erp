"""
Page 11 — B&G Offer Generator

Generates branded techno-commercial offer DOCX documents.
Password-gated. Reads logo from Supabase storage bucket.
Optionally links to process design projects via pd_project_id.

Tables written to:
  offers           (offer_data stored as JSONB)
  customer_master  (when adding new clients inline)
  anchor_projects  (only writes back offer_id when spawned from anchor)

Save behavior:
  - INSERT a new row when no offer is loaded
  - UPDATE the existing row when an offer is loaded
  - "💾 Save Draft" saves with status='draft'
  - "💾 Save Final to DB" saves with status='final'

Anchor integration:
  - "Spawn from Anchor Enquiry" section appears for Ammu's anchor entries
    that have a pd_project_id but no offer_id yet
"""
import sys, os
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import date, datetime, timezone
import json
import copy
import math

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
# CONNECTION + MODULE IMPORTS
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
# ECONOMICS CALCULATION
# ---------------------------------------------------------------------
def _recalc_economics(econ: dict, technical_specs: dict = None,
                      utilities: dict = None, capacity_kld: float = None) -> dict:
    hours = float(econ.get("operating_hours_day", 20) or 0)
    days  = float(econ.get("operating_days_year", 300) or 0)
    steam_cost = float(econ.get("steam_cost_inr_kg", 2.0) or 0)

    conv_kgh = float(econ.get("conventional_steam_kgh", 0) or 0)
    ecox_kgh = float(econ.get("ecox_steam_kgh", 0) or 0)
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
        utilities["power_consumption_kwh"] = round(total_power)
        utilities["cooling_water_m3h"]     = round(total_cw_m3)
    return econ


# ---------------------------------------------------------------------
# JSON SANITIZER — strip NaN / Infinity which JSONB rejects
# ---------------------------------------------------------------------
def _json_safe(obj):
    """
    Recursively replace NaN / +Inf / -Inf with None so the payload is
    valid JSON for Supabase's JSONB column.

    NaN typically sneaks in from st.data_editor (pandas) when a user adds
    a blank row or clears a numeric cell. pandas stores those as float NaN,
    which json.dumps(allow_nan=False) — used by the Supabase client — rejects.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    # pandas / numpy scalars sometimes report as float-like; catch by duck-typing
    try:
        # numpy floats
        import numpy as np  # local import; numpy is already a pandas dep
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


# ---------------------------------------------------------------------
# SUPABASE QUERIES
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
    """
    Ammu's anchor entries that have a pd_project_id (design exists)
    but no offer_id yet (no offer generated). These are ready to bridge.
    """
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
    """
    Ammu's anchor entries that ALREADY have an offer linked. Shown so users
    can jump straight back to their saved offer after logout, instead of
    re-spawning fresh defaults.
    """
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
    """
    Permanently delete an offer row. The anchor_projects.offer_id FK is
    ON DELETE SET NULL, so any linked anchor entry has its link cleared
    automatically (it becomes available to bridge again). No orphan rows.
    """
    try:
        _get_raw_client().table("offers").delete().eq("id", offer_id).execute()
        _load_offers_list.clear()
        _load_anchor_enquiries_for_bridge.clear()
        _load_anchor_enquiries_already_linked.clear()
        return True
    except Exception as e:
        st.error(f"Failed to delete offer #{offer_id}: {e}")
        return False


def _load_pd_project_by_id(pd_id: int):
    try:
        res = _get_raw_client().table("pd_projects").select("*").eq("id", pd_id).execute()
        if res.data:
            return res.data[0]
    except Exception as e:
        st.error(f"Failed to load pd_project #{pd_id}: {e}")
    return None


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


def _link_anchor_to_offer(anchor_id: int, offer_id: int) -> bool:
    """Write offer_id back to anchor_projects.id."""
    try:
        _get_raw_client().table("anchor_projects").update({
            "offer_id": offer_id,
        }).eq("id", anchor_id).execute()
        _load_anchor_enquiries_for_bridge.clear()
        _load_anchor_enquiries_already_linked.clear()
        return True
    except Exception as e:
        st.warning(f"Created offer but couldn't link back to anchor entry: {e}")
        return False


def _save_offer_to_db(data: dict, status: str = "final", offer_id: int = None,
                     pd_project_id=None):
    """Smart upsert. Returns (offer_id, was_insert) or (None, None) on failure."""
    try:
        # Strip NaN/Inf anywhere in the dict (e.g. blank rows from data_editor)
        data = _json_safe(copy.deepcopy(data))
        cov = data["cover"]
        pr = data["pricing"]

        # GUARD: block placeholder quote_ref. Saving multiple offers with the
        # same "XXXX" placeholder causes them to collide and overwrite each
        # other. Force a real, unique reference first.
        qref = (cov.get("quote_ref") or "").strip()
        if (not qref) or ("XXXX" in qref.upper()):
            st.error(
                "❌ Please set a real **Quote Reference** in Tab ① Cover & Client "
                "before saving. It still contains the placeholder `XXXX`. "
                "Each offer needs its own unique reference (e.g. "
                "`BG/ECOX-ZLD/26-27/2948 R0`), otherwise offers overwrite each other."
            )
            return (None, None)

        payload = {
            "quote_ref": qref,
            "client_id": data.get("_client_id"),
            "pd_project_id": pd_project_id or data.get("_pd_project_id"),
            "quote_date": cov["quote_date"],
            "capacity_kld": cov["capacity_kld"],
            "prepared_by": cov["prepared_by"],
            "offer_data": data,
            "option1_total_cr": pr["option1_total_cr"],
            "option2_total_cr": pr["option2_total_cr"],
            "price_validity_days": pr["price_validity_days"],
            "status": status,
        }

        if offer_id:
            res = _get_raw_client().table("offers").update(payload).eq("id", offer_id).execute()
            if res.data:
                _load_offers_list.clear()
                return (offer_id, False)
        else:
            # No offer_id in session — check if a row with this exact quote_ref
            # exists. If it does, that means the user is re-saving an offer whose
            # session lost track of its id (e.g. after a refresh). Adopt + update
            # it. Because we now block placeholder XXXX refs above, a quote_ref
            # match here is a genuine same-offer match, not an accidental collision.
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
                        f"ℹ️ Found an existing offer with this exact reference "
                        f"(id={existing_id}) and updated it. If you meant to create "
                        f"a *new* offer, change the Quote Reference in Tab ① first."
                    )
                    # Re-link anchor if applicable
                    anchor_id = data.get("_anchor_id")
                    if anchor_id:
                        _link_anchor_to_offer(anchor_id, existing_id)
                    return (existing_id, False)
                return (None, None)
            res = _get_raw_client().table("offers").insert(payload).execute()
            if res.data:
                _load_offers_list.clear()
                # If this offer was spawned from an anchor entry, link back
                anchor_id = data.get("_anchor_id")
                if anchor_id:
                    _link_anchor_to_offer(anchor_id, res.data[0]["id"])
                return (res.data[0]["id"], True)
    except Exception as e:
        st.error(f"Failed to save offer to DB: {e}")
    return (None, None)


# ---------------------------------------------------------------------
# DIRTY-TRACKING
# ---------------------------------------------------------------------
def _snapshot_for_dirty_check(data: dict) -> str:
    EXCLUDE_PATHS = {
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
    d2 = copy.deepcopy(data)
    for section, key in EXCLUDE_PATHS:
        if section in d2 and isinstance(d2[section], dict):
            d2[section].pop(key, None)
    try:
        return json.dumps(d2, sort_keys=True, default=str)
    except Exception:
        return ""


def _mark_clean(data: dict):
    st.session_state.og_saved_snapshot = _snapshot_for_dirty_check(data)
    st.session_state.og_last_saved_at = datetime.now(timezone.utc)
  def _clear_scope_editor_cache():
    """Clear cached DataFrames so data_editor reloads from the new offer."""
    for key in ["_df_src_og_sc_s", "_df_src_og_sc_m",
                "_df_src_og_sc_a", "_df_src_og_sc_i", "_df_src_og_sm"]:
        st.session_state.pop(key, None)


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
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 5: return "just now"
    if secs < 60: return f"{secs}s ago"
    mins = secs // 60
    if mins < 60: return f"{mins} min ago"
    hrs = mins // 60
    if hrs < 24: return f"{hrs} h {mins % 60} min ago"
    days = hrs // 24
    return f"{days} day{'s' if days > 1 else ''} ago"


# ---------------------------------------------------------------------
# BRIDGE FROM ANCHOR → PD → OFFER (in-memory build, no save yet)
# ---------------------------------------------------------------------
def _spawn_offer_from_anchor(anchor_row: dict) -> bool:
    """
    Given an anchor_projects row with pd_project_id set:
      1. Load the pd_project full export
      2. Bridge into offer_data
      3. Tag data with anchor_id and pd_project_id (saved later by save handler)
      4. Load into session_state, ready for the user to edit

    Returns True on success.
    """
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

    # Tag for save handler — these get pushed into the offers row on save
    new_data["_anchor_id"] = anchor_row["id"]
    new_data["_pd_project_id"] = pd_id

    # Pre-fill cover details from anchor entry
    cov = new_data["cover"]
    if anchor_row.get("client_name"):
        cov["submitted_to"] = f"M/s. {anchor_row['client_name']}"
    if anchor_row.get("contact_person"):
        cov["kind_attn"] = f"Mr. {anchor_row['contact_person']}"
    if anchor_row.get("contact_phone"):
        cov["contact_details"] = anchor_row["contact_phone"]
    # Generate a unique quote_ref so two spawns never collide on the XXXX
    # placeholder. Prefer the anchor job_no; fall back to the anchor id.
    job = str(anchor_row.get("job_no") or "").strip()
    suffix = job if job else f"ANC{anchor_row['id']}"
    cov["quote_ref"] = f"BG/ECOX-ZLD/26-27/{suffix} R0"

    # Recompute everything
    _recalc_economics(new_data["economics"],
                      technical_specs=new_data.get("technical_specs"),
                      utilities=new_data.get("utilities"),
                      capacity_kld=new_data["cover"].get("capacity_kld"))

    st.session_state.og_offer_data = new_data
    st.session_state.og_loaded_offer_id = None  # not yet saved → INSERT path
    _mark_clean(new_data)
    st.session_state.og_last_saved_at = None
    return True


def build_full_project_export_from_offer_side(pd_id: int):
    """Wrapper that imports build_full_project_export only when needed."""
    from bg_process_design.utils.export_utils import build_full_project_export
    return build_full_project_export(conn, pd_id)


# ---------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------
if "og_offer_data" not in st.session_state:
    st.session_state.og_offer_data = default_offer_data()
if "og_form_version" not in st.session_state:
    st.session_state.og_form_version = 0
if "og_loaded_offer_id" not in st.session_state:
    st.session_state.og_loaded_offer_id = None
if "og_last_saved_at" not in st.session_state:
    st.session_state.og_last_saved_at = None
if "og_saved_snapshot" not in st.session_state:
    st.session_state.og_saved_snapshot = _snapshot_for_dirty_check(
        st.session_state.og_offer_data
    )


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


# ---------------------------------------------------------------------
# Schema backfill BEFORE any tab renders
# ---------------------------------------------------------------------
d = st.session_state.og_offer_data

d.setdefault("cover", {})
d["cover"].setdefault("capacity_kld", 150)

econ_defaults = {
    "operating_hours_day": 20,
    "operating_days_year": 300,
    "steam_cost_inr_kg": 2.0,
    "power_cost_inr_kwh": 9.0,
    "cooling_water_cost_inr_m3": 90.0,
    "effluent_treatment_cost_inr_kl": 1185.0,
    "conventional_steam_kgh": 0,
    "ecox_steam_kgh": 0,
}
d.setdefault("economics", {})
for k, v in econ_defaults.items():
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

_recalc_economics(
    d["economics"],
    technical_specs=d["technical_specs"],
    utilities=d["utilities"],
    capacity_kld=d["cover"].get("capacity_kld"),
)


# ---------------------------------------------------------------------
# TOP STATUS BAR
# ---------------------------------------------------------------------
dirty = _is_dirty(d)
loaded_id = st.session_state.og_loaded_offer_id
last_saved = st.session_state.og_last_saved_at

bar_c1, bar_c2, bar_c3, bar_c4 = st.columns([3, 2, 2, 1])

with bar_c1:
    if loaded_id:
        st.markdown(
            f"📂 **Editing offer #{loaded_id}** — "
            f"`{d['cover'].get('quote_ref', '')}`"
        )
    elif d.get("_anchor_id"):
        st.markdown(
            f"🔗 **New offer from anchor #{d['_anchor_id']}** — "
            f"not yet saved"
        )
    else:
        st.markdown("📝 **New offer** (not yet saved)")

with bar_c2:
    if last_saved:
        st.markdown(f"💾 Last saved: **{_time_since(last_saved)}**")
    else:
        st.markdown("💾 Last saved: **never**")

with bar_c3:
    if dirty:
        if st.button("💾 Save Draft", type="primary", use_container_width=True,
                     key="og_save_draft_top"):
            new_id, was_insert = _save_offer_to_db(
                d, status="draft",
                offer_id=st.session_state.og_loaded_offer_id,
            )
            if new_id:
                st.session_state.og_loaded_offer_id = new_id
                _mark_clean(d)
                st.success(
                    f"✅ Draft {'created' if was_insert else 'updated'} (id={new_id})"
                )
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


# ---------- Tab 1: Cover & Client ----------
with tabs[0]:
    fv = st.session_state.og_form_version  # ← ADD THIS LINE HERE
    d = st.session_state.og_offer_data
    cov = d["cover"]
    # ====== OPEN EXISTING OFFER ======
    with st.expander("📂 Open Existing Offer", expanded=not loaded_id and not d.get("_anchor_id")):
        offers_list = _load_offers_list()
        clients_map = {c["id"]: c["name"] for c in _load_clients()}

        if not offers_list:
            st.info("No saved offers yet. Fill in the form below and click **💾 Save Draft** to create one.")
        else:
            def _fmt_offer(o):
                client_name = clients_map.get(o.get("client_id"), "—") if o.get("client_id") else "—"
                status_emoji = "📝" if o.get("status") == "draft" else "✅"
                updated = o.get("updated_at") or o.get("created_at") or ""
                updated_short = str(updated)[:16].replace("T", " ")
                cap = o.get("capacity_kld") or "?"
                price = o.get("option1_total_cr")
                price_str = f" · ₹{price:.2f}Cr" if price else ""
                return (
                    f"{status_emoji} #{o['id']} · {o['quote_ref']} · "
                    f"{client_name} · {cap} KLD{price_str} · {updated_short}"
                )

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
                        chosen = offers_list[sel_idx - 1]
                        full_row = _load_offer_by_id(chosen["id"])
                        if full_row and full_row.get("offer_data"):
                            st.session_state.og_offer_data = full_row["offer_data"]
                            st.session_state.og_loaded_offer_id = full_row["id"]
                            st.session_state.og_form_version += 1
                            _clear_scope_editor_cache()
                            _mark_clean(st.session_state.og_offer_data)
                            st.success(f"✅ Opened offer #{full_row['id']}")
                            st.rerun()
                        else:
                            st.error("Could not load this offer.")
            with cols[1]:
                if loaded_id or d.get("_anchor_id"):
                    if st.button("🆕 New Offer", disabled=False, use_container_width=True,
                                 key="og_new_offer_btn"):
                        if dirty:
                            st.session_state.og_pending_new = True
                            st.rerun()
                        else:
                            st.session_state.og_offer_data = default_offer_data()
                            st.session_state.og_loaded_offer_id = None
                            _mark_clean(st.session_state.og_offer_data)
                            st.session_state.og_last_saved_at = None
                            st.rerun()
            with cols[2]:
                # Delete with a two-click confirm popover so it can't fire by accident
                with st.popover("🗑️ Delete", disabled=(sel_idx == 0),
                                use_container_width=True):
                    if sel_idx != 0:
                        target = offers_list[sel_idx - 1]
                        st.warning(
                            f"Permanently delete offer **#{target['id']}** "
                            f"(`{target['quote_ref']}`)? This cannot be undone. "
                            f"If it's linked to an anchor enquiry, that link will be "
                            f"cleared and the enquiry becomes available to bridge again."
                        )
                        if st.button("⚠️ Yes, delete permanently",
                                     type="primary", key="og_delete_confirm_btn"):
                            del_id = target["id"]
                            if _delete_offer(del_id):
                                # If we were editing the deleted offer, reset to a fresh form
                                if st.session_state.og_loaded_offer_id == del_id:
                                    st.session_state.og_offer_data = default_offer_data()
                                    st.session_state.og_loaded_offer_id = None
                                    _mark_clean(st.session_state.og_offer_data)
                                    st.session_state.og_last_saved_at = None
                                st.success(f"🗑️ Deleted offer #{del_id}")
                                st.rerun()

            if st.session_state.get("og_pending_load_id"):
                pid = st.session_state.og_pending_load_id
                st.warning(f"⚠️ You have unsaved changes. Opening offer #{pid} will discard them. Continue?")
                pc1, pc2 = st.columns(2)
                if pc1.button("✅ Yes, discard and open", key="og_pending_yes"):
                    full_row = _load_offer_by_id(pid)
                    if full_row and full_row.get("offer_data"):
                        st.session_state.og_offer_data = full_row["offer_data"]
                        st.session_state.og_loaded_offer_id = full_row["id"]
                        st.session_state.og_form_version += 1
                        _clear_scope_editor_cache()
                        _mark_clean(st.session_state.og_offer_data)
                    st.session_state.pop("og_pending_load_id", None)
                    st.rerun()
                if pc2.button("❌ Cancel", key="og_pending_no"):
                    st.session_state.pop("og_pending_load_id", None)
                    st.rerun()

            if st.session_state.get("og_pending_new"):
                st.warning("⚠️ You have unsaved changes. Starting a new offer will discard them. Continue?")
                pn1, pn2 = st.columns(2)
                if pn1.button("✅ Yes, discard and start new", key="og_new_yes"):
                    st.session_state.og_offer_data = default_offer_data()
                    st.session_state.og_loaded_offer_id = None
                    st.session_state.og_form_version += 1
                    _clear_scope_editor_cache()
                    _mark_clean(st.session_state.og_offer_data)
                    st.session_state.og_last_saved_at = None
                    st.session_state.pop("og_pending_new", None)
                    st.rerun()
                if pn2.button("❌ Cancel", key="og_new_no"):
                    st.session_state.pop("og_pending_new", None)
                    st.rerun()

    # ====== SPAWN FROM ANCHOR ENQUIRY (NEW) ======
    with st.expander("🔗 Spawn Offer from Anchor Enquiry (Ammu · MEE projects)",
                     expanded=False):
        st.caption(
            "Shows Ammu's anchor enquiries that already have a Process Design "
            "linked but no offer yet. Selecting one bridges the design data into "
            "a new offer (not saved until you click Save Draft / Save Final)."
        )
        anchor_bridge_rows = _load_anchor_enquiries_for_bridge()
        if not anchor_bridge_rows:
            st.info(
                "No anchor enquiries ready to bridge. "
                "An enquiry is ready when it has a linked Process Design but no offer yet — "
                "spawn one from Tab 🧪 Process Design first."
            )
        else:
            def _fmt_anchor(r):
                client = r.get("client_name") or "?"
                desc = (r.get("project_description") or "")[:40]
                job = r.get("job_no") or "—"
                dt = str(r.get("enquiry_date") or "")[:10]
                return (
                    f"Anchor #{r['id']} · {client} · {desc} · "
                    f"Job {job} · pd_project #{r['pd_project_id']} · {dt}"
                )

            opts = ["— select an enquiry —"] + [_fmt_anchor(r) for r in anchor_bridge_rows]
            sel_idx = st.selectbox(
                f"Ammu's enquiries ready to bridge ({len(anchor_bridge_rows)} found)",
                range(len(opts)),
                format_func=lambda i: opts[i],
                key="og_anchor_bridge_sel",
            )
            if st.button("🔀 Bridge to Offer", type="primary",
                         disabled=(sel_idx == 0),
                         key="og_anchor_bridge_btn"):
                if dirty:
                    st.warning("⚠️ Save your current changes first, or discard them via 🆕 New Offer.")
                else:
                    chosen = anchor_bridge_rows[sel_idx - 1]
                    if _spawn_offer_from_anchor(chosen):
                        st.success(
                            f"✅ Bridged anchor #{chosen['id']} → pd_project "
                            f"#{chosen['pd_project_id']} into new offer. "
                            f"Review the form, then set a Quote Reference and click 💾 Save Draft."
                        )
                        st.rerun()

        # ----- Already-generated offers (re-open saved work) -----
        linked_rows = _load_anchor_enquiries_already_linked()
        if linked_rows:
            st.divider()
            st.markdown("**↩️ Already generated an offer? Re-open your saved work:**")
            st.caption(
                "After logout, anchor enquiries that already have an offer no longer "
                "appear in the bridge list above (to avoid duplicates). Open the saved "
                "offer directly here — it has all your Scope of Supply data."
            )
            def _fmt_linked(r):
                client = r.get("client_name") or "?"
                desc = (r.get("project_description") or "")[:35]
                return f"Anchor #{r['id']} · {client} · {desc} · → offer #{r['offer_id']}"

            lopts = ["— select —"] + [_fmt_linked(r) for r in linked_rows]
            lsel = st.selectbox(
                f"Linked offers ({len(linked_rows)})",
                range(len(lopts)),
                format_func=lambda i: lopts[i],
                key="og_anchor_linked_sel",
            )
            if st.button("📂 Open Saved Offer", disabled=(lsel == 0),
                         key="og_anchor_linked_open"):
                if dirty:
                    st.warning("⚠️ Save or discard current changes first (🆕 New Offer).")
                else:
                    target = linked_rows[lsel - 1]
                    full_row = _load_offer_by_id(target["offer_id"])
                    if full_row and full_row.get("offer_data"):
                        st.session_state.og_offer_data = full_row["offer_data"]
                        st.session_state.og_loaded_offer_id = full_row["id"]
                        st.session_state.og_form_version += 1
                        _clear_scope_editor_cache()
                        _mark_clean(st.session_state.og_offer_data)
                        st.success(f"✅ Opened saved offer #{full_row['id']}")
                        st.rerun()
                    else:
                        st.error(
                            f"Anchor #{target['id']} points to offer "
                            f"#{target['offer_id']} but it couldn't be loaded."
                        )

    st.divider()

    # ====== COVER & CLIENT FIELDS ======
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
        elif d.get("_client_id"):
            for i, c in enumerate(clients):
                if c["id"] == d["_client_id"]:
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
        cov["quote_ref"] = st.text_input("Quote Reference", value=cov["quote_ref"], key=f"11_Offer_Generator_text_input_2_{fv}")
        cov["quote_date"] = st.text_input("Quote Date (YYYY-MM-DD)", value=str(cov["quote_date"]), key=f"11_Offer_Generator_text_input_3_{fv}")
        cov["submitted_to"] = st.text_input("Submitted to", value=cov["submitted_to"], key=f"11_Offer_Generator_text_input_4_{fv}")
        cov["location"] = st.text_input("Location", value=cov["location"], key=f"11_Offer_Generator_text_input_5_{fv}")
        cov["capacity_kld"] = st.number_input("Capacity (KLD)", value=int(cov["capacity_kld"]), min_value=1, max_value=5000, step=1, key=f"11_Offer_Generator_number_input_6_{fv}")
    with c2:
        cov["prepared_by"] = st.text_input("Prepared By", value=cov["prepared_by"], key=f"11_Offer_Generator_text_input_7_{fv}")
        cov["contact_details"] = st.text_input("Contact", value=cov["contact_details"], key=f"11_Offer_Generator_text_input_8_{fv}")
        cov["email"] = st.text_input("E-mail", value=cov["email"], key=f"11_Offer_Generator_text_input_9_{fv}")
        cov["kind_attn"] = st.text_input("Kind Attention", value=cov["kind_attn"], key=f"11_Offer_Generator_text_input_10_{fv}")
        cov["discussion_date"] = st.text_input("Discussion Date", value=cov["discussion_date"], key=f"11_Offer_Generator_text_input_11_{fv}")

    cov["subject"] = st.text_input("Subject Line", value=cov["subject"], key=f"11_Offer_Generator_text_input_12_{fv}")


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

    st.markdown("### Overall Parameters")
    op1, op2, op3 = st.columns(3)
    with op1:
        econ["operating_hours_day"] = st.number_input("Operating Hours per Day (h)",
            value=float(econ["operating_hours_day"]), min_value=1.0, max_value=24.0, step=1.0, key="og_e_ophrs")
    with op2:
        econ["operating_days_year"] = st.number_input("Days of Operation per Year",
            value=int(econ["operating_days_year"]), min_value=1, max_value=365, step=1, key="og_e_days")
    with op3:
        econ["effluent_treatment_cost_inr_kl"] = st.number_input("Effluent Treatment Cost (₹/KL)",
            value=float(econ["effluent_treatment_cost_inr_kl"]), min_value=0.0, step=1.0, format="%.2f", key="og_e_eff_cost")

    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        econ["steam_cost_inr_kg"] = st.number_input("Steam Cost (₹/kg)",
            value=float(econ["steam_cost_inr_kg"]), min_value=0.0, step=0.1, format="%.2f", key="og_e_steam_rate")
    with cc2:
        econ["power_cost_inr_kwh"] = st.number_input("Power Cost (₹/kWh)",
            value=float(econ["power_cost_inr_kwh"]), min_value=0.0, step=0.5, format="%.2f", key="og_e_pwr_rate")
    with cc3:
        econ["cooling_water_cost_inr_m3"] = st.number_input("Cooling Water Cost (₹/m³)",
            value=float(econ["cooling_water_cost_inr_m3"]), min_value=0.0, step=1.0, format="%.2f", key="og_e_cw_rate")

    st.divider()
    st.markdown("### Steam Comparison — BG ECOX-ZLD Advantage")
    st.caption("Enter MEE steam consumption for conventional and ECOX-ZLD systems.")
    si1, si2 = st.columns(2)
    with si1:
        econ["conventional_steam_kgh"] = st.number_input("Conventional — MEE Steam (kg/h)",
            value=float(econ.get("conventional_steam_kgh", 0) or 0), min_value=0.0, step=1.0, key="og_e_conv_kgh")
    with si2:
        econ["ecox_steam_kgh"] = st.number_input("ECOX-ZLD — MEE Steam (kg/h)",
            value=float(econ.get("ecox_steam_kgh", 0) or 0), min_value=0.0, step=1.0, key="og_e_ecox_kgh")

    _recalc_economics(econ, technical_specs=d["technical_specs"],
                      utilities=d["utilities"], capacity_kld=d["cover"].get("capacity_kld"))

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

    st.info("💡 Total Steam/Power/CW and Annual Operational Cost are displayed at the bottom of Tab ⑤ Technical.")

    with st.expander("ℹ️ Formula reference", expanded=False):
        st.markdown("""
- **Annual (t/yr)** = (Steam kg/h × Operating hours × Days per year) ÷ 1000
- **Cost (Cr/yr)** = (Annual t/yr × Steam Cost ₹/kg) ÷ 10,000
- **Reduction %** = ((Conv. steam − ECOX steam) ÷ Conv. steam) × 100
- **Savings (t/yr)** = Conv. annual − ECOX annual
- **Savings (Lakhs/yr)** = (Conv. cost Cr − ECOX cost Cr) × 100
- **Annual Operational Cost (₹/yr)** = Effluent Cost (₹/KL) × Capacity (KLD) × Days/year
""")


# ---------- Tab 5: Technical ----------
with tabs[4]:
    st.subheader("PART V — Technical Details & Utilities")
    fp = d["feed_parameters"]
    ts = d["technical_specs"]

    with st.expander("📋 Feed Parameters", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            fp["capacity_kld"] = st.number_input("Feed / Capacity (KLD)",
                value=int(fp["capacity_kld"]), min_value=1, max_value=5000, step=1, key="t_cap")
            fp["feed_ph"] = st.text_input("Feed pH", value=str(fp["feed_ph"]), key="t_ph")
            fp["specific_gravity"] = st.text_input("Specific Gravity",
                value=str(fp.get("specific_gravity", "1.0")), key="t_sg")
            fp["total_cod_ppm"] = st.number_input("Total COD (PPM)",
                value=int(fp["total_cod_ppm"]), step=1, key="t_cod")
            fp["volatile_organic_solvents_ppm"] = st.number_input("Volatile Organic Solvents (PPM)",
                value=int(fp.get("volatile_organic_solvents_ppm", 0)), step=1, key="t_vos")
            fp["total_solids_pct"] = st.text_input("Total Solids (% w/w)",
                value=str(fp["total_solids_pct"]), key="t_ts")
        with c2:
            fp["suspended_solids_ppm"] = st.text_input("Suspended Solids (PPM)",
                value=str(fp.get("suspended_solids_ppm", "")), key="t_ss")
            fp["feed_temp_c"] = st.number_input("Feed Temperature (°C)",
                value=int(fp["feed_temp_c"]), step=1, key="t_T")
            fp["total_hardness_ppm"] = st.text_input("Total Hardness (PPM)",
                value=str(fp.get("total_hardness_ppm", "")), key="t_th")
            fp["silica_ppm"] = st.text_input("Silica (PPM)",
                value=str(fp.get("silica_ppm", "")), key="t_si")
            fp["free_chloride_ppm"] = st.text_input("Free Chloride (PPM)",
                value=str(fp.get("free_chloride_ppm", "")), key="t_cl")
            fp["feed_nature"] = st.text_input("Feed Nature", value=fp["feed_nature"], key="t_nat")

    with st.expander("⚙️ Stripper System", expanded=True):
        s = ts["stripper"]
        s["type"] = st.text_input("Type", value=s.get("type", "Tray Type Column"), key="ts_s_type")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Process Flows**")
            s["feed_kgh"] = st.number_input("Inlet Feed Rate (kg/h)", value=int(s.get("feed_kgh", 0)), step=1, key="ts_s_feed")
            s["distillate_kgh"] = st.number_input("Top Distillate Out (kg/h)", value=int(s.get("distillate_kgh", 0)), step=1, key="ts_s_dist")
            s["distillate_composition"] = st.text_input("Distillate Composition", value=s.get("distillate_composition", ""), key="ts_s_dc")
            s["bottoms_kgh"] = st.number_input("Stripper Bottom Out (kg/h)", value=int(s.get("bottoms_kgh", 0)), step=1, key="ts_s_bot")
            s["reflux_kgh"] = st.number_input("Reflux Rate (kg/h)", value=int(s.get("reflux_kgh", 0)), step=1, key="ts_s_ref")
        with c2:
            st.markdown("**Utilities**")
            s["steam_pressure"] = st.text_input("Steam Pressure", value=s.get("steam_pressure", "1.5 Bar-g"), key="ts_s_sp")
            s["steam_kgh"] = st.number_input("Dry & Saturated Steam (kg/h)", value=int(s.get("steam_kgh", 0)), step=1, key="ts_s_st")
            s["power_kwh"] = st.number_input("Power Consumption (kWh)", value=int(s.get("power_kwh", 0)), step=1, key="ts_s_pw")
            cc1, cc2 = st.columns(2)
            s["cooling_water_m3h"] = cc1.number_input("Cooling Water (m³/h)", value=int(s.get("cooling_water_m3h", 0)), step=1, key="ts_s_cw")
            s["cooling_water_tr"] = cc2.number_input("Cooling Water (TR)", value=int(s.get("cooling_water_tr", 0)), step=1, key="ts_s_cw_tr")
            s["cooling_water_temps"] = st.text_input("Cooling Water Temps", value=s.get("cooling_water_temps", "In/Out: 32 / 38 °C"), key="ts_s_cwt")
            cc3, cc4 = st.columns(2)
            s["compressed_air_nm3h"] = cc3.text_input("Compressed Air (Nm³/h)", value=str(s.get("compressed_air_nm3h", "8")), key="ts_s_ca")
            s["compressed_air_pressure"] = cc4.text_input("CA Pressure", value=s.get("compressed_air_pressure", "6 Bar-g"), key="ts_s_cap")

    with st.expander("⚙️ Multiple Effect Evaporator System", expanded=True):
        m = ts["mee"]
        c0a, c0b = st.columns(2)
        m["type"] = c0a.text_input("Type", value=m.get("type", "4-Effect Multiple Effect Evaporator"), key="ts_m_type")
        m["configuration"] = c0b.text_input("Configuration", value=m.get("configuration", "Forced Circulation Type"), key="ts_m_cfg")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Process Flows**")
            m["feed_kgh"] = st.number_input("Feed Inlet — Stripper Bottom (kg/h)", value=int(m.get("feed_kgh", 0)), step=1, key="ts_m_feed")
            m["feed_solids_pct"] = st.text_input("Feed Solids (%)", value=str(m.get("feed_solids_pct", "")), key="ts_m_fs")
            m["evaporation_kgh"] = st.number_input("Water Evaporation Rate (kg/h)", value=int(m.get("evaporation_kgh", 0)), step=1, key="ts_m_evap")
            m["concentrate_kgh"] = st.number_input("MEE Concentrate Out (kg/h)", value=int(m.get("concentrate_kgh", 0)), step=1, key="ts_m_conc")
            m["concentrate_solids_pct"] = st.number_input("Concentrate Out (%)", value=int(m.get("concentrate_solids_pct", 40)), min_value=0, max_value=100, step=1, key="ts_m_cs")
        with c2:
            st.markdown("**Utilities**")
            m["steam_pressure"] = st.text_input("Steam Pressure", value=m.get("steam_pressure", "1.5 Bar-g"), key="ts_m_sp")
            m["steam_kgh"] = st.number_input("Dry & Saturated Steam (kg/h)", value=int(m.get("steam_kgh", 0)), step=1, key="ts_m_st")
            m["steam_economy"] = st.number_input("Steam Economy (kg/kg)", value=float(m.get("steam_economy", 4.3)), min_value=0.0, step=0.1, format="%.2f", key="ts_m_se")
            m["power_kwh"] = st.number_input("Power Consumption (kWh)", value=int(m.get("power_kwh", 0)), step=1, key="ts_m_pw")
            cc1, cc2 = st.columns(2)
            m["cooling_water_m3h"] = cc1.number_input("Cooling Water (m³/h)", value=int(m.get("cooling_water_m3h", 0)), step=1, key="ts_m_cw")
            m["cooling_water_tr"] = cc2.number_input("Cooling Water (TR)", value=int(m.get("cooling_water_tr", 0)), step=1, key="ts_m_cw_tr")
            m["cooling_water_temps"] = st.text_input("Cooling Water Temps", value=m.get("cooling_water_temps", "In/Out: 32 / 38 °C"), key="ts_m_cwt")
            cc3, cc4 = st.columns(2)
            m["compressed_air_nm3h"] = cc3.text_input("Compressed Air (Nm³/h)", value=str(m.get("compressed_air_nm3h", "8-10")), key="ts_m_ca")
            m["compressed_air_pressure"] = cc4.text_input("CA Pressure", value=m.get("compressed_air_pressure", "6 Bar-g"), key="ts_m_cap")

    with st.expander("⚙️ Agitated Thin Film Dryer (ATFD)", expanded=True):
        a = ts["atfd"]
        a["type"] = st.text_input("Type", value=a.get("type", "Agitated Thin Film Dryer"), key="ts_a_type")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Process Flows**")
            a["feed_kgh"] = st.number_input("Feed Inlet — MEE Concentrate (kg/h)", value=int(a.get("feed_kgh", 0)), step=1, key="ts_a_feed")
            a["feed_solids_pct"] = st.number_input("Feed Solids (%)", value=int(a.get("feed_solids_pct", 40)), min_value=0, max_value=100, step=1, key="ts_a_fs")
            a["evaporation_kgh"] = st.number_input("Water Evaporation Rate (kg/h)", value=int(a.get("evaporation_kgh", 0)), step=1, key="ts_a_evap")
            a["product_kgh"] = st.number_input("ATFD Product Out (kg/h)", value=int(a.get("product_kgh", 0)), step=1, key="ts_a_prod")
            a["product_moisture_pct"] = st.text_input("Moisture in ATFD Product (%)", value=str(a.get("product_moisture_pct", "8-10")), key="ts_a_pm")
        with c2:
            st.markdown("**Utilities**")
            a["steam_pressure"] = st.text_input("Steam Pressure", value=a.get("steam_pressure", "1.5 Bar-g"), key="ts_a_sp")
            a["steam_kgh"] = st.number_input("Dry & Saturated Steam (kg/h)", value=int(a.get("steam_kgh", 0)), step=1, key="ts_a_st")
            a["power_kwh"] = st.number_input("Power Consumption (kWh)", value=int(a.get("power_kwh", 0)), step=1, key="ts_a_pw")
            cc1, cc2 = st.columns(2)
            a["cooling_water_m3h"] = cc1.number_input("Cooling Water (m³/h)", value=int(a.get("cooling_water_m3h", 0)), step=1, key="ts_a_cw")
            a["cooling_water_tr"] = cc2.number_input("Cooling Water (TR)", value=int(a.get("cooling_water_tr", 0)), step=1, key="ts_a_cw_tr")
            a["cooling_water_temps"] = st.text_input("Cooling Water Temps", value=a.get("cooling_water_temps", "In/Out: 32 / 38 °C"), key="ts_a_cwt")
            cc3, cc4 = st.columns(2)
            a["compressed_air_nm3h"] = cc3.text_input("Compressed Air (Nm³/h)", value=str(a.get("compressed_air_nm3h", "8")), key="ts_a_ca")
            a["compressed_air_pressure"] = cc4.text_input("CA Pressure", value=a.get("compressed_air_pressure", "6 Bar-g"), key="ts_a_cap")

    ut = d["utilities"]
    ut["stripper_steam"] = {"param": f"{ts['stripper']['steam_pressure']}, >96% dryness", "value_kgh": ts["stripper"]["steam_kgh"]}
    ut["mee_steam"] = {"param": f"{ts['mee']['steam_pressure']}, >96% dryness", "value_kgh": ts["mee"]["steam_kgh"], "steam_economy": ts["mee"]["steam_economy"]}
    ut["atfd_steam"] = {"param": f"{ts['atfd']['steam_pressure']}, >96% dryness", "value_kgh": ts["atfd"]["steam_kgh"]}

    _recalc_economics(d["economics"], technical_specs=ts, utilities=ut, capacity_kld=d["cover"].get("capacity_kld"))

    st.divider()
    st.markdown("### Plant-Wide Totals (computed from per-unit values above)")
    tc1, tc2, tc3 = st.columns(3)
    tc1.metric("Total Steam Consumption", f"{ut['total_steam_kgh']} kg/h", help="Stripper + MEE + ATFD")
    tc2.metric("Total Power Consumption", f"{ut['total_power_kwh']} kWh", help="Sum of per-unit power")
    tc3.metric("Total Cooling Water", f"{ut['total_cooling_water_m3h']} m³/h", f"{ut['total_cooling_water_tr']} TR")

    st.markdown("### Overall System Operational Cost")
    cap = d["cover"].get("capacity_kld", 0)
    e = d["economics"]
    osc1, osc2, osc3, osc4 = st.columns(4)
    osc1.metric("Plant Capacity", f"{cap} KLD")
    osc2.metric("Total Steam", f"{ut['total_steam_kgh']} kg/h")
    osc3.metric("Total Power", f"{ut['total_power_kwh']} kWh")
    osc4.metric("Total CW", f"{ut['total_cooling_water_m3h']} m³/h", f"{ut['total_cooling_water_tr']} TR")
    osc5, osc6 = st.columns(2)
    osc5.metric("Effluent Treatment Cost", f"₹{e['effluent_treatment_cost_inr_kl']:,.0f}/KL")
    osc6.metric("Annual Operational Cost", f"₹{e['annual_operational_cost_inr']:,.0f}/yr")

    with st.expander("🎯 Performance Guarantee (bullet points)", expanded=False):
        txt = "\n".join(d.get("performance_guarantee", []))
        new_pg = st.text_area("One bullet per line", value=txt, height=120, key="og_pg")
        d["performance_guarantee"] = [l.strip() for l in new_pg.split("\n") if l.strip()]


# ---------- Tab 6: Scope of Supply ----------
with tabs[5]:
    import pandas as pd
    st.subheader("PART VI — Scope of Supply")

    def _editor_records(records, key, col_order):
        # Use session_state as the source of truth once the widget exists.
        # This prevents the DataFrame being rebuilt from the dict on every
        # rerun, which is what causes the first-edit revert.
        ss_key = f"_df_src_{key}"
        if ss_key not in st.session_state:
            df = pd.DataFrame(records)
            for c in col_order:
                if c not in df.columns:
                    df[c] = ""
            df = df[col_order] if not df.empty else pd.DataFrame(columns=col_order)
            df = df.reset_index(drop=True)
            st.session_state[ss_key] = df
        else:
            # Only rebuild from records if the number of rows changed
            # (e.g. a new offer was loaded), not on every widget interaction.
            existing = st.session_state[ss_key]
            if len(existing) != len(records):
                df = pd.DataFrame(records)
                for c in col_order:
                    if c not in df.columns:
                        df[c] = ""
                df = df[col_order] if not df.empty else pd.DataFrame(columns=col_order)
                df = df.reset_index(drop=True)
                st.session_state[ss_key] = df

        edited = st.data_editor(st.session_state[ss_key], use_container_width=True,
                                num_rows="dynamic", key=key)
        cleaned = edited.where(pd.notnull(edited), "")
        result = cleaned.to_dict("records")
        # Keep session_state in sync with edits
        st.session_state[ss_key] = cleaned.reset_index(drop=True)
        return result

    _SCOPE_COLS = ["equipment", "specification", "qty", "bg_scope", "buyer_scope"]
    _INSTR_COLS = ["item", "qty", "scope"]

    sub = st.tabs(["Stripper", "MEE", "ATFD", "Instruments"])
    with sub[0]:
        d["scope_stripper"] = _editor_records(d["scope_stripper"], "og_sc_s", _SCOPE_COLS)
    with sub[1]:
        d["scope_mee"] = _editor_records(d["scope_mee"], "og_sc_m", _SCOPE_COLS)
    with sub[2]:
        d["scope_atfd"] = _editor_records(d["scope_atfd"], "og_sc_a", _SCOPE_COLS)
    with sub[3]:
        d["instruments"] = _editor_records(d["instruments"], "og_sc_i", _INSTR_COLS)


# ---------- Tab 7: Scope Matrix ----------
with tabs[6]:
    import pandas as pd
    st.subheader("PART VII & VIII")

    def _editor_records_sm(records, key, col_order):
        ss_key = f"_df_src_{key}"
        if ss_key not in st.session_state:
            df = pd.DataFrame(records)
            for c in col_order:
                if c not in df.columns:
                    df[c] = ""
            df = df[col_order] if not df.empty else pd.DataFrame(columns=col_order)
            df = df.reset_index(drop=True)
            st.session_state[ss_key] = df
        else:
            existing = st.session_state[ss_key]
            if len(existing) != len(records):
                df = pd.DataFrame(records)
                for c in col_order:
                    if c not in df.columns:
                        df[c] = ""
                df = df[col_order] if not df.empty else pd.DataFrame(columns=col_order)
                df = df.reset_index(drop=True)
                st.session_state[ss_key] = df

        edited = st.data_editor(st.session_state[ss_key], use_container_width=True,
                                num_rows="dynamic", key=key)
        cleaned = edited.where(pd.notnull(edited), "")
        result = cleaned.to_dict("records")
        st.session_state[ss_key] = cleaned.reset_index(drop=True)
        return result

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
            _recalc_economics(d["economics"], technical_specs=d.get("technical_specs"),
                              utilities=d.get("utilities"), capacity_kld=d["cover"].get("capacity_kld"))
            with st.spinner("Loading brand assets from Supabase..."):
                logo_bytes, tagline_bytes, hero_bytes = load_brand_assets()
            if logo_bytes:
                st.success("✅ Logo loaded from Supabase")
            else:
                st.info("Logo not found — DOCX will render text-only header")
            with st.spinner("Building DOCX..."):
                try:
                    docx_bytes = generate_offer_docx(d, logo_path=logo_bytes,
                                                     tagline_path=tagline_bytes, hero_path=hero_bytes)
                    st.session_state.og_generated_docx = docx_bytes
                    st.success(f"✅ DOCX generated: {len(docx_bytes)/1024:.1f} KB")
                except Exception as e:
                    st.error(f"Generation failed: {e}")
                    import traceback
                    st.code(traceback.format_exc())

    with col2:
        if st.button("💾 Save Final to DB", use_container_width=True, key="11_Offer_Generator_button_16",
                     help="Saves with status='final'. Existing offer is updated; new offer is inserted."):
            _recalc_economics(d["economics"], technical_specs=d.get("technical_specs"),
                              utilities=d.get("utilities"), capacity_kld=d["cover"].get("capacity_kld"))
            new_id, was_insert = _save_offer_to_db(
                d, status="final",
                offer_id=st.session_state.og_loaded_offer_id,
            )
            if new_id:
                st.session_state.og_loaded_offer_id = new_id
                _mark_clean(d)
                st.success(f"✅ Offer {'created' if was_insert else 'updated'} as FINAL (id={new_id})")
                st.rerun()

    with col3:
        if st.button("🔄 New Offer", use_container_width=True, key="11_Offer_Generator_button_17",
                     help="Discards the current form and starts fresh."):
            if dirty:
                st.session_state.og_pending_new = True
                st.rerun()
            else:
                st.session_state.og_offer_data = default_offer_data()
                st.session_state.og_loaded_offer_id = None
                st.session_state.og_form_version += 1
                _clear_scope_editor_cache()
                _mark_clean(st.session_state.og_offer_data)
                st.session_state.og_last_saved_at = None
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
            st.download_button("📥 Download Template", st.session_state.og_xlsx,
                "BG_Offer_Form_Template.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="11_Offer_Generator_download_button_19")

    with st.expander("🔗 Import from bg_process_design Project", expanded=True):
        pd_projects = _load_pd_projects()
        if not pd_projects:
            st.info("No process design projects yet.")
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
                        _recalc_economics(new_data["economics"], technical_specs=new_data.get("technical_specs"),
                                          utilities=new_data.get("utilities"), capacity_kld=new_data["cover"].get("capacity_kld"))
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
                    _recalc_economics(new_data["economics"], technical_specs=new_data.get("technical_specs"),
                                      utilities=new_data.get("utilities"), capacity_kld=new_data["cover"].get("capacity_kld"))
                    st.session_state.og_offer_data = new_data
                    st.success("✅ Imported from JSON")
                    st.rerun()
            except Exception as e:
                st.error(f"Parse failed: {e}")
