import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Production Control | BGEngg ERP", layout="wide", page_icon="🏗️")

conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=5)
def get_won_jobs():
    res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_prod = get_won_jobs()

st.title("🏗️ Production Planning & Activity Sync")

# Top Level Metrics
if not df_prod.empty:
    total_jobs = len(df_prod)
    shortages = len(df_prod[df_prod['material_shortage'] == True])
    
    m1, m2 = st.columns(2)
    m1.metric("Total Active Jobs", total_jobs)
    m2.metric("Material Stoppages", shortages, delta=-shortages, delta_color="inverse")

st.markdown("---")

stages = [
    "Material Identification/MTC Check", "Shell & Dish Layout", "Plasma Cutting", 
    "Shell Rolling", "Long Seam Welding", "Circ Seam Welding", "Nozzle Fit-up", 
    "Final Welding", "NDT (RT/DP/UT)", "Hydro-Testing", "Pickling & Passivation", "Dispatch"
]

if not df_prod.empty:
    for index, row in df_prod.iterrows():
        # Calculate Progress %
        current_idx = stages.index(row['drawing_status']) if row['drawing_status'] in stages else 0
        progress_val = (current_idx + 1) / len(stages)
        
        # UI Container
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.subheader(f"Job {row['job_no']} | {row['client_name']}")
                st.caption(f"📦 **Vessel:** {row['project_description']}")
            with c2:
                if row.get('material_shortage'):
                    st.error("🚨 MATERIAL SHORTAGE")
                else:
                    st.success("✅ Clear for Production")

            # Progress Bar
            st.progress(progress_val, text=f"Overall Progress: {int(progress_val*100)}%")

            # Input Fields
            col1, col2, col3 = st.columns(3)
            with col1:
                new_stage = st.selectbox("Current Activity", stages, index=current_idx, key=f"stg_{row['id']}")
            
            with col2:
                new_shortage = st.toggle("Report Shortage", value=row.get('material_shortage', False), key=f"sh_{row['id']}")
                new_note = st.text_input("Shortage/Activity Note", value=row.get('shortage_details', ""), key=f"nt_{row['id']}")

            with col3:
                st.write(" ") # Padding
                if st.button("Update Floor Data", key=f"btn_{row['id']}", use_container_width=True, type="primary"):
                    conn.table("anchor_projects").update({
                        "drawing_status": new_stage,
                        "material_shortage": new_shortage,
                        "shortage_details": new_note,
                        "last_activity_update": datetime.now().isoformat()
                    }).eq("id", row['id']).execute()
                    st.toast(f"Updated Job {row['job_no']}")
                    st.rerun()
else:
    st.info("No active 'Won' jobs found in database.")
