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
    
    # 1. Initialize session states
    if "rev_data" not in st.session_state: st.session_state.rev_data = None
    if "indent_cart" not in st.session_state: st.session_state.indent_cart = []

    raised_by = st.selectbox("Raised By", get_staff_list(), key="user_sel")
    
    # 2. PART A: THE ENTRY FORM
    with st.expander("➕ Add Item to Draft", expanded=True if not st.session_state.indent_cart else False):
        # FIX: Explicitly check for 'is not None' to avoid Pandas ValueError
        rd = st.session_state.rev_data if st.session_state.rev_data is not None else {}
        
        if st.session_state.rev_data is not None:
            st.info(f"🔧 Currently Editing/Revising: {rd.get('item_name', 'Item')}")

        with st.form("indent_form", clear_on_submit=True):
            f1, f2 = st.columns(2)
            
            # Pre-select jobs
            def_jobs = rd.get('job_no', "").split(", ") if rd.get('job_no') else []
            sel_jobs = f1.multiselect("Select Job Nos", get_jobs(), default=[j for j in def_jobs if j in get_jobs()])
            
            m_list = get_material_groups()
            try:
                def_m_idx = m_list.index(rd['material_group']) if 'material_group' in rd else 0
            except:
                def_m_idx = 0
            m_grp = f2.selectbox("Material Group", m_list, index=def_m_idx)
            
            i_name = st.text_input("Item Name", value=rd.get('item_name', ""))
            i_specs = st.text_area("Specifications", value=rd.get('specs', ""))
            
            c1, c2, c3 = st.columns(3)
            try:
                curr_qty = float(rd.get('quantity', 0.1))
            except:
                curr_qty = 0.1
                
            i_qty = c1.number_input("Qty", min_value=0.1, value=curr_qty)
            
            u_list = ["Nos", "Kgs", "Mts", "Sft", "Sets"]
            try:
                def_u_idx = u_list.index(rd['units']) if 'units' in rd else 0
            except:
                def_u_idx = 0
            i_unit = c2.selectbox("Units", u_list, index=def_u_idx)
            
            i_note = st.text_input("Notes", value=rd.get('special_notes', ""))
            
            f_btn1, f_btn2 = st.columns([1, 4])
            submit_item = f_btn2.form_submit_button("✅ Add Item to List", use_container_width=True)
            cancel_edit = f_btn1.form_submit_button("❌ Cancel")

            if cancel_edit:
                st.session_state.rev_data = None
                st.rerun()

            if submit_item:
                if sel_jobs and i_name:
                    st.session_state.indent_cart.append({
                        "job_no": ", ".join(sel_jobs), "material_group": m_grp, "item_name": i_name.upper(),
                        "specs": i_specs, "quantity": i_qty, "units": i_unit, "special_notes": i_note,
                        "triggered_by": raised_by, "status": "Triggered", "is_urgent": rd.get('is_urgent', False)
                    })
                    st.session_state.rev_data = None 
                    st.rerun()
                else:
                    st.error("Job and Item Name required.")

    # 3. PART B: DRAFT LIST (Items not yet submitted to DB)
    if st.session_state.indent_cart:
        st.markdown("### 🛒 Current Draft List")
        for idx, item in enumerate(st.session_state.indent_cart):
            with st.container(border=True):
                d1, d2 = st.columns([5, 1])
                d1.write(f"**{item['item_name']}** | {item['quantity']} {item['units']} | {item['job_no']}")
                if d2.button("🗑️", key=f"del_draft_{idx}"):
                    st.session_state.indent_cart.pop(idx)
                    st.rerun()

        if st.button("🚀 FINAL SUBMIT INDENT", type="primary", use_container_width=True):
            try:
                header = conn.table("indent_headers").insert({"raised_by": raised_by}).execute()
                new_id = header.data[0]['indent_no']
                for item in st.session_state.indent_cart:
                    item['indent_no'] = new_id
                    conn.table("purchase_orders").insert(item).execute()
                st.session_state.indent_cart = []
                st.success("Indent Submitted Successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Submission Error: {e}")

    st.divider()
    
    # 4. PART C: HISTORY, TRIGGER & EDIT/REVISE
    st.subheader("🔍 Tracking & Adjustments")
    search_j = st.selectbox("Filter History by Job", ["ALL"] + get_jobs())
    
    # Pulling history (Limited to 30 for performance)
    hist = conn.table("purchase_orders").select("*").order("created_at", desc=True).limit(30).execute()
    
    if hist.data:
        df_h = pd.DataFrame(hist.data)
        if search_j != "ALL": 
            df_h = df_h[df_h['job_no'].str.contains(search_j, na=False)]
        
        for _, h_row in df_h.iterrows():
            row_id = h_row['id']
            status = h_row['status']
            is_urg = h_row.get('is_urgent', False)
            
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                
                # Info Display
                urg_icon = "🚨" if is_urg else "📦"
                col1.write(f"**{urg_icon} {h_row['item_name']}** | Status: `{status}`")
                col1.caption(f"Job: {h_row['job_no']} | Qty: {h_row['quantity']} {h_row['units']}")
                
                # Logic 1: REVISE (For Rejected Items)
                if status == "Rejected":
                    col1.error(f"Reason: {h_row.get('reject_note', 'No details')}")
                    if col2.button("📝 REVISE", key=f"rev_{row_id}", use_container_width=True):
                        st.session_state.rev_data = h_row
                        st.rerun()

                # Logic 2: EDIT/DELETE/TRIGGER (For Pending Items)
                if status == "Triggered":
                    # EDIT: Pulls back to form and deletes old record
                    if col2.button("✏️ EDIT", key=f"edit_{row_id}", use_container_width=True):
                        st.session_state.rev_data = h_row
                        conn.table("purchase_orders").delete().eq("id", row_id).execute()
                        st.rerun()
                    
                    # TRIGGER: Flag as urgent
                    if not is_urg:
                        if col3.button("🚨", key=f"trig_{row_id}", help="Trigger Urgent"):
                            conn.table("purchase_orders").update({"is_urgent": True}).eq("id", row_id).execute()
                            st.rerun()
                    else:
                        col3.info("Priority")
                    
                    # DELETE: Remove completely
                    if col4.button("🗑️", key=f"del_db_{row_id}", help="Delete Entry"):
                        conn.table("purchase_orders").delete().eq("id", row_id).execute()
                        st.rerun()
                
                # Logic 3: Read-only for Ordered/Received
                if status in ["Ordered", "Received"]:
                    col2.write("✅ Active")
# --- TAB 2: PURCHASE CONSOLE (With WhatsApp, Email, Pro Export & Vendor Linking) ---
with main_tabs[1]:
    st.subheader("🛒 Purchase Processing")
    
    # 1. Load Vendors for selection
    res_v = conn.table("master_vendors").select("name, phone_number, email").order("name").execute()
    vendor_options = {v['name']: v for v in res_v.data} if res_v.data else {}
    
    # 2. Pull pending items
    res_p = conn.table("purchase_orders").select("*").neq("status", "Received").neq("status", "Rejected").execute()
    
    if res_p.data:
        df_p = pd.DataFrame(res_p.data).sort_values(by=['is_urgent', 'created_at'], ascending=[False, False])
        
        for _, p_row in df_p.iterrows():
            row_id = p_row['id']
            with st.container(border=True):
                h1, h2 = st.columns([3, 1.2])
                urgent_tag = "🚨 [URGENT]" if p_row.get('is_urgent') else ""
                
                with h1:
                    st.markdown(f"**{urgent_tag} Indent #{p_row.get('indent_no', 'N/A')}** | Job: {p_row['job_no']}")
                    st.markdown(f"**Item:** {p_row['item_name']} | Qty: {p_row['quantity']} {p_row.get('units', 'Nos')}")
                    st.caption(f"Specs: {p_row.get('specs', 'None')}")
                    
                    # VENDOR SELECTION
                    selected_vendor_name = st.selectbox(
                        "Select Vendor for Enquiry", 
                        options=["--- Choose Vendor ---"] + list(vendor_options.keys()),
                        key=f"v_sel_{row_id}"
                    )
                    v_info = vendor_options.get(selected_vendor_name, {})

                with h2:
                    # --- 1. DYNAMIC WHATSAPP BUTTON ---
                    msg = f"B&G Enquiry:\nJob: {p_row['job_no']}\nItem: {p_row['item_name']}\nQty: {p_row['quantity']}\nSpecs: {p_row.get('specs')}"
                    
                    # Logic: If vendor has a phone number, use it; otherwise open general WA
                    v_phone = v_info.get('phone_number', "").strip()
                    wa_base = f"https://wa.me/{v_phone}" if v_phone else "https://wa.me/"
                    wa_url = f"{wa_base}?text={urllib.parse.quote(msg)}"
                    
                    st.markdown(f"""<a href="{wa_url}" target="_blank" style="text-decoration: none;">
                        <div style="background-color: #25D366; color: white; padding: 8px; border-radius: 5px; text-align: center; font-weight: bold; margin-bottom: 8px;">📲 WhatsApp</div>
                        </a>""", unsafe_allow_html=True)

                    # --- 2. DYNAMIC EMAIL ENQUIRY ---
                    v_email = v_info.get('email', "")
                    mail_subject = urllib.parse.quote(f"Material Enquiry: {p_row['item_name']} | Job: {p_row['job_no']}")
                    mail_body = urllib.parse.quote(f"Dear Sir/Madam,\n\nPlease find our enquiry for {p_row['item_name']} (Job: {p_row['job_no']}).\nQty: {p_row['quantity']}\nSpecs: {p_row.get('specs')}\n\nRegards,\nB&G Engineering")
                    mail_url = f"mailto:{v_email}?subject={mail_subject}&body={mail_body}"
                    
                    st.markdown(f"""<a href="{mail_url}" style="text-decoration: none;">
                        <div style="background-color: #007bff; color: white; padding: 8px; border-radius: 5px; text-align: center; font-weight: bold; margin-bottom: 8px;">📧 Email Enquiry</div>
                        </a>""", unsafe_allow_html=True)
                    
                    # --- 3. PRO EXCEL EXPORT ---
                    html_form = f"""
                    <html><body><table>
                    <tr><td colspan="2" style="font-size: 18pt; font-weight: bold; color: #003366;">B&G ENGINEERING</td></tr>
                    <tr><td>DATE:</td><td>{date.today().strftime('%d-%m-%Y')}</td></tr>
                    <tr style="background-color: #f2f2f2;"><td colspan="2" style="font-weight: bold;">TECHNICAL SPECIFICATIONS</td></tr>
                    <tr><td>Item:</td><td><b>{p_row['item_name']}</b></td></tr>
                    <tr><td>Specs:</td><td>{p_row.get('specs', '-')}</td></tr>
                    <tr><td>Qty:</td><td><b>{p_row['quantity']} {p_row.get('units')}</b></td></tr>
                    </table></body></html>
                    """
                    st.download_button(label="📄 Export Pro Enquiry", data=html_form, file_name=f"BG_{p_row['job_no']}.xls", mime='application/vnd.ms-excel', key=f"dl_{row_id}", use_container_width=True)

                # --- ACTION AREA ---
                c1, c2 = st.columns(2)
                with c1.expander("✅ Finalize Purchase Order"):
                    p_no = st.text_input("PO No", key=f"po_{row_id}")
                    # Use selected vendor as default remark
                    p_rem = st.text_input("Vendor / Remarks", value=selected_vendor_name if selected_vendor_name != "--- Choose Vendor ---" else "", key=f"rem_{row_id}")
                    if st.button("Confirm Order", key=f"ok_{row_id}", type="primary", use_container_width=True):
                        conn.table("purchase_orders").update({"status": "Ordered", "po_no": p_no, "purchase_reply": p_rem}).eq("id", row_id).execute()
                        st.rerun()
                
                with c2.expander("🚫 Reject Indent"):
                    rejection_reason = st.text_area("Reason for Rejection", key=f"rej_res_{row_id}")
                    if st.button("Confirm Rejection", key=f"rej_btn_{row_id}", type="secondary", use_container_width=True):
                        if rejection_reason:
                            conn.table("purchase_orders").update({"status": "Rejected", "reject_note": rejection_reason}).eq("id", row_id).execute()
                            st.rerun()
                        else: st.warning("Please provide a reason.")
    else: 
        st.info("No pending purchase requests found.")
# --- TAB 3: STORES GRN (The Logistics Desk) ---
with main_tabs[2]:
    st.subheader("📦 Goods Receipt Note (GRN) Desk")
    
    # 1. Store Search & Filter
    s_search_col, s_stat_col = st.columns([2, 1])
    po_search = s_search_col.text_input("🔍 Search by PO or Item", placeholder="e.g. PO-107", key="grn_search")
    
    # Fetch only active Command Center orders
    res_s = conn.table("purchase_orders").select("*").eq("status", "Ordered").not_.is_("indent_no", "null").execute()
    
    if res_s.data:
        df_s = pd.DataFrame(res_s.data)
        if po_search:
            df_s = df_s[
                df_s['po_no'].str.contains(po_search, case=False, na=False) | 
                df_s['item_name'].str.contains(po_search, case=False, na=False)
            ]

        st.markdown(f"**Items Pending Arrival ({len(df_s)})**")
        
        for _, s_row in df_s.iterrows():
            row_id = s_row['id']
            
            with st.container(border=True):
                c_info, c_status, c_action = st.columns([2.5, 1, 1.5])
                
                with c_info:
                    st.markdown(f"#### PO: {s_row.get('po_no', 'N/A')}")
                    st.markdown(f"**{s_row['item_name']}** | Job: `{s_row['job_no']}`")
                    st.caption(f"Indent Ref: #{s_row.get('indent_no')} | Vendor Note: {s_row.get('purchase_reply', '-')}")
                
                with c_status:
                    st.write("🚚 **In-Transit**")
                    st.caption(f"Qty: {s_row['quantity']} {s_row.get('units')}")
                    st.progress(66)

                with c_action:
                    # Added DC No and Remarks fields
                    dc_no = st.text_input("DC / Vehicle No", key=f"dc_{row_id}", placeholder="DC-123")
                    s_rem = st.text_input("Stores Remarks", key=f"srem_{row_id}", placeholder="Shortage/Damage?")
                    
                    if st.button("✅ Confirm Receipt", key=f"btn_{row_id}", use_container_width=True, type="primary"):
                        if dc_no:
                            update_payload = {
                                "status": "Received",
                                "received_date": str(date.today()),
                                "stores_remarks": f"DC: {dc_no} | Note: {s_rem}"
                            }
                            try:
                                conn.table("purchase_orders").update(update_payload).eq("id", row_id).execute()
                                st.success(f"GRN recorded for {s_row['item_name']}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                        else:
                            st.warning("Please enter DC/Vehicle No")
    else:
        st.info("🚚 No pending arrivals.")

    # 3. Audit Trail with Remarks Column
    st.divider()
    with st.expander("🕒 View Recently Received (Showing Stores Remarks)"):
        recent_res = conn.table("purchase_orders").select("*").eq("status", "Received").not_.is_("indent_no", "null").order("received_date", desc=True).limit(5).execute()
        if recent_res.data:
            df_recent = pd.DataFrame(recent_res.data)
            # Displaying the remarks in the history table
            st.dataframe(df_recent[['received_date', 'po_no', 'item_name', 'quantity', 'job_no', 'stores_remarks']], 
                         use_container_width=True, hide_index=True)
# --- TAB 4: MASTER SETUP ---
with main_tabs[3]:
    st.subheader("⚙️ System Configuration & Master Data")
    
    # Using three columns for a cleaner layout
    col_grp, col_vend_form, col_vend_list = st.columns([1, 1.5, 2])

    # --- SECTION 1: MATERIAL GROUPS ---
    with col_grp:
        st.markdown("#### 📦 Material Groups")
        with st.form("m_grp_form", clear_on_submit=True):
            new_g = st.text_input("New Group Name")
            if st.form_submit_button("➕ Save Group") and new_g:
                conn.table("material_master").insert({"material_group": new_g.upper()}).execute()
                st.rerun()
        
        # Display existing groups
        grps = conn.table("material_master").select("*").execute().data
        if grps:
            st.dataframe(pd.DataFrame(grps)[['material_group']], hide_index=True, use_container_width=True)

    # --- SECTION 2: VENDOR MASTER ENTRY ---
    with col_vend_form:
        st.markdown("#### 🤝 Add New Vendor")
        with st.form("vendor_entry_form", clear_on_submit=True):
            v_name = st.text_input("Vendor Company Name*")
            v_cat = st.selectbox("Category", ["Steel", "Hardware", "Electrical", "Consumables", "Services", "General"])
            v_phone = st.text_input("WhatsApp (91xxxxxxxxxx)", help="Important: Include 91, no spaces.")
            v_email = st.text_input("Official Email")
            
            if st.form_submit_button("💾 Save Vendor Details"):
                if v_name:
                    v_payload = {
                        "name": v_name.strip().upper(),
                        "category": v_cat,
                        "phone_number": v_phone.strip(),
                        "email": v_email.strip().lower()
                    }
                    try:
                        conn.table("master_vendors").insert(v_payload).execute()
                        st.success(f"Vendor {v_name} Added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
                else:
                    st.warning("Company Name is required.")

    # --- SECTION 3: VENDOR DIRECTORY ---
    with col_vend_list:
        st.markdown("#### 🔍 Vendor Directory")
        v_search = st.text_input("Search Vendors...", placeholder="Type name or category")
        
        # Fetching Vendors
        res_v = conn.table("master_vendors").select("*").order("name").execute()
        if res_v.data:
            df_v = pd.DataFrame(res_v.data)
            if v_search:
                df_v = df_v[df_v['name'].str.contains(v_search, case=False, na=False) | 
                            df_v['category'].str.contains(v_search, case=False, na=False)]
            
            # Displaying Vendors in a clean, scrollable dataframe or list
            for _, v_row in df_v.iterrows():
                with st.container(border=True):
                    v_c1, v_c2 = st.columns([4, 1])
                    v_c1.write(f"**{v_row['name']}** ({v_row['category']})")
                    v_c1.caption(f"📞 {v_row.get('phone_number', 'N/A')} | 📧 {v_row.get('email', 'N/A')}")
                    
                    if v_c2.button("🗑️", key=f"del_v_{v_row['id']}"):
                        conn.table("master_vendors").delete().eq("id", v_row['id']).execute()
                        st.rerun()
        else:
            st.info("No vendors registered yet.")
