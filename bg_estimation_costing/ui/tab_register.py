"""Register tab — list saved costings, open one, or start a new blank costing."""
from __future__ import annotations
import streamlit as st
import pandas as pd

from bg_estimation_costing import db
from bg_estimation_costing.utils.state import reset_state
from bg_estimation_costing.utils.persistence import load_costing


def render():
    st.subheader("Costing Register")

    a, b, _ = st.columns(3)
    if a.button("➕ New blank costing", use_container_width=True):
        reset_state()
        st.rerun()
    if b.button("🔄 Refresh from DB", use_container_width=True):
        db.refresh_all_caches()
        st.rerun()

    saved = db.list_costings()
    if not saved:
        st.info("No costings saved yet. Use **➕ New blank costing** "
                "or link a process-design project from the **Cover Page** tab.")
        return

    df = pd.DataFrame(saved)
    display_cols = [c for c in
                    ("qps_no", "client_name", "project_name", "capacity",
                     "plant_type", "status", "supply_cost", "quote_price",
                     "prepared_by", "updated_at")
                    if c in df.columns]
    show = df[display_cols].copy()
    for c_ in ("supply_cost", "quote_price"):
        if c_ in show.columns:
            show[c_] = show[c_].fillna(0).map(lambda v: f"₹{v/1e5:,.1f} L")
    if "updated_at" in show.columns:
        show["updated_at"] = show["updated_at"].astype(str).str[:16]
    st.dataframe(show, use_container_width=True, hide_index=True)

    st.markdown("##### Open a saved costing")
    opts = ["— select —"] + [f"#{r['id']}  ·  {r.get('qps_no','')}  ·  "
                              f"{r.get('client_name','')}" for r in saved]
    choice = st.selectbox("Costing", opts, label_visibility="collapsed")
    if choice != "— select —":
        cid = int(choice.split("·")[0].replace("#", "").strip())
        if st.button(f"📂 Load costing #{cid}", type="primary"):
            if load_costing(cid):
                st.success(f"Loaded costing #{cid}")
                st.rerun()
