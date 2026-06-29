# pages/14_Quick_Reports.py
# ======================================================================
# B&G Engineering ERP — Quick Reports
# A daily-driver "morning check" page: a few pre-defined, read-only
# reports. No free-text, no AI at runtime — fast and safe.
#
# Built to match the patterns already used in 01_Anchor_Portal.py:
#   - st_supabase_connection  (conn = st.connection("supabase", ...))
#   - @st.cache_data(ttl=30) on each fetch
#   - conn.table("...").select("*").execute()  query-builder style
#   - check_password() gate
#
# To add a 4th/5th report later: write one build_* function + one
# expander block. That's it.
# ======================================================================

import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import date, datetime

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
PENDING_QUOTE_STATUS = "Quotation Sent"   # anchor_projects.status — live quotes (confirmed)
ENQUIRY_STATUS       = "Enquiry"          # anchor_projects.status — pre-quote (confirmed)

# leave_requests.status value(s) that mean "granted". I'm guessing here —
# run:  select distinct status from leave_requests;
# and put the real approved label(s) below. Matching is case-insensitive.
APPROVED_LEAVE_STATUSES = ["Approved", "Sanctioned", "Granted"]

# --- Overdue Jobs ---------------------------------------------------
# A job is "overdue" when its effective delivery date (revised if set,
# else PO delivery date) is before today AND it's still a live order.
# "Live order" = status == 'Won' (Enquiry/Quotation Sent have no PO date;
# Lost is dead). Confirmed status values: Enquiry / Quotation Sent / Won / Lost.
OVERDUE_OPEN_STATUS = "Won"

# >>> CONFIRM <<<  Is there a column that marks a Won job as already
# dispatched / delivered / closed? (e.g. a dispatch_date / actual_delivery_date
# on anchor_projects, or a "Dispatched"/"Completed" value in
# bg_job_master.current_stage). I don't have one confirmed, so by default this
# report can include jobs that are already out the door.
# To fix: set DISPATCH_DONE_COL to that DATE column's name and rows with a
# value there will be excluded. Leave as None until confirmed.
DISPATCH_DONE_COL = None   # e.g. "dispatch_date"

TRUNC = 55  # description truncation length

# ----------------------------------------------------------------------
# HELPERS  (mirrors your safe_date / trunc)
# ----------------------------------------------------------------------
def parse_date(val):
    """Raw DB value -> python date, or None if unparseable."""
    try:
        parsed = pd.to_datetime(val)
        return parsed.date() if pd.notnull(parsed) else None
    except Exception:
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

def coalesce_date(*vals):
    """First parseable date among the args, else None."""
    for v in vals:
        d = parse_date(v)
        if d is not None:
            return d
    return None

def is_true(v) -> bool:
    """Truthy across a real bool or text 'true'/'t'/'yes'/'y'/'1'.
    Supabase booleans usually arrive as real bools, but guard for text."""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in {"true", "t", "yes", "y", "1"}

# ----------------------------------------------------------------------
# DATA ACCESS LAYER  (your conn.table(...).select(...).execute() idiom)
# ----------------------------------------------------------------------
@st.cache_data(ttl=30)
def get_staff() -> pd.DataFrame:
    res = conn.table("bg_staff_master").select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

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
def get_jobs() -> pd.DataFrame:
    res = conn.table("bg_job_master").select("*").execute()
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
            "Name": nm,
            "Department": r.get("department"),
            "Role": r.get("role"),
            "Status": "On leave" if norm(nm) in on_leave else "Absent",
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
        "Client":       df.get("client_name"),
        "Project":      df.get("project_description").apply(trunc),
        "Quote ref":    df.get("quote_ref"),
        "Quote date":   df.get("quote_date"),
        "Est. value":   df.get("estimated_value").apply(fmt_money),
        "Days pending": df.get("quote_date").apply(days_since),
        "Anchor":       df.get("anchor_person"),
    })
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
        "Client":       df.get("client_name"),
        "Project":      df.get("project_description").apply(trunc),
        "Enquiry date": df.get("enquiry_date"),
        "Days waiting": df.get("enquiry_date").apply(days_since),
        "Anchor":       df.get("anchor_person"),
    })
    return out.sort_values("Days waiting", ascending=False,
                           na_position="last").reset_index(drop=True)


def build_overdue_jobs():
    """Live ('Won') orders whose effective delivery date is in the past."""
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
        "Client":       df.get("client_name"),
        "Project":      df.get("project_description").apply(trunc),
        "Job no":       df.get("job_no"),
        "PO no":        df.get("po_no"),
        "Due date":     df["_due"],
        "Days overdue": df["_days_over"],
        "Priority":     df.get("prod_priority"),
        "Anchor":       df.get("anchor_person"),
    })
    return out.sort_values("Days overdue", ascending=False,
                           na_position="last").reset_index(drop=True)


def build_material_shortages():
    """Two independent sources (no join assumed):
       1) anchor_projects.material_shortage = true
       2) bg_job_master.is_shortage       = true
    Returns (projects_df, jobs_df)."""
    # --- source 1: anchor_projects ---
    proj = get_projects()
    proj_df = pd.DataFrame()
    if not proj.empty and "material_shortage" in proj:
        f = proj[proj["material_shortage"].apply(is_true)].copy()
        if not f.empty:
            proj_df = pd.DataFrame({
                "Client":  f.get("client_name"),
                "Project": f.get("project_description").apply(trunc),
                "Job no":  f.get("job_no"),
                "Details": (f.get("shortage_details").apply(trunc)
                            if "shortage_details" in f else ""),
                "Priority": f.get("prod_priority"),
                "Anchor":  f.get("anchor_person"),
            }).reset_index(drop=True)

    # --- source 2: bg_job_master ---
    jobs = get_jobs()
    jobs_df = pd.DataFrame()
    if not jobs.empty and "is_shortage" in jobs:
        g = jobs[jobs["is_shortage"].apply(is_true)].copy()
        if not g.empty:
            jobs_df = pd.DataFrame({
                "Job code": g.get("job_code"),
                "Customer": g.get("customer_name"),
                "Stage":    g.get("current_stage"),
            }).reset_index(drop=True)

    return proj_df, jobs_df

# ----------------------------------------------------------------------
# PAGE
# ----------------------------------------------------------------------
st.title("\U0001F4CB Quick Reports")
st.caption(f"Live snapshot \u00B7 {datetime.now().strftime('%d %b %Y, %I:%M %p')}")

if st.button("\U0001F504 Refresh data"):
    st.cache_data.clear()
    st.rerun()

# ---- Absent Today ----
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
    except Exception as e:
        st.warning(f"Could not build Absent Today: {e}")

# ---- Pending Quotes ----
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

# ---- Open Enquiries ----
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

# ---- Overdue Jobs ----
with st.expander("\u23F0  Overdue Jobs  (past delivery date)", expanded=True):
    try:
        df_od = build_overdue_jobs()
        st.metric("Open jobs past their delivery date", len(df_od))
        if df_od.empty:
            st.success("No open ('Won') jobs are past their delivery date.")
        else:
            st.dataframe(df_od, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Overdue Jobs: {e}")

# ---- Material Shortages ----
with st.expander("\U0001F4E6  Material Shortages", expanded=True):
    try:
        df_ms_proj, df_ms_jobs = build_material_shortages()
        m1, m2 = st.columns(2)
        m1.metric("Projects flagged (anchor_projects)", len(df_ms_proj))
        m2.metric("Jobs flagged (bg_job_master)", len(df_ms_jobs))
        if df_ms_proj.empty and df_ms_jobs.empty:
            st.success("No material shortages flagged in either table.")
        else:
            if not df_ms_proj.empty:
                st.markdown("**From anchor_projects**")
                st.dataframe(df_ms_proj, use_container_width=True, hide_index=True)
            if not df_ms_jobs.empty:
                st.markdown("**From bg_job_master**")
                st.dataframe(df_ms_jobs, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Material Shortages: {e}")
