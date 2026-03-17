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

# --- 2. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_quality_context():
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    try:
        staff_res = conn.table("master_staff").select("name").execute()
        staff_list = sorted([s['name'] for s in staff_res.data]) if staff_res.data else []
    except Exception as e:
        st.error(f"⚠️ Master Staff Error: {e}")
        staff_list = []
    return pd.DataFrame(plan_res.data or []), staff_list

df_plan, authorized_inspectors = get_quality_context()

# --- 3. UI: QUALITY INSPECTION FORM ---
st.title("🔍 Quality Assurance Portal")

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
                q_status = st.segmented_control("Result", ["✅ Pass", "❌ Reject", "⚠️ Rework"], default="✅ Pass")
                inspector = st.selectbox("Authorized Inspector", ["-- Select Name --"] + authorized_inspectors)
                q_notes = st.text_area("Technical Observations")

            with f_col2:
                # UPDATED: Accept up to 4 files
                q_photos = st.file_uploader("Upload Evidence (Max 4 photos, 60KB each)", 
                                           type=['png', 'jpg', 'jpeg'], 
                                           accept_multiple_files=True)
                st.caption("Auto-resizing to Passport size and compressing...")

            if st.form_submit_button("🚀 Submit Quality Report", use_container_width=True):
                if inspector == "-- Select Name --":
                    st.error("Please select an authorized inspector.")
                elif len(q_photos) > 4:
                    st.error("Maximum 4 photos allowed.")
                else:
                    try:
                        all_urls = []
                        
                        # PROCESS EACH PHOTO
                        for i, photo_file in enumerate(q_photos):
                            img = Image.open(photo_file)
                            img.thumbnail((400, 500)) # Passport size dimensions
                            
                            buffer = io.BytesIO()
                            img.save(buffer, format="JPEG", quality=60, optimize=True)
                            
                            # Strict 60KB check
                            if buffer.tell() > 60 * 1024:
                                buffer = io.BytesIO()
                                img.save(buffer, format="JPEG", quality=40, optimize=True)
                            
                            file_name = f"{str(sel_job).replace('/', '-')}_{sel_stage}_{i}_{datetime.now().strftime('%H%M%S')}.jpg"
                            
                            conn.client.storage.from_("quality-photos").upload(
                                path=file_name, file=buffer.getvalue(),
                                file_options={"content-type": "image/jpeg"}
                            )
                            url = conn.client.storage.from_("quality-photos").get_public_url(file_name)
                            all_urls.append(url)

                        # UPDATE DATABASE (Save as Array)
                        conn.table("job_planning").update({
                            "quality_status": q_status,
                            "quality_notes": f"{datetime.now(IST).strftime('%d/%m %H:%M')}: {q_notes}",
                            "quality_by": inspector,
                            "quality_photo_url": all_urls, # Sending list/array
                            "quality_updated_at": datetime.now(IST).isoformat()
                        }).eq("id", stage_record['id']).execute()
                        
                        st.success(f"Successfully recorded with {len(all_urls)} photos!")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Submission Error: {e}")

# --- 4. SUMMARY VIEW & UPDATED GALLERY WITH DELETE ---
st.divider()
st.subheader("📋 Recent Quality Clearances")

if not df_plan.empty:
    inspected_df = df_plan.dropna(subset=['quality_status']).sort_values(by='quality_updated_at', ascending=False)
    
    if not inspected_df.empty:
        st.dataframe(inspected_df[['job_no', 'gate_name', 'quality_status', 'quality_by', 'quality_notes']], use_container_width=True, hide_index=True)

        st.markdown("### 🖼️ Evidence Gallery & Management")
        
        # Filter rows that have photos
        photo_rows = inspected_df[inspected_df['quality_photo_url'].apply(lambda x: len(x) > 0 if isinstance(x, list) else False)]
        
        if not photo_rows.empty:
            sel_row_idx = st.selectbox("Select Job to Manage Photos", photo_rows.index, 
                                      format_func=lambda x: f"{photo_rows.loc[x, 'job_no']} - {photo_rows.loc[x, 'gate_name']}")
            
            current_urls = photo_rows.loc[sel_row_idx, 'quality_photo_url']
            record_id = photo_rows.loc[sel_row_idx, 'id']
            
            # Display Gallery in Columns
            cols = st.columns(4)
            for i, url in enumerate(current_urls):
                with cols[i]:
                    st.image(url, use_container_width=True)
                    # DELETE BUTTON FOR EACH PHOTO
                    if st.button(f"🗑️ Remove {i+1}", key=f"del_{record_id}_{i}"):
                        try:
                            # 1. Identify filename from URL to delete from Storage
                            # URL format is usually .../bucket/filename
                            file_name = url.split("/")[-1]
                            conn.client.storage.from_("quality-photos").remove([file_name])
                            
                            # 2. Update the Database Array (Remove this specific URL)
                            updated_urls = [u for u in current_urls if u != url]
                            conn.table("job_planning").update({
                                "quality_photo_url": updated_urls
                            }).eq("id", record_id).execute()
                            
                            st.toast(f"Photo {i+1} removed successfully!")
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Delete failed: {e}")
        else:
            st.info("No photos uploaded for recent inspections.")
