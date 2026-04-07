import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import date

conn = st.connection("supabase", type=SupabaseConnection)
st.title("📦 Stores Application")

# Logic: Only show items that are 'Ordered' or 'In-Transit'
ordered_items = conn.table("purchase_orders").select("*").in_("status", ["Ordered", "In-Transit"]).execute().data

if ordered_items:
    for item in ordered_items:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.markdown(f"**Item:** {item['item_name']}  \n**Job:** {item['job_no']}")
            c2.markdown(f"**PO No:** {item.get('po_no', 'N/A')}  \n**Qty:** {item['quantity']} {item['units']}")
            
            with c3.popover("📥 Receive Item"):
                rec_date = st.date_input("Received Date", value=date.today(), key=f"rd_{item['id']}")
                remarks = st.text_area("Stores Remarks", key=f"srem_{item['id']}")
                if st.button("Confirm Receipt", key=f"btn_{item['id']}", type="primary"):
                    conn.table("purchase_orders").update({
                        "status": "Received",
                        "received_date": str(rec_date),
                        "stores_remarks": remarks
                    }).eq("id", item['id']).execute()
                    st.success("Item updated in inventory!")
                    st.rerun()
else:
    st.info("No items currently pending receipt (Wait for Purchase to Issue PO).")

st.divider()
st.subheader("Recently Received (Last 10)")
rec_hist = conn.table("purchase_orders").select("*").eq("status", "Received").order("received_date", desc=True).limit(10).execute().data
if rec_hist:
    st.dataframe(pd.DataFrame(rec_hist)[['received_date', 'item_name', 'job_no', 'po_no', 'stores_remarks']], hide_index=True)
