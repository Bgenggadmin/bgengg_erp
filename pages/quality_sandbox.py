import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz
from PIL import Image
import io
from fpdf import FPDF
import base64
import requests
from tempfile import NamedTemporaryFile

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Quality Portal", layout="wide", page_icon="🔍")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SMART UTILITIES & HELPERS ---

def create_birth_certificate(job_no, header_data, tech_data, photo_data):
    # HELPER: Remove emojis to prevent 'latin-1' crash
    def clean_text(text):
        if not text: return "N/A"
        text = str(text).replace("✅", "[PASS]").replace("❌", "[REJECT]").replace("⚠️", "[REWORK]")
        return text.encode('ascii', 'ignore').decode('ascii')

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # --- 1. BRANDED HEADER ---
    pdf.set_font("Arial", 'B', 16)
    pdf.set_text_color(0, 51, 102) # B&G Dark Blue
    pdf.cell(190, 10, "B&G ENGINEERING INDUSTRIES", ln=True, align='C')
    pdf.set_font("Arial", 'B', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(190, 5, "CHEMICAL PROCESS EQUIPMENT SPECIALISTS", ln=True, align='C')
    pdf.set_draw_color(0, 51, 102)
    pdf.line(10, 27, 200, 27)
    pdf.ln(10)

    # --- 2. BIRTH CERTIFICATE TITLE ---
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(190, 10, f"PRODUCT BIRTH CERTIFICATE: {job_no}", ln=True, align='L')
    pdf.ln(2)

    # --- 3. PRODUCT IDENTIFICATION TABLE ---
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", 'B', 10)
    # Header Row
    pdf.cell(95, 8, " CLIENT / CUSTOMER DETAILS", border=1, fill=True)
    pdf.cell(95, 8, " PURCHASE ORDER DETAILS", border=1, fill=True, ln=True)
    # Data Rows
    pdf.set_font("Arial", '', 10)
    pdf.cell(95, 8, f" Name: {clean_text(header_data['client_name'])}", border=1)
    pdf.cell(95, 8, f" PO No: {clean_text(header_data['po_no'])}", border=1, ln=True)
    pdf.cell(95, 8, f" Drawing No: {clean_text(header_data.get('drawing_no', 'N/A'))}", border=1)
    pdf.cell(95, 8, f" PO Date: {clean_text(header_data['po_date'])}", border=1, ln=True)
    pdf.ln(10)

    # --- 4. MANUFACTURING RECORD (DATE-WISE WITH PHOTOS) ---
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(190, 8, "MANUFACTURING LOG & VISUAL EVIDENCE", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    if not photo_data.empty:
        # 1. Clean the data: Remove rows where quality_updated_at is missing to avoid NaT errors
        photo_data = photo_data.dropna(subset=['quality_updated_at'])
        
        # 2. Sort by completion time
        photo_data = photo_data.sort_values('quality_updated_at')
        
        for idx, row in photo_data.iterrows():
            # SAFETY CHECK FOR DATE
            raw_date = row.get('quality_updated_at')
            if pd.notnull(raw_date):
                date_str = pd.to_datetime(raw_date).strftime('%d-%m-%Y')
            else:
                date_str = "Date Pending"

            # Entry Box Bricks
            pdf.set_font("Arial", 'B', 10)
            pdf.set_fill_color(230, 240, 255)
            pdf.cell(190, 8, f" [{date_str}] - {clean_text(row['gate_name'])}", border="TLR", ln=True, fill=True)
            
                      
            pdf.set_font("Arial", '', 9)
            pdf.multi_cell(190, 6, f" Inspector: {clean_text(row['quality_by'])} | Status: {clean_text(row['quality_status'])}\n Remarks: {clean_text(row['quality_notes'])}", border="LR")
            
            # --- IMAGE HANDLING ---
            urls = row.get('quality_photo_url', [])
            if isinstance(urls, list) and len(urls) > 0:
                # Create a row for images
                x_start = pdf.get_x()
                y_start = pdf.get_y()
                img_width = 45
                
                for i, url in enumerate(urls[:4]): # Show up to 4 images per gate
                    try:
                        response = requests.get(url)
                        if response.status_status == 200:
                            with NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                                tmp.write(response.content)
                                tmp_path = tmp.name
                            pdf.image(tmp_path, x=10 + (i * (img_width + 2)), y=y_start + 2, w=img_width)
                    except:
                        continue
                
                pdf.set_y(y_start + 40) # Advance Y after images
            
            pdf.cell(190, 2, "", border="BLR", ln=True) # Bottom border
            pdf.ln(5)
    else:
        pdf.cell(190, 10, "No visual records found for this product.", ln=True)

    # --- 5. FOOTER ---
    pdf.set_y(-25)
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(190, 10, f"This is a digitally generated Birth Certificate from B&G ERP. Page {pdf.page_no()}", align='C')

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
            # --- PROFESSIONAL MARKETING PRESENTATION (TAB 1) ---
            with st.container(border=True):
                st.subheader("💎 Presentation Mode")
                
                # 1. Prepare Header (Anchor Data)
                h_match = df_anchor[df_anchor['job_no'] == sel_job]
                h_data = {
                    "client_name": h_match.iloc[0].get('client_name', 'N/A') if not h_match.empty else "N/A",
                    "po_no": h_match.iloc[0].get('po_no', 'N/A') if not h_match.empty else "N/A",
                    "po_date": str(h_match.iloc[0].get('po_date', 'N/A')) if not h_match.empty else "N/A",
                    "drawing_no": "Verified on Shop Floor"
                }

                # 2. Fetch Visual Data (Photos/Gate Status)
                p_data = df_plan[df_plan['job_no'] == sel_job]

                # 3. Fetch Tech Data (If exists, use it. If not, send empty dict)
                # This prevents the "Log technical data" message from blocking you
                tech_res = conn.table("quality_check_list").select("*").eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute().data
                t_data = tech_res[0] if tech_res else {}

                # 4. INSTANT PDF GENERATION
                try:
                    pdf_bytes = create_birth_certificate(sel_job, h_data, t_data, p_data)
                    
                    st.download_button(
                        label=f"📂 DOWNLOAD PRODUCT BIRTH CERTIFICATE: {sel_job}",
                        data=pdf_bytes,
                        file_name=f"BG_Birth_Cert_{sel_job}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary",
                        key="pg_marketing_pdf"
                    )
                    
                    # Optional: Subtle hint if tech data is missing
                    if not t_data:
                        st.caption("ℹ️ Presentation contains Manufacturing Photos. Technical checklist pending.")
                        
                except Exception as e:
                    st.error(f"Could not generate PDF: {e}")

            st.divider()

            st.divider()

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
