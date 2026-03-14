import streamlit as st
from st_supabase_connection import SupabaseConnection
from fpdf import FPDF
from io import BytesIO

st.set_page_config(page_title="PDF Test")
conn = st.connection("supabase", type=SupabaseConnection)

def simple_pdf():
    pdf = FPDF()
    pdf.add_page()
    
    # 1. ATTEMPT LOGO
    try:
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            img_file = BytesIO(logo_data)
            # We use a simple alias 'logo.png' so FPDF knows the format
            pdf.image(img_file, x=10, y=10, h=20, type='PNG')
    except Exception as e:
        pdf.set_font("Arial", size=10)
        pdf.text(10, 20, f"Logo failed: {str(e)}")

    # 2. ADD TEXT
    pdf.set_font("Arial", 'B', 16)
    pdf.set_xy(10, 40)
    pdf.cell(0, 10, "B&G Hub Connection Test", ln=True)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"Generated on: {st.session_state.get('now', 'Today')}", ln=True)

    # 3. OUTPUT AS BYTES
    return bytes(pdf.output())

st.title("🛠️ PDF Engine Test")

if st.button("Generate Test PDF"):
    try:
        pdf_bytes = simple_pdf()
        st.success("PDF Generated Successfully!")
        st.download_button(
            label="📥 Download Test PDF",
            data=pdf_bytes,
            file_name="test_report.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Engine Crash: {e}")
