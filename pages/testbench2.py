import streamlit as st
import pandas as pd
from supabase import create_client
from fpdf import FPDF
import requests
from io import BytesIO

# --- 1. CREDENTIALS & CONNECTION ---
try:
    # Accessing secrets via the [connections.supabase] header
    url = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
    key = st.secrets["connections"]["supabase"]["SUPABASE_KEY"]
    supabase = create_client(url, key)
except KeyError:
    st.error("Secrets Configuration Error: Please ensure your secrets.toml has the [connections.supabase] header.")
    st.stop()

# --- 2. ACCESS CONTROL ---
def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        # Check against your admin password
        if st.session_state["password"] == st.secrets.get("TESTBENCH_PWD", "bg_admin_2026"):
            st.session_state["password_correct"] = True
            del st.session_state["password"] 
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Enter Password for testbench2", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Enter Password for testbench2", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        return True

# --- 3. PDF GENERATOR FUNCTION ---
def generate_offer_pdf(data):
    pdf = FPDF()
    pdf.add_page()
    
    # Logo from 'progress-photos' bucket
    try:
        supabase_url = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
        logo_url = f"{supabase_url}/storage/v1/object/public/progress-photos/logo.png"
        response = requests.get(logo_url)
        if response.status_code == 200:
            logo_data = BytesIO(response.content)
            pdf.image(logo_data, 10, 8, 33) 
    except Exception as e:
        pass # Fallback to text if logo fails

    # Header
    pdf.set_y(15)
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "TECHNO-COMMERCIAL OFFER", ln=True, align='R')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 5, "Responsible towards water", ln=True, align='R')
    pdf.ln(20)

    # Project Info
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "1. PROJECT INFORMATION", ln=True)
    pdf.set_font("Arial", '', 10)
    pdf.cell(50, 8, "Quote Reference:", 0)
    pdf.cell(0, 8, f"{data['quote_ref']}", ln=True)
    pdf.cell(50, 8, "Client Name:", 0)
    pdf.cell(0, 8, f"{data['client_name']}", ln=True)
    pdf.cell(50, 8, "System Capacity:", 0)
    pdf.cell(0, 8, f"{data['capacity_kld']} KLD", ln=True)
    pdf.ln(5)

    # Tech Specs
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "2. ENGINEERING SPECIFICATIONS", ln=True)
    pdf.set_font("Arial", '', 10)
    moc_label = "Option 1: Titanium Gr2 & Duplex 2205" if data['moc_option'] == 1 else "Option 2: SS 316Ti & SS 316L"
    pdf.cell(50, 8, "Metallurgy Path:", 0)
    pdf.cell(0, 8, moc_label, ln=True)
    pdf.cell(50, 8, "Energy Recovery:", 0)
    pdf.cell(0, 8, ">20% Fresh Steam Savings", ln=True)
    pdf.ln(5)

    # Commercial
    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 10, "3. COMMERCIAL SUMMARY", ln=True, fill=True)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 15, f"Total Project Value: Rs. {data['total_project_value']:,.2f}", ln=True)

    return pdf.output(dest='S').encode('latin-1')

# --- 4. MAIN APP LOGIC ---
if check_password():
    st.title("🛠️ testbench2: Optimized MEE Offer Builder")
    
    menu = st.sidebar.selectbox("Offer Sections", [
        "1. Executive Summary",
        "2. Technical Specs & Metallurgy",
        "3. Energy Synergy & Economics",
        "4. Scope & Battery Limits",
        "5. Commercials & Guarantees"
    ])

    # Persistent Data using Session State
    if 'client_name' not in st.session_state: st.session_state.client_name = "M/s. MSN Life Sciences Pvt Ltd - I" [cite: 9]
    if 'quote_ref' not in st.session_state: st.session_state.quote_ref = "BG/ECOX-ZLD/25-26/2930 R0" [cite: 7]
    if 'capacity' not in st.session_state: st.session_state.capacity = 110 [cite: 73]
    if 'total_val' not in st.session_state: st.session_state.total_val = 75800000 [cite: 123]
    if 'moc_opt' not in st.session_state: st.session_state.moc_opt = "Option 1: Titanium/Duplex"

    if menu == "1. Executive Summary":
        st.subheader("Part I: Project Overview [cite: 23, 24]")
        st.session_state.client_name = st.text_input("Client Name", st.session_state.client_name)
        st.session_state.quote_ref = st.text_input("Quote Reference", st.session_state.quote_ref)
        st.info("Key Value: Focus on the 'ECOX-BG ZLD' energy recovery. [cite: 34, 60]")

    elif menu == "2. Technical Specs & Metallurgy":
        st.subheader("Part V: Engineering Parameters [cite: 71, 72]")
        col1, col2 = st.columns(2)
        with col1:
            st.session_state.capacity = st.number_input("Capacity (KLD) [cite: 73]", value=st.session_state.capacity)
            cod = st.number_input("Feed COD (PPM) [cite: 73]", value=200000)
        with col2:
            st.session_state.moc_opt = st.radio("Metallurgy Path", ["Option 1: Titanium/Duplex", "Option 2: SS 316Ti/L"])
            steam_econ = st.text_input("Guaranteed Economy [cite: 75]", "~4.3 Kg/Kg")
        
        if "Option 1" in st.session_state.moc_opt:
            st.success("MOC: Titanium Gr2 Tubes & Duplex 2205 Tube Sheets. [cite: 92, 93]")
        else:
            st.warning("MOC: SS 316Ti Tubes & SS 316L Tube Sheets. [cite: 92, 93]")

    elif menu == "3. Energy Synergy & Economics":
        st.subheader("Part IV: Efficiency & ROI [cite: 66, 67]")
        st.write("Energy from ATFD vapor is recovered to save >20% fresh steam. [cite: 60]")
        steam_saved = st.number_input("Steam Savings (Kg/h) [cite: 68]", value=240) 
        steam_cost = st.number_input("Steam Cost (INR/Kg) [cite: 69]", value=2.5, step=0.1)
        annual_savings = (steam_saved * 24 * 300 * steam_cost) / 100000 [cite: 68, 69]
        st.metric("Annual Value to Client", f"₹ {annual_savings:.2f} Lakhs")

    elif menu == "4. Scope & Battery Limits":
        st.subheader("Part VIII: Responsibility Matrix [cite: 105, 106]")
        scope_data = {
            "Item": ["Structural MS", "PLC/SCADA", "Civil Foundations", "Utility Piping"],
            "Responsibility": ["B&G", "B&G", "Client", "Client"]
        }
        st.table(pd.DataFrame(scope_data))

    elif menu == "5. Commercials & Guarantees":
        st.subheader("Part X: Commercial Summary [cite: 120]")
        st.session_state.total_val = st.number_input("Total Contract Price (INR)", value=st.session_state.total_val)
        
        # Action Buttons
        col_a, col_b = st.columns(2)
        
        if col_a.button("Finalize & Sync to Supabase"):
            offer_payload = {
                "client_name": st.session_state.client_name,
                "quote_ref": st.session_state.quote_ref,
                "capacity_kld": st.session_state.capacity,
                "total_project_value": st.session_state.total_val,
                "moc_option": 1 if "Option 1" in st.session_state.moc_opt else 2,
                "status": "Ready"
            }
            try:
                supabase.table("mee_offers").insert(offer_payload).execute()
                st.success("Offer successfully synced to Supabase.")
            except Exception as e:
                st.error(f"Sync failed: {e}")

        # PDF Download
        current_data = {
            "quote_ref": st.session_state.quote_ref,
            "client_name": st.session_state.client_name,
            "capacity_kld": st.session_state.capacity,
            "moc_option": 1 if "Option 1" in st.session_state.moc_opt else 2,
            "total_project_value": st.session_state.total_val
        }
        pdf_bytes = generate_offer_pdf(current_data)
        col_b.download_button(
            label="📥 Download Offer PDF",
            data=pdf_bytes,
            file_name=f"Offer_{st.session_state.quote_ref.replace('/', '_')}.pdf",
            mime="application/pdf"
        )
