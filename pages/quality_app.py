import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Quality Inspector", layout="wide", page_icon="🔍")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_quality_context():
    # Only pull jobs that are currently 'Active' or 'Completed' (needing clearance)
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    return pd.DataFrame(plan_res.data or [])

df_plan = get_quality_context()

# --- 3. UI: QUALITY INSPECTION FORM ---
st.title("🔍 Quality Assurance Portal")
st.info("Record inspections for Active or Completed production stages.")

if not df_plan.empty:
    # Filter 1: Select Job
    unique_jobs = sorted(df_plan['job_no'].unique())
    sel_job = st.selectbox("Select Job for Inspection", ["-- Select --"] + unique_jobs)

    if sel_job != "-- Select --":
        # Filter 2: Select Stage (Gate) for that Job
        job_stages = df_plan[df_plan['job_no'] == sel_job]
        sel_stage = st.selectbox("Select Stage to Inspect", job_stages['gate_name'].tolist())

        # Get the specific record ID for this stage
        stage_record = job_stages[job_stages['gate_name'] == sel_stage].iloc[0]
        
        st.divider()
        
        with st.form("quality_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            
            # Inspection Data
            q_status = c1.segmented_control(
                "Inspection Result", 
                ["✅ Pass", "❌ Reject", "⚠️ Rework"], 
                default="✅ Pass"
            )
            inspector = c1.text_input("Inspected By (Name/Initial)")
            
            # Photo Upload (Supabase storage or URL linking)
            # Note: For now, we store the note; you can add actual storage.upload later
            q_photo = c2.file_uploader("Upload Inspection Photo", type=['png', 'jpg', 'jpeg'])
            q_notes = st.text_area("Observation Notes (e.g., 'Weld root penetration OK', 'Buffing marks visible')")

            if st.form_submit_button("Submit Inspection Report"):
                if not inspector:
                    st.error("Please enter the Inspector's name.")
                else:
                    try:
                        photo_url = None
                        
                        # --- PHOTO UPLOAD LOGIC ---
                        if q_photo is not None:
                            # Create a unique filename: JobNo_Stage_Timestamp.jpg
                            file_ext = q_photo.name.split(".")[-1]
                            clean_job = str(sel_job).replace("/", "-")
                            file_name = f"{clean_job}_{sel_stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file_ext}"
                            
                            # Upload to Supabase Storage Bucket
                            storage_res = conn.storage.from_("quality-photos").upload(
                                path=file_name,
                                file=q_photo.getvalue(),
                                file_options={"content-type": f"image/{file_ext}"}
                            )
                            # Get the public URL to save in the table
                            photo_url = conn.storage.from_("quality-photos").get_public_url(file_name)

                        # --- DATABASE UPDATE ---
                        conn.table("job_planning").update({
                            "quality_status": q_status,
                            "quality_notes": f"{datetime.now(IST).strftime('%d/%m %H:%M')}: {q_notes}",
                            "quality_by": inspector,
                            "quality_photo_url": photo_url, # Add this column to SQL if you use this
                            "quality_updated_at": datetime.now(IST).isoformat()
                        }).eq("id", stage_record['id']).execute()
                        
                        st.success(f"Report & Photo Saved for {sel_job}!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

# --- 4. SUMMARY VIEW ---
st.subheader("📋 Recent Quality Clearances")
if not df_plan.empty:
    # Show only those that have been inspected
    inspected_df = df_plan.dropna(subset=['quality_status'])
    if not inspected_df.empty:
        st.dataframe(
            inspected_df[['job_no', 'gate_name', 'quality_status', 'quality_by', 'quality_notes']],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.write("No inspections recorded yet.")
