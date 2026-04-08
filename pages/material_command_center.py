import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz
import urllib.parse

# --- 1. SETUP & BRANDING ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Command Center", layout="wide", page_icon="🏗️")

st.markdown("""
    <style>
    .bg-header { background-color: #003366; color: white; padding: 1rem; border-radius: 8px; text-align: center; }
    .blue-strip { background-color: #007bff; height: 3px; width: 100%; margin: 10px 0 20px 0; }
    .urgent-row { background-color: #fff5f5; border: 1px solid #ff0000; border-radius: 5px; padding: 10px; margin-bottom: 5px; }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
def get_jobs():
    try:
        res = conn.table("anchor_projects").select("job_no").execute()
        return sorted([str(r['job_no']).strip() for r in res.data if r.get('job_no')])
    except: return []

def get_material_groups():
    try:
        res = conn.table("material_master").select("material_group").execute()
        return sorted([str(r['material_group']) for r in res.data])
    except: return ["GENERAL"]

def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return sorted([r['name'] for r in res.data])
    except: return ["Admin", "Staff"]

# --- BRANDED HEADER ---
st.markdown('<div class="bg-header"><h1>B&G ENGINEERING</h1><p>MATERIAL COMMAND CENTER</p></div>', unsafe_allow_html=True)
st.markdown('<div class="blue-strip"></div>', unsafe_allow_html=True)

main_tabs = st.tabs(["📝 Indent Application", "🛒 Purchase Console", "📦 Stores GRN", "⚙️ Master Setup"])

# --- TAB 1: INDENT APPLICATION ---
with main_tabs[0]:
    st.subheader("📝 Material Indent & Tracking")
    raised_by = st.selectbox("Raised By", get_staff_list(), key="user_sel")
    
    if "indent_cart" not in st.session_state: st.session_state.indent_cart = []

    with st.expander("➕ Add Item to Draft", expanded=True):
        with st.form("indent_form", clear_on_submit=True):
            f1, f2 = st.columns(2)
            sel_jobs = f1.multiselect("Select Job Nos", get_jobs())
            m_grp = f2.selectbox("Material Group", get_material_groups())
            i_name = st.text_input("Item Name")
            i_specs = st.text_area("Specifications")
            c1, c2, c3 = st.columns(3)
            i_qty = c1.number_input("Qty", min_value=0.1)
            i_unit = c2.selectbox("Units", ["Nos", "Kgs", "Mts", "Sft", "Sets"])
            i_note = c3.text_input("Notes")
            
            if st.form_submit_button("Add to List"):
                if sel_jobs and i_name:
                    st.session_state.indent_cart.append({
                        "job_no": ", ".join(sel_jobs), "material_group": m_grp, "item_name": i_name.upper(),
                        "specs": i_specs, "quantity": i_qty, "units": i_unit, "special_notes": i_note,
                        "triggered_by": raised_by, "status": "Triggered", "is_urgent": False
                    })
                else: st.error("Job and Item Name required.")

    if st.session_state.indent_cart:
        st.dataframe(pd.DataFrame(st.session_state.indent_cart)[['job_no', 'item_name', 'quantity']], use_container_width=True)
        if st.button("🚀 FINAL SUBMIT INDENT", type="primary"):
            header = conn.table("indent_headers").insert({"raised_by": raised_by}).execute()
            new_id = header.data[0]['indent_no']
            for item in st.session_state.indent_cart:
                item['indent_no'] = new_id
                conn.table("purchase_orders").insert(item).execute()
            st.session_state.indent_cart = []; st.rerun()

    st.divider()
    # SEARCH & URGENT TRIGGER LOGIC
    job_list = ["ALL"] + get_jobs()
    search_j = st.selectbox("Filter History by Job Code", job_list)
    hist = conn.table("purchase_orders").select("*").neq("status", "Received").order("created_at", desc=True).execute()
    
    if hist.data:
        df_h = pd.DataFrame(hist.data)
        if search_j != "ALL": df_h = df_h[df_h['job_no'].str.contains(search_j, na=False)]
        
        for _, h_row in df_h.iterrows():
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                is_urg = h_row.get('is_urgent', False)
                urg_icon = "🚨" if is_urg else "📦"
                col1.write(f"**{urg_icon} {h_row['item_name']}** ({h_row['quantity']} {h_row['units']}) | Job: {h_row['job_no']}")
                if not is_urg:
                    if col2.button("🚨 TRIGGER", key=f"trig_{h_row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({"is_urgent": True}).eq("id", h_row['id']).execute()
                        st.rerun()

# --- TAB 2: PURCHASE CONSOLE (With WhatsApp, Email & Pro Export) ---
with main_tabs[1]:
    st.subheader("🛒 Purchase Processing")
    res_p = conn.table("purchase_orders").select("*").neq("status", "Received").neq("status", "Rejected").execute()
    
    if res_p.data:
        # Sort: Urgent items first, then by date
        df_p = pd.DataFrame(res_p.data).sort_values(by=['is_urgent', 'created_at'], ascending=[False, False])
        
        for _, p_row in df_p.iterrows():
            with st.container(border=True):
                h1, h2 = st.columns([3, 1.2])
                urgent_tag = "🚨 [URGENT]" if p_row.get('is_urgent') else ""
                
                with h1:
                    st.markdown(f"**{urgent_tag} Indent #{p_row.get('indent_no', 'N/A')}** | Job: {p_row['job_no']}")
                    st.markdown(f"**Item:** {p_row['item_name']} | Qty: {p_row['quantity']} {p_row.get('units', 'Nos')}")
                    st.caption(f"Specs: {p_row.get('specs', 'None')}")
                
                with h2:
                    # --- 1. WHATSAPP BUTTON ---
                    msg = f"B&G Enquiry:\nJob: {p_row['job_no']}\nItem: {p_row['item_name']}\nQty: {p_row['quantity']}\nSpecs: {p_row.get('specs')}"
                    wa_url = f"https://wa.me/?text={urllib.parse.quote(msg)}"
                    st.markdown(f"""
                        <a href="{wa_url}" target="_blank" style="text-decoration: none;">
                            <div style="background-color: #25D366; color: white; padding: 8px; border-radius: 5px; text-align: center; font-weight: bold; margin-bottom: 8px;">
                                📲 WhatsApp
                            </div>
                        </a>
                    """, unsafe_allow_html=True)

                    # --- 2. EMAIL ENQUIRY (Outlook Integration) ---
                    mail_subject = urllib.parse.quote(f"Material Enquiry: {p_row['item_name']} | Job: {p_row['job_no']}")
                    mail_body = urllib.parse.quote(
                        f"Dear Sir/Madam,\n\n"
                        f"Please find our official enquiry for the following material:\n\n"
                        f"Item: {p_row['item_name']}\n"
                        f"Job Code: {p_row['job_no']}\n"
                        f"Quantity: {p_row['quantity']} {p_row.get('units')}\n"
                        f"Specifications: {p_row.get('specs')}\n\n"
                        f"Please provide your best quote and earliest lead time.\n\n"
                        f"Regards,\n"
                        f"B&G Engineering - Procurement"
                    )
                    mail_url = f"mailto:?subject={mail_subject}&body={mail_body}"
                    
                    st.markdown(f"""
                        <a href="{mail_url}" style="text-decoration: none;">
                            <div style="background-color: #007bff; color: white; padding: 8px; border-radius: 5px; text-align: center; font-weight: bold; margin-bottom: 8px;">
                                📧 Email Enquiry
                            </div>
                        </a>
                    """, unsafe_allow_html=True)
                    
                    # --- 3. PRO EXCEL FORMATTED EXPORT ---
                    html_form = f"""
                    <html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40">
                    <head><meta charset="utf-8"></head>
                    <body>
                        <table>
                            <tr><td colspan="2" style="font-size: 18pt; font-weight: bold; color: #003366; font-family: Arial;">B&G ENGINEERING</td></tr>
                            <tr><td colspan="2" style="color: #666666; font-family: Arial;">Paletipadu, Andhra Pradesh | Material Procurement Hub</td></tr>
                            <tr><td>&nbsp;</td></tr>
                            <tr><td style="font-weight: bold; width: 160pt; font-family: Arial; border-bottom: 1px solid #007bff;">DOCUMENT:</td><td style="font-weight: bold; color: #007bff; font-family: Arial; border-bottom: 1px solid #007bff;">OFFICIAL MATERIAL ENQUIRY</td></tr>
                            <tr><td style="font-family: Arial;">DATE:</td><td style="font-family: Arial;">{date.today().strftime('%d-%m-%Y')}</td></tr>
                            <tr><td>&nbsp;</td></tr>
                            <tr style="background-color: #f2f2f2;"><td colspan="2" style="font-weight: bold; font-family: Arial; border: 1px solid #ccc;">REFERENCE DETAILS</td></tr>
                            <tr><td style="font-family: Arial;">Indent Number:</td><td style="font-family: Arial;">{p_row.get('indent_no', 'N/A')}</td></tr>
                            <tr><td style="font-family: Arial;">Job Code:</td><td style="font-family: Arial; font-weight: bold;">{p_row['job_no']}</td></tr>
                            <tr><td style="font-family: Arial;">Urgency Level:</td><td style="font-family: Arial; color: {"#ff0000" if p_row.get('is_urgent') else "#000"};">{"URGENT / CRITICAL" if p_row.get('is_urgent') else "Normal"}</td></tr>
                            <tr><td>&nbsp;</td></tr>
                            <tr style="background-color: #f2f2f2;"><td colspan="2" style="font-weight: bold; font-family: Arial; border: 1px solid #ccc;">TECHNICAL SPECIFICATIONS</td></tr>
                            <tr><td style="font-family: Arial;">Item Description:</td><td style="font-family: Arial; font-weight: bold;">{p_row['item_name']}</td></tr>
                            <tr><td style="font-family: Arial;">Technical Specs:</td><td style="font-family: Arial;">{p_row.get('specs', '-')}</td></tr>
                            <tr><td style="font-family: Arial;">Required Quantity:</td><td style="font-family: Arial; font-weight: bold;">{p_row['quantity']} {p_row.get('units', 'Nos')}</td></tr>
                            <tr><td style="font-family: Arial;">Special Notes:</td><td style="font-family: Arial; font-style: italic;">{p_row.get('special_notes', '-')}</td></tr>
                            <tr><td>&nbsp;</td></tr>
                            <tr style="background-color: #f2f2f2;"><td colspan="2" style="font-weight: bold; font-family: Arial; border: 1px solid #ccc;">CLOSING REMARKS</td></tr>
                            <tr><td colspan="2" style="font-family: Arial;">Please submit your commercial quote with earliest possible lead time.</td></tr>
                            <tr><td>&nbsp;</td></tr>
                            <tr><td style="font-weight: bold; font-family: Arial;">Authorized By:</td><td style="font-family: Arial;">B&G Procurement Hub</td></tr>
                        </table>
                    </body>
                    </html>
                    """
                    
                    st.download_button(
                        label="📄 Export Pro Enquiry",
                        data=html_form,
                        file_name=f"BG_Enquiry_{p_row['job_no']}.xls",
                        mime='application/vnd.ms-excel',
                        key=f"dl_pro_{p_row['id']}",
                        use_container_width=True
                    )

                with st.expander("🛠️ Finalize Purchase Order"):
                    c1, c2 = st.columns(2)
                    p_no = c1.text_input("PO No", key=f"po_{p_row['id']}")
                    p_rem = c2.text_input("Vendor / Remarks", key=f"rem_{p_row['id']}")
                    
                    if st.button("✅ Confirm Order", key=f"ok_{p_row['id']}", type="primary", use_container_width=True):
                        conn.table("purchase_orders").update({
                            "status": "Ordered", 
                            "po_no": p_no, 
                            "purchase_reply": p_rem
                        }).eq("id", p_row['id']).execute()
                        st.success(f"Order {p_no} Recorded!")
                        st.rerun()
    else: 
        st.info("No pending purchase requests found.")
# --- TAB 3: STORES GRN (The Logistics Desk) ---
with main_tabs[2]:
    st.subheader("📦 Goods Receipt Note (GRN) Desk")
    
    # 1. Store Search & Filter
    s_search_col, s_stat_col = st.columns([2, 1])
    po_search = s_search_col.text_input("🔍 Search by PO Number or Item", placeholder="e.g. PO-2024-001", key="grn_search")
    
    # Fetch only items that are 'Ordered' (In-Transit)
    # Added a filter to only show items from the Command Center (where indent_no is not null)
    res_s = conn.table("purchase_orders").select("*").eq("status", "Ordered").not_.is_("indent_no", "null").execute()
    
    if res_s.data:
        df_s = pd.DataFrame(res_s.data)
        
        # Apply Search Filter
        if po_search:
            # FIX: Changed df_h to df_s to prevent the search crash
            df_s = df_s[
                df_s['po_no'].str.contains(po_search, case=False, na=False) | 
                df_s['item_name'].str.contains(po_search, case=False, na=False)
            ]

        # 2. Receipt Queue
        st.markdown(f"**Items Pending Arrival ({len(df_s)})**")
        
        for _, s_row in df_s.iterrows():
            # Create a unique key using the database ID
            row_id = s_row['id']
            
            with st.container(border=True):
                # Layout for the "Cargo Card"
                c_info, c_status, c_action = st.columns([3, 1, 1])
                
                with c_info:
                    st.markdown(f"#### PO: {s_row.get('po_no', 'N/A')}")
                    st.markdown(f"**{s_row['item_name']}** | Job: `{s_row['job_no']}`")
                    st.caption(f"Supplier Note: {s_row.get('purchase_reply', 'Standard Order')}")
                
                with c_status:
                    # Visual Indicator of Progress
                    st.write("🚚 **In-Transit**")
                    st.progress(66) 
                    st.caption(f"Qty: {s_row['quantity']} {s_row.get('units')}")

                with c_action:
                    # FIX: Added a unique 'key' to the popover to ensure it remains selectable
                    if st.popover("📥 Log Receipt", use_container_width=True, key=f"popover_{row_id}"):
                        st.markdown("### GRN Entry Form")
                        with st.form(key=f"grn_form_{row_id}", clear_on_submit=True):
                            g1, g2 = st.columns(2)
                            rec_date = g1.date_input("Arrival Date", value=date.today())
                            veh_no = g2.text_input("Vehicle / DC Number", placeholder="e.g. AP 31 XX 1234")
                            
                            condition = st.select_slider(
                                "Material Condition",
                                options=["Damaged", "Partial", "Good", "Excellent"],
                                value="Good",
                                key=f"slider_{row_id}"
                            )
                            
                            store_remarks = st.text_area("Storekeeper Remarks", placeholder="Any shortage or remarks...")
                            
                            if st.form_submit_button("✅ Finalize GRN & Update Stock", use_container_width=True):
                                update_payload = {
                                    "status": "Received",
                                    "received_date": str(rec_date),
                                    "stores_remarks": f"Veh: {veh_no} | Cond: {condition} | {store_remarks}"
                                }
                                try:
                                    conn.table("purchase_orders").update(update_payload).eq("id", row_id).execute()
                                    st.success(f"GRN Created for {s_row['item_name']}!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error updating stores: {e}")
    else:
        st.info("🚚 No pending arrivals from the Command Center.")

    # 3. Quick View: Recently Received (Filtered for Command Center only)
    with st.expander("🕒 View Recently Received Materials (Last 5)"):
        recent_res = conn.table("purchase_orders").select("*").eq("status", "Received").not_.is_("indent_no", "null").order("received_date", desc=True).limit(5).execute()
        if recent_res.data:
            st.table(pd.DataFrame(recent_res.data)[['received_date', 'po_no', 'item_name', 'quantity']])
# --- TAB 4: MASTER SETUP ---
with main_tabs[3]:
    st.subheader("⚙️ Configuration")
    m1, m2 = st.columns(2)
    with m1:
        with st.form("m_grp_form", clear_on_submit=True):
            new_g = st.text_input("New Material Group")
            if st.form_submit_button("➕ Save Group"):
                if new_g: conn.table("material_master").insert({"material_group": new_g.upper()}).execute()
                st.rerun()
    with m2:
        grps = conn.table("material_master").select("*").execute().data
        if grps: st.dataframe(pd.DataFrame(grps)[['material_group']], hide_index=True)
