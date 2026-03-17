import streamlit as st
from st_supabase_connection import SupabaseConnection
from database_utils import fetch_all_master_data

# 1. Page Config MUST be the first Streamlit command
st.set_page_config(page_title="BGEngg ERP", page_icon="🏗️", layout="wide")

conn = st.connection("supabase", type=SupabaseConnection)

if "master_data" not in st.session_state:
    st.session_state.master_data = fetch_all_master_data(conn)

# 2. DEFINE PAGES MANUALLY
# Use the full path relative to the root
p1 = st.Page("pages/01_Anchor_Portal.py", title="Anchor Portal", icon="⚓", default=True)
p2 = st.Page("pages/02_Purchase_Console.py", title="Purchase Console", icon="🛒")
p3 = st.Page("pages/03_Production_Master.py", title="Production Master", icon="🏗️")
p4 = st.Page("pages/04_Project_Reporting.py", title="Project Reporting", icon="📈")

# 3. NAVIGATION
# This specific format prevents Streamlit from scanning the folder automatically
pg = st.navigation({
    "Operations": [p1, p2, p3],
    "Reporting": [p4]
})

pg.run()
