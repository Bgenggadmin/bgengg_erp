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

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=5)
def get_full_purchase_data():
    # FIXED: Added safety check for .data to prevent AttributeError on failure
    proj = conn.table("anchor_projects").select("*").eq("purchase_trigger", True).execute()
    items = conn.table("purchase_orders").select("*").execute()
    return pd.DataFrame(proj.data or []), pd.DataFrame(items.data or [])

df_p, df_items = get_full_purchase_data()

st.title("🛒 Purchase Integration Console")

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

# --- 4. STACKED ACTION CENTER ---
if not df_p.empty:
    for p_idx, p_row in df_p.iterrows():
        p_db_id = p_row['id']
        job_no = str(p_row.get('job_no', 'N/A')).strip().upper()
        
        # FIXED: Added .str.upper() comparison to prevent missing items due to case-mismatch
        job_items = pd.DataFrame()
        if not df_items.empty and 'job_no' in df_items.columns:
            job_items = df_items[df_items['job_no'].astype(str).str.upper() == job_no]
        
        with st.expander(f"📋 JOB: {job_no} | {p_row.get('client_name', 'Client')} | Items: {len(job_items)}", expanded=True):
            
            # --- SECTION 1: ANCHOR CONTEXT (Full Width) ---
            st.markdown('<div class="section-header">🚩 Procurement Context (Sales/Anchor)</div>', unsafe_allow_html=True)
            
            ac1, ac2, ac3 = st.columns([1, 2, 1])
            ac1.write(f"**Anchor Person:**\n{p_row.get('anchor_person', 'N/A')}")
            ac2.info(f"**Critical Requirements:**\n{p_row.get('critical_materials', 'N/A')}")
            
            # Context Update Controls
            stat_opts = ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"]
            curr_p_stat = p_row.get('purchase_status', "Pending Review")
            
            # FIXED: Added safety index check to prevent ValueError if DB status isn't in stat_opts
            def_stat_idx = stat_opts.index(curr_p_stat) if curr_p_stat in stat_opts else 0
            
            new_p_stat = ac3.selectbox("Logistics Status", stat_opts, 
                                      index=def_stat_idx,
                                      key=f"h_stat_{p_db_id}")
            
            if ac3.button("Update Context", key=f"h_btn_{p_db_id}", type="primary", use_container_width=True):
                conn.table("anchor_projects").update({"purchase_status": new_p_stat}).eq("id", p_db_id).execute()
                st.toast("Project Status Updated")
                st.rerun()

            st.write(" ") # Spacer
            
            # --- SECTION 2: ITEMIZED FULFILLMENT (Full Width) ---
            st.markdown(f'<div class="section-header">📋 Itemized Fulfillment ({len(job_items)})</div>', unsafe_allow_html=True)
            
            if job_items.empty:
                st.info("No specific material requests logged for this job.")
            else:
                for i, i_row in job_items.reset_index().iterrows():
                    i_db_id = i_row['id']
                    # Bulletproof Key maintained
                    k_suffix = f"p{p_db_id}_i{i_db_id}_idx{i}" 
                    
                    is_prod = "SHOP" in str(i_row.get('item_name', '')).upper()
                    
                    with st.container(border=True):
                        ic1, ic2, ic3, ic4 = st.columns([1.5, 2.5, 1, 0.8])
                        
                        # Source & Item Info
                        with ic1:
                            if is_prod:
                                st.markdown('<span class="tag-prod">🏗️ PRODUCTION TRIGGER</span>', unsafe_allow_html=True)
                            else:
                                st.markdown('<span class="tag-anchor">⚓ ANCHOR TRIGGER</span>', unsafe_allow_html=True)
                            st.write(f"**{i_row.get('item_name', 'Item')}**")
                            st.caption(f"Spec: {i_row.get('specs', '-')}")
                        
                        # Fulfillment Input
                        # FIXED: Added None-check for purchase_reply to prevent textarea crashing on nulls
                        i_reply_val = i_row.get('purchase_reply', "")
                        if i_reply_val is None: i_reply_val = ""
                        
                        i_reply = ic2.text_area("Purchase Reply / Action Taken", 
                                                value=i_reply_val, 
                                                key=f"irep_{k_suffix}", 
                                                height=68)
                        
                        # Item Status
                        i_opts = ["Triggered", "Sourcing", "Ordered", "Received", "Urgent"]
                        curr_i_stat = i_row.get('status', 'Triggered')
                        def_i_idx = i_opts.index(curr_i_stat) if curr_i_stat in i_opts else 0
                        
                        i_stat = ic3.selectbox("Status", i_opts, 
                                              index=def_i_idx,
                                              key=f"istat_{k_suffix}")
                        
                        # Action
                        if ic4.button("Update Item", key=f"isave_{k_suffix}", use_container_width=True):
                            conn.table("purchase_orders").update({
                                "purchase_reply": i_reply,
                                "status": i_stat,
                                "updated_at": datetime.now(IST).isoformat()
                            }).eq("id", i_db_id).execute()
                            st.toast("Item Saved")
                            st.rerun()
            st.markdown("---")
else:
    st.success("All clear! No pending purchase triggers.")
