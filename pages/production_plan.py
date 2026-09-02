import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz

# ─────────────────────────────────────────────
# CONSTANTS & CONFIG
# ─────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")
NOW_IST = lambda: datetime.now(IST).isoformat()

st.set_page_config(
    page_title="Production Master ERP | B&G",
    layout="wide",
    page_icon="🏗️",
)

conn = st.connection("supabase", type=SupabaseConnection)

OUTPUT_UNITS = ["Nos", "Mtrs", "Sq.Ft", "Kgs", "Joints"]
PERIOD_OPTIONS = ["Today", "Last 7 Days", "Current Month", "Custom Range"]

# A job is flagged "Due soon" when dispatch is this many days away or less.
DUE_SOON_DAYS = 7

# A worker must log at least this many hours in a day to appear on the
# best/worst leaderboard. Stops a 15-minute entry from topping the chart.
LEADERBOARD_MIN_HOURS = 1.0


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def safe_date(val) -> date | None:
    """Parse a value to date safely, returning None on failure."""
    if pd.isnull(val):
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def fmt_date(d: date | None, fmt="%d-%b-%Y") -> str:
    return d.strftime(fmt) if d else "---"


def days_remaining(target: date | None) -> int | None:
    return (target - date.today()).days if target else None


def to_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


# ─────────────────────────────────────────────
# SESSION STATE — MASTER LISTS
# ─────────────────────────────────────────────
def _load_master_lists() -> dict:
    """Fetch master lists once and cache them in session state."""
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
        st.error(f"Master Sync Error: {e}")
        return {"workers": [], "staff": [], "gates": []}


if "master_data" not in st.session_state or not st.session_state.master_data:
    st.session_state.master_data = _load_master_lists()

master = st.session_state.master_data


# ─────────────────────────────────────────────
# DATA LOADERS — cached per TTL
# ─────────────────────────────────────────────
@st.cache_data(ttl=2)
def load_all_data() -> tuple[pd.DataFrame, ...]:
    """Load all core tables and return as a named tuple of DataFrames."""
    try:
        p  = conn.table("anchor_projects").select(
                "job_no, status, po_no, po_date, po_delivery_date, revised_delivery_date"
             ).eq("status", "Won").execute()
        l  = conn.table("production").select("*").order("created_at", desc=True).execute()
        g  = conn.table("production_gates").select("*").order("step_order").execute()
        jp = conn.table("job_planning").select("*").order("step_order").execute()
        po = conn.table("purchase_orders").select("*").execute()
        wr = conn.table("worker_day_ratings").select("*").order("work_date", desc=True).execute()

        return (
            pd.DataFrame(p.data  or []),
            pd.DataFrame(l.data  or []),
            pd.DataFrame(g.data  or []),
            pd.DataFrame(jp.data or []),
            pd.DataFrame(po.data or []),
            pd.DataFrame(wr.data or []),
        )
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return (pd.DataFrame(),) * 6


(df_projects, df_logs, df_master_gates,
 df_job_plans, df_purchase, df_ratings) = load_all_data()

# Derived lists
all_staff      = master.get("staff", [])
all_workers    = sorted(set(master.get("workers", [])))
all_jobs       = sorted(df_projects["job_no"].astype(str).unique()) if not df_projects.empty else []
all_activities = master.get("gates", [])


# ─────────────────────────────────────────────
# SUPABASE WRITE HELPERS
# ─────────────────────────────────────────────
def db_update(table: str, data: dict, match_col: str, match_val):
    conn.table(table).update(data).eq(match_col, match_val).execute()
    st.cache_data.clear()


def db_insert(table: str, data: dict | list):
    conn.table(table).insert(data).execute()
    st.cache_data.clear()


def db_delete(table: str, match_col: str, match_val):
    conn.table(table).delete().eq(match_col, match_val).execute()
    st.cache_data.clear()


def db_upsert(table: str, data: dict | list, on_conflict: str):
    """
    Insert, or update the existing row when it collides.
    `on_conflict` must name columns covered by a UNIQUE constraint —
    for worker_day_ratings that is "worker,work_date". This is what
    makes re-rating a worker correct their row instead of adding a
    second one for the same day.
    """
    conn.table(table).upsert(data, on_conflict=on_conflict).execute()
    st.cache_data.clear()


# ─────────────────────────────────────────────
# ANALYSIS HELPERS (used by Dashboard + Job Plans)
# ─────────────────────────────────────────────
def classify_step(status, p_start, p_end, a_end, today) -> tuple[int, str]:
    """
    Judge one plan step against its schedule.

    Returns (delay_days, flag_text). delay_days is always >= 0;
    zero means "not late". A step can be late in three different ways:
      - Completed, but finished after its planned end date
      - Active, and today is already past its planned end date
      - Pending, and today is already past its planned start date
    """
    if status == "Completed":
        if a_end and p_end:
            d = (a_end - p_end).days
            return (max(d, 0), "🏁 Done (late)" if d > 0 else "🏁 Done on time")
        return (0, "🏁 Done")

    if status == "Active":
        if p_end and today > p_end:
            return ((today - p_end).days, "🔴 Running late")
        return (0, "🚀 Active")

    # Anything else is treated as Pending / not started
    if p_start and today > p_start:
        return ((today - p_start).days, "🟠 Not started")
    return (0, "⏳ Pending")


def enrich_plan(df_plans: pd.DataFrame) -> pd.DataFrame:
    """
    Take the raw job_planning table and add readable date columns,
    a numeric Delay (Days) and a Schedule Flag for every step.
    This single enriched frame feeds the Dashboard and the Job Plans tab.
    """
    if df_plans.empty:
        return pd.DataFrame()

    d = df_plans.copy()

    # Guard: these columns may not exist on very old rows
    for col in ("actual_start_date", "actual_end_date", "current_status"):
        if col not in d.columns:
            d[col] = None

    d["job_no"] = d["job_no"].astype(str)
    d["Planned Start"] = d["planned_start_date"].apply(safe_date)
    d["Planned End"]   = d["planned_end_date"].apply(safe_date)
    d["Actual Start"]  = d["actual_start_date"].apply(safe_date)
    d["Actual End"]    = d["actual_end_date"].apply(safe_date)

    today = date.today()
    verdicts = [
        classify_step(r["current_status"], r["Planned Start"],
                      r["Planned End"], r["Actual End"], today)
        for _, r in d.iterrows()
    ]
    d["Delay (Days)"]  = [v[0] for v in verdicts]
    d["Schedule Flag"] = [v[1] for v in verdicts]
    return d


def build_dispatch_board(projects: pd.DataFrame, plan: pd.DataFrame) -> pd.DataFrame:
    """
    One row per Won job: committed dispatch date, plan progress,
    worst step delay, and an overall traffic-light status.
    """
    if projects.empty:
        return pd.DataFrame()

    today = date.today()
    rows = []

    for _, p in projects.iterrows():
        job = str(p.get("job_no"))
        po_dt  = safe_date(p.get("po_delivery_date"))
        rev_dt = safe_date(p.get("revised_delivery_date"))
        target = rev_dt or po_dt

        steps = plan[plan["job_no"] == job] if not plan.empty else pd.DataFrame()
        total = len(steps)
        done  = int((steps["current_status"] == "Completed").sum()) if total else 0
        pct   = round(done / total * 100) if total else 0

        max_delay = int(steps["Delay (Days)"].max()) if total else 0
        plan_end  = max([d for d in steps["Planned End"] if d], default=None) if total else None
        days_left = (target - today).days if target else None

        # Does the plan itself already overshoot the commitment?
        gap = (plan_end - target).days if (plan_end and target) else None

        if total == 0:
            flag, rank = "⚪ No plan", 3
        elif pct == 100:
            flag, rank = "✅ Plan complete", 5
        elif target and days_left is not None and days_left < 0:
            flag, rank = "🔴 Overdue", 0
        elif max_delay > 0:
            flag, rank = "🟠 Lagging", 1
        elif days_left is not None and days_left <= DUE_SOON_DAYS:
            flag, rank = "🟡 Due soon", 2
        else:
            flag, rank = "🟢 On track", 4

        rows.append({
            "Status":          flag,
            "Job No":          job,
            "PO No":           p.get("po_no") or "---",
            "Dispatch Target": fmt_date(target),
            # None (not "") keeps this an integer column — mixing int and str
            # here makes Streamlit's Arrow conversion complain.
            "Days Left":       days_left,
            "Plan Ends":       fmt_date(plan_end),
            "Plan vs Target":  f"+{gap}d over" if (gap is not None and gap > 0)
                               else ("OK" if gap is not None else ""),
            "Progress":        f"{done}/{total} ({pct}%)",
            "Worst Delay":     max_delay,
            "_rank":           rank,
            "_days":           days_left if days_left is not None else 9999,
        })

    board = pd.DataFrame(rows).sort_values(["_rank", "_days"])
    return board.reset_index(drop=True)


def latest_log_date(logs: pd.DataFrame) -> date | None:
    """Most recent calendar date (IST) that has any production log."""
    if logs.empty or "created_at" not in logs.columns:
        return None
    dts = pd.to_datetime(logs["created_at"], utc=True, errors="coerce").dropna()
    if dts.empty:
        return None
    return dts.dt.tz_convert(IST).dt.date.max()


def worker_day_board(logs: pd.DataFrame, day: date) -> pd.DataFrame:
    """
    Per-worker summary for a single day: hours, output, jobs touched,
    units used, and output-per-hour.
    """
    if logs.empty or not day:
        return pd.DataFrame()

    d = logs.copy()
    d["dt"] = pd.to_datetime(d["created_at"], utc=True, errors="coerce")
    d = d.dropna(subset=["dt"])
    if d.empty:
        return pd.DataFrame()

    d["date_only"] = d["dt"].dt.tz_convert(IST).dt.date
    d = d[d["date_only"] == day]
    if d.empty:
        return pd.DataFrame()

    d["Hours"]  = pd.to_numeric(d["Hours"],  errors="coerce").fillna(0)
    d["Output"] = pd.to_numeric(d["Output"], errors="coerce").fillna(0)

    grp = d.groupby("Worker").agg(
        Hours=("Hours", "sum"),
        Output=("Output", "sum"),
        Jobs=("Job_Code", lambda s: ", ".join(sorted(set(s.astype(str))))),
        Units=("Unit", lambda s: ", ".join(sorted(set(s.dropna().astype(str))))),
        Entries=("Worker", "size"),
    ).reset_index()

    grp["Output/Hr"] = (
        grp["Output"] / grp["Hours"].replace(0, pd.NA)
    ).astype(float).round(2).fillna(0)

    return grp.sort_values("Output/Hr", ascending=False).reset_index(drop=True)


def ratings_for_day(ratings: pd.DataFrame, day: date) -> pd.DataFrame:
    """Rows from worker_day_ratings for one work_date."""
    if ratings.empty or "work_date" not in ratings.columns or not day:
        return pd.DataFrame()
    r = ratings.copy()
    r["work_date"] = r["work_date"].apply(safe_date)
    return r[r["work_date"] == day]


def attach_ratings(board: pd.DataFrame, ratings: pd.DataFrame, day: date) -> pd.DataFrame:
    """
    Add the supervisor's Rating column to a worker day board.

    A left join is used on purpose: a worker who logged hours but has
    not been rated keeps their row with Rating as NaN. Filling that
    with 0 would make an unrated worker look like a zero-graded one.
    """
    if board.empty:
        return board

    out = board.copy()
    day_r = ratings_for_day(ratings, day)

    if day_r.empty:
        out["Rating"] = pd.NA
        out["Rated By"] = ""
        out["Remarks"] = ""
        return out

    keep = day_r[["worker", "rating", "supervisor", "remarks"]].rename(columns={
        "worker": "Worker", "rating": "Rating",
        "supervisor": "Rated By", "remarks": "Remarks",
    })
    out = out.merge(keep, on="Worker", how="left")
    out["Rated By"] = out["Rated By"].fillna("")
    out["Remarks"]  = out["Remarks"].fillna("")
    return out


enriched_plan = enrich_plan(df_job_plans)
plan_job_list = sorted(enriched_plan["job_no"].unique()) if not enriched_plan.empty else []


# ─────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────
def render_project_header(p_data: pd.Series, target_job: str):
    """Project info card with dates and days-to-dispatch metric."""
    po_num        = p_data.get("po_no") or "---"
    po_placed_dt  = safe_date(p_data.get("po_date"))
    po_disp_dt    = safe_date(p_data.get("po_delivery_date"))
    rev_dt        = safe_date(p_data.get("revised_delivery_date"))
    final_target  = rev_dt or po_disp_dt

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"📄 **PO No: {po_num}**\nDate: {fmt_date(po_placed_dt)}")
        c2.write(f"🚚 **PO Dispatch**\n{fmt_date(po_disp_dt)}")
        c3.write(f"🔴 **Revised Date**\n{fmt_date(rev_dt)}")

        days = days_remaining(final_target)
        if days is not None:
            c4.metric("Days to Dispatch", f"{days} Days", delta=days,
                      delta_color="normal" if days > 7 else "inverse")
        else:
            c4.caption("⏳ No target date set")

        if st.button("📝 Update Schedule", key="edit_delivery"):
            @st.dialog("Update Commitment")
            def _update_dates():
                n_po_disp = st.date_input("Original PO Dispatch Date",
                                          value=po_disp_dt or date.today())
                n_rev     = st.date_input("Revised Delivery Date",
                                          value=rev_dt or n_po_disp)
                if st.button("Save Changes"):
                    db_update("anchor_projects",
                              {"po_delivery_date": str(n_po_disp),
                               "revised_delivery_date": str(n_rev)},
                              "job_no", target_job)
                    st.rerun()
            _update_dates()


def render_purchase_section(target_job: str):
    """Urgent purchase form + material status expanders."""
    with st.expander("🚨 Trigger Urgent Purchase Requisition", expanded=False):
        with st.form("urgent_purchase_form", clear_on_submit=True):
            r1, r2, r3 = st.columns([2, 1, 1])
            it_name  = r1.text_input("Material Item Name")
            it_qty   = r2.text_input("Qty")
            it_date  = r3.date_input("Required By", value=date.today() + timedelta(days=2))
            it_specs = st.text_area("Specs / Reason for Urgency")

            if st.form_submit_button("🔥 Send Urgent Request"):
                if it_name and it_qty:
                    db_insert("purchase_orders", {
                        "job_no":    target_job,
                        "item_name": it_name,
                        "specs":     f"URGENT (By {fmt_date(it_date, '%d-%b')}): {it_specs} (Qty: {it_qty})",
                        "status":    "Triggered",
                        "created_at": NOW_IST(),
                    })
                    st.success("Urgent request sent!")
                    st.rerun()

    with st.expander("🛒 Current Material Status", expanded=False):
        job_po = df_purchase[df_purchase["job_no"] == target_job] if not df_purchase.empty else pd.DataFrame()
        if job_po.empty:
            st.info("No materials tracked.")
        else:
            for _, row in job_po.iterrows():
                c1, c2, c3 = st.columns([2, 2, 1])
                c1.write(f"🔹 **{row['item_name']}**")
                c2.caption(str(row["specs"]))
                (c3.success if row["status"] == "Received" else c3.warning)(row["status"])


def render_gate_step(row: pd.Series, all_activities: list):
    """Single execution step card (Pending / Active / Completed)."""
    p_start = safe_date(row["planned_start_date"])
    p_end   = safe_date(row["planned_end_date"])
    today   = date.today()
    status  = row["current_status"]

    with st.container(border=True):
        col1, col2, col3, col4 = st.columns([2.5, 1, 1, 1])
        with col1:
            st.markdown(f"**Step {row['step_order']}: {row['gate_name']}**")
            if p_start and p_end:
                st.caption(f"🗓️ Planned: {fmt_date(p_start, '%d %b')} — {fmt_date(p_end, '%d %b')}")

        if status == "Pending":
            col2.warning("⏳ Pending")
            if col4.button("▶️ Start", key=f"st_{row['id']}", use_container_width=True):
                db_update("job_planning",
                          {"current_status": "Active", "actual_start_date": NOW_IST()},
                          "id", row["id"])
                st.rerun()

        elif status == "Active":
            col2.info("🚀 Active")
            if p_end:
                diff = (today - p_end).days
                if diff > 0:
                    col3.metric("Delay", f"{diff} Days", delta=f"-{diff}", delta_color="inverse")
                else:
                    col3.success("On Track")
            if col4.button("✅ Close", key=f"cl_{row['id']}", use_container_width=True):
                db_update("job_planning",
                          {"current_status": "Completed", "actual_end_date": NOW_IST()},
                          "id", row["id"])
                st.rerun()

        else:  # Completed
            col2.success("🏁 Completed")
            act_end = safe_date(row.get("actual_end_date"))
            if act_end:
                col3.caption(f"Finished: {fmt_date(act_end, '%d %b')}")


# ─────────────────────────────────────────────
# TAB RENDERERS
# ─────────────────────────────────────────────
def render_dashboard():
    """Landing view: dispatch outlook, lagging jobs, worker leaderboard."""
    st.subheader("🎯 Production Command Dashboard")
    st.caption(f"As on {fmt_date(date.today())} • all dates IST")

    board = build_dispatch_board(df_projects, enriched_plan)

    # ── KPI strip ──
    if board.empty:
        st.info("No 'Won' projects found in anchor_projects.")
    else:
        overdue   = int((board["Status"] == "🔴 Overdue").sum())
        lagging   = int((board["Status"] == "🟠 Lagging").sum())
        due_soon  = int((board["Status"] == "🟡 Due soon").sum())
        no_plan   = int((board["Status"] == "⚪ No plan").sum())

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Live Jobs", len(board))
        k2.metric("🔴 Overdue", overdue)
        k3.metric("🟠 Lagging", lagging)
        k4.metric(f"🟡 Due ≤{DUE_SOON_DAYS}d", due_soon)
        k5.metric("⚪ No Plan", no_plan)

    st.divider()

    # ── Dispatch schedule ──
    st.markdown("#### 🚚 Dispatch Outlook")
    if board.empty:
        st.caption("Nothing to show yet.")
    else:
        show = board.drop(columns=["_rank", "_days"])
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download Dispatch Outlook",
            to_csv(show),
            f"dispatch_outlook_{date.today()}.csv",
            "text/csv",
            key="dl_dispatch_board",
        )

    st.divider()

    # ── Lagging equipment detail ──
    st.markdown("#### ⚠️ Lagging Against Schedule")
    if enriched_plan.empty:
        st.caption("No production plans created yet.")
    else:
        late = enriched_plan[enriched_plan["Delay (Days)"] > 0].copy()
        if late.empty:
            st.success("No step is behind schedule right now.")
        else:
            late_view = late[[
                "job_no", "step_order", "gate_name", "Schedule Flag",
                "Planned Start", "Planned End", "Delay (Days)",
            ]].rename(columns={
                "job_no": "Job No", "step_order": "Step", "gate_name": "Gate",
            }).sort_values("Delay (Days)", ascending=False)

            st.dataframe(late_view, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 Download Lagging Report",
                to_csv(late_view),
                f"lagging_steps_{date.today()}.csv",
                "text/csv",
                key="dl_lagging",
            )

    st.divider()

    # ── Worker leaderboard ──
    st.markdown("#### 👷 Worker Performance — Single Day")
    last_day = latest_log_date(df_logs)

    if not last_day:
        st.info("No production logs recorded yet.")
        return

    pick_day = st.date_input(
        "Day to review",
        # min() guards against a stray future-dated log breaking max_value
        value=min(last_day, date.today()),
        max_value=date.today(),
        key="dash_day",
        help="Defaults to the most recent day that has entries.",
    )

    day_board = worker_day_board(df_logs, pick_day)

    if day_board.empty:
        st.warning(f"No entries logged on {fmt_date(pick_day)}.")
        return

    day_board = attach_ratings(day_board, df_ratings, pick_day)

    rated_count = int(day_board["Rating"].notna().sum())
    total_count = len(day_board)
    st.caption(f"{rated_count} of {total_count} workers rated for {fmt_date(pick_day)}.")

    ranked = day_board[day_board["Hours"] >= LEADERBOARD_MIN_HOURS]
    cols = ["Worker", "Rating", "Output/Hr", "Hours", "Output", "Units", "Jobs"]

    if ranked.empty:
        st.warning(
            f"Entries exist on {fmt_date(pick_day)}, but nobody crossed "
            f"{LEADERBOARD_MIN_HOURS} hrs — too little to rank."
        )

    elif rated_count == 0:
        # No supervisor judgement yet. Output/Hr alone is not a sound basis
        # for naming a worst performer, so show the day without that framing.
        st.info(
            "Not rated yet — showing the day's work without a best/worst "
            "ranking. Rate it in Daily Entry → Morning Rating."
        )
        st.dataframe(
            ranked.sort_values("Hours", ascending=False)[cols],
            use_container_width=True, hide_index=True,
        )

    else:
        # Rank on the supervisor's rating, using Output/Hr only to break ties.
        # Unrated workers sit out of both lists rather than sinking to the
        # bottom on a missing value.
        rated = ranked[ranked["Rating"].notna()].copy()
        rated["Rating"] = pd.to_numeric(rated["Rating"], errors="coerce")

        top5 = rated.sort_values(["Rating", "Output/Hr"], ascending=[False, False]).head(5)
        bot5 = rated.sort_values(["Rating", "Output/Hr"], ascending=[True, True]).head(5)

        b1, b2 = st.columns(2)
        with b1:
            st.markdown("**🏆 Top 5 — supervisor rating**")
            st.dataframe(top5[cols], use_container_width=True, hide_index=True)
        with b2:
            st.markdown("**🐢 Bottom 5 — supervisor rating**")
            st.dataframe(bot5[cols], use_container_width=True, hide_index=True)

        unrated = ranked[ranked["Rating"].isna()]
        if not unrated.empty:
            st.caption(
                f"{len(unrated)} worker(s) logged hours but were not rated, "
                "so they appear in neither list: "
                + ", ".join(unrated["Worker"].astype(str))
            )

        st.caption(
            "⚠️ Output/Hr is shown beside the rating, not ranked on. It mixes "
            "units (Nos, Mtrs, Kgs, Joints), so two workers on different gates "
            "are not comparable on that number."
        )

    with st.expander("📋 Full day board (everyone who logged)"):
        st.dataframe(day_board, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 Download Day Board",
            to_csv(day_board),
            f"worker_day_{pick_day}.csv",
            "text/csv",
            key="dl_day_board",
        )


def render_job_plans():
    """Read-only view of production plans, per job or all jobs, with CSV export."""
    st.subheader("📅 Job-wise Production Plan")

    if enriched_plan.empty:
        st.info("No production plans exist yet. Create one in 'Scheduling & Execution'.")
        return

    view_cols = {
        "job_no": "Job No",
        "step_order": "Step",
        "gate_name": "Gate",
        "current_status": "Status",
        "Schedule Flag": "Schedule Flag",
        "Planned Start": "Planned Start",
        "Planned End": "Planned End",
        "Actual Start": "Actual Start",
        "Actual End": "Actual End",
        "Delay (Days)": "Delay (Days)",
    }

    # ── All jobs ──
    st.markdown("#### 📚 All Jobs — Consolidated Plan")
    all_view = (
        enriched_plan[list(view_cols.keys())]
        .rename(columns=view_cols)
        .sort_values(["Job No", "Step"])
    )
    st.dataframe(all_view, use_container_width=True, hide_index=True, height=320)
    st.download_button(
        "📥 Download ALL Job Plans",
        to_csv(all_view),
        f"all_job_plans_{date.today()}.csv",
        "text/csv",
        key="dl_all_plans",
    )

    st.divider()

    # ── Single job ──
    st.markdown("#### 🔍 Single Job Plan")
    sel_job = st.selectbox(
        "Select Job", ["-- Select --"] + plan_job_list, key="jp_job"
    )

    if sel_job == "-- Select --":
        st.caption("Pick a job above to see its plan and download it separately.")
        return

    one = enriched_plan[enriched_plan["job_no"] == sel_job]
    one_view = (
        one[list(view_cols.keys())]
        .rename(columns=view_cols)
        .sort_values("Step")
    )

    total = len(one_view)
    done  = int((one_view["Status"] == "Completed").sum())
    late  = int((one_view["Delay (Days)"] > 0).sum())

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Steps", total)
    m2.metric("Completed", f"{done} ({round(done / total * 100) if total else 0}%)")
    m3.metric("Steps Behind", late)

    st.dataframe(one_view, use_container_width=True, hide_index=True)
    st.download_button(
        f"📥 Download Plan — {sel_job}",
        to_csv(one_view),
        f"plan_{sel_job}_{date.today()}.csv",
        "text/csv",
        key="dl_one_plan",
    )


def render_morning_rating():
    """
    Supervisor rates the previous day's workers, 0-4.
    Defaults to yesterday because the rating happens next morning.
    """
    st.markdown("#### 🌅 Morning Rating")

    r1, r2 = st.columns([1, 2])
    rate_day = r1.date_input(
        "Work date being rated",
        value=date.today() - timedelta(days=1),
        max_value=date.today(),
        key="mr_day",
    )
    supervisor = r2.selectbox("Rating by", ["-- Select --"] + all_staff, key="mr_sup")

    board = worker_day_board(df_logs, rate_day)
    if board.empty:
        st.info(f"Nobody logged hours on {fmt_date(rate_day)}.")
        return

    # Pre-fill anything already saved for this date so re-rating shows
    # the current value rather than resetting to blank.
    day_r = ratings_for_day(df_ratings, rate_day)
    prev_rating  = dict(zip(day_r["worker"], day_r["rating"])) if not day_r.empty else {}
    prev_remarks = dict(zip(day_r["worker"], day_r["remarks"])) if not day_r.empty else {}

    NOT_RATED = "— not rated —"
    options   = [NOT_RATED, 0, 1, 2, 3, 4]

    with st.form("morning_rating_form"):
        st.caption("0 = poor, 4 = excellent. Leave as 'not rated' to skip someone.")
        picks = {}

        for _, row in board.iterrows():
            w = str(row["Worker"])
            c1, c2, c3 = st.columns([2, 1, 2])

            c1.write(f"**{w}**")
            c1.caption(f"{row['Hours']:.1f} hrs • {row['Jobs']}")

            pv = prev_rating.get(w)
            idx = options.index(int(pv)) if pd.notna(pv) and int(pv) in options else 0

            picks[w] = (
                c2.selectbox("Rating", options, index=idx,
                             key=f"mr_r_{w}", label_visibility="collapsed"),
                c3.text_input("Remarks", value=str(prev_remarks.get(w) or ""),
                              key=f"mr_n_{w}", label_visibility="collapsed",
                              placeholder="Remarks (optional)"),
            )

        if st.form_submit_button("💾 Save Ratings"):
            if supervisor == "-- Select --":
                st.error("Please select who is giving these ratings.")
            else:
                payload = [
                    {
                        "worker":     w,
                        "work_date":  rate_day.isoformat(),
                        # None, not 0 — an unrated worker must not be
                        # stored as a zero grade.
                        "rating":     None if val == NOT_RATED else int(val),
                        "supervisor": supervisor,
                        "remarks":    note or None,
                        "updated_at": NOW_IST(),
                    }
                    for w, (val, note) in picks.items()
                ]
                db_upsert("worker_day_ratings", payload, "worker,work_date")
                st.success(f"Saved {len(payload)} rating(s) for {fmt_date(rate_day)}.")
                st.rerun()


def render_analytics():
    """
    Analytics tab. Uses `return` instead of st.stop() so that an empty
    dataset here never blocks the tabs rendered after this one.
    """
    st.subheader("📊 Production Intelligence Reports")

    if df_logs.empty:
        st.info("No production data available yet.")
        return

    # Pre-process once
    adf = df_logs.copy()
    adf["dt"]        = pd.to_datetime(adf["created_at"], utc=True, errors="coerce").dt.tz_convert(IST)
    adf["date_only"] = adf["dt"].dt.date
    adf["Hours"]     = pd.to_numeric(adf["Hours"],  errors="coerce").fillna(0)
    adf["Output"]    = pd.to_numeric(adf["Output"], errors="coerce").fillna(0)

    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        today  = date.today()
        period = c1.selectbox("Timeframe", PERIOD_OPTIONS, index=1)

        date_ranges = {
            "Today":          [today, today],
            "Last 7 Days":    [today - timedelta(days=7), today],
            "Current Month":  [today.replace(day=1), today],
        }
        d_range = date_ranges.get(period) or c1.date_input(
            "Select Range", [today - timedelta(days=30), today]
        )

        f_jobs    = c2.multiselect("Filter Jobs",    all_jobs,    default=all_jobs)
        f_workers = c3.multiselect("Filter Workers", all_workers, default=all_workers)

    if len(d_range) != 2:
        st.info("Please pick both a start and an end date.")
        return

    mask = (
        (adf["date_only"] >= d_range[0]) &
        (adf["date_only"] <= d_range[1]) &
        (adf["Job_Code"].isin(f_jobs)) &
        (adf["Worker"].isin(f_workers))
    )
    rdf = adf.loc[mask]

    if rdf.empty:
        st.warning("No data matches the selected filters.")
        return

    # KPIs
    total_hrs    = rdf["Hours"].sum()
    total_out    = rdf["Output"].sum()
    productivity = total_out / total_hrs if total_hrs > 0 else 0

    k1, k2, k3 = st.columns(3)
    k1.metric("Total Man-Hours",    f"{total_hrs:.1f} hrs")
    k2.metric("Total Output",       f"{total_out:.0f}")
    k3.metric("Productivity Index", f"{productivity:.2f} U/Hr")

    st.download_button(
        "📂 Export All Filtered Data",
        to_csv(rdf), f"bg_full_report_{period}.csv", "text/csv",
        key="dl_full_report",
    )
    st.divider()

    # Job-wise summary
    st.markdown("#### 🏗️ Job-wise Performance Report")
    job_sum = (
        rdf.groupby("Job_Code")[["Hours", "Output"]]
        .sum()
        .rename(columns={"Hours": "Total Hours", "Output": "Total Output"})
        .reset_index()
    )
    job_sum["Efficiency (U/Hr)"] = (
        job_sum["Total Output"] / job_sum["Total Hours"].replace(0, pd.NA)
    ).round(2).fillna(0)
    st.dataframe(job_sum, use_container_width=True, hide_index=True)
    st.download_button(
        "📥 Export Job Summary", to_csv(job_sum),
        f"job_summary_{period}.csv", key="dl_job_summary",
    )

    st.divider()

    # Worker summary
    st.markdown("#### 👷 Worker Contribution Report")
    worker_sum = (
        rdf.groupby("Worker")[["Hours", "Output"]]
        .sum()
        .rename(columns={"Hours": "Hours Logged", "Output": "Units Completed"})
        .reset_index()
    )
    st.dataframe(worker_sum, use_container_width=True, hide_index=True)
    st.download_button(
        "📥 Export Worker Summary", to_csv(worker_sum),
        f"worker_summary_{period}.csv", key="dl_worker_summary",
    )


# ─────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────
tab_dash, tab_plan, tab_entry, tab_jobplan, tab_analytics, tab_master = st.tabs([
    "🎯 Dashboard",
    "🏗️ Scheduling & Execution",
    "👷 Daily Entry",
    "📅 Job Plans",
    "📊 Analytics & Reports",
    "⚙️ Master Settings",
])

# ── TAB 0: DASHBOARD ───────────────────────────
with tab_dash:
    render_dashboard()


# ── TAB 1: SCHEDULING & EXECUTION ──────────────
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)

    # NOTE: this used to be `st.stop()`, which halts the WHOLE script and
    # therefore stopped every later tab from being built. An if/else only
    # skips this tab's body.
    if target_job == "-- Select --":
        st.info("👆 Select a job to view its schedule, materials and execution gates.")
    else:
        proj_match = df_projects[df_projects["job_no"] == target_job]
        if not proj_match.empty:
            render_project_header(proj_match.iloc[0], target_job)

        render_purchase_section(target_job)

        st.divider()

        job_steps = (
            df_job_plans[df_job_plans["job_no"] == target_job]
            if not df_job_plans.empty
            else pd.DataFrame()
        )

        # ── No plan yet: clone or start fresh ──
        if job_steps.empty:
            st.warning("⚠️ No Plan Detected")
            src_job = st.selectbox("Clone from Template:", ["-- Select --"] + all_jobs, key="clone_src")
            if st.button("🚀 Clone Sequence") and src_job != "-- Select --":
                src_steps = df_job_plans[df_job_plans["job_no"] == src_job]
                if not src_steps.empty:
                    today = date.today()
                    payload = [
                        {
                            "job_no": target_job,
                            "gate_name": s["gate_name"],
                            "step_order": s["step_order"],
                            "planned_start_date": today.isoformat(),
                            "planned_end_date": (today + timedelta(days=5)).isoformat(),
                            "current_status": "Pending",
                        }
                        for _, s in src_steps.iterrows()
                    ]
                    db_insert("job_planning", payload)
                    st.rerun()

        # ── Add single gate ──
        with st.expander("➕ Add Single Gate to Plan", expanded=False):
            with st.form("add_gate_form", clear_on_submit=True):
                sc1, sc2, sc3 = st.columns([2, 2, 1])
                ng_gate  = sc1.selectbox("Process Gate", all_activities)
                ng_dates = sc2.date_input("Planned Window",
                                          [date.today(), date.today() + timedelta(days=5)])
                ng_order = sc3.number_input("Step Order", min_value=1, value=len(job_steps) + 1)

                if st.form_submit_button("🚀 Add to Plan") and len(ng_dates) == 2:
                    db_insert("job_planning", {
                        "job_no": target_job,
                        "gate_name": ng_gate,
                        "step_order": ng_order,
                        "planned_start_date": ng_dates[0].isoformat(),
                        "planned_end_date":   ng_dates[1].isoformat(),
                        "current_status": "Pending",
                    })
                    st.rerun()

        # ── Manage / Edit sequence ──
        if not job_steps.empty:
            with st.expander("📝 Manage Sequence & Dates", expanded=False):
                for _, edit_row in job_steps.sort_values("step_order").iterrows():
                    eid = edit_row["id"]
                    with st.container(border=True):
                        ec1, ec2, ec3, ec4 = st.columns([2, 2, 1, 1])
                        u_gate  = ec1.selectbox(
                            "Gate", all_activities,
                            index=all_activities.index(edit_row["gate_name"])
                                   if edit_row["gate_name"] in all_activities else 0,
                            key=f"en_{eid}",
                        )
                        u_dates = ec2.date_input(
                            "Dates",
                            [safe_date(edit_row["planned_start_date"]),
                             safe_date(edit_row["planned_end_date"])],
                            key=f"ed_{eid}",
                        )
                        u_order = ec3.number_input("Order", value=int(edit_row["step_order"]),
                                                   key=f"eo_{eid}")

                        if ec4.button("💾", key=f"sv_{eid}"):
                            db_update("job_planning", {
                                "gate_name": u_gate,
                                "planned_start_date": u_dates[0].isoformat(),
                                "planned_end_date":   u_dates[1].isoformat(),
                                "step_order": u_order,
                            }, "id", eid)
                            st.rerun()

                        if ec4.button("🗑️", key=f"dl_{eid}"):
                            db_delete("job_planning", "id", eid)
                            st.rerun()

            # ── Execution view ──
            st.subheader(f"🏁 Execution: {target_job}")
            for _, row in job_steps.sort_values("step_order").iterrows():
                render_gate_step(row, all_activities)


# ── TAB 2: DAILY ENTRY ─────────────────────────
with tab_entry:
    with st.expander("🌅 Morning Rating — rate yesterday's work", expanded=False):
        render_morning_rating()

    st.divider()

    st.subheader("👷 Labor & Output Tracking")
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + all_jobs, key="ent_job")

    if f_job != "-- Select --":
        job_plan_df  = df_job_plans[df_job_plans["job_no"] == f_job] if not df_job_plans.empty else pd.DataFrame()
        active_gates = job_plan_df[job_plan_df["current_status"] == "Active"]["gate_name"].tolist()
        form_gates   = active_gates or job_plan_df["gate_name"].tolist()

        if not form_gates:
            st.warning("⚠️ No gates found in plan.")
        else:
            with st.form("prod_form", clear_on_submit=True):
                f1, f2, f3 = st.columns(3)
                f_act  = f1.selectbox("Gate", form_gates)
                f_wrks = f1.multiselect("Workers Involved", all_workers)
                f_hrs  = f2.number_input("Hrs (Per Person)", min_value=0.0, step=0.5)
                f_unit = f2.selectbox("Unit", OUTPUT_UNITS)
                f_out  = f3.number_input("Qty", min_value=0.0, step=0.1)
                f_sup  = f3.selectbox("Supervisor", ["-- Select --"] + all_staff)
                f_notes = st.text_input("Remarks / Notes")

                if st.form_submit_button("🚀 Log Progress"):
                    if not f_wrks:
                        st.error("Please select at least one worker.")
                    elif f_sup == "-- Select --":
                        st.error("Please select the supervisor for this entry.")
                    else:
                        shared_output = f_out / len(f_wrks)
                        payload = [
                            {
                                "Job_Code":   f_job,
                                "Activity":   f_act,
                                "Worker":     w,
                                "Supervisor": f_sup,
                                "Hours":      f_hrs,
                                "Output":     shared_output,
                                "Unit":       f_unit,
                                "notes":      f_notes,
                                "created_at": NOW_IST(),
                            }
                            for w in f_wrks
                        ]
                        db_insert("production", payload)
                        st.success(f"Logged for {len(f_wrks)} workers!")
                        st.rerun()

    st.divider()

    if not df_logs.empty:
        display_logs = df_logs.copy()
        if f_job != "-- Select --":
            display_logs = display_logs[display_logs["Job_Code"] == f_job]

        display_logs["dt"] = pd.to_datetime(display_logs["created_at"], utc=True, errors="coerce")
        display_logs["Time (IST)"] = (
            display_logs["dt"].dt.tz_convert(IST).dt.strftime("%d-%b %I:%M %p")
        )

        with st.expander("🛠️ Correction Tools"):
            if not display_logs.empty:
                last_row = display_logs.iloc[0]
                if st.button("✏️ Edit Last Entry"):
                    @st.dialog("Edit Log")
                    def _edit_log(item):
                        nh = st.number_input("Hrs", value=float(item["Hours"]))
                        nq = st.number_input("Qty", value=float(item["Output"]))
                        nn = st.text_input("Notes", value=item.get("notes", ""))
                        if st.button("Save"):
                            db_update("production",
                                      {"Hours": nh, "Output": nq, "notes": nn},
                                      "id", item["id"])
                            st.rerun()
                    _edit_log(last_row)

        st.dataframe(
            display_logs[["Time (IST)", "Job_Code", "Activity", "Worker",
                           "Hours", "Output", "Unit", "notes"]].head(20),
            use_container_width=True,
            hide_index=True,
        )


# ── TAB 3: JOB PLANS ───────────────────────────
with tab_jobplan:
    render_job_plans()


# ── TAB 4: ANALYTICS ───────────────────────────
with tab_analytics:
    render_analytics()


# ── TAB 5: MASTER SETTINGS ─────────────────────
with tab_master:
    st.subheader("⚙️ Gate Master")

    with st.form("new_gate", clear_on_submit=True):
        ng_name  = st.text_input("Gate Name")
        ng_order = st.number_input("Order", value=len(df_master_gates) + 1)
        if st.form_submit_button("Add Gate"):
            if ng_name:
                db_insert("production_gates", {"gate_name": ng_name, "step_order": ng_order})
                st.rerun()

    if not df_master_gates.empty:
        st.dataframe(
            df_master_gates.sort_values("step_order")[["step_order", "gate_name"]],
            hide_index=True,
        )
