"""Reusable equipment display widgets for all unit UIs."""
import streamlit as st
import pandas as pd


def render_pumps_table(pumps: dict, title: str = "Pump List"):
    """Show all pumps as a single table."""
    if not pumps:
        return
    st.markdown(f"#### {title}")
    rows = []
    for key, p in pumps.items():
        rows.append({
            "Pump": p.get("service", key),
            "Flow (m³/h)": f"{p.get('flow_m3h', 0):.2f}",
            "Head (MLC)": f"{p.get('head_mlc', 0):.0f}",
            "Density (kg/m³)": f"{p.get('fluid_density_kgm3', 0):.0f}",
            "Efficiency": f"{p.get('efficiency', 0):.2f}",
            "BKW (kW)": f"{p.get('brake_power_kw', 0):.2f}",
            "Motor HP": f"{p.get('motor_hp_selected', 0):.1f}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_tube_bundle(tubes: dict, title: str = "Tube Bundle"):
    """Show tube bundle geometry for a heat exchanger."""
    if not tubes or tubes.get("total_tubes", 0) == 0:
        return
    st.markdown(f"##### {title}")
    rows = [
        ("Tube OD × Thk × L",
         f"{tubes['tube_od_mm']:.1f} × {tubes['tube_thk_mm']:.1f} mm × {tubes['tube_length_m']:.1f} m"),
        ("Total tubes", f"{tubes['total_tubes']}"),
        ("Passes", f"{tubes['n_passes']}"),
        ("Tubes per pass", f"{tubes['tubes_per_pass']}"),
        ("Actual HTA", f"{tubes['actual_hta_m2']:.2f} m²"),
        ("Tube velocity", f"{tubes['tube_velocity_ms']:.2f} m/s"),
        ("Tube-side fluid flow", f"{tubes['fluid_flow_m3h']:.1f} m³/h"),
        ("Tube pitch (1.25×OD)", f"{tubes['pitch_mm']:.1f} mm"),
        ("Bundle diameter", f"{tubes['bundle_dia_m']:.3f} m"),
        ("Shell ID (selected)", f"{tubes['shell_id_selected_m']:.2f} m"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                 use_container_width=True, hide_index=True)


def render_vls(vls: dict, title: str = "Vapor-Liquid Separator"):
    """Show VLS sizing."""
    if not vls or vls.get("vessel_dia_selected_m", 0) == 0:
        return
    st.markdown(f"##### {title}")
    rows = [
        ("Vapor flow", f"{vls['vapor_flow_kgh']:.0f} kg/h"),
        ("Vapor density", f"{vls['vapor_density_kgm3']:.3f} kg/m³"),
        ("Vapor volumetric flow", f"{vls['vapor_vol_m3h']:.0f} m³/h"),
        ("K factor (Souders-Brown)", f"{vls['k_factor']:.3f}"),
        ("Terminal velocity", f"{vls['terminal_velocity_ms']:.2f} m/s"),
        ("Cross-sect area", f"{vls['cross_sect_area_m2']:.3f} m²"),
        ("Vessel dia (calc → selected)",
         f"{vls['vessel_dia_calc_m']:.3f} → {vls['vessel_dia_selected_m']:.2f} m"),
        ("L/D ratio", f"{vls['l_over_d_ratio']:.1f}"),
        ("Vessel height (T/T)", f"{vls['vessel_height_m']:.2f} m"),
        ("Holdup volume", f"{vls['holdup_volume_m3']:.2f} m³"),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                 use_container_width=True, hide_index=True)


def render_calandria_detail(effect: dict):
    """Combined display for one MEE calandria: tubes + VLS."""
    c1, c2 = st.columns(2)
    with c1:
        render_tube_bundle(effect.get("calandria_tubes", {}),
                            title=f"Calandria Tubes — E-0{effect['effect_no']}")
    with c2:
        render_vls(effect.get("vls", {}),
                    title=f"VLS — E-0{effect['effect_no']}")
