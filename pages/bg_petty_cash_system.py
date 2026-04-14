import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz

# ============================================================
# 1. SETUP & CONFIG
# ============================================================
IST = pytz.timezone('Asia/Kolkata')
ADMIN_PASSWORD = "admin_bg_finance"   # FIX [Critical]: Move to st.secrets in production
                                       #   st.secrets.get("admin_password", "admin_bg_finance")

st.set_page_config(
    page_title="B&G Finance | Petty Cash",
    layout="wide",
    page_icon="💰"
)
conn = st.connection("supabase", type=SupabaseConnection)

# ============================================================
# 2. LOGIN GATEWAY
# FIX [Warning]: Extracted password into a constant (easy to move to secrets).
# FIX [Warning]: Added a rerun-safe guard so repeated wrong attempts don't
#                re-render the full UI before st.stop() fires.
# ============================================================
PORTAL_PASSWORD = "pcash_bgengg"   # Move to st.secrets.get("portal_password", ...)

def check_password():
    if st.session_state.get("password_correct"):
        return True

    st.title("🔐 B&G Engineering | Petty Cash Login")
    pwd = st.text_input("Enter Portal Password", type="password", key="password_input")
    if st.button("Login", use_container_width=True):
        if pwd == PORTAL_PASSWORD:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("😕 Password incorrect.")
    return False

if not check_password():
    st.stop()

# ============================================================
# 3. UTILITIES
# ============================================================
def get_now_ist():
    return datetime.now(IST)

def safe_db_write(fn, success_msg=None, error_prefix="DB Error"):
    """
    Centralised error handler for all DB writes.
    ENHANCEMENT: Returns the result object so callers can read inserted IDs etc.
    """
    try:
        result = fn()
        if success_msg:
            st.success(success_msg)
        return result
    except Exception as e:
        st.error(f"{error_prefix}: {e}")
        return None

# ============================================================
# 4. CACHED DATA LOADERS
# FIX [Critical]: get_cash_metrics() was completely uncached — it fired TWO
#                 full table scans on every single widget interaction.
# FIX [Warning]:  get_all_expense_heads() and get_staff_list() were uncached —
#                 called multiple times per render (once in Tab 1, once in Tab 4).
# ============================================================

@st.cache_data(ttl=30)
def get_all_expense_heads():
    try:
        res = conn.table("petty_cash_heads").select("head_name").order("head_name").execute()
        return [row['head_name'] for row in res.data] if res.data else ["GENERAL/INTERNAL"]
    except Exception:
        return ["GENERAL/INTERNAL"]

@st.cache_data(ttl=60)
def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return [s['name'] for s in res.data] if res.data else ["Staff Member"]
    except Exception:
        return ["Staff Member"]

@st.cache_data(ttl=30)
def get_cash_metrics():
    """
    FIX [Critical]: Was uncached — 2 full-table scans on every rerun.
    Now cached with 30s TTL so metrics refresh quickly but don't hammer the DB.
    ENHANCEMENT: Returns pending count as well (used in dashboard badge).
    """
    try:
        res_in  = conn.table("petty_cash_topups").select("amount").execute()
        res_out = conn.table("petty_cash").select("amount").eq("status", "Authorized").execute()
        res_pend = conn.table("petty_cash").select("id").eq("status", "Pending").execute()
        total_in  = sum(float(i['amount']) for i in res_in.data)  if res_in.data  else 0.0
        total_out = sum(float(i['amount']) for i in res_out.data) if res_out.data else 0.0
        pending_count = len(res_pend.data) if res_pend.data else 0
        return total_in, total_out, (total_in - total_out), pending_count
    except Exception:
        return 0.0, 0.0, 0.0, 0

@st.cache_data(ttl=60)
def get_chart_data():
    """
    FIX [Critical]: Dashboard was calling conn.table("petty_cash").select("*")
    uncached in the tab body — refired on every widget touch anywhere on the page.
    """
    try:
        res = conn.table("petty_cash").select(
            "vch_date, amount, head_account, status"
        ).eq("status", "Authorized").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=20)
def get_pending_vouchers():
    """
    FIX [Warning]: Admin auth section called this inline without caching —
    hit the DB on every keystroke in the password box.
    Now separated and cached.
    """
    try:
        res = conn.table("petty_cash").select("*").eq("status", "Pending").order("id").execute()
        return res.data if res.data else []
    except Exception:
        return []

@st.cache_data(ttl=30)
def get_recent_vouchers(limit=10):
    """
    FIX [Warning]: Tab 1 'Recent Submissions' fetched inline on every render.
    """
    try:
        res = conn.table("petty_cash").select("*").order("created_at", desc=True).limit(limit).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_full_history():
    """
    FIX [Critical]: Tab 4 fetched the ENTIRE petty_cash table on every filter
    interaction (every selectbox change triggered a full re-fetch).
    Now fetched once and filtered in-memory — dramatically reduces DB load.
    ENHANCEMENT: Fetches all columns needed for the enriched history view.
    """
    try:
        res = conn.table("petty_cash").select("*").order("vch_date", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_topup_history():
    """ENHANCEMENT: Cached topup history for the receipts ledger."""
    try:
        res = conn.table("petty_cash_topups").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def invalidate_finance_cache():
    """
    FIX [Critical]: Original code used st.cache_data.clear() — this nukes ALL
    cached data across ALL functions and ALL users simultaneously.
    This targeted helper only clears the functions whose data actually changed.
    Call after any write that affects cash totals or voucher lists.
    """
    get_cash_metrics.clear()
    get_chart_data.clear()
    get_pending_vouchers.clear()
    get_recent_vouchers.clear()
    get_full_history.clear()

def invalidate_heads_cache():
    get_all_expense_heads.clear()

def invalidate_topup_cache():
    get_cash_metrics.clear()
    get_topup_history.clear()

# ============================================================
# 5. NAVIGATION
# ============================================================
st.sidebar.title("💰 B&G Finance Hub")
st.sidebar.caption("Petty Cash Management System")
st.sidebar.divider()

# ENHANCEMENT: Show live balance in sidebar so it's always visible
try:
    _, _, live_bal, pend_ct = get_cash_metrics()
    st.sidebar.metric("Live Balance", f"₹{live_bal:,.2f}")
    if pend_ct > 0:
        st.sidebar.warning(f"⏳ {pend_ct} voucher(s) pending approval")
except Exception:
    pass

if st.sidebar.button("🔓 Logout Portal", use_container_width=True):
    del st.session_state["password_correct"]
    st.rerun()

tabs = st.tabs([
    "📊 Dashboard",
    "📝 Raise Voucher",
    "📥 Add Cash",
    "⚙️ Manage Headers",
    "📜 History",
    "📑 Receipts Ledger",   # ENHANCEMENT: New tab — full topups history
])

# ============================================================
# TAB 0: DASHBOARD
# ============================================================
with tabs[0]:
    st.title("📊 Petty Cash Control Center")

    # --- Metrics Row ---
    total_in, total_out, balance, pending_count = get_cash_metrics()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Receipts (In)",  f"₹{total_in:,.2f}")
    m2.metric("Total Issues (Out)",   f"₹{total_out:,.2f}", delta_color="inverse")
    m3.metric("Live Balance",         f"₹{balance:,.2f}",
              delta="Healthy" if balance > 5000 else "Low — top up soon",
              delta_color="normal" if balance > 5000 else "inverse")
    m4.metric("Pending Approvals",    pending_count,
              delta_color="off" if pending_count == 0 else "inverse")

    # ENHANCEMENT: Low balance warning banner
    if balance < 2000:
        st.error(f"🚨 **Critical: Cash balance is ₹{balance:,.2f}. Immediate top-up required.**")
    elif balance < 5000:
        st.warning(f"⚠️ Cash balance is running low (₹{balance:,.2f}). Consider topping up.")

    st.divider()

    # --- Charts ---
    df_charts = get_chart_data()
    if not df_charts.empty:
        df_charts['vch_date'] = pd.to_datetime(df_charts['vch_date'])
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.subheader("📈 Spending Trend")
            st.line_chart(df_charts.groupby('vch_date')['amount'].sum())
        with chart_col2:
            st.subheader("🏗️ Head-wise Breakdown")
            st.bar_chart(df_charts.groupby('head_account')['amount'].sum())

        # ENHANCEMENT: Top 5 spending heads summary table
        st.subheader("🔝 Top Expense Heads")
        top_heads = (
            df_charts.groupby('head_account')['amount']
            .sum()
            .sort_values(ascending=False)
            .head(5)
            .reset_index()
        )
        top_heads.columns = ['Head Account', 'Total Spent (₹)']
        top_heads['Total Spent (₹)'] = top_heads['Total Spent (₹)'].map(lambda x: f"₹{x:,.2f}")
        st.dataframe(top_heads, use_container_width=True, hide_index=True)
    else:
        st.info("No authorized voucher data to chart yet.")

    st.divider()

    # --- Admin Authorization Panel ---
    st.subheader("🔐 Admin Authorization")

    # FIX [Warning]: Admin password box was checking inline — fired DB query
    # (get_pending_vouchers equivalent) on every keystroke.
    # Now uses session state so the panel stays open without re-querying on each keypress.
    if not st.session_state.get("admin_unlocked"):
        admin_auth = st.text_input(
            "Enter Admin Password to view pending vouchers",
            type="password", key="admin_auth_pwd"
        )
        if st.button("Unlock Admin Panel", use_container_width=True):
            # FIX [Critical]: Hard-coded string comparison — use st.secrets in production
            if admin_auth == st.secrets.get("admin_password", ADMIN_PASSWORD):
                st.session_state["admin_unlocked"] = True
                st.rerun()
            else:
                st.error("Invalid admin password.")
    else:
        if st.button("🔒 Lock Admin Panel"):
            st.session_state["admin_unlocked"] = False
            st.rerun()

        pending = get_pending_vouchers()
        if pending:
            st.markdown(f"**{len(pending)} voucher(s) awaiting authorization:**")
            for v in pending:
                with st.container(border=True):
                    col1, col2, col3 = st.columns([1.5, 3, 1.2])
                    col1.write(f"**Vch No: {v.get('physical_vch_no', '—')}**")
                    col1.write(f"📅 {v.get('vch_date', '—')}")
                    col1.markdown(f"### ₹{float(v.get('amount', 0)):,.2f}")
                    col2.markdown(
                        f"**Head:** {v.get('head_account', '—')}  \n"
                        f"**Receiver:** {v.get('received_by', '—')}  \n"
                        f"**Requested by:** {v.get('requested_by', '—')}"
                    )
                    col2.write(f"**Narration:** {v.get('purpose', '—')}")

                    # FIX [Critical]: Admin note must be outside the button callbacks
                    # so it's readable at button-click time. Using a unique session key.
                    note_key = f"note_{v['id']}"
                    adm_note = col2.text_input(
                        "Admin Remarks (required for rejection)",
                        key=note_key
                    )

                    # FIX [Critical]: Lambda closure bug — capture v['id'] into a
                    # local variable BEFORE the lambda, otherwise all lambdas in
                    # the loop close over the same `v` (the last iteration's value).
                    vid = v['id']

                    btn_auth, btn_rej = col3.columns(2)
                    if btn_auth.button("✅ Authorize", key=f"auth_{vid}", use_container_width=True):
                        safe_db_write(
                            lambda _id=vid, _note=st.session_state.get(note_key, ""): (
                                conn.table("petty_cash").update({
                                    "status": "Authorized",
                                    "authorized_at": get_now_ist().isoformat(),
                                    "reject_reason": _note or None
                                }).eq("id", _id).execute()
                            ),
                            success_msg="✅ Voucher authorized.",
                            error_prefix="Authorization Error"
                        )
                        invalidate_finance_cache()
                        st.rerun()

                    if btn_rej.button("❌ Reject", key=f"rej_{vid}", use_container_width=True):
                        note_val = st.session_state.get(note_key, "")
                        if not note_val:
                            col2.error("⚠️ Remarks are required to reject a voucher.")
                        else:
                            safe_db_write(
                                lambda _id=vid, _note=note_val: (
                                    conn.table("petty_cash").update({
                                        "status": "Rejected",
                                        "reject_reason": _note
                                    }).eq("id", _id).execute()
                                ),
                                success_msg="Voucher rejected.",
                                error_prefix="Rejection Error"
                            )
                            invalidate_finance_cache()
                            st.rerun()
        else:
            st.success("✅ No pending vouchers. All clear!")

# ============================================================
# TAB 1: RAISE VOUCHER
# ============================================================
with tabs[1]:
    st.title("📝 Raise New Expense Voucher")

    all_heads = get_all_expense_heads()
    staff     = get_staff_list()

    with st.form("voucher_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        v_phys_no = c1.text_input("Physical Voucher No.")
        v_date    = c2.date_input("Voucher Date", value=date.today())
        v_amount  = c3.number_input("Amount (₹)", min_value=1.0, step=10.0)

        c4, c5 = st.columns(2)
        v_head   = c4.selectbox("Towards Head Account", all_heads)
        v_recom  = c5.selectbox("Recommended By", staff)

        v_particulars = st.text_input("Particulars (Received By / Vendor Name)")
        v_narration   = st.text_area("Narration (Description of expense)")

        submitted = st.form_submit_button("🚀 Submit Voucher", use_container_width=True)
        if submitted:
            errors = []
            if not v_phys_no.strip():
                errors.append("Physical Voucher No. is required.")
            if not v_particulars.strip():
                errors.append("Particulars / Receiver field is required.")
            if not v_narration.strip():
                errors.append("Narration is required.")
            # ENHANCEMENT: Duplicate voucher number guard
            if v_phys_no.strip():
                try:
                    dup = conn.table("petty_cash").select("id") \
                        .eq("physical_vch_no", v_phys_no.strip()).execute()
                    if dup.data:
                        errors.append(f"Voucher No. '{v_phys_no}' already exists in the system.")
                except Exception:
                    pass

            if errors:
                for e in errors:
                    st.error(e)
            else:
                # Capture ALL form values before lambda (clear_on_submit clears widgets first)
                _vno  = v_phys_no.strip()
                _vdt  = str(v_date)
                _vamt = float(v_amount)
                _vhd  = v_head
                _vrec = v_particulars.strip()
                _vreq = v_recom
                _vpur = v_narration.strip()
                result = safe_db_write(
                    lambda: conn.table("petty_cash").insert({
                        "physical_vch_no": _vno,
                        "vch_date":        _vdt,
                        "amount":          _vamt,
                        "head_account":    _vhd,
                        "received_by":     _vrec,
                        "requested_by":    _vreq,
                        "purpose":         _vpur,
                        "status":          "Pending"
                    }).execute(),
                    success_msg="✅ Voucher submitted! Awaiting admin authorization.",
                    error_prefix="Voucher Submit Error"
                )
                if result:
                    invalidate_finance_cache()
                    st.rerun()

    st.divider()
    st.subheader("🔔 Recent Submissions")

    df_s = get_recent_vouchers(limit=10)
    if not df_s.empty:
        # FIX [Warning]: Was calling a raw query here inline — now uses cached loader.
        pend_ct  = len(df_s[df_s['status'] == 'Pending'])
        auth_ct  = len(df_s[df_s['status'] == 'Authorized'])
        rej_ct   = len(df_s[df_s['status'] == 'Rejected'])

        sm1, sm2, sm3 = st.columns(3)
        sm1.metric("Pending",    pend_ct)
        sm2.metric("Authorized", auth_ct)
        sm3.metric("Rejected",   rej_ct)

        display_cols = ['vch_date', 'physical_vch_no', 'head_account', 'amount', 'received_by', 'status', 'reject_reason']
        available    = [c for c in display_cols if c in df_s.columns]
        st.dataframe(
            df_s[available],
            column_config={"reject_reason": "Admin Remarks", "physical_vch_no": "Vch No."},
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No vouchers submitted yet.")

# ============================================================
# TAB 2: ADD CASH (TOP-UP)
# ============================================================
with tabs[2]:
    st.title("📥 Top-up Cash [Receipts]")
    st.caption("Record cash received into the petty cash fund.")

    with st.form("cash_in_form", clear_on_submit=True):
        t_col1, t_col2 = st.columns(2)
        t_amt  = t_col1.number_input("Amount Received (₹)", min_value=100.0, step=100.0)
        t_date = t_col2.date_input("Receipt Date", value=date.today())
        t_src  = st.text_input("Source (e.g. Director, Bank withdrawal, Reimbursement)")
        # ENHANCEMENT: Optional reference number for the receipt
        t_ref  = st.text_input("Reference No. (optional)", placeholder="Cheque/NEFT/Cash memo number")

        if st.form_submit_button("💰 Log Receipt", use_container_width=True):
            if t_src.strip():
                # FIX [Critical]: Capture all form values into local variables BEFORE
                # the lambda. With clear_on_submit=True, Streamlit resets widget state
                # before the lambda executes inside safe_db_write, so t_src.strip()
                # and t_ref.strip() would read "" (the cleared value), inserting a
                # blank source and no reference. This is why the amount appeared not
                # to save — the row WAS written but with empty source, causing
                # silent failures or filtered-out rows in the display query.
                _amt  = float(t_amt)
                _src  = t_src.strip()
                _date = str(t_date)
                _ref  = t_ref.strip() or None
                _now  = get_now_ist().isoformat()

                # Build payload — only include new columns if they exist in your schema.
                # The original petty_cash_topups table had: amount, source, created_at
                # If you have NOT yet added receipt_date / reference_no columns to
                # Supabase, the insert will throw a 400. The try/except below handles
                # this gracefully and falls back to the original minimal schema.
                try:
                    res = conn.table("petty_cash_topups").insert({
                        "amount":       _amt,
                        "source":       _src,
                        "receipt_date": _date,
                        "reference_no": _ref,
                        "logged_at":    _now,
                    }).execute()
                    insert_ok = bool(res.data)
                except Exception:
                    # Fallback: original minimal schema (amount + source only)
                    try:
                        res = conn.table("petty_cash_topups").insert({
                            "amount": _amt,
                            "source": _src,
                        }).execute()
                        insert_ok = bool(res.data)
                    except Exception as e2:
                        st.error(f"Top-up Error: {e2}")
                        insert_ok = False

                if insert_ok:
                    st.success("💰 Cash receipt logged. Balance updated.")
                    invalidate_topup_cache()
                    st.rerun()
            else:
                st.error("Please specify the source of funds.")

    # Show last 5 topups inline for quick reference
    st.divider()
    rc1, rc2 = st.columns([3, 1])
    rc1.subheader("Recent Receipts")
    if rc2.button("🔄 Refresh", key="refresh_topups", use_container_width=True):
        get_topup_history.clear()
        get_cash_metrics.clear()
        st.rerun()

    # Always fetch fresh from DB here — bypass cache so new entries are immediately visible
    try:
        _fresh = conn.table("petty_cash_topups").select("*").order("created_at", desc=True).execute()
        df_topups = pd.DataFrame(_fresh.data) if _fresh.data else pd.DataFrame()
    except Exception as _e:
        st.error(f"Could not load receipts: {_e}")
        df_topups = pd.DataFrame()

    if not df_topups.empty:
        # Show whichever columns actually exist in the table
        preferred = ['receipt_date', 'created_at', 'amount', 'source', 'reference_no', 'logged_at']
        display_cols = [c for c in preferred if c in df_topups.columns]
        # Prefer receipt_date over created_at if both present
        if 'receipt_date' in display_cols and 'created_at' in display_cols:
            display_cols.remove('created_at')
        st.dataframe(df_topups[display_cols].head(10), use_container_width=True, hide_index=True)
        st.caption(f"Showing latest {min(10, len(df_topups))} of {len(df_topups)} receipt(s).")
    else:
        st.info("No receipts logged yet.")

# ============================================================
# TAB 3: MANAGE EXPENSE HEADERS
# ============================================================
with tabs[3]:
    st.title("⚙️ Manage Expense Heads")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("➕ Add New Head")
        with st.form("add_head_form", clear_on_submit=True):
            new_head = st.text_input("Head Name")
            if st.form_submit_button("Add to System", use_container_width=True):
                if new_head.strip():
                    # ENHANCEMENT: Duplicate head guard
                    existing = get_all_expense_heads()
                    if new_head.upper() in [h.upper() for h in existing]:
                        st.error(f"'{new_head.upper()}' already exists.")
                    else:
                        _head_name = new_head.strip().upper()
                        safe_db_write(
                            lambda _h=_head_name: conn.table("petty_cash_heads").insert({
                                "head_name": _h
                            }).execute(),
                            success_msg=f"✅ '{_head_name}' added.",
                            error_prefix="Head Add Error"
                        )
                        invalidate_heads_cache()
                        st.rerun()
                else:
                    st.error("Head name cannot be empty.")

    with col2:
        st.subheader("🗑️ Remove Header")
        current_heads = get_all_expense_heads()
        head_to_delete = st.selectbox("Select Head to Remove", current_heads, key="del_head_sel")
        # FIX [Warning]: Delete button had no confirmation — one mis-click deleted a head.
        # Added a confirmation checkbox before the destructive action.
        confirm_del = st.checkbox(f"I confirm I want to delete **{head_to_delete}**", key="del_confirm")
        if st.button("🗑️ Delete Selected Header", type="primary", disabled=not confirm_del):
            try:
                usage_check = conn.table("petty_cash").select("id") \
                    .eq("head_account", head_to_delete).limit(1).execute()
                if usage_check.data:
                    st.error(
                        f"Cannot delete '{head_to_delete}' — it is referenced by existing vouchers. "
                        "Deactivate it instead or reassign those vouchers first."
                    )
                else:
                    safe_db_write(
                        lambda: conn.table("petty_cash_heads").delete()
                            .eq("head_name", head_to_delete).execute(),
                        success_msg=f"✅ '{head_to_delete}' removed.",
                        error_prefix="Head Delete Error"
                    )
                    invalidate_heads_cache()
                    st.rerun()
            except Exception as e:
                st.error(f"Usage check failed: {e}")

    # ENHANCEMENT: Show current heads as a clean list
    st.divider()
    st.subheader("📋 Current Expense Heads")
    heads = get_all_expense_heads()
    head_grid = st.columns(3)
    for i, h in enumerate(heads):
        head_grid[i % 3].markdown(f"• {h}")

# ============================================================
# TAB 4: HISTORY
# FIX [Critical]: Was fetching the full table inline on every filter change
#                 (every selectbox interaction). Now loads once (cached) and
#                 filters entirely in-memory — zero extra DB calls per filter.
# ============================================================
with tabs[4]:
    st.title("📜 Voucher Transaction History")

    with st.expander("🔍 Filters", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        filter_range  = f1.selectbox("Date Range", ["All Time", "Today", "This Week", "This Month", "Custom Range"])
        selected_head = f2.selectbox("Head Account", ["All"] + get_all_expense_heads(), key="hist_head")
        selected_stat = f3.selectbox("Status", ["All", "Authorized", "Pending", "Rejected"], key="hist_status")
        # ENHANCEMENT: Filter by requester
        selected_req  = f4.selectbox("Requested By", ["All"] + get_staff_list(), key="hist_req")

        today = date.today()
        start_d, end_d = None, None
        if filter_range == "Today":
            start_d = end_d = today
        elif filter_range == "This Week":
            start_d = today - timedelta(days=today.weekday())
            end_d   = today
        elif filter_range == "This Month":
            start_d = today.replace(day=1)
            end_d   = today
        elif filter_range == "Custom Range":
            custom_range = st.date_input(
                "Select Date Range", [today - timedelta(days=30), today], key="hist_custom"
            )
            if len(custom_range) == 2:
                start_d, end_d = custom_range

    df_h = get_full_history()

    if not df_h.empty:
        df_h['vch_date'] = pd.to_datetime(df_h['vch_date'], errors='coerce').dt.date

        # Apply all filters in-memory (no extra DB calls)
        if start_d and end_d:
            df_h = df_h[(df_h['vch_date'] >= start_d) & (df_h['vch_date'] <= end_d)]
        if selected_head != "All":
            df_h = df_h[df_h['head_account'] == selected_head]
        if selected_stat != "All":
            df_h = df_h[df_h['status'] == selected_stat]
        if selected_req != "All" and 'requested_by' in df_h.columns:
            df_h = df_h[df_h['requested_by'] == selected_req]

        # ENHANCEMENT: Filtered summary metrics
        if not df_h.empty:
            fh1, fh2, fh3 = st.columns(3)
            fh1.metric("Filtered Records", len(df_h))
            fh2.metric("Filtered Total (₹)", f"₹{df_h['amount'].sum():,.2f}")
            fh3.metric("Avg Voucher (₹)",    f"₹{df_h['amount'].mean():,.2f}")

        display_cols = [
            'vch_date', 'physical_vch_no', 'head_account', 'amount',
            'received_by', 'requested_by', 'status', 'reject_reason'
        ]
        available = [c for c in display_cols if c in df_h.columns]
        st.dataframe(
            df_h[available],
            column_config={
                "reject_reason":    "Admin Remarks",
                "physical_vch_no":  "Vch No.",
                "requested_by":     "Requested By",
                "received_by":      "Receiver / Vendor",
            },
            use_container_width=True,
            hide_index=True
        )

        # ENHANCEMENT: Download button with descriptive filename
        range_label = filter_range.lower().replace(" ", "_")
        st.download_button(
            "💾 Download Filtered CSV",
            data=df_h[available].to_csv(index=False).encode('utf-8'),
            file_name=f"bg_petty_cash_{range_label}_{today}.csv",
            mime="text/csv"
        )
    else:
        st.info("No records found for the selected filters.")

# ============================================================
# TAB 5: RECEIPTS LEDGER (NEW)
# ENHANCEMENT: Dedicated view for all cash-in (top-up) entries.
# Previously, receipts had no history view at all — you could add cash
# but never audit what had been received.
# ============================================================
with tabs[5]:
    st.title("📑 Cash Receipts Ledger")
    st.caption("Full history of all cash received into the petty cash fund.")

    # Direct DB fetch — never cached — so this tab always shows current data
    try:
        _r = conn.table("petty_cash_topups").select("*").order("created_at", desc=True).execute()
        df_topups = pd.DataFrame(_r.data) if _r.data else pd.DataFrame()
    except Exception as _e:
        st.error(f"Could not load receipts ledger: {_e}")
        df_topups = pd.DataFrame()

    if not df_topups.empty:
        # Normalise date column — handle both old schema (created_at only) and new (receipt_date)
        if 'receipt_date' in df_topups.columns:
            df_topups['receipt_date'] = pd.to_datetime(df_topups['receipt_date'], errors='coerce').dt.date
        elif 'created_at' in df_topups.columns:
            df_topups['receipt_date'] = pd.to_datetime(df_topups['created_at'], errors='coerce').dt.date

        total = float(df_topups['amount'].sum()) if 'amount' in df_topups.columns else 0.0
        rl1, rl2, rl3 = st.columns(3)
        rl1.metric("Total Cash Received", f"₹{total:,.2f}")
        rl2.metric("No. of Receipts",     len(df_topups))
        if len(df_topups) > 0:
            rl3.metric("Avg Receipt",     f"₹{total / len(df_topups):,.2f}")

        preferred_cols = ['receipt_date', 'amount', 'source', 'reference_no', 'logged_at', 'created_at']
        display_cols   = [c for c in preferred_cols if c in df_topups.columns]
        # Drop raw created_at if cleaner receipt_date exists
        if 'receipt_date' in display_cols and 'created_at' in display_cols:
            display_cols.remove('created_at')

        st.dataframe(df_topups[display_cols], use_container_width=True, hide_index=True)

        today = date.today()
        st.download_button(
            "💾 Download Receipts CSV",
            data=df_topups[display_cols].to_csv(index=False).encode('utf-8'),
            file_name=f"bg_cash_receipts_{today}.csv",
            mime="text/csv"
        )
    else:
        st.info("No cash receipts logged yet.")import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz

# ============================================================
# 1. SETUP & CONFIG
# ============================================================
IST = pytz.timezone('Asia/Kolkata')
ADMIN_PASSWORD = "admin_bg_finance"   # FIX [Critical]: Move to st.secrets in production
                                       #   st.secrets.get("admin_password", "admin_bg_finance")

st.set_page_config(
    page_title="B&G Finance | Petty Cash",
    layout="wide",
    page_icon="💰"
)
conn = st.connection("supabase", type=SupabaseConnection)

# ============================================================
# 2. LOGIN GATEWAY
# FIX [Warning]: Extracted password into a constant (easy to move to secrets).
# FIX [Warning]: Added a rerun-safe guard so repeated wrong attempts don't
#                re-render the full UI before st.stop() fires.
# ============================================================
PORTAL_PASSWORD = "pcash_bgengg"   # Move to st.secrets.get("portal_password", ...)

def check_password():
    if st.session_state.get("password_correct"):
        return True

    st.title("🔐 B&G Engineering | Petty Cash Login")
    pwd = st.text_input("Enter Portal Password", type="password", key="password_input")
    if st.button("Login", use_container_width=True):
        if pwd == PORTAL_PASSWORD:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("😕 Password incorrect.")
    return False

if not check_password():
    st.stop()

# ============================================================
# 3. UTILITIES
# ============================================================
def get_now_ist():
    return datetime.now(IST)

def safe_db_write(fn, success_msg=None, error_prefix="DB Error"):
    """
    Centralised error handler for all DB writes.
    ENHANCEMENT: Returns the result object so callers can read inserted IDs etc.
    """
    try:
        result = fn()
        if success_msg:
            st.success(success_msg)
        return result
    except Exception as e:
        st.error(f"{error_prefix}: {e}")
        return None

# ============================================================
# 4. CACHED DATA LOADERS
# FIX [Critical]: get_cash_metrics() was completely uncached — it fired TWO
#                 full table scans on every single widget interaction.
# FIX [Warning]:  get_all_expense_heads() and get_staff_list() were uncached —
#                 called multiple times per render (once in Tab 1, once in Tab 4).
# ============================================================

@st.cache_data(ttl=30)
def get_all_expense_heads():
    try:
        res = conn.table("petty_cash_heads").select("head_name").order("head_name").execute()
        return [row['head_name'] for row in res.data] if res.data else ["GENERAL/INTERNAL"]
    except Exception:
        return ["GENERAL/INTERNAL"]

@st.cache_data(ttl=60)
def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return [s['name'] for s in res.data] if res.data else ["Staff Member"]
    except Exception:
        return ["Staff Member"]

@st.cache_data(ttl=30)
def get_cash_metrics():
    """
    FIX [Critical]: Was uncached — 2 full-table scans on every rerun.
    Now cached with 30s TTL so metrics refresh quickly but don't hammer the DB.
    ENHANCEMENT: Returns pending count as well (used in dashboard badge).
    """
    try:
        res_in  = conn.table("petty_cash_topups").select("amount").execute()
        res_out = conn.table("petty_cash").select("amount").eq("status", "Authorized").execute()
        res_pend = conn.table("petty_cash").select("id").eq("status", "Pending").execute()
        total_in  = sum(float(i['amount']) for i in res_in.data)  if res_in.data  else 0.0
        total_out = sum(float(i['amount']) for i in res_out.data) if res_out.data else 0.0
        pending_count = len(res_pend.data) if res_pend.data else 0
        return total_in, total_out, (total_in - total_out), pending_count
    except Exception:
        return 0.0, 0.0, 0.0, 0

@st.cache_data(ttl=60)
def get_chart_data():
    """
    FIX [Critical]: Dashboard was calling conn.table("petty_cash").select("*")
    uncached in the tab body — refired on every widget touch anywhere on the page.
    """
    try:
        res = conn.table("petty_cash").select(
            "vch_date, amount, head_account, status"
        ).eq("status", "Authorized").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=20)
def get_pending_vouchers():
    """
    FIX [Warning]: Admin auth section called this inline without caching —
    hit the DB on every keystroke in the password box.
    Now separated and cached.
    """
    try:
        res = conn.table("petty_cash").select("*").eq("status", "Pending").order("id").execute()
        return res.data if res.data else []
    except Exception:
        return []

@st.cache_data(ttl=30)
def get_recent_vouchers(limit=10):
    """
    FIX [Warning]: Tab 1 'Recent Submissions' fetched inline on every render.
    """
    try:
        res = conn.table("petty_cash").select("*").order("created_at", desc=True).limit(limit).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_full_history():
    """
    FIX [Critical]: Tab 4 fetched the ENTIRE petty_cash table on every filter
    interaction (every selectbox change triggered a full re-fetch).
    Now fetched once and filtered in-memory — dramatically reduces DB load.
    ENHANCEMENT: Fetches all columns needed for the enriched history view.
    """
    try:
        res = conn.table("petty_cash").select("*").order("vch_date", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_topup_history():
    """ENHANCEMENT: Cached topup history for the receipts ledger."""
    try:
        res = conn.table("petty_cash_topups").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def invalidate_finance_cache():
    """
    FIX [Critical]: Original code used st.cache_data.clear() — this nukes ALL
    cached data across ALL functions and ALL users simultaneously.
    This targeted helper only clears the functions whose data actually changed.
    Call after any write that affects cash totals or voucher lists.
    """
    get_cash_metrics.clear()
    get_chart_data.clear()
    get_pending_vouchers.clear()
    get_recent_vouchers.clear()
    get_full_history.clear()

def invalidate_heads_cache():
    get_all_expense_heads.clear()

def invalidate_topup_cache():
    get_cash_metrics.clear()
    get_topup_history.clear()

# ============================================================
# 5. NAVIGATION
# ============================================================
st.sidebar.title("💰 B&G Finance Hub")
st.sidebar.caption("Petty Cash Management System")
st.sidebar.divider()

# ENHANCEMENT: Show live balance in sidebar so it's always visible
try:
    _, _, live_bal, pend_ct = get_cash_metrics()
    st.sidebar.metric("Live Balance", f"₹{live_bal:,.2f}")
    if pend_ct > 0:
        st.sidebar.warning(f"⏳ {pend_ct} voucher(s) pending approval")
except Exception:
    pass

if st.sidebar.button("🔓 Logout Portal", use_container_width=True):
    del st.session_state["password_correct"]
    st.rerun()

tabs = st.tabs([
    "📊 Dashboard",
    "📝 Raise Voucher",
    "📥 Add Cash",
    "⚙️ Manage Headers",
    "📜 History",
    "📑 Receipts Ledger",   # ENHANCEMENT: New tab — full topups history
])

# ============================================================
# TAB 0: DASHBOARD
# ============================================================
with tabs[0]:
    st.title("📊 Petty Cash Control Center")

    # --- Metrics Row ---
    total_in, total_out, balance, pending_count = get_cash_metrics()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Receipts (In)",  f"₹{total_in:,.2f}")
    m2.metric("Total Issues (Out)",   f"₹{total_out:,.2f}", delta_color="inverse")
    m3.metric("Live Balance",         f"₹{balance:,.2f}",
              delta="Healthy" if balance > 5000 else "Low — top up soon",
              delta_color="normal" if balance > 5000 else "inverse")
    m4.metric("Pending Approvals",    pending_count,
              delta_color="off" if pending_count == 0 else "inverse")

    # ENHANCEMENT: Low balance warning banner
    if balance < 2000:
        st.error(f"🚨 **Critical: Cash balance is ₹{balance:,.2f}. Immediate top-up required.**")
    elif balance < 5000:
        st.warning(f"⚠️ Cash balance is running low (₹{balance:,.2f}). Consider topping up.")

    st.divider()

    # --- Charts ---
    df_charts = get_chart_data()
    if not df_charts.empty:
        df_charts['vch_date'] = pd.to_datetime(df_charts['vch_date'])
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.subheader("📈 Spending Trend")
            st.line_chart(df_charts.groupby('vch_date')['amount'].sum())
        with chart_col2:
            st.subheader("🏗️ Head-wise Breakdown")
            st.bar_chart(df_charts.groupby('head_account')['amount'].sum())

        # ENHANCEMENT: Top 5 spending heads summary table
        st.subheader("🔝 Top Expense Heads")
        top_heads = (
            df_charts.groupby('head_account')['amount']
            .sum()
            .sort_values(ascending=False)
            .head(5)
            .reset_index()
        )
        top_heads.columns = ['Head Account', 'Total Spent (₹)']
        top_heads['Total Spent (₹)'] = top_heads['Total Spent (₹)'].map(lambda x: f"₹{x:,.2f}")
        st.dataframe(top_heads, use_container_width=True, hide_index=True)
    else:
        st.info("No authorized voucher data to chart yet.")

    st.divider()

    # --- Admin Authorization Panel ---
    st.subheader("🔐 Admin Authorization")

    # FIX [Warning]: Admin password box was checking inline — fired DB query
    # (get_pending_vouchers equivalent) on every keystroke.
    # Now uses session state so the panel stays open without re-querying on each keypress.
    if not st.session_state.get("admin_unlocked"):
        admin_auth = st.text_input(
            "Enter Admin Password to view pending vouchers",
            type="password", key="admin_auth_pwd"
        )
        if st.button("Unlock Admin Panel", use_container_width=True):
            # FIX [Critical]: Hard-coded string comparison — use st.secrets in production
            if admin_auth == st.secrets.get("admin_password", ADMIN_PASSWORD):
                st.session_state["admin_unlocked"] = True
                st.rerun()
            else:
                st.error("Invalid admin password.")
    else:
        if st.button("🔒 Lock Admin Panel"):
            st.session_state["admin_unlocked"] = False
            st.rerun()

        pending = get_pending_vouchers()
        if pending:
            st.markdown(f"**{len(pending)} voucher(s) awaiting authorization:**")
            for v in pending:
                with st.container(border=True):
                    col1, col2, col3 = st.columns([1.5, 3, 1.2])
                    col1.write(f"**Vch No: {v.get('physical_vch_no', '—')}**")
                    col1.write(f"📅 {v.get('vch_date', '—')}")
                    col1.markdown(f"### ₹{float(v.get('amount', 0)):,.2f}")
                    col2.markdown(
                        f"**Head:** {v.get('head_account', '—')}  \n"
                        f"**Receiver:** {v.get('received_by', '—')}  \n"
                        f"**Requested by:** {v.get('requested_by', '—')}"
                    )
                    col2.write(f"**Narration:** {v.get('purpose', '—')}")

                    # FIX [Critical]: Admin note must be outside the button callbacks
                    # so it's readable at button-click time. Using a unique session key.
                    note_key = f"note_{v['id']}"
                    adm_note = col2.text_input(
                        "Admin Remarks (required for rejection)",
                        key=note_key
                    )

                    # FIX [Critical]: Lambda closure bug — capture v['id'] into a
                    # local variable BEFORE the lambda, otherwise all lambdas in
                    # the loop close over the same `v` (the last iteration's value).
                    vid = v['id']

                    btn_auth, btn_rej = col3.columns(2)
                    if btn_auth.button("✅ Authorize", key=f"auth_{vid}", use_container_width=True):
                        safe_db_write(
                            lambda _id=vid, _note=st.session_state.get(note_key, ""): (
                                conn.table("petty_cash").update({
                                    "status": "Authorized",
                                    "authorized_at": get_now_ist().isoformat(),
                                    "reject_reason": _note or None
                                }).eq("id", _id).execute()
                            ),
                            success_msg="✅ Voucher authorized.",
                            error_prefix="Authorization Error"
                        )
                        invalidate_finance_cache()
                        st.rerun()

                    if btn_rej.button("❌ Reject", key=f"rej_{vid}", use_container_width=True):
                        note_val = st.session_state.get(note_key, "")
                        if not note_val:
                            col2.error("⚠️ Remarks are required to reject a voucher.")
                        else:
                            safe_db_write(
                                lambda _id=vid, _note=note_val: (
                                    conn.table("petty_cash").update({
                                        "status": "Rejected",
                                        "reject_reason": _note
                                    }).eq("id", _id).execute()
                                ),
                                success_msg="Voucher rejected.",
                                error_prefix="Rejection Error"
                            )
                            invalidate_finance_cache()
                            st.rerun()
        else:
            st.success("✅ No pending vouchers. All clear!")

# ============================================================
# TAB 1: RAISE VOUCHER
# ============================================================
with tabs[1]:
    st.title("📝 Raise New Expense Voucher")

    all_heads = get_all_expense_heads()
    staff     = get_staff_list()

    with st.form("voucher_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        v_phys_no = c1.text_input("Physical Voucher No.")
        v_date    = c2.date_input("Voucher Date", value=date.today())
        v_amount  = c3.number_input("Amount (₹)", min_value=1.0, step=10.0)

        c4, c5 = st.columns(2)
        v_head   = c4.selectbox("Towards Head Account", all_heads)
        v_recom  = c5.selectbox("Recommended By", staff)

        v_particulars = st.text_input("Particulars (Received By / Vendor Name)")
        v_narration   = st.text_area("Narration (Description of expense)")

        submitted = st.form_submit_button("🚀 Submit Voucher", use_container_width=True)
        if submitted:
            errors = []
            if not v_phys_no.strip():
                errors.append("Physical Voucher No. is required.")
            if not v_particulars.strip():
                errors.append("Particulars / Receiver field is required.")
            if not v_narration.strip():
                errors.append("Narration is required.")
            # ENHANCEMENT: Duplicate voucher number guard
            if v_phys_no.strip():
                try:
                    dup = conn.table("petty_cash").select("id") \
                        .eq("physical_vch_no", v_phys_no.strip()).execute()
                    if dup.data:
                        errors.append(f"Voucher No. '{v_phys_no}' already exists in the system.")
                except Exception:
                    pass

            if errors:
                for e in errors:
                    st.error(e)
            else:
                # Capture ALL form values before lambda (clear_on_submit clears widgets first)
                _vno  = v_phys_no.strip()
                _vdt  = str(v_date)
                _vamt = float(v_amount)
                _vhd  = v_head
                _vrec = v_particulars.strip()
                _vreq = v_recom
                _vpur = v_narration.strip()
                result = safe_db_write(
                    lambda: conn.table("petty_cash").insert({
                        "physical_vch_no": _vno,
                        "vch_date":        _vdt,
                        "amount":          _vamt,
                        "head_account":    _vhd,
                        "received_by":     _vrec,
                        "requested_by":    _vreq,
                        "purpose":         _vpur,
                        "status":          "Pending"
                    }).execute(),
                    success_msg="✅ Voucher submitted! Awaiting admin authorization.",
                    error_prefix="Voucher Submit Error"
                )
                if result:
                    invalidate_finance_cache()
                    st.rerun()

    st.divider()
    st.subheader("🔔 Recent Submissions")

    df_s = get_recent_vouchers(limit=10)
    if not df_s.empty:
        # FIX [Warning]: Was calling a raw query here inline — now uses cached loader.
        pend_ct  = len(df_s[df_s['status'] == 'Pending'])
        auth_ct  = len(df_s[df_s['status'] == 'Authorized'])
        rej_ct   = len(df_s[df_s['status'] == 'Rejected'])

        sm1, sm2, sm3 = st.columns(3)
        sm1.metric("Pending",    pend_ct)
        sm2.metric("Authorized", auth_ct)
        sm3.metric("Rejected",   rej_ct)

        display_cols = ['vch_date', 'physical_vch_no', 'head_account', 'amount', 'received_by', 'status', 'reject_reason']
        available    = [c for c in display_cols if c in df_s.columns]
        st.dataframe(
            df_s[available],
            column_config={"reject_reason": "Admin Remarks", "physical_vch_no": "Vch No."},
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No vouchers submitted yet.")

# ============================================================
# TAB 2: ADD CASH (TOP-UP)
# ============================================================
with tabs[2]:
    st.title("📥 Top-up Cash [Receipts]")
    st.caption("Record cash received into the petty cash fund.")

    with st.form("cash_in_form", clear_on_submit=True):
        t_col1, t_col2 = st.columns(2)
        t_amt  = t_col1.number_input("Amount Received (₹)", min_value=100.0, step=100.0)
        t_date = t_col2.date_input("Receipt Date", value=date.today())
        t_src  = st.text_input("Source (e.g. Director, Bank withdrawal, Reimbursement)")
        # ENHANCEMENT: Optional reference number for the receipt
        t_ref  = st.text_input("Reference No. (optional)", placeholder="Cheque/NEFT/Cash memo number")

        if st.form_submit_button("💰 Log Receipt", use_container_width=True):
            if t_src.strip():
                # FIX [Critical]: Capture all form values into local variables BEFORE
                # the lambda. With clear_on_submit=True, Streamlit resets widget state
                # before the lambda executes inside safe_db_write, so t_src.strip()
                # and t_ref.strip() would read "" (the cleared value), inserting a
                # blank source and no reference. This is why the amount appeared not
                # to save — the row WAS written but with empty source, causing
                # silent failures or filtered-out rows in the display query.
                _amt  = float(t_amt)
                _src  = t_src.strip()
                _date = str(t_date)
                _ref  = t_ref.strip() or None
                _now  = get_now_ist().isoformat()

                # Build payload — only include new columns if they exist in your schema.
                # The original petty_cash_topups table had: amount, source, created_at
                # If you have NOT yet added receipt_date / reference_no columns to
                # Supabase, the insert will throw a 400. The try/except below handles
                # this gracefully and falls back to the original minimal schema.
                try:
                    res = conn.table("petty_cash_topups").insert({
                        "amount":       _amt,
                        "source":       _src,
                        "receipt_date": _date,
                        "reference_no": _ref,
                        "logged_at":    _now,
                    }).execute()
                    insert_ok = bool(res.data)
                except Exception:
                    # Fallback: original minimal schema (amount + source only)
                    try:
                        res = conn.table("petty_cash_topups").insert({
                            "amount": _amt,
                            "source": _src,
                        }).execute()
                        insert_ok = bool(res.data)
                    except Exception as e2:
                        st.error(f"Top-up Error: {e2}")
                        insert_ok = False

                if insert_ok:
                    st.success("💰 Cash receipt logged. Balance updated.")
                    invalidate_topup_cache()
                    st.rerun()
            else:
                st.error("Please specify the source of funds.")

    # Show last 5 topups inline for quick reference
    st.divider()
    rc1, rc2 = st.columns([3, 1])
    rc1.subheader("Recent Receipts")
    if rc2.button("🔄 Refresh", key="refresh_topups", use_container_width=True):
        get_topup_history.clear()
        get_cash_metrics.clear()
        st.rerun()

    # Always fetch fresh from DB here — bypass cache so new entries are immediately visible
    try:
        _fresh = conn.table("petty_cash_topups").select("*").order("created_at", desc=True).execute()
        df_topups = pd.DataFrame(_fresh.data) if _fresh.data else pd.DataFrame()
    except Exception as _e:
        st.error(f"Could not load receipts: {_e}")
        df_topups = pd.DataFrame()

    if not df_topups.empty:
        # Show whichever columns actually exist in the table
        preferred = ['receipt_date', 'created_at', 'amount', 'source', 'reference_no', 'logged_at']
        display_cols = [c for c in preferred if c in df_topups.columns]
        # Prefer receipt_date over created_at if both present
        if 'receipt_date' in display_cols and 'created_at' in display_cols:
            display_cols.remove('created_at')
        st.dataframe(df_topups[display_cols].head(10), use_container_width=True, hide_index=True)
        st.caption(f"Showing latest {min(10, len(df_topups))} of {len(df_topups)} receipt(s).")
    else:
        st.info("No receipts logged yet.")

# ============================================================
# TAB 3: MANAGE EXPENSE HEADERS
# ============================================================
with tabs[3]:
    st.title("⚙️ Manage Expense Heads")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("➕ Add New Head")
        with st.form("add_head_form", clear_on_submit=True):
            new_head = st.text_input("Head Name")
            if st.form_submit_button("Add to System", use_container_width=True):
                if new_head.strip():
                    # ENHANCEMENT: Duplicate head guard
                    existing = get_all_expense_heads()
                    if new_head.upper() in [h.upper() for h in existing]:
                        st.error(f"'{new_head.upper()}' already exists.")
                    else:
                        _head_name = new_head.strip().upper()
                        safe_db_write(
                            lambda _h=_head_name: conn.table("petty_cash_heads").insert({
                                "head_name": _h
                            }).execute(),
                            success_msg=f"✅ '{_head_name}' added.",
                            error_prefix="Head Add Error"
                        )
                        invalidate_heads_cache()
                        st.rerun()
                else:
                    st.error("Head name cannot be empty.")

    with col2:
        st.subheader("🗑️ Remove Header")
        current_heads = get_all_expense_heads()
        head_to_delete = st.selectbox("Select Head to Remove", current_heads, key="del_head_sel")
        # FIX [Warning]: Delete button had no confirmation — one mis-click deleted a head.
        # Added a confirmation checkbox before the destructive action.
        confirm_del = st.checkbox(f"I confirm I want to delete **{head_to_delete}**", key="del_confirm")
        if st.button("🗑️ Delete Selected Header", type="primary", disabled=not confirm_del):
            try:
                usage_check = conn.table("petty_cash").select("id") \
                    .eq("head_account", head_to_delete).limit(1).execute()
                if usage_check.data:
                    st.error(
                        f"Cannot delete '{head_to_delete}' — it is referenced by existing vouchers. "
                        "Deactivate it instead or reassign those vouchers first."
                    )
                else:
                    safe_db_write(
                        lambda: conn.table("petty_cash_heads").delete()
                            .eq("head_name", head_to_delete).execute(),
                        success_msg=f"✅ '{head_to_delete}' removed.",
                        error_prefix="Head Delete Error"
                    )
                    invalidate_heads_cache()
                    st.rerun()
            except Exception as e:
                st.error(f"Usage check failed: {e}")

    # ENHANCEMENT: Show current heads as a clean list
    st.divider()
    st.subheader("📋 Current Expense Heads")
    heads = get_all_expense_heads()
    head_grid = st.columns(3)
    for i, h in enumerate(heads):
        head_grid[i % 3].markdown(f"• {h}")

# ============================================================
# TAB 4: HISTORY
# FIX [Critical]: Was fetching the full table inline on every filter change
#                 (every selectbox interaction). Now loads once (cached) and
#                 filters entirely in-memory — zero extra DB calls per filter.
# ============================================================
with tabs[4]:
    st.title("📜 Voucher Transaction History")

    with st.expander("🔍 Filters", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        filter_range  = f1.selectbox("Date Range", ["All Time", "Today", "This Week", "This Month", "Custom Range"])
        selected_head = f2.selectbox("Head Account", ["All"] + get_all_expense_heads(), key="hist_head")
        selected_stat = f3.selectbox("Status", ["All", "Authorized", "Pending", "Rejected"], key="hist_status")
        # ENHANCEMENT: Filter by requester
        selected_req  = f4.selectbox("Requested By", ["All"] + get_staff_list(), key="hist_req")

        today = date.today()
        start_d, end_d = None, None
        if filter_range == "Today":
            start_d = end_d = today
        elif filter_range == "This Week":
            start_d = today - timedelta(days=today.weekday())
            end_d   = today
        elif filter_range == "This Month":
            start_d = today.replace(day=1)
            end_d   = today
        elif filter_range == "Custom Range":
            custom_range = st.date_input(
                "Select Date Range", [today - timedelta(days=30), today], key="hist_custom"
            )
            if len(custom_range) == 2:
                start_d, end_d = custom_range

    df_h = get_full_history()

    if not df_h.empty:
        df_h['vch_date'] = pd.to_datetime(df_h['vch_date'], errors='coerce').dt.date

        # Apply all filters in-memory (no extra DB calls)
        if start_d and end_d:
            df_h = df_h[(df_h['vch_date'] >= start_d) & (df_h['vch_date'] <= end_d)]
        if selected_head != "All":
            df_h = df_h[df_h['head_account'] == selected_head]
        if selected_stat != "All":
            df_h = df_h[df_h['status'] == selected_stat]
        if selected_req != "All" and 'requested_by' in df_h.columns:
            df_h = df_h[df_h['requested_by'] == selected_req]

        # ENHANCEMENT: Filtered summary metrics
        if not df_h.empty:
            fh1, fh2, fh3 = st.columns(3)
            fh1.metric("Filtered Records", len(df_h))
            fh2.metric("Filtered Total (₹)", f"₹{df_h['amount'].sum():,.2f}")
            fh3.metric("Avg Voucher (₹)",    f"₹{df_h['amount'].mean():,.2f}")

        display_cols = [
            'vch_date', 'physical_vch_no', 'head_account', 'amount',
            'received_by', 'requested_by', 'status', 'reject_reason'
        ]
        available = [c for c in display_cols if c in df_h.columns]
        st.dataframe(
            df_h[available],
            column_config={
                "reject_reason":    "Admin Remarks",
                "physical_vch_no":  "Vch No.",
                "requested_by":     "Requested By",
                "received_by":      "Receiver / Vendor",
            },
            use_container_width=True,
            hide_index=True
        )

        # ENHANCEMENT: Download button with descriptive filename
        range_label = filter_range.lower().replace(" ", "_")
        st.download_button(
            "💾 Download Filtered CSV",
            data=df_h[available].to_csv(index=False).encode('utf-8'),
            file_name=f"bg_petty_cash_{range_label}_{today}.csv",
            mime="text/csv"
        )
    else:
        st.info("No records found for the selected filters.")

# ============================================================
# TAB 5: RECEIPTS LEDGER (NEW)
# ENHANCEMENT: Dedicated view for all cash-in (top-up) entries.
# Previously, receipts had no history view at all — you could add cash
# but never audit what had been received.
# ============================================================
with tabs[5]:
    st.title("📑 Cash Receipts Ledger")
    st.caption("Full history of all cash received into the petty cash fund.")

    # Direct DB fetch — never cached — so this tab always shows current data
    try:
        _r = conn.table("petty_cash_topups").select("*").order("created_at", desc=True).execute()
        df_topups = pd.DataFrame(_r.data) if _r.data else pd.DataFrame()
    except Exception as _e:
        st.error(f"Could not load receipts ledger: {_e}")
        df_topups = pd.DataFrame()

    if not df_topups.empty:
        # Normalise date column — handle both old schema (created_at only) and new (receipt_date)
        if 'receipt_date' in df_topups.columns:
            df_topups['receipt_date'] = pd.to_datetime(df_topups['receipt_date'], errors='coerce').dt.date
        elif 'created_at' in df_topups.columns:
            df_topups['receipt_date'] = pd.to_datetime(df_topups['created_at'], errors='coerce').dt.date

        total = float(df_topups['amount'].sum()) if 'amount' in df_topups.columns else 0.0
        rl1, rl2, rl3 = st.columns(3)
        rl1.metric("Total Cash Received", f"₹{total:,.2f}")
        rl2.metric("No. of Receipts",     len(df_topups))
        if len(df_topups) > 0:
            rl3.metric("Avg Receipt",     f"₹{total / len(df_topups):,.2f}")

        preferred_cols = ['receipt_date', 'amount', 'source', 'reference_no', 'logged_at', 'created_at']
        display_cols   = [c for c in preferred_cols if c in df_topups.columns]
        # Drop raw created_at if cleaner receipt_date exists
        if 'receipt_date' in display_cols and 'created_at' in display_cols:
            display_cols.remove('created_at')

        st.dataframe(df_topups[display_cols], use_container_width=True, hide_index=True)

        today = date.today()
        st.download_button(
            "💾 Download Receipts CSV",
            data=df_topups[display_cols].to_csv(index=False).encode('utf-8'),
            file_name=f"bg_cash_receipts_{today}.csv",
            mime="text/csv"
        )
    else:
        st.info("No cash receipts logged yet.")
