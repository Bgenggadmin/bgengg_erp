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
    # Helper for character safety
    def clean_text(text):
        if not text: return "N/A"
        text = str(text).replace("✅", "[PASS]").replace("❌", "[REJECT]").replace("⚠️", "[REWORK]")
        return text.encode('ascii', 'ignore').decode('ascii')

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # --- 1. LOGO & BLUE STRIP HEADER ---
    logo_path = None
    try:
        # Pulling logo from your existing progress-photos bucket
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            with NamedTemporaryFile(delete=False, suffix=".png") as tmp_logo:
                tmp_logo.write(logo_data)
                logo_path = tmp_logo.name
    except: pass

    # Dark Blue Strip
    pdf.set_fill_color(0, 51, 102) 
    pdf.rect(0, 0, 210, 25, 'F')
    
    if logo_path:
        pdf.image(logo_path, x=12, y=5, h=15)
    
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Arial", 'B', 16)
    pdf.set_xy(70, 5)
    pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
    pdf.set_font("Arial", "I", 10)
    pdf.set_xy(70, 14)
    pdf.cell(130, 5, "PRODUCT QUALITY BIRTH CERTIFICATE", 0, 1, "L")

    # Reset text to black for body
    pdf.set_text_color(0, 0, 0)
    pdf.ln(15)

    # --- 2. PRODUCT IDENTIFICATION TABLE (Structured Format) ---
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

    # --- 3. MANUFACTURING LOG (With Image Grid) ---
    pdf.set_font("Arial", 'B', 12)
    pdf.set_text_color(0, 51, 102)
    pdf.cell(190, 8, "MANUFACTURING LOG & VISUAL EVIDENCE", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    if not photo_data.empty:
        # Sort chronologically
        photo_data = photo_data.dropna(subset=['quality_updated_at']).sort_values('quality_updated_at')
        
        for idx, row in photo_data.iterrows():
            date_str = pd.to_datetime(row['quality_updated_at']).strftime('%d-%m-%Y')
            
            # Entry header with blue background tint
            pdf.set_font("Arial", 'B', 10)
            pdf.set_fill_color(230, 240, 255)
            pdf.cell(190, 8, f" [{date_str}] - {clean_text(row['gate_name'])}", border="TLR", ln=True, fill=True)
            
            # Remarks and Inspector
            pdf.set_font("Arial", '', 9)
            remarks = f" Inspector: {clean_text(row['quality_by'])} | Status: {clean_text(row['quality_status'])}\n Technical Remarks: {clean_text(row['quality_notes'])}"
            pdf.multi_cell(190, 6, remarks, border="LR")
            
            # Image Grid Logic
            urls = row.get('quality_photo_url', [])
            if isinstance(urls, list) and len(urls) > 0:
                y_current = pdf.get_y()
                img_w, img_h = 44, 55 # Calculated aspect ratio for 4 images
                
                # Check for page space
                if y_current + img_h > 260:
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
                
                pdf.set_y(y_current + img_h + 5) # Advance cursor past images
            
            pdf.cell(190, 1, "", border="BLR", ln=True) # Close the block
            pdf.ln(4)
    else:
        pdf.cell(190, 10, "No manufacturing evidence logged yet.", ln=True)

    # Clean up temp logo
    if logo_path and os.path.exists(logo_path): os.unlink(logo_path)

    return pdf.output(dest='S').encode('latin-1')

# --- 3. DATA LOADERS ---
@st.cache_data(ttl=2)
def get_quality_context():
    plan_res = conn.table("job_planning").select("*").neq("current_status", "Pending").execute()
    anchor_res = conn.table("anchor_projects").select("job_no, client_name, po_no, po_date").execute()
    try:
        staff_res = conn.table("master_staff").select("name").execute()
        staff_list = sorted([s['name'] for s in staff_res.data]) if staff_res.data else []
    except:
        staff_list = []
    return pd.DataFrame(plan_res.data or []), pd.DataFrame(anchor_res.data or []), staff_list

df_plan, df_anchor, authorized_inspectors = get_quality_context()

# --- 4. UI ---
st.title("🔍 Quality Assurance & Inspection Portal")
main_tabs = st.tabs(["🚪 Process Gate (Evidence)", "📋 Technical Checklist (Reports)"])

with main_tabs[0]:
    if not df_plan.empty:
        # Date Filter
        st.subheader("🗓️ Inspection Timeline Filter")
        range_col1, range_col2 = st.columns([1, 2])
        filter_option = range_col1.selectbox("Select Range", ["All Records", "Last 7 Days", "This Month", "Custom Range"], key="pg_date_filter")
        
        today = datetime.now(IST).date()
        start_dt, end_dt = None, None
        if filter_option == "Last 7 Days": start_dt = today - pd.Timedelta(days=7)
        elif filter_option == "This Month": start_dt = today.replace(day=1)
        elif filter_option == "Custom Range":
            custom_range = range_col2.date_input("Pick Dates", [today - pd.Timedelta(days=30), today])
            if len(custom_range) == 2: start_dt, end_dt = custom_range

        df_filtered = df_plan.copy()
        df_filtered['quality_updated_at_dt'] = pd.to_datetime(df_filtered['quality_updated_at']).dt.date
        if start_dt: df_filtered = df_filtered[df_filtered['quality_updated_at_dt'] >= start_dt]
        if end_dt: df_filtered = df_filtered[df_filtered['quality_updated_at_dt'] <= end_dt]

        st.divider()
        c1, c2 = st.columns(2)
        unique_jobs = sorted(df_filtered['job_no'].unique()) if not df_filtered.empty else []
        sel_job = c1.selectbox("🏗️ Select Job Number", ["-- Select --"] + unique_jobs, key="pg_job_sel")

        if sel_job != "-- Select --":
            # PDF Presentation Mode
            with st.container(border=True):
                st.subheader("💎 BIRTH CERTIFICATE")
                h_match = df_anchor[df_anchor['job_no'] == sel_job]
                h_data = {
                    "client_name": h_match.iloc[0].get('client_name', 'N/A') if not h_match.empty else "N/A",
                    "po_no": h_match.iloc[0].get('po_no', 'N/A') if not h_match.empty else "N/A",
                    "po_date": str(h_match.iloc[0].get('po_date', 'N/A')) if not h_match.empty else "N/A",
                    "drawing_no": "Verified on Shop Floor"
                }
                
                p_data = df_filtered[df_filtered['job_no'] == sel_job]
                tech_res = conn.table("quality_check_list").select("*").eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute().data
                t_data = tech_res[0] if tech_res else {}

                try:
                    pdf_bytes = create_birth_certificate(sel_job, h_data, t_data, p_data)
                    st.download_button(label=f"📂 DOWNLOAD BIRTH CERTIFICATE: {sel_job}", data=pdf_bytes, file_name=f"Birth_Cert_{sel_job}.pdf", mime="application/pdf", use_container_width=True, type="primary")
                except Exception as e:
                    st.error(f"PDF Error: {e}")

            st.divider()
            
            # --- SAVE NEW RECORD LOGIC ---
            job_stages = df_plan[df_plan['job_no'] == sel_job]
            sel_stage = c2.selectbox("🚪 Select Process/Gate", job_stages['gate_name'].tolist(), key="pg_gate_sel")
            stage_record = job_stages[job_stages['gate_name'] == sel_stage].iloc[0]
            
            with st.form("quality_form", clear_on_submit=True):
                st.subheader(f"Log Evidence: {sel_job} > {sel_stage}")
                f1, f2 = st.columns(2)
                with f1:
                    q_status = st.segmented_control("Result", ["✅ Pass", "❌ Reject", "⚠️ Rework"], default="✅ Pass")
                    inspector = st.selectbox("Inspector", ["-- Select --"] + authorized_inspectors, key="pg_insp")
                    q_notes = st.text_area("Observations")
                with f2:
                    q_photos = st.file_uploader("Photos (Max 4)", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)

                if st.form_submit_button("🚀 Submit Gate Report", use_container_width=True):
                    if inspector == "-- Select --":
                        st.error("Select Inspector")
                    else:
                        try:
                            # --- INSERT STORAGE & DB UPDATE LOGIC HERE ---
                            # (Omitted for brevity, keep your existing image resize/upload code here)
                            st.success("Gate update successful!")
                            st.rerun()
                        except Exception as e: st.error(f"Submit Error: {e}")

# TAB 2
with main_tabs[1]:
    st.subheader("📋 Technical Check List")
    if not df_anchor.empty:
        with st.container(border=True):
            tc1, tc2 = st.columns(2)
            q_job_tech = tc1.selectbox("Job No", ["-- Select --"] + df_anchor['job_no'].tolist(), key="tc_job")
            # ... Rest of your Technical Checklist form code ...

# --- 5. SUMMARY VIEW ---
st.divider()
st.subheader("📋 Recent Quality Clearances")
if not df_plan.empty:
    inspected_df = df_plan.dropna(subset=['quality_status']).sort_values(by='quality_updated_at', ascending=False)
    if not inspected_df.empty:
        st.dataframe(inspected_df[['job_no', 'gate_name', 'quality_status', 'quality_by', 'quality_notes']], use_container_width=True, hide_index=True)
