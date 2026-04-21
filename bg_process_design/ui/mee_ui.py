"""MEE (Multi-Effect Evaporator) Design - Streamlit UI"""
import streamlit as st
import pandas as pd
from bg_process_design.modules.mee import calc_mee
from bg_process_design.db import save_design, list_designs, delete_design, log_action


def render(client, project):
    st.header("💧 Multi-Effect Evaporator (MEE) with Vapor Integration")
    st.caption(f"Project: **{project['project_name']}** ({project['project_code']})")

    tab_input, tab_saved = st.tabs(["📝 Design Inputs", "📂 Saved Designs"])
    with tab_input:
        _render_input_form(client, project)
    with tab_saved:
        _render_saved_designs(client, project)


def _render_input_form(client, project):
    st.subheader("Design Inputs")

    # Pull in stripper bottoms if available
    stripper_bottoms = None
    if "stripper_results" in st.session_state:
        stripper_bottoms = st.session_state["stripper_results"].get("bottoms_kgh")
        if stripper_bottoms:
            st.info(f"💡 Stripper bottoms available: **{stripper_bottoms:.1f} kg/h**. "
                    f"Use it as feed to MEE by clicking below.")
            if st.button("⬇ Pull feed from Stripper", key="pull_from_stripper"):
                st.session_state["mee_feed_prefill"] = stripper_bottoms
                st.rerun()

    default_feed = st.session_state.get("mee_feed_prefill", 18000.0)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Feed & Concentrate**")
        feed = st.number_input("Feed rate (kg/h)", value=float(default_feed),
                                min_value=0.0, step=100.0, key="mee_ui_number_input_1")
        feed_ts = st.number_input("Feed TS (%)", value=2.2, min_value=0.0, max_value=50.0, step=0.1, key="mee_ui_number_input_2") / 100.0
        out_ts = st.number_input("Outlet TS (%) — MEE concentrate", value=43.0,
                                  min_value=5.0, max_value=70.0, step=1.0, key="mee_ui_number_input_3") / 100.0

    with c2:
        st.markdown("**Steam Side**")
        steam_p = st.number_input("Steam pressure (bar-a)", value=3.0, min_value=1.0, max_value=10.0, step=0.1, key="mee_ui_number_input_4")
        U_ph = st.number_input("U pre-heater (W/m²K)", value=800, min_value=200, max_value=1500, step=50, key="mee_ui_number_input_5")
        cw_in = st.number_input("CW in (°C)", value=32.0, key="mee_ui_number_input_6")
        cw_out = st.number_input("CW out (°C)", value=38.0, key="mee_ui_number_input_7")

    with c3:
        st.markdown("**Vapor Integration (from Stripper)**")
        str_vap = st.number_input("Stripper vapor available (kg/h)", value=0.0, min_value=0.0, step=10.0,
                                   help="Set to 0 if no vapor integration", key="mee_ui_number_input_8")
        str_solv = st.number_input("Stripper vapor solvent %", value=45.0, min_value=0.0, max_value=100.0, key="mee_ui_number_input_9") / 100.0
        str_water = st.number_input("Stripper vapor water %", value=55.0, min_value=0.0, max_value=100.0, key="mee_ui_number_input_10") / 100.0

    # ----- Number of Effects (drives dynamic inputs below) -----
    st.markdown("---")
    st.markdown("**Evaporator Configuration**")
    n_effects = st.select_slider(
        "Number of Effects",
        options=[2, 3, 4, 5, 6, 7],
        value=4,
        help="Pick the number of MEE effects. Inputs below adjust automatically.", key="mee_ui_select_slider_11")
    n_ph = n_effects + 1  # +1 for PH-C (condenser preheater)

    # Auto-generate defaults for N effects
    from bg_process_design.modules.mee import (
        _generate_default_shell_temps,
        _generate_default_bpr,
        _generate_default_feed_inlets,
        _generate_default_product_outlets,
    )
    default_shell_T = _generate_default_shell_temps(n_effects)
    default_bpr = _generate_default_bpr(n_effects)
    default_U = [max(400, 700 - i * 50) for i in range(n_effects)]
    default_feed_in = _generate_default_feed_inlets(n_ph)
    default_prod_out = _generate_default_product_outlets(n_ph)

    st.markdown(f"**Effect Shell Temperatures (°C)** — E-1 hottest, E-{n_effects} coolest")
    cols_T = st.columns(n_effects)
    effect_temps = []
    for i, col in enumerate(cols_T):
        with col:
            t = st.number_input(
                f"E-0{i+1} Shell T",
                value=float(default_shell_T[i]),
                min_value=30.0, max_value=180.0, step=1.0,
                key=f"mee_t_{n_effects}_{i}"
            )
            effect_temps.append(t)

    st.markdown("**Boiling Point Rise per effect (°C)**")
    cols_B = st.columns(n_effects)
    bpr_list = []
    for i, col in enumerate(cols_B):
        with col:
            b = st.number_input(
                f"E-0{i+1} BPR",
                value=float(default_bpr[i]),
                min_value=0.0, max_value=20.0, step=0.5,
                key=f"mee_bpr_{n_effects}_{i}"
            )
            bpr_list.append(b)

    st.markdown("**U — Calandria (W/m²K) per effect**")
    cols_U = st.columns(n_effects)
    U_list = []
    for i, col in enumerate(cols_U):
        with col:
            u = st.number_input(
                f"U E-0{i+1}",
                value=int(default_U[i]),
                min_value=200, max_value=1500, step=50,
                key=f"mee_u_{n_effects}_{i}"
            )
            U_list.append(u)

    with st.expander(f"⚙ Feed & Product Temperatures through Pre-Heaters (PH-1 → PH-{n_effects} + PH-C)"):
        st.caption(f"One PH per effect plus PH-C (condenser preheater) = {n_ph} pre-heaters total")
        feed_inlets = []
        product_outlets = []
        for i in range(n_ph):
            ph_name = f"PH-{i+1}" if i < n_effects else "PH-C"
            colA, colB = st.columns(2)
            with colA:
                fi = st.number_input(
                    f"{ph_name} — Feed inlet (°C)",
                    value=float(default_feed_in[i]),
                    min_value=10.0, max_value=150.0, step=1.0,
                    key=f"mee_fi_{n_effects}_{i}"
                )
                feed_inlets.append(fi)
            with colB:
                po = st.number_input(
                    f"{ph_name} — Product out (°C)",
                    value=float(default_prod_out[i]),
                    min_value=10.0, max_value=150.0, step=1.0,
                    key=f"mee_po_{n_effects}_{i}"
                )
                product_outlets.append(po)

    st.markdown("**Economics Inputs**")
    ec1, ec2, ec3 = st.columns(3)
    with ec1:
        op_h = st.number_input("Operating hours/day", value=20, min_value=1, max_value=24, key="mee_ui_number_input_12")
        op_d = st.number_input("Operating days/year", value=300, min_value=1, max_value=365, key="mee_ui_number_input_13")
    with ec2:
        steam_cost = st.number_input("Steam cost (INR/kg)", value=2.0, min_value=0.1, step=0.5, key="mee_ui_number_input_14")
        power_cost = st.number_input("Power cost (INR/kWh)", value=8.0, min_value=0.1, step=0.5, key="mee_ui_number_input_15")
    with ec3:
        cw_cost = st.number_input("CW cost (INR/m³)", value=90.0, min_value=0.0, step=10.0, key="mee_ui_number_input_16")

    # Feed characterization widget — auto-prefill from stripper if available
    from bg_process_design.ui.feed_char_ui import render_feed_char_input
    prefill_char = None
    if "stripper_results" in st.session_state:
        prefill_char = st.session_state["stripper_results"].get("bottoms_feed_characterization")
        if prefill_char:
            st.caption("💡 Auto-prefilled from Stripper bottoms characterization")

    feed_char = render_feed_char_input(
        prefix="mee",
        defaults=prefill_char,
        title="Feed Characterization (TS / COD / BOD / Salt split)",
        expanded=False
    )

    st.markdown("**Calculation Options**")
    auto_bpr = st.checkbox(
        "Auto-calculate BPR per effect from TS concentration",
        value=False,
        help="When on, BPR is calculated via correlation BPR = 0.5+0.5·exp(4·(TS-0.10)) per effect. "
             "When off, uses the BPR values entered above.", key="mee_ui_checkbox_17")

    calc_btn = st.button("▶ Calculate", type="primary", use_container_width=True, key="mee_ui_button_18")

    if calc_btn:
        inputs = {
            "feed_rate_kgh": feed, "feed_ts_pct": feed_ts, "outlet_ts_pct": out_ts,
            "n_effects": n_effects,
            "effect_temps_c": effect_temps,
            "boiling_point_rise_c": bpr_list,
            "steam_pressure_bar": steam_p,
            "stripper_vapor_kgh": str_vap,
            "stripper_vapor_solvent_pct": str_solv,
            "stripper_vapor_water_pct": str_water,
            "cw_in_c": cw_in, "cw_out_c": cw_out,
            "U_calandria": U_list, "U_preheater": U_ph,
            "feed_inlet_temps": feed_inlets,
            "product_outlet_temps": product_outlets,
            "operating_hours_day": op_h, "operating_days_year": op_d,
            "steam_cost_inr_kg": steam_cost, "power_cost_inr_kwh": power_cost,
            "cw_cost_inr_m3": cw_cost,
            "feed_characterization": feed_char,
            "auto_bpr_from_ts": auto_bpr,
        }
        try:
            results = calc_mee(inputs)
            st.session_state["mee_results"] = results
            st.session_state["mee_inputs"] = inputs
            st.success(f"✅ Calculation complete for {n_effects}-effect MEE")
        except Exception as e:
            st.error(f"Calculation failed: {e}")

    if "mee_results" in st.session_state:
        _render_results(client, project, st.session_state["mee_results"],
                       st.session_state["mee_inputs"])


def _render_results(client, project, r, inputs):
    st.divider()
    n_eff = r.get("n_effects", len(r["effects"]))
    st.subheader(f"📊 Results Summary — {n_eff}-Effect MEE")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Evap", f"{r['total_evap_kgh']:.0f} kg/h")
    m2.metric("Concentrate", f"{r['final_concentrate_kgh']:.0f} kg/h")
    m3.metric("Steam", f"{r['steam_consumption_kgh']:.0f} kg/h")
    m4.metric("Steam Economy", f"{r['steam_economy']:.2f}")

    st.markdown(f"#### Effect-wise Mass & Heat Balance ({n_eff} effects)")
    eff_rows = []
    for e in r["effects"]:
        eff_rows.append({
            "Effect": f"E-0{e['effect_no']}",
            "Feed (kg/h)": f"{e['feed_kgh']:.0f}",
            "Feed TS %": f"{e['feed_conc']*100:.2f}",
            "Product (kg/h)": f"{e['product_kgh']:.0f}",
            "Product TS %": f"{e['product_conc']*100:.2f}",
            "Evap (kg/h)": f"{e['evap_kgh']:.0f}",
            "Shell T (°C)": f"{e['shell_temp_c']:.1f}",
            "Boil T (°C)": f"{e.get('boiling_temp_elevated_c', 0):.1f}",
            "LMTD (°C)": f"{e['lmtd_c']:.2f}",
            "HTA calc (m²)": f"{e['HTA_calc_m2']:.1f}",
            "HTA sel (m²)": f"{e['HTA_selected_m2']:.0f}",
        })
    st.dataframe(pd.DataFrame(eff_rows), use_container_width=True, hide_index=True)

    st.markdown(f"#### Pre-Heater Design ({len(r['preheaters'])} PHs: PH-1..PH-{n_eff} + PH-C)")
    ph_rows = []
    for p in r["preheaters"]:
        ph_rows.append({
            "PH": p["ph_name"],
            "Shell T (°C)": f"{p['shell_temp_c']:.1f}",
            "Feed in (°C)": f"{p['feed_inlet_c']:.1f}",
            "Feed out (°C)": f"{p['feed_outlet_c']:.1f}",
            "Q (kcal/h)": f"{p['Q_kcalh']:.0f}",
            "LMTD (°C)": f"{p['lmtd_c']:.2f}",
            "HTA calc (m²)": f"{p['HTA_calc_m2']:.1f}",
            "HTA sel (m²)": f"{p['HTA_selected_m2']:.0f}",
            "Vapor consumed (kg/h)": f"{p['vapor_consumed_kgh']:.1f}",
        })
    st.dataframe(pd.DataFrame(ph_rows), use_container_width=True, hide_index=True)

    with st.expander("🔍 Condenser & Utilities"):
        cond = r["condenser"]
        util = r["utilities"]
        cu1, cu2 = st.columns(2)
        with cu1:
            st.markdown("**Condenser**")
            cd = [
                ("Heat load", f"{cond['heat_load_kcalh']:.0f} kcal/h"),
                ("LMTD", f"{cond['lmtd_c']:.2f} °C"),
                ("HTA calc", f"{cond['HTA_calc_m2']:.1f} m²"),
                ("HTA selected", f"{cond['HTA_selected_m2']:.0f} m²"),
                ("CW flow", f"{cond['cw_flow_m3h']:.1f} m³/h"),
            ]
            st.dataframe(pd.DataFrame(cd, columns=["Parameter", "Value"]),
                         use_container_width=True, hide_index=True)
        with cu2:
            st.markdown("**Utilities**")
            ud = [
                ("Steam", f"{util['steam_kgh']:.0f} kg/h"),
                ("Power", f"{util['power_kw']:.1f} kW"),
                ("CW circulation", f"{util['cw_m3h']:.1f} m³/h"),
                ("CW makeup (2%)", f"{util['cw_makeup_m3h']:.2f} m³/h"),
            ]
            st.dataframe(pd.DataFrame(ud, columns=["Parameter", "Value"]),
                         use_container_width=True, hide_index=True)

    with st.expander("💰 Economics"):
        ec = r["economics"]
        ec_rows = [
            ("Operating hours/day", f"{ec['operating_hours_day']}"),
            ("Operating days/year", f"{ec['operating_days_year']}"),
            ("Daily steam cost", f"₹{ec['daily_steam_cost_inr']:,.0f}"),
            ("Daily power cost", f"₹{ec['daily_power_cost_inr']:,.0f}"),
            ("Daily CW cost", f"₹{ec['daily_cw_cost_inr']:,.0f}"),
            ("Total daily op cost", f"₹{ec['total_daily_op_cost_inr']:,.0f}"),
            ("Annual op cost", f"₹{ec['annual_op_cost_inr']:,.0f}"),
            ("Cost per KL treated", f"₹{ec['cost_per_kl_inr']:.2f}"),
        ]
        st.dataframe(pd.DataFrame(ec_rows, columns=["Parameter", "Value"]),
                     use_container_width=True, hide_index=True)

    # Equipment Sizing — VLS per effect, tube bundles, full pump list
    if r.get("pumps") or (r["effects"] and r["effects"][0].get("vls")):
        with st.expander("⚙️ Equipment Sizing — VLS, Tube Bundles, Pumps"):
            from bg_process_design.ui.equipment_ui import (
                render_pumps_table, render_tube_bundle,
                render_vls, render_calandria_detail,
            )

            # VLS + Calandria tubes per effect
            st.markdown("#### Calandria + VLS per Effect")
            for e in r["effects"]:
                st.markdown(f"**E-0{e['effect_no']}** — Calandria HTA {e['HTA_selected_m2']} m²")
                render_calandria_detail(e)
                st.markdown("")

            # Pre-heater tubes
            if r["preheaters"] and r["preheaters"][0].get("tubes"):
                st.markdown("#### Pre-Heater Tube Bundles")
                ph_cols = st.columns(min(3, len(r["preheaters"])))
                for i, ph in enumerate(r["preheaters"]):
                    with ph_cols[i % 3]:
                        render_tube_bundle(ph["tubes"], title=ph["ph_name"])

            # Condenser tubes
            if r["condenser"].get("tubes"):
                st.markdown("#### Condenser")
                render_tube_bundle(r["condenser"]["tubes"], title="Final Condenser")

            # Full pump list
            if r.get("pumps"):
                render_pumps_table(r["pumps"], title="MEE Pump List")

    # Feed characterization per effect
    if r.get("feed_characterization"):
        with st.expander("🧫 Feed Characterization — Per Effect Propagation"):
            prop_rows = []
            for e in r["effects"]:
                fc_out = e.get("feed_characterization_out", {})
                prop_rows.append({
                    "Effect": f"E-0{e['effect_no']}",
                    "TS %": f"{fc_out.get('ts_pct', 0):.2f}",
                    "TDS %": f"{fc_out.get('tds_pct', 0):.2f}",
                    "COD mg/L": f"{fc_out.get('cod_mgl', 0):,.0f}",
                    "BOD mg/L": f"{fc_out.get('bod_mgl', 0):,.0f}",
                    "Cl mg/L": f"{fc_out.get('chlorides_mgl', 0):,.0f}",
                    "SO₄ mg/L": f"{fc_out.get('sulphates_mgl', 0):,.0f}",
                })
            st.dataframe(pd.DataFrame(prop_rows), use_container_width=True, hide_index=True)
            st.caption("All non-volatile species concentrate as water evaporates through each effect. "
                       "COD and BOD carry through with the liquid stream.")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**MEE Inlet Feed**")
                from bg_process_design.ui.feed_char_ui import render_feed_char_display
                render_feed_char_display(r["feed_characterization"], label="Inlet")
            with c2:
                st.markdown("**MEE Concentrate (→ ATFD)**")
                render_feed_char_display(r["concentrate_feed_characterization"], label="Concentrate")

    # Salt routing
    if r.get("salt_routing"):
        sr = r["salt_routing"]
        with st.expander("⚗️ Salt Routing & Crystallization Estimate"):
            sr_rows = [
                ("Total solids in feed", f"{sr['total_solids_kgh']:.1f} kg/h"),
                ("Crystalline salts (fraction of solids)", f"{sr['crystalline_salt_kgh']:.1f} kg/h"),
                ("Non-crystalline salts", f"{sr['non_crystalline_salt_kgh']:.1f} kg/h"),
                ("Crystallization saturation point", f"{sr['crystallization_saturation_pct']:.0f} %"),
                ("MEE outlet TS", f"{sr['mee_outlet_ts_pct']:.1f} %"),
                ("Precipitated (crystallized) salt", f"{sr['precipitated_salt_kgh']:.1f} kg/h"),
                ("Remaining in mother liquor", f"{sr['remaining_in_ml_kgh']:.1f} kg/h"),
            ]
            st.dataframe(pd.DataFrame(sr_rows, columns=["Parameter", "Value"]),
                         use_container_width=True, hide_index=True)
            st.caption("Crystalline salts (NaCl, Na₂SO₄ etc.) precipitate once MEE outlet TS exceeds "
                       "saturation (~36%). Non-crystalline species stay in mother liquor to ATFD.")

    st.divider()
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        design_name = st.text_input("Design name (optional)",
                                     placeholder="e.g. Rev 0 - 4E with Vap Integration",
                                     key="mee_design_name")
    with c2:
        st.write("")
        st.write("")
        if st.button("💾 Save to DB", type="primary", use_container_width=True, key="mee_save"):
            if not client:
                st.warning("Supabase not configured.")
            else:
                saved = save_design(client, "mee", project["id"], inputs, r,
                                    design_name=design_name,
                                    created_by=project.get("created_by", ""))
                if saved:
                    log_action(client, project["id"], "mee", "create",
                               project.get("created_by", ""), {"design_id": saved["id"]})
                    st.success(f"✅ Saved. ID: {saved['id'][:8]}…")
    with c3:
        st.write("")
        st.write("")
        from bg_process_design.utils.export_utils import (
            export_mee_design, to_json_string, generate_filename
        )
        export_data = export_mee_design(project, r, inputs)
        json_str = to_json_string(export_data)
        filename = generate_filename(project, "mee")
        st.download_button(
            label="📥 Download for PPT",
            data=json_str,
            file_name=filename,
            mime="application/json",
            use_container_width=True,
            help="Download design data as JSON. Attach to Claude and ask to prepare a PPT.",
            key="mee_download"
        )


def _render_saved_designs(client, project):
    st.subheader("Saved MEE Designs")
    if not client:
        st.info("Supabase not configured.")
        return

    designs = list_designs(client, "mee", project["id"])
    if not designs:
        st.info("No saved MEE designs for this project yet.")
        return

    for d in designs:
        with st.expander(f"📋 {d.get('design_name', 'unnamed')}  "
                        f"— Evap {d.get('total_evap_kgh', 0):.0f} kg/h, "
                        f"SE {d.get('steam_economy', 0):.2f}  ({d['created_at'][:10]})"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Feed", f"{d.get('feed_kgh') or 0:.0f} kg/h")
            c2.metric("Evap", f"{d.get('total_evap_kgh') or 0:.0f} kg/h")
            c3.metric("Steam", f"{d.get('steam_consumption_kgh') or 0:.0f} kg/h")
            c4.metric("SE", f"{d.get('steam_economy') or 0:.2f}")

            b1, b2 = st.columns(2)
            with b1:
                if st.button("📥 Load", key=f"mee_load_{d['id']}"):
                    st.session_state["mee_results"] = d["results"]
                    st.session_state["mee_inputs"] = d["inputs"]
                    st.rerun()
            with b2:
                if st.button("🗑 Delete", key=f"mee_del_{d['id']}"):
                    if delete_design(client, "mee", d["id"]):
                        st.success("Deleted.")
                        st.rerun()
