import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Materials ERP", layout="wide", page_icon="🏗️")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA UTILITIES ---
def get_jobs():
    res = conn.table("anchor_projects").select("job_no").execute()
    return sorted([r['job_no'] for r in res.data]) if res.data else []

def get_material_groups():
    res = conn.table("material_master").select("material_group").execute()
    return sorted([r['material_group'] for r in res.data]) if res.data else ["GENERAL"]

# --- 3. NAVIGATION ---
st.title("🏗️ B&G Materials Command Center")
tab_indent, tab_purchase, tab_stores, tab_master = st.tabs([
    "📝 Indent Application", 
    "⚖️ Purchase Console", 
    "📦 Stores Application", 
    "⚙️ Master Setup"
])

# --- 4. INDENT APPLICATION (The Entry Point) ---
with tab_indent:
    st.subheader("New Material Request")
    with st.form("indent_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        jobs = col1.multiselect("Target Job Nos", get_jobs())
        group = col2.selectbox("Material Group", get_material_groups())
        
        desc = st.text_input("Material Description (Item Name)")
        specs = st.text_area("Detailed Specs (Size, Grade, etc.)")
        
        c1, c2, c3 = st.columns([1, 1, 2])
        qty = c1.number_input("Quantity", min_value=0.1, step=0.1)
        unit = c2.selectbox("Units", ["Nos", "Kgs", "Mts", "Sft", "Sets"])
        notes = c3.text_input("Special Notes")
        
        if st.form_submit_button("🚀 Submit Indent"):
            if jobs and desc:
                payload = {
                    "job_no": ", ".join(jobs),
                    "material_group": group,
                    "item_name": desc.upper(),
                    "specs": specs,
                    "quantity": qty,
                    "units": unit,
                    "special_notes": notes,
                    "status": "Triggered",
                    "created_at": datetime.now(pytz.utc).isoformat()
                }
                conn.table("purchase_orders").insert(payload).execute()
                st.success("Indent Created!"); st.rerun()
            else:
                st.error("Please select Job No and enter Description.")

# --- 5. PURCHASE CONSOLE (The Processing Hub) ---
with tab_purchase:
    st.subheader("Pending Indent Processing")
    # Fetch items that are NOT received or rejected
    res = conn.table("purchase_orders").select("*").neq("status", "Received").neq("status", "Rejected").execute()
    df_p = pd.DataFrame(res.data) if res.data else pd.DataFrame()

    if not df_p.empty:
        for _, row in df_p.iterrows():
            with st.container(border=True):
                h1, h2, h3 = st.columns([2, 2, 1])
                h1.write(f"**Job:** {row['job_no']} | **Group:** {row['material_group']}")
                h2.write(f"**Item:** {row['item_name']} ({row['quantity']} {row['units']})")
                h3.write(f"Status: `{row['status']}`")
                
                with st.expander("🛠️ Process Order / Reject"):
                    c1, c2, c3 = st.columns(3)
                    po_no = c1.text_input("PO Number", key=f"po_{row['id']}")
                    po_dt = c2.date_input("PO Date", key=f"podt_{row['id']}")
                    exp_dt = c3.date_input("Exp. Delivery", key=f"exp_{row['id']}")
                    
                    p_note = st.text_input("Rejection Note / Purchase Remarks", key=f"rem_{row['id']}")
                    
                    b1, b2, b3 = st.columns(3)
                    if b1.button("✅ Issue PO", key=f"ok_{row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({
                            "status": "Ordered", "po_no": po_no, "po_date": str(po_dt), 
                            "expected_delivery": str(exp_dt), "purchase_reply": p_note
                        }).eq("id", row['id']).execute(); st.rerun()
                        
                    if b2.button("❌ Reject", key=f"rej_{row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({"status": "Rejected", "reject_note": p_note}).eq("id", row['id']).execute(); st.rerun()
    else:
        st.info("No pending indents.")

# --- 6. STORES APPLICATION (The Arrival Point) ---
with tab_stores:
    st.subheader("GRN / Material Receipt")
    # Only items marked as Ordered show up here
    res_s = conn.table("purchase_orders").select("*").eq("status", "Ordered").execute()
    df_s = pd.DataFrame(res_s.data) if res_s.data else pd.DataFrame()

    if not df_s.empty:
        for _, row in df_s.iterrows():
            with st.container(border=True):
                s1, s2, s3 = st.columns([2, 2, 1])
                s1.write(f"**PO:** {row['po_no']} | **Job:** {row['job_no']}")
                s2.write(f"**Item:** {row['item_name']} ({row['quantity']} {row['units']})")
                
                if s3.popover("📥 Receive"):
                    rec_dt = st.date_input("Received Date", key=f"rdt_{row['id']}")
                    s_rem = st.text_area("Stores Remarks", key=f"srem_{row['id']}")
                    if st.button("Confirm Receipt", key=f"cbtn_{row['id']}"):
                        conn.table("purchase_orders").update({
                            "status": "Received", "received_date": str(rec_dt), "stores_remarks": s_rem
                        }).eq("id", row['id']).execute(); st.success("GRN Complete!"); st.rerun()
    else:
        st.info("No items pending receipt.")

# --- 7. MASTER SETUP ---
with tab_master:
    st.subheader("Material Master Configuration")
    with st.form("master_form", clear_on_submit=True):
        new_g = st.text_input("New Material Group")
        if st.form_submit_button("➕ Add Group"):
            if new_g:
                conn.table("material_master").insert({"material_group": new_g.upper()}).execute()
                st.rerun()
    
    m_list = conn.table("material_master").select("*").execute().data
    if m_list: st.table(pd.DataFrame(m_list)[['material_group']])
