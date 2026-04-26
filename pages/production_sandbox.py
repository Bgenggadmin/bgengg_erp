"""
B&G Production Scheduler ERP — v7 (Single Source of Truth)
ARCHITECTURE CHANGE: Work Slips no longer have a separate "Generate" form.
Slips are auto-derived from `task_assignments` joined with `sub_tasks`.
The supervisor's job is just to allocate workers to tasks (Manpower tab) —
the Work Slips tab shows pending slips ready to issue with one click.
This eliminates the dual-input bug class (allocation vs. slip generation
disagreeing about who has which task).

Data flow:
    sub_tasks (dates)  ┐
                       ├──► auto-derived candidate slips ──► [Issue] ──► weekly_slips snapshot
    task_assignments   ┘                                                  (frozen for audit)

All bugs fixed:
  ✅ Slips: Work Slips tab is now a derived view of task_assignments + sub_tasks
           with one-click Issue. No more dual-input data entry. (v7)
  ✅ Slips: Acknowledgement preserved on the snapshot weekly_slips row. (v7)
  ✅ Slips: STRICT MODE — only assigned workers get the task on a slip
  ✅ Slips: assignments are filtered by overlap with the slip's period
  ✅ Slips: per-card 🗑️ delete + bulk delete of filtered slips
  ✅ Manpower load: uses real sub_task date windows, not just stored week
  ✅ Manpower: per-worker drill-down shows which tasks make up the load
  ✅ Tabs: Schedule/Gantt no longer halt the script when no job is selected
           (replaced st.stop() with if/else so later tabs still render)
  ✅ Daily log: hours prefill moved outside form
  ✅ Type safety: sub_task_id cast to int everywhere
  ✅ All previous fixes retained
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


def log_revision(job_no, sub_task_id, old_start, old_end,
                 new_start, new_end, reason, revised_by, existing_revs_df):
    rev_no = len(existing_revs_df[existing_revs_df["sub_task_id"] == sub_task_id]) + 1 \
             if not existing_revs_df.empty else 1
    impact = (new_end - old_end).days if old_end and new_end else 0
    db_insert("schedule_revisions", {
        "job_no": job_no, "sub_task_id": sub_task_id,
        "revision_no": rev_no, "reason": reason,
        "revised_by": revised_by or "System",
        "old_start": str(old_start) if old_start else None,
        "old_end":   str(old_end)   if old_end   else None,
        "new_start": str(new_start), "new_end": str(new_end),
        "impact_days": impact, "created_at": NOW_IST(),
    })
    return rev_no


# ─────────────────────────────────────────────
# MASTER LISTS — session cache
# ─────────────────────────────────────────────
def _load_master() -> dict:
    try:
        w = conn.table("master_workers").select("name").order("name").execute()
        s = conn.table("master_staff").select("name").order("name").execute()
        g = conn.table("production_gates").select("gate_name").order("step_order").execute()
        return {
            "workers": [r["name"] for r in (w.data or [])],
            "staff":   [r["name"] for r in (s.data or [])],
            "gates":   [r["gate_name"] for r in (g.data or [])],
        }
    except Exception as e:
        st.error(f"Master sync error: {e}")
        return {"workers": [], "staff": [], "gates": []}


if "master" not in st.session_state or not st.session_state.master.get("workers"):
    st.session_state.master = _load_master()

master      = st.session_state.master
all_workers = sorted(list(set(master.get("workers", []))))
all_staff   = master.get("staff", [])


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
        return (pd.DataFrame(proj.data  or []), pd.DataFrame(mt.data    or []),
                pd.DataFrame(st_.data   or []), pd.DataFrame(asgn.data  or []),
                pd.DataFrame(rev.data   or []), pd.DataFrame(pool.data  or []),
                pd.DataFrame(logs.data  or []), pd.DataFrame(slips.data or []))
    except Exception as e:
        st.error(f"Load error: {e}")
        return tuple(pd.DataFrame() for _ in range(8))


(df_proj, df_main, df_sub, df_asgn,
 df_rev, df_pool, df_logs, df_slips) = load_data()

# FIX: cast sub_task_id to int everywhere for consistent comparison
if not df_asgn.empty and "sub_task_id" in df_asgn.columns:
    df_asgn["sub_task_id"] = df_asgn["sub_task_id"].astype("Int64")
if not df_sub.empty and "id" in df_sub.columns:
    df_sub["id"] = df_sub["id"].astype("Int64")

all_jobs = sorted(df_proj["job_no"].astype(str).unique().tolist()) if not df_proj.empty else []


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
# AUTO-SCHEDULE
# ─────────────────────────────────────────────
def auto_schedule_from(source_subs: pd.DataFrame, new_start: date) -> pd.DataFrame:
    if source_subs.empty:
        return source_subs
    df = source_subs.copy().sort_values("sub_order").reset_index(drop=True)
    df["duration_days"] = pd.to_numeric(df["duration_days"], errors="coerce").fillna(1).astype(int)
    cursor = new_start
    new_starts, new_ends = [], []
    for _, row in df.iterrows():
        dur = int(row["duration_days"])
        new_starts.append(cursor)
        new_ends.append(cursor + timedelta(days=dur - 1))
        cursor = cursor + timedelta(days=dur)
    df["planned_start"] = new_starts
    df["planned_end"]   = new_ends
    return df


# ─────────────────────────────────────────────
# MANPOWER LOAD
# ─────────────────────────────────────────────
def manpower_load(asgn_df: pd.DataFrame, pool_df: pd.DataFrame,
                  week: date, sub_df: pd.DataFrame = None) -> pd.DataFrame:
    """
    Compute per-worker load for the given week.

    AUDIT FIX: An assignment row's `week_start_date` is just the week the
    supervisor recorded it on — it does NOT mean the task only spans that one
    week. The task's actual active window comes from sub_tasks.planned_start /
    planned_end. We treat an assignment as "active in the requested week" if
    the task overlaps that week.

    If sub_df is None or empty, falls back to the old (buggy) week_start_date
    matching behaviour so the function is backward compatible.
    """
    if asgn_df.empty:
        return pd.DataFrame()

    # Build a sub_task_id -> (planned_start, planned_end) lookup for date-range filtering
    task_window = {}
    if sub_df is not None and not sub_df.empty:
        for _, row in sub_df.iterrows():
            sid = int(row["id"]) if pd.notna(row["id"]) else None
            if sid is None:
                continue
            ps = safe_date(row.get("planned_start"))
            pe = safe_date(row.get("planned_end"))
            if ps and pe:
                task_window[sid] = (ps, pe)

    week_end = week + timedelta(days=6)

    wa = asgn_df.copy()

    if task_window:
        # NEW correct behaviour: keep assignments whose underlying task overlaps the week
        def overlaps(row):
            sid = int(row["sub_task_id"]) if pd.notna(row["sub_task_id"]) else None
            if sid is None or sid not in task_window:
                # Fall back to week_start_date check for orphan assignments
                wsd = safe_date(row.get("week_start_date"))
                return wsd == week
            ps, pe = task_window[sid]
            # overlap if task_start <= week_end AND task_end >= week_start
            return ps <= week_end and pe >= week
        wa = wa[wa.apply(overlaps, axis=1)]
    else:
        # OLD behaviour: match the stored week_start_date directly
        wa["week_start_date"] = pd.to_datetime(wa["week_start_date"]).dt.date
        wa = wa[wa["week_start_date"] == week]

    if wa.empty:
        return pd.DataFrame()

    worker_hrs = wa.groupby("worker_name")["allocated_hrs_day"].sum().reset_index()
    worker_hrs.columns = ["worker_name", "allocated_hrs"]
    if not pool_df.empty:
        merged = worker_hrs.merge(pool_df[["worker_name", "daily_cap_hrs"]], on="worker_name", how="left")
    else:
        merged = worker_hrs.copy()
        merged["daily_cap_hrs"] = 8.0
    merged["daily_cap_hrs"] = merged["daily_cap_hrs"].fillna(8)
    merged["load_pct"] = (merged["allocated_hrs"] / merged["daily_cap_hrs"] * 100).round(1)
    merged["status"] = merged["load_pct"].apply(
        lambda x: "🔴 Overloaded" if x > 100 else ("⚪ Underutilised" if x < 60 else "🟢 Optimal"))
    return merged


# ─────────────────────────────────────────────
# ALLOTMENT BADGE
# ─────────────────────────────────────────────
def allotment_badge(sub_row, asgn_df: pd.DataFrame):
    sub_id      = int(sub_row["id"])
    req_workers = int(sub_row.get("manpower_required", 1) or 1)
    mh_per_day  = float(sub_row.get("man_hours_per_day", 8) or 8)
    duration    = int(sub_row.get("duration_days", 1) or 1)
    required_mh = req_workers * mh_per_day * duration

    if not asgn_df.empty:
        task_asgn        = asgn_df[asgn_df["sub_task_id"] == sub_id].copy()
        allotted_workers = task_asgn["worker_name"].nunique()
        allotted_mh      = task_asgn["allocated_hrs_day"].sum() * duration
    else:
        allotted_workers = 0
        allotted_mh      = 0

    if allotted_workers == 0:
        badge = "❌ No allotment"
    elif allotted_mh > required_mh * 1.2:
        badge = f"⚠️ Over ({allotted_mh:.0f}/{required_mh:.0f}h, {allotted_workers}w)"
    elif allotted_mh >= required_mh * 0.95:
        badge = f"✅ OK ({allotted_mh:.0f}/{required_mh:.0f}h, {allotted_workers}w)"
    else:
        badge = f"🔻 Under ({allotted_mh:.0f}/{required_mh:.0f}h, {allotted_workers}w)"

    return badge, allotted_workers, allotted_mh, required_mh


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
                            "msg": f"Overdue by {(TODAY - p_end).days}d. Was due {fmt(p_end, '%d-%b')}."})
        if status == "Pending" and p_end and 0 <= (p_end - TODAY).days <= 3:
            alerts.append({"type": "🟡 Due Soon", "job": row.get("job_no"), "task": row.get("name"),
                            "msg": f"Due in {(p_end - TODAY).days}d."})
        if row.get("is_critical") and status != "Completed" and p_end and p_end < TODAY + timedelta(days=5):
            alerts.append({"type": "⛔ Critical", "job": row.get("job_no"), "task": row.get("name"),
                            "msg": f"Critical path. Float=0. Ends {fmt(p_end, '%d-%b')}."})
    return alerts


# ─────────────────────────────────────────────
# CASCADE RESCHEDULE
# ─────────────────────────────────────────────
def cascade_reschedule(changed_sub_id: int, new_end: date,
                       all_subs_df: pd.DataFrame, job_no: str,
                       reason: str, revised_by: str, rev_df: pd.DataFrame):
    if all_subs_df.empty:
        return

    def parse_deps(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return []
        if isinstance(val, list):
            return [int(x) for x in val if x]
        try:
            return [int(x) for x in json.loads(str(val))]
        except Exception:
            return []

    dependents = {}
    for _, row in all_subs_df.iterrows():
        for dep_id in parse_deps(row.get("depends_on")):
            dependents.setdefault(dep_id, []).append(int(row["id"]))

    changed_row = all_subs_df[all_subs_df["id"] == changed_sub_id]
    if changed_row.empty:
        return
    old_end = safe_date(changed_row.iloc[0].get("planned_end"))
    if not old_end or new_end <= old_end:
        return

    delta   = (new_end - old_end).days
    visited = set()
    queue   = dependents.get(changed_sub_id, [])[:]

    while queue:
        dep_id = queue.pop(0)
        if dep_id in visited:
            continue
        visited.add(dep_id)
        dep_row = all_subs_df[all_subs_df["id"] == dep_id]
        if dep_row.empty:
            continue
        dr    = dep_row.iloc[0]
        old_s = safe_date(dr.get("planned_start"))
        old_e = safe_date(dr.get("planned_end"))
        if not old_s or not old_e:
            continue
        new_s = old_s + timedelta(days=delta)
        new_e = old_e + timedelta(days=delta)
        db_update("sub_tasks", {"planned_start": str(new_s), "planned_end": str(new_e)}, "id", dep_id)
        log_revision(job_no, dep_id, old_s, old_e, new_s, new_e,
                     f"[Auto-cascade] {reason}", revised_by, rev_df)
        queue += dependents.get(dep_id, [])


# ══════════════════════════════════════════════
# NAVIGATION
# ══════════════════════════════════════════════
(tab_schedule, tab_gantt, tab_manpower,
 tab_slips, tab_logs, tab_analytics, tab_master) = st.tabs([
    "🏗️ Schedule", "📅 Gantt", "👥 Manpower",
    "📋 Work Slips", "📝 Daily Logs", "📊 Analytics", "⚙️ Master",
])


# ══════════════════════════════════════════════
# TAB 1 — SCHEDULE
# ══════════════════════════════════════════════
with tab_schedule:
    st.subheader("🏗️ Work Breakdown Schedule")

    alerts_all = get_alerts(df_sub)
    if alerts_all:
        with st.expander(f"⚠️ {len(alerts_all)} Alert(s) across all jobs", expanded=True):
            for a in alerts_all[:15]:
                st.markdown(f"**{a['type']}** · `{a['job']}` · {a['task']} — {a['msg']}")

    job = st.selectbox("Select Job", ["-- Select --"] + all_jobs, key="sch_job")
    if job == "-- Select --":
        st.info("Select a job to manage its schedule.")
    else:
        pr = df_proj[df_proj["job_no"] == job]
        if not pr.empty:
            p = pr.iloc[0]
            po_disp = safe_date(p.get("po_delivery_date"))
            rev_dt  = safe_date(p.get("revised_delivery_date"))
            target  = rev_dt or po_disp
            days    = (target - TODAY).days if target else None
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("PO No",        p.get("po_no") or "---")
            c2.metric("PO Dispatch",  fmt(po_disp))
            c3.metric("Revised Date", fmt(rev_dt))
            if days is not None:
                c4.metric("Days Left", f"{days}d", delta=days,
                          delta_color="normal" if days > 7 else "inverse")

        st.divider()

        job_main = df_main[df_main["job_no"] == job].sort_values("task_order") \
                   if not df_main.empty else pd.DataFrame()
        job_sub  = df_sub[df_sub["job_no"] == job].sort_values("sub_order") \
                   if not df_sub.empty else pd.DataFrame()
        if not job_sub.empty:
            job_sub = compute_cpm(job_sub)

        # ── Clone ──────────────────────────────────
        if job_main.empty:
            st.warning("⚠️ No schedule found for this job.")
            with st.expander("🔁 Clone Schedule from Another Job", expanded=True):
                other_jobs = [j for j in all_jobs if j != job]
                clone_src  = st.selectbox("Source Job (template)", ["-- Select --"] + other_jobs, key="clone_src")

                if clone_src != "-- Select --":
                    src_main = df_main[df_main["job_no"] == clone_src].sort_values("task_order") \
                               if not df_main.empty else pd.DataFrame()
                    src_sub  = df_sub[df_sub["job_no"] == clone_src].sort_values("sub_order") \
                               if not df_sub.empty else pd.DataFrame()

                    if src_main.empty:
                        st.info("Source job has no schedule to clone.")
                    else:
                        new_start = st.date_input("New Project Start Date", value=TODAY, key="clone_start")
                        preview_rows = []
                        cursor = new_start
                        for _, sm in src_main.iterrows():
                            sm_id      = int(sm["id"])
                            sm_subs    = src_sub[src_sub["main_task_id"] == sm_id]
                            sched_subs = auto_schedule_from(sm_subs, cursor)
                            for _, ss in sched_subs.iterrows():
                                preview_rows.append({
                                    "Main Task": sm["name"], "Sub Task": ss["name"],
                                    "Duration (d)": int(ss.get("duration_days", 1)),
                                    "Start": ss["planned_start"], "End": ss["planned_end"],
                                    "Workers/day": int(ss.get("manpower_required", 1)),
                                })
                            if not sched_subs.empty:
                                last_end = sched_subs["planned_end"].max()
                                cursor = (last_end if isinstance(last_end, date)
                                          else pd.to_datetime(last_end).date()) + timedelta(days=1)

                        if preview_rows:
                            st.markdown("#### 📋 Preview — Edit before saving")
                            prev_df = pd.DataFrame(preview_rows)
                            edited  = st.data_editor(
                                prev_df, use_container_width=True, num_rows="fixed",
                                column_config={
                                    "Start": st.column_config.DateColumn("Start", format="DD-MMM-YYYY"),
                                    "End":   st.column_config.DateColumn("End",   format="DD-MMM-YYYY"),
                                    "Duration (d)": st.column_config.NumberColumn("Duration (d)", min_value=1),
                                    "Workers/day":  st.column_config.NumberColumn("Workers/day",  min_value=1),
                                },
                                key="clone_editor",
                            )
                            if st.button("🚀 Save Cloned Schedule", type="primary"):
                                for _, sm in src_main.sort_values("task_order").iterrows():
                                    sm_rows  = edited[edited["Main Task"] == sm["name"]]
                                    mt_start = sm_rows["Start"].min() if not sm_rows.empty else TODAY
                                    mt_end   = sm_rows["End"].max()   if not sm_rows.empty else TODAY
                                    new_mt   = db_insert("main_tasks", {
                                        "job_no": job, "name": sm["name"],
                                        "description": sm.get("description", ""),
                                        "task_order": int(sm.get("task_order", 1)),
                                        "planned_start": str(mt_start), "planned_end": str(mt_end),
                                        "status": "Pending", "created_at": NOW_IST(),
                                    })
                                    new_mt_id = new_mt[0]["id"]
                                    sm_subs   = src_sub[src_sub["main_task_id"] == int(sm["id"])]
                                    for _, ss in sm_subs.sort_values("sub_order").iterrows():
                                        er = edited[(edited["Main Task"] == sm["name"]) &
                                                    (edited["Sub Task"]  == ss["name"])]
                                        if not er.empty:
                                            er  = er.iloc[0]
                                            ps  = er["Start"] if isinstance(er["Start"], date) else pd.to_datetime(er["Start"]).date()
                                            pe  = er["End"]   if isinstance(er["End"],   date) else pd.to_datetime(er["End"]).date()
                                            dur = int(er["Duration (d)"]); mp = int(er["Workers/day"])
                                        else:
                                            ps, pe, dur, mp = TODAY, TODAY, 1, 1
                                        db_insert("sub_tasks", {
                                            "main_task_id": new_mt_id, "job_no": job,
                                            "name": ss["name"], "sub_order": int(ss.get("sub_order", 1)),
                                            "duration_days": dur, "planned_start": str(ps), "planned_end": str(pe),
                                            "manpower_required": mp,
                                            "man_hours_per_day": float(ss.get("man_hours_per_day", 8)),
                                            "outsource_flag": bool(ss.get("outsource_flag", False)),
                                            "notes": ss.get("notes", ""), "status": "Pending", "created_at": NOW_IST(),
                                        })
                                st.success(f"✅ Cloned {len(src_main)} main tasks from {clone_src}.")
                                st.rerun()

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

        job_main = df_main[df_main["job_no"] == job].sort_values("task_order") \
                   if not df_main.empty else pd.DataFrame()

        if not job_main.empty:
            for _, mt in job_main.iterrows():
                mt_id   = int(mt["id"])
                subs    = job_sub[job_sub["main_task_id"] == mt_id] \
                          if not job_sub.empty else pd.DataFrame()
                mt_icon = STATUS_ICON.get(mt.get("status", "Pending"), "🔵")
                done    = len(subs[subs["status"] == "Completed"]) if not subs.empty else 0

                with st.expander(
                    f"{mt_icon} **{mt['name']}**  ·  "
                    f"{fmt(safe_date(mt.get('planned_start')), '%d-%b')} → "
                    f"{fmt(safe_date(mt.get('planned_end')), '%d-%b')}  "
                    f"· {done}/{len(subs)} done",
                    expanded=True,
                ):
                    edit_mt_key = f"edit_mt_{mt_id}"
                    if st.session_state.get(edit_mt_key):
                        with st.form(f"edit_mt_form_{mt_id}", clear_on_submit=False):
                            e1, e2 = st.columns([3, 1])
                            new_mt_name  = e1.text_input("Task Name", value=mt["name"])
                            new_mt_order = e2.number_input("Order", value=int(mt.get("task_order", 1)), min_value=1)
                            new_mt_desc  = st.text_input("Description", value=mt.get("description", "") or "")
                            new_mt_dates = st.date_input("Planned Window",
                                [safe_date(mt.get("planned_start")) or TODAY,
                                 safe_date(mt.get("planned_end"))   or TODAY])
                            new_mt_status = st.selectbox("Status", STATUSES,
                                index=STATUSES.index(mt.get("status", "Pending"))
                                      if mt.get("status") in STATUSES else 0)
                            bc1, bc2 = st.columns(2)
                            if bc1.form_submit_button("💾 Save"):
                                db_update("main_tasks", {
                                    "name": new_mt_name, "description": new_mt_desc,
                                    "task_order": new_mt_order,
                                    "planned_start": str(new_mt_dates[0]) if len(new_mt_dates) > 0 else None,
                                    "planned_end":   str(new_mt_dates[1]) if len(new_mt_dates) > 1 else None,
                                    "status": new_mt_status,
                                }, "id", mt_id)
                                del st.session_state[edit_mt_key]; st.rerun()
                            if bc2.form_submit_button("Cancel"):
                                del st.session_state[edit_mt_key]; st.rerun()
                    else:
                        mc1, mc2, mc3, mc4 = st.columns([5, 1, 1, 1])
                        mc1.caption(mt.get("description", "") or "")
                        if mc2.button("✏️ Edit", key=f"mt_edit_btn_{mt_id}"):
                            st.session_state[edit_mt_key] = True; st.rerun()
                        new_mt_s = mc3.selectbox("", STATUSES,
                            index=STATUSES.index(mt.get("status", "Pending"))
                                  if mt.get("status") in STATUSES else 0,
                            key=f"mts_{mt_id}", label_visibility="collapsed")
                        if mc3.button("✓", key=f"mtsv_{mt_id}"):
                            db_update("main_tasks", {"status": new_mt_s}, "id", mt_id); st.rerun()
                        if mc4.button("🗑️ Delete", key=f"mtdl_{mt_id}"):
                            db_delete("main_tasks", "id", mt_id); st.rerun()

                    st.markdown("---")

                    with st.form(f"add_sub_{mt_id}", clear_on_submit=True):
                        st.caption("➕ New Sub Task")
                        f1, f2, f3 = st.columns([3, 1, 1])
                        sn  = f1.text_input("Sub Task Name", key=f"sn_{mt_id}")
                        dur = f2.number_input("Duration (days)", min_value=1, value=3, key=f"dur_{mt_id}")
                        mp  = f3.number_input("Workers/day", min_value=1, value=2, key=f"mp_{mt_id}")
                        f4, f5, f6 = st.columns([2, 1, 2])
                        ps   = f4.date_input("Planned Start", value=TODAY, key=f"ps_{mt_id}")
                        ord_ = f5.number_input("Order", min_value=1, value=len(subs) + 1, key=f"ord_{mt_id}")
                        mh   = f6.number_input("Man-hrs/person/day", min_value=1.0, value=8.0,
                                               step=0.5, key=f"mh_{mt_id}")
                        dep_opts = {int(r["id"]): r["name"] for _, r in subs.iterrows()} \
                                   if not subs.empty else {}
                        deps = st.multiselect("Depends on", list(dep_opts.keys()),
                                              format_func=lambda x: dep_opts.get(x, str(x)),
                                              key=f"deps_{mt_id}")
                        f7, f8 = st.columns(2)
                        outsrc = f7.checkbox("Outsource", key=f"out_{mt_id}")
                        vendor = f8.text_input("Vendor", key=f"vend_{mt_id}")
                        notes  = st.text_input("Notes / Specs", key=f"notes_{mt_id}")
                        if st.form_submit_button("Add Sub Task") and sn:
                            pe = ps + timedelta(days=dur - 1)
                            db_insert("sub_tasks", {
                                "main_task_id": mt_id, "job_no": job,
                                "name": sn, "sub_order": ord_, "duration_days": dur,
                                "planned_start": ps.isoformat(), "planned_end": pe.isoformat(),
                                "manpower_required": mp, "man_hours_per_day": float(mh),
                                "depends_on": deps if deps else None,
                                "outsource_flag": outsrc, "outsource_vendor": vendor or None,
                                "notes": notes or None, "status": "Pending", "created_at": NOW_IST(),
                            })
                            st.success("Sub task added."); st.rerun()

                    if subs.empty:
                        st.caption("No sub tasks yet.")
                    else:
                        for _, sub in subs.sort_values("sub_order").iterrows():
                            sub_id  = int(sub["id"])
                            is_crit = bool(sub.get("is_critical", False))
                            float_d = int(sub.get("float_days", 0)) if pd.notna(sub.get("float_days")) else 0
                            p_start = safe_date(sub.get("planned_start"))
                            p_end   = safe_date(sub.get("planned_end"))
                            status  = sub.get("status", "Pending")
                            outsrc  = sub.get("outsource_flag", False)
                            badge, _, _, _ = allotment_badge(sub, df_asgn)
                            crit_tag = " 🔥" if is_crit else ""
                            out_tag  = " 🏭" if outsrc else ""

                            with st.container(border=True):
                                edit_sub_key = f"edit_sub_{sub_id}"
                                if st.session_state.get(edit_sub_key):
                                    with st.form(f"edit_sub_form_{sub_id}", clear_on_submit=False):
                                        es1, es2, es3 = st.columns([3, 1, 1])
                                        new_sname = es1.text_input("Name", value=sub["name"])
                                        new_dur   = es2.number_input("Duration (d)", min_value=1,
                                                                      value=int(sub.get("duration_days", 1)))
                                        new_mp    = es3.number_input("Workers/day", min_value=1,
                                                                      value=int(sub.get("manpower_required", 1)))
                                        es4, es5, es6 = st.columns([2, 2, 1])
                                        new_ps   = es4.date_input("Planned Start", value=p_start or TODAY)
                                        new_mh   = es5.number_input("Man-hrs/person/day",
                                                                      value=float(sub.get("man_hours_per_day", 8)),
                                                                      min_value=0.5, step=0.5)
                                        new_sord = es6.number_input("Order", value=int(sub.get("sub_order", 1)), min_value=1)
                                        new_notes  = st.text_input("Notes", value=sub.get("notes", "") or "")
                                        rev_reason = st.text_input("Reason for change (required if dates change)")
                                        rev_by     = st.text_input("Changed by")
                                        bc1, bc2   = st.columns(2)
                                        if bc1.form_submit_button("💾 Save"):
                                            new_pe = new_ps + timedelta(days=new_dur - 1)
                                            dates_changed = (new_ps != p_start or new_pe != p_end)
                                            if dates_changed:
                                                if not rev_reason:
                                                    st.error("Please provide a reason for the date change.")
                                                    st.stop()
                                                rev_no = log_revision(job, sub_id, p_start, p_end,
                                                                       new_ps, new_pe, rev_reason, rev_by, df_rev)
                                                st.toast(f"Rev #{rev_no} auto-logged.")
                                                cascade_reschedule(sub_id, new_pe, df_sub, job,
                                                                   rev_reason, rev_by, df_rev)
                                            db_update("sub_tasks", {
                                                "name": new_sname, "duration_days": new_dur,
                                                "manpower_required": new_mp, "man_hours_per_day": float(new_mh),
                                                "planned_start": str(new_ps), "planned_end": str(new_pe),
                                                "sub_order": new_sord, "notes": new_notes,
                                            }, "id", sub_id)
                                            del st.session_state[edit_sub_key]; st.rerun()
                                        if bc2.form_submit_button("Cancel"):
                                            del st.session_state[edit_sub_key]; st.rerun()
                                else:
                                    r1, r2, r3, r4, r5 = st.columns([4, 1.5, 1, 1, 1])
                                    r1.markdown(
                                        f"{STATUS_ICON.get(status, '🔵')} **{sub['name']}**{crit_tag}{out_tag}  \n"
                                        f"<small>{fmt(p_start, '%d-%b')} → {fmt(p_end, '%d-%b')} "
                                        f"| {sub.get('duration_days', 1)}d "
                                        f"| {sub.get('manpower_required', 1)} workers "
                                        f"| Float: {float_d}d | {badge}</small>",
                                        unsafe_allow_html=True,
                                    )
                                    new_s = r2.selectbox("", STATUSES,
                                        index=STATUSES.index(status) if status in STATUSES else 0,
                                        key=f"sts_{sub_id}", label_visibility="collapsed")
                                    if r3.button("✓", key=f"stssv_{sub_id}", use_container_width=True):
                                        upd = {"status": new_s}
                                        if new_s == "Active" and not sub.get("actual_start"):
                                            upd["actual_start"] = TODAY.isoformat()
                                        elif new_s == "Completed" and not sub.get("actual_end"):
                                            upd["actual_end"] = TODAY.isoformat()
                                        db_update("sub_tasks", upd, "id", sub_id); st.rerun()
                                    if r4.button("✏️", key=f"edit_sub_btn_{sub_id}", use_container_width=True):
                                        st.session_state[edit_sub_key] = True; st.rerun()
                                    if r5.button("🗑️", key=f"del_{sub_id}", use_container_width=True):
                                        db_delete("sub_tasks", "id", sub_id); st.rerun()

                                sub_revs = df_rev[df_rev["sub_task_id"] == sub_id] \
                                           if not df_rev.empty else pd.DataFrame()
                                if not sub_revs.empty:
                                    with st.expander(f"📜 {len(sub_revs)} revision(s)"):
                                        for _, rv in sub_revs.iterrows():
                                            imp    = int(rv.get("impact_days", 0))
                                            color  = "red" if imp > 0 else "green"
                                            auto   = "[Auto-cascade]" in str(rv.get("reason", ""))
                                            prefix = "🔄 " if auto else ""
                                            st.markdown(
                                                f"{prefix}**Rev #{rv['revision_no']}** · {rv.get('revised_by', '—')}  \n"
                                                f"{fmt(safe_date(rv.get('old_start')), '%d-%b')} → "
                                                f"{fmt(safe_date(rv.get('old_end')), '%d-%b')} ⟶ "
                                                f"{fmt(safe_date(rv.get('new_start')), '%d-%b')} → "
                                                f"{fmt(safe_date(rv.get('new_end')), '%d-%b')} "
                                                f"| <span style='color:{color}'>Δ {imp:+d}d</span>  \n"
                                                f"*{rv.get('reason', '')}*",
                                                unsafe_allow_html=True,
                                            )


# ══════════════════════════════════════════════
# TAB 2 — GANTT
# ══════════════════════════════════════════════
with tab_gantt:
    st.subheader("📅 Gantt Chart")
    g_job = st.selectbox("Job", ["-- Select --"] + all_jobs, key="gantt_job")
    if g_job == "-- Select --":
        st.info("Select a job to view its Gantt chart.")
    else:
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
                st.warning("No dates set.")
            else:
                win_start = starts.min().date()
                win_end   = ends.max().date()
                weeks = []
                d = win_start - timedelta(days=win_start.weekday())
                while d <= win_end:
                    weeks.append(d); d += timedelta(days=7)

                html = (
                    "<style>.gw{overflow-x:auto}.gt{border-collapse:collapse;font-size:12px;width:100%}"
                    ".gt th,.gt td{border:0.5px solid var(--color-border-tertiary);padding:3px 6px;white-space:nowrap}"
                    ".gt th{background:var(--color-background-secondary);font-weight:500;text-align:center}"
                    ".gt .lbl{text-align:left;min-width:170px;max-width:240px;overflow:hidden;text-overflow:ellipsis}"
                    ".bc{border-radius:3px;height:13px;margin:2px 0}"
                    ".bc-cr{background:#E24B4A}.bc-ac{background:#378ADD}"
                    ".bc-dn{background:#639922}.bc-pe{background:#B4B2A9}.bc-hl{background:#EF9F27}"
                    ".mtr td{background:var(--color-background-secondary);font-weight:500}"
                    ".tw{background:rgba(239,159,39,0.10)!important}</style>"
                    "<div class='gw'><table class='gt'><thead><tr><th class='lbl'>Task</th>"
                )
                for w in weeks:
                    cls = " class='tw'" if w <= TODAY <= w + timedelta(days=6) else ""
                    html += f"<th{cls} style='min-width:72px'>{w.strftime('%d %b')}</th>"
                html += "</tr></thead><tbody>"

                for _, mt in g_main.iterrows():
                    html += f"<tr class='mtr'><td class='lbl'>&#128230; {mt['name']}</td>"
                    html += "<td></td>" * len(weeks) + "</tr>"
                    mt_subs = g_sub[g_sub["main_task_id"] == int(mt["id"])]
                    for _, sub in mt_subs.iterrows():
                        ps  = safe_date(sub.get("planned_start"))
                        pe  = safe_date(sub.get("planned_end"))
                        st_ = sub.get("status", "Pending")
                        cr  = sub.get("is_critical", False)
                        out = sub.get("outsource_flag", False)
                        html += (f"<td class='lbl' style='padding-left:18px'>"
                                 f"{STATUS_ICON.get(st_,'')}{sub['name']}"
                                 f"{'&#128293;' if cr else ''}{'&#127981;' if out else ''}</td>")
                        for w in weeks:
                            we  = w + timedelta(days=6)
                            twc = " tw" if w <= TODAY <= we else ""
                            if ps and pe and ps <= we and pe >= w:
                                bar = ("bc-cr" if cr and st_ != "Completed" else
                                       "bc-dn" if st_ == "Completed" else
                                       "bc-ac" if st_ == "Active" else
                                       "bc-hl" if st_ in ("On Hold","Blocked") else "bc-pe")
                                html += f"<td class='{twc}'><div class='bc {bar}'></div></td>"
                            else:
                                html += f"<td class='{twc}'></td>"
                        html += "</tr>"
                html += ("</tbody></table></div>"
                         "<div style='margin-top:8px;font-size:11px;color:var(--color-text-secondary);"
                         "display:flex;gap:12px;flex-wrap:wrap'>"
                         "<span><span style='display:inline-block;width:12px;height:8px;background:#E24B4A;border-radius:2px'></span> Critical</span>"
                         "<span><span style='display:inline-block;width:12px;height:8px;background:#378ADD;border-radius:2px'></span> Active</span>"
                         "<span><span style='display:inline-block;width:12px;height:8px;background:#639922;border-radius:2px'></span> Completed</span>"
                         "<span><span style='display:inline-block;width:12px;height:8px;background:#B4B2A9;border-radius:2px'></span> Pending</span>"
                         "<span><span style='display:inline-block;width:12px;height:8px;background:#EF9F27;border-radius:2px'></span> On Hold</span></div>")
                st.components.v1.html(html, height=min(100 + len(g_sub) * 28, 650), scrolling=True)

        job_revs = df_rev[df_rev["job_no"] == g_job] if not df_rev.empty else pd.DataFrame()
        if not job_revs.empty:
            with st.expander(f"📜 Revision Log — {len(job_revs)} entries"):
                disp = job_revs.copy()
                disp["created_at"] = pd.to_datetime(disp["created_at"], utc=True, errors="coerce") \
                                        .dt.tz_convert(IST).dt.strftime("%d-%b %H:%M")
                st.dataframe(disp[["revision_no","sub_task_id","reason","revised_by",
                                    "old_start","old_end","new_start","new_end",
                                    "impact_days","created_at"]],
                             use_container_width=True, hide_index=True)
                st.download_button("📥 Export", to_csv(disp), f"revisions_{g_job}.csv")


# ══════════════════════════════════════════════
# TAB 3 — MANPOWER
# ══════════════════════════════════════════════
with tab_manpower:
    st.subheader("👥 Manpower Load & Optimisation")

    mc1, mc2 = st.columns(2)
    m_job  = mc1.selectbox("Filter Job", ["All Jobs"] + all_jobs, key="mp_job")
    m_week = mc2.date_input("Week starting", value=week_monday(), key="mp_week")
    m_week = week_monday(m_week)

    asgn_src = df_asgn.copy() if not df_asgn.empty else pd.DataFrame()
    if m_job != "All Jobs" and not asgn_src.empty:
        asgn_src = asgn_src[asgn_src["job_no"] == m_job]

    load_df = manpower_load(asgn_src, df_pool, m_week, sub_df=df_sub)

    if not load_df.empty:
        ov = load_df[load_df["status"].str.contains("Over")]
        ok = load_df[load_df["status"].str.contains("Opt")]
        un = load_df[load_df["status"].str.contains("Under")]
        mk1, mk2, mk3 = st.columns(3)
        mk1.metric("🔴 Overloaded",    len(ov))
        mk2.metric("🟢 Optimal",       len(ok))
        mk3.metric("⚪ Underutilised", len(un))
        if not ov.empty:
            st.warning("**Overloaded — action needed:**")
            for _, w in ov.iterrows():
                excess = w["allocated_hrs"] - w["daily_cap_hrs"]
                st.markdown(
                    f"🔴 **{w['worker_name']}** · {w['allocated_hrs']:.1f}h / "
                    f"{w['daily_cap_hrs']:.1f}h cap → **+{excess:.1f}h excess/day**  \n"
                    f"Options: ① Extend task by ~{int(np.ceil(w['allocated_hrs']/w['daily_cap_hrs']))-1}d "
                    f"② Add temp worker  ③ Outsource sub task"
                )
        if not un.empty:
            st.info(f"{len(un)} underutilised workers — redeploy to overloaded tasks.")
        st.dataframe(
            load_df.rename(columns={"worker_name": "Worker", "allocated_hrs": "Alloc. Hrs/Day (own)",
                                     "daily_cap_hrs": "Capacity Hrs/Day", "load_pct": "Load %",
                                     "status": "Status"}),
            use_container_width=True, hide_index=True)
        st.download_button("📥 Export Load", to_csv(load_df), f"load_{m_week}.csv")

        # ── Drill-down: see WHICH tasks make up a worker's load ──
        with st.expander("🔍 Drill down — which tasks make up a worker's load?"):
            picked = st.selectbox(
                "Worker", ["-- Select --"] + load_df["worker_name"].tolist(),
                key="mp_drill_worker",
            )
            if picked != "-- Select --":
                # Re-run the same overlap logic to get the assignments contributing
                week_end = m_week + timedelta(days=6)
                task_window = {}
                if not df_sub.empty:
                    for _, row in df_sub.iterrows():
                        sid = int(row["id"]) if pd.notna(row["id"]) else None
                        if sid is None:
                            continue
                        ps = safe_date(row.get("planned_start"))
                        pe = safe_date(row.get("planned_end"))
                        if ps and pe:
                            task_window[sid] = (ps, pe, str(row.get("name", "")),
                                                str(row.get("job_no", "")))

                worker_rows = []
                for _, ar in asgn_src[asgn_src["worker_name"] == picked].iterrows():
                    sid = int(ar["sub_task_id"]) if pd.notna(ar["sub_task_id"]) else None
                    if sid is None:
                        continue
                    info = task_window.get(sid)
                    if info is None:
                        # Orphan: no matching sub_task. Use stored week_start_date check.
                        wsd = safe_date(ar.get("week_start_date"))
                        if wsd != m_week:
                            continue
                        worker_rows.append({
                            "Job": ar.get("job_no", ""),
                            "Task": "(orphan - sub-task missing)",
                            "Task Start": "—", "Task End": "—",
                            "Hrs/Day": float(ar["allocated_hrs_day"]),
                            "Assignment ID": int(ar["id"]),
                        })
                        continue
                    ps, pe, tname, tjob = info
                    if ps <= week_end and pe >= m_week:
                        worker_rows.append({
                            "Job": tjob, "Task": tname,
                            "Task Start": fmt(ps, "%d-%b"),
                            "Task End":   fmt(pe, "%d-%b"),
                            "Hrs/Day": float(ar["allocated_hrs_day"]),
                            "Assignment ID": int(ar["id"]),
                        })

                if worker_rows:
                    drill_df = pd.DataFrame(worker_rows)
                    total_h = drill_df["Hrs/Day"].sum()
                    cap_row = df_pool[df_pool["worker_name"] == picked]
                    cap = float(cap_row.iloc[0]["daily_cap_hrs"]) if not cap_row.empty else 8.0
                    st.markdown(
                        f"**{picked}** — {len(drill_df)} active assignment(s) "
                        f"in week of {fmt(m_week, '%d-%b-%Y')}  \n"
                        f"Total allocated: **{total_h:.1f} hrs/day**  ·  "
                        f"Capacity: **{cap:.1f} hrs/day**  ·  "
                        f"Load: **{(total_h/cap*100):.0f}%**"
                    )
                    st.dataframe(drill_df, use_container_width=True, hide_index=True)
                    st.caption(
                        "💡 If you see duplicate or wrong rows, go to "
                        "'Assign Worker Pool to Sub Task' below and remove them with "
                        "the 🗑️ button. Or run: "
                        f"`DELETE FROM task_assignments WHERE id = <Assignment ID>;` in Supabase."
                    )
                else:
                    st.info(f"No active assignments for {picked} in this week.")
    else:
        st.info("No assignments for this week.")

    st.divider()
    st.markdown("#### Assign Worker Pool to Sub Task")
    st.caption("Each worker works their own hours — e.g. 3 workers × 2 hrs/day → 6 man-hrs/day team total, each charged 2 hrs only.")

    a_job = st.selectbox("Job", ["-- Select --"] + all_jobs, key="asgn_job")
    if a_job == "-- Select --":
        st.info("Select a job to assign workers.")
    else:
        a_subs = df_sub[df_sub["job_no"] == a_job] if not df_sub.empty else pd.DataFrame()
        if a_subs.empty:
            st.info("No sub tasks in this job.")
        else:
            sub_opts = {
                int(r["id"]): f"{r['name']}  ({r.get('duration_days',1)}d | "
                              f"needs {r.get('manpower_required',1)}w × {r.get('man_hours_per_day',8)}h/d)"
                for _, r in a_subs.iterrows()
            }
            a_sub_id = st.selectbox("Sub Task", list(sub_opts.keys()),
                                    format_func=lambda x: sub_opts.get(x, str(x)), key="asgn_sub")

            existing_asgn = df_asgn[df_asgn["sub_task_id"] == a_sub_id].copy() \
                            if not df_asgn.empty else pd.DataFrame()
            sub_row     = a_subs[a_subs["id"] == a_sub_id].iloc[0]
            duration    = int(sub_row.get("duration_days",    1) or 1)
            req_workers = int(sub_row.get("manpower_required", 1) or 1)
            mh_per_day  = float(sub_row.get("man_hours_per_day", 8) or 8)
            required_mh = req_workers * mh_per_day * duration

            if not existing_asgn.empty:
                allotted_mh = existing_asgn["allocated_hrs_day"].sum() * duration
                team_mh_day = existing_asgn["allocated_hrs_day"].sum()
                pct         = min(allotted_mh / required_mh * 100, 100) if required_mh else 0
                fill_color  = "#639922" if pct >= 95 else ("#EF9F27" if pct >= 50 else "#E24B4A")
                st.markdown(
                    f"<div style='background:var(--color-background-secondary);border-radius:6px;height:10px;margin:6px 0'>"
                    f"<div style='background:{fill_color};width:{pct:.0f}%;height:10px;border-radius:6px'></div></div>"
                    f"<small>Team: <b>{team_mh_day:.1f} hrs/day</b> × {duration}d = <b>{allotted_mh:.0f} hrs</b>"
                    f" | Required: {req_workers}w × {mh_per_day}h × {duration}d = <b>{required_mh:.0f} hrs</b>"
                    f" ({pct:.0f}%)</small>", unsafe_allow_html=True)

                st.markdown("**Current worker pool:**")
                for _, ea in existing_asgn.iterrows():
                    rc1, rc2, rc3, rc4 = st.columns([3, 1.5, 1, 0.8])
                    rc1.markdown(f"👤 **{ea['worker_name']}**  \n"
                                 f"<small>Wk {fmt(safe_date(ea.get('week_start_date')),'%d-%b')} "
                                 f"| {ea.get('target_description') or '—'}</small>",
                                 unsafe_allow_html=True)
                    new_hrs = rc2.number_input("h/day", min_value=0.5,
                                               value=float(ea["allocated_hrs_day"]),
                                               step=0.5, key=f"ea_h_{ea['id']}",
                                               label_visibility="collapsed")
                    if rc3.button("✓ Save", key=f"ea_sv_{ea['id']}", use_container_width=True):
                        db_update("task_assignments", {"allocated_hrs_day": float(new_hrs)},
                                  "id", int(ea["id"])); st.rerun()
                    if rc4.button("🗑️", key=f"ea_dl_{ea['id']}", use_container_width=True):
                        db_delete("task_assignments", "id", int(ea["id"])); st.rerun()
            else:
                st.caption("No workers assigned to this task yet.")

            st.divider()
            st.markdown("**Add workers to this task:**")
            already_assigned = existing_asgn["worker_name"].tolist() \
                               if not existing_asgn.empty else []

            with st.form("assign_worker_pool", clear_on_submit=True):
                selected_workers = st.multiselect(
                    "Select workers (one or more)", options=all_workers, default=[],
                    help="Pick all workers for this task. Each gets their own hour allocation.",
                    key="pool_multiselect",
                )
                if already_assigned:
                    st.caption("Already in pool: " + ", ".join(f"✓ {w}" for w in already_assigned))
                f1, f2, f3 = st.columns(3)
                shared_hrs = f1.number_input("Hrs/day per worker", min_value=0.5,
                                              value=float(mh_per_day), step=0.5,
                                              help="Each selected worker gets this many hrs/day individually.")
                a_week   = f2.date_input("Week Starting", value=week_monday())
                a_target = f3.text_input("Shared target / goal")

                new_workers_count = len(selected_workers)
                if new_workers_count:
                    new_team_day = (existing_asgn["allocated_hrs_day"].sum()
                                   if not existing_asgn.empty else 0) + new_workers_count * shared_hrs
                    new_total_mh = new_team_day * duration
                    preview_pct  = min(new_total_mh / required_mh * 100, 150) if required_mh else 0
                    pclr = "#639922" if preview_pct >= 95 else ("#EF9F27" if preview_pct >= 50 else "#E24B4A")
                    st.markdown(
                        f"<small style='color:{pclr}'>After adding: {new_workers_count} worker(s) × "
                        f"{shared_hrs}h/day → Team {new_team_day:.1f}h/day × {duration}d = "
                        f"<b>{new_total_mh:.0f} man-hrs</b> ({preview_pct:.0f}% of {required_mh:.0f}h)</small>",
                        unsafe_allow_html=True)

                if st.form_submit_button("➕ Assign Workers to Task"):
                    if not selected_workers:
                        st.error("Select at least one worker.")
                    else:
                        skipped, added = [], []
                        for w in selected_workers:
                            if w in already_assigned:
                                skipped.append(w); continue
                            db_insert("task_assignments", {
                                "sub_task_id": int(a_sub_id), "job_no": a_job,
                                "worker_name": w, "allocated_hrs_day": float(shared_hrs),
                                "week_start_date": str(week_monday(a_week)),
                                "target_description": a_target, "created_at": NOW_IST(),
                            })
                            added.append(w)
                        if added:
                            st.success(f"✅ Assigned {len(added)} worker(s): {', '.join(added)}  \n"
                                       f"Each gets {shared_hrs} hrs/day (individual allocation).")
                        if skipped:
                            st.warning(f"Skipped (already assigned): {', '.join(skipped)}")
                        st.rerun()

    with st.expander("👤 Manpower Pool"):
        if not df_pool.empty:
            st.dataframe(df_pool[["worker_name","worker_type","trade","daily_cap_hrs","active"]],
                         use_container_width=True, hide_index=True)
        else:
            st.info("Add workers in Master tab.")


# ══════════════════════════════════════════════
# TAB 4 — WORK SLIPS  (fully audited)
# ══════════════════════════════════════════════
with tab_slips:
    st.subheader("📋 Work Slips")

    # ── helpers ──────────────────────────────────────────────────────
    def build_slip_text(slip, tasks, period_label):
        # FIX 4: use period_label from caller — no hardcoded +5 days
        lines = [
            "=" * 58, "         B&G ENGINEERING — WORK PLAN SLIP", "=" * 58,
            f"Worker    : {slip['worker_name']}",
            f"Job No.   : {slip['job_no']}",
            f"Period    : {period_label}",
            f"Issued by : {slip.get('generated_by') or '—'}",
            "-" * 58,
        ]
        for i, t in enumerate(tasks, 1):
            hrs  = t.get("target_hrs", 8)
            days = t.get("target_days", 6)   # stored per-slip, not hardcoded
            lines += [f"{i}. TASK   : {t.get('task_name','—')}",
                      f"   TARGET : {hrs} hrs/day  |  Total: {hrs * days:.0f} hrs over {days}d"]
            if t.get("target_desc"): lines.append(f"   GOAL   : {t['target_desc']}")
            if t.get("notes"):       lines.append(f"   NOTES  : {t['notes']}")
            lines.append("")
        lines += ["-" * 58,
                  "Worker Signature : ___________________________",
                  "Supervisor Sign  : ___________________________",
                  "Date             : ________________", "=" * 58]
        return "\n".join(lines)

    def render_slip_card(slip, period_label, card_key):
        # FIX 3: card_key already sanitised by caller
        try:
            tasks = json.loads(slip["slip_data"]) \
                    if isinstance(slip["slip_data"], str) else (slip["slip_data"] or [])
        except Exception:
            tasks = []
        ack = slip.get("acknowledged", False)
        with st.container(border=True):
            h1, h2, h3, h4 = st.columns([3, 2, 1, 1])
            h1.markdown(f"**{slip['worker_name']}** &nbsp;·&nbsp; `{slip['job_no']}`  \n"
                        f"<small>{period_label}</small>", unsafe_allow_html=True)
            h2.caption(f"Issued: {slip.get('generated_by') or '—'}  \n"
                       f"{'✅ Acknowledged' if ack else '⏳ Pending'}")
            if not ack:
                if h3.button("✅ Ack", key=f"ack_{card_key}"):
                    db_update("weekly_slips", {"acknowledged": True}, "id", int(slip["id"])); st.rerun()
            # Delete with two-click confirmation via session state
            confirm_key = f"confirm_del_{card_key}"
            if st.session_state.get(confirm_key):
                if h4.button("⚠️ Confirm", key=f"cfm_{card_key}", type="primary",
                             help="Click again to permanently delete this slip"):
                    db_delete("weekly_slips", "id", int(slip["id"]))
                    st.session_state.pop(confirm_key, None)
                    st.toast(f"Deleted slip for {slip['worker_name']}")
                    st.rerun()
            else:
                if h4.button("🗑️ Del", key=f"del_{card_key}",
                             help="Delete this slip"):
                    st.session_state[confirm_key] = True
                    st.rerun()
            if tasks:
                rows = [{"Task": t.get("task_name","—"), "Hrs/Day": t.get("target_hrs",8),
                         "Days": t.get("target_days",6),
                         "Total Hrs": f"{t.get('target_hrs',8)*t.get('target_days',6):.0f}",
                         "Goal": t.get("target_desc") or "—", "Notes": t.get("notes") or "—"}
                        for t in tasks]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            txt = build_slip_text(slip, tasks, period_label)
            st.download_button("🖨️ Download", txt.encode(),
                               f"Slip_{slip['worker_name'].replace(' ','_')}_{card_key}.txt",
                               key=f"dlslip_{card_key}")

    # ════════════════════════
    # SECTION A — PENDING ISSUANCE  (auto-derived from task_assignments)
    # ════════════════════════
    st.markdown("#### 📋 Pending Issuance")
    st.caption(
        "Slips are auto-derived from task assignments (set in the **Manpower** tab). "
        "Pick a period, review the cards, and click **📋 Issue** to record the slip "
        "and mark it ready to print."
    )

    pi1, pi2, pi3, pi4 = st.columns([2, 2, 2, 2])
    pi_period = pi1.selectbox(
        "Period type",
        ["Weekly (Mon–Sat)", "Daily", "Custom range"],
        key="pi_period",
    )
    if pi_period == "Daily":
        pi_from = pi2.date_input("Date", value=TODAY, key="pi_date")
        pi_to   = pi_from
    elif pi_period == "Custom range":
        cr      = pi2.date_input("From – To",
                                  value=[TODAY, TODAY + timedelta(days=6)],
                                  key="pi_custom")
        pi_from = cr[0] if len(cr) > 0 else TODAY
        pi_to   = cr[1] if len(cr) > 1 else TODAY
    else:  # Weekly
        raw_w   = pi2.date_input("Week starting", value=week_monday(), key="pi_week")
        pi_from = week_monday(raw_w)
        pi_to   = pi_from + timedelta(days=5)

    pi_job_filter    = pi3.selectbox("Job", ["All Jobs"] + all_jobs, key="pi_job")
    pi_worker_filter = pi4.selectbox("Worker", ["All Workers"] + all_workers, key="pi_worker")
    pi_issued_by     = st.text_input("Issued by (supervisor)", key="pi_issued_by")

    pi_days = (pi_to - pi_from).days + 1
    period_str_pi = (
        fmt(pi_from, "%d-%b-%Y") if pi_from == pi_to
        else f"{fmt(pi_from, '%d-%b')} – {fmt(pi_to, '%d-%b-%Y')}"
    )
    week_key_pi = str(pi_from)

    # Build sub_task_id -> task info lookup
    sub_info = {}
    if not df_sub.empty:
        for _, sr in df_sub.iterrows():
            sid = int(sr["id"]) if pd.notna(sr["id"]) else None
            if sid is None: continue
            sub_info[sid] = {
                "name": str(sr.get("name", "")),
                "job_no": str(sr.get("job_no", "")),
                "planned_start": safe_date(sr.get("planned_start")),
                "planned_end":   safe_date(sr.get("planned_end")),
                "notes": str(sr.get("notes", "") or ""),
            }

    # Aggregate active assignments by (worker, job) for the selected period.
    # An assignment is considered active in the period if either:
    #   (a) its stored week_start_date's 7-day window overlaps [pi_from, pi_to], OR
    #   (b) the underlying sub_task's planned_start..planned_end overlaps [pi_from, pi_to]
    pending_buckets = {}   # (worker, job) -> list of task dicts
    if not df_asgn.empty:
        for _, ar in df_asgn.iterrows():
            sid = int(ar["sub_task_id"]) if pd.notna(ar["sub_task_id"]) else None
            if sid is None: continue
            wname = str(ar["worker_name"])
            jno   = str(ar["job_no"])

            if pi_job_filter    != "All Jobs"    and jno   != pi_job_filter:    continue
            if pi_worker_filter != "All Workers" and wname != pi_worker_filter: continue

            asgn_wsd = safe_date(ar.get("week_start_date"))
            in_period = False
            if asgn_wsd is not None:
                if asgn_wsd <= pi_to and (asgn_wsd + timedelta(days=6)) >= pi_from:
                    in_period = True
            si = sub_info.get(sid)
            if not in_period and si and si["planned_start"] and si["planned_end"]:
                if si["planned_start"] <= pi_to and si["planned_end"] >= pi_from:
                    in_period = True
            if not in_period:
                continue

            task_name = si["name"] if si else f"(sub_task {sid})"
            ps  = si["planned_start"] if si else None
            pe  = si["planned_end"]   if si else None
            note = si["notes"] if si else ""

            bucket = pending_buckets.setdefault((wname, jno), [])
            bucket.append({
                "sub_task_id": sid,
                "task_name": task_name,
                "target_hrs": float(ar["allocated_hrs_day"]),
                "target_days": pi_days,
                "target_desc": str(ar.get("target_description") or ""),
                "notes": note,
                "planned_start": ps,
                "planned_end":   pe,
                "asgn_id": int(ar["id"]),
            })

    # Detect whether each (worker, job, period) already has a slip on record
    issued_keys = set()
    if not df_slips.empty:
        for _, sl in df_slips.iterrows():
            sl_wsd = safe_date(sl.get("week_start_date"))
            if sl_wsd is None: continue
            # match if slip's week_start_date equals our period start
            if sl_wsd == pi_from:
                issued_keys.add((str(sl["worker_name"]), str(sl["job_no"])))

    if not pending_buckets:
        st.info(
            "No pending assignments for this period. "
            "Either nothing is assigned, or all assignments fall outside "
            f"**{period_str_pi}**. Assign workers in the Manpower tab first."
        )
    else:
        not_yet_issued = {k: v for k, v in pending_buckets.items() if k not in issued_keys}
        already_issued = {k: v for k, v in pending_buckets.items() if k in issued_keys}

        if not_yet_issued:
            st.markdown(f"**{len(not_yet_issued)} pending — not yet issued for {period_str_pi}:**")

            # Bulk-issue button
            if st.button(
                f"📋 Issue all {len(not_yet_issued)} pending slip(s)",
                type="primary", key="pi_bulk_issue",
                help="One slip per (worker, job) is recorded. Snapshot is taken now; later changes "
                     "to assignments don't alter issued slips."
            ):
                created = 0
                for (wname, jno), tasks in not_yet_issued.items():
                    items = [{
                        "sub_task_id": t["sub_task_id"],
                        "task_name": t["task_name"],
                        "target_hrs": t["target_hrs"],
                        "target_days": t["target_days"],
                        "target_desc": t["target_desc"],
                        "notes": t["notes"],
                    } for t in tasks]
                    db_insert("weekly_slips", {
                        "worker_name": wname, "job_no": jno,
                        "week_start_date": week_key_pi,
                        "slip_data": json.dumps(items),
                        "generated_by": pi_issued_by, "acknowledged": False,
                        "created_at": NOW_IST(),
                    })
                    created += 1
                st.success(f"✅ Issued {created} slip(s) for {period_str_pi}.")
                st.rerun()

            # Per-card preview
            for (wname, jno), tasks in sorted(not_yet_issued.items()):
                with st.container(border=True):
                    hc1, hc2 = st.columns([5, 1])
                    total_hrs_day = sum(t["target_hrs"] for t in tasks)
                    hc1.markdown(
                        f"**{wname}** &nbsp;·&nbsp; `{jno}` &nbsp;·&nbsp; "
                        f"{len(tasks)} task(s) &nbsp;·&nbsp; "
                        f"**{total_hrs_day:.1f} hrs/day** total  \n"
                        f"<small>{period_str_pi}</small>",
                        unsafe_allow_html=True,
                    )
                    issue_key = f"pi_issue_{wname}_{jno}".replace(" ", "_")
                    if hc2.button("📋 Issue", key=issue_key, use_container_width=True):
                        items = [{
                            "sub_task_id": t["sub_task_id"],
                            "task_name": t["task_name"],
                            "target_hrs": t["target_hrs"],
                            "target_days": t["target_days"],
                            "target_desc": t["target_desc"],
                            "notes": t["notes"],
                        } for t in tasks]
                        db_insert("weekly_slips", {
                            "worker_name": wname, "job_no": jno,
                            "week_start_date": week_key_pi,
                            "slip_data": json.dumps(items),
                            "generated_by": pi_issued_by, "acknowledged": False,
                            "created_at": NOW_IST(),
                        })
                        st.toast(f"Issued slip for {wname}")
                        st.rerun()

                    rows = [{
                        "Task": t["task_name"],
                        "Window": (f"{fmt(t['planned_start'], '%d-%b')} → "
                                   f"{fmt(t['planned_end'], '%d-%b')}"
                                   if t["planned_start"] and t["planned_end"] else "—"),
                        "Hrs/Day": t["target_hrs"],
                        "Days": t["target_days"],
                        "Total Hrs": f"{t['target_hrs']*t['target_days']:.0f}",
                        "Goal": t["target_desc"] or "—",
                    } for t in tasks]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if already_issued:
            with st.expander(
                f"✅ {len(already_issued)} (worker, job) pair(s) already have a slip "
                f"for {period_str_pi}",
                expanded=False,
            ):
                for (wname, jno), _ in sorted(already_issued.items()):
                    st.caption(f"• **{wname}** · `{jno}` — already issued; see View section below.")


    st.divider()

    # ════════════════════════
    # SECTION B — VIEW
    # ════════════════════════
    st.markdown("#### View & Download Slips")

    vf1, vf2, vf3, vf4 = st.columns([2, 2, 2, 2])
    view_mode   = vf1.selectbox("View by",
                                ["This Week","Today","This Month","Custom Range","All Time"],
                                key="slip_view_mode")
    view_job    = vf2.selectbox("Job",    ["All Jobs"]    + all_jobs,    key="slip_view_job")
    view_worker = vf3.selectbox("Worker", ["All Workers"] + all_workers, key="slip_view_worker")
    view_ack    = vf4.selectbox("Status", ["All","Pending only","Acknowledged only"],
                                key="slip_view_ack")

    if view_mode == "Today":
        v_from, v_to = TODAY, TODAY
    elif view_mode == "This Week":
        v_from = week_monday(); v_to = v_from + timedelta(days=6)
    elif view_mode == "This Month":
        v_from = TODAY.replace(day=1); v_to = TODAY
    elif view_mode == "Custom Range":
        cr     = st.date_input("Date range", [TODAY - timedelta(days=30), TODAY], key="slip_cr")
        v_from = cr[0] if len(cr) > 0 else TODAY - timedelta(days=30)
        v_to   = cr[1] if len(cr) > 1 else TODAY
    else:
        v_from = date(2000, 1, 1); v_to = date(2099, 12, 31)

    view_df = df_slips.copy() if not df_slips.empty else pd.DataFrame()
    if not view_df.empty:
        # FIX 4: safe parse of stored date (daily slips store plain dates, not Mondays)
        view_df["_wsd"] = pd.to_datetime(view_df["week_start_date"], errors="coerce").dt.date
        view_df = view_df[view_df["_wsd"].notna()]
        view_df = view_df[(view_df["_wsd"] >= v_from) & (view_df["_wsd"] <= v_to)]
        if view_job    != "All Jobs":    view_df = view_df[view_df["job_no"]     == view_job]
        if view_worker != "All Workers": view_df = view_df[view_df["worker_name"] == view_worker]

        # FIX 6: acknowledged may be None from Supabase — use fillna before bool comparison
        view_df["acknowledged"] = view_df["acknowledged"].fillna(False).astype(bool)
        if view_ack == "Pending only":
            view_df = view_df[~view_df["acknowledged"]]
        elif view_ack == "Acknowledged only":
            view_df = view_df[view_df["acknowledged"]]

    if view_df.empty:
        st.info("No slips match the selected filters.")
    else:
        total = len(view_df)
        acked = int(view_df["acknowledged"].sum())
        sv1, sv2, sv3 = st.columns(3)
        sv1.metric("Total Slips",  total)
        sv2.metric("Acknowledged", acked)
        sv3.metric("Pending",      total - acked)

        all_lines = []
        for _, slip in view_df.iterrows():
            try:
                tasks = json.loads(slip["slip_data"]) \
                        if isinstance(slip["slip_data"], str) else (slip["slip_data"] or [])
            except Exception:
                tasks = []
            wsd = safe_date(slip.get("week_start_date"))
            pl  = fmt(wsd, "%d-%b-%Y") if wsd else "—"
            all_lines.append(build_slip_text(slip, tasks, pl))
            all_lines.append("\n\n")

        bulk_c1, bulk_c2 = st.columns(2)
        bulk_c1.download_button(
            f"📦 Download All {total} Slip(s) as One File",
            "\n".join(all_lines).encode(),
            f"Slips_{view_mode.replace(' ','_')}_{view_job}.txt",
            key="bulk_download",
            use_container_width=True,
        )
        # Bulk delete with two-click confirmation
        bulk_confirm_key = "bulk_del_confirm"
        if st.session_state.get(bulk_confirm_key):
            if bulk_c2.button(
                f"⚠️ CONFIRM — Delete all {total} filtered slip(s)?",
                key="bulk_del_cfm", type="primary", use_container_width=True,
                help="This permanently deletes every slip currently shown below"
            ):
                deleted = 0
                for _, sd in view_df.iterrows():
                    db_delete("weekly_slips", "id", int(sd["id"]))
                    deleted += 1
                st.session_state.pop(bulk_confirm_key, None)
                st.toast(f"Deleted {deleted} slip(s)")
                st.rerun()
            if bulk_c2.button("Cancel", key="bulk_del_cancel", use_container_width=True):
                st.session_state.pop(bulk_confirm_key, None)
                st.rerun()
        else:
            if bulk_c2.button(
                f"🗑️ Delete All {total} Filtered Slip(s)",
                key="bulk_del_btn", use_container_width=True,
                help="Permanently delete every slip currently shown — use the filters above to narrow first"
            ):
                st.session_state[bulk_confirm_key] = True
                st.rerun()
        st.divider()

        if view_job == "All Jobs":
            for job_grp, grp_df in view_df.groupby("job_no"):
                st.markdown(f"##### 🏗️ Job: `{job_grp}` — {len(grp_df)} slip(s)")
                for _, slip in grp_df.iterrows():
                    wsd      = safe_date(slip.get("week_start_date"))
                    # FIX 3: sanitise card_key
                    card_key = f"{int(slip['id'])}_{str(slip['worker_name']).replace(' ','_')}"
                    render_slip_card(slip, fmt(wsd, "%d-%b-%Y") if wsd else "—", card_key)
        else:
            for _, slip in view_df.iterrows():
                wsd      = safe_date(slip.get("week_start_date"))
                card_key = f"{int(slip['id'])}_{str(slip['worker_name']).replace(' ','_')}"
                render_slip_card(slip, fmt(wsd, "%d-%b-%Y") if wsd else "—", card_key)


# ══════════════════════════════════════════════
# TAB 5 — DAILY LOGS
# ══════════════════════════════════════════════
with tab_logs:
    st.subheader("📝 Daily Production Log")
    lg_job = st.selectbox("Job", ["-- Select --"] + all_jobs, key="lg_job")

    if lg_job != "-- Select --":
        lg_subs = df_sub[df_sub["job_no"] == lg_job] if not df_sub.empty else pd.DataFrame()
        active  = lg_subs[lg_subs["status"] == "Active"] if not lg_subs.empty else pd.DataFrame()
        fsubs   = active if not active.empty else lg_subs

        if not fsubs.empty:
            sopts = {int(r["id"]): r["name"] for _, r in fsubs.iterrows()}

            # FIX 5: sub-task and worker pickers OUTSIDE the form so prefill is not stale
            lf1, lf2, lf3 = st.columns(3)
            lg_sub    = lf1.selectbox("Sub Task", list(sopts.keys()),
                                      format_func=lambda x: sopts.get(x, str(x)),
                                      key="lg_sub_sel")
            lg_worker = lf2.selectbox("Worker", all_workers, key="lg_worker_sel")
            lg_date   = lf3.date_input("Date", value=TODAY, key="lg_date_sel")

            # FIX 5: prefill computed OUTSIDE form — reactive to sub/worker changes
            if not df_asgn.empty:
                prefill     = df_asgn[(df_asgn["sub_task_id"] == lg_sub) &
                                      (df_asgn["worker_name"] == lg_worker)]
                default_hrs = float(prefill.iloc[0]["allocated_hrs_day"]) \
                              if not prefill.empty else 8.0
            else:
                default_hrs = 8.0

            with st.form("daily_log", clear_on_submit=True):
                lf4, lf5, lf6 = st.columns(3)
                lg_hrs  = lf4.number_input(
                    f"Hours worked (default: {default_hrs}h from assignment)",
                    min_value=0.0, step=0.5, value=default_hrs,
                    help="Log only THIS worker's hours.")
                lg_out  = lf5.number_input("Output Qty", min_value=0.0, step=0.1)
                lg_unit = lf6.selectbox("Unit", UNITS)
                lg_note = st.text_input("Remarks")
                if st.form_submit_button("Log Entry"):
                    db_insert("daily_logs", {
                        "sub_task_id": int(lg_sub), "job_no": lg_job,
                        "worker_name": lg_worker, "log_date": str(lg_date),
                        "hours_worked": float(lg_hrs), "output_qty": float(lg_out),
                        "output_unit": lg_unit, "notes": lg_note, "created_at": NOW_IST(),
                    })
                    st.success("Logged."); st.rerun()
        else:
            st.warning("No sub tasks.")

    if not df_logs.empty:
        show_logs = df_logs[df_logs["job_no"] == lg_job].copy() \
                    if lg_job != "-- Select --" else df_logs.copy()
        show_logs["log_date"] = pd.to_datetime(show_logs["log_date"]).dt.date
        st.dataframe(show_logs[["log_date","job_no","worker_name","hours_worked",
                                 "output_qty","output_unit","notes"]].head(30),
                     use_container_width=True, hide_index=True)
        st.download_button("📥 Export", to_csv(show_logs),
                           f"logs_{lg_job if lg_job != '-- Select --' else 'all'}.csv")


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
        period  = st.selectbox("Period", ["Last 7 Days","Last 30 Days","Current Month","All Time"])
        d_from  = {"Last 7 Days":   TODAY - timedelta(days=7),
                   "Last 30 Days":  TODAY - timedelta(days=30),
                   "Current Month": TODAY.replace(day=1),
                   "All Time":      date(2000, 1, 1)}[period]

        rdf = adf[(adf["log_date"] >= d_from) &
                  (adf["job_no"].isin(an_job)) &
                  (adf["worker_name"].isin(an_wrkr))]

        if rdf.empty:
            st.warning("No data for selection.")
        else:
            k1, k2, k3, k4 = st.columns(4)
            th = rdf["hours_worked"].sum(); to_ = rdf["output_qty"].sum()
            k1.metric("Man-Hours",      f"{th:.1f}")
            k2.metric("Total Output",   f"{to_:.0f}")
            k3.metric("Productivity",   f"{(to_/th if th else 0):.2f} U/Hr")
            k4.metric("Active Workers", rdf["worker_name"].nunique())

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### By Worker")
                ws = rdf.groupby("worker_name")[["hours_worked","output_qty"]].sum().reset_index()
                ws["U/Hr"] = (ws["output_qty"] / ws["hours_worked"].replace(0, np.nan)).round(2).fillna(0)
                st.dataframe(ws.rename(columns={"worker_name":"Worker","hours_worked":"Hrs","output_qty":"Output"}),
                             use_container_width=True, hide_index=True)
                st.download_button("📥", to_csv(ws), "worker_analytics.csv")
            with c2:
                st.markdown("#### By Job")
                js = rdf.groupby("job_no")[["hours_worked","output_qty"]].sum().reset_index()
                st.dataframe(js.rename(columns={"job_no":"Job","hours_worked":"Hrs","output_qty":"Output"}),
                             use_container_width=True, hide_index=True)
                st.download_button("📥", to_csv(js), "job_analytics.csv")

            if not df_sub.empty:
                st.markdown("#### Schedule Compliance")
                comp = df_sub[df_sub["job_no"].isin(an_job)].copy()
                comp["p_end"] = pd.to_datetime(comp["planned_end"]).dt.date
                comp["a_end"] = pd.to_datetime(comp["actual_end"]).dt.date
                comp["delay"] = comp.apply(
                    lambda r: (r["a_end"] - r["p_end"]).days
                              if pd.notna(r.get("actual_end")) and pd.notna(r.get("planned_end")) else None,
                    axis=1)
                comp["result"] = comp["delay"].apply(
                    lambda x: "✅ On time" if x is not None and x <= 0
                              else ("🔴 Late" if x is not None else "⏳ Ongoing"))
                st.dataframe(
                    comp[["job_no","name","p_end","a_end","delay","result","status"]].rename(columns={
                        "job_no":"Job","name":"Sub Task","p_end":"Planned End",
                        "a_end":"Actual End","delay":"Delay (d)","result":"Result","status":"Status"}),
                    use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════
# TAB 7 — MASTER
# ══════════════════════════════════════════════
with tab_master:
    st.subheader("⚙️ Master Settings")
    st.info("Worker dropdowns across the app pull from the **master_workers** table. "
            "Add workers there first, then register them in the pool below for load analysis.", icon="ℹ️")

    m1, m2 = st.columns(2)
    with m1:
        st.markdown("#### Register Worker in Manpower Pool")
        st.caption("Sets capacity, type, and availability for load analysis.")
        with st.form("add_worker", clear_on_submit=True):
            w1, w2  = st.columns(2)
            w_name  = w1.selectbox("Worker (from master)", all_workers, key="pool_wname")
            w_type  = w2.selectbox("Type", WORKER_TYPES)
            w3, w4  = st.columns(2)
            w_trade = w3.selectbox("Trade", TRADES)
            w_cap   = w4.number_input("Daily Capacity (hrs)", value=8.0, step=0.5)
            w5, w6  = st.columns(2)
            w_from  = w5.date_input("Available From", value=TODAY)
            w_to    = w6.date_input("Available To",   value=TODAY + timedelta(days=180))
            w_rate  = st.number_input("Daily Rate (₹)", min_value=0.0, step=100.0)
            if st.form_submit_button("Register in Pool") and w_name:
                db_insert("manpower_pool", {
                    "worker_name": w_name, "worker_type": w_type, "trade": w_trade,
                    "daily_cap_hrs": float(w_cap), "available_from": str(w_from),
                    "available_to": str(w_to),
                    "daily_rate": float(w_rate) if w_rate else None,
                    "active": True, "created_at": NOW_IST(),
                })
                st.success(f"Registered {w_name}."); st.rerun()

    with m2:
        st.markdown("#### Manpower Pool")
        if not df_pool.empty:
            st.dataframe(df_pool[["worker_name","worker_type","trade","daily_cap_hrs","active"]],
                         use_container_width=True, hide_index=True)
            t_name = st.selectbox("Toggle active for:", df_pool["worker_name"].tolist())
            if st.button("Toggle Active"):
                cur = bool(df_pool[df_pool["worker_name"] == t_name]["active"].iloc[0])
                db_update("manpower_pool", {"active": not cur}, "worker_name", t_name); st.rerun()
        else:
            st.info("No workers registered yet.")
