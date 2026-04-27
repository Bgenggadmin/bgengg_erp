"""Cover Page tab — links to a process-design project + costing-header fields."""
from __future__ import annotations
from datetime import date, datetime
import streamlit as st

from bg_estimation_costing import db
from bg_estimation_costing.utils.state import S, setS
from bg_estimation_costing.utils.persistence import import_design_equipment
from bg_estimation_costing.ui.constants import PLANT_TYPES


def render():
    st.subheader("Cover Page")

    # ── Linked Process-Design Project ──────────────────────────────────────
    st.markdown("#### 🔗 Linked Process-Design Project")
    projects = db.list_projects()
    if projects:
        proj_opts = ["— none —"] + [
            f"#{p['id']}  ·  {p.get('client_name','')}  ·  "
            f"{p.get('project_name','')}  ·  {p.get('capacity','')}"
            for p in projects
        ]
        pid_now = S("project_id")
        idx = 0
        if pid_now:
            for i, p in enumerate(projects, 1):
                if p["id"] == pid_now:
                    idx = i
                    break
        sel = st.selectbox(
            "Process Design Project", proj_opts, index=idx,
            help="Once linked, you can pull equipment list automatically.",
        )
        if sel != "— none —":
            pid = int(sel.split("·")[0].replace("#", "").strip())
            setS("project_id", pid)
            chosen = next(p for p in projects if p["id"] == pid)

            # Auto-fill cover-page fields if blank
            for src, dst in [("client_name",  "client_name"),
                             ("project_name", "project_name"),
                             ("project_no",   "project_no"),
                             ("capacity",     "capacity"),
                             ("location",     "location"),
                             ("plant_type",   "plant_type")]:
                if not S(dst) and chosen.get(src):
                    setS(dst, chosen[src])

            ic1, ic2 = st.columns(2)
            if ic1.button("⬇️ Import equipment from process design",
                          type="primary"):
                n = import_design_equipment(pid)
                if n:
                    st.success(f"Imported {n} lines from process design.")
                else:
                    st.warning("No equipment rows found for this project.")
                st.rerun()
            if ic2.button("🔄 Re-import (overwrites current lines)"):
                if st.session_state.get("_qps_confirm_reimport"):
                    n = import_design_equipment(pid)
                    st.success(f"Re-imported {n} lines.")
                    st.session_state.pop("_qps_confirm_reimport", None)
                    st.rerun()
                else:
                    st.session_state["_qps_confirm_reimport"] = True
                    st.warning("Click again to confirm — this will replace "
                               "all current equipment lines.")
        else:
            setS("project_id", None)
    else:
        if db.is_connected():
            st.caption("No process-design projects in DB. "
                       "You can still build a costing from scratch below.")
        else:
            st.caption("Database offline — projects unavailable. "
                       "Build a costing from scratch below.")

    st.divider()

    # ── Cover-page fields ──────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        setS("qps_no",       st.text_input("QPS No.", S("qps_no")))
        setS("revision",     st.text_input("Revision", S("revision")))
        setS("client_name",  st.text_input("Client Name", S("client_name"),
                                            placeholder="M/s. ABC Pharma Pvt Ltd"))
        setS("project_name", st.text_input("Project / Plant", S("project_name")))
        setS("project_no",   st.text_input("Project No.", S("project_no")))
        setS("capacity",     st.text_input("Capacity", S("capacity"),
                                            placeholder="150 KLD"))
    with c2:
        setS("location",   st.text_input("Plant Location", S("location")))
        pt = S("plant_type") if S("plant_type") in PLANT_TYPES else "MEE"
        setS("plant_type", st.selectbox("Plant Type", PLANT_TYPES,
                                          index=PLANT_TYPES.index(pt)))
        cd = S("costing_date")
        if isinstance(cd, str):
            try:
                cd = datetime.fromisoformat(cd).date()
            except Exception:
                cd = date.today()
        setS("costing_date", st.date_input("Costing Date", cd))
        setS("prepared_by",  st.text_input("Costing By", S("prepared_by")))
        setS("approved_by",  st.text_input("Costing Approved By", S("approved_by")))

    setS("scope_summary", st.text_area("Scope Summary",
                                        S("scope_summary"), height=80))

    st.divider()
    with st.expander("⚙️ Material rates — used by parametric calculators",
                     expanded=False):
        # Show source of rates
        rate_count = len(S("rm_rates", {}))
        st.caption(f"📊 Loaded {rate_count} material rates "
                   f"(from `est_rm_master` + hardcoded fallback). "
                   f"Edit below to override for this costing only — "
                   f"the master tables aren't modified.")

        rc1, rc2 = st.columns([1, 3])
        if rc1.button("🔄 Reload from masters", key="reload_rates",
                      help="Pull latest rates from est_rm_master and "
                           "est_oh_master, discarding any per-costing edits."):
            from bg_estimation_costing import db as _db
            _db.load_rm_master.clear()
            _db.load_oh_master.clear()
            from bg_estimation_costing.utils.state import (
                load_rm_rates_with_fallback, load_lab_rates_with_fallback,
            )
            setS("rm_rates",  load_rm_rates_with_fallback())
            setS("lab_rates", load_lab_rates_with_fallback())
            st.success("Reloaded rates from master tables.")
            st.rerun()

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Raw-Material Rates (₹/kg)** — `est_rm_master`")
            rm = S("rm_rates", {})
            for k in list(rm.keys()):
                rm[k] = st.number_input(k, value=float(rm[k]),
                                        step=10.0, key=f"rm_rate_{k}")
            setS("rm_rates", rm)
        with c2:
            st.markdown("**Labour Rates (₹/kg)** — `est_oh_master`")
            lr = S("lab_rates", {})
            for k in list(lr.keys()):
                lr[k] = st.number_input(k, value=float(lr[k]),
                                        step=5.0, key=f"lab_rate_{k}")
            setS("lab_rates", lr)
