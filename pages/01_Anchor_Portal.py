import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import plotly.express as px
import urllib.parse

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
PIPELINE_STAGES = ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"]
DRAWING_STATUSES = ["Pending", "Drafting", "Approved", "NA"]
PURCHASE_STATUSES = ["Triggered", "Ordered", "Received"]
ANCHOR_PERSONS = ["API", "MEE"]   # API first = default opening profile (was Kishore)
DESC_TRUNCATE = 50  # single consistent truncation length
PROSPECT_STAGES = ["Identified", "Contacted", "Qualified", "Converted", "Dropped"]
PROSPECT_OPEN_STAGES = ["Identified", "Contacted", "Qualified"]   # still need follow-up
BD_ZONES = ["South", "West / Gujarat", "Maha + North + East"]
# BDMs reuse ANCHOR_PERSONS. If you add a 3rd BDM, just extend ANCHOR_PERSONS.

# ---- QUOTATION FOLLOW-UP ---------------------------------------------------
# Days after the clock starts (quote_date, else enquiry_date).
# Index = number of follow-ups already logged. Mirrors the ladder in
# v_ap_followups_due — change BOTH or the portal and the reports disagree.
FOLLOWUP_LADDER   = [3, 10, 21, 45, 75]
DECISION_GATE_DAY = 90   # past this, stop chasing and call it Won or Lost
MIN_GAP_DAYS      = 7    # never chase the same client twice inside a week

FOLLOWUP_CHANNELS = ["Call", "WhatsApp", "Email", "Visit"]
FOLLOWUP_OUTCOMES = [
    "No response",
    "Acknowledged \u2014 under review",
    "Revision requested",
    "Budget / approval hold",
    "Competitor in play",
    "Verbal yes",
    "Declined",
]
FOLLOWUP_SENDER   = "B&G Engineering Industries"

# ---------------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Anchor Portal | BGEngg ERP", layout="wide", page_icon="⚓")

# ---------------------------------------------------------------------------
# PASSWORD PROTECTION
# Add this to your Streamlit Cloud Secrets:
#   APP_PASSWORD = "1234"
# ---------------------------------------------------------------------------
def check_password() -> bool:
    def _verify():
        if st.session_state.get("password") == "1234":
            st.session_state["password_correct"] = True
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔑 Enter Master Password", type="password",
                      on_change=_verify, key="password")
        return False
    if not st.session_state["password_correct"]:
        st.text_input("🔑 Enter Master Password", type="password",
                      on_change=_verify, key="password")
        st.error("😕 Password incorrect")
        return False
    return True

if not check_password():
    st.stop()

# ---------------------------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------------------------
conn = st.connection("supabase", type=SupabaseConnection)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def safe_date(val, fallback: date | None = None) -> date:
    """Convert a raw DB value to a Python date, falling back gracefully."""
    if fallback is None:
        fallback = date.today()
    try:
        parsed = pd.to_datetime(val)
        return parsed.date() if pd.notnull(parsed) else fallback
    except Exception:
        return fallback


def trunc(text: str | None, n: int = DESC_TRUNCATE) -> str:
    if not text:
        return ""
    return text[:n] + ("..." if len(text) > n else "")


# ---------------------------------------------------------------------------
# DATA ACCESS LAYER
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def get_projects() -> pd.DataFrame:
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


@st.cache_data(ttl=30)
def get_purchase_items() -> pd.DataFrame:
    try:
        res = conn.table("purchase_orders").select("*").execute()
        if res.data:
            df_p = pd.DataFrame(res.data)
            df_p["job_no"] = df_p["job_no"].astype(str).str.strip().str.upper()
            if "created_at" in df_p.columns:
                df_p["created_at"] = pd.to_datetime(df_p["created_at"])
            return df_p
        return pd.DataFrame(
            columns=["job_no", "item_name", "specs", "status", "purchase_reply", "created_at"]
        )
    except Exception as e:
        st.warning(f"⚠️ Could not load purchase data: {e}")
        return pd.DataFrame(
            columns=["job_no", "item_name", "specs", "status", "purchase_reply", "created_at"]
        )


@st.cache_data(ttl=30)
def get_prospects() -> pd.DataFrame:
    try:
        res = conn.table("bd_prospects").select("*").order("id", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception as e:
        st.warning(f"⚠️ Could not load BD prospects: {e}")
        return pd.DataFrame()


def _refresh_prospects():
    get_prospects.clear()


def create_prospect(payload: dict):
    conn.table("bd_prospects").insert(payload).execute()
    _refresh_prospects()


def update_prospect(prospect_id: int, payload: dict):
    conn.table("bd_prospects").update(payload).eq("id", prospect_id).execute()
    _refresh_prospects()


def delete_prospect(prospect_id: int):
    conn.table("bd_prospects").delete().eq("id", prospect_id).execute()
    _refresh_prospects()


# ---------------------------------------------------------------------------
# QUOTATION FOLLOW-UP  (reads/writes quote_followups)
# The only write this feature makes is one INSERT into quote_followups.
# Nothing in anchor_projects is modified.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def get_followups() -> pd.DataFrame:
    """All rows from quote_followups. Empty frame if the table is missing."""
    try:
        res = (conn.table("quote_followups").select("*")
               .order("followup_date", desc=True).execute())
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception as e:
        st.warning(f"\u26a0\ufe0f Could not load follow-ups: {e}")
        return pd.DataFrame()


def _refresh_followups():
    get_followups.clear()


def log_followup(payload: dict):
    conn.table("quote_followups").insert(payload).execute()
    _refresh_followups()


def clean_phone(raw) -> str:
    """Digits only \u2014 same rule the Material Command Center uses."""
    return "".join(filter(str.isdigit, str(raw or "")))


def clean_ref(raw) -> str | None:
    """quote_ref holds the literal string 'nan' on some rows (an import
    artefact, not a null). Treat it as absent, or drafts go out saying
    'Reference: nan'."""
    s = str(raw or "").strip()
    return None if s == "" or s.lower() in ("nan", "none") else s


def followup_clock_start(row) -> date | None:
    """quote_date if present, else enquiry_date. None if neither parses."""
    for c in ("quote_date", "enquiry_date"):
        raw = row.get(c)
        try:
            parsed = pd.to_datetime(raw)
            if pd.notnull(parsed):
                return parsed.date()
        except Exception:
            continue
    return None


def followup_due_date(clock_start, attempts: int, last_date, override):
    """Cadence resolver. A manual next_action_date always wins. Otherwise
    the ladder decides, floored at MIN_GAP_DAYS after the last contact."""
    if override:
        return override
    if clock_start is None:
        return None
    if attempts < len(FOLLOWUP_LADDER):
        due = clock_start + timedelta(days=FOLLOWUP_LADDER[attempts])
    else:
        due = clock_start + timedelta(days=DECISION_GATE_DAY)
    if last_date:
        due = max(due, last_date + timedelta(days=MIN_GAP_DAYS))
    return due


def _followup_draft(row, attempts: int):
    """(subject, body) for the outgoing chase. Tone escalates with attempts."""
    person = str(row.get("contact_person") or "").strip() or "Sir/Madam"
    qref   = clean_ref(row.get("quote_ref")) or "our quotation"
    desc   = row.get("project_description") or "the enquiry"

    subject = f"Follow-up \u2014 {qref} | {desc[:60]} | {FOLLOWUP_SENDER}"

    if attempts == 0:
        ask = ("Just confirming you received our quotation. Happy to walk "
               "through the scope or the technical annexure whenever "
               "convenient.")
    elif attempts < 3:
        ask = ("Wanted to check where this sits on your side, and whether "
               "you need any revision to the scope, delivery schedule or "
               "commercial terms.")
    else:
        ask = ("We'd like to close our books on this one. Could you let us "
               "know whether it's still live, on hold, or decided? A clear "
               "'not now' is genuinely as useful to us as a yes.")

    body = (f"Dear {person},\n\n"
            f"Reference: {qref} \u2014 {desc}\n\n"
            f"{ask}\n\n"
            f"Regards,\n{FOLLOWUP_SENDER}")
    return subject, body


def render_followup_block(row, df_followups: pd.DataFrame, logged_by: str):
    """Follow-up panel. Renders only for status = 'Quotation Sent'."""
    if str(row.get("status")) != "Quotation Sent":
        return

    pid = int(row["id"])

    mine = pd.DataFrame()
    if not df_followups.empty and "project_id" in df_followups.columns:
        mine = df_followups[
            pd.to_numeric(df_followups["project_id"], errors="coerce") == pid
        ].copy()

    attempts, last_date, last_row, override = len(mine), None, None, None
    if attempts:
        mine["_fd"] = pd.to_datetime(mine["followup_date"], errors="coerce")
        mine = mine.sort_values("_fd", ascending=False)
        last_row = mine.iloc[0]
        if pd.notnull(last_row["_fd"]):
            last_date = last_row["_fd"].date()
        nad = pd.to_datetime(last_row.get("next_action_date"), errors="coerce")
        override = nad.date() if pd.notnull(nad) else None

    clock = followup_clock_start(row)
    due   = followup_due_date(clock, attempts, last_date, override)
    age   = (date.today() - clock).days if clock else None

    st.markdown("##### \U0001F4DE Quotation Follow-up")

    if clock is None:
        st.error("No quote date and no enquiry date \u2014 this quote has no "
                 "clock. Set a Quote Date above before the cadence can work.")
    elif age is not None and age >= DECISION_GATE_DAY:
        st.error(f"\U0001F514 **Decision gate** \u2014 {age} days open. Move "
                 f"this to Won or Lost, or record why it stays open.")
    elif due and due <= date.today():
        st.warning(f"\u23F0 **Follow-up due** \u2014 was due "
                   f"{due.strftime('%d %b')} ({(date.today()-due).days}d ago)")
    elif due:
        st.success(f"\u2705 Next follow-up scheduled for "
                   f"{due.strftime('%d %b %Y')}")

    fm1, fm2, fm3 = st.columns(3)
    fm1.metric("Attempts logged", attempts)
    fm2.metric("Quote age", f"{age}d" if age is not None else "\u2014")
    fm3.metric("Last contact",
               last_date.strftime("%d %b") if last_date else "Never")

    if last_row is not None:
        st.caption(
            f"Last: **{last_row.get('outcome') or '\u2014'}** via "
            f"{last_row.get('channel') or '\u2014'} on "
            f"{last_date.strftime('%d %b %Y') if last_date else '\u2014'}"
            + (f" \u00b7 {last_row.get('logged_by')}"
               if last_row.get("logged_by") else "")
        )
        if last_row.get("notes"):
            st.caption(f"\U0001F4DD {last_row['notes']}")

    # ---- outgoing drafts ---------------------------------------------
    subject, body = _followup_draft(row, attempts)
    phone = clean_phone(row.get("contact_phone"))
    # anchor_projects has NO contact_email column today. .get() returns
    # None, so the mailto opens with an empty To: field and you type the
    # address. Add the column and this fills itself.
    email = str(row.get("contact_email") or "").strip()

    if not phone and not str(row.get("contact_person") or "").strip():
        st.error("\u26a0\ufe0f No contact person and no phone on this project "
                 "\u2014 nobody to follow up with. Add contact details first.")

    dc1, dc2 = st.columns(2)
    wa_url = (f"https://wa.me/{phone}?text={urllib.parse.quote(body)}"
              if phone else f"https://wa.me/?text={urllib.parse.quote(body)}")
    dc1.markdown(
        f'<a href="{wa_url}" target="_blank" style="text-decoration:none;">'
        f'<div style="background:#25D366;color:white;padding:7px;'
        f'border-radius:5px;text-align:center;font-weight:bold;">'
        f'\U0001F4F2 WhatsApp draft</div></a>', unsafe_allow_html=True)
    mail_url = (f"mailto:{email}?subject={urllib.parse.quote(subject)}"
                f"&body={urllib.parse.quote(body)}")
    dc2.markdown(
        f'<a href="{mail_url}" style="text-decoration:none;">'
        f'<div style="background:#007bff;color:white;padding:7px;'
        f'border-radius:5px;text-align:center;font-weight:bold;">'
        f'\U0001F4E7 Email draft</div></a>', unsafe_allow_html=True)

    with st.expander("\u270F\ufe0f Edit the draft before sending"):
        st.text_area("Message", value=body, height=180, key=f"fu_draft_{pid}")
        st.caption("Copy from here to tweak the wording. The buttons above "
                   "always use the generated version.")

    # ---- log the attempt ---------------------------------------------
    with st.form(f"fu_form_{pid}", clear_on_submit=True):
        st.caption("Log what actually happened \u2014 this is what drives "
                   "the reports and the Monday brief.")
        g1, g2, g3 = st.columns(3)
        f_date    = g1.date_input("Date", value=date.today(), key=f"fud_{pid}")
        f_channel = g2.selectbox("Channel", FOLLOWUP_CHANNELS, key=f"fuc_{pid}")
        f_outcome = g3.selectbox("Outcome", FOLLOWUP_OUTCOMES, key=f"fuo_{pid}")
        f_notes   = st.text_input("Notes", key=f"fun_{pid}",
                                  placeholder="What did they actually say?")
        h1, h2 = st.columns([1, 2])
        f_set_next = h1.checkbox("Set next date manually", key=f"fus_{pid}")
        f_next     = h2.date_input("Next action date",
                                   value=date.today() + timedelta(days=14),
                                   key=f"fux_{pid}")

        if st.form_submit_button("\U0001F4BE Log follow-up", type="primary",
                                 use_container_width=True):
            try:
                log_followup({
                    "project_id":       pid,
                    "followup_date":    str(f_date),
                    "channel":          f_channel,
                    "outcome":          f_outcome,
                    "notes":            f_notes.strip(),
                    "next_action_date": str(f_next) if f_set_next else None,
                    "logged_by":        logged_by,
                })
                st.success("Logged.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not log follow-up: {e}")

    if attempts:
        with st.expander(f"\U0001F4CB Follow-up history ({attempts})"):
            hist = mine[["followup_date", "channel", "outcome",
                         "notes", "logged_by"]].copy()
            hist.columns = ["Date", "Channel", "Outcome", "Notes", "By"]
            st.dataframe(hist, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# DASHBOARD  (read-only — writes nothing, derives everything from the
# projects and follow-ups already loaded at the bottom of this file)
# ---------------------------------------------------------------------------
def _date_col(df_in: pd.DataFrame, col: str) -> pd.Series:
    """Parse a date column into plain Python `date` objects.

    utc=True followed by tz_convert(None) sidesteps the 'mixed timezone'
    error pandas throws when some rows carry an offset and others do not.
    enquiry_date and quote_date are DATE columns in Postgres, so there is
    no clock time to lose here.
    """
    if df_in.empty or col not in df_in.columns:
        return pd.Series([pd.NaT] * len(df_in), index=df_in.index, dtype="object")
    return (pd.to_datetime(df_in[col], errors="coerce", utc=True)
              .dt.tz_convert(None).dt.date)


def _in_window(dates: pd.Series, start: date, end: date) -> pd.Series:
    """Boolean mask: date falls inside [start, end]. Blanks are False."""
    return dates.apply(lambda d: pd.notna(d) and start <= d <= end)


def build_followup_queue(df_scope: pd.DataFrame,
                         df_followups: pd.DataFrame) -> pd.DataFrame:
    """One row per live quotation, with where it sits on the follow-up ladder.

    Deliberately re-uses followup_clock_start() and followup_due_date() —
    the same two functions the panel inside the Pipeline tab uses — so the
    dashboard count and the per-project panel can never drift apart.

    Deliberately does NOT read v_ap_followups_due. That view's CASE buckets
    evaluate 'No contact details' before 'Decision gate', so a 90-day-old
    quote with no phone number disappears from the urgent bucket — which is
    exactly the row that most needs chasing.
    """
    if df_scope.empty or "status" not in df_scope.columns:
        return pd.DataFrame()

    quoted = df_scope[df_scope["status"] == "Quotation Sent"]
    if quoted.empty:
        return pd.DataFrame()

    # Index the follow-up log by project once, rather than re-filtering the
    # whole frame inside the loop.
    fu_by_project = {}
    if not df_followups.empty and "project_id" in df_followups.columns:
        f = df_followups.copy()
        f["_pid"] = pd.to_numeric(f["project_id"], errors="coerce")
        f["_fd"] = pd.to_datetime(f["followup_date"], errors="coerce")
        for pid, grp in f.dropna(subset=["_pid"]).groupby("_pid"):
            fu_by_project[int(pid)] = grp.sort_values("_fd", ascending=False)

    today = date.today()
    rows = []
    for _, r in quoted.iterrows():
        pid = int(r["id"])
        mine = fu_by_project.get(pid)
        attempts = 0 if mine is None else len(mine)

        last_date = None
        override = None
        if attempts:
            top = mine.iloc[0]
            if pd.notnull(top["_fd"]):
                last_date = top["_fd"].date()
            nad = pd.to_datetime(top.get("next_action_date"), errors="coerce")
            override = nad.date() if pd.notnull(nad) else None

        clock = followup_clock_start(r)
        due = followup_due_date(clock, attempts, last_date, override)
        age = (today - clock).days if clock else None

        # Bucket order matters: a quote past the decision gate is a
        # different problem from one that is merely overdue.
        if clock is None:
            bucket = "No clock"
        elif age >= DECISION_GATE_DAY:
            bucket = "Decision gate"
        elif due and due <= today:
            bucket = "Overdue"
        else:
            bucket = "Scheduled"

        rows.append({
            "id": pid,
            "bucket": bucket,
            "client_name": r.get("client_name") or "",
            "project_description": trunc(r.get("project_description"), 40),
            "quote_ref": clean_ref(r.get("quote_ref")) or "—",
            "anchor_person": r.get("anchor_person") or "",
            "value": float(r.get("estimated_value") or 0),
            "attempts": attempts,
            "age_days": age,
            "due_date": due,
            "days_over": (today - due).days if due and due <= today else 0,
            "last_contact": last_date,
            "has_phone": bool(clean_phone(r.get("contact_phone"))),
        })

    q = pd.DataFrame(rows)
    # Keep whole-day counts as integers. Int64 (capital I) is the nullable
    # integer type — it tolerates the blank age on a quote with no clock
    # instead of forcing the whole column to float and printing "100.0".
    for c in ("age_days", "days_over", "attempts"):
        q[c] = pd.to_numeric(q[c], errors="coerce").astype("Int64")
    return q


def render_dashboard_tab(df_all: pd.DataFrame, df_followups: pd.DataFrame,
                         anchor_choice: str):
    """Four numbers that answer 'what happened, and what is waiting on me'."""
    st.subheader("🏠 Daily Dashboard")

    if df_all.empty:
        st.info("No projects in the system yet.")
        return

    c_scope, c_win = st.columns([1, 2])
    all_anchors = c_scope.checkbox("👁️ All anchor persons", key="dash_owner_view")
    window = c_win.radio(
        "Activity window", ["Yesterday", "Last 7 days", "This month"],
        horizontal=True, key="dash_window",
        help="On a Monday 'Yesterday' is Sunday and will read zero — "
             "switch to Last 7 days.",
    )

    scope = (df_all if all_anchors
             else df_all[df_all["anchor_person"] == anchor_choice]).copy()
    if scope.empty:
        st.info("No projects for this profile.")
        return

    today = date.today()
    if window == "Yesterday":
        start = end = today - timedelta(days=1)
    elif window == "Last 7 days":
        start, end = today - timedelta(days=6), today
    else:
        start, end = today.replace(day=1), today

    period = (start.strftime("%d %b %Y") if start == end
              else f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}")

    enq_dates = _date_col(scope, "enquiry_date")
    qte_dates = _date_col(scope, "quote_date")

    new_enq = scope[_in_window(enq_dates, start, end)]

    # quote_date on its own over-counts. The Pipeline form defaults an empty
    # Quote Date to today and writes it back on every save, so an Enquiry row
    # that was merely opened and saved picks up a quote_date it never earned.
    # Requiring the row to have actually reached quotation stage or beyond
    # filters those phantoms out.
    quoted_out = scope[_in_window(qte_dates, start, end)
                       & scope["status"].isin(["Quotation Sent", "Won", "Lost"])]

    # Standing backlog — not tied to the window. Same definition the Live
    # Action Summary above already uses, so the two never contradict.
    pending = scope[scope["status"].isin(["Enquiry", "Estimation"])].copy()
    pending["_age"] = pd.to_numeric(
        _date_col(pending, "enquiry_date").apply(
            lambda d: (today - d).days if pd.notna(d) else None
        ), errors="coerce"
    ).astype("Int64")

    # Drawings pending — Won jobs whose drawing is not Approved and not NA.
    # Same rule the Live Action Summary above uses. A null drawing_status
    # counts as pending on purpose: ~isin() returns True for NaN, and a Won
    # job with nothing recorded is genuinely outstanding, not exempt.
    if "drawing_status" in scope.columns:
        drawings = scope[(scope["status"] == "Won")
                         & (~scope["drawing_status"].isin(["Approved", "NA"]))].copy()
    else:
        drawings = scope.iloc[0:0].copy()

    if not drawings.empty:
        # Two different clocks. Won age says how long the drawing office has
        # had the job; days-to-delivery says how much runway is left. The
        # second is the one that actually hurts, so we sort on it.
        drawings["_won_age"] = pd.to_numeric(
            _date_col(drawings, "won_date").apply(
                lambda d: (today - d).days if pd.notna(d) else None
            ), errors="coerce").astype("Int64")
        drawings["_del_days"] = pd.to_numeric(
            _date_col(drawings, "revised_delivery_date").apply(
                lambda d: (d - today).days if pd.notna(d) else None
            ), errors="coerce").astype("Int64")

    queue = build_followup_queue(scope, df_followups)
    if queue.empty:
        due = no_clock = pd.DataFrame()
    else:
        due = queue[queue["bucket"].isin(["Overdue", "Decision gate"])]
        no_clock = queue[queue["bucket"] == "No clock"]

    # ---- headline numbers -------------------------------------------------
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Enquiries received", len(new_enq))
    m2.metric("Quotations sent", len(quoted_out))
    m3.metric("Pending quotations", len(pending))
    m4.metric("Follow-ups due", len(due))
    m5.metric("Drawings pending", len(drawings))

    pend_value = float(pending["estimated_value"].fillna(0).sum()) if not pending.empty else 0.0
    due_value = float(due["value"].sum()) if not due.empty else 0.0
    st.caption(
        f"Window **{period}** · scope "
        f"**{'all anchors' if all_anchors else anchor_choice}** · "
        f"pending backlog ₹{pend_value:,.0f} · chase list ₹{due_value:,.0f}"
    )

    if not due.empty:
        no_phone = int((~due["has_phone"]).sum())
        if no_phone:
            st.warning(
                f"☎️ {no_phone} of {len(due)} due follow-ups have no phone "
                f"number on record — add contact details before the chase "
                f"list is usable."
            )
    if not drawings.empty and "_del_days" in drawings.columns:
        tight = drawings[drawings["_del_days"].notna() & (drawings["_del_days"] <= 14)]
        if not tight.empty:
            st.warning(
                f"\U0001F4D0 {len(tight)} job(s) ship within 14 days with the "
                f"drawing still unapproved."
            )
    if not no_clock.empty:
        st.error(
            f"🕳️ {len(no_clock)} quotation(s) have neither a quote date nor "
            f"an enquiry date, so no follow-up clock is running on them."
        )

    st.divider()

    # ---- yesterday's activity ---------------------------------------------
    a1, a2 = st.columns(2)
    with a1:
        st.markdown(f"##### 🆕 Enquiries received — {period}")
        if new_enq.empty:
            st.caption("Nothing logged in this window.")
        else:
            st.dataframe(
                new_enq[["client_name", "project_description",
                         "anchor_person", "enquiry_date"]]
                .rename(columns={"client_name": "Client",
                                 "project_description": "Description",
                                 "anchor_person": "Anchor",
                                 "enquiry_date": "Date"}),
                hide_index=True, use_container_width=True,
            )
    with a2:
        st.markdown(f"##### 📤 Quotations sent — {period}")
        if quoted_out.empty:
            st.caption("Nothing quoted in this window.")
        else:
            q_show = quoted_out[["client_name", "quote_ref", "estimated_value",
                                 "status", "quote_date"]].copy()
            q_show["quote_ref"] = q_show["quote_ref"].apply(
                lambda v: clean_ref(v) or "—"
            )
            st.dataframe(
                q_show.rename(columns={"client_name": "Client",
                                       "quote_ref": "Quote Ref",
                                       "estimated_value": "Value ₹",
                                       "status": "Stage",
                                       "quote_date": "Quote Date"}),
                hide_index=True, use_container_width=True,
            )

    st.divider()

    # ---- standing backlog --------------------------------------------------
    st.markdown(f"##### 📋 Pending quotations ({len(pending)})")
    st.caption("Enquiry or Estimation stage — quotation not yet out.")
    if pending.empty:
        st.success("✅ Nothing waiting to be quoted.")
    else:
        p_show = (pending[["client_name", "project_description",
                           "anchor_person", "status", "_age", "estimated_value"]]
                  .sort_values("_age", ascending=False, na_position="last")
                  .rename(columns={"client_name": "Client",
                                   "project_description": "Description",
                                   "anchor_person": "Anchor",
                                   "status": "Stage",
                                   "_age": "Days Open",
                                   "estimated_value": "Est. Value ₹"}))
        st.dataframe(p_show, hide_index=True, use_container_width=True)

    st.divider()

    # ---- drawings outstanding ----------------------------------------------
    st.markdown(f"##### \U0001F4D0 Drawings pending ({len(drawings)})")
    st.caption(
        "Won jobs where the drawing is not Approved and not marked NA. "
        "Sorted by delivery date — the top row is the one running out of "
        "runway. Edit these in the Drawings tab."
    )
    if drawings.empty:
        st.success("\u2705 No drawings outstanding.")
    else:
        by_stat = drawings["drawing_status"].fillna("Not set").value_counts()
        st.caption(" \u00b7 ".join(f"**{k}**: {v}" for k, v in by_stat.items()))

        dr_cols = ["client_name", "job_no", "project_description", "anchor_person",
                   "drawing_status", "drawing_ref", "_won_age", "_del_days",
                   "revised_delivery_date"]
        dr_show = drawings[[c for c in dr_cols if c in drawings.columns]].copy()
        for c in ("drawing_status", "drawing_ref", "job_no"):
            if c in dr_show.columns:
                dr_show[c] = (dr_show[c].fillna("").astype(str).str.strip()
                              .replace("", "\u2014"))
        # A negative runway means the promised date has already gone past.
        if "_del_days" in dr_show.columns:
            dr_show.insert(0, "_flag", dr_show["_del_days"].apply(
                lambda v: "\U0001F534" if pd.notna(v) and v < 0
                else ("\U0001F7E0" if pd.notna(v) and v <= 14 else "\U0001F535")))
            dr_show = dr_show.sort_values("_del_days", na_position="last")
        dr_show = dr_show.rename(columns={
            "_flag": " ", "client_name": "Client", "job_no": "Job No",
            "project_description": "Description", "anchor_person": "Anchor",
            "drawing_status": "Drawing", "drawing_ref": "Dwg Ref",
            "_won_age": "Days Since Won", "_del_days": "Days To Delivery",
            "revised_delivery_date": "Delivery Date"})
        st.dataframe(dr_show, hide_index=True, use_container_width=True)

    st.divider()

    # ---- the chase list ----------------------------------------------------
    st.markdown(f"##### 📞 Follow-ups required ({len(due)})")
    st.caption(
        f"Ladder: {', '.join(str(d) for d in FOLLOWUP_LADDER)} days after the "
        f"quote, minimum {MIN_GAP_DAYS} days between calls, decision gate at "
        f"{DECISION_GATE_DAY} days. Open the Pipeline tab to log the call."
    )
    if due.empty:
        st.success("✅ No follow-up is overdue right now.")
    else:
        d_show = due.copy()
        d_show["Client"] = d_show.apply(
            lambda r: ("🔔 " if r["bucket"] == "Decision gate" else "⏰ ")
                      + r["client_name"], axis=1
        )
        d_show["Phone"] = d_show["has_phone"].map({True: "✔", False: "✖ missing"})
        d_show = (d_show[["Client", "quote_ref", "project_description",
                          "anchor_person", "value", "attempts", "age_days",
                          "days_over", "last_contact", "Phone", "bucket"]]
                  .sort_values(["days_over", "age_days"], ascending=False)
                  .rename(columns={"quote_ref": "Quote Ref",
                                   "project_description": "Description",
                                   "anchor_person": "Anchor",
                                   "value": "Value ₹",
                                   "attempts": "Tries",
                                   "age_days": "Quote Age",
                                   "days_over": "Days Late",
                                   "last_contact": "Last Contact",
                                   "bucket": "Why"}))
        st.dataframe(d_show, hide_index=True, use_container_width=True)
        st.download_button(
            "💾 Download chase list (CSV)",
            data=d_show.to_csv(index=False).encode("utf-8"),
            file_name=f"BGE_chase_list_{today.strftime('%Y%m%d')}.csv",
            key="dash_chase_dl",
        )

    if not queue.empty:
        with st.expander(f"📆 Scheduled — not due yet "
                         f"({int((queue['bucket'] == 'Scheduled').sum())})"):
            sched = queue[queue["bucket"] == "Scheduled"]
            if sched.empty:
                st.caption("None.")
            else:
                st.dataframe(
                    sched[["client_name", "quote_ref", "attempts",
                           "age_days", "due_date"]]
                    .sort_values("due_date")
                    .rename(columns={"client_name": "Client",
                                     "quote_ref": "Quote Ref",
                                     "attempts": "Tries",
                                     "age_days": "Quote Age",
                                     "due_date": "Next Due"}),
                    hide_index=True, use_container_width=True,
                )


def convert_prospect_to_enquiry(row) -> int | None:
    """Push a BD prospect into the live anchor_projects pipeline as an Enquiry."""
    payload = {
        "client_name": row["company"],
        "project_description": (row.get("buying_signal") or "BD-sourced opportunity"),
        "anchor_person": row.get("assigned_to") or ANCHOR_PERSONS[0],
        "enquiry_date": str(date.today()),
        "contact_person": row.get("contact_name") or "",
        "contact_phone": row.get("contact_phone") or "",
        "special_notes": (
            f"[BD lead | {row.get('location','')}] "
            f"Fit: {row.get('equipment_fit','')}. {row.get('notes','') or ''}"
        ).strip(),
        "status": "Enquiry",
        "drawing_status": "Pending",
    }
    ins = conn.table("anchor_projects").insert(payload).execute()
    new_id = ins.data[0]["id"] if getattr(ins, "data", None) else None
    conn.table("bd_prospects").update(
        {"stage": "Converted", "converted_project_id": new_id}
    ).eq("id", int(row["id"])).execute()
    # clear every cache so the new enquiry shows up immediately
    get_projects.clear()
    get_purchase_items.clear()
    get_prospects.clear()
    return new_id


# Mutation helpers — invalidate only the relevant cache after writes
def _refresh_projects():
    get_projects.clear()


def _refresh_purchase():
    get_purchase_items.clear()


def _refresh_all():
    get_projects.clear()
    get_purchase_items.clear()


def create_project(payload: dict):
    conn.table("anchor_projects").insert(payload).execute()
    _refresh_projects()


def update_project(project_id: int, payload: dict):
    conn.table("anchor_projects").update(payload).eq("id", project_id).execute()
    _refresh_projects()


def delete_project(project_id: int, job_no: str | None):
    """Delete project and cascade-clean orphaned purchase rows."""
    if job_no:
        conn.table("purchase_orders").delete().eq("job_no", job_no).execute()
    conn.table("anchor_projects").delete().eq("id", project_id).execute()
    _refresh_all()


def add_purchase_item(job_no: str, item_name: str, specs: str):
    conn.table("purchase_orders").insert({
        "job_no": job_no,
        "item_name": item_name,
        "specs": specs,
        "status": "Triggered",
    }).execute()
    _refresh_purchase()


# ---------------------------------------------------------------------------
# BD SIDEBAR ALERTS  (defined here, called in the sidebar section below)
# ---------------------------------------------------------------------------
def render_bd_sidebar_alerts(df_prospects, anchor_choice, today_dt):
    st.sidebar.divider()
    owner_view = st.sidebar.checkbox(
        "👁️ Owner view — all BDMs (BD)", key="bd_owner_view"
    )
    if df_prospects.empty:
        st.sidebar.caption("No BD prospects yet.")
        return

    scope = (
        df_prospects
        if owner_view
        else df_prospects[df_prospects["assigned_to"] == anchor_choice]
    ).copy()

    if scope.empty or "next_action_date" not in scope.columns:
        st.sidebar.success("✅ No BD follow-ups due")
        return

    scope["nad"] = pd.to_datetime(scope["next_action_date"], errors="coerce")
    due = scope[
        scope["nad"].notna()
        & (scope["nad"] <= today_dt)
        & (~scope["stage"].isin(["Converted", "Dropped"]))
    ]
    if not due.empty:
        st.sidebar.error(f"🎯 **{len(due)} BD follow-up(s) due**")
        if st.sidebar.checkbox("Show BD due list", key="bd_due_list"):
            for _, p in due.sort_values("nad").iterrows():
                who = f" · {p['assigned_to']}" if owner_view else ""
                st.sidebar.caption(f"📞 {p['company']}{who} — {p.get('next_action') or ''}")
    else:
        st.sidebar.success("✅ No BD follow-ups due")


# ---------------------------------------------------------------------------
# PROSPECTS TAB  (defined here, rendered at the very bottom under tabs[5])
# ---------------------------------------------------------------------------
def render_prospects_tab(df_prospects, anchor_choice, today_dt):
    st.subheader("🎯 Business Development — Prospect Tracker")

    owner_view = st.session_state.get("bd_owner_view", False)
    scope_label = "All BDMs (owner view)" if owner_view else f"{anchor_choice}'s prospects"
    st.caption(f"Showing: **{scope_label}** · toggle owner view in the sidebar.")

    # ---- Add a new prospect -------------------------------------------------
    with st.expander("➕ Add a prospect"):
        with st.form("new_prospect_form", clear_on_submit=True):
            a1, a2 = st.columns(2)
            p_company = a1.text_input("Company *")
            p_location = a2.text_input("Plant / Location (State)")
            b1, b2, b3 = st.columns(3)
            p_zone = b1.selectbox("Zone", BD_ZONES)
            p_segment = b2.text_input("Segment", placeholder="API / CDMO / Formulations")
            p_assigned = b3.selectbox("Assign to (BDM)", ANCHOR_PERSONS)
            p_signal = st.text_input("Buying signal", placeholder="Expansion / Schedule M / ZLD ...")
            c1, c2 = st.columns(2)
            p_fit = c1.text_input("Equipment fit (B&G)", placeholder="Reactor / ATFD / MEE / HX")
            p_role = c2.text_input("Decision contact (role)", placeholder="Projects Head")
            d1, d2 = st.columns(2)
            p_action = d1.text_input("Next action")
            p_action_date = d2.date_input("Next action date", value=date.today())
            p_notes = st.text_area("Notes")
            if st.form_submit_button("Add Prospect"):
                if p_company.strip():
                    create_prospect({
                        "company": p_company.strip(),
                        "location": p_location.strip(),
                        "zone": p_zone,
                        "segment": p_segment.strip(),
                        "buying_signal": p_signal.strip(),
                        "equipment_fit": p_fit.strip(),
                        "contact_role": p_role.strip(),
                        "assigned_to": p_assigned,
                        "stage": "Identified",
                        "next_action": p_action.strip(),
                        "next_action_date": str(p_action_date),
                        "notes": p_notes.strip(),
                    })
                    st.success(f"Added {p_company.strip()}")
                    st.rerun()
                else:
                    st.error("Company name is required.")

    # ---- Bulk import from CSV (load the 36-prospect list) -------------------
    with st.expander("📥 Bulk import from CSV"):
        st.caption(
            "CSV headers expected: company, location, zone, segment, buying_signal, "
            "equipment_fit, contact_role, next_action, next_action_date, notes"
        )
        imp1, imp2 = st.columns(2)
        imp_assigned = imp1.selectbox("Assign all imported rows to", ANCHOR_PERSONS, key="imp_assign")
        imp_zone_default = imp2.selectbox("Default zone (if blank in file)", BD_ZONES, key="imp_zone")
        up = st.file_uploader("Upload CSV", type=["csv"], key="bd_import")
        if up is not None:
            try:
                imp_df = pd.read_csv(up).fillna("")
                st.dataframe(imp_df.head(10), use_container_width=True, hide_index=True)
                if st.button(f"Import {len(imp_df)} rows", key="do_import"):
                    rows = []
                    for _, r in imp_df.iterrows():
                        rows.append({
                            "company": str(r.get("company", "")).strip(),
                            "location": str(r.get("location", "")).strip(),
                            "zone": str(r.get("zone", "")).strip() or imp_zone_default,
                            "segment": str(r.get("segment", "")).strip(),
                            "buying_signal": str(r.get("buying_signal", "")).strip(),
                            "equipment_fit": str(r.get("equipment_fit", "")).strip(),
                            "contact_role": str(r.get("contact_role", "")).strip(),
                            "assigned_to": imp_assigned,
                            "stage": "Identified",
                            "next_action": str(r.get("next_action", "")).strip(),
                            "next_action_date": str(r.get("next_action_date", "")).strip() or None,
                            "notes": str(r.get("notes", "")).strip(),
                        })
                    rows = [x for x in rows if x["company"]]
                    if rows:
                        conn.table("bd_prospects").insert(rows).execute()
                        _refresh_prospects()
                        st.success(f"Imported {len(rows)} prospects.")
                        st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

    st.divider()

    if df_prospects.empty:
        st.info("No prospects yet — add one above or import a CSV.")
        return

    # ---- Scope + funnel snapshot -------------------------------------------
    view = df_prospects if owner_view else df_prospects[df_prospects["assigned_to"] == anchor_choice]
    view = view.copy()
    if view.empty:
        st.info("No prospects assigned to this profile.")
        return

    view["nad"] = pd.to_datetime(view["next_action_date"], errors="coerce")
    open_view = view[view["stage"].isin(PROSPECT_OPEN_STAGES)]
    due_now = open_view[open_view["nad"].notna() & (open_view["nad"] <= today_dt)]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Open prospects", len(open_view))
    k2.metric("Follow-ups due", len(due_now))
    k3.metric("Qualified", int((view["stage"] == "Qualified").sum()))
    k4.metric("Converted", int((view["stage"] == "Converted").sum()))

    # ---- Filters ------------------------------------------------------------
    fcol1, fcol2 = st.columns([2, 2])
    stage_pick = fcol1.radio("Stage", ["All"] + PROSPECT_STAGES, horizontal=True)
    zone_pick = fcol2.selectbox("Zone", ["All"] + BD_ZONES)

    filt = view.copy()
    if stage_pick != "All":
        filt = filt[filt["stage"] == stage_pick]
    if zone_pick != "All":
        filt = filt[filt["zone"] == zone_pick]
    filt = filt.sort_values("nad", na_position="last")

    # ---- Rows ---------------------------------------------------------------
    for _, row in filt.iterrows():
        nad = row["nad"]
        is_due = pd.notna(nad) and nad <= today_dt and row["stage"] in PROSPECT_OPEN_STAGES
        icon = "🔴" if is_due else "🔹"
        who = f" · {row['assigned_to']}" if owner_view else ""
        due_txt = f"  [⏰ due {row['next_action_date']}]" if is_due else ""
        title = f"{icon} {row['company']} | {row['stage']}{who}{due_txt}"

        with st.expander(title):
            top = st.columns(3)
            top[0].caption(f"📍 {row.get('location') or '—'}")
            top[1].caption(f"🏭 {row.get('segment') or '—'}")
            top[2].caption(f"🔧 {row.get('equipment_fit') or '—'}")
            if row.get("buying_signal"):
                st.caption(f"💡 **Signal:** {row['buying_signal']}")

            e1, e2 = st.columns(2)
            new_stage = e1.selectbox(
                "Stage", PROSPECT_STAGES,
                index=PROSPECT_STAGES.index(row["stage"]) if row["stage"] in PROSPECT_STAGES else 0,
                key=f"pstage_{row['id']}",
            )
            new_assigned = e2.selectbox(
                "BDM", ANCHOR_PERSONS,
                index=ANCHOR_PERSONS.index(row["assigned_to"]) if row.get("assigned_to") in ANCHOR_PERSONS else 0,
                key=f"passign_{row['id']}",
            )

            g1, g2 = st.columns(2)
            new_cname = g1.text_input("Contact name", value=row.get("contact_name") or "", key=f"pcn_{row['id']}")
            new_crole = g2.text_input("Contact role", value=row.get("contact_role") or "", key=f"pcr_{row['id']}")
            h1, h2 = st.columns(2)
            new_phone = h1.text_input("Contact phone", value=row.get("contact_phone") or "", key=f"pph_{row['id']}")
            new_email = h2.text_input("Contact email", value=row.get("contact_email") or "", key=f"pem_{row['id']}")

            i1, i2 = st.columns([2, 1])
            new_action = i1.text_input("Next action", value=row.get("next_action") or "", key=f"pna_{row['id']}")
            new_action_date = i2.date_input(
                "Next action date",
                value=safe_date(row.get("next_action_date")),
                key=f"pnad_{row['id']}",
            )
            new_notes = st.text_area("Notes", value=row.get("notes") or "", key=f"pnotes_{row['id']}")

            if row.get("converted_project_id"):
                st.success(f"✅ Converted → anchor_projects id {int(row['converted_project_id'])}")

            b_save, b_conv, b_del = st.columns([2, 2, 1])
            if b_save.button("💾 Save", key=f"psave_{row['id']}", type="primary", use_container_width=True):
                update_prospect(int(row["id"]), {
                    "stage": new_stage,
                    "assigned_to": new_assigned,
                    "contact_name": new_cname.strip(),
                    "contact_role": new_crole.strip(),
                    "contact_phone": new_phone.strip(),
                    "contact_email": new_email.strip(),
                    "next_action": new_action.strip(),
                    "next_action_date": str(new_action_date),
                    "notes": new_notes.strip(),
                })
                st.rerun()

            # Convert → live enquiry (disabled once converted)
            already = bool(row.get("converted_project_id"))
            if b_conv.button(
                "➡️ Convert to Enquiry", key=f"pconv_{row['id']}",
                use_container_width=True, disabled=already,
            ):
                new_id = convert_prospect_to_enquiry(row)
                st.success(f"Created enquiry (id {new_id}) for {row['company']}. See the Pipeline tab.")
                st.rerun()

            with b_del.popover("🗑️"):
                st.warning("Delete this prospect?")
                if st.button("Confirm", key=f"pdel_{row['id']}", type="primary"):
                    delete_prospect(int(row["id"]))
                    st.rerun()


# ---------------------------------------------------------------------------
# LOAD DATA
# ---------------------------------------------------------------------------
df = get_projects()
df_prospects = get_prospects()
df_pur = get_purchase_items()
df_followups = get_followups()
today_dt = pd.to_datetime(date.today())

# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
st.sidebar.title("🎯 Anchor Control")
anchor_choice = st.sidebar.selectbox("Select Your Profile", ANCHOR_PERSONS)

# Full dataset for this anchor person — never modified by search
df_anchor = df[df["anchor_person"] == anchor_choice].copy() if not df.empty else pd.DataFrame()

# Compute aging once, on the full anchor dataset
if not df_anchor.empty:
    df_anchor["enquiry_date_dt"] = pd.to_datetime(df_anchor["enquiry_date"]).dt.tz_localize(None)
    df_anchor["aging_days"] = (today_dt - df_anchor["enquiry_date_dt"]).dt.days

# Sidebar: critical material alerts
st.sidebar.divider()
if not df_anchor.empty and not df_pur.empty:
    won_jobs = df_anchor[df_anchor["status"] == "Won"]["job_no"].dropna().unique()
    pending_items = df_pur[
        df_pur["job_no"].isin(won_jobs) &
        (~df_pur["status"].isin(["Ordered", "Received"]))
    ]
    if not pending_items.empty:
        st.sidebar.error(f"⚠️ **{len(pending_items)} Pending Orders**")
        if st.sidebar.checkbox("Show Quick List", key="sidebar_list"):
            for _, item in pending_items.iterrows():
                st.sidebar.caption(f"📍 {item['job_no']}: {item['item_name']}")
    else:
        st.sidebar.success("✅ All Materials Ordered")

# Sidebar: BD follow-up alerts  (this is the call that was missing)
render_bd_sidebar_alerts(df_prospects, anchor_choice, today_dt)

# Sidebar: sync & search
st.sidebar.divider()
if not df_anchor.empty and "enquiry_date_dt" in df_anchor.columns:
    st.sidebar.caption(f"🕒 Data as of: {datetime.now().strftime('%H:%M:%S')}")

if st.sidebar.button("🔄 Force Refresh Data", use_container_width=True):
    _refresh_all()
    st.rerun()

search_query = st.sidebar.text_input(
    "🔍 Quick Search", placeholder="Client, Job, or Desc...", key="sidebar_search"
)

# Search produces a separate filtered view used only in the Live Action Summary
if search_query and not df_anchor.empty:
    df_search = df_anchor[
        df_anchor["client_name"].str.contains(search_query, case=False, na=False) |
        df_anchor["job_no"].str.contains(search_query, case=False, na=False) |
        df_anchor["project_description"].str.contains(search_query, case=False, na=False)
    ]
else:
    df_search = df_anchor

# ---------------------------------------------------------------------------
# PAGE HEADER
# ---------------------------------------------------------------------------
st.title(f"⚓ {anchor_choice}'s Project Portal")
st.markdown("---")

# ---------------------------------------------------------------------------
# LIVE ACTION SUMMARY  (uses df_search so sidebar search is scoped here only)
# ---------------------------------------------------------------------------
if not df_search.empty:
    st.subheader("🚀 Live Action Summary")
    pend_quotes = df_search[df_search["status"].isin(["Enquiry", "Estimation"])]
    pend_drawings = df_search[
        (df_search["status"] == "Won") &
        (~df_search["drawing_status"].isin(["Approved", "NA"]))
    ]

    col1, col2 = st.columns(2)
    with col1:
        st.info(f"📋 **Pending Quotations ({len(pend_quotes)})**")
        if not pend_quotes.empty:
            st.dataframe(
                pend_quotes[["client_name", "project_description", "aging_days"]]
                .rename(columns={"aging_days": "Days Pending"}),
                hide_index=True, use_container_width=True,
            )
    with col2:
        st.warning(f"📐 **Pending Drawings ({len(pend_drawings)})**")
        if not pend_drawings.empty:
            st.dataframe(
                pend_drawings[["client_name", "drawing_status", "aging_days"]]
                .rename(columns={"aging_days": "Days Since Won"}),
                hide_index=True, use_container_width=True,
            )
    st.markdown("---")

# ---------------------------------------------------------------------------
# MAIN TABS  (all use df_anchor — the full unfiltered anchor dataset)
# ---------------------------------------------------------------------------
tab_dash, tab_new, tab_pipe, tab_draw, tab_pur, tab_ana, tab_bd = st.tabs(
    ["🏠 Dashboard", "📝 New Entry", "📂 Pipeline", "📐 Drawings",
     "🛒 Purchase Status", "📊 Analytics", "🎯 Prospects (BD)"]
)

# ── TAB 0: DASHBOARD ────────────────────────────────────────────────────────
# Uses df (every project) not df_anchor, so the owner-view checkbox inside
# the dashboard can widen the scope to all anchor persons.
with tab_dash:
    render_dashboard_tab(df, df_followups, anchor_choice)

# ── TAB 1: NEW ENTRY ────────────────────────────────────────────────────────
with tab_new:
    st.subheader("Register New Project Enquiry")
    with st.form("new_project_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        u_client = col1.text_input("Client Name")
        u_proj = col2.text_input("Project Description")
        c1, c2, c3 = st.columns(3)
        u_date = c1.date_input("Enquiry Date", value=datetime.now())
        u_contact = c2.text_input("Contact Person Name")
        u_phone = c3.text_input("Contact Phone")
        u_notes = st.text_area("Initial Remarks")
        if st.form_submit_button("Log Enquiry"):
            client_clean = u_client.strip()
            proj_clean = u_proj.strip()
            if client_clean and proj_clean:
                create_project({
                    "client_name": client_clean,
                    "project_description": proj_clean,
                    "anchor_person": anchor_choice,
                    "enquiry_date": str(u_date),
                    "contact_person": u_contact.strip(),
                    "contact_phone": u_phone.strip(),
                    "special_notes": u_notes,
                    "status": "Enquiry",
                    "drawing_status": "Pending",
                })
                st.success("Enquiry Logged!")
                st.rerun()
            else:
                st.error("Client Name and Project Description are required.")

# ── TAB 2: PIPELINE ─────────────────────────────────────────────────────────
with tab_pipe:
    st.subheader("Sales Lifecycle & Project Tracking")
    if df_anchor.empty:
        st.info("No projects found for this anchor person.")
    else:
        view_col, stage_col = st.columns([1, 2])
        bulk_mode = view_col.toggle("⚡ Bulk Update Mode", value=False)
        stage_filter_options = ["All"] + PIPELINE_STAGES
        selected_stage = stage_col.radio(
            "Filter Stage", stage_filter_options, horizontal=True
        )

        df_pipeline = (
            df_anchor if selected_stage == "All"
            else df_anchor[df_anchor["status"] == selected_stage]
        )

        if bulk_mode:
            with st.form("bulk_update_form"):
                selected_ids = []
                for _, row in df_pipeline.iterrows():
                    cols = st.columns([0.5, 2, 2, 2])
                    if cols[0].checkbox("", key=f"bulk_{row['id']}"):
                        selected_ids.append(row["id"])
                    cols[1].write(f"**{row['client_name']}**")
                    cols[2].write(trunc(row["project_description"], 40))
                    cols[3].caption(f"Current: {row['status']}")
                new_bulk_status = st.selectbox("Move selected to:", PIPELINE_STAGES)
                if st.form_submit_button("🚀 Execute Bulk Update"):
                    if selected_ids:
                        payload = {
                            "status": new_bulk_status,
                            "status_updated_at": datetime.now().isoformat(),
                        }
                        if new_bulk_status == "Won":
                            payload["won_date"] = str(date.today())
                        conn.table("anchor_projects").update(payload).in_(
                            "id", selected_ids
                        ).execute()
                        _refresh_projects()
                        st.success("Bulk Update Complete!")
                        st.rerun()
        else:
            for _, row in df_pipeline.iterrows():
                is_aging = (
                    row.get("aging_days", 0) > 7 and
                    row["status"] in ["Enquiry", "Estimation"]
                )
                aging_label = f" [⚠️ {row['aging_days']} DAYS OLD]" if is_aging else ""
                icon = "🔥" if is_aging else "📋"
                job_label = row["job_no"] or "N/A"
                desc_label = trunc(row["project_description"])

                with st.expander(
                    f"{icon} {row['client_name']} | Job: {job_label} | 📝 {desc_label}{aging_label}"
                ):
                    # PO details
                    pd1, pd2 = st.columns(2)
                    u_po_no = pd1.text_input(
                        "PO Number", value=row.get("po_no") or "", key=f"pono_{row['id']}"
                    )
                    u_po_date = pd2.date_input(
                        "PO Date",
                        value=safe_date(row.get("po_date")),
                        key=f"podt_{row['id']}",
                    )

                    # Delivery metrics
                    d1, d2, d3 = st.columns(3)
                    u_po_del = d1.date_input(
                        "Original PO Del. Date",
                        value=safe_date(row.get("po_delivery_date")),
                        key=f"po_del_date_{row['id']}",
                    )
                    u_rev_del = d2.date_input(
                        "Revised Del. Date",
                        value=safe_date(
                            row.get("revised_delivery_date"),
                            fallback=safe_date(row.get("po_delivery_date")),
                        ),
                        key=f"rev_del_date_{row['id']}",
                    )
                    days_to_go = (u_rev_del - date.today()).days
                    d3.metric("Days to Dispatch", f"{days_to_go} Days", delta=days_to_go)

                    st.divider()

                    # Financials
                    f1, f2, f3, f4 = st.columns(4)
                    u_val = f1.number_input(
                        "Est. Value (₹)", value=float(row.get("estimated_value") or 0),
                        key=f"val_{row['id']}",
                    )
                    u_act_val = f2.number_input(
                        "Actual PO Value (₹)", value=float(row.get("actual_value") or 0),
                        key=f"act_val_{row['id']}",
                    )
                    u_qref = f3.text_input(
                        "Quote Ref.", value=row.get("quote_ref") or "",
                        key=f"qref_{row['id']}",
                    )
                    u_qdate = f4.date_input(
                        "Quote Date",
                        value=safe_date(row.get("quote_date")),
                        key=f"qdt_{row['id']}",
                    )

                    # Margin variance — rendered once only
                    if row["status"] == "Won" and u_act_val > 0:
                        variance = u_act_val - u_val
                        colour = "green" if variance >= 0 else "red"
                        st.markdown(f"**Margin Variance:** :{colour}[₹{variance:,.0f}]")

                    render_followup_block(row, df_followups, anchor_choice)
                    st.divider()

                    new_status = st.selectbox(
                        "Update Stage",
                        PIPELINE_STAGES,
                        index=PIPELINE_STAGES.index(row["status"])
                        if row["status"] in PIPELINE_STAGES else 0,
                        key=f"st_select_{row['id']}",
                    )

                    # Purchase trigger
                    st.markdown("##### 🛒 Item-wise Purchase Trigger")
                    pc1, _ = st.columns([1, 2])
                    u_job = pc1.text_input(
                        "Job No.", value=row["job_no"] or "", key=f"pjob_{row['id']}"
                    )
                    u_trig = pc1.checkbox(
                        "Trigger Purchase?", value=bool(row.get("purchase_trigger")),
                        key=f"ptrig_{row['id']}",
                    )

                    with st.container(border=True):
                        ic1, ic2, ic3 = st.columns([2, 1, 1])
                        i_name = ic1.text_input("Material Name", key=f"iname_{row['id']}")
                        i_spec = ic2.text_input("Qty / Specs", key=f"ispec_{row['id']}")
                        if ic3.button("➕ Add Item", key=f"ibtn_{row['id']}", use_container_width=True):
                            if i_name.strip() and u_job.strip():
                                clean_job = u_job.strip().upper()
                                add_purchase_item(clean_job, i_name.strip(), i_spec.strip())
                                conn.table("anchor_projects").update({
                                    "purchase_trigger": True,
                                    "job_no": clean_job,
                                }).eq("id", row["id"]).execute()
                                _refresh_all()
                                st.rerun()
                            else:
                                st.warning("Provide both a Job No. and Material Name.")

                    col_save, col_del = st.columns([3, 1])
                    if col_save.button(
                        "Save Project Status", key=f"up_btn_{row['id']}",
                        type="primary", use_container_width=True,
                    ):
                        payload = {
                            "po_no": u_po_no,
                            "po_date": str(u_po_date),
                            "estimated_value": u_val,
                            "actual_value": u_act_val,
                            "quote_ref": u_qref,
                            "quote_date": str(u_qdate),
                            "status": new_status,
                            "job_no": u_job.strip().upper(),
                            "purchase_trigger": u_trig,
                            "po_delivery_date": str(u_po_del),
                            "revised_delivery_date": str(u_rev_del),
                        }
                        if new_status != row["status"]:
                            payload["status_updated_at"] = datetime.now().isoformat()
                            if new_status == "Won":
                                payload["won_date"] = str(date.today())
                        update_project(row["id"], payload)
                        st.rerun()

                    with col_del.popover("🗑️ Delete"):
                        st.warning("Delete this project permanently?")
                        if st.button("Confirm Delete", key=f"del_{row['id']}", type="primary"):
                            raw_job = row.get("job_no")
                            delete_project(
                                row["id"],
                                str(raw_job).strip().upper()
                                if pd.notnull(raw_job) and str(raw_job).strip()
                                else None,
                            )
                            st.rerun()

# ── TAB 3: DRAWINGS ─────────────────────────────────────────────────────────
with tab_draw:
    st.subheader("Drawing Control")
    won_projects = (
        df_anchor[df_anchor["status"] == "Won"] if not df_anchor.empty else pd.DataFrame()
    )
    if won_projects.empty:
        st.info("No Won projects yet.")
    else:
        for _, row in won_projects.iterrows():
            with st.expander(f"📐 DRAWING: {row['client_name']}"):
                c1, c2 = st.columns(2)
                d_ref = c1.text_input(
                    "Drawing Ref No.", value=row.get("drawing_ref") or "",
                    key=f"dr_{row['id']}",
                )
                current_ds = row.get("drawing_status") or "Pending"
                d_stat = c2.selectbox(
                    "Status", DRAWING_STATUSES,
                    index=DRAWING_STATUSES.index(current_ds)
                    if current_ds in DRAWING_STATUSES else 0,
                    key=f"ds_{row['id']}",
                )
                if st.button("Save Drawing Info", key=f"dbtn_{row['id']}"):
                    conn.table("anchor_projects").update({
                        "drawing_ref": d_ref,
                        "drawing_status": d_stat,
                    }).eq("id", row["id"]).execute()
                    _refresh_projects()
                    st.rerun()

# ── TAB 4: PURCHASE STATUS ───────────────────────────────────────────────────
with tab_pur:
    st.subheader("📦 Item-wise Purchase Feedback")
    if df_anchor.empty:
        st.info("No projects found.")
    else:
        won_with_job = df_anchor[
            (df_anchor["status"] == "Won") &
            df_anchor["job_no"].notna() &
            (df_anchor["job_no"].astype(str).str.strip() != "")
        ]
        if won_with_job.empty:
            st.info("No Won projects with a Job No. assigned yet.")
        else:
            for _, row in won_with_job.iterrows():
                clean_job = str(row["job_no"]).strip().upper()
                job_items = (
                    df_pur[df_pur["job_no"] == clean_job]
                    if not df_pur.empty
                    else pd.DataFrame()
                )
                if not job_items.empty:
                    with st.container(border=True):
                        st.markdown(f"#### Job: {clean_job} | {row['client_name']}")
                        for _, item in job_items.iterrows():
                            c_at_raw = item.get("created_at")
                            created_at = (
                                pd.to_datetime(c_at_raw).tz_localize(None)
                                if pd.notnull(pd.to_datetime(c_at_raw, errors="coerce"))
                                else today_dt
                            )
                            order_age = (today_dt - created_at).days

                            c1, c2, c3, c4 = st.columns([2, 1, 3, 1])
                            overdue = order_age > 2 and item["status"] == "Triggered"
                            c1.write(f"{'🛑' if overdue else '🔹'} {item['item_name']}")
                            c2.write(item.get("specs") or "")
                            c3.info(item.get("purchase_reply") or "⌛ No reply yet")
                            if item["status"] == "Received":
                                c4.success("Received")
                            else:
                                c4.warning(item["status"])

# ── TAB 5: ANALYTICS ────────────────────────────────────────────────────────
with tab_ana:
    st.subheader("📊 Business Intelligence")
    if df_anchor.empty:
        st.info("No data to analyse yet.")
    else:
        won_df = df_anchor[df_anchor["status"] == "Won"].copy()
        lost_count = len(df_anchor[df_anchor["status"] == "Lost"])
        total_closed = len(won_df) + lost_count
        win_rate = (len(won_df) / total_closed * 100) if total_closed > 0 else 0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Win Rate", f"{win_rate:.1f}%")
        m2.metric("Won Value", f"₹{won_df['actual_value'].sum():,.0f}")

        has_enquiry_date = "enquiry_date_dt" in won_df.columns

        if not won_df.empty and "won_date" in won_df.columns and has_enquiry_date:
            won_df["won_date_dt"] = pd.to_datetime(won_df["won_date"]).dt.tz_localize(None)
            won_df["cycle_time"] = (
                won_df["won_date_dt"] - won_df["enquiry_date_dt"]
            ).dt.days
            avg_cycle = won_df["cycle_time"].mean()
            m3.metric(
                "Avg. Sales Cycle",
                f"{int(avg_cycle)} Days" if not pd.isna(avg_cycle) else "N/A",
            )

            won_df["delivery_month"] = (
                pd.to_datetime(won_df["revised_delivery_date"]).dt.strftime("%b %Y")
            )
            monthly_data = (
                won_df.groupby("delivery_month")["actual_value"].sum().reset_index()
            )
            st.markdown("##### 📅 Revenue Forecast (by Delivery Month)")
            fig_month = px.bar(
                monthly_data, x="delivery_month", y="actual_value", text_auto=".2s"
            )
            st.plotly_chart(fig_month, use_container_width=True)

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### Pipeline Status")
            fig_pie = px.pie(df_anchor, names="status", hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            st.markdown("##### Master Export")
            export_df = df_anchor.drop(
                columns=["id", "enquiry_date_dt", "aging_days"], errors="ignore"
            )
            st.download_button(
                "💾 Download CSV",
                data=export_df.to_csv(index=False).encode("utf-8"),
                file_name=f"BGE_{anchor_choice}.csv",
                key="master_csv_dl",
            )
            st.dataframe(export_df, use_container_width=True)

# ── TAB 6: PROSPECTS (BD) ────────────────────────────────────────────────────
# NOTE: render_prospects_tab is defined far above, so this call is safe.
with tab_bd:
    render_prospects_tab(get_prospects(), anchor_choice, today_dt)
