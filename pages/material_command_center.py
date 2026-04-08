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
    .summary-box { background-color: #f0f7ff; padding: 12px; border-radius: 10px; border-left: 5px solid #003366; }
    .urgent-row { background-color: #fff5f5; border: 1px solid #ff0000; border-radius: 5px; padding: 10px; margin-bottom: 5px; }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
def get_jobs():
    res = conn.table("anchor_projects").select("job_no").execute()
    return sorted([str(r['job_no']).strip() for r in res.data if r.get('job_no')])

def get_material_groups():
    res = conn.table("material_master").select("material_group").execute()
    return sorted([str(r['material_group']) for r in res.data]) if res.data else ["GENERAL"]

def get_staff_list():
    res = conn.table("master_staff").select("name").execute()
    return sorted([r['name'] for r in res.data]) if res.data else ["Admin"]

# --- BRANDED HEADER ---
st.markdown('<div class="bg-header"><h1>B&G ENGINEERING</h1><p>MATERIAL COMMAND CENTER</p></div>', unsafe_allow_html=True)
st.markdown('<div class="blue-strip"></div>', unsafe_allow_html=True)

main_tabs = st.tabs(["📝 Indent Application", "🛒 Purchase Console", "📦 Stores GRN", "⚙️ Master Setup"])

# --- TAB 1: INDENT APPLICATION ---
with main_tabs[0]:
    st.subheader("📝 Raise Material Indent")
    raised_by_name = st.selectbox("Identify Yourself", get_staff_list())
    
    if "indent_cart" not in st.session_state:
        st.session_state.indent_cart = []

    # PART A: SIMPLE ENTRY (No Trigger here)
    with st.expander("➕ Add Item to List", expanded=True):
        with st.form("indent_form", clear_on_submit=True):
            f1, f2 = st.columns(2)
            selected_jobs = f1.multiselect("Select Job Nos", get_jobs())
            mat_group = f2.selectbox("Material Group", get_material_groups())
            
            i_desc = st.text_input("Item Name")
            i_specs = st.text_area("Specifications")
            
            c1, c2, c3 = st.columns(3)
            i_qty = c1.number_input("Quantity", min_value=0.1)
            i_unit = c2.selectbox("Units", ["Nos", "Kgs", "Mts", "Sft", "Sets"])
            i_notes = c3.text_input("Notes")
            
            if st.form_submit_button("Add to Draft"):
                if selected_jobs and i_desc:
                    st.session_state.indent_cart.append({
                        "job_no": ", ".join(selected_jobs),
                        "material_group": mat_group,
                        "item_name": i_desc.upper(),
                        "specs": i_specs,
                        "quantity": i_qty,
                        "units": i_unit,
                        "special_notes": i_notes,
                        "triggered_by": raised_by_name,
                        "status": "Triggered",
                        "is_urgent": False # Default to false
                    })
                else: st.error("Fill mandatory fields")

    # PART B: SUBMIT
    if st.session_state.indent_cart:
        st.dataframe(pd.DataFrame(st.session_state.indent_cart)[['job_no', 'item_name', 'quantity']], use_container_width=True)
        if st.button("🚀 FINAL SUBMIT INDENT", type="primary"):
            header = conn.table("indent_headers").insert({"raised_by": raised_by_name}).execute()
            new_id = header.data[0]['indent_no']
            for item in st.session_state.indent_cart:
                item['indent_no'] = new_id
                conn.table("purchase_orders").insert(item).execute()
            st.session_state.indent_cart = []; st.rerun()

    # PART C: HISTORY & LATE TRIGGER LOGIC
    st.divider()
    st.subheader("🔍 Tracking & Urgent Triggers")
    
    job_list = ["ALL"] + get_jobs()
    search_j = st.selectbox("Filter by Job Code", job_list)
    
    hist_res = conn.table("purchase_orders").select("*").neq("status", "Received").order("created_at", desc=True).execute()
    
    if hist_res.data:
        df_h = pd.DataFrame(hist_res.data)
        if search_j != "ALL":
            df_h = df_h[df_h['job_no'].str.contains(search_j, na=False)]
        
        # Displaying items with a "Trigger" button for each
        for _, h_row in df_h.iterrows():
            with st.container(border=True):
                col1, col2, col3 = st.columns([3, 1, 1])
                
                # Column 1: Info
                is_urg = h_row.get('is_urgent', False)
                urg_prefix = "🚨 [URGENT] " if is_urg else ""
                col1.write(f"**{urg_prefix}{h_row['item_name']}** ({h_row['quantity']} {h_row['units']})")
                col1.caption(f"Job: {h_row['job_no']} | Status: {h_row['status']}")
                
                # Column 2: The Trigger Button (Only if not already urgent)
                if not is_urg:
                    if col2.button("🚨 TRIGGER URGENT", key=f"trig_{h_row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({"is_urgent": True}).eq("id", h_row['id']).execute()
                        st.toast(f"Triggered {h_row['item_name']} as Urgent!")
                        st.rerun()
                else:
                    col2.info("High Priority")

                # Column 3: Export single item
                csv_single = pd.DataFrame([h_row]).to_csv(index=False).encode('utf-8')
                col3.download_button("📥 Export", data=csv_single, file_name=f"Indent_{h_row['id']}.csv", key=f"dl_{h_row['id']}")

# --- TAB 2: PURCHASE CONSOLE (Same as before, prioritizing Urgent) ---
with main_tabs[1]:
    st.subheader("🛒 Purchase Console")
    # Same sorting logic applies: Urgent items will always show at the top
    res_p = conn.table("purchase_orders").select("*").neq("status", "Received").neq("status", "Rejected").execute()
    if res_p.data:
        df_p = pd.DataFrame(res_p.data).sort_values(by=['is_urgent', 'created_at'], ascending=[False, False])
        for _, p_row in df_p.iterrows():
            # [Standard Purchase Logic here...]
            st.write(f"{'🚨' if p_row['is_urgent'] else '📦'} {p_row['item_name']}")
