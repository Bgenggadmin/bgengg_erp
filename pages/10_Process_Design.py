"""
Page 10 — B&G Process Design Tool

Integrates the bg_process_design module into the ERP.
Password-gated. Uses ERP's Supabase connection + customer_master for clients.

Tables written to:
  pd_projects, pd_stripper_designs, pd_mee_designs,
  pd_atfd_designs, pd_salt_routing, pd_audit_log
"""
# Ensure repo root is on sys.path so sibling modules (bg_process_design/, bg_offer_generator/) import correctly
import sys, os
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

import streamlit as st
from st_supabase_connection import SupabaseConnection

# ---------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Process Design — BGEngg ERP",
    page_icon="🧪",
    layout="wide",
)

# ---------------------------------------------------------------------
# PASSWORD GATE
# ---------------------------------------------------------------------
_TEAM_PASSWORD = "BG@Design2026"

def _password_gate() -> bool:
    """Return True if user has entered correct password."""
    if st.session_state.get("pd_authenticated"):
        return True

    st.title("🔒 Process Design — Restricted")
    st.caption("Enter team password to access B&G process design tools.")
    pwd = st.text_input("Password", type="password", key="pd_pwd_input")
    if st.button("Unlock", type="primary", key="10_Process_Design_button_1"):
        if pwd == _TEAM_PASSWORD:
            st.session_state.pd_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


# Block if not authenticated
if not _password_gate():
    st.stop()


# ---------------------------------------------------------------------
# CONNECTION + MODULE IMPORTS (only run after auth)
# ---------------------------------------------------------------------
conn = st.connection("supabase", type=SupabaseConnection)

# Import here so failed imports don't break password gate
from bg_process_design.db import (
    create_project, list_projects, get_project,
    update_project, delete_project, log_action,
)
from bg_process_design.ui import projects_ui, dashboard_ui
from bg_process_design.ui import stripper_ui, mee_ui, atfd_ui
from bg_process_design.utils.export_utils import build_full_project_export


# ---------------------------------------------------------------------
# CLIENT PICKER (uses customer_master)
# ---------------------------------------------------------------------
@st.cache_data(ttl=300)
def _load_clients():
    """Fetch list of clients from customer_master."""
    try:
        client = conn.client if hasattr(conn, "client") else conn
        res = client.table("customer_master").select("id, name").order("name").execute()
        return res.data or []
    except Exception as e:
        st.error(f"Failed to load clients: {e}")
        return []


def _client_picker(label="Client", key=None, current_id=None):
    """Render a dropdown of customers from customer_master. Returns (id, name)."""
    clients = _load_clients()
    if not clients:
        st.warning("No clients found in customer_master. Add clients via the ERP first.")
        return None, None
    options = {f"{c['name']} (id={c['id']})": c for c in clients}
    default_idx = 0
    if current_id:
        for i, (_, c) in enumerate(options.items()):
            if c["id"] == current_id:
                default_idx = i
                break
    choice_label = st.selectbox(label, list(options.keys()), index=default_idx, key=key)
    if choice_label:
        chosen = options[choice_label]
        return chosen["id"], chosen["name"]
    return None, None


# ---------------------------------------------------------------------
# PROJECT SELECTION STATE
# ---------------------------------------------------------------------
if "pd_active_project" not in st.session_state:
    st.session_state.pd_active_project = None


# ---------------------------------------------------------------------
# MAIN UI
# ---------------------------------------------------------------------
st.title("🧪 Process Design — Stripper · MEE · ATFD")
st.caption("B&G Engineering ZLD Design Tool")

# Top bar: project selector
with st.container():
    c1, c2, c3 = st.columns([3, 2, 1])
    with c1:
        projects = list_projects(conn)
        proj_options = {"— Select / create project —": None}
        for p in projects:
            proj_options[f"{p['project_code']} · {p['project_name']}"] = p

        sel_label = st.selectbox("Active Project",
                                    list(proj_options.keys()),
                                    key="pd_proj_select")
        sel_proj = proj_options[sel_label]
        if sel_proj:
            st.session_state.pd_active_project = sel_proj

    with c2:
        if st.button("➕ New Project", use_container_width=True, key="10_Process_Design_button_2"):
            st.session_state.pd_show_new_project = True

    with c3:
        if st.button("🚪 Logout", use_container_width=True, key="10_Process_Design_button_3"):
            st.session_state.pd_authenticated = False
            st.rerun()

# New project dialog
if st.session_state.get("pd_show_new_project"):
    with st.form("new_proj_form"):
        st.subheader("Create New Project")
        c1, c2 = st.columns(2)
        with c1:
            project_code = c1.text_input("Project Code", placeholder="e.g. 2948")
            project_name = c1.text_input("Project Name", placeholder="e.g. 100 KLD ZLD — Lee Pharma")
            plant_location = c1.text_input("Plant Location", value="Hyderabad")
        with c2:
            client_id, client_name = _client_picker("Client", key="new_proj_client")
            capacity_kld = c2.number_input("Capacity (KLD)", min_value=1, max_value=5000, value=100, step=10)
            scheme = c2.selectbox("Scheme", ["Stripper+MEE+ATFD", "MEE+ATFD", "MEE only", "Stripper only"])

        designed_by = st.text_input("Designed By", value="", key="10_Process_Design_text_input_4")
        notes = st.text_area("Notes", value="", key="10_Process_Design_text_area_5")

        col_a, col_b = st.columns(2)
        if col_a.form_submit_button("Create", type="primary"):
            data = {
                "project_code": project_code,
                "project_name": project_name,
                "client_id": client_id,
                "plant_location": plant_location,
                "capacity_kld": capacity_kld,
                "scheme": scheme,
                "designed_by": designed_by,
                "notes": notes,
                "status": "active",
            }
            result = create_project(conn, data)
            if result:
                st.session_state.pd_active_project = result
                st.session_state.pd_show_new_project = False
                log_action(conn, result["id"], "project", "create",
                           designed_by or "admin", {"code": project_code})
                st.success(f"Created: {project_code}")
                st.rerun()
        if col_b.form_submit_button("Cancel"):
            st.session_state.pd_show_new_project = False
            st.rerun()

# Main workspace — active project
proj = st.session_state.pd_active_project
if not proj:
    st.info("👆 Select or create a project above to start designing.")
    st.stop()

# Show project header
st.divider()
cols = st.columns(4)
cols[0].metric("Project", proj.get("project_code", "—"))
cols[1].metric("Client ID", proj.get("client_id", "—"))
cols[2].metric("Capacity", f"{proj.get('capacity_kld', '—')} KLD")
cols[3].metric("Status", proj.get("status", "—").upper())

# Module tabs
tabs = st.tabs([
    "📊 Dashboard",
    "🧪 Stripper",
    "💧 MEE",
    "🌡 ATFD",
    "📤 Export",
])

with tabs[0]:
    dashboard_ui.render(conn, proj)

with tabs[1]:
    stripper_ui.render(conn, proj)

with tabs[2]:
    mee_ui.render(conn, proj)

with tabs[3]:
    atfd_ui.render(conn, proj)

with tabs[4]:
    st.subheader("Full Project Export")
    st.caption("Export all design data as JSON (for PPT generation, offer bridge, etc.)")
    if st.button("🔽 Build Full Project JSON", type="primary", key="10_Process_Design_button_6"):
        try:
            export_data = build_full_project_export(conn, proj["id"])
            import json
            json_str = json.dumps(export_data, indent=2, default=str)
            st.download_button(
                label="📥 Download full_project.json",
                data=json_str,
                file_name=f"{proj['project_code']}_full_project.json",
                mime="application/json", key="10_Process_Design_download_button_7")
            st.success(f"Export ready: {len(json_str)/1024:.1f} KB")
            with st.expander("Preview"):
                st.json(export_data)
        except Exception as e:
            st.error(f"Export failed: {e}")
            import traceback
            st.code(traceback.format_exc())
