import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Anchor Portal | BGEngg ERP", layout="wide", page_icon="⚓")

# --- 1. DATABASE CONNECTION ---
conn = st.connection("supabase", type=SupabaseConnection)

@st.cache_data(ttl=10)
def get_projects():
    res = conn.table("anchor_projects").select("*").order("id", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

df = get_projects()

# --- 2. SIDEBAR & SEARCH ---
st.sidebar.title("🎯 Anchor Control")
anchor_choice = st.sidebar.selectbox("Select Your Profile", ["Ammu", "Kishore"])
st.sidebar.divider()
search_query = st.sidebar.text_input("Search Client, Job, or Desc")

df_display = df[df['anchor_person'] == anchor_choice] if not df.empty else pd.DataFrame()

# --- 3. MAIN TABS ---
tabs = st.tabs(["📝 New Entry", "📂 Pipeline", "📐 Drawings", "🛒 Item-wise Purchase", "📊 Download"])

# --- TAB 1: NEW ENTRY (Keep existing) ---
with tabs[0]:
    st.subheader("Register New Project Enquiry")
    # ... (Your existing form code here) ...

# --- TAB 2: PIPELINE (Updated for Item-wise Trigger) ---
with tabs[1]:
    st.subheader("Sales Lifecycle & Item-wise Purchase Trigger")
    if not df_display.empty:
        for index, row in df_display.iterrows():
            with st.expander(f"💼 {row['client_name']} | Job: {row['job_no'] or 'N/A'}"):
                # Sales Updates
                c1, c2 = st.columns(2)
                u_job = c1.text_input("Job No.", value=row['job_no'] or "", key=f"pjob_{row['id']}")
                new_status = c2.selectbox("Stage", ["Enquiry", "Estimation", "Won", "Lost"], index=0, key=f"st_{row['id']}")
                
                st.divider()
                st.markdown("##### ➕ Add Critical Items for Purchase")
                
                # Form to add individual items
                with st.form(key=f"item_add_{row['id']}", clear_on_submit=True):
                    ic1, ic2 = st.columns([3, 1])
                    new_item = ic1.text_input("Item Name (e.g. Motor, SS Plate)")
                    item_spec = ic2.text_input("Qty/Specs")
                    if st.form_submit_button("Submit Item to Purchase"):
                        if u_job and new_item:
                            conn.table("purchase_orders").insert({
                                "job_no": u_job, "item_name": new_item, "specs": item_spec
                            }).execute()
                            st.success(f"Triggered: {new_item}")
                            st.rerun()
                        else:
                            st.error("Please ensure Job No is entered before adding items.")

                if st.button("Update Project Info", key=f"up_{row['id']}"):
                    conn.table("anchor_projects").update({"job_no": u_job, "status": new_status}).eq("id", row['id']).execute()
                    st.rerun()

# --- TAB 4: PURCHASE STATUS (Item-wise Response) ---
with tabs[3]:
    st.subheader("📦 Detailed Item-wise Purchase Status")
    if not df_display.empty:
        # Fetch items for projects belonging to this anchor
        try:
            # Get all job numbers for the current anchor
            job_list = df_display['job_no'].dropna().unique().tolist()
            if job_list:
                items_res = conn.table("purchase_orders").select("*").in_("job_no", job_list).execute()
                items_df = pd.DataFrame(items_res.data) if items_res.data else pd.DataFrame()
                
                if not items_df.empty:
                    for job in job_list:
                        job_items = items_df[items_df['job_no'] == job]
                        with st.container(border=True):
                            st.markdown(f"**Job No: {job}**")
                            # Display each item as a row
                            for _, item in job_items.iterrows():
                                col_a, col_b, col_c = st.columns([2, 1, 2])
                                col_a.write(f"🔹 {item['item_name']} ({item['specs']})")
                                
                                # Status with color
                                color = "green" if item['status'] == "Received" else "orange"
                                col_b.markdown(f":{color}[{item['status']}]")
                                
                                # Purchase Reply
                                reply = item['purchase_reply'] if item['purchase_reply'] else "Waiting for reply..."
                                col_c.caption(f"Reply: {reply}")
                else:
                    st.info("No items triggered for purchase yet.")
        except Exception as e:
            st.error("Purchase table not found. Please run the SQL setup in Supabase.")

# --- OTHER TABS (Keep existing) ---
