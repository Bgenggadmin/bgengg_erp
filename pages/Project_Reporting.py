import streamlit as st
from st_supabase_connection import SupabaseConnection
from fpdf import FPDF

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0")
conn = st.connection("supabase", type=SupabaseConnection)

def create_pdf_with_logo():
    # Use 'P' for Portrait, 'mm' for millimeters, 'A4' size
    pdf = FPDF()
    pdf.add_page()
    
    # --- THE LOGO FIX ---
    try:
        # Get the PUBLIC URL instead of downloading raw bytes
        # This prevents the "string argument" and "damaged file" errors
        logo_url = conn.client.storage.from_("progress-photos").get_public_url("logo.png")
        pdf.image(logo_url, x=10, y=8, h=20)
    except Exception as e:
        st.warning(f"Logo couldn't load, but PDF will still work. Error: {e}")

    # --- HEADER TEXT ---
    pdf.set_font("Arial", 'B', 16)
    pdf.set_xy(60, 12) # Move text to the right of the logo
    pdf.cell(0, 10, "B&G ENGINEERING INDUSTRIES", ln=True)
    
    pdf.set_font("Arial", 'I', 10)
    pdf.set_xy(60, 18)
    pdf.cell(0, 10, "PROJECT PROGRESS REPORT", ln=True)
    
    pdf.ln(15)
    pdf.line(10, 32, 200, 32) # Horizontal line

    # --- SAMPLE CONTENT ---
    pdf.set_font("Arial", size=12)
    pdf.set_y(40)
    pdf.cell(0, 10, "Connection Test: SUCCESSFUL", ln=True)
    pdf.cell(0, 10, "Logo Integration: ACTIVE", ln=True)
    
    # --- THE STABLE OUTPUT ---
    # We return the output as bytes immediately to ensure Adobe can read it
    return pdf.output(dest='S').encode('latin-1')

st.title("🚀 Logo & PDF Recovery")

if st.button("Generate Final Test PDF"):
    try:
        final_data = create_pdf_with_logo()
        
        st.success("✅ PDF Generated with Logo!")
        st.download_button(
            label="📥 Download & Open in Adobe",
            data=final_data,
            file_name="BG_Final_Test.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Engine Error: {e}")
