import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Purchase Console | BGEngg ERP", layout="wide", page_icon="🛒")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

def get_purchase_tasks():
    # Keep fetching projects with triggers for the Summary UI
    res = conn.table("anchor_projects").select("*").eq("purchase_trigger", True).order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def get_all_items():
    # Fetch all individual items for the actual updates
    res = conn.table("purchase_orders").select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_p = get_purchase_tasks()
df_items = get_all_items()

st.title("🛒 Purchase Integration Console")
st.info("Items listed below have been flagged as **Critical** by Project Anchors.")

# --- 2. PROCUREMENT WORKLOAD SUMMARY (Kept from your code) ---
st.subheader("📦 Procurement Overview")
if not df_p.empty:
    p_summary = df_p.groupby('purchase_status').agg(
        Total_Jobs=('id', 'count'),
        Anchors=('anchor_person', lambda x: ", ".join(x.unique())),
    ).reset_index()
    
    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.dataframe(p_summary, hide_index=True, use_container_width=True)
    
    with col2:
        fig = px.pie(p_summary, values='Total_Jobs', names='purchase_status', 
                     title="Workload by Project Status", hole=0.4,
                     color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_layout(margin=dict(t=30, b=0, l=0, r=0), height=200)
        st.plotly_chart(fig, use_container_width=True)
st.divider()

# --- 3. DETAILED PURCHASE CARDS (Integrated with Item-wise Logic) ---
if not df_p.empty:
    st.subheader("📝 Pending Material Actions")
    for index, row in df_p.iterrows():
        # Clean Job No for matching
        curr_job = str(row['job_no']).strip().upper() if row['job_no'] else None
        
        # Filter items belonging to this Job
        job_items = df_items[df_items['job_no'] == curr_job] if curr_job and not df_items.empty else pd.DataFrame()
        
        status_color = "🟢" if row['purchase_status'] == "Received" else "🟡"
        
        with st.expander(f"{status_color} Job: {curr_job} | {row['client_name']} | Items: {len(job_items)}"):
            c1, c2 = st.columns([1, 2])
            
            with c1:
                st.markdown("### Job Info")
                st.write(f"**Anchor:** {row['anchor_person']}")
                st.write(f"**Description:** {row['project_description']}")
                
                # High-level status update for the project
                new_p_stat = st.selectbox("Overall Project Status", 
                                        ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"],
                                        index=["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"].index(row['purchase_status']) if row['purchase_status'] in ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"] else 0,
                                        key=f"proj_stat_{row['id']}")
                
                if st.button("Update Project Header", key=f"up_head_{row['id']}"):
                    conn.table("anchor_projects").update({"purchase_status": new_p_stat}).eq("id", row['id']).execute()
                    st.rerun()

            with c2:
                st.markdown("### Individual Items")
                if job_items.empty:
                    st.warning("No specific items added by Anchor yet.")
                else:
                    # Header for items
                    h1, h2, h3, h4 = st.columns([2, 2, 1.5, 0.5])
                    h1.caption("Item Name")
                    h2.caption("Purchase Reply")
                    h3.caption("Status")
                    
                    for _, item in job_items.iterrows():
                        with st.container():
                            ic1, ic2, ic3, ic4 = st.columns([2, 2, 1.5, 0.5])
                            # Field 1: Item Info
                            ic1.write(f"**{item['item_name']}**\n\n({item['specs']})")
                            
                            # Field 2: Reply Input
                            i_reply = ic2.text_input("Reply", value=item['purchase_reply'] or "", key=f"irep_{item['id']}", label_visibility="collapsed")
                            
                            # Field 3: Status Select
                            i_status_opts = ["Triggered", "Enquiry", "Ordered", "Received"]
                            i_status = ic3.selectbox("Status", i_status_opts, 
                                                   index=i_status_opts.index(item['status']) if item['status'] in i_status_opts else 0,
                                                   key=f"istat_{item['id']}", label_visibility="collapsed")
                            
                            # Field 4: Save button for specific item
                            if ic4.button("💾", key=f"isave_{item['id']}"):
                                conn.table("purchase_orders").update({
                                    "purchase_reply": i_reply,
                                    "status": i_status
                                }).eq("id", item['id']).execute()
                                st.toast(f"Updated {item['item_name']}")
                                st.rerun()
                            st.divider()

else:
    st.success("All clear! No pending material requests.")
