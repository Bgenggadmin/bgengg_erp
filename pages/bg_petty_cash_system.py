import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz

# --- 1. SETUP & CONFIG ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Finance | Petty Cash", layout="wide", page_icon="💰")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. LOGIN GATEWAY (PORTAL ACCESS) ---
def check_password():
    def password_entered():
        # Portal Password for staff/accounts to enter
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

# --- TAB: DASHBOARD (ADMIN AUTHORIZATION) ---
with tabs[0]:
    st.title("📊 Petty Cash Control Center")
    total_in, total_out, balance = get_cash_metrics()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Receipts (In)", f"₹{total_in:,.2f}")
    c2.metric("Total Issues (Out)", f"₹{total_out:,.2f}", delta_color="inverse")
    c3.metric("Live Balance", f"₹{balance:,.2f}")

    st.divider()
    st.subheader("🔐 Admin Authorization")
    
    # NEW: Secure Admin Password for your use only
    admin_auth = st.text_input("Enter Admin Password to Authorize", type="password", key="admin_auth_pwd")
    
    if admin_auth == "admin_bg_finance":
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
                        st.success(f"Voucher {v['id']} Authorized.")
                        st.rerun()
        else: st.info("No vouchers awaiting authorization.")
    elif admin_auth != "":
        st.error("❌ Admin Password Incorrect.")

# --- TAB: MANAGE HEADERS (PROTECTED) ---
with tabs[3]:
    st.title("⚙️ Manage Expense Heads")
    # Only allow management if Admin password is correct
    admin_manage = st.text_input("Enter Admin Password to Manage Headers", type="password", key="admin_manage_pwd")
    
    if admin_manage == "admin_bg_finance":
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("➕ Add New Header")
            with st.form("add_head_form", clear_on_submit=True):
                new_head = st.text_input("Header Name")
                if st.form_submit_button("Add to System"):
                    if new_head:
                        conn.table("petty_cash_heads").insert({"head_name": new_head.upper()}).execute()
                        st.success("Header Added.")
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
    elif admin_manage != "":
        st.error("❌ Admin Password Incorrect.")

# --- REMAINING TABS (RAISE VOUCHER, ADD CASH, HISTORY) ---
# [Logic remains as per previous version...]

# --- TAB: HISTORY ---
with tabs[4]:
    st.title("📜 Transaction History")
    res = conn.table("petty_cash").select("*").order("created_at", desc=True).execute()
    if res.data:
        df = pd.DataFrame(res.data)
        st.dataframe(df[['created_at', 'head_account', 'amount', 'received_by', 'status']], use_container_width=True)
