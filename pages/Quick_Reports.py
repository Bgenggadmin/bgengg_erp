# pages/14_Quick_Reports.py
# ======================================================================
# B&G Engineering ERP — Quick Reports
#
# Five read-only reports across three source systems.
#
# WORKFORCE — master_staff / attendance_logs / leave_requests:
#   0. Absent Today      — on the roster, no punch-in yet today
#
# MATERIAL — Material Command Center
#            (indent_headers / purchase_orders / grn_receipts):
#   1. Pending Material  — indented, no PO raised yet
#   2. Pending Orders    — PO raised, not yet fully received
#
# QUOTATIONS — Anchor Portal (anchor_projects / quote_followups):
#   3. Quotations Sent    — issued to the client, awaiting a decision.
#                           Shows follow-up state and what to chase today.
#   4. Quotations Pending — enquiry logged, quote NOT yet issued.
#
# The old anchor_projects.material_shortage and bg_job_master.is_shortage
# signals are legacy and are deliberately NOT read here.
#
# Report 0 reads the view v_qr_absent_today. ALL of its logic lives in
# SQL — the roster table (master_staff, NOT the empty bg_staff_master),
# the placeholder/Admin exclusions, and the approved-leave labels. This
# page does no filtering of its own, so it cannot drift from the view.
# Reportable roster = 15 (19 rows less Driver / Freelancer / test / Admin).
# Admin is the founder's login and must never be deleted from
# master_staff — get_staff_list() in bg_workforce_erp.py builds the user
# selector from it. Excluded in the view, not in the table.
#
# Report 3 reads the view v_ap_followups_due, which computes the
# follow-up cadence in SQL so this page and the Monday Cowork brief can
# never disagree. Run quote_followups_schema.sql before deploying.
# Follow-ups are LOGGED in 01_Anchor_Portal.py (Pipeline tab) — this page
# only reports. If nobody logs a call, every quote reads "Due" forever.
#
# >>> This file replaces pages/15_Material_Status.py. Delete that file,
# >>> or the material reports render twice in the sidebar.
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
# PASSWORD GATE — currently off.
# To restore it, un-comment this block:
#
# def check_password() -> bool:
#     def _verify():
#         if st.session_state.get("qr_password") == st.secrets.get("APP_PASSWORD"):
#             st.session_state["password_correct"] = True
#             st.session_state.pop("qr_password", None)
#         else:
#             st.session_state["password_correct"] = False
#
#     if st.session_state.get("password_correct"):
#         return True
#     st.text_input("\U0001F511 Enter Master Password", type="password",
#                   on_change=_verify, key="qr_password")
#     if st.session_state.get("password_correct") is False:
#         st.error("\U0001F623 Password incorrect")
#     return False
#
# if not check_password():
#     st.stop()
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# DATABASE CONNECTION
# ----------------------------------------------------------------------
conn = st.connection("supabase", type=SupabaseConnection)

# ----------------------------------------------------------------------
# CONFIG — WORKFORCE
# The view name only. Roster source, exclusions and the approved-leave
# labels (Approved / Sanctioned / Granted, case-insensitive) are all
# defined inside v_qr_absent_today — do not re-declare them here.
# ----------------------------------------------------------------------
ABSENT_VIEW = "v_qr_absent_today"

# ----------------------------------------------------------------------
# CONFIG — MATERIAL  —  >>> CONFIRM THESE MATCH YOUR DATA <<<
# purchase_orders.status values, exactly as the Command Center writes them.
# ----------------------------------------------------------------------
STATUS_AWAITING_PO = "Triggered"   # indented, no PO yet
STATUS_MID_EDIT    = "Editing"     # locked by an in-progress edit -> hidden
                                   # from the Purchase Console, so it stalls
STATUS_ORDERED     = "Ordered"     # PO placed, nothing received
STATUS_PARTIAL     = "Partial"     # PO placed, part-received

MATERIAL_AGE_WARN = 3    # days an indent can sit with no PO before we tag it
TRUNC             = 55   # item-name truncation length

# ----------------------------------------------------------------------
# CONFIG — QUOTATIONS  —  >>> CONFIRM THESE MATCH YOUR DATA <<<
# anchor_projects.status values, confirmed:
#   Enquiry (3) / Quotation Sent (46) / Won (45) / Lost (17)
# ----------------------------------------------------------------------
# Quote not yet issued to the client. 'Estimation' is in PIPELINE_STAGES
# in 01_Anchor_Portal.py but currently has zero rows — included so the
# report doesn't silently miss them once estimation starts being used.
NOT_YET_QUOTED = ["Enquiry", "Estimation"]

# Days an enquiry can sit without a quote before it's flagged. A working
# assumption, not a measured number — adjust once you know your real
# estimation turnaround.
QUOTE_AGE_WARN = 7

# Follow-up view. The cadence ladder lives in SQL; these are display
# labels only — change them ONLY if you change the view's CASE expression.
FOLLOWUP_VIEW    = "v_ap_followups_due"
BUCKET_DUE       = "Due"
BUCKET_SCHEDULED = "Scheduled"
BUCKET_GATE      = "Decision gate"
BUCKET_NO_PHONE  = "No contact details"
BUCKET_NO_DATE   = "No quote date"
BUCKET_DUP       = "Duplicate row"

# Sort priority — what needs a human first.
BUCKET_ORDER = {
    BUCKET_GATE:      0,
    BUCKET_DUE:       1,
    BUCKET_NO_PHONE:  2,
    BUCKET_NO_DATE:   3,
    BUCKET_DUP:       4,
    BUCKET_SCHEDULED: 5,
}

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


def fmt_date(val) -> str:
    d = parse_date(val)
    return d.strftime("%d-%m-%Y") if d else "\u2014"


def trunc(text, n: int = TRUNC) -> str:
    if not text:
        return ""
    text = str(text)
    return text[:n] + ("\u2026" if len(text) > n else "")


def is_true(v) -> bool:
    """Supabase sometimes hands booleans back as text. Normalise."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "t", "yes", "1")


def num(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        return default if pd.isna(f) else f
    except (TypeError, ValueError):
        return default


def blank(v) -> str:
    """Render nulls as an em-dash instead of NaN / None."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "\u2014"
    s = str(v).strip()
    if s.lower() in ("nan", "none", "nat", ""):
        return "\u2014"
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s


def days_ago(val):
    """Days since a timestamp/date value. None if unparseable."""
    d = parse_date(val)
    return (date.today() - d).days if d else None


def days_late(val):
    """Positive = overdue by N days. Negative = N days still to run."""
    d = parse_date(val)
    return (date.today() - d).days if d else None


# ---- added for the quotation reports ---------------------------------
def fmt_money(v) -> str:
    """NaN survives float(), so it must be checked explicitly or nulls
    render as 'Rs nan'. estimated_value is null on several open quotes."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "\u2014"
    return "\u2014" if pd.isna(f) else f"\u20B9 {f:,.0f}"


def col(df: pd.DataFrame, name: str, default=None) -> pd.Series:
    """Fetch a column that may not exist, without exploding.
    df.get() returns None for a missing column, which then blows up
    inside pd.DataFrame({...}); this returns an aligned Series instead."""
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index)


def days_txt(v, suffix: str = "d") -> str:
    n = pd.to_numeric(v, errors="coerce")
    return f"{int(n)}{suffix}" if pd.notna(n) else "\u2014"


def outcome_txt(v) -> str:
    """blank() but with a meaningful placeholder for an empty history."""
    s = blank(v)
    return "never contacted" if s == "\u2014" else s


def contact_txt(row) -> str:
    """NaN is truthy, so str(v or '') yields the literal 'nan' on null
    columns. Route through blank() instead."""
    person = blank(row.get("contact_person"))
    phone  = blank(row.get("contact_phone"))
    person = "" if person == "\u2014" else person
    phone  = "" if phone  == "\u2014" else phone
    if person and phone:
        return f"{person} \u00B7 {phone}"
    return person or phone or "\u26A0\uFE0F none"

# ----------------------------------------------------------------------
# DATA ACCESS LAYER
# ----------------------------------------------------------------------
@st.cache_data(ttl=30)
def get_absent_today() -> pd.DataFrame:
    """Roster rows with no attendance_logs entry for today (IST).
    Columns: name, role, absence_type ('Absent' / 'On leave').
    Empty frame if the view hasn't been created yet."""
    res = conn.table(ABSENT_VIEW).select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def get_open_purchase_orders() -> pd.DataFrame:
    """Every purchase_orders row that is not finished or dead."""
    res = (conn.table("purchase_orders").select("*")
           .in_("status", [STATUS_AWAITING_PO, STATUS_MID_EDIT,
                           STATUS_ORDERED, STATUS_PARTIAL])
           .order("created_at", desc=True)
           .limit(500).execute())
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def get_grn_totals() -> pd.DataFrame:
    """Total received qty per purchase_orders.id, from the GRN desk."""
    res = conn.table("grn_receipts").select("po_id, received_qty").execute()
    df = pd.DataFrame(res.data) if res.data else pd.DataFrame()
    if df.empty or "po_id" not in df:
        return pd.DataFrame(columns=["po_id", "received_qty"])
    df["received_qty"] = df["received_qty"].apply(num)
    return df.groupby("po_id", as_index=False)["received_qty"].sum()


@st.cache_data(ttl=30)
def get_followups() -> pd.DataFrame:
    """
    Every 'Quotation Sent' row with cadence state already computed:
    attempts, last_outcome, due_date, quote_age_days, bucket.
    Empty frame if the view hasn't been created yet.
    """
    res = conn.table(FOLLOWUP_VIEW).select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def get_projects() -> pd.DataFrame:
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

# ----------------------------------------------------------------------
# REPORT BUILDER — WORKFORCE
# ----------------------------------------------------------------------
def build_absent_today():
    """Not-yet-punched-in staff, split into Absent vs On leave.
    No filtering happens here — the view is the single source of truth."""
    df = get_absent_today()
    if df.empty:
        return pd.DataFrame(), 0, 0

    out = pd.DataFrame({
        "Name":   col(df, "name").apply(blank),
        "Role":   col(df, "role").apply(blank),
        "Status": col(df, "absence_type").apply(blank),
    })
    out = out.sort_values(["Status", "Name"]).reset_index(drop=True)

    absent_n = int((out["Status"] == "Absent").sum())
    leave_n  = int((out["Status"] == "On leave").sum())
    return out, absent_n, leave_n

# ----------------------------------------------------------------------
# REPORT BUILDERS — MATERIAL
# ----------------------------------------------------------------------
def build_pending_material():
    """Indented material with no PO yet, plus anything stuck mid-edit."""
    po = get_open_purchase_orders()
    if po.empty or "status" not in po:
        return pd.DataFrame(), 0, 0

    df = po[po["status"].astype(str).str.strip()
            .isin([STATUS_AWAITING_PO, STATUS_MID_EDIT])].copy()
    if df.empty:
        return pd.DataFrame(), 0, 0

    df["_urgent"] = df.get("is_urgent").apply(is_true) \
        if "is_urgent" in df else False
    df["_age"] = pd.to_numeric(
        df.get("created_at").apply(days_ago), errors="coerce") \
        if "created_at" in df else pd.NA
    df["_editing"] = df["status"].astype(str).str.strip() == STATUS_MID_EDIT

    def stage(r):
        if r["_editing"]:
            return "\u26A0\uFE0F Stuck in edit"
        if pd.notna(r["_age"]) and r["_age"] >= MATERIAL_AGE_WARN:
            return "Awaiting PO (aged)"
        return "Awaiting PO"

    def enquiry_flag(v):
        return "Sent" if (v is not None and not pd.isna(v)
                          and str(v).strip()) else "\u2014"

    out = pd.DataFrame({
        "Priority":     df["_urgent"].apply(lambda u: "\U0001F6A8" if u else ""),
        "Job(s)":       df.get("job_no").apply(blank),
        "Item":         df.get("item_name").apply(trunc),
        "Group":        df.get("material_group").apply(blank),
        "Qty":          df.apply(
                            lambda r: f"{num(r.get('quantity')):g} "
                                      f"{r.get('units') or ''}".strip(), axis=1),
        "Indent #":     df.get("indent_no").apply(blank),
        "Raised by":    df.get("triggered_by").apply(blank),
        "Indented":     df.get("created_at").apply(fmt_date),
        "Days waiting": df["_age"],
        "Enquiry":      df.get("enquiry_sent_at").apply(enquiry_flag)
                        if "enquiry_sent_at" in df else "\u2014",
        "Stage":        df.apply(stage, axis=1),
    })

    out = (out.assign(_u=df["_urgent"].values)
              .sort_values(["_u", "Days waiting"],
                           ascending=[False, False], na_position="last")
              .drop(columns="_u").reset_index(drop=True))

    awaiting_n = int((~df["_editing"]).sum())
    stuck_n    = int(df["_editing"].sum())
    return out, awaiting_n, stuck_n


def build_pending_orders():
    """POs placed but not closed: overdue first, with GRN balances."""
    po = get_open_purchase_orders()
    if po.empty or "status" not in po:
        return pd.DataFrame(), 0

    df = po[po["status"].astype(str).str.strip()
            .isin([STATUS_ORDERED, STATUS_PARTIAL])].copy()
    if df.empty:
        return pd.DataFrame(), 0

    grn  = get_grn_totals()
    recd = dict(zip(grn["po_id"], grn["received_qty"])) if not grn.empty else {}

    df["_ordered"] = df.get("quantity").apply(num)
    df["_recd"]    = df.get("id").apply(lambda i: num(recd.get(i, 0)))
    df["_bal"]     = (df["_ordered"] - df["_recd"]).clip(lower=0)
    df["_late"]    = pd.to_numeric(
        df.get("expected_delivery").apply(days_late), errors="coerce") \
        if "expected_delivery" in df else pd.NA
    df["_urgent"]  = df.get("is_urgent").apply(is_true) \
        if "is_urgent" in df else False

    def late_label(d):
        if d is None or pd.isna(d):
            return "\U0001F7E1 No date"
        d = int(d)
        if d > 0:
            return f"\U0001F534 {d}d late"
        if d == 0:
            return "\U0001F7E0 Due today"
        return f"\U0001F7E2 {abs(d)}d to go"

    out = pd.DataFrame({
        "Priority": df["_urgent"].apply(lambda u: "\U0001F6A8" if u else ""),
        "Job(s)":   df.get("job_no").apply(blank),
        "Item":     df.get("item_name").apply(trunc),
        "PO no":    df.get("po_no").apply(blank),
        "Vendor":   df.get("purchase_reply").apply(blank),
        "PO date":  df.get("po_date").apply(fmt_date),
        "Expected": df.get("expected_delivery").apply(fmt_date),
        "Delivery": df["_late"].apply(late_label),
        "Ordered":  df.apply(lambda r: f"{r['_ordered']:g}", axis=1),
        "Received": df.apply(lambda r: f"{r['_recd']:g}", axis=1),
        "Balance":  df.apply(
                        lambda r: f"{r['_bal']:g} "
                                  f"{r.get('units') or ''}".strip(), axis=1),
        "Status":   df.get("status"),
    })

    out = (out.assign(_u=df["_urgent"].values, _l=df["_late"].values)
              .sort_values(["_u", "_l"],
                           ascending=[False, False], na_position="last")
              .drop(columns=["_u", "_l"]).reset_index(drop=True))

    overdue_n = int((pd.to_numeric(df["_late"], errors="coerce") > 0).sum())
    return out, overdue_n

# ----------------------------------------------------------------------
# REPORT BUILDERS — QUOTATIONS
# ----------------------------------------------------------------------
def build_quotations_sent():
    """
    Every open quotation with its follow-up state, action-needed first.
    Returns (table, counts dict).
    """
    df = get_followups()
    if df.empty or "bucket" not in df:
        return pd.DataFrame(), {}

    df = df.copy()
    df["_age"]  = pd.to_numeric(col(df, "quote_age_days"), errors="coerce")
    df["_over"] = pd.to_numeric(col(df, "days_until_due"), errors="coerce")
    df["_rank"] = df["bucket"].map(BUCKET_ORDER).fillna(9)

    def action(r):
        b = r["bucket"]
        if b == BUCKET_GATE:
            att = int(num(r.get("attempts")))
            return ("Decide: Won or Lost" if att
                    else "Never chased \u2014 last attempt")
        if b == BUCKET_DUE:
            o = r["_over"]
            return (f"Chase \u2014 {int(-o)}d overdue"
                    if pd.notna(o) and o < 0 else "Chase today")
        if b == BUCKET_NO_PHONE:
            return "Add contact details"
        if b == BUCKET_NO_DATE:
            return "Set a quote date"
        if b == BUCKET_DUP:
            return "Duplicate \u2014 mark one Lost"
        return f"Next: {fmt_date(r.get('due_date'))}"

    out = pd.DataFrame({
        "Stage":        df["bucket"].apply(blank),
        "Action":       df.apply(action, axis=1),
        "Client":       col(df, "client_name"),
        "Quote ref":    col(df, "quote_ref").apply(blank),
        "Project":      col(df, "project_description").apply(trunc),
        "Est. value":   col(df, "estimated_value").apply(fmt_money),
        "Quote date":   col(df, "quote_date").apply(fmt_date),
        "Age":          df["_age"].apply(days_txt),
        "Attempts":     col(df, "attempts").apply(blank),
        "Last outcome": col(df, "last_outcome").apply(outcome_txt),
        "Anchor":       col(df, "anchor_person").apply(blank),
        "Contact":      df.apply(contact_txt, axis=1),
    })

    out = (out.assign(_r=df["_rank"].values, _a=df["_age"].values)
              .sort_values(["_r", "_a"], ascending=[True, False],
                           na_position="last")
              .drop(columns=["_r", "_a"]).reset_index(drop=True))

    attempts = pd.to_numeric(col(df, "attempts"), errors="coerce").fillna(0)
    counts = {
        "total":   len(df),
        "due":     int((df["bucket"] == BUCKET_DUE).sum()),
        "gate":    int((df["bucket"] == BUCKET_GATE).sum()),
        "never":   int((attempts == 0).sum()),
        "blocked": int(df["bucket"].isin(
                       [BUCKET_NO_PHONE, BUCKET_NO_DATE, BUCKET_DUP]).sum()),
        "value":   float(pd.to_numeric(col(df, "estimated_value"),
                                       errors="coerce").fillna(0).sum()),
    }
    return out, counts


def build_quotations_pending():
    """Enquiries logged but no quote issued yet."""
    proj = get_projects()
    if proj.empty or "status" not in proj:
        return pd.DataFrame(), 0

    df = proj[proj["status"].astype(str).str.strip()
              .isin(NOT_YET_QUOTED)].copy()
    if df.empty:
        return pd.DataFrame(), 0

    df["_wait"] = pd.to_numeric(
        col(df, "enquiry_date").apply(days_ago), errors="coerce")

    def flag(w):
        if pd.isna(w):
            return "\u26A0\uFE0F No enquiry date"
        return (f"\U0001F534 {int(w)}d waiting" if w >= QUOTE_AGE_WARN
                else f"\U0001F7E2 {int(w)}d")

    out = pd.DataFrame({
        "Waiting":      df["_wait"].apply(flag),
        "Client":       col(df, "client_name"),
        "Project":      col(df, "project_description").apply(trunc),
        "Stage":        col(df, "status").apply(blank),
        "Enquiry date": col(df, "enquiry_date").apply(fmt_date),
        "Est. value":   col(df, "estimated_value").apply(fmt_money),
        "Drawing":      col(df, "drawing_status").apply(blank),
        "Contact":      df.apply(contact_txt, axis=1),
        "Anchor":       col(df, "anchor_person").apply(blank),
    })

    out = (out.assign(_s=df["_wait"].values)
              .sort_values("_s", ascending=False, na_position="first")
              .drop(columns="_s").reset_index(drop=True))

    aged_n = int((df["_wait"] >= QUOTE_AGE_WARN).sum())
    return out, aged_n

# ----------------------------------------------------------------------
# PAGE
# ----------------------------------------------------------------------
st.title("\U0001F4CB Quick Reports")
st.caption(f"Live snapshot \u00B7 {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
           " \u00B7 sources: Workforce \u00B7 Material Command Center"
           " \u00B7 Anchor Portal")

if st.button("\U0001F504 Refresh data"):
    st.cache_data.clear()
    st.rerun()

st.subheader("Workforce")

# ---- 0. Absent Today (roster vs punch-ins) ----
with st.expander("\U0001F64B  Absent Today  (no punch-in yet)", expanded=True):
    try:
        df_abs, absent_n, leave_n = build_absent_today()
        m1, m2 = st.columns(2)
        m1.metric("Absent (unexplained)", absent_n)
        m2.metric("On approved leave", leave_n)
        if df_abs.empty:
            st.success("Everyone on the roster has punched in today.")
        else:
            st.dataframe(df_abs, use_container_width=True, hide_index=True)
        st.caption(
            "Live against today's punch-ins \u2014 before the shift starts "
            "this correctly lists the whole roster. Read it after "
            "start-of-day. Roster excludes the Driver / Freelancer / test "
            "placeholders and the Admin login."
        )
    except Exception as e:
        st.warning(
            f"Could not build Absent Today: {e}  \n"
            f"If `{ABSENT_VIEW}` is missing, run qr_views_patch_02.sql. "
            f"If it exists but errors, check: "
            f"`grant select on {ABSENT_VIEW} to anon, authenticated;`"
        )

st.subheader("Material")

# ---- 1. Pending Material (indented, not yet ordered) ----
with st.expander("\U0001F4E6  Pending Material  (indented, no PO yet)",
                 expanded=True):
    try:
        df_pm, awaiting_n, stuck_n = build_pending_material()
        m1, m2 = st.columns(2)
        m1.metric("Awaiting a PO", awaiting_n)
        m2.metric("Stuck in edit", stuck_n)
        if stuck_n:
            st.warning(
                f"{stuck_n} item(s) are in 'Editing' \u2014 the Purchase "
                "Console hides these, so they will not be actioned until "
                "someone resumes or resets them in the Indent tab."
            )
        if df_pm.empty:
            st.success("No indented material is waiting for a PO.")
        else:
            st.dataframe(df_pm, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Pending Material: {e}")

# ---- 2. Pending Orders (PO placed, not fully received) ----
with st.expander("\U0001F69A  Pending Orders  (PO placed, not received)",
                 expanded=True):
    try:
        df_po, overdue_n = build_pending_orders()
        m1, m2 = st.columns(2)
        m1.metric("Open POs", len(df_po))
        m2.metric("Past expected delivery", overdue_n,
                  delta=f"{overdue_n} late" if overdue_n else None,
                  delta_color="inverse")
        if df_po.empty:
            st.success("No open purchase orders awaiting delivery.")
        else:
            st.dataframe(df_po, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Pending Orders: {e}")

st.subheader("Quotations")

# ---- 3. Quotations Sent (follow-up) ----
with st.expander("\U0001F4DE  Quotations Sent  \u2014 follow-up", expanded=True):
    try:
        df_sent, c = build_quotations_sent()
        if df_sent.empty:
            st.info(
                f"No data from `{FOLLOWUP_VIEW}`. Run "
                "`quote_followups_schema.sql` first. If you already have, "
                "check the view is readable by the API role:  "
                f"`grant select on {FOLLOWUP_VIEW} to anon, authenticated;`"
            )
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Chase today", c["due"])
            m2.metric("Past 90 days", c["gate"])
            m3.metric("Never contacted", c["never"])
            m4.metric("Open quotations", c["total"])
            st.caption(
                f"\u20B9 {c['value']:,.0f} of quoted value open \u00B7 "
                f"{c['blocked']} row(s) blocked on missing data"
            )
            st.dataframe(df_sent, use_container_width=True, hide_index=True)
            st.caption(
                "Sorted by what needs a human first. Log the call in the "
                "Anchor Portal (Pipeline tab) once you've made it \u2014 that "
                "is what advances the next due date."
            )
    except Exception as e:
        st.warning(f"Could not build Quotations Sent: {e}")

# ---- 4. Quotations Pending (not yet sent) ----
with st.expander("\u270D\uFE0F  Quotations Pending  (not yet sent to client)",
                 expanded=True):
    try:
        df_pend, aged_n = build_quotations_pending()
        m1, m2 = st.columns(2)
        m1.metric("Awaiting a quote", len(df_pend))
        m2.metric(f"Waiting {QUOTE_AGE_WARN}+ days", aged_n,
                  delta=f"{aged_n} aged" if aged_n else None,
                  delta_color="inverse")
        if df_pend.empty:
            st.success("Every logged enquiry has been quoted.")
        else:
            st.dataframe(df_pend, use_container_width=True, hide_index=True)
            st.caption(
                "Statuses counted as not-yet-quoted: "
                + ", ".join(f"`{s}`" for s in NOT_YET_QUOTED)
            )
    except Exception as e:
        st.warning(f"Could not build Quotations Pending: {e}")
