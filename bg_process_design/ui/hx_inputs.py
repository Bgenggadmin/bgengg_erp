"""
Shared HX tube geometry input widget for the Stripper, MEE, and ATFD UIs.

Renders an expander with:
  - Project-level defaults (OD, length, passes) at the top
  - One row per individual HX with overridable values pre-filled
  - Plus a 'U-value' input per HX (heat transfer coefficient)

Returns a dict that can be merged into the inputs dict passed to the engine:

    inputs = {
        ...
        "hx_specs": {
            "_project_default": {"od_mm": ..., "length_m": ..., "passes": ...} or {},
            "<hx_key>": {"od_mm": ..., "length_m": ..., "passes": ...} or {},
            ...
        },
        "U_reboiler": <float>,   # for stripper
        "U_cond1": <float>,
        ...
    }

The keys empty-out to the service preset if user leaves them at the preset value;
the resolve_hx_specs() function in equipment_sizing.py walks the override hierarchy.
"""
import streamlit as st

from bg_process_design.utils.equipment_sizing import (
    SERVICE_PRESETS, STANDARD_TUBE_OD_MM, STANDARD_PASS_COUNTS,
)


def _od_dropdown(label, default_value, key):
    """Render an OD selector — dropdown of standards + 'Custom...' option."""
    options = [str(v) for v in STANDARD_TUBE_OD_MM] + ["Custom..."]
    # Find the matching default index
    try:
        default_idx = STANDARD_TUBE_OD_MM.index(default_value)
    except ValueError:
        default_idx = len(STANDARD_TUBE_OD_MM)  # Custom

    choice = st.selectbox(label, options, index=default_idx, key=key)
    if choice == "Custom...":
        return st.number_input(
            f"  ↳ Custom {label} (mm)",
            value=float(default_value), min_value=10.0, max_value=200.0, step=0.5,
            key=f"{key}_custom"
        )
    return float(choice)


def _passes_dropdown(label, default_value, key):
    options = [str(v) for v in STANDARD_PASS_COUNTS] + ["Custom..."]
    try:
        default_idx = STANDARD_PASS_COUNTS.index(default_value)
    except ValueError:
        default_idx = len(STANDARD_PASS_COUNTS)

    choice = st.selectbox(label, options, index=default_idx, key=key)
    if choice == "Custom...":
        return st.number_input(
            f"  ↳ Custom {label}",
            value=int(default_value), min_value=1, max_value=12, step=1,
            key=f"{key}_custom"
        )
    return int(choice)


def render_stripper_hx_inputs():
    """
    Render HX tube geometry inputs for the Stripper.
    Returns ({"hx_specs": {...}, "U_reboiler": ..., "U_cond1": ..., "U_cond2": ...})
    """
    out = {"hx_specs": {}, "U_reboiler": 700.0, "U_cond1": 200.0, "U_cond2": 150.0}

    with st.expander("🔧 Heat Exchanger Geometry & U-values", expanded=False):
        st.caption(
            "Override tube specs and heat-transfer coefficients per HX. "
            "Leave at defaults for typical service. "
            "Project-level defaults apply to all HX unless individually overridden below."
        )

        # ---- Project defaults ----
        st.markdown("**Project defaults** (applies to all HX unless overridden)")
        cp1, cp2, cp3 = st.columns(3)
        proj_od = cp1.selectbox(
            "Tube OD (mm)",
            ["(use service preset)"] + [str(v) for v in STANDARD_TUBE_OD_MM],
            index=0, key="stripper_hx_proj_od"
        )
        proj_L = cp2.number_input(
            "Tube length (m)",
            value=0.0, min_value=0.0, max_value=10.0, step=0.5,
            help="0 = use service preset", key="stripper_hx_proj_L"
        )
        proj_passes = cp3.selectbox(
            "Tube passes",
            ["(use service preset)"] + [str(v) for v in STANDARD_PASS_COUNTS],
            index=0, key="stripper_hx_proj_passes"
        )

        proj_default = {}
        if proj_od != "(use service preset)":
            proj_default["od_mm"] = float(proj_od)
        if proj_L > 0:
            proj_default["length_m"] = float(proj_L)
        if proj_passes != "(use service preset)":
            proj_default["passes"] = int(proj_passes)
        out["hx_specs"]["_project_default"] = proj_default

        st.divider()

        # ---- Per-HX rows ----
        # Reboiler
        reb_preset = SERVICE_PRESETS["REBOILER"]
        st.markdown("**Reboiler** (Forced Circulation)")
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            reb_od = _od_dropdown("OD (mm)", reb_preset["od_mm"], "stripper_hx_reb_od")
        with r2:
            reb_L = st.number_input("Length (m)", value=float(reb_preset["length_m"]),
                                     min_value=0.5, max_value=10.0, step=0.5,
                                     key="stripper_hx_reb_L")
        with r3:
            reb_passes = _passes_dropdown("Passes", reb_preset["passes"], "stripper_hx_reb_passes")
        with r4:
            U_reb = st.number_input("U (W/m²·K)", value=700.0, min_value=50.0, max_value=3000.0,
                                     step=50.0, key="stripper_hx_reb_U")
        out["hx_specs"]["reboiler"] = {"od_mm": reb_od, "length_m": reb_L, "passes": reb_passes}
        out["U_reboiler"] = U_reb

        # Condenser-1
        c1_preset = SERVICE_PRESETS["CONDENSER_CW"]
        st.markdown("**Condenser-1** (CW)")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            c1_od = _od_dropdown("OD (mm)", c1_preset["od_mm"], "stripper_hx_c1_od")
        with c2:
            c1_L = st.number_input("Length (m)", value=float(c1_preset["length_m"]),
                                    min_value=0.5, max_value=10.0, step=0.5,
                                    key="stripper_hx_c1_L")
        with c3:
            c1_passes = _passes_dropdown("Passes", c1_preset["passes"], "stripper_hx_c1_passes")
        with c4:
            U_c1 = st.number_input("U (W/m²·K)", value=200.0, min_value=50.0, max_value=2000.0,
                                    step=25.0, key="stripper_hx_c1_U")
        out["hx_specs"]["condenser1"] = {"od_mm": c1_od, "length_m": c1_L, "passes": c1_passes}
        out["U_cond1"] = U_c1

        # Condenser-2 (only show if enabled)
        st.markdown("**Condenser-2** (CHW — only used if 'Include Condenser-2' is checked)")
        c2c1, c2c2, c2c3, c2c4 = st.columns(4)
        c2_preset = SERVICE_PRESETS["CONDENSER_CHW"]
        with c2c1:
            c2_od = _od_dropdown("OD (mm)", c2_preset["od_mm"], "stripper_hx_c2_od")
        with c2c2:
            c2_L = st.number_input("Length (m)", value=float(c2_preset["length_m"]),
                                    min_value=0.5, max_value=10.0, step=0.5,
                                    key="stripper_hx_c2_L")
        with c2c3:
            c2_passes = _passes_dropdown("Passes", c2_preset["passes"], "stripper_hx_c2_passes")
        with c2c4:
            U_c2 = st.number_input("U (W/m²·K)", value=150.0, min_value=50.0, max_value=2000.0,
                                    step=25.0, key="stripper_hx_c2_U")
        out["hx_specs"]["condenser2"] = {"od_mm": c2_od, "length_m": c2_L, "passes": c2_passes}
        out["U_cond2"] = U_c2

    return out


def render_mee_hx_inputs(n_effects: int = 4):
    """
    Render HX tube geometry inputs for the MEE (per-effect calandrias + N+1 PHs + 1 condenser).
    Returns ({"hx_specs": {...}, "U_calandria": [...], "U_preheater": [...], "U_cond_mee": ...})
    """
    n_ph = n_effects + 1
    out = {"hx_specs": {}, "U_calandria": [], "U_preheater": [], "U_cond_mee": 600.0}

    with st.expander("🔧 Heat Exchanger Geometry & U-values", expanded=False):
        st.caption(
            f"MEE has {n_effects} calandrias, {n_ph} pre-heaters (PH-1..PH-{n_effects}, PH-C), "
            "and 1 final condenser. Override tube specs and U-values per HX."
        )

        # ---- Project defaults ----
        st.markdown("**Project defaults** (applies to all HX unless overridden)")
        cp1, cp2, cp3 = st.columns(3)
        proj_od = cp1.selectbox(
            "Tube OD (mm)",
            ["(use service preset)"] + [str(v) for v in STANDARD_TUBE_OD_MM],
            index=0, key="mee_hx_proj_od"
        )
        proj_L = cp2.number_input(
            "Tube length (m)", value=0.0, min_value=0.0, max_value=10.0, step=0.5,
            help="0 = use service preset", key="mee_hx_proj_L"
        )
        proj_passes = cp3.selectbox(
            "Tube passes",
            ["(use service preset)"] + [str(v) for v in STANDARD_PASS_COUNTS],
            index=0, key="mee_hx_proj_passes"
        )
        proj_default = {}
        if proj_od != "(use service preset)":
            proj_default["od_mm"] = float(proj_od)
        if proj_L > 0:
            proj_default["length_m"] = float(proj_L)
        if proj_passes != "(use service preset)":
            proj_default["passes"] = int(proj_passes)
        out["hx_specs"]["_project_default"] = proj_default

        # ---- Calandrias (per effect) ----
        st.divider()
        st.markdown(f"**Calandrias** — {n_effects} effects")
        cal_preset = SERVICE_PRESETS["CALANDRIA"]
        default_U_cal = [700.0, 650.0, 600.0, 550.0, 500.0, 450.0, 400.0]
        for i in range(n_effects):
            st.markdown(f"*Effect E-0{i+1}*")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                cal_od = _od_dropdown(f"OD (mm)", cal_preset["od_mm"],
                                       f"mee_hx_cal{i}_od")
            with c2:
                cal_L = st.number_input(f"Length (m)", value=float(cal_preset["length_m"]),
                                         min_value=0.5, max_value=12.0, step=0.5,
                                         key=f"mee_hx_cal{i}_L")
            with c3:
                cal_passes = _passes_dropdown(f"Passes", cal_preset["passes"],
                                               f"mee_hx_cal{i}_passes")
            with c4:
                U_cal_i = st.number_input(
                    f"U (W/m²·K)", value=default_U_cal[i] if i < len(default_U_cal) else 500.0,
                    min_value=50.0, max_value=3000.0, step=25.0,
                    key=f"mee_hx_cal{i}_U"
                )
            out["hx_specs"][f"calandria_{i+1}"] = {
                "od_mm": cal_od, "length_m": cal_L, "passes": cal_passes
            }
            out["U_calandria"].append(U_cal_i)

        # ---- Pre-heaters ----
        st.divider()
        st.markdown(f"**Pre-heaters** — PH-1..PH-{n_effects} (vapor-fed) + PH-C (condenser-fed)")
        ph_preset = SERVICE_PRESETS["PREHEATER"]
        ph_keys = [f"preheater_{i+1}" for i in range(n_effects)] + ["preheater_c"]
        ph_labels = [f"PH-{i+1}" for i in range(n_effects)] + ["PH-C"]
        for i in range(n_ph):
            st.markdown(f"*{ph_labels[i]}*")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                ph_od = _od_dropdown(f"OD (mm)", ph_preset["od_mm"],
                                      f"mee_hx_ph{i}_od")
            with c2:
                ph_L = st.number_input(f"Length (m)", value=float(ph_preset["length_m"]),
                                        min_value=0.5, max_value=12.0, step=0.5,
                                        key=f"mee_hx_ph{i}_L")
            with c3:
                ph_passes = _passes_dropdown(f"Passes", ph_preset["passes"],
                                              f"mee_hx_ph{i}_passes")
            with c4:
                U_ph_i = st.number_input(
                    f"U (W/m²·K)", value=800.0, min_value=50.0, max_value=3000.0,
                    step=50.0, key=f"mee_hx_ph{i}_U"
                )
            out["hx_specs"][ph_keys[i]] = {
                "od_mm": ph_od, "length_m": ph_L, "passes": ph_passes
            }
            out["U_preheater"].append(U_ph_i)

        # ---- Final condenser ----
        st.divider()
        st.markdown("**Final Condenser** (CW)")
        cd_preset = SERVICE_PRESETS["MEE_CONDENSER"]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cd_od = _od_dropdown("OD (mm)", cd_preset["od_mm"], "mee_hx_cond_od")
        with c2:
            cd_L = st.number_input("Length (m)", value=float(cd_preset["length_m"]),
                                    min_value=0.5, max_value=12.0, step=0.5,
                                    key="mee_hx_cond_L")
        with c3:
            cd_passes = _passes_dropdown("Passes", cd_preset["passes"], "mee_hx_cond_passes")
        with c4:
            U_cd = st.number_input("U (W/m²·K)", value=600.0, min_value=50.0, max_value=2500.0,
                                    step=25.0, key="mee_hx_cond_U")
        out["hx_specs"]["mee_condenser"] = {
            "od_mm": cd_od, "length_m": cd_L, "passes": cd_passes
        }
        out["U_cond_mee"] = U_cd

    return out


def render_atfd_hx_inputs():
    """
    Render HX tube geometry inputs for the ATFD (just the condenser).
    Returns ({"hx_specs": {...}, "U_cond_atfd": ...})
    """
    out = {"hx_specs": {}, "U_cond_atfd": 500.0}

    with st.expander("🔧 Heat Exchanger Geometry & U-values", expanded=False):
        st.caption(
            "ATFD has one condenser HX. Override tube specs and U-value if needed."
        )

        # Project defaults
        st.markdown("**Project defaults** (applies to all HX)")
        cp1, cp2, cp3 = st.columns(3)
        proj_od = cp1.selectbox(
            "Tube OD (mm)",
            ["(use service preset)"] + [str(v) for v in STANDARD_TUBE_OD_MM],
            index=0, key="atfd_hx_proj_od"
        )
        proj_L = cp2.number_input(
            "Tube length (m)", value=0.0, min_value=0.0, max_value=10.0, step=0.5,
            help="0 = use service preset", key="atfd_hx_proj_L"
        )
        proj_passes = cp3.selectbox(
            "Tube passes",
            ["(use service preset)"] + [str(v) for v in STANDARD_PASS_COUNTS],
            index=0, key="atfd_hx_proj_passes"
        )
        proj_default = {}
        if proj_od != "(use service preset)":
            proj_default["od_mm"] = float(proj_od)
        if proj_L > 0:
            proj_default["length_m"] = float(proj_L)
        if proj_passes != "(use service preset)":
            proj_default["passes"] = int(proj_passes)
        out["hx_specs"]["_project_default"] = proj_default

        st.divider()

        # Condenser
        st.markdown("**Condenser** (CW)")
        cd_preset = SERVICE_PRESETS["ATFD_CONDENSER"]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cd_od = _od_dropdown("OD (mm)", cd_preset["od_mm"], "atfd_hx_cond_od")
        with c2:
            cd_L = st.number_input("Length (m)", value=float(cd_preset["length_m"]),
                                    min_value=0.5, max_value=10.0, step=0.5,
                                    key="atfd_hx_cond_L")
        with c3:
            cd_passes = _passes_dropdown("Passes", cd_preset["passes"], "atfd_hx_cond_passes")
        with c4:
            U_cd = st.number_input("U (W/m²·K)", value=500.0, min_value=50.0, max_value=2500.0,
                                    step=25.0, key="atfd_hx_cond_U")
        out["hx_specs"]["atfd_condenser"] = {
            "od_mm": cd_od, "length_m": cd_L, "passes": cd_passes
        }
        out["U_cond_atfd"] = U_cd

    return out
