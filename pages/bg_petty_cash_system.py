import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz

# --- 1. SETUP & CONFIG ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Finance | Petty Cash", layout="wide", page_icon="💰")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. LOGIN GATEWAY ---
def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == "pcash_bgengg":
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.title("🔐 B&G Engineering | Petty Cash Login")
        st.text_input(
            "Enter Portal Password", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password incorrect, show input + error.
        st.title("🔐 B&G Engineering | Petty Cash Login")
        st.text_input(
            "Enter Portal Password", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password incorrect. Please try again.")
        return False
    else:
        # Password correct.
        return True

if not check_password():
    st.stop()  # Do not run the rest of the app if not logged in

# --- 3. SMART UTILITIES ---
def get_now_ist():
    return datetime.now(IST)

def get_all_expense_heads():
    try:
        res = conn.table("petty_cash_heads").select("head_name").order("head_name").execute()
        if res.data:
            return [row['head_name'] for row in res.data]
        return ["GENERAL/INTERNAL", "ACCOUNTS", "PURCHASE", "MAINTENANCE"]
    except:
        return ["GENERAL/INTERNAL"]

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
if st.sidebar.button("🔓 Logout"):
    del st.session_state["password_correct"]
    st.rerun()

menu = ["📊 Dashboard", "📝 Raise Voucher", "📥 Add Cash", "⚙️ Manage Headers", "📜 History"]
choice = st.sidebar.radio("Navigate", menu)

# --- PAGE: DASHBOARD ---
if choice == "📊 Dashboard":
    st.title("📊 Petty Cash Control Center")
    total_in, total_out, balance = get_cash_metrics()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Receipts (In)", f"₹{total_in:,.2f}")
    c2.metric("Total Issues (Out)", f"₹{total_out:,.2f}", delta_color="inverse")
    c3.metric("Live Balance", f"₹{balance:,.2f}")

    st.divider()
    st.subheader("🔐 Admin Authorization (Brahmiah)")
    # Note: Admin uses the same password as the app for authorization convenience
    if st.text_input("Enter Admin Authorization Key", type="password") == "pcash_bgengg":
        pending = conn.table("petty_cash").select("*").eq("status", "Pending").order("id").execute()
        if pending.data:
            for v in pending.data:
                with st.container(border=True):
                    col1, col2, col3 = st.columns([1, 3, 1])
                    col1.write(f"**Vch #{v['id']}**\n### ₹{v['amount']}")
                    col2.markdown(f"**Head:** {v['head_account']} | **Receiver:** {v['received_by']}")
                    col2.write(f"**Narration:** {v['purpose']}")
                    if col3.button("✅ Authorize", key=f"auth_{v['id']}", use_container_width=True):
                        conn.table("petty_cash").update({"status": "Authorized", "authorized_at": get_now_ist().isoformat()}).eq("id", v['id']).execute()
                        st.rerun()
        else: st.info("No pending vouchers for authorization.")

# --- PAGE: MANAGE HEADERS ---
elif choice == "⚙️ Manage Headers":
    st.title("⚙️ Manage Expense Heads")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("➕ Add New Header")
        with st.form("add_head_form", clear_on_submit=True):
            new_head = st.text_input("Header Name")
            if st.form_submit_button("Add to System"):
                if new_head:
                    conn.table("petty_cash_heads").insert({"head_name": new_head.upper()}).execute()
                    st.success(f"Added '{new_head.upper()}'")
                    st.rerun()
    with col2:
        st.subheader("🗑️ Remove Header")
        current_heads = get_all_expense_heads()
        head_to_delete = st.selectbox("Select to Remove", current_heads)
        if st.button("Delete Selected Header", type="primary"):
            usage_check = conn.table("petty_cash").select("id").eq("head_account", head_to_delete).limit(1).execute()
            if usage_check.data:
                st.error("Header is in use and cannot be deleted.")
            else:
                conn.table("petty_cash_heads").delete().eq("head_name", head_to_delete).execute()
                st.success("Removed.")
                st.rerun()

# --- PAGE: RAISE VOUCHER ---
elif choice == "📝 Raise Voucher":
    st.title("📝 Raise New Expense Voucher")
    all_heads = get_all_expense_heads()
    with st.form("voucher_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        v_amount = c1.number_input("Amount (₹)", min_value=1.0)
        v_head = c2.selectbox("Towards Head Account", all_heads)
        c3, c4 = st.columns(2)
        v_particulars = c3.text_input("Particulars (Paid To)")
        v_recom = c4.selectbox("Recommended By", get_staff_list())
        v_narration = st.text_area("Narration")
        if st.form_submit_button("Submit"):
            conn.table("petty_cash").insert({
                "amount": v_amount, "head_account": v_head, "received_by": v_particulars,
                "requested_by": v_recom, "purpose": v_narration, "status": "Pending"
            }).execute()
            st.success("Submitted for Approval.")

# --- PAGE: ADD CASH ---
elif choice == "📥 Add Cash":
    st.title("📥 Top-up Cash [Receipts]")
    with st.form("cash_in"):
        t_amt = st.number_input("Amount Received (₹)", min_value=100.0, step=100.0)
        t_src = st.text_input("Received From (e.g. Bank Withdrawal)")
        if st.form_submit_button("Log Receipt"):
            conn.table("petty_cash_topups").insert({"amount": t_amt, "source": t_src}).execute()
            st.success("Balance Updated!")

# --- PAGE: HISTORY ---
elif choice == "📜 History":
    st.title("📜 Transaction History")
    res = conn.table("petty_cash").select("*").order("created_at", desc=True).execute()
    if res.data:
        df = pd.DataFrame(res.data)
        st.dataframe(df[['created_at', 'head_account', 'amount', 'received_by', 'status']], use_container_width=True)
