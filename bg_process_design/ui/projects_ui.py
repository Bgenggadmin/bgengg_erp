"""Projects management UI"""
import streamlit as st
from datetime import date
from bg_process_design.db import (
    create_project, list_projects, get_project, update_project, delete_project
)


def render(client):
    st.header("📁 Projects")
    st.caption("Create or select a project to begin. One project links Stripper → MEE → ATFD designs.")

    if not client:
        st.warning("⚠️ Supabase is not configured. Set credentials in `.streamlit/secrets.toml` "
                   "or as environment variables to enable project storage.")
        st.info("You can still run calculations — results stay in session memory for the current tab.")
        # Allow in-memory project fallback
        if "local_project" not in st.session_state:
            st.session_state["local_project"] = {
                "id": "local",
                "project_code": "LOCAL-001",
                "project_name": "Local Session Project",
                "buyer": "—",
                "plant_location": "—",
                "capacity_kld": 100,
                "created_by": "local",
            }
        if st.button("Use Local Session Project", key="projects_ui_button_1"):
            st.session_state["active_project"] = st.session_state["local_project"]
            st.rerun()
        return

    tab_list, tab_new = st.tabs(["📋 All Projects", "➕ New Project"])

    with tab_new:
        _render_new_project(client)

    with tab_list:
        _render_project_list(client)


def _render_new_project(client):
    st.subheader("Create New Project")
    with st.form("new_project_form"):
        c1, c2 = st.columns(2)
        with c1:
            code = st.text_input("Project code *", placeholder="e.g. BG-MSN-2026-001", key="projects_ui_text_input_2")
            name = st.text_input("Project name *", placeholder="e.g. 100 KLD ZLD System", key="projects_ui_text_input_3")
            buyer = st.text_input("Buyer", placeholder="e.g. MSN Organics", key="projects_ui_text_input_4")
            plant = st.text_input("Plant location", placeholder="e.g. Hyderabad", key="projects_ui_text_input_5")
            capacity = st.number_input("Capacity (KLD)", value=100, min_value=1, step=10, key="projects_ui_number_input_6")

        with c2:
            scheme = st.text_input("Scheme",
                                    placeholder="e.g. Stripper + 4-MEE + ATFD", key="projects_ui_text_input_7")
            designed_by = st.text_input("Designed by", key="projects_ui_text_input_8")
            checked_by = st.text_input("Checked by", key="projects_ui_text_input_9")
            approved_by = st.text_input("Approved by", key="projects_ui_text_input_10")
            design_date = st.date_input("Design date", value=date.today(), key="projects_ui_date_input_11")
            rev = st.number_input("Revision no.", value=0, min_value=0, step=1, key="projects_ui_number_input_12")

        notes = st.text_area("Notes (optional)", key="projects_ui_text_area_13")
        submitted = st.form_submit_button("Create Project", type="primary",
                                           use_container_width=True)

        if submitted:
            if not code or not name:
                st.error("Project code and name are required.")
            else:
                # Only include fields that exist in the pd_projects schema
                data = {
                    "project_code": code,
                    "project_name": name,
                    "plant_location": plant or None,
                    "capacity_kld": capacity,
                    "scheme": scheme or None,
                    "designed_by": designed_by or None,
                    "notes": notes or None,
                    "status": "active",
                }
                created = create_project(client, data)
                if created:
                    st.success(f"✅ Project created: {created['project_code']}")
                    st.session_state["active_project"] = created
                    st.rerun()


def _render_project_list(client):
    projects = list_projects(client)

    if not projects:
        st.info("No projects yet. Create one in the **New Project** tab.")
        return

    active_id = st.session_state.get("active_project", {}).get("id")

    for p in projects:
        is_active = (p["id"] == active_id)
        prefix = "⭐" if is_active else "📁"
        with st.expander(f"{prefix} **{p['project_code']}** — {p['project_name']}  "
                        f"({p.get('capacity_kld', '?')} KLD)"):
            c1, c2, c3 = st.columns(3)
            c1.write(f"**Buyer:** {p.get('buyer', '—')}")
            c1.write(f"**Location:** {p.get('plant_location', '—')}")
            c2.write(f"**Scheme:** {p.get('scheme', '—')}")
            c2.write(f"**Design date:** {p.get('design_date', '—')}")
            c3.write(f"**Rev:** {p.get('revision_no', 0)}")
            c3.write(f"**Status:** {p.get('status', 'draft')}")

            if p.get("notes"):
                st.caption(p["notes"])

            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("✅ Activate",
                             key=f"activate_{p['id']}",
                             disabled=is_active,
                             use_container_width=True):
                    st.session_state["active_project"] = p
                    st.rerun()
            with b2:
                if st.button("📝 Edit",
                             key=f"edit_{p['id']}",
                             use_container_width=True):
                    st.session_state["editing_project"] = p["id"]
            with b3:
                if st.button("🗑 Delete",
                             key=f"del_proj_{p['id']}",
                             use_container_width=True):
                    if delete_project(client, p["id"]):
                        if active_id == p["id"]:
                            st.session_state.pop("active_project", None)
                        st.success("Project deleted.")
                        st.rerun()

            if st.session_state.get("editing_project") == p["id"]:
                _render_edit_form(client, p)


def _render_edit_form(client, project):
    st.divider()
    st.markdown("### Edit Project")
    with st.form(f"edit_{project['id']}"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Project name", value=project.get("project_name", ""), key="projects_ui_text_input_14")
            buyer = st.text_input("Buyer", value=project.get("buyer") or "", key="projects_ui_text_input_15")
            plant = st.text_input("Plant location", value=project.get("plant_location") or "", key="projects_ui_text_input_16")
            capacity = st.number_input("Capacity (KLD)",
                                        value=float(project.get("capacity_kld") or 100), key="projects_ui_number_input_17")
        with c2:
            scheme = st.text_input("Scheme", value=project.get("scheme") or "", key="projects_ui_text_input_18")
            status = st.selectbox("Status", options=["draft", "approved", "archived"],
                                   index=["draft", "approved", "archived"].index(
                                       project.get("status", "draft")), key="projects_ui_selectbox_19")
            rev = st.number_input("Revision no.", value=int(project.get("revision_no") or 0), key="projects_ui_number_input_20")

        notes = st.text_area("Notes", value=project.get("notes") or "", key="projects_ui_text_area_21")
        c1, c2 = st.columns(2)
        with c1:
            save = st.form_submit_button("Save changes", type="primary",
                                          use_container_width=True)
        with c2:
            cancel = st.form_submit_button("Cancel", use_container_width=True)

        if save:
            update_project(client, project["id"], {
                "project_name": name, "buyer": buyer or None,
                "plant_location": plant or None, "capacity_kld": capacity,
                "scheme": scheme or None, "status": status,
                "revision_no": rev, "notes": notes or None,
            })
            st.session_state.pop("editing_project", None)
            st.success("Updated.")
            st.rerun()

        if cancel:
            st.session_state.pop("editing_project", None)
            st.rerun()
