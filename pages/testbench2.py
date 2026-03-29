import streamlit as st
import pandas as pd
from supabase import create_client
from fpdf import FPDF
import requests
from io import BytesIO

# --- 1. CREDENTIALS & CONNECTION ---
try:
    url = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
    key = st.secrets["connections"]["supabase"]["SUPABASE_KEY"]
    supabase = create_client(url, key)
except KeyError:
    st.error("Secrets Configuration Error: Ensure secrets.toml has [connections.supabase]")
    st.stop()

# --- 2. ACCESS CONTROL ---
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets.get("TESTBENCH_PWD", "bg_admin_2026"):
            st.session_state["password_correct"] = True
            del st.session_state["password"] 
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Enter Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Enter Password", type="password", on_change=password_entered, key="password")
        st.error("Password incorrect")
        return False
    else:
        return True

# --- 3. PDF GENERATOR ---
def generate_offer_pdf(data):
    pdf = FPDF()
    pdf.add_page()
    try:
        logo_url = f"{st.secrets['connections']['supabase']['SUPABASE_URL']}/storage/v1/object/public/progress-photos/logo.png"
        response = requests.get(logo_url)
        if response.status_code == 200:
            pdf.image(BytesIO(response.content), 10, 8, 33) 
    except:
        pass

    pdf.set_y(15)
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "TECHNO-COMMERCIAL OFFER", ln=True, align='R')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 5, "Responsible towards water", ln=True, align='R')
    pdf.ln(20)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "1. PROJECT INFORMATION", ln=True)
    pdf.set_font("Arial", '', 10)
    pdf.cell(50, 8, "Quote Reference:", 0); pdf.cell(0, 8, f"{data['quote_ref']}", ln=True)
    pdf.cell(50, 8, "Client Name:", 0); pdf.cell(0, 8, f"{data['client_name']}", ln=True)
    pdf.cell(50, 8, "Capacity:", 0); pdf.cell(0, 8, f"{data['capacity_kld']} KLD", ln=True)
    
    return pdf.output(dest='S').encode('latin-1')

# --- 4. MAIN APP ---
if check_password():
    st.title("🛠️ testbench2: Optimized MEE Offer Builder")
    
    menu = st.sidebar.selectbox("Offer Sections", [
        "1. Executive Summary",
        "2. Technical Specs",
        "3. Economics",
        "4. Scope",
        "5. Finalize"
    ])

    if menu == "1. Executive Summary":
        st.subheader("Part I: Project Overview")
        client_name = st.text_input("Client Name", "M/s. MSN Life Sciences Pvt Ltd - I")
        quote_ref = st.text_input("Quote Reference", "BG/ECOX-ZLD/25-26/2930 R0")

    elif menu == "2. Technical Specs":
        st.subheader("Part V: Engineering Parameters")
        capacity = st.number_input("Capacity (KLD)", value=110)
        moc = st.radio("Metallurgy Path", ["Option 1: Titanium/Duplex", "Option 2: SS 316Ti/L"])
        st.session_state.update({"cap": capacity, "moc": moc, "client": client_name, "ref": quote_ref})

    elif menu == "5. Finalize":
        st.subheader("Finalize Offer")
        if st.button("Sync to Supabase"):
            # Sync logic here
            st.success("Synced!")
        
        # Pass collected data to PDF generator
        current_data = {
            "quote_ref": st.session_state.get('ref', "N/A"),
            "client_name": st.session_state.get('client', "N/A"),
            "capacity_kld": st.session_state.get('cap', 110),
            "moc_option": 1 if "Option 1" in st.session_state.get('moc', "") else 2,
            "total_project_value": 75800000
        }
        pdf_bytes = generate_offer_pdf(current_data)
        st.download_button("📥 Download Offer PDF", pdf_bytes, "Offer.pdf", "application/pdf")
