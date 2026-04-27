"""Shared 'calc result + add to lines' widget used by every parametric tab."""
from __future__ import annotations
import json
from typing import Dict, Optional

import streamlit as st
import pandas as pd

from bg_estimation_costing.utils.state import S, setS


def show_calc_result(r: Dict, equipment_name: str, *, section: str,
                     sub: str, moc: str, description: str = "",
                     replace_idx: Optional[int] = None,
                     design_payload: Optional[Dict] = None):
    cost_field = "rounded" if "rounded" in r["costs"] else "final"
    st.success(f"✅ Computed cost: ₹{r['costs'][cost_field]:,.0f}")

    cc1, cc2 = st.columns([2, 1])
    with cc1:
        st.markdown("**Cost Breakdown**")
        bd = [{"Item": k.replace('_', ' ').title(), "Value (₹)": v}
              for k, v in r["costs"].items()
              if isinstance(v, (int, float)) and k != cost_field]
        if bd:
            st.dataframe(
                pd.DataFrame(bd).style.format({"Value (₹)": "{:,.0f}"}),
                hide_index=True, use_container_width=True,
            )
        if "rows" in r:
            st.markdown("**Component Details**")
            df = pd.DataFrame(r["rows"])
            st.dataframe(
                df.style.format({"wt": "{:,.1f}", "rate": "{:,.0f}",
                                 "rmc": "{:,.0f}", "lab_rate": "{:,.0f}",
                                 "lab": "{:,.0f}"}),
                hide_index=True, use_container_width=True,
            )
        if "weights" in r:
            st.markdown("**Weight Breakdown (kg)**")
            wd = [{"Component": k.replace('_', ' ').title(), "Weight (kg)": v}
                  for k, v in r["weights"].items()
                  if isinstance(v, (int, float))]
            st.dataframe(
                pd.DataFrame(wd).style.format({"Weight (kg)": "{:,.1f}"}),
                hide_index=True, use_container_width=True,
            )
    with cc2:
        st.markdown("**Add to Equipment Lines**")
        with st.form(f"add_form_{equipment_name}_{replace_idx}"):
            line_qty  = st.number_input(
                "Qty", 1, 50, 1,
                key=f"add_qty_{equipment_name}_{replace_idx}",
            )
            cust_desc = st.text_input(
                "Description override", description,
                key=f"add_desc_{equipment_name}_{replace_idx}",
            )
            label = "💾 Update line" if replace_idx is not None else "➕ Add as new line"
            if st.form_submit_button(label, type="primary"):
                line = {
                    "section": section, "sub_section": sub,
                    "equipment": equipment_name,
                    "description": cust_desc, "moc": moc,
                    "qty": line_qty, "unit_cost": r["costs"][cost_field],
                    "category": "B&G-MFG", "item_type": "MECH_EQP",
                    "calc_source": equipment_name,
                    "design_payload": json.dumps(
                        design_payload or r.get("inputs", {}), default=str,
                    ),
                }
                lines = S("equipment_lines", []) or []
                if replace_idx is not None and 0 <= replace_idx < len(lines):
                    lines[replace_idx] = line
                else:
                    lines.append(line)
                setS("equipment_lines", lines)
                st.success(
                    f"{'Updated' if replace_idx is not None else 'Added'}: "
                    f"{equipment_name} (₹{r['costs'][cost_field]:,.0f})"
                )
                st.rerun()
