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
    try:
        proj_res = conn.table("anchor_projects").select("*").execute()
        items_res = conn.table("purchase_orders").select("*").execute()
        
        df_all_proj = pd.DataFrame(proj_res.data or [])
        df_items = pd.DataFrame(items_res.data or [])
        
        if not df_all_proj.empty:
            active_item_jobs = []
            if not df_items.empty:
                active_item_jobs = df_items['job_no'].astype(str).str.upper().unique()
            
            # Show if Anchor flagged it OR if there are items in purchase_orders table
            df_p = df_all_proj[
                (df_all_proj.get('purchase_trigger') == True) | 
                (df_all_proj['job_no'].astype(str).str.upper().isin(active_item_jobs))
            ]
            return df_p, df_items
            
        return pd.DataFrame(), df_items
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_p, df_items = get_full_purchase_data()

st.title("🛒 Purchase Integration Console")

# --- 3. ANALYTICS ---
if not df_p.empty:
    status_col = 'purchase_status' if 'purchase_status' in df_p.columns else 'status'
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
        
        # Filter items for this specific job
        job_items = pd.DataFrame()
        if not df_items.empty and 'job_no' in df_items.columns:
            job_items = df_items[df_items['job_no'].astype(str).str.upper() == job_no]
        
        # Source detection logic for header summary
        prod_count = 0
        if not job_items.empty:
            prod_count = len(job_items[
                job_items['item_name'].str.contains("URGENT|SHOP", case=False, na=False) | 
                job_items['specs'].str.contains("URGENT|SHOP", case=False, na=False)
            ])
        anchor_count = len(job_items) - prod_count

        header_label = f"📋 JOB: {job_no} | {p_row.get('client_name', 'Client')} | ⚓ {anchor_count} | 🏗️ {prod_count}"
        
        with st.expander(header_label, expanded=True):
            # --- PART A: LOGISTICS SUMMARY ---
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
                st.toast("Status Updated"); st.rerun()

            # --- PART B: ITEMIZED FULFILLMENT (De-duplicated & Grouped) ---
            st.markdown(f'<div class="section-header">📦 Material Request Breakdown</div>', unsafe_allow_html=True)
            
            if job_items.empty:
                st.info("No specific material requests logged for this job.")
            else:
                # Group all items inside ONE bordered container
                with st.container(border=True):
                    items_sorted = job_items.sort_values('id').reset_index(drop=True)
                    for i, i_row in items_sorted.iterrows():
                        i_db_id = i_row['id']
                        k_suffix = f"pur_{p_db_id}_{i_db_id}_{i}"
                        
                        # Detect Source
                        item_name_up = str(i_row.get('item_name', '')).upper()
                        item_spec_up = str(i_row.get('specs', '')).upper()
                        is_prod = any(x in item_name_up for x in ["SHOP", "URGENT"]) or \
                                  any(x in item_spec_up for x in ["SHOP", "URGENT"])
                        
                        ic1, ic2, ic3, ic4 = st.columns([1.5, 2.5, 1, 0.8])
                        
                        with ic1:
                            if is_prod:
                                st.markdown('<span class="tag-prod">🏗️ FROM PRODUCTION</span>', unsafe_allow_html=True)
                                st.error("🚨 URGENT")
                            else:
                                st.markdown('<span class="tag-anchor">⚓ FROM ANCHOR</span>', unsafe_allow_html=True)
                            st.write(f"**{i_row.get('item_name', 'Item')}**")
                            st.caption(f"Spec: {i_row.get('specs', '-')}")
                        
                        i_reply_val = i_row.get('purchase_reply', "") or ""
                        i_reply = ic2.text_area("Reply", value=i_reply_val, key=f"irep_{k_suffix}", height=80, label_visibility="collapsed")
                        
                        i_opts = ["Triggered", "Sourcing", "Ordered", "Received", "Urgent"]
                        curr_i_stat = str(i_row.get('status', 'Triggered'))
                        def_i_idx = i_opts.index(curr_i_stat) if curr_i_stat in i_opts else 0
                        i_stat = ic3.selectbox("Status", i_opts, index=def_i_idx, key=f"istat_{k_suffix}", label_visibility="collapsed")
                        
                        if ic4.button("Update", key=f"isave_{k_suffix}", use_container_width=True):
                            conn.table("purchase_orders").update({
                                "purchase_reply": i_reply, "status": i_stat,
                                "updated_at": datetime.now(IST).isoformat()
                            }).eq("id", i_db_id).execute()
                            st.toast(f"Saved {i_row.get('item_name')}"); st.cache_data.clear(); st.rerun()
                        
                        if i < len(items_sorted) - 1:
                            st.divider()
        st.write(" ") # Spacer between Job expanders
else:
    st.success("All clear! No pending purchase triggers.")
