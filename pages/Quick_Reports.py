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
#
# Reports:
#   1. Absent Today          5. Material Shortages
#   2. Pending Quotes        6. Pending Enquiries   (purchase pipeline)
#   3. Open Enquiries        7. Pending Orders      (purchase pipeline)
#   4. Overdue Jobs
#
# To add a report later: write one build_* function + one expander
# block. That's it.
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
PENDING_QUOTE_STATUS = "Quotation Sent"   # anchor_projects.status — live quotes (confirmed)
ENQUIRY_STATUS       = "Enquiry"          # anchor_projects.status — pre-quote (confirmed)

# leave_requests.status value(s) that mean "granted". I'm guessing here —
# run:  select distinct status from leave_requests;
# and put the real approved label(s) below. Matching is case-insensitive.
APPROVED_LEAVE_STATUSES = ["Approved", "Sanctioned", "Granted"]

# --- Staff roster -----------------------------------------------------
# CONFIRMED 15-Aug-2026: bg_staff_master is EMPTY (0 rows); the live
# roster is master_staff (19 rows). This report silently reported
# "everyone present" for its entire life before this was caught.
# master_staff columns: id, name, role, contact_no, created_at, phone, email
# NOTE: no department column, and no active/inactive flag — leavers will
# show as absent forever until one is added.
STAFF_TABLE = "master_staff"

# Rows in master_staff that aren't a person. Without this they show as
# absent every single day and train everyone to ignore the report.
# Confirmed: 'Driver', 'Freelancer' and 'test' have never punched in.
# 'Admin' does punch in, so it is NOT excluded.
NON_STAFF_NAMES = ["Driver", "Freelancer", "test"]

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

# --- Purchase pipeline (reports 6 & 7) ------------------------------
# Statuses derived from material_command_center.py, which is the only
# writer of purchase_orders: Triggered / Editing / Ordered / Partial /
# Received / Rejected.
# >>> CONFIRM <<<  run:  select distinct status from purchase_orders;
# A stray legacy value here silently drops rows from both reports.
AWAITING_ENQUIRY_STATUSES = ["Triggered", "Editing"]   # raised, no vendor enquiry sent yet
OPEN_ORDER_STATUSES       = ["Ordered", "Partial"]     # PO placed, material not fully in

# rate_enquiries.status — 'Pending' on insert, 'Quoted' once a rate is saved.
RATE_ENQ_PENDING_STATUS = "Pending"

# Column recording "we sent this to a vendor". Null = not sent yet.
ENQUIRY_SENT_COL = "enquiry_sent_at"

# How far back to pull purchase rows. Anything older than this that's
# still open is almost certainly abandoned data, not a live item.
PURCHASE_LOOKBACK_DAYS = 180

# Rejected items sitting unrevised are arguably "pending" too. Flip to
# True to surface them in the awaiting-enquiry table.
INCLUDE_REJECTED_AS_PENDING = False

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

def is_blank(v) -> bool:
    """True for None / NaN / NaT / empty-ish strings."""
    try:
        if pd.isna(v):
            return True
    except (TypeError, ValueError):
        pass
    return str(v).strip() in ("", "None", "NaT", "nan")

def col(df: pd.DataFrame, name: str, default=None) -> pd.Series:
    """df[name], or a same-length Series of `default` if the column is
    absent. Stops one missing column blanking a whole report."""
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index)

def clean_trunc(v) -> str:
    """trunc() but NaN-safe — bare trunc(nan) returns the string 'nan'."""
    return "" if is_blank(v) else trunc(v)

def fmt_date(val) -> str:
    d = parse_date(val)
    return d.strftime("%d-%m-%Y") if d else "\u2014"

def fmt_qty(q, units) -> str:
    try:
        s = f"{float(q):g}"
    except (TypeError, ValueError):
        s = "\u2014"
    u = "" if is_blank(units) else str(units)
    return f"{s} {u}".strip()

def to_num(v, default=0.0) -> float:
    n = pd.to_numeric(v, errors="coerce")
    return float(n) if pd.notna(n) else default

def as_int_col(s: pd.Series) -> pd.Series:
    """Whole-number day counts, blanks left blank (no 12.0 / NaN)."""
    return pd.to_numeric(s, errors="coerce").astype("Int64")

# ----------------------------------------------------------------------
# DATA ACCESS LAYER  (your conn.table(...).select(...).execute() idiom)
# ----------------------------------------------------------------------
@st.cache_data(ttl=30)
def get_staff() -> pd.DataFrame:
    res = conn.table(STAFF_TABLE).select("*").execute()
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

@st.cache_data(ttl=30)
def get_open_purchase_items() -> pd.DataFrame:
    """All live purchase_orders rows: pre-enquiry AND on-order, one fetch.

    Note purchase_orders holds indent LINE ITEMS from the moment they're
    raised (status 'Triggered', no PO yet); the same row later becomes
    the PO. It is not a table of purchase orders only."""
    cutoff = (date.today() - timedelta(days=PURCHASE_LOOKBACK_DAYS)).isoformat()
    wanted = list(AWAITING_ENQUIRY_STATUSES) + list(OPEN_ORDER_STATUSES)
    if INCLUDE_REJECTED_AS_PENDING:
        wanted.append("Rejected")
    res = (conn.table("purchase_orders").select("*")
           .in_("status", wanted)
           .gte("created_at", f"{cutoff}T00:00:00")
           .order("created_at", desc=True)
           .limit(500)
           .execute())
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

@st.cache_data(ttl=30)
def get_pending_rate_enquiries() -> pd.DataFrame:
    res = (conn.table("rate_enquiries").select("*")
           .eq("status", RATE_ENQ_PENDING_STATUS)
           .order("created_at", desc=True)
           .limit(200)
           .execute())
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

@st.cache_data(ttl=30)
def get_grn_for(po_ids: tuple) -> pd.DataFrame:
    """Receipts against the given purchase_orders.id values. Chunked,
    because .in_() with a few hundred ids can blow the URL length."""
    if not po_ids:
        return pd.DataFrame()
    frames = []
    ids = list(po_ids)
    for i in range(0, len(ids), 100):
        res = (conn.table("grn_receipts")
               .select("po_id, received_qty, received_date")
               .in_("po_id", ids[i:i + 100]).execute())
        if res.data:
            frames.append(pd.DataFrame(res.data))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

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

    skip = {norm(x) for x in NON_STAFF_NAMES}

    rows = []
    for _, r in staff.iterrows():
        nm = r.get("name")
        if norm(nm) in present or norm(nm) in skip:
            continue
        # NB: pandas turns a null phone into NaN, which is truthy — so
        # `r.get("phone") or r.get("contact_no")` silently returns NaN.
        phone = r.get("phone")
        if is_blank(phone):
            phone = r.get("contact_no")
        rows.append({
            "Name": nm,
            "Role": r.get("role"),
            "Phone": phone if not is_blank(phone) else "\u2014",
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


def build_pending_rate_enquiries():
    """Estimation asked Purchase for a rate; no rate entered yet."""
    re_df = get_pending_rate_enquiries()
    if re_df.empty:
        return pd.DataFrame()

    out = pd.DataFrame({
        "Item":         col(re_df, "item_name"),
        "Specs":        col(re_df, "specs", "").apply(clean_trunc),
        "Qty":          [fmt_qty(q, u) for q, u in
                         zip(col(re_df, "quantity"), col(re_df, "units"))],
        "Job":          col(re_df, "job_no", "").apply(
                            lambda v: "\u2014" if is_blank(v) else v),
        "Requested by": col(re_df, "requested_by"),
        "Raised":       col(re_df, "created_at").apply(fmt_date),
        "Days waiting": col(re_df, "created_at").apply(days_since),
    })
    out = out.sort_values("Days waiting", ascending=False,
                          na_position="last").reset_index(drop=True)
    out["Days waiting"] = as_int_col(out["Days waiting"])
    return out


def build_awaiting_vendor_enquiry():
    """Indent items raised but never sent out to a vendor.

    'Editing' rows are included deliberately: the Purchase Console hides
    them with .neq("status","Editing"), so a row abandoned mid-edit is
    invisible to purchase. Surfacing them here is the only safety net."""
    po = get_open_purchase_items()
    if po.empty or "status" not in po.columns:
        return pd.DataFrame()

    wanted = list(AWAITING_ENQUIRY_STATUSES)
    if INCLUDE_REJECTED_AS_PENDING:
        wanted.append("Rejected")
    df = po[po["status"].isin(wanted)].copy()
    if df.empty:
        return pd.DataFrame()

    df = df[col(df, ENQUIRY_SENT_COL).apply(is_blank)]
    if df.empty:
        return pd.DataFrame()

    out = pd.DataFrame({
        "!":            col(df, "is_urgent").apply(
                            lambda v: "\U0001F6A8" if is_true(v) else ""),
        "Indent #":     col(df, "indent_no"),
        "Item":         col(df, "item_name", "").apply(clean_trunc),
        "Group":        col(df, "material_group"),
        "Qty":          [fmt_qty(q, u) for q, u in
                         zip(col(df, "quantity"), col(df, "units"))],
        "Job":          col(df, "job_no"),
        "Raised by":    col(df, "triggered_by"),
        "Status":       col(df, "status"),
        "Indented":     col(df, "created_at").apply(fmt_date),
        "Days waiting": col(df, "created_at").apply(days_since),
    })
    out = out.sort_values("Days waiting", ascending=False,
                          na_position="last").reset_index(drop=True)
    out["Days waiting"] = as_int_col(out["Days waiting"])
    return out


def build_pending_orders():
    """PO placed, material not fully received. Returns (df, overdue_count)."""
    po = get_open_purchase_items()
    if po.empty or "status" not in po.columns:
        return pd.DataFrame(), 0

    df = po[po["status"].isin(OPEN_ORDER_STATUSES)].copy()
    if df.empty:
        return pd.DataFrame(), 0

    # receipts so far, keyed by purchase_orders.id
    ids = tuple(df["id"].dropna().tolist()) if "id" in df.columns else ()
    grn = get_grn_for(ids)
    recd = {}
    if not grn.empty and "po_id" in grn.columns:
        g = grn.copy()
        g["received_qty"] = pd.to_numeric(g["received_qty"], errors="coerce").fillna(0)
        recd = g.groupby("po_id")["received_qty"].sum().to_dict()

    today = date.today()
    rows = []
    for _, r in df.iterrows():
        qty   = to_num(r.get("quantity"))
        got   = to_num(recd.get(r.get("id")), 0.0)
        bal   = max(0.0, qty - got)
        units = r.get("units")

        exp  = parse_date(r.get("expected_delivery"))
        late = (today - exp).days if exp else None
        # po_date is blank on anything confirmed before the Command Center
        # dates patch — fall back to the indent date so ageing still works.
        basis = parse_date(r.get("po_date")) or parse_date(r.get("created_at"))
        age   = (today - basis).days if basis else None

        rows.append({
            "!":          "\U0001F6A8" if is_true(r.get("is_urgent")) else "",
            "PO no":      r.get("po_no") if not is_blank(r.get("po_no")) else "\u2014",
            "Item":       clean_trunc(r.get("item_name")),
            "Job":        r.get("job_no"),
            "Vendor":     r.get("purchase_reply") if not is_blank(r.get("purchase_reply")) else "\u2014",
            "Ordered":    fmt_qty(qty, units),
            "Received":   fmt_qty(got, units),
            "Balance":    fmt_qty(bal, units),
            "Status":     r.get("status"),
            "Expected":   fmt_date(r.get("expected_delivery")),
            "Days late":  late if (late is not None and late > 0) else None,
            "Age (days)": age,
            "Indent #":   r.get("indent_no"),
        })

    out = pd.DataFrame(rows)
    out = out.sort_values(["Days late", "Age (days)"],
                          ascending=[False, False],
                          na_position="last").reset_index(drop=True)
    overdue_n = int(out["Days late"].notna().sum())
    out["Days late"]  = as_int_col(out["Days late"])
    out["Age (days)"] = as_int_col(out["Age (days)"])
    return out, overdue_n

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

# ---- Pending Enquiries ----
with st.expander("\U0001F4B0  Pending Enquiries  (nobody has asked a vendor yet)",
                 expanded=True):
    try:
        df_rate = build_pending_rate_enquiries()
        df_wait = build_awaiting_vendor_enquiry()

        e1, e2 = st.columns(2)
        e1.metric("Rate enquiries awaiting a quote", len(df_rate))
        e2.metric("Indent items not yet sent to a vendor", len(df_wait))

        st.markdown("**Rate enquiries \u2014 Estimation is waiting on Purchase**")
        if df_rate.empty:
            st.success("No rate enquiries pending.")
        else:
            st.dataframe(df_rate, use_container_width=True, hide_index=True)

        st.markdown("**Indent items \u2014 raised, but no vendor enquiry sent**")
        if df_wait.empty:
            st.success("Every open indent item has been sent out.")
        else:
            st.dataframe(df_wait, use_container_width=True, hide_index=True)
            st.caption(
                "Rows showing status 'Editing' are parked mid-edit and are "
                "hidden from the Purchase Console \u2014 chase or reset them."
            )
    except Exception as e:
        st.warning(f"Could not build Pending Enquiries: {e}")

# ---- Pending Orders ----
with st.expander("\U0001F69A  Pending Orders  (ordered, not yet fully received)",
                 expanded=True):
    try:
        df_po, overdue_n = build_pending_orders()

        o1, o2 = st.columns(2)
        o1.metric("Items on order", len(df_po))
        o2.metric("Past expected delivery", overdue_n,
                  delta=f"{overdue_n} late" if overdue_n else None,
                  delta_color="inverse")

        if df_po.empty:
            st.success("Nothing outstanding \u2014 all POs fully received.")
        else:
            st.dataframe(df_po, use_container_width=True, hide_index=True)
            st.caption(
                "'Expected' is blank on orders confirmed before the Command "
                "Center dates patch \u2014 those rows can't be flagged late. "
                "'Age (days)' falls back to the indent date so the list still "
                "sorts sensibly."
            )
    except Exception as e:
        st.warning(f"Could not build Pending Orders: {e}")
