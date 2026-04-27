"""Equipment tab — parametric calculators + line-item editor."""
from __future__ import annotations
import streamlit as st
import pandas as pd

from bg_estimation_costing import db
from bg_estimation_costing.modules import qps_calculators as qc
from bg_estimation_costing.utils.state import S, setS, new_eqp_line
from bg_estimation_costing.utils.totals import (
    total_equipment_cost, cost_summary_by,
)
from bg_estimation_costing.utils.templates import mee_skeleton
from bg_estimation_costing.ui.calc_widget import show_calc_result
from bg_estimation_costing.ui.constants import (
    SECTIONS, SUB_SECTIONS, CATEGORIES, ITEM_TYPES,
    MOC_CHOICES, CLADDING_OPTIONS, HE_LABELS,
)


def render():
    st.subheader("Equipment Cost")

    cb1, cb2, cb3 = st.columns(3)
    if cb1.button("➕ Add blank line", use_container_width=True,
                  key="eqp_add_blank"):
        lines = S("equipment_lines", []) or []
        lines.append(new_eqp_line())
        setS("equipment_lines", lines)
        st.rerun()
    if cb2.button("📋 Load MEE skeleton template",
                  use_container_width=True, key="eqp_load_skeleton"):
        setS("equipment_lines", mee_skeleton())
        st.rerun()
    if cb3.button("🗑️ Clear all lines", use_container_width=True,
                  type="secondary", key="eqp_clear"):
        setS("equipment_lines", [])
        st.rerun()

    # ── BO-master picker (pumps, valves, motors, gearboxes etc.) ──────────
    _render_bo_picker_for_equipment()

    st.divider()

    # ── Parametric Calculators ────────────────────────────────────────────
    st.markdown("### 🧮 Parametric Calculators")
    st.caption("Use these to auto-cost an equipment based on sizing inputs.")
    calc_tabs = st.tabs([
        "Stripper Column", "Heat Exchanger", "VLS", "Tank", "ATFD",
    ])

    with calc_tabs[0]: _render_stripper_column()
    with calc_tabs[1]: _render_heat_exchanger()
    with calc_tabs[2]: _render_vls()
    with calc_tabs[3]: _render_tank()
    with calc_tabs[4]: _render_atfd()

    st.divider()
    _render_lines_editor()


# ─────────────────────────────────────────────────────────────────────────────
# BO-MASTER PICKER FOR EQUIPMENT  (pumps, motors, gearboxes, valves, etc.)
# ─────────────────────────────────────────────────────────────────────────────
def _render_bo_picker_for_equipment():
    """Quick-pick from est_rm_master (BO category) for non-fab equipment."""
    bo = db.bo_items()
    if not bo:
        return  # silently skip if master is empty

    # Exclude pure-instrument rows — those belong on the EIA tab.
    # Heuristic: rm_type in instrument-y categories. Anything we keep here
    # are pumps, gearboxes, motors, mech-seals, manual valves, sight glasses.
    INSTRUMENT_TYPES = {
        "Transmitter", "Sensor", "PLC", "HMI", "Panel", "MCC", "VFD",
        "Cable", "Cabling", "Gauge",
    }
    # Also exclude control valves (sub_type='Control') — those are EIA scope
    eqp_items = [r for r in bo
                 if (r.get("rm_type") or "") not in INSTRUMENT_TYPES
                 and (r.get("sub_type") or "") != "Control"]
    if not eqp_items:
        return

    with st.expander(
        f"🔍 Pick from BO Master — pumps / motors / valves "
        f"({len(eqp_items)} items)", expanded=False,
    ):
        f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
        search   = f1.text_input(
            "Search description / vendor", key="eqp_bo_search",
            placeholder="e.g. centrifugal pump, gearbox, butterfly valve",
        ).strip().lower()
        rm_types = sorted({r.get("rm_type") or "—"
                            for r in eqp_items if r.get("rm_type")})
        type_sel = f2.selectbox("Type", ["All"] + rm_types,
                                key="eqp_bo_type")
        subtypes = sorted({r.get("sub_type") or "—"
                            for r in eqp_items if r.get("sub_type")})
        sub_sel  = f3.selectbox("Sub-type", ["All"] + subtypes,
                                key="eqp_bo_subtype")
        section  = f4.selectbox("Default Section",
                                SECTIONS,
                                index=SECTIONS.index("Evaporator"),
                                key="eqp_bo_section")

        items = eqp_items
        if search:
            items = [r for r in items
                     if search in (r.get("description", "") or "").lower()
                     or search in (r.get("ref_code", "") or "").lower()
                     or search in (r.get("rm_type", "") or "").lower()
                     or search in (r.get("vendor", "") or "").lower()]
        if type_sel != "All":
            items = [r for r in items if r.get("rm_type") == type_sel]
        if sub_sel != "All":
            items = [r for r in items if r.get("sub_type") == sub_sel]

        if not items:
            st.caption("No items match.")
            return

        st.caption(f"Showing {min(len(items), 50)} of {len(items)} item(s).")
        preview = pd.DataFrame([
            {"Ref Code":    r.get("ref_code", ""),
             "Type":        r.get("rm_type", ""),
             "Sub-type":    r.get("sub_type", ""),
             "Description": r.get("description", ""),
             "Material":    r.get("material", ""),
             "Size":        r.get("size", ""),
             "Vendor":      r.get("vendor", ""),
             "Rate (₹)":    r.get("rate", 0)}
            for r in items[:50]
        ])
        st.dataframe(
            preview.style.format({"Rate (₹)": "{:,.0f}"}),
            hide_index=True, use_container_width=True,
        )

        opts = [
            f"{r.get('ref_code','')}  |  {r.get('description','')}  "
            f"|  ₹{r.get('rate', 0):,.0f}"
            for r in items[:50]
        ]
        picked = st.multiselect(
            "Select items to add as equipment lines",
            opts, key="eqp_bo_picked",
        )
        if st.button(f"➕ Add {len(picked)} item(s) to Equipment lines",
                     type="primary",
                     disabled=(len(picked) == 0),
                     key="eqp_bo_add"):
            ref_to_item = {
                f"{r.get('ref_code','')}  |  {r.get('description','')}  "
                f"|  ₹{r.get('rate', 0):,.0f}": r
                for r in items[:50]
            }
            lines = S("equipment_lines", []) or []
            added = 0
            for label in picked:
                r = ref_to_item.get(label)
                if not r:
                    continue
                # Map rm_type → sub_section best-effort
                rm_type = (r.get("rm_type") or "").upper()
                sub = ("PUMP"   if "PUMP"   in rm_type else
                       "VALVES" if "VALVE"  in rm_type else
                       "OTHER")
                lines.append({
                    "section":     section,
                    "sub_section": sub,
                    "equipment":   r.get("rm_type", "") or "",
                    "description": (f"{r.get('description','')} "
                                    f"{r.get('size','')}").strip(),
                    "moc":         r.get("material") or "SS316L",
                    "qty":         1,
                    "unit_cost":   float(r.get("rate", 0) or 0),
                    "category":    "B.O-Local",
                    "item_type":   "MECH_EQP",
                    "calc_source": "BO-Master",
                    "design_payload": "",
                })
                added += 1
            setS("equipment_lines", lines)
            if added:
                st.success(f"✅ Added {added} item(s) to Equipment lines.")
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# CALCULATOR PANELS
# ─────────────────────────────────────────────────────────────────────────────
def _render_stripper_column():
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        sc_dia = st.number_input("Column Dia (mm)", 200, 5000, 850,
                                 step=50, key="sc_dia")
        sc_ht  = st.number_input("Column Height (m)", 1.0, 50.0, 20.0,
                                 step=0.5, key="sc_ht")
    with c2:
        sc_ph  = st.number_input("Packing Height (m)", 0.5, 40.0, 16.0,
                                 step=0.5, key="sc_ph")
        sc_typ = st.selectbox("Type", ["Tray Type", "Packed Bed Type"],
                              key="sc_typ")
    with c3:
        sc_moc = st.selectbox("Shell MOC", MOC_CHOICES,
                              index=MOC_CHOICES.index("SS316L"), key="sc_moc")
        sc_thk = st.number_input("Shell Thk (mm) [0=auto]", 0, 30, 0,
                                 key="sc_thk")
    with c4:
        sc_dish = st.number_input("Dish Thk (mm)", 3, 30, 6, key="sc_dish")
        sc_cont = st.number_input("Contingency (%)", 0.0, 50.0, 20.0,
                                  step=1.0, key="sc_cont")
    if st.button("Compute Stripper Column", key="btn_sc"):
        r = qc.stripper_column_cost(
            column_dia_mm=sc_dia, column_height_m=sc_ht,
            packing_height_m=sc_ph, column_type=sc_typ,
            moc_shell=sc_moc, moc_trays=sc_moc, moc_packing=sc_moc,
            shell_thk_mm=sc_thk if sc_thk > 0 else None,
            dish_thk_mm=sc_dish,
            rm_rates=S("rm_rates"), lab_rates=S("lab_rates"),
            contingency_pct=sc_cont/100,
        )
        show_calc_result(
            r, "Stripper Column",
            section="Stripper", sub="STRIPPER COLUMN_TRAY TYPE",
            moc=sc_moc, description=f"{sc_dia}Ø × {sc_ht}m",
            design_payload=dict(
                column_dia_mm=sc_dia, column_height_m=sc_ht,
                packing_height_m=sc_ph, column_type=sc_typ,
            ),
        )


def _render_heat_exchanger():
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        he_label = st.selectbox("Equipment label", HE_LABELS, key="he_label")
        he_hta   = st.number_input("HTA (m²)", 0.5, 1000.0, 25.0,
                                    step=0.5, key="he_hta")
    with c2:
        he_tlen = st.number_input("Tube Length (m)", 0.5, 12.0, 6.0,
                                   step=0.5, key="he_tlen")
        he_tod  = st.number_input("Tube OD (mm)", 12.7, 50.8, 25.4,
                                   step=0.1, key="he_tod")
        he_tthk = st.number_input("Tube Thk (mm)", 0.5, 5.0, 0.9,
                                   step=0.1, key="he_tthk")
    with c3:
        he_shell = st.selectbox("Shell MOC", MOC_CHOICES,
                                 index=MOC_CHOICES.index("SS304"),
                                 key="he_shell")
        he_tube  = st.selectbox("Tube MOC", MOC_CHOICES,
                                 index=MOC_CHOICES.index("Ti Gr2"),
                                 key="he_tube")
        he_ts    = st.selectbox("Tubesheet MOC", MOC_CHOICES,
                                 index=MOC_CHOICES.index("SS316L"),
                                 key="he_ts")
    with c4:
        he_de    = st.selectbox("Dishend MOC", MOC_CHOICES,
                                 index=MOC_CHOICES.index("Duplex 2205"),
                                 key="he_de")
        he_clad  = st.selectbox("BF/TS Cladding", CLADDING_OPTIONS,
                                 key="he_clad")
        he_grade = st.selectbox("Tube Grade", ["SMLS", "ERW"],
                                 key="he_grade")
    if st.button("Compute Heat Exchanger", key="btn_he"):
        r = qc.heat_exchanger_cost(
            hta_m2=he_hta, tube_length_m=he_tlen,
            tube_od_mm=he_tod, tube_thk_mm=he_tthk,
            moc_shell=he_shell, moc_dishend=he_de,
            moc_tubesheet=he_ts, moc_tubes=he_tube,
            moc_bonnet=he_de, moc_partition=he_de,
            moc_body_flange=he_ts,
            moc_bf_cladding=he_clad, tube_grade=he_grade,
            rm_rates=S("rm_rates"), lab_rates=S("lab_rates"),
            equipment_label=he_label,
        )
        sub = ("STRIPPER REBOILER"  if "Reboiler"  in he_label else
               "STRIPPER CONDENSER" if "Stripper Condenser" in he_label else
               "HEAT EXCHANGER")
        section = ("Stripper" if "Stripper" in he_label or "Reboiler" in he_label
                   else "Evaporator" if any(x in he_label for x in
                                            ["MEE", "Calandria", "Pre-Heater"])
                   else "Common")
        show_calc_result(
            r, he_label, section=section, sub=sub, moc=he_shell,
            description=f"HTA {he_hta} m² · {he_tube} tubes",
            design_payload=dict(
                hta_m2=he_hta, tube_length_m=he_tlen,
                tube_od_mm=he_tod, tube_thk_mm=he_tthk,
            ),
        )


def _render_vls():
    c1, c2, c3 = st.columns(3)
    with c1:
        v_no  = st.number_input("VLS Number", 1, 7, 1, key="v_no")
        v_vol = st.number_input("Gross Volume (m³)", 0.1, 50.0, 2.0,
                                 step=0.1, key="v_vol")
    with c2:
        v_id  = st.number_input("Selected ID (mm)  [0=auto]", 0, 5000,
                                 1050, step=50, key="v_id")
        v_hd  = st.number_input("H/D ratio", 1.0, 4.0, 2.0,
                                 step=0.1, key="v_hd")
    with c3:
        v_moc = st.selectbox("MOC", MOC_CHOICES,
                              index=MOC_CHOICES.index("SS316L"), key="v_moc")
        v_thk = st.number_input("Shell Thk (mm) [0=auto]", 0, 30, 0,
                                 key="v_thk")
    if st.button("Compute VLS", key="btn_vls"):
        r = qc.vls_cost(
            gross_volume_m3=v_vol,
            selected_id_mm=v_id if v_id > 0 else None,
            h_over_d=v_hd, moc=v_moc,
            shell_thk_mm=v_thk if v_thk > 0 else None,
            rm_rates=S("rm_rates"), lab_rates=S("lab_rates"),
        )
        show_calc_result(
            r, f"VLS-{v_no}",
            section="Evaporator", sub="SEPARATORS", moc=v_moc,
            description=f"{r['inputs']['selected_id_mm']} mm ID",
            design_payload=dict(
                gross_volume_m3=v_vol, h_over_d=v_hd, selected_id_mm=v_id,
            ),
        )


def _render_tank():
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        t_name = st.text_input("Tank Name", "Feed Tank", key="t_name")
        t_cap  = st.number_input("Capacity (KL)", 0.05, 200.0, 2.5,
                                  step=0.5, key="t_cap")
    with c2:
        t_ld   = st.number_input("L/D ratio", 0.5, 5.0, 1.25,
                                  step=0.05, key="t_ld")
        t_moc  = st.selectbox("MOC", MOC_CHOICES,
                                 index=MOC_CHOICES.index("SS316L"),
                                 key="t_moc")
    with c3:
        t_st   = st.number_input("Shell Thk (mm) [0=auto]", 0, 30, 0,
                                  key="t_st")
        t_tt   = st.number_input("Top Thk (mm) [0=auto]", 0, 30, 0,
                                  key="t_tt")
    with c4:
        t_bt   = st.number_input("Bottom Thk (mm) [0=auto]", 0, 30, 0,
                                  key="t_bt")
        t_sec  = st.selectbox("Section", SECTIONS,
                                 index=SECTIONS.index("Common"),
                                 key="t_sec")
    if st.button("Compute Tank", key="btn_tank"):
        r = qc.tank_cost(
            capacity_kl=t_cap, L_over_D=t_ld, moc=t_moc,
            shell_thk_mm=t_st if t_st > 0 else None,
            top_dish_thk_mm=t_tt if t_tt > 0 else None,
            bottom_dish_thk_mm=t_bt if t_bt > 0 else None,
            rm_rates=S("rm_rates"), lab_rates=S("lab_rates"),
        )
        show_calc_result(
            r, t_name, section=t_sec, sub="TANK", moc=t_moc,
            description=f"{t_cap} KL",
            design_payload=dict(capacity_kl=t_cap, L_over_D=t_ld),
        )


def _render_atfd():
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        a_hta = st.number_input("HTA (m²)", 1.0, 100.0, 15.0,
                                 step=0.5, key="a_hta")
        a_dia = st.number_input("Shell Dia (mm)", 300, 2000, 600,
                                 step=50, key="a_dia")
    with c2:
        a_len = st.number_input("Shell Length (m)", 1.0, 6.0, 2.5,
                                 step=0.1, key="a_len")
        a_thk = st.number_input("Shell Thk (mm)", 4, 20, 8, key="a_thk")
    with c3:
        a_moc = st.selectbox("Body MOC", MOC_CHOICES,
                              index=MOC_CHOICES.index("Duplex 2205"),
                              key="a_moc")
        a_jacket = st.selectbox("Jacket MOC", MOC_CHOICES,
                                 index=MOC_CHOICES.index("SS304"),
                                 key="a_jacket")
    with c4:
        a_blades = st.number_input("Number of blades", 2, 12, 4, key="a_blades")
        a_bo  = st.number_input("Bought-Out Cost (₹) — gearbox/motor/seal",
                                 0, 10000000, 1500000, step=10000, key="a_bo")
    if st.button("Compute ATFD", key="btn_atfd"):
        r = qc.atfd_cost(
            hta_m2=a_hta, shell_dia_mm=a_dia,
            shell_length_m=a_len, moc=a_moc,
            moc_jacket=a_jacket, moc_rotor=a_moc,
            shell_thk_mm=a_thk, n_blades=a_blades,
            bo_items_cost=a_bo,
            rm_rates=S("rm_rates"), lab_rates=S("lab_rates"),
        )
        show_calc_result(
            r, "ATFD", section="Dryer", sub="ATFD-Body", moc=a_moc,
            description=f"HTA {a_hta} m²",
            design_payload=dict(
                hta_m2=a_hta, shell_dia_mm=a_dia, shell_length_m=a_len,
            ),
        )


# ─────────────────────────────────────────────────────────────────────────────
# LINES EDITOR
# ─────────────────────────────────────────────────────────────────────────────
def _render_lines_editor():
    st.markdown("### 📋 Equipment Lines")
    if not S("equipment_lines"):
        st.info("No equipment lines yet. Use the buttons above, or import "
                "from a process-design project on the Cover Page tab.")
        return

    df = pd.DataFrame(S("equipment_lines"))
    df["total_cost"] = df["qty"].fillna(0) * df["unit_cost"].fillna(0)

    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True,
        column_config={
            "section":        st.column_config.SelectboxColumn("Section", options=SECTIONS),
            "sub_section":    st.column_config.SelectboxColumn("Sub-Section", options=SUB_SECTIONS),
            "equipment":      st.column_config.TextColumn("Equipment", width="medium"),
            "description":    st.column_config.TextColumn("Description"),
            "moc":            st.column_config.SelectboxColumn("MOC", options=MOC_CHOICES),
            "qty":            st.column_config.NumberColumn("Qty", format="%d"),
            "unit_cost":      st.column_config.NumberColumn("Unit Cost (₹)", format="%.0f"),
            "total_cost":     st.column_config.NumberColumn("Total (₹)", format="%.0f", disabled=True),
            "category":       st.column_config.SelectboxColumn("Category", options=CATEGORIES),
            "item_type":      st.column_config.SelectboxColumn("Type", options=ITEM_TYPES),
            "calc_source":    st.column_config.TextColumn("Source", disabled=True, width="small"),
            "design_payload": st.column_config.TextColumn("Design", disabled=True, width="small"),
        },
        column_order=[
            "section", "sub_section", "equipment", "description", "moc",
            "qty", "unit_cost", "total_cost", "category", "item_type",
            "calc_source",
        ],
        key="eqp_editor",
    )

    # Persist edits — preserve design_payload from existing rows
    existing = {
        (l.get("equipment", ""), l.get("description", "")):
            l.get("design_payload", "")
        for l in S("equipment_lines")
    }
    new_lines = []
    for _, row in edited.iterrows():
        d = row.to_dict()
        d.pop("total_cost", None)
        for k in ("qty", "unit_cost"):
            try:
                d[k] = float(d.get(k) or 0)
            except (TypeError, ValueError):
                d[k] = 0
        if not d.get("design_payload"):
            d["design_payload"] = existing.get(
                (d.get("equipment", ""), d.get("description", "")), "",
            )
        new_lines.append(d)
    setS("equipment_lines", new_lines)

    # Roll-up summaries
    c1, c2, c3 = st.columns(3)
    op = total_equipment_cost() or 1
    for col, fld, title in [(c1, "category",  "By Category"),
                             (c2, "section",   "By Section"),
                             (c3, "item_type", "By Item Type")]:
        with col:
            st.markdown(f"**{title}**")
            d = cost_summary_by(fld)
            if any(v > 0 for v in d.values()):
                rows = [{"Key": k, "Cost (₹)": v, "%": v / op * 100}
                        for k, v in d.items() if v > 0]
                st.dataframe(
                    pd.DataFrame(rows).style.format(
                        {"Cost (₹)": "{:,.0f}", "%": "{:.1f}%"}),
                    hide_index=True, use_container_width=True,
                )
