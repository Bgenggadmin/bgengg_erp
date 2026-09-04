import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, time, timedelta
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

# Production lifecycle, stored in anchor_projects.prod_stage.
# NULL in the database means Running — nothing needed backfilling.
PROD_STAGES = ["Running", "Hold", "Dispatched", "Stock"]

# Stages that take a job out of the dispatch outlook. Both are
# terminal: nothing is being chased towards a customer date.
CLOSED_STAGES = ["Dispatched", "Stock"]

# A job is flagged "Due soon" when dispatch is this many days away or less.
DUE_SOON_DAYS = 7

# A worker must log at least this many hours in a day to appear on the
# best/worst leaderboard. Stops a 15-minute entry from topping the chart.
LEADERBOARD_MIN_HOURS = 1.0

# Attendance
ATT_STATUSES = ["Present", "Half Day", "Absent", "Leave", "Holiday"]
# Statuses where nobody is expected to punch in.
ATT_AWAY = ["Absent", "Leave", "Holiday"]
DEFAULT_PUNCH_IN  = time(9, 0)
DEFAULT_PUNCH_OUT = time(17, 30)

# Slack when comparing hours logged against hours present, so that
# rounding or a 20-minute gap does not get called under-allotment.
ALLOTMENT_TOLERANCE_HRS = 0.5


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


def safe_time(val) -> time | None:
    """Parse a Postgres `time` value ('09:00:00') to a Python time."""
    if val is None or (not isinstance(val, time) and pd.isnull(val)):
        return None
    if isinstance(val, time):
        return val
    try:
        return pd.to_datetime(str(val)).time()
    except Exception:
        return None


def hours_between(punch_in, punch_out) -> float | None:
    """
    Hours between two clock times.

    A punch_out earlier than punch_in means the shift crossed midnight,
    so 24 hours are added rather than returning a negative number. That
    is why the database does not reject punch_out < punch_in.
    """
    pin, pout = safe_time(punch_in), safe_time(punch_out)
    if pin is None or pout is None:
        return None
    start = timedelta(hours=pin.hour,  minutes=pin.minute,  seconds=pin.second)
    end   = timedelta(hours=pout.hour, minutes=pout.minute, seconds=pout.second)
    if end < start:
        end += timedelta(days=1)
    return round((end - start).total_seconds() / 3600, 2)


def allotment_bucket(present, logged, status=None) -> str:
    """
    Compare hours logged on jobs against hours physically present.

    `status` is needed as well as the hours: a man marked Absent has no
    punch times, so his present-hours are missing — the same shape as a
    man whose punches nobody entered. Without the status those two look
    identical, and an absent man gets reported as idle on the floor.

    'Over' is flagged as a suspected entry error, not as high output: a
    man present 8 hours cannot work 11. It usually means team hours were
    entered per-team instead of per-person.
    """
    if status in ATT_AWAY:
        return "⚫ Away"
    # pd.isna catches NaN, which `is None` does not.
    if present is None or pd.isna(present):
        return "⚪ No attendance"
    if present <= 0:
        return "⚫ Away"
    if logged is None or pd.isna(logged) or logged <= 0:
        return "🔴 Not allotted"
    if logged > present + ALLOTMENT_TOLERANCE_HRS:
        return "⚠️ Over — check entry"
    if logged < present - ALLOTMENT_TOLERANCE_HRS:
        return "🟠 Under-allotted"
    return "🟢 Balanced"


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
                "job_no, status, po_no, po_date, po_delivery_date, "
                "revised_delivery_date, prod_stage"
             ).eq("status", "Won").execute()
        l  = conn.table("production").select("*").order("created_at", desc=True).execute()
        g  = conn.table("production_gates").select("*").order("step_order").execute()
        jp = conn.table("job_planning").select("*").order("step_order").execute()
        po = conn.table("purchase_orders").select("*").execute()
        wr = conn.table("worker_day").select("*").order("work_date", desc=True).execute()

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
 df_job_plans, df_purchase, df_day) = load_all_data()

# Derived lists
all_staff      = master.get("staff", [])
all_workers    = sorted(set(master.get("workers", [])))
all_jobs       = sorted(df_projects["job_no"].astype(str).unique()) if not df_projects.empty else []


def _active_job_list(projects: pd.DataFrame) -> list:
    """
    Jobs still being worked on: Running or Hold.

    Reads prod_stage with NULL meaning Running. Guards against the column
    being absent so the app still runs if prod_stage.sql has not been
    applied yet — in that case every job counts as active, which is the
    old behaviour rather than an empty dropdown.
    """
    if projects.empty:
        return []
    if "prod_stage" not in projects.columns:
        return sorted(projects["job_no"].astype(str).unique())

    stage = projects["prod_stage"].fillna("Running")
    keep  = projects.loc[~stage.isin(CLOSED_STAGES), "job_no"]
    return sorted(keep.astype(str).unique())


active_jobs = _active_job_list(df_projects)
closed_jobs = [j for j in all_jobs if j not in set(active_jobs)]
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
    for worker_day that is "worker,work_date". This is what
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
        stage = (p.get("prod_stage") or "Running")

        # Dispatched and Stock jobs are finished with. Neither is being
        # chased towards a customer date, so neither belongs in an
        # outlook of what is still to come.
        if stage in CLOSED_STAGES:
            continue

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

        # Hold is checked first: a job the customer has paused should not
        # be reported as overdue or lagging against us.
        if stage == "Hold":
            flag, rank = "🔵 Hold", 3
        elif total == 0:
            flag, rank = "⚪ No plan", 4
        elif pct == 100:
            flag, rank = "✅ Plan complete", 6
        elif target and days_left is not None and days_left < 0:
            flag, rank = "🔴 Overdue", 0
        elif max_delay > 0:
            flag, rank = "🟠 Lagging", 1
        elif days_left is not None and days_left <= DUE_SOON_DAYS:
            flag, rank = "🟡 Due soon", 2
        else:
            flag, rank = "🟢 On track", 5

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


def work_detail_for_day(logs: pd.DataFrame, day: date, max_lines: int = 4) -> dict:
    """
    worker -> readable summary of what they actually worked on that day.

    Grouped by job AND gate, because "8 hours on RTP_1522" tells a
    supervisor much less than "6h welding, 2h buffing" when he is trying
    to judge the work. Long lists are capped so one busy man cannot
    stretch the whole row.
    """
    if logs.empty or not day:
        return {}

    d = logs.copy()
    d["dt"] = pd.to_datetime(d["created_at"], utc=True, errors="coerce")
    d = d.dropna(subset=["dt"])
    if d.empty:
        return {}

    d = d[d["dt"].dt.tz_convert(IST).dt.date == day]
    if d.empty:
        return {}

    d["Hours"]  = pd.to_numeric(d["Hours"],  errors="coerce").fillna(0)
    d["Output"] = pd.to_numeric(d["Output"], errors="coerce").fillna(0)

    grp = (d.groupby(["Worker", "Job_Code", "Activity", "Unit"], dropna=False)
             .agg(Hours=("Hours", "sum"), Output=("Output", "sum"))
             .reset_index()
             .sort_values(["Worker", "Hours"], ascending=[True, False]))

    out = {}
    for worker, rows in grp.groupby("Worker"):
        lines = []
        for _, r in rows.iterrows():
            # NaN is TRUTHY in Python, so `r["Activity"] or "—"` returns the
            # NaN and prints as the string "nan". pd.isna is the only safe
            # test here.
            job  = "—" if pd.isna(r["Job_Code"]) else str(r["Job_Code"])
            gate = "—" if pd.isna(r["Activity"]) else str(r["Activity"])
            bit  = f"**{job}** · {gate} — {r['Hours']:.1f}h"
            if r["Output"] > 0:
                unit = "" if pd.isna(r["Unit"]) else f" {r['Unit']}"
                bit += f", {r['Output']:.0f}{unit}"
            lines.append(bit)

        extra = len(lines) - max_lines
        shown = lines[:max_lines]
        if extra > 0:
            shown.append(f"_+{extra} more_")
        out[str(worker)] = "<br>".join(shown)

    return out


def rows_for_day(day_rows: pd.DataFrame, day: date) -> pd.DataFrame:
    """Rows from worker_day for one work_date."""
    if day_rows.empty or "work_date" not in day_rows.columns or not day:
        return pd.DataFrame()
    r = day_rows.copy()
    r["work_date"] = r["work_date"].apply(safe_date)
    return r[r["work_date"] == day]


ATT_COLS = ["worker", "rating", "supervisor", "remarks",
            "attendance_status", "punch_in", "punch_out"]


def attach_day_data(board: pd.DataFrame, day_rows: pd.DataFrame, day: date) -> pd.DataFrame:
    """
    Add attendance and rating to a worker day board, then derive
    hours present and the allotment bucket.

    An OUTER join, not a left join. The board is built from production
    logs, so a left join would only ever describe men who were given
    work. The whole point of attendance is to see the man who was
    present all day and logged nothing — he has no production row, so
    he only appears if attendance rows are brought in too.
    """
    day_r = rows_for_day(day_rows, day)

    if board.empty and day_r.empty:
        return pd.DataFrame()

    out = board.copy() if not board.empty else pd.DataFrame(columns=["Worker"])

    if day_r.empty:
        for c, v in [("Rating", pd.NA), ("Rated By", ""), ("Remarks", ""),
                     ("Attendance", ""), ("In", ""), ("Out", "")]:
            out[c] = v
    else:
        keep = day_r[[c for c in ATT_COLS if c in day_r.columns]].rename(columns={
            "worker": "Worker", "rating": "Rating", "supervisor": "Rated By",
            "remarks": "Remarks", "attendance_status": "Attendance",
            "punch_in": "In", "punch_out": "Out",
        })
        out = out.merge(keep, on="Worker", how="outer")
        for c in ["Rated By", "Remarks", "Attendance", "In", "Out"]:
            if c in out.columns:
                out[c] = out[c].fillna("")

    # Men brought in by attendance alone have no production numbers.
    for c, v in [("Hours", 0.0), ("Output", 0.0), ("Output/Hr", 0.0),
                 ("Jobs", ""), ("Units", ""), ("Entries", 0)]:
        if c not in out.columns:
            out[c] = v
        else:
            out[c] = out[c].fillna(v)

    out["Present Hrs"] = [hours_between(i, o) for i, o in zip(out["In"], out["Out"])]
    out["Logged Hrs"]  = pd.to_numeric(out["Hours"], errors="coerce").fillna(0.0)
    att_col = out["Attendance"] if "Attendance" in out.columns else [None] * len(out)
    out["Allotment"] = [allotment_bucket(p, l, a)
                        for p, l, a in zip(out["Present Hrs"],
                                           out["Logged Hrs"], att_col)]
    out["Util %"] = [
        round(l / p * 100) if (p and p > 0) else pd.NA
        for p, l in zip(out["Present Hrs"], out["Logged Hrs"])
    ]
    return out.sort_values("Worker").reset_index(drop=True)


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

        # Same rule as the Anchor Portal: a job that has shipped or gone to
        # stock is not counting down to anything.
        stage_now = p_data.get("prod_stage") or "Running"
        days = days_remaining(final_target)

        if stage_now == "Dispatched":
            c4.metric("Dispatch Status", "✅ Dispatched")
        elif stage_now == "Stock":
            c4.metric("Dispatch Status", "📦 In Stock")
        elif stage_now == "Hold":
            c4.metric("Dispatch Status", "🔵 On Hold")
            c4.caption(f"Target was {fmt_date(final_target)}")
        elif days is not None:
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

        # ── Production stage ──
        # Writes anchor_projects.prod_stage, the same column the Anchor
        # Portal reads and writes. Set it here or there; both show it.
        st.divider()
        cur_stage = p_data.get("prod_stage") or "Running"
        s1, s2 = st.columns([2, 1])
        new_stage = s1.radio(
            "Production Stage",
            PROD_STAGES,
            index=PROD_STAGES.index(cur_stage) if cur_stage in PROD_STAGES else 0,
            horizontal=True,
            key=f"stage_{target_job}",
            help="Dispatched hides the job from the outlook. "
                 "Hold keeps it visible but stops it counting as late.",
        )
        if new_stage != cur_stage:
            if s2.button("💾 Save Stage", key=f"savestage_{target_job}",
                         type="primary", use_container_width=True):
                db_update("anchor_projects",
                          {"prod_stage": new_stage,
                           "prod_stage_updated_at": NOW_IST()},
                          "job_no", target_job)
                st.success(f"{target_job} marked {new_stage}.")
                st.rerun()
        else:
            s2.caption(f"Currently **{cur_stage}**")


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
    st.markdown("#### 👷 Attendance, Allotment & Performance")
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

    day_board = attach_day_data(day_board, df_day, pick_day)

    # ── Attendance vs work allotted ──
    present_hrs = pd.to_numeric(day_board["Present Hrs"], errors="coerce").fillna(0).sum()
    logged_hrs  = pd.to_numeric(day_board["Logged Hrs"],  errors="coerce").fillna(0).sum()
    util        = round(logged_hrs / present_hrs * 100) if present_hrs > 0 else 0

    counts = day_board["Allotment"].value_counts().to_dict()
    n_none = counts.get("🔴 Not allotted", 0)
    n_und  = counts.get("🟠 Under-allotted", 0)
    n_over = counts.get("⚠️ Over — check entry", 0)

    a1, a2, a3, a4, a5, a6 = st.columns(6)
    a1.metric("Hours Present", f"{present_hrs:.1f}")
    a2.metric("Hours on Jobs", f"{logged_hrs:.1f}")
    a3.metric("Utilisation", f"{util}%")
    a4.metric("🔴 Not allotted", n_none)
    a5.metric("🟠 Under", n_und)
    a6.metric("⚠️ Check entry", n_over)

    if present_hrs > 0 and logged_hrs < present_hrs:
        st.caption(
            f"{present_hrs - logged_hrs:.1f} hours present but not booked to "
            "any job. That is idle capacity, work nobody logged, or both."
        )
    if n_over:
        st.warning(
            f"{n_over} worker(s) logged more hours than they were present. "
            "That is usually team hours entered per-team instead of "
            "per-person — worth correcting before it reaches a report."
        )

    idle = day_board[day_board["Allotment"] == "🔴 Not allotted"]
    if not idle.empty:
        with st.expander(f"🔴 Present but no work allotted ({len(idle)})",
                         expanded=False):
            st.dataframe(
                idle[["Worker", "Attendance", "In", "Out", "Present Hrs", "Remarks"]],
                use_container_width=True, hide_index=True,
            )

    st.divider()
    st.markdown("##### 🏅 Ratings")

    rated_count = int(day_board["Rating"].notna().sum())
    total_count = len(day_board)
    st.caption(f"{rated_count} of {total_count} workers rated for {fmt_date(pick_day)}.")

    ranked = day_board[day_board["Hours"] >= LEADERBOARD_MIN_HOURS]
    cols = ["Worker", "Rating", "Present Hrs", "Logged Hrs", "Util %",
            "Allotment", "Output/Hr", "Rated By"]

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


def job_plan_status(projects: pd.DataFrame, plan: pd.DataFrame) -> pd.DataFrame:
    """
    One row per Won job with a lifecycle bucket.

    The explicit marker wins. anchor_projects.prod_stage is set by hand
    in either this app or the Anchor Portal — one column, so a change in
    one place shows in the other with nothing to sync.

    Gate completion is NOT used to infer dispatch any more. A job whose
    gates are all closed but which nobody has marked stays visible,
    because "the plan finished" and "it left the factory" are different
    claims and only a person knows the second one.
    """
    if projects.empty:
        return pd.DataFrame()

    today = date.today()
    rows = []

    for _, p in projects.iterrows():
        job    = str(p.get("job_no"))
        stage  = (p.get("prod_stage") or "Running")
        target = safe_date(p.get("revised_delivery_date")) or safe_date(p.get("po_delivery_date"))
        steps  = plan[plan["job_no"] == job] if not plan.empty else pd.DataFrame()
        total  = len(steps)
        done   = int((steps["current_status"] == "Completed").sum()) if total else 0

        if stage in CLOSED_STAGES:
            bucket = stage
        elif stage == "Hold":
            bucket = "Hold"
        elif total == 0:
            bucket = "Yet to plan"
        else:
            bucket = "Running"

        rows.append({
            "Job No":    job,
            "PO No":     p.get("po_no") or "---",
            "Bucket":    bucket,
            "Target":    fmt_date(target),
            "Days Left": (target - today).days if target else None,
            "Steps":     total,
            "Done":      done,
            "_target":   target or date(2099, 1, 1),
        })

    return pd.DataFrame(rows)


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
    status_df = job_plan_status(df_projects, enriched_plan)

    def _bucket(name: str) -> set:
        if status_df.empty:
            return set()
        return set(status_df.loc[status_df["Bucket"] == name, "Job No"])

    st.markdown("#### 📚 Consolidated Plan")

    counts = {b: len(_bucket(b)) for b in ["Running", "Hold", "Dispatched", "Stock"]}
    chosen = st.multiselect(
        "Show stages",
        options=list(counts.keys()),
        default=["Running", "Hold"],
        format_func=lambda b: f"{b} ({counts[b]})",
        key="jp_stages",
        help="Hold is on by default so paused jobs are not forgotten. "
             "Dispatched and Stock are off — turn them on for history.",
    )

    visible = set()
    for b in chosen:
        visible |= _bucket(b)

    all_view = (
        enriched_plan[enriched_plan["job_no"].isin(visible)][list(view_cols.keys())]
        .rename(columns=view_cols)
        .sort_values(["Job No", "Step"])
    )

    if all_view.empty:
        st.info("No jobs match the selected stages.")
    else:
        hidden = sum(v for b, v in counts.items() if b not in chosen)
        st.caption(
            f"{all_view['Job No'].nunique()} job(s), {len(all_view)} steps."
            + (f" {hidden} job(s) hidden by the stage filter." if hidden else "")
        )
        st.dataframe(all_view, use_container_width=True, hide_index=True, height=320)
        st.download_button(
            "📥 Download Consolidated Plan",
            to_csv(all_view),
            f"job_plans_{date.today()}.csv",
            "text/csv",
            key="dl_all_plans",
        )

    # ── Jobs with no plan yet ──
    if not status_df.empty:
        unplanned = (
            status_df[status_df["Bucket"] == "Yet to plan"]
            .sort_values("_target")
            .drop(columns=["Bucket", "Steps", "Done", "_target"])
        )
        if not unplanned.empty:
            overdue = int((unplanned["Days Left"] < 0).sum())
            st.markdown(f"#### 🕳️ Yet to Plan — {len(unplanned)} job(s)")
            if overdue:
                st.warning(
                    f"{overdue} of these are already past their delivery date "
                    "with no production plan created."
                )
            st.dataframe(unplanned, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 Download Yet-to-Plan List",
                to_csv(unplanned),
                f"yet_to_plan_{date.today()}.csv",
                "text/csv",
                key="dl_unplanned",
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


def render_morning_roll_call():
    """
    Morning screen: who was here, from when to when, and how they did.

    The worker list is NOT limited to men who logged production. A man
    who was present and given nothing to do has no production row, and
    he is precisely the one this screen exists to surface.
    """
    st.markdown("#### 🌅 Morning Roll Call & Rating")

    rate_day = st.date_input(
        "Work date",
        value=date.today() - timedelta(days=1),
        max_value=date.today(),
        key="mr_day",
    )

    board  = worker_day_board(df_logs, rate_day)
    logged = set(board["Worker"].astype(str)) if not board.empty else set()

    saved   = rows_for_day(df_day, rate_day)
    saved_w = set(saved["worker"].astype(str)) if not saved.empty else set()
    prev    = {str(r["worker"]): r for _, r in saved.iterrows()} if not saved.empty else {}

    logged_hrs = (dict(zip(board["Worker"].astype(str), board["Hours"]))
                  if not board.empty else {})
    work_detail = work_detail_for_day(df_logs, rate_day)

    # Anyone already saved, plus anyone who logged work, was obviously
    # present. Add the rest by hand.
    default_present = sorted(saved_w | logged)
    present = st.multiselect(
        "Workers present",
        options=all_workers,
        default=[w for w in default_present if w in all_workers],
        key=f"mr_present_{rate_day}",
        help="Pre-filled with anyone who logged hours. Add men who were "
             "here but had no job assigned — they are the ones this screen "
             "exists to surface.",
    )

    if not present:
        st.info("Select who was present to start the roll call.")
        return

    NOT_RATED, NO_SUP = "— not rated —", "— who? —"
    r_opts   = [NOT_RATED, 0, 1, 2, 3, 4]
    sup_opts = [NO_SUP] + all_staff

    # Keys carry the date. Without it, switching days would show one
    # day's entries sitting under another day's date.
    k = lambda kind, w: f"mr_{kind}_{rate_day}_{w}"

    # Shift times and supervisor are usually shared, so offer a bulk fill.
    # Outside the form: a widget inside a form cannot update its
    # neighbours until the form is submitted.
    st.caption("Optional bulk fill — you can still change any row after.")
    b1, b2, b3, b4 = st.columns([1, 1, 1.5, 1])
    bulk_in  = b1.time_input("In",  value=DEFAULT_PUNCH_IN,  key=f"bin_{rate_day}")
    bulk_out = b2.time_input("Out", value=DEFAULT_PUNCH_OUT, key=f"bout_{rate_day}")
    bulk_sup = b3.selectbox("Rated by", sup_opts, key=f"bsup_{rate_day}")
    if b4.button("Apply to all", key=f"bapply_{rate_day}", use_container_width=True):
        for w in present:
            st.session_state[k("in", w)]  = bulk_in
            st.session_state[k("out", w)] = bulk_out
            if bulk_sup != NO_SUP:
                st.session_state[k("sup", w)] = bulk_sup
        st.rerun()

    with st.form("roll_call_form"):
        # Work Done sits second, right beside the name: the supervisor
        # reads what the man did before choosing a rating.
        widths = [1.3, 2.4, 1.0, 0.8, 0.8, 1.0, 1.2, 1.3]
        for col, label in zip(st.columns(widths),
                              ["Worker", "Work Done", "Attendance", "In", "Out",
                               "Rating", "Rated by", "Remarks"]):
            col.markdown(f"**{label}**")

        picks = {}
        for w in present:
            pr = prev.get(w)
            c = st.columns(widths)

            c[0].write(f"**{w}**")
            lh = float(logged_hrs.get(w, 0) or 0)
            c[0].caption(f"logged {lh:.1f} hrs" if lh else "no work logged")

            detail = work_detail.get(w)
            if detail:
                c[1].markdown(
                    f"<div style='font-size:0.82rem;line-height:1.5'>{detail}</div>",
                    unsafe_allow_html=True,
                )
            else:
                # Not a blank cell: an empty space reads as "nothing entered",
                # but this man genuinely had no work booked, which is the
                # thing worth noticing before rating him.
                c[1].markdown(
                    "<div style='font-size:0.82rem;color:#c33'>no work booked</div>",
                    unsafe_allow_html=True,
                )

            a_prev = (pr.get("attendance_status") if pr is not None else None) or "Present"
            att = c[2].selectbox("Attendance", ATT_STATUSES,
                                 index=ATT_STATUSES.index(a_prev)
                                 if a_prev in ATT_STATUSES else 0,
                                 key=k("att", w), label_visibility="collapsed")

            pin_prev  = safe_time(pr.get("punch_in"))  if pr is not None else None
            pout_prev = safe_time(pr.get("punch_out")) if pr is not None else None
            pin  = c[3].time_input("In",  value=pin_prev  or DEFAULT_PUNCH_IN,
                                   key=k("in", w), label_visibility="collapsed")
            pout = c[4].time_input("Out", value=pout_prev or DEFAULT_PUNCH_OUT,
                                   key=k("out", w), label_visibility="collapsed")

            rv = pr.get("rating") if pr is not None else None
            r_idx = r_opts.index(int(rv)) if pd.notna(rv) and int(rv) in r_opts else 0
            rating = c[5].selectbox("Rating", r_opts, index=r_idx,
                                    key=k("r", w), label_visibility="collapsed")

            sv = pr.get("supervisor") if pr is not None else None
            s_idx = sup_opts.index(sv) if (pd.notna(sv) and sv in sup_opts) else 0
            sup = c[6].selectbox("Rated by", sup_opts, index=s_idx,
                                 key=k("sup", w), label_visibility="collapsed")

            note = c[7].text_input(
                "Remarks",
                value=str((pr.get("remarks") if pr is not None else "") or ""),
                key=k("n", w), label_visibility="collapsed", placeholder="optional")

            picks[w] = (att, pin, pout, rating, sup, note)

        if st.form_submit_button("💾 Save Roll Call"):
            missing = [w for w, (_, _, _, r, sp, _) in picks.items()
                       if r != NOT_RATED and sp == NO_SUP]
            if missing:
                st.error("Rated but no supervisor named: " + ", ".join(missing))
            else:
                payload = []
                for w, (att, pin, pout, rating, sup, note) in picks.items():
                    away  = att in ATT_AWAY
                    rated = rating != NOT_RATED
                    payload.append({
                        "worker":            w,
                        "work_date":         rate_day.isoformat(),
                        "attendance_status": att,
                        # Nobody punches in on a day off. Leaving stale
                        # times would compute present-hours for a man who
                        # was never here.
                        "punch_in":          None if away else pin.strftime("%H:%M:%S"),
                        "punch_out":         None if away else pout.strftime("%H:%M:%S"),
                        "rating":            int(rating) if rated else None,
                        "supervisor":        None if sup == NO_SUP else sup,
                        "remarks":           note.strip() or None,
                        "updated_at":        NOW_IST(),
                    })
                db_upsert("worker_day", payload, "worker,work_date")
                st.success(f"Roll call saved for {len(payload)} worker(s) "
                           f"on {fmt_date(rate_day)}.")
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

        # Full list on purpose: reports look backwards, so dispatched
        # jobs must stay available here.
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
    # Dispatched and Stock jobs are out of the list by default. The
    # checkbox matters: without it, marking a job Dispatched by mistake
    # would remove the only control that can un-mark it.
    jc1, jc2 = st.columns([3, 1])
    show_closed_jobs = jc2.checkbox(
        f"Show closed ({len(closed_jobs)})", value=False, key="pc_show_closed",
        help="Dispatched and Stock jobs. Tick this to reopen or correct one.",
    )
    job_choices = active_jobs + closed_jobs if show_closed_jobs else active_jobs

    target_job = jc1.selectbox("Select Job to Manage", ["-- Select --"] + job_choices)

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
            # Full list on purpose: a finished job is often the best
            # template to copy a gate sequence from.
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
    with st.expander("🌅 Morning Roll Call — attendance & rating", expanded=False):
        render_morning_roll_call()

    st.divider()

    st.subheader("👷 Labor & Output Tracking")
    # Active jobs only — logging hours against a dispatched job is almost
    # always a mis-click. Use Scheduling & Execution to reopen one first.
    f_job = st.selectbox("Select Job Code", ["-- Select --"] + active_jobs, key="ent_job")

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
