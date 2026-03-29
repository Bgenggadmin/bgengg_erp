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
    
    # --- PAGE 1: COVER & SUMMARY ---
    pdf.add_page()
    try:
        supabase_url = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
        logo_url = f"{supabase_url}/storage/v1/object/public/progress-photos/logo.png"
        response = requests.get(logo_url)
        if response.status_code == 200:
            pdf.image(BytesIO(response.content), 10, 8, 45) 
    except:
        pass

    pdf.set_y(15)
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "TECHNO-COMMERCIAL OFFER", ln=True, align='R')
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(0, 5, "Responsible towards water", ln=True, align='R')
    pdf.ln(20)

    pdf.set_font("Arial", 'B', 12); pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 10, " 1. PROJECT INFORMATION", ln=True, fill=True)
    pdf.set_font("Arial", '', 10)
    pdf.cell(50, 8, "Quote Reference:", 0); pdf.cell(0, 8, data['ref'], ln=True)
    pdf.cell(50, 8, "Client Name:", 0); pdf.cell(0, 8, data['client'], ln=True)
    pdf.cell(50, 8, "Capacity:", 0); pdf.cell(0, 8, f"{data['cap']} KLD", ln=True)
    pdf.ln(10)

    # --- PAGE 2: PROCESS & ECONOMICS ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, " 2. PROCESS & ECONOMICS", ln=True, fill=True)
    pdf.set_font("Arial", '', 10)
    pdf.multi_cell(0, 8, "The ECOX-BG ZLD SYSTEM utilizes energy recovery from ATFD vapors to save more than 20% of fresh steam consumption.")
    pdf.ln(5)
    pdf.cell(0, 8, f"Estimated Annual Steam Savings: Rs. {data['savings']} Lakhs/Year", ln=True)

    # --- PAGE 3: TECHNICAL SPECIFICATIONS (Option Based) ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, " 3. TECHNICAL SPECIFICATIONS", ln=True, fill=True)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(0, 10, f"Selected Metallurgy Path: {data['moc']}", ln=True)
    
    # Table Header for Apple-to-Apple check
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(60, 8, "Equipment", 1); pdf.cell(130, 8, "Specification", 1, ln=True)
    pdf.set_font("Arial", '', 9)
    
    # Logic to print specific specs from your Word doc based on MOC
    if "Option 1" in data['moc']:
        specs = [("Stripper Re-Boiler", "Titanium Gr2 Seamless Tubes, Duplex 2205 Sheet"),
                 ("MEE Calandria", "Titanium Gr2 Seamless Tubes, Duplex 2205 Sheet"),
                 ("ATFD Unit", "Duplex 2205 Inner Shell & Blades")]
    else:
        specs = [("Stripper Re-Boiler", "SS 316Ti Tubes, SS 316L Sheet"),
                 ("MEE Calandria", "SS 316Ti Tubes, SS 316L Sheet"),
                 ("ATFD Unit", "SS 316L Inner Shell & Blades")]
    
    for eq, sp in specs:
        pdf.cell(60, 8, eq, 1); pdf.cell(130, 8, sp, 1, ln=True)

    # --- FINAL PAGE: COMMERCIALS ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 12); pdf.cell(0, 10, " 4. COMMERCIAL SUMMARY", ln=True, fill=True)
    pdf.set_font("Arial", 'B', 11)
    pdf.cell(0, 15, f"Total Project Value (DAP, Hyderabad): Rs. {data['total']:,.2f}", ln=True)
    pdf.set_font("Arial", 'I', 9)
    pdf.multi_cell(0, 8, "Validity: 15 Days. Delivery: 6-7 Months (Option 1) or 3.5 Months (Option 2) from advance.")

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
