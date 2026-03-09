import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd

st.set_page_config(page_title="Purchase Console | BGEngg ERP", layout="wide", page_icon="🛒")

conn = st.connection("supabase", type=SupabaseConnection)

def get_purchase_tasks():
    # Only fetch projects where Ammu/Kishore have flipped the "purchase_trigger"
    res = conn.table("anchor_projects").select("*").eq("purchase_trigger", True).order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_p = get_purchase_tasks()

st.title("🛒 Purchase Integration Console")
st.info("Items listed below have been flagged as **Critical** by Project Anchors.")
# --- PURCHASE WORKLOAD SUMMARY ---
st.subheader("📦 Procurement Overview")
if not df_p.empty:
    # Summary of items by status (Ordered, Sourcing, Received, etc.)
    p_summary = df_p.groupby('purchase_status').agg(
        Count=('id', 'count'),
        Projects=('client_name', lambda x: ", ".join(x.unique()))
    ).reset_index()
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.dataframe(p_summary, hide_index=True)
    with col2:
        # Visual breakdown of the workload
        import plotly.express as px
        fig = px.pie(p_summary, values='Count', names='purchase_status', title="Items by Status", hole=0.4)
        fig.update_layout(margin=dict(t=30, b=0, l=0, r=0), height=200)
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No active purchase requests to summarize.")
if not df_p.empty:
    for index, row in df_p.iterrows():
        with st.expander(f"📦 {row['client_name']} | Item: {row['project_description']} | Status: {row['purchase_status']}"):
            c1, c2, c3 = st.columns([2, 2, 1])
            
            with c1:
                st.markdown(f"**Critical Materials Required:**\n\n{row['critical_materials']}")
                st.caption(f"Requested by: {row['anchor_person']}")
            
            with c2:
                # Purchase Team Updates
                p_stat = st.selectbox("Update Procurement Status", 
                                    ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"],
                                    index=["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"].index(row['purchase_status']) if row['purchase_status'] in ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"] else 0,
                                    key=f"pstat_{row['id']}")
                
                rem = st.text_area("Reply / Remarks to Anchor", value=row['purchase_remarks'] or "", key=f"prem_{row['id']}")
            
            with c3:
                eta = st.date_input("Expected Arrival", value=None, key=f"eta_{row['id']}")
                
                if st.button("Update Anchor", key=f"upbtn_{row['id']}", use_container_width=True):
                    conn.table("anchor_projects").update({
                        "purchase_status": p_stat,
                        "purchase_remarks": rem,
                        "expected_arrival": str(eta) if eta else None
                    }).eq("id", row['id']).execute()
                    st.success("Anchor Notified!"); st.rerun()
else:
    st.success("No pending critical purchase requests!")
