"""Price Summary tab — % editors, cost build-up, pricing tiers, cash flow."""
from __future__ import annotations
import streamlit as st
import pandas as pd

from bg_estimation_costing.utils.state import S, setS
from bg_estimation_costing.utils.totals import price_summary


def render():
    st.subheader("Price Summary & Cash Flow")

    _render_pct_editors()
    st.divider()
    _render_pricing_tiers()
    st.divider()
    _render_summary_tables()
    st.divider()
    _render_cashflow()


def _render_pct_editors():
    st.markdown("##### Soft-Cost Percentages (% of Operations Cost)")
    pc1, pc2, pc3, pc4 = st.columns(4)
    with pc1:
        setS("inspection_pct",
             st.number_input("Inspection / QC / QA (%)", 0.0, 10.0,
                              float(S("inspection_pct")), step=0.1))
        setS("packing_pct",
             st.number_input("Packing & Forwarding (%)", 0.0, 10.0,
                              float(S("packing_pct")), step=0.1))
    with pc2:
        setS("risk_pct",
             st.number_input("Risk Insurance (%)", 0.0, 10.0,
                              float(S("risk_pct")), step=0.1))
        setS("overhead_pct",
             st.number_input("Overheads (%)", 0.0, 25.0,
                              float(S("overhead_pct")), step=0.5))
    with pc3:
        setS("material_handling_pct",
             st.number_input("Material Handling (%)", 0.0, 10.0,
                              float(S("material_handling_pct")), step=0.1))
        setS("contingency_pct",
             st.number_input("Contingency (%)", 0.0, 25.0,
                              float(S("contingency_pct")), step=0.5))
    with pc4:
        setS("engg_travel_amt",
             st.number_input("Engg + Travel (₹ flat)", 0, 10000000,
                              int(S("engg_travel_amt")), step=10000))
        setS("transport_amt",
             st.number_input("Transportation (₹ flat)", 0, 5000000,
                              int(S("transport_amt")), step=5000))


def _render_pricing_tiers():
    st.markdown("##### Pricing Tiers (margin % on Supply Cost)")
    pp1, pp2, pp3, pp4 = st.columns(4)
    with pp1:
        setS("bg_margin_pct",
             st.number_input("Quote Price Margin (%)", 0.0, 80.0,
                              float(S("bg_margin_pct")), step=1.0))
    with pp2:
        setS("best_price_pct",
             st.number_input("Best Price (%)", 0.0, 80.0,
                              float(S("best_price_pct")), step=1.0))
    with pp3:
        setS("target_price_pct",
             st.number_input("Target Price (%)", 0.0, 80.0,
                              float(S("target_price_pct")), step=1.0))
    with pp4:
        setS("no_regret_price_pct",
             st.number_input("No-Regret Price (%)", 0.0, 80.0,
                              float(S("no_regret_price_pct")), step=1.0))


def _render_summary_tables():
    ps = price_summary()

    s1, s2 = st.columns(2)
    with s1:
        st.markdown("### 📊 Cost Build-Up")
        rows = [
            ("Equipment Cost",           ps["eqp"]),
            ("EIA Cost",                 ps["eia"]),
            ("Pipeline Cost",            ps["pipe"]),
            ("Operations Cost",          ps["op_cost"]),
            ("Inspection / QC / QA",     ps["inspection"]),
            ("Packing & Forwarding",     ps["packing"]),
            ("Risk Insurance",           ps["risk"]),
            ("Overheads",                ps["overhead"]),
            ("Engg + Travel",            ps["engg_trav"]),
            ("Transportation",           ps["transport"]),
            ("Margin on Bought-Out",     ps["bo_margin"]),
            ("Material Handling",        ps["mat_handling"]),
            ("Soft Cost",                ps["soft_cost"]),
            ("Contingency",              ps["contingency"]),
            ("Total Supply Cost (B&G)",  ps["supply_cost"]),
        ]
        df_sum = pd.DataFrame(rows, columns=["Line", "Amount (₹)"])
        df_sum["Lakh"] = df_sum["Amount (₹)"] / 1e5
        st.dataframe(
            df_sum.style.format({"Amount (₹)": "{:,.0f}", "Lakh": "{:,.1f}"}),
            hide_index=True, use_container_width=True,
        )
    with s2:
        st.markdown("### 💰 Pricing Tiers")
        for name, amt, pct in [
            ("Quote Price",      ps["quote_price"],     S("bg_margin_pct")),
            ("Best Price",       ps["best_price"],      S("best_price_pct")),
            ("Target Price",     ps["target_price"],    S("target_price_pct")),
            ("No-Regret Price",  ps["no_regret_price"], S("no_regret_price_pct")),
        ]:
            icon = "🟢" if name == "Quote Price" else "💡"
            st.metric(f"{icon} {name} ({pct:.0f}%)",
                      f"₹{amt:,.0f}", delta=f"₹{amt/1e5:,.1f} L")
        st.markdown("##### Cost Mix by Category")
        cat = ps["category"]
        if any(v > 0 for v in cat.values()):
            mix = pd.DataFrame([
                {"Category": k,
                 "%": v / ps['op_cost'] * 100 if ps['op_cost'] else 0}
                for k, v in cat.items() if v > 0
            ])
            st.bar_chart(mix.set_index("Category")["%"])


def _render_cashflow():
    st.markdown("### 💸 Cash-Flow Plan")
    ps = price_summary()
    cf_total = ps["quote_price"]
    cf = S("cashflow_pattern", {})
    if not cf:
        return
    if abs(sum(cf.values()) - 1.0) > 0.001:
        st.warning(f"⚠️ Cash-flow pattern sums to "
                   f"{sum(cf.values())*100:.1f}% — should be 100%")
    cf_rows = [{"Stage": k, "%": v * 100, "Amount (₹)": cf_total * v,
                "Lakh": cf_total * v / 1e5} for k, v in cf.items()]
    st.dataframe(
        pd.DataFrame(cf_rows).style.format(
            {"%": "{:.0f}%", "Amount (₹)": "{:,.0f}", "Lakh": "{:,.1f}"}),
        hide_index=True, use_container_width=True,
    )
