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
import os 

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Quality Portal", layout="wide", page_icon="🔍")
conn = st.connection("supabase", type=SupabaseConnection)

# --- 2. SMART UTILITIES & HELPERS ---

def create_birth_certificate(job_no, header_data, tech_data, photo_data):
    def clean_text(text):
        if not text: return "N/A"
        # Character safety for FPDF (Standard Latin-1)
        text = str(text).replace("✅", "[PASS]").replace("❌", "[REJECT]").replace("⚠️", "[REWORK]")
        return text.encode('ascii', 'ignore').decode('ascii')

    # 1. PREPARE LOGO
    logo_path = None
    try:
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            with NamedTemporaryFile(delete=False, suffix=".png") as tmp_logo:
                tmp_logo.write(logo_data)
                logo_path = tmp_logo.name
    except: 
        pass

    # 2. DEFINE CUSTOM PDF CLASS
    class BrandedPDF(FPDF):
        def header(self):
            self.set_fill_color(0, 51, 102)
            self.rect(0, 0, 210, 25, 'F')
            if logo_path and os.path.exists(logo_path):
                self.image(logo_path, x=12, y=5, h=15)
            self.set_text_color(255, 255, 255)
            self.set_font("Arial", 'B', 16)
            self.set_xy(70, 5)
            self.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
            self.set_font("Arial", "I", 10)
            self.set_xy(70, 14)
            self.cell(130, 5, "PRODUCT QUALITY BIRTH CERTIFICATE", 0, 1, "L")
            self.set_font("Arial", "B", 8)
            self.set_xy(160, 14)
            self.cell(40, 5, f"JOB: {job_no}", 0, 0, "R")
            self.set_text_color(0, 0, 0)
            self.set_y(30)

        def footer(self):
            self.set_y(-15)
            self.set_font("Arial", 'I', 8)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, f"B&G ERP System - Page {self.page_no()}", 0, 0, 'C')

    pdf = BrandedPDF()
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.add_page()
    
    # 4. HEADER TABLE
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 8, " CLIENT / CUSTOMER DETAILS", border=1, fill=True)
    pdf.cell(95, 8, " PURCHASE ORDER DETAILS", border=1, fill=True, ln=True)
    pdf.set_font("Arial", '', 10)
    pdf.cell(95, 8, f" Name: {clean_text(header_data['client_name'])}", border=1)
    pdf.cell(95, 8, f" PO No: {clean_text(header_data['po_no'])}", border=1, ln=True)
    pdf.cell(95, 8, f" Job No: {job_no}", border=1)
    pdf.cell(95, 8, f" PO Date: {clean_text(header_data['po_date'])}", border=1, ln=True)
    pdf.ln(10)

    # 5. MANUFACTURING LOG WITH GRID
    if not photo_data.empty:
        photo_data = photo_data.dropna(subset=['quality_updated_at']).sort_values('quality_updated_at')
        
        for idx, row in photo_data.iterrows():
            if pdf.get_y() > 200: pdf.add_page()
            date_str = pd.to_datetime(row['quality_updated_at']).strftime('%d-%m-%Y')
            
            pdf.set_font("Arial", 'B', 10)
            pdf.set_fill_color(230, 240, 255)
            pdf.cell(190, 8, f" [{date_str}] - {clean_text(row['gate_name'])}", border="TLR", ln=True, fill=True)
            
            pdf.set_font("Arial", '', 9)
            details = f" Inspector: {clean_text(row['quality_by'])} | Status: {clean_text(row['quality_status'])}\n Remarks: {clean_text(row['quality_notes'])}"
            pdf.multi_cell(190, 6, details, border="LR")
            
            urls = row.get('quality_photo_url', [])
            if isinstance(urls, list) and len(urls) > 0:
                img_w, img_h = 44, 55 
                if pdf.get_y() + img_h > 260:
                    pdf.cell(190, 1, "", border="B", ln=True)
                    pdf.add_page()

                y_img_start = pdf.get_y()
                pdf.cell(190, img_h + 4, "", border="LR", ln=True) 

                for i, url in enumerate(urls[:4]):
                    try:
                        resp = requests.get(url, timeout=10)
                        if resp.status_code == 200:
                            with NamedTemporaryFile(delete=False, suffix=f"_{i}.jpg") as tmp:
                                tmp.write(resp.content)
                                tmp_name = tmp.name
                            pdf.image(tmp_name, x=12 + (i * 46), y=y_img_start + 2, w=img_w, h=img_h)
                            os.unlink(tmp_name)
                    except: 
                        continue
                pdf.set_y(y_img_start + img_h + 4)
            
            pdf.cell(190, 1, "", border="BLR", ln=True)
            pdf.ln(5)

    # --- CRITICAL FIX: ENSURE THIS RETURN IS AT THE BASE LEVEL OF THE FUNCTION ---
    if logo_path and os.path.exists(logo_path): 
        try: os.unlink(logo_path)
        except: pass
        
    return pdf.output(dest='S').encode('latin-1')
# --- 3. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_quality_context():
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    anchor_res = conn.table("anchor_projects").select("job_no, client_name, po_no, po_date").execute()
    df_a_raw = pd.DataFrame(anchor_res.data or [])
    
    if not df_a_raw.empty:
        df_a_cleaned = df_a_raw[df_a_raw['job_no'].notna() & (df_a_raw['job_no'].astype(str) != "")]
        df_a_cleaned = df_a_cleaned.drop_duplicates(subset=['job_no'])
    else:
        df_a_cleaned = pd.DataFrame()

    try:
        staff_res = conn.table("master_staff").select("name").execute()
        staff_list = sorted([str(s['name']) for s in staff_res.data]) if staff_res.data else ["Internal QC"]
    except:
        staff_list = ["Internal QC"]
        
    return pd.DataFrame(plan_res.data or []), df_a_cleaned, staff_list

# Initialize Data
df_plan, df_anchor, authorized_inspectors = get_quality_context()

# --- 4. UI ---
st.title("🔍 Quality Assurance & Inspection Portal")
main_tabs = st.tabs(["🚪 Process Gate (Evidence)", "📋 Technical Checklist (Reports)", "📜 QA Plan (QAP)", "📉 Material Flow Chart"])

# --- TAB 1: PROCESS GATE ---
with main_tabs[0]:
    if not df_plan.empty:
        st.subheader("🗓️ Inspection Timeline Filter")
        # (Timeline filter logic here)

        unique_jobs = sorted(df_plan['job_no'].dropna().astype(str).unique().tolist())
        sel_job = st.selectbox("🏗️ Select Job Number", ["-- Select --"] + unique_jobs, key="pg_job_sel")

        if sel_job != "-- Select --":
            match = df_anchor[df_anchor['job_no'].astype(str) == str(sel_job)]
            
            if not match.empty:
                h_data = {
                    "client_name": match.iloc[0].get('client_name', 'N/A'),
                    "po_no": match.iloc[0].get('po_no', 'N/A'),
                    "po_date": str(match.iloc[0].get('po_date', 'N/A'))
                }
                
                p_data = df_plan[df_plan['job_no'].astype(str) == str(sel_job)]
                
                try:
                    pdf_bytes = create_birth_certificate(sel_job, h_data, {}, p_data)
                    st.download_button(label=f"📂 DOWNLOAD BIRTH CERTIFICATE: {sel_job}", data=pdf_bytes, file_name=f"Birth_Cert_{sel_job}.pdf", mime="application/pdf", width='stretch', type="primary")
                except Exception as e:
                    st.error(f"PDF Error: {e}")

# --- TAB 2: TECHNICAL CHECKLIST ---
with main_tabs[1]:
    st.subheader("📋 Quality Check List (Official Record)")
    
    if not df_anchor.empty:
        # 1. Clean Dropdown for Job Selection
        clean_tc_jobs = sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
        q_job_tech = st.selectbox("Select Job for Technical Report", ["-- Select --"] + clean_tc_jobs, key="tc_job_sel_final")

        if q_job_tech != "-- Select --":
            # 2. Fetch Project Context from Anchor
            tc_match = df_anchor[df_anchor['job_no'].astype(str) == str(q_job_tech)]
            
            if not tc_match.empty:
                proj = tc_match.iloc[0]
                
                # --- START THE FORM ---
                with st.form("quality_check_list_standard", clear_on_submit=True):
                    st.markdown("### 🏗️ Project Identification")
                    h1, h2, h3 = st.columns(3)
                    # Values pulled from Anchor table
                    c_name = h1.text_input("Client Name", value=proj.get('client_name', 'N/A'))
                    p_no = h2.text_input("PO Number", value=proj.get('po_no', 'N/A'))
                    p_date = h3.text_input("PO Date", value=str(proj.get('po_date', 'N/A')))
                    
                    st.divider()
                    
                    st.markdown("### 📏 Equipment Specifications")
                    t1, t2, t3 = st.columns(3)
                    item_n = t1.text_input("Item Name / Description")
                    drg_n = t2.text_input("Drawing Number")
                    qap_n = t3.text_input("QAP Reference No.")
                    
                    e_id = t1.text_input("Equipment ID No.")
                    qty_val = t2.text_input("Quantity")
                    ins_date = t3.date_input("Inspection Date", value=datetime.now(IST).date())

                    st.divider()
                    
                    st.markdown("### 🔍 Inspection Stages & Status")
                    st.caption("Record the verification status for each gate (e.g., 'Accepted', 'W')")
                    
                    s1, s2, s3, s4 = st.columns(4)
                    mat_s = s1.text_input("Material Certification")
                    fit_s = s2.text_input("Fit-up Exam")
                    vis_s = s3.text_input("Visual Exam")
                    pt_s = s4.text_input("PT (Welds)")
                    
                    hyd_s = s1.text_input("Hydro / Vacuum Test")
                    fin_s = s2.text_input("Final Inspection")
                    pun_s = s3.text_input("Punching Status")
                    ncr_s = s4.text_input("NCR Status (if any)")

                    st.divider()
                    
                    st.markdown("### ✍️ Final Authorization")
                    notes = st.text_area("Technical Notes / Deviations")
                    f1, f2 = st.columns(2)
                    # Pulls from master_staff list
                    insp_by = f1.selectbox("Quality Inspector", authorized_inspectors, key="qc_insp_select_tab2")
                    
                    if st.form_submit_button("🚀 Save Technical Report", use_container_width=True):
                        # Construct Payload matching your quality_check_list table
                        payload = {
                            "job_no": q_job_tech,
                            "client_name": c_name,
                            "po_no": p_no,
                            "po_date": p_date,
                            "item_name": item_n,
                            "drawing_no": drg_n,
                            "qap_no": qap_n,
                            "equipment_id_no": e_id,
                            "qty": qty_val,
                            "mat_cert_status": mat_s,
                            "fit_up_status": fit_s,
                            "visual_status": vis_s,
                            "pt_weld_status": pt_s,
                            "hydro_status": hyd_s,
                            "final_status": fin_s,
                            "punching_status": pun_s,
                            "ncr_status": ncr_s,
                            "technical_notes": notes,
                            "inspected_by": insp_by,
                            "inspection_date": str(ins_date)
                        }
                        
                        try:
                            conn.table("quality_check_list").insert(payload).execute()
                            st.success(f"✅ Technical Report for {q_job_tech} saved successfully!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Supabase Error: {e}")
            else:
                st.error("Project details missing in Anchor records.")
    else:
        st.warning("No projects found in Anchor Portal.")

# --- TAB 3: QAP DESIGNER ---
with main_tabs[2]:
    st.subheader("📜 Quality Assurance Plan (QAP) Designer")
    if not df_anchor.empty:
        clean_job_list = sorted(df_anchor['job_no'].astype(str).unique().tolist())
        sel_job_qap = st.selectbox("Select Project for QAP", ["-- Select --"] + clean_job_list, key="qap_job_ref")
        
        if sel_job_qap != "-- Select --":
            match_qap = df_anchor[df_anchor['job_no'].astype(str) == str(sel_job_qap)]
            if not match_qap.empty:
                project_details = match_qap.iloc[0]
                with st.container(border=True):
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"**Client:** {project_details.get('client_name', 'N/A')}")
                    c2.write(f"**PO No:** {project_details.get('po_no', 'N/A')}")
                    c3.write(f"**PO Date:** {project_details.get('po_date', 'N/A')}")
                
                with st.form("create_qap_form"):
                    st.write("### QAP Parameters")
                    f1, f2, f3 = st.columns(3)
                    qap_num = f1.text_input("QAP Document No.")
                    equip_name = f2.text_input("Equipment/Component Name")
                    prepared_by = f3.selectbox("Prepared By", authorized_inspectors) 
                    st.divider()
                    st.write("### Inspection Grid")
                    df_init = pd.DataFrame([{"Component": "", "Activity": "", "Check_Type": "Visual", "Quantum": "100%", "Acceptance": "Approved Drawing", "B&G": "W", "Client": "R"}])
                    st.data_editor(df_init, num_rows="dynamic", use_container_width=True, key="qap_editor")
                    if st.form_submit_button("💾 Save QAP Template"):
                        st.success("QAP Template Saved!")

# --- 5. SUMMARY VIEW ---
st.divider()
st.subheader("📋 Recent Quality Clearances")
if not df_plan.empty:
    st.dataframe(df_plan[['job_no', 'gate_name', 'quality_status', 'quality_by']].dropna(subset=['quality_status']), use_container_width=True, hide_index=True)

# --- TAB 3: MATERIAL FLOW CHART (Traceability Record) ---
with main_tabs[3]:
    st.subheader("📉 Material Flow Chart & Traceability Record")
    
    if not df_anchor.empty:
        # 1. CLEAN DROPDOWN (Using your Master logic)
        clean_mfc_jobs = sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
        sel_job_mfc = st.selectbox("Select Job for Flow Chart", ["-- Select --"] + clean_mfc_jobs, key="mfc_job_sel")

        if sel_job_mfc != "-- Select --":
            # 2. AUTO-FETCH FROM ANCHOR MASTER
            mfc_match = df_anchor[df_anchor['job_no'].astype(str) == str(sel_job_mfc)]
            
            if not mfc_match.empty:
                proj = mfc_match.iloc[0]
                
                # Visual Header matching the paper form layout
                with st.container(border=True):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Customer:** {proj.get('client_name', 'N/A')}")
                    c1.write(f"**PO No & Date:** {proj.get('po_no')} | {proj.get('po_date')}")
                    
                    # Manual inputs for specific equipment details
                    item_desc = c2.text_input("Item Name / Description", placeholder="e.g. 30KL SS Tank")
                    total_qty = c2.text_input("Total Quantity", placeholder="e.g. 1 No.")

                st.divider()

                # 3. TRACEABILITY GRID (st.data_editor for friendly UI)
                st.markdown("### 🔍 Material Identification Matrix")
                st.caption("Sl. No | Item Description | Size | Matl. Specn. | Heat No. / Plate No. | MTC No.")
                
                # Template matching the columns in your paper form
                mfc_template = [
                    {"Sl": 1, "Description": "Shell Plate", "Size": "", "Matl_Spec": "", "Heat_Plate_No": "", "MTC_No": ""},
                    {"Sl": 2, "Description": "Dish End 1", "Size": "", "Matl_Spec": "", "Heat_Plate_No": "", "MTC_No": ""},
                    {"Sl": 3, "Description": "Dish End 2", "Size": "", "Matl_Spec": "", "Heat_Plate_No": "", "MTC_No": ""},
                    {"Sl": 4, "Description": "Nozzle Pipe", "Size": "", "Matl_Spec": "", "Heat_Plate_No": "", "MTC_No": ""},
                    {"Sl": 5, "Description": "Flange", "Size": "", "Matl_Spec": "", "Heat_Plate_No": "", "MTC_No": ""},
                ]

                # The dynamic grid editor
                trace_grid = st.data_editor(
                    pd.DataFrame(mfc_template),
                    num_rows="dynamic", # Allows inspector to add more rows for nozzles/plates
                    use_container_width=True,
                    key="mfc_grid_editor",
                    hide_index=True
                )

                # 4. SUBMISSION FORM
                with st.form("mfc_submit_form", clear_on_submit=True):
                    st.markdown("#### ✍️ Verification")
                    f1, f2 = st.columns(2)
                    # Pulls from authorized_inspectors Master
                    verifier = f1.selectbox("Verified By (QC Inspector)", authorized_inspectors, key="mfc_verifier")
                    mfc_remarks = st.text_area("Observations / Traceability Notes")

                    if st.form_submit_button("🚀 Save Traceability Record", use_container_width=True):
                        # Construct Payload
                        payload = {
                            "job_no": sel_job_mfc,
                            "item_name": item_desc,
                            "qty": total_qty,
                            "traceability_data": trace_grid.to_dict('records'), # Stored as JSONB
                            "verified_by": verifier,
                            "remarks": mfc_remarks,
                            "created_at": datetime.now(IST).isoformat()
                        }
                        
                        try:
                            conn.table("material_flow_charts").insert(payload).execute()
                            st.success(f"✅ Material Flow Chart for {sel_job_mfc} recorded!")
                            st.balloons()
                        except Exception as e:
                            st.error(f"Failed to save: {e}")
            else:
                st.error("Project details not found in Anchor records.")
    else:
        st.warning("No Master Data available in Anchor Portal.")
