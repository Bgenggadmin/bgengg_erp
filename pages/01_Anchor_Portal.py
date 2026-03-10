import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Anchor Portal | BGEngg ERP", layout="wide", page_icon="⚓")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=60) # Cache data for 1 minute to improve speed
def get_projects():
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df = get_projects()

# --- 2. SIDEBAR CONFIGURATION & SEARCH ---
st.sidebar.title("🎯 Anchor Control")
anchor_choice = st.sidebar.selectbox("Select Your Profile", ["Ammu", "Kishore"])

st.sidebar.divider()
st.sidebar.subheader("🔍 Global Search")
search_query = st.sidebar.text_input("Search Client or Job No.", placeholder="e.g. Tata or J-101")

# Apply Filters
df_display = df[df['anchor_person'] == anchor_choice] if not df.empty else pd.DataFrame()

if search_query and not df_display.empty:
    df_display = df_display[
        df_display['client_name'].str.contains(search_query, case=False, na=False) |
        df_display['job_no'].str.contains(search_query, case=False, na=False) |
        df_display['project_description'].str.contains(search_query, case=False, na=False)
    ]

st.title(f"⚓ {anchor_choice}'s Project Portal")
if search_query:
    st.caption(f"Showing results for: '{search_query}'")
st.markdown("---")

# --- 3. LIVE ACTION SUMMARY ---
if not df_display.empty:
    today = pd.to_datetime(datetime.now().date())
    df_display['enquiry_date'] = pd.to_datetime(df_display['enquiry_date'])
    df_display['aging_days'] = (today - df_display['enquiry_date']).dt.days

    st.subheader("🚀 Live Action Summary")
    pend_quotes = df_display[df_display['status'].isin(['Enquiry', 'Estimation'])]
    pend_drawings = df_display[(df_display['drawing_status'] != 'Approved') & (df_display['status'] != 'Lost')]

    col1, col2 = st.columns(2)
    with col1:
        st.info(f"📋 **Pending Quotations ({len(pend_quotes)})**")
        if not pend_quotes.empty:
            st.dataframe(pend_quotes[['client_name', 'project_description', 'aging_days']].rename(columns={'aging_days': 'Days Pending'}), hide_index=True, use_container_width=True)
    with col2:
        st.warning(f"📐 **Pending Drawings ({len(pend_drawings)})**")
        if not pend_drawings.empty:
            st.dataframe(pend_drawings[['client_name', 'drawing_status', 'aging_days']].rename(columns={'aging_days': 'Days Since Enq'}), hide_index=True, use_container_width=True)
    st.markdown("---")

# --- 4. MAIN TABS ---
tabs = st.tabs(["📝 New Entry", "📂 Pipeline", "📐 Drawings", "🛒 Purchase", "📊 Download Data"])

# --- TAB 1 to 4: (Same as previous logic, now operating on filtered df_display) ---
# [Note: The logic inside Tabs 1-4 remains identical to your previous code, 
# ensuring they only show filtered items if a search is active]

# --- TAB 5: DOWNLOAD DATA ---
with tabs[4]:
    st.subheader("📥 Export Your Project Records")
    st.write("Download your filtered project list as a CSV file for Excel reporting.")
    
    if not df_display.empty:
        # Clean up dataframe for export
        export_df = df_display.drop(columns=['id'], errors='ignore')
        
        # Create Download Button
        csv = export_df.to_csv(index=False).encode('utf-8')
        
        st.download_button(
            label="💾 Download CSV Report",
            data=csv,
            file_name=f"BGEngg_{anchor_choice}_Report_{datetime.now().strftime('%Y%m%d')}.csv",
            mime='text/csv',
            use_container_width=True
        )
        
        st.write("### Preview of Export Data")
        st.dataframe(export_df, use_container_width=True)
    else:
        st.warning("No data available to download.")

# (Tab 1-4 logic continues here...)
# [Insert the TAB 1, 2, 3, 4 logic from the previous turn here to complete the file]
