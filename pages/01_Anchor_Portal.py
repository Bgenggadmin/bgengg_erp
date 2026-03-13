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

df = get_projects()

# --- 2. SIDEBAR CONFIGURATION ---
st.sidebar.title("🎯 Anchor Control")
anchor_choice = st.sidebar.selectbox("Select Your Profile", ["Ammu", "Kishore"])

st.sidebar.divider()
st.sidebar.subheader("🔍 Global Search")
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
if search_query:
    st.caption(f"🔎 Filtering for: '{search_query}'")
st.markdown("---")

# --- 3. LIVE ACTION SUMMARY (SINGLE BLOCK) ---
if not df_display.empty:
    today = pd.to_datetime(datetime.now().date())
    df_display['enquiry_date'] = pd.to_datetime(df_display['enquiry_date']).dt.tz_localize(None)
    df_display['aging_days'] = (today - df_display['enquiry_date']).dt.days

    st.subheader("🚀 Live Action Summary")
    
    # Logic: Quotes are Enquiry/Estimation stages
    pend_quotes = df_display[df_display['status'].isin(['Enquiry', 'Estimation'])]
    
    # Logic: Drawings ONLY after WON and not yet Approved
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
        else:
            st.write("No drawings required (None in 'Won' stage).")
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

# --- TAB 2: PIPELINE (Updated with Item-wise Trigger) ---
with tabs[1]:
    st.subheader("Sales Lifecycle & Item-wise Purchase Trigger")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            with st.expander(f"💼 {row['client_name']} | {row['project_description']}"):
                # ... [Keep your existing Sales Info columns here] ...
                
                st.markdown("---")
                st.markdown("##### 🛒 Item-wise Purchase Trigger")
                
                # 1. Add New Item Form
                with st.form(key=f"item_add_{row['id']}", clear_on_submit=True):
                    ic1, ic2, ic3 = st.columns([2, 1, 1])
                    new_item = ic1.text_input("Add Critical Item", placeholder="e.g. 10HP Motor")
                    item_qty = ic2.text_input("Qty/Spec")
                    if ic3.form_submit_button("➕ Add Item"):
                        if new_item and row['job_no']:
                            conn.table("purchase_orders").insert({
                                "job_no": row['job_no'],
                                "item_name": new_item,
                                "specs": item_qty,
                                "status": "Triggered"
                            }).execute()
                            st.toast(f"Added {new_item}")
                            st.rerun()
                        else:
                            st.warning("Ensure Job No. is saved before adding items.")

                # 2. Display existing items for this job
                if row['job_no']:
                    items_res = conn.table("purchase_orders").select("*").eq("job_no", row['job_no']).execute()
                    if items_res.data:
                        item_df = pd.DataFrame(items_res.data)
                        st.dataframe(item_df[['item_name', 'specs', 'status', 'purchase_reply']], 
                                     hide_index=True, use_container_width=True)

                # 3. Save Project Level Updates
                if st.button("Save Project Status", key=f"up_{row['id']}", type="primary"):
                    conn.table("anchor_projects").update({
                        "status": new_status, "job_no": u_job, "purchase_trigger": True
                    }).eq("id", row['id']).execute(); st.rerun()

# --- TAB 3: DRAWINGS (FIXED FOR ALL) ---
with tabs[2]:
    st.subheader("Drawing Control")
    if not df_display.empty:
        won_projects = df_display[df_display['status'] == 'Won']
        other_projects = df_display[df_display['status'] != 'Won']

        if won_projects.empty:
            st.info("Drawing entries will appear here once project status is updated to **'Won'** in the Pipeline.")
        
        for index, row in won_projects.iterrows():
            with st.expander(f"📐 DRAWING: {row['client_name']} ({row['drawing_status']})", expanded=True):
                c1, c2 = st.columns(2)
                d_ref = c1.text_input("Drawing Ref No.", value=row['drawing_ref'] or "", key=f"dr_{row['id']}")
                d_stat = c2.selectbox("Status", ["Pending", "Drafting", "Approved", "NA"], 
                     index=["Pending", "Drafting", "Approved", "NA"].index(row['drawing_status']) if row['drawing_status'] in ["Pending", "Drafting", "Approved", "NA"] else 0, key=f"ds_{row['id']}")
                d_notes = st.text_area("Drawing Notes", value=row['drawing_notes'] or "", key=f"dn_{row['id']}")
                if st.button("Save Drawing Info", key=f"dbtn_{row['id']}", type="primary"):
                    conn.table("anchor_projects").update({"drawing_ref": d_ref, "drawing_status": d_stat, "drawing_notes": d_notes}).eq("id", row['id']).execute()
                    st.rerun()

        if not other_projects.empty:
            with st.expander("⏳ Future Drawings (Pipeline Status: In-Progress)"):
                st.dataframe(other_projects[['client_name', 'project_description', 'status']], hide_index=True, use_container_width=True)

# --- TAB 4: PURCHASE STATUS (Updated for Item-wise Feedback) ---
with tabs[3]:
    st.subheader("📦 Detailed Item-wise Purchase Feedback")
    if not df_display.empty:
        # Get all purchase data at once for speed
        pur_res = conn.table("purchase_orders").select("*").execute()
        all_pur_df = pd.DataFrame(pur_res.data) if pur_res.data else pd.DataFrame()

        for index, row in df_display.iterrows():
            if not all_pur_df.empty and row['job_no']:
                job_items = all_pur_df[all_pur_df['job_no'] == row['job_no']]
                if not job_items.empty:
                    with st.container(border=True):
                        st.markdown(f"**Job: {row['job_no']} | {row['client_name']}**")
                        
                        # Create a clean table for the items
                        for _, item in job_items.iterrows():
                            c1, c2, c3, c4 = st.columns([2, 1, 2, 1])
                            c1.write(f"🔹 {item['item_name']}")
                            c2.caption(f"Qty: {item['specs']}")
                            
                            # Color coding status
                            stat_color = "green" if item['status'] == "Received" else "orange"
                            c4.markdown(f":{stat_color}[**{item['status']}**]")
                            
                            if item['purchase_reply']:
                                c3.info(f"💬 {item['purchase_reply']}")
                            else:
                                c3.write("⌛ No reply yet")
                        st.divider()

# --- TAB 5: DOWNLOAD DATA ---
with tabs[4]:
    st.subheader("📊 Data Export")
    if not df_display.empty:
        export_df = df_display.drop(columns=['id'], errors='ignore')
        csv = export_df.to_csv(index=False).encode('utf-8')
        st.download_button("💾 Download Filtered CSV", data=csv, file_name=f"BGEngg_{anchor_choice}.csv", mime='text/csv', use_container_width=True)
        st.dataframe(export_df, use_container_width=True)
