import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Production Control | BGEngg ERP", layout="wide", page_icon="🏗️")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=10)
def get_won_jobs():
    # Only pull projects marked as 'Won' to start production
    res = conn.table("anchor_projects").select("*").eq("status", "Won").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_prod = get_won_jobs()

st.title("🏗️ Production Planning & Material Sync")
st.markdown("---")

if not df_prod.empty:
    # --- 2. ACTIVITY DEFINITION ---
    # Standard SS Pressure Vessel Stages
    stages = [
        "Material Identification/MTC Check",
        "Shell & Dish Layout",
        "Plasma Cutting & Edge Prep",
        "Shell Rolling",
        "Long Seam Welding",
        "Circ Seam Welding",
        "Nozzle Fit-up",
        "Final Welding",
        "NDT (RT/DP/UT)",
        "Hydro-Testing",
        "Pickling & Passivation",
        "Final Inspection/Dispatch"
    ]

    # --- 3. LIVE PRODUCTION BOARD ---
    for index, row in df_prod.iterrows():
        # Visual color coding for stalled projects
        is_stalled = row.get('material_shortage', False)
        
        with st.container(border=True):
            header_col, alert_col = st.columns([3, 1])
            header_col.subheader(f"Job: {row['job_no']} | {row['client_name']}")
            
            if is_stalled:
                alert_col.error("⚠️ MATERIAL SHORTAGE")

            col1, col2, col3 = st.columns([1, 1, 1])

            with col1:
                st.write(f"**Vessel:** {row['project_description']}")
                # We reuse 'drawing_status' for production stage tracking in this basic version
                current_stage = st.selectbox(
                    "Current Activity", 
                    stages, 
                    index=stages.index(row['drawing_status']) if row['drawing_status'] in stages else 0,
                    key=f"stage_{row['id']}"
                )

            with col2:
                st.write("**Material Alert**")
                shortage_flag = st.toggle("Shortage Alert", value=is_stalled, key=f"flag_{row['id']}")
                shortage_note = st.text_input(
                    "Shortage Details", 
                    value=row.get('shortage_details', ""), 
                    placeholder="e.g., Missing 4 nos 3'' Flanges",
                    key=f"note_{row['id']}"
                )

            with col3:
                st.write("**Data Sync**")
                if st.button("Update Shop Floor", key=f"up_{row['id']}", use_container_width=True, type="primary"):
                    conn.table("anchor_projects").update({
                        "drawing_status": current_stage,
                        "material_shortage": shortage_flag,
                        "shortage_details": shortage_note
                    }).eq("id", row['id']).execute()
                    st.success(f"Job {row['job_no']} Updated!")
                    st.rerun()

else:
    st.info("No 'Won' projects found. Once a project is marked 'Won' in the Anchor Portal, it will appear here for production.")
