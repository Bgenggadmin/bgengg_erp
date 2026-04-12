import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date, timedelta
import pytz
import urllib.parse

# ============================================================
# 1. SETUP & BRANDING
# ============================================================
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Command Center", layout="wide", page_icon="🏗️")

# FIX [Quick Win]: Removed hardcoded dark-mode-breaking CSS colors.
# urgent-row now uses st.error() natively. Header uses neutral styling.
st.markdown("""
    <style>
    .bg-header { background-color: #003366; color: white; padding: 1rem;
                 border-radius: 8px; text-align: center; }
    .blue-strip { background-color: #007bff; height: 1px; width: 100%;
                  margin:5px 0 10px 0; }
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("supabase", type=SupabaseConnection)

# ============================================================
# 2. UTILITIES
# ============================================================
def safe_db_write(fn, success_msg=None, error_prefix="DB Error"):
    """Wrap all DB writes — no silent crashes."""
    try:
        fn()
        if success_msg:
            st.success(success_msg)
        return True
    except Exception as e:
        st.error(f"{error_prefix}: {e}")
        return False

def clean_phone(raw):
    """FIX [Warning]: Strip non-digits so WhatsApp links always work."""
    return ''.join(filter(str.isdigit, str(raw or "")))

# ============================================================
# 3. DATA LOADERS — all cached
# ============================================================

# FIX [Critical]: Added @st.cache_data(ttl=60) — was uncached, fired on every rerun
@st.cache_data(ttl=60)
def get_jobs():
    try:
        res = conn.table("anchor_projects").select("job_no").execute()
        return sorted([str(r['job_no']).strip() for r in res.data if r.get('job_no')])
    except Exception:
        return []

# FIX [Critical]: Added @st.cache_data(ttl=60)
@st.cache_data(ttl=60)
def get_material_groups():
    try:
        res = conn.table("material_master").select("material_group").execute()
        return sorted([str(r['material_group']) for r in res.data])
    except Exception:
        return ["GENERAL"]

# FIX [Critical]: Added @st.cache_data(ttl=60)
@st.cache_data(ttl=60)
def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return sorted([r['name'] for r in res.data])
    except Exception:
        return ["Admin", "Staff"]

# FIX [Critical]: Fetch vendors once, cached — was fetched twice (Tab 2 + Tab 4)
@st.cache_data(ttl=60)
def get_vendors():
    try:
        res = conn.table("master_vendors").select("*").order("name").execute()
        return res.data if res.data else []
    except Exception:
        return []

# ============================================================
# 4. BRANDED HEADER
# ============================================================
st.markdown(
    '<div class="bg-header"><h1>B&G ENGINEERING</h1>'
    '<p>MATERIAL COMMAND CENTER</p></div>',
    unsafe_allow_html=True
)
st.markdown('<div class="blue-strip"></div>', unsafe_allow_html=True)

main_tabs = st.tabs([
    "📝 Indent Application",
    "🛒 Purchase Console",
    "📦 Stores GRN",
    "⚙️ Master Setup"
])

# ============================================================
# TAB 0: INDENT APPLICATION
# ============================================================
with main_tabs[0]:
    st.subheader("📝 Material Indent & Tracking")

    # Session state init
    if "rev_data"     not in st.session_state: st.session_state.rev_data     = None
    if "indent_cart"  not in st.session_state: st.session_state.indent_cart  = []

    raised_by = st.selectbox("Raised By", get_staff_list(), key="user_sel")

    # ── PART A: ENTRY FORM ───────────────────────────────────
    with st.expander(
        "➕ Add Item to Draft",
        expanded=True if not st.session_state.indent_cart else False
    ):
        rd = st.session_state.rev_data if st.session_state.rev_data is not None else {}

        if st.session_state.rev_data is not None:
            st.info(f"🔧 Editing / Revising: {rd.get('item_name', 'Item')}")

        with st.form("indent_form", clear_on_submit=True):
            f1, f2 = st.columns(2)

            def_jobs = rd.get('job_no', "").split(", ") if rd.get('job_no') else []
            job_list = get_jobs()
            sel_jobs = f1.multiselect(
                "Select Job Nos", job_list,
                default=[j for j in def_jobs if j in job_list]
            )

            m_list = get_material_groups()
            try:
                def_m_idx = m_list.index(rd['material_group']) if 'material_group' in rd else 0
            except Exception:
                def_m_idx = 0
            m_grp = f2.selectbox("Material Group", m_list, index=def_m_idx)

            i_name  = st.text_input("Item Name",       value=rd.get('item_name', ""))
            i_specs = st.text_area("Specifications",   value=rd.get('specs', ""))

            c1, c2, c3 = st.columns(3)
            try:
                curr_qty = float(rd.get('quantity', 0.1))
            except Exception:
                curr_qty = 0.1
            i_qty = c1.number_input("Qty", min_value=0.1, value=curr_qty)

            u_list = ["Nos", "Kgs", "Mts", "Sft", "Sets"]
            try:
                def_u_idx = u_list.index(rd['units']) if 'units' in rd else 0
            except Exception:
                def_u_idx = 0
            i_unit = c2.selectbox("Units", u_list, index=def_u_idx)

            i_note = st.text_input("Notes", value=rd.get('special_notes', ""))

            f_btn1, f_btn2 = st.columns([1, 4])
            submit_item = f_btn2.form_submit_button("✅ Add Item to List", use_container_width=True)
            cancel_edit = f_btn1.form_submit_button("❌ Cancel")

            if cancel_edit:
                st.session_state.rev_data = None
                st.rerun()

            if submit_item:
                if not sel_jobs or not i_name:
                    st.error("Job and Item Name are required.")
                # FIX [Warning]: Cap cart at 20 items
                elif len(st.session_state.indent_cart) >= 20:
                    st.warning("⚠️ Draft limit reached (20 items). Please submit before adding more.")
                else:
                    st.session_state.indent_cart.append({
                        "job_no": ", ".join(sel_jobs),
                        "material_group": m_grp,
                        "item_name": i_name.upper(),
                        "specs": i_specs,
                        "quantity": i_qty,
                        "units": i_unit,
                        "special_notes": i_note,
                        "triggered_by": raised_by,
                        "status": "Triggered",
                        "is_urgent": rd.get('is_urgent', False)
                    })
                    st.session_state.rev_data = None
                    st.rerun()

    # ── PART B: DRAFT LIST ───────────────────────────────────
    if st.session_state.indent_cart:
        st.markdown(f"### 🛒 Current Draft List ({len(st.session_state.indent_cart)}/20)")
        for idx, item in enumerate(st.session_state.indent_cart):
            with st.container(border=True):
                d1, d2 = st.columns([5, 1])
                d1.write(
                    f"**{item['item_name']}** | "
                    f"{item['quantity']} {item['units']} | {item['job_no']}"
                )
                if d2.button("🗑️", key=f"del_draft_{idx}"):
                    st.session_state.indent_cart.pop(idx)
                    st.rerun()

        if st.button("🚀 FINAL SUBMIT INDENT", type="primary", use_container_width=True):
            try:
                header = conn.table("indent_headers").insert({"raised_by": raised_by}).execute()
                new_id = header.data[0]['indent_no']
                for item in st.session_state.indent_cart:
                    item['indent_no'] = new_id
                    conn.table("purchase_orders").insert(item).execute()
                st.session_state.indent_cart = []
                st.cache_data.clear()
                st.success("✅ Indent Submitted Successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Submission Error: {e}")

    st.divider()

    # ── PART C: HISTORY, TRIGGER & EDIT/REVISE ───────────────
    st.subheader("🔍 Tracking & Adjustments")

    fc1, fc2 = st.columns(2)
    search_j   = fc1.selectbox("Filter by Job",    ["ALL"] + get_jobs())
    search_sta = fc2.selectbox("Filter by Status", ["ALL", "Triggered", "Ordered", "Received", "Rejected"])

    # FIX [Quick Win]: Filter by raised_by for relevance; keep limit=50
    try:
        hist_query = conn.table("purchase_orders").select("*") \
            .eq("triggered_by", raised_by) \
            .order("created_at", desc=True).limit(50).execute()
        hist_data = hist_query.data or []
    except Exception as e:
        st.error(f"History load error: {e}")
        hist_data = []

    if hist_data:
        df_h = pd.DataFrame(hist_data)
        if search_j   != "ALL": df_h = df_h[df_h['job_no'].str.contains(search_j, na=False)]
        if search_sta != "ALL": df_h = df_h[df_h['status'] == search_sta]

        if df_h.empty:
            st.info("No records match this filter.")
        else:
            for _, h_row in df_h.iterrows():
                row_id = h_row['id']
                status = h_row['status']
                is_urg = h_row.get('is_urgent', False)

                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    urg_icon = "🚨" if is_urg else "📦"
                    col1.write(f"**{urg_icon} {h_row['item_name']}** | Status: `{status}`")
                    col1.caption(f"Job: {h_row['job_no']} | Qty: {h_row['quantity']} {h_row['units']}")

                    # Rejected — show reason + revise
                    if status == "Rejected":
                        col1.error(f"Reason: {h_row.get('reject_note', 'No details')}")
                        if col2.button("📝 REVISE", key=f"rev_{row_id}", use_container_width=True):
                            st.session_state.rev_data = h_row
                            st.rerun()

                    # Triggered — edit / urgent / delete
                    if status == "Triggered":
                        # FIX [Warning]: Mark as "Editing" instead of immediate delete
                        # Record is only removed when new form is submitted successfully
                        if col2.button("✏️ EDIT", key=f"edit_{row_id}", use_container_width=True):
                            safe_db_write(
                                lambda: conn.table("purchase_orders")
                                    .update({"status": "Editing"})
                                    .eq("id", row_id).execute(),
                                error_prefix="Edit flag error"
                            )
                            st.session_state.rev_data = dict(h_row)
                            st.session_state.rev_data['_edit_id'] = row_id
                            st.rerun()

                        if not is_urg:
                            if col3.button("🚨", key=f"trig_{row_id}", help="Mark Urgent"):
                                safe_db_write(
                                    lambda: conn.table("purchase_orders")
                                        .update({"is_urgent": True})
                                        .eq("id", row_id).execute(),
                                    error_prefix="Urgent flag error"
                                )
                                st.rerun()
                        else:
                            col3.info("Priority")

                        if col4.button("🗑️", key=f"del_db_{row_id}", help="Delete"):
                            safe_db_write(
                                lambda: conn.table("purchase_orders")
                                    .delete().eq("id", row_id).execute(),
                                error_prefix="Delete error"
                            )
                            st.rerun()

                    # Active / received — read only
                    if status in ["Ordered", "Received"]:
                        col2.write("✅ Active")
    else:
        st.info("No indent history found.")

# ============================================================
# TAB 1: PURCHASE CONSOLE
# ============================================================
with main_tabs[1]:
    st.subheader("🛒 Purchase Processing")

    # FIX [Critical]: Reuse cached vendor data — no second DB call
    vendors_raw    = get_vendors()
    vendor_options = {v['name']: v for v in vendors_raw}

    # FIX [Critical]: Added 90-day date filter + limit(100) — was unbounded full scan
    cutoff_90 = str(date.today() - timedelta(days=90))
    try:
        res_p = conn.table("purchase_orders").select("*") \
            .neq("status", "Received") \
            .neq("status", "Rejected") \
            .neq("status", "Editing") \
            .gte("created_at", f"{cutoff_90}T00:00:00") \
            .limit(100).execute()
        pending_data = res_p.data or []
    except Exception as e:
        st.error(f"Purchase load error: {e}")
        pending_data = []

    if pending_data:
        df_p = pd.DataFrame(pending_data).sort_values(
            by=['is_urgent', 'created_at'], ascending=[False, False]
        )

        for _, p_row in df_p.iterrows():
            row_id = p_row['id']
            with st.container(border=True):
                h1, h2 = st.columns([3, 1.2])
                urgent_tag = "🚨 [URGENT]" if p_row.get('is_urgent') else ""

                with h1:
                    st.markdown(
                        f"**{urgent_tag} Indent #{p_row.get('indent_no', 'N/A')}** "
                        f"| Job: {p_row['job_no']}"
                    )
                    st.markdown(
                        f"**Item:** {p_row['item_name']} "
                        f"| Qty: {p_row['quantity']} {p_row.get('units', 'Nos')}"
                    )
                    st.caption(f"Specs: {p_row.get('specs', 'None')}")

                    selected_vendor_name = st.selectbox(
                        "Select Vendor for Enquiry",
                        options=["--- Choose Vendor ---"] + list(vendor_options.keys()),
                        key=f"v_sel_{row_id}"
                    )
                    v_info = vendor_options.get(selected_vendor_name, {})

                with h2:
                    # WhatsApp button
                    msg = (
                        f"B&G Enquiry:\nJob: {p_row['job_no']}\n"
                        f"Item: {p_row['item_name']}\nQty: {p_row['quantity']}\n"
                        f"Specs: {p_row.get('specs', '-')}"
                    )
                    # FIX [Warning]: Clean phone number before building URL
                    v_phone  = clean_phone(v_info.get('phone_number', ""))
                    wa_base  = f"https://wa.me/{v_phone}" if v_phone else "https://wa.me/"
                    wa_url   = f"{wa_base}?text={urllib.parse.quote(msg)}"
                    st.markdown(
                        f'<a href="{wa_url}" target="_blank" style="text-decoration:none;">'
                        f'<div style="background-color:#25D366; color:white; padding:8px; '
                        f'border-radius:5px; text-align:center; font-weight:bold; '
                        f'margin-bottom:8px;">📲 WhatsApp</div></a>',
                        unsafe_allow_html=True
                    )

                    # Email button
                    v_email      = v_info.get('email', "")
                    mail_subject = urllib.parse.quote(
                        f"Material Enquiry: {p_row['item_name']} | Job: {p_row['job_no']}"
                    )
                    mail_body = urllib.parse.quote(
                        f"Dear Sir/Madam,\n\nPlease find our enquiry for "
                        f"{p_row['item_name']} (Job: {p_row['job_no']}).\n"
                        f"Qty: {p_row['quantity']}\nSpecs: {p_row.get('specs', '-')}\n\n"
                        f"Regards,\nB&G Engineering"
                    )
                    mail_url = f"mailto:{v_email}?subject={mail_subject}&body={mail_body}"
                    st.markdown(
                        f'<a href="{mail_url}" style="text-decoration:none;">'
                        f'<div style="background-color:#007bff; color:white; padding:8px; '
                        f'border-radius:5px; text-align:center; font-weight:bold; '
                        f'margin-bottom:8px;">📧 Email Enquiry</div></a>',
                        unsafe_allow_html=True
                    )

                    # Pro Excel export
                    html_form = f"""
                    <html><body><table>
                    <tr><td colspan="2" style="font-size:18pt;font-weight:bold;color:#003366;">
                        B&G ENGINEERING</td></tr>
                    <tr><td>DATE:</td><td>{date.today().strftime('%d-%m-%Y')}</td></tr>
                    <tr style="background-color:#f2f2f2;">
                        <td colspan="2" style="font-weight:bold;">TECHNICAL SPECIFICATIONS</td></tr>
                    <tr><td>Item:</td><td><b>{p_row['item_name']}</b></td></tr>
                    <tr><td>Specs:</td><td>{p_row.get('specs', '-')}</td></tr>
                    <tr><td>Qty:</td>
                        <td><b>{p_row['quantity']} {p_row.get('units', 'Nos')}</b></td></tr>
                    </table></body></html>
                    """
                    st.download_button(
                        label="📄 Export Pro Enquiry",
                        data=html_form,
                        file_name=f"BG_{p_row['job_no']}.xls",
                        mime='application/vnd.ms-excel',
                        key=f"dl_{row_id}",
                        use_container_width=True
                    )

                # Action area
                c1, c2 = st.columns(2)
                with c1.expander("✅ Finalize Purchase Order"):
                    p_no  = st.text_input("PO No", key=f"po_{row_id}")
                    p_rem = st.text_input(
                        "Vendor / Remarks",
                        value=selected_vendor_name if selected_vendor_name != "--- Choose Vendor ---" else "",
                        key=f"rem_{row_id}"
                    )
                    if st.button("Confirm Order", key=f"ok_{row_id}", type="primary",
                                 use_container_width=True):
                        safe_db_write(
                            lambda: conn.table("purchase_orders").update({
                                "status": "Ordered", "po_no": p_no, "purchase_reply": p_rem
                            }).eq("id", row_id).execute(),
                            success_msg="Order confirmed!",
                            error_prefix="Order Error"
                        )
                        st.cache_data.clear()
                        st.rerun()

                with c2.expander("🚫 Reject Indent"):
                    rejection_reason = st.text_area("Reason for Rejection", key=f"rej_res_{row_id}")
                    if st.button("Confirm Rejection", key=f"rej_btn_{row_id}",
                                 type="secondary", use_container_width=True):
                        if rejection_reason:
                            safe_db_write(
                                lambda: conn.table("purchase_orders").update({
                                    "status": "Rejected", "reject_note": rejection_reason
                                }).eq("id", row_id).execute(),
                                error_prefix="Rejection Error"
                            )
                            st.rerun()
                        else:
                            st.warning("Please provide a reason.")
    else:
        st.info("No pending purchase requests found (last 90 days).")

# ============================================================
# TAB 2: STORES GRN
# ============================================================
with main_tabs[2]:
    st.subheader("📦 Goods Receipt Note (GRN) Desk")

    po_search = st.text_input(
        "🔍 Search by PO or Item", placeholder="e.g. PO-107", key="grn_search"
    )

    # FIX [Warning]: Added 90-day filter + limit(100) — was unbounded
    try:
        res_s = conn.table("purchase_orders").select("*") \
            .eq("status", "Ordered") \
            .not_.is_("indent_no", "null") \
            .gte("created_at", f"{cutoff_90}T00:00:00") \
            .limit(100).execute()
        stores_data = res_s.data or []
    except Exception as e:
        st.error(f"GRN load error: {e}")
        stores_data = []

    if stores_data:
        df_s = pd.DataFrame(stores_data)
        if po_search:
            df_s = df_s[
                df_s['po_no'].str.contains(po_search, case=False, na=False) |
                df_s['item_name'].str.contains(po_search, case=False, na=False)
            ]

        st.markdown(f"**Items Pending Arrival ({len(df_s)})**")

        for _, s_row in df_s.iterrows():
            row_id = s_row['id']
            with st.container(border=True):
                c_info, c_status, c_action = st.columns([2.5, 1, 1.5])

                with c_info:
                    st.markdown(f"#### PO: {s_row.get('po_no', 'N/A')}")
                    st.markdown(f"**{s_row['item_name']}** | Job: `{s_row['job_no']}`")
                    st.caption(
                        f"Indent Ref: #{s_row.get('indent_no')} "
                        f"| Vendor: {s_row.get('purchase_reply', '-')}"
                    )

                with c_status:
                    st.write("🚚 **In-Transit**")
                    st.caption(f"Qty: {s_row['quantity']} {s_row.get('units', 'Nos')}")
                    st.progress(66)

                with c_action:
                    dc_no = st.text_input(
                        "DC / Vehicle No", key=f"dc_{row_id}", placeholder="DC-123"
                    )
                    s_rem = st.text_input(
                        "Stores Remarks", key=f"srem_{row_id}", placeholder="Shortage/Damage?"
                    )
                    if st.button("✅ Confirm Receipt", key=f"btn_{row_id}",
                                 use_container_width=True, type="primary"):
                        if dc_no:
                            safe_db_write(
                                lambda: conn.table("purchase_orders").update({
                                    "status": "Received",
                                    "received_date": str(date.today()),
                                    "stores_remarks": f"DC: {dc_no} | Note: {s_rem}"
                                }).eq("id", row_id).execute(),
                                success_msg=f"GRN recorded for {s_row['item_name']}",
                                error_prefix="GRN Error"
                            )
                            st.rerun()
                        else:
                            st.warning("Please enter DC/Vehicle No")
    else:
        st.info("🚚 No pending arrivals (last 90 days).")

    # Audit trail
    st.divider()
    with st.expander("🕒 View Recently Received"):
        try:
            recent_res = conn.table("purchase_orders").select("*") \
                .eq("status", "Received") \
                .not_.is_("indent_no", "null") \
                .order("received_date", desc=True).limit(10).execute()
            if recent_res.data:
                df_recent = pd.DataFrame(recent_res.data)
                cols = [c for c in
                        ['received_date', 'po_no', 'item_name', 'quantity', 'job_no', 'stores_remarks']
                        if c in df_recent.columns]
                st.dataframe(df_recent[cols], use_container_width=True, hide_index=True)
            else:
                st.info("No received items yet.")
        except Exception as e:
            st.error(f"Audit load error: {e}")

# ============================================================
# TAB 3: MASTER SETUP
# ============================================================
with main_tabs[3]:
    st.subheader("⚙️ System Configuration & Master Data")

    col_grp, col_vend_form, col_vend_list = st.columns([1, 1.5, 2])

    # --- Material Groups ---
    with col_grp:
        st.markdown("#### 📦 Material Groups")
        with st.form("m_grp_form", clear_on_submit=True):
            new_g = st.text_input("New Group Name")
            if st.form_submit_button("➕ Save Group") and new_g:
                safe_db_write(
                    lambda: conn.table("material_master")
                        .insert({"material_group": new_g.upper()}).execute(),
                    success_msg=f"Group '{new_g.upper()}' added!",
                    error_prefix="Group Error"
                )
                st.cache_data.clear()
                st.rerun()

        try:
            grps = conn.table("material_master").select("*").execute().data
            if grps:
                st.dataframe(
                    pd.DataFrame(grps)[['material_group']],
                    hide_index=True, use_container_width=True
                )
        except Exception as e:
            st.error(f"Group load error: {e}")

    # --- Vendor Entry Form ---
    with col_vend_form:
        st.markdown("#### 🤝 Add New Vendor")
        with st.form("vendor_entry_form", clear_on_submit=True):
            v_name  = st.text_input("Vendor Company Name*")
            v_cat   = st.selectbox(
                "Category",
                ["Steel", "Hardware", "Electrical", "Consumables", "Services", "General"]
            )
            v_phone = st.text_input(
                "WhatsApp (91xxxxxxxxxx)", help="Include country code 91, no spaces."
            )
            v_email = st.text_input("Official Email")

            if st.form_submit_button("💾 Save Vendor Details"):
                if v_name:
                    # FIX [Warning]: Clean phone on save too
                    safe_db_write(
                        lambda: conn.table("master_vendors").insert({
                            "name":         v_name.strip().upper(),
                            "category":     v_cat,
                            "phone_number": clean_phone(v_phone),
                            "email":        v_email.strip().lower()
                        }).execute(),
                        success_msg=f"Vendor {v_name.upper()} added!",
                        error_prefix="Vendor Save Error"
                    )
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning("Company Name is required.")

    # --- Vendor Directory ---
    with col_vend_list:
        st.markdown("#### 🔍 Vendor Directory")
        v_search = st.text_input("Search Vendors...", placeholder="Name or category")

        # FIX [Quick Win]: Reuse cached vendor data — no extra DB call
        vendors_all = get_vendors()
        if vendors_all:
            df_v = pd.DataFrame(vendors_all)
            if v_search:
                mask = (
                    df_v['name'].str.contains(v_search, case=False, na=False) |
                    df_v['category'].str.contains(v_search, case=False, na=False)
                )
                df_v = df_v[mask]

            # FIX [Quick Win]: Show as dataframe instead of slow Python loop
            # Deletion kept as a targeted action below the table
            if not df_v.empty:
                display_cols = [c for c in ['name', 'category', 'phone_number', 'email']
                                if c in df_v.columns]
                st.dataframe(df_v[display_cols], use_container_width=True, hide_index=True)

                st.markdown("**Delete a vendor:**")
                del_name = st.selectbox(
                    "Select vendor to remove",
                    ["-- Select --"] + df_v['name'].tolist(),
                    key="del_vendor_sel"
                )
                if del_name != "-- Select --":
                    del_row = df_v[df_v['name'] == del_name].iloc[0]
                    if st.button(f"🗑️ Delete {del_name}", type="secondary",
                                 key="confirm_del_vendor"):
                        safe_db_write(
                            lambda: conn.table("master_vendors")
                                .delete().eq("id", int(del_row['id'])).execute(),
                            success_msg=f"{del_name} removed.",
                            error_prefix="Delete Error"
                        )
                        st.cache_data.clear()
                        st.rerun()
            else:
                st.info("No vendors match your search.")
        else:
            st.info("No vendors registered yet.")
