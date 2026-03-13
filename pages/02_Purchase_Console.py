import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Purchase Console | BGEngg ERP", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=2)
def get_purchase_data():
    # Fetching both the trigger projects and the itemized orders
    proj = conn.table("anchor_projects").select("*").eq("purchase_trigger", True).execute()
    items = conn.table("purchase_orders").select("*").execute()
    return pd.DataFrame(proj.data or []), pd.DataFrame(items.data or [])

df_p, df_items = get_purchase_data()

st.title("📦 Purchase Console")
st.markdown("---")

if not df_p.empty:
    # Outer Loop: Projects
    for p_idx, p_row in df_p.iterrows():
        p_db_id = p_row['id']
        job_no = str(p_row.get('job_no', 'N/A')).strip().upper()
        
        with st.expander(f"📋 Job: {job_no} | {p_row.get('client_name', '')}"):
            # Filter items for this job
            job_items = df_items[df_items['job_no'] == job_no] if not df_items.empty else pd.DataFrame()
            
            # Inner Loop: Items
            # We use 'enumerate' to get an index (i) for absolute uniqueness
            for i, i_row in job_items.reset_index().iterrows():
                i_db_id = i_row['id']
                
                # --- THE BULLETPROOF KEY STRATEGY ---
                # We combine: Widget Name + Project ID + Item ID + Loop Index
                # This prevents collision even if the same item is listed twice.
                k_suffix = f"{p_db_id}_{i_db_id}_{i}" 
                
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([1.5, 2, 1, 0.8])
                    
                    c1.write(f"**{i_row.get('item_name', 'Item')}**")
                    c1.caption(f"Spec: {i_row.get('specs', '-')}")
                    
                    # Widget 1: Reply
                    i_reply = c2.text_input(
                        "Reply", 
                        value=i_row.get('purchase_reply', "") or "", 
                        key=f"txt_{k_suffix}", # UNIQUE KEY
                        label_visibility="collapsed"
                    )
                    
                    # Widget 2: Status
                    i_opts = ["Triggered", "Sourcing", "Ordered", "Received"]
                    curr_stat = i_row.get('status', 'Triggered')
                    i_stat = c3.selectbox(
                        "Status", 
                        i_opts, 
                        index=i_opts.index(curr_stat) if curr_stat in i_opts else 0,
                        key=f"sel_{k_suffix}", # UNIQUE KEY
                        label_visibility="collapsed"
                    )
                    
                    # Widget 3: Button
                    if c4.button("Save", key=f"btn_{k_suffix}", use_container_width=True):
                        conn.table("purchase_orders").update({
                            "purchase_reply": i_reply,
                            "status": i_stat,
                            "updated_at": datetime.now(IST).isoformat()
                        }).eq("id", i_db_id).execute()
                        st.rerun()
else:
    st.info("No active purchase triggers.")
