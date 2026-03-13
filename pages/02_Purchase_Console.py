import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime
import pytz

# --- 1. SETUP & STYLING ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Purchase Console | BGEngg ERP", layout="wide", page_icon="🛒")

# High-quality UI refinements
st.markdown("""
    <style>
    .stMetric { background-color: #f8f9fa; padding: 10px; border-radius: 10px; border: 1px solid #e9ecef; }
    .urgent-tag { background-color: #ff4b4b; color: white; padding: 2px 8px; border-radius: 4px; font-weight: bold; }
    .source-anchor { color: #007bff; font-weight: bold; }
    .source-prod { color: #28a745; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=5)
def get_purchase_tasks():
    # Fetch projects triggered for purchase
    res = conn.table("anchor_projects").select("*").eq("purchase_trigger", True).order("id", desc=True).execute()
    return pd.DataFrame(res.data or [])

@st.cache_data(ttl=2)
def get_all_items():
    # Fetch specific material requests
    res = conn.table("purchase_orders").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data or [])

df_p = get_purchase_tasks()
df_items = get_all_items()

# --- 3. HEADER & ANALYTICS ---
st.title("🛒 Purchase Integration Console")

if not df_p.empty:
    # Handle missing status columns gracefully
    p_stat_col = 'purchase_status' if 'purchase_status' in df_p.columns else None
    
    if p_stat_col:
        p_summary = df_p.groupby(p_stat_col).agg(Total_Jobs=('id', 'count')).reset_index()
        col1, col2 = st.columns([1, 1])
        with col1:
            st.dataframe(p_summary, hide_index=True, use_container_width=True)
        with col2:
            fig = px.pie(p_summary, values='Total_Jobs', names=p_stat_col, 
                         title="Workload Distribution", hole=0.4, height=200)
            fig.update_layout(margin=dict(t=30, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- 4. ACTION CENTER (The Aligned Layout) ---
if not df_p.empty:
    st.subheader("📝 Pending Material Actions")
    
    for index, row in df_p.iterrows():
        db_id = row['id']
        curr_job = str(row.get('job_no', 'N/A')).strip().upper()
        
        # Filter items for this job
        job_items = df_items[df_items['job_no'] == curr_job] if not df_items.empty else pd.DataFrame()
        
        # Status Icon
        p_stat = row.get('purchase_status', 'Pending Review')
        icon = "🟢" if p_stat == "Received" else "🟡"
        
        with st.expander(f"{icon} JOB: {curr_job} | {row.get('client_name', 'Unknown Client')} | Requests: {len(job_items)}"):
            c1, c2 = st.columns([1, 2.5])
            
            # --- LEFT: PROJECT OVERVIEW ---
            with c1:
                st.markdown("### 📋 Project Header")
                st.write(f"**Anchor:** {row.get('anchor_person', 'N/A')}")
                st.info(f"**Critical Summary:**\n{row.get('critical_materials', 'None reported')}")
                
                # Overall Project Purchase Status
                stat_opts = ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"]
                current_idx = stat_opts.index(p_stat) if p_stat in stat_opts else 0
                
                new_proj_stat = st.selectbox("Update Project Status", stat_opts, index=current_idx, key=f"pstat_{db_id}")
                new_rem = st.text_area("Global Purchase Remarks", value=row.get('purchase_remarks', "") or "", key=f"prem_{db_id}")
                
                if st.button("Save Project Header", key=f"ubtn_{db_id}", type="primary", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "purchase_status": new_proj_stat,
                        "purchase_remarks": new_rem
                    }).eq("id", db_id).execute()
                    st.toast("Project Header Updated")
                    st.rerun()

            # --- RIGHT: ITEM BREAKDOWN (Clean & Aligned) ---
            with c2:
                st.markdown("### 📦 Item-wise Response")
                if job_items.empty:
                    st.warning("No specific items requested for this job.")
                else:
                    for _, item in job_items.iterrows():
                        item_id = item['id']
                        # Composite key to PREVENT DuplicateKey Error
                        comp_key = f"{curr_job}_{item_id}"
                        
                        is_prod = "SHOP" in str(item.get('item_name', '')).upper()
                        is_urgent = "URGENT" in str(item.get('status', '')).upper()
                        
                        with st.container(border=True):
                            # Horizontal alignment for item response
                            ic1, ic2, ic3, ic4 = st.columns([1.2, 2, 1, 0.8])
                            
                            # Info Column
                            tag = "🏗️ PROD" if is_prod else "⚓ ANCHOR"
                            ic1.markdown(f"<span class='{'source-prod' if is_prod else 'source-anchor'}'>{tag}</span>", unsafe_allow_html=True)
                            if is_urgent: ic1.markdown("<span class='urgent-tag'>URGENT</span>", unsafe_allow_html=True)
                            ic1.write(f"**{item.get('item_name', 'N/A')}**")
                            ic1.caption(f"Spec: {item.get('specs', 'N/A')}")
                            
                            # Reply Column
                            i_reply = ic2.text_input("Reply to Team", 
                                                    value=item.get('purchase_reply', "") or "", 
                                                    key=f"irep_{comp_key}", 
                                                    placeholder="Ordered / ETA...")
                            
                            # Status Column
                            i_stat_opts = ["Triggered", "Sourcing", "Ordered", "Received", "Urgent"]
                            i_curr_stat = item.get('status', 'Triggered')
                            i_stat = ic3.selectbox("Item Status", i_stat_opts, 
                                                  index=i_stat_opts.index(i_curr_stat) if i_curr_stat in i_stat_opts else 0,
                                                  key=f"istat_{comp_key}")
                            
                            # Save Column
                            if ic4.button("Update", key=f"isave_{comp_key}", use_container_width=True):
                                conn.table("purchase_orders").update({
                                    "purchase_reply": i_reply,
                                    "status": i_stat
                                }).eq("id", item_id).execute()
                                st.toast(f"Updated {item['item_name']}")
                                st.rerun()
else:
    st.success("All clear! No pending requests.")
