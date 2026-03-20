import streamlit as st
from st_supabase_connection import SupabaseConnection
from datetime import datetime, timedelta
from fpdf import FPDF
from io import BytesIO
import tempfile
import os

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection, ttl=60)

# Aligned with your SQL 'progress_logs' columns
HEADER_FIELDS = [
    "customer", "job_code", "equipment", "po_no", 
    "po_date", "engineer", "po_delivery_date", "exp_dispatch_date"
]

# EXACT MATCH to your SQL column names
MILESTONE_MAP = [
    ("Drawing Submission", "draw_sub", "draw_sub_note"),
    ("Drawing Approval", "draw_app", "draw_app_note"),
    ("RM Status", "rm_status", "rm_note"),
    ("Sub-deliveries", "sub_del", "sub_del_note"),
    ("Fabrication Status", "fab_status", "remarks"),
    ("Buffing Status", "buff_stat", "buff_note"),
    ("Testing Status", "testing", "test_note"),
    ("Dispatch Status", "qc_stat", "qc_note"),
    ("FAT Status", "fat_stat", "fat_note")
]

# --- 2. DATA FETCH ---
@st.cache_data(ttl=300)
def get_anchor_data():
    try:
        j_res = conn.table("job_master").select("job_code").execute()
        # Fallback for customers if job_master is empty
        c_res = conn.table("customer_master").select("name").execute()
        return sorted([d['job_code'] for d in j_res.data]), sorted([d['name'] for d in c_res.data])
    except: return [], []

jobs, customers = get_anchor_data()

# --- 3. MAIN UI ---
tab1, tab2 = st.tabs(["📝 New Entry", "📂 Archive"])

with tab1:
    st.subheader("📋 Project Update")
    f_job = st.selectbox("Job Code (Anchor Portal)", [""] + jobs, key="job_selector")

    if f_job and st.session_state.get('last_selected_job') != f_job:
        m_query = conn.table("job_master").select("*").eq("job_code", f_job).execute()
        l_query = conn.table("progress_logs").select("*").eq("job_code", f_job).order("id", desc=True).limit(1).execute()
        
        master_info = m_query.data[0] if m_query.data else {}
        latest_log = l_query.data[0] if l_query.data else {}

        # The MERGE: Start with History, overwrite ONLY if Master has data
        new_data = {**latest_log} 
        for f in HEADER_FIELDS:
            if f in master_info and master_info[f] not in [None, "", "None"]:
                new_data[f] = master_info[f]
        
        st.session_state.form_data = new_data
        st.session_state.last_selected_job = f_job
        st.rerun()

    if not f_job:
        st.info("Select a Job Code. If fields are empty, add columns to 'job_master' table via SQL.")
        st.stop()

    current_data = st.session_state.get('form_data', {})

    def safe_date(field):
        d = current_data.get(field)
        if not d or d == "None": return datetime.now()
        try: return datetime.strptime(str(d)[:10], "%Y-%m-%d")
        except: return datetime.now()

    with st.form(key=f"form_{f_job}"):
        c1, c2 = st.columns(2)
        # Handle Customer selection safely
        c_val = current_data.get('customer', "")
        c_idx = customers.index(c_val) + 1 if c_val in customers else 0
        f_cust = c1.selectbox("Customer", [""] + customers, index=c_idx)
        f_eq = c2.text_input("Equipment", value=current_data.get('equipment', ""))
        
        c3, c4, c5 = st.columns(3)
        f_po_n = c3.text_input("PO Number", value=current_data.get('po_no', ""))
        f_po_d = c4.date_input("PO Date", value=safe_date('po_date'))
        f_eng = c5.text_input("Engineer", value=current_data.get('engineer', ""))
        
        c6, c7 = st.columns(2)
        f_po_del = c6.date_input("PO Del. Date", value=safe_date('po_delivery_date'))
        f_exp_dis = c7.date_input("Exp. Dispatch Date", value=safe_date('exp_dispatch_date'))
        
        st.divider()
        st.subheader("📊 Milestone Tracking")
        m_responses = {}
        opts = ["Pending", "NA", "In-Progress", "Submitted", "Approved", "Ordered", "Received", "Hold", "Completed"]

        for label, skey, nkey in MILESTONE_MAP:
            # Handle naming inconsistency in SQL (rm_status vs rm_status_prog)
            pk = f"{skey}_prog" if skey != "rm_status" else "rm_status_prog"
            
            r1, r2, r3 = st.columns([1.5, 1, 2])
            cur_status = current_data.get(skey, "Pending")
            s_idx = opts.index(cur_status) if cur_status in opts else 0
            
            m_responses[skey] = r1.selectbox(label, opts, index=s_idx, key=f"s_{skey}")
            m_responses[pk] = r2.slider("Prog %", 0, 100, value=int(current_data.get(pk, 0) or 0), key=f"p_{skey}")
            m_responses[nkey] = r3.text_input("Remarks", value=current_data.get(nkey, ""), key=f"n_{skey}")

        st.divider()
        f_progress = st.slider("📈 Overall %", 0, 100, value=int(current_data.get('overall_progress', 0) or 0))
        
        if st.form_submit_button("🚀 SAVE UPDATE", use_container_width=True):
            payload = {
                "customer": f_cust, "job_code": f_job, "equipment": f_eq,
                "po_no": f_po_n, "po_date": str(f_po_d), "engineer": f_eng,
                "po_delivery_date": str(f_po_del), "exp_dispatch_date": str(f_exp_dis),
                "overall_progress": f_progress, **m_responses
            }
            conn.table("progress_logs").insert(payload).execute()
            st.success("✅ Saved!"); st.cache_data.clear(); st.rerun()

with tab2:
    st.subheader("📂 Report Archive")
    f1, f2, f3 = st.columns(3)
    sel_c = f1.selectbox("Filter Customer", ["All"] + customers)
    report_type = f2.selectbox("📅 Period", ["All Time", "Current Week", "Current Month", "Custom Range"])
    
    # --- Date Filtering Logic ---
    start_date, end_date = None, None
    now = datetime.now()
    if report_type == "Current Week":
        start_date = (now - timedelta(days=now.weekday())).date()
    elif report_type == "Current Month":
        start_date = now.replace(day=1).date()
    elif report_type == "Custom Range":
        dates = f3.date_input("Select Range", [now, now])
        if len(dates) == 2:
            start_date, end_date = dates[0], dates[1]

    # --- Database Query ---
    query = conn.table("progress_logs").select("*").order("id", desc=True)
    if sel_c != "All":
        query = query.eq("customer", sel_c)
    
    res = query.execute()
    raw_data = res.data if res.data else []

    # --- Local Time Filtering ---
    data = []
    if start_date:
        for d in raw_data:
            try:
                # Parse date from created_at or po_date
                raw_ts = d.get('created_at') or d.get('po_date')
                d_date = datetime.strptime(raw_ts[:10], "%Y-%m-%d").date()
                if end_date:
                    if start_date <= d_date <= end_date: data.append(d)
                else:
                    if d_date >= start_date: data.append(d)
            except:
                # Fallback: if date parsing fails, keep the record
                data.append(d)
    else:
        data = raw_data

    # --- UI Rendering ---
    if data:
        # Summary Metrics
        total_jobs = len(data)
        completed = len([d for d in data if int(d.get('overall_progress', 0) or 0) == 100])
        pending = total_jobs - completed
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Reports", total_jobs)
        m2.metric("Completed", completed)
        m3.metric("Pending", pending)
        st.divider()

        # LAZY LOAD PDF: This button prevents the slow load times
        if st.button("📥 Prepare PDF for Download", use_container_width=True):
            with st.spinner("Generating PDF... This may take a moment for large reports."):
                pdf_bytes = generate_pdf(data)
                if pdf_bytes:
                    st.download_button(
                        label="✅ Click here to Save PDF",
                        data=pdf_bytes,
                        file_name=f"BG_Report_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
        
        # Fast Preview List
        for log in data:
            job_info = f"📦 {log.get('job_code')} - {log.get('customer')}"
            with st.expander(job_info):
                prog = int(log.get('overall_progress', 0) or 0)
                st.write(f"**Current Progress: {prog}%**")
                st.progress(prog / 100)
                st.write(f"Engineer: {log.get('engineer', 'N/A')}")
    else:
        st.info("No records found for the selected filters.")

with tab3:
    st.subheader("🛠️ Master Management")
    c_col, j_col = st.columns(2)
    with c_col:
        st.write("**Current Customers:**", ", ".join(customers) if customers else "None")
        with st.form("add_cust"):
            nc = st.text_input("New Customer")
            if st.form_submit_button("Add Customer") and nc:
                conn.table("customer_master").insert({"name": nc}).execute()
                st.cache_data.clear(); st.rerun()
    with j_col:
        st.write("**Current Job Codes:**", ", ".join(jobs) if jobs else "None")
        with st.form("add_job"):
            nj = st.text_input("New Job Code")
            if st.form_submit_button("Add Job") and nj:
                conn.table("job_master").insert({"job_code": nj}).execute()
                st.cache_data.clear(); st.rerun()
