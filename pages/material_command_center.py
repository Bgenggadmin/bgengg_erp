import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timezone, date
import pytz
import urllib.parse

# --- 1. SETUP & THEME ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Material Command Center | B&G", layout="wide", page_icon="🏗️")

# Custom CSS for B&G Branding
st.markdown("""
    <style>
    .bg-header { background-color: #003366; color: white; padding: 1rem; border-radius: 8px; text-align: center; }
    /* Reduced Blue Strip Size */
    .blue-strip { background-color: #007bff; height: 3px; width: 100%; margin: 10px 0 20px 0; }
    .summary-box { background-color: #f0f7ff; padding: 12px; border-radius: 10px; border-left: 5px solid #003366; }
    .stTabs [aria-selected="true"] { background-color: #007bff !important; color: white !important; }
    </style>
    """, unsafe_allow_html=True)

# --- PASSWORD PROTECTION ---
def check_password():
    if "password_correct" not in st.session_state:
        st.markdown('<div class="bg-header"><h1>B&G ENGINEERING</h1><p>ERP SYSTEM ACCESS</p></div>', unsafe_allow_html=True)
        st.text_input("🔑 Enter Master Password", type="password", 
                      on_change=lambda: st.session_state.update({"password_correct": st.session_state["password"] == "1234"}), 
                      key="password")
        return False
    return st.session_state["password_correct"]

if not check_password(): st.stop()

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS (FIXED FOR JOB CODES) ---
def get_jobs():
    # Explicitly selecting job_no from anchor_projects
    try:
        res = conn.table("anchor_projects").select("job_no").execute()
        # Filter for non-null and non-empty jobs
        jobs = [str(r['job_no']) for r in res.data if r.get('job_no') and str(r['job_no']).strip() != ""]
        return sorted(list(set(jobs)))
    except: return []

def get_material_groups():
    res = conn.table("material_master").select("material_group").execute()
    return sorted([str(r['material_group']) for r in res.data]) if res.data else ["GENERAL"]

def get_staff_list():
    res = conn.table("master_staff").select("name").execute()
    return sorted([r['name'] for r in res.data]) if res.data else ["Admin"]

# --- BRANDED HEADER ---
st.markdown('<div class="bg-header"><h1>B&G ENGINEERING</h1><p>UNIFIED MATERIAL LOGISTICS HUB</p></div>', unsafe_allow_html=True)
st.markdown('<div class="blue-strip"></div>', unsafe_allow_html=True)

# --- 3. NAVIGATION ---
main_tabs = st.tabs(["📝 Indent Application", "🛒 Purchase Console", "📦 Stores GRN", "⚙️ Master Setup"])

# --- TAB 1: INDENT APPLICATION ---
with main_tabs[0]:
    st.subheader("New Material Request")
    raised_by_name = st.selectbox("Identify Yourself (Raised By)", get_staff_list())
    
    if "indent_cart" not in st.session_state:
        st.session_state.indent_cart = []

    # PART A: ITEM ENTRY FORM
    with st.expander("➕ Add Item to this Indent", expanded=True):
        with st.form("indent_item_form", clear_on_submit=True):
            f1, f2 = st.columns(2)
            selected_jobs = f1.multiselect("Target Job Nos", get_jobs())
            mat_group = f2.selectbox("Material Group", get_material_groups())
            
            i_desc = st.text_input("Item Name / Description")
            i_specs = st.text_area("Specifications (Size/Grade/Brand)")
            
            c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
            i_qty = c1.number_input("Quantity", min_value=0.1)
            i_unit = c2.selectbox("Units", ["Nos", "Kgs", "Mts", "Sft", "Sets"])
            
            # TRIGGER LOGIC: Item-wise Trigger
            i_urgent = c3.toggle("🚨 URGENT TRIGGER?")
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
                    st.toast("Item Added!")
                else: st.error("Job and Item Name required.")

    # PART B: SUBMIT & EXPORT
    if st.session_state.indent_cart:
        st.markdown("### 📋 Review Draft Indent")
        cart_df = pd.DataFrame(st.session_state.indent_cart)
        st.dataframe(cart_df[['job_no', 'item_name', 'quantity', 'is_urgent']], use_container_width=True, hide_index=True)
        
        c_b1, c_b2 = st.columns(2)
        if c_b1.button("🗑️ Clear List", use_container_width=True):
            st.session_state.indent_cart = []
            st.rerun()
            
        if c_b2.button("🚀 FINAL SUBMIT INDENT", type="primary", use_container_width=True):
            try:
                header = conn.table("indent_headers").insert({"raised_by": raised_by_name}).execute()
                new_id = header.data[0]['indent_no']
                for item in st.session_state.indent_cart:
                    item['indent_no'] = new_id
                    conn.table("purchase_orders").insert(item).execute()
                st.success(f"Indent #{new_id} submitted!"); st.session_state.indent_cart = []; st.rerun()
            except Exception as e: st.error(f"Submit Error: {e}")

    # PART C: SEARCH & HISTORY
    st.divider()
    sc1, sc2 = st.columns([3, 1])
    search_j = sc1.text_input("🔍 Filter History by Job Code", placeholder="Type Job No...")
    
    hist_res = conn.table("purchase_orders").select("*").order("created_at", desc=True).execute()
    if hist_res.data:
        df_h = pd.DataFrame(hist_res.data)
        if search_j:
            df_h = df_h[df_h['job_no'].str.contains(search_j, case=False, na=False)]
        
        st.dataframe(df_h[['indent_no', 'job_no', 'item_name', 'quantity', 'status', 'is_urgent']], use_container_width=True, hide_index=True)
        
        csv = df_h.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Export Indent Summary (CSV)", data=csv, file_name=f"BG_Indents_{date.today()}.csv")

        # Summary Footer
        st.markdown('<div class="summary-box">', unsafe_allow_html=True)
        sum1, sum2, sum3 = st.columns(3)
        sum1.metric("Items Found", len(df_h))
        sum2.metric("Total Quantity", f"{df_h['quantity'].sum():.1f}")
        sum3.metric("Urgent Triggers", int(df_h['is_urgent'].sum()))
        st.markdown('</div>', unsafe_allow_html=True)

# --- TAB 2: PURCHASE CONSOLE ---
with main_tabs[1]:
    st.subheader("📋 Purchase Processing")
    res_p = conn.table("purchase_orders").select("*").neq("status", "Received").neq("status", "Rejected").execute()
    
    if res_p.data:
        df_p = pd.DataFrame(res_p.data).sort_values(by=['is_urgent', 'created_at'], ascending=[False, False])
        for _, row in df_p.iterrows():
            urgent_tag = "🚨 [URGENT]" if row.get('is_urgent') else ""
            with st.container(border=True):
                h1, h2, h3 = st.columns([2, 2, 1])
                h1.write(f"**Indent #{row.get('indent_no')}** | Job: {row['job_no']}")
                h1.caption(f"Triggered by: {row.get('triggered_by')}")
                h2.write(f"{urgent_tag} **{row['item_name']}**")
                h2.caption(f"Specs: {row.get('specs', 'N/A')}")
                
                # SHARE LOGIC: Direct text for WhatsApp/Email
                share_text = f"B&G Enquiry: {row['item_name']} | Qty: {row['quantity']} | Specs: {row.get('specs')}"
                whatsapp_url = f"https://wa.me/?text={urllib.parse.quote(share_text)}"
                h3.markdown(f"[📲 Send to Supplier]({whatsapp_url})")

                with st.expander("🛠️ Finalize Purchase"):
                    c1, c2, c3 = st.columns(3)
                    p_no = c1.text_input("PO No", key=f"po_{row['id']}")
                    p_dt = c2.date_input("PO Date", key=f"podt_{row['id']}")
                    p_rem = st.text_input("Remarks", key=f"rem_{row['id']}")
                    
                    b1, b2 = st.columns(2)
                    if b1.button("✅ Confirm Order", key=f"ok_{row['id']}", use_container_width=True, type="primary"):
                        conn.table("purchase_orders").update({"status": "Ordered", "po_no": p_no, "po_date": str(p_dt), "purchase_reply": p_rem}).eq("id", row['id']).execute()
                        st.rerun()
                    if b2.button("❌ Reject", key=f"rej_{row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({"status": "Rejected", "reject_note": p_rem}).eq("id", row['id']).execute()
                        st.rerun()
    else: st.info("No pending requests.")

# --- TAB 3: STORES GRN ---
with main_tabs[2]:
    st.subheader("📦 Stores Management")
    res_s = conn.table("purchase_orders").select("*").eq("status", "Ordered").execute()
    if res_s.data:
        for row in res_s.data:
            with st.container(border=True):
                s1, s2, s3 = st.columns([2, 2, 1])
                s1.write(f"**PO:** {row.get('po_no')} | Job: {row['job_no']}")
                s2.write(f"**Item:** {row.get('item_name')} ({row['quantity']})")
                if s3.popover("📥 Log Arrival"):
                    rdt = st.date_input("Arrival Date", value=date.today(), key=f"rdt_{row['id']}")
                    snote = st.text_area("Remarks", key=f"snote_{row['id']}")
                    if st.button("Confirm", key=f"sbtn_{row['id']}", type="primary"):
                        conn.table("purchase_orders").update({"status": "Received", "received_date": str(rdt), "stores_remarks": snote}).eq("id", row['id']).execute()
                        st.rerun()
    else: st.info("Waiting for POs to be issued.")

# --- TAB 4: MASTER SETUP ---
with main_tabs[3]:
    st.subheader("⚙️ Configuration")
    m_col1, m_col2 = st.columns(2)
    with m_col1:
        with st.form("master_group_form", clear_on_submit=True):
            new_g = st.text_input("Add Material Group")
            if st.form_submit_button("➕ Save"):
                if new_g:
                    conn.table("material_master").insert({"material_group": new_g.upper()}).execute()
                    st.rerun()
    with m_col2:
        groups = conn.table("material_master").select("*").execute().data
        if groups: st.dataframe(pd.DataFrame(groups)[['material_group']], hide_index=True)
