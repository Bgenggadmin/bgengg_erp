import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd

conn = st.connection("supabase", type=SupabaseConnection)

st.title("📝 Material Indent Application")

# Helper Loaders
def get_jobs():
    res = conn.table("anchor_projects").select("job_no").execute()
    return [r['job_no'] for r in res.data] if res.data else []

def get_groups():
    res = conn.table("material_master").select("material_group").execute()
    return [r['material_group'] for r in res.data] if res.data else ["GENERAL"]

with st.form("indent_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    selected_jobs = col1.multiselect("Job Nos (Multi-Select)", get_jobs())
    m_group = col2.selectbox("Material Group", get_groups())
    
    item_name = st.text_input("Item Name / Description")
    specs = st.text_area("Detailed Specifications", placeholder="Size, Grade, Brand, etc.")
    
    c1, c2, c3 = st.columns([1, 1, 2])
    qty = c1.number_input("Quantity", min_value=0.1, step=0.1)
    unit = c2.selectbox("Units", ["Nos", "Kgs", "Mts", "Sft", "Sets"])
    notes = c3.text_input("Special Notes")
    
    if st.form_submit_button("🚀 Raise Indent"):
        if selected_jobs and item_name:
            # We store the selected jobs as a string for simplicity in the 'job_no' column
            job_string = ", ".join(selected_jobs)
            payload = {
                "job_no": job_string,
                "item_name": item_name.upper(),
                "specs": specs,
                "quantity": qty,
                "units": unit,
                "material_group": m_group,
                "special_notes": notes,
                "status": "Triggered"
            }
            conn.table("purchase_orders").insert(payload).execute()
            st.success("Indent submitted to Purchase Console!")
        else:
            st.error("Job No and Item Name are mandatory.")

st.divider()
st.subheader("My Indent Status")
my_indents = conn.table("purchase_orders").select("*").order("created_at", desc=True).limit(10).execute().data
if my_indents:
    st.dataframe(pd.DataFrame(my_indents)[['job_no', 'item_name', 'quantity', 'status', 'po_no']], hide_index=True)
