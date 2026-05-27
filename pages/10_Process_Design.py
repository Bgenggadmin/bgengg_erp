"""
Page 10 — B&G Process Design Tool

Integrates the bg_process_design module into the ERP.
Password-gated. Uses ERP's Supabase connection + customer_master for clients.

Tables written to:
  pd_projects, pd_stripper_designs, pd_mee_designs,
  pd_atfd_designs, pd_salt_routing, pd_audit_log

Updated: integration with Anchor Portal (Ammu's MEE enquiries).
  - New "Open from Anchor Enquiry" section spawns a pd_project from
    an anchor_projects row, auto-creates the customer_master entry if
    needed, and writes the new pd_project_id back to anchor_projects.
"""
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


if not _password_gate():
    st.stop()


# ---------------------------------------------------------------------
# CONNECTION + MODULE IMPORTS (only run after auth)
# ---------------------------------------------------------------------
conn = st.connection("supabase", type=SupabaseConnection)

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
# RAW SUPABASE CLIENT (for tables not wrapped by bg_process_design.db)
# ---------------------------------------------------------------------
def _raw_client():
    return conn.client if hasattr(conn, "client") else conn


# ---------------------------------------------------------------------
# CLIENT PICKER (uses customer_master)
# ---------------------------------------------------------------------
@st.cache_data(ttl=300)
def _load_clients():
    try:
        res = _raw_client().table("customer_master").select(
            "id, name, address, contact, email"
        ).order("name").execute()
        return res.data or []
    except Exception as e:
        st.error(f"Failed to load clients: {e}")
        return []


def _client_picker(label="Client", key=None, current_id=None):
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
# ANCHOR ENQUIRY INTEGRATION
# ---------------------------------------------------------------------
@st.cache_data(ttl=60)
def _load_unlinked_anchor_enquiries():
    """
    Fetch Ammu's anchor_projects rows that don't yet have a pd_project linked.
    These are MEE enquiries ready to spawn a process design from.
    """
    try:
        res = _raw_client().table("anchor_projects").select(
            "id, client_name, project_description, job_no, status, "
            "contact_person, contact_phone, special_notes, enquiry_date, "
            "estimated_value, anchor_person, pd_project_id"
        ).eq("anchor_person", "Ammu").is_("pd_project_id", "null").order(
            "enquiry_date", desc=True
        ).execute()
        return res.data or []
    except Exception as e:
        st.warning(f"Could not load anchor enquiries: {e}")
        return []


def _find_or_create_customer(client_name: str, contact: str = None, email: str = None):
    """
    Case-insensitive trimmed match on customer_master.name.
    If a match is found, return that row. Otherwise create a new one.
    Returns the customer_master row dict (with id) or None on failure.
    """
    if not client_name or not client_name.strip():
        return None
    needle = client_name.strip().lower()

    # First try a fuzzy match against the cached list
    for c in _load_clients():
        if (c.get("name") or "").strip().lower() == needle:
            return c

    # Not found → create
    try:
        payload = {
            "name": client_name.strip(),
            "contact": (contact or "").strip() or None,
            "email":   (email or "").strip() or None,
        }
        res = _raw_client().table("customer_master").insert(payload).execute()
        if res.data:
            _load_clients.clear()  # bust cache
            return res.data[0]
    except Exception as e:
        st.error(f"Failed to create customer_master entry: {e}")
    return None


def _link_anchor_to_pd_project(anchor_id: int, pd_project_id: int) -> bool:
    """Write pd_project_id back into anchor_projects.id."""
    try:
        _raw_client().table("anchor_projects").update({
            "pd_project_id": pd_project_id,
        }).eq("id", anchor_id).execute()
        _load_unlinked_anchor_enquiries.clear()
        return True
    except Exception as e:
        st.error(f"Failed to link anchor entry to pd_project: {e}")
        return False


# ---------------------------------------------------------------------
# PROJECT SELECTION STATE
# ---------------------------------------------------------------------
if "pd_active_project" not in st.session_state:
    st.session_state.pd_active_project = None
if "pd_show_new_project" not in st.session_state:
    st.session_state.pd_show_new_project = False
if "pd_show_anchor_spawn" not in st.session_state:
    st.session_state.pd_show_anchor_spawn = False
if "pd_anchor_selected_row" not in st.session_state:
    st.session_state.pd_anchor_selected_row = None


# ---------------------------------------------------------------------
# MAIN UI
# ---------------------------------------------------------------------
st.title("🧪 Process Design — Stripper · MEE · ATFD")
st.caption("B&G Engineering ZLD Design Tool")


# =====================================================================
# OPEN FROM ANCHOR ENQUIRY  (new section)
# =====================================================================
with st.expander("📂 Open from Anchor Enquiry (Ammu · MEE projects)", expanded=False):
    anchor_rows = _load_unlinked_anchor_enquiries()
    if not anchor_rows:
        st.info(
            "No unlinked MEE enquiries from Ammu's anchor portal. "
            "Either all of Ammu's enquiries already have a process-design "
            "project, or no enquiries have been logged yet."
        )
    else:
        def _fmt_anchor(r):
            client = r.get("client_name") or "?"
            desc = (r.get("project_description") or "")[:40]
            status = r.get("status") or ""
            job = r.get("job_no") or "—"
            dt = str(r.get("enquiry_date") or "")[:10]
            return f"#{r['id']} · {client} · {desc} · Job {job} · {status} · {dt}"

        opts = ["— select an enquiry —"] + [_fmt_anchor(r) for r in anchor_rows]
        sel_idx = st.selectbox(
            f"Ammu's unlinked enquiries ({len(anchor_rows)} found)",
            range(len(opts)),
            format_func=lambda i: opts[i],
            key="pd_anchor_sel",
        )
        c1, c2 = st.columns([1, 4])
        if c1.button("🚀 Start Design", type="primary", disabled=(sel_idx == 0),
                     key="pd_anchor_spawn_btn", use_container_width=True):
            st.session_state.pd_anchor_selected_row = anchor_rows[sel_idx - 1]
            st.session_state.pd_show_anchor_spawn = True
            st.rerun()


# Spawn-from-anchor dialog
if st.session_state.pd_show_anchor_spawn and st.session_state.pd_anchor_selected_row:
    anc = st.session_state.pd_anchor_selected_row
    with st.form("anchor_spawn_form"):
        st.subheader("🧪 Spawn Process Design from Anchor Enquiry")
        st.caption(
            f"Anchor entry #{anc['id']} · {anc.get('client_name')} · "
            f"{anc.get('project_description', '')[:60]}"
        )

        c1, c2 = st.columns(2)
        with c1:
            # Pre-fill project_code: use job_no if available, else ANC<id>
            default_code = (
                str(anc.get("job_no") or "").strip().upper()
                or f"ANC{anc['id']}"
            )
            project_code = st.text_input(
                "Project Code *", value=default_code,
                help="Editable. Pre-filled from anchor job_no or ANC+id.",
            )
            default_name = (
                anc.get("project_description")
                or f"MEE Project — {anc.get('client_name')}"
            )
            project_name = st.text_input("Project Name *", value=default_name)
            plant_location = st.text_input("Plant Location", value="Hyderabad")
        with c2:
            st.text_input(
                "Client (auto-linked)",
                value=anc.get("client_name", ""),
                disabled=True,
                help="Will be matched against customer_master, "
                     "or auto-created if no match.",
            )
            capacity_kld = st.number_input(
                "Capacity (KLD) *", min_value=1, max_value=5000, value=100, step=10,
                help="Not captured in anchor portal — please enter.",
            )
            scheme = st.selectbox("Scheme",
                ["Stripper+MEE+ATFD", "MEE+ATFD", "MEE only", "Stripper only"])

        designed_by = st.text_input("Designed By", value="Ammu")
        notes = st.text_area(
            "Notes",
            value=(anc.get("special_notes") or ""),
            help="Pre-filled with anchor entry's special_notes. Edit as needed.",
        )

        col_a, col_b = st.columns(2)
        if col_a.form_submit_button("🚀 Create & Link", type="primary"):
            if not project_code.strip() or not project_name.strip():
                st.error("Project Code and Project Name are required.")
            else:
                # 1. Find or create customer_master entry
                cust = _find_or_create_customer(
                    anc.get("client_name", ""),
                    contact=anc.get("contact_phone"),
                    email=None,
                )
                if not cust:
                    st.error("Could not resolve customer. Aborted.")
                else:
                    # 2. Create pd_project
                    data = {
                        "project_code": project_code.strip(),
                        "project_name": project_name.strip(),
                        "client_id": cust["id"],
                        "plant_location": plant_location.strip(),
                        "capacity_kld": capacity_kld,
                        "scheme": scheme,
                        "designed_by": designed_by.strip(),
                        "notes": notes,
                        "status": "active",
                    }
                    result = create_project(conn, data)
                    if result:
                        # 3. Link anchor → pd_project
                        _link_anchor_to_pd_project(anc["id"], result["id"])
                        # 4. Log + set active
                        log_action(
                            conn, result["id"], "project", "create_from_anchor",
                            designed_by.strip() or "admin",
                            {"anchor_id": anc["id"], "code": project_code},
                        )
                        st.session_state.pd_active_project = result
                        st.session_state.pd_show_anchor_spawn = False
                        st.session_state.pd_anchor_selected_row = None
                        st.success(
                            f"✅ Created project {project_code} (id={result['id']}), "
                            f"linked customer #{cust['id']} ({cust['name']}), "
                            f"linked anchor #{anc['id']}"
                        )
                        st.rerun()
        if col_b.form_submit_button("Cancel"):
            st.session_state.pd_show_anchor_spawn = False
            st.session_state.pd_anchor_selected_row = None
            st.rerun()


# =====================================================================
# Existing project selector (unchanged)
# =====================================================================
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

# New project dialog (unchanged)
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

    # --- PDF CLIENT DECK ---
    st.divider()
    st.markdown("#### 📑 Client Presentation Deck")
    st.caption(
        "Generate a 10-slide branded PDF presentation from this project's "
        "saved designs. Ready to share with clients — no external tools needed."
    )

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
                _logo_bytes = None
                try:
                    from bg_offer_generator.utils.assets import load_brand_assets
                    _logo_bytes, _, _ = load_brand_assets()
                except Exception:
                    pass

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

    # --- REVIEW EXCEL ---
    st.divider()
    st.markdown("#### 📊 Design Review Excel")
    st.caption(
        "Generate a 5-sheet Excel workbook with all design outputs for manager review. "
        "Static values only — read-only summary of what has been calculated."
    )

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
