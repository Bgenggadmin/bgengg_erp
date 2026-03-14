import streamlit as st
from fpdf import FPDF

st.title("🛠️ Final PDF Engine Test")

def create_valid_pdf():
    # Use standard Latin-1 encoding for maximum compatibility with Adobe
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.add_page()
    
    # Header
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "B&G Hub Connection Test", ln=True, align='C')
    pdf.ln(10)
    
    # Body
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 10, "If you can read this, the PDF engine is working perfectly and the file is not damaged.")
    
    # CRITICAL FIX: The specific output method for Streamlit
    # This returns a raw string that we then encode to bytes
    return pdf.output(dest='S').encode('latin-1')

try:
    pdf_data = create_valid_pdf()
    
    st.success("✅ PDF created in memory!")
    
    st.download_button(
        label="📥 Download and Open in Adobe",
        data=pdf_data,
        file_name="bg_test_report.pdf",
        mime="application/pdf"
    )
except Exception as e:
    st.error(f"Error: {e}")
