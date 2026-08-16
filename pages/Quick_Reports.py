# pages/14_Quick_Reports.py
# ======================================================================
# B&G Engineering ERP — Quick Reports
# A daily-driver "morning check" page: pre-defined, read-only reports.
# No free-text, no AI at runtime — fast and safe.
#
# Built to match the patterns already used in 01_Anchor_Portal.py:
#   - st_supabase_connection  (conn = st.connection("supabase", ...))
#   - @st.cache_data(ttl=30) on each fetch
#   - conn.table("...").select("*").execute()  query-builder style
#
# Reports:
#   1. Absent Today          5. Follow-ups Due       (quotations)
#   2. Pending Quotes        6. Decision Gate        (90+ days)
#   3. Open Enquiries        7. Follow-up data gaps  (housekeeping)
#   4. Overdue Jobs
#
# Material reporting lives on pages/15_Material_Status.py — it is NOT
# here. The old Report 5 (Material Shortages) was retired on 16 Aug 2026
# when anchor_projects.material_shortage / bg_job_master.is_shortage were
# confirmed legacy. Do not re-add it.
#
# Reports 5-7 read v_ap_followups_due. Run quote_followups_schema_v2.sql
# before deploying, or those three sections show a setup message.
#
# To add a report later: write one build_* function + one expander block.
# ======================================================================

import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import date, datetime, timedelta

# ----------------------------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------------------------
st.set_page_config(page_title="Quick Reports | BGEngg ERP",
                   layout="wide", page_icon="\U0001F4CB")

# ----------------------------------------------------------------------
# PASSWORD PROTECTION — REMOVED on request.
# This page is now open: anyone who can reach it sees all report data,
# with no login. To restore the gate, paste back the check_password()
# block from any other page (e.g. 01_Anchor_Portal.py) and re-add:
#     if not check_password():
#         st.stop()
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# DATABASE CONNECTION  (identical to 01_Anchor_Portal.py, line 54)
# ----------------------------------------------------------------------
conn = st.connection("supabase", type=SupabaseConnection)

# ----------------------------------------------------------------------
# CONFIG  —  >>> CONFIRM THESE LABELS MATCH YOUR DATA <<<
# ----------------------------------------------------------------------
PENDING_QUOTE_STATUS = "Quotation Sent"   # anchor_projects.status (confirmed)
ENQUIRY_STATUS       = "Enquiry"          # anchor_projects.status (confirmed)

# >>> CHANGED 16 Aug 2026 <<<
# bg_staff_master has ZERO rows. Absent Today silently reported "everyone
# present" for its entire existence. The real roster is master_staff (19
# rows). Switched here. To revert, set this back to "bg_staff_master".
# NOTE: master_staff has name/phone/email only — no department, no role,
# and no active/inactive flag. Those columns render as "—".
STAFF_TABLE = "master_staff"

# Non-employee placeholder rows in master_staff. Case-insensitive.
EXCLUDE_STAFF_NAMES = ["driver", "freelancer", "test"]

# leave_requests.status value(s) that mean "granted". Still unconfirmed —
# run:  select distinct status from leave_requests;
# and put the real approved label(s) below. Matching is case-insensitive.
APPROVED_LEAVE_STATUSES = ["Approved", "Sanctioned", "Granted"]

# "Live order" = status == 'Won'. Confirmed values:
# Enquiry / Quotation Sent / Won / Lost.
OVERDUE_OPEN_STATUS = "Won"

# >>> STILL UNRESOLVED <<<
# No dispatch/completion signal exists anywhere in the database. Checked
# all 43 anchor_projects columns, job_gate_history (covers 0 of 58 Won
# jobs), and the logistics tables (don't key on job_no). Overdue Jobs
# therefore includes jobs already out the door — of ~53 rows only ~8 are
# plausibly live. Set this to a real date column name once one exists.
DISPATCH_DONE_COL = None   # e.g. "dispatch_date"

# Quotation follow-up view (see quote_followups_schema_v2.sql)
FOLLOWUP_VIEW     = "v_ap_followups_due"
BUCKET_DUE        = "Due"
BUCKET_GATE       = "Decision gate"
BUCKET_NO_PHONE   = "No contact details"
BUCKET_NO_DATE    = "No quote date"
BUCKET_DUP        = "Duplicate row"
DECISION_GATE_DAY = 90     # display only; the view is the authority

TRUNC = 55  # description truncation length

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def parse_date(val):
    """Raw DB value -> python date, or None if unparseable."""
    try:
        parsed = pd.to_datetime(val)
        return parsed.date() if pd.notnull(parsed) else None
    except Exception:
        return None


def coalesce_date(*vals):
    """First parseable date among the args, else None."""
    for v in vals:
        d = parse_date(v)
        if d is not None:
            return d
    return None


def days_since(val):
    d = parse_date(val)
    return (date.today() - d).days if d else None


def trunc(text, n: int = TRUNC) -> str:
    if not text:
        return ""
    text = str(text)
    return text[:n] + ("\u2026" if len(text) > n else "")


def fmt_money(v) -> str:
    try:
        return f"\u20B9 {float(v):,.0f}"
    except Exception:
        return "\u2014"


def norm(s) -> str:
    """Normalise a name for comparison: trimmed + lowercased."""
    return str(s).strip().lower() if s is not None else ""


def is_true(v) -> bool:
    """Truthy across a real bool or text 'true'/'t'/'yes'/'y'/'1'.
    Supabase booleans usually arrive as real bools, but guard for text."""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in {"true", "t", "yes", "y", "1"}


def col(df: pd.DataFrame, name: str, default=None) -> pd.Series:
    """Fetch a column that may not exist, without exploding."""
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index)


def blank(v, dash: str = "\u2014") -> str:
    """Null-safe display. Null-heavy int columns arrive as floats (41.0)."""
    try:
        if v is None or pd.isna(v):
            return dash
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and float(v).is_integer():
        return str(int(v))
    return str(v)


def days_txt(v, suffix: str = "d") -> str:
    n = pd.to_numeric(v, errors="coerce")
    return f"{int(n)}{suffix}" if pd.notna(n) else "\u2014"


def clean_ref(raw) -> str:
    """quote_ref holds the literal string 'nan' on some rows (import artefact)."""
    s = str(raw or "").strip()
    return "\u2014" if s == "" or s.lower() in ("nan", "none") else s


def contact_txt(row) -> str:
    person = str(row.get("contact_person") or "").strip()
    phone  = str(row.get("contact_phone") or "").strip()
    if person and phone:
        return f"{person} \u00B7 {phone}"
    return person or phone or "\u26A0\uFE0F none"


# ----------------------------------------------------------------------
# DATA ACCESS LAYER
# ----------------------------------------------------------------------
@st.cache_data(ttl=30)
def get_staff() -> pd.DataFrame:
    res = conn.table(STAFF_TABLE).select("*").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if not df.empty and "name" in df.columns:
        bad = {n.lower() for n in EXCLUDE_STAFF_NAMES}
        df = df[~df["name"].apply(lambda n: norm(n) in bad)]
    return df


@st.cache_data(ttl=30)
def get_today_attendance() -> pd.DataFrame:
    today = date.today().isoformat()
    res = conn.table("attendance_logs").select("*").eq("work_date", today).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def get_leaves_covering_today() -> pd.DataFrame:
    today = date.today().isoformat()
    res = (conn.table("leave_requests").select("*")
           .lte("start_date", today).gte("end_date", today).execute())
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def get_projects() -> pd.DataFrame:
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def get_followups_due() -> pd.DataFrame:
    """Quotation follow-up view. Empty frame if the view isn't there yet."""
    res = conn.table(FOLLOWUP_VIEW).select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


# ----------------------------------------------------------------------
# REPORT BUILDERS
# ----------------------------------------------------------------------
def build_absent_today():
    """Staff with no attendance row today, split into Absent vs On leave."""
    staff  = get_staff()
    att    = get_today_attendance()
    leaves = get_leaves_covering_today()

    if staff.empty or "name" not in staff:
        return pd.DataFrame(), 0, 0

    present = set()
    if not att.empty and "employee_name" in att:
        present = {norm(n) for n in att["employee_name"]}

    on_leave = set()
    if not leaves.empty and "employee_name" in leaves:
        appr = leaves
        if "status" in leaves:
            allowed = {norm(x) for x in APPROVED_LEAVE_STATUSES}
            appr = leaves[leaves["status"].apply(lambda s: norm(s) in allowed)]
        on_leave = {norm(n) for n in appr["employee_name"]}

    rows = []
    for _, r in staff.iterrows():
        nm = r.get("name")
        if norm(nm) in present:
            continue
        rows.append({
            "Name":       nm,
            "Department": blank(r.get("department")),
            "Role":       blank(r.get("role")),
            "Status":     "On leave" if norm(nm) in on_leave else "Absent",
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Status", "Name"]).reset_index(drop=True)
    absent_n = int((df["Status"] == "Absent").sum()) if not df.empty else 0
    leave_n  = int((df["Status"] == "On leave").sum()) if not df.empty else 0
    return df, absent_n, leave_n


def build_pending_quotes():
    proj = get_projects()
    if proj.empty or "status" not in proj:
        return pd.DataFrame()
    df = proj[proj["status"] == PENDING_QUOTE_STATUS].copy()
    if df.empty:
        return df
    out = pd.DataFrame({
        "Client":       col(df, "client_name"),
        "Project":      col(df, "project_description").apply(trunc),
        "Quote ref":    col(df, "quote_ref").apply(clean_ref),
        "Quote date":   col(df, "quote_date"),
        "Est. value":   col(df, "estimated_value").apply(fmt_money),
        "Days pending": col(df, "quote_date").apply(days_since),
        "Anchor":       col(df, "anchor_person"),
    })
    out["Days pending"] = pd.to_numeric(out["Days pending"], errors="coerce")
    return out.sort_values("Days pending", ascending=False,
                           na_position="last").reset_index(drop=True)


def build_open_enquiries():
    proj = get_projects()
    if proj.empty or "status" not in proj:
        return pd.DataFrame()
    df = proj[proj["status"] == ENQUIRY_STATUS].copy()
    if df.empty:
        return df
    out = pd.DataFrame({
        "Client":       col(df, "client_name"),
        "Project":      col(df, "project_description").apply(trunc),
        "Enquiry date": col(df, "enquiry_date"),
        "Days waiting": col(df, "enquiry_date").apply(days_since),
        "Anchor":       col(df, "anchor_person"),
    })
    out["Days waiting"] = pd.to_numeric(out["Days waiting"], errors="coerce")
    return out.sort_values("Days waiting", ascending=False,
                           na_position="last").reset_index(drop=True)


def build_overdue_jobs():
    """Won jobs past their effective delivery date."""
    proj = get_projects()
    if proj.empty or "status" not in proj:
        return pd.DataFrame()
    df = proj[proj["status"] == OVERDUE_OPEN_STATUS].copy()
    if df.empty:
        return df

    # effective due = revised_delivery_date if set, else po_delivery_date
    df["_due"] = df.apply(
        lambda r: coalesce_date(r.get("revised_delivery_date"),
                                r.get("po_delivery_date")),
        axis=1)
    today = date.today()
    df["_days_over"] = df["_due"].apply(
        lambda d: (today - d).days if d else None)

    # keep only rows genuinely past due
    df = df[df["_days_over"].apply(lambda x: x is not None and x > 0)]

    # exclude already-dispatched jobs IF a confirmed dispatch column exists
    if DISPATCH_DONE_COL and DISPATCH_DONE_COL in df:
        df = df[df[DISPATCH_DONE_COL].apply(lambda v: parse_date(v) is None)]

    if df.empty:
        return df

    out = pd.DataFrame({
        "Client":       col(df, "client_name"),
        "Project":      col(df, "project_description").apply(trunc),
        "Job no":       col(df, "job_no"),
        "PO no":        col(df, "po_no"),
        "Due date":     df["_due"],
        "Days overdue": df["_days_over"],
        "Priority":     col(df, "prod_priority"),
        "Anchor":       col(df, "anchor_person"),
    })
    out["Days overdue"] = pd.to_numeric(out["Days overdue"], errors="coerce")
    return out.sort_values("Days overdue", ascending=False,
                           na_position="last").reset_index(drop=True)


def _fu_frame(bucket: str) -> pd.DataFrame:
    df = get_followups_due()
    if df.empty or "bucket" not in df.columns:
        return pd.DataFrame()
    return df[df["bucket"] == bucket].copy()


def build_followups_due():
    """Quotes whose next chase is due today or overdue."""
    df = _fu_frame(BUCKET_DUE)
    if df.empty:
        return df

    # Coerce sort keys — mixed None/int object columns blow up sort_values.
    df["_overdue"] = pd.to_numeric(col(df, "days_until_due"), errors="coerce")
    df["_age"]     = pd.to_numeric(col(df, "quote_age_days"), errors="coerce")

    out = pd.DataFrame({
        "Client":       col(df, "client_name"),
        "Quote ref":    col(df, "quote_ref").apply(clean_ref),
        "Project":      col(df, "project_description").apply(trunc),
        "Est. value":   col(df, "estimated_value").apply(fmt_money),
        "Age":          df["_age"].apply(days_txt),
        "Attempts":     col(df, "attempts").apply(blank),
        "Last outcome": col(df, "last_outcome").apply(
                            lambda v: blank(v, "never contacted")),
        "Overdue by":   df["_overdue"].apply(
                            lambda v: days_txt(-v) if pd.notna(v) and v < 0
                            else "due today"),
        "Anchor":       col(df, "anchor_person"),
        "Contact":      df.apply(contact_txt, axis=1),
        "_sort":        df["_overdue"],
    })
    out = out.sort_values("_sort", ascending=True, na_position="last")
    return out.drop(columns=["_sort"]).reset_index(drop=True)


def build_decision_gate():
    """Quotes past the 90-day gate — these should be Won or Lost by now."""
    df = _fu_frame(BUCKET_GATE)
    if df.empty:
        return df

    df["_age"] = pd.to_numeric(col(df, "quote_age_days"), errors="coerce")

    def verdict(r):
        outcome = str(r.get("last_outcome") or "").strip().lower()
        att     = pd.to_numeric(r.get("attempts"), errors="coerce")
        att     = int(att) if pd.notna(att) else 0
        if att == 0:
            return "Never chased \u2014 one last attempt"
        if outcome in ("", "no response", "none"):
            return f"No response in {att} tries \u2014 mark Lost"
        if outcome == "declined":
            return "Declined \u2014 mark Lost"
        return "Responded \u2014 chase to a decision"

    out = pd.DataFrame({
        "Client":       col(df, "client_name"),
        "Quote ref":    col(df, "quote_ref").apply(clean_ref),
        "Project":      col(df, "project_description").apply(trunc),
        "Est. value":   col(df, "estimated_value").apply(fmt_money),
        "Age":          df["_age"].apply(days_txt),
        "Attempts":     col(df, "attempts").apply(blank),
        "Last outcome": col(df, "last_outcome").apply(
                            lambda v: blank(v, "never contacted")),
        "Suggested":    df.apply(verdict, axis=1),
        "Anchor":       col(df, "anchor_person"),
        "_sort":        df["_age"],
    })
    out = out.sort_values("_sort", ascending=False, na_position="last")
    return out.drop(columns=["_sort"]).reset_index(drop=True)


def build_followup_gaps():
    """Rows the cadence can't act on until someone fixes the data."""
    df = get_followups_due()
    if df.empty or "bucket" not in df.columns:
        return pd.DataFrame()

    gaps = df[df["bucket"].isin([BUCKET_NO_PHONE, BUCKET_NO_DATE,
                                 BUCKET_DUP])].copy()
    if gaps.empty:
        return gaps

    fix = {
        BUCKET_NO_PHONE: "Add a contact person or phone in the Anchor Portal",
        BUCKET_NO_DATE:  "Set a Quote Date \u2014 no clock, no cadence",
        BUCKET_DUP:      "Duplicate of an open quote \u2014 mark one Lost",
    }
    out = pd.DataFrame({
        "Problem":    gaps["bucket"],
        "Client":     col(gaps, "client_name"),
        "Quote ref":  col(gaps, "quote_ref").apply(clean_ref),
        "Quote date": col(gaps, "quote_date").apply(blank),
        "Anchor":     col(gaps, "anchor_person"),
        "Fix":        gaps["bucket"].map(fix),
    })
    return out.sort_values(["Problem", "Client"]).reset_index(drop=True)


# ----------------------------------------------------------------------
# PAGE
# ----------------------------------------------------------------------
st.title("\U0001F4CB Quick Reports")
st.caption(f"Live snapshot \u00B7 {datetime.now().strftime('%d %b %Y, %I:%M %p')}")

if st.button("\U0001F504 Refresh data"):
    st.cache_data.clear()
    st.rerun()

# ---- 1. Absent Today ----
with st.expander("\U0001F64B  Absent Today", expanded=True):
    try:
        df_abs, absent_n, leave_n = build_absent_today()
        m1, m2 = st.columns(2)
        m1.metric("Absent (unexplained)", absent_n)
        m2.metric("On approved leave", leave_n)
        if df_abs.empty:
            st.success("Everyone on the staff list has punched in today.")
        else:
            st.dataframe(df_abs, use_container_width=True, hide_index=True)
        st.caption(f"Roster source: `{STAFF_TABLE}`")
    except Exception as e:
        st.warning(f"Could not build Absent Today: {e}")

# ---- 2. Pending Quotes ----
with st.expander("\U0001F4E8  Pending Quotes  (Quotation Sent)", expanded=True):
    try:
        df_pq = build_pending_quotes()
        st.metric("Open quotes awaiting a decision", len(df_pq))
        if df_pq.empty:
            st.info("No quotes are currently in 'Quotation Sent'.")
        else:
            st.dataframe(df_pq, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Pending Quotes: {e}")

# ---- 3. Open Enquiries ----
with st.expander("\U0001F4E5  Open Enquiries  (not yet quoted)", expanded=True):
    try:
        df_oe = build_open_enquiries()
        st.metric("Enquiries awaiting a quote", len(df_oe))
        if df_oe.empty:
            st.info("No enquiries are currently open.")
        else:
            st.dataframe(df_oe, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Open Enquiries: {e}")

# ---- 4. Overdue Jobs ----
with st.expander("\u23F0  Overdue Jobs  (Won, past delivery date)", expanded=True):
    try:
        df_od = build_overdue_jobs()
        st.metric("Jobs past their delivery date", len(df_od))
        if df_od.empty:
            st.success("No Won jobs are past their delivery date.")
        else:
            if DISPATCH_DONE_COL is None:
                st.caption(
                    "\u26A0\uFE0F No dispatch/completion signal exists in the "
                    "database, so already-dispatched jobs still appear here. "
                    "Treat this list as a superset."
                )
            st.dataframe(df_od, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Overdue Jobs: {e}")

# ---- 5. Follow-ups Due ----
with st.expander("\U0001F4DE  Follow-ups Due  (quotations)", expanded=True):
    try:
        df_all = get_followups_due()
        if df_all.empty:
            st.info(
                "No data from `v_ap_followups_due`. If you haven't run "
                "`quote_followups_schema_v2.sql` yet, do that first. If you "
                "have, check the view is exposed to the API role:  "
                "`grant select on v_ap_followups_due to anon, authenticated;`"
            )
        else:
            df_fu  = build_followups_due()
            never  = int((pd.to_numeric(col(df_all, "attempts"),
                                        errors="coerce").fillna(0) == 0).sum())
            m1, m2, m3 = st.columns(3)
            m1.metric("Due for a chase", len(df_fu))
            m2.metric("Open quotations", len(df_all))
            m3.metric("Never contacted", never)

            if df_fu.empty:
                st.success("Nothing due today. Every open quote is on schedule.")
            else:
                st.dataframe(df_fu, use_container_width=True, hide_index=True)
                st.caption(
                    "Log the call in the Anchor Portal (Pipeline tab) once "
                    "you've made it \u2014 that's what moves the next due date."
                )
    except Exception as e:
        st.warning(f"Could not build Follow-ups Due: {e}")

# ---- 6. Decision Gate ----
with st.expander(f"\u2696\uFE0F  Decision Gate  ({DECISION_GATE_DAY}+ days old)",
                 expanded=True):
    try:
        df_gate = build_decision_gate()
        st.metric("Quotes past the gate", len(df_gate))
        if df_gate.empty:
            st.success("No quotations have aged past the decision gate.")
        else:
            st.warning(
                "These have been open longer than a normal decision cycle. "
                "Each should move to Won or Lost, or carry a written reason "
                "for staying open."
            )
            st.dataframe(df_gate, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Decision Gate: {e}")

# ---- 7. Follow-up data gaps ----
with st.expander("\U0001F9F9  Follow-up data gaps", expanded=False):
    try:
        df_gaps = build_followup_gaps()
        if df_gaps.empty:
            st.success("No blocked rows \u2014 every open quote is actionable.")
        else:
            st.caption(
                "These open quotations are invisible to the follow-up cadence "
                "until the underlying data is fixed."
            )
            st.dataframe(df_gaps, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build data gaps: {e}")
