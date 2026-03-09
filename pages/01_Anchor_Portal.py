import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd

st.set_page_config(page_title="Anchor Portal | BGEngg ERP", layout="wide", page_icon="⚓")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

def get_projects():
    # Fetch data from Supabase
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    
    # Define the "Expected" columns to match our pre-production logic
    expected_columns = [
        'id', 'status', 'anchor_person', 'client_name', 'project_description', 
        'drawing_status', 'drawing_ref', 'purchase_trigger', 'critical_materials',
        'estimated_value', 'special_notes'
    ]
    
    # If no data exists yet, return an empty dataframe with these headers
    if not res.data:
        return pd.DataFrame(columns=expected_columns)
    
    df_result = pd.DataFrame(res.data)
    
    # Safety Check: If Supabase table is missing a column, add it as empty to prevent KeyErrors
    for col in expected_columns:
        if col not in df_result.columns:
            df_result[col] = None
            
    return df_result

# Load the data
df = get_projects()

# --- 2. SIDEBAR CONFIGURATION ---
st.sidebar.title("🎯 Anchor Filter")
anchor_choice = st.sidebar.selectbox("Lead Person", ["All", "Ammu", "Kishore"])

# Filter the dataframe based on selection
if anchor_choice != "All":
    df_display = df[df['anchor_person'] == anchor_choice]
else:
    df_display = df

# --- 3. MAIN INTERFACE ---
st.title(f"⚓ Anchor Portal: {anchor_choice}")
st.markdown("---")

# Quick Metrics
if not df_display.empty:
    c1, c2, c3 = st.columns(3)
    c1.metric("Active Enquiries", len(df_display[df_display['status'] == 'Enquiry']))
    c2.metric("Pending Drawings", len(df_display[df_display['drawing_status'] != 'Approved']))
    c3.metric("Purchase Alerts", len(df_display[df_display['purchase_trigger'] == True]))

tabs = st.tabs(["📝 New Entry", "📂 Project Pipeline", "📐 Technical & Drawings", "🛒 Purchase Link"])

# --- TAB 1: NEW ENTRY (Sales/Marketing) ---
with tabs[0]:
    st.subheader("Register New Project Enquiry")
    with st.form("new_project_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        u_client = col1.text_input("Client Name")
        u_proj = col2.text_input("Project Description")
        
        col3, col4, col5 = st.columns(3)
        u_anchor = col3.selectbox("Lead Anchor", ["Ammu", "Kishore"])
        u_val = col4.number_input("Est. Value (₹)", min_value=0)
        u_notes = col5.text_area("Special Notes / Remarks")
        
        if st.form_submit_button("Add to Pipeline"):
            if u_client and u_proj:
                conn.table("anchor_projects").insert({
                    "client_name": u_client,
                    "project_description": u_proj,
                    "anchor_person": u_anchor,
                    "estimated_value": u_val,
                    "special_notes": u_notes,
                    "status": "Enquiry",
                    "drawing_status": "Pending"
                }).execute()
                st.success(f"Project for {u_client} added!"); st.rerun()
            else:
                st.error("Client Name and Project Description are required.")

# --- TAB 2: PROJECT PIPELINE ---
with tabs[1]:
    st.subheader("Sales Lifecycle Management")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            with st.expander(f"💼 {row['client_name']} | {row['project_description']} | Status: {row['status']}"):
                c1, c2 = st.columns(2)
                new_status = c1.selectbox("Update Stage", 
                                        ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"], 
                                        index=["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"].index(row['status']) if row['status'] in ["Enquiry", "Estimation", "Quotation Sent", "Won", "Lost"] else 0,
                                        key=f"stat_{row['id']}")
                
                if c1.button("Update Stage", key=f"btn_stat_{row['id']}"):
                    conn.table("anchor_projects").update({"status": new_status}).eq("id", row['id']).execute(); st.rerun()
                
                c2.info(f"**Notes:** {row['special_notes']}")
    else:
        st.info("No active projects found.")

# --- TAB 3: TECHNICAL & DRAWINGS ---
with tabs[2]:
    st.subheader("Drawing & Design Control")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            with st.expander(f"📐 {row['client_name']} | Drawing: {row['drawing_status']}"):
                c1, c2 = st.columns(2)
                d_ref = c1.text_input("Drawing Ref No.", value=row['drawing_ref'] or "", key=f"dref_{row['id']}")
                d_stat = c2.selectbox("Drawing Approval", 
                                     ["Pending", "Drafting", "Client Review", "Approved"],
                                     index=["Pending", "Drafting", "Client Review", "Approved"].index(row['drawing_status']) if row['drawing_status'] in ["Pending", "Drafting", "Client Review", "Approved"] else 0,
                                     key=f"dstat_{row['id']}")
                
                if st.button("Save Technical Details", key=f"tbtn_{row['id']}"):
                    conn.table("anchor_projects").update({"drawing_ref": d_ref, "drawing_status": d_stat}).eq("id", row['id']).execute(); st.rerun()
    else:
        st.info("No data available.")

# --- TAB 4: PURCHASE LINK (Updated with Reply Visibility) ---
with tabs[3]:
    st.subheader("Critical Material Procurement Triggers")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            with st.container():
                col1, col2, col3 = st.columns([1, 2, 1])
                
                with col1:
                    st.write(f"**{row['client_name']}**")
                    is_trig = st.checkbox("Trigger Purchase", value=row['purchase_trigger'], key=f"trig_{row['id']}")
                
                with col2:
                    mats = st.text_area("Critical Materials Needed", value=row['critical_materials'] or "", key=f"mat_{row['id']}")
                
                with col3:
                    # SHOW PURCHASE TEAM'S REPLY HERE
                    st.markdown("**Purchase Status:**")
                    status_color = "green" if row['purchase_status'] == "Received" else "orange"
                    st.markdown(f":{status_color}[{row['purchase_status'] or 'Not Seen Yet'}]")
                    
                    if row['purchase_remarks']:
                        st.caption(f"💬 Reply: {row['purchase_remarks']}")

                if st.button("Sync Data", key=f"pbtn_{row['id']}"):
                    conn.table("anchor_projects").update({
                        "critical_materials": mats,
                        "purchase_trigger": is_trig
                    }).eq("id", row['id']).execute(); st.rerun()
                st.divider()
