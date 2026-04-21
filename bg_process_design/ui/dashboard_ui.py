"""Project Overview Dashboard - shows linked Stripper→MEE→ATFD"""
import streamlit as st
from bg_process_design.db import list_designs


def render(client, project):
    st.header("🏭 Project Overview")
    st.caption(f"**{project['project_name']}** ({project['project_code']})")

    # Top-line project info
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Capacity", f"{project.get('capacity_kld', '?')} KLD")
    c2.metric("Buyer", project.get("buyer", "—") or "—")
    c3.metric("Location", project.get("plant_location", "—") or "—")
    c4.metric("Revision", project.get("revision_no", 0))

    # Full-project download button (prominent)
    _render_full_project_download(client, project)

    st.divider()

    # Process flow diagram (simple text)
    st.markdown("### Process Flow")
    st.markdown(
        "```\n"
        "  Effluent Feed → Stripper Column → MEE (4-Effect) → ATFD → Dry Solids\n"
        "                       │                │               │\n"
        "                       ↓                ↓               ↓\n"
        "                  Solvent Rec.    Concentrate       Water Evap.\n"
        "```"
    )

    st.divider()

    # Unit status cards
    st.markdown("### Design Status")
    col1, col2, col3 = st.columns(3)

    with col1:
        _status_card(client, project, "stripper", "🧪 Stripper", col1)
    with col2:
        _status_card(client, project, "mee", "💧 MEE", col2)
    with col3:
        _status_card(client, project, "atfd", "🌡 ATFD", col3)

    st.divider()

    # Linked design summary
    if client and project["id"] != "local":
        _render_linked_summary(client, project)
    else:
        _render_session_summary()


def _status_card(client, project, module, title, col):
    """Render a status card for a unit (stripper/mee/atfd)."""
    with col:
        st.markdown(f"#### {title}")
        if client and project["id"] != "local":
            designs = list_designs(client, module, project["id"])
            count = len(designs)
            if count > 0:
                latest = designs[0]
                st.success(f"✅ {count} design(s)")
                st.caption(f"Latest: {latest.get('design_name', '—')}")
                st.caption(f"Saved: {latest['created_at'][:10]}")
            else:
                st.info("No designs yet")
        else:
            in_session = f"{module}_results" in st.session_state
            if in_session:
                st.success("✅ Calculated (in session)")
            else:
                st.info("Not calculated yet")


def _render_linked_summary(client, project):
    """Show latest design from each module side-by-side."""
    st.markdown("### Linked Design Summary (Latest from each unit)")

    strip = list_designs(client, "stripper", project["id"])
    mee = list_designs(client, "mee", project["id"])
    atfd = list_designs(client, "atfd", project["id"])

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**🧪 Stripper**")
        if strip:
            d = strip[0]
            st.metric("Feed", f"{d.get('feed_kgh') or 0:.0f} kg/h")
            st.metric("Bottoms → MEE", f"{d.get('bottoms_kgh') or 0:.0f} kg/h")
            st.metric("Steam", f"{d.get('steam_consumption_kgh') or 0:.0f} kg/h")
            st.metric("Col Dia", f"{d.get('column_dia_selected_m') or 0:.2f} m")
        else:
            st.caption("— No design —")

    with c2:
        st.markdown("**💧 MEE**")
        if mee:
            d = mee[0]
            st.metric("Feed", f"{d.get('feed_kgh') or 0:.0f} kg/h")
            st.metric("Concentrate → ATFD", f"{d.get('final_concentrate_kgh') or 0:.0f} kg/h")
            st.metric("Steam", f"{d.get('steam_consumption_kgh') or 0:.0f} kg/h")
            st.metric("SE", f"{d.get('steam_economy') or 0:.2f}")
        else:
            st.caption("— No design —")

    with c3:
        st.markdown("**🌡 ATFD**")
        if atfd:
            d = atfd[0]
            st.metric("Feed", f"{d.get('feed_kgh') or 0:.0f} kg/h")
            st.metric("Dry Product", f"{d.get('product_kgh') or 0:.1f} kg/h")
            st.metric("HTA", f"{d.get('hta_selected_m2') or 0} m²")
            st.metric("Motor", f"{d.get('motor_hp') or 0} HP")
        else:
            st.caption("— No design —")

    # Mass closure check
    if strip and mee and atfd:
        st.divider()
        st.markdown("### Mass Balance Check (Stripper → MEE → ATFD)")
        strip_out = strip[0].get("bottoms_kgh") or 0
        mee_in = mee[0].get("feed_kgh") or 0
        mee_out = mee[0].get("final_concentrate_kgh") or 0
        atfd_in = atfd[0].get("feed_kgh") or 0

        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown("**Stripper → MEE**")
            if abs(strip_out - mee_in) / max(strip_out, 1) < 0.05:
                st.success(f"✅ Stripper bottoms {strip_out:.0f} ≈ MEE feed {mee_in:.0f}")
            else:
                st.warning(f"⚠️ Stripper bottoms {strip_out:.0f} kg/h, but MEE feed {mee_in:.0f} kg/h "
                           f"({abs(strip_out - mee_in):.0f} kg/h mismatch)")
        with cc2:
            st.markdown("**MEE → ATFD**")
            if abs(mee_out - atfd_in) / max(mee_out, 1) < 0.05:
                st.success(f"✅ MEE concentrate {mee_out:.0f} ≈ ATFD feed {atfd_in:.0f}")
            else:
                st.warning(f"⚠️ MEE concentrate {mee_out:.0f} kg/h, but ATFD feed {atfd_in:.0f} kg/h "
                           f"({abs(mee_out - atfd_in):.0f} kg/h mismatch)")

    # Plant-wide feed parameter traceability
    if strip and mee and atfd:
        strip_res = strip[0].get("results", {})
        mee_res = mee[0].get("results", {})
        atfd_res = atfd[0].get("results", {})

        feed_in = strip_res.get("feed_characterization")
        strip_bot = strip_res.get("bottoms_feed_characterization")
        mee_conc = mee_res.get("concentrate_feed_characterization")
        atfd_out = atfd_res.get("dry_product_feed_characterization")

        if any([feed_in, strip_bot, mee_conc, atfd_out]):
            st.divider()
            st.markdown("### 🧫 Plant-Wide Parameter Traceability")
            st.caption("Non-volatile species (TDS, COD, salts) concentrate progressively; "
                       "volatile solvents exit via stripper distillate")

            import pandas as pd
            rows = []
            stages = [
                ("1. Raw Effluent Feed", feed_in),
                ("2. Stripper Bottoms", strip_bot),
                ("3. MEE Concentrate", mee_conc),
                ("4. ATFD Dry Product", atfd_out),
            ]
            for stage_name, fc in stages:
                if fc:
                    rows.append({
                        "Stage": stage_name,
                        "TS %": f"{fc.get('ts_pct', 0):.2f}",
                        "TDS %": f"{fc.get('tds_pct', 0):.2f}",
                        "COD mg/L": f"{fc.get('cod_mgl', 0):,.0f}",
                        "BOD mg/L": f"{fc.get('bod_mgl', 0):,.0f}",
                        "Cl mg/L": f"{fc.get('chlorides_mgl', 0):,.0f}",
                        "pH": f"{fc.get('ph', 7.0):.1f}",
                    })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_session_summary():
    st.markdown("### Session Summary")
    strip = st.session_state.get("stripper_results")
    mee = st.session_state.get("mee_results")
    atfd = st.session_state.get("atfd_results")

    if not any([strip, mee, atfd]):
        st.info("Run calculations in Stripper / MEE / ATFD pages to see summary here.")
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        if strip:
            st.markdown("**Stripper**")
            st.metric("Feed", f"{strip.get('feed_kgh', 0):.0f} kg/h")
            st.metric("Col Dia", f"{strip.get('column_dia_selected_m', 0):.2f} m")
            st.metric("Steam", f"{strip.get('steam_consumption_kgh', 0):.0f} kg/h")
    with c2:
        if mee:
            st.markdown("**MEE**")
            st.metric("Feed", f"{mee.get('feed_kgh', 0):.0f} kg/h")
            st.metric("Evap", f"{mee.get('total_evap_kgh', 0):.0f} kg/h")
            st.metric("SE", f"{mee.get('steam_economy', 0):.2f}")
    with c3:
        if atfd:
            st.markdown("**ATFD**")
            st.metric("Feed", f"{atfd.get('feed_kgh', 0):.0f} kg/h")
            st.metric("Product", f"{atfd.get('product_kgh', 0):.1f} kg/h")
            st.metric("HTA", f"{atfd.get('HTA_selected_m2', 0)} m²")


def _render_full_project_download(client, project):
    """Prominent download button — captures everything for PPT generation."""
    from bg_process_design.utils.export_utils import (
        export_full_project, to_json_string, generate_filename
    )

    # Gather data — prefer latest saved (DB), fall back to session
    s_data, m_data, a_data = None, None, None
    s_inputs, m_inputs, a_inputs = None, None, None

    if client and project.get("id") != "local":
        strip_designs = list_designs(client, "stripper", project["id"])
        mee_designs = list_designs(client, "mee", project["id"])
        atfd_designs = list_designs(client, "atfd", project["id"])
        if strip_designs:
            s_data = strip_designs[0].get("results")
            s_inputs = strip_designs[0].get("inputs")
        if mee_designs:
            m_data = mee_designs[0].get("results")
            m_inputs = mee_designs[0].get("inputs")
        if atfd_designs:
            a_data = atfd_designs[0].get("results")
            a_inputs = atfd_designs[0].get("inputs")

    # Fall back to session if nothing in DB
    if not s_data and "stripper_results" in st.session_state:
        s_data = st.session_state["stripper_results"]
        s_inputs = st.session_state.get("stripper_inputs")
    if not m_data and "mee_results" in st.session_state:
        m_data = st.session_state["mee_results"]
        m_inputs = st.session_state.get("mee_inputs")
    if not a_data and "atfd_results" in st.session_state:
        a_data = st.session_state["atfd_results"]
        a_inputs = st.session_state.get("atfd_inputs")

    any_data = any([s_data, m_data, a_data])

    # Always render something so the button area is consistent
    if any_data:
        export = export_full_project(
            project=project,
            stripper_result=s_data, mee_result=m_data, atfd_result=a_data,
            stripper_inputs=s_inputs, mee_inputs=m_inputs, atfd_inputs=a_inputs,
        )
        json_str = to_json_string(export)
        filename = generate_filename(project, "full_project")
        size_kb = len(json_str) / 1024

        st.info(
            f"📦 **Full project export ready** — {size_kb:.1f} KB JSON · "
            f"{'✓' if s_data else '✗'} Stripper · "
            f"{'✓' if m_data else '✗'} MEE · "
            f"{'✓' if a_data else '✗'} ATFD · "
            "Download and attach to Claude to prepare a client PPT."
        )
        st.download_button(
            label="📥 Download Full Project (for PPT)",
            data=json_str,
            file_name=filename,
            mime="application/json",
            type="primary",
            use_container_width=True,
            help="Captures every calculation, equipment sizing, feed characterization, "
                 "utilities and economics. Attach to Claude and ask: 'Prepare a PPT from this project data.'",
        )
    else:
        st.warning("⚠️ No designs yet. Run Stripper / MEE / ATFD calculations first, "
                    "then come back here to download the full project export.")
