# pages/15_Material_Status.py
# ======================================================================
# B&G Engineering ERP — Material Status
#
# Two read-only reports, sourced ONLY from the Material Command Center
# (indent_headers / purchase_orders / grn_receipts):
#   1. Pending Material  — indented, no PO raised yet
#   2. Pending Orders    — PO raised, not yet fully received
#
# The old anchor_projects.material_shortage and bg_job_master.is_shortage
# signals are legacy and are deliberately NOT read here.
# ======================================================================

import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import date, datetime

# ----------------------------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------------------------
st.set_page_config(page_title="Material Status | BGEngg ERP",
                   layout="wide", page_icon="\U0001F4E6")

# ----------------------------------------------------------------------
# PASSWORD GATE — currently off, matching 14_Quick_Reports.py.
# To restore it, un-comment this block:
#
# def check_password() -> bool:
#     def _verify():
#         if st.session_state.get("ms_password") == st.secrets.get("APP_PASSWORD"):
#             st.session_state["password_correct"] = True
#             st.session_state.pop("ms_password", None)
#         else:
#             st.session_state["password_correct"] = False
#
#     if st.session_state.get("password_correct"):
#         return True
#     st.text_input("\U0001F511 Enter Master Password", type="password",
#                   on_change=_verify, key="ms_password")
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
# CONFIG  —  >>> CONFIRM THESE MATCH YOUR DATA <<<
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

# ----------------------------------------------------------------------
# DATA ACCESS LAYER
# ----------------------------------------------------------------------
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

# ----------------------------------------------------------------------
# REPORT BUILDERS
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
# PAGE
# ----------------------------------------------------------------------
st.title("\U0001F4E6 Material Status")
st.caption(f"Live snapshot \u00B7 {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
           " \u00B7 source: Material Command Center")

if st.button("\U0001F504 Refresh data"):
    st.cache_data.clear()
    st.rerun()

# ---- Pending Material (indented, not yet ordered) ----
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

# ---- Pending Orders (PO placed, not fully received) ----
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
