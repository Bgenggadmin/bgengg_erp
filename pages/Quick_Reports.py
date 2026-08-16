# ======================================================================
# QUOTATION FOLLOW-UP — drop-in patch for pages/14_Quick_Reports.py
#
# Adds two reports (plus one collapsed housekeeping block):
#   Report 6  📞 Follow-ups Due
#   Report 7  ⚖️  Decision Gate — 90+ days
#   Report 7b 🧹 Follow-up data gaps       (expanded=False)
#
# Reads v_ap_followups_due only. The cadence ladder lives in the view, so
# this page and the Monday Cowork brief can never disagree.
#
# PREREQUISITE: run quote_followups_schema_v2.sql first. If the view is
# missing, these blocks say so plainly instead of throwing.
#
# Insertion points:
#   PATCH 1  constants -> with PENDING_QUOTE_STATUS / ENQUIRY_STATUS
#   PATCH 2  helpers   -> only the ones you don't already have
#   PATCH 3  fetch     -> with the other @st.cache_data loaders
#   PATCH 4  builders  -> with the other build_* functions
#   PATCH 5  expanders -> at the bottom, after your last report block
# ======================================================================

import streamlit as st
import pandas as pd
from datetime import date


# ----------------------------------------------------------------------
# PATCH 1 — CONSTANTS
# ----------------------------------------------------------------------
FOLLOWUP_VIEW = "v_ap_followups_due"

# Bucket labels, exactly as the view emits them. Change here only if you
# change the CASE expression in the view.
BUCKET_DUE       = "Due"
BUCKET_GATE      = "Decision gate"
BUCKET_NO_PHONE  = "No contact details"
BUCKET_NO_DATE   = "No quote date"
BUCKET_DUP       = "Duplicate row"

DECISION_GATE_DAY = 90   # display only; the view is the authority


# ----------------------------------------------------------------------
# PATCH 2 — HELPERS
# Add ONLY the ones missing from your file. is_true / blank / num are
# already there per the working-knowledge doc; trunc and fmt_money too.
# ----------------------------------------------------------------------
def is_true(v) -> bool:
    """Supabase can hand back booleans as the strings 'true'/'false'."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "t", "1", "yes")


def blank(v, dash: str = "\u2014") -> str:
    """Null-safe display. Null-heavy int columns arrive as floats (41.0)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return dash
    if pd.isna(v):
        return dash
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
# PATCH 3 — FETCH
# ----------------------------------------------------------------------
@st.cache_data(ttl=30)
def get_followups_due() -> pd.DataFrame:
    """
    Read the follow-up view. Returns an empty frame if the view is absent
    so the page degrades to a message instead of a traceback.
    """
    res = conn.table(FOLLOWUP_VIEW).select("*").execute()      # noqa: F821
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


# ----------------------------------------------------------------------
# PATCH 4 — BUILDERS
# ----------------------------------------------------------------------
def _fu_frame(bucket: str) -> pd.DataFrame:
    df = get_followups_due()
    if df.empty or "bucket" not in df.columns:
        return pd.DataFrame()
    return df[df["bucket"] == bucket].copy()


def build_followups_due() -> pd.DataFrame:
    """Quotes whose next chase is due today or overdue."""
    df = _fu_frame(BUCKET_DUE)
    if df.empty:
        return df

    # Coerce sort keys before sorting — mixed None/int object columns blow up.
    df["_overdue"] = pd.to_numeric(df.get("days_until_due"), errors="coerce")
    df["_age"]     = pd.to_numeric(df.get("quote_age_days"), errors="coerce")

    out = pd.DataFrame({
        "Client":       df.get("client_name"),
        "Quote ref":    df.get("quote_ref").apply(clean_ref),
        "Project":      df.get("project_description").apply(trunc),   # noqa: F821
        "Est. value":   df.get("estimated_value").apply(fmt_money),   # noqa: F821
        "Age":          df["_age"].apply(days_txt),
        "Attempts":     df.get("attempts").apply(blank),
        "Last outcome": df.get("last_outcome").apply(
                            lambda v: blank(v, "never contacted")),
        "Overdue by":   df["_overdue"].apply(
                            lambda v: days_txt(-v) if pd.notna(v) and v <= 0
                            else "due today"),
        "Anchor":       df.get("anchor_person"),
        "Contact":      df.apply(contact_txt, axis=1),
        "_sort":        df["_overdue"],
    })
    out = out.sort_values("_sort", ascending=True, na_position="last")
    return out.drop(columns=["_sort"]).reset_index(drop=True)


def build_decision_gate() -> pd.DataFrame:
    """Quotes past the 90-day gate — these should be Won or Lost by now."""
    df = _fu_frame(BUCKET_GATE)
    if df.empty:
        return df

    df["_age"] = pd.to_numeric(df.get("quote_age_days"), errors="coerce")

    def verdict(r):
        outcome = str(r.get("last_outcome") or "").strip().lower()
        att     = pd.to_numeric(r.get("attempts"), errors="coerce")
        att     = int(att) if pd.notna(att) else 0
        if att == 0:
            return "Never chased \u2014 one last attempt"
        if outcome in ("", "no response", "none"):
            return "No response in " + str(att) + " tries \u2014 mark Lost"
        if outcome in ("declined",):
            return "Declined \u2014 mark Lost"
        return "Responded \u2014 chase to a decision"

    out = pd.DataFrame({
        "Client":       df.get("client_name"),
        "Quote ref":    df.get("quote_ref").apply(clean_ref),
        "Project":      df.get("project_description").apply(trunc),   # noqa: F821
        "Est. value":   df.get("estimated_value").apply(fmt_money),   # noqa: F821
        "Age":          df["_age"].apply(days_txt),
        "Attempts":     df.get("attempts").apply(blank),
        "Last outcome": df.get("last_outcome").apply(
                            lambda v: blank(v, "never contacted")),
        "Suggested":    df.apply(verdict, axis=1),
        "Anchor":       df.get("anchor_person"),
        "_sort":        df["_age"],
    })
    out = out.sort_values("_sort", ascending=False, na_position="last")
    return out.drop(columns=["_sort"]).reset_index(drop=True)


def build_followup_gaps() -> pd.DataFrame:
    """Rows the cadence can't act on until someone fixes the data."""
    df = get_followups_due()
    if df.empty or "bucket" not in df.columns:
        return pd.DataFrame()

    gaps = df[df["bucket"].isin([BUCKET_NO_PHONE, BUCKET_NO_DATE, BUCKET_DUP])].copy()
    if gaps.empty:
        return gaps

    fix = {
        BUCKET_NO_PHONE: "Add a contact person or phone in the Anchor Portal",
        BUCKET_NO_DATE:  "Set a Quote Date \u2014 no clock, no cadence",
        BUCKET_DUP:      "Duplicate of an open quote \u2014 mark one Lost",
    }
    out = pd.DataFrame({
        "Problem":   gaps["bucket"],
        "Client":    gaps.get("client_name"),
        "Quote ref": gaps.get("quote_ref").apply(clean_ref),
        "Quote date": gaps.get("quote_date").apply(lambda v: blank(v)),
        "Anchor":    gaps.get("anchor_person"),
        "Fix":       gaps["bucket"].map(fix),
    })
    return out.sort_values(["Problem", "Client"]).reset_index(drop=True)


# ----------------------------------------------------------------------
# PATCH 5 — PAGE BLOCKS
# Paste after your last report expander.
# ----------------------------------------------------------------------

# ---- Follow-ups Due ----
with st.expander("\U0001F4DE  Follow-ups Due  (quotations)", expanded=True):
    try:
        df_fu = build_followups_due()
        df_all = get_followups_due()

        if df_all.empty:
            st.info(
                "No data from `v_ap_followups_due`. If you haven't run "
                "`quote_followups_schema_v2.sql` yet, do that first. If you "
                "have, check the view is exposed to the API role:  "
                "`grant select on v_ap_followups_due to anon, authenticated;`"
            )
        else:
            open_n = len(df_all)
            due_n  = len(df_fu)
            never  = int((pd.to_numeric(df_all.get("attempts"),
                                        errors="coerce").fillna(0) == 0).sum())
            m1, m2, m3 = st.columns(3)
            m1.metric("Due for a chase", due_n)
            m2.metric("Open quotations", open_n)
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


# ---- Decision Gate ----
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
                "Each one should move to Won or Lost, or carry a written "
                "reason for staying open."
            )
            st.dataframe(df_gate, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Decision Gate: {e}")


# ---- Data gaps (housekeeping, collapsed) ----
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
