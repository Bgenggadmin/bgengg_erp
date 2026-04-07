import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timezone, date
import pytz

# --- 1. SETUP & THEME ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Material Management | B&G", layout="wide", page_icon="🏗️")

# --- PASSWORD PROTECTION ---
def check_password():
    if "password_correct" not in st.session_state:
        st.text_input("🔑 Enter Master Password", type="password", 
                      on_change=lambda: st.session_state.update({"password_correct": st.session_state["password"] == "1234"}), 
                      key="password")
        return False
    return st.session_state["password_correct"]

if not check_password(): st.stop()

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
def get_jobs():
    res = conn.table("anchor_projects").select("job_no").execute()
    return sorted([str(r['job_no']) for r in res.data if r.get('job_no')]) if res.data else []

def get_material_groups():
    res = conn.table("material_master").select("material_group").execute()
    return sorted([str(r['material_group']) for r in res.data]) if res.data else ["GENERAL"]

def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return sorted([r['name'] for r in res.data]) if res.data else ["Admin", "General Staff"]
    except: return ["Admin", "General Staff"]

# --- 3. NAVIGATION ---
main_tabs = st.tabs(["🛒 Purchase Console", "📝 New Indent", "📦 Stores GRN", "⚙️ Master Setup"])

# --- TAB 1: PURCHASE CONSOLE ---
with main_tabs[0]:
    st.subheader("📋 Pending Material Requests")
    
    # Fetch data: Everything triggered but not yet Received/Rejected
    res = conn.table("purchase_orders").select("*").neq("status", "Received").neq("status", "Rejected").execute()
    df_p = pd.DataFrame(res.data) if res.data else pd.DataFrame()

    if not df_p.empty:
        # Sort so newest/Urgent are prominent
        df_p = df_p.sort_values(by=['is_urgent', 'created_at'], ascending=[False, False])
        
        for _, row in df_p.iterrows():
            urgent_tag = "🚨 [URGENT]" if row.get('is_urgent') else ""
            indent_id = row.get('indent_no', 'Direct')
            raised_by = row.get('triggered_by', 'Unknown')
            
            with st.container(border=True):
                h1, h2, h3 = st.columns([2, 2, 1])
                h1.write(f"**Indent #{indent_id}** | Job: {row['job_no']}")
                h1.caption(f"Raised by: **{raised_by}** | Group: {row.get('material_group', 'General')}")
                
                h2.write(f"{urgent_tag} **{row['item_name']}**")
                h2.caption(f"Qty: {row['quantity']} {row.get('units', 'Nos')} | Notes: {row.get('special_notes', '-')}")
                
                h3.write(f"Status: `{row['status']}`")
                
                with st.expander("🛠️ Action: Process PO / Reject"):
                    c1, c2, c3 = st.columns(3)
                    po_no = c1.text_input("PO Number", key=f"po_{row['id']}")
                    po_dt = c2.date_input("PO Date", key=f"podt_{row['id']}")
                    exp_dt = c3.date_input("Expected Delivery", key=f"exp_{row['id']}")
                    p_note = st.text_input("Purchase Note / Remarks", key=f"rem_{row['id']}")
                    
                    b1, b2 = st.columns(2)
                    if b1.button("✅ Issue PO", key=f"ok_{row['id']}", use_container_width=True, type="primary"):
                        conn.table("purchase_orders").update({
                            "status": "Ordered", "po_no": po_no, "po_date": str(po_dt), 
                            "expected_delivery": str(exp_dt), "purchase_reply": p_note
                        }).eq("id", row['id']).execute()
                        st.success(f"PO {po_no} Issued!"); st.rerun()
                        
                    if b2.button("❌ Reject Item", key=f"rej_{row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({
                            "status": "Rejected", "reject_note": p_note
                        }).eq("id", row['id']).execute()
                        st.warning("Item Rejected."); st.rerun()
    else:
        st.info("No active material requests found.")

# --- TAB 2: INDENT APPLICATION (The Hub) ---
with main_tabs[1]:
    st.subheader("📝 Create New Material Indent")
    
    # Selection of Staff Name from Master List
    raised_by_name = st.selectbox("Identify Yourself (Indent Raised By)", get_staff_list())
    
    # Session State for Multi-Item Indent
    if "indent_cart" not in st.session_state:
        st.session_state.indent_cart = []

    # --- PART A: ADD ITEM TO CART ---
    with st.expander("➕ Add Item to this Indent", expanded=True):
        with st.form("indent_item_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            selected_jobs = col1.multiselect("Select Job Nos", get_jobs())
            mat_group = col2.selectbox("Material Group", get_material_groups())
            
            i_desc = st.text_input("Item Name / Description")
            i_specs = st.text_area("Specifications (Size/Grade/Brand)")
            
            c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
            i_qty = c1.number_input("Quantity", min_value=0.1)
            i_unit = c2.selectbox("Units", ["Nos", "Kgs", "Mts", "Sft", "Sets"])
            i_urgent = c3.toggle("🚨 URGENT?")
            i_notes = c4.text_input("Item Remarks")
            
            if st.form_submit_button("Add Item to List"):
                if selected_jobs and i_desc:
                    st.session_state.indent_cart.append({
                        "job_no": ", ".join(selected_jobs),
                        "material_group": mat_group,
                        "item_name": i_desc.upper(),
                        "specs": i_specs,
                        "quantity": i_qty,
                        "units": i_unit,
                        "is_urgent": i_urgent,
                        "special_notes": i_notes,
                        "triggered_by": raised_by_name,
                        "status": "Triggered"
                    })
                    st.toast("Item Added to List!")
                else:
                    st.error("Please provide Job No and Item Name.")

    # --- PART B: REVIEW AND FINAL SUBMIT ---
    if st.session_state.indent_cart:
        st.write("---")
        st.write("### Review Draft Indent")
        cart_df = pd.DataFrame(st.session_state.indent_cart)
        st.dataframe(cart_df[['job_no', 'item_name', 'quantity', 'units', 'is_urgent']], use_container_width=True, hide_index=True)
        
        btn_c1, btn_c2 = st.columns(2)
        if btn_c1.button("🗑️ Clear All Items", use_container_width=True):
            st.session_state.indent_cart = []
            st.rerun()
            
        if btn_c2.button("🚀 FINAL SUBMIT INDENT", type="primary", use_container_width=True):
            try:
                # 1. Create a Header entry to get a unique Indent No
                header = conn.table("indent_headers").insert({"raised_by": raised_by_name}).execute()
                new_indent_id = header.data[0]['indent_no']
                
                # 2. Push all cart items to the database with the linked Indent No
                for item in st.session_state.indent_cart:
                    item['indent_no'] = new_indent_id
                    conn.table("purchase_orders").insert(item).execute()
                
                st.success(f"Indent #{new_indent_id} submitted successfully!")
                st.session_state.indent_cart = []
                st.rerun()
            except Exception as e:
                st.error(f"Submit Error: {e}")

# --- TAB 3: STORES GRN ---
with main_tabs[2]:
    st.subheader("📦 Stores Receipt Management")
    res_s = conn.table("purchase_orders").select("*").eq("status", "Ordered").execute()
    
    if res_s.data:
        for row in res_s.data:
            with st.container(border=True):
                s1, s2, s3 = st.columns([2, 2, 1])
                s1.write(f"**PO No:** {row.get('po_no')} | **Indent:** {row.get('indent_no')}")
                s1.caption(f"Job: {row['job_no']}")
                
                s2.write(f"**Item:** {row['item_name']}")
                s2.caption(f"Qty: {row['quantity']} {row.get('units')}")
                
                if s3.popover("📥 Log Receipt"):
                    r_date = st.date_input("Received Date", value=date.today(), key=f"rdt_{row['id']}")
                    r_note = st.text_area("Stores Remarks (Shortage/Damage?)", key=f"snote_{row['id']}")
                    if st.button("Confirm Arrival", key=f"sbtn_{row['id']}", type="primary"):
                        conn.table("purchase_orders").update({
                            "status": "Received",
                            "received_date": str(r_date),
                            "stores_remarks": r_note
                        }).eq("id", row['id']).execute()
                        st.success("Item Marked as Received!"); st.rerun()
    else:
        st.info("No items currently marked as 'Ordered' (Waiting for Purchase PO).")

# --- TAB 4: MASTER SETUP ---
with main_tabs[3]:
    st.subheader("⚙️ Materials Master Configuration")
    
    m_col1, m_col2 = st.columns(2)
    
    with m_col1:
        st.markdown("**Add Material Group**")
        with st.form("master_group_form", clear_on_submit=True):
            new_g = st.text_input("New Group Name (e.g., Raw Steel)")
            if st.form_submit_button("➕ Save Group"):
                if new_g:
                    conn.table("material_master").insert({"material_group": new_g.upper()}).execute()
                    st.success("Group Added!"); st.rerun()

    with m_col2:
        st.markdown("**Current Groups**")
        groups = conn.table("material_master").select("*").execute().data
        if groups:
            st.dataframe(pd.DataFrame(groups)[['material_group']], hide_index=True, use_container_width=True)
