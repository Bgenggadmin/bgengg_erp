import streamlit as st
import pandas as pd
from supabase import create_client

# 1. Credentials & Connection using your nested TOML format
try:
    # Accessing secrets via the [connections.supabase] header
    url = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
    key = st.secrets["connections"]["supabase"]["SUPABASE_KEY"]
    supabase = create_client(url, key)
except KeyError:
    st.error("Secrets Configuration Error: Please ensure your secrets.toml has the [connections.supabase] header.")
    st.stop()

# 2. Access Control for testbench2
def check_password():
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

if check_password():
    st.title("🛠️ testbench2: Optimized MEE Offer Builder")
    
    # Sidebar Navigation - Focused Index [cite: 21, 22]
    menu = st.sidebar.selectbox("Offer Sections", [
        "1. Executive Summary",
        "2. Technical Specs & Metallurgy",
        "3. Energy Synergy & Economics",
        "4. Scope & Battery Limits",
        "5. Commercials & Guarantees"
    ])

    # --- DATA ENTRY SECTIONS ---
    
    if menu == "1. Executive Summary":
        st.subheader("Part I: Project Overview [cite: 23, 24]")
        client_name = st.text_input("Client Name", "M/s. MSN Life Sciences Pvt Ltd - I [cite: 9]")
        quote_ref = st.text_input("Quote Reference", "BG/ECOX-ZLD/25-26/2930 R0 [cite: 7]")
        st.info("Key Value: Focus on the 'ECOX-BG ZLD' energy recovery. [cite: 34, 60]")

    elif menu == "2. Technical Specs & Metallurgy":
        st.subheader("Part V: Engineering Parameters [cite: 71, 72]")
        col1, col2 = st.columns(2)
        with col1:
            capacity = st.number_input("Capacity (KLD) [cite: 73]", value=110)
            cod = st.number_input("Feed COD (PPM) [cite: 73]", value=200000)
        with col2:
            # Selection for Apple-to-Apple Comparison [cite: 123]
            moc = st.radio("Metallurgy Path", ["Option 1: Titanium/Duplex", "Option 2: SS 316Ti/L"])
            steam_econ = st.text_input("Guaranteed Economy [cite: 75]", "~4.3 Kg/Kg")
        
        # Displaying specific Metallurgy Specs based on selection [cite: 92, 93, 94]
        if "Option 1" in moc:
            st.success("MOC: Titanium Gr2 Tubes & Duplex 2205 Tube Sheets.")
        else:
            st.warning("MOC: SS 316Ti Tubes & SS 316L Tube Sheets.")

    elif menu == "3. Energy Synergy & Economics":
        st.subheader("Part IV: Efficiency & ROI [cite: 66, 67]")
        st.write("Energy from ATFD vapor is recovered to save >20% fresh steam. [cite: 60]")
        
        steam_saved = st.number_input("Steam Savings (Kg/h) [cite: 68]", value=240) 
        steam_cost = st.number_input("Steam Cost (INR/Kg) [cite: 69]", value=2.5, step=0.1)
        
        # Calculation Logic from [cite: 68, 69]
        annual_savings = (steam_saved * 24 * 300 * steam_cost) / 100000 
        st.metric("Annual Value to Client", f"₹ {annual_savings:.2f} Lakhs")

    elif menu == "4. Scope & Battery Limits":
        st.subheader("Part VIII: Responsibility Matrix [cite: 105, 106]")
        # Mapping responsibilities from [cite: 107]
        scope_data = {
            "Item": ["Structural MS", "PLC/SCADA", "Civil Foundations", "Utility Piping"],
            "Responsibility": ["B&G", "B&G", "Client", "Client"]
        }
        st.table(pd.DataFrame(scope_data))

    elif menu == "5. Commercials & Guarantees":
        st.subheader("Part X: Commercial Summary [cite: 120]")
        total_val = st.number_input("Total Contract Price (INR) [cite: 123]", value=75800000)
        
        st.markdown("**Performance Guarantees[cite: 77, 78]:**")
        st.write("* 48-Hour Performance Trial. [cite: 112]")
        st.write("* 10% tolerance on steam/power consumption. [cite: 78]")

        if st.button("Finalize & Sync to bgengg_erp"):
            offer_payload = {
                "client_name": client_name,
                "quote_ref": quote_ref,
                "capacity_kld": capacity,
                "total_project_value": total_val,
                "moc_option": 1 if "Option 1" in moc else 2,
                "status": "Ready"
            }
            try:
                # Syncing to your dedicated table
                supabase.table("mee_offers").insert(offer_payload).execute()
                st.success(f"Offer {quote_ref} successfully synced to Supabase.")
            except Exception as e:
                st.error(f"Sync failed: {e}")
