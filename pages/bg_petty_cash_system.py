import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz

# ============================================================
# 1. SETUP & CONFIG
# ============================================================
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Finance | Petty Cash", layout="wide", page_icon="💰")
conn = st.connection("supabase", type=SupabaseConnection)

PORTAL_PASSWORD = "pcash_bgengg"
ADMIN_PASSWORD  = "admin_bg_finance"

# ============================================================
# 2. LOGIN GATEWAY
# ============================================================
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

def db_insert(table, payload):
    """Direct insert — surfaces the real Supabase error instead of hiding it."""
    try:
        conn.table(table).insert(payload).execute()
        return True
    except Exception as e:
        st.error(f"Insert failed [{table}]: {e}")
        return False

def db_update(table, payload, col, val):
    try:
        conn.table(table).update(payload).eq(col, val).execute()
        return True
    except Exception as e:
        st.error(f"Update failed [{table}]: {e}")
        return False

def db_delete(table, col, val):
    try:
        conn.table(table).delete().eq(col, val).execute()
        return True
    except Exception as e:
        st.error(f"Delete failed [{table}]: {e}")
        return False

# ============================================================
# 4. CACHED DATA LOADERS
# ============================================================
@st.cache_data(ttl=30)
def get_all_expense_heads():
    try:
        res = conn.table("petty_cash_heads").select("head_name").order("head_name").execute()
        return [r['head_name'] for r in res.data] if res.data else ["GENERAL/INTERNAL"]
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
    try:
        res_in   = conn.table("petty_cash_topups").select("amount").execute()
        res_out  = conn.table("petty_cash").select("amount").eq("status", "Authorized").execute()
        res_pend = conn.table("petty_cash").select("id").eq("status", "Pending").execute()
        total_in  = sum(float(i['amount']) for i in res_in.data)  if res_in.data  else 0.0
        total_out = sum(float(i['amount']) for i in res_out.data) if res_out.data else 0.0
        pend_ct   = len(res_pend.data) if res_pend.data else 0
        return total_in, total_out, (total_in - total_out), pend_ct
    except Exception:
        return 0.0, 0.0, 0.0, 0

@st.cache_data(ttl=60)
def get_chart_data():
    try:
        res = conn.table("petty_cash").select(
            "vch_date, amount, head_account"
        ).eq("status", "Authorized").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=20)
def get_pending_vouchers():
    try:
        res = conn.table("petty_cash").select("*").eq("status", "Pending").order("id").execute()
        return res.data if res.data else []
    except Exception:
        return []

@st.cache_data(ttl=30)
def get_recent_vouchers(limit=10):
    try:
        res = conn.table("petty_cash").select("*").order("created_at", desc=True).limit(limit).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_full_history():
    try:
        res = conn.table("petty_cash").select("*").order("vch_date", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def fetch_topups_fresh():
    """No cache — always live. Used wherever receipts must appear immediately."""
    try:
        res = conn.table("petty_cash_topups").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception as e:
        st.error(f"Could not load receipts: {e}")
        return pd.DataFrame()

def display_topups(df, max_rows=None):
    """Render receipts table — works with both original and extended schema."""
    if df.empty:
        st.info("No receipts logged yet.")
        return
    df = df.copy()
    # Derive a clean date column regardless of schema
    if 'receipt_date' not in df.columns and 'created_at' in df.columns:
        df['receipt_date'] = (
            pd.to_datetime(df['created_at'], errors='coerce')
            .dt.tz_convert(IST)
            .dt.strftime('%d-%m-%Y %I:%M %p')
        )
    preferred = ['receipt_date', 'amount', 'source', 'reference_no', 'created_at']
    show_cols = [c for c in preferred if c in df.columns]
    if 'receipt_date' in show_cols and 'created_at' in show_cols:
        show_cols.remove('created_at')
    render_df = df[show_cols] if max_rows is None else df[show_cols].head(max_rows)
    st.dataframe(render_df, use_container_width=True, hide_index=True)

def invalidate_finance_cache():
    get_cash_metrics.clear()
    get_chart_data.clear()
    get_pending_vouchers.clear()
    get_recent_vouchers.clear()
    get_full_history.clear()

def invalidate_heads_cache():
    get_all_expense_heads.clear()

# ============================================================
# 5. SIDEBAR
# ============================================================
st.sidebar.title("💰 B&G Finance Hub")
st.sidebar.caption("Petty Cash Management System")
st.sidebar.divider()

try:
    _, _, live_bal, pend_ct = get_cash_metrics()
    st.sidebar.metric("Live Balance", f"₹{live_bal:,.2f}")
    if pend_ct > 0:
        st.sidebar.warning(f"⏳ {pend_ct} voucher(s) pending approval")
except Exception:
    pass

if st.sidebar.button("🔓 Logout", use_container_width=True):
    del st.session_state["password_correct"]
    st.rerun()

# ============================================================
# 6. TABS
# ============================================================
tabs = st.tabs([
    "📊 Dashboard",
    "📝 Raise Voucher",
    "📥 Add Cash",
    "⚙️ Manage Headers",
    "📜 History",
    "📑 Receipts Ledger",
])

# ============================================================
# TAB 0: DASHBOARD
# ============================================================
with tabs[0]:
    st.title("📊 Petty Cash Control Center")

    total_in, total_out, balance, pending_count = get_cash_metrics()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Receipts (In)",  f"₹{total_in:,.2f}")
    m2.metric("Total Issues (Out)",   f"₹{total_out:,.2f}", delta_color="inverse")
    m3.metric("Live Balance",         f"₹{balance:,.2f}",
              delta="Healthy" if balance > 5000 else "Low — top up soon",
              delta_color="normal" if balance > 5000 else "inverse")
    m4.metric("Pending Approvals",    pending_count,
              delta_color="off" if pending_count == 0 else "inverse")

    if balance < 2000:
        st.error(f"🚨 Critical: Cash balance is ₹{balance:,.2f}. Immediate top-up required.")
    elif balance < 5000:
        st.warning(f"⚠️ Cash balance running low (₹{balance:,.2f}). Consider topping up.")

    st.divider()
    df_charts = get_chart_data()
    if not df_charts.empty:
        df_charts['vch_date'] = pd.to_datetime(df_charts['vch_date'])
        ch1, ch2 = st.columns(2)
        with ch1:
            st.subheader("📈 Spending Trend")
            st.line_chart(df_charts.groupby('vch_date')['amount'].sum())
        with ch2:
            st.subheader("🏗️ Head-wise Breakdown")
            st.bar_chart(df_charts.groupby('head_account')['amount'].sum())
        st.subheader("🔝 Top Expense Heads")
        top_heads = (
            df_charts.groupby('head_account')['amount']
            .sum().sort_values(ascending=False).head(5).reset_index()
        )
        top_heads.columns = ['Head Account', 'Total Spent (₹)']
        top_heads['Total Spent (₹)'] = top_heads['Total Spent (₹)'].map(lambda x: f"₹{x:,.2f}")
        st.dataframe(top_heads, use_container_width=True, hide_index=True)
    else:
        st.info("No authorized voucher data to chart yet.")

    st.divider()
    st.subheader("🔐 Admin Authorization")

    if not st.session_state.get("admin_unlocked"):
        admin_pwd = st.text_input("Admin Password", type="password", key="admin_auth_pwd")
        if st.button("Unlock Admin Panel", use_container_width=True):
            if admin_pwd == st.secrets.get("admin_password", ADMIN_PASSWORD):
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
                vid      = v['id']
                note_key = f"note_{vid}"
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
                    col2.text_input("Admin Remarks (required for rejection)", key=note_key)
                    ba, br = col3.columns(2)
                    if ba.button("✅ Auth", key=f"auth_{vid}", use_container_width=True):
                        ok = db_update("petty_cash", {
                            "status":        "Authorized",
                            "authorized_at": get_now_ist().isoformat(),
                            "reject_reason": st.session_state.get(note_key) or None,
                        }, "id", vid)
                        if ok:
                            st.success("✅ Authorized.")
                            invalidate_finance_cache()
                            st.rerun()
                    if br.button("❌ Reject", key=f"rej_{vid}", use_container_width=True):
                        note_val = st.session_state.get(note_key, "").strip()
                        if not note_val:
                            col2.error("Remarks required to reject.")
                        else:
                            ok = db_update("petty_cash", {
                                "status":        "Rejected",
                                "reject_reason": note_val,
                            }, "id", vid)
                            if ok:
                                st.success("Rejected.")
                                invalidate_finance_cache()
                                st.rerun()
        else:
            st.success("✅ No pending vouchers. All clear!")

# ============================================================
# TAB 1: RAISE VOUCHER
# KEY FIX: clear_on_submit=False. Processing happens OUTSIDE the
# form block so all widget values are still valid when read.
# ============================================================
with tabs[1]:
    st.title("📝 Raise New Expense Voucher")

    all_heads = get_all_expense_heads()
    staff     = get_staff_list()

    with st.form("voucher_form", clear_on_submit=False):
        c1, c2, c3   = st.columns([1, 1, 2])
        v_phys_no     = c1.text_input("Physical Voucher No.", key="vf_phys_no")
        v_date        = c2.date_input("Voucher Date", value=date.today(), key="vf_date")
        v_amount      = c3.number_input("Amount (₹)", min_value=1.0, step=10.0, key="vf_amount")
        c4, c5        = st.columns(2)
        v_head        = c4.selectbox("Towards Head Account", all_heads, key="vf_head")
        v_recom       = c5.selectbox("Recommended By", staff, key="vf_recom")
        v_particulars = st.text_input("Particulars (Received By / Vendor Name)", key="vf_part")
        v_narration   = st.text_area("Narration (Description of expense)", key="vf_narr")
        sub_voucher   = st.form_submit_button("🚀 Submit Voucher", use_container_width=True)

    # Process OUTSIDE form — widget values intact here
    if sub_voucher:
        errors = []
        if not v_phys_no.strip():
            errors.append("Physical Voucher No. is required.")
        if not v_particulars.strip():
            errors.append("Particulars / Receiver field is required.")
        if not v_narration.strip():
            errors.append("Narration is required.")
        if v_phys_no.strip():
            try:
                dup = conn.table("petty_cash").select("id").eq("physical_vch_no", v_phys_no.strip()).execute()
                if dup.data:
                    errors.append(f"Voucher No. '{v_phys_no.strip()}' already exists.")
            except Exception:
                pass
        if errors:
            for err in errors:
                st.error(err)
        else:
            ok = db_insert("petty_cash", {
                "physical_vch_no": v_phys_no.strip(),
                "vch_date":        str(v_date),
                "amount":          float(v_amount),
                "head_account":    v_head,
                "received_by":     v_particulars.strip(),
                "requested_by":    v_recom,
                "purpose":         v_narration.strip(),
                "status":          "Pending",
            })
            if ok:
                st.success("✅ Voucher submitted! Awaiting admin authorization.")
                invalidate_finance_cache()
                st.rerun()

    st.divider()
    st.subheader("🔔 Recent Submissions")
    df_s = get_recent_vouchers(limit=10)
    if not df_s.empty:
        sm1, sm2, sm3 = st.columns(3)
        sm1.metric("Pending",    len(df_s[df_s['status'] == 'Pending']))
        sm2.metric("Authorized", len(df_s[df_s['status'] == 'Authorized']))
        sm3.metric("Rejected",   len(df_s[df_s['status'] == 'Rejected']))
        want = ['vch_date', 'physical_vch_no', 'head_account', 'amount', 'received_by', 'status', 'reject_reason']
        show = [c for c in want if c in df_s.columns]
        st.dataframe(df_s[show], column_config={
            "reject_reason":   "Admin Remarks",
            "physical_vch_no": "Vch No.",
        }, use_container_width=True, hide_index=True)
    else:
        st.info("No vouchers submitted yet.")

# ============================================================
# TAB 2: ADD CASH (TOP-UP)
# KEY FIX: clear_on_submit=False + process outside form.
# KEY FIX: Try extended schema first; fall back to original
#          (amount + source only) if new columns don't exist yet.
# KEY FIX: fetch_topups_fresh() — no cache, always current.
# ============================================================
with tabs[2]:
    st.title("📥 Top-up Cash [Receipts]")
    st.caption("Record cash received into the petty cash fund.")

    with st.form("cash_in_form", clear_on_submit=False):
        tc1, tc2    = st.columns(2)
        t_amt       = tc1.number_input("Amount Received (₹)", min_value=100.0, step=100.0, key="ti_amt")
        t_date      = tc2.date_input("Receipt Date", value=date.today(), key="ti_date")
        t_src       = st.text_input("Source (e.g. Director, Bank withdrawal)", key="ti_src")
        t_ref       = st.text_input("Reference No. (optional — Cheque/NEFT no.)", key="ti_ref")
        sub_topup   = st.form_submit_button("💰 Log Receipt", use_container_width=True)

    # Process OUTSIDE form — values are guaranteed intact here
    if sub_topup:
        if not t_src.strip():
            st.error("Please specify the source of funds.")
        else:
            # Try extended schema first
            ok = db_insert("petty_cash_topups", {
                "amount":       float(t_amt),
                "source":       t_src.strip(),
                "receipt_date": str(t_date),
                "reference_no": t_ref.strip() or None,
            })
            if not ok:
                # Fall back to original schema (amount + source only)
                st.warning("Retrying with base schema (receipt_date/reference_no columns may not exist yet)...")
                ok = db_insert("petty_cash_topups", {
                    "amount": float(t_amt),
                    "source": t_src.strip(),
                })
            if ok:
                st.success(f"💰 ₹{float(t_amt):,.2f} from '{t_src.strip()}' logged successfully.")
                get_cash_metrics.clear()
                st.rerun()

    st.divider()
    rc1, rc2 = st.columns([3, 1])
    rc1.subheader("Recent Receipts")
    if rc2.button("🔄 Refresh", key="refresh_topups", use_container_width=True):
        st.rerun()

    df_t = fetch_topups_fresh()
    display_topups(df_t, max_rows=10)
    if not df_t.empty:
        st.caption(f"Showing latest {min(10, len(df_t))} of {len(df_t)} receipt(s).")

# ============================================================
# TAB 3: MANAGE EXPENSE HEADERS
# ============================================================
with tabs[3]:
    st.title("⚙️ Manage Expense Heads")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("➕ Add New Head")
        with st.form("add_head_form", clear_on_submit=False):
            new_head      = st.text_input("Head Name", key="ah_name")
            sub_add_head  = st.form_submit_button("Add to System", use_container_width=True)

    # Process outside form
    if sub_add_head:
        if not new_head.strip():
            st.error("Head name cannot be empty.")
        else:
            head_val = new_head.strip().upper()
            existing = get_all_expense_heads()
            if head_val in [h.upper() for h in existing]:
                st.error(f"'{head_val}' already exists.")
            else:
                ok = db_insert("petty_cash_heads", {"head_name": head_val})
                if ok:
                    st.success(f"✅ '{head_val}' added.")
                    invalidate_heads_cache()
                    st.rerun()

    with col2:
        st.subheader("🗑️ Remove Header")
        current_heads  = get_all_expense_heads()
        head_to_delete = st.selectbox("Select Head to Remove", current_heads, key="del_head_sel")
        confirm_del    = st.checkbox(f"Confirm deletion of **{head_to_delete}**", key="del_confirm")
        if st.button("🗑️ Delete", type="primary", disabled=not confirm_del):
            try:
                usage = conn.table("petty_cash").select("id").eq("head_account", head_to_delete).limit(1).execute()
                if usage.data:
                    st.error(f"Cannot delete '{head_to_delete}' — referenced by existing vouchers.")
                else:
                    ok = db_delete("petty_cash_heads", "head_name", head_to_delete)
                    if ok:
                        st.success(f"✅ '{head_to_delete}' removed.")
                        invalidate_heads_cache()
                        st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    st.divider()
    st.subheader("📋 Current Expense Heads")
    heads = get_all_expense_heads()
    gcols = st.columns(3)
    for i, h in enumerate(heads):
        gcols[i % 3].markdown(f"• {h}")

# ============================================================
# TAB 4: HISTORY
# ============================================================
with tabs[4]:
    st.title("📜 Voucher Transaction History")

    with st.expander("🔍 Filters", expanded=True):
        f1, f2, f3, f4 = st.columns(4)
        filter_range  = f1.selectbox("Date Range", ["All Time", "Today", "This Week", "This Month", "Custom Range"])
        selected_head = f2.selectbox("Head Account", ["All"] + get_all_expense_heads(), key="hist_head")
        selected_stat = f3.selectbox("Status", ["All", "Authorized", "Pending", "Rejected"], key="hist_status")
        selected_req  = f4.selectbox("Requested By", ["All"] + get_staff_list(), key="hist_req")

        today   = date.today()
        start_d = None
        end_d   = today
        if filter_range == "Today":
            start_d = end_d = today
        elif filter_range == "This Week":
            start_d = today - timedelta(days=today.weekday())
        elif filter_range == "This Month":
            start_d = today.replace(day=1)
        elif filter_range == "Custom Range":
            cr = st.date_input("Select Range", [today - timedelta(days=30), today], key="hist_custom")
            if len(cr) == 2:
                start_d, end_d = cr

    df_h = get_full_history()
    if not df_h.empty:
        df_h['vch_date'] = pd.to_datetime(df_h['vch_date'], errors='coerce').dt.date
        if start_d:
            df_h = df_h[(df_h['vch_date'] >= start_d) & (df_h['vch_date'] <= end_d)]
        if selected_head != "All":
            df_h = df_h[df_h['head_account'] == selected_head]
        if selected_stat != "All":
            df_h = df_h[df_h['status'] == selected_stat]
        if selected_req != "All" and 'requested_by' in df_h.columns:
            df_h = df_h[df_h['requested_by'] == selected_req]

        if not df_h.empty:
            fh1, fh2, fh3 = st.columns(3)
            fh1.metric("Records",  len(df_h))
            fh2.metric("Total",    f"₹{df_h['amount'].sum():,.2f}")
            fh3.metric("Average",  f"₹{df_h['amount'].mean():,.2f}")
            want = ['vch_date', 'physical_vch_no', 'head_account', 'amount',
                    'received_by', 'requested_by', 'status', 'reject_reason']
            show = [c for c in want if c in df_h.columns]
            st.dataframe(df_h[show], column_config={
                "reject_reason":   "Admin Remarks",
                "physical_vch_no": "Vch No.",
                "requested_by":    "Requested By",
                "received_by":     "Receiver / Vendor",
            }, use_container_width=True, hide_index=True)
            range_label = filter_range.lower().replace(" ", "_")
            st.download_button("💾 Download CSV",
                data=df_h[show].to_csv(index=False).encode('utf-8'),
                file_name=f"bg_petty_cash_{range_label}_{today}.csv",
                mime="text/csv")
        else:
            st.info("No records match the selected filters.")
    else:
        st.info("No voucher records found.")

# ============================================================
# TAB 5: RECEIPTS LEDGER
# ============================================================
with tabs[5]:
    st.title("📑 Cash Receipts Ledger")
    st.caption("Full history of all cash received into the petty cash fund.")

    if st.button("🔄 Refresh Ledger", key="refresh_ledger"):
        st.rerun()

    df_ledger = fetch_topups_fresh()
    if not df_ledger.empty:
        total_rx = float(df_ledger['amount'].sum()) if 'amount' in df_ledger.columns else 0.0
        l1, l2, l3 = st.columns(3)
        l1.metric("Total Cash Received", f"₹{total_rx:,.2f}")
        l2.metric("No. of Receipts",     len(df_ledger))
        l3.metric("Avg Receipt",         f"₹{total_rx / len(df_ledger):,.2f}")
        st.divider()
        display_topups(df_ledger)
        st.download_button("💾 Download Receipts CSV",
            data=df_ledger.to_csv(index=False).encode('utf-8'),
            file_name=f"bg_cash_receipts_{date.today()}.csv",
            mime="text/csv")
    else:
        st.info("No cash receipts logged yet.")
