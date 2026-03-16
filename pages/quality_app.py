import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Quality Portal", layout="wide", page_icon="🔍")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_quality_context():
    # Only pull jobs that are currently 'Active' or 'Completed' 
    # This ensures inspectors only see what is actually on the floor
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    return pd.DataFrame(plan_res.data or [])

df_plan = get_quality_context()

# --- 3. UI: QUALITY INSPECTION FORM ---
st.title("🔍 Quality Assurance Portal")
st.markdown("---")

if not df_plan.empty:
    # Selection Area
    c1, c2 = st.columns(2)
    
    unique_jobs = sorted(df_plan['job_no'].unique())
    sel_job = c1.selectbox("🏗️ Select Job Number", ["-- Select --"] + unique_jobs)

    if sel_job != "-- Select --":
        job_stages = df_plan[df_plan['job_no'] == sel_job]
        sel_stage = c2.selectbox("🚪 Select Process/Gate", job_stages['gate_name'].tolist())

        # Get the specific record ID for this stage
        stage_record = job_stages[job_stages['gate_name'] == sel_stage].iloc[0]
        
        # Form for Inspection
        with st.form("quality_form", clear_on_submit=True):
            st.subheader(f"Inspection for: {sel_job} - {sel_stage}")
            
            f_col1, f_col2 = st.columns(2)
            
            with f_col1:
                q_status = st.segmented_control(
                    "Result", 
                    ["✅ Pass", "❌ Reject", "⚠️ Rework"], 
                    default="✅ Pass"
                )
                inspector = st.text_input("Inspector Name/ID")
                q_notes = st.text_area("Observations", placeholder="E.g. Weld root penetration satisfactory, surface finish clear.")

            with f_col2:
                q_photo = st.file_uploader("Capture/Upload Photo", type=['png', 'jpg', 'jpeg'])
                st.info("💡 Tip: Use mobile camera for direct upload.")

            # Submission Logic
            if st.form_submit_button("🚀 Submit Quality Report", use_container_width=True):
                if not inspector:
                    st.error("Please enter the Inspector's name.")
                else:
                    try:
                        photo_url = None
                        
                        # --- PHOTO UPLOAD LOGIC ---
                        if q_photo is not None:
                            file_ext = q_photo.name.split(".")[-1]
                            clean_job = str(sel_job).replace("/", "-")
                            # Unique filename: Job_Stage_Time.jpg
                            file_name = f"{clean_job}_{sel_stage}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file_ext}"
                            
                            # Upload to Supabase Storage Bucket 'quality-photos'
                            storage_res = conn.storage.from_("quality-photos").upload(
                                path=file_name,
                                file=q_photo.getvalue(),
                                file_options={"content-type": f"image/{file_ext}"}
                            )
                            photo_url = conn.storage.from_("quality-photos").get_public_url(file_name)

                        # --- DATABASE UPDATE ---
                        conn.table("job_planning").update({
                            "quality_status": q_status,
                            "quality_notes": f"{datetime.now(IST).strftime('%d/%m %H:%M')}: {q_notes}",
                            "quality_by": inspector,
                            "quality_photo_url": photo_url,
                            "quality_updated_at": datetime.now(IST).isoformat()
                        }).eq("id", stage_record['id']).execute()
                        
                        st.success(f"Report & Photo Saved for {sel_job}!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error during submission: {e}")

else:
    st.warning("No active jobs found in the production plan.")

# --- 4. SUMMARY VIEW & PHOTO PREVIEW ---
st.divider()
st.subheader("📋 Recent Quality Clearances")

if not df_plan.empty:
    # Filter for inspected items
    inspected_df = df_plan.dropna(subset=['quality_status']).sort_values(by='quality_updated_at', ascending=False)
    
    if not inspected_df.empty:
        # 1. Show the Data Table
        st.dataframe(
            inspected_df[['job_no', 'gate_name', 'quality_status', 'quality_by', 'quality_notes']],
            use_container_width=True,
            hide_index=True
        )

        # 2. Photo Previewer
        st.markdown("### 🖼️ Photo Preview")
        # Let the user pick which recent record to view the photo for
        photo_list = inspected_df[inspected_df['quality_photo_url'].notna()]
        
        if not photo_list.empty:
            options = photo_list.apply(lambda x: f"{x['job_no']} - {x['gate_name']}", axis=1).tolist()
            selection = st.selectbox("Select a record to view its photo:", options)
            
            # Find the selected photo URL
            selected_row = photo_list[photo_list.apply(lambda x: f"{x['job_no']} - {x['gate_name']}", axis=1) == selection].iloc[0]
            
            # Display the image
            st.image(selected_row['quality_photo_url'], caption=f"Evidence for {selection}", use_container_width=True)
        else:
            st.info("No photos available for recent clearances.")
    else:
        st.write("No inspections recorded yet.")
