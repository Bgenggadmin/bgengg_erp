import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Purchase Console | BGEngg ERP", layout="wide", page_icon="🛒")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=5)
def get_purchase_tasks():
    # Fetch projects where purchase is triggered
    res = conn.table("anchor_projects").select("*").eq("purchase_trigger", True).order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

@st.cache_data(ttl=2)
def get_all_items():
    # Fetch all specific material items
    res = conn.table("purchase_orders").select("*").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_p = get_purchase_tasks()
df_items = get_all_items()

st.title("🛒 Purchase Integration Console")
st.info("Manage both Project-level status and Specific Material items below.")

# --- 2. PROCUREMENT WORKLOAD SUMMARY (PRESERVED) ---
if not df_p.empty:
    st.subheader("📦 Procurement Overview")
    p_summary = df_p.groupby('purchase_status').agg(Total_Jobs=('id', 'count')).reset_index()
    
    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.dataframe(p_summary, hide_index=True, use_container_width=True)
    with col2:
        fig = px.pie(p_summary, values='Total_Jobs', names='purchase_status', 
                     title="Workload", hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
        fig.update_layout(margin=dict(t=30, b=0, l=0, r=0), height=200)
        st.plotly_chart(fig, use_container_width=True)

st.divider()

# --- 3. DETAILED ACTION CENTER ---
if not df_p.empty:
    st.subheader("📝 Pending Material Actions")
    for index, row in df_p.iterrows():
        curr_job = str(row['job_no']).strip().upper() if row['job_no'] else "N/A"
        
        # Filter items for this specific job
        job_items = df_items[df_items['job_no'] == curr_job] if not df_items.empty else pd.DataFrame()
        
        status_color = "🟢" if row['purchase_status'] == "Received" else "🟡"
        
        with st.expander(f"{status_color} Job: {curr_job} | {row['client_name']} | Items: {len(job_items)}"):
            c1, c2 = st.columns([1, 2])
            
            with c1:
                st.markdown("### Project Header")
                st.write(f"**Anchor:** {row['anchor_person']}")
                st.write(f"**Critical Summary:** {row['critical_materials']}")
                
                # Update high-level project status
                new_proj_stat = st.selectbox("Overall Status", 
                                           ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"],
                                           index=["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"].index(row['purchase_status']) if row['purchase_status'] in ["Pending Review", "Sourcing", "Ordered", "In-Transit", "Received"] else 0,
                                           key=f"pstat_{row['id']}")
                
                new_rem = st.text_area("Purchase Remarks", value=row['purchase_remarks'] or "", key=f"prem_{row['id']}")
                
                if st.button("Update Project Info", key=f"ubtn_{row['id']}", type="primary"):
                    conn.table("anchor_projects").update({
                        "purchase_status": new_proj_stat,
                        "purchase_remarks": new_rem
                    }).eq("id", row['id']).execute()
                    st.rerun()

            with c2:
                st.markdown("### Item-wise Breakdown")
                if job_items.empty:
                    st.warning("No specific items added to list yet.")
                else:
                    for _, item in job_items.iterrows():
                        with st.container(border=True):
                            ic1, ic2, ic3 = st.columns([1.5, 2, 1])
                            ic1.write(f"**{item['item_name']}**\n\n{item['specs']}")
                            
                            # Item-specific feedback
                            i_reply = ic2.text_input("Reply", value=item['purchase_reply'] or "", key=f"irep_{item['id']}")
                            
                            i_stat_opts = ["Triggered", "Sourcing", "Ordered", "Received"]
                            i_stat = ic3.selectbox("Item Status", i_stat_opts, 
                                                 index=i_stat_opts.index(item['status']) if item['status'] in i_stat_opts else 0,
                                                 key=f"istat_{item['id']}")
                            
                            if st.button("Update Item", key=f"isave_{item['id']}"):
                                conn.table("purchase_orders").update({
                                    "purchase_reply": i_reply,
                                    "status": i_stat
                                }).eq("id", item['id']).execute()
                                st.toast(f"Updated {item['item_name']}")
                                st.rerun()
else:
    st.success("All clear! No pending requests.")
