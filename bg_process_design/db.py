"""
Database access layer for bg_process_design when running inside bgengg_erp.

This module replaces the standalone app/db/supabase_client.py. Instead of
creating its own Supabase client, it uses the `conn` object from the ERP's
`st.connection("supabase", type=SupabaseConnection)` pattern.

Tables used (prefixed with pd_ to avoid collision with ERP tables):
    pd_projects
    pd_stripper_designs
    pd_mee_designs
    pd_atfd_designs
    pd_salt_routing
    pd_audit_log
"""
from datetime import datetime
from typing import Optional
import streamlit as st


# The `conn` from st_supabase_connection exposes .table() that behaves like
# supabase-py's client. But we need to access the underlying client for
# consistency. Both forms work; we normalize below.

def _client(conn):
    """Extract the underlying supabase-py client from st.connection wrapper."""
    if conn is None:
        return None
    # st_supabase_connection wraps the client; access varies by version
    if hasattr(conn, "client"):
        return conn.client
    if hasattr(conn, "_instance"):
        return conn._instance
    # Last resort — treat conn itself as the client (some versions)
    return conn


# =====================================================================
# PROJECTS
# =====================================================================
def create_project(conn, data: dict) -> Optional[dict]:
    client = _client(conn)
    if not client:
        return None
    try:
        res = client.table("pd_projects").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"Failed to create project: {e}")
        return None


def list_projects(conn, status: Optional[str] = None) -> list:
    client = _client(conn)
    if not client:
        return []
    try:
        q = client.table("pd_projects").select("*").order("created_at", desc=True)
        if status:
            q = q.eq("status", status)
        return q.execute().data or []
    except Exception as e:
        st.error(f"Failed to list projects: {e}")
        return []


def get_project(conn, project_id) -> Optional[dict]:
    client = _client(conn)
    if not client:
        return None
    try:
        res = client.table("pd_projects").select("*").eq("id", project_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"Failed to load project: {e}")
        return None


def update_project(conn, project_id, data: dict) -> Optional[dict]:
    client = _client(conn)
    if not client:
        return None
    try:
        res = client.table("pd_projects").update(data).eq("id", project_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"Failed to update project: {e}")
        return None


def delete_project(conn, project_id) -> bool:
    client = _client(conn)
    if not client:
        return False
    try:
        client.table("pd_projects").delete().eq("id", project_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to delete project: {e}")
        return False


# =====================================================================
# DESIGNS (stripper / mee / atfd)
# =====================================================================
def save_design(conn, module: str, project_id, inputs: dict,
                results: dict, design_name: str = "",
                created_by: str = "") -> Optional[dict]:
    """
    Save a design for a project.
    module: 'stripper' | 'mee' | 'atfd'
    """
    client = _client(conn)
    if not client:
        return None

    table_name = f"pd_{module}_designs"
    payload = {
        "project_id": project_id,
        "status": "designed",
        "inputs": inputs,
        "results": results,
        "feed_char_out": results.get("feed_characterization", {}),
    }
    if module == "mee":
        payload["n_effects"] = results.get("n_effects")
        payload["per_effect"] = results.get("per_effect", [])
    payload["equipment"] = {
        k: results.get(k) for k in ("vls", "tubes", "pumps", "condenser", "blower", "utilities")
        if k in results
    }

    try:
        res = client.table(table_name).insert(payload).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"Failed to save {module} design: {e}")
        return None


def list_designs(conn, module: str, project_id=None) -> list:
    client = _client(conn)
    if not client:
        return []
    table_name = f"pd_{module}_designs"
    try:
        q = client.table(table_name).select("*").order("created_at", desc=True)
        if project_id:
            q = q.eq("project_id", project_id)
        return q.execute().data or []
    except Exception as e:
        st.error(f"Failed to list {module} designs: {e}")
        return []


def get_design(conn, module: str, design_id) -> Optional[dict]:
    client = _client(conn)
    if not client:
        return None
    table_name = f"pd_{module}_designs"
    try:
        res = client.table(table_name).select("*").eq("id", design_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        st.error(f"Failed to load design: {e}")
        return None


def delete_design(conn, module: str, design_id) -> bool:
    client = _client(conn)
    if not client:
        return False
    table_name = f"pd_{module}_designs"
    try:
        client.table(table_name).delete().eq("id", design_id).execute()
        return True
    except Exception as e:
        st.error(f"Failed to delete design: {e}")
        return False


# =====================================================================
# SALT ROUTING (optional, stored per project)
# =====================================================================
def save_salt_routing(conn, project_id, routing_data: dict) -> bool:
    client = _client(conn)
    if not client:
        return False
    try:
        # Replace existing routing for this project
        client.table("pd_salt_routing").delete().eq("project_id", project_id).execute()
        client.table("pd_salt_routing").insert({
            "project_id": project_id,
            "routing_data": routing_data,
        }).execute()
        return True
    except Exception as e:
        st.error(f"Failed to save salt routing: {e}")
        return False


# =====================================================================
# LINE SIZING (kept as stub - was separate table in original code)
# =====================================================================
def save_line_sizing(conn, project_id, lines: list) -> bool:
    """Line sizing stored inline in project feed_characterization JSONB for now."""
    client = _client(conn)
    if not client:
        return False
    try:
        # Fetch project, merge lines into feed_characterization
        proj = get_project(conn, project_id)
        if not proj:
            return False
        fc = proj.get("feed_characterization") or {}
        fc["line_sizing"] = lines
        update_project(conn, project_id, {"feed_characterization": fc})
        return True
    except Exception as e:
        st.error(f"Failed to save line sizing: {e}")
        return False


def get_line_sizing(conn, project_id) -> list:
    proj = get_project(conn, project_id)
    if not proj:
        return []
    fc = proj.get("feed_characterization") or {}
    return fc.get("line_sizing", [])


# =====================================================================
# AUDIT LOG
# =====================================================================
def log_action(conn, project_id, module: str,
               action: str, actor: str, payload: dict = None):
    client = _client(conn)
    if not client:
        return
    try:
        client.table("pd_audit_log").insert({
            "entity_type": module,
            "entity_id": project_id,
            "action": action,
            "user_name": actor,
            "payload": payload or {},
        }).execute()
    except Exception:
        pass  # non-critical


# =====================================================================
# BACKWARDS-COMPAT: old code calls `get_supabase_client()` expecting a client
# We expose this as a no-op that just returns the conn wrapper
# =====================================================================
def get_supabase_client():
    """
    Deprecated — kept for backwards compat. When running inside the ERP,
    pages should pass `conn` from st.connection("supabase") directly.
    Returns None here since we don't create our own.
    """
    return None
