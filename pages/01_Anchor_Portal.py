import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd

st.set_page_config(page_title="Anchor Portal | BGEngg", layout="wide")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

def get_data():
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df = get_data()

# --- 2. SIDEBAR FILTER ---
st.sidebar.title("👤 Anchor Selection")
user_role = st.sidebar.radio("View as:", ["Ammu (API Lead)", "Kishore (ZLD Lead)"])
anchor_name = "Ammu" if "Ammu" in user_role else "Kishore"

st.title(f"⚓ {user_role} Dashboard")
tabs = st.tabs(["📝 New Enquiry", "📂 Project Pipeline", "🛒 Purchase Integration", "⚠️ Quality (NCR)"])

# --- TAB 1: NEW ENQUIRY ---
with tabs[0]:
    st.subheader("Register New Enquiry")
    with st.form("new_enquiry", clear_on_submit=True):
        c1, c2 = st.columns(2)
        client = c1.text_input("Client Name")
        proj = c2.text_input("Project / Item Description")
        
        c3, c4 = st.columns(2)
        d_ref = c3.text_input("Drawing Reference No.")
        crit_mat = c4.text_area("Critical Materials Identified")
        
        if st.form_submit_button("Log Enquiry"):
            if client and proj:
                conn.table("anchor_projects").insert({
                    "anchor_person": anchor_name, "client_name": client,
                    "project_description": proj, "drawing_ref": d_ref,
                    "critical_materials": crit_mat, "status": "Enquiry"
                }).execute()
                st.success("Enquiry Registered!"); st.rerun()

# --- TAB 2: PIPELINE & DRAWINGS ---
with tabs[1]:
    st.subheader(f"Active Projects for {anchor_name}")
    active_df = df[df['anchor_person'] == anchor_name] if not df.empty else pd.DataFrame()
    
    if not active_df.empty:
        for _, row in active_df.iterrows():
            with st.expander(f"📁 {row['client_name']} | {row['project_description']} ({row['status']})"):
                col1, col2, col3 = st.columns(3)
                
                # Update Status (Sales/Estimation)
                new_status = col1.selectbox("Project Stage", 
                                          ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"], 
                                          index=["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"].index(row['status']),
                                          key=f"status_{row['id']}")
                
                # Update Drawing Status
                new_d_status = col2.selectbox("Drawing Status", 
                                            ["Pending", "In-Progress", "Approved", "Revised"],
                                            index=["Pending", "In-Progress", "Approved", "Revised"].index(row['drawing_status']),
                                            key=f"draw_{row['id']}")
                
                # Trigger Purchase
                trigger = col3.checkbox("🚀 Trigger Critical Purchase?", value=row['purchase_trigger'], key=f"trig_{row['id']}")
                
                if st.button("Save Updates", key=f"btn_{row['id']}"):
                    conn.table("anchor_projects").update({
                        "status": new_status, 
                        "drawing_status": new_d_status,
                        "purchase_trigger": trigger
                    }).eq("id", row['id']).execute(); st.rerun()
    else:
        st.info("No active projects found.")

# --- TAB 3: PURCHASE INTEGRATION ---
with tabs[2]:
    st.subheader("📦 Critical Material Procurement List")
    st.write("Items flagged for early purchase by Ammu/Kishore.")
    if not df.empty:
        # Show projects from BOTH anchors that have triggered purchase
        purchase_df = df[df['purchase_trigger'] == True]
        st.dataframe(purchase_df[["client_name", "project_description", "critical_materials", "anchor_person", "status"]], use_container_width=True)
    else:
        st.info("No purchase triggers active.")

# --- TAB 4: QUALITY (NCR) ---
with tabs[3]:
    st.subheader("Non-Conformance Reports")
    st.info("This section replaces api_ncr.csv for tracking project defects.")
    # (We can expand this with a simple insert form for NCRs linked to Project IDs)
