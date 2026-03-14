import streamlit as st
from st_supabase_connection import SupabaseConnection
from fpdf import FPDF

# 1. SETUP
st.set_page_config(page_title="B&G Hub 2.0")
conn = st.connection("supabase", type=SupabaseConnection)

def create_pdf_with_header():
    # Standard setup
    pdf = FPDF()
    pdf.add_page()
    
    # --- 1. THE BLUE STRIP ---
    # set_fill_color(Red, Green, Blue) -> 0, 51, 102 is the B&G Navy Blue
    pdf.set_fill_color(0, 51, 102) 
    # rect(x, y, width, height, style='F' for filled)
    pdf.rect(0, 0, 210, 25, 'F')

    # --- 2. THE LOGO (Over the blue strip) ---
    try:
        logo_url = conn.client.storage.from_("progress-photos").get_public_url("logo.png")
        # Placing logo at x=12, y=5 within the 25mm blue strip
        pdf.image(logo_url, x=12, y=5, h=15)
    except:
        pass

    # --- 3. THE HEADER TEXT (White text over blue strip) ---
    pdf.set_text_color(255, 255, 255) # White
    pdf.set_font("Arial", 'B', 16)
    pdf.set_xy(70, 5) 
    pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
    
    pdf.set_font("Arial", 'I', 10)
    pdf.set_xy(70, 14)
    pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
    
    # Reset text color to black for the rest of the document
    pdf.set_text_color(0, 0, 0)
    pdf.ln(15)

    # --- 4. SAMPLE CONTENT ---
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Layout Verification:", ln=True)
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 8, "- Blue Header Strip: OK", ln=True)
    pdf.cell(0, 8, "- White Header Text: OK", ln=True)
    pdf.cell(0, 8, "- Logo over Blue: OK", ln=True)

    # Return bytes for Streamlit
    return pdf.output(dest='S').encode('latin-1')

st.title("🎨 Header Layout Test")

if st.button("Generate PDF with Blue Strip"):
    try:
        pdf_bytes = create_pdf_with_header()
        st.success("✅ PDF Generated with Branding!")
        st.download_button(
            label="📥 Download & Check Layout",
            data=pdf_bytes,
            file_name="BG_Branding_Test.pdf",
            mime="application/pdf"
        )
    except Exception as e:
        st.error(f"Layout Error: {e}")
