# --- TAB 1: SCHEDULING & EXECUTION ---
with tab_plan:
    st.subheader("📋 Production Control Center")
    target_job = st.selectbox("Select Job to Manage", ["-- Select --"] + all_jobs)
    
    if target_job != "-- Select --":
        # --- NEW: DELIVERY DATE LOGIC ---
        # We find the specific project row from df_projects
        proj_match = df_projects[df_projects['job_no'] == target_job]
        
        if not proj_match.empty:
            p_data = proj_match.iloc[0]
            # Safety check: only run if columns exist in the dataframe
            if 'po_delivery_date' in p_data:
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                    
                    po_dt = pd.to_datetime(p_data['po_delivery_date']).date() if p_data['po_delivery_date'] else None
                    rev_dt = pd.to_datetime(p_data['revised_delivery_date']).date() if p_data.get('revised_delivery_date') else None
                    
                    c1.markdown(f"**PO Delivery Date**\n{po_dt.strftime('%d-%b-%Y') if po_dt else 'Not Set'}")
                    
                    final_target = rev_dt if rev_dt else po_dt
                    if rev_dt:
                        c2.markdown(f"**🔴 Revised Date**\n{rev_dt.strftime('%d-%b-%Y')}")
                    else:
                        c2.markdown("**Revised Date**\nNo Revision")
                    
                    if final_target:
                        days_left = (final_target - date.today()).days
                        c3.metric("Days to Dispatch", f"{days_left} Days", 
                                  delta=days_left, delta_color="normal" if days_left > 7 else "inverse")
                    
                    # Edit Button to update dates directly
                    if c4.button("📝 Edit", key="edit_dates_btn"):
                        @st.dialog("Update Delivery Schedule")
                        def update_dates_ui(job, current_po, current_rev):
                            new_po = st.date_input("Original PO Date", value=current_po)
                            new_rev = st.date_input("Revised Date (Leave same if no change)", value=current_rev if current_rev else current_po)
                            if st.button("Save to Database"):
                                try:
                                    conn.table("anchor_projects").update({
                                        "po_delivery_date": new_po.isoformat(),
                                        "revised_delivery_date": new_rev.isoformat()
                                    }).eq("job_no", job).execute()
                                    st.cache_data.clear()
                                    st.success("Updated successfully!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Update failed: {e}")
                        
                        update_dates_ui(target_job, po_dt, rev_dt)

        st.divider()
        # ... (rest of your existing current_job_steps logic follows here)
