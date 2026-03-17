import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date

st.set_page_config(page_title="Anchor Portal | BGEngg ERP", layout="wide", page_icon="⚓")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=0) 
def get_projects():
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

@st.cache_data(ttl=2)
def get_purchase_items():
    try:
        res = conn.table("purchase_orders").select("*").execute()
        if res.data:
            df_p = pd.DataFrame(res.data)
            df_p['job_no'] = df_p['job_no'].astype(str).str.strip().str.upper()
            return df_p
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
    today_dt = pd.to_datetime(datetime.now().date())
    df_display['enquiry_date'] = pd.to_datetime(df_display['enquiry_date']).dt.tz_localize(None)
    df_display['aging_days'] = (today_dt - df_display['enquiry_date']).dt.days

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

# --- TAB 2: PIPELINE ---
with tabs[1]:
    st.subheader("Sales Lifecycle & Project Tracking")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            with st.expander(f"💼 {row['client_name']} | Job: {row['job_no'] or 'N/A'}"):
                st.info(f"📝 **Description:** {row['project_description']}")
                
                # --- NEW: DELIVERY DATES & DISPATCH METRIC ---
                d1, d2, d3 = st.columns(3)
                curr_po = pd.to_datetime(row['po_delivery_date']).date() if pd.notnull(row.get('po_delivery_date')) else None
                curr_rev = pd.to_datetime(row['revised_delivery_date']).date() if pd.notnull(row.get('revised_delivery_date')) else None
                
                u_po_date = d1.date_input("Original PO Date", value=curr_po if curr_po else date.today(), key=f"po_date_{row['id']}")
                u_rev_date = d2.date_input("Revised Date", value=curr_rev if curr_rev else u_po_date, key=f"rev_date_{row['id']}")
                
                final_target = u_rev_date if u_rev_date else u_po_date
                if final_target:
                    days_to_go = (final_target - date.today()).days
                    d3.metric("Days to Dispatch", f"{days_to_go} Days", delta=days_to_go, delta_color="normal" if days_to_go > 7 else "inverse")

                st.divider()
                
                # Sales Cycle Inputs
                c1, c2, c3 = st.columns(3)
                u_val = c1.number_input("Value (₹)", value=float(row['estimated_value'] or 0), key=f"val_{row['id']}")
                u_qref = c2.text_input("Quote Ref.", value=row['quote_ref'] or "", key=f"qref_{row['id']}")
                u_qdate = c3.date_input("Quote Date", value=pd.to_datetime(row['quote_date']).date() if row['quote_date'] else datetime.now(), key=f"qdt_{row['id']}")
                
                status_list = ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"]
                current_st = row['status'] if row['status'] in status_list else "Enquiry"
                new_status = st.selectbox("Update Stage", status_list, index=status_list.index(current_st), key=f"st_{row['id']}")
                
                st.markdown("---")
                
                # --- ITEM-WISE PURCHASE & JOB CODE (NESTED AS REQUESTED) ---
                st.markdown("##### 🛒 Item-wise Purchase Trigger")
                pc1, pc2 = st.columns([1, 2])
                u_job = pc1.text_input("Job No.", value=row['job_no'] or "", key=f"pjob_{row['id']}")
                u_trig = pc1.checkbox("Trigger Purchase?", value=row['purchase_trigger'], key=f"ptrig_{row['id']}")
                
                clean_job = str(u_job).strip().upper()

                with st.container(border=True):
                    st.write("**Add Individual Material Item:**")
                    ic1, ic2, ic3 = st.columns([2, 1, 1])
                    i_name = ic1.text_input("Material Name", key=f"iname_{row['id']}")
                    i_spec = ic2.text_input("Qty / Specs", key=f"ispec_{row['id']}")
                    
                    if ic3.button("➕ Add Item", key=f"ibtn_{row['id']}", use_container_width=True):
                        if i_name and clean_job:
                            conn.table("purchase_orders").insert({"job_no": clean_job, "item_name": i_name, "specs": i_spec, "status": "Triggered"}).execute()
                            # Ensure main record is updated with Job No if item is added
                            conn.table("anchor_projects").update({"purchase_trigger": True, "job_no": clean_job}).eq("id", row['id']).execute()
                            st.success(f"Added {i_name}")
                            st.rerun()
                        else: st.error("Job No & Material Name required")
                    
                    if clean_job and not df_pur.empty:
                        job_items_mini = df_pur[df_pur['job_no'] == clean_job]
                        if not job_items_mini.empty:
                            st.caption("Items already triggered:")
                            st.dataframe(job_items_mini[['item_name', 'specs', 'status']], hide_index=True, use_container_width=True)

                if st.button("Save Project Status", key=f"up_{row['id']}", type="primary", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "estimated_value": u_val, "quote_ref": u_qref, "quote_date": str(u_qdate),
                        "status": new_status, "job_no": u_job, "purchase_trigger": u_trig,
                        "po_delivery_date": u_po_date.isoformat(),
                        "revised_delivery_date": u_rev_date.isoformat()
                    }).eq("id", row['id']).execute(); st.rerun()

# --- TAB 3: DRAWINGS ---
with tabs[2]:
    st.subheader("Drawing Control")
    won_projects = df_display[df_display['status'] == 'Won'] if not df_display.empty else pd.DataFrame()
    for index, row in won_projects.iterrows():
        with st.expander(f"📐 DRAWING: {row['client_name']}"):
            c1, c2 = st.columns(2)
            d_ref = c1.text_input("Drawing Ref No.", value=row['drawing_ref'] or "", key=f"dr_{row['id']}")
            d_stat = c2.selectbox("Status", ["Pending", "Drafting", "Approved", "NA"], index=["Pending", "Drafting", "Approved", "NA"].index(row['drawing_status']) if row['drawing_status'] in ["Pending", "Drafting", "Approved", "NA"] else 0, key=f"ds_{row['id']}")
            if st.button("Save Drawing Info", key=f"dbtn_{row['id']}"):
                conn.table("anchor_projects").update({"drawing_ref": d_ref, "drawing_status": d_stat}).eq("id", row['id']).execute()
                st.rerun()

# --- TAB 4: PURCHASE STATUS (Feedback View) ---
with tabs[3]:
    st.subheader("📦 Item-wise Purchase Feedback")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            if row['job_no']:
                curr_job = str(row['job_no']).strip().upper()
                job_items = df_pur[df_pur['job_no'] == curr_job] if not df_pur.empty else pd.DataFrame()
                
                if not job_items.empty:
                    with st.container(border=True):
                        st.markdown(f"#### Job: {curr_job} | {row['client_name']}")
                        for _, item in job_items.iterrows():
                            c1, c2, c3, c4 = st.columns([2, 1, 3, 1])
                            c1.write(f"🔹 {item['item_name']}")
                            c2.write(item['specs'])
                            c3.info(item['purchase_reply'] or "⌛ No reply yet")
                            s = item['status']
                            if s == "Received": c4.success(s)
                            else: c4.warning(s)
                elif row['purchase_trigger']:
                    st.info(f"Job {curr_job}: No specific items added yet.")

# --- TAB 5: DOWNLOAD DATA ---
with tabs[4]:
    st.subheader("📊 Data Export")
    if not df_display.empty:
        export_df = df_display.drop(columns=['id'], errors='ignore')
        csv = export_df.to_csv(index=False).encode('utf-8')
        st.download_button("💾 Download Filtered CSV", data=csv, file_name=f"BGEngg_{anchor_choice}.csv", mime='text/csv')
        st.dataframe(export_df)
