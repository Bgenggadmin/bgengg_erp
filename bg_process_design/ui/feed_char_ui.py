"""Reusable feed characterization input widget for all unit UIs."""
import streamlit as st
from bg_process_design.utils.feed_characterization import (
    default_feed_characterization, validate_feed_characterization,
    calc_bpr_from_ts
)


def render_feed_char_input(prefix: str, defaults: dict = None,
                             title: str = "Feed Characterization",
                             expanded: bool = False) -> dict:
    """
    Render a standardized feed characterization input block.

    prefix: unique key prefix (e.g. 'stripper', 'mee', 'atfd')
    defaults: dict of default values (optional)
    title: expander title
    expanded: whether the expander starts open

    Returns: dict with all feed characterization values
    """
    if defaults is None:
        defaults = default_feed_characterization()

    with st.expander(f"🧫 {title}", expanded=expanded):
        st.caption("Full feed characterization — tracked through mass balance across all units")

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Solids**")
            ts = st.number_input(
                "TS (Total Solids) %",
                value=float(defaults.get("ts_pct", 2.2)),
                min_value=0.0, max_value=100.0, step=0.1,
                key=f"{prefix}_ts_pct"
            )
            tds = st.number_input(
                "TDS (Total Dissolved) %",
                value=float(defaults.get("tds_pct", 2.2)),
                min_value=0.0, max_value=100.0, step=0.1,
                key=f"{prefix}_tds_pct"
            )
            tss = st.number_input(
                "TSS (Total Suspended) %",
                value=float(defaults.get("tss_pct", 0.0)),
                min_value=0.0, max_value=100.0, step=0.1,
                key=f"{prefix}_tss_pct"
            )

        with c2:
            st.markdown("**Organic Load**")
            cod = st.number_input(
                "COD (mg/L)",
                value=float(defaults.get("cod_mgl", 8000.0)),
                min_value=0.0, max_value=500000.0, step=500.0,
                key=f"{prefix}_cod_mgl"
            )
            bod = st.number_input(
                "BOD (mg/L)",
                value=float(defaults.get("bod_mgl", 2500.0)),
                min_value=0.0, max_value=500000.0, step=100.0,
                key=f"{prefix}_bod_mgl"
            )
            ph = st.number_input(
                "pH",
                value=float(defaults.get("ph", 7.2)),
                min_value=0.0, max_value=14.0, step=0.1,
                key=f"{prefix}_ph"
            )

        with c3:
            st.markdown("**Ions / Salt Split**")
            cl = st.number_input(
                "Chlorides (mg/L)",
                value=float(defaults.get("chlorides_mgl", 3500.0)),
                min_value=0.0, max_value=200000.0, step=100.0,
                key=f"{prefix}_chlorides_mgl"
            )
            so4 = st.number_input(
                "Sulphates (mg/L)",
                value=float(defaults.get("sulphates_mgl", 1200.0)),
                min_value=0.0, max_value=200000.0, step=100.0,
                key=f"{prefix}_sulphates_mgl"
            )
            crys = st.number_input(
                "Crystalline salt %",
                value=float(defaults.get("crystalline_salt_pct", 90.0)),
                min_value=0.0, max_value=100.0, step=1.0,
                key=f"{prefix}_crystalline_salt_pct",
                help="% of TDS that is crystalline (NaCl, Na₂SO₄, etc.)"
            )
            non_crys = 100.0 - crys
            st.caption(f"Non-crystalline: **{non_crys:.1f} %** (auto)")

        feed_char = {
            "ts_pct": ts, "tds_pct": tds, "tss_pct": tss,
            "cod_mgl": cod, "bod_mgl": bod, "ph": ph,
            "chlorides_mgl": cl, "sulphates_mgl": so4,
            "crystalline_salt_pct": crys,
            "non_crystalline_salt_pct": non_crys,
        }

        # Validation warnings
        warnings = validate_feed_characterization(feed_char)
        if warnings:
            for w in warnings:
                st.warning(f"⚠️ {w}")

        # Show derived BPR hint if this will be used in MEE
        if prefix == "mee":
            estimated_bpr = calc_bpr_from_ts(ts / 100.0)
            st.caption(f"💡 At {ts:.1f}% TS, correlated BPR ≈ **{estimated_bpr:.2f} °C** "
                       f"(used in E-1 by default; later effects scale up)")

        return feed_char


def render_feed_char_display(feed_char: dict, label: str = "Outlet Feed"):
    """Render a compact display of feed characterization (for output showing)."""
    import pandas as pd
    from bg_process_design.utils.feed_characterization import feed_char_to_display_rows

    rows = feed_char_to_display_rows(feed_char, label)
    st.dataframe(pd.DataFrame(rows, columns=["Parameter", "Value"]),
                 use_container_width=True, hide_index=True)
