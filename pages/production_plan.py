import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="Production Control | BGEngg ERP", layout="wide", page_icon="🏭")

conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=5)
def get_won_jobs():
    res = conn.table("anchor_projects").select("*").eq("status", "Won").order("id").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df_prod = get_won_jobs()

# --- 1. UNIVERSAL GATES & LEAD TIMES ---
universal_stages = [
    "1. Engineering & MTC Verify", "2. Marking & Cutting", "3. Sub-Assembly & Machining",
    "4. Shell/Body Fabrication", "5. Main Assembly/Internals", "6. Nozzles & Accessories",
    "7. Inspection & NDT", "8. Hydro/Pressure Testing", "9. Insulation & Finishing",
    "10. Final Assembly & Dispatch"
]

days_to_finish = {
    "1. Engineering & MTC Verify": 45, "2. Marking & Cutting": 40, "3. Sub-Assembly & Machining": 35,
    "4. Shell/Body Fabrication": 30, "5. Main Assembly/Internals": 22, "6. Nozzles & Accessories": 15,
    "7. Inspection & NDT": 10, "8. Hydro/Pressure Testing": 7, "9. Insulation & Finishing": 4,
    "10. Final Assembly & Dispatch": 1
}

st.title("🏭 Production & Dispatch Planning")

# --- 2. EXPORT / DOWNLOAD SECTION ---
if not df_prod.empty:
    with st.expander("📊 Export Production Report for Meeting"):
        # Create a formatted dataframe for export
        report_df = df_prod.copy()
        report_df['Est. Days Left'] = report_df['drawing_status'].map(days_to_finish).fillna(45)
        report_df['Projected Dispatch'] = report_df['Est. Days Left'].apply(lambda x: (datetime.now() + timedelta(days=x)).strftime('%d-%b-%Y'))
        
        # Select and rename columns for clarity
        export_cols = {
            'job_no': 'Job No',
            'client_name': 'Customer',
            'project_description': 'Equipment Details',
            'drawing_status': 'Current Gate',
            'material_shortage': 'Shortage Alert',
            'shortage_details': 'Floor Remarks',
            'Projected Dispatch': 'Target Date'
        }
        final_report = report_df[list(export_cols.keys())].rename(columns=export_cols)
        
        st.dataframe(final_report, use_container_width=True, hide_index=True)
        
        csv = final_report.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="💾 Download CSV for Shop Meeting",
            data=csv,
            file_name=f"BGEngg_Production_{datetime.now().strftime('%d_%b')}.csv",
            mime='text/csv',
            use_container_width=True
        )

st.markdown("---")

# --- 3. SMART CHECKLIST LOGIC ---
def show_checklist(desc, job_id):
    desc = desc.upper()
    st.write("📋 **Critical Component Checklist**")
    cols = st.columns(3)
    # Reactor / Mixer
    if any(x in desc for x in ["REACTOR", "BLENDER", "ANFD", "MIXER"]):
        with cols[0]:
            st.checkbox("Drive/Motor Align", key=f"ch1_{job_id}")
            st.checkbox("Agitator Clearance", key=f"ch2_{job_id}")
        with cols[1]:
            st.checkbox("Mechanical Seal Prep", key=f"ch3_{job_id}")
            st.checkbox("Bearing Housing", key=f"ch4_{job_id}")
    # Tanks / Receivers
    if any(x in desc for x in ["JACKET", "INSULATED", "RECEIVER", "TCVD", "TANK"]):
        with cols[0]: st.checkbox("Jacket Pressure Test", key=f"ch5_{job_id}")
        with cols[1]: st.checkbox("Insulation (Puff/Wool)", key=f"ch6_{job_id}")
    # Heat Exchangers / ZLD
    if any(x in desc for x in ["CONDENSER", "COLUMN", "REBOILER", "CALENDRIA"]):
        with cols[0]: st.checkbox("Tube Sheet Welding", key=f"ch7_{job_id}")
        with cols[1]: st.checkbox("Internal Packing", key=f"ch8_{job_id}")
    with cols[2]:
        st.checkbox("MTC Verified", key=f"ch9_{job_id}")
        st.checkbox("NDT Clear", key=f"ch10_{job_id}")

# --- 4. MAIN PRODUCTION CARDS ---
if not df_prod.empty:
    for index, row in df_prod.iterrows():
        current_idx = universal_stages.index(row['drawing_status']) if row['drawing_status'] in universal_stages else 0
        days_left = days_to_finish.get(row['drawing_status'], 45)
        proj_date = (datetime.now() + timedelta(days=days_left)).strftime('%d-%b')

        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.subheader(f"Job {row['job_no']} | {row['client_name']}")
            c1.caption(f"🛠️ {row['project_description']}")
            
            c2.metric("Target Dispatch", proj_date, f"{days_left} days")
            
            if row.get('material_shortage'):
                c3.error(f"🚨 SHORTAGE: {row.get('shortage_details', 'Pending')}")
            else:
                c3.success("✅ Workflow OK")

            st.progress((current_idx + 1) / len(universal_stages))

            col1, col2, col3 = st.columns(3)
            new_stage = col1.selectbox("Current Gate", universal_stages, index=current_idx, key=f"stg_{row['id']}")
            new_shortage = col2.toggle("Report Shortage", value=row.get('material_shortage', False), key=f"sh_{row['id']}")
            new_note = col3.text_input("Floor Remarks", value=row.get('shortage_details', ""), key=f"nt_{row['id']}")

            if st.button("Save Updates", key=f"sync_{row['id']}", type="primary", use_container_width=True):
                conn.table("anchor_projects").update({
                    "drawing_status": new_stage,
                    "material_shortage": new_shortage,
                    "shortage_details": new_note,
                    "last_activity_update": datetime.now().isoformat()
                }).eq("id", row['id']).execute()
                st.toast("Updated Successfully!")
                st.rerun()

            with st.expander("🔍 View Technical Checklist"):
                show_checklist(row['project_description'], row['id'])
else:
    st.info("No active production jobs.")
