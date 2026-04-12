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

        return (
            pd.DataFrame(p.data  or []),
            pd.DataFrame(l.data  or []),
            pd.DataFrame(g.data  or []),
            pd.DataFrame(jp.data or []),
            pd.DataFrame(po.data or []),
        )
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return (pd.DataFrame(),) * 5


df_projects, df_logs, df_master_gates, df_job_plans, df_purchase = load_all_data()

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
# TABS
# ─────────────────────────────────────────────
tab_plan, tab_entry, tab_analytics, tab_master = st.tabs([
    "🏗️ Scheduling & Execution",
    "👷 Daily Entry",
    "📊 Analytics & Reports",
    "⚙️ Master Settings",
])

# ── TAB 1: SCHEDULING & EXECUTION ──────────────
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)

    if target_job == "-- Select --":
        st.stop()

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
                f_notes = st.text_input("Remarks / Notes")

                if st.form_submit_button("🚀 Log Progress"):
                    if not f_wrks:
                        st.error("Please select at least one worker.")
                    else:
                        shared_output = f_out / len(f_wrks)
                        payload = [
                            {
                                "Job_Code":   f_job,
                                "Activity":   f_act,
                                "Worker":     w,
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


# ── TAB 3: ANALYTICS ───────────────────────────
with tab_analytics:
    st.subheader("📊 Production Intelligence Reports")

    if df_logs.empty:
        st.info("No production data available yet.")
        st.stop()

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
        st.stop()

    mask = (
        (adf["date_only"] >= d_range[0]) &
        (adf["date_only"] <= d_range[1]) &
        (adf["Job_Code"].isin(f_jobs)) &
        (adf["Worker"].isin(f_workers))
    )
    rdf = adf.loc[mask]

    if rdf.empty:
        st.warning("No data matches the selected filters.")
        st.stop()

    # KPIs
    total_hrs   = rdf["Hours"].sum()
    total_out   = rdf["Output"].sum()
    productivity = total_out / total_hrs if total_hrs > 0 else 0

    k1, k2, k3 = st.columns(3)
    k1.metric("Total Man-Hours",    f"{total_hrs:.1f} hrs")
    k2.metric("Total Output",       f"{total_out:.0f}")
    k3.metric("Productivity Index", f"{productivity:.2f} U/Hr")

    st.download_button(
        "📂 Export All Filtered Data",
        to_csv(rdf), f"bg_full_report_{period}.csv", "text/csv",
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
    st.download_button("📥 Export Job Summary", to_csv(job_sum), f"job_summary_{period}.csv")

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
    st.download_button("📥 Export Worker Summary", to_csv(worker_sum), f"worker_summary_{period}.csv")


# ── TAB 4: MASTER SETTINGS ─────────────────────
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
