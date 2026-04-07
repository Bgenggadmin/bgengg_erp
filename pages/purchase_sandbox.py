import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timezone, date
import pytz

# --- 1. SETUP & THEME ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Material Management | B&G", layout="wide", page_icon="🏗️")

# --- PASSWORD PROTECTION (Keeping your existing logic) ---
def check_password():
    if "password_correct" not in st.session_state:
        st.text_input("🔑 Enter Master Password", type="password", 
                      on_change=lambda: st.session_state.update({"password_correct": st.session_state["password"] == "1234"}), 
                      key="password")
        return False
    return st.session_state["password_correct"]

if not check_password(): st.stop()

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS (Fixed for TypeErrors) ---
def get_jobs():
    res = conn.table("anchor_projects").select("job_no").execute()
    # FIX: Filter out None/Empty job numbers before sorting to prevent TypeError
    return sorted([str(r['job_no']) for r in res.data if r.get('job_no')]) if res.data else []

def get_material_groups():
    res = conn.table("material_master").select("material_group").execute()
    return sorted([str(r['material_group']) for r in res.data]) if res.data else ["GENERAL"]

# --- 3. NAVIGATION ---
main_tabs = st.tabs(["🛒 Purchase Console", "📝 New Indent", "📦 Stores GRN", "⚙️ Master Setup"])

# --- TAB 1: PURCHASE CONSOLE (Your existing logic) ---
with main_tabs[0]:
    st.subheader("Pending Material Requests")
    # Fetch data
    res = conn.table("purchase_orders").select("*").neq("status", "Received").neq("status", "Rejected").execute()
    df_p = pd.DataFrame(res.data) if res.data else pd.DataFrame()

    if not df_p.empty:
        for _, row in df_p.iterrows():
            with st.container(border=True):
                h1, h2, h3 = st.columns([2, 2, 1])
                h1.write(f"**Job:** {row['job_no']} | **Group:** {row.get('material_group', 'General')}")
                h2.write(f"**Item:** {row['item_name']} ({row['quantity']} {row.get('units', 'Nos')})")
                h3.write(f"Status: `{row['status']}`")
                
                with st.expander("🛠️ Process PO / Reject"):
                    c1, c2, c3 = st.columns(3)
                    po_no = c1.text_input("PO Number", key=f"po_{row['id']}")
                    po_dt = c2.date_input("PO Date", key=f"podt_{row['id']}")
                    exp_dt = c3.date_input("Exp. Delivery", key=f"exp_{row['id']}")
                    p_note = st.text_input("Remarks", key=f"rem_{row['id']}")
                    
                    b1, b2 = st.columns(2)
                    # FIX: Integrated the PO Save logic
                    if b1.button("✅ Issue PO", key=f"ok_{row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({
                            "status": "Ordered", "po_no": po_no, "po_date": str(po_dt), 
                            "expected_delivery": str(exp_dt), "purchase_reply": p_note
                        }).eq("id", row['id']).execute()
                        st.rerun()
                    if b2.button("❌ Reject", key=f"rej_{row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({"status": "Rejected", "reject_note": p_note}).eq("id", row['id']).execute()
                        st.rerun()
    else:
        st.info("No active material requests found.")

# --- TAB 2: INDENT APPLICATION ---
with main_tabs[1]:
    st.subheader("Create New Indent")
    with st.form("indent_form_fixed", clear_on_submit=True):
        col1, col2 = st.columns(2)
        jobs = col1.multiselect("Target Job Nos", get_jobs())
        group = col2.selectbox("Material Group", get_material_groups())
        desc = st.text_input("Item Name")
        specs = st.text_area("Specifications")
        c1, c2, c3 = st.columns(3)
        qty = c1.number_input("Qty", min_value=0.1)
        unit = c2.selectbox("Units", ["Nos", "Kgs", "Mts", "Sft"])
        notes = c3.text_input("Notes")
        
        # FIX: Added the mandatory Submit Button
        if st.form_submit_button("🚀 Submit Indent"):
            if jobs and desc:
                conn.table("purchase_orders").insert({
                    "job_no": ", ".join(jobs), "material_group": group, "item_name": desc.upper(),
                    "specs": specs, "quantity": qty, "units": unit, "special_notes": notes, "status": "Triggered"
                }).execute()
                st.success("Indent Created!"); st.rerun()
            else: st.error("Job and Item Name are required.")

# --- TAB 3: STORES GRN ---
with main_tabs[2]:
    st.subheader("Confirm Material Receipt")
    res_s = conn.table("purchase_orders").select("*").eq("status", "Ordered").execute()
    if res_s.data:
        for row in res_s.data:
            with st.container(border=True):
                s1, s2, s3 = st.columns([2, 2, 1])
                s1.write(f"**PO:** {row.get('po_no')} | **Job:** {row['job_no']}")
                s2.write(f"**Item:** {row['item_name']}")
                if s3.popover("📥 Receive"):
                    rec_dt = st.date_input("Received Date", key=f"rdt_{row['id']}")
                    if st.button("Confirm", key=f"cbtn_{row['id']}"):
                        conn.table("purchase_orders").update({"status": "Received", "received_date": str(rec_dt)}).eq("id", row['id']).execute()
                        st.rerun()
    else: st.info("No items pending receipt.")

# --- TAB 4: MASTER SETUP ---
with main_tabs[3]:
    st.subheader("Manage Material Groups")
    with st.form("master_form_fixed", clear_on_submit=True):
        new_g = st.text_input("New Group Name")
        if st.form_submit_button("➕ Add"):
            if new_g:
                conn.table("material_master").insert({"material_group": new_g.upper()}).execute()
                st.rerun()
