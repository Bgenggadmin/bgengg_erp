import streamlit as st
from st_supabase_connection import SupabaseConnection
from fpdf import FPDF
from io import BytesIO

st.set_page_config(page_title="PDF Test")
conn = st.connection("supabase", type=SupabaseConnection)

def simple_pdf():
    # Force FPDF2 behavior
    pdf = FPDF()
    pdf.add_page()
    
    # 1. LOGO WITH TYPE PROTECTION
    try:
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            # Wrap in BytesIO and name it so FPDF is happy
            img_file = BytesIO(logo_data)
            img_file.name = "logo.png" 
            pdf.image(img_file, x=10, y=10, h=20)
    except:
        pdf.set_font("Helvetica", size=10)
        pdf.text(10, 20, "Logo skipped to prevent crash")

    # 2. TEXT
    pdf.set_font("Helvetica", 'B', 16)
    pdf.set_xy(10, 40)
    pdf.cell(0, 10, "B&G Hub Connection Test", ln=True)

    # 3. THE FIX: Explicit byte conversion
    # This prevents the "string argument without encoding" error
    pdf_output = pdf.output()
    if isinstance(pdf_output, str):
        return pdf_output.encode('latin-1')
    return bytes(pdf_output)

st.title("🛠️ PDF Engine Test")

if st.button("Generate Test PDF"):
    try:
        final_pdf = simple_pdf()
        st.success("✅ Engine is Working!")
        st.download_button(
            label="📥 Download Now",
            data=final_pdf,
            file_name="test.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Engine Crash: {str(e)}")
