        st.warning(f"Could not build Absent Today: {e}")
 
# ---- Pending Quotes ----
with st.expander("\U0001F4E8  Pending Quotes  (Quotation Sent)", expanded=True):
    try:
        df_pq = build_pending_quotes()
        st.metric("Open quotes awaiting a decision", len(df_pq))
        if df_pq.empty:
            st.info("No quotes are currently in 'Quotation Sent'.")
        else:
            st.dataframe(df_pq, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Pending Quotes: {e}")
 
# ---- Open Enquiries ----
with st.expander("\U0001F4E5  Open Enquiries  (not yet quoted)", expanded=True):
    try:
        df_oe = build_open_enquiries()
        st.metric("Enquiries awaiting a quote", len(df_oe))
        if df_oe.empty:
            st.info("No enquiries are currently open.")
        else:
            st.dataframe(df_oe, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning(f"Could not build Open Enquiries: {e}")
