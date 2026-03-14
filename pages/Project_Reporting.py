import streamlit as st
from st_supabase_connection import SupabaseConnection
from fpdf import FPDF

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0")
conn = st.connection("supabase", type=SupabaseConnection)

def create_pdf_with_header():
    pdf = FPDF()
    pdf.add_page()
    
    # --- 1. THE BLUE STRIP ---
    pdf.set_fill_color(0, 51, 102) 
    pdf.rect(0, 0, 210, 25, 'F')

    # --- 2. THE LOGO ---
    try:
        logo_url = conn.client.storage.from_("progress-photos").get_public_url("logo.png")
        pdf.image(logo_url, x=12, y=5, h=15)
    except:
        pass

    # --- 3. THE HEADER TEXT ---
    pdf.set_text_color(255, 255, 255) 
    pdf.set_font("Arial", 'B', 16)
    pdf.set_xy(70, 5) 
    pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
    
    pdf.set_font("Arial", 'I', 10)
    pdf.set_xy(70, 14)
    pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
    
    pdf.set_text_color(0, 0, 0)
    pdf.ln(15)

    # --- 4. SAMPLE CONTENT ---
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "System Status: FIXED", ln=True)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 8, "- Library Version Conflict: Resolved", ln=True)

    # --- THE UNIVERSAL FIX ---
    # We check the type before deciding whether to encode or not.
    raw_output = pdf.output() 
    
    if isinstance(raw_output, (bytes, bytearray)):
        return bytes(raw_output)  # Already bytes, just pass it through
    else:
        return raw_output.encode('latin-1') # It's a string, encode it

st.title("🎨 Header Layout Test")

if st.button("Generate PDF with Blue Strip"):
    try:
        pdf_bytes = create_pdf_with_header()
        st.success("✅ PDF Generated Successfully!")
        st.download_button(
            label="📥 Download & Check Layout",
            data=pdf_bytes,
            file_name="BG_Branding_Test.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Layout Error: {e}")
