import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import plotly.express as px

# --- 1. PAGE CONFIG ---
st.set_page_config(page_title="Anchor Portal | BGEngg ERP", layout="wide", page_icon="⚓")

# --- 2. PASSWORD PROTECTION ---
def check_password():
    def password_entered():
        if st.session_state["password"] == "1234": 
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔑 Enter Master Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    return True

if not check_password():
    st.stop()

# --- 3. DATABASE CONNECTION ---
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
            if 'created_at' in df_p.columns:
                df_p['created_at'] = pd.to_datetime(df_p['created_at'])
            return df_p
        return pd.DataFrame(columns=['job_no', 'item_name', 'specs', 'status', 'purchase_reply', 'created_at'])
    except:
        return pd.DataFrame(columns=['job_no', 'item_name', 'specs', 'status', 'purchase_reply', 'created_at'])

df = get_projects()
df_pur = get_purchase_items()

# --- 4. SIDEBAR CONFIGURATION ---
st.sidebar.title("🎯 Anchor Control")
anchor_choice = st.sidebar.selectbox("Select Your Profile", ["Ammu", "Kishore"])

# Filter Data by Anchor
df_display = df[df['anchor_person'] == anchor_choice] if not df.empty else pd.DataFrame()

# Sidebar: Critical Material Alerts
st.sidebar.divider()
if not df_display.empty and not df_pur.empty:
    won_jobs = df_display[df_display['status'] == "Won"]['job_no'].unique()
    pending_items = df_pur[(df_pur['job_no'].isin(won_jobs)) & (~df_pur['status'].isin(["Ordered", "Received"]))]
    
    if not pending_items.empty:
        st.sidebar.error(f"⚠️ **{len(pending_items)} Pending Orders**")
        if st.sidebar.checkbox("Show Quick List", key="sidebar_list"):
            for _, item in pending_items.iterrows():
                st.sidebar.caption(f"📍 {item['job_no']}: {item['item_name']}")
    else:
        st.sidebar.success("✅ All Materials Ordered")

# Sidebar: Sync & Search
st.sidebar.divider()
if st.sidebar.button("🔄 Force Refresh Data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

search_query = st.sidebar.text_input("🔍 Quick Search", placeholder="Client, Job, or Desc...", key="sidebar_search")

if search_query and not df_display.empty:
    df_display = df_display[
        df_display['client_name'].str.contains(search_query, case=False, na=False) |
        df_display['job_no'].str.contains(search_query, case=False, na=False) |
        df_display['project_description'].str.contains(search_query, case=False, na=False)
    ]

st.title(f"⚓ {anchor_choice}'s Project Portal")
st.markdown("---")

# --- 5. LIVE ACTION SUMMARY ---
if not df_display.empty:
    today_dt = pd.to_datetime(date.today())
    df_display['enquiry_date_dt'] = pd.to_datetime(df_display['enquiry_date']).dt.tz_localize(None)
    df_display['aging_days'] = (today_dt - df_display['enquiry_date_dt']).dt.days

    st.subheader("🚀 Live Action Summary")
    pend_quotes = df_display[df_display['status'].isin(['Enquiry', 'Estimation'])]
    pend_drawings = df_display[(df_display['status'] == 'Won') & (~df_display['drawing_status'].isin(['Approved', 'NA']))]
    
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

# --- 6. MAIN TABS ---
tabs = st.tabs(["📝 New Entry", "📂 Pipeline", "📐 Drawings", "🛒 Purchase Status", "📊 Analytics"])

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
                st.cache_data.clear(); st.success("Enquiry Logged!"); st.rerun()

# --- TAB 2: PIPELINE ---
with tabs[1]:
    st.subheader("Sales Lifecycle & Project Tracking")
    if not df_display.empty:
        pipeline_stages = ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"]
        
        for index, row in df_display.iterrows():
            is_aging = row['aging_days'] > 7 and row['status'] in ["Enquiry", "Estimation"]
            aging_label = f" [⚠️ {row['aging_days']} DAYS OLD]" if is_aging else ""
            
            with st.expander(f"{'🔥' if is_aging else '📋'} {row['client_name']} | Job: {row['job_no'] or 'N/A'}{aging_label}"):
                
                # PO Details
                pd1, pd2 = st.columns(2)
                u_po_no = pd1.text_input("PO Number", value=row.get('po_no') or "", key=f"pono_{row['id']}")
                u_po_date_actual = pd2.date_input("PO Date", value=pd.to_datetime(row.get('po_date')).date() if pd.notnull(row.get('po_date')) else date.today(), key=f"podt_{row['id']}")
                
                # Delivery Metrics
                d1, d2, d3 = st.columns(3)
                curr_po_del = pd.to_datetime(row.get('po_delivery_date')).date() if pd.notnull(row.get('po_delivery_date')) else date.today()
                curr_rev_del = pd.to_datetime(row.get('revised_delivery_date')).date() if pd.notnull(row.get('revised_delivery_date')) else curr_po_del
                u_po_del = d1.date_input("Original PO Del. Date", value=curr_po_del, key=f"po_del_date_{row['id']}")
                u_rev_del = d2.date_input("Revised Del. Date", value=curr_rev_del, key=f"rev_del_date_{row['id']}")
                
                days_to_go = (u_rev_del - date.today()).days
                d3.metric("Days to Dispatch", f"{days_to_go} Days", delta=days_to_go)

                st.divider()
                
                # Financials & Quote
                f1, f2, f3 = st.columns(3)
                u_val = f1.number_input("Est. Value (₹)", value=float(row.get('estimated_value') or 0), key=f"val_{row['id']}")
                u_qref = f2.text_input("Quote Ref.", value=row.get('quote_ref') or "", key=f"qref_{row['id']}")
                u_qdate = f3.date_input("Quote Date", value=pd.to_datetime(row['quote_date']).date() if row['quote_date'] else datetime.now(), key=f"qdt_{row['id']}")
                
                # Status Update
                new_status = st.selectbox("Update Stage", pipeline_stages, index=pipeline_stages.index(row['status']) if row['status'] in pipeline_stages else 0, key=f"st_select_{row['id']}")
                
                # Purchase Trigger Sub-section
                st.markdown("##### 🛒 Item-wise Purchase Trigger")
                pc1, pc2 = st.columns([1, 2])
                u_job = pc1.text_input("Job No.", value=row['job_no'] or "", key=f"pjob_{row['id']}")
                u_trig = pc1.checkbox("Trigger Purchase?", value=row['purchase_trigger'], key=f"ptrig_{row['id']}")
                
                with st.container(border=True):
                    ic1, ic2, ic3 = st.columns([2, 1, 1])
                    i_name = ic1.text_input("Material Name", key=f"iname_{row['id']}")
                    i_spec = ic2.text_input("Qty / Specs", key=f"ispec_{row['id']}")
                    if ic3.button("➕ Add Item", key=f"ibtn_{row['id']}", use_container_width=True):
                        if i_name and u_job:
                            conn.table("purchase_orders").insert({"job_no": u_job.strip().upper(), "item_name": i_name, "specs": i_spec, "status": "Triggered"}).execute()
                            conn.table("anchor_projects").update({"purchase_trigger": True, "job_no": u_job.strip().upper()}).eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()

                if st.button("Save Project Status", key=f"up_btn_{row['id']}", type="primary", use_container_width=True):
                    update_payload = {
                        "po_no": u_po_no, "po_date": str(u_po_date_actual),
                        "estimated_value": u_val, "quote_ref": u_qref, "quote_date": str(u_qdate),
                        "status": new_status, "job_no": u_job.strip().upper(), "purchase_trigger": u_trig,
                        "po_delivery_date": str(u_po_del), "revised_delivery_date": str(u_rev_del)
                    }
                    if new_status == "Won" and row['status'] != "Won":
                        update_payload["won_date"] = str(date.today())
                    
                    conn.table("anchor_projects").update(update_payload).eq("id", row['id']).execute()
                    st.cache_data.clear(); st.rerun()
                    st.divider()
with st.expander("⚠️ Danger Zone"):
    st.warning("Deleting a project is permanent. This will not delete related Purchase Orders.")
    if st.checkbox(f"Confirm Delete for {row['client_name']}?", key=f"del_check_{row['id']}"):
        if st.button("❌ Permanently Delete", key=f"del_btn_{row['id']}", type="primary", use_container_width=True):
            conn.table("anchor_projects").delete().eq("id", row['id']).execute()
            st.cache_data.clear()
            st.success("Project Deleted.")
            st.rerun()

# --- TAB 3: DRAWINGS ---
with tabs[2]:
    st.subheader("Drawing Control")
    won_projects = df_display[df_display['status'] == 'Won'] if not df_display.empty else pd.DataFrame()
    for index, row in won_projects.iterrows():
        with st.expander(f"📐 DRAWING: {row['client_name']}"):
            c1, c2 = st.columns(2)
            d_ref = c1.text_input("Drawing Ref No.", value=row['drawing_ref'] or "", key=f"dr_{row['id']}")
            d_stat = c2.selectbox("Status", ["Pending", "Drafting", "Approved", "NA"], 
                                 index=["Pending", "Drafting", "Approved", "NA"].index(row['drawing_status']) if row['drawing_status'] in ["Pending", "Drafting", "Approved", "NA"] else 0, 
                                 key=f"ds_{row['id']}")
            if st.button("Save Drawing Info", key=f"dbtn_{row['id']}"):
                conn.table("anchor_projects").update({"drawing_ref": d_ref, "drawing_status": d_stat}).eq("id", row['id']).execute()
                st.cache_data.clear(); st.rerun()

# --- TAB 4: PURCHASE STATUS ---
with tabs[3]:
    st.subheader("📦 Item-wise Purchase Feedback")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            if row['job_no']:
                job_items = df_pur[df_pur['job_no'] == row['job_no'].strip().upper()] if not df_pur.empty else pd.DataFrame()
                if not job_items.empty:
                    with st.container(border=True):
                        st.markdown(f"#### Job: {row['job_no']} | {row['client_name']}")
                        for _, item in job_items.iterrows():
                            c1, c2, c3, c4 = st.columns([2, 1, 3, 1])
                            c1.write(f"🔹 {item['item_name']}")
                            c2.write(item['specs'])
                            c3.info(item['purchase_reply'] or "⌛ No reply yet")
                            if item['status'] == "Received": c4.success("Received")
                            else: c4.warning(item['status'])

# --- TAB 5: ANALYTICS ---
with tabs[4]:
    st.subheader("📊 Business Intelligence")
    if not df_display.empty:
        # Pipeline Pie Chart
        st.markdown("##### Pipeline Status")
        fig_pie = px.pie(df_display, names='status', hole=0.4)
        st.plotly_chart(fig_pie, use_container_width=True)
        
        # CSV Export
        st.divider()
        st.markdown("##### Master Export")
        export_df = df_display.drop(columns=['id'], errors='ignore')
        st.download_button("💾 Download CSV", data=export_df.to_csv(index=False).encode('utf-8'), file_name=f"BGE_{anchor_choice}.csv", key="download_csv")
        st.dataframe(export_df, use_container_width=True)
