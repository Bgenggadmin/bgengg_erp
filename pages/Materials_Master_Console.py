import streamlit as st
from st_supabase_connection import SupabaseConnection

conn = st.connection("supabase", type=SupabaseConnection)

st.title("🏗️ Materials Master Console")

with st.form("add_group_form", clear_on_submit=True):
    st.subheader("Add New Material Group")
    new_group = st.text_input("Material Group Name (e.g., Raw Steel, Fasteners)")
    category = st.selectbox("Category", ["Consumables", "Raw Materials", "Hardware", "Tools", "Electrical"])
    if st.form_submit_button("Save to Master"):
        if new_group:
            conn.table("material_master").insert({"material_group": new_group.upper(), "category": category}).execute()
            st.success(f"Group {new_group} added!")
        else:
            st.error("Enter group name.")

st.divider()
st.subheader("Existing Material Groups")
groups = conn.table("material_master").select("*").execute().data
if groups:
    st.table(groups)
