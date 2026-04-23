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
from bg_process_design.utils.pdf_deck import build_client_deck_pdf
from bg_process_design.utils.excel_export import build_review_workbook


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

    # --- PDF CLIENT DECK (v5 auto-added) ---
    st.divider()
    st.markdown("#### 📑 Client Presentation Deck")
    st.caption(
        "Generate a 10-slide branded PDF presentation from this project's "
        "saved designs. Ready to share with clients — no external tools needed."
    )

    # Build export data on demand so the button reflects current DB state
    try:
        _pdf_data = build_full_project_export(conn, proj["id"])
    except Exception as _e:
        _pdf_data = {}
        st.warning(f"Could not load project data for PDF: {_e}")

    _has_strip = bool((_pdf_data.get("stripper") or {}).get("results"))
    _has_mee = bool((_pdf_data.get("mee") or {}).get("results"))
    _has_atfd = bool((_pdf_data.get("atfd") or {}).get("results"))
    _stages_saved = sum([_has_strip, _has_mee, _has_atfd])

    _c_info, _c_btn = st.columns([3, 1])
    with _c_info:
        _icons = (
            f"{'✅' if _has_strip else '⚪'} Stripper  "
            f"{'✅' if _has_mee else '⚪'} MEE  "
            f"{'✅' if _has_atfd else '⚪'} ATFD"
        )
        st.markdown(f"**Designs included:** {_icons}")
        if _stages_saved == 0:
            st.warning("No designs saved yet. Save at least one unit design first.")

    with _c_btn:
        _gen_pdf = st.button(
            "📑 Generate PDF",
            key="pd_export_gen_pdf_btn",
            type="primary",
            disabled=(_stages_saved == 0),
            use_container_width=True,
        )

    if _gen_pdf:
        with st.spinner("Building PDF deck…"):
            try:
                # Try to fetch logo from Supabase (same loader the Offer Generator uses)
                _logo_bytes = None
                try:
                    from bg_offer_generator.utils.assets import load_brand_assets
                    _logo_bytes, _, _ = load_brand_assets()
                except Exception:
                    pass  # fall back to text wordmark

                _designer = (proj.get("designed_by") or "Design Team").upper()
                _pdf_bytes = build_client_deck_pdf(
                    _pdf_data,
                    logo_bytes=_logo_bytes,
                    prepared_label=f"Prepared by B&G Engineering  •  {_designer}",
                )
                st.session_state["pd_export_pdf_bytes"] = _pdf_bytes
                st.session_state["pd_export_pdf_filename"] = (
                    f"BG_{proj.get('project_code', 'project')}_ClientDeck.pdf"
                )
                st.success(f"✅ Deck ready ({len(_pdf_bytes)/1024:.0f} KB, 10 slides)")
            except Exception as _e:
                st.error(f"PDF generation failed: {_e}")
                import traceback
                with st.expander("Error details"):
                    st.code(traceback.format_exc())

    if st.session_state.get("pd_export_pdf_bytes"):
        st.download_button(
            "⬇️ Download Client Deck PDF",
            data=st.session_state["pd_export_pdf_bytes"],
            file_name=st.session_state.get(
                "pd_export_pdf_filename", "BG_ClientDeck.pdf"
            ),
            mime="application/pdf",
            key="pd_export_pdf_download_btn",
            use_container_width=True,
        )
    # --- end PDF CLIENT DECK block ---

    # --- REVIEW EXCEL (v6 auto-added) ---
    st.divider()
    st.markdown("#### 📊 Design Review Excel")
    st.caption(
        "Generate a 5-sheet Excel workbook with all design outputs for manager review. "
        "Static values only — read-only summary of what has been calculated."
    )

    # Reuse the same _pdf_data if it was built by the PDF section above;
    # otherwise build it here.
    try:
        _xlsx_source = _pdf_data
    except NameError:
        try:
            _xlsx_source = build_full_project_export(conn, proj["id"])
        except Exception as _e:
            _xlsx_source = {}
            st.warning(f"Could not load project data for Excel: {_e}")

    _has_any_design = bool(
        (_xlsx_source.get("stripper") or {}).get("results") or
        (_xlsx_source.get("mee") or {}).get("results") or
        (_xlsx_source.get("atfd") or {}).get("results")
    )

    _c_xl_info, _c_xl_btn = st.columns([3, 1])
    with _c_xl_info:
        if not _has_any_design:
            st.warning("No designs saved yet. Save at least one unit design first.")
        else:
            st.markdown(
                "Includes: **Project Summary** • **Stripper** • "
                "**MEE** • **ATFD** • **Plant-Wide** "
                "(utilities, pump schedule, feed trace, economics)"
            )

    with _c_xl_btn:
        _gen_xlsx = st.button(
            "📊 Generate Excel",
            key="pd_export_gen_xlsx_btn",
            type="primary",
            disabled=(not _has_any_design),
            use_container_width=True,
        )

    if _gen_xlsx:
        with st.spinner("Building review workbook…"):
            try:
                _xlsx_bytes = build_review_workbook(_xlsx_source)
                st.session_state["pd_export_xlsx_bytes"] = _xlsx_bytes
                st.session_state["pd_export_xlsx_filename"] = (
                    f"BG_{proj.get('project_code', 'project')}_Review.xlsx"
                )
                st.success(f"✅ Workbook ready ({len(_xlsx_bytes)/1024:.0f} KB, 5 sheets)")
            except Exception as _e:
                st.error(f"Excel generation failed: {_e}")
                import traceback
                with st.expander("Error details"):
                    st.code(traceback.format_exc())

    if st.session_state.get("pd_export_xlsx_bytes"):
        st.download_button(
            "⬇️ Download Review Excel",
            data=st.session_state["pd_export_xlsx_bytes"],
            file_name=st.session_state.get(
                "pd_export_xlsx_filename", "BG_Review.xlsx"
            ),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="pd_export_xlsx_download_btn",
            use_container_width=True,
        )
    # --- end REVIEW EXCEL block ---

