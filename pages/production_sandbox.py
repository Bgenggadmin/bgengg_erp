"""
B&G Production Scheduler ERP
WBS-based: Main Task → Sub Task, CPM critical path,
manpower load analysis, weekly work plan slips,
rescheduling with revision log, Gantt view, and alerts.
"""

import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import pytz
import json

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
IST     = pytz.timezone("Asia/Kolkata")
NOW_IST = lambda: datetime.now(IST).isoformat()
TODAY   = date.today()

st.set_page_config(page_title="B&G Production Scheduler", layout="wide", page_icon="🏗️")
conn = st.connection("supabase", type=SupabaseConnection)

STATUSES     = ["Pending", "Active", "Completed", "Delayed", "Blocked", "On Hold"]
WORKER_TYPES = ["Permanent", "Temporary", "Outsource", "Contractor"]
TRADES       = ["Welder", "Fitter", "Painter", "Fabricator", "Electrician",
                "Piping", "Structural", "QC Inspector", "Helper", "Supervisor", "Other"]
UNITS        = ["Nos", "Mtrs", "Sq.Ft", "Kgs", "Joints", "Sets", "Hrs"]
STATUS_ICON  = {"Pending": "🔵", "Active": "🟡", "Completed": "🟢",
                "Delayed": "🔴", "Blocked": "⛔", "On Hold": "⚪"}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def safe_date(val) -> date | None:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None

def fmt(d, f="%d-%b-%Y"):
    return d.strftime(f) if d else "---"

def week_monday(d: date = None) -> date:
    d = d or TODAY
    return d - timedelta(days=d.weekday())

def to_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

def db_insert(table, data):
    res = conn.table(table).insert(data).execute()
    st.cache_data.clear()
    return res.data

def db_update(table, data, col, val):
    conn.table(table).update(data).eq(col, val).execute()
    st.cache_data.clear()

def db_delete(table, col, val):
    conn.table(table).delete().eq(col, val).execute()
    st.cache_data.clear()


# ─────────────────────────────────────────────
# DATA LOADERS
# ─────────────────────────────────────────────
@st.cache_data(ttl=3)
def load_data():
    try:
        proj  = conn.table("anchor_projects").select(
                    "job_no,status,po_no,po_date,po_delivery_date,revised_delivery_date"
                ).eq("status", "Won").execute()
        mt    = conn.table("main_tasks").select("*").order("task_order").execute()
        st_   = conn.table("sub_tasks").select("*").order("sub_order").execute()
        asgn  = conn.table("task_assignments").select("*").execute()
        rev   = conn.table("schedule_revisions").select("*").order("created_at", desc=True).execute()
        pool  = conn.table("manpower_pool").select("*").order("worker_name").execute()
        logs  = conn.table("daily_logs").select("*").order("log_date", desc=True).execute()
        slips = conn.table("weekly_slips").select("*").order("created_at", desc=True).execute()
        return (pd.DataFrame(proj.data or []), pd.DataFrame(mt.data or []),
                pd.DataFrame(st_.data or []),  pd.DataFrame(asgn.data or []),
                pd.DataFrame(rev.data or []),   pd.DataFrame(pool.data or []),
                pd.DataFrame(logs.data or []),  pd.DataFrame(slips.data or []))
    except Exception as e:
        st.error(f"Load error: {e}")
        return tuple(pd.DataFrame() for _ in range(8))

(df_proj, df_main, df_sub, df_asgn,
 df_rev, df_pool, df_logs, df_slips) = load_data()

all_jobs    = sorted(df_proj["job_no"].astype(str).unique().tolist()) if not df_proj.empty else []
all_workers = sorted(df_pool["worker_name"].tolist()) if not df_pool.empty else []


# ─────────────────────────────────────────────
# CRITICAL PATH ENGINE
# ─────────────────────────────────────────────
def compute_cpm(sub_df: pd.DataFrame) -> pd.DataFrame:
    if sub_df.empty:
        return sub_df
    df = sub_df.copy().reset_index(drop=True)
    df["duration_days"] = pd.to_numeric(df["duration_days"], errors="coerce").fillna(1).astype(int)

    def parse_deps(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return []
        if isinstance(val, list):
            return [int(x) for x in val if x]
        try:
            return [int(x) for x in json.loads(str(val))]
        except Exception:
            return []

    df["deps"] = df.get("depends_on", pd.Series([None] * len(df))).apply(parse_deps)
    id_idx = {int(row["id"]): i for i, row in df.iterrows()}
    n = len(df)
    ES, EF = [0] * n, [0] * n

    for i, row in df.iterrows():
        preds = [id_idx[d] for d in row["deps"] if d in id_idx]
        ES[i] = max((EF[p] for p in preds), default=0)
        EF[i] = ES[i] + int(row["duration_days"])

    proj_end = max(EF) if EF else 0
    LS, LF = [proj_end] * n, [proj_end] * n

    for i in reversed(range(n)):
        succs = [j for j, row in df.iterrows()
                 if i in [id_idx.get(d) for d in row["deps"] if d in id_idx]]
        if succs:
            LF[i] = min(LS[s] for s in succs)
        LS[i] = LF[i] - int(df.loc[i, "duration_days"])

    df["ES"] = ES; df["EF"] = EF; df["LS"] = LS; df["LF"] = LF
    df["float_days"]  = [LS[i] - ES[i] for i in range(n)]
    df["is_critical"] = df["float_days"] == 0
    return df


# ─────────────────────────────────────────────
# MANPOWER LOAD
# ─────────────────────────────────────────────
def manpower_load(asgn_df: pd.DataFrame, pool_df: pd.DataFrame, week: date) -> pd.DataFrame:
    if asgn_df.empty or pool_df.empty:
        return pd.DataFrame()
    wa = asgn_df.copy()
    wa["week_start_date"] = pd.to_datetime(wa["week_start_date"]).dt.date
    week_asgn = wa[wa["week_start_date"] == week]
    if week_asgn.empty:
        return pd.DataFrame()
    worker_hrs = week_asgn.groupby("worker_name")["allocated_hrs_day"].sum().reset_index()
    worker_hrs.columns = ["worker_name", "allocated_hrs"]
    merged = worker_hrs.merge(pool_df[["worker_name", "daily_cap_hrs"]], on="worker_name", how="left")
    merged["daily_cap_hrs"] = merged["daily_cap_hrs"].fillna(8)
    merged["load_pct"] = (merged["allocated_hrs"] / merged["daily_cap_hrs"] * 100).round(1)
    merged["status"] = merged["load_pct"].apply(
        lambda x: "🔴 Overloaded" if x > 100 else ("⚪ Underutilised" if x < 60 else "🟢 Optimal"))
    return merged


# ─────────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────────
def get_alerts(sub_df: pd.DataFrame) -> list[dict]:
    alerts = []
    if sub_df.empty:
        return alerts
    for _, row in sub_df.iterrows():
        p_end  = safe_date(row.get("planned_end"))
        status = row.get("status", "Pending")
        if status == "Active" and p_end and p_end < TODAY:
            alerts.append({"type": "🔴 Overdue", "job": row.get("job_no"), "task": row.get("name"),
                            "msg": f"Overdue by {(TODAY-p_end).days}d. Was due {fmt(p_end,'%d-%b')}."})
        if status == "Pending" and p_end and 0 <= (p_end - TODAY).days <= 3:
            alerts.append({"type": "🟡 Due Soon", "job": row.get("job_no"), "task": row.get("name"),
                            "msg": f"Due in {(p_end-TODAY).days}d."})
        if row.get("is_critical") and status != "Completed" and p_end and p_end < TODAY + timedelta(days=5):
            alerts.append({"type": "⛔ Critical", "job": row.get("job_no"), "task": row.get("name"),
                            "msg": f"On critical path. Float=0. Ends {fmt(p_end,'%d-%b')}."})
    return alerts


# ─────────────────────────────────────────────
# NAVIGATION TABS
# ─────────────────────────────────────────────
(tab_schedule, tab_gantt, tab_manpower,
 tab_slips, tab_logs, tab_analytics, tab_master) = st.tabs([
    "🏗️ Schedule", "📅 Gantt", "👥 Manpower",
    "📋 Weekly Slips", "📝 Daily Logs", "📊 Analytics", "⚙️ Master",
])


# ══════════════════════════════════════════════
# TAB 1 — SCHEDULE (WBS Tree)
# ══════════════════════════════════════════════
with tab_schedule:
    st.subheader("🏗️ Work Breakdown Schedule")

    # Global alerts banner
    alerts_all = get_alerts(df_sub)
    if alerts_all:
        with st.expander(f"⚠️ {len(alerts_all)} Alert(s) across all jobs", expanded=True):
            for a in alerts_all[:15]:
                st.markdown(f"**{a['type']}** · `{a['job']}` · {a['task']} — {a['msg']}")

    job = st.selectbox("Select Job", ["-- Select --"] + all_jobs, key="sch_job")
    if job == "-- Select --":
        st.info("Select a job to view and manage its schedule.")
        st.stop()

    # Project header strip
    pr = df_proj[df_proj["job_no"] == job]
    if not pr.empty:
        p = pr.iloc[0]
        po_disp = safe_date(p.get("po_delivery_date"))
        rev_dt  = safe_date(p.get("revised_delivery_date"))
        target  = rev_dt or po_disp
        days    = (target - TODAY).days if target else None
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("PO No",          p.get("po_no") or "---")
        c2.metric("PO Dispatch",    fmt(po_disp))
        c3.metric("Revised Date",   fmt(rev_dt))
        if days is not None:
            c4.metric("Days Left", f"{days}d",
                      delta=days, delta_color="normal" if days > 7 else "inverse")

    st.divider()

    # ── Add Main Task ──
    with st.expander("➕ Add Main Task", expanded=False):
        with st.form("add_main_task", clear_on_submit=True):
            c1, c2, c3 = st.columns([3, 1, 2])
            mt_name  = c1.text_input("Name")
            mt_order = c2.number_input("Order", min_value=1, value=1)
            mt_dates = c3.date_input("Planned Window", [TODAY, TODAY + timedelta(days=10)])
            mt_desc  = st.text_input("Description (optional)")
            if st.form_submit_button("Add Main Task") and mt_name:
                db_insert("main_tasks", {
                    "job_no": job, "name": mt_name, "description": mt_desc,
                    "task_order": mt_order,
                    "planned_start": mt_dates[0].isoformat() if len(mt_dates) > 0 else None,
                    "planned_end":   mt_dates[1].isoformat() if len(mt_dates) > 1 else None,
                    "status": "Pending", "created_at": NOW_IST(),
                })
                st.success("Main task added."); st.rerun()

    # ── WBS Tree ──
    job_main = df_main[df_main["job_no"] == job].sort_values("task_order") \
               if not df_main.empty else pd.DataFrame()
    job_sub  = df_sub[df_sub["job_no"] == job].sort_values("sub_order") \
               if not df_sub.empty else pd.DataFrame()

    if not job_sub.empty:
        job_sub = compute_cpm(job_sub)

    if job_main.empty:
        st.info("No main tasks yet.")
    else:
        for _, mt in job_main.iterrows():
            mt_id  = int(mt["id"])
            subs   = job_sub[job_sub["main_task_id"] == mt_id] \
                     if not job_sub.empty else pd.DataFrame()
            mt_icon = STATUS_ICON.get(mt.get("status", "Pending"), "🔵")

            # Count completed subs
            done    = len(subs[subs["status"] == "Completed"]) if not subs.empty else 0
            prog    = f"{done}/{len(subs)}" if not subs.empty else "0/0"

            with st.expander(
                f"{mt_icon} **{mt['name']}**  ·  "
                f"{fmt(safe_date(mt.get('planned_start')),'%d-%b')} → "
                f"{fmt(safe_date(mt.get('planned_end')),'%d-%b')}  "
                f"· {prog} sub-tasks done",
                expanded=True,
            ):
                # Main task status controls
                mc1, mc2, mc3, mc4 = st.columns([4, 2, 1, 1])
                mc1.caption(mt.get("description", ""))
                new_mt_status = mc2.selectbox(
                    "Status", STATUSES,
                    index=STATUSES.index(mt.get("status", "Pending"))
                          if mt.get("status") in STATUSES else 0,
                    key=f"mts_{mt_id}", label_visibility="collapsed")
                if mc3.button("✓", key=f"mtsv_{mt_id}"):
                    db_update("main_tasks", {"status": new_mt_status}, "id", mt_id)
                    st.rerun()
                if mc4.button("🗑️", key=f"mtdl_{mt_id}",
                               help="Delete main task and all its sub tasks"):
                    db_delete("main_tasks", "id", mt_id); st.rerun()

                st.markdown("---")

                # ── Add Sub Task form ──
                with st.form(f"add_sub_{mt_id}", clear_on_submit=True):
                    st.caption("➕ New Sub Task")
                    f1, f2, f3 = st.columns([3, 1, 1])
                    sn  = f1.text_input("Sub Task Name", key=f"sn_{mt_id}")
                    dur = f2.number_input("Duration (days)", min_value=1, value=3, key=f"dur_{mt_id}")
                    mp  = f3.number_input("Workers/day", min_value=1, value=2, key=f"mp_{mt_id}")

                    f4, f5, f6 = st.columns([2, 1, 2])
                    ps  = f4.date_input("Planned Start", value=TODAY, key=f"ps_{mt_id}")
                    ord_= f5.number_input("Order", min_value=1, value=len(subs)+1, key=f"ord_{mt_id}")
                    mh  = f6.number_input("Man-hrs/person/day", min_value=1.0, value=8.0,
                                          step=0.5, key=f"mh_{mt_id}")

                    # Dependency selector (other sub tasks in same main task)
                    dep_opts = {int(r["id"]): r["name"] for _, r in subs.iterrows()} \
                               if not subs.empty else {}
                    deps = st.multiselect(
                        "Depends on", options=list(dep_opts.keys()),
                        format_func=lambda x: dep_opts.get(x, str(x)),
                        key=f"deps_{mt_id}")

                    f7, f8 = st.columns(2)
                    outsrc = f7.checkbox("Outsource this task", key=f"out_{mt_id}")
                    vendor = f8.text_input("Vendor (if outsource)", key=f"vend_{mt_id}")
                    notes  = st.text_input("Notes / Specs", key=f"notes_{mt_id}")

                    if st.form_submit_button("Add Sub Task") and sn:
                        pe = ps + timedelta(days=dur - 1)
                        db_insert("sub_tasks", {
                            "main_task_id": mt_id, "job_no": job,
                            "name": sn, "sub_order": ord_,
                            "duration_days": dur,
                            "planned_start": ps.isoformat(),
                            "planned_end": pe.isoformat(),
                            "manpower_required": mp,
                            "man_hours_per_day": float(mh),
                            "depends_on": deps if deps else None,
                            "outsource_flag": outsrc,
                            "outsource_vendor": vendor or None,
                            "notes": notes or None,
                            "status": "Pending", "created_at": NOW_IST(),
                        })
                        st.success("Sub task added."); st.rerun()

                # ── Sub Task Cards ──
                if subs.empty:
                    st.caption("No sub tasks yet.")
                else:
                    for _, sub in subs.sort_values("sub_order").iterrows():
                        sub_id   = int(sub["id"])
                        is_crit  = bool(sub.get("is_critical", False))
                        float_d  = int(sub.get("float_days", 0)) \
                                   if not pd.isna(sub.get("float_days", 0)) else 0
                        p_start  = safe_date(sub.get("planned_start"))
                        p_end    = safe_date(sub.get("planned_end"))
                        status   = sub.get("status", "Pending")
                        outsrc   = sub.get("outsource_flag", False)

                        # Compute total allotted man-hours for this task
                        task_asgn = df_asgn[df_asgn["sub_task_id"] == sub_id] \
                                    if not df_asgn.empty else pd.DataFrame()
                        total_allotted_mh = (task_asgn["allocated_hrs_day"].sum()
                                             if not task_asgn.empty else 0)
                        req_mh = (int(sub.get("manpower_required", 1))
                                  * float(sub.get("man_hours_per_day", 8))
                                  * int(sub.get("duration_days", 1)))

                        crit_badge  = " 🔥 CRITICAL" if is_crit else ""
                        out_badge   = " 🏭 OUTSOURCE" if outsrc else ""
                        mh_status   = ("✅" if total_allotted_mh >= req_mh
                                       else "⚠️" if total_allotted_mh > 0 else "❌")

                        with st.container(border=True):
                            r1, r2, r3, r4, r5 = st.columns([3.5, 1.5, 1, 1, 1])

                            r1.markdown(
                                f"{STATUS_ICON.get(status,'🔵')} **{sub['name']}**"
                                f"{crit_badge}{out_badge}  \n"
                                f"<small>"
                                f"{fmt(p_start,'%d-%b')} → {fmt(p_end,'%d-%b')} "
                                f"| {sub.get('duration_days',1)}d "
                                f"| {sub.get('manpower_required',1)} workers "
                                f"| Float: {float_d}d "
                                f"| MH: {mh_status} {total_allotted_mh:.0f}/{req_mh:.0f}h"
                                f"</small>",
                                unsafe_allow_html=True,
                            )

                            new_s = r2.selectbox(
                                "", STATUSES,
                                index=STATUSES.index(status) if status in STATUSES else 0,
                                key=f"sts_{sub_id}", label_visibility="collapsed")
                            if r3.button("✓", key=f"stssv_{sub_id}", use_container_width=True):
                                upd = {"status": new_s}
                                if new_s == "Active" and not sub.get("actual_start"):
                                    upd["actual_start"] = TODAY.isoformat()
                                elif new_s == "Completed" and not sub.get("actual_end"):
                                    upd["actual_end"] = TODAY.isoformat()
                                db_update("sub_tasks", upd, "id", sub_id)
                                st.rerun()

                            if r4.button("📅", key=f"resch_{sub_id}",
                                         use_container_width=True, help="Reschedule"):
                                st.session_state[f"resch_{sub_id}"] = True

                            if r5.button("🗑️", key=f"del_{sub_id}", use_container_width=True):
                                db_delete("sub_tasks", "id", sub_id); st.rerun()

                            # Reschedule panel
                            if st.session_state.get(f"resch_{sub_id}"):
                                with st.container(border=True):
                                    st.caption("📅 Reschedule Sub Task")
                                    rc1, rc2 = st.columns(2)
                                    new_start = rc1.date_input("New Start",
                                                               value=p_start or TODAY,
                                                               key=f"nrs_{sub_id}")
                                    new_dur   = rc2.number_input(
                                        "New Duration (days)", min_value=1,
                                        value=int(sub.get("duration_days", 1)),
                                        key=f"nrd_{sub_id}")
                                    rev_reason = st.text_input("Reason *", key=f"rrr_{sub_id}")
                                    rev_by     = st.text_input("Revised by", key=f"rrb_{sub_id}")

                                    bc1, bc2 = st.columns(2)
                                    if bc1.button("💾 Save", key=f"savrev_{sub_id}"):
                                        if not rev_reason:
                                            st.error("Reason is mandatory.")
                                        else:
                                            new_end = new_start + timedelta(days=new_dur - 1)
                                            rev_no  = len(df_rev[df_rev["sub_task_id"] == sub_id]) + 1
                                            db_insert("schedule_revisions", {
                                                "job_no": job, "sub_task_id": sub_id,
                                                "revision_no": rev_no, "reason": rev_reason,
                                                "revised_by": rev_by,
                                                "old_start": str(p_start), "old_end": str(p_end),
                                                "new_start": str(new_start), "new_end": str(new_end),
                                                "impact_days": (new_end - p_end).days if p_end else 0,
                                                "created_at": NOW_IST(),
                                            })
                                            db_update("sub_tasks", {
                                                "planned_start": str(new_start),
                                                "planned_end":   str(new_end),
                                                "duration_days": new_dur,
                                            }, "id", sub_id)
                                            del st.session_state[f"resch_{sub_id}"]
                                            st.success(f"Rev #{rev_no} saved.")
                                            st.rerun()
                                    if bc2.button("Cancel", key=f"canrev_{sub_id}"):
                                        del st.session_state[f"resch_{sub_id}"]; st.rerun()

                            # Revision history
                            sub_revs = df_rev[df_rev["sub_task_id"] == sub_id] \
                                       if not df_rev.empty else pd.DataFrame()
                            if not sub_revs.empty:
                                with st.expander(f"📜 {len(sub_revs)} revision(s)"):
                                    for _, rv in sub_revs.iterrows():
                                        imp   = int(rv.get("impact_days", 0))
                                        color = "red" if imp > 0 else "green"
                                        st.markdown(
                                            f"**Rev #{rv['revision_no']}** · "
                                            f"{rv.get('revised_by','—')}  \n"
                                            f"{fmt(safe_date(rv.get('old_start')),'%d-%b')} → "
                                            f"{fmt(safe_date(rv.get('old_end')),'%d-%b')} ⟶ "
                                            f"{fmt(safe_date(rv.get('new_start')),'%d-%b')} → "
                                            f"{fmt(safe_date(rv.get('new_end')),'%d-%b')} "
                                            f"| <span style='color:{color}'>Δ {imp:+d}d</span>  \n"
                                            f"*{rv.get('reason','')}*",
                                            unsafe_allow_html=True,
                                        )


# ══════════════════════════════════════════════
# TAB 2 — GANTT
# ══════════════════════════════════════════════
with tab_gantt:
    st.subheader("📅 Gantt Chart")
    g_job = st.selectbox("Job", ["-- Select --"] + all_jobs, key="gantt_job")
    if g_job == "-- Select --":
        st.stop()

    g_main = df_main[df_main["job_no"] == g_job].sort_values("task_order") \
             if not df_main.empty else pd.DataFrame()
    g_sub  = df_sub[df_sub["job_no"] == g_job].sort_values("sub_order") \
             if not df_sub.empty else pd.DataFrame()

    if not g_sub.empty:
        g_sub = compute_cpm(g_sub)

    if g_sub.empty:
        st.info("No sub tasks to display.")
    else:
        starts = pd.to_datetime(g_sub["planned_start"].dropna())
        ends   = pd.to_datetime(g_sub["planned_end"].dropna())

        if starts.empty:
            st.warning("No dates set on sub tasks.")
        else:
            win_start = starts.min().date()
            win_end   = ends.max().date()

            # Weekly columns
            weeks = []
            d = win_start - timedelta(days=win_start.weekday())
            while d <= win_end:
                weeks.append(d)
                d += timedelta(days=7)

            html = (
                "<style>"
                ".gantt-wrap{overflow-x:auto}"
                ".gantt{border-collapse:collapse;font-size:12px;width:100%}"
                ".gantt th,.gantt td{border:0.5px solid var(--color-border-tertiary);"
                "padding:3px 6px;white-space:nowrap}"
                ".gantt th{background:var(--color-background-secondary);font-weight:500;text-align:center}"
                ".gantt .lbl{text-align:left;min-width:170px;max-width:220px;"
                "overflow:hidden;text-overflow:ellipsis}"
                ".bc{border-radius:3px;height:13px;margin:2px 0}"
                ".b-crit{background:#E24B4A}"
                ".b-act{background:#378ADD}"
                ".b-done{background:#639922}"
                ".b-pend{background:#B4B2A9}"
                ".b-hold{background:#EF9F27}"
                ".mt-r td{background:var(--color-background-secondary);font-weight:500}"
                ".tw{background:rgba(239,159,39,0.10)!important}"
                "</style>"
                "<div class='gantt-wrap'><table class='gantt'>"
                "<thead><tr><th class='lbl'>Task</th>"
            )
            for w in weeks:
                is_tw = w <= TODAY <= w + timedelta(days=6)
                cls   = " class='tw'" if is_tw else ""
                html += f"<th{cls} style='min-width:76px'>{w.strftime('%d %b')}</th>"
            html += "</tr></thead><tbody>"

            for _, mt in g_main.iterrows():
                html += f"<tr class='mt-r'><td class='lbl'>&#128230; {mt['name']}</td>"
                html += "<td></td>" * len(weeks)
                html += "</tr>"

                mt_subs = g_sub[g_sub["main_task_id"] == int(mt["id"])]
                for _, sub in mt_subs.iterrows():
                    ps     = safe_date(sub.get("planned_start"))
                    pe     = safe_date(sub.get("planned_end"))
                    status = sub.get("status", "Pending")
                    crit   = sub.get("is_critical", False)
                    out    = sub.get("outsource_flag", False)

                    icon = STATUS_ICON.get(status, "")
                    crit_tag = " &#128293;" if crit else ""
                    out_tag  = " &#127981;" if out else ""
                    html += (f"<td class='lbl' style='padding-left:18px'>"
                             f"{icon}{sub['name']}{crit_tag}{out_tag}</td>")

                    for w in weeks:
                        w_end  = w + timedelta(days=6)
                        tw_cls = " tw" if w <= TODAY <= w_end else ""
                        if ps and pe and ps <= w_end and pe >= w:
                            bar = ("b-crit" if crit and status != "Completed"
                                   else "b-done" if status == "Completed"
                                   else "b-act"  if status == "Active"
                                   else "b-hold" if status in ("On Hold", "Blocked")
                                   else "b-pend")
                            html += f"<td class='{tw_cls}'><div class='bc {bar}'></div></td>"
                        else:
                            html += f"<td class='{tw_cls}'></td>"
                    html += "</tr>"

            html += "</tbody></table></div>"
            html += (
                "<div style='margin-top:8px;font-size:11px;"
                "color:var(--color-text-secondary);display:flex;gap:14px;flex-wrap:wrap'>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#E24B4A;border-radius:2px'></span> Critical</span>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#378ADD;border-radius:2px'></span> Active</span>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#639922;border-radius:2px'></span> Completed</span>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#B4B2A9;border-radius:2px'></span> Pending</span>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#EF9F27;border-radius:2px'></span> On Hold</span>"
                "<span style='background:rgba(239,159,39,0.10);padding:0 4px;"
                "border-radius:2px'>Current week</span>"
                "</div>"
            )
            st.components.v1.html(html,
                                  height=min(100 + len(g_sub) * 28, 650),
                                  scrolling=True)

    # Revision log for this job
    job_revs = df_rev[df_rev["job_no"] == g_job] if not df_rev.empty else pd.DataFrame()
    if not job_revs.empty:
        with st.expander(f"📜 Schedule Revision Log — {len(job_revs)} entries"):
            disp = job_revs[["revision_no", "sub_task_id", "reason", "revised_by",
                              "old_start", "old_end", "new_start", "new_end",
                              "impact_days", "created_at"]].copy()
            disp["created_at"] = pd.to_datetime(disp["created_at"], utc=True, errors="coerce")\
                                    .dt.tz_convert(IST).dt.strftime("%d-%b %H:%M")
            st.dataframe(disp, use_container_width=True, hide_index=True)
            st.download_button("📥 Export", to_csv(disp), f"revisions_{g_job}.csv")


# ══════════════════════════════════════════════
# TAB 3 — MANPOWER LOAD
# ══════════════════════════════════════════════
with tab_manpower:
    st.subheader("👥 Manpower Load & Optimisation")

    c1, c2 = st.columns(2)
    m_job  = c1.selectbox("Filter Job", ["All Jobs"] + all_jobs, key="mp_job")
    m_week = c2.date_input("Week starting", value=week_monday(), key="mp_week")
    m_week = week_monday(m_week)

    asgn_src = df_asgn.copy() if not df_asgn.empty else pd.DataFrame()
    if m_job != "All Jobs" and not asgn_src.empty:
        asgn_src = asgn_src[asgn_src["job_no"] == m_job]

    load_df = manpower_load(asgn_src, df_pool, m_week)

    if not load_df.empty:
        ov = len(load_df[load_df["status"].str.contains("Over")])
        ok = len(load_df[load_df["status"].str.contains("Opt")])
        un = len(load_df[load_df["status"].str.contains("Under")])
        mk1, mk2, mk3 = st.columns(3)
        mk1.metric("🔴 Overloaded",    ov)
        mk2.metric("🟢 Optimal",       ok)
        mk3.metric("⚪ Underutilised", un)

        over_df = load_df[load_df["status"].str.contains("Over")]
        if not over_df.empty:
            st.warning("**Overloaded workers — action needed:**")
            for _, w in over_df.iterrows():
                excess = w["allocated_hrs"] - w["daily_cap_hrs"]
                st.markdown(
                    f"🔴 **{w['worker_name']}** · {w['allocated_hrs']:.1f}h / "
                    f"{w['daily_cap_hrs']:.1f}h cap → **+{excess:.1f}h excess/day**  \n"
                    f"Options: ① Extend task duration by ~{int(np.ceil(w['allocated_hrs']/w['daily_cap_hrs']))-1} days  "
                    f"② Add temporary worker  ③ Outsource sub task"
                )

        under_df = load_df[load_df["status"].str.contains("Under")]
        if not under_df.empty:
            st.info(f"**{len(under_df)} underutilised workers** — consider redeploying to overloaded tasks.")

        st.dataframe(
            load_df.rename(columns={
                "worker_name":   "Worker",
                "allocated_hrs": "Alloc. Hrs/Day",
                "daily_cap_hrs": "Capacity Hrs/Day",
                "load_pct":      "Load %",
                "status":        "Status",
            }),
            use_container_width=True, hide_index=True,
        )
        st.download_button("📥 Export Load", to_csv(load_df), f"load_{m_week}.csv")
    else:
        st.info("No assignments for this week. Use the form below to assign workers.")

    st.divider()
    st.markdown("#### Assign Worker to Sub Task")
    a_job = st.selectbox("Job", ["-- Select --"] + all_jobs, key="asgn_job")
    if a_job != "-- Select --":
        a_subs = df_sub[df_sub["job_no"] == a_job] if not df_sub.empty else pd.DataFrame()
        if not a_subs.empty:
            with st.form("assign_worker", clear_on_submit=True):
                sub_opts = {int(r["id"]): f"{r['name']} ({r.get('duration_days',1)}d)"
                            for _, r in a_subs.iterrows()}
                a1, a2, a3 = st.columns(3)
                a_sub    = a1.selectbox("Sub Task", list(sub_opts.keys()),
                                        format_func=lambda x: sub_opts.get(x, str(x)))
                a_worker = a2.selectbox("Worker", all_workers)
                a_hrs    = a3.number_input("Hrs/Day allocated", min_value=0.5, value=8.0, step=0.5)
                b1, b2   = st.columns(2)
                a_week   = b1.date_input("Week Starting", value=week_monday())
                a_target = b2.text_input("Weekly target / goal")
                if st.form_submit_button("Assign"):
                    db_insert("task_assignments", {
                        "sub_task_id": a_sub, "job_no": a_job,
                        "worker_name": a_worker,
                        "allocated_hrs_day": float(a_hrs),
                        "week_start_date": str(week_monday(a_week)),
                        "target_description": a_target,
                        "created_at": NOW_IST(),
                    })
                    st.success(f"Assigned {a_worker}."); st.rerun()
        else:
            st.info("No sub tasks in this job.")

    with st.expander("👤 Manpower Pool"):
        if not df_pool.empty:
            st.dataframe(df_pool[["worker_name","worker_type","trade",
                                   "daily_cap_hrs","active"]],
                         use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════
# TAB 4 — WEEKLY SLIPS
# ══════════════════════════════════════════════
with tab_slips:
    st.subheader("📋 Weekly Work Plan Slips")

    sc1, sc2 = st.columns(2)
    sl_week   = sc1.date_input("Week Starting", value=week_monday(), key="sl_week")
    sl_week   = week_monday(sl_week)
    sl_worker = sc2.selectbox("Worker", ["-- All --"] + all_workers, key="sl_worker")

    with st.expander("➕ Generate Slip for a Worker", expanded=False):
        with st.form("gen_slip", clear_on_submit=True):
            g1, g2, g3 = st.columns(3)
            gs_worker = g1.selectbox("Worker", all_workers, key="gsw")
            gs_job    = g2.selectbox("Job", all_jobs, key="gsj") if all_jobs else None
            gs_week   = g3.date_input("Week", value=week_monday())
            gs_week   = week_monday(gs_week)
            gs_by     = st.text_input("Issued by (supervisor)")

            gs_subs = df_sub[df_sub["job_no"] == gs_job] if gs_job and not df_sub.empty else pd.DataFrame()
            sub_opts2 = {int(r["id"]): r["name"] for _, r in gs_subs.iterrows()}
            gs_tasks = st.multiselect("Tasks to include", list(sub_opts2.keys()),
                                      format_func=lambda x: sub_opts2.get(x, str(x)))

            if st.form_submit_button("Generate Slip") and gs_job and gs_tasks:
                slip_items = []
                for tid in gs_tasks:
                    sr = df_sub[df_sub["id"] == tid]
                    if sr.empty:
                        continue
                    sr = sr.iloc[0]
                    arow = df_asgn[
                        (df_asgn["sub_task_id"] == tid) &
                        (df_asgn["worker_name"] == gs_worker) &
                        (pd.to_datetime(df_asgn["week_start_date"]).dt.date == gs_week)
                    ] if not df_asgn.empty else pd.DataFrame()
                    t_hrs  = float(arow.iloc[0]["allocated_hrs_day"]) if not arow.empty else float(sr.get("man_hours_per_day", 8))
                    t_desc = arow.iloc[0]["target_description"] if not arow.empty else ""
                    slip_items.append({
                        "sub_task_id": tid, "task_name": sr["name"],
                        "target_hrs": t_hrs, "notes": sr.get("notes",""),
                        "target_desc": t_desc,
                    })
                db_insert("weekly_slips", {
                    "worker_name": gs_worker, "job_no": gs_job,
                    "week_start_date": str(gs_week),
                    "slip_data": json.dumps(slip_items),
                    "generated_by": gs_by, "acknowledged": False,
                    "created_at": NOW_IST(),
                })
                st.success(f"Slip generated for {gs_worker} — w/c {fmt(gs_week,'%d-%b')}.")
                st.rerun()

    st.divider()

    # Display slips
    show_slips = df_slips.copy() if not df_slips.empty else pd.DataFrame()
    if not show_slips.empty:
        show_slips["week_start_date"] = pd.to_datetime(show_slips["week_start_date"]).dt.date
        if sl_worker != "-- All --":
            show_slips = show_slips[show_slips["worker_name"] == sl_worker]
        show_slips = show_slips[show_slips["week_start_date"] == sl_week]

    if show_slips.empty:
        st.info("No slips for the selected week/worker.")
    else:
        for _, slip in show_slips.iterrows():
            try:
                tasks = json.loads(slip["slip_data"]) if isinstance(slip["slip_data"], str) \
                        else (slip["slip_data"] or [])
            except Exception:
                tasks = []

            wk_end = slip["week_start_date"] + timedelta(days=5)
            ack    = slip.get("acknowledged", False)

            with st.container(border=True):
                h1, h2, h3 = st.columns([3, 2, 1])
                h1.markdown(
                    f"### {slip['worker_name']}\n"
                    f"**Job:** `{slip['job_no']}` · "
                    f"{fmt(slip['week_start_date'],'%d-%b')} – {fmt(wk_end,'%d-%b')}"
                )
                h2.caption(
                    f"Issued by: {slip.get('generated_by','—')}  \n"
                    f"{'✅ Acknowledged' if ack else '⏳ Pending acknowledgement'}"
                )
                if not ack and h3.button("✅ Acknowledge", key=f"ack_{slip['id']}"):
                    db_update("weekly_slips", {"acknowledged": True}, "id", int(slip["id"]))
                    st.rerun()

                if tasks:
                    rows = [{"Task": t.get("task_name","—"),
                             "Hrs/Day": t.get("target_hrs", 8),
                             "Week Total (6d)": f"{t.get('target_hrs',8)*6:.0f} hrs",
                             "Goal / Target": t.get("target_desc","—"),
                             "Notes": t.get("notes","—")}
                            for t in tasks]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.caption("No tasks in slip.")

                # Printable text download
                lines = [
                    "=" * 55,
                    "   B&G ENGINEERING — WEEKLY WORK PLAN SLIP",
                    "=" * 55,
                    f"Worker   : {slip['worker_name']}",
                    f"Job No.  : {slip['job_no']}",
                    f"Week     : {fmt(slip['week_start_date'],'%d-%b-%Y')} to {fmt(wk_end,'%d-%b-%Y')}",
                    f"Issued by: {slip.get('generated_by','—')}",
                    "-" * 55,
                ]
                for i, t in enumerate(tasks, 1):
                    lines += [
                        f"{i}. TASK   : {t.get('task_name')}",
                        f"   TARGET : {t.get('target_hrs')} hrs/day  |  Week total: {t.get('target_hrs',8)*6:.0f} hrs",
                    ]
                    if t.get("target_desc"):
                        lines.append(f"   GOAL   : {t.get('target_desc')}")
                    if t.get("notes"):
                        lines.append(f"   NOTES  : {t.get('notes')}")
                    lines.append("")
                lines += [
                    "-" * 55,
                    "Worker Signature : _________________________",
                    "Supervisor Sign  : _________________________",
                    f"Date             : _______________",
                    "=" * 55,
                ]
                st.download_button(
                    "🖨️ Download Printable Slip (.txt)",
                    "\n".join(lines).encode(),
                    f"WorkSlip_{slip['worker_name'].replace(' ','_')}_{slip['week_start_date']}.txt",
                    key=f"dlslip_{slip['id']}",
                )


# ══════════════════════════════════════════════
# TAB 5 — DAILY LOGS
# ══════════════════════════════════════════════
with tab_logs:
    st.subheader("📝 Daily Production Log")
    lg_job = st.selectbox("Job", ["-- Select --"] + all_jobs, key="lg_job")

    if lg_job != "-- Select --":
        lg_subs = df_sub[df_sub["job_no"] == lg_job] if not df_sub.empty else pd.DataFrame()
        active  = lg_subs[lg_subs["status"] == "Active"] if not lg_subs.empty else pd.DataFrame()
        form_subs = active if not active.empty else lg_subs

        if not form_subs.empty:
            sub_opts3 = {int(r["id"]): r["name"] for _, r in form_subs.iterrows()}
            with st.form("daily_log", clear_on_submit=True):
                l1, l2, l3 = st.columns(3)
                lg_sub    = l1.selectbox("Sub Task", list(sub_opts3.keys()),
                                         format_func=lambda x: sub_opts3.get(x, str(x)))
                lg_worker = l2.selectbox("Worker", all_workers)
                lg_date   = l3.date_input("Date", value=TODAY)
                l4, l5, l6 = st.columns(3)
                lg_hrs  = l4.number_input("Hours", min_value=0.0, step=0.5)
                lg_out  = l5.number_input("Output Qty", min_value=0.0, step=0.1)
                lg_unit = l6.selectbox("Unit", UNITS)
                lg_note = st.text_input("Remarks")
                if st.form_submit_button("Log Entry"):
                    db_insert("daily_logs", {
                        "sub_task_id": lg_sub, "job_no": lg_job,
                        "worker_name": lg_worker, "log_date": str(lg_date),
                        "hours_worked": float(lg_hrs), "output_qty": float(lg_out),
                        "output_unit": lg_unit, "notes": lg_note,
                        "created_at": NOW_IST(),
                    })
                    st.success("Entry logged."); st.rerun()
        else:
            st.warning("No sub tasks in this job.")

    if not df_logs.empty:
        show_logs = df_logs[df_logs["job_no"] == lg_job] if lg_job != "-- Select --" else df_logs
        show_logs = show_logs.copy()
        show_logs["log_date"] = pd.to_datetime(show_logs["log_date"]).dt.date
        st.dataframe(
            show_logs[["log_date","job_no","worker_name","hours_worked",
                        "output_qty","output_unit","notes"]].head(30),
            use_container_width=True, hide_index=True,
        )
        st.download_button("📥 Export", to_csv(show_logs),
                           f"logs_{lg_job if lg_job!='-- Select --' else 'all'}.csv")


# ══════════════════════════════════════════════
# TAB 6 — ANALYTICS
# ══════════════════════════════════════════════
with tab_analytics:
    st.subheader("📊 Analytics")
    if df_logs.empty:
        st.info("No log data yet.")
    else:
        adf = df_logs.copy()
        adf["log_date"]     = pd.to_datetime(adf["log_date"]).dt.date
        adf["hours_worked"] = pd.to_numeric(adf["hours_worked"], errors="coerce").fillna(0)
        adf["output_qty"]   = pd.to_numeric(adf["output_qty"],   errors="coerce").fillna(0)

        ac1, ac2 = st.columns(2)
        an_job  = ac1.multiselect("Jobs",    all_jobs,    default=all_jobs)
        an_wrkr = ac2.multiselect("Workers", all_workers, default=all_workers)
        period  = st.selectbox("Period",
                               ["Last 7 Days","Last 30 Days","Current Month","All Time"])
        d_from  = {"Last 7 Days":  TODAY - timedelta(days=7),
                   "Last 30 Days": TODAY - timedelta(days=30),
                   "Current Month":TODAY.replace(day=1),
                   "All Time":     date(2000, 1, 1)}[period]

        rdf = adf[
            (adf["log_date"] >= d_from) &
            (adf["job_no"].isin(an_job)) &
            (adf["worker_name"].isin(an_wrkr))
        ]

        if rdf.empty:
            st.warning("No data for selection.")
        else:
            k1, k2, k3, k4 = st.columns(4)
            th = rdf["hours_worked"].sum()
            to_ = rdf["output_qty"].sum()
            k1.metric("Man-Hours",      f"{th:.1f}")
            k2.metric("Total Output",   f"{to_:.0f}")
            k3.metric("Productivity",   f"{(to_/th if th else 0):.2f} U/Hr")
            k4.metric("Active Workers", rdf["worker_name"].nunique())

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### By Worker")
                ws = rdf.groupby("worker_name")[["hours_worked","output_qty"]].sum().reset_index()
                ws["U/Hr"] = (ws["output_qty"] / ws["hours_worked"].replace(0, np.nan)).round(2).fillna(0)
                st.dataframe(ws.rename(columns={"worker_name":"Worker","hours_worked":"Hrs",
                                                 "output_qty":"Output"}),
                             use_container_width=True, hide_index=True)
                st.download_button("📥", to_csv(ws), "worker_analytics.csv")

            with c2:
                st.markdown("#### By Job")
                js = rdf.groupby("job_no")[["hours_worked","output_qty"]].sum().reset_index()
                st.dataframe(js.rename(columns={"job_no":"Job","hours_worked":"Hrs",
                                                  "output_qty":"Output"}),
                             use_container_width=True, hide_index=True)
                st.download_button("📥", to_csv(js), "job_analytics.csv")

            # Schedule compliance: planned vs actual per sub task
            if not df_sub.empty and not df_logs.empty:
                st.markdown("#### Schedule Compliance")
                comp = df_sub[df_sub["job_no"].isin(an_job)].copy()
                comp["p_start"] = pd.to_datetime(comp["planned_start"]).dt.date
                comp["p_end"]   = pd.to_datetime(comp["planned_end"]).dt.date
                comp["a_end"]   = pd.to_datetime(comp["actual_end"]).dt.date
                comp["delay"]   = comp.apply(
                    lambda r: (r["a_end"] - r["p_end"]).days
                              if r["a_end"] and r["p_end"] else None, axis=1)
                comp["on_time"] = comp["delay"].apply(
                    lambda x: "✅ On time" if x is not None and x <= 0
                              else ("🔴 Late" if x is not None else "⏳ Ongoing"))
                st.dataframe(comp[["job_no","name","p_start","p_end","a_end","delay","on_time",
                                    "status"]].rename(columns={
                    "job_no":"Job","name":"Sub Task","p_start":"Planned Start",
                    "p_end":"Planned End","a_end":"Actual End","delay":"Delay (days)",
                    "on_time":"Result","status":"Status",
                }), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════
# TAB 7 — MASTER
# ══════════════════════════════════════════════
with tab_master:
    st.subheader("⚙️ Master Settings")
    m1, m2 = st.columns(2)

    with m1:
        st.markdown("#### Add Worker")
        with st.form("add_worker", clear_on_submit=True):
            w1, w2 = st.columns(2)
            w_name  = w1.text_input("Name")
            w_type  = w2.selectbox("Type", WORKER_TYPES)
            w3, w4  = st.columns(2)
            w_trade = w3.selectbox("Trade", TRADES)
            w_cap   = w4.number_input("Daily Capacity (hrs)", value=8.0, step=0.5)
            w5, w6  = st.columns(2)
            w_from  = w5.date_input("Available From", value=TODAY)
            w_to    = w6.date_input("Available To",   value=TODAY + timedelta(days=180))
            w_rate  = st.number_input("Daily Rate (₹)", min_value=0.0, step=100.0)

            if st.form_submit_button("Add Worker") and w_name:
                db_insert("manpower_pool", {
                    "worker_name": w_name, "worker_type": w_type,
                    "trade": w_trade, "daily_cap_hrs": float(w_cap),
                    "available_from": str(w_from), "available_to": str(w_to),
                    "daily_rate": float(w_rate) if w_rate else None,
                    "active": True, "created_at": NOW_IST(),
                })
                st.success(f"Added {w_name}."); st.rerun()

    with m2:
        st.markdown("#### Manpower Pool")
        if not df_pool.empty:
            st.dataframe(df_pool[["worker_name","worker_type","trade",
                                   "daily_cap_hrs","active"]],
                         use_container_width=True, hide_index=True)
            t_name = st.selectbox("Toggle active status for:", df_pool["worker_name"].tolist())
            if st.button("Toggle"):
                cur = bool(df_pool[df_pool["worker_name"] == t_name]["active"].iloc[0])
                db_update("manpower_pool", {"active": not cur}, "worker_name", t_name)
                st.rerun()
        else:
            st.info("No workers added yet.")
