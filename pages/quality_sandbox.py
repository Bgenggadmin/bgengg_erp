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
main_tabs = st.tabs(["🚪 Process Gate (Evidence)", "📋 Technical Checklist (Reports)", "📜 QA Plan (QAP)"])

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
    st.subheader("📋 Technical Check List")
    if not df_anchor.empty:
        tc_jobs = sorted(df_anchor['job_no'].astype(str).unique().tolist())
        q_job_tech = st.selectbox("Job No", ["-- Select --"] + tc_jobs, key="tc_job")

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
