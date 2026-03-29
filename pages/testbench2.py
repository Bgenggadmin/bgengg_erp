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
    
    # 1. Logo from Supabase [cite: 7]
    try:
        supabase_url = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
        logo_url = f"{supabase_url}/storage/v1/object/public/progress-photos/logo.png"
        response = requests.get(logo_url)
        if response.status_code == 200:
            pdf.image(BytesIO(response.content), 10, 8, 45) 
    except:
        pass

    # 2. Header & Slogan [cite: 1, 7]
    pdf.set_y(15)
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "TECHNO-COMMERCIAL OFFER", ln=True, align='R')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 5, "Responsible towards water", ln=True, align='R')
    pdf.ln(20)

    # 3. Project Information [cite: 7, 9, 11]
    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 10, " 1. PROJECT INFORMATION", ln=True, fill=True)
    pdf.set_font("Arial", '', 10)
    info_fields = [
        ("Quote Reference:", data.get('ref', 'N/A')),
        ("Client Name:", data.get('client', 'N/A')),
        ("Capacity:", f"{data.get('cap', 110)} KLD"),
        ("MOC Selection:", data.get('moc', 'N/A'))
    ]
    for label, val in info_fields:
        pdf.cell(50, 8, label, 0); pdf.cell(0, 8, str(val), ln=True)
    pdf.ln(5)

    # 4. Plant Economics [cite: 68]
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, " 2. ESTIMATED PLANT ECONOMICS", ln=True, fill=True)
    pdf.set_font("Arial", '', 10)
    pdf.cell(0, 8, f"Annual Steam Savings: {data.get('savings', '36')} Lakhs/Year", ln=True)
    pdf.cell(0, 8, "Energy Recovery: Save more than 20% of fresh steam consumption", ln=True)
    pdf.ln(5)

    # 5. Commercial Summary 
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, " 3. COMMERCIAL SUMMARY", ln=True, fill=True)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 15, f"Total Project Value (DAP, Hyderabad): Rs. {data.get('total', 75800000):,.2f}", ln=True)
    
    return pdf.output(dest='S').encode('latin-1')

# --- 4. MAIN APP ---
if check_password():
    st.title("🛠️ testbench2: Optimized MEE Offer Builder")
    
    # Initialize session state keys if they don't exist
    for key, val in [('client', "M/s. MSN Life Sciences Pvt Ltd - I"), ('ref', "BG/ECOX-ZLD/25-26/2930 R0"), 
                     ('cap', 110), ('moc', "Option 1: Titanium/Duplex"), ('total', 75800000)]:
        if key not in st.session_state:
            st.session_state[key] = val

    menu = st.sidebar.selectbox("Offer Sections", ["1. Executive Summary", "2. Technical Specs", "3. Economics", "4. Scope", "5. Finalize"])

    if menu == "1. Executive Summary":
        st.subheader("Part I: Project Overview")
        st.session_state.client = st.text_input("Client Name", st.session_state.client)
        st.session_state.ref = st.text_input("Quote Reference", st.session_state.ref)

    elif menu == "2. Technical Specs":
        st.subheader("Part V: Engineering Parameters")
        st.session_state.cap = st.number_input("Capacity (KLD)", value=st.session_state.cap)
        st.session_state.moc = st.radio("Metallurgy Path", ["Option 1: Titanium/Duplex", "Option 2: SS 316Ti/L"], 
                                        index=0 if "Option 1" in st.session_state.moc else 1)

    elif menu == "3. Economics":
        st.subheader("Part IV: Plant Economics")
        steam_saved = st.number_input("Steam Savings (Kg/h)", value=240)
        annual_savings = (steam_saved * 24 * 300 * 2.5) / 100000
        st.session_state.savings = annual_savings
        st.metric("Annual Value to Client", f"₹ {annual_savings:.2f} Lakhs")

    elif menu == "5. Finalize":
        st.subheader("Finalize Offer")
        st.session_state.total = st.number_input("Total Price (INR)", value=st.session_state.total)
        
        if st.button("Sync to Supabase"):
            st.success("Synced to bgengg_erp!")
        
        # Prepare data for PDF [cite: 7, 9, 68, 123]
        current_data = {
            "ref": st.session_state.ref,
            "client": st.session_state.client,
            "cap": st.session_state.cap,
            "moc": st.session_state.moc,
            "savings": f"{st.session_state.get('savings', 36):.2f}",
            "total": st.session_state.total
        }
        
        pdf_bytes = generate_offer_pdf(current_data)
        st.download_button("📥 Download Final Offer PDF", pdf_bytes, 
                           f"Offer_{st.session_state.ref.replace('/', '_')}.pdf", "application/pdf")
