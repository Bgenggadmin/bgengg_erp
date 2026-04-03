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
    def clean_text(text):
        if not text: return "N/A"
        text = str(text).replace("✅", "[PASS]").replace("❌", "[REJECT]").replace("⚠️", "[REWORK]")
        return text.encode('ascii', 'ignore').decode('ascii')

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # --- BRANDED HEADER ---
    pdf.set_font("Arial", 'B', 16)
    pdf.set_text_color(0, 51, 102) 
    pdf.cell(190, 10, "B&G ENGINEERING INDUSTRIES", ln=True, align='C')
    pdf.set_font("Arial", 'B', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(190, 5, "CHEMICAL PROCESS EQUIPMENT SPECIALISTS", ln=True, align='C')
    pdf.set_draw_color(0, 51, 102)
    pdf.line(10, 27, 200, 27)
    pdf.ln(10)

    # --- TITLE ---
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(190, 10, f"PRODUCT BIRTH CERTIFICATE: {job_no}", ln=True, align='L')
    pdf.ln(2)

    # --- PRODUCT IDENTIFICATION TABLE ---
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(95, 8, " CLIENT / CUSTOMER DETAILS", border=1, fill=True)
    pdf.cell(95, 8, " PURCHASE ORDER DETAILS", border=1, fill=True, ln=True)
    
    pdf.set_font("Arial", '', 10)
    pdf.cell(95, 8, f" Name: {clean_text(header_data['client_name'])}", border=1)
    pdf.cell(95, 8, f" PO No: {clean_text(header_data['po_no'])}", border=1, ln=True)
    pdf.cell(95, 8, f" Drawing No: {clean_text(header_data.get('drawing_no', 'N/A'))}", border=1)
    pdf.cell(95, 8, f" PO Date: {clean_text(header_data['po_date'])}", border=1, ln=True)
    pdf.ln(10)

    # --- MANUFACTURING LOG & VISUAL EVIDENCE ---
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(190, 8, "MANUFACTURING LOG & VISUAL EVIDENCE", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    if not photo_data.empty:
        photo_data = photo_data.dropna(subset=['quality_updated_at']).sort_values('quality_updated_at')
        
        for idx, row in photo_data.iterrows():
            date_str = pd.to_datetime(row['quality_updated_at']).strftime('%d-%m-%Y')
            pdf.set_font("Arial", 'B', 10)
            pdf.set_fill_color(230, 240, 255)
            pdf.cell(190, 8, f" [{date_str}] - {clean_text(row['gate_name'])}", border="TLR", ln=True, fill=True)
            
            pdf.set_font("Arial", '', 9)
            info_text = f" Inspector: {clean_text(row['quality_by'])} | Status: {clean_text(row['quality_status'])}\n Remarks: {clean_text(row['quality_notes'])}"
            pdf.multi_cell(190, 6, info_text, border="LR")
            
            urls = row.get('quality_photo_url', [])
            if isinstance(urls, list) and len(urls) > 0:
                y_current = pdf.get_y()
                img_w, img_h = 44, 55
                if y_current + img_h > 250:
                    pdf.add_page()
                    y_current = 20

                for i, url in enumerate(urls[:4]): 
                    try:
                        resp = requests.get(url, timeout=5)
                        if resp.status_code == 200:
                            with NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                                tmp.write(resp.content)
                                tmp_path = tmp.name
                            x_pos = 12 + (i * (img_w + 2))
                            pdf.image(tmp_path, x=x_pos, y=y_current + 2, w=img_w, h=img_h)
                    except: continue
                pdf.set_y(y_current + img_h + 5)
            
            pdf.cell(190, 1, "", border="BLR", ln=True)
            pdf.ln(4)
    else:
        pdf.cell(190, 10, "No visual records found.", ln=True)

    pdf.set_y(-20)
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(128, 128, 128)
    pdf.cell(190, 10, f"Digitally generated Birth Certificate - B&G ERP System. Page {pdf.page_no()}", align='C')

    return pdf.output(dest='S').encode('latin-1')

# --- 3. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_quality_context():
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    anchor_res = conn.table("anchor_projects").select("job_no, client_name, po_no, po_date").execute()
    try:
        staff_res = conn.table("master_staff").select("name").execute()
        staff_list = sorted([s['name'] for s in staff_res.data]) if staff_res.data else []
    except Exception as e:
        st.error(f"⚠️ Master Staff Error: {e}")
        staff_list = []
    return pd.DataFrame(plan_res.data or []), pd.DataFrame(anchor_res.data or []), staff_list

df_plan, df_anchor, authorized_inspectors = get_quality_context()

# --- 3. UI ---
st.title("🔍 Quality Assurance & Inspection Portal")
main_tabs = st.tabs(["🚪 Process Gate (Evidence)", "📋 Technical Checklist (Reports)"])

with main_tabs[0]:
    if not df_plan.empty:
        st.subheader("📸 Direct Gate Inspection & Marketing Presentation")
        c1, c2 = st.columns(2)
        unique_jobs = sorted(df_plan['job_no'].unique())
        sel_job = c1.selectbox("🏗️ Select Job Number", ["-- Select --"] + unique_jobs, key="pg_job_sel")

        if sel_job != "-- Select --":
            with st.container(border=True):
                st.subheader("💎 Presentation Mode")
                h_match = df_anchor[df_anchor['job_no'] == sel_job]
                h_data = {
                    "client_name": h_match.iloc[0].get('client_name', 'N/A') if not h_match.empty else "N/A",
                    "po_no": h_match.iloc[0].get('po_no', 'N/A') if not h_match.empty else "N/A",
                    "po_date": str(h_match.iloc[0].get('po_date', 'N/A')) if not h_match.empty else "N/A",
                    "drawing_no": "Verified on Shop Floor"
                }
                p_data = df_plan[df_plan['job_no'] == sel_job]
                tech_res = conn.table("quality_check_list").select("*").eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute().data
                t_data = tech_res[0] if tech_res else {}

                try:
                    pdf_bytes = create_birth_certificate(sel_job, h_data, t_data, p_data)
                    st.download_button(
                        label=f"📂 DOWNLOAD PRODUCT BIRTH CERTIFICATE: {sel_job}",
                        data=pdf_bytes,
                        file_name=f"Birth_Cert_{sel_job}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        type="primary",
                        key="pg_marketing_pdf"
                    )
                except Exception as e:
                    st.error(f"Could not generate PDF: {e}")

            st.divider()
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
                    # Photo upload logic would go here
                    pass

with main_tabs[1]:
    st.subheader("📋 Final Technical Inspection")
    # Technical checklist code remains the same...

st.divider()
st.subheader("📋 Recent Quality Clearances")
if not df_plan.empty:
    inspected_df = df_plan.dropna(subset=['quality_status']).sort_values(by='quality_updated_at', ascending=False)
    if not inspected_df.empty:
        st.dataframe(inspected_df[['job_no', 'gate_name', 'quality_status', 'quality
