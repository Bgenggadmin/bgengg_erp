import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime
import pytz

# --- 1. SETUP & THEME ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Purchase Integration | B&G", layout="wide", page_icon="🛒")

# Custom Styles for specialized tags
st.markdown("""
    <style>
    .section-header { background-color: #f8f9fa; padding: 10px; border-radius: 8px; border-left: 5px solid #007bff; margin-bottom: 15px; font-weight: bold; }
    .tag-anchor { background-color: #e7f3ff; color: #007bff; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 13px; }
    .tag-prod { background-color: #f0fff4; color: #28a745; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 13px; }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. UPDATED DATA LOADERS ---
@st.cache_data(ttl=5)
def get_full_purchase_data():
    try:
        # 1. Fetch data from both tables
        proj_res = conn.table("anchor_projects").select("*").execute()
        items_res = conn.table("purchase_orders").select("*").execute()
        
        df_all_proj = pd.DataFrame(proj_res.data or [])
        df_items = pd.DataFrame(items_res.data or [])
        
        # 2. Logic to identify which projects to show
        if not df_all_proj.empty:
            # If we have items, find jobs that are linked to those items
            active_item_jobs = []
            if not df_items.empty:
                active_item_jobs = df_items['job_no'].astype(str).str.upper().unique()
            
            # Filter: Show if Anchor flagged it OR if Production added items
            df_p = df_all_proj[
                (df_all_proj.get('purchase_trigger') == True) | 
                (df_all_proj['job_no'].astype(str).str.upper().isin(active_item_jobs))
            ]
            return df_p, df_items
            
        # Fallback for empty projects table
        return pd.DataFrame(), df_items
        
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

# This ensures the variables are ALWAYS created
df_p, df_items = get_full_purchase_data()

# --- 3. ANALYTICS (Kept from earlier layout) ---
if not df_p.empty:
    status_col = 'purchase_status' if 'purchase_status' in df_p.columns else 'status'
    # FIXED: Groupby will fail if the column is missing; added a fallback
    if status_col in df_p.columns:
        p_summary = df_p.groupby(status_col).agg(Total_Jobs=('id', 'count')).reset_index()
        sum_c1, sum_c2 = st.columns([1, 1])
        with sum_c1: 
            st.dataframe(p_summary, hide_index=True, use_container_width=True)
        with sum_c2:
            fig = px.pie(p_summary, values='Total_Jobs', names=status_col, hole=0.4, height=220)
            fig.update_layout(margin=dict(t=20, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- 4. STACKED ACTION CENTER (ENHANCED SOURCE TRACKING) ---
if not df_p.empty:
    for p_idx, p_row in df_p.iterrows():
        p_db_id = p_row['id']
        job_no = str(p_row.get('job_no', 'N/A')).strip().upper()
        
        job_items = pd.DataFrame()
        if not df_items.empty and 'job_no' in df_items.columns:
            job_items = df_items[df_items['job_no'].astype(str).str.upper() == job_no]
        
        # Count triggers for the header summary
        # We assume "SHOP" in the name or specific flags identify Production triggers
        prod_count = len(job_items[job_items['item_name'].str.contains("URGENT|SHOP", case=False, na=False)])
        anchor_count = len(job_items) - prod_count

        header_label = f"📋 JOB: {job_no} | {p_row.get('client_name', 'Client')} | ⚓ {anchor_count} | 🏗️ {prod_count}"
        
        with st.expander(header_label, expanded=True):
            # --- SECTION 1: ANCHOR CONTEXT ---
            st.markdown('<div class="section-header">🚩 Logistics Summary</div>', unsafe_allow_html=True)
            ac1, ac2, ac3 = st.columns([1, 2, 1])
            ac1.write(f"**Anchor Person:**\n{p_row.get('anchor_person', 'N/A')}")
            ac2.info(f"**Critical Requirements:**\n{p_row.get('critical_materials', 'N/A')}")
            
            stat_opts = ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"]
            curr_p_stat = p_row.get('purchase_status', "Pending Review")
            def_stat_idx = stat_opts.index(curr_p_stat) if curr_p_stat in stat_opts else 0
            new_p_stat = ac3.selectbox("Overall Status", stat_opts, index=def_stat_idx, key=f"h_stat_{p_db_id}")
            
            if ac3.button("Update Overall", key=f"h_btn_{p_db_id}", type="primary", use_container_width=True):
                conn.table("anchor_projects").update({"purchase_status": new_p_stat}).eq("id", p_db_id).execute()
                st.toast("Updated"); st.rerun()

            # --- SECTION 2: ITEMIZED FULFILLMENT ---
            st.markdown(f'<div class="section-header">📦 Material Request Breakdown</div>', unsafe_allow_html=True)
            
            if job_items.empty:
                st.info("No specific material requests logged.")
            else:
                for i, i_row in job_items.reset_index().iterrows():
                    i_db_id = i_row['id']
                    k_suffix = f"pur_{p_db_id}_{i_db_id}_{i}" 
                    
                    # LOGIC: Identify if trigger came from Shop Floor or Anchor Portal
                    # Looking for "URGENT" prefix typically added by your Production script
                    is_urgent_prod = "URGENT" in str(i_row.get('specs', '')).upper() or "SHOP" in str(i_row.get('item_name', '')).upper()
                    
                    with st.container(border=True):
                        ic1, ic2, ic3, ic4 = st.columns([1.5, 2.5, 1, 0.8])
                        
                        with ic1:
                            if is_urgent_prod:
                                st.markdown('<span class="tag-prod">🏗️ FROM PRODUCTION</span>', unsafe_allow_html=True)
                                st.error("🚨 HIGH URGENCY")
                            else:
                                st.markdown('<span class="tag-anchor">⚓ FROM ANCHOR</span>', unsafe_allow_html=True)
                            
                            st.write(f"**{i_row.get('item_name', 'Item')}**")
                            st.caption(f"Details: {i_row.get('specs', '-')}")
                        
                        i_reply_val = i_row.get('purchase_reply', "") or ""
                        i_reply = ic2.text_area("Purchase Action", value=i_reply_val, key=f"irep_{k_suffix}", height=80)
                        
                        i_opts = ["Triggered", "Sourcing", "Ordered", "Received", "Urgent"]
                        curr_i_stat = i_row.get('status', 'Triggered')
                        def_i_idx = i_opts.index(curr_i_stat) if curr_i_stat in i_opts else 0
                        i_stat = ic3.selectbox("Status", i_opts, index=def_i_idx, key=f"istat_{k_suffix}")
                        
                        if ic4.button("Update", key=f"isave_{k_suffix}", use_container_width=True):
                            conn.table("purchase_orders").update({
                                "purchase_reply": i_reply, "status": i_stat,
                                "updated_at": datetime.now(IST).isoformat()
                            }).eq("id", i_db_id).execute()
                            st.toast("Saved"); st.rerun()
            
           # --- SECTION 2: ITEMIZED FULFILLMENT (Full Width) ---
st.markdown(f'<div class="section-header">📋 Itemized Fulfillment ({len(job_items)})</div>', unsafe_allow_html=True)

if job_items.empty:
    st.info("No specific material requests logged for this job.")
else:
    # IMPORTANT: .reset_index() ensures 'i' is always 0, 1, 2... for THIS job only.
    for i, i_row in job_items.reset_index().iterrows():
        i_db_id = i_row['id']
        
        # FIX 1: ULTRA-UNIQUE KEY 
        # Prevents DuplicateElementKey error by combining Project ID, Item ID, and Loop Index
        k_suffix = f"pur_{p_db_id}_{i_db_id}_{i}" 
        
        # Identify if trigger came from Shop Floor (URGENT/SHOP) or Anchor
        is_urgent_prod = "URGENT" in str(i_row.get('specs', '')).upper() or "SHOP" in str(i_row.get('item_name', '')).upper()
        
        with st.container(border=True):
            ic1, ic2, ic3, ic4 = st.columns([1.5, 2.5, 1, 0.8])
            
            # Column 1: Source & Item Details
            with ic1:
                if is_urgent_prod:
                    st.markdown('<span class="tag-prod">🏗️ FROM PRODUCTION</span>', unsafe_allow_html=True)
                else:
                    st.markdown('<span class="tag-anchor">⚓ FROM ANCHOR</span>', unsafe_allow_html=True)
                
                st.write(f"**{i_row.get('item_name', 'Item')}**")
                st.caption(f"Spec: {i_row.get('specs', '-')}")
            
            # Column 2: Fulfillment Input (FIX 2: Safe handling of Nulls)
            i_reply_val = i_row.get('purchase_reply', "")
            if i_reply_val is None: i_reply_val = ""
            
            i_reply = ic2.text_area(
                "Purchase Action", 
                value=i_reply_val, 
                key=f"irep_{k_suffix}", 
                height=80
            )
            
            # Column 3: Item Status
            i_opts = ["Triggered", "Sourcing", "Ordered", "Received", "Urgent"]
            curr_i_stat = i_row.get('status', 'Triggered')
            # Safety check if status in DB is not in our list
            def_i_idx = i_opts.index(curr_i_stat) if curr_i_stat in i_opts else 0
            
            i_stat = ic3.selectbox(
                "Status", 
                i_opts, 
                index=def_i_idx, 
                key=f"istat_{k_suffix}"
            )
            
            # Column 4: Save Action
            if ic4.button("Update", key=f"isave_{k_suffix}", use_container_width=True):
                conn.table("purchase_orders").update({
                    "purchase_reply": i_reply,
                    "status": i_stat,
                    "updated_at": datetime.now(IST).isoformat()
                }).eq("id", i_db_id).execute()
                
                st.toast(f"✅ Item '{i_row.get('item_name')}' Updated")
                st.cache_data.clear() # Ensure the console reflects the change immediately
                st.rerun()

st.write(" ") # Spacer
