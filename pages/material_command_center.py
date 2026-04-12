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
    .blue-strip { background-color: #007bff; height: 3px; width: 100%;
                  margin: 10px 0 20px 0; }
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
# TAB 1: PURCHASE CONSOLE  (Indent → Material Group → Items)
# ============================================================
with main_tabs[1]:
    st.subheader("🛒 Purchase Processing")

    vendors_raw    = get_vendors()
    vendor_options = {v['name']: v for v in vendors_raw}
    vendor_list    = ["--- Choose Vendor ---"] + list(vendor_options.keys())

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
        df_p = pd.DataFrame(pending_data)
        df_p['_has_urgent'] = df_p['is_urgent'].fillna(False)
        df_p = df_p.sort_values(
            by=['_has_urgent', 'indent_no'], ascending=[False, False]
        )

        # ── LEVEL 1: GROUP BY INDENT ─────────────────────────
        for indent_no, indent_grp in df_p.groupby('indent_no', sort=False):
            indent_grp  = indent_grp.reset_index(drop=True)
            has_urgent  = indent_grp['is_urgent'].fillna(False).any()
            all_jobs    = ", ".join(sorted(indent_grp['job_no'].dropna().unique()))
            item_count  = len(indent_grp)
            raised_by_i = indent_grp.iloc[0].get('triggered_by', '—')
            mat_groups  = sorted(indent_grp['material_group'].dropna().unique())

            with st.container(border=True):
                # Indent header
                st.markdown(
                    f"### {'🚨 ' if has_urgent else ''}Indent #{indent_no} &nbsp;"
                    f"<span style='font-size:14px; color:gray;'>"
                    f"{item_count} item{'s' if item_count>1 else ''} | "
                    f"Job(s): {all_jobs} | Raised by: {raised_by_i} | "
                    f"Groups: {', '.join(mat_groups)}</span>",
                    unsafe_allow_html=True
                )
                st.divider()

                # ── LEVEL 2: GROUP BY MATERIAL GROUP ─────────
                for grp_idx, mat_grp in enumerate(mat_groups):
                    grp_items = indent_grp[
                        indent_grp['material_group'] == mat_grp
                    ].reset_index(drop=True)

                    # Composite key base: indent + group position — globally unique
                    gkey = f"{indent_no}_g{grp_idx}"

                    # Group subheader + vendor selector side by side
                    gh1, gh2 = st.columns([2.5, 2])
                    with gh1:
                        st.markdown(
                            f"#### 📦 {mat_grp} "
                            f"<span style='font-size:13px; color:gray;'>"
                            f"({len(grp_items)} item{'s' if len(grp_items)>1 else ''})"
                            f"</span>",
                            unsafe_allow_html=True
                        )
                        # Item rows for this group
                        for item_idx, p_row in enumerate(grp_items.to_dict('records')):
                            row_id   = p_row['id']
                            status   = p_row['status']
                            ukey     = f"{gkey}_i{item_idx}"
                            urg_icon = "🚨" if p_row.get('is_urgent') else "▪️"

                            ic1, ic2, ic3, ic4 = st.columns([3.5, 1, 1, 1])
                            ic1.markdown(
                                f"{urg_icon} **{p_row['item_name']}** &nbsp;"
                                f"`{p_row['quantity']} {p_row.get('units','Nos')}` &nbsp;"
                                f"Job: {p_row['job_no']} &nbsp; `{status}`"
                            )
                            if p_row.get('specs'):
                                ic1.caption(f"Specs: {p_row['specs']}")

                            if status == "Rejected":
                                ic1.error(f"Reason: {p_row.get('reject_note','No details')}")
                                if ic2.button("📝 Revise", key=f"pc_rev_{ukey}",
                                              use_container_width=True):
                                    st.session_state.rev_data = p_row
                                    st.rerun()

                            if status == "Triggered":
                                if not p_row.get('is_urgent'):
                                    if ic3.button("🚨", key=f"pc_trig_{ukey}",
                                                  help="Mark Urgent"):
                                        safe_db_write(
                                            lambda rid=row_id: conn.table("purchase_orders")
                                                .update({"is_urgent": True})
                                                .eq("id", rid).execute(),
                                            error_prefix="Urgent flag error"
                                        )
                                        st.rerun()
                                else:
                                    ic3.caption("Priority")

                                if ic4.button("🗑️", key=f"pc_del_{ukey}",
                                              help="Delete item"):
                                    safe_db_write(
                                        lambda rid=row_id: conn.table("purchase_orders")
                                            .delete().eq("id", rid).execute(),
                                        error_prefix="Delete error"
                                    )
                                    st.rerun()

                            if status in ["Ordered", "Received"]:
                                ic2.write("✅ Active")

                    # ── GROUP-LEVEL VENDOR & ENQUIRY ──────────
                    with gh2:
                        with st.container(border=True):
                            st.caption(f"Enquiry for **{mat_grp}** group")

                            sel_vendor = st.selectbox(
                                "Select vendor",
                                options=vendor_list,
                                key=f"pc_vsel_{gkey}"
                            )
                            v_info  = vendor_options.get(sel_vendor, {})
                            v_phone = clean_phone(v_info.get('phone_number', ""))
                            v_email = v_info.get('email', "")

                            # Build message for this group's items only
                            item_lines = ""
                            for ii, row in enumerate(grp_items.to_dict('records')):
                                item_lines += (
                                    f"\n{ii+1}. {row['item_name']}"
                                    f" | Qty: {row['quantity']} {row.get('units','Nos')}"
                                    f" | Job: {row['job_no']}"
                                    + (f" | Specs: {row['specs']}" if row.get('specs') else "")
                                )

                            wa_msg = (
                                f"B&G Engineering — {mat_grp} Enquiry\n"
                                f"Indent Ref: #{indent_no}\n"
                                f"Date: {date.today().strftime('%d-%m-%Y')}\n"
                                f"{'='*28}\n"
                                f"{item_lines}\n"
                                f"{'='*28}\n"
                                f"Please share your best quote.\nRegards, B&G Engineering"
                            )
                            wa_base = f"https://wa.me/{v_phone}" if v_phone else "https://wa.me/"
                            wa_url  = f"{wa_base}?text={urllib.parse.quote(wa_msg)}"
                            st.markdown(
                                f'<a href="{wa_url}" target="_blank" style="text-decoration:none;">'
                                f'<div style="background:#25D366; color:white; padding:7px; '
                                f'border-radius:5px; text-align:center; font-weight:bold; '
                                f'margin-bottom:5px;">📲 WhatsApp — {mat_grp}</div></a>',
                                unsafe_allow_html=True
                            )

                            mail_subj = urllib.parse.quote(
                                f"{mat_grp} Enquiry — Indent #{indent_no} | B&G Engineering"
                            )
                            mail_body_str = (
                                f"Dear Sir/Madam,\n\n"
                                f"Please find our {mat_grp} material enquiry "
                                f"(Indent #{indent_no}):\n"
                                f"{item_lines}\n\n"
                                f"Kindly share your best quote at the earliest.\n\n"
                                f"Regards,\nB&G Engineering"
                            )
                            mail_url = (
                                f"mailto:{v_email}"
                                f"?subject={mail_subj}"
                                f"&body={urllib.parse.quote(mail_body_str)}"
                            )
                            st.markdown(
                                f'<a href="{mail_url}" style="text-decoration:none;">'
                                f'<div style="background:#007bff; color:white; padding:7px; '
                                f'border-radius:5px; text-align:center; font-weight:bold; '
                                f'margin-bottom:5px;">📧 Email — {mat_grp}</div></a>',
                                unsafe_allow_html=True
                            )

                            # XLS export for this group
                            item_rows_html = "".join([
                                f"<tr><td>{ii+1}</td><td><b>{r['item_name']}</b></td>"
                                f"<td>{r.get('specs','-')}</td>"
                                f"<td><b>{r['quantity']} {r.get('units','Nos')}</b></td>"
                                f"<td>{r['job_no']}</td></tr>"
                                for ii, r in enumerate(grp_items.to_dict('records'))
                            ])
                            html_form = f"""<html><body>
                            <table border="1" cellpadding="5" cellspacing="0">
                            <tr><td colspan="5" style="font-size:16pt;font-weight:bold;
                                color:#003366;">B&G ENGINEERING</td></tr>
                            <tr><td colspan="2">Indent Ref:</td>
                                <td colspan="3"><b>#{indent_no}</b></td></tr>
                            <tr><td colspan="2">Material Group:</td>
                                <td colspan="3"><b>{mat_grp}</b></td></tr>
                            <tr><td colspan="2">Date:</td>
                                <td colspan="3">{date.today().strftime('%d-%m-%Y')}</td></tr>
                            <tr style="background:#003366;color:white;">
                                <td>#</td><td>Item</td><td>Specifications</td>
                                <td>Qty</td><td>Job No</td></tr>
                            {item_rows_html}
                            </table></body></html>"""
                            st.download_button(
                                label=f"📄 Export {mat_grp} (XLS)",
                                data=html_form,
                                file_name=f"BG_Indent{indent_no}_{mat_grp}.xls",
                                mime='application/vnd.ms-excel',
                                key=f"pc_dl_{gkey}",
                                use_container_width=True
                            )

                            # ── GROUP-LEVEL ORDER / REJECT ────
                            with st.expander("✅ Confirm PO for this group"):
                                p_no  = st.text_input("PO No", key=f"pc_po_{gkey}")
                                p_rem = st.text_input(
                                    "Vendor / Remarks",
                                    value=sel_vendor if sel_vendor != "--- Choose Vendor ---" else "",
                                    key=f"pc_rem_{gkey}"
                                )
                                if st.button("Confirm Order", key=f"pc_ok_{gkey}",
                                             type="primary", use_container_width=True):
                                    grp_ids = grp_items['id'].tolist()
                                    errors  = []
                                    for rid in grp_ids:
                                        try:
                                            conn.table("purchase_orders").update({
                                                "status": "Ordered",
                                                "po_no": p_no,
                                                "purchase_reply": p_rem
                                            }).eq("id", rid).execute()
                                        except Exception as e:
                                            errors.append(str(e))
                                    if errors:
                                        st.error(f"Errors: {'; '.join(errors)}")
                                    else:
                                        st.success(f"✅ {mat_grp} items ordered!")
                                        st.cache_data.clear()
                                        st.rerun()

                            with st.expander("🚫 Reject this group"):
                                rej_r = st.text_area(
                                    "Rejection reason", key=f"pc_rejr_{gkey}"
                                )
                                if st.button("Confirm Rejection",
                                             key=f"pc_rejb_{gkey}",
                                             type="secondary",
                                             use_container_width=True):
                                    if rej_r:
                                        grp_ids = grp_items['id'].tolist()
                                        errors  = []
                                        for rid in grp_ids:
                                            try:
                                                conn.table("purchase_orders").update({
                                                    "status": "Rejected",
                                                    "reject_note": rej_r
                                                }).eq("id", rid).execute()
                                            except Exception as e:
                                                errors.append(str(e))
                                        if errors:
                                            st.error(f"Errors: {'; '.join(errors)}")
                                        else:
                                            st.rerun()
                                    else:
                                        st.warning("Please provide a reason.")

                    # Separator between material groups within same indent
                    if grp_idx < len(mat_groups) - 1:
                        st.markdown("---")

    else:
        st.info("No pending purchase requests found (last 90 days).")

# ============================================================
# TAB 2: STORES GRN  (Partial Receipt Support)
# ============================================================
# SUPABASE TABLE REQUIRED: grn_receipts
#   id            uuid PK default gen_random_uuid()
#   po_id         bigint  references purchase_orders(id)
#   received_qty  numeric not null
#   dc_no         text
#   remarks       text
#   received_date date    default current_date
#   created_at    timestamptz default now()
# ============================================================
with main_tabs[2]:
    st.subheader("📦 Goods Receipt Note (GRN) Desk")

    po_search = st.text_input(
        "🔍 Search by PO or Item", placeholder="e.g. PO-107", key="grn_search"
    )

    # Fetch all Ordered items (not yet fully received)
    try:
        res_s = conn.table("purchase_orders").select("*") \
            .in_("status", ["Ordered", "Partial"]) \
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

        # Fetch all past receipts for these PO IDs in one query
        po_ids = df_s['id'].tolist()
        try:
            grn_res = conn.table("grn_receipts").select("*") \
                .in_("po_id", po_ids).execute()
            grn_data = grn_res.data or []
        except Exception:
            grn_data = []

        # Build a lookup: po_id -> list of receipt dicts
        from collections import defaultdict
        receipts_by_po = defaultdict(list)
        for r in grn_data:
            receipts_by_po[r['po_id']].append(r)

        partial_count = sum(1 for r in stores_data if r.get('status') == 'Partial')
        ordered_count = sum(1 for r in stores_data if r.get('status') == 'Ordered')
        st.markdown(
            f"**Pending Arrivals: {len(df_s)}** &nbsp;|&nbsp; "
            f"🆕 New: {ordered_count} &nbsp;|&nbsp; "
            f"🔄 Partial: {partial_count}"
        )

        for s_idx, s_row in enumerate(df_s.to_dict('records')):
            row_id      = s_row['id']
            ordered_qty = float(s_row.get('quantity', 0))
            units       = s_row.get('units', 'Nos')
            past        = receipts_by_po.get(row_id, [])
            recd_so_far = sum(float(r.get('received_qty', 0)) for r in past)
            balance_qty = max(0, ordered_qty - recd_so_far)
            pct_done    = min(100, int((recd_so_far / ordered_qty * 100) if ordered_qty else 0))
            skey        = f"grn_{row_id}"
            is_partial  = s_row.get('status') == 'Partial'

            with st.container(border=True):
                c_info, c_status, c_action = st.columns([2.5, 1.2, 1.8])

                # ── INFO ──────────────────────────────────────
                with c_info:
                    st.markdown(
                        f"#### PO: {s_row.get('po_no','N/A')} "
                        f"{'🔄' if is_partial else '🆕'}"
                    )
                    st.markdown(f"**{s_row['item_name']}** | Job: `{s_row['job_no']}`")
                    st.caption(
                        f"Indent: #{s_row.get('indent_no')} "
                        f"| Vendor: {s_row.get('purchase_reply','-')} "
                        f"| Group: {s_row.get('material_group','-')}"
                    )

                    # Show receipt history if any partial receipts exist
                    if past:
                        with st.expander(
                            f"📋 Receipt history ({len(past)} delivery/ies — "
                            f"{recd_so_far:.1f} of {ordered_qty:.1f} {units} received)"
                        ):
                            for pr in sorted(past, key=lambda x: x.get('received_date','')):
                                st.markdown(
                                    f"- **{pr.get('received_date','?')}** — "
                                    f"`{pr.get('received_qty',0)} {units}` | "
                                    f"DC: {pr.get('dc_no','-')} | "
                                    f"{pr.get('remarks','-')}"
                                )

                # ── STATUS ────────────────────────────────────
                with c_status:
                    if is_partial:
                        st.warning("🔄 Partial")
                    else:
                        st.info("🚚 In-Transit")

                    st.caption(f"Ordered: {ordered_qty:.1f} {units}")
                    if recd_so_far > 0:
                        st.caption(f"Received: {recd_so_far:.1f} {units}")
                        st.caption(f"Balance: **{balance_qty:.1f} {units}**")
                    st.progress(pct_done / 100)
                    st.caption(f"{pct_done}% fulfilled")

                # ── GRN ACTION ────────────────────────────────
                with c_action:
                    st.markdown("**Record Receipt**")

                    recv_qty = st.number_input(
                        f"Qty received ({units})",
                        min_value=0.1,
                        max_value=float(balance_qty) if balance_qty > 0 else 0.1,
                        value=min(float(balance_qty), float(balance_qty)) if balance_qty > 0 else 0.1,
                        step=0.1,
                        key=f"rqty_{skey}"
                    )
                    dc_no = st.text_input(
                        "DC / Vehicle No", key=f"dc_{skey}", placeholder="DC-123"
                    )
                    s_rem = st.text_input(
                        "Remarks", key=f"srem_{skey}",
                        placeholder="Shortage/Damage/OK?"
                    )

                    is_full_receipt = abs(recv_qty - balance_qty) < 0.01

                    btn_label = (
                        "✅ Full Receipt — Close PO"
                        if is_full_receipt
                        else f"📦 Partial Receipt ({recv_qty} {units})"
                    )

                    if st.button(btn_label, key=f"btn_{skey}",
                                 use_container_width=True, type="primary"):
                        if not dc_no:
                            st.warning("Please enter DC / Vehicle No")
                        elif recv_qty <= 0:
                            st.warning("Quantity must be greater than 0")
                        else:
                            # 1. Insert into grn_receipts
                            grn_ok = safe_db_write(
                                lambda: conn.table("grn_receipts").insert({
                                    "po_id":        row_id,
                                    "received_qty": recv_qty,
                                    "dc_no":        dc_no,
                                    "remarks":      s_rem,
                                    "received_date": str(date.today())
                                }).execute(),
                                error_prefix="GRN Insert Error"
                            )

                            if grn_ok:
                                # 2. Update purchase_orders status
                                new_status = "Received" if is_full_receipt else "Partial"
                                update_payload = {"status": new_status}
                                if is_full_receipt:
                                    update_payload["received_date"] = str(date.today())
                                    update_payload["stores_remarks"] = (
                                        f"DC: {dc_no} | {s_rem} | "
                                        f"Full qty {ordered_qty} {units} received"
                                    )

                                safe_db_write(
                                    lambda st=new_status, pl=update_payload:
                                        conn.table("purchase_orders")
                                            .update(pl).eq("id", row_id).execute(),
                                    success_msg=(
                                        f"✅ PO closed — full qty received!"
                                        if is_full_receipt
                                        else f"📦 Partial GRN recorded. "
                                             f"Balance: {balance_qty - recv_qty:.1f} {units}"
                                    ),
                                    error_prefix="Status Update Error"
                                )
                                st.rerun()
    else:
        st.info("🚚 No pending arrivals (last 90 days).")

    # ── AUDIT TRAIL ───────────────────────────────────────────
    st.divider()
    with st.expander("🕒 GRN Audit Trail — All Receipts"):
        try:
            recent_res = conn.table("grn_receipts").select(
                "*, purchase_orders(po_no, item_name, job_no, quantity, units)"
            ).order("received_date", desc=True).limit(20).execute()

            if recent_res.data:
                rows = []
                for r in recent_res.data:
                    po = r.get('purchase_orders') or {}
                    rows.append({
                        "Date":       r.get('received_date', ''),
                        "PO No":      po.get('po_no', '-'),
                        "Item":       po.get('item_name', '-'),
                        "Job":        po.get('job_no', '-'),
                        "Recd Qty":   r.get('received_qty', 0),
                        "Units":      po.get('units', '-'),
                        "DC No":      r.get('dc_no', '-'),
                        "Remarks":    r.get('remarks', '-'),
                    })
                st.dataframe(
                    pd.DataFrame(rows),
                    use_container_width=True, hide_index=True
                )
            else:
                # Fallback: show from purchase_orders if grn_receipts is empty
                fallback = conn.table("purchase_orders").select("*") \
                    .eq("status", "Received") \
                    .not_.is_("indent_no", "null") \
                    .order("received_date", desc=True).limit(10).execute()
                if fallback.data:
                    df_fb = pd.DataFrame(fallback.data)
                    cols  = [c for c in [
                        'received_date', 'po_no', 'item_name',
                        'quantity', 'job_no', 'stores_remarks'
                    ] if c in df_fb.columns]
                    st.dataframe(df_fb[cols], use_container_width=True, hide_index=True)
                else:
                    st.info("No receipts recorded yet.")
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
