import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Anchor Portal | BGEngg ERP", layout="wide", page_icon="⚓")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=10)
def get_projects():
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

@st.cache_data(ttl=10)
def get_purchase_items():
    try:
        res = conn.table("purchase_orders").select("*").execute()
        if res.data:
            return pd.DataFrame(res.data)
        else:
            # SAFETY: Create empty DF with columns to prevent KeyError
            return pd.DataFrame(columns=['job_no', 'item_name', 'specs', 'status', 'purchase_reply'])
    except Exception as e:
        # SAFETY: Fallback if table doesn't exist yet
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
    # Ensure date conversion
    df_display['enquiry_date'] = pd.to_datetime(df_display['enquiry_date']).dt.tz_localize(None)
    df_display['aging_days'] = (today - df_display['enquiry_date']).dt.days

    st.subheader("🚀 Live Action Summary")
    pend_quotes = df_display[df_display['status'].isin(['Enquiry', 'Estimation'])]
    pend_drawings = df_display[(df_display['status'] == 'Won') & (df_display['drawing_status'] != 'Approved') & (df_display['drawing_status'] != 'NA')]
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"📋 **Pending Quotations ({len(pend_quotes)})**")
        if not pend_quotes.empty:
            st.dataframe(pend_quotes[['client_name', 'project_description', 'aging_days']].rename(columns={'aging_days': 'Days Pending'}), hide_index=True)
    with col2:
        st.warning(f"📐 **Pending Drawings ({len(pend_drawings)})**")
        if not pend_drawings.empty:
            st.dataframe(pend_drawings[['client_name', 'drawing_status', 'aging_days']].rename(columns={'aging_days': 'Days Since Won'}), hide_index=True)
    st.markdown("---")

# --- 4. MAIN TABS ---
tabs = st.tabs(["📝 New Entry", "📂 Pipeline", "📐 Drawings", "🛒 Purchase Status", "📊 Download"])

# --- TAB 1: NEW ENTRY ---
with tabs[0]:
    st.subheader("Register New Project Enquiry")
    with st.form("new_project_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        u_client = col1.text_input("Client Name")
        u_proj = col2.text_input("Project Description")
        c1, c2, c3 = st.columns(3)
        u_date = c1.date_input("Enquiry Date", value=datetime.now())
        u_contact = c2.text_input("Contact Person Name")
        u_phone = c3.text_input("Contact Phone")
        u_notes = st.text_area("Initial Remarks")
        if st.form_submit_button("Log Enquiry"):
            if u_client and u_proj:
                conn.table("anchor_projects").insert({
                    "client_name": u_client, "project_description": u_proj,
                    "anchor_person": anchor_choice, "enquiry_date": str(u_date),
                    "contact_person": u_contact, "contact_phone": u_phone,
                    "special_notes": u_notes, "status": "Enquiry", "drawing_status": "Pending"
                }).execute()
                st.success("Enquiry Logged!"); st.rerun()

# --- TAB 2: PIPELINE (The Trigger) ---
with tabs[1]:
    st.subheader("Sales Lifecycle & Item-wise Purchase Trigger")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            with st.expander(f"💼 {row['client_name']} | Status: {row['status']}"):
                st.markdown("##### 💰 Sales Info")
                c1, c2, c3 = st.columns(3)
                u_val = c1.number_input("Value (₹)", value=float(row['estimated_value'] or 0), key=f"val_{row['id']}")
                u_qref = c2.text_input("Quote Ref.", value=row['quote_ref'] or "", key=f"qref_{row['id']}")
                u_qdate = c3.date_input("Quote Date", value=pd.to_datetime(row['quote_date']).date() if row['quote_date'] else datetime.now(), key=f"qdt_{row['id']}")
                
                # Check if current status is valid for the list
                current_st = row['status'] if row['status'] in ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"] else "Enquiry"
                new_status = st.selectbox("Update Stage", ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"], 
                            index=["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"].index(current_st), key=f"st_{row['id']}")
                
                st.markdown("---")
                st.markdown("##### 🛒 Item-wise Purchase Trigger")
                pc1, pc2 = st.columns([1, 2])
                u_job = pc1.text_input("Job No.", value=row['job_no'] or "", key=f"pjob_{row['id']}")
                u_trig = pc1.checkbox("Trigger Purchase?", value=row['purchase_trigger'], key=f"ptrig_{row['id']}")
                
                # Item Addition Container
                with st.container(border=True):
                    st.caption("Add specific items for Purchase")
                    ic1, ic2, ic3 = st.columns([2, 1, 1])
                    i_name = ic1.text_input("Item Name", key=f"iname_{row['id']}")
                    i_spec = ic2.text_input("Qty/Specs", key=f"ispec_{row['id']}")
                    if ic3.button("➕ Add Item", key=f"ibtn_{row['id']}"):
                        if i_name and u_job:
                            conn.table("purchase_orders").insert({
                                "job_no": u_job, "item_name": i_name, "specs": i_spec, "status": "Triggered"
                            }).execute()
                            st.toast(f"Added {i_name}")
                            st.rerun()
                        else: st.warning("Ensure Job No & Item Name are filled")

                if st.button("Save All Updates", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "estimated_value": u_val, "quote_ref": u_qref, "quote_date": str(u_qdate),
                        "status": new_status, "job_no": u_job, "purchase_trigger": u_trig
                    }).eq("id", row['id']).execute(); st.rerun()

# --- TAB 3: DRAWINGS ---
with tabs[2]:
    st.subheader("Drawing Control")
    won_projects = df_display[df_display['status'] == 'Won'] if not df_display.empty else pd.DataFrame()
    for index, row in won_projects.iterrows():
        with st.expander(f"📐 DRAWING: {row['client_name']}"):
            c1, c2 = st.columns(2)
            d_ref = c1.text_input("Drawing Ref No.", value=row['drawing_ref'] or "", key=f"dr_{row['id']}")
            d_stat = c2.selectbox("Status", ["Pending", "Drafting", "Approved", "NA"], key=f"ds_{row['id']}")
            if st.button("Save Drawing Info", key=f"dbtn_{row['id']}"):
                conn.table("anchor_projects").update({"drawing_ref": d_ref, "drawing_status": d_stat}).eq("id", row['id']).execute()
                st.rerun()

# --- TAB 4: PURCHASE STATUS (The Fix) ---
with tabs[3]:
    st.subheader("📦 Item-wise Purchase Feedback")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            # Check if job_no exists in the anchor_projects row AND in the df_pur columns
            if row['job_no'] and 'job_no' in df_pur.columns:
                job_items = df_pur[df_pur['job_no'] == row['job_no']]
                if not job_items.empty:
                    with st.container(border=True):
                        st.markdown(f"**Job: {row['job_no']} | Client: {row['client_name']}**")
                        h1, h2, h3, h4 = st.columns([2, 1, 2, 1])
                        h1.caption("Item Name")
                        h2.caption("Qty")
                        h3.caption("Purchase Reply")
                        h4.caption("Status")
                        
                        for _, item in job_items.iterrows():
                            c1, c2, c3, c4 = st.columns([2, 1, 2, 1])
                            c1.write(item['item_name'])
                            c2.write(item['specs'])
                            c3.info(item['purchase_reply'] or "No reply")
                            c4.write(item['status'])
                elif row['purchase_trigger']:
                    st.info(f"Job {row['job_no']}: No items listed.")

# --- TAB 5: DOWNLOAD ---
with tabs[4]:
    st.subheader("📊 Data Export")
    if not df_display.empty:
        export_df = df_display.drop(columns=['id'], errors='ignore')
        st.download_button("💾 Download Filtered CSV", data=export_df.to_csv(index=False).encode('utf-8'), file_name=f"BGEngg_{anchor_choice}.csv", mime='text/csv')
        st.dataframe(export_df)
