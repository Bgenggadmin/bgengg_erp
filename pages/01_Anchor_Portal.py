import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Anchor Portal | BGEngg ERP", layout="wide", page_icon="⚓")

conn = st.connection("supabase", type=SupabaseConnection)

def get_projects():
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    if not res.data:
        return pd.DataFrame()
    return pd.DataFrame(res.data)

df = get_projects()

st.sidebar.title("🎯 Anchor Filter")
anchor_choice = st.sidebar.selectbox("Select Your Profile", ["Ammu", "Kishore"])
df_display = df[df['anchor_person'] == anchor_choice] if not df.empty else pd.DataFrame()

st.title(f"⚓ {anchor_choice}'s Project Portal")

# --- TAB 1: NEW ENTRY ---
tabs = st.tabs(["📝 New Entry", "📂 Project Pipeline", "📐 Technical & Drawings", "🛒 Purchase Link"])

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
                    "special_notes": u_notes, "status": "Enquiry"
                }).execute()
                st.success("Enquiry Logged!"); st.rerun()

# --- TAB 2: PROJECT PIPELINE (SALES) ---
with tabs[1]:
    st.subheader("Sales Lifecycle & Quotation")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            with st.expander(f"💼 {row['client_name']} | {row['project_description']} | Status: {row['status']}"):
                c1, c2, c3 = st.columns(3)
                u_val = c1.number_input("Project Value (₹)", value=float(row['estimated_value'] or 0), key=f"val_{row['id']}")
                u_qref = c2.text_input("Quote Ref.", value=row['quote_ref'] or "", key=f"qref_{row['id']}")
                u_qdate = c3.date_input("Quote Date", value=pd.to_datetime(row['quote_date']).date() if row['quote_date'] else datetime.now(), key=f"qdt_{row['id']}")
                
                new_status = st.selectbox("Update Stage", ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"], 
                                         index=["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"].index(row['status']), key=f"st_{row['id']}")
                
                rev_notes = st.text_area("Revision Notes", value=row['revision_notes'] or "", key=f"rev_{row['id']}")
                
                if st.button("Update Sales Info", key=f"up_{row['id']}"):
                    conn.table("anchor_projects").update({
                        "estimated_value": u_val, "quote_ref": u_qref, "quote_date": str(u_qdate),
                        "status": new_status, "revision_notes": rev_notes
                    }).eq("id", row['id']).execute(); st.rerun()

# --- TAB 3: DRAWINGS ---
with tabs[2]:
    st.subheader("Drawing Control")
    for index, row in df_display.iterrows():
        with st.expander(f"📐 {row['client_name']} - {row['drawing_status']}"):
            c1, c2 = st.columns(2)
            d_ref = c1.text_input("Drawing Ref No.", value=row['drawing_ref'] or "", key=f"dr_{row['id']}")
            d_stat = c2.selectbox("Status", ["Pending", "Drafting", "Approved"], key=f"ds_{row['id']}")
            d_notes = st.text_area("Drawing Notes", value=row['drawing_notes'] or "", key=f"dn_{row['id']}")
            
            if st.button("Save Drawing Info", key=f"dbtn_{row['id']}"):
                update_data = {"drawing_ref": d_ref, "drawing_status": d_stat, "drawing_notes": d_notes}
                if d_stat == "Approved" and not row['drawing_submit_date']:
                    update_data["drawing_submit_date"] = str(datetime.now().date())
                conn.table("anchor_projects").update(update_data).eq("id", row['id']).execute(); st.rerun()

# --- TAB 4: PURCHASE ---
with tabs[3]:
    st.subheader("Purchase Integration")
    for index, row in df_display.iterrows():
        with st.container():
            c1, c2, c3 = st.columns([1, 2, 1])
            u_job = c1.text_input("Job No.", value=row['job_no'] or "", key=f"job_{row['id']}")
            is_trig = c1.checkbox("Trigger", value=row['purchase_trigger'], key=f"t_{row['id']}")
            mats = c2.text_area("Materials", value=row['critical_materials'] or "", key=f"m_{row['id']}")
            c3.write(f"Status: {row['purchase_status'] or 'Pending'}")
            
            if st.button("Sync Purchase", key=f"p_{row['id']}"):
                conn.table("anchor_projects").update({"job_no": u_job, "purchase_trigger": is_trig, "critical_materials": mats}).eq("id", row['id']).execute(); st.rerun()
