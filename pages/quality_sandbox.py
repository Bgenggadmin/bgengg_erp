import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz
from PIL import Image
import io
from fpdf import FPDF
import base64

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Quality Portal", layout="wide", page_icon="🔍")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SMART UTILITIES & HELPERS ---

def create_birth_certificate(job_no, header_data, tech_data, photo_data):
    pdf = FPDF()
    pdf.add_page()
    
    # Header: B&G Engineering Branding
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(190, 10, "B&G ENGINEERING - PRODUCT BIRTH CERTIFICATE", ln=True, align='C')
    pdf.set_font("Arial", '', 10)
    pdf.cell(190, 5, f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align='C')
    pdf.ln(10)
    
    # Section 1: Product Identification
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(190, 8, "SECTION 1: PRODUCT IDENTIFICATION", ln=True, fill=True)
    pdf.set_font("Arial", '', 10)
    
    col_width = 95
    pdf.cell(col_width, 7, f"Job Number: {job_no}")
    pdf.cell(col_width, 7, f"Client: {header_data['client_name']}", ln=True)
    pdf.cell(col_width, 7, f"PO Number: {header_data['po_no']}")
    pdf.cell(col_width, 7, f"PO Date: {header_data['po_date']}", ln=True)
    pdf.cell(col_width, 7, f"Drawing No: {header_data['drawing_no']}", ln=True)
    pdf.ln(5)

    # Section 2: Technical Compliance
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(190, 8, "SECTION 2: QUALITY CHECKLIST COMPLIANCE", ln=True, fill=True)
    pdf.set_font("Arial", '', 9)
    
    # List of technical keys to include in PDF
    tech_keys = [
        "mat_cert_status", "fit_up_status", "visual_status", 
        "pt_weld_status", "hydro_status", "final_status", 
        "punching_status", "ncr_status"
    ]
    
    for i, key in enumerate(tech_keys):
        label = key.replace('_status','').replace('_',' ').title()
        val = tech_data.get(key, "N/A")
        pdf.cell(95, 8, f"{label}: {val}", border=1)
        if i % 2 != 0: pdf.ln(8)
    pdf.ln(10)

    # Section 3: Manufacturing Stage Evidence
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(190, 8, "SECTION 3: MANUFACTURING STAGE EVIDENCE", ln=True, fill=True)
    
    if not photo_data.empty:
        for idx, row in photo_data.iterrows():
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(190, 7, f"Gate: {row['gate_name']} (Status: {row['quality_status']})", ln=True)
            pdf.set_font("Arial", 'I', 8)
            pdf.multi_cell(190, 5, f"Notes: {row['quality_notes']}")
            pdf.ln(2)
    
    return pdf.output(dest='S').encode('latin-1')

# --- 3. DATA LOADERS (Existing) ---
@st.cache_data(ttl=2)
def get_quality_context():
    # 1. Fetch Planning Data
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    # 2. Fetch Anchor Data
    anchor_res = conn.table("anchor_projects").select("job_no, client_name, po_no, po_date").execute()
    # 3. Fetch Staff List
    try:
        staff_res = conn.table("master_staff").select("name").execute()
        staff_list = sorted([s['name'] for s in staff_res.data]) if staff_res.data else []
    except Exception as e:
        st.error(f"⚠️ Master Staff Error: {e}")
        staff_list = []
    
    # RETURNS THREE ITEMS
    return pd.DataFrame(plan_res.data or []), pd.DataFrame(anchor_res.data or []), staff_list

# CRITICAL CALL LINE:
df_plan, df_anchor, authorized_inspectors = get_quality_context()

# --- 3. UI: TABBED NAVIGATION ---
st.title("🔍 Quality Assurance & Inspection Portal")
main_tabs = st.tabs(["🚪 Process Gate (Evidence)", "📋 Technical Checklist (Reports)"])

# =========================================================
# TAB 1: PROCESS GATE LOGIC (WITH MARKETING PDF)
# =========================================================
with main_tabs[0]:
    if not df_plan.empty:
        st.subheader("📸 Direct Gate Inspection & Marketing Presentation")
        c1, c2 = st.columns(2)
        unique_jobs = sorted(df_plan['job_no'].unique())
        sel_job = c1.selectbox("🏗️ Select Job Number", ["-- Select --"] + unique_jobs, key="pg_job_sel")

        if sel_job != "-- Select --":
            # --- MARKETING SECTION (ADDED) ---
            with st.container(border=True):
                st.markdown("### 💎 Live Client Presentation")
                st.caption("Generate a visual 'Birth Certificate' showing all completed process gate photos for this job.")
                
                # Prepare data for PDF
                # 1. Fetch Header Info from Anchor
                h_match = df_anchor[df_anchor['job_no'] == sel_job]
                if not h_match.empty:
                    h_row = h_match.iloc[0]
                    h_data = {
                        "client_name": h_row.get('client_name', 'N/A'),
                        "po_no": h_row.get('po_no', 'N/A'),
                        "po_date": str(h_row.get('po_date', 'N/A')),
                        "drawing_no": "Refer Technical Tab"
                    }
                else:
                    h_data = {"client_name": "Unknown", "po_no": "N/A", "po_date": "N/A", "drawing_no": "N/A"}

                # 2. Fetch latest Tech Status
                tech_res = conn.table("quality_check_list").select("*").eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute().data
                t_data = tech_res[0] if tech_res else {}

                # 3. Fetch all gate photos
                p_data = df_plan[df_plan['job_no'] == sel_job]

                # 4. Generate Button
                try:
                    pdf_bytes = create_birth_certificate(sel_job, h_data, t_data, p_data)
                    st.download_button(
                        label=f"📂 GENERATE LIVE BIRTH CERTIFICATE: {sel_job}",
                        data=pdf_bytes,
                        file_name=f"BG_Quality_Dossier_{sel_job}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary"
                    )
                except Exception as e:
                    st.info("Log technical data in Tab 2 to enable full PDF features.")

            st.divider()
            
            # --- EXISTING INSPECTION FORM ---
            job_stages = df_plan[df_plan['job_no'] == sel_job]
            sel_stage = c2.selectbox("🚪 Select Process/Gate", job_stages['gate_name'].tolist(), key="pg_gate_sel")
            stage_record = job_stages[job_stages['gate_name'] == sel_stage].iloc[0]
            
            with st.form("quality_form", clear_on_submit=True):
                st.subheader(f"Log New Evidence: {sel_job} > {sel_stage}")
                f_col1, f_col2 = st.columns(2)
                
                with f_col1:
                    q_status = st.segmented_control("Result", ["✅ Pass", "❌ Reject", "⚠️ Rework"], default="✅ Pass")
                    inspector = st.selectbox("Authorized Inspector", ["-- Select Name --"] + authorized_inspectors, key="pg_insp")
                    q_notes = st.text_area("Technical Observations", key="pg_notes")

                with f_col2:
                    q_photos = st.file_uploader("Upload Evidence (Max 4)", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

                if st.form_submit_button("🚀 Submit Gate Report", use_container_width=True):
                    # ... [YOUR EXISTING PHOTO PROCESSING LOGIC] ...
                    pass

# =========================================================
# TAB 2: UPDATED TECHNICAL CHECKLIST & ON-SPOT PDF
# =========================================================
with main_tabs[1]:
    st.subheader("📋 Final Technical Inspection & Birth Certificate")
    
    if not df_anchor.empty:
        # 1. HEADER SECTION
        with st.container(border=True):
            tc1, tc2, tc3 = st.columns(3)
            q_job = tc1.selectbox("Identify Job No", ["-- Select Job --"] + df_anchor['job_no'].tolist(), key="tc_job")
            
            c_val, p_val = "", ""
            d_val = datetime.now()
            if q_job != "-- Select Job --":
                match = df_anchor[df_anchor['job_no'] == q_job].iloc[0]
                c_val, p_val = match.get('client_name', ''), match.get('po_no', '')
                try: d_val = pd.to_datetime(match.get('po_date'))
                except: d_val = datetime.now()

            q_client = tc2.text_input("Customer Name", value=c_val, key="tc_cli")
            q_po = tc3.text_input("PO Number", value=p_val, key="tc_po")
            
            tc4, tc5 = st.columns(2)
            q_po_date = tc4.date_input("PO Date", value=d_val, key="tc_po_date")
            q_drawing = tc5.text_input("Drawing No / Revision", placeholder="BG-ENG-001", key="tc_draw")

        # 2. THE "ON THE SPOT" PRESENTATION LOGIC
        if q_job != "-- Select Job --":
            st.divider()
            st.markdown("### 💎 Marketing Presentation Mode")
            
            # --- AUTO-PREPARE DATA ---
            h_data = {"client_name": q_client, "po_no": q_po, "po_date": str(q_po_date), "drawing_no": q_drawing}
            
            # Fetch tech status (if exists)
            tech_res = conn.table("quality_check_list").select("*").eq("job_no", q_job).order("created_at", desc=True).limit(1).execute().data
            t_data = tech_res[0] if tech_res else {}
            
            # Fetch gate evidence
            p_data = df_plan[df_plan['job_no'] == q_job]

            # --- GENERATE PDF AUTOMATICALLY IN MEMORY ---
            try:
                pdf_bytes = create_birth_certificate(q_job, h_data, t_data, p_data)
                
                # Big Presentation Button
                st.download_button(
                    label=f"📂 DOWNLOAD BIRTH CERTIFICATE: {q_job}",
                    data=pdf_bytes,
                    file_name=f"BG_Birth_Cert_{q_job}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    type="primary" # Makes the button blue/noticeable
                )
            except Exception as e:
                st.warning(f"Note: Ensure technical data is logged to generate full certificate. Error: {e}")

            # 3. DATA ENTRY FORM (Below the presentation button)
            with st.expander("📝 Log/Update Technical Checkpoints", expanded=False):
                with st.form("technical_checklist_form"):
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

                    f1, f2 = st.columns(2)
                    q_inspector = f1.selectbox("Inspector Name", ["-- Select --"] + authorized_inspectors, key="tc_insp")
                    q_remarks = f2.text_area("Technical Remarks", key="tc_notes")

                    if st.form_submit_button("✅ Finalize Quality Record"):
                        conn.table("quality_check_list").insert({
                            "job_no": q_job, "client_name": q_client, "po_no": q_po, "po_date": str(q_po_date),
                            "drawing_no": q_drawing, "mat_cert_status": v1, "fit_up_status": v2, 
                            "visual_status": v3, "pt_weld_status": v4, "hydro_status": v5, 
                            "final_status": v6, "punching_status": v7, "ncr_status": v8,
                            "inspected_by": q_inspector, "technical_notes": q_remarks
                        }).execute()
                        st.success("Record Saved!"); st.rerun()
# --- 4. SHARED GALLERY VIEW ---
st.divider()
st.subheader("📋 Recent Quality Clearances")
if not df_plan.empty:
    inspected_df = df_plan.dropna(subset=['quality_status']).sort_values(by='quality_updated_at', ascending=False)
    if not inspected_df.empty:
        st.dataframe(inspected_df[['job_no', 'gate_name', 'quality_status', 'quality_by', 'quality_notes']], use_container_width=True, hide_index=True)
