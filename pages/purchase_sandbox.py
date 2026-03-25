import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timezone
import pytz

# --- 1. SETUP & THEME ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Purchase Integration | B&G", layout="wide", page_icon="🛒")

# --- PASSWORD PROTECTION ---
def check_password():
    if "password_correct" not in st.session_state:
        st.text_input("🔑 Enter Master Password", type="password", 
                      on_change=lambda: st.session_state.update({"password_correct": st.session_state["password"] == "1234"}), 
                      key="password")
        return False
    return st.session_state["password_correct"]

if not check_password(): st.stop()

st.markdown("""
    <style>
    .section-header { background-color: #f8f9fa; padding: 10px; border-radius: 8px; border-left: 5px solid #007bff; margin-bottom: 15px; font-weight: bold; }
    .tag-anchor { background-color: #e7f3ff; color: #007bff; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 11px; }
    .tag-prod { background-color: #f0fff4; color: #28a745; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 11px; }
    .aging-red { color: white; background-color: #dc3545; padding: 3px 10px; border-radius: 4px; font-weight: bold; font-size: 12px; animation: blinker 1.5s linear infinite; }
    .aging-orange { color: #856404; background-color: #fff3cd; padding: 3px 10px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    @keyframes blinker { 50% { opacity: 0.5; } }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS & AGING LOGIC ---
def calculate_aging(created_at_str):
    try:
        if not created_at_str: return 0, ""
        created_at = pd.to_datetime(created_at_str).replace(tzinfo=timezone.utc).astimezone(IST)
        now = datetime.now(IST)
        hrs = (now - created_at).total_seconds() / 3600
        if hrs > 48:
            return hrs, f'<span class="aging-red">🛑 CRITICAL: {int(hrs)} HRS</span>'
        elif hrs > 24:
            return hrs, f'<span class="aging-orange">⚠️ DELAYED: {int(hrs)} HRS</span>'
        else:
            return hrs, f'<span style="color:gray; font-size:11px;">⏱️ {int(hrs)}h ago</span>'
    except:
        return 0, ""

@st.cache_data(ttl=2)
def get_full_purchase_data():
    try:
        proj_res = conn.table("anchor_projects").select("*").execute()
        items_res = conn.table("purchase_orders").select("*").execute()
        df_all_proj = pd.DataFrame(proj_res.data or [])
        df_items = pd.DataFrame(items_res.data or [])
        
        if not df_all_proj.empty:
            # Identify jobs with any status that isn't 'Received'
            active_item_jobs = df_items[df_items['status'] != "Received"]['job_no'].astype(str).str.upper().unique() if not df_items.empty else []
            
            # Show if: Status is Won OR has active purchase items OR manually triggered
            mask = (df_all_proj['status'] == "Won") | \
                   (df_all_proj['job_no'].astype(str).str.upper().isin(active_item_jobs)) | \
                   (df_all_proj.get('purchase_trigger') == True)
            
            df_p = df_all_proj[mask]
            return df_p, df_items
        return pd.DataFrame(), df_items
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return pd.DataFrame(), pd.DataFrame()

# LOAD DATA
df_p, df_items = get_full_purchase_data()

# --- 3. HEADER & SEARCH ---
st.title("🛒 Purchase Integration Console")

search_col, spacer = st.columns([1, 2])
search_query = search_col.text_input("🔍 Search Job No or Client", placeholder="Ex: BGE-101...").strip().upper()

# --- 4. PRODUCTIVITY SUMMARY ---
if not df_items.empty:
    pending_items = df_items[df_items['status'] != "Received"].copy()
    if not pending_items.empty:
        aging_results = pending_items['created_at'].apply(calculate_aging)
        pending_items['hrs_old'] = [res[0] for res in aging_results]
        critical_count = len(pending_items[pending_items['hrs_old'] > 48])
        if critical_count > 0:
            st.error(f"🚨 **Productivity Alert:** {critical_count} items are currently CRITICAL (>48h delay).")

# --- 5. ACTION CENTER ---
if not df_p.empty:
    # Apply Search Filter
    if search_query:
        df_p = df_p[
            (df_p['job_no'].astype(str).str.upper().contains(search_query)) | 
            (df_p['client_name'].astype(str).str.upper().contains(search_query))
        ]

    for _, p_row in df_p.iterrows():
        job_no = str(p_row.get('job_no', 'N/A')).strip().upper()
        p_db_id = p_row['id']
        
        job_items = df_items[df_items['job_no'].astype(str).str.upper() == job_no] if not df_items.empty else pd.DataFrame()
        active_items = job_items[job_items['status'] != "Received"].copy()
        
        # Only show the expander if there are active items to handle
        if active_items.empty: continue 

        # TAGGING LOGIC: PRODUCTION VS ANCHOR
        active_items['is_prod'] = active_items.apply(lambda x: 
            any(word in str(x['item_name']).upper() for word in ["SHOP", "URGENT"]) or 
            any(word in str(x['specs']).upper() for word in ["SHOP", "URGENT"]), axis=1)
        
        prod_count = active_items['is_prod'].sum()
        anchor_count = len(active_items) - prod_count
        job_has_critical = any(calculate_aging(r.get('created_at'))[0] > 48 for _, r in active_items.iterrows())

        header_label = f"{'🔴' if job_has_critical else '📋'} JOB: {job_no} | {p_row.get('client_name', 'Client')} | ⚓ {anchor_count} | 🏗️ {prod_count}"
        
        with st.expander(header_label, expanded=job_has_critical or search_query != ""):
            st.markdown('<div class="section-header">🚩 Logistics Summary</div>', unsafe_allow_html=True)
            ac1, ac2, ac3 = st.columns([1, 2, 1])
            ac1.write(f"**Anchor:** {p_row.get('anchor_person', 'N/A')}")
            ac2.info(f"**Critical Materials:** {p_row.get('critical_materials', 'N/A')}")
            
            # Job Progress Select
            stat_opts = ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"]
            curr_p_stat = p_row.get('purchase_status', "Pending Review")
            def_idx = stat_opts.index(curr_p_stat) if curr_p_stat in stat_opts else 0
            new_p_stat = ac3.selectbox("Job Level Status", stat_opts, index=def_idx, key=f"h_stat_{p_db_id}")
            if ac3.button("Update Job Status", key=f"h_btn_{p_db_id}", type="primary", use_container_width=True):
                conn.table("anchor_projects").update({"purchase_status": new_p_stat}).eq("id", p_db_id).execute()
                st.rerun()

            st.markdown('<div class="section-header">📦 Material Request Breakdown</div>', unsafe_allow_html=True)
            for i, i_row in active_items.sort_values('id').iterrows():
                _, aging_tag = calculate_aging(i_row.get('created_at'))
                
                with st.container(border=True):
                    ic1, ic2, ic3, ic4 = st.columns([1.5, 2.5, 1, 0.8])
                    with ic1:
                        if i_row['is_prod']:
                            st.markdown('<span class="tag-prod">🏗️ PRODUCTION TRIGGER</span>', unsafe_allow_html=True)
                        else:
                            st.markdown('<span class="tag-anchor">⚓ ANCHOR REQUEST</span>', unsafe_allow_html=True)
                        st.markdown(aging_tag, unsafe_allow_html=True)
                        st.write(f"**{i_row.get('item_name')}**")
                    
                    i_reply = ic2.text_area("Purchase Note", value=i_row.get('purchase_reply', ""), key=f"rep_{i_row['id']}", height=85, placeholder="Enter lead time, vendor info...", label_visibility="collapsed")
                    
                    status_list = ["Triggered", "Sourcing", "Ordered", "Received"]
                    curr_item_stat = i_row.get('status', "Triggered")
                    stat_idx = status_list.index(curr_item_stat) if curr_item_stat in status_list else 0
                    i_stat = ic3.selectbox("Status", status_list, index=stat_idx, key=f"st_{i_row['id']}", label_visibility="collapsed")
                    
                    if ic4.button("Update Item", key=f"btn_{i_row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({
                            "purchase_reply": i_reply, 
                            "status": i_stat, 
                            "updated_at": datetime.now(IST).isoformat()
                        }).eq("id", i_row['id']).execute()
                        st.cache_data.clear()
                        st.rerun()
else:
    st.info("No active material requests found.")
