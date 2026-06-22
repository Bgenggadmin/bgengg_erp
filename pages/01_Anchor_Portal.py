import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import plotly.express as px

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
tabs = st.tabs(["📝 New Entry", "📂 Pipeline", "📐 Drawings", "🛒 Purchase Status", "📊 Analytics", "🎯 Prospects (BD)"])

# ── TAB 1: NEW ENTRY ────────────────────────────────────────────────────────
with tabs[0]:
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
with tabs[1]:
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
with tabs[2]:
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
with tabs[3]:
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
with tabs[4]:
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
with tabs[5]:
    render_prospects_tab(get_prospects(), anchor_choice, today_dt)
