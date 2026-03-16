import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz
from PIL import Image
import io

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Quality Portal", layout="wide", page_icon="🔍")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. DATA LOADERS (Updated for Troubleshooting) ---
@st.cache_data(ttl=2)
def get_quality_context():
    # 1. Pull Jobs
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    
    # 2. Pull Staff - Updated with error handling
    try:
        # Check if your table is named 'master_staff' or 'staff_master'
        staff_res = conn.table("master_staff").select("name").execute()
        staff_list = sorted([s['name'] for s in staff_res.data]) if staff_res.data else []
    except Exception as e:
        st.error(f"⚠️ Master Staff Error: {e}")
        staff_list = [] # Returns empty list if table not found
    
    return pd.DataFrame(plan_res.data or []), staff_list

df_plan, authorized_inspectors = get_quality_context()

# --- 3. UI: QUALITY INSPECTION FORM ---
st.title("🔍 Quality Assurance Portal")
st.info("Authorized Inspection & Evidence Upload")

if not df_plan.empty:
    c1, c2 = st.columns(2)
    
    unique_jobs = sorted(df_plan['job_no'].unique())
    sel_job = c1.selectbox("🏗️ Select Job Number", ["-- Select --"] + unique_jobs)

    if sel_job != "-- Select --":
        job_stages = df_plan[df_plan['job_no'] == sel_job]
        sel_stage = c2.selectbox("🚪 Select Process/Gate", job_stages['gate_name'].tolist())
        stage_record = job_stages[job_stages['gate_name'] == sel_stage].iloc[0]
        
        st.divider()
        
        with st.form("quality_form", clear_on_submit=True):
            st.subheader(f"Direct Inspection: {sel_job} > {sel_stage}")
            f_col1, f_col2 = st.columns(2)
            
            with f_col1:
                q_status = st.segmented_control(
                    "Inspection Result", 
                    ["✅ Pass", "❌ Reject", "⚠️ Rework"], 
                    default="✅ Pass"
                )
                # Inspector from Master Settings
                inspector = st.selectbox("Authorized Inspector", ["-- Select Name --"] + authorized_inspectors)
                q_notes = st.text_area("Technical Observations", placeholder="Enter specific details about the weld, buffing, or fitment...")

            with f_col2:
                q_photo = st.file_uploader("Capture Photo (Max 60KB Auto-Resize)", type=['png', 'jpg', 'jpeg'])
                st.caption("Upload will automatically resize to passport dimensions and compress to ~60KB.")

            if st.form_submit_button("🚀 Submit Quality Report", use_container_width=True):
                if inspector == "-- Select Name --":
                    st.error("Please select an authorized inspector name.")
                else:
                    try:
                        photo_url = None
                        
                        # --- PHOTO PROCESSING & UPLOAD ---
                        if q_photo is not None:
                            # 1. Open and Resize (Passport Size Proportions)
                            img = Image.open(q_photo)
                            img.thumbnail((500, 500)) 
                            
                            # 2. Compress to Bytes
                            buffer = io.BytesIO()
                            # Start with 70% quality
                            img.save(buffer, format="JPEG", quality=70, optimize=True)
                            
                            # 3. Aggressive compression if still > 60KB
                            if buffer.tell() > 60 * 1024:
                                buffer = io.BytesIO()
                                img.save(buffer, format="JPEG", quality=50, optimize=True)
                            
                            file_bytes = buffer.getvalue()
                            clean_job = str(sel_job).replace("/", "-")
                            file_name = f"{clean_job}_{sel_stage}_{datetime.now().strftime('%H%M%S')}.jpg"
                            
                            # 4. Upload using conn.client.storage
                            conn.client.storage.from_("quality-photos").upload(
                                path=file_name,
                                file=file_bytes,
                                file_options={"content-type": "image/jpeg"}
                            )
                            photo_url = conn.client.storage.from_("quality-photos").get_public_url(file_name)

                        # --- DATABASE UPDATE ---
                        conn.table("job_planning").update({
                            "quality_status": q_status,
                            "quality_notes": f"{datetime.now(IST).strftime('%d/%m %H:%M')}: {q_notes}",
                            "quality_by": inspector,
                            "quality_photo_url": photo_url,
                            "quality_updated_at": datetime.now(IST).isoformat()
                        }).eq("id", stage_record['id']).execute()
                        
                        st.success(f"Quality Clearances Recorded for {sel_job}!")
                        st.cache_data.clear()
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Submission Error: {e}")

else:
    st.warning("No active jobs found in the production plan.")

# --- 4. SUMMARY VIEW & PHOTO PREVIEW ---
st.divider()
st.subheader("📋 Recent Quality Clearances")

if not df_plan.empty:
    inspected_df = df_plan.dropna(subset=['quality_status']).sort_values(by='quality_updated_at', ascending=False)
    
    if not inspected_df.empty:
        # Display as a clean list
        st.dataframe(
            inspected_df[['job_no', 'gate_name', 'quality_status', 'quality_by', 'quality_notes']],
            use_container_width=True, hide_index=True
        )

        # Photo Previewer
        st.markdown("### 🖼️ Evidence Preview")
        photo_list = inspected_df[inspected_df['quality_photo_url'].notna()]
        
        if not photo_list.empty:
            options = photo_list.apply(lambda x: f"{x['job_no']} - {x['gate_name']}", axis=1).tolist()
            selection = st.selectbox("Select record to view photo:", options)
            
            selected_row = photo_list[photo_list.apply(lambda x: f"{x['job_no']} - {x['gate_name']}", axis=1) == selection].iloc[0]
            st.image(selected_row['quality_photo_url'], caption=f"QC Proof: {selection}", use_container_width=True)
        else:
            st.info("No photos uploaded for recent inspections.")
