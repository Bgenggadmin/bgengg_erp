import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime
import pytz

# --- 1. SETUP & THEME ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Purchase Integration | B&G", layout="wide", page_icon="🛒")
# --- PASSWORD PROTECTION ---
def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == "1234": # You can change this!
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct.
        return True

if not check_password():
    st.stop()  # Do not run the rest of the app if password isn't correct
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
        # STEP 1: Fetch only projects that are NOT in Enquiry or Estimation
        # This keeps the Purchase Console strictly for active/won jobs
        proj_res = (
            conn.table("anchor_projects")
            .select("*")
            .not_.in_("status", ["Enquiry", "Estimation"])
            .execute()
        )
        
        items_res = conn.table("purchase_orders").select("*").execute()
        
        df_all_proj = pd.DataFrame(proj_res.data or [])
        df_items = pd.DataFrame(items_res.data or [])
        
        if not df_all_proj.empty:
            active_item_jobs = []
            if not df_items.empty:
                # Standardize job numbers to uppercase for matching
                active_item_jobs = df_items['job_no'].astype(str).str.upper().unique()
            
            # STEP 2: Apply your existing logic on the filtered dataset
            # Shows project if Anchor flagged it OR if items already exist in purchase_orders
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
        
        # 1. Split items into Active and Received (HISTORY)
        job_items = df_items[df_items['job_no'].astype(str).str.upper() == job_no] if not df_items.empty else pd.DataFrame()
        
        active_items = job_items[job_items['status'] != "Received"]
        received_items = job_items[job_items['status'] == "Received"]

        # 2. Skip this Job Card if everything is already Received
        if job_items.empty or active_items.empty:
            continue 

        # 3. Source detection & Aging for Header
        prod_count = len(active_items[active_items['item_name'].str.contains("URGENT|SHOP", case=False, na=False)])
        anchor_count = len(active_items) - prod_count
        
        # Check for delays > 48hrs in active items only
        job_has_critical = False
        for _, r in active_items.iterrows():
            if calculate_aging(r.get('created_at'))[0] > 48:
                job_has_critical = True; break

        header_label = f"{'🔴' if job_has_critical else '📋'} JOB: {job_no} | {p_row.get('client_name', 'Client')} | ⚓ {anchor_count} | 🏗️ {prod_count}"
        
        with st.expander(header_label, expanded=job_has_critical):
            # --- PART A: LOGISTICS SUMMARY ---
            st.markdown('<div class="section-header">🚩 Logistics Summary</div>', unsafe_allow_html=True)
            ac1, ac2, ac3 = st.columns([1, 2, 1])
            ac1.write(f"**Anchor:** {p_row.get('anchor_person', 'N/A')}")
            ac2.info(f"**Critical Requirements:** {p_row.get('critical_materials', 'N/A')}")
            
            # Overall Status Selector
            stat_opts = ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"]
            curr_p_stat = p_row.get('purchase_status', "Pending Review")
            def_stat_idx = stat_opts.index(curr_p_stat) if curr_p_stat in stat_opts else 0
            new_p_stat = ac3.selectbox("Job Progress", stat_opts, index=def_stat_idx, key=f"h_stat_{p_db_id}")
            
            if ac3.button("Save Progress", key=f"h_btn_{p_db_id}", type="primary", use_container_width=True):
                conn.table("anchor_projects").update({"purchase_status": new_p_stat}).eq("id", p_db_id).execute()
                st.toast("Job Status Updated"); st.rerun()

            # --- PART B: ACTIVE ITEM BREAKDOWN ---
            st.markdown(f'<div class="section-header">📦 Active Material Requests</div>', unsafe_allow_html=True)
            with st.container(border=True):
                items_sorted = active_items.sort_values('id').reset_index(drop=True)
                for i, i_row in items_sorted.iterrows():
                    # Calculate aging tag
                    _, aging_tag = calculate_aging(i_row.get('created_at'))
                    
                    ic1, ic2, ic3, ic4 = st.columns([1.5, 2.5, 1, 0.8])
                    with ic1:
                        st.markdown(aging_tag, unsafe_allow_html=True) # Shows Red/Orange aging tags
                        st.write(f"**{i_row.get('item_name')}**")
                        st.caption(f"Spec: {i_row.get('specs', '-')}")
                    
                    i_reply = ic2.text_area("Reply", value=i_row.get('purchase_reply', ""), key=f"rep_{i_row['id']}", height=80, label_visibility="collapsed")
                    i_stat = ic3.selectbox("Status", ["Triggered", "Sourcing", "Ordered", "Received"], index=0, key=f"st_{i_row['id']}", label_visibility="collapsed")
                    
                    if ic4.button("Update", key=f"btn_{i_row['id']}", use_container_width=True):
                        conn.table("purchase_orders").update({
                            "purchase_reply": i_reply, "status": i_stat,
                            "updated_at": datetime.now(IST).isoformat()
                        }).eq("id", i_row['id']).execute()
                        st.cache_data.clear(); st.rerun() # Item disappears if moved to 'Received'

            # --- PART C: HISTORY (RECEIVED ITEMS) ---
            if not received_items.empty:
                with st.expander(f"View {len(received_items)} Received Items"):
                    for _, r_item in received_items.iterrows():
                        st.write(f"✅ {r_item['item_name']} — {r_item.get('purchase_reply', 'Fulfillment complete')}")

else:
    st.success("All clear! No pending purchase triggers.")
