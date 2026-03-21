import streamlit as st

st.title("Session 3: The Warehouse")

# --- 1. THE LIST (The Conveyor Belt) ---
# Ordered collection of equipment
equipment_list = ["Lathe", "Milling Machine", "Drill Press", "Welding Rig"]

# --- 2. THE DICTIONARY (The Spec Sheet) ---
# Labeled data for a specific 'Job'
job_spec = {
    "Job_ID": "BG-2026-001",
    "Client": "Local Industrial Corp",
    "Material": "Mild Steel",
    "Quantity": 50
}

# --- 3. THE INTERFACE (The Warehouse Manager) ---
st.header("Inventory Overview")

# Displaying the List (The Belt)
st.subheader("Equipment on Floor")
st.write(f"Primary Tool: {equipment_list[0]}") # Accessing the 1st item
st.write(f"Backup Tool: {equipment_list[3]}")  # Accessing the 4th item

st.divider()

# Displaying the Dictionary (The Bin)
st.subheader("Active Job Specifications")
st.json(job_spec) # .json() is a great way to view 'Spec Sheets' clearly

# Accessing a specific 'Bin' by its 'Label'
st.info(f"Currently Processing: {job_spec['Material']}")
