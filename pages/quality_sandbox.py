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

def generate_technical_pdf(job_no, report_title, master_data, grid_data, remarks, inspector):
    pdf = FPDF()
    pdf.add_page()
    
    # Header Branding
    pdf.set_fill_color(0, 51, 102)
    pdf.rect(0, 0, 210, 30, 'F')
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "B&G ENGINEERING INDUSTRIES", ln=True, align='C')
    pdf.set_font("Arial", "I", 10)
    pdf.cell(0, 10, report_title, ln=True, align='C')
    pdf.ln(10)
    
    # Project Info
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 8, f" Client: {master_data.get('client_name', 'N/A')}", border=1, fill=True)
    pdf.cell(95, 8, f" Job No: {job_no}", border=1, fill=True, ln=True)
    pdf.cell(95, 8, f" PO No: {master_data.get('po_no', 'N/A')}", border=1)
    pdf.cell(95, 8, f" Date: {datetime.now().strftime('%d-%m-%Y')}", border=1, ln=True)
    pdf.ln(5)

    # Data Table Headers
    pdf.set_fill_color(230, 240, 255)
    pdf.cell(15, 8, "Sl", 1, 0, 'C', fill=True)
    pdf.cell(85, 8, "Description", 1, 0, 'C', fill=True)
    pdf.cell(45, 8, "Design", 1, 0, 'C', fill=True)
    pdf.cell(45, 8, "Actual", 1, 1, 'C', fill=True)
    
    pdf.set_font("Arial", '', 9)
    sl = 1
    for row in grid_data:
        # THE "NA" LOGIC: Skip row if Actual is blank or NA
        act = str(row.get('Actual', '')).strip().upper()
        if not act or act in ["NA", "N/A", "NONE", "-", "NAN"]:
            continue
            
        pdf.cell(15, 8, str(sl), 1, 0, 'C')
        pdf.cell(85, 8, str(row.get('Description', 'N/A')), 1, 0, 'L')
        pdf.cell(45, 8, str(row.get('Design', 'N/A')), 1, 0, 'C')
        pdf.cell(45, 8, str(act), 1, 1, 'C')
        sl += 1

    pdf.ln(10)
    pdf.multi_cell(0, 6, f"Remarks: {remarks}")
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(95, 10, f"QC Inspector: {inspector}", 0, 0, 'L')
    pdf.cell(95, 10, "Authorized Signatory", 0, 1, 'R')
    return pdf.output(dest='S').encode('latin-1', 'ignore')
# --- 3. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_quality_context():
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    # ADDED 'equipment_type' HERE
    anchor_res = conn.table("anchor_projects").select("job_no, client_name, po_no, po_date, equipment_type").execute()
    df_a_raw = pd.DataFrame(anchor_res.data or [])
    
    if not df_a_raw.empty:
        df_a_cleaned = df_a_raw[df_a_raw['job_no'].notna() & (df_a_raw['job_no'].astype(str) != "")]
        # Safe String Cleaning
        df_a_cleaned['job_no'] = df_a_cleaned['job_no'].fillna('').astype(str).str.strip().str.upper()
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
main_tabs = st.tabs([
    "🚪 Process Gate (Evidence)", 
    "📋 Technical Checklist (Reports)", 
    "📜 QA Plan (QAP)", 
    "📉 Material Flow Chart", 
    "🔧 Nozzle Flow Chart",
    "📐 Dimensional Report",
    "💧 Hydro Test Report",
    "🏁 Final Inspection (FIR)",
    "🛡️ Guarantee Certificate",
    "⭐ Customer Feedback",
    "📂 MTC & Document Vault" # Index 10
])

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
            
            # Inside your Quality Portal Tab 2
            if not tc_match.empty:
                proj = tc_match.iloc[0]
                e_type = proj.get('equipment_type', 'Storage Tank') # Get the type
    
                with st.form("quality_check_list_standard"):
                    # standard fields...
        
                    # DYNAMIC SECTION: Only show if it's a Reactor
                    if e_type == "Reactor":
                        st.markdown("### ⚛️ Reactor Specifics")
                        r1, r2 = st.columns(2)
                        agitator_stat = r1.text_input("Agitator Run Test", value="NA")
                        jacket_hydro = r2.text_input("Jacket Hydro Test", value="NA")
        
                    # DYNAMIC SECTION: Only show if it's a Storage Tank
                    if e_type == "Storage Tank":
                        st.markdown("### 🛢️ Tank Specifics")
                        t1, t2 = st.columns(2)
                        roof_fitup = t1.text_input("Roof Structure Fit-up", value="NA")
                        curb_angle = t2.text_input("Curb Angle Inspection", value="NA")
                    
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

# --- TAB 5: NOZZLE FLOW CHART (Component Specific Traceability) ---
with main_tabs[4]:
    st.subheader("🔧 Nozzle Flow Chart & Traceability")
    
    if not df_anchor.empty:
        # 1. Selection using Master Job List
        nfc_jobs = sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
        sel_job_nfc = st.selectbox("Select Job for Nozzle Chart", ["-- Select --"] + nfc_jobs, key="nfc_job_sel")

        if sel_job_nfc != "-- Select --":
            nfc_match = df_anchor[df_anchor['job_no'].astype(str) == str(sel_job_nfc)]
            
            if not nfc_match.empty:
                proj = nfc_match.iloc[0]
                
                # Visual Header using Anchor Master Data
                with st.container(border=True):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Client:** {proj.get('client_name', 'N/A')}")
                    c1.write(f"**PO Details:** {proj.get('po_no')} | {proj.get('po_date')}")
                    
                    equip_name = c2.text_input("Equipment Name", placeholder="e.g. Pressure Vessel")
                    n_mark = c2.text_input("Nozzle Mark / ID", placeholder="e.g. N1 / N2")

                st.divider()

                # 2. NOZZLE GRID (Based on Image e4954d.jpg)
                st.markdown(f"### 🛠️ Traceability Matrix for Nozzle: {n_mark}")
                st.caption("Map individual nozzle sub-components to Material Specs and Heat Numbers")
                
                # Template based on standard nozzle assembly
                nfc_template = [
                    {"Component": "Nozzle Neck (Pipe/Shell)", "Size/Sch": "", "Matl_Spec": "", "Heat_Plate_No": "", "MTC_No": ""},
                    {"Component": "Nozzle Flange", "Size/Rating": "", "Matl_Spec": "", "Heat_Plate_No": "", "MTC_No": ""},
                    {"Component": "Reinforcement Pad", "Thk": "", "Matl_Spec": "", "Heat_Plate_No": "", "MTC_No": ""},
                    {"Component": "Internal Projection", "Size": "", "Matl_Spec": "", "Heat_Plate_No": "", "MTC_No": ""},
                ]

                nfc_grid = st.data_editor(
                    pd.DataFrame(nfc_template),
                    num_rows="dynamic",
                    use_container_width=True,
                    key="nfc_grid_editor",
                    hide_index=True
                )

                # 3. VERIFICATION & SUBMIT
                with st.form("nfc_submit_form", clear_on_submit=True):
                    f1, f2 = st.columns(2)
                    # Staff Master Dropdown
                    nfc_verifier = f1.selectbox("Inspected By", authorized_inspectors, key="nfc_verifier_select")
                    nfc_remarks = st.text_area("Orientation / Fit-up Remarks")

                    if st.form_submit_button("🚀 Save Nozzle Flow Chart"):
                        payload = {
                            "job_no": sel_job_nfc,
                            "equipment_name": equip_name,
                            "nozzle_mark": n_mark,
                            "traceability_data": nfc_grid.to_dict('records'),
                            "verified_by": nfc_verifier,
                            "remarks": nfc_remarks,
                            "created_at": datetime.now(IST).isoformat()
                        }
                        
                        try:
                            conn.table("nozzle_flow_charts").insert(payload).execute()
                            st.success(f"✅ Nozzle Flow Chart for {n_mark} (Job {sel_job_nfc}) saved!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Database Error: {e}")
            else:
                st.error("Job details not found in Anchor records.")
    else:
        st.warning("Anchor Portal Master Data is empty.")

# --- TAB 6: DIMENSIONAL INSPECTION REPORT (FIXED PDF LOGIC) ---
with main_tabs[5]:
    st.subheader("📐 Dimensional Inspection Report")
    
    if not df_anchor.empty:
        dim_jobs = sorted(df_anchor['job_no'].dropna().unique().tolist())
        sel_job_dim = st.selectbox("Select Job for Dimensional Report", ["-- Select --"] + dim_jobs, key="dim_job_sel")

        if sel_job_dim != "-- Select --":
            dim_match = df_anchor[df_anchor['job_no'] == sel_job_dim]
            
            if not dim_match.empty:
                proj = dim_match.iloc[0]
                e_type = proj.get('equipment_type', 'Storage Tank')
                
                with st.container(border=True):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Customer:** {proj.get('client_name')}")
                    c1.info(f"**Category:** {e_type}")
                    equip_dim = c2.text_input("Equipment Name", placeholder="e.g. 50KL Storage Tank")
                    stage_dim = c2.selectbox("Inspection Stage", ["Final Inspection", "Internal Fit-up", "Jacket Prep"])

                st.divider()

                # --- Template Logic ---
                base_template = [
                    {"Sl": 1, "Description": "Overall Length / Height", "Design": "", "Actual": ""},
                    {"Sl": 2, "Description": "Inside Diameter (ID)", "Design": "", "Actual": ""},
                    {"Sl": 3, "Description": "Shell Thickness", "Design": "", "Actual": ""},
                ]

                if e_type == "Reactor":
                    base_template.extend([
                        {"Sl": 4, "Description": "Jacket ID", "Design": "", "Actual": ""},
                        {"Sl": 5, "Description": "Agitator Shaft Runout", "Design": "0.5mm", "Actual": ""},
                    ])
                elif e_type == "Storage Tank":
                    base_template.extend([
                        {"Sl": 4, "Description": "Curb Angle Level", "Design": "Level", "Actual": ""},
                        {"Sl": 5, "Description": "Roof Slope", "Design": "1:100", "Actual": ""},
                    ])

                st.markdown(f"### 📏 Measurement Log for {e_type}")
                dim_grid = st.data_editor(pd.DataFrame(base_template), num_rows="dynamic", use_container_width=True, key="dim_editor", hide_index=True)

                # --- FORM START ---
                with st.form("dim_submit_form"):
                    f1, f2 = st.columns(2)
                    dim_inspector = f1.selectbox("QC Inspector", authorized_inspectors, key="dim_insp_final")
                    dim_remarks = st.text_area("Notes (Enter 'NA' if none)")

                    # Submit button is INSIDE the form
                    submitted = st.form_submit_button("🚀 Save Technical Data", use_container_width=True)
                    
                    if submitted:
                        payload = {
                            "job_no": sel_job_dim,
                            "equipment_name": equip_dim,
                            "dim_grid_data": dim_grid.to_dict('records'),
                            "inspected_by": dim_inspector,
                            "remarks": dim_remarks,
                            "created_at": datetime.now(IST).isoformat()
                        }
                        try:
                            conn.table("dimensional_reports").insert(payload).execute()
                            # Store PDF bytes in session state so we can show the button OUTSIDE
                            st.session_state["last_pdf"] = generate_technical_pdf(sel_job_dim, f"DIMENSIONAL REPORT - {e_type}", proj, dim_grid.to_dict('records'), dim_remarks, dim_inspector)
                            st.session_state["pdf_ready"] = True
                            st.success("✅ Data Saved to Supabase!")
                        except Exception as e:
                            st.error(f"Error: {e}")
                # --- FORM END ---

                # --- DOWNLOAD BUTTON (Must be OUTSIDE the form) ---
                if st.session_state.get("pdf_ready"):
                    st.download_button(
                        label="📥 Download Clean PDF Report", 
                        data=st.session_state["last_pdf"], 
                        file_name=f"Report_{sel_job_dim}.pdf", 
                        mime="application/pdf", 
                        type="primary", 
                        use_container_width=True
                    )

# --- TAB 7: HYDRO TEST REPORT ---
with main_tabs[6]:
    st.subheader("💧 Hydrostatic / Pneumatic Test Report")
    
    if not df_anchor.empty:
        # 1. Clean Dropdown from Master
        hydro_jobs = sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
        sel_job_hydro = st.selectbox("Select Job for Hydro Test", ["-- Select --"] + hydro_jobs, key="hydro_job_sel")

        if sel_job_hydro != "-- Select --":
            hydro_match = df_anchor[df_anchor['job_no'].astype(str) == str(sel_job_hydro)]
            
            if not hydro_match.empty:
                proj = hydro_match.iloc[0]
                
                # Visual Header aligned with image_e4fb44.jpg
                with st.container(border=True):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Customer:** {proj.get('client_name', 'N/A')}")
                    c1.write(f"**PO Reference:** {proj.get('po_no')} | {proj.get('po_date')}")
                    
                    e_name_hydro = c2.text_input("Equipment Description", placeholder="e.g. 500L Receiver Tank")
                    drg_ref_hydro = c2.text_input("Drawing Ref.", placeholder="BGE-HT-01")

                st.divider()

                # 2. TEST PARAMETERS FORM
                with st.form("hydro_test_form", clear_on_submit=True):
                    st.markdown("### ⏲️ Test Parameters & Observations")
                    f1, f2, f3 = st.columns(3)
                    
                    t_pressure = f1.text_input("Test Pressure (Kg/cm²)", placeholder="e.g. 15.0")
                    d_pressure = f2.text_input("Design Pressure (Kg/cm²)", placeholder="e.g. 10.0")
                    h_time = f3.text_input("Holding Duration", placeholder="e.g. 45 Mins")
                    
                    medium = f1.selectbox("Testing Medium", ["Potable Water", "Hydraulic Oil", "Compressed Air", "Nitrogen"])
                    g_nos = f2.text_input("Pressure Gauge ID(s)", placeholder="e.g. BG/QC/PG-01")
                    temp = f3.text_input("Medium Temp (°C)", value="Ambient")

                    st.markdown("### ✍️ Final Inspection & Witnessing")
                    w1, w2 = st.columns(2)
                    
                    # Pulls from master_staff (authorized_inspectors)
                    insp_hydro = w1.selectbox("Inspected By (B&G QC)", authorized_inspectors, key="hydro_insp")
                    wit_hydro = w2.text_input("Witnessed By (Client/TPI)", placeholder="Third Party Name")
                    
                    h_remarks = st.text_area("Observations (Leakage, Pressure Drop, etc.)")

                    if st.form_submit_button("🚀 Finalize & Save Hydro Report", use_container_width=True):
                        payload = {
                            "job_no": sel_job_hydro,
                            "equipment_name": e_name_hydro,
                            "test_pressure": t_pressure,
                            "holding_time": h_time,
                            "test_medium": medium,
                            "gauge_nos": g_nos,
                            "inspection_notes": h_remarks,
                            "inspected_by": insp_hydro,
                            "witness_name": wit_hydro,
                            "created_at": datetime.now(IST).isoformat()
                        }
                        
                        try:
                            conn.table("hydro_test_reports").insert(payload).execute()
                            st.success(f"✅ Hydro Test Report for {sel_job_hydro} submitted successfully!")
                            st.balloons()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to save to Supabase: {e}")
            else:
                st.error("Could not link to Anchor Master records.")
    else:
        st.warning("Project data not loaded from Anchor.")

# --- TAB 8: FINAL INSPECTION REPORT (FIR) ---
with main_tabs[7]:
    st.subheader("🏁 Final Inspection Report & Release Note")
    
    if not df_anchor.empty:
        # 1. Selection using Job Master
        fir_jobs = sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
        sel_job_fir = st.selectbox("Select Job for FIR", ["-- Select --"] + fir_jobs, key="fir_job_sel")

        if sel_job_fir != "-- Select --":
            fir_match = df_anchor[df_anchor['job_no'].astype(str) == str(sel_job_fir)]
            
            if not fir_match.empty:
                proj = fir_match.iloc[0]
                
                # Visual Header aligned with image_e50dcb.jpg
                with st.container(border=True):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Customer:** {proj.get('client_name', 'N/A')}")
                    c1.write(f"**PO Ref:** {proj.get('po_no')} | Date: {proj.get('po_date')}")
                    
                    fir_item = c2.text_input("Item Name", placeholder="e.g. Storage Tank")
                    fir_tag = c2.text_input("Equipment Tag No.", placeholder="e.g. V-101")

                st.divider()

                # 2. QUANTITY & STATUS FORM
                with st.form("fir_submit_form", clear_on_submit=True):
                    st.markdown("### 📊 Quantity & Clearance Summary")
                    q1, q2, q3 = st.columns(3)
                    ord_qty = q1.text_input("Ordered Qty")
                    off_qty = q2.text_input("Offered for Insp.")
                    acc_qty = q3.text_input("Accepted Qty")
                    
                    st.markdown("### 🔍 Final Verdict")
                    v1, v2 = st.columns(2)
                    fir_status = v1.segmented_control("Inspection Result", ["✅ Accepted", "❌ Rejected", "⚠️ Rework Required"], default="✅ Accepted")
                    
                    # Staff Master Dropdown
                    fir_inspector = v2.selectbox("QC Inspector", authorized_inspectors, key="fir_qc_insp")
                    fir_witness = v2.text_input("Witnessed By (Client/TPI Name)")
                    
                    fir_remarks = st.text_area("Final Observations / Release Notes")

                    if st.form_submit_button("🚀 Finalize & Save FIR", use_container_width=True):
                        payload = {
                            "job_no": sel_job_fir,
                            "equipment_name": fir_item,
                            "tag_no": fir_tag,
                            "ordered_qty": ord_qty,
                            "offered_qty": off_qty,
                            "accepted_qty": acc_qty,
                            "inspection_status": fir_status,
                            "inspected_by": fir_inspector,
                            "witnessed_by": fir_witness,
                            "remarks": fir_remarks,
                            "created_at": datetime.now(IST).isoformat()
                        }
                        
                        try:
                            conn.table("final_inspection_reports").insert(payload).execute()
                            st.success(f"✅ Final Inspection for {sel_job_fir} saved successfully!")
                            st.balloons()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to save record: {e}")
            else:
                st.error("Project details missing in Anchor portal.")
    else:
        st.warning("No Master Data available.")

# --- TAB 9: GUARANTEE CERTIFICATE ---
with main_tabs[8]:
    st.subheader("🛡️ Product Guarantee Certificate")
    
    if not df_anchor.empty:
        # 1. Selection using Job Master
        gc_jobs = sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
        sel_job_gc = st.selectbox("Select Job Number", ["-- Select --"] + gc_jobs, key="gc_job_sel")

        if sel_job_gc != "-- Select --":
            gc_match = df_anchor[df_anchor['job_no'].astype(str) == str(sel_job_gc)]
            
            if not gc_match.empty:
                proj = gc_match.iloc[0]
                
                # Visual Header aligned with image_e56f20.jpg
                with st.container(border=True):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Customer:** {proj.get('client_name', 'N/A')}")
                    c1.write(f"**Purchase Order:** {proj.get('po_no')}")
                    
                    # Additional Details for Certificate
                    equip_name_gc = c2.text_input("Equipment Description", placeholder="e.g. Stainless Steel Reactor")
                    serial_no_gc = c2.text_input("Serial / Tag Number", placeholder="e.g. BGE/2026/101")

                st.divider()

                # 2. GUARANTEE TERMS FORM
                with st.form("guarantee_submit_form", clear_on_submit=True):
                    st.markdown("### 📜 Certificate Details")
                    
                    g_period = st.text_input(
                        "Guarantee Period", 
                        value="12 months from date of commissioning or 18 months from date of supply, whichever is earlier."
                    )
                    
                    f1, f2 = st.columns(2)
                    inv_ref = f1.text_input("Invoice / Dispatch Ref No.")
                    cert_date = f2.date_input("Date of Issue", value=datetime.now(IST).date())

                    st.info("💡 This certificate guarantees that the materials and workmanship are free from defects as per B&G Standard Quality norms.")

                    # Staff Master Dropdown
                    certifier = f1.selectbox("Authorized Signatory", authorized_inspectors, key="gc_auth_sign")
                    gc_remarks = st.text_area("Additional Terms / Remarks")

                    if st.form_submit_button("🚀 Generate & Save Guarantee Certificate", use_container_width=True):
                        payload = {
                            "job_no": sel_job_gc,
                            "equipment_name": equip_name_gc,
                            "serial_no": serial_no_gc,
                            "guarantee_period": g_period,
                            "invoice_ref": inv_ref,
                            "certified_by": certifier,
                            "remarks": gc_remarks,
                            "created_at": datetime.now(IST).isoformat()
                        }
                        
                        try:
                            conn.table("guarantee_certificates").insert(payload).execute()
                            st.success(f"✅ Guarantee Certificate for {sel_job_gc} recorded successfully!")
                            st.balloons()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error saving to database: {e}")
            else:
                st.error("Project details missing in Anchor portal.")
    else:
        st.warning("No Master Data available.")

# --- TAB 10: CUSTOMER FEEDBACK FORM ---
with main_tabs[9]:
    st.subheader("⭐ Customer Satisfaction & Feedback")
    
    if not df_anchor.empty:
        # 1. Selection using Job Master
        fb_jobs = sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
        sel_job_fb = st.selectbox("Select Job for Feedback", ["-- Select --"] + fb_jobs, key="fb_job_sel")

        if sel_job_fb != "-- Select --":
            fb_match = df_anchor[df_anchor['job_no'].astype(str) == str(sel_job_fb)]
            
            if not fb_match.empty:
                proj = fb_match.iloc[0]
                
                # Header pre-filled from Master Data
                with st.container(border=True):
                    f_col1, f_col2 = st.columns(2)
                    f_col1.write(f"**Customer:** {proj.get('client_name', 'N/A')}")
                    f_col1.write(f"**Project Ref:** {sel_job_fb}")
                    
                    c_person = f_col2.text_input("Contact Person Name")
                    c_desig = f_col2.text_input("Designation")

                st.divider()

                # 2. FEEDBACK QUESTIONNAIRE
                with st.form("customer_feedback_form", clear_on_submit=True):
                    st.markdown("##### Please rate our performance (5 = Excellent, 1 = Poor)")
                    
                    # Rating Scale Logic
                    r_col1, r_col2 = st.columns(2)
                    
                    q_val = r_col1.slider("Quality of Product/Workmanship", 1, 5, 5)
                    d_val = r_col1.slider("Adherence to Delivery Schedule", 1, 5, 5)
                    r_val = r_col1.slider("Promptness of Response", 1, 5, 5)
                    
                    t_val = r_col2.slider("Technical Support & Competence", 1, 5, 5)
                    doc_val = r_col2.slider("Quality of Documentation/MTCs", 1, 5, 5)
                    recommend = r_col2.radio("Would you recommend B&G to others?", ["Yes", "No"], horizontal=True)

                    st.divider()
                    
                    st.markdown("##### Additional Comments")
                    user_suggestions = st.text_area("How can we improve our services further?")
                    
                    # Disclaimer
                    st.caption("Your feedback is strictly used for ISO Quality Management and internal improvement.")

                    if st.form_submit_button("🚀 Submit Feedback", use_container_width=True):
                        payload = {
                            "job_no": sel_job_fb,
                            "customer_name": proj.get('client_name'),
                            "contact_person": f"{c_person} ({c_desig})",
                            "rating_quality": q_val,
                            "rating_delivery": d_val,
                            "rating_response": r_val,
                            "rating_technical_support": t_val,
                            "rating_documentation": doc_val,
                            "suggestions": user_suggestions,
                            "recommend_bg": recommend,
                            "created_at": datetime.now(IST).isoformat()
                        }
                        
                        try:
                            conn.table("customer_feedback").insert(payload).execute()
                            st.success("✅ Thank you for your feedback! It has been recorded for review.")
                            st.balloons()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error saving feedback: {e}")
            else:
                st.error("Customer details missing in project records.")
    else:
        st.warning("Project master data is not available.")

# --- TAB 11: MTC & DOCUMENT VAULT ---
with main_tabs[10]:
    st.subheader("📂 MTC & Document Upload Vault")
    
    if not df_anchor.empty:
        # 1. Master Selection
        vault_jobs = sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist())
        sel_job_vault = st.selectbox("Select Project to Manage Documents", ["-- Select --"] + vault_jobs, key="vault_job_sel")

        if sel_job_vault != "-- Select --":
            match_vault = df_anchor[df_anchor['job_no'].astype(str) == str(sel_job_vault)]
            if not match_vault.empty:
                proj = match_vault.iloc[0]
                st.info(f"📂 Managing Vault for: **{proj.get('client_name')}**")

                # 2. UPLOAD SECTION
                with st.form("vault_upload_form", clear_on_submit=True):
                    up1, up2 = st.columns(2)
                    c_type = up1.selectbox("Document Type", ["Material Test Certificate (MTC)", "Guarantee Certificate", "NDT Report", "Drawing", "Invoice"])
                    up_files = up2.file_uploader("Upload Scanned PDF or Image", accept_multiple_files=True, type=['pdf', 'jpg', 'jpeg', 'png'])
                    u_notes = st.text_input("Brief Document Label (e.g. Shell Plate MTC)")
                    
                    if st.form_submit_button("🚀 Upload to Project Vault"):
                        if up_files:
                            for uploaded_file in up_files:
                                try:
                                    # File path logic
                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    file_path = f"{sel_job_vault}/{c_type.split()[0]}_{timestamp}_{uploaded_file.name}"
                                    
                                    # 1. Upload to Supabase Storage
                                    content = uploaded_file.getvalue()
                                    conn.client.storage.from_("project-certificates").upload(file_path, content)
                                    
                                    # 2. Get Public URL
                                    file_url = conn.client.storage.from_("project-certificates").get_public_url(file_path)
                                    
                                    # 3. Record in Database
                                    payload = {
                                        "job_no": sel_job_vault,
                                        "cert_type": c_type,
                                        "file_name": uploaded_file.name,
                                        "file_url": file_url,
                                        "uploaded_by": "QC Staff", # Can link to master_staff if needed
                                        "created_at": datetime.now(IST).isoformat()
                                    }
                                    conn.table("project_certificates").insert(payload).execute()
                                    st.success(f"Successfully uploaded: {uploaded_file.name}")
                                except Exception as e:
                                    st.error(f"Error uploading {uploaded_file.name}: {e}")
                        else:
                            st.warning("Please select files first.")

                st.divider()

                # 3. VIEW SECTION (Fetch existing docs)
                st.markdown("### 📑 Existing Project Documents")
                try:
                    docs_res = conn.table("project_certificates").select("*").eq("job_no", sel_job_vault).execute()
                    if docs_res.data:
                        df_docs = pd.DataFrame(docs_res.data)
                        for _, doc in df_docs.iterrows():
                            with st.container(border=True):
                                d1, d2, d3 = st.columns([2, 2, 1])
                                d1.write(f"**Type:** {doc['cert_type']}")
                                d2.write(f"**Name:** {doc['file_name']}")
                                d3.link_button("👁️ View Doc", doc['file_url'])
                    else:
                        st.info("No documents uploaded for this project yet.")
                except:
                    st.info("Vault is currently empty.")
    else:
        st.warning("No Master Data available.")
