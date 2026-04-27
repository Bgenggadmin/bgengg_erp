"""Pipeline tab — line-by-line piping cost with auto kg/m + cost calc."""
from __future__ import annotations
import streamlit as st
import pandas as pd

from bg_estimation_costing.modules import qps_calculators as qc
from bg_estimation_costing.utils.state import S, setS
from bg_estimation_costing.utils.totals import total_pipeline_cost
from bg_estimation_costing.ui.constants import SECTIONS


def render():
    st.subheader("Pipeline Cost")
    st.caption("Per-line piping. Weight & cost auto-calculated from MOC + NB + length.")

    cb1, cb2 = st.columns(2)
    if cb1.button("➕ Add pipeline line", use_container_width=True, key="add_pipe"):
        lines = S("pipeline_lines", []) or []
        lines.append({
            "section": "Stripper", "line": "Process Line",
            "from_point": "", "to_point": "", "qty": 1, "nb": 50,
            "length_m": 1.0, "moc": "SS316L", "kg_per_m": 0.0,
            "total_wt": 0.0, "rm_cost": 0.0, "lab_cost": 0.0, "total": 0.0,
        })
        setS("pipeline_lines", lines)
        st.rerun()
    if cb2.button("🗑️ Clear all pipelines", use_container_width=True,
                  key="clear_pipe", type="secondary"):
        setS("pipeline_lines", [])
        st.rerun()

    if not S("pipeline_lines"):
        st.info("No pipeline lines yet.")
        return

    df = pd.DataFrame(S("pipeline_lines"))
    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True, key="pipe_editor",
        column_config={
            "section":    st.column_config.SelectboxColumn("Section", options=SECTIONS),
            "line":       st.column_config.TextColumn("Line", width="small"),
            "from_point": st.column_config.TextColumn("From"),
            "to_point":   st.column_config.TextColumn("To"),
            "qty":        st.column_config.NumberColumn("Qty", format="%d"),
            "nb":         st.column_config.SelectboxColumn(
                              "NB",
                              options=list(qc.PIPE_KG_PER_M_SCH40.keys())),
            "length_m":   st.column_config.NumberColumn("Length (m)", format="%.1f"),
            "moc":        st.column_config.SelectboxColumn(
                              "MOC", options=list(qc.PIPE_RM_RATES.keys())),
            "kg_per_m":   st.column_config.NumberColumn("kg/m", format="%.2f", disabled=True),
            "total_wt":   st.column_config.NumberColumn("Wt (kg)", format="%.1f", disabled=True),
            "rm_cost":    st.column_config.NumberColumn("RM (₹)", format="%.0f", disabled=True),
            "lab_cost":   st.column_config.NumberColumn("Lab (₹)", format="%.0f", disabled=True),
            "total":      st.column_config.NumberColumn("Total (₹)", format="%.0f", disabled=True),
        },
    )
    # Recalculate every line on each save
    new = []
    for _, r in edited.iterrows():
        d = r.to_dict()
        try:
            calc = qc.pipeline_line_cost(
                nb=int(d.get("nb") or 50),
                length_m=float(d.get("length_m") or 0),
                qty=int(d.get("qty") or 1),
                moc=d.get("moc", "SS316L"),
            )
            d.update(calc)
        except Exception:
            pass
        new.append(d)
    setS("pipeline_lines", new)

    st.metric("Total Pipeline Cost", f"₹{total_pipeline_cost():,.0f}")
