import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz

# --- 1. SETUP & BRANDING ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G | Material Indent", layout="wide", page_icon="📝")
conn = st.connection("supabase", type=SupabaseConnection)

# Custom CSS for B&G Branding
st.markdown("""
    <style>
    .main-header { background-color: #003366; color: white; padding: 1.5rem; border-radius: 10px; text-align: center; border-bottom: 8px solid #007bff; }
    .stButton>button { background-color: #007bff; color: white; border-radius: 5px; width: 100%; }
    .summary-box { background-color: #e7f3ff; padding: 15px; border-radius: 10px; border-left: 5px solid #003366; margin-top: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- BRANDED HEADER ---
st.markdown('<div class="main-header"><h1>B&G ENGINEERING</h1><p>MATERIAL INDENT MANAGEMENT SYSTEM</p></div>', unsafe_allow_html=True)

# --- 2. DATA LOADERS ---
def get_jobs():
    res = conn.table("anchor_projects").select("job_no").execute()
    return sorted([str(r['job_no']) for r in res.data if r.get('job_no')]) if res.data else []

def get_groups():
    res = conn.table("material_master").select("material_group").execute()
    return sorted([str(r['material_group']) for r in res.data]) if res.data else ["GENERAL"]

def get_staff_names():
    res = conn.table("master_staff").select("name").execute()
    return sorted([r['name'] for r in res.data]) if res.data else ["Admin"]

# --- 3. INDENT APPLICATION ENGINE ---
st.subheader("📝 New Indent Creation")

# A. Identifiers
c1, c2 = st.columns(2)
raised_by = c1.selectbox("Indent Raised By", get_staff_names())
indent_date = c2.date_input("Indent Date", datetime.now(IST))

# B. Multi-Item Entry Logic (The "Cart")
if "cart" not in st.session_state:
    st.session_state.cart = []

with st.container(border=True):
    st.markdown("**➕ Add Item Details**")
    f1, f2, f3 = st.columns([2, 2, 1])
    target_jobs = f1.multiselect("Job No(s)", get_jobs())
    m_group = f2.selectbox("Material Group", get_groups())
    is_urgent = f3.toggle("🚨 Urgent?", key="urg_toggle")
    
    desc = st.text_input("Item Description / Specifications")
    
    col_q1, col_q2, col_q3 = st.columns([1, 1, 3])
    qty = col_q1.number_input("Quantity", min_value=0.0, step=0.1)
    unit = col_q2.selectbox("Unit", ["Nos", "Kgs", "Mts", "Sft", "Sets"])
    notes = col_q3.text_input("Special Remarks")

    if st.button("➕ Add Item to List"):
        if target_jobs and desc and qty > 0:
            st.session_state.cart.append({
                "job_no": ", ".join(target_jobs),
                "material_group": m_group,
                "item_name": desc.upper(),
                "quantity": qty,
                "units": unit,
                "is_urgent": is_urgent,
                "special_notes": notes,
                "triggered_by": raised_by,
                "status": "Triggered"
            })
            st.rerun()
        else:
            st.error("Please fill Job, Description and Quantity.")

# C. Table Preview and Final Submission
if st.session_state.cart:
    st.markdown("### 📋 Preview Indent Items")
    df_cart = pd.DataFrame(st.session_state.cart)
    st.dataframe(df_cart[['job_no', 'item_name', 'quantity', 'units', 'is_urgent']], use_container_width=True, hide_index=True)
    
    btn1, btn2 = st.columns(2)
    if btn1.button("🗑️ Clear List"):
        st.session_state.cart = []
        st.rerun()
        
    if btn2.button("🚀 FINAL SUBMIT & GENERATE INDENT", type="primary"):
        try:
            # 1. Generate Indent No Header
            header_res = conn.table("indent_headers").insert({"raised_by": raised_by}).execute()
            new_id = header_res.data[0]['indent_no']
            
            # 2. Assign Indent No and Bulk Insert Items
            for item in st.session_state.cart:
                item['indent_no'] = new_id
                conn.table("purchase_orders").insert(item).execute()
            
            st.success(f"Indent #{new_id} Submitted Successfully!")
            st.session_state.cart = []
            st.rerun()
        except Exception as e:
            st.error(f"Submit Error: {e}")

# --- 4. SEARCH, EXPORT & SUMMARY SECTION ---
st.divider()
st.subheader("🔍 Search & Export Past Indents")

# Filter UI
q_col, s_col = st.columns([3, 1])
search_job = q_col.text_input("Filter by Job Code", placeholder="Type Job No...")
stat_filter = s_col.selectbox("Status", ["All", "Triggered", "Ordered", "Received", "Rejected"])

# Fetch All Data for Export/Summary
raw_data = conn.table("purchase_orders").select("*").order("created_at", desc=True).execute()

if raw_data.data:
    df_db = pd.DataFrame(raw_data.data)
    
    # Apply Filtering
    if search_job:
        df_db = df_db[df_db['job_no'].str.contains(search_job, case=False, na=False)]
    if stat_filter != "All":
        df_db = df_db[df_db['status'] == stat_filter]

    if not df_db.empty:
        # Format for Display
        df_db['Date'] = pd.to_datetime(df_db['created_at']).dt.strftime('%d-%m-%Y')
        display_cols = ['indent_no', 'Date', 'job_no', 'item_name', 'quantity', 'units', 'status', 'is_urgent']
        st.dataframe(df_db[display_cols], use_container_width=True, hide_index=True)

        # CSV Export
        csv = df_db[display_cols].to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Export Indent Data (CSV)",
            data=csv,
            file_name=f"BG_Indent_Export_{datetime.now().strftime('%Y%m%d')}.csv",
            mime='text/csv'
        )

        # --- SUMMARY FOOTER (At bottom as requested) ---
        st.markdown('<div class="summary-box">', unsafe_allow_html=True)
        st.markdown(f"#### 📊 Indent Summary for Range")
        sum1, sum2, sum3, sum4 = st.columns(4)
        sum1.metric("Total Line Items", len(df_db))
        sum2.metric("Total Qty", f"{df_db['quantity'].sum():.1f}")
        sum3.metric("Urgent Items", int(df_db['is_urgent'].sum() if 'is_urgent' in df_db.columns else 0))
        sum4.metric("Jobs Involved", df_db['job_no'].nunique())
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("No matching records found.")
