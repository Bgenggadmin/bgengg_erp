"""
B&G Production Scheduler ERP — v3
Enhancements over v2:
  ✅ Worker dropdowns from master_workers table (same as old app)
  ✅ Clone schedule from any job → enter new start date → auto-schedule (editable before save)
  ✅ Over/under allotment shown inline on every sub-task card
  ✅ Inline edit for main task name, description, dates
  ✅ Inline edit for sub-task name, duration, workers/day, man-hrs
  ✅ Automatic revision log entry whenever planned dates change
  ✅ Cascade reschedule: postponing a task shifts all dependent tasks automatically
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
    """Insert a revision record and return the new revision number."""
    rev_no = len(existing_revs_df[existing_revs_df["sub_task_id"] == sub_task_id]) + 1 \
             if not existing_revs_df.empty else 1
    impact = (new_end - old_end).days if old_end and new_end else 0
    db_insert("schedule_revisions", {
        "job_no":       job_no,
        "sub_task_id":  sub_task_id,
        "revision_no":  rev_no,
        "reason":       reason,
        "revised_by":   revised_by or "System",
        "old_start":    str(old_start) if old_start else None,
        "old_end":      str(old_end)   if old_end   else None,
        "new_start":    str(new_start),
        "new_end":      str(new_end),
        "impact_days":  impact,
        "created_at":   NOW_IST(),
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
all_workers = sorted(list(set(master.get("workers", []))))   # ← from master_workers
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
# AUTO-SCHEDULE (clone logic)
# ─────────────────────────────────────────────
def auto_schedule_from(source_subs: pd.DataFrame, new_start: date) -> pd.DataFrame:
    """
    Given a set of sub_tasks from a template job, compute new planned_start / planned_end
    starting from new_start, respecting sub_order sequence and duration_days.
    Returns a DataFrame with new planned_start / planned_end columns (as date objects).
    """
    if source_subs.empty:
        return source_subs

    df = source_subs.copy().sort_values("sub_order").reset_index(drop=True)
    df["duration_days"] = pd.to_numeric(df["duration_days"], errors="coerce").fillna(1).astype(int)

    # Simple sequential scheduling: each task starts after the previous one ends
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
def manpower_load(asgn_df: pd.DataFrame, pool_df: pd.DataFrame, week: date) -> pd.DataFrame:
    if asgn_df.empty:
        return pd.DataFrame()
    wa = asgn_df.copy()
    wa["week_start_date"] = pd.to_datetime(wa["week_start_date"]).dt.date
    week_asgn = wa[wa["week_start_date"] == week]
    if week_asgn.empty:
        return pd.DataFrame()
    worker_hrs = week_asgn.groupby("worker_name")["allocated_hrs_day"].sum().reset_index()
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
# ALLOTMENT STATUS for a single sub-task
# ─────────────────────────────────────────────
def allotment_badge(sub_row, asgn_df: pd.DataFrame) -> str:
    """
    Returns an emoji+text badge showing if this sub-task has enough man-hours allotted.
    Required = manpower_required × man_hours_per_day × duration_days
    Allotted  = sum of allocated_hrs_day × duration for all assignments to this sub-task
    """
    sub_id      = int(sub_row["id"])
    req_workers = int(sub_row.get("manpower_required", 1) or 1)
    mh_per_day  = float(sub_row.get("man_hours_per_day", 8) or 8)
    duration    = int(sub_row.get("duration_days", 1) or 1)
    required_mh = req_workers * mh_per_day * duration

    if not asgn_df.empty:
        task_asgn = asgn_df[asgn_df["sub_task_id"] == sub_id]
        allotted_workers = task_asgn["worker_name"].nunique()
        allotted_mh      = task_asgn["allocated_hrs_day"].sum() * duration
    else:
        allotted_workers = 0
        allotted_mh      = 0

    if allotted_workers == 0:
        badge = "❌ No allotment"
    elif allotted_mh >= required_mh:
        if allotted_mh > required_mh * 1.2:
            badge = f"⚠️ Over ({allotted_mh:.0f}/{required_mh:.0f}h)"
        else:
            badge = f"✅ OK ({allotted_mh:.0f}/{required_mh:.0f}h)"
    else:
        badge = f"🔻 Under ({allotted_mh:.0f}/{required_mh:.0f}h)"

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
    """
    When a sub-task end date is pushed out, shift all sub-tasks that depend on it
    (directly or transitively) by the same delta. Logs a revision for each shifted task.
    """
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

    # Build dependency map: sub_task_id → list of sub_task_ids that depend on it
    dependents = {}
    for _, row in all_subs_df.iterrows():
        for dep_id in parse_deps(row.get("depends_on")):
            dependents.setdefault(dep_id, []).append(int(row["id"]))

    # BFS from changed_sub_id
    changed_row = all_subs_df[all_subs_df["id"] == changed_sub_id]
    if changed_row.empty:
        return
    old_end = safe_date(changed_row.iloc[0].get("planned_end"))
    if not old_end or new_end <= old_end:
        return  # no cascade needed

    delta = (new_end - old_end).days
    visited = set()
    queue = dependents.get(changed_sub_id, [])[:]

    while queue:
        dep_id = queue.pop(0)
        if dep_id in visited:
            continue
        visited.add(dep_id)

        dep_row = all_subs_df[all_subs_df["id"] == dep_id]
        if dep_row.empty:
            continue
        dr = dep_row.iloc[0]
        old_s = safe_date(dr.get("planned_start"))
        old_e = safe_date(dr.get("planned_end"))
        if not old_s or not old_e:
            continue

        new_s = old_s + timedelta(days=delta)
        new_e = old_e + timedelta(days=delta)

        db_update("sub_tasks", {
            "planned_start": str(new_s),
            "planned_end":   str(new_e),
        }, "id", dep_id)

        log_revision(job_no, dep_id, old_s, old_e, new_s, new_e,
                     f"[Auto-cascade] {reason}", revised_by, rev_df)

        queue += dependents.get(dep_id, [])


# ══════════════════════════════════════════════
# NAVIGATION
# ══════════════════════════════════════════════
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

    alerts_all = get_alerts(df_sub)
    if alerts_all:
        with st.expander(f"⚠️ {len(alerts_all)} Alert(s) across all jobs", expanded=True):
            for a in alerts_all[:15]:
                st.markdown(f"**{a['type']}** · `{a['job']}` · {a['task']} — {a['msg']}")

    job = st.selectbox("Select Job", ["-- Select --"] + all_jobs, key="sch_job")
    if job == "-- Select --":
        st.info("Select a job to manage its schedule.")
        st.stop()

    # Project header
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

    # ── WBS data for this job ──
    job_main = df_main[df_main["job_no"] == job].sort_values("task_order") \
               if not df_main.empty else pd.DataFrame()
    job_sub  = df_sub[df_sub["job_no"] == job].sort_values("sub_order") \
               if not df_sub.empty else pd.DataFrame()
    if not job_sub.empty:
        job_sub = compute_cpm(job_sub)

    # ─────────────────────────────────────────
    # CLONE SCHEDULE FROM ANOTHER JOB
    # ─────────────────────────────────────────
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

                    # Auto-schedule preview
                    preview_rows = []
                    cursor = new_start
                    for _, sm in src_main.iterrows():
                        sm_id    = int(sm["id"])
                        sm_subs  = src_sub[src_sub["main_task_id"] == sm_id]
                        sched_subs = auto_schedule_from(sm_subs, cursor)
                        for _, ss in sched_subs.iterrows():
                            preview_rows.append({
                                "Main Task":    sm["name"],
                                "Sub Task":     ss["name"],
                                "Duration (d)": int(ss.get("duration_days", 1)),
                                "Start":        ss["planned_start"],
                                "End":          ss["planned_end"],
                                "Workers/day":  int(ss.get("manpower_required", 1)),
                            })
                        if not sched_subs.empty:
                            last_end = sched_subs["planned_end"].max()
                            if isinstance(last_end, date):
                                cursor = last_end + timedelta(days=1)
                            else:
                                cursor = pd.to_datetime(last_end).date() + timedelta(days=1)

                    if preview_rows:
                        st.markdown("#### 📋 Preview — Edit before saving")
                        prev_df = pd.DataFrame(preview_rows)

                        # Editable preview using st.data_editor
                        edited = st.data_editor(
                            prev_df,
                            use_container_width=True,
                            num_rows="fixed",
                            column_config={
                                "Start": st.column_config.DateColumn("Start", format="DD-MMM-YYYY"),
                                "End":   st.column_config.DateColumn("End",   format="DD-MMM-YYYY"),
                                "Duration (d)": st.column_config.NumberColumn("Duration (d)", min_value=1),
                                "Workers/day":  st.column_config.NumberColumn("Workers/day",  min_value=1),
                            },
                            key="clone_editor",
                        )

                        if st.button("🚀 Save Cloned Schedule", type="primary"):
                            saved_mts = {}
                            for _, sm in src_main.sort_values("task_order").iterrows():
                                # Create main task
                                sm_rows = edited[edited["Main Task"] == sm["name"]]
                                mt_start = sm_rows["Start"].min() if not sm_rows.empty else TODAY
                                mt_end   = sm_rows["End"].max()   if not sm_rows.empty else TODAY
                                new_mt   = db_insert("main_tasks", {
                                    "job_no":       job,
                                    "name":         sm["name"],
                                    "description":  sm.get("description", ""),
                                    "task_order":   int(sm.get("task_order", 1)),
                                    "planned_start": str(mt_start),
                                    "planned_end":   str(mt_end),
                                    "status":       "Pending",
                                    "created_at":   NOW_IST(),
                                })
                                new_mt_id = new_mt[0]["id"]
                                saved_mts[int(sm["id"])] = new_mt_id

                                # Create sub tasks for this main task
                                sm_subs = src_sub[src_sub["main_task_id"] == int(sm["id"])]
                                for _, ss in sm_subs.sort_values("sub_order").iterrows():
                                    edit_row = edited[
                                        (edited["Main Task"] == sm["name"]) &
                                        (edited["Sub Task"]  == ss["name"])
                                    ]
                                    if not edit_row.empty:
                                        er = edit_row.iloc[0]
                                        ps = er["Start"] if isinstance(er["Start"], date) else pd.to_datetime(er["Start"]).date()
                                        pe = er["End"]   if isinstance(er["End"],   date) else pd.to_datetime(er["End"]).date()
                                        dur = int(er["Duration (d)"])
                                        mp  = int(er["Workers/day"])
                                    else:
                                        ps, pe, dur, mp = TODAY, TODAY, 1, 1

                                    db_insert("sub_tasks", {
                                        "main_task_id":      new_mt_id,
                                        "job_no":            job,
                                        "name":              ss["name"],
                                        "description":       ss.get("description", ""),
                                        "sub_order":         int(ss.get("sub_order", 1)),
                                        "duration_days":     dur,
                                        "planned_start":     str(ps),
                                        "planned_end":       str(pe),
                                        "manpower_required": mp,
                                        "man_hours_per_day": float(ss.get("man_hours_per_day", 8)),
                                        "outsource_flag":    bool(ss.get("outsource_flag", False)),
                                        "notes":             ss.get("notes", ""),
                                        "status":            "Pending",
                                        "created_at":        NOW_IST(),
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

    # ── WBS Tree ──
    if job_main.empty and not df_main.empty:
        # job_main was populated above or not
        pass

    # Reload fresh after possible clone save
    job_main = df_main[df_main["job_no"] == job].sort_values("task_order") \
               if not df_main.empty else pd.DataFrame()

    if not job_main.empty:
        for _, mt in job_main.iterrows():
            mt_id   = int(mt["id"])
            subs    = job_sub[job_sub["main_task_id"] == mt_id] \
                      if not job_sub.empty else pd.DataFrame()
            mt_icon = STATUS_ICON.get(mt.get("status", "Pending"), "🔵")
            done    = len(subs[subs["status"] == "Completed"]) if not subs.empty else 0
            prog    = f"{done}/{len(subs)}"

            with st.expander(
                f"{mt_icon} **{mt['name']}**  ·  "
                f"{fmt(safe_date(mt.get('planned_start')), '%d-%b')} → "
                f"{fmt(safe_date(mt.get('planned_end')), '%d-%b')}  "
                f"· {prog} done",
                expanded=True,
            ):
                # ── Main Task: inline edit ──
                edit_mt_key = f"edit_mt_{mt_id}"
                if st.session_state.get(edit_mt_key):
                    with st.form(f"edit_mt_form_{mt_id}", clear_on_submit=False):
                        e1, e2 = st.columns([3, 1])
                        new_mt_name  = e1.text_input("Task Name", value=mt["name"])
                        new_mt_order = e2.number_input("Order", value=int(mt.get("task_order", 1)), min_value=1)
                        new_mt_desc  = st.text_input("Description", value=mt.get("description", "") or "")
                        new_mt_dates = st.date_input(
                            "Planned Window",
                            [safe_date(mt.get("planned_start")) or TODAY,
                             safe_date(mt.get("planned_end"))   or TODAY],
                        )
                        new_mt_status = st.selectbox("Status", STATUSES,
                                                     index=STATUSES.index(mt.get("status","Pending"))
                                                           if mt.get("status") in STATUSES else 0)
                        bc1, bc2 = st.columns(2)
                        if bc1.form_submit_button("💾 Save"):
                            db_update("main_tasks", {
                                "name":         new_mt_name,
                                "description":  new_mt_desc,
                                "task_order":   new_mt_order,
                                "planned_start": str(new_mt_dates[0]) if len(new_mt_dates) > 0 else None,
                                "planned_end":   str(new_mt_dates[1]) if len(new_mt_dates) > 1 else None,
                                "status":       new_mt_status,
                            }, "id", mt_id)
                            del st.session_state[edit_mt_key]
                            st.rerun()
                        if bc2.form_submit_button("Cancel"):
                            del st.session_state[edit_mt_key]; st.rerun()
                else:
                    mc1, mc2, mc3, mc4 = st.columns([5, 1, 1, 1])
                    mc1.caption(mt.get("description", "") or "")
                    if mc2.button("✏️ Edit", key=f"mt_edit_btn_{mt_id}"):
                        st.session_state[edit_mt_key] = True; st.rerun()
                    # Status quick-save
                    new_mt_s = mc3.selectbox("", STATUSES,
                                             index=STATUSES.index(mt.get("status","Pending"))
                                                   if mt.get("status") in STATUSES else 0,
                                             key=f"mts_{mt_id}", label_visibility="collapsed")
                    if mc3.button("✓", key=f"mtsv_{mt_id}"):
                        db_update("main_tasks", {"status": new_mt_s}, "id", mt_id); st.rerun()
                    if mc4.button("🗑️ Delete", key=f"mtdl_{mt_id}"):
                        db_delete("main_tasks", "id", mt_id); st.rerun()

                st.markdown("---")

                # ── Add Sub Task ──
                with st.form(f"add_sub_{mt_id}", clear_on_submit=True):
                    st.caption("➕ New Sub Task")
                    f1, f2, f3 = st.columns([3, 1, 1])
                    sn  = f1.text_input("Sub Task Name", key=f"sn_{mt_id}")
                    dur = f2.number_input("Duration (days)", min_value=1, value=3, key=f"dur_{mt_id}")
                    mp  = f3.number_input("Workers/day", min_value=1, value=2, key=f"mp_{mt_id}")
                    f4, f5, f6 = st.columns([2, 1, 2])
                    ps      = f4.date_input("Planned Start", value=TODAY, key=f"ps_{mt_id}")
                    ord_    = f5.number_input("Order", min_value=1, value=len(subs) + 1,
                                              key=f"ord_{mt_id}")
                    mh      = f6.number_input("Man-hrs/person/day", min_value=1.0, value=8.0,
                                              step=0.5, key=f"mh_{mt_id}")
                    dep_opts = {int(r["id"]): r["name"] for _, r in subs.iterrows()} \
                               if not subs.empty else {}
                    deps    = st.multiselect("Depends on", list(dep_opts.keys()),
                                             format_func=lambda x: dep_opts.get(x, str(x)),
                                             key=f"deps_{mt_id}")
                    f7, f8  = st.columns(2)
                    outsrc  = f7.checkbox("Outsource", key=f"out_{mt_id}")
                    vendor  = f8.text_input("Vendor", key=f"vend_{mt_id}")
                    notes   = st.text_input("Notes / Specs", key=f"notes_{mt_id}")

                    if st.form_submit_button("Add Sub Task") and sn:
                        pe = ps + timedelta(days=dur - 1)
                        db_insert("sub_tasks", {
                            "main_task_id":      mt_id, "job_no": job,
                            "name":              sn, "sub_order": ord_,
                            "duration_days":     dur,
                            "planned_start":     ps.isoformat(),
                            "planned_end":       pe.isoformat(),
                            "manpower_required": mp,
                            "man_hours_per_day": float(mh),
                            "depends_on":        deps if deps else None,
                            "outsource_flag":    outsrc,
                            "outsource_vendor":  vendor or None,
                            "notes":             notes or None,
                            "status":            "Pending",
                            "created_at":        NOW_IST(),
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
                                   if pd.notna(sub.get("float_days")) else 0
                        p_start  = safe_date(sub.get("planned_start"))
                        p_end    = safe_date(sub.get("planned_end"))
                        status   = sub.get("status", "Pending")
                        outsrc   = sub.get("outsource_flag", False)

                        # Allotment badge
                        badge, allot_w, allot_mh, req_mh = allotment_badge(sub, df_asgn)

                        crit_tag = " 🔥" if is_crit else ""
                        out_tag  = " 🏭" if outsrc else ""

                        with st.container(border=True):
                            # ── Inline edit mode ──
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
                                    new_ps    = es4.date_input("Planned Start", value=p_start or TODAY)
                                    new_mh    = es5.number_input("Man-hrs/person/day",
                                                                   value=float(sub.get("man_hours_per_day", 8)),
                                                                   min_value=0.5, step=0.5)
                                    new_sord  = es6.number_input("Order",
                                                                   value=int(sub.get("sub_order", 1)),
                                                                   min_value=1)
                                    new_notes  = st.text_input("Notes", value=sub.get("notes", "") or "")
                                    rev_reason = st.text_input(
                                        "Reason for change (required if dates change)")
                                    rev_by     = st.text_input("Changed by")

                                    bc1, bc2 = st.columns(2)
                                    if bc1.form_submit_button("💾 Save"):
                                        new_pe = new_ps + timedelta(days=new_dur - 1)

                                        # Auto-revision: if dates changed, log it
                                        dates_changed = (new_ps != p_start or new_pe != p_end)
                                        if dates_changed:
                                            if not rev_reason:
                                                st.error("Please provide a reason for the date change.")
                                                st.stop()
                                            rev_no = log_revision(
                                                job, sub_id, p_start, p_end,
                                                new_ps, new_pe, rev_reason, rev_by, df_rev)
                                            st.toast(f"Rev #{rev_no} auto-logged.")
                                            # Cascade to dependents
                                            cascade_reschedule(
                                                sub_id, new_pe, df_sub, job,
                                                rev_reason, rev_by, df_rev)

                                        db_update("sub_tasks", {
                                            "name":              new_sname,
                                            "duration_days":     new_dur,
                                            "manpower_required": new_mp,
                                            "man_hours_per_day": float(new_mh),
                                            "planned_start":     str(new_ps),
                                            "planned_end":       str(new_pe),
                                            "sub_order":         new_sord,
                                            "notes":             new_notes,
                                        }, "id", sub_id)
                                        del st.session_state[edit_sub_key]
                                        st.rerun()
                                    if bc2.form_submit_button("Cancel"):
                                        del st.session_state[edit_sub_key]; st.rerun()

                            else:
                                # ── Display mode ──
                                r1, r2, r3, r4, r5 = st.columns([4, 1.5, 1, 1, 1])
                                r1.markdown(
                                    f"{STATUS_ICON.get(status, '🔵')} **{sub['name']}**"
                                    f"{crit_tag}{out_tag}  \n"
                                    f"<small>"
                                    f"{fmt(p_start, '%d-%b')} → {fmt(p_end, '%d-%b')} "
                                    f"| {sub.get('duration_days', 1)}d "
                                    f"| {sub.get('manpower_required', 1)} workers "
                                    f"| Float: {float_d}d "
                                    f"| {badge}"
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
                                    db_update("sub_tasks", upd, "id", sub_id); st.rerun()

                                if r4.button("✏️", key=f"edit_sub_btn_{sub_id}",
                                             use_container_width=True, help="Edit"):
                                    st.session_state[edit_sub_key] = True; st.rerun()

                                if r5.button("🗑️", key=f"del_{sub_id}", use_container_width=True):
                                    db_delete("sub_tasks", "id", sub_id); st.rerun()

                            # ── Revision history ──
                            sub_revs = df_rev[df_rev["sub_task_id"] == sub_id] \
                                       if not df_rev.empty else pd.DataFrame()
                            if not sub_revs.empty:
                                with st.expander(f"📜 {len(sub_revs)} revision(s)"):
                                    for _, rv in sub_revs.iterrows():
                                        imp   = int(rv.get("impact_days", 0))
                                        color = "red" if imp > 0 else "green"
                                        auto  = "[Auto-cascade]" in str(rv.get("reason", ""))
                                        prefix = "🔄 " if auto else ""
                                        st.markdown(
                                            f"{prefix}**Rev #{rv['revision_no']}** · "
                                            f"{rv.get('revised_by', '—')}  \n"
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
            st.warning("No dates set.")
        else:
            win_start = starts.min().date()
            win_end   = ends.max().date()
            weeks = []
            d = win_start - timedelta(days=win_start.weekday())
            while d <= win_end:
                weeks.append(d); d += timedelta(days=7)

            html = (
                "<style>"
                ".gw{overflow-x:auto}"
                ".gt{border-collapse:collapse;font-size:12px;width:100%}"
                ".gt th,.gt td{border:0.5px solid var(--color-border-tertiary);padding:3px 6px;white-space:nowrap}"
                ".gt th{background:var(--color-background-secondary);font-weight:500;text-align:center}"
                ".gt .lbl{text-align:left;min-width:170px;max-width:240px;overflow:hidden;text-overflow:ellipsis}"
                ".bc{border-radius:3px;height:13px;margin:2px 0}"
                ".bc-cr{background:#E24B4A}.bc-ac{background:#378ADD}"
                ".bc-dn{background:#639922}.bc-pe{background:#B4B2A9}.bc-hl{background:#EF9F27}"
                ".mtr td{background:var(--color-background-secondary);font-weight:500}"
                ".tw{background:rgba(239,159,39,0.10)!important}"
                "</style>"
                "<div class='gw'><table class='gt'><thead><tr><th class='lbl'>Task</th>"
            )
            for w in weeks:
                cls = " class='tw'" if w <= TODAY <= w + timedelta(days=6) else ""
                html += f"<th{cls} style='min-width:72px'>{w.strftime('%d %b')}</th>"
            html += "</tr></thead><tbody>"

            for _, mt in g_main.iterrows():
                html += f"<tr class='mtr'><td class='lbl'>&#128230; {mt['name']}</td>"
                html += "<td></td>" * len(weeks)
                html += "</tr>"
                mt_subs = g_sub[g_sub["main_task_id"] == int(mt["id"])]
                for _, sub in mt_subs.iterrows():
                    ps  = safe_date(sub.get("planned_start"))
                    pe  = safe_date(sub.get("planned_end"))
                    st_ = sub.get("status", "Pending")
                    cr  = sub.get("is_critical", False)
                    out = sub.get("outsource_flag", False)
                    icon = STATUS_ICON.get(st_, "")
                    html += (f"<td class='lbl' style='padding-left:18px'>"
                             f"{icon}{sub['name']}"
                             f"{'&#128293;' if cr else ''}{'&#127981;' if out else ''}</td>")
                    for w in weeks:
                        we  = w + timedelta(days=6)
                        twc = " tw" if w <= TODAY <= we else ""
                        if ps and pe and ps <= we and pe >= w:
                            bar = ("bc-cr" if cr and st_ != "Completed"
                                   else "bc-dn" if st_ == "Completed"
                                   else "bc-ac" if st_ == "Active"
                                   else "bc-hl" if st_ in ("On Hold","Blocked")
                                   else "bc-pe")
                            html += f"<td class='{twc}'><div class='bc {bar}'></div></td>"
                        else:
                            html += f"<td class='{twc}'></td>"
                    html += "</tr>"
            html += "</tbody></table></div>"
            html += (
                "<div style='margin-top:8px;font-size:11px;color:var(--color-text-secondary);"
                "display:flex;gap:12px;flex-wrap:wrap'>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#E24B4A;border-radius:2px'></span> Critical</span>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#378ADD;border-radius:2px'></span> Active</span>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#639922;border-radius:2px'></span> Completed</span>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#B4B2A9;border-radius:2px'></span> Pending</span>"
                "<span><span style='display:inline-block;width:12px;height:8px;"
                "background:#EF9F27;border-radius:2px'></span> On Hold/Blocked</span>"
                "</div>"
            )
            st.components.v1.html(html, height=min(100 + len(g_sub) * 28, 650), scrolling=True)

    # Revision log
    job_revs = df_rev[df_rev["job_no"] == g_job] if not df_rev.empty else pd.DataFrame()
    if not job_revs.empty:
        with st.expander(f"📜 Revision Log — {len(job_revs)} entries"):
            disp = job_revs.copy()
            disp["created_at"] = pd.to_datetime(disp["created_at"], utc=True, errors="coerce") \
                                    .dt.tz_convert(IST).dt.strftime("%d-%b %H:%M")
            st.dataframe(
                disp[["revision_no", "sub_task_id", "reason", "revised_by",
                       "old_start", "old_end", "new_start", "new_end",
                       "impact_days", "created_at"]],
                use_container_width=True, hide_index=True)
            st.download_button("📥 Export", to_csv(disp), f"revisions_{g_job}.csv")


# ══════════════════════════════════════════════
# TAB 3 — MANPOWER LOAD
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

    load_df = manpower_load(asgn_src, df_pool, m_week)

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
            load_df.rename(columns={"worker_name": "Worker", "allocated_hrs": "Alloc. Hrs/Day",
                                     "daily_cap_hrs": "Capacity Hrs/Day",
                                     "load_pct": "Load %", "status": "Status"}),
            use_container_width=True, hide_index=True,
        )
        st.download_button("📥 Export Load", to_csv(load_df), f"load_{m_week}.csv")
    else:
        st.info("No assignments for this week.")

    st.divider()
    st.markdown("#### Assign Worker to Sub Task")
    a_job = st.selectbox("Job", ["-- Select --"] + all_jobs, key="asgn_job")
    if a_job != "-- Select --":
        a_subs = df_sub[df_sub["job_no"] == a_job] if not df_sub.empty else pd.DataFrame()
        if not a_subs.empty:
            sub_opts = {int(r["id"]): f"{r['name']} ({r.get('duration_days',1)}d)"
                        for _, r in a_subs.iterrows()}
            with st.form("assign_worker", clear_on_submit=True):
                a1, a2, a3 = st.columns(3)
                a_sub    = a1.selectbox("Sub Task", list(sub_opts.keys()),
                                        format_func=lambda x: sub_opts.get(x, str(x)))
                # ← workers from master_workers
                a_worker = a2.selectbox("Worker", all_workers)
                a_hrs    = a3.number_input("Hrs/Day allotted", min_value=0.5, value=8.0, step=0.5)
                b1, b2   = st.columns(2)
                a_week   = b1.date_input("Week Starting", value=week_monday())
                a_target = b2.text_input("Weekly target / goal")
                if st.form_submit_button("Assign"):
                    db_insert("task_assignments", {
                        "sub_task_id":       a_sub,
                        "job_no":            a_job,
                        "worker_name":       a_worker,
                        "allocated_hrs_day": float(a_hrs),
                        "week_start_date":   str(week_monday(a_week)),
                        "target_description": a_target,
                        "created_at":        NOW_IST(),
                    })
                    st.success(f"Assigned {a_worker}."); st.rerun()
        else:
            st.info("No sub tasks in this job.")

    with st.expander("👤 Manpower Pool"):
        if not df_pool.empty:
            st.dataframe(df_pool[["worker_name", "worker_type", "trade",
                                   "daily_cap_hrs", "active"]],
                         use_container_width=True, hide_index=True)
        else:
            st.info("Add workers in Master tab.")


# ══════════════════════════════════════════════
# TAB 4 — WEEKLY SLIPS
# ══════════════════════════════════════════════
with tab_slips:
    st.subheader("📋 Weekly Work Plan Slips")
    sc1, sc2 = st.columns(2)
    sl_week   = sc1.date_input("Week Starting", value=week_monday(), key="sl_week")
    sl_week   = week_monday(sl_week)
    # ← workers from master_workers
    sl_worker = sc2.selectbox("Worker", ["-- All --"] + all_workers, key="sl_worker")

    with st.expander("➕ Generate Slip", expanded=False):
        with st.form("gen_slip", clear_on_submit=True):
            g1, g2, g3 = st.columns(3)
            gs_worker = g1.selectbox("Worker", all_workers, key="gsw")
            gs_job    = g2.selectbox("Job", all_jobs, key="gsj") if all_jobs else None
            gs_week   = g3.date_input("Week", value=week_monday())
            gs_week   = week_monday(gs_week)
            gs_by     = st.text_input("Issued by (supervisor)")
            gs_subs   = df_sub[df_sub["job_no"] == gs_job] \
                        if gs_job and not df_sub.empty else pd.DataFrame()
            sub_opts2 = {int(r["id"]): r["name"] for _, r in gs_subs.iterrows()}
            gs_tasks  = st.multiselect("Tasks", list(sub_opts2.keys()),
                                       format_func=lambda x: sub_opts2.get(x, str(x)))

            if st.form_submit_button("Generate") and gs_job and gs_tasks:
                items = []
                for tid in gs_tasks:
                    sr = df_sub[df_sub["id"] == tid]
                    if sr.empty: continue
                    sr = sr.iloc[0]
                    ar = df_asgn[
                        (df_asgn["sub_task_id"] == tid) &
                        (df_asgn["worker_name"] == gs_worker) &
                        (pd.to_datetime(df_asgn["week_start_date"]).dt.date == gs_week)
                    ] if not df_asgn.empty else pd.DataFrame()
                    items.append({
                        "sub_task_id": tid, "task_name": sr["name"],
                        "target_hrs":  float(ar.iloc[0]["allocated_hrs_day"])
                                       if not ar.empty else float(sr.get("man_hours_per_day", 8)),
                        "notes":       sr.get("notes", ""),
                        "target_desc": ar.iloc[0]["target_description"] if not ar.empty else "",
                    })
                db_insert("weekly_slips", {
                    "worker_name":     gs_worker, "job_no": gs_job,
                    "week_start_date": str(gs_week),
                    "slip_data":       json.dumps(items),
                    "generated_by":    gs_by, "acknowledged": False,
                    "created_at":      NOW_IST(),
                })
                st.success(f"Slip generated for {gs_worker}."); st.rerun()

    st.divider()
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
                    f"{fmt(slip['week_start_date'], '%d-%b')} – {fmt(wk_end, '%d-%b')}"
                )
                h2.caption(f"Issued by: {slip.get('generated_by','—')}  \n"
                           f"{'✅ Acknowledged' if ack else '⏳ Pending'}")
                if not ack and h3.button("✅ Ack", key=f"ack_{slip['id']}"):
                    db_update("weekly_slips", {"acknowledged": True}, "id", int(slip["id"]))
                    st.rerun()

                if tasks:
                    rows = [{"Task": t.get("task_name", "—"),
                             "Hrs/Day": t.get("target_hrs", 8),
                             "Week Total (6d)": f"{t.get('target_hrs', 8) * 6:.0f} hrs",
                             "Goal": t.get("target_desc", "—"),
                             "Notes": t.get("notes", "—")} for t in tasks]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

                lines = ["=" * 55, "   B&G ENGINEERING — WEEKLY WORK PLAN SLIP", "=" * 55,
                         f"Worker   : {slip['worker_name']}",
                         f"Job No.  : {slip['job_no']}",
                         f"Week     : {fmt(slip['week_start_date'],'%d-%b-%Y')} to {fmt(wk_end,'%d-%b-%Y')}",
                         f"Issued by: {slip.get('generated_by','—')}", "-" * 55]
                for i, t in enumerate(tasks, 1):
                    lines += [f"{i}. TASK   : {t.get('task_name')}",
                              f"   TARGET : {t.get('target_hrs')} hrs/day  |  "
                              f"Week total: {t.get('target_hrs', 8) * 6:.0f} hrs"]
                    if t.get("target_desc"): lines.append(f"   GOAL   : {t.get('target_desc')}")
                    if t.get("notes"):       lines.append(f"   NOTES  : {t.get('notes')}")
                    lines.append("")
                lines += ["-" * 55,
                          "Worker Signature : _________________________",
                          "Supervisor Sign  : _________________________",
                          "Date             : _______________", "=" * 55]
                st.download_button(
                    "🖨️ Download Slip",
                    "\n".join(lines).encode(),
                    f"Slip_{slip['worker_name'].replace(' ','_')}_{slip['week_start_date']}.txt",
                    key=f"dlslip_{slip['id']}",
                )


# ══════════════════════════════════════════════
# TAB 5 — DAILY LOGS
# ══════════════════════════════════════════════
with tab_logs:
    st.subheader("📝 Daily Production Log")
    lg_job = st.selectbox("Job", ["-- Select --"] + all_jobs, key="lg_job")
    if lg_job != "-- Select --":
        lg_subs  = df_sub[df_sub["job_no"] == lg_job] if not df_sub.empty else pd.DataFrame()
        active   = lg_subs[lg_subs["status"] == "Active"] if not lg_subs.empty else pd.DataFrame()
        fsubs    = active if not active.empty else lg_subs
        if not fsubs.empty:
            sopts = {int(r["id"]): r["name"] for _, r in fsubs.iterrows()}
            with st.form("daily_log", clear_on_submit=True):
                l1, l2, l3 = st.columns(3)
                lg_sub    = l1.selectbox("Sub Task", list(sopts.keys()),
                                         format_func=lambda x: sopts.get(x, str(x)))
                # ← workers from master_workers
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
                    st.success("Logged."); st.rerun()
        else:
            st.warning("No sub tasks.")

    if not df_logs.empty:
        show_logs = df_logs[df_logs["job_no"] == lg_job].copy() \
                    if lg_job != "-- Select --" else df_logs.copy()
        show_logs["log_date"] = pd.to_datetime(show_logs["log_date"]).dt.date
        st.dataframe(
            show_logs[["log_date","job_no","worker_name","hours_worked",
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
        period  = st.selectbox("Period",
                               ["Last 7 Days", "Last 30 Days", "Current Month", "All Time"])
        d_from  = {"Last 7 Days":   TODAY - timedelta(days=7),
                   "Last 30 Days":  TODAY - timedelta(days=30),
                   "Current Month": TODAY.replace(day=1),
                   "All Time":      date(2000, 1, 1)}[period]

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
                st.dataframe(ws.rename(columns={"worker_name": "Worker",
                                                  "hours_worked": "Hrs", "output_qty": "Output"}),
                             use_container_width=True, hide_index=True)
                st.download_button("📥", to_csv(ws), "worker_analytics.csv")

            with c2:
                st.markdown("#### By Job")
                js = rdf.groupby("job_no")[["hours_worked","output_qty"]].sum().reset_index()
                st.dataframe(js.rename(columns={"job_no": "Job",
                                                  "hours_worked": "Hrs", "output_qty": "Output"}),
                             use_container_width=True, hide_index=True)
                st.download_button("📥", to_csv(js), "job_analytics.csv")

            # Schedule compliance
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
                        "job_no": "Job", "name": "Sub Task", "p_end": "Planned End",
                        "a_end": "Actual End", "delay": "Delay (d)",
                        "result": "Result", "status": "Status",
                    }),
                    use_container_width=True, hide_index=True,
                )


# ══════════════════════════════════════════════
# TAB 7 — MASTER
# ══════════════════════════════════════════════
with tab_master:
    st.subheader("⚙️ Master Settings")

    st.info(
        "Worker names for dropdowns come from the **master_workers** table "
        "(same as the rest of the ERP). Add workers there to make them available here.",
        icon="ℹ️",
    )

    m1, m2 = st.columns(2)
    with m1:
        st.markdown("#### Register Worker in Manpower Pool")
        st.caption("This sets capacity / availability / type for scheduling load analysis.")
        with st.form("add_worker", clear_on_submit=True):
            w1, w2 = st.columns(2)
            # ← select from master_workers, not free text
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
                    "worker_name":   w_name, "worker_type": w_type,
                    "trade":         w_trade, "daily_cap_hrs": float(w_cap),
                    "available_from": str(w_from), "available_to": str(w_to),
                    "daily_rate":    float(w_rate) if w_rate else None,
                    "active":        True, "created_at": NOW_IST(),
                })
                st.success(f"Registered {w_name}."); st.rerun()

    with m2:
        st.markdown("#### Manpower Pool")
        if not df_pool.empty:
            st.dataframe(df_pool[["worker_name","worker_type","trade",
                                   "daily_cap_hrs","active"]],
                         use_container_width=True, hide_index=True)
            t_name = st.selectbox("Toggle active for:", df_pool["worker_name"].tolist())
            if st.button("Toggle Active"):
                cur = bool(df_pool[df_pool["worker_name"] == t_name]["active"].iloc[0])
                db_update("manpower_pool", {"active": not cur}, "worker_name", t_name); st.rerun()
        else:
            st.info("No workers registered yet.")
