import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz

# --- 1. SETUP & BRANDING ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Material Indent | B&G", layout="wide", page_icon="📝")
conn = st.connection("supabase", type=SupabaseConnection)

# Custom CSS for B&G Branding Assets
st.markdown("""
    <style>
    .bg-header { background-color: #004085; color: white; padding: 20px; border-radius: 5px; text-align: center; margin-bottom: 10px; }
    .blue-strip { background-color: #007bff; height: 5px; width: 100%; border-radius: 2px; margin-bottom: 20px; }
    .footer-summary { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border-top: 3px solid #007bff; margin-top: 20px; }
    </style>
    """, unsafe_allow_html=True)

# --- BRANDED HEADER ---
st.markdown('<div class="bg-header"><h1>B&G ENGINEERING | Material Indent Portal</h1></div>', unsafe_allow_html=True)
st.markdown('<div class="blue-strip"></div>', unsafe_allow_html=True)

# --- 2. DATA LOADERS ---
def get_jobs():
    res = conn.table("anchor_projects").select("job_no").execute()
    return sorted([str(r['job_no']) for r in res.data if r.get('job_no')]) if res.data else []

def get_groups():
    res = conn.table("material_master").select("material_group").execute()
    return sorted([str(r['material_group']) for r in res.data]) if res.data else ["GENERAL"]

# --- 3. INDENT FORM ---
with st.expander("📝 RAISE NEW MATERIAL INDENT", expanded=True):
    with st.form("indent_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        selected_jobs = col1.multiselect("Job Nos (Multi-Select)", get_jobs())
        m_group = col2.selectbox("Material Group", get_groups())
        
        item_name = st.text_input("Item Name / Description")
        specs = st.text_area("Detailed Specifications", placeholder="Size, Grade, Brand, etc.")
        
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        qty = c1.number_input("Quantity Required", min_value=0.1, step=0.1)
        unit = c2.selectbox("Units", ["Nos", "Kgs", "Mts", "Sft", "Sets"])
        urgent = c3.toggle("🚨 Mark as URGENT")
        notes = c4.text_input("Special Notes")
        
        if st.form_submit_button("🚀 Submit Indent to Purchase"):
            if selected_jobs and item_name:
                job_string = ", ".join(selected_jobs)
                payload = {
                    "job_no": job_string,
                    "item_name": item_name.upper(),
                    "specs": specs,
                    "quantity": qty,
                    "units": unit,
                    "material_group": m_group,
                    "special_notes": notes,
                    "is_urgent": urgent,
                    "status": "Triggered"
                }
                conn.table("purchase_orders").insert(payload).execute()
                st.success(f"Indent for {item_name} submitted successfully!")
                st.rerun()
            else:
                st.error("Missing mandatory fields: Job No or Item Name.")

# --- 4. SEARCH & EXPORT SECTION ---
st.divider()
st.subheader("🔍 Search & Export Indents")

# Filter UI
search_col, filter_col = st.columns([2, 1])
query = search_col.text_input("Search by Job No", placeholder="Enter Job Code (e.g. BGE-101)")
status_filter = filter_col.selectbox("Filter by Status", ["All", "Triggered", "Ordered", "Received", "Rejected"])

# Fetch Data
res = conn.table("purchase_orders").select("*").order("created_at", desc=True).execute()
if res.data:
    df_all = pd.DataFrame(res.data)
    
    # Apply Filters
    if query:
        df_all = df_all[df_all['job_no'].str.contains(query, case=False, na=False)]
    if status_filter != "All":
        df_all = df_all[df_all['status'] == status_filter]

    # --- DISPLAY & EXPORT ---
    if not df_all.empty:
        # Professional Columns for Display
        display_cols = ['created_at', 'job_no', 'item_name', 'quantity', 'units', 'status', 'is_urgent']
        df_display = df_all[display_cols].copy()
        
        # Format date for readability
        df_display['created_at'] = pd.to_datetime(df_display['created_at']).dt.strftime('%d-%m-%Y')
        
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Export Options
        csv = df_display.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Export Indent Form (CSV)",
            data=csv,
            file_name=f"BG_Indent_Export_{datetime.now().strftime('%Y%m%d')}.csv",
            mime='text/csv',
        )

        # --- SUMMARY FOOTER ---
        st.markdown('<div class="footer-summary">', unsafe_allow_html=True)
        s_col1, s_col2, s_col3 = st.columns(3)
        s_col1.metric("Total Line Items", len(df_all))
        s_col2.metric("Urgent Requests", int(df_all['is_urgent'].sum()))
        s_col3.metric("Pending (Triggered)", len(df_all[df_all['status'] == 'Triggered']))
        st.markdown('</div>', unsafe_allow_html=True)
        
    else:
        st.warning("No indents found matching your search criteria.")
else:
    st.info("No indent history found in database.")
