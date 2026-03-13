import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime
import pytz

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Purchase Console | BGEngg ERP", layout="wide", page_icon="🛒")

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_purchase_tasks():
    res = conn.table("anchor_projects").select("*").eq("purchase_trigger", True).order("id", desc=True).execute()
    return pd.DataFrame(res.data or [])

@st.cache_data(ttl=2)
def get_all_items():
    res = conn.table("purchase_orders").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data or [])

df_p = get_purchase_tasks()
df_items = get_all_items()

st.title("🛒 Purchase Integration Console")

# --- 3. ACTION CENTER ---
if not df_p.empty:
    for index, row in df_p.iterrows():
        db_id = row['id']
        curr_job = str(row.get('job_no', 'N/A')).strip().upper()
        job_items = df_items[df_items['job_no'] == curr_job] if not df_items.empty else pd.DataFrame()
        
        with st.expander(f"📦 JOB: {curr_job} | {row.get('client_name', 'Unknown')} | Items: {len(job_items)}"):
            c1, c2 = st.columns([1, 2.5])
            
            with c1:
                st.markdown("### 📋 Project Header")
                # Using 'header' prefix to keep keys distinct from item keys
                new_proj_stat = st.selectbox("Status", 
                    ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"], 
                    index=0, key=f"header_stat_{db_id}")
                
                if st.button("Save Header", key=f"header_btn_{db_id}", type="primary"):
                    conn.table("anchor_projects").update({"purchase_status": new_proj_stat}).eq("id", db_id).execute()
                    st.rerun()

            with c2:
                st.markdown("### 📦 Item Response")
                for _, item in job_items.iterrows():
                    item_id = item['id']
                    
                    # --- THE FIX: TRIPLE-LAYER UNIQUE KEY ---
                    # 1. Widget type (irep)
                    # 2. Job Number (curr_job)
                    # 3. Database Primary Key (item_id)
                    # This combination is mathematically guaranteed to be unique.
                    item_key_base = f"{curr_job}_{item_id}"
                    
                    with st.container(border=True):
                        ic1, ic2, ic3, ic4 = st.columns([1.2, 2, 1, 0.8])
                        
                        ic1.write(f"**{item.get('item_name', 'N/A')}**")
                        
                        # Apply the unique key here
                        i_reply = ic2.text_input(
                            "Reply", 
                            value=item.get('purchase_reply', "") or "", 
                            key=f"irep_input_{item_key_base}", 
                            label_visibility="collapsed"
                        )
                        
                        i_stat = ic3.selectbox(
                            "Stat", 
                            ["Triggered", "Sourcing", "Ordered", "Received"], 
                            key=f"istat_sel_{item_key_base}",
                            label_visibility="collapsed"
                        )
                        
                        if ic4.button("Update", key=f"isave_btn_{item_key_base}"):
                            conn.table("purchase_orders").update({
                                "purchase_reply": i_reply,
                                "status": i_stat
                            }).eq("id", item_id).execute()
                            st.toast("Updated")
                            st.rerun()
