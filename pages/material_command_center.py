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

# --- TAB 2: PURCHASE CONSOLE (Enhanced Excel-Friendly Export) ---
with main_tabs[1]:
    st.subheader("🛒 Purchase processing")
    res_p = conn.table("purchase_orders").select("*").neq("status", "Received").neq("status", "Rejected").execute()
    
    if res_p.data:
        df_p = pd.DataFrame(res_p.data).sort_values(by=['is_urgent', 'created_at'], ascending=[False, False])
        for _, p_row in df_p.iterrows():
            with st.container(border=True):
                h1, h2 = st.columns([3, 1.2])
                urgent_tag = "🚨 [URGENT]" if p_row.get('is_urgent') else ""
                
                with h1:
                    st.markdown(f"**{urgent_tag} Indent #{p_row.get('indent_no')}** | Job: {p_row['job_no']}")
                    st.markdown(f"**Item:** {p_row['item_name']} | Qty: {p_row['quantity']} {p_row.get('units', 'Nos')}")
                    st.caption(f"Specs: {p_row.get('specs', 'None')}")
                
                with h2:
                    # WhatsApp Button remains the same
                    msg = f"B&G Enquiry:\nJob: {p_row['job_no']}\nItem: {p_row['item_name']}\nQty: {p_row['quantity']}\nSpecs: {p_row.get('specs')}"
                    wa_url = f"https://wa.me/?text={urllib.parse.quote(msg)}"
                    st.markdown(f"""<a href="{wa_url}" target="_blank" style="text-decoration: none;">
                        <div style="background-color: #25D366; color: white; padding: 8px; border-radius: 5px; text-align: center; font-weight: bold; margin-bottom: 8px;">📲 WhatsApp</div>
                        </a>""", unsafe_allow_html=True)
                    
                    # --- IMPROVED EXCEL-FRIENDLY EXPORT ---
                    # Structuring as a Formal Letter/Table
                    excel_form = [
                        ["COMPANY:", "B&G ENGINEERING"],
                        ["LOCATION:", "Paletipadu, Andhra Pradesh"],
                        ["DOCUMENT:", "OFFICIAL MATERIAL ENQUIRY"],
                        ["DATE:", date.today().strftime('%d-%m-%Y')],
                        [""], # Spacer
                        ["REFERENCE DETAILS", ""],
                        ["------------------", "------------------"],
                        ["Indent Number:", p_row.get('indent_no')],
                        ["Job Code:", p_row['job_no']],
                        ["Urgency Level:", "URGENT / CRITICAL" if p_row.get('is_urgent') else "Normal"],
                        [""], # Spacer
                        ["TECHNICAL SPECIFICATIONS", ""],
                        ["------------------", "------------------"],
                        ["Item Description:", p_row['item_name']],
                        ["Technical Specs:", p_row.get('specs')],
                        ["Required Quantity:", f"{p_row['quantity']} {p_row.get('units')}"],
                        ["Engineer Notes:", p_row.get('special_notes', '-')],
                        [""], # Spacer
                        ["CLOSING REMARKS", ""],
                        ["------------------", "------------------"],
                        ["Note:", "Please submit your commercial quote with lead time."],
                        ["Authorized By:", "B&G Procurement Hub"]
                    ]
                    
                    # Convert to DataFrame
                    df_excel = pd.DataFrame(excel_form)
                    csv_excel = df_excel.to_csv(index=False, header=False).encode('utf-8')
                    
                    st.download_button(
                        label="📄 Export Enquiry Form",
                        data=csv_excel,
                        file_name=f"BG_Enquiry_{p_row['job_no']}.csv",
                        mime='text/csv',
                        key=f"dl_excel_{p_row['id']}",
                        use_container_width=True
                    )

                with st.expander("🛠️ Finalize Purchase Order"):
                    c1, c2 = st.columns(2)
                    p_no = c1.text_input("PO No", key=f"po_{p_row['id']}")
                    p_rem = c2.text_input("Vendor / Remarks", key=f"rem_{p_row['id']}")
                    if st.button("✅ Confirm Order", key=f"ok_{p_row['id']}", type="primary", use_container_width=True):
                        conn.table("purchase_orders").update({
                            "status": "Ordered", "po_no": p_no, "purchase_reply": p_rem
                        }).eq("id", p_row['id']).execute()
                        st.rerun()

# --- TAB 3: STORES GRN ---
with main_tabs[2]:
    st.subheader("📦 Stores Management")
    res_s = conn.table("purchase_orders").select("*").eq("status", "Ordered").execute()
    if res_s.data:
        for s_row in res_s.data:
            with st.container(border=True):
                sc1, sc2 = st.columns([3, 1])
                sc1.write(f"**PO:** {s_row.get('po_no')} | **Item:** {s_row['item_name']} ({s_row['quantity']})")
                if sc2.popover("📥 Log Receipt"):
                    rdt = st.date_input("Date", value=date.today(), key=f"rdt_{s_row['id']}")
                    if st.button("Confirm", key=f"sbtn_{s_row['id']}", type="primary"):
                        conn.table("purchase_orders").update({"status": "Received", "received_date": str(rdt)}).eq("id", s_row['id']).execute()
                        st.rerun()
    else: st.info("No items in transit.")

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
