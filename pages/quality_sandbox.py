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
    # Load planning data for photo-gate process
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    # Load anchor projects for the technical checklist
    anchor_res = conn.table("anchor_projects").select("job_no, client_name, po_no, po_date").execute()
    try:
        staff_res = conn.table("master_staff").select("name").execute()
        staff_list = sorted([s['name'] for s in staff_res.data]) if staff_res.data else []
    except Exception as e:
        st.error(f"⚠️ Master Staff Error: {e}")
        staff_list = []
    return pd.DataFrame(plan_res.data or []), pd.DataFrame(anchor_res.data or []), staff_list

df_plan, df_anchor, authorized_inspectors = get_quality_context()

# --- 3. UI: TABBED NAVIGATION ---
st.title("🔍 Quality Assurance & Inspection Portal")
main_tabs = st.tabs(["🚪 Process Gate (Evidence)", "📋 Technical Checklist (Reports)"])

# =========================================================
# TAB 1: EXISTING PROCESS GATE LOGIC (WITH PHOTOS)
# =========================================================
with main_tabs[0]:
    if not df_plan.empty:
        st.subheader("📸 Direct Gate Inspection with Evidence")
        c1, c2 = st.columns(2)
        unique_jobs = sorted(df_plan['job_no'].unique())
        sel_job = c1.selectbox("🏗️ Select Job Number", ["-- Select --"] + unique_jobs, key="pg_job_sel")

        if sel_job != "-- Select --":
            job_stages = df_plan[df_plan['job_no'] == sel_job]
            sel_stage = c2.selectbox("🚪 Select Process/Gate", job_stages['gate_name'].tolist(), key="pg_gate_sel")
            stage_record = job_stages[job_stages['gate_name'] == sel_stage].iloc[0]
            
            st.divider()
            with st.form("quality_form", clear_on_submit=True):
                st.subheader(f"Inspection: {sel_job} > {sel_stage}")
                f_col1, f_col2 = st.columns(2)
                
                with f_col1:
                    q_status = st.segmented_control("Result", ["✅ Pass", "❌ Reject", "⚠️ Rework"], default="✅ Pass")
                    inspector = st.selectbox("Authorized Inspector", ["-- Select Name --"] + authorized_inspectors, key="pg_insp")
                    q_notes = st.text_area("Technical Observations", key="pg_notes")

                with f_col2:
                    q_photos = st.file_uploader("Upload Evidence (Max 4, 60KB each)", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
                    st.caption("Auto-resizing to passport size enabled.")

                if st.form_submit_button("🚀 Submit Photo Evidence", use_container_width=True):
                    # --- PHOTO PROCESSING LOGIC ---
                    if inspector == "-- Select Name --":
                        st.error("Select Inspector")
                    elif len(q_photos) > 4:
                        st.error("Max 4 photos")
                    else:
                        try:
                            all_urls = []
                            for i, photo_file in enumerate(q_photos):
                                img = Image.open(photo_file)
                                img.thumbnail((400, 500))
                                buffer = io.BytesIO()
                                img.save(buffer, format="JPEG", quality=60, optimize=True)
                                
                                file_name = f"{str(sel_job).replace('/', '-')}_{sel_stage}_{i}_{datetime.now().strftime('%H%M%S')}.jpg"
                                conn.client.storage.from_("quality-photos").upload(
                                    path=file_name, file=buffer.getvalue(),
                                    file_options={"content-type": "image/jpeg"}
                                )
                                url = conn.client.storage.from_("quality-photos").get_public_url(file_name)
                                all_urls.append(url)

                            conn.table("job_planning").update({
                                "quality_status": q_status,
                                "quality_notes": f"{datetime.now(IST).strftime('%d/%m %H:%M')}: {q_notes}",
                                "quality_by": inspector,
                                "quality_photo_url": all_urls,
                                "quality_updated_at": datetime.now(IST).isoformat()
                            }).eq("id", stage_record['id']).execute()
                            
                            st.success("Gate status updated!"); st.rerun()
                        except Exception as e: st.error(f"Error: {e}")

# =========================================================
# TAB 2: NEW TECHNICAL CHECKLIST (REPORT DATA)
# =========================================================
with main_tabs[1]:
    st.subheader("📋 Final Technical Inspection Report")
    st.caption("Complete this form for daily documentation and PDF report generation.")

    if not df_anchor.empty:
        with st.container(border=True):
            tc1, tc2, tc3 = st.columns(3)
            q_job = tc1.selectbox("Identify Job No", ["-- Select Job --"] + df_anchor['job_no'].tolist(), key="tc_job")
            
            # Auto-fill Logic
            c_val, p_val, d_val = "", "", datetime.now()
            if q_job != "-- Select Job --":
                match = df_anchor[df_anchor['job_no'] == q_job].iloc[0]
                c_val, p_val = match.get('client_name', ''), match.get('po_no', '')
                try: d_val = pd.to_datetime(match.get('po_date'))
                except: d_val = datetime.now()

            q_client = tc2.text_input("Customer Name", value=c_val, key="tc_cli")
            q_po = tc3.text_input("PO Number", value=p_val, key="tc_po")

        if q_job != "-- Select Job --":
            with st.form("technical_checklist_form"):
                st.write("### ⚙️ Inspection Checkpoints")
                col_a, col_b = st.columns(2)
                opts = ["Pending", "Verified/OK", "Rejected", "N/A"]
                
                with col_a:
                    v1 = st.selectbox("1. Material Certification", opts)
                    v2 = st.selectbox("2. Fit-up Examination (100%)", opts)
                    v3 = st.selectbox("3. Dimensions & Visual Exam", opts)
                    v4 = st.selectbox("4. Liquid Penetrant Test", opts)
                
                with col_b:
                    v5 = st.selectbox("5. Hydro / Vacuum Test", opts)
                    v6 = st.selectbox("6. Final Inspection (Pre-Dispatch)", opts)
                    v7 = st.selectbox("7. Identification Punching", opts)
                    v8 = st.selectbox("8. NCR Status", ["None", "Open", "Closed"])

                st.divider()
                f1, f2 = st.columns(2)
                q_inspector = f1.selectbox("Inspector Name", ["-- Select --"] + authorized_inspectors, key="tc_insp")
                q_remarks = f2.text_area("Technical Remarks", key="tc_notes")

                if st.form_submit_button("✅ Finalize Quality Record"):
                    if q_inspector == "-- Select --":
                        st.error("Please select an inspector.")
                    else:
                        conn.table("quality_check_list").insert({
                            "job_no": q_job, "client_name": q_client, "po_no": q_po,
                            "mat_cert_status": v1, "fit_up_status": v2, "visual_status": v3,
                            "pt_weld_status": v4, "hydro_status": v5, "final_status": v6,
                            "punching_status": v7, "ncr_status": v8,
                            "inspected_by": q_inspector, "technical_notes": q_remarks
                        }).execute()
                        st.success("Record Saved Successfully!"); st.rerun()

# --- 4. SHARED GALLERY VIEW ---
st.divider()
st.subheader("📋 Recent Quality Clearances")
if not df_plan.empty:
    inspected_df = df_plan.dropna(subset=['quality_status']).sort_values(by='quality_updated_at', ascending=False)
    if not inspected_df.empty:
        st.dataframe(inspected_df[['job_no', 'gate_name', 'quality_status', 'quality_by', 'quality_notes']], use_container_width=True, hide_index=True)
