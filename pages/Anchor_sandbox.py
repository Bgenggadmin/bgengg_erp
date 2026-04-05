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

# --- 3. DATABASE CONNECTION & DATA LOADING ---
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=0) 
def get_projects():
    try:
        res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading projects: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=2)
def get_purchase_items():
    try:
        res = conn.table("purchase_orders").select("*").execute()
        if res.data:
            df_p = pd.DataFrame(res.data)
            # Safe string cleaning for Job Numbers
            if 'job_no' in df_p.columns:
                df_p['job_no'] = df_p['job_no'].fillna('').astype(str).str.strip().str.upper()
            if 'created_at' in df_p.columns:
                df_p['created_at'] = pd.to_datetime(df_p['created_at'], errors='coerce')
            return df_p
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

# Initialize Data Safely
df = get_projects()
df_pur = get_purchase_items()
today_dt = pd.to_datetime(date.today()).tz_localize(None)

# --- 4. SIDEBAR CONFIGURATION ---
st.sidebar.title("🎯 Anchor Control")
anchor_choice = st.sidebar.selectbox("Select Your Profile", ["Ammu", "Kishore"])

# Line 66: This will now work because df is guaranteed to exist
if not df.empty and 'anchor_person' in df.columns:
    df_display = df[df['anchor_person'] == anchor_choice]
else:
    df_display = pd.DataFrame()

# Sidebar: Critical Material Alerts
st.sidebar.divider()
if not df_display.empty and not df_pur.empty:
    # Safe conversion for won_jobs
    won_jobs = df_display[df_display['status'] == "Won"]['job_no'].fillna('').astype(str).str.strip().str.upper().unique()
    
    # Filter pending items using the cleaned list
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
st.sidebar.caption(f"🕒 Last Sync: {datetime.now().strftime('%H:%M:%S')}")
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

# --- TAB 1: NEW ENTRY (Updated with Equipment Type) ---
with tabs[0]:
    st.subheader("Register New Project Enquiry")
    # Form must be correctly indented under the 'with' block
    with st.form("new_project_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        u_client = col1.text_input("Client Name")
        u_proj = col2.text_input("Project Description")
        
        c1, c2, c3 = st.columns(3)
        u_date = c1.date_input("Enquiry Date", value=datetime.now())
        # This dropdown must stay indented inside the form
        u_equip_type = c2.selectbox("Equipment Type", 
                                    ["Storage Tank", "Reactor", "Condenser", "Filter", "RCVD", "Other"])
        u_contact = c3.text_input("Contact Person Name")
        
        u_phone = col1.text_input("Contact Phone")
        u_notes = st.text_area("Initial Remarks")
        
        # The submit button is the boundary of the form indentation
        if st.form_submit_button("Log Enquiry"):
            if u_client and u_proj:
                conn.table("anchor_projects").insert({
                    "client_name": u_client, 
                    "project_description": u_proj,
                    "equipment_type": u_equip_type, # New Column
                    "anchor_person": anchor_choice, 
                    "enquiry_date": str(u_date),
                    "contact_person": u_contact, 
                    "contact_phone": u_phone,
                    "special_notes": u_notes, 
                    "status": "Enquiry", 
                    "drawing_status": "Pending"
                }).execute()
                st.cache_data.clear()
                st.success("Enquiry Logged!")
                st.rerun()

# --- TAB 2: PIPELINE (UPDATED) ---
with tabs[1]:
    st.subheader("Sales Lifecycle & Project Tracking")
    if not df_display.empty:
        view_col, stage_col = st.columns([1, 2])
        bulk_mode = view_col.toggle("⚡ Bulk Update Mode", value=False)
        pipeline_stages = ["All", "Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"]
        selected_stage = stage_col.radio("Filter Stage", pipeline_stages, horizontal=True)

        df_pipeline = df_display if selected_stage == "All" else df_display[df_display['status'] == selected_stage]

        if bulk_mode:
            with st.form("bulk_update_form"):
                selected_ids = []
                for _, row in df_pipeline.iterrows():
                    cols = st.columns([0.5, 2, 2, 2])
                    if cols[0].checkbox("", key=f"bulk_{row['id']}"): selected_ids.append(row['id'])
                    cols[1].write(f"**{row['client_name']}**")
                    cols[2].write(f"{row['project_description'][:40]}...")
                    cols[3].caption(f"Current: {row['status']}")
                new_bulk_status = st.selectbox("Move selected to:", pipeline_stages[1:])
                if st.form_submit_button("🚀 Execute Bulk Update"):
                    if selected_ids:
                        update_payload = {"status": new_bulk_status, "status_updated_at": datetime.now().isoformat()}
                        if new_bulk_status == "Won": update_payload["won_date"] = str(date.today())
                        conn.table("anchor_projects").update(update_payload).in_("id", selected_ids).execute()
                        st.cache_data.clear(); st.success("Bulk Update Complete!"); st.rerun()
        else:
            for index, row in df_pipeline.iterrows():
                is_aging = row['aging_days'] > 7 and row['status'] in ["Enquiry", "Estimation"]
                aging_label = f" [⚠️ {row['aging_days']} DAYS OLD]" if is_aging else ""
                
                # --- MODIFIED ROW HEADER ---
                client_part = f"{'🔥' if is_aging else '📋'} {row['client_name']}"
                job_part = f" | Job: {row['job_no'] or 'N/A'}"
                desc_part = f" | 📝 {row['project_description'][:50]}..." if row['project_description'] else ""
                
                with st.expander(f"{client_part}{job_part}{desc_part}{aging_label}"):
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
                    
                    # Financials
                    f1, f2, f3, f4 = st.columns(4)
                    u_val = f1.number_input("Est. Value (₹)", value=float(row.get('estimated_value') or 0), key=f"val_{row['id']}")
                    u_act_val = f2.number_input("Actual PO Value (₹)", value=float(row.get('actual_value') or 0), key=f"act_val_{row['id']}")
                    u_qref = f3.text_input("Quote Ref.", value=row.get('quote_ref') or "", key=f"qref_{row['id']}")
                    # 1. Convert to a pandas datetime object safely
                    raw_quote_date = pd.to_datetime(row.get('quote_date'))

                    # 2. Check if it is a valid date (not null/NaT)
                    if pd.notnull(raw_quote_date):
                        initial_q_date = raw_quote_date.date()
                    else:
                        initial_q_date = date.today() # Fallback to today if empty

                    # 3. Use the safe variable in the widget
                    u_qdate = f4.date_input("Quote Date", value=initial_q_date, key=f"qdt_{row['id']}")
                    
                    if row['status'] == "Won" and u_act_val > 0:
                        variance = u_act_val - u_val
                        st.markdown(f"**Margin Variance:** :{'green' if variance >= 0 else 'red'}[₹{variance:,.0f}]")

                    new_status = st.selectbox("Update Stage", pipeline_stages[1:], index=pipeline_stages[1:].index(row['status']) if row['status'] in pipeline_stages[1:] else 0, key=f"st_select_{row['id']}")
                    
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

                    col_save, col_del = st.columns([3, 1])
                    if col_save.button("Save Project Status", key=f"up_btn_{row['id']}", type="primary", use_container_width=True):
                        update_payload = {
                            "po_no": u_po_no, "po_date": str(u_po_date_actual),
                            "estimated_value": u_val, "actual_value": u_act_val,
                            "quote_ref": u_qref, "quote_date": str(u_qdate),
                            "status": new_status, "job_no": u_job.strip().upper(), "purchase_trigger": u_trig,
                            "po_delivery_date": str(u_po_del), "revised_delivery_date": str(u_rev_del)
                        }
                        if new_status != row['status']:
                            update_payload["status_updated_at"] = datetime.now().isoformat()
                            if new_status == "Won": update_payload["won_date"] = str(date.today())
                        
                        conn.table("anchor_projects").update(update_payload).eq("id", row['id']).execute()
                        st.cache_data.clear(); st.rerun()

                    with col_del.popover("🗑️ Delete"):
                        st.warning("Delete this project permanently?")
                        if st.button("Confirm Delete", key=f"del_{row['id']}", type="primary"):
                            conn.table("anchor_projects").delete().eq("id", row['id']).execute()
                            st.cache_data.clear(); st.rerun()

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
                            created_at = pd.to_datetime(item.get('created_at')).tz_localize(None) if 'created_at' in item else today_dt
                            order_age = (today_dt - created_at).days
                            c1, c2, c3, c4 = st.columns([2, 1, 3, 1])
                            c1.write(f"{'🛑' if order_age > 2 and item['status'] == 'Triggered' else '🔹'} {item['item_name']}")
                            c2.write(item['specs'])
                            c3.info(item['purchase_reply'] or "⌛ No reply yet")
                            if item['status'] == "Received": c4.success("Received")
                            else: c4.warning(item['status'])

# --- TAB 5: ANALYTICS ---
with tabs[4]:
    st.subheader("📊 Business Intelligence")
    if not df_display.empty:
        won_df = df_display[df_display['status'] == "Won"].copy()
        lost_count = len(df_display[df_display['status'] == "Lost"])
        win_rate = (len(won_df) / (len(won_df) + lost_count) * 100) if (len(won_df) + lost_count) > 0 else 0
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Win Rate", f"{win_rate:.1f}%")
        m2.metric("Won Value", f"₹{won_df['actual_value'].sum():,.0f}")
        
        if not won_df.empty and 'won_date' in won_df.columns:
            won_df['won_date_dt'] = pd.to_datetime(won_df['won_date']).dt.tz_localize(None)
            won_df['cycle_time'] = (won_df['won_date_dt'] - won_df['enquiry_date_dt']).dt.days
            avg_cycle = won_df['cycle_time'].mean()
            m3.metric("Avg. Sales Cycle", f"{int(avg_cycle)} Days" if not pd.isna(avg_cycle) else "N/A")
            
            won_df['delivery_month'] = pd.to_datetime(won_df['revised_delivery_date']).dt.strftime('%b %Y')
            monthly_data = won_df.groupby('delivery_month')['actual_value'].sum().reset_index()
            st.markdown("##### 📅 Revenue Forecast (by Delivery Month)")
            fig_month = px.bar(monthly_data, x='delivery_month', y='actual_value', text_auto='.2s')
            st.plotly_chart(fig_month, use_container_width=True)

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### Pipeline Status")
            fig_pie = px.pie(df_display, names='status', hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            st.markdown("##### Master Export")
            export_df = df_display.drop(columns=['id'], errors='ignore')
            st.download_button("💾 Download CSV", data=export_df.to_csv(index=False).encode('utf-8'), file_name=f"BGE_{anchor_choice}.csv", key="master_csv_dl")
            st.dataframe(export_df, use_container_width=True)
