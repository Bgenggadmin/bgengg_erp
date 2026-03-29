import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz

# --- 1. SETUP & CONFIG ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Finance | Petty Cash", layout="wide", page_icon="💰")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. LOGIN GATEWAY ---
def check_password():
    def password_entered():
        if st.session_state["password"] == "pcash_bgengg":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔐 B&G Engineering | Petty Cash Login")
        st.text_input("Enter Portal Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔐 B&G Engineering | Petty Cash Login")
        st.text_input("Enter Portal Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect.")
        return False
    return True

if not check_password():
    st.stop()

# --- 3. SMART UTILITIES ---
def get_now_ist():
    return datetime.now(IST)

def get_all_expense_heads():
    try:
        res = conn.table("petty_cash_heads").select("head_name").order("head_name").execute()
        return [row['head_name'] for row in res.data] if res.data else ["GENERAL/INTERNAL"]
    except: return ["GENERAL/INTERNAL"]

def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return [s['name'] for s in res.data] if res.data else ["Staff Member"]
    except: return ["Staff Member"]

def get_cash_metrics():
    res_in = conn.table("petty_cash_topups").select("amount").execute()
    total_in = sum([float(i['amount']) for i in res_in.data]) if res_in.data else 0.0
    res_out = conn.table("petty_cash").select("amount").eq("status", "Authorized").execute()
    total_out = sum([float(i['amount']) for i in res_out.data]) if res_out.data else 0.0
    return total_in, total_out, (total_in - total_out)

# --- 4. NAVIGATION ---
st.sidebar.title("💰 B&G Finance Hub")
if st.sidebar.button("🔓 Logout Portal"):
    del st.session_state["password_correct"]
    st.rerun()

tabs = st.tabs(["📊 Dashboard", "📝 Raise Voucher", "📥 Add Cash", "⚙️ Manage Headers", "📜 History"])

# --- TAB 0: DASHBOARD ---
with tabs[0]:
    st.title("📊 Petty Cash Control Center")
    total_in, total_out, balance = get_cash_metrics()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Receipts (In)", f"₹{total_in:,.2f}")
    c2.metric("Total Issues (Out)", f"₹{total_out:,.2f}", delta_color="inverse")
    c3.metric("Live Balance", f"₹{balance:,.2f}")

    # Analytics Section
    st.divider()
    all_data_res = conn.table("petty_cash").select("*").eq("status", "Authorized").execute()
    if all_data_res.data:
        df_charts = pd.DataFrame(all_data_res.data)
        df_charts['vch_date'] = pd.to_datetime(df_charts['vch_date'])
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.subheader("📈 Spending Trend")
            st.line_chart(df_charts.groupby('vch_date')['amount'].sum())
        with chart_col2:
            st.subheader("🏗️ Head-wise Breakdown")
            st.bar_chart(df_charts.groupby('head_account')['amount'].sum())
    
    st.divider()
    st.subheader("🔐 Admin Authorization")
    admin_auth = st.text_input("Enter Admin Password to Authorize", type="password", key="admin_auth_pwd")
    if admin_auth == "admin_bg_finance":
        pending = conn.table("petty_cash").select("*").eq("status", "Pending").order("id").execute()
        if pending.data:
            for v in pending.data:
                with st.container(border=True):
                    col1, col2, col3 = st.columns([1.5, 3, 1.2])
                    col1.write(f"**Vch No: {v.get('physical_vch_no')}**\n📅 {v.get('vch_date')}\n### ₹{v['amount']}")
                    col2.markdown(f"**Head:** {v['head_account']} | **Receiver:** {v['received_by']}")
                    col2.write(f"**Narration:** {v['purpose']}")
                    adm_note = col2.text_input("Admin Note", key=f"note_{v['id']}")
                    if col3.button("✅ Authorize", key=f"auth_{v['id']}", use_container_width=True):
                        conn.table("petty_cash").update({"status": "Authorized", "authorized_at": get_now_ist().isoformat(), "reject_reason": adm_note}).eq("id", v['id']).execute()
                        st.rerun()
                    if col3.button("❌ Reject", key=f"rej_{v['id']}", use_container_width=True):
                        if not adm_note: st.error("Note required for rejection")
                        else:
                            conn.table("petty_cash").update({"status": "Rejected", "reject_reason": adm_note}).eq("id", v['id']).execute()
                            st.rerun()
        else: st.info("No pending vouchers.")

# --- TAB 1: RAISE VOUCHER (Summary at Bottom) ---
with tabs[1]:
    st.title("📝 Raise New Expense Voucher")
    
    all_heads = get_all_expense_heads()
    # 1. Entry Form First
    with st.form("voucher_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 1, 2])
        v_phys_no = c1.text_input("Physical Voucher No.")
        v_date = c2.date_input("Voucher Date", value=date.today())
        v_amount = c3.number_input("Amount (₹)", min_value=1.0)
        c4, c5 = st.columns(2)
        v_head = c4.selectbox("Towards Head Account", all_heads)
        v_recom = c5.selectbox("Recommended By", get_staff_list())
        v_particulars = st.text_input("Particulars (Received By)")
        v_narration = st.text_area("Narration (Description)")
        if st.form_submit_button("Submit Voucher"):
            if v_particulars and v_narration and v_phys_no:
                conn.table("petty_cash").insert({
                    "physical_vch_no": v_phys_no, "vch_date": str(v_date), "amount": v_amount, 
                    "head_account": v_head, "received_by": v_particulars, "requested_by": v_recom, 
                    "purpose": v_narration, "status": "Pending"
                }).execute()
                st.success("✅ Submitted! Check status below.")
                st.rerun()
            else: st.error("Please fill all fields.")

    st.divider()
    
    # 2. Recent Status Summary Second
    st.subheader("🔔 Recent Submissions Status")
    summary_res = conn.table("petty_cash").select("*").order("created_at", desc=True).limit(10).execute()
    if summary_res.data:
        df_s = pd.DataFrame(summary_res.data)
        pending_count = len(df_s[df_s['status'] == 'Pending'])
        rejected_count = len(df_s[df_s['status'] == 'Rejected'])
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Pending Approval", pending_count)
        m2.metric("Rejected", rejected_count, delta=rejected_count, delta_color="inverse" if rejected_count > 0 else "normal")
        m3.info("Latest 10 entries shown below.")

        st.dataframe(
            df_s[['vch_date', 'physical_vch_no', 'amount', 'status', 'reject_reason']],
            column_config={
                "reject_reason": st.column_config.TextColumn("Admin Remarks"), 
                "status": st.column_config.TextColumn("Status")
            },
            use_container_width=True, hide_index=True
        )

# --- TAB 2, 3, 4 ---
with tabs[2]: # Add Cash
    st.title("📥 Top-up Cash [Receipts]")
    with st.form("cash_in_form", clear_on_submit=True):
        t_amt = st.number_input("Amount Received (₹)", min_value=100.0, step=100.0)
        t_src = st.text_input("Source")
        if st.form_submit_button("Log Receipt"):
            if t_src:
                conn.table("petty_cash_topups").insert({"amount": t_amt, "source": t_src}).execute()
                st.success("💰 Balance Updated!")
                st.rerun()

with tabs[3]: # Manage Headers
    st.title("⚙️ Manage Expense Heads")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("➕ Add New Header")
        with st.form("add_head_form", clear_on_submit=True):
            new_head = st.text_input("Header Name")
            if st.form_submit_button("Add to System"):
                if new_head:
                    conn.table("petty_cash_heads").insert({"head_name": new_head.upper()}).execute()
                    st.rerun()
    with col2:
        st.subheader("🗑️ Remove Header")
        current_heads = get_all_expense_heads()
        head_to_delete = st.selectbox("Select to Remove", current_heads)
        if st.button("Delete Selected Header", type="primary"):
            usage_check = conn.table("petty_cash").select("id").eq("head_account", head_to_delete).limit(1).execute()
            if usage_check.data: st.error("Header in use.")
            else:
                conn.table("petty_cash_heads").delete().eq("head_name", head_to_delete).execute()
                st.rerun()

with tabs[4]: # History
    st.title("📜 Transaction History")
    # ... (Keep existing Filter logic)
    res = conn.table("petty_cash").select("*").order("vch_date", desc=True).execute()
    if res.data:
        df = pd.DataFrame(res.data)
        st.dataframe(df[['vch_date', 'physical_vch_no', 'head_account', 'amount', 'received_by', 'status', 'reject_reason']], use_container_width=True, hide_index=True)
