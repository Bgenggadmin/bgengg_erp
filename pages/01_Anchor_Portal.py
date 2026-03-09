import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import date, timedelta

st.set_page_config(page_title="Anchor Portal | BGEngg", layout="wide")

# --- DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

def get_projects():
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df = get_projects()

# --- HEADER & ROLE ---
st.title("⚓ Anchor Management Portal")
st.sidebar.title("Configuration")
anchor_filter = st.sidebar.selectbox("Filter by Lead:", ["All", "Ammu", "Kishore"])

# --- KPIS / TOP METRICS ---
if not df.empty:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Enquiries", len(df))
    m2.metric("In Estimation", len(df[df['status'] == 'Estimation']))
    m3.metric("Purchase Alerts", len(df[df['purchase_trigger'] == True]))
    m4.metric("Conversion Rate", f"{(len(df[df['status'] == 'Won']) / len(df) * 100):.1f}%")

tabs = st.tabs(["📋 Sales & Enquiries", "📐 Drawings & Technical", "🛒 Purchase Integration", "📊 Analytics"])

# --- TAB 1: SALES & ENQUIRIES (Ammu/Kishore Lead) ---
with tabs[0]:
    with st.expander("➕ Register New Project Enquiry"):
        with st.form("enquiry_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            client = c1.text_input("Client Name")
            proj_name = c2.text_input("Project Name/Part")
            lead = c3.selectbox("Lead Anchor", ["Ammu", "Kishore"])
            
            c4, c5, c6 = st.columns(3)
            val = c4.number_input("Estimated Value (₹)", min_value=0)
            target_date = c5.date_input("Required Delivery Date")
            notes = c6.text_area("Initial Project Notes")
            
            if st.form_submit_button("Submit to Pipeline"):
                conn.table("anchor_projects").insert({
                    "anchor_person": lead, "client_name": client, "project_description": proj_name,
                    "estimated_value": val, "status": "Enquiry", "special_notes": notes
                }).execute(); st.rerun()

    # Active Pipeline View
    st.subheader("Current Sales Pipeline")
    display_df = df if anchor_filter == "All" else df[df['anchor_person'] == anchor_filter]
    if not display_df.empty:
        st.dataframe(display_df[["client_name", "project_description", "status", "estimated_value", "anchor_person"]], 
                     use_container_width=True, hide_index=True)
    else:
        st.info("No active enquiries in pipeline.")

# --- TAB 2: DRAWINGS & TECHNICAL (The "API/ZLD Anchor" Role) ---
with tabs[1]:
    st.subheader("Technical & Design Approval")
    technical_df = df[df['status'].isin(['Enquiry', 'Estimation'])]
    
    for _, row in technical_df.iterrows():
        with st.expander(f"🛠️ {row['client_name']} - {row['project_description']}"):
            col1, col2 = st.columns(2)
            d_ref = col1.text_input("Drawing Ref #", value=row['drawing_ref'] or "", key=f"dr_{row['id']}")
            d_status = col2.selectbox("Approval Status", ["Pending", "Drafting", "Client Review", "Approved"], 
                                      index=["Pending", "Drafting", "Client Review", "Approved"].index(row['drawing_status'] or "Pending"),
                                      key=f"ds_{row['id']}")
            
            if st.button("Update Technical Specs", key=f"up_tech_{row['id']}"):
                conn.table("anchor_projects").update({"drawing_ref": d_ref, "drawing_status": d_status}).eq("id", row['id']).execute(); st.rerun()

# --- TAB 3: PURCHASE INTEGRATION (Critical Material Trigger) ---
with tabs[2]:
    st.subheader("🚩 Purchase & Procurement Link")
    st.markdown("Flag materials here that need to be ordered **before** production starts.")
    
    for _, row in df[df['status'] != 'Won'].iterrows():
        with st.container():
            c1, c2, c3 = st.columns([2, 3, 1])
            c1.write(f"**{row['client_name']}**")
            mat_req = c2.text_area("Identify Critical Materials (e.g. ZLD Pumps, SS316 Sheets)", 
                                   value=row['critical_materials'] or "", key=f"mat_{row['id']}")
            
            is_triggered = c3.checkbox("Trigger Purchase", value=row['purchase_trigger'], key=f"trig_{row['id']}")
            
            if st.button("Update Procurement Request", key=f"p_btn_{row['id']}"):
                conn.table("anchor_projects").update({
                    "critical_materials": mat_req,
                    "purchase_trigger": is_triggered
                }).eq("id", row['id']).execute(); st.rerun()
            st.divider()
