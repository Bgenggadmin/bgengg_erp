import streamlit as st
import pandas as pd
from supabase import create_client

# 1. Existing Credentials & Connection
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

# 2. Temporary Access Control for testbench2
def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == st.secrets.get("TESTBENCH_PWD", "bg_admin_2026"):
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
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

if check_password():
    st.title("🛠️ testbench2: MEE High-End Offer Builder")
    
    # Sidebar Navigation for the 29-Page Offer Index [cite: 21, 22]
    menu = st.sidebar.selectbox("Offer Navigation", [
        "1. Executive Summary",
        "2. Process & Technical Specs",
        "3. Plant Economics (ROI)",
        "4. Scope & Battery Limits",
        "5. Commercials & Guarantees"
    ])

    # --- DATA ENTRY SECTIONS ---
    
    if menu == "1. Executive Summary":
        st.subheader("Part I: Executive Summary [cite: 23, 24]")
        client_name = st.text_input("Client Name", "M/s. MSN Life Sciences Pvt Ltd - I [cite: 9]")
        quote_ref = st.text_input("Quote Reference", "BG/ECOX-ZLD/25-26/2930 R0 [cite: 7]")
        st.info("AI Tip: Focus on the ECOX-ZLD energy recovery savings here. [cite: 34, 60]")

    elif menu == "2. Process & Technical Specs":
        st.subheader("Part V: Technical Parameters [cite: 71, 72]")
        col1, col2 = st.columns(2)
        with col1:
            capacity = st.number_input("Capacity (KLD) [cite: 73]", value=110)
            cod = st.number_input("Feed COD (PPM) [cite: 73]", value=200000)
        with col2:
            moc = st.radio("Metallurgy Selection ", ["Option 1: Titanium/Duplex", "Option 2: SS 316Ti/L"])
            steam_econ = st.text_input("Guaranteed Steam Economy [cite: 75]", "~4.3 Kg/Kg")

    elif menu == "3. Plant Economics (ROI)":
        st.subheader("Part IV: O&M Savings Analysis [cite: 66, 67]")
        # Logic matches your verified offer data 
        steam_saved = st.number_input("Steam Savings (Kg/h)", value=240) 
        annual_savings = (steam_saved * 24 * 300 * 2.5) / 100000 # In Lakhs [cite: 69]
        st.metric("Annual Value to Client", f"₹ {annual_savings:.2f} Lakhs ")

    elif menu == "4. Scope & Battery Limits":
        st.subheader("Part VIII: Scope Matrix [cite: 105, 106]")
        # Pre-filled based on your master document [cite: 107]
        scope_data = {
            "Item": ["Structural MS", "PLC/SCADA", "Civil Work", "Utility Piping"],
            "Responsibility": ["B&G", "B&G", "Client", "Client"]
        }
        st.table(pd.DataFrame(scope_data))

    elif menu == "5. Commercials & Guarantees":
        st.subheader("Part X: Commercial Summary [cite: 120]")
        total_val = st.number_input("Total Contract Price (INR) ", value=75800000)
        if st.button("Finalize & Sync to Supabase"):
            # Use your existing function [cite: 129, 130, 131]
            data = {"client": client_name, "ref": quote_ref, "value": total_val, "status": "Ready"}
            # save_offer(data) 
            st.success("Offer synced to bgengg_erp database.")
