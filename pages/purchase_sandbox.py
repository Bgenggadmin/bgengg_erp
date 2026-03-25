import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
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

# Custom Styles for Productivity Reminders
st.markdown("""
    <style>
    .section-header { background-color: #f8f9fa; padding: 10px; border-radius: 8px; border-left: 5px solid #007bff; margin-bottom: 15px; font-weight: bold; }
    .tag-anchor { background-color: #e7f3ff; color: #007bff; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 13px; }
    .tag-prod { background-color: #f0fff4; color: #28a745; padding: 4px 10px; border-radius: 5px; font-weight: bold; font-size: 13px; }
    .aging-red { color: white; background-color: #dc3545; padding: 3px 10px; border-radius: 4px; font-weight: bold; font-size: 12px; animation: blinker 1.5s linear infinite; }
    .aging-orange { color: #856404; background-color: #fff3cd; padding: 3px 10px; border-radius: 4px; font-weight: bold; font-size: 12px; }
    @keyframes blinker { 50% { opacity: 0.5; } }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS & AGING LOGIC ---
@st.cache_data(ttl=5)
def get_full_purchase_data():
    proj_res = conn.table("anchor_projects").select("*").execute()
    items_res = conn.table("purchase_orders").select("*").execute()
    return pd.DataFrame(proj_res.data or []), pd.DataFrame(items_res.data or [])

def calculate_aging(created_at_str):
    """Returns hours elapsed and a formatted HTML tag."""
    try:
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

df_p, df_items = get_full_purchase_data()

st.title("🛒 Purchase Integration Console")

# --- 3. PRODUCTIVITY SUMMARY (Reminders) ---
if not df_items.empty:
    # Filter for items not yet "Received"
    pending_items = df_items[df_items['status'] != "Received"].copy()
    if not pending_items.empty:
        # Calculate aging for all pending items
        aging_results = pending_items['created_at'].apply(calculate_aging)
        pending_items['hrs_old'] = [res[0] for res in aging_results]
        
        critical_count = len(pending_items[pending_items['hrs_old'] > 48])
        warning_count = len(pending_items[(pending_items['hrs_old'] > 24) & (pending_items['hrs_old'] <= 48)])
        
        if critical_count > 0 or warning_count > 0:
            st.error(f"🚨 **Productivity Alert:** {critical_count} items have been unattended for over 48 hours. {warning_count} items are over 24 hours. Delayed procurement directly impacts shop floor throughput.")

# --- 4. ACTION CENTER ---
if not df_p.empty:
    for p_idx, p_row in df_p.iterrows():
        job_no = str(p_row.get('job_no', 'N/A')).strip().upper()
        p_db_id = p_row['id']
        
        # 1. Pull all items for this job
        all_items = df_items[df_items['job_no'].astype(str).str.upper() == job_no] if not df_items.empty else pd.DataFrame()
        
        # 2. SEPARATE LOGIC: Split items into Active and Received
        active_items = all_items[all_items['status'] != "Received"]
        received_items = all_items[all_items['status'] == "Received"]

        # 3. Check for delays ONLY in active items
        job_has_critical = False
        for _, r in active_items.iterrows():
            if calculate_aging(r.get('created_at'))[0] > 48:
                job_has_critical = True; break

        # 4. Update label to show the count of open triggers
        open_count = len(active_items)
        label = f"{'🔴' if job_has_critical else '📋'} JOB: {job_no} | {p_row.get('client_name', 'Client')} ({open_count} Open)"
        
        with st.expander(label, expanded=job_has_critical):
            # --- LOGISTICS SUMMARY ---
            st.markdown('<div class="section-header">🚩 Logistics Summary</div>', unsafe_allow_html=True)
            ac1, ac2 = st.columns([1, 3])
            ac1.write(f"**Anchor:** {p_row.get('anchor_person', 'N/A')}")
            ac2.info(f"**Critical:** {p_row.get('critical_materials', 'N/A')}")
            
            # --- ITEM BREAKDOWN (ACTIVE ONLY) ---
            st.markdown('<div class="section-header">📦 Active Material Requests</div>', unsafe_allow_html=True)
            with st.container(border=True):
                if active_items.empty:
                    st.success("✅ All items for this job are closed.")
                else:
                    # NOTICE: We only loop through active_items now
                    for i, i_row in active_items.sort_values('id').reset_index(drop=True).iterrows():
                        _, aging_tag = calculate_aging(i_row.get('created_at'))
                        
                        ic1, ic2, ic3, ic4 = st.columns([1.5, 2.5, 1, 0.8])
                        with ic1:
                            st.markdown(aging_tag, unsafe_allow_html=True)
                            st.write(f"**{i_row.get('item_name')}**")
                            st.caption(f"Spec: {i_row.get('specs', '-')}")
                        
                        i_reply = ic2.text_area("Reply", value=i_row.get('purchase_reply', ""), key=f"r_{i_row['id']}", height=80, label_visibility="collapsed")
                        i_stat = ic3.selectbox("Status", ["Triggered", "Sourcing", "Ordered", "Received"], key=f"s_{i_row['id']}", label_visibility="collapsed")
                        
                        if ic4.button("Update", key=f"b_{i_row['id']}", type="primary", use_container_width=True):
                            conn.table("purchase_orders").update({
                                "purchase_reply": i_reply, "status": i_stat,
                                "updated_at": datetime.now(IST).isoformat()
                            }).eq("id", i_row['id']).execute()
                            st.cache_data.clear()
                            st.rerun() # Once updated to "Received", it disappears from this list

            # --- OPTIONAL: HISTORY SECTION ---
            if not received_items.empty:
                with st.expander("View Received History"):
                    for _, c_row in received_items.iterrows():
                        st.write(f"✅ {c_row['item_name']} (Received)")
