"""Man-Hour tab — engineering / PM / commissioning days × rates."""
from __future__ import annotations
import streamlit as st
import pandas as pd

from bg_estimation_costing.utils.state import S, setS
from bg_estimation_costing.utils.totals import total_manhours


def render():
    st.subheader("Man-Hour Cost — Engineering, PM & Execution")

    df = pd.DataFrame(S("manhour_lines"))
    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True, key="mh_editor",
        column_config={
            "department": st.column_config.TextColumn("Department"),
            "hod":        st.column_config.NumberColumn("HOD (days)",     format="%d"),
            "mgr":        st.column_config.NumberColumn("Manager (days)", format="%d"),
            "eng":        st.column_config.NumberColumn("Engineer (days)",format="%d"),
        },
    )
    new = []
    for _, r in edited.iterrows():
        d = r.to_dict()
        for k in ("hod", "mgr", "eng"):
            try:
                d[k] = int(d.get(k) or 0)
            except (TypeError, ValueError):
                d[k] = 0
        new.append(d)
    setS("manhour_lines", new)

    breakdown, total_cost = total_manhours()
    if breakdown:
        st.dataframe(
            pd.DataFrame(breakdown)[["department", "hod", "mgr", "eng",
                                      "days", "cost"]]
              .style.format({"cost": "{:,.0f}"}),
            hide_index=True, use_container_width=True,
        )
        st.metric(
            "Total Man-hour Cost",
            f"₹{total_cost:,.0f}",
            delta=f"{sum(x['days'] for x in breakdown)} total days",
        )
