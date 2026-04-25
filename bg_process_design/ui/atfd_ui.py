"""ATFD (Agitated Thin Film Dryer) Design - Streamlit UI"""
import streamlit as st
import pandas as pd
from bg_process_design.modules.atfd import calc_atfd
from bg_process_design.db import save_design, list_designs, delete_design, log_action


def render(client, project):
    st.header("🌡 Agitated Thin Film Dryer (ATFD)")
    st.caption(f"Project: **{project['project_name']}** ({project['project_code']})")

    tab_input, tab_saved = st.tabs(["📝 Design Inputs", "📂 Saved Designs"])
    with tab_input:
        _render_input_form(client, project)
    with tab_saved:
        _render_saved_designs(client, project)


def _render_input_form(client, project):
    st.subheader("Design Inputs")

    # Pull from MEE concentrate
    if "mee_results" in st.session_state:
        mee_conc = st.session_state["mee_results"].get("final_concentrate_kgh")
        mee_out_ts = st.session_state["mee_results"].get("outlet_ts_pct")
        if mee_conc:
            st.info(f"💡 MEE concentrate available: **{mee_conc:.1f} kg/h** at "
                    f"**{mee_out_ts:.1f}% TS**. Click to prefill feed.")
            if st.button("⬇ Pull feed from MEE", key="pull_from_mee"):
                st.session_state["atfd_feed_prefill"] = mee_conc
                st.session_state["atfd_ts_prefill"] = mee_out_ts / 100.0
                st.rerun()

    default_feed = st.session_state.get("atfd_feed_prefill", 860.0)
    default_ts = st.session_state.get("atfd_ts_prefill", 0.40)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Feed**")
        feed = st.number_input("Feed rate (kg/h)", value=float(default_feed),
                                min_value=0.0, step=10.0, key="atfd_ui_number_input_1")
        feed_ts = st.number_input("Feed TS (%)", value=float(default_ts * 100),
                                   min_value=10.0, max_value=70.0, step=1.0, key="atfd_ui_number_input_2") / 100.0
        feed_temp = st.number_input("Feed temp (°C)", value=55.0, min_value=20.0, max_value=100.0, key="atfd_ui_number_input_3")
        cp_feed = st.number_input("Sp. heat of feed (kcal/kg.K)", value=0.80,
                                   min_value=0.1, max_value=1.5, step=0.05, key="atfd_ui_number_input_4")

    with c2:
        st.markdown("**Product & Dryer**")
        product_ts = st.number_input("Product TS (%) — target solids", value=90.0,
                                      min_value=50.0, max_value=99.5, step=1.0, key="atfd_ui_number_input_5") / 100.0
        shell_temp = st.number_input("Shell temp (°C)", value=170.0,
                                      min_value=100.0, max_value=250.0, step=5.0, key="atfd_ui_number_input_6")
        steam_p = st.number_input("Shell steam pressure (bar-a)", value=8.0,
                                   min_value=1.0, max_value=20.0, step=0.5, key="atfd_ui_number_input_7")
        BPE = st.number_input("Boiling point elevation (°C)", value=10.0,
                               min_value=0.0, max_value=50.0, step=1.0, key="atfd_ui_number_input_8")
        U = st.number_input("U dryer (W/m²K)", value=230.0, min_value=100.0, max_value=500.0, step=10.0, key="atfd_ui_number_input_9")

    with c3:
        st.markdown("**Condenser & Blower**")
        cw_in = st.number_input("CW in (°C)", value=32.0, key="atfd_ui_number_input_10")
        cw_out = st.number_input("CW out (°C)", value=38.0, key="atfd_ui_number_input_11")
        subcool = st.number_input("Subcooling (°C)", value=40.0, min_value=0.0, max_value=60.0, key="atfd_ui_number_input_12")
        air_inleak = st.number_input("Air in-leak (% of vapor)", value=20.0,
                                      min_value=0.0, max_value=50.0, step=5.0, key="atfd_ui_number_input_13") / 100.0
        blower_dp = st.number_input("Blower ΔP (mmWC)", value=200, min_value=50, max_value=500, step=10, key="atfd_ui_number_input_14")
        blower_eff = st.number_input("Blower efficiency", value=0.40, min_value=0.2, max_value=0.8, step=0.05, key="atfd_ui_number_input_15")

    # Feed characterization widget — auto-prefill from MEE concentrate if available
    from bg_process_design.ui.feed_char_ui import render_feed_char_input
    prefill_char = None
    if "mee_results" in st.session_state:
        prefill_char = st.session_state["mee_results"].get("concentrate_feed_characterization")
        if prefill_char:
            st.caption("💡 Auto-prefilled from MEE concentrate characterization")

    feed_char = render_feed_char_input(
        prefix="atfd",
        defaults=prefill_char,
        title="Feed Characterization (TS / COD / BOD / Salt split)",
        expanded=False
    )

    # v7: HX tube geometry & U-values
    from bg_process_design.ui.hx_inputs import render_atfd_hx_inputs
    hx_inputs = render_atfd_hx_inputs()

    calc_btn = st.button("▶ Calculate", type="primary", use_container_width=True, key="atfd_ui_button_16")

    if calc_btn:
        inputs = {
            "feed_rate_kgh": feed, "feed_ts_pct": feed_ts, "feed_temp_c": feed_temp,
            "sp_heat_feed": cp_feed, "product_ts_pct": product_ts,
            "shell_temp_c": shell_temp, "steam_pressure_bar": steam_p,
            "boiling_point_elevation_c": BPE, "U_dryer": U,
            "cw_in_c": cw_in, "cw_out_c": cw_out, "subcooling_c": subcool,
            "air_inleak_pct": air_inleak, "blower_dp_mmwc": blower_dp,
            "blower_efficiency": blower_eff,
            "feed_characterization": feed_char,
        }
        # v7: merge HX specs and U_cond_atfd
        inputs.update(hx_inputs)
        try:
            results = calc_atfd(inputs)
            st.session_state["atfd_results"] = results
            st.session_state["atfd_inputs"] = inputs
            st.success("✅ Calculation complete")
        except Exception as e:
            st.error(f"Calculation failed: {e}")

    if "atfd_results" in st.session_state:
        _render_results(client, project, st.session_state["atfd_results"],
                       st.session_state["atfd_inputs"])


def _render_results(client, project, r, inputs):
    st.divider()
    st.subheader("📊 Results Summary")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("HTA Selected", f"{r['HTA_selected_m2']} m²", f"calc {r['HTA_calc_m2']:.1f}")
    m2.metric("Motor", f"{r['motor_hp']} HP")
    m3.metric("Steam", f"{r['steam_consumption_kgh']:.0f} kg/h")
    m4.metric("Water Evap", f"{r['water_evap_kgh']:.1f} kg/h")

    u1, u2, u3, u4 = st.columns(4)
    u1.metric("Product out", f"{r['product_kgh']:.1f} kg/h")
    u2.metric("Condenser HTA", f"{r['condenser']['HTA_selected_m2']:.0f} m²")
    u3.metric("CW Flow", f"{r['condenser']['cw_flow_m3h']:.1f} m³/h")
    u4.metric("Blower Motor", f"{r['blower']['motor_hp']} HP")

    with st.expander("🔍 Mass Balance"):
        rows = [
            ("Feed rate", f"{r['feed_kgh']:.1f} kg/h"),
            ("Feed TS", f"{r['feed_ts_pct']:.1f}%"),
            ("Solids (in)", f"{r['solids_kgh']:.1f} kg/h"),
            ("Water (in)", f"{r['water_in_kgh']:.1f} kg/h"),
            ("Product TS", f"{r['product_ts_pct']:.1f}%"),
            ("Product (out)", f"{r['product_kgh']:.1f} kg/h"),
            ("Water evaporated", f"{r['water_evap_kgh']:.1f} kg/h"),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                     use_container_width=True, hide_index=True)

    with st.expander("🔍 Dryer Heat Balance"):
        rows = [
            ("Shell temp", f"{r['shell_temp_c']:.1f} °C"),
            ("Shell pressure", f"{r['shell_pressure_bar']:.1f} bar-a"),
            ("BPE", f"{r['bpe_c']:.1f} °C"),
            ("Boiling temp (elevated)", f"{r['boiling_temp_c']:.1f} °C"),
            ("LMTD", f"{r['lmtd_c']:.1f} °C"),
            ("U dryer", f"{r['U_dryer']:.0f} W/m²K"),
            ("Sensible heat", f"{r['Q_sensible_kcalh']:.0f} kcal/h"),
            ("Latent heat req", f"{r['Q_latent_kcalh']:.0f} kcal/h"),
            ("Total heat req", f"{r['Q_total_kcalh']:.0f} kcal/h"),
            ("HTA (calc)", f"{r['HTA_calc_m2']:.2f} m²"),
            ("HTA (selected)", f"{r['HTA_selected_m2']} m²"),
            ("Motor HP (selected)", f"{r['motor_hp']}"),
            ("Consumed power", f"{r['power_consumed_kwh']} kWh/h"),
            ("Connected load", f"{r['connected_load_kw']:.1f} kW"),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                     use_container_width=True, hide_index=True)

    with st.expander("🔍 Condenser"):
        c = r["condenser"]
        rows = [
            ("Vapor in", f"{c['vapor_in_kgh']:.1f} kg/h"),
            ("Inert in", f"{c['inert_in_kgh']:.1f} kg/h"),
            ("Heat load", f"{c['heat_load_kcalh']:.0f} kcal/h"),
            ("LMTD", f"{c['lmtd_c']:.2f} °C"),
            ("HTA calc", f"{c['HTA_calc_m2']:.2f} m²"),
            ("HTA selected", f"{c['HTA_selected_m2']} m²"),
            ("CW flow", f"{c['cw_flow_m3h']:.1f} m³/h"),
            ("CW in → out", f"{c['cw_in_c']:.0f} → {c['cw_out_c']:.0f} °C"),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                     use_container_width=True, hide_index=True)

    with st.expander("🔍 Blower"):
        b = r["blower"]
        rows = [
            ("Vapor vol", f"{b['vapor_vol_m3h']:.1f} m³/h"),
            ("Vapor vol (CFM)", f"{b['vapor_vol_cfm']:.1f} CFM"),
            ("Pressure drop", f"{b['pressure_drop_mmwc']:.0f} mmWC"),
            ("Efficiency", f"{b['efficiency']:.2f}"),
            ("Power", f"{b['power_kw']:.2f} kW"),
            ("Motor HP", f"{b['motor_hp']}"),
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                     use_container_width=True, hide_index=True)

    # Feed characterization propagation (final stage of plant)
    if r.get("dry_product_feed_characterization"):
        with st.expander("🧫 Feed Characterization — Dry Product (Final Output)"):
            from bg_process_design.ui.feed_char_ui import render_feed_char_display
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**ATFD Feed (MEE concentrate)**")
                render_feed_char_display(r["feed_characterization"], label="In")
            with c2:
                st.markdown("**Dry Product**")
                render_feed_char_display(r["dry_product_feed_characterization"], label="Out")
            st.caption("All non-volatile species (TS, COD, salts) concentrate as water evaporates. "
                       "Dry product represents the final solids stream for disposal/recovery.")

    # Equipment Sizing
    if r.get("pumps") or r.get("condenser", {}).get("tubes"):
        with st.expander("⚙️ Equipment Sizing — Pumps & Tubes"):
            from bg_process_design.ui.equipment_ui import render_pumps_table, render_tube_bundle

            if r["condenser"].get("tubes"):
                render_tube_bundle(r["condenser"]["tubes"], title="Condenser Tube Bundle")

            if r.get("pumps"):
                render_pumps_table(r["pumps"], title="ATFD Pump List")

    st.divider()
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        design_name = st.text_input("Design name (optional)",
                                     placeholder="e.g. Rev 0 - 22 m² ATFD",
                                     key="atfd_design_name")
    with c2:
        st.write("")
        st.write("")
        if st.button("💾 Save to DB", type="primary", use_container_width=True, key="atfd_save"):
            if not client:
                st.warning("Supabase not configured.")
            else:
                saved = save_design(client, "atfd", project["id"], inputs, r,
                                    design_name=design_name,
                                    created_by=project.get("created_by", ""))
                if saved:
                    log_action(client, project["id"], "atfd", "create",
                               project.get("created_by", ""), {"design_id": saved["id"]})
                    st.success(f"✅ Saved. Design ID: {saved.get('id', '?')}")
    with c3:
        st.write("")
        st.write("")
        from bg_process_design.utils.export_utils import (
            export_atfd_design, to_json_string, generate_filename
        )
        export_data = export_atfd_design(project, r, inputs)
        json_str = to_json_string(export_data)
        filename = generate_filename(project, "atfd")
        st.download_button(
            label="📥 Download for PPT",
            data=json_str,
            file_name=filename,
            mime="application/json",
            use_container_width=True,
            help="Download design data as JSON. Attach to Claude and ask to prepare a PPT.",
            key="atfd_download"
        )


def _render_saved_designs(client, project):
    st.subheader("Saved ATFD Designs")
    if not client:
        st.info("Supabase not configured.")
        return

    designs = list_designs(client, "atfd", project["id"])
    if not designs:
        st.info("No saved ATFD designs for this project yet.")
        return

    for d in designs:
        with st.expander(f"📋 {d.get('design_name', 'unnamed')}  "
                        f"— HTA {(d.get('results') or {}).get('HTA_selected_m2', 0)} m², "
                        f"Motor {(d.get('results') or {}).get('motor_hp', 0)} HP  ({d['created_at'][:10]})"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Feed", f"{(d.get('results') or {}).get('feed_kgh') or 0:.0f} kg/h")
            c2.metric("Product", f"{(d.get('results') or {}).get('product_kgh') or 0:.1f} kg/h")
            c3.metric("HTA", f"{(d.get('results') or {}).get('HTA_selected_m2') or 0} m²")
            c4.metric("Steam", f"{(d.get('results') or {}).get('steam_consumption_kgh') or 0:.0f} kg/h")

            b1, b2 = st.columns(2)
            with b1:
                if st.button("📥 Load", key=f"atfd_load_{d['id']}"):
                    st.session_state["atfd_results"] = d["results"]
                    st.session_state["atfd_inputs"] = d["inputs"]
                    st.rerun()
            with b2:
                if st.button("🗑 Delete", key=f"atfd_del_{d['id']}"):
                    if delete_design(client, "atfd", d["id"]):
                        st.success("Deleted.")
                        st.rerun()
