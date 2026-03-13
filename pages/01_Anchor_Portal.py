import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Anchor Portal | BGEngg ERP", layout="wide", page_icon="⚓")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=5) # Reduced TTL for faster updates
def get_projects():
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

@st.cache_data(ttl=5)
def get_purchase_items():
    try:
        res = conn.table("purchase_orders").select("*").execute()
        if res.data:
            return pd.DataFrame(res.data)
        return pd.DataFrame(columns=['job_no', 'item_name', 'specs', 'status', 'purchase_reply'])
    except:
        return pd.DataFrame(columns=['job_no', 'item_name', 'specs', 'status', 'purchase_reply'])

df = get_projects()
df_pur = get_purchase_items()

# --- 2. SIDEBAR CONFIGURATION ---
st.sidebar.title("🎯 Anchor Control")
anchor_choice = st.sidebar.selectbox("Select Your Profile", ["Ammu", "Kishore"])
st.sidebar.divider()
search_query = st.sidebar.text_input("Search Client, Job, or Desc", placeholder="Type here...")

# Filtering Logic
df_display = df[df['anchor_person'] == anchor_choice] if not df.empty else pd.DataFrame()
if search_query and not df_display.empty:
    df_display = df_display[
        df_display['client_name'].str.contains(search_query, case=False, na=False) |
        df_display['job_no'].str.contains(search_query, case=False, na=False) |
        df_display['project_description'].str.contains(search_query, case=False, na=False)
    ]

st.title(f"⚓ {anchor_choice}'s Project Portal")
st.markdown("---")

# --- 3. LIVE ACTION SUMMARY ---
if not df_display.empty:
    today = pd.to_datetime(datetime.now().date())
    df_display['enquiry_date'] = pd.to_datetime(df_display['enquiry_date']).dt.tz_localize(None)
    df_display['aging_days'] = (today - df_display['enquiry_date']).dt.days

    st.subheader("🚀 Live Action Summary")
    pend_quotes = df_display[df_display['status'].isin(['Enquiry', 'Estimation'])]
    pend_drawings = df_display[(df_display['status'] == 'Won') & (df_display['drawing_status'] != 'Approved') & (df_display['drawing_status'] != 'NA')]
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"📋 **Pending Quotations ({len(pend_quotes)})**")
        if not pend_quotes.empty:
            st.dataframe(pend_quotes[['client_name', 'project_description', 'aging_days']].rename(columns={'aging_days': 'Days Pending'}), hide_index=True, use_container_width=True)
    with col2:
        st.warning(f"📐 **Pending Drawings ({len(pend_drawings)})**")
        if not pend_drawings.empty:
            st.dataframe(pend_drawings[['client_name', 'drawing_status', 'aging_days']].rename(columns={'aging_days': 'Days Since Won'}), hide_index=True, use_container_width=True)
    st.markdown("---")

# --- 4. MAIN TABS ---
tabs = st.tabs(["📝 New Entry", "📂 Pipeline", "📐 Drawings", "🛒 Purchase Status", "📊 Download"])

# --- TAB 2: PIPELINE (Where you add items) ---
with tabs[1]:
    st.subheader("Sales Lifecycle & Item-wise Purchase Trigger")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            with st.expander(f"💼 {row['client_name']} | Job: {row['job_no'] or 'N/A'}"):
                c1, c2, c3 = st.columns(3)
                u_val = c1.number_input("Value (₹)", value=float(row['estimated_value'] or 0), key=f"val_{row['id']}")
                u_qref = c2.text_input("Quote Ref.", value=row['quote_ref'] or "", key=f"qref_{row['id']}")
                u_qdate = c3.date_input("Quote Date", value=pd.to_datetime(row['quote_date']).date() if row['quote_date'] else datetime.now(), key=f"qdt_{row['id']}")
                
                status_list = ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"]
                current_st = row['status'] if row['status'] in status_list else "Enquiry"
                new_status = st.selectbox("Update Stage", status_list, index=status_list.index(current_st), key=f"st_{row['id']}")
                
                st.markdown("---")
                st.markdown("##### 🛒 Item-wise Purchase Trigger")
                pc1, pc2 = st.columns([1, 2])
                u_job = pc1.text_input("Job No.", value=row['job_no'] or "", key=f"pjob_{row['id']}")
                u_trig = pc1.checkbox("Trigger Purchase?", value=row['purchase_trigger'], key=f"ptrig_{row['id']}")
                
                # Material Entry Form
                with st.container(border=True):
                    st.write("**Add Individual Material Item:**")
                    ic1, ic2, ic3 = st.columns([2, 1, 1])
                    i_name = ic1.text_input("Material Name", key=f"iname_{row['id']}")
                    i_spec = ic2.text_input("Qty / Specs", key=f"ispec_{row['id']}")
                    if ic3.button("➕ Add Item", key=f"ibtn_{row['id']}", use_container_width=True):
                        if i_name and u_job:
                            conn.table("purchase_orders").insert({"job_no": u_job, "item_name": i_name, "specs": i_spec, "status": "Triggered"}).execute()
                            st.success(f"Added {i_name} for Job {u_job}")
                            st.rerun()
                        else: st.error("Enter Job No & Item Name")
                    
                    # Show items already added for THIS job
                    if u_job and not df_pur.empty:
                        job_items_mini = df_pur[df_pur['job_no'] == u_job]
                        if not job_items_mini.empty:
                            st.caption("Items already triggered:")
                            st.dataframe(job_items_mini[['item_name', 'specs', 'status']], hide_index=True, use_container_width=True)

                if st.button("Save Project Status", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "estimated_value": u_val, "quote_ref": u_qref, "quote_date": str(u_qdate),
                        "status": new_status, "job_no": u_job, "purchase_trigger": u_trig
                    }).eq("id", row['id']).execute(); st.rerun()

# --- TAB 4: PURCHASE STATUS (Feedback View) ---
with tabs[3]:
    st.subheader("📦 Item-wise Purchase Feedback")
    if not df_display.empty:
        # Sort display by Job No
        df_sorted = df_display.dropna(subset=['job_no'])
        for index, row in df_sorted.iterrows():
            job_items = df_pur[df_pur['job_no'] == row['job_no']] if 'job_no' in df_pur.columns else pd.DataFrame()
            
            if not job_items.empty:
                with st.container(border=True):
                    st.markdown(f"#### Job: {row['job_no']} | {row['client_name']}")
                    st.write(f"Description: {row['project_description']}")
                    
                    # Layout Header
                    cols = st.columns([2, 1, 3, 1])
                    cols[0].label("Item")
                    cols[1].label("Qty")
                    cols[2].label("Purchase Reply")
                    cols[3].label("Status")
                    
                    for _, item in job_items.iterrows():
                        c1, c2, c3, c4 = st.columns([2, 1, 3, 1])
                        c1.write(f"🔹 {item['item_name']}")
                        c2.write(item['specs'])
                        
                        if item['purchase_reply']:
                            c3.info(item['purchase_reply'])
                        else:
                            c3.write("⌛ Pending response")
                        
                        # Color coding status
                        s = item['status']
                        if s == "Received": c4.success(s)
                        elif s == "Delayed": c4.error(s)
                        else: c4.warning(s)
            elif row['purchase_trigger']:
                st.info(f"Job {row['job_no']}: Purchase Triggered, but no items added in Pipeline tab.")

# --- (Keep TAB 1, 3, and 5 as per your original script) ---
