"""Stripper Column Design - Streamlit UI"""
import streamlit as st
import pandas as pd
from bg_process_design.modules.stripper import calc_stripper
from bg_process_design.utils.solvents import list_solvent_names
from bg_process_design.db import save_design, list_designs, get_design, delete_design, log_action


def render(client, project):
    st.header("🧪 Stripper Column Design")
    st.caption(f"Project: **{project['project_name']}** ({project['project_code']})")

    tab_input, tab_saved = st.tabs(["📝 Design Inputs", "📂 Saved Designs"])

    with tab_input:
        _render_input_form(client, project)

    with tab_saved:
        _render_saved_designs(client, project)


def _render_input_form(client, project):
    st.subheader("Design Inputs")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Mass Balance**")
        feed = st.number_input("Feed rate (kg/h)", value=5000.0, min_value=0.0, step=100.0)
        solv_frac = st.number_input("Solvent fraction (w/w)", value=0.07, min_value=0.0, max_value=1.0, step=0.01, format="%.3f")
        solids_frac = st.number_input("Solids fraction (w/w)", value=0.07, min_value=0.0, max_value=1.0, step=0.01, format="%.3f")
        water_frac = st.number_input("Water fraction (w/w)", value=0.86, min_value=0.0, max_value=1.0, step=0.01, format="%.3f")
        recov = st.number_input("Solvent recovery (%)", value=98.0, min_value=80.0, max_value=100.0, step=0.5) / 100.0

    with col2:
        st.markdown("**Operating Conditions**")
        feed_temp = st.number_input("Feed temperature (°C)", value=85.0, min_value=20.0, max_value=150.0)
        steam_p = st.number_input("Steam pressure (bar-a)", value=3.0, min_value=1.0, max_value=10.0, step=0.1)
        approach = st.number_input("Approach (°C)", value=35.0, min_value=5.0, max_value=100.0)
        reflux = st.number_input("Reflux ratio L/D", value=0.25, min_value=0.0, max_value=10.0, step=0.05)
        sp_solv = st.number_input("Sp. heat solvent (kJ/kg.K)", value=2.14, min_value=0.1, step=0.1)
        rho_L = st.number_input("Liquid density (kg/m³)", value=900.0, min_value=500.0, max_value=1500.0)

    with col3:
        st.markdown("**Column Hardware**")
        n_trays = st.number_input("No. of trays", value=25, min_value=5, max_value=60, step=1)
        tray_spacing = st.number_input("Tray spacing (m)", value=0.45, min_value=0.2, max_value=1.0, step=0.05)
        hole_dia = st.number_input("Tray hole dia (mm)", value=6.5, min_value=3.0, max_value=15.0, step=0.5)
        weir_height = st.number_input("Weir height (mm)", value=50.8, min_value=25.0, max_value=150.0)
        cw_in = st.number_input("CW in (°C)", value=32.0)
        cw_out = st.number_input("CW out (°C)", value=37.0)

    st.markdown("**Solvent Mixture** (enter weight fractions — will auto-normalize)")
    solv_options = list_solvent_names()
    default_mix = {"Methanol": 0.60, "Ethanol": 0.10, "Acetone": 0.10, "Toluene": 0.10, "IPA": 0.10}
    selected = st.multiselect("Solvents present", options=solv_options,
                              default=list(default_mix.keys()))

    solvent_mix = {}
    if selected:
        cols = st.columns(min(len(selected), 5))
        for i, name in enumerate(selected):
            with cols[i % 5]:
                solvent_mix[name] = st.number_input(
                    f"{name}", value=default_mix.get(name, 0.1),
                    min_value=0.0, max_value=1.0, step=0.05, format="%.3f",
                    key=f"mix_{name}"
                )

    st.markdown("**Condenser-2 (Chilled Water)** — optional")
    use_c2 = st.checkbox("Include Condenser-2 for light solvents", value=False)
    chw_in = 10.0
    chw_out = 15.0
    subcool = 30.0
    if use_c2:
        c1, c2, c3 = st.columns(3)
        with c1: chw_in = st.number_input("CHW in (°C)", value=10.0)
        with c2: chw_out = st.number_input("CHW out (°C)", value=15.0)
        with c3: subcool = st.number_input("Subcooling (°C)", value=30.0)

    fraction_sum = solv_frac + solids_frac + water_frac
    if abs(fraction_sum - 1.0) > 0.01:
        st.warning(f"⚠️ Solvent + Solids + Water = {fraction_sum:.3f} (should be 1.0)")

    # Feed characterization widget
    from bg_process_design.ui.feed_char_ui import render_feed_char_input
    feed_char = render_feed_char_input(
        prefix="stripper",
        title="Feed Characterization (TS / COD / BOD / Salt split)",
        expanded=False
    )

    calc_btn = st.button("▶ Calculate", type="primary", use_container_width=True)

    if calc_btn:
        inputs = {
            "feed_rate_kgh": feed, "solvent_frac": solv_frac, "solids_frac": solids_frac,
            "water_frac": water_frac, "solvent_mix": solvent_mix, "feed_temp_c": feed_temp,
            "steam_pressure_bar": steam_p, "approach_c": approach, "tray_spacing_m": tray_spacing,
            "tray_hole_dia_mm": hole_dia, "weir_height_mm": weir_height,
            "no_of_trays": n_trays, "reflux_ratio": reflux, "cw_in_c": cw_in, "cw_out_c": cw_out,
            "chw_in_c": chw_in, "chw_out_c": chw_out, "sp_heat_solvent": sp_solv,
            "liquid_density_kgm3": rho_L, "solvent_recovery": recov, "use_condenser2": use_c2,
            "subcooling_c": subcool,
            "feed_characterization": feed_char,
        }
        try:
            results = calc_stripper(inputs)
            st.session_state["stripper_results"] = results
            st.session_state["stripper_inputs"] = inputs
            st.success("✅ Calculation complete")
        except Exception as e:
            st.error(f"Calculation failed: {e}")

    if "stripper_results" in st.session_state:
        _render_results(client, project, st.session_state["stripper_results"],
                       st.session_state["stripper_inputs"])


def _render_results(client, project, r, inputs):
    st.divider()
    st.subheader("📊 Results Summary")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Column Dia", f"{r['column_dia_selected_m']:.2f} m",
              f"calc {r['column_dia_calc_m']:.3f}")
    m2.metric("Reboiler HTA", f"{r['reboiler_HTA_selected']:.1f} m²",
              f"calc {r['reboiler_HTA_calc']:.1f}")
    m3.metric("Condenser-1 HTA", f"{r['condenser1_HTA_selected']:.1f} m²",
              f"calc {r['condenser1_HTA_calc']:.1f}")
    m4.metric("Steam", f"{r['steam_consumption_kgh']:.0f} kg/h")

    u1, u2, u3, u4 = st.columns(4)
    u1.metric("Distillate", f"{r['distillate_kgh']:.1f} kg/h")
    u2.metric("Bottoms", f"{r['bottoms_kgh']:.1f} kg/h")
    u3.metric("CW Flow", f"{r['cw_flow_m3h']:.1f} m³/h")
    u4.metric("Total Power", f"{r['total_power_kwh']:.2f} kW")

    with st.expander("🔍 Detailed Column Hydraulics"):
        rows = [
            ("Vapor flow", f"{r['vapor_flow_kgh']:.1f} kg/h"),
            ("Liquid flow", f"{r['liquid_flow_kgh']:.1f} kg/h"),
            ("Vapor density", f"{r['vapor_density']:.3f} kg/m³"),
            ("FLV", f"{r['FLV']:.4f}"),
            ("K factor", f"{r['K_factor']:.4f}"),
            ("Flooding velocity", f"{r['flooding_velocity_ms']:.3f} m/s"),
            ("Design velocity (65% flood)", f"{r['design_velocity_ms']:.3f} m/s"),
            ("Bubbling area", f"{r['bubbling_area_m2']:.3f} m²"),
            ("Column area", f"{r['column_area_m2']:.3f} m²"),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                     use_container_width=True, hide_index=True)

    with st.expander("🔍 Tray Pressure Drop"):
        rows = [
            ("Weir length", f"{r['weir_length_m']:.3f} m"),
            ("hd (dry plate)", f"{r['hd_mm']:.2f} mm"),
            ("how (crest over weir)", f"{r['how_mm']:.2f} mm"),
            ("hl (liquid head)", f"{r['hl_mm']:.2f} mm"),
            ("ht (total head)", f"{r['ht_mm']:.2f} mm"),
            ("Froth height Zc", f"{r['froth_height_mm']:.1f} mm"),
            ("Downcomer height", f"{r['downcomer_height_mm']:.1f} mm"),
            ("ΔP per tray", f"{r['dp_per_tray_mm']:.2f} mm"),
            ("Total ΔP", f"{r['dp_total_mm']:.1f} mm ({r['dp_total_bar']:.4f} bar)"),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                     use_container_width=True, hide_index=True)

    with st.expander("🔍 Reboiler & Condensers"):
        rows = [
            ("Reboiler shell temp", f"{r['reboiler_shell_temp']:.1f} °C"),
            ("Reboiler LMTD", f"{r['reboiler_lmtd']:.2f} °C"),
            ("Reboiler heat load", f"{r['reboiler_heat_load_kcalh']:.0f} kcal/h"),
            ("  - Sensible", f"{r['reboiler_sensible_kcalh']:.0f} kcal/h"),
            ("  - Evaporation", f"{r['reboiler_evap_kcalh']:.0f} kcal/h"),
            ("Condenser-1 LMTD", f"{r['condenser1_lmtd']:.2f} °C"),
            ("Condenser-1 heat load", f"{r['condenser1_heat_load_kcalh']:.0f} kcal/h"),
            ("RCP flow", f"{r['rcp_flow_m3h']:.1f} m³/h ({r['rcp_bkw']:.2f} kW)"),
            ("Reflux pump flow", f"{r['reflux_pump_flow_m3h']:.2f} m³/h ({r['reflux_pump_bkw']:.2f} kW)"),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                     use_container_width=True, hide_index=True)

    # Feed characterization propagation
    if r.get("bottoms_feed_characterization"):
        with st.expander("🧫 Feed Characterization — Stripper Bottoms (→ feeds into MEE)"):
            from bg_process_design.ui.feed_char_ui import render_feed_char_display
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Inlet Feed**")
                render_feed_char_display(r["feed_characterization"], label="Feed")
            with c2:
                st.markdown("**Stripper Bottoms (concentrated)**")
                render_feed_char_display(r["bottoms_feed_characterization"], label="Bottoms")

    # Equipment Sizing — Pumps & Tube Bundles
    if r.get("pumps") or r.get("reboiler_tubes"):
        with st.expander("⚙️ Equipment Sizing — Pumps & Tube Bundles"):
            from bg_process_design.ui.equipment_ui import render_pumps_table, render_tube_bundle
            if r.get("pumps"):
                render_pumps_table(r["pumps"], title="Pump List")

            if r.get("reboiler_tubes"):
                st.markdown("#### Heat Exchanger Tube Bundles")
                c1, c2 = st.columns(2)
                with c1:
                    render_tube_bundle(r["reboiler_tubes"], title="Reboiler (FC type)")
                with c2:
                    render_tube_bundle(r["condenser1_tubes"], title="Condenser-1 (CW)")
                if r.get("condenser2_tubes"):
                    render_tube_bundle(r["condenser2_tubes"], title="Condenser-2 (CHW)")

    st.divider()
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        design_name = st.text_input("Design name (optional)",
                                     placeholder="e.g. Rev 0 - Base case")
    with c2:
        st.write("")
        st.write("")
        if st.button("💾 Save to DB", type="primary", use_container_width=True):
            if not client:
                st.warning("Supabase not configured — results kept in session only.")
            else:
                saved = save_design(client, "stripper", project["id"], inputs, r,
                                    design_name=design_name,
                                    created_by=project.get("created_by", ""))
                if saved:
                    log_action(client, project["id"], "stripper", "create",
                               project.get("created_by", ""), {"design_id": saved["id"]})
                    st.success(f"✅ Saved. ID: {saved['id'][:8]}…")
    with c3:
        st.write("")
        st.write("")
        from bg_process_design.utils.export_utils import (
            export_stripper_design, to_json_string, generate_filename
        )
        export_data = export_stripper_design(project, r, inputs)
        json_str = to_json_string(export_data)
        filename = generate_filename(project, "stripper")
        st.download_button(
            label="📥 Download for PPT",
            data=json_str,
            file_name=filename,
            mime="application/json",
            use_container_width=True,
            help="Download design data as JSON. Attach to Claude and ask to prepare a PPT."
        )


def _render_saved_designs(client, project):
    st.subheader("Saved Stripper Designs")
    if not client:
        st.info("Supabase not configured — no saved designs available.")
        return

    designs = list_designs(client, "stripper", project["id"])
    if not designs:
        st.info("No saved designs for this project yet.")
        return

    for d in designs:
        with st.expander(f"📋 {d.get('design_name', 'unnamed')}  "
                        f"— Col {d.get('column_dia_selected_m', 0):.2f} m, "
                        f"Steam {d.get('steam_consumption_kgh', 0):.0f} kg/h  "
                        f"({d['created_at'][:10]})"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Column Dia", f"{d.get('column_dia_selected_m') or 0:.2f} m")
            c2.metric("Trays", d.get("no_of_trays") or 0)
            c3.metric("Reboiler HTA", f"{d.get('reboiler_hta_selected') or 0:.1f} m²")
            c4.metric("Steam", f"{d.get('steam_consumption_kgh') or 0:.0f} kg/h")

            b1, b2 = st.columns(2)
            with b1:
                if st.button("📥 Load", key=f"load_{d['id']}"):
                    st.session_state["stripper_results"] = d["results"]
                    st.session_state["stripper_inputs"] = d["inputs"]
                    st.rerun()
            with b2:
                if st.button("🗑 Delete", key=f"del_{d['id']}"):
                    if delete_design(client, "stripper", d["id"]):
                        st.success("Deleted.")
                        st.rerun()
