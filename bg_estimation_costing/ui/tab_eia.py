"""EIA tab — line-by-line instrumentation cost.

Instruments come from the shared `est_rm_master` table (rows where
category='BO'), so PLCs, transmitters, control valves, panels etc.
are pre-priced. The user picks an item from the master and it auto-fills
the description, MOC/spec, and unit cost.
"""
from __future__ import annotations
import streamlit as st
import pandas as pd

from bg_estimation_costing import db
from bg_estimation_costing.utils.state import S, setS
from bg_estimation_costing.utils.totals import total_eia_cost
from bg_estimation_costing.utils.templates import eia_skeleton
from bg_estimation_costing.ui.constants import SECTIONS


def render():
    st.subheader("EIA — Electrical, Instrumentation & Automation")

    # ── Top action row ────────────────────────────────────────────────────
    cb1, cb2, cb3, cb4 = st.columns(4)
    if cb1.button("➕ Add blank line", use_container_width=True, key="add_eia"):
        lines = S("eia_lines", []) or []
        lines.append({
            "section": "Stripper", "equipment": "", "instrument": "",
            "description": "", "moc": "FLP", "qty": 1, "unit_cost": 0.0,
            "ref_code": "",
        })
        setS("eia_lines", lines)
        st.rerun()
    if cb2.button("📋 Standard EIA template",
                  use_container_width=True, key="load_eia"):
        setS("eia_lines", eia_skeleton())
        st.rerun()
    if cb3.button("🔄 Refresh master",
                  use_container_width=True, key="refresh_bo"):
        db.load_rm_master.clear()
        st.success("Pulled latest from est_rm_master.")
        st.rerun()
    if cb4.button("🗑️ Clear all", use_container_width=True,
                  key="clear_eia", type="secondary"):
        setS("eia_lines", [])
        st.rerun()

    # ── BO-master picker (instruments / panels / valves) ──────────────────
    _render_bo_picker()

    st.divider()

    # ── Lines editor ──────────────────────────────────────────────────────
    if not S("eia_lines"):
        st.info("No EIA lines yet. Add from the master picker above, "
                "load the standard template, or add a blank line.")
        return

    df = pd.DataFrame(S("eia_lines"))
    df["total"] = df["qty"].fillna(0) * df["unit_cost"].fillna(0)
    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True, key="eia_editor",
        column_config={
            "ref_code":    st.column_config.TextColumn("Ref Code", width="small"),
            "section":     st.column_config.SelectboxColumn("Section", options=SECTIONS),
            "equipment":   st.column_config.TextColumn("Equipment"),
            "instrument":  st.column_config.TextColumn("Instrument"),
            "description": st.column_config.TextColumn("Description"),
            "moc":         st.column_config.SelectboxColumn(
                                "Spec",
                                options=["FLP", "Non-FLP", "NA",
                                         "SS316L", "SS304"]),
            "qty":         st.column_config.NumberColumn("Qty", format="%d"),
            "unit_cost":   st.column_config.NumberColumn("Unit Cost (₹)",
                                                          format="%.0f"),
            "total":       st.column_config.NumberColumn("Total (₹)",
                                                          format="%.0f", disabled=True),
        },
        column_order=["ref_code", "section", "equipment", "instrument",
                      "description", "moc", "qty", "unit_cost", "total"],
    )
    new = []
    for _, r in edited.iterrows():
        d = r.to_dict()
        d.pop("total", None)
        for k in ("qty", "unit_cost"):
            try:
                d[k] = float(d.get(k) or 0)
            except (TypeError, ValueError):
                d[k] = 0
        new.append(d)
    setS("eia_lines", new)

    st.metric("Total EIA Cost", f"₹{total_eia_cost():,.0f}")


# ─────────────────────────────────────────────────────────────────────────────
# BO-MASTER PICKER — pulls priced instruments from est_rm_master
# ─────────────────────────────────────────────────────────────────────────────
def _render_bo_picker():
    bo = db.bo_items()
    if not bo:
        st.caption("ℹ️ No bought-out items found in `est_rm_master` "
                   "(category='BO'). Add instruments / pumps / valves "
                   "to the master to enable quick-pick here.")
        return

    with st.expander(f"🔍 Pick from BO Master ({len(bo)} priced items)",
                     expanded=False):
        # Filter row
        f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
        search   = f1.text_input("Search description / ref code / vendor",
                                 key="eia_bo_search",
                                 placeholder="e.g. transmitter, PLC, valve").strip().lower()
        rm_types = sorted({r.get("rm_type") or "—"
                            for r in bo if r.get("rm_type")})
        type_sel = f2.selectbox("Type", ["All"] + rm_types, key="eia_bo_type")
        subtypes = sorted({r.get("sub_type") or "—"
                           for r in bo if r.get("sub_type")})
        sub_sel  = f3.selectbox("Sub-type", ["All"] + subtypes,
                                key="eia_bo_subtype")
        section  = f4.selectbox("Default Section to assign",
                                SECTIONS, index=SECTIONS.index("Common"),
                                key="eia_bo_section")

        # Apply filters
        items = bo
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
            st.caption("No items match your filter.")
            return

        st.caption(f"Showing {min(len(items), 50)} of {len(items)} item(s). "
                   f"Pick from the dropdown to add to EIA lines.")

        preview = pd.DataFrame([
            {"Ref Code":    r.get("ref_code", ""),
             "Type":        r.get("rm_type", ""),
             "Sub-type":    r.get("sub_type", ""),
             "Description": r.get("description", ""),
             "Spec":        r.get("spec", ""),
             "Size":        r.get("size", ""),
             "Vendor":      r.get("vendor", ""),
             "UOM":         r.get("uom", ""),
             "Rate (₹)":    r.get("rate", 0)}
            for r in items[:50]
        ])
        st.dataframe(
            preview.style.format({"Rate (₹)": "{:,.0f}"}),
            hide_index=True, use_container_width=True,
        )

        # Multi-select to pick which to add
        opts = [
            f"{r.get('ref_code','')}  |  {r.get('description','')}  "
            f"|  ₹{r.get('rate', 0):,.0f}"
            for r in items[:50]
        ]
        picked = st.multiselect(
            "Select items to add",
            opts, key="eia_bo_picked",
            help="Each selected item is added as a new EIA line "
                 "with qty=1 and unit_cost=master rate.",
        )

        c1, _ = st.columns([1, 3])
        if c1.button(f"➕ Add {len(picked)} item(s)",
                     type="primary",
                     disabled=(len(picked) == 0),
                     key="eia_bo_add"):
            ref_to_item = {
                f"{r.get('ref_code','')}  |  {r.get('description','')}  "
                f"|  ₹{r.get('rate', 0):,.0f}": r
                for r in items[:50]
            }
            lines = S("eia_lines", []) or []
            added = 0
            for label in picked:
                r = ref_to_item.get(label)
                if not r:
                    continue
                spec = r.get("spec", "")
                moc_val = (spec if spec in ("FLP", "Non-FLP", "NA",
                                            "SS316L", "SS304") else "FLP")
                lines.append({
                    "ref_code":    r.get("ref_code", ""),
                    "section":     section,
                    "equipment":   r.get("rm_type", "") or "",
                    "instrument":  r.get("description", "") or "",
                    "description": (f"{spec} {r.get('size','')}").strip(),
                    "moc":         moc_val,
                    "qty":         1,
                    "unit_cost":   float(r.get("rate", 0) or 0),
                })
                added += 1
            setS("eia_lines", lines)
            if added:
                st.success(f"✅ Added {added} item(s) to EIA lines.")
                st.rerun()
