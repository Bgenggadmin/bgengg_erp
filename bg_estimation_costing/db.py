"""
bg_estimation_costing.db
────────────────────────
Supabase CRUD layer for the MEE Estimation & Costing module.

Reads (upstream — produced by bg_process_design):
  • mee_projects               — process-design project headers
  • mee_design_equipment       — sized equipment list

Reads (shared masters — same tables as Pharma estimation module):
  • est_rm_master              — raw material + bought-out items
                                  (category='RM'  → sheet/plate rates)
                                  (category='BO'  → instruments / pumps / valves)
  • est_oh_master              — labour, consumables, packing, transport, etc.

Writes (downstream — consumed by bg_offer_generator):
  • mee_qps_costings           — costing header (1 per revision)
  • mee_qps_costing_lines      — equipment cost lines (n per costing)

All public functions accept an optional `conn` (st_supabase_connection
SupabaseConnection). If not provided they pull from `st.connection("supabase")`
the same way bg_process_design.db does.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from typing import Dict, List, Optional, Any

import streamlit as st


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION
# ─────────────────────────────────────────────────────────────────────────────
def _get_conn():
    """Return the shared SupabaseConnection, or None if not configured."""
    try:
        from st_supabase_connection import SupabaseConnection
        return st.connection("supabase", type=SupabaseConnection)
    except Exception:
        return None


def is_connected() -> bool:
    return _get_conn() is not None


# ─────────────────────────────────────────────────────────────────────────────
# LOW-LEVEL HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _fetch(table: str, *, select: str = "*",
           order: Optional[str] = None,
           filters: Optional[Dict] = None) -> List[Dict]:
    conn = _get_conn()
    if conn is None:
        return []
    try:
        q = conn.table(table).select(select)
        if order:
            q = q.order(order)
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        return q.execute().data or []
    except Exception as e:
        st.error(f"DB read error ({table}): {e}")
        return []


def _insert(table: str, row: Dict, *, returning: bool = False):
    conn = _get_conn()
    if conn is None:
        st.warning(f"Supabase not connected — could not insert into {table}.")
        return None
    try:
        res = conn.table(table).insert(row).execute()
        return res.data if returning else True
    except Exception as e:
        st.error(f"DB insert error ({table}): {e}")
        return None


def _update(table: str, row: Dict, match_col: str, match_val) -> bool:
    conn = _get_conn()
    if conn is None:
        return False
    try:
        conn.table(table).update(row).eq(match_col, match_val).execute()
        return True
    except Exception as e:
        st.error(f"DB update error ({table}): {e}")
        return False


def _delete(table: str, match_col: str, match_val) -> bool:
    conn = _get_conn()
    if conn is None:
        return False
    try:
        conn.table(table).delete().eq(match_col, match_val).execute()
        return True
    except Exception as e:
        st.error(f"DB delete error ({table}): {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# UPSTREAM READS — process-design output
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def list_projects() -> List[Dict]:
    """All process-design projects available for costing."""
    return _fetch("mee_projects", order="created_at")


@st.cache_data(ttl=300, show_spinner=False)
def get_design_equipment(project_id) -> List[Dict]:
    """Equipment list produced by bg_process_design for one project."""
    return _fetch("mee_design_equipment",
                  filters={"project_id": project_id},
                  order="line_no")


# ─────────────────────────────────────────────────────────────────────────────
# COSTING HEADERS
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def list_costings() -> List[Dict]:
    return _fetch("mee_qps_costings", order="created_at")


def get_costing(costing_id) -> Optional[Dict]:
    rows = _fetch("mee_qps_costings", filters={"id": costing_id})
    return rows[0] if rows else None


def upsert_costing(row: Dict, costing_id: Optional[int] = None
                   ) -> Optional[int]:
    """Insert or update a costing header. Returns the costing_id."""
    # Coerce date / datetime to ISO string
    for k, v in list(row.items()):
        if isinstance(v, (date, datetime)):
            row[k] = v.isoformat()

    if costing_id:
        ok = _update("mee_qps_costings", row, "id", costing_id)
        list_costings.clear()
        return costing_id if ok else None

    row.setdefault("created_at", datetime.utcnow().isoformat())
    res = _insert("mee_qps_costings", row, returning=True)
    list_costings.clear()
    return res[0]["id"] if res else None


def delete_costing(costing_id) -> bool:
    """Delete a costing and (via FK CASCADE) all its lines."""
    ok = _delete("mee_qps_costings", "id", costing_id)
    list_costings.clear()
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# COSTING LINES (children of a costing header)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def get_costing_lines(costing_id) -> List[Dict]:
    return _fetch("mee_qps_costing_lines",
                  filters={"costing_id": costing_id},
                  order="line_no")


def replace_costing_lines(costing_id, lines: List[Dict]) -> bool:
    """Atomic-ish: delete all existing lines, then insert the new set."""
    _delete("mee_qps_costing_lines", "costing_id", costing_id)
    for i, l in enumerate(lines, 1):
        line_row = {**l, "costing_id": costing_id, "line_no": i}
        # Ensure JSON columns are strings, not dicts
        if isinstance(line_row.get("design_payload"), dict):
            line_row["design_payload"] = json.dumps(line_row["design_payload"])
        _insert("mee_qps_costing_lines", line_row)
    get_costing_lines.clear()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# SHARED MASTERS — read from est_rm_master / est_oh_master
# (Same tables the Pharma estimation module uses — single source of truth.)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner=False)
def load_rm_master() -> List[Dict]:
    """All raw-material + bought-out items from est_rm_master."""
    rows = _fetch("est_rm_master", order="material")
    # Filter to active rows only
    return [r for r in rows if r.get("active") in (None, "Yes", True, "Y")]


@st.cache_data(ttl=600, show_spinner=False)
def load_oh_master() -> List[Dict]:
    """All overhead items from est_oh_master."""
    return _fetch("est_oh_master", order="oh_type")


# ── Convenience views over the masters ──────────────────────────────────────
def rm_rate_lookup() -> Dict[str, float]:
    """
    Build a {material → rate ₹/kg} dict from est_rm_master where category='RM'.
    Falls back to hardcoded defaults if the DB row is missing.
    Used by the parametric calculators.
    """
    out: Dict[str, float] = {}
    for r in load_rm_master():
        if r.get("category") == "RM" and r.get("material") and r.get("rate"):
            mat = r["material"]
            # Multiple rows for same material → take latest (highest rate-row last)
            out[mat] = float(r["rate"])
    return out


def labour_rate_lookup() -> Dict[str, float]:
    """
    Build a {material → labour-rate ₹/kg} dict from est_oh_master where
    oh_type='LABOUR'.

    Priority for the material key:
      1. `material` column (added by migration 02_extend_masters_for_mee.sql)
      2. `description` column (fallback for legacy rows)
      3. `oh_code` (last-resort fallback)
    """
    out: Dict[str, float] = {}
    for r in load_oh_master():
        if r.get("oh_type") in ("LABOUR", "LABOUR_BUFF") and r.get("rate"):
            key = (r.get("material")
                   or r.get("description")
                   or r.get("oh_code")
                   or "").strip()
            if key:
                out[key] = float(r["rate"])
    return out


def bo_items(sub_type: Optional[str] = None) -> List[Dict]:
    """
    All bought-out items from est_rm_master where category='BO'.
    These are instruments, pumps, valves, transmitters, panels, motors, etc.

    Optional `sub_type` filter (e.g. 'Temperature', 'Pressure', 'Flow',
    'Centrifugal', 'Drive', 'Panel') — matches the `sub_type` column added
    in migration 02_extend_masters_for_mee.sql.
    """
    rows = [r for r in load_rm_master() if r.get("category") == "BO"]
    if sub_type:
        rows = [r for r in rows if r.get("sub_type") == sub_type]
    return rows


def bo_subtypes() -> List[str]:
    """Distinct sub_type values across all BO items — for picker filter."""
    return sorted({(r.get("sub_type") or "").strip()
                   for r in load_rm_master()
                   if r.get("category") == "BO" and r.get("sub_type")})


def bo_rmtypes() -> List[str]:
    """Distinct rm_type values across all BO items."""
    return sorted({(r.get("rm_type") or "").strip()
                   for r in load_rm_master()
                   if r.get("category") == "BO" and r.get("rm_type")})


# ─────────────────────────────────────────────────────────────────────────────
# CACHE BUSTERS — call after external writes
# ─────────────────────────────────────────────────────────────────────────────
def refresh_all_caches():
    list_projects.clear()
    get_design_equipment.clear()
    list_costings.clear()
    get_costing_lines.clear()
    load_rm_master.clear()
    load_oh_master.clear()
