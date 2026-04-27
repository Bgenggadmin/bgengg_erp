"""Header bar with title, status indicator and key metrics."""
from __future__ import annotations
import streamlit as st

from bg_estimation_costing import db
from bg_estimation_costing.utils.state import S
from bg_estimation_costing.utils.totals import price_summary


BG_NAME     = "B&G Engineering Industries"
QPS_VERSION = "Ver 2025(1.1)"


def render():
    st.title("🧾 MEE — Estimation & Costing")
    sub = (f"{BG_NAME} · MEE Vertical · {QPS_VERSION}"
           + (" · 🟢 DB connected" if db.is_connected()
              else " · 🟡 DB offline (session-only)"))
    st.caption(sub)

    ps = price_summary()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Operations Cost",   f"₹{ps['op_cost']/1e5:,.1f} L")
    m2.metric("Soft Cost",         f"₹{ps['soft_cost']/1e5:,.1f} L")
    m3.metric("Supply Cost (B&G)", f"₹{ps['supply_cost']/1e5:,.1f} L")
    m4.metric("Quote Price",       f"₹{ps['quote_price']/1e5:,.1f} L",
              delta=f"+{S('bg_margin_pct'):.0f}% margin")
    m5.metric("Equipment Lines",   len(S("equipment_lines", []) or []))

    cid_now = S("costing_id")
    if cid_now:
        st.info(f"✏️ **Editing costing #{cid_now}** | {S('qps_no')} | "
                f"{S('client_name')} | Status: **{S('status')}**")
    elif S("qps_no"):
        st.warning(f"📝 New costing in progress: **{S('qps_no')}** — not yet saved.")

    st.markdown("---")
