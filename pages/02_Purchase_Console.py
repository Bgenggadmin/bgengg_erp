import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Purchase Console | BGEngg ERP", layout="wide", page_icon="🛒")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

def get_purchase_tasks():
    # Only fetch projects where 'purchase_trigger' is True
    res = conn.table("anchor_projects").select("*").eq("purchase_trigger", True).order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_p = get_purchase_tasks()

st.title("🛒 Purchase Integration Console")
st.info("Items listed below have been flagged as **Critical** by Project Anchors (Ammu/Kishore).")

# --- 2. PROCUREMENT WORKLOAD SUMMARY ---
st.subheader("📦 Procurement Overview")
if not df_p.empty:
    # Aggregated Summary of requests and status
    p_summary = df_p.groupby('purchase_status').agg(
        Total_Items=('id', 'count'),
        Anchors=('anchor_person', lambda x: ", ".join(x.unique())),
        Job_Codes=('job_no', lambda x: ", ".join([str(i) for i in x.unique() if i]))
    ).reset_index()
    
    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.write("**Request Status Summary**")
        st.dataframe(p_summary, hide_index=True, use_container_width=True)
    
    with col2:
        # Visual Workload Chart
        fig = px.pie(p_summary, values='Total_Items', names='purchase_status', 
                     title="Workload by Status", hole=0.4,
                     color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_layout(margin=dict(t=30, b=0, l=0, r=0), height=200)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No active purchase requests to summarize.")

st.divider()

# --- 3. DETAILED PURCHASE CARDS ---
if not df_p.empty:
    st.subheader("📝 Pending Material Actions")
    for index, row in df_p.iterrows():
        # Dynamic color coding based on status
        status_color = "🟢" if row['purchase_status'] == "Received" else "🟡"
        
        with st.expander(f"{status_color} Job: {row['job_no'] or 'N/A'} | {row['client_name']} | Status: {row['purchase_status']}"):
            c1, c2, c3 = st.columns([1.5, 2, 1])
            
            with c1:
                st.markdown(f"### Job Info")
                st.write(f"**Job Code:** `{row['job_no'] or 'NOT SET'}`")
                st.write(f"**Anchor:** {row['anchor_person']}")
                st.write(f"**Client:** {row['client_name']}")
                st.write(f"**Project:** {row['project_description']}")
            
            with c2:
                st.markdown(f"### Material Requirements")
                st.info(f"{row['critical_materials']}")
                rem = st.text_area("Update Remarks to Anchor", value=row['purchase_remarks'] or "", key=f"prem_{row['id']}")
            
            with c3:
                st.markdown(f"### Action Center")
                p_stat = st.selectbox("Update Status", 
                                    ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"],
                                    index=["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"].index(row['purchase_status']) if row['purchase_status'] in ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"] else 0,
                                    key=f"pstat_{row['id']}")
                
                # Material Receipt Confirmation logic
                if p_stat == "Received":
                    st.success("✅ Mark as Confirmed")
                
                eta = st.date_input("Arrival Date", value=pd.to_datetime(row['expected_arrival']).date() if row['expected_arrival'] else None, key=f"eta_{row['id']}")
                
                if st.button("Update System", key=f"upbtn_{row['id']}", use_container_width=True, type="primary"):
                    conn.table("anchor_projects").update({
                        "purchase_status": p_stat,
                        "purchase_remarks": rem,
                        "expected_arrival": str(eta) if eta else None
                    }).eq("id", row['id']).execute()
                    st.toast(f"Updated Job {row['job_no']}")
                    st.rerun()
else:
    st.success("All clear! No pending material requests.")
