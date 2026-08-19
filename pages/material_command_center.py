import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
import urllib.parse
from collections import defaultdict

# ============================================================
# 1. SETUP & BRANDING
# ============================================================
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Command Center", layout="wide", page_icon="🏗️")

st.markdown("""
    <style>
    .bg-header { background-color: #003366; color: white; padding: 1rem;
                 border-radius: 8px; text-align: center; }
    .blue-strip { background-color: #007bff; height: 3px; width: 100%;
                  margin: 10px 0 20px 0; }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# ============================================================
# 2. UTILITIES
# ============================================================
def safe_db_write(fn, success_msg=None, error_prefix="DB Error"):
    try:
        fn()
        if success_msg:
            st.success(success_msg)
        return True
    except Exception as e:
        st.error(f"{error_prefix}: {e}")
        return False

def clean_phone(raw):
    return ''.join(filter(str.isdigit, str(raw or "")))

# ============================================================
# 3. DATA LOADERS
# ============================================================
@st.cache_data(ttl=60)
def get_jobs():
    try:
        res = conn.table("anchor_projects").select("job_no").execute()
        return sorted([str(r['job_no']).strip() for r in res.data if r.get('job_no')])
    except Exception:
        return []

@st.cache_data(ttl=60)
def get_material_groups():
    """Names only, for dropdowns. Skips NULL/blank rows (str(None) was
    printing a literal 'None' option) and de-duplicates, so a stray
    duplicate in the master can't appear twice in a selectbox."""
    try:
        res = conn.table("material_master").select("material_group").execute()
        names = {
            str(r['material_group']).strip()
            for r in (res.data or [])
            if r.get('material_group') and str(r['material_group']).strip()
        }
        return sorted(names)
    except Exception:
        return ["GENERAL"]


@st.cache_data(ttl=60)
def get_material_master_rows():
    """Full rows (id, name, category). Needed by Master Setup for edit and
    delete — get_material_groups() returns names only, which is all the
    dropdowns need but not enough to target a row by id."""
    try:
        res = conn.table("material_master").select("*") \
            .order("material_group").execute()
        return res.data or []
    except Exception:
        return []

@st.cache_data(ttl=60)
def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return sorted([r['name'] for r in res.data])
    except Exception:
        return ["Admin", "Staff"]

@st.cache_data(ttl=60)
def get_vendors():
    try:
        res = conn.table("master_vendors").select("*").order("name").execute()
        return res.data if res.data else []
    except Exception:
        return []

def get_staff_phones():
    try:
        res = conn.table("master_staff").select("name, phone, email").execute()
        return {r['name']: r for r in res.data} if res.data else {}
    except Exception:
        return {}

# ============================================================
# 4. BRANDED HEADER
# ============================================================
st.markdown(
    '<div class="bg-header"><h1>B&G ENGINEERING</h1>'
    '<p>MATERIAL COMMAND CENTER</p></div>',
    unsafe_allow_html=True
)
st.markdown('<div class="blue-strip"></div>', unsafe_allow_html=True)

main_tabs = st.tabs([
    "📝 Indent Application",
    "🛒 Purchase Console",
    "📦 Stores GRN",
    "📊 Analytics",
    "⚙️ Master Setup"
])

# ============================================================
# TAB 0: INDENT APPLICATION
# ============================================================
with main_tabs[0]:
    st.subheader("📝 Material Indent & Tracking")

    if "rev_data"    not in st.session_state: st.session_state.rev_data    = None
    if "indent_cart" not in st.session_state: st.session_state.indent_cart = []

    raised_by = st.selectbox("Raised By", get_staff_list(), key="user_sel")

    # ── PART A: ENTRY FORM ───────────────────────────────────
    with st.expander(
        "➕ Add Item to Draft",
        expanded=True if not st.session_state.indent_cart else False
    ):
        rd = st.session_state.rev_data if st.session_state.rev_data is not None else {}

        if st.session_state.rev_data is not None:
            st.info(f"🔧 Editing / Revising: {rd.get('item_name', 'Item')}")

        with st.form("indent_form", clear_on_submit=True):
            f1, f2 = st.columns(2)

            def_jobs = rd.get('job_no', "").split(", ") if rd.get('job_no') else []
            job_list = get_jobs()
            sel_jobs = f1.multiselect(
                "Select Job Nos", job_list,
                default=[j for j in def_jobs if j in job_list]
            )

            m_list = get_material_groups()
            try:
                def_m_idx = m_list.index(rd['material_group']) if 'material_group' in rd else 0
            except Exception:
                def_m_idx = 0
            m_grp = f2.selectbox("Material Group", m_list, index=def_m_idx)

            i_name  = st.text_input("Item Name",     value=rd.get('item_name', ""))
            i_specs = st.text_area("Specifications", value=rd.get('specs', ""))

            c1, c2, c3 = st.columns(3)
            try:
                curr_qty = float(rd.get('quantity', 0.1))
            except Exception:
                curr_qty = 0.1
            i_qty = c1.number_input("Qty", min_value=0.1, value=curr_qty)

            u_list = ["Nos", "Kgs", "Mts", "Sft", "Sets"]
            try:
                def_u_idx = u_list.index(rd['units']) if 'units' in rd else 0
            except Exception:
                def_u_idx = 0
            i_unit = c2.selectbox("Units", u_list, index=def_u_idx)

            i_note = st.text_input("Notes", value=rd.get('special_notes', ""))

            f_btn1, f_btn2 = st.columns([1, 4])
            submit_item = f_btn2.form_submit_button("✅ Add Item to List", use_container_width=True)
            cancel_edit = f_btn1.form_submit_button("❌ Cancel")

            if cancel_edit:
                # Backing out of an edit must put the row back to
                # Triggered, or it stays invisible to the Purchase Console.
                stuck_id = (st.session_state.rev_data or {}).get('_edit_id') \
                    if isinstance(st.session_state.rev_data, dict) else None
                if stuck_id:
                    safe_db_write(
                        lambda: conn.table("purchase_orders")
                            .update({"status": "Triggered"})
                            .eq("id", stuck_id).execute(),
                        error_prefix="Edit cancel error"
                    )
                st.session_state.rev_data = None
                st.rerun()

            if submit_item:
                if not sel_jobs or not i_name:
                    st.error("Job and Item Name are required.")
                elif len(st.session_state.indent_cart) >= 20:
                    st.warning("⚠️ Draft limit reached (20 items). Please submit before adding more.")
                else:
                    st.session_state.indent_cart.append({
                        "job_no":         ", ".join(sel_jobs),
                        "material_group": m_grp,
                        "item_name":      i_name.upper(),
                        "specs":          i_specs,
                        "quantity":       i_qty,
                        "units":          i_unit,
                        "special_notes":  i_note,
                        "triggered_by":   raised_by,
                        "status":         "Triggered",
                        "is_urgent":      rd.get('is_urgent', False),
                        # None for a brand-new item; a row id when we're
                        # editing an existing one (see FINAL SUBMIT).
                        "_edit_id":       rd.get('_edit_id')
                    })
                    st.session_state.rev_data = None
                    st.rerun()

    # ── PART B: DRAFT LIST ───────────────────────────────────
    if st.session_state.indent_cart:
        st.markdown(f"### 🛒 Current Draft List ({len(st.session_state.indent_cart)}/20)")
        for idx, item in enumerate(st.session_state.indent_cart):
            with st.container(border=True):
                d1, d2 = st.columns([5, 1])
                d1.write(
                    f"**{item['item_name']}** | "
                    f"{item['quantity']} {item['units']} | {item['job_no']}"
                )
                if item.get('specs'):
                    d1.caption(f"📐 Specs: {item['specs']}")
                if item.get('special_notes'):
                    d1.caption(f"📝 Notes: {item['special_notes']}")
                if d2.button("🗑️", key=f"del_draft_{idx}"):
                    st.session_state.indent_cart.pop(idx)
                    st.rerun()

        if st.button("🚀 FINAL SUBMIT INDENT", type="primary", use_container_width=True):
            try:
                cart      = st.session_state.indent_cart
                new_items = [i for i in cart if not i.get("_edit_id")]
                edits     = [i for i in cart if i.get("_edit_id")]

                # Only mint a new indent header if there's genuinely new
                # material. An all-edits submit keeps its original indent.
                new_id = None
                if new_items:
                    header = conn.table("indent_headers").insert(
                        {"raised_by": raised_by}
                    ).execute()
                    new_id = header.data[0]['indent_no']

                for item in new_items:
                    payload = {k: v for k, v in item.items() if k != "_edit_id"}
                    payload['indent_no'] = new_id
                    conn.table("purchase_orders").insert(payload).execute()

                for item in edits:
                    edit_id = item["_edit_id"]
                    payload = {k: v for k, v in item.items() if k != "_edit_id"}
                    payload['status'] = "Triggered"   # release the Editing lock
                    conn.table("purchase_orders").update(payload).eq("id", edit_id).execute()

                st.session_state.indent_cart = []
                st.session_state.rev_data    = None
                st.cache_data.clear()
                bits = []
                if new_items: bits.append(f"{len(new_items)} new item(s)")
                if edits:     bits.append(f"{len(edits)} updated")
                st.success("✅ Indent submitted — " + ", ".join(bits))
                st.rerun()
            except Exception as e:
                st.error(f"Submission Error: {e}")

    st.divider()

    # ── PART C: HISTORY, TRIGGER & EDIT/REVISE ───────────────
    st.subheader("🔍 Tracking & Adjustments")

    fc1, fc2, fc3 = st.columns(3)
    search_j   = fc1.selectbox("Filter by Job", ["ALL"] + get_jobs())
    search_sta = fc2.selectbox("Filter by Status",
        ["ALL", "Triggered", "Editing", "Ordered", "Partial", "Received", "Rejected"])
    show_all   = fc3.toggle("👥 Show All Users", value=False)

    try:
        hist_q = conn.table("purchase_orders").select("*") \
            .order("created_at", desc=True).limit(200)
        if not show_all:
            hist_q = hist_q.eq("triggered_by", raised_by)
        hist_data = hist_q.execute().data or []
    except Exception as e:
        st.error(f"History load error: {e}")
        hist_data = []

    if hist_data:
        df_h = pd.DataFrame(hist_data)
        if search_j   != "ALL": df_h = df_h[df_h['job_no'].str.contains(search_j, na=False)]
        if search_sta != "ALL": df_h = df_h[df_h['status'] == search_sta]

        if df_h.empty:
            st.info("No records match this filter.")
        else:
            if show_all:
                st.caption(f"Showing all users — {len(df_h)} record(s) found")
            else:
                st.caption(f"Showing indents raised by: **{raised_by}** — {len(df_h)} record(s)")

            for _, h_row in df_h.iterrows():
                row_id = h_row['id']
                status = h_row['status']
                is_urg = h_row.get('is_urgent', False)

                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    urg_icon = "🚨" if is_urg else "📦"
                    col1.write(f"**{urg_icon} {h_row['item_name']}** | Status: `{status}`")
                    col1.caption(
                        f"Job: {h_row['job_no']} | Qty: {h_row['quantity']} {h_row['units']}"
                        + (f" | 👤 {h_row['triggered_by']}" if show_all else "")
                    )
                    if h_row.get('specs'):
                        col1.caption(f"📐 Specs: {h_row['specs']}")
                    if h_row.get('special_notes'):
                        col1.caption(f"📝 Notes: {h_row['special_notes']}")

                    if status == "Rejected":
                        col1.error(f"Reason: {h_row.get('reject_note', 'No details')}")
                        if col2.button("📝 REVISE", key=f"rev_{row_id}", use_container_width=True):
                            st.session_state.rev_data = h_row
                            st.rerun()

                    if status == "Triggered":
                        if col2.button("✏️ EDIT", key=f"edit_{row_id}", use_container_width=True):
                            safe_db_write(
                                lambda: conn.table("purchase_orders")
                                    .update({"status": "Editing"})
                                    .eq("id", row_id).execute(),
                                error_prefix="Edit flag error"
                            )
                            st.session_state.rev_data = dict(h_row)
                            st.session_state.rev_data['_edit_id'] = row_id
                            st.rerun()

                        if not is_urg:
                            if col3.button("🚨", key=f"trig_{row_id}", help="Mark Urgent"):
                                safe_db_write(
                                    lambda: conn.table("purchase_orders")
                                        .update({"is_urgent": True})
                                        .eq("id", row_id).execute(),
                                    error_prefix="Urgent flag error"
                                )
                                st.rerun()
                        else:
                            col3.info("Priority")

                        if col4.button("🗑️", key=f"del_db_{row_id}", help="Delete"):
                            safe_db_write(
                                lambda: conn.table("purchase_orders")
                                    .delete().eq("id", row_id).execute(),
                                error_prefix="Delete error"
                            )
                            st.rerun()

                    if status == "Editing":
                        col1.warning("⚠️ Edit in progress")
                        if col2.button("▶️ RESUME", key=f"res_{row_id}", use_container_width=True):
                            st.session_state.rev_data = dict(h_row)
                            st.session_state.rev_data['_edit_id'] = row_id
                            st.rerun()
                        if col3.button("↩️ RESET", key=f"rst_{row_id}",
                                       help="Reset to Triggered", use_container_width=True):
                            safe_db_write(
                                lambda: conn.table("purchase_orders")
                                    .update({"status": "Triggered"})
                                    .eq("id", row_id).execute(),
                                success_msg="Reset to Triggered",
                                error_prefix="Reset error"
                            )
                            st.rerun()

                    if status in ["Ordered", "Received", "Partial"]:
                        col2.write("✅ Active")
    else:
        st.info("No indent history found.")

    st.divider()

    # ── RATE ENQUIRY SECTION ─────────────────────────────────
    st.subheader("💰 Rate Enquiry Requests")

    with st.expander("➕ Request Rate Enquiry", expanded=False):
        with st.form("rate_enq_form", clear_on_submit=True):
            re1, re2 = st.columns(2)
            re_item  = re1.text_input("Item Name*")
            re_specs = re2.text_input("Specifications")
            re3, re4, re5 = st.columns(3)
            re_qty  = re3.number_input("Qty", min_value=0.1, value=1.0)
            re_unit = re4.selectbox("Units", ["Nos", "Kgs", "Mts", "Sft", "Sets"])
            re_job  = re5.text_input("Job No (optional)")

            if st.form_submit_button("📨 Submit Rate Enquiry", use_container_width=True):
                if not re_item:
                    st.error("Item Name is required.")
                else:
                    safe_db_write(
                        lambda: conn.table("rate_enquiries").insert({
                            "requested_by": raised_by,
                            "item_name":    re_item.upper(),
                            "specs":        re_specs,
                            "quantity":     re_qty,
                            "units":        re_unit,
                            "job_no":       re_job,
                            "status":       "Pending"
                        }).execute(),
                        success_msg="✅ Rate enquiry submitted to Purchase team!",
                        error_prefix="Rate Enquiry Error"
                    )

    st.markdown("#### 📋 My Rate Enquiries")
    try:
        my_re      = conn.table("rate_enquiries").select("*") \
            .eq("requested_by", raised_by) \
            .order("created_at", desc=True).limit(30).execute()
        my_re_data = my_re.data or []
    except Exception as e:
        st.error(f"Rate enquiry load error: {e}")
        my_re_data = []

    if my_re_data:
        for re_row in my_re_data:
            re_status = re_row.get('status', 'Pending')
            with st.container(border=True):
                rc1, rc2 = st.columns([4, 1])
                status_icon = "🟡" if re_status == "Pending" else "🟢" if re_status == "Quoted" else "⚪"
                rc1.markdown(
                    f"**{re_row['item_name']}** | "
                    f"`{re_row['quantity']} {re_row['units']}` | "
                    f"Status: {status_icon} `{re_status}`"
                )
                if re_row.get('specs'):
                    rc1.caption(f"📐 Specs: {re_row['specs']}")
                if re_row.get('job_no'):
                    rc1.caption(f"Job: {re_row['job_no']}")
                try:
                    re_dt = pd.to_datetime(re_row['created_at']).astimezone(IST).strftime('%d-%m-%Y %I:%M %p')
                except Exception:
                    re_dt = str(re_row.get('created_at', ''))[:16]
                rc1.caption(f"🕐 Requested: {re_dt}")

                if re_status == "Quoted":
                    rc1.success(
                        f"💰 Rate: ₹{re_row.get('quoted_rate','—')} per {re_row['units']} | "
                        f"Vendor: {re_row.get('vendor_name','—')} | "
                        f"Remarks: {re_row.get('rate_remarks','—')}"
                    )
                    try:
                        qt = pd.to_datetime(re_row['quoted_at']).astimezone(IST).strftime('%d-%m-%Y %I:%M %p')
                    except Exception:
                        qt = '—'
                    rc1.caption(f"🕐 Quoted at: {qt}")

                if rc2.button("🗑️", key=f"re_del_{re_row['id']}", help="Delete"):
                    if re_status == "Pending":
                        safe_db_write(
                            lambda: conn.table("rate_enquiries")
                                .delete().eq("id", re_row['id']).execute(),
                            success_msg="Deleted.",
                            error_prefix="Delete Error"
                        )
                        st.rerun()
                    else:
                        st.warning("Only Pending enquiries can be deleted.")
    else:
        st.info("No rate enquiries raised yet.")

# ============================================================
# TAB 1: PURCHASE CONSOLE   (full drop-in replacement)
# ------------------------------------------------------------
# Replace everything in material_command_center from the line
#       with main_tabs[1]:
# up to (but NOT including) the line
#       # TAB 2: STORES GRN
# with the block below.
#
# Nothing else in the file needs to change. cutoff_90 is still
# defined here because the Stores GRN tab depends on it.
# ============================================================

with main_tabs[1]:
    st.subheader("🛒 Purchase Processing")

    vendors_raw    = get_vendors()
    vendor_options = {v['name']: v for v in vendors_raw}
    vendor_list    = ["--- Choose Vendor ---"] + list(vendor_options.keys())

    # Kept for Tab 2 (Stores GRN), which references cutoff_90
    cutoff_90 = str(date.today() - timedelta(days=90))

    # ── SEARCH & FILTER BAR ──────────────────────────────────
    PC_KEYS = ["pc_search", "pc_range", "pc_f_group", "pc_f_job",
               "pc_f_status", "pc_f_raiser", "pc_f_urgent"]

    with st.container(border=True):
        s1, s2 = st.columns([3, 1])
        pc_query = s1.text_input(
            "🔍 Search",
            placeholder="Indent no, item, specs, job/project, vendor, PO no, group, raised by…",
            key="pc_search",
            help="Space-separated words are ANDed. e.g. `107 steel` or `PO-22 anchor`"
        )
        pc_range = s2.selectbox(
            "Period",
            ["Last 30 days", "Last 90 days", "Last 180 days", "All time"],
            index=1, key="pc_range"
        )

        f1, f2, f3, f4, f5 = st.columns(5)
        pc_group  = f1.selectbox("Material Group", ["All"] + get_material_groups(), key="pc_f_group")
        pc_job    = f2.selectbox("Job / Project",  ["All"] + get_jobs(),            key="pc_f_job")
        pc_status = f3.selectbox(
            "Status",
            ["All (pending)", "Triggered", "Ordered", "Partial", "Rejected"],
            key="pc_f_status"
        )
        pc_raiser = f4.selectbox("Raised By", ["All"] + get_staff_list(), key="pc_f_raiser")
        pc_urgent = f5.selectbox("Priority", ["All", "🚨 Urgent only", "Normal only"], key="pc_f_urgent")

        r1, r2 = st.columns([1, 4])
        if r1.button("♻️ Reset filters", key="pc_reset", use_container_width=True):
            for k in PC_KEYS:
                st.session_state.pop(k, None)
            st.rerun()

        active_bits = []
        if pc_query:                     active_bits.append(f"“{pc_query}”")
        if pc_group  != "All":           active_bits.append(pc_group)
        if pc_job    != "All":           active_bits.append(f"Job {pc_job}")
        if pc_status != "All (pending)": active_bits.append(pc_status)
        if pc_raiser != "All":           active_bits.append(pc_raiser)
        if pc_urgent != "All":           active_bits.append(pc_urgent)
        if active_bits:
            r2.caption("Active filters: " + "  •  ".join(active_bits))

    # ── QUERY (server-side filters) ──────────────────────────
    range_days = {"Last 30 days": 30, "Last 90 days": 90,
                  "Last 180 days": 180, "All time": None}[pc_range]

    try:
        q = conn.table("purchase_orders").select("*").neq("status", "Editing")

        if pc_status == "All (pending)":
            q = q.neq("status", "Received").neq("status", "Rejected")
        else:
            q = q.eq("status", pc_status)

        if range_days:
            pc_cutoff = str(date.today() - timedelta(days=range_days))
            q = q.gte("created_at", f"{pc_cutoff}T00:00:00")

        if pc_group != "All":
            q = q.eq("material_group", pc_group)
        if pc_raiser != "All":
            q = q.eq("triggered_by", pc_raiser)

        pending_data = q.order("created_at", desc=True).limit(300).execute().data or []
    except Exception as e:
        st.error(f"Purchase load error: {e}")
        pending_data = []

    # ── CLIENT-SIDE FILTERS (job match, priority, free text) ──
    df_p = pd.DataFrame(pending_data) if pending_data else pd.DataFrame()

    if not df_p.empty:
        if 'is_urgent' not in df_p.columns:
            df_p['is_urgent'] = False
        df_p['is_urgent'] = df_p['is_urgent'].fillna(False)

        # job_no is stored comma-joined -> substring match
        if pc_job != "All" and 'job_no' in df_p.columns:
            df_p = df_p[df_p['job_no'].astype(str).str.contains(pc_job, case=False, na=False)]

        if pc_urgent == "🚨 Urgent only":
            df_p = df_p[df_p['is_urgent'] == True]
        elif pc_urgent == "Normal only":
            df_p = df_p[df_p['is_urgent'] != True]

    if not df_p.empty and pc_query:
        search_cols = ['indent_no', 'item_name', 'specs', 'job_no', 'po_no',
                       'purchase_reply', 'material_group', 'triggered_by',
                       'special_notes', 'units', 'status']
        use_cols = [c for c in search_cols if c in df_p.columns]
        blob = (
            df_p[use_cols].fillna("").astype(str)
            .agg(" | ".join, axis=1).str.lower()
        )
        mask = pd.Series(True, index=df_p.index)
        for term in pc_query.replace(",", " ").split():
            t = term.strip().lower().lstrip("#")
            if t:
                mask &= blob.str.contains(t, na=False, regex=False)
        df_p = df_p[mask]

    # ── RESULTS ──────────────────────────────────────────────
    if df_p.empty:
        if pending_data:
            st.info("No items match your search / filters. Try ♻️ Reset filters.")
        else:
            st.info(f"No purchase requests found for: {pc_range}.")
    else:
        n_items   = len(df_p)
        n_indents = df_p['indent_no'].nunique() if 'indent_no' in df_p.columns else 0
        n_urgent  = int(df_p['is_urgent'].sum())
        st.caption(
            f"Showing **{n_items}** item{'s' if n_items != 1 else ''} "
            f"across **{n_indents}** indent{'s' if n_indents != 1 else ''}"
            + (f"  •  🚨 {n_urgent} urgent" if n_urgent else "")
        )

        df_p['_has_urgent'] = df_p['is_urgent']
        df_p = df_p.sort_values(by=['_has_urgent', 'indent_no'], ascending=[False, False])

        for indent_no, indent_grp in df_p.groupby('indent_no', sort=False):
            indent_grp  = indent_grp.reset_index(drop=True)
            has_urgent  = indent_grp['is_urgent'].fillna(False).any()
            all_jobs    = ", ".join(sorted(indent_grp['job_no'].dropna().unique()))
            item_count  = len(indent_grp)
            raised_by_i = indent_grp.iloc[0].get('triggered_by', '—')
            mat_groups  = sorted(indent_grp['material_group'].dropna().unique())

            with st.container(border=True):
                st.markdown(
                    f"### {'🚨 ' if has_urgent else ''}Indent #{indent_no} &nbsp;"
                    f"<span style='font-size:14px; color:gray;'>"
                    f"{item_count} item{'s' if item_count>1 else ''} | "
                    f"Job(s): {all_jobs} | Raised by: {raised_by_i} | "
                    f"Groups: {', '.join(mat_groups)}</span>",
                    unsafe_allow_html=True
                )
                st.divider()

                for grp_idx, mat_grp in enumerate(mat_groups):
                    grp_items = indent_grp[
                        indent_grp['material_group'] == mat_grp
                    ].reset_index(drop=True)
                    gkey = f"{indent_no}_g{grp_idx}"

                    gh1, gh2 = st.columns([2.5, 2])
                    with gh1:
                        st.markdown(
                            f"#### 📦 {mat_grp} "
                            f"<span style='font-size:13px; color:gray;'>"
                            f"({len(grp_items)} item{'s' if len(grp_items)>1 else ''})"
                            f"</span>",
                            unsafe_allow_html=True
                        )
                        for item_idx, p_row in enumerate(grp_items.to_dict('records')):
                            row_id   = p_row['id']
                            status   = p_row['status']
                            ukey     = f"{gkey}_i{item_idx}"
                            urg_icon = "🚨" if p_row.get('is_urgent') else "▪️"

                            ic1, ic2, ic3, ic4 = st.columns([3.5, 1, 1, 1])
                            ic1.markdown(
                                f"{urg_icon} **{p_row['item_name']}** &nbsp;"
                                f"`{p_row['quantity']} {p_row.get('units','Nos')}` &nbsp;"
                                f"Job: {p_row['job_no']} &nbsp; `{status}`"
                            )
                            if p_row.get('specs'):
                                ic1.caption(f"📐 Specs: {p_row['specs']}")
                            if p_row.get('special_notes'):
                                ic1.caption(f"📝 Notes: {p_row['special_notes']}")
                            try:
                                indent_dt_fmt = pd.to_datetime(p_row['created_at']).astimezone(IST).strftime('%d-%m-%Y %I:%M %p')
                            except Exception:
                                indent_dt_fmt = str(p_row.get('created_at', ''))[:16]
                            ic1.caption(f"🕐 Indented: {indent_dt_fmt}")

                            if status == "Rejected":
                                ic1.error(f"Reason: {p_row.get('reject_note','No details')}")
                                if ic2.button("📝 Revise", key=f"pc_rev_{ukey}",
                                              use_container_width=True):
                                    st.session_state.rev_data = p_row
                                    st.rerun()

                            if status == "Triggered":
                                if not p_row.get('is_urgent'):
                                    if ic3.button("🚨", key=f"pc_trig_{ukey}", help="Mark Urgent"):
                                        safe_db_write(
                                            lambda rid=row_id: conn.table("purchase_orders")
                                                .update({"is_urgent": True})
                                                .eq("id", rid).execute(),
                                            error_prefix="Urgent flag error"
                                        )
                                        st.rerun()
                                else:
                                    ic3.caption("Priority")

                                if ic4.button("🗑️", key=f"pc_del_{ukey}", help="Delete item"):
                                    safe_db_write(
                                        lambda rid=row_id: conn.table("purchase_orders")
                                            .delete().eq("id", rid).execute(),
                                        error_prefix="Delete error"
                                    )
                                    st.rerun()

                            if status in ["Ordered", "Received"]:
                                ic2.write("✅ Active")

                    with gh2:
                        with st.container(border=True):
                            st.caption(f"Enquiry for **{mat_grp}** group")

                            sel_vendor = st.selectbox(
                                "Select vendor", options=vendor_list, key=f"pc_vsel_{gkey}"
                            )
                            v_info  = vendor_options.get(sel_vendor, {})
                            v_phone = clean_phone(v_info.get('phone_number', ""))
                            v_email = v_info.get('email', "")

                            item_lines = ""
                            for ii, row in enumerate(grp_items.to_dict('records')):
                                item_lines += (
                                    f"\n{ii+1}. {row['item_name']}"
                                    f" | Qty: {row['quantity']} {row.get('units','Nos')}"
                                    + (f" | Specs: {row['specs']}" if row.get('specs') else "")
                                )

                            wa_msg = (
                                f"B&G Engineering Industries — {mat_grp} Enquiry\n"
                                f"Indent Ref: #{indent_no}\n"
                                f"Date: {date.today().strftime('%d-%m-%Y')}\n"
                                f"{'='*28}\n"
                                f"{item_lines}\n"
                                f"{'='*28}\n"
                                f"Please share your best quote.\n"
                                f"Regards,\nSanthoshi,\nB&G Engineering Industries"
                            )
                            wa_base = f"https://wa.me/{v_phone}" if v_phone else "https://wa.me/"
                            wa_url  = f"{wa_base}?text={urllib.parse.quote(wa_msg)}"
                            wa_html = (
                                f'<a href="{wa_url}" target="_blank" style="text-decoration:none;">'
                                f'<div style="background:#25D366; color:white; padding:7px; '
                                f'border-radius:5px; text-align:center; font-weight:bold; '
                                f'margin-bottom:5px;">📲 WhatsApp — {mat_grp}</div></a>'
                            )
                            st.markdown(wa_html, unsafe_allow_html=True)

                            mail_subj     = urllib.parse.quote(
                                f"{mat_grp} Enquiry — Indent #{indent_no} | B&G Engineering Industries"
                            )
                            mail_body_str = (
                                f"Dear Sir/Madam,\n\n"
                                f"Please find our {mat_grp} material enquiry "
                                f"(Indent #{indent_no}):\n"
                                f"{item_lines}\n\n"
                                f"Kindly share your best quote at the earliest.\n\n"
                                f"Regards,\nSanthoshi\nB&G Engineering Industries"
                            )
                            mail_url  = (
                                f"mailto:{v_email}"
                                f"?subject={mail_subj}"
                                f"&body={urllib.parse.quote(mail_body_str)}"
                            )
                            mail_html = (
                                f'<a href="{mail_url}" style="text-decoration:none;">'
                                f'<div style="background:#007bff; color:white; padding:7px; '
                                f'border-radius:5px; text-align:center; font-weight:bold; '
                                f'margin-bottom:5px;">📧 Email — {mat_grp}</div></a>'
                            )
                            st.markdown(mail_html, unsafe_allow_html=True)

                            grp_ids      = grp_items['id'].tolist()
                            already_sent = grp_items['enquiry_sent_at'].notna().all() \
                                           if 'enquiry_sent_at' in grp_items.columns else False
                            if already_sent:
                                first_sent = grp_items['enquiry_sent_at'].min()
                                try:
                                    sent_fmt = pd.to_datetime(first_sent).strftime('%d-%m %I:%M %p')
                                except Exception:
                                    sent_fmt = str(first_sent)[:16]
                                st.success(f"✅ Enquiry sent: {sent_fmt}")
                            else:
                                if st.button("📬 Mark Enquiry Sent", key=f"pc_enq_{gkey}",
                                             use_container_width=True):
                                    now_ist = datetime.now(IST).isoformat()
                                    errors  = []
                                    for rid in grp_ids:
                                        try:
                                            conn.table("purchase_orders").update({
                                                "enquiry_sent_at": now_ist
                                            }).eq("id", rid).execute()
                                        except Exception as e:
                                            errors.append(str(e))
                                    if errors:
                                        st.error(f"Error: {errors[0]}")
                                    else:
                                        st.success("Enquiry timestamp recorded!")
                                        st.rerun()

                            item_rows_html = "".join([
                                f"<tr><td>{ii+1}</td><td><b>{r['item_name']}</b></td>"
                                f"<td>{r.get('specs','-')}</td>"
                                f"<td><b>{r['quantity']} {r.get('units','Nos')}</b></td>"
                                f"<td>{r['job_no']}</td></tr>"
                                for ii, r in enumerate(grp_items.to_dict('records'))
                            ])
                            html_form = (
                                f"<html><body>"
                                f"<table border='1' cellpadding='5' cellspacing='0'>"
                                f"<tr><td colspan='5' style='font-size:16pt;font-weight:bold;"
                                f"color:#003366;'>B&G ENGINEERING INDUSTRIES</td></tr>"
                                f"<tr><td colspan='2'>Indent Ref:</td>"
                                f"<td colspan='3'><b>#{indent_no}</b></td></tr>"
                                f"<tr><td colspan='2'>Material Group:</td>"
                                f"<td colspan='3'><b>{mat_grp}</b></td></tr>"
                                f"<tr><td colspan='2'>Date:</td>"
                                f"<td colspan='3'>{date.today().strftime('%d-%m-%Y')}</td></tr>"
                                f"<tr style='background:#003366;color:white;'>"
                                f"<td>#</td><td>Item</td><td>Specifications</td>"
                                f"<td>Qty</td><td>Job No</td></tr>"
                                f"{item_rows_html}"
                                f"</table></body></html>"
                            )
                            st.download_button(
                                label=f"📄 Export {mat_grp} (XLS)",
                                data=html_form,
                                file_name=f"BG_Indent{indent_no}_{mat_grp}.xls",
                                mime='application/vnd.ms-excel',
                                key=f"pc_dl_{gkey}",
                                use_container_width=True
                            )

                            with st.expander("✅ Confirm PO for this group"):
                                p_no  = st.text_input("PO No", key=f"pc_po_{gkey}")
                                p_rem = st.text_input(
                                    "Vendor / Remarks",
                                    value=sel_vendor if sel_vendor != "--- Choose Vendor ---" else "",
                                    key=f"pc_rem_{gkey}"
                                )
                                pd_c1, pd_c2 = st.columns(2)
                                p_date = pd_c1.date_input(
                                    "PO Date", value=date.today(), key=f"pc_pdate_{gkey}"
                                )
                                p_exp = pd_c2.date_input(
                                    "Expected Delivery",
                                    value=date.today() + timedelta(days=7),
                                    key=f"pc_pexp_{gkey}",
                                    help="Best estimate is fine. Drives the overdue alerts."
                                )
                                if st.button("Confirm Order", key=f"pc_ok_{gkey}",
                                             type="primary", use_container_width=True):
                                    if not p_no.strip():
                                        st.warning("PO No is required.")
                                    elif p_exp < p_date:
                                        st.warning("Expected delivery is before the PO date.")
                                    else:
                                        errors = []
                                        for rid in grp_ids:
                                            try:
                                                conn.table("purchase_orders").update({
                                                    "status":            "Ordered",
                                                    "po_no":             p_no.strip(),
                                                    "purchase_reply":    p_rem,
                                                    "po_date":           str(p_date),
                                                    "expected_delivery": str(p_exp)
                                                }).eq("id", rid).execute()
                                            except Exception as e:
                                                errors.append(str(e))
                                        if errors:
                                            st.error(f"Errors: {'; '.join(errors)}")
                                        else:
                                            st.success(f"✅ {mat_grp} items ordered!")
                                            st.cache_data.clear()
                                            st.rerun()

                            with st.expander("🚫 Reject this group"):
                                rej_r = st.text_area("Rejection reason", key=f"pc_rejr_{gkey}")
                                if st.button("Confirm Rejection", key=f"pc_rejb_{gkey}",
                                             type="secondary", use_container_width=True):
                                    if rej_r:
                                        errors = []
                                        for rid in grp_ids:
                                            try:
                                                conn.table("purchase_orders").update({
                                                    "status":      "Rejected",
                                                    "reject_note": rej_r
                                                }).eq("id", rid).execute()
                                            except Exception as e:
                                                errors.append(str(e))
                                        if errors:
                                            st.error(f"Errors: {'; '.join(errors)}")
                                        else:
                                            st.rerun()
                                    else:
                                        st.warning("Please provide a reason.")

                    if grp_idx < len(mat_groups) - 1:
                        st.markdown("---")

    # ── RATE ENQUIRIES FROM ESTIMATION ───────────────────────
    st.divider()
    st.subheader("💰 Rate Enquiries from Estimation Team")

    staff_contacts = get_staff_phones()

    try:
        all_re      = conn.table("rate_enquiries").select("*") \
            .eq("status", "Pending") \
            .order("created_at", desc=True).limit(50).execute()
        all_re_data = all_re.data or []
    except Exception as e:
        st.error(f"Rate enquiry load error: {e}")
        all_re_data = []

    if all_re_data:
        st.caption(f"{len(all_re_data)} pending rate enquiry/ies")
        for re_row in all_re_data:
            re_id     = re_row['id']
            requester = re_row.get('requested_by', '—')
            req_info  = staff_contacts.get(requester, {})
            req_phone = clean_phone(req_info.get('phone', ''))
            req_email = req_info.get('email', '')

            try:
                re_dt = pd.to_datetime(re_row['created_at']).astimezone(IST).strftime('%d-%m-%Y %I:%M %p')
            except Exception:
                re_dt = str(re_row.get('created_at', ''))[:16]

            with st.container(border=True):
                st.markdown(
                    f"**{re_row['item_name']}** | "
                    f"`{re_row['quantity']} {re_row['units']}` | "
                    f"👤 Requested by: **{requester}**"
                )
                if re_row.get('specs'):
                    st.caption(f"📐 Specs: {re_row['specs']}")
                if re_row.get('job_no'):
                    st.caption(f"Job: {re_row['job_no']}")
                st.caption(f"🕐 Requested: {re_dt}")

                pv1, pv2 = st.columns(2)

                with pv1:
                    with st.container(border=True):
                        st.caption("📤 Send Vendor Enquiry")
                        re_vsel   = st.selectbox(
                            "Select Vendor", vendor_list, key=f"re_vsel_{re_id}"
                        )
                        re_vinfo  = vendor_options.get(re_vsel, {})
                        re_vphone = clean_phone(re_vinfo.get('phone_number', ''))
                        re_vemail = re_vinfo.get('email', '')

                        re_va_msg = (
                            f"B&G Engineering Industries — Rate Enquiry\n"
                            f"Date: {date.today().strftime('%d-%m-%Y')}\n"
                            f"{'='*28}\n"
                            f"Item: {re_row['item_name']}\n"
                            f"Qty: {re_row['quantity']} {re_row['units']}\n"
                            + (f"Specs: {re_row['specs']}\n" if re_row.get('specs') else "")
                            + f"{'='*28}\n"
                            f"Please share your best rate.\n"
                            f"Regards,\nSanthoshi,\nB&G Engineering Industries"
                        )
                        re_wa_url = (
                            f"https://wa.me/{re_vphone}?text={urllib.parse.quote(re_va_msg)}"
                            if re_vphone else "https://wa.me/"
                        )
                        re_wa_html = (
                            f'<a href="{re_wa_url}" target="_blank" style="text-decoration:none;">'
                            f'<div style="background:#25D366; color:white; padding:7px; '
                            f'border-radius:5px; text-align:center; font-weight:bold; '
                            f'margin-bottom:5px;">📲 WhatsApp Vendor</div></a>'
                        )
                        st.markdown(re_wa_html, unsafe_allow_html=True)

                        re_mail_subj = urllib.parse.quote(
                            f"Rate Enquiry — {re_row['item_name']} | B&G Engineering Industries"
                        )
                        re_mail_body = urllib.parse.quote(
                            f"Dear Sir/Madam,\n\n"
                            f"Please find our rate enquiry:\n\n"
                            f"Item: {re_row['item_name']}\n"
                            f"Qty: {re_row['quantity']} {re_row['units']}\n"
                            + (f"Specs: {re_row['specs']}\n" if re_row.get('specs') else "")
                            + f"\nKindly share your best rate at the earliest.\n\n"
                            f"Regards,\nSanthoshi\nB&G Engineering Industries"
                        )
                        re_mail_url  = f"mailto:{re_vemail}?subject={re_mail_subj}&body={re_mail_body}"
                        re_mail_html = (
                            f'<a href="{re_mail_url}" style="text-decoration:none;">'
                            f'<div style="background:#007bff; color:white; padding:7px; '
                            f'border-radius:5px; text-align:center; font-weight:bold; '
                            f'margin-bottom:5px;">📧 Email Vendor</div></a>'
                        )
                        st.markdown(re_mail_html, unsafe_allow_html=True)

                with pv2:
                    with st.container(border=True):
                        st.caption("📥 Enter Quoted Rate & Notify Requester")
                        q_vendor  = st.text_input(
                            "Vendor Name",
                            value=re_vsel if re_vsel != "--- Choose Vendor ---" else "",
                            key=f"re_qvend_{re_id}"
                        )
                        q_rate    = st.number_input(
                            f"Rate per {re_row['units']} (₹)",
                            min_value=0.0, step=0.5,
                            key=f"re_rate_{re_id}"
                        )
                        q_remarks = st.text_input(
                            "Remarks (validity, taxes, delivery etc.)",
                            key=f"re_rem_{re_id}"
                        )

                        quote_summary = (
                            f"B&G Engineering Industries — Rate Quote\n"
                            f"{'='*28}\n"
                            f"Item: {re_row['item_name']}\n"
                            + (f"Specs: {re_row['specs']}\n" if re_row.get('specs') else "")
                            + f"Qty: {re_row['quantity']} {re_row['units']}\n"
                            f"{'='*28}\n"
                            f"Vendor: {q_vendor}\n"
                            f"Rate: Rs.{q_rate} per {re_row['units']}\n"
                            f"Total (approx): Rs.{round(q_rate * re_row['quantity'], 2)}\n"
                            + (f"Remarks: {q_remarks}\n" if q_remarks else "")
                            + f"{'='*28}\n"
                            f"Regards,\nSanthoshi,\nB&G Engineering Industries"
                        )

                        req_wa_url  = (
                            f"https://wa.me/{req_phone}?text={urllib.parse.quote(quote_summary)}"
                            if req_phone else "https://wa.me/"
                        )
                        req_wa_html = (
                            f'<a href="{req_wa_url}" target="_blank" style="text-decoration:none;">'
                            f'<div style="background:#25D366; color:white; padding:7px; '
                            f'border-radius:5px; text-align:center; font-weight:bold; '
                            f'margin-bottom:5px;">📲 WhatsApp Quote → {requester}</div></a>'
                        )
                        st.markdown(req_wa_html, unsafe_allow_html=True)

                        req_mail_subj = urllib.parse.quote(
                            f"Rate Quote — {re_row['item_name']} | B&G Engineering Industries"
                        )
                        req_mail_body = urllib.parse.quote(
                            f"Dear {requester},\n\n"
                            f"Please find the rate quote for your enquiry:\n\n"
                            f"Item: {re_row['item_name']}\n"
                            + (f"Specs: {re_row['specs']}\n" if re_row.get('specs') else "")
                            + f"Qty: {re_row['quantity']} {re_row['units']}\n\n"
                            f"Vendor: {q_vendor}\n"
                            f"Rate: Rs.{q_rate} per {re_row['units']}\n"
                            f"Total (approx): Rs.{round(q_rate * re_row['quantity'], 2)}\n"
                            + (f"Remarks: {q_remarks}\n" if q_remarks else "")
                            + f"\nRegards,\nSanthoshi\nB&G Engineering Industries"
                        )
                        req_mail_url  = (
                            f"mailto:{req_email}"
                            f"?subject={req_mail_subj}"
                            f"&body={req_mail_body}"
                        )
                        req_mail_html = (
                            f'<a href="{req_mail_url}" style="text-decoration:none;">'
                            f'<div style="background:#007bff; color:white; padding:7px; '
                            f'border-radius:5px; text-align:center; font-weight:bold; '
                            f'margin-bottom:5px;">📧 Email Quote → {requester}</div></a>'
                        )
                        st.markdown(req_mail_html, unsafe_allow_html=True)

                        if st.button(
                            "✅ Save Rate & Mark Quoted",
                            key=f"re_save_{re_id}",
                            type="primary",
                            use_container_width=True
                        ):
                            if q_rate <= 0:
                                st.warning("Please enter a valid rate.")
                            elif not q_vendor:
                                st.warning("Please enter vendor name.")
                            else:
                                safe_db_write(
                                    lambda: conn.table("rate_enquiries").update({
                                        "status":       "Quoted",
                                        "vendor_name":  q_vendor,
                                        "quoted_rate":  q_rate,
                                        "rate_remarks": q_remarks,
                                        "quoted_at":    datetime.now(IST).isoformat()
                                    }).eq("id", re_id).execute(),
                                    success_msg="✅ Rate saved! Send the quote via WhatsApp/Email above.",
                                    error_prefix="Rate Save Error"
                                )
                                st.rerun()
    else:
        st.info("✅ No pending rate enquiries.")

# ============================================================
# TAB 2: STORES GRN
# ============================================================
with main_tabs[2]:
    st.subheader("📦 Goods Receipt Note (GRN) Desk")

    po_search = st.text_input(
        "🔍 Search by PO or Item", placeholder="e.g. PO-107", key="grn_search"
    )

    try:
        res_s = conn.table("purchase_orders").select("*") \
            .in_("status", ["Ordered", "Partial"]) \
            .not_.is_("indent_no", "null") \
            .gte("created_at", f"{cutoff_90}T00:00:00") \
            .limit(100).execute()
        stores_data = res_s.data or []
    except Exception as e:
        st.error(f"GRN load error: {e}")
        stores_data = []

    if stores_data:
        df_s = pd.DataFrame(stores_data)
        if po_search:
            df_s = df_s[
                df_s['po_no'].str.contains(po_search, case=False, na=False) |
                df_s['item_name'].str.contains(po_search, case=False, na=False)
            ]

        po_ids = df_s['id'].tolist()
        try:
            grn_res  = conn.table("grn_receipts").select("*").in_("po_id", po_ids).execute()
            grn_data = grn_res.data or []
        except Exception:
            grn_data = []

        receipts_by_po = defaultdict(list)
        for r in grn_data:
            receipts_by_po[r['po_id']].append(r)

        partial_count = sum(1 for r in stores_data if r.get('status') == 'Partial')
        ordered_count = sum(1 for r in stores_data if r.get('status') == 'Ordered')
        st.markdown(
            f"**Pending Arrivals: {len(df_s)}** &nbsp;|&nbsp; "
            f"🆕 New: {ordered_count} &nbsp;|&nbsp; "
            f"🔄 Partial: {partial_count}"
        )

        for s_idx, s_row in enumerate(df_s.to_dict('records')):
            row_id      = s_row['id']
            ordered_qty = float(s_row.get('quantity', 0))
            units       = s_row.get('units', 'Nos')
            past        = receipts_by_po.get(row_id, [])
            recd_so_far = sum(float(r.get('received_qty', 0)) for r in past)
            balance_qty = max(0, ordered_qty - recd_so_far)
            pct_done    = min(100, int((recd_so_far / ordered_qty * 100) if ordered_qty else 0))
            skey        = f"grn_{row_id}"
            is_partial  = s_row.get('status') == 'Partial'

            with st.container(border=True):
                c_info, c_status, c_action = st.columns([2.5, 1.2, 1.8])

                with c_info:
                    st.markdown(
                        f"#### PO: {s_row.get('po_no','N/A')} "
                        f"{'🔄' if is_partial else '🆕'}"
                    )
                    st.markdown(f"**{s_row['item_name']}** | Job: `{s_row['job_no']}`")
                    st.caption(
                        f"Indent: #{s_row.get('indent_no')} "
                        f"| Vendor: {s_row.get('purchase_reply','-')} "
                        f"| Group: {s_row.get('material_group','-')}"
                    )
                    if s_row.get('specs'):
                        st.caption(f"📐 Specs: {s_row['specs']}")
                    if s_row.get('special_notes'):
                        st.caption(f"📝 Notes: {s_row['special_notes']}")

                    if past:
                        with st.expander(
                            f"📋 Receipt history ({len(past)} delivery/ies — "
                            f"{recd_so_far:.1f} of {ordered_qty:.1f} {units} received)"
                        ):
                            for pr in sorted(past, key=lambda x: x.get('received_date','')):
                                st.markdown(
                                    f"- **{pr.get('received_date','?')}** — "
                                    f"`{pr.get('received_qty',0)} {units}` | "
                                    f"DC: {pr.get('dc_no','-')} | "
                                    f"{pr.get('remarks','-')}"
                                )

                with c_status:
                    if is_partial:
                        st.warning("🔄 Partial")
                    else:
                        st.info("🚚 In-Transit")
                    st.caption(f"Ordered: {ordered_qty:.1f} {units}")
                    if recd_so_far > 0:
                        st.caption(f"Received: {recd_so_far:.1f} {units}")
                        st.caption(f"Balance: **{balance_qty:.1f} {units}**")
                    st.progress(pct_done / 100)
                    st.caption(f"{pct_done}% fulfilled")

                with c_action:
                    st.markdown("**Record Receipt**")
                    recv_qty = st.number_input(
                        f"Qty received ({units})",
                        min_value=0.1,
                        max_value=float(balance_qty) if balance_qty > 0 else 0.1,
                        value=float(balance_qty) if balance_qty > 0 else 0.1,
                        step=0.1,
                        key=f"rqty_{skey}"
                    )
                    dc_no = st.text_input(
                        "DC / Vehicle No", key=f"dc_{skey}", placeholder="DC-123"
                    )
                    s_rem = st.text_input(
                        "Remarks", key=f"srem_{skey}", placeholder="Shortage/Damage/OK?"
                    )

                    is_full_receipt = abs(recv_qty - balance_qty) < 0.01
                    btn_label = (
                        "✅ Full Receipt — Close PO"
                        if is_full_receipt
                        else f"📦 Partial Receipt ({recv_qty} {units})"
                    )

                    if st.button(btn_label, key=f"btn_{skey}",
                                 use_container_width=True, type="primary"):
                        if not dc_no:
                            st.warning("Please enter DC / Vehicle No")
                        elif recv_qty <= 0:
                            st.warning("Quantity must be greater than 0")
                        else:
                            grn_ok = safe_db_write(
                                lambda: conn.table("grn_receipts").insert({
                                    "po_id":         row_id,
                                    "received_qty":  recv_qty,
                                    "dc_no":         dc_no,
                                    "remarks":       s_rem,
                                    "received_date": str(date.today())
                                }).execute(),
                                error_prefix="GRN Insert Error"
                            )
                            if grn_ok:
                                new_status     = "Received" if is_full_receipt else "Partial"
                                update_payload = {"status": new_status}
                                if is_full_receipt:
                                    update_payload["received_date"]  = str(date.today())
                                    update_payload["stores_remarks"] = (
                                        f"DC: {dc_no} | {s_rem} | "
                                        f"Full qty {ordered_qty} {units} received"
                                    )
                                safe_db_write(
                                    lambda pl=update_payload:
                                        conn.table("purchase_orders")
                                            .update(pl).eq("id", row_id).execute(),
                                    success_msg=(
                                        "✅ PO closed — full qty received!"
                                        if is_full_receipt
                                        else f"📦 Partial GRN recorded. "
                                             f"Balance: {balance_qty - recv_qty:.1f} {units}"
                                    ),
                                    error_prefix="Status Update Error"
                                )
                                st.rerun()
    else:
        st.info("🚚 No pending arrivals (last 90 days).")

    st.divider()
    with st.expander("🕒 GRN Audit Trail — All Receipts"):
        try:
            recent_res = conn.table("grn_receipts").select(
                "*, purchase_orders(po_no, item_name, job_no, quantity, units)"
            ).order("received_date", desc=True).limit(20).execute()

            if recent_res.data:
                rows = []
                for r in recent_res.data:
                    po = r.get('purchase_orders') or {}
                    rows.append({
                        "Date":     r.get('received_date', ''),
                        "PO No":    po.get('po_no', '-'),
                        "Item":     po.get('item_name', '-'),
                        "Job":      po.get('job_no', '-'),
                        "Recd Qty": r.get('received_qty', 0),
                        "Units":    po.get('units', '-'),
                        "DC No":    r.get('dc_no', '-'),
                        "Remarks":  r.get('remarks', '-'),
                    })
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                fallback = conn.table("purchase_orders").select("*") \
                    .eq("status", "Received") \
                    .not_.is_("indent_no", "null") \
                    .order("received_date", desc=True).limit(10).execute()
                if fallback.data:
                    df_fb = pd.DataFrame(fallback.data)
                    cols  = [c for c in [
                        'received_date', 'po_no', 'item_name',
                        'quantity', 'job_no', 'stores_remarks'
                    ] if c in df_fb.columns]
                    st.dataframe(df_fb[cols], use_container_width=True, hide_index=True)
                else:
                    st.info("No receipts recorded yet.")
        except Exception as e:
            st.error(f"Audit load error: {e}")


# ============================================================
# TAB 3: ANALYTICS   (full drop-in replacement)
# ------------------------------------------------------------
# Replace everything from the line
#       with main_tabs[3]:
# up to (but NOT including) the line
#       # TAB 4: MASTER SETUP
# with the block below.
#
# WHY THIS CHANGED
# po_date and expected_delivery are null on all 525 rows, so every
# metric routed through them rendered as "—" and Overdue was always 0.
# All timings are now measured from fields that are actually written:
#   created_at (indent)  ->  enquiry_sent_at  ->  received_date / GRN
# Overdue-vs-promise is replaced by AGE, which is measurable today.
# ============================================================

with main_tabs[3]:
    st.subheader("📊 Procurement Analytics — Cycle Times & Ageing")

    # Days an OPEN item can sit before it's called aged. No promised
    # delivery date exists anywhere in the data, so this is our own
    # service-level line, not a vendor commitment.
    AGED_DAYS      = 14
    ENQUIRY_SLA    = 1     # indent -> enquiry sent
    OPEN_STATUSES  = ['Triggered', 'Editing', 'Ordered', 'Partial']

    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    cutoff_opts = {"Last 30 days": 30, "Last 60 days": 60,
                   "Last 90 days": 90, "Last 180 days": 180, "All time": 3650}
    cutoff_sel  = fc1.selectbox("Date Range", list(cutoff_opts.keys()),
                                index=2, key="an_range")
    cutoff_days = cutoff_opts[cutoff_sel]
    cutoff_date = date.today() - timedelta(days=cutoff_days)

    an_status = fc2.selectbox(
        "Status", ["All", "Open only", "Triggered", "Editing",
                   "Ordered", "Partial", "Received", "Rejected"],
        key="an_status"
    )
    an_group = fc3.selectbox("Material Group", ["All"] + get_material_groups(),
                             key="an_group")
    an_age   = fc4.selectbox(
        "Ageing", ["All items", f"Aged open (>{AGED_DAYS}d)",
                   "Awaiting enquiry", "Stuck in edit"],
        key="an_age"
    )
    an_job   = fc5.selectbox("Job No", ["All"] + get_jobs(), key="an_job")

    try:
        an_res = conn.table("purchase_orders").select("*") \
            .gte("created_at", f"{cutoff_date}T00:00:00") \
            .order("created_at", desc=True).limit(1000).execute()
        an_data = an_res.data or []
    except Exception as e:
        st.error(f"Analytics load error: {e}")
        an_data = []

    try:
        if an_data:
            an_ids = [r['id'] for r in an_data]
            grn_an = conn.table("grn_receipts") \
                .select("po_id, received_date, received_qty") \
                .in_("po_id", an_ids).execute()
            grn_an_data = grn_an.data or []
        else:
            grn_an_data = []
    except Exception:
        grn_an_data = []

    grn_lookup = defaultdict(lambda: {"first_date": None, "last_date": None,
                                      "total_qty": 0.0, "n": 0})
    for g in grn_an_data:
        pid = g['po_id']
        grn_lookup[pid]["total_qty"] += float(g.get('received_qty', 0) or 0)
        grn_lookup[pid]["n"] += 1
        fd = g.get('received_date')
        if fd:
            if grn_lookup[pid]["first_date"] is None or fd < grn_lookup[pid]["first_date"]:
                grn_lookup[pid]["first_date"] = fd
            if grn_lookup[pid]["last_date"] is None or fd > grn_lookup[pid]["last_date"]:
                grn_lookup[pid]["last_date"] = fd

    if not an_data:
        st.info(f"No purchase data found for: {cutoff_sel}.")
    else:
        df_an   = pd.DataFrame(an_data)
        today_d = date.today()

        def to_date(val):
            if val is None or (isinstance(val, float) and pd.isna(val)) or val == '':
                return None
            try:
                d = pd.to_datetime(val)
                return d.date() if pd.notnull(d) else None
            except Exception:
                return None

        def days_between(d1, d2):
            return (d2 - d1).days if (d1 and d2) else None

        def fmt_date(d):
            return d.strftime('%d-%m-%Y') if d else '—'

        def sval(v, dash="—"):
            """None / NaN / blank -> dash. NaN is truthy, so `v or x` fails."""
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return dash
            t = str(v).strip()
            return t if t and t.lower() not in ("nan", "none", "nat") else dash

        def ival(v):
            """Integer-ish display for null-heavy int columns (41.0 -> 41)."""
            return "—" if v is None or pd.isna(v) else str(int(v))

        def truthy(v):
            """is_urgent can arrive as bool, text 'true'/'false', or null."""
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in ('true', 't', 'yes', '1')

        # FIX: pd.DataFrame() turns None into NaN inside numeric columns, so
        # the old `if d is None` test missed them and printed "nand".
        def day_cell(d, warn_above=None):
            if d is None or pd.isna(d):
                return '—'
            d = int(d)
            if warn_above is not None and d > warn_above:
                return f"⚠️ {d}d"
            return f"{d}d"

        def age_bucket(d):
            if d is None or pd.isna(d):
                return "unknown"
            d = int(d)
            if d <= 3:   return "0–3d"
            if d <= 7:   return "4–7d"
            if d <= 14:  return "8–14d"
            if d <= 30:  return "15–30d"
            return "30d+"

        rows = []
        for _, r in df_an.iterrows():
            status       = r.get('status', '')
            indent_date  = to_date(r.get('created_at'))
            enquiry_date = to_date(r.get('enquiry_sent_at'))
            grn_info     = grn_lookup.get(r['id'], {})
            first_grn    = to_date(grn_info.get('first_date'))
            last_grn     = to_date(grn_info.get('last_date'))
            recv_col     = to_date(r.get('received_date'))
            # First physical arrival, whichever source recorded it.
            eff_receipt  = first_grn or recv_col
            closed_on    = last_grn or recv_col

            total_recd   = float(grn_info.get('total_qty', 0) or 0)
            ordered_qty  = float(r.get('quantity', 0) or 0)
            is_open      = status in OPEN_STATUSES

            d_indent_enq  = days_between(indent_date, enquiry_date)
            d_enq_recv    = days_between(enquiry_date, eff_receipt)
            d_indent_recv = days_between(indent_date, eff_receipt)
            # Open items have no end date yet — clock runs to today.
            age_days      = days_between(indent_date, today_d) if is_open else None

            if ordered_qty > 0:
                pct = min(100, round(total_recd / ordered_qty * 100))
            else:
                pct = 100 if status == 'Received' else 0

            rows.append({
                'id':             r.get('id'),
                'indent_no':      r.get('indent_no'),
                'item_name':      r.get('item_name', ''),
                'material_group': sval(r.get('material_group')),
                'job_no':         sval(r.get('job_no')),
                'triggered_by':   sval(r.get('triggered_by')),
                'status':         status,
                'is_open':        is_open,
                'is_urgent':      truthy(r.get('is_urgent')),
                'quantity':       ordered_qty,
                'received_qty':   total_recd,
                'units':          sval(r.get('units'), dash=''),
                'po_no':          sval(r.get('po_no'), dash=''),
                'vendor':         sval(r.get('purchase_reply'), dash=''),
                'indent_date':    indent_date,
                'enquiry_date':   enquiry_date,
                'receipt_date':   eff_receipt,
                'closed_date':    closed_on,
                'n_receipts':     grn_info.get('n', 0),
                'd_indent_enq':   d_indent_enq,
                'd_enq_recv':     d_enq_recv,
                'd_indent_recv':  d_indent_recv,
                'age_days':       age_days,
                'pct_fulfilled':  pct,
            })

        df_view = pd.DataFrame(rows)

        # Coerce day columns to numeric so sorts and means never hit
        # mixed None/int object columns.
        for c in ['d_indent_enq', 'd_enq_recv', 'd_indent_recv', 'age_days']:
            df_view[c] = pd.to_numeric(df_view[c], errors='coerce')

        df_view['awaiting_enquiry'] = (
            (df_view['status'] == 'Triggered') & df_view['enquiry_date'].isna()
        )
        df_view['aged_open'] = df_view['is_open'] & (df_view['age_days'] > AGED_DAYS)

        # ── FILTERS ──────────────────────────────────────────
        if an_status == "Open only":
            df_view = df_view[df_view['is_open']]
        elif an_status != "All":
            df_view = df_view[df_view['status'] == an_status]
        if an_group != "All":
            df_view = df_view[df_view['material_group'] == an_group]
        if an_job != "All":
            df_view = df_view[df_view['job_no'].astype(str)
                              .str.contains(an_job, case=False, na=False)]
        if an_age == f"Aged open (>{AGED_DAYS}d)":
            df_view = df_view[df_view['aged_open']]
        elif an_age == "Awaiting enquiry":
            df_view = df_view[df_view['awaiting_enquiry']]
        elif an_age == "Stuck in edit":
            df_view = df_view[df_view['status'] == 'Editing']

        if df_view.empty:
            st.info("No items match these filters.")
        else:
            open_df   = df_view[df_view['is_open']]
            closed_df = df_view[df_view['d_indent_recv'].notna()]

            avg_i_enq  = df_view['d_indent_enq'].mean()
            avg_i_recv = closed_df['d_indent_recv'].mean()
            aged_n     = int(df_view['aged_open'].sum())
            no_enq_n   = int(df_view['awaiting_enquiry'].sum())

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Total items", len(df_view))
            m2.metric("Still open", len(open_df))
            m3.metric("Avg Indent→Enquiry",
                      f"{avg_i_enq:.1f}d" if pd.notna(avg_i_enq) else "—",
                      help=f"Target: within {ENQUIRY_SLA}d of the indent.")
            m4.metric("Avg Indent→Receipt",
                      f"{avg_i_recv:.1f}d" if pd.notna(avg_i_recv) else "—",
                      help=f"Measured on {len(closed_df)} item(s) that actually arrived.")
            m5.metric(f"Aged open (>{AGED_DAYS}d)", aged_n,
                      delta=f"{aged_n} items" if aged_n else None,
                      delta_color="inverse")

            st.divider()

            # ── ACTION QUEUES ────────────────────────────────
            stuck_df = df_view[df_view['status'] == 'Editing']
            noenq_df = df_view[df_view['awaiting_enquiry']]

            if not stuck_df.empty:
                with st.expander(
                    f"⚪ {len(stuck_df)} item(s) stuck in Editing — invisible to Purchase",
                    expanded=True
                ):
                    st.caption(
                        "The Purchase Console filters out `Editing`. These will "
                        "never be actioned until someone opens the Indent tab and "
                        "hits RESUME or RESET."
                    )
                    for _, s in stuck_df.sort_values('age_days', ascending=False).iterrows():
                        st.warning(
                            f"**{s['item_name']}** · Indent #{ival(s['indent_no'])} · "
                            f"Job {s['job_no']} · {s['triggered_by']} · "
                            f"**{day_cell(s['age_days'])}** in edit"
                        )

            if not noenq_df.empty:
                with st.expander(
                    f"📭 {len(noenq_df)} indent(s) with no vendor enquiry sent",
                    expanded=False
                ):
                    st.dataframe(
                        pd.DataFrame({
                            "Item":     noenq_df['item_name'],
                            "Group":    noenq_df['material_group'],
                            "Job":      noenq_df['job_no'],
                            "Raised by": noenq_df['triggered_by'],
                            "Waiting":  noenq_df['age_days'].apply(day_cell),
                        }).sort_values("Waiting", ascending=False),
                        use_container_width=True, hide_index=True
                    )

            # ── AGEING PROFILE ───────────────────────────────
            if not open_df.empty:
                st.markdown("#### ⏳ Ageing of open items")
                open_df = open_df.copy()
                open_df['bucket'] = open_df['age_days'].apply(age_bucket)
                order = ["0–3d", "4–7d", "8–14d", "15–30d", "30d+", "unknown"]
                prof = (open_df.groupby('bucket')
                        .agg(Items=('id', 'count'),
                             Urgent=('is_urgent', 'sum'))
                        .reindex(order).dropna(how='all').reset_index())
                prof.columns = ['Age', 'Items', '🚨 Urgent']
                prof['Items'] = prof['Items'].astype(int)
                prof['🚨 Urgent'] = prof['🚨 Urgent'].astype(int)
                ac1, ac2 = st.columns([1, 2])
                with ac1:
                    st.dataframe(prof, use_container_width=True, hide_index=True)
                with ac2:
                    st.bar_chart(prof.set_index('Age')['Items'], height=220)

                worst = open_df.sort_values('age_days', ascending=False).head(10)
                st.markdown("**Oldest open items**")
                st.dataframe(
                    pd.DataFrame({
                        "":        worst['is_urgent'].apply(lambda u: "🚨" if u else ""),
                        "Item":    worst['item_name'],
                        "Job":     worst['job_no'],
                        "Status":  worst['status'],
                        "Vendor":  worst['vendor'].apply(sval),
                        "Age":     worst['age_days'].apply(day_cell),
                    }),
                    use_container_width=True, hide_index=True
                )

            st.divider()

            # ── ITEM-WISE TIMELINE ───────────────────────────
            st.markdown("#### 📋 Item-wise Procurement Timeline")

            status_colors = {
                'Triggered': '🟡', 'Ordered': '🔵', 'Partial': '🟠',
                'Received': '🟢', 'Rejected': '🔴', 'Editing': '⚪'
            }

            def outcome(r):
                if r['is_open']:
                    a = r['age_days']
                    if pd.isna(a):
                        return "🟡 Open"
                    return (f"🔴 Open {int(a)}d" if a > AGED_DAYS
                            else f"🟡 Open {int(a)}d")
                if pd.notna(r['d_indent_recv']):
                    return f"✅ Closed in {int(r['d_indent_recv'])}d"
                if r['status'] == 'Rejected':
                    return "🔴 Rejected"
                return "⚪ Closed, no date"

            disp = pd.DataFrame({
                'Indent #':     df_view['indent_no'].apply(
                                    lambda v: "—" if pd.isna(v) else f"#{int(v)}"),
                'Item':         df_view.apply(
                                    lambda r: ('🚨 ' if r['is_urgent'] else '')
                                              + str(r['item_name']), axis=1),
                'Group':        df_view['material_group'],
                'Job':          df_view['job_no'],
                'Raised By':    df_view['triggered_by'],
                'Vendor':       df_view['vendor'].apply(sval),
                'Status':       df_view['status'].apply(
                                    lambda s: status_colors.get(s, '⚪') + ' ' + str(s)),
                'PO No':        df_view['po_no'].apply(sval),
                'Indent Date':  df_view['indent_date'].apply(fmt_date),
                'Enquiry Sent': df_view['enquiry_date'].apply(fmt_date),
                'Received':     df_view['receipt_date'].apply(fmt_date),
                'I→Enq':        df_view['d_indent_enq'].apply(
                                    lambda d: day_cell(d, warn_above=ENQUIRY_SLA)),
                'Enq→Recv':     df_view['d_enq_recv'].apply(
                                    lambda d: day_cell(d, warn_above=20)),
                'Total':        df_view['d_indent_recv'].apply(
                                    lambda d: day_cell(d, warn_above=AGED_DAYS)),
                'Outcome':      df_view.apply(outcome, axis=1),
                'Qty':          df_view.apply(
                                    lambda r: f"{r['received_qty']:g}/{r['quantity']:g} "
                                              f"{r['units']}".strip(), axis=1),
                'Fulfilled':    df_view['pct_fulfilled'].apply(lambda p: f"{p}%"),
            })
            st.dataframe(disp, use_container_width=True, hide_index=True, height=420)

            st.download_button(
                "📥 Export Timeline (CSV)",
                data=disp.to_csv(index=False).encode('utf-8'),
                file_name=f"BG_Procurement_Analytics_{date.today()}.csv",
                mime="text/csv", key="an_dl_csv"
            )

            st.divider()

            # ── MATERIAL GROUP ───────────────────────────────
            st.markdown("#### 📦 Cycle time by material group")
            grp = df_view.groupby('material_group').agg(
                Items     =('id',             'count'),
                Open      =('is_open',        'sum'),
                Aged      =('aged_open',      'sum'),
                AvgIEnq   =('d_indent_enq',   'mean'),
                AvgIRecv  =('d_indent_recv',  'mean'),
            ).reset_index()
            grp.columns = ['Material Group', 'Items', 'Open',
                           f'Aged >{AGED_DAYS}d', 'Avg I→Enq (d)', 'Avg I→Recv (d)']
            for c in ['Avg I→Enq (d)', 'Avg I→Recv (d)']:
                grp[c] = grp[c].apply(lambda x: f"{x:.1f}" if pd.notna(x) else '—')
            for c in ['Open', f'Aged >{AGED_DAYS}d']:
                grp[c] = grp[c].astype(int)
            st.dataframe(grp.sort_values('Items', ascending=False),
                         use_container_width=True, hide_index=True)

            # ── VENDOR ───────────────────────────────────────
            st.markdown("#### 🤝 Vendor delivery performance")
            st.caption(
                "Measured indent→receipt, since no PO date or promised "
                "delivery date is recorded anywhere in the data."
            )
            vdf = df_view[df_view['vendor'].astype(str).str.strip() != '']
            if vdf.empty:
                st.info("No vendor data available yet.")
            else:
                vend = vdf.groupby('vendor').agg(
                    Orders   =('id',            'count'),
                    Open     =('is_open',       'sum'),
                    Aged     =('aged_open',     'sum'),
                    Delivered=('d_indent_recv', 'count'),
                    AvgDays  =('d_indent_recv', 'mean'),
                    WorstDays=('d_indent_recv', 'max'),
                ).reset_index()
                vend.columns = ['Vendor', 'Orders', 'Open', f'Aged >{AGED_DAYS}d',
                                'Delivered', 'Avg I→Recv (d)', 'Worst (d)']
                vend['Avg I→Recv (d)'] = vend['Avg I→Recv (d)'].apply(
                    lambda x: f"{x:.1f}" if pd.notna(x) else '—')
                vend['Worst (d)'] = vend['Worst (d)'].apply(
                    lambda x: f"{int(x)}" if pd.notna(x) else '—')
                for c in ['Open', f'Aged >{AGED_DAYS}d']:
                    vend[c] = vend[c].astype(int)
                st.dataframe(
                    vend.sort_values([f'Aged >{AGED_DAYS}d', 'Orders'],
                                     ascending=[False, False]),
                    use_container_width=True, hide_index=True
                )

            # ── DATA HEALTH ──────────────────────────────────
            with st.expander("🩺 Data health — why some columns are blank"):
                miss_po_date = int(df_view['po_no'].ne('').sum()) if 'po_no' in df_view else 0
                checks = pd.DataFrame([
                    {"Field": "po_date",
                     "Populated": "0 rows",
                     "Impact": "PO→Receipt and Enq→PO cannot be measured."},
                    {"Field": "expected_delivery",
                     "Populated": "0 rows",
                     "Impact": "Nothing can be flagged late against a promise. "
                               "Ageing since indent is used instead."},
                    {"Field": "enquiry_sent_at",
                     "Populated": f"{int(df_view['enquiry_date'].notna().sum())} of {len(df_view)}",
                     "Impact": "Drives Indent→Enquiry."},
                    {"Field": "received_date / GRN",
                     "Populated": f"{int(df_view['receipt_date'].notna().sum())} of {len(df_view)}",
                     "Impact": "Drives Indent→Receipt and vendor stats."},
                ])
                st.dataframe(checks, use_container_width=True, hide_index=True)
                st.caption(
                    f"{miss_po_date} row(s) in this view carry a PO number but no "
                    "PO date. The Confirm Order form writes both — so orders are "
                    "being marked Ordered somewhere other than that form."
                )

# ============================================================
# TAB 4: MASTER SETUP
# ============================================================
with main_tabs[4]:
    st.subheader("⚙️ System Configuration & Master Data")

    col_grp, col_vend_form, col_vend_list = st.columns([1.6, 1.5, 2])

    # ── MATERIAL GROUPS ──────────────────────────────────────
    with col_grp:
        st.markdown("#### 📦 Material Groups")

        MG_CATEGORIES = ["Consumables", "Raw Materials", "Hardware",
                         "Tools", "Electrical", "General"]

        # Which row (if any) is armed for edit / delete.
        st.session_state.setdefault("mg_edit_id", None)
        st.session_state.setdefault("mg_del_id", None)

        mg_rows = get_material_master_rows()
        mg_editing = next(
            (g for g in mg_rows if g.get("id") == st.session_state.mg_edit_id),
            None
        )

        def mg_refresh():
            """Both loaders read material_master — clear just those two, not
            the whole app cache, so vendor and job lists aren't needlessly
            re-fetched on every group save."""
            get_material_master_rows.clear()
            get_material_groups.clear()

        def mg_name_taken(name, ignore_id=None):
            """Case-insensitive duplicate check. ignore_id lets a row skip
            comparing against itself while being edited."""
            t = (name or "").strip().upper()
            return any(
                (g.get("material_group") or "").strip().upper() == t
                and (ignore_id is None or g.get("id") != ignore_id)
                for g in mg_rows
            )

        def mg_usage(name):
            """How many purchase_orders rows carry this group name.
            material_group is stored on purchase_orders as free text with no
            foreign key, so nothing in the database protects us here — we
            have to look before renaming or deleting."""
            try:
                res = conn.table("purchase_orders").select("id") \
                    .eq("material_group", name).execute()
                return len(res.data or [])
            except Exception:
                return 0

        # ADD mode (no row being edited)
        if mg_editing is None:
            with st.form("m_grp_form", clear_on_submit=True):
                new_g = st.text_input("New Group Name")
                new_c = st.selectbox("Category", MG_CATEGORIES)
                if st.form_submit_button("➕ Save Group"):
                    clean = (new_g or "").strip().upper()
                    if not clean:
                        st.warning("Enter a group name.")
                    elif mg_name_taken(clean):
                        st.warning(f"'{clean}' already exists.")
                    else:
                        ok = safe_db_write(
                            lambda: conn.table("material_master").insert({
                                "material_group": clean,
                                "category":       new_c
                            }).execute(),
                            success_msg=f"Group '{clean}' added!",
                            error_prefix="Group Error"
                        )
                        if ok:
                            mg_refresh()
                            st.rerun()

        # EDIT mode
        else:
            mg_old  = mg_editing.get("material_group", "")
            mg_used = mg_usage(mg_old)
            with st.form("m_grp_edit_form"):
                st.info(f"✏️ Editing: **{mg_old}**")
                ed_name = st.text_input("Group Name", value=mg_old)
                cur_c   = mg_editing.get("category")
                ed_cat  = st.selectbox(
                    "Category", MG_CATEGORIES,
                    index=MG_CATEGORIES.index(cur_c) if cur_c in MG_CATEGORIES else 0
                )
                if mg_used:
                    st.caption(
                        f"⚠️ {mg_used} indent item(s) use this name. "
                        "Renaming relabels all of them."
                    )
                e1, e2 = st.columns(2)
                mg_save   = e1.form_submit_button("✅ Update", use_container_width=True)
                mg_cancel = e2.form_submit_button("✖ Cancel", use_container_width=True)

                if mg_cancel:
                    st.session_state.mg_edit_id = None
                    st.rerun()

                if mg_save:
                    clean = (ed_name or "").strip().upper()
                    if not clean:
                        st.warning("Enter a group name.")
                    elif mg_name_taken(clean, ignore_id=mg_editing.get("id")):
                        st.warning(f"'{clean}' already exists.")
                    else:
                        ok = safe_db_write(
                            lambda: conn.table("material_master").update({
                                "material_group": clean,
                                "category":       ed_cat
                            }).eq("id", mg_editing["id"]).execute(),
                            error_prefix="Group update error"
                        )
                        # Cascade the rename by hand. There is no foreign key
                        # from purchase_orders.material_group back to this
                        # table, so without this step old indents keep the old
                        # label and drop out of the Purchase Console filter.
                        if ok and clean != mg_old.strip().upper():
                            safe_db_write(
                                lambda: conn.table("purchase_orders").update(
                                    {"material_group": clean}
                                ).eq("material_group", mg_old).execute(),
                                error_prefix="Relabel error"
                            )
                        if ok:
                            mg_refresh()
                            st.session_state.mg_edit_id = None
                            st.success(f"Updated to '{clean}'")
                            st.rerun()

        # LIST with per-row edit / delete
        if not mg_rows:
            st.info("No material groups yet.")
        else:
            st.caption(f"{len(mg_rows)} group(s)")
            for g in mg_rows:
                gid   = g.get("id")
                gname = g.get("material_group") or "(blank)"
                gr1, gr2, gr3 = st.columns([3, 0.8, 0.8])
                gr1.write(f"**{gname}**")
                gr1.caption(g.get("category") or "—")

                if gr2.button("✏️", key=f"mg_e_{gid}", help="Edit"):
                    st.session_state.mg_edit_id = gid
                    st.session_state.mg_del_id  = None
                    st.rerun()

                if gr3.button("🗑️", key=f"mg_d_{gid}", help="Delete"):
                    st.session_state.mg_del_id = gid
                    st.rerun()

                # Two-step delete, blocked outright if indents depend on it.
                if st.session_state.mg_del_id == gid:
                    used = mg_usage(g.get("material_group") or "")
                    with st.container(border=True):
                        if used:
                            st.error(
                                f"Can't delete — {used} indent item(s) still "
                                f"use '{gname}'. Rename it instead, or move "
                                "those items to another group first."
                            )
                            if st.button("OK", key=f"mg_dx_{gid}"):
                                st.session_state.mg_del_id = None
                                st.rerun()
                        else:
                            st.warning(f"Delete '{gname}'? Not used by any indent.")
                            dc1, dc2 = st.columns(2)
                            if dc1.button("Yes, delete", key=f"mg_dy_{gid}",
                                          type="primary"):
                                ok = safe_db_write(
                                    lambda: conn.table("material_master")
                                        .delete().eq("id", gid).execute(),
                                    success_msg="Deleted.",
                                    error_prefix="Delete Error"
                                )
                                if ok:
                                    mg_refresh()
                                    st.session_state.mg_del_id = None
                                    st.rerun()
                            if dc2.button("Cancel", key=f"mg_dn_{gid}"):
                                st.session_state.mg_del_id = None
                                st.rerun()

    # ── ADD VENDOR ───────────────────────────────────────────
    with col_vend_form:
        st.markdown("#### 🤝 Add New Vendor")
        with st.form("vendor_entry_form", clear_on_submit=True):
            v_name  = st.text_input("Vendor Company Name*")
            v_cat   = st.selectbox(
                "Category",
                ["Steel", "Hardware", "Electrical", "Consumables", "Services", "General"]
            )
            v_phone = st.text_input(
                "WhatsApp (91xxxxxxxxxx)", help="Include country code 91, no spaces."
            )
            v_email = st.text_input("Official Email")
            if st.form_submit_button("💾 Save Vendor Details"):
                if v_name:
                    safe_db_write(
                        lambda: conn.table("master_vendors").insert({
                            "name":         v_name.strip().upper(),
                            "category":     v_cat,
                            "phone_number": clean_phone(v_phone),
                            "email":        v_email.strip().lower()
                        }).execute(),
                        success_msg=f"Vendor {v_name.upper()} added!",
                        error_prefix="Vendor Save Error"
                    )
                    get_vendors.clear()
                    st.rerun()
                else:
                    st.warning("Company Name is required.")

    # ── VENDOR DIRECTORY ─────────────────────────────────────
    with col_vend_list:
        st.markdown("#### 🔍 Vendor Directory")
        v_search    = st.text_input("Search Vendors...", placeholder="Name or category")
        vendors_all = get_vendors()
        if vendors_all:
            df_v = pd.DataFrame(vendors_all)
            if v_search:
                mask = (
                    df_v['name'].str.contains(v_search, case=False, na=False) |
                    df_v['category'].str.contains(v_search, case=False, na=False)
                )
                df_v = df_v[mask]

            if not df_v.empty:
                display_cols = [c for c in ['name', 'category', 'phone_number', 'email']
                                if c in df_v.columns]
                st.dataframe(df_v[display_cols], use_container_width=True, hide_index=True)

                st.markdown("**Delete a vendor:**")
                del_name = st.selectbox(
                    "Select vendor to remove",
                    ["-- Select --"] + df_v['name'].tolist(),
                    key="del_vendor_sel"
                )
                if del_name != "-- Select --":
                    del_row = df_v[df_v['name'] == del_name].iloc[0]
                    if st.button(f"🗑️ Delete {del_name}", type="secondary",
                                 key="confirm_del_vendor"):
                        ok = safe_db_write(
                            lambda: conn.table("master_vendors")
                                .delete().eq("id", int(del_row['id'])).execute(),
                            success_msg=f"{del_name} removed.",
                            error_prefix="Delete Error"
                        )
                        if ok:
                            get_vendors.clear()
                            st.rerun()
            else:
                st.info("No vendors match your search.")
        else:
            st.info("No vendors registered yet.")
