"""
13_🌾_Farm_Manager.py

Farm Manager module for BG Engg ERP.
- Tab 1: Petty Cash (receipts/payments + custom heads)
- Tab 2: Daily Work Log (per-farm entries with photos)
- Tab 3: Assets Register (lands, barns, vehicles, sheds with documents)

Password-gated. Tables are prefixed `farm_` to coexist with the rest of the ERP schema.
"""

import uuid
import io
from pathlib import Path
from datetime import date, timedelta

import streamlit as st
import pandas as pd
from supabase import create_client, Client


# ─────────────────────────────────────────────────────────────
# CONFIG — change the password here
# ─────────────────────────────────────────────────────────────
FARM_MANAGER_PASSWORD = "farm@2026"   # ← change this to whatever you want


# ─────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Farm Manager", page_icon="🌾", layout="wide")


# ─────────────────────────────────────────────────────────────
# PASSWORD GATE
# ─────────────────────────────────────────────────────────────
def check_password() -> bool:
    """Returns True only if the user has entered the correct password this session."""
    if st.session_state.get("farm_authed"):
        return True

    st.title("🌾 Farm Manager")
    st.caption("Restricted module — please enter the password to continue.")

    with st.form("farm_login", clear_on_submit=False):
        pwd = st.text_input("Password", type="password")
        ok = st.form_submit_button("Unlock", type="primary")

    if ok:
        if pwd == FARM_MANAGER_PASSWORD:
            st.session_state["farm_authed"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


if not check_password():
    st.stop()


# ─────────────────────────────────────────────────────────────
# SUPABASE CLIENT
# ─────────────────────────────────────────────────────────────
@st.cache_resource
def get_client() -> Client:
    """Reuses your existing ERP Supabase credentials."""
    url = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
    key = st.secrets["connections"]["supabase"]["SUPABASE_KEY"]
    return create_client(url, key)


client = get_client()


# ─────────────────────────────────────────────────────────────
# STORAGE HELPERS
# ─────────────────────────────────────────────────────────────
def upload_file(uploaded_file, bucket: str, folder: str = "") -> str:
    """Upload a single Streamlit UploadedFile to Supabase Storage; return public URL."""
    ext = Path(uploaded_file.name).suffix
    filename = f"{folder}/{uuid.uuid4().hex}{ext}".lstrip("/")
    file_bytes = uploaded_file.getvalue()
    client.storage.from_(bucket).upload(
        path=filename,
        file=file_bytes,
        file_options={"content-type": uploaded_file.type or "application/octet-stream"},
    )
    return client.storage.from_(bucket).get_public_url(filename)


def upload_many(files, bucket: str, folder: str = "") -> list[str]:
    return [upload_file(f, bucket, folder) for f in files] if files else []


# ─────────────────────────────────────────────────────────────
# CONFIRM-DELETE HELPER
# ─────────────────────────────────────────────────────────────
def confirm_delete_ui(record_key: str, label: str) -> bool:
    """
    Two-step delete confirmation. Returns True if user has confirmed delete.

    Usage:
        if confirm_delete_ui(f"txn_{t['id']}", f"transaction #{t['id']}"):
            client.table(...).delete().eq("id", t["id"]).execute()
            st.rerun()
    """
    pending_key = f"_confirm_del_{record_key}"

    if not st.session_state.get(pending_key):
        if st.button("🗑️ Delete", key=f"btn_del_{record_key}", type="secondary"):
            st.session_state[pending_key] = True
            st.rerun()
        return False

    # Confirmation stage
    st.warning(f"⚠️ Are you sure you want to delete {label}? This cannot be undone.")
    c1, c2 = st.columns(2)
    if c1.button("✅ Yes, delete", key=f"btn_yes_{record_key}", type="primary"):
        st.session_state.pop(pending_key, None)
        return True
    if c2.button("Cancel", key=f"btn_no_{record_key}"):
        st.session_state.pop(pending_key, None)
        st.rerun()
    return False


# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────
header_l, header_r = st.columns([4, 1])
with header_l:
    st.title("🌾 Farm Manager")
    st.caption("Petty cash · Daily work · Assets · Vehicles · Reports")
with header_r:
    st.write("")
    st.write("")
    if st.button("🔒 Lock", use_container_width=True):
        st.session_state.pop("farm_authed", None)
        st.rerun()

tab_cash, tab_work, tab_assets, tab_vehicles, tab_reports = st.tabs([
    "💰 Petty Cash",
    "🌾 Daily Work",
    "🏞️ Assets",
    "🚜 Vehicles",
    "📊 Reports",
])


# ═════════════════════════════════════════════════════════════
# TAB 1 · PETTY CASH
# ═════════════════════════════════════════════════════════════
with tab_cash:
    sub_entry, sub_heads, sub_ledger = st.tabs(["➕ New Entry", "🏷️ Manage Heads", "📒 Ledger"])

    # --- New Entry ---
    with sub_entry:
        heads = client.table("farm_heads").select("*").order("name").execute().data
        if not heads:
            st.warning("No heads yet. Add one in 'Manage Heads' first.")
        else:
            # Type radio OUTSIDE the form so changing it triggers a rerun
            # and the Head dropdown filters correctly.
            txn_type = st.radio(
                "Type", ["receipt", "payment"], horizontal=True, key="txn_type_radio"
            )
            filtered = [h for h in heads if h["type"] == txn_type]

            with st.form("txn_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    txn_date = st.date_input("Date", value=date.today())
                    amount = st.number_input("Amount (₹)", min_value=0.01, step=100.0, format="%.2f")
                with c2:
                    if not filtered:
                        st.warning(f"No '{txn_type}' heads. Create one in Manage Heads.")
                        head_id = None
                    else:
                        head_choice = st.selectbox(
                            "Head",
                            options=filtered,
                            format_func=lambda h: h["name"],
                        )
                        head_id = head_choice["id"]

                remarks = st.text_area("Remarks", placeholder="Optional notes...")
                if st.form_submit_button("Save", type="primary", use_container_width=True) and head_id:
                    client.table("farm_transactions").insert({
                        "txn_date": str(txn_date),
                        "head_id": head_id,
                        "type": txn_type,
                        "amount": amount,
                        "remarks": remarks or None,
                    }).execute()
                    st.success(f"✅ {txn_type.title()} of ₹{amount:,.2f} saved.")
                    st.rerun()

    # --- Manage Heads ---
    with sub_heads:
        with st.form("head_form", clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 1, 1])
            new_name = c1.text_input("Head name", placeholder="e.g. Diesel, Wages, Mango Sales")
            new_type = c2.selectbox("Type", ["payment", "receipt"])
            c3.markdown("&nbsp;")
            if c3.form_submit_button("Add", use_container_width=True) and new_name.strip():
                try:
                    client.table("farm_heads").insert({
                        "name": new_name.strip(),
                        "type": new_type,
                    }).execute()
                    st.success(f"Added: {new_name}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        heads = client.table("farm_heads").select("*").order("type").order("name").execute().data
        if heads:
            st.markdown("#### Existing Heads")
            for h in heads:
                with st.expander(f"🏷️ {h['name']} ({h['type']})"):
                    edit_key = f"edit_head_{h['id']}"
                    if st.session_state.get(edit_key):
                        # Edit mode
                        with st.form(f"edit_head_form_{h['id']}", clear_on_submit=False):
                            new_name = st.text_input("Name", value=h["name"])
                            new_type = st.selectbox(
                                "Type", ["payment", "receipt"],
                                index=0 if h["type"] == "payment" else 1,
                            )
                            c1, c2 = st.columns(2)
                            if c1.form_submit_button("💾 Save", type="primary", use_container_width=True):
                                try:
                                    client.table("farm_heads").update({
                                        "name": new_name.strip(),
                                        "type": new_type,
                                    }).eq("id", h["id"]).execute()
                                    st.session_state.pop(edit_key, None)
                                    st.success("Updated.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                            if c2.form_submit_button("Cancel", use_container_width=True):
                                st.session_state.pop(edit_key, None)
                                st.rerun()
                    else:
                        c1, c2 = st.columns(2)
                        if c1.button("✏️ Edit", key=f"btn_edit_head_{h['id']}", use_container_width=True):
                            st.session_state[edit_key] = True
                            st.rerun()
                        with c2:
                            if confirm_delete_ui(f"head_{h['id']}", f"head '{h['name']}'"):
                                try:
                                    client.table("farm_heads").delete().eq("id", h["id"]).execute()
                                    st.success("Deleted.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Cannot delete (in use by transactions?): {e}")

    # --- Ledger ---
    with sub_ledger:
        txns = (
            client.table("farm_transactions")
            .select("*, farm_heads(name)")
            .order("txn_date", desc=True)
            .execute()
            .data
        )
        if not txns:
            st.info("No transactions yet.")
        else:
            # Summary metrics
            receipts_total = sum(t["amount"] for t in txns if t["type"] == "receipt")
            payments_total = sum(t["amount"] for t in txns if t["type"] == "payment")
            c1, c2, c3 = st.columns(3)
            c1.metric("Receipts", f"₹{receipts_total:,.0f}")
            c2.metric("Payments", f"₹{payments_total:,.0f}")
            c3.metric("Balance", f"₹{receipts_total - payments_total:,.0f}")

            # CSV download (from full ledger as flat table)
            df = pd.DataFrame([{
                "ID": t["id"],
                "Date": t["txn_date"],
                "Type": t["type"],
                "Head": (t.get("farm_heads") or {}).get("name", "—"),
                "Amount": t["amount"],
                "Remarks": t.get("remarks") or "",
            } for t in txns])
            st.download_button(
                "⬇️ Download CSV",
                df.to_csv(index=False).encode("utf-8"),
                "farm_ledger.csv",
                "text/csv",
            )

            st.markdown("#### Transactions (click to expand and edit)")
            all_heads = client.table("farm_heads").select("*").order("name").execute().data

            for t in txns:
                head_name = (t.get("farm_heads") or {}).get("name", "—")
                icon = "📈" if t["type"] == "receipt" else "📉"
                sign = "+" if t["type"] == "receipt" else "-"
                with st.expander(
                    f"{icon} {t['txn_date']} — {head_name} — {sign}₹{t['amount']:,.2f}"
                ):
                    edit_key = f"edit_txn_{t['id']}"
                    if st.session_state.get(edit_key):
                        # Edit mode — Type radio outside form so head dropdown filters live
                        cur_type = st.session_state.get(
                            f"_txn_type_edit_{t['id']}", t["type"]
                        )
                        new_type = st.radio(
                            "Type", ["receipt", "payment"],
                            index=0 if cur_type == "receipt" else 1,
                            horizontal=True,
                            key=f"_txn_type_edit_{t['id']}",
                        )
                        filtered_heads = [h for h in all_heads if h["type"] == new_type]

                        with st.form(f"edit_txn_form_{t['id']}", clear_on_submit=False):
                            c1, c2 = st.columns(2)
                            with c1:
                                new_date = st.date_input(
                                    "Date",
                                    value=pd.to_datetime(t["txn_date"]).date(),
                                )
                                new_amount = st.number_input(
                                    "Amount (₹)",
                                    min_value=0.01,
                                    value=float(t["amount"]),
                                    step=100.0, format="%.2f",
                                )
                            with c2:
                                if not filtered_heads:
                                    st.warning(f"No '{new_type}' heads exist.")
                                    new_head_id = None
                                else:
                                    # Find current head index in the filtered list
                                    cur_head_id = t.get("head_id")
                                    head_ids = [h["id"] for h in filtered_heads]
                                    idx = head_ids.index(cur_head_id) if cur_head_id in head_ids else 0
                                    new_head = st.selectbox(
                                        "Head",
                                        options=filtered_heads,
                                        format_func=lambda h: h["name"],
                                        index=idx,
                                    )
                                    new_head_id = new_head["id"]
                            new_remarks = st.text_area(
                                "Remarks", value=t.get("remarks") or ""
                            )
                            c1, c2 = st.columns(2)
                            if c1.form_submit_button(
                                "💾 Save", type="primary", use_container_width=True
                            ):
                                if not new_head_id:
                                    st.error("Select a head.")
                                else:
                                    client.table("farm_transactions").update({
                                        "txn_date": str(new_date),
                                        "head_id": new_head_id,
                                        "type": new_type,
                                        "amount": float(new_amount),
                                        "remarks": new_remarks or None,
                                    }).eq("id", t["id"]).execute()
                                    st.session_state.pop(edit_key, None)
                                    st.session_state.pop(f"_txn_type_edit_{t['id']}", None)
                                    st.success("Updated.")
                                    st.rerun()
                            if c2.form_submit_button("Cancel", use_container_width=True):
                                st.session_state.pop(edit_key, None)
                                st.session_state.pop(f"_txn_type_edit_{t['id']}", None)
                                st.rerun()
                    else:
                        # View + buttons
                        if t.get("remarks"):
                            st.write(f"**Remarks:** {t['remarks']}")
                        c1, c2 = st.columns(2)
                        if c1.button("✏️ Edit", key=f"btn_edit_txn_{t['id']}", use_container_width=True):
                            st.session_state[edit_key] = True
                            st.rerun()
                        with c2:
                            if confirm_delete_ui(
                                f"txn_{t['id']}",
                                f"this {t['type']} of ₹{t['amount']:,.2f}"
                            ):
                                client.table("farm_transactions").delete().eq(
                                    "id", t["id"]
                                ).execute()
                                st.success("Deleted.")
                                st.rerun()


# ═════════════════════════════════════════════════════════════
# TAB 2 · DAILY WORK LOG
# ═════════════════════════════════════════════════════════════
with tab_work:
    sub_w_entry, sub_w_farms, sub_w_hist = st.tabs(["➕ New Entry", "🏞️ Manage Farms", "📅 History"])

    # --- New Entry ---
    with sub_w_entry:
        farms = client.table("farm_farms").select("*").order("name").execute().data
        if not farms:
            st.warning("No farms registered. Add one in 'Manage Farms' first.")
        else:
            with st.form("work_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    work_date = st.date_input("Work date", value=date.today(), key="w_date")
                    farm = st.selectbox("Farm", options=farms, format_func=lambda f: f["name"])
                with c2:
                    workers = st.number_input("Workers count", min_value=0, step=1)
                    cost = st.number_input("Cost (₹)", min_value=0.0, step=100.0, format="%.2f")

                description = st.text_area(
                    "Work description",
                    placeholder="e.g. Pruning mango trees, sprayed pesticide...",
                    height=100,
                )
                photos = st.file_uploader(
                    "Upload photos (multiple allowed)",
                    type=["jpg", "jpeg", "png"],
                    accept_multiple_files=True,
                )

                if st.form_submit_button("Save Entry", type="primary", use_container_width=True):
                    if not description.strip():
                        st.error("Description is required.")
                    else:
                        with st.spinner("Saving..."):
                            photo_urls = upload_many(photos, "farm-photos", folder=str(work_date))
                            client.table("farm_work_entries").insert({
                                "work_date": str(work_date),
                                "farm_id": farm["id"],
                                "description": description.strip(),
                                "workers_count": int(workers) if workers else None,
                                "cost": float(cost) if cost else None,
                                "photo_urls": photo_urls,
                            }).execute()
                        st.success(f"✅ Saved with {len(photo_urls)} photo(s).")
                        st.rerun()

    # --- Manage Farms ---
    with sub_w_farms:
        with st.form("farm_form", clear_on_submit=True):
            c1, c2 = st.columns([3, 1])
            new_farm = c1.text_input("Farm short name", placeholder="e.g. North Mango, East Tobacco")
            c2.markdown("&nbsp;")
            if c2.form_submit_button("Add", use_container_width=True) and new_farm.strip():
                try:
                    client.table("farm_farms").insert({"name": new_farm.strip()}).execute()
                    st.success(f"Added: {new_farm}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        farms = client.table("farm_farms").select("*").order("name").execute().data
        if farms:
            st.markdown("#### Existing Farms")
            for f in farms:
                with st.expander(f"🏞️ {f['name']}"):
                    edit_key = f"edit_farm_{f['id']}"
                    if st.session_state.get(edit_key):
                        with st.form(f"edit_farm_form_{f['id']}", clear_on_submit=False):
                            new_name = st.text_input("Name", value=f["name"])
                            c1, c2 = st.columns(2)
                            if c1.form_submit_button("💾 Save", type="primary", use_container_width=True):
                                try:
                                    client.table("farm_farms").update(
                                        {"name": new_name.strip()}
                                    ).eq("id", f["id"]).execute()
                                    st.session_state.pop(edit_key, None)
                                    st.success("Updated.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                            if c2.form_submit_button("Cancel", use_container_width=True):
                                st.session_state.pop(edit_key, None)
                                st.rerun()
                    else:
                        c1, c2 = st.columns(2)
                        if c1.button("✏️ Edit", key=f"btn_edit_farm_{f['id']}", use_container_width=True):
                            st.session_state[edit_key] = True
                            st.rerun()
                        with c2:
                            if confirm_delete_ui(f"farm_{f['id']}", f"farm '{f['name']}'"):
                                try:
                                    client.table("farm_farms").delete().eq("id", f["id"]).execute()
                                    st.success("Deleted.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Cannot delete (has work entries?): {e}")

    # --- History ---
    with sub_w_hist:
        farms = client.table("farm_farms").select("*").order("name").execute().data
        farm_filter = st.selectbox(
            "Filter by farm",
            options=[None] + farms,
            format_func=lambda f: "All farms" if f is None else f["name"],
        )

        q = client.table("farm_work_entries").select("*, farm_farms(name)").order("work_date", desc=True)
        if farm_filter:
            q = q.eq("farm_id", farm_filter["id"])
        entries = q.limit(100).execute().data

        if not entries:
            st.info("No entries yet.")
        else:
            for e in entries:
                farm_name = (e.get("farm_farms") or {}).get("name", "—")
                with st.expander(f"📅 {e['work_date']} — {farm_name}"):
                    edit_key = f"edit_work_{e['id']}"
                    if st.session_state.get(edit_key):
                        # Edit mode
                        with st.form(f"edit_work_form_{e['id']}", clear_on_submit=False):
                            c1, c2 = st.columns(2)
                            with c1:
                                new_date = st.date_input(
                                    "Date",
                                    value=pd.to_datetime(e["work_date"]).date(),
                                )
                                farm_ids = [fm["id"] for fm in farms]
                                idx = farm_ids.index(e["farm_id"]) if e["farm_id"] in farm_ids else 0
                                new_farm = st.selectbox(
                                    "Farm", options=farms,
                                    format_func=lambda fm: fm["name"],
                                    index=idx,
                                )
                            with c2:
                                new_workers = st.number_input(
                                    "Workers", min_value=0, step=1,
                                    value=int(e.get("workers_count") or 0),
                                )
                                new_cost = st.number_input(
                                    "Cost (₹)", min_value=0.0, step=100.0, format="%.2f",
                                    value=float(e.get("cost") or 0),
                                )
                            new_desc = st.text_area(
                                "Description",
                                value=e["description"],
                                height=100,
                            )
                            st.caption("Note: existing photos are kept. To replace photos, delete and re-create the entry.")
                            c1, c2 = st.columns(2)
                            if c1.form_submit_button("💾 Save", type="primary", use_container_width=True):
                                client.table("farm_work_entries").update({
                                    "work_date": str(new_date),
                                    "farm_id": new_farm["id"],
                                    "description": new_desc.strip(),
                                    "workers_count": int(new_workers) if new_workers else None,
                                    "cost": float(new_cost) if new_cost else None,
                                }).eq("id", e["id"]).execute()
                                st.session_state.pop(edit_key, None)
                                st.success("Updated.")
                                st.rerun()
                            if c2.form_submit_button("Cancel", use_container_width=True):
                                st.session_state.pop(edit_key, None)
                                st.rerun()
                    else:
                        # View mode
                        st.write(f"**Description:** {e['description']}")
                        c1, c2 = st.columns(2)
                        c1.metric("Workers", e.get("workers_count") or 0)
                        c2.metric("Cost", f"₹{e.get('cost') or 0:,.2f}")
                        urls = e.get("photo_urls") or []
                        if urls:
                            st.write(f"**Photos ({len(urls)}):**")
                            cols = st.columns(min(len(urls), 4))
                            for i, url in enumerate(urls):
                                cols[i % 4].image(url, use_container_width=True)

                        st.divider()
                        c1, c2 = st.columns(2)
                        if c1.button("✏️ Edit", key=f"btn_edit_work_{e['id']}", use_container_width=True):
                            st.session_state[edit_key] = True
                            st.rerun()
                        with c2:
                            if confirm_delete_ui(
                                f"work_{e['id']}",
                                f"work entry on {e['work_date']} for {farm_name}"
                            ):
                                client.table("farm_work_entries").delete().eq(
                                    "id", e["id"]
                                ).execute()
                                st.success("Deleted.")
                                st.rerun()


# ═════════════════════════════════════════════════════════════
# TAB 3 · ASSETS REGISTER
# ═════════════════════════════════════════════════════════════
with tab_assets:
    sub_a_add, sub_a_list = st.tabs(["➕ Add Asset", "📋 All Assets"])

    # --- Add Asset ---
    with sub_a_add:
        with st.form("asset_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                short_name = st.text_input("Short name *", placeholder="e.g. North Mango Farm")
                survey_no = st.text_input("Survey No.")
                passbook = st.text_input("Passbook details")
            with c2:
                area = st.number_input("Area", min_value=0.0, step=0.1, format="%.2f")
                area_unit = st.selectbox("Unit", ["acres", "sq.ft", "sq.m", "hectares", "guntas"])

            notes = st.text_area("Short notes", placeholder="Anything worth remembering...")
            docs = st.file_uploader(
                "Upload documents (passbook scans, deeds, photos)",
                type=["pdf", "jpg", "jpeg", "png"],
                accept_multiple_files=True,
            )

            if st.form_submit_button("Save Asset", type="primary", use_container_width=True):
                if not short_name.strip():
                    st.error("Short name is required.")
                else:
                    with st.spinner("Saving..."):
                        doc_urls = upload_many(docs, "farm-asset-docs", folder=short_name.strip())
                        client.table("farm_assets").insert({
                            "short_name": short_name.strip(),
                            "survey_no": survey_no or None,
                            "passbook_details": passbook or None,
                            "area": area or None,
                            "area_unit": area_unit,
                            "notes": notes or None,
                            "document_urls": doc_urls,
                        }).execute()
                    st.success(f"✅ Asset '{short_name}' saved with {len(doc_urls)} document(s).")
                    st.rerun()

    # --- List Assets ---
    with sub_a_list:
        search = st.text_input("🔍 Search by name", placeholder="Type to filter...")

        q = client.table("farm_assets").select("*").order("short_name")
        if search.strip():
            q = q.ilike("short_name", f"%{search.strip()}%")
        assets = q.execute().data

        if not assets:
            st.info("No assets found." if search else "No assets registered yet.")
        else:
            st.write(f"**{len(assets)} asset(s) found**")
            for a in assets:
                with st.expander(f"🏷️ {a['short_name']}"):
                    edit_key = f"edit_asset_{a['id']}"
                    if st.session_state.get(edit_key):
                        # Edit mode
                        with st.form(f"edit_asset_form_{a['id']}", clear_on_submit=False):
                            c1, c2 = st.columns(2)
                            with c1:
                                new_name = st.text_input("Short name *", value=a["short_name"])
                                new_survey = st.text_input(
                                    "Survey No.", value=a.get("survey_no") or ""
                                )
                                new_passbook = st.text_input(
                                    "Passbook details", value=a.get("passbook_details") or ""
                                )
                            with c2:
                                new_area = st.number_input(
                                    "Area", min_value=0.0, step=0.1, format="%.2f",
                                    value=float(a.get("area") or 0),
                                )
                                units = ["acres", "sq.ft", "sq.m", "hectares", "guntas"]
                                cur_unit = a.get("area_unit") or "acres"
                                idx = units.index(cur_unit) if cur_unit in units else 0
                                new_unit = st.selectbox("Unit", units, index=idx)

                            new_notes = st.text_area("Notes", value=a.get("notes") or "")
                            st.caption("Note: existing documents are kept. To replace documents, delete and re-create the asset.")
                            c1, c2 = st.columns(2)
                            if c1.form_submit_button("💾 Save", type="primary", use_container_width=True):
                                if not new_name.strip():
                                    st.error("Short name is required.")
                                else:
                                    client.table("farm_assets").update({
                                        "short_name": new_name.strip(),
                                        "survey_no": new_survey or None,
                                        "passbook_details": new_passbook or None,
                                        "area": new_area or None,
                                        "area_unit": new_unit,
                                        "notes": new_notes or None,
                                    }).eq("id", a["id"]).execute()
                                    st.session_state.pop(edit_key, None)
                                    st.success("Updated.")
                                    st.rerun()
                            if c2.form_submit_button("Cancel", use_container_width=True):
                                st.session_state.pop(edit_key, None)
                                st.rerun()
                    else:
                        # View mode
                        c1, c2 = st.columns(2)
                        with c1:
                            st.write(f"**Survey No:** {a.get('survey_no') or '—'}")
                            st.write(f"**Passbook:** {a.get('passbook_details') or '—'}")
                        with c2:
                            if a.get("area"):
                                st.write(f"**Area:** {a['area']} {a.get('area_unit') or ''}")
                        if a.get("notes"):
                            st.write(f"**Notes:** {a['notes']}")
                        urls = a.get("document_urls") or []
                        if urls:
                            st.write(f"**Documents ({len(urls)}):**")
                            for i, url in enumerate(urls, 1):
                                st.markdown(f"- [Document {i}]({url})")

                        st.divider()
                        c1, c2 = st.columns(2)
                        if c1.button("✏️ Edit", key=f"btn_edit_asset_{a['id']}", use_container_width=True):
                            st.session_state[edit_key] = True
                            st.rerun()
                        with c2:
                            if confirm_delete_ui(
                                f"asset_{a['id']}", f"asset '{a['short_name']}'"
                            ):
                                client.table("farm_assets").delete().eq("id", a["id"]).execute()
                                st.success("Deleted.")
                                st.rerun()


# ═════════════════════════════════════════════════════════════
# TAB 4 · VEHICLES (Trips · Fuel · Maintenance)
# ═════════════════════════════════════════════════════════════
with tab_vehicles:

    def get_or_create_head(name: str, head_type: str = "payment") -> int:
        """Find or create a petty cash head and return its id."""
        existing = (
            client.table("farm_heads").select("id").eq("name", name).execute().data
        )
        if existing:
            return existing[0]["id"]
        new_row = (
            client.table("farm_heads")
            .insert({"name": name, "type": head_type})
            .execute()
            .data
        )
        return new_row[0]["id"]

    def auto_log_payment(head_name: str, amount: float, txn_date, remarks: str) -> int | None:
        """Create a payment in farm_transactions; returns the transaction id."""
        try:
            head_id = get_or_create_head(head_name, "payment")
            res = (
                client.table("farm_transactions")
                .insert({
                    "txn_date": str(txn_date),
                    "head_id": head_id,
                    "type": "payment",
                    "amount": float(amount),
                    "remarks": remarks,
                })
                .execute()
                .data
            )
            return res[0]["id"] if res else None
        except Exception as e:
            st.warning(f"Saved entry, but could not auto-log to petty cash: {e}")
            return None

    def sync_linked_payment(txn_id: int | None, head_name: str, amount: float,
                             txn_date, remarks: str) -> int | None:
        """
        Keep the auto-linked petty cash row in sync with the vehicle entry.
        If txn_id exists → update it. Otherwise → create a new one and return its id.
        """
        if txn_id:
            try:
                head_id = get_or_create_head(head_name, "payment")
                client.table("farm_transactions").update({
                    "txn_date": str(txn_date),
                    "head_id": head_id,
                    "amount": float(amount),
                    "remarks": remarks,
                }).eq("id", txn_id).execute()
                return txn_id
            except Exception as e:
                st.warning(f"Could not sync linked petty cash row: {e}")
                return txn_id
        else:
            # No prior link — create one
            return auto_log_payment(head_name, amount, txn_date, remarks)

    def delete_linked_payment(txn_id: int | None) -> None:
        """Delete the auto-linked petty cash row if it exists."""
        if txn_id:
            try:
                client.table("farm_transactions").delete().eq("id", txn_id).execute()
            except Exception as e:
                st.warning(f"Could not delete linked petty cash row: {e}")

    def latest_odometer(vehicle_id: int, exclude_trip_id: int | None = None) -> float | None:
        """
        Find the most recent odometer reading for a vehicle, looking at:
        - the highest odometer_end from trips
        - the highest odometer reading from fuel entries
        Returns the max of both, or None if no readings exist.
        Pass exclude_trip_id to skip a specific trip (used when editing it).
        """
        readings = []

        # From trips
        q = (
            client.table("farm_vehicle_trips")
            .select("id, odometer_end")
            .eq("vehicle_id", vehicle_id)
            .not_.is_("odometer_end", "null")
        )
        for row in q.execute().data:
            if exclude_trip_id and row["id"] == exclude_trip_id:
                continue
            if row.get("odometer_end"):
                readings.append(float(row["odometer_end"]))

        # From fuel
        for row in (
            client.table("farm_vehicle_fuel")
            .select("odometer")
            .eq("vehicle_id", vehicle_id)
            .not_.is_("odometer", "null")
            .execute()
            .data
        ):
            if row.get("odometer"):
                readings.append(float(row["odometer"]))

        return max(readings) if readings else None

    sub_v_list, sub_v_trip, sub_v_fuel, sub_v_maint, sub_v_history = st.tabs([
        "🚜 Vehicles",
        "🛣️ Log Trip",
        "⛽ Log Fuel",
        "🔧 Log Maintenance",
        "📒 History",
    ])

    # --- Manage Vehicles ---
    with sub_v_list:
        st.subheader("Vehicles")
        with st.form("vehicle_form", clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 1, 2])
            v_name = c1.text_input("Vehicle name *", placeholder="e.g. Tractor 1, Old Jimney")
            v_type = c2.selectbox("Type", ["Tractor", "Jimney", "Other"])
            v_reg = c3.text_input("Registration No.", placeholder="AP12 AB 1234")
            v_notes = st.text_input("Notes", placeholder="Optional")
            if st.form_submit_button("Add Vehicle", type="primary", use_container_width=True):
                if not v_name.strip():
                    st.error("Name is required.")
                else:
                    try:
                        client.table("farm_vehicles").insert({
                            "name": v_name.strip(),
                            "vehicle_type": v_type,
                            "registration_no": v_reg or None,
                            "notes": v_notes or None,
                        }).execute()
                        st.success(f"Added: {v_name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        vehicles = client.table("farm_vehicles").select("*").order("name").execute().data
        if not vehicles:
            st.info("No vehicles yet. Add one above to start logging trips, fuel, and maintenance.")
        else:
            st.markdown("#### Existing Vehicles")
            for v in vehicles:
                with st.expander(f"🚜 {v['name']} ({v['vehicle_type']})"):
                    edit_key = f"edit_vehicle_{v['id']}"
                    if st.session_state.get(edit_key):
                        with st.form(f"edit_vehicle_form_{v['id']}", clear_on_submit=False):
                            c1, c2 = st.columns(2)
                            with c1:
                                new_name = st.text_input("Name", value=v["name"])
                                types = ["Tractor", "Jimney", "Other"]
                                idx = types.index(v["vehicle_type"]) if v["vehicle_type"] in types else 0
                                new_type = st.selectbox("Type", types, index=idx)
                            with c2:
                                new_reg = st.text_input(
                                    "Registration No.", value=v.get("registration_no") or ""
                                )
                                new_notes = st.text_input(
                                    "Notes", value=v.get("notes") or ""
                                )
                            c1, c2 = st.columns(2)
                            if c1.form_submit_button("💾 Save", type="primary", use_container_width=True):
                                client.table("farm_vehicles").update({
                                    "name": new_name.strip(),
                                    "vehicle_type": new_type,
                                    "registration_no": new_reg or None,
                                    "notes": new_notes or None,
                                }).eq("id", v["id"]).execute()
                                st.session_state.pop(edit_key, None)
                                st.success("Updated.")
                                st.rerun()
                            if c2.form_submit_button("Cancel", use_container_width=True):
                                st.session_state.pop(edit_key, None)
                                st.rerun()
                    else:
                        st.write(f"**Registration:** {v.get('registration_no') or '—'}")
                        if v.get("notes"):
                            st.write(f"**Notes:** {v['notes']}")
                        st.divider()
                        c1, c2 = st.columns(2)
                        if c1.button("✏️ Edit", key=f"btn_edit_v_{v['id']}", use_container_width=True):
                            st.session_state[edit_key] = True
                            st.rerun()
                        with c2:
                            if confirm_delete_ui(
                                f"vehicle_{v['id']}",
                                f"vehicle '{v['name']}' (this will also delete all its trips, fuel, and maintenance records)"
                            ):
                                client.table("farm_vehicles").delete().eq("id", v["id"]).execute()
                                st.success("Deleted.")
                                st.rerun()

    vehicles = client.table("farm_vehicles").select("*").order("name").execute().data

    # --- Log Trip ---
    with sub_v_trip:
        if not vehicles:
            st.warning("Add a vehicle first in the 'Vehicles' tab.")
        else:
            # Vehicle picker OUTSIDE the form so we can auto-fill start odometer
            t_vehicle = st.selectbox(
                "Vehicle", options=vehicles,
                format_func=lambda v: v["name"], key="trip_v",
            )

            # Auto-fill start odometer from the latest known reading
            prev_reading = latest_odometer(t_vehicle["id"])
            if prev_reading is not None:
                st.caption(
                    f"💡 Last known odometer for **{t_vehicle['name']}**: "
                    f"**{prev_reading:,.1f} km** — used as default Start below."
                )
            else:
                st.caption(
                    f"ℹ️ This is the first odometer entry for **{t_vehicle['name']}**. "
                    "Enter both Start and End readings."
                )

            with st.form("trip_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    t_date = st.date_input("Date", value=date.today(), key="trip_date")
                    t_driver = st.text_input("Driver")
                    t_odo_start = st.number_input(
                        "Start odometer (km)",
                        min_value=0.0, step=1.0, format="%.2f",
                        value=float(prev_reading) if prev_reading is not None else 0.0,
                        help="Pre-filled from last trip/fuel entry. Override if needed.",
                    )
                with c2:
                    t_from = st.text_input("From")
                    t_to = st.text_input("To")
                    t_odo_end = st.number_input(
                        "End odometer (km) *",
                        min_value=0.0, step=1.0, format="%.2f",
                    )

                # Live KM preview
                if t_odo_end > 0 and t_odo_end >= t_odo_start:
                    calc_km = t_odo_end - t_odo_start
                    st.success(f"📏 Distance: **{calc_km:,.2f} km** ({t_odo_start:,.1f} → {t_odo_end:,.1f})")
                elif t_odo_end > 0 and t_odo_end < t_odo_start:
                    st.error(
                        f"End odometer ({t_odo_end:,.1f}) is less than Start ({t_odo_start:,.1f}). "
                        "Please check the values."
                    )

                t_purpose = st.text_area("Purpose / notes", height=80)

                if st.form_submit_button("Save Trip", type="primary", use_container_width=True):
                    if t_odo_end <= 0:
                        st.error("End odometer is required.")
                    elif t_odo_end < t_odo_start:
                        st.error("End odometer must be greater than or equal to Start.")
                    else:
                        km = t_odo_end - t_odo_start
                        client.table("farm_vehicle_trips").insert({
                            "trip_date": str(t_date),
                            "vehicle_id": t_vehicle["id"],
                            "from_place": t_from or None,
                            "to_place": t_to or None,
                            "odometer_start": float(t_odo_start),
                            "odometer_end": float(t_odo_end),
                            "km": float(km),
                            "purpose": t_purpose or None,
                            "driver": t_driver or None,
                        }).execute()
                        st.success(f"✅ Trip logged: {km:,.1f} km for {t_vehicle['name']}.")
                        st.rerun()

    # --- Log Fuel ---
    with sub_v_fuel:
        if not vehicles:
            st.warning("Add a vehicle first in the 'Vehicles' tab.")
        else:
            with st.form("fuel_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    f_date = st.date_input("Date", value=date.today(), key="fuel_date")
                    f_vehicle = st.selectbox(
                        "Vehicle", options=vehicles, format_func=lambda v: v["name"], key="fuel_v"
                    )
                    f_liters = st.number_input("Liters", min_value=0.0, step=0.5, format="%.2f")
                with c2:
                    f_amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0, format="%.2f")
                    f_odo = st.number_input("Odometer reading (km)", min_value=0.0, step=1.0, format="%.2f")

                f_remarks = st.text_input("Remarks", placeholder="Pump name, etc.")
                st.info("💡 This will auto-create a payment in Petty Cash under 'Vehicle Fuel'.")

                if st.form_submit_button("Save Fuel Entry", type="primary", use_container_width=True):
                    if f_liters <= 0 or f_amount <= 0:
                        st.error("Liters and amount are both required.")
                    else:
                        # Auto-log payment to petty cash
                        remarks = f"Fuel — {f_vehicle['name']} — {f_liters:.2f} L"
                        if f_remarks:
                            remarks += f" — {f_remarks}"
                        txn_id = auto_log_payment("Vehicle Fuel", f_amount, f_date, remarks)

                        client.table("farm_vehicle_fuel").insert({
                            "fuel_date": str(f_date),
                            "vehicle_id": f_vehicle["id"],
                            "liters": float(f_liters),
                            "amount": float(f_amount),
                            "odometer": float(f_odo) if f_odo else None,
                            "remarks": f_remarks or None,
                            "txn_id": txn_id,
                        }).execute()

                        msg = f"✅ Fuel entry saved for {f_vehicle['name']}."
                        if txn_id:
                            msg += f" Petty cash payment of ₹{f_amount:,.2f} auto-logged."
                        st.success(msg)
                        st.rerun()

    # --- Log Maintenance ---
    with sub_v_maint:
        if not vehicles:
            st.warning("Add a vehicle first in the 'Vehicles' tab.")
        else:
            with st.form("maint_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    m_date = st.date_input("Date", value=date.today(), key="maint_date")
                    m_vehicle = st.selectbox(
                        "Vehicle", options=vehicles, format_func=lambda v: v["name"], key="maint_v"
                    )
                    m_type = st.text_input(
                        "Service type *", placeholder="e.g. Oil change, Tyre, Engine repair"
                    )
                with c2:
                    m_cost = st.number_input("Cost (₹)", min_value=0.0, step=100.0, format="%.2f")
                    m_vendor = st.text_input("Vendor / mechanic")

                m_notes = st.text_area("Notes", height=80)
                m_bills = st.file_uploader(
                    "Upload bill / photos",
                    type=["pdf", "jpg", "jpeg", "png"],
                    accept_multiple_files=True,
                )
                st.info("💡 This will auto-create a payment in Petty Cash under 'Vehicle Maintenance'.")

                if st.form_submit_button("Save Maintenance Entry", type="primary", use_container_width=True):
                    if not m_type.strip() or m_cost <= 0:
                        st.error("Service type and cost are required.")
                    else:
                        with st.spinner("Saving..."):
                            bill_urls = upload_many(
                                m_bills, "farm-asset-docs", folder=f"vehicle-bills/{m_vehicle['name']}"
                            )

                            # Auto-log payment to petty cash
                            remarks = f"Maintenance — {m_vehicle['name']} — {m_type.strip()}"
                            if m_vendor:
                                remarks += f" @ {m_vendor}"
                            txn_id = auto_log_payment("Vehicle Maintenance", m_cost, m_date, remarks)

                            client.table("farm_vehicle_maintenance").insert({
                                "service_date": str(m_date),
                                "vehicle_id": m_vehicle["id"],
                                "service_type": m_type.strip(),
                                "cost": float(m_cost),
                                "vendor": m_vendor or None,
                                "notes": m_notes or None,
                                "bill_urls": bill_urls,
                                "txn_id": txn_id,
                            }).execute()

                        msg = f"✅ Maintenance saved with {len(bill_urls)} bill(s)."
                        if txn_id:
                            msg += f" Petty cash payment of ₹{m_cost:,.2f} auto-logged."
                        st.success(msg)
                        st.rerun()

    # --- History ---
    with sub_v_history:
        if not vehicles:
            st.warning("No vehicles registered.")
        else:
            v_filter = st.selectbox(
                "Vehicle",
                options=vehicles,
                format_func=lambda v: v["name"],
                key="hist_v",
            )
            hist_kind = st.radio(
                "Show", ["Trips", "Fuel", "Maintenance", "Summary"], horizontal=True
            )

            # ─── TRIPS ───
            if hist_kind == "Trips":
                trips = (
                    client.table("farm_vehicle_trips")
                    .select("*")
                    .eq("vehicle_id", v_filter["id"])
                    .order("trip_date", desc=True)
                    .execute()
                    .data
                )
                if not trips:
                    st.info("No trips logged.")
                else:
                    total_km = sum((t.get("km") or 0) for t in trips)
                    st.metric("Total KM", f"{total_km:,.1f}")

                    for tr in trips:
                        with st.expander(
                            f"🛣️ {tr['trip_date']} — {tr.get('from_place') or '?'} → "
                            f"{tr.get('to_place') or '?'} — {tr.get('km') or 0} km"
                        ):
                            edit_key = f"edit_trip_{tr['id']}"
                            if st.session_state.get(edit_key):
                                with st.form(f"edit_trip_form_{tr['id']}", clear_on_submit=False):
                                    c1, c2 = st.columns(2)
                                    with c1:
                                        n_date = st.date_input(
                                            "Date",
                                            value=pd.to_datetime(tr["trip_date"]).date(),
                                        )
                                        n_from = st.text_input("From", value=tr.get("from_place") or "")
                                        n_driver = st.text_input("Driver", value=tr.get("driver") or "")
                                        n_odo_start = st.number_input(
                                            "Start odometer (km)",
                                            min_value=0.0, step=1.0, format="%.2f",
                                            value=float(tr.get("odometer_start") or 0),
                                        )
                                    with c2:
                                        n_to = st.text_input("To", value=tr.get("to_place") or "")
                                        n_odo_end = st.number_input(
                                            "End odometer (km)",
                                            min_value=0.0, step=1.0, format="%.2f",
                                            value=float(tr.get("odometer_end") or 0),
                                        )

                                    # Live KM preview
                                    if n_odo_end > 0 and n_odo_end >= n_odo_start:
                                        calc_km = n_odo_end - n_odo_start
                                        st.success(f"📏 Distance: **{calc_km:,.2f} km**")
                                    elif n_odo_end > 0 and n_odo_end < n_odo_start:
                                        st.error(
                                            f"End odometer ({n_odo_end:,.1f}) is less than "
                                            f"Start ({n_odo_start:,.1f})."
                                        )

                                    n_purpose = st.text_area("Purpose", value=tr.get("purpose") or "")
                                    c1, c2 = st.columns(2)
                                    if c1.form_submit_button("💾 Save", type="primary", use_container_width=True):
                                        if n_odo_end > 0 and n_odo_end < n_odo_start:
                                            st.error("End odometer must be ≥ Start odometer.")
                                        else:
                                            km = (n_odo_end - n_odo_start) if (n_odo_end and n_odo_end >= n_odo_start) else None
                                            client.table("farm_vehicle_trips").update({
                                                "trip_date": str(n_date),
                                                "from_place": n_from or None,
                                                "to_place": n_to or None,
                                                "odometer_start": float(n_odo_start) if n_odo_start else None,
                                                "odometer_end": float(n_odo_end) if n_odo_end else None,
                                                "km": float(km) if km is not None else None,
                                                "purpose": n_purpose or None,
                                                "driver": n_driver or None,
                                            }).eq("id", tr["id"]).execute()
                                            st.session_state.pop(edit_key, None)
                                            st.success("Updated.")
                                            st.rerun()
                                    if c2.form_submit_button("Cancel", use_container_width=True):
                                        st.session_state.pop(edit_key, None)
                                        st.rerun()
                            else:
                                if tr.get("odometer_start") is not None and tr.get("odometer_end") is not None:
                                    st.write(
                                        f"**Odometer:** {tr['odometer_start']:,.1f} → "
                                        f"{tr['odometer_end']:,.1f} km"
                                    )
                                if tr.get("driver"):
                                    st.write(f"**Driver:** {tr['driver']}")
                                if tr.get("purpose"):
                                    st.write(f"**Purpose:** {tr['purpose']}")
                                st.divider()
                                c1, c2 = st.columns(2)
                                if c1.button("✏️ Edit", key=f"btn_edit_trip_{tr['id']}", use_container_width=True):
                                    st.session_state[edit_key] = True
                                    st.rerun()
                                with c2:
                                    if confirm_delete_ui(
                                        f"trip_{tr['id']}",
                                        f"trip on {tr['trip_date']}"
                                    ):
                                        client.table("farm_vehicle_trips").delete().eq(
                                            "id", tr["id"]
                                        ).execute()
                                        st.success("Deleted.")
                                        st.rerun()

            # ─── FUEL ───
            elif hist_kind == "Fuel":
                fuel = (
                    client.table("farm_vehicle_fuel")
                    .select("*")
                    .eq("vehicle_id", v_filter["id"])
                    .order("fuel_date", desc=True)
                    .execute()
                    .data
                )
                if not fuel:
                    st.info("No fuel entries.")
                else:
                    total_l = sum((f.get("liters") or 0) for f in fuel)
                    total_amt = sum((f.get("amount") or 0) for f in fuel)
                    avg_rate = total_amt / total_l if total_l > 0 else 0
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total Liters", f"{total_l:,.2f}")
                    c2.metric("Total Spent", f"₹{total_amt:,.0f}")
                    c3.metric("Avg ₹/L", f"₹{avg_rate:,.2f}")

                    for fu in fuel:
                        with st.expander(
                            f"⛽ {fu['fuel_date']} — {fu['liters']:.2f} L — ₹{fu['amount']:,.0f}"
                        ):
                            edit_key = f"edit_fuel_{fu['id']}"
                            if st.session_state.get(edit_key):
                                with st.form(f"edit_fuel_form_{fu['id']}", clear_on_submit=False):
                                    c1, c2 = st.columns(2)
                                    with c1:
                                        n_date = st.date_input(
                                            "Date",
                                            value=pd.to_datetime(fu["fuel_date"]).date(),
                                        )
                                        n_liters = st.number_input(
                                            "Liters", min_value=0.01, step=0.5, format="%.2f",
                                            value=float(fu["liters"]),
                                        )
                                    with c2:
                                        n_amount = st.number_input(
                                            "Amount (₹)", min_value=0.01, step=100.0, format="%.2f",
                                            value=float(fu["amount"]),
                                        )
                                        n_odo = st.number_input(
                                            "Odometer (km)", min_value=0.0, step=1.0, format="%.2f",
                                            value=float(fu.get("odometer") or 0),
                                        )
                                    n_remarks = st.text_input(
                                        "Remarks", value=fu.get("remarks") or ""
                                    )
                                    st.info("💡 The linked petty cash payment will also be updated.")
                                    c1, c2 = st.columns(2)
                                    if c1.form_submit_button("💾 Save", type="primary", use_container_width=True):
                                        # Sync the linked petty cash row first
                                        rem = f"Fuel — {v_filter['name']} — {n_liters:.2f} L"
                                        if n_remarks:
                                            rem += f" — {n_remarks}"
                                        new_txn_id = sync_linked_payment(
                                            fu.get("txn_id"), "Vehicle Fuel",
                                            n_amount, n_date, rem
                                        )
                                        client.table("farm_vehicle_fuel").update({
                                            "fuel_date": str(n_date),
                                            "liters": float(n_liters),
                                            "amount": float(n_amount),
                                            "odometer": float(n_odo) if n_odo else None,
                                            "remarks": n_remarks or None,
                                            "txn_id": new_txn_id,
                                        }).eq("id", fu["id"]).execute()
                                        st.session_state.pop(edit_key, None)
                                        st.success("Updated (petty cash synced).")
                                        st.rerun()
                                    if c2.form_submit_button("Cancel", use_container_width=True):
                                        st.session_state.pop(edit_key, None)
                                        st.rerun()
                            else:
                                if fu.get("odometer"):
                                    st.write(f"**Odometer:** {fu['odometer']:,.0f} km")
                                if fu.get("remarks"):
                                    st.write(f"**Remarks:** {fu['remarks']}")
                                if fu.get("txn_id"):
                                    st.caption(f"🔗 Linked to petty cash payment #{fu['txn_id']}")
                                st.divider()
                                c1, c2 = st.columns(2)
                                if c1.button("✏️ Edit", key=f"btn_edit_fuel_{fu['id']}", use_container_width=True):
                                    st.session_state[edit_key] = True
                                    st.rerun()
                                with c2:
                                    if confirm_delete_ui(
                                        f"fuel_{fu['id']}",
                                        f"fuel entry of ₹{fu['amount']:,.2f} on {fu['fuel_date']} "
                                        f"(linked petty cash payment will also be deleted)"
                                    ):
                                        delete_linked_payment(fu.get("txn_id"))
                                        client.table("farm_vehicle_fuel").delete().eq(
                                            "id", fu["id"]
                                        ).execute()
                                        st.success("Deleted (petty cash row also removed).")
                                        st.rerun()

            # ─── MAINTENANCE ───
            elif hist_kind == "Maintenance":
                maint = (
                    client.table("farm_vehicle_maintenance")
                    .select("*")
                    .eq("vehicle_id", v_filter["id"])
                    .order("service_date", desc=True)
                    .execute()
                    .data
                )
                if not maint:
                    st.info("No maintenance entries.")
                else:
                    st.metric(
                        "Total Maintenance Spend",
                        f"₹{sum(m['cost'] for m in maint):,.0f}",
                    )
                    for m in maint:
                        with st.expander(
                            f"🔧 {m['service_date']} — {m['service_type']} — ₹{m['cost']:,.0f}"
                        ):
                            edit_key = f"edit_maint_{m['id']}"
                            if st.session_state.get(edit_key):
                                with st.form(f"edit_maint_form_{m['id']}", clear_on_submit=False):
                                    c1, c2 = st.columns(2)
                                    with c1:
                                        n_date = st.date_input(
                                            "Date",
                                            value=pd.to_datetime(m["service_date"]).date(),
                                        )
                                        n_type = st.text_input(
                                            "Service type *", value=m["service_type"]
                                        )
                                    with c2:
                                        n_cost = st.number_input(
                                            "Cost (₹)", min_value=0.01, step=100.0, format="%.2f",
                                            value=float(m["cost"]),
                                        )
                                        n_vendor = st.text_input(
                                            "Vendor", value=m.get("vendor") or ""
                                        )
                                    n_notes = st.text_area("Notes", value=m.get("notes") or "")
                                    st.caption("Existing bill photos are kept. The linked petty cash payment will be updated.")
                                    c1, c2 = st.columns(2)
                                    if c1.form_submit_button("💾 Save", type="primary", use_container_width=True):
                                        if not n_type.strip():
                                            st.error("Service type is required.")
                                        else:
                                            rem = f"Maintenance — {v_filter['name']} — {n_type.strip()}"
                                            if n_vendor:
                                                rem += f" @ {n_vendor}"
                                            new_txn_id = sync_linked_payment(
                                                m.get("txn_id"), "Vehicle Maintenance",
                                                n_cost, n_date, rem
                                            )
                                            client.table("farm_vehicle_maintenance").update({
                                                "service_date": str(n_date),
                                                "service_type": n_type.strip(),
                                                "cost": float(n_cost),
                                                "vendor": n_vendor or None,
                                                "notes": n_notes or None,
                                                "txn_id": new_txn_id,
                                            }).eq("id", m["id"]).execute()
                                            st.session_state.pop(edit_key, None)
                                            st.success("Updated (petty cash synced).")
                                            st.rerun()
                                    if c2.form_submit_button("Cancel", use_container_width=True):
                                        st.session_state.pop(edit_key, None)
                                        st.rerun()
                            else:
                                st.write(f"**Vendor:** {m.get('vendor') or '—'}")
                                if m.get("notes"):
                                    st.write(f"**Notes:** {m['notes']}")
                                urls = m.get("bill_urls") or []
                                if urls:
                                    st.write(f"**Bills ({len(urls)}):**")
                                    for i, url in enumerate(urls, 1):
                                        st.markdown(f"- [Bill {i}]({url})")
                                if m.get("txn_id"):
                                    st.caption(f"🔗 Linked to petty cash payment #{m['txn_id']}")
                                st.divider()
                                c1, c2 = st.columns(2)
                                if c1.button("✏️ Edit", key=f"btn_edit_maint_{m['id']}", use_container_width=True):
                                    st.session_state[edit_key] = True
                                    st.rerun()
                                with c2:
                                    if confirm_delete_ui(
                                        f"maint_{m['id']}",
                                        f"maintenance entry of ₹{m['cost']:,.2f} on {m['service_date']} "
                                        f"(linked petty cash payment will also be deleted)"
                                    ):
                                        delete_linked_payment(m.get("txn_id"))
                                        client.table("farm_vehicle_maintenance").delete().eq(
                                            "id", m["id"]
                                        ).execute()
                                        st.success("Deleted (petty cash row also removed).")
                                        st.rerun()

            else:  # Summary
                trips = client.table("farm_vehicle_trips").select("km").eq(
                    "vehicle_id", v_filter["id"]
                ).execute().data
                fuel = client.table("farm_vehicle_fuel").select("liters, amount").eq(
                    "vehicle_id", v_filter["id"]
                ).execute().data
                maint = client.table("farm_vehicle_maintenance").select("cost").eq(
                    "vehicle_id", v_filter["id"]
                ).execute().data

                total_km = sum((t.get("km") or 0) for t in trips)
                total_liters = sum((f.get("liters") or 0) for f in fuel)
                total_fuel_cost = sum((f.get("amount") or 0) for f in fuel)
                total_maint_cost = sum((m.get("cost") or 0) for m in maint)
                mileage = (total_km / total_liters) if total_liters > 0 else 0

                st.subheader(f"📊 {v_filter['name']} — All-time Summary")
                c1, c2, c3 = st.columns(3)
                c1.metric("Total KM", f"{total_km:,.1f}")
                c2.metric("Total Fuel", f"{total_liters:,.1f} L")
                c3.metric("Mileage", f"{mileage:,.2f} km/L" if mileage else "—")

                c4, c5, c6 = st.columns(3)
                c4.metric("Fuel Cost", f"₹{total_fuel_cost:,.0f}")
                c5.metric("Maintenance Cost", f"₹{total_maint_cost:,.0f}")
                c6.metric("Total Spend", f"₹{total_fuel_cost + total_maint_cost:,.0f}")


# ═════════════════════════════════════════════════════════════
# TAB 5 · REPORTS
# ═════════════════════════════════════════════════════════════
with tab_reports:

    # ---------- Date range helper ----------
    def date_range_picker(key_prefix: str) -> tuple[date, date]:
        """Renders a quick-filter + custom range picker. Returns (start, end)."""
        today = date.today()
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        first_of_year = today.replace(month=1, day=1)

        c1, c2 = st.columns([2, 3])
        with c1:
            preset = st.selectbox(
                "Quick filter",
                [
                    "Custom range",
                    "This month",
                    "Last month",
                    "This year",
                    "All time",
                ],
                key=f"{key_prefix}_preset",
            )
        with c2:
            if preset == "This month":
                start, end = first_of_month, today
                st.info(f"📅 {start} → {end}")
            elif preset == "Last month":
                start, end = last_month_start, last_month_end
                st.info(f"📅 {start} → {end}")
            elif preset == "This year":
                start, end = first_of_year, today
                st.info(f"📅 {start} → {end}")
            elif preset == "All time":
                start, end = date(2000, 1, 1), today
                st.info("📅 All available data")
            else:  # Custom range
                d1, d2 = st.columns(2)
                start = d1.date_input("From", value=first_of_month, key=f"{key_prefix}_from")
                end = d2.date_input("To", value=today, key=f"{key_prefix}_to")
        return start, end

    # ---------- Excel export helper ----------
    def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
        """Build a multi-sheet xlsx in memory; returns bytes."""
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for sheet_name, df in sheets.items():
                if df is None or df.empty:
                    pd.DataFrame({"Note": ["No data in this range"]}).to_excel(
                        writer, sheet_name=sheet_name[:31], index=False
                    )
                else:
                    df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
                    # Auto-fit column widths
                    ws = writer.sheets[sheet_name[:31]]
                    for col_cells in ws.columns:
                        max_len = max(
                            (len(str(c.value)) if c.value is not None else 0)
                            for c in col_cells
                        )
                        ws.column_dimensions[col_cells[0].column_letter].width = min(
                            max_len + 2, 50
                        )
        return buf.getvalue()

    # ---------- Report selector ----------
    report = st.radio(
        "Select report",
        [
            "💰 Cash Summary",
            "🚜 Vehicle Running Cost",
            "🌾 Daily Work Summary",
            "🏞️ Asset Register",
        ],
        horizontal=True,
    )
    st.divider()

    # ═══════════════════════════════════════════════════════════
    # CASH SUMMARY
    # ═══════════════════════════════════════════════════════════
    if report == "💰 Cash Summary":
        st.subheader("Cash Summary by Head")
        start, end = date_range_picker("cash")

        txns = (
            client.table("farm_transactions")
            .select("*, farm_heads(name)")
            .gte("txn_date", str(start))
            .lte("txn_date", str(end))
            .order("txn_date", desc=True)
            .execute()
            .data
        )

        if not txns:
            st.info("No transactions in this range.")
        else:
            df = pd.DataFrame([
                {
                    "Date": t["txn_date"],
                    "Type": t["type"],
                    "Head": (t.get("farm_heads") or {}).get("name", "—"),
                    "Amount": t["amount"],
                    "Remarks": t.get("remarks") or "",
                }
                for t in txns
            ])

            receipts = df[df["Type"] == "receipt"]["Amount"].sum()
            payments = df[df["Type"] == "payment"]["Amount"].sum()
            balance = receipts - payments

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Receipts", f"₹{receipts:,.0f}")
            c2.metric("Payments", f"₹{payments:,.0f}")
            c3.metric("Net", f"₹{balance:,.0f}")
            c4.metric("Entries", len(df))

            # By-head breakdown
            st.markdown("#### Breakdown by Head")
            by_head = (
                df.groupby(["Type", "Head"])["Amount"]
                .agg(["sum", "count"])
                .reset_index()
                .rename(columns={"sum": "Total", "count": "Entries"})
                .sort_values(["Type", "Total"], ascending=[True, False])
            )
            st.dataframe(by_head, use_container_width=True, hide_index=True)

            with st.expander("📋 All transactions"):
                st.dataframe(df, use_container_width=True, hide_index=True)

            # Excel download
            sheets = {
                "Summary": pd.DataFrame({
                    "Metric": ["Receipts", "Payments", "Net Balance", "Entry Count"],
                    "Value": [receipts, payments, balance, len(df)],
                }),
                "By Head": by_head,
                "Transactions": df,
            }
            c1, c2 = st.columns(2)
            c1.download_button(
                "⬇️ Download Excel",
                to_excel_bytes(sheets),
                f"cash_summary_{start}_to_{end}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            c2.download_button(
                "⬇️ Download CSV (transactions)",
                df.to_csv(index=False).encode("utf-8"),
                f"cash_transactions_{start}_to_{end}.csv",
                "text/csv",
                use_container_width=True,
            )

    # ═══════════════════════════════════════════════════════════
    # VEHICLE RUNNING COST
    # ═══════════════════════════════════════════════════════════
    elif report == "🚜 Vehicle Running Cost":
        st.subheader("Vehicle Running Cost")
        start, end = date_range_picker("vehicle")

        vehicles = client.table("farm_vehicles").select("*").order("name").execute().data
        if not vehicles:
            st.info("No vehicles registered.")
        else:
            v_options = ["All vehicles"] + [v["name"] for v in vehicles]
            v_choice = st.selectbox("Vehicle", v_options)
            selected = vehicles if v_choice == "All vehicles" else [
                v for v in vehicles if v["name"] == v_choice
            ]

            rows = []
            for v in selected:
                trips = (
                    client.table("farm_vehicle_trips")
                    .select("km")
                    .eq("vehicle_id", v["id"])
                    .gte("trip_date", str(start))
                    .lte("trip_date", str(end))
                    .execute()
                    .data
                )
                fuel = (
                    client.table("farm_vehicle_fuel")
                    .select("liters, amount")
                    .eq("vehicle_id", v["id"])
                    .gte("fuel_date", str(start))
                    .lte("fuel_date", str(end))
                    .execute()
                    .data
                )
                maint = (
                    client.table("farm_vehicle_maintenance")
                    .select("cost")
                    .eq("vehicle_id", v["id"])
                    .gte("service_date", str(start))
                    .lte("service_date", str(end))
                    .execute()
                    .data
                )

                total_km = sum((t.get("km") or 0) for t in trips)
                total_liters = sum((f.get("liters") or 0) for f in fuel)
                fuel_cost = sum((f.get("amount") or 0) for f in fuel)
                maint_cost = sum((m.get("cost") or 0) for m in maint)
                mileage = (total_km / total_liters) if total_liters > 0 else 0
                cost_per_km = ((fuel_cost + maint_cost) / total_km) if total_km > 0 else 0

                rows.append({
                    "Vehicle": v["name"],
                    "Type": v["vehicle_type"],
                    "Total KM": round(total_km, 1),
                    "Liters": round(total_liters, 2),
                    "Mileage (km/L)": round(mileage, 2) if mileage else None,
                    "Fuel Cost (₹)": round(fuel_cost, 0),
                    "Maintenance (₹)": round(maint_cost, 0),
                    "Total Spend (₹)": round(fuel_cost + maint_cost, 0),
                    "₹/km": round(cost_per_km, 2) if cost_per_km else None,
                })

            df = pd.DataFrame(rows)

            # Totals
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total KM", f"{df['Total KM'].sum():,.1f}")
            c2.metric("Total Fuel", f"{df['Liters'].sum():,.1f} L")
            c3.metric("Fuel Cost", f"₹{df['Fuel Cost (₹)'].sum():,.0f}")
            c4.metric("Maintenance", f"₹{df['Maintenance (₹)'].sum():,.0f}")

            st.dataframe(df, use_container_width=True, hide_index=True)

            # Detailed per-vehicle data for export
            detail_sheets = {"Summary": df}
            for v in selected:
                trips_full = (
                    client.table("farm_vehicle_trips")
                    .select("trip_date, from_place, to_place, km, driver, purpose")
                    .eq("vehicle_id", v["id"])
                    .gte("trip_date", str(start))
                    .lte("trip_date", str(end))
                    .order("trip_date", desc=True)
                    .execute()
                    .data
                )
                fuel_full = (
                    client.table("farm_vehicle_fuel")
                    .select("fuel_date, liters, amount, odometer, remarks")
                    .eq("vehicle_id", v["id"])
                    .gte("fuel_date", str(start))
                    .lte("fuel_date", str(end))
                    .order("fuel_date", desc=True)
                    .execute()
                    .data
                )
                maint_full = (
                    client.table("farm_vehicle_maintenance")
                    .select("service_date, service_type, cost, vendor, notes")
                    .eq("vehicle_id", v["id"])
                    .gte("service_date", str(start))
                    .lte("service_date", str(end))
                    .order("service_date", desc=True)
                    .execute()
                    .data
                )
                short = v["name"][:20]
                if trips_full:
                    detail_sheets[f"{short} Trips"] = pd.DataFrame(trips_full)
                if fuel_full:
                    detail_sheets[f"{short} Fuel"] = pd.DataFrame(fuel_full)
                if maint_full:
                    detail_sheets[f"{short} Maint"] = pd.DataFrame(maint_full)

            st.download_button(
                "⬇️ Download Excel (with per-vehicle detail sheets)",
                to_excel_bytes(detail_sheets),
                f"vehicle_running_cost_{start}_to_{end}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    # ═══════════════════════════════════════════════════════════
    # DAILY WORK SUMMARY
    # ═══════════════════════════════════════════════════════════
    elif report == "🌾 Daily Work Summary":
        st.subheader("Daily Work Summary")
        start, end = date_range_picker("work")

        farms = client.table("farm_farms").select("*").order("name").execute().data
        farm_options = ["All farms"] + [f["name"] for f in farms]
        f_choice = st.selectbox("Farm", farm_options)

        q = (
            client.table("farm_work_entries")
            .select("*, farm_farms(name)")
            .gte("work_date", str(start))
            .lte("work_date", str(end))
            .order("work_date", desc=True)
        )
        if f_choice != "All farms":
            farm_id = next(f["id"] for f in farms if f["name"] == f_choice)
            q = q.eq("farm_id", farm_id)
        entries = q.execute().data

        if not entries:
            st.info("No work entries in this range.")
        else:
            df = pd.DataFrame([
                {
                    "Date": e["work_date"],
                    "Farm": (e.get("farm_farms") or {}).get("name", "—"),
                    "Workers": e.get("workers_count") or 0,
                    "Cost (₹)": e.get("cost") or 0,
                    "Description": e["description"],
                    "Photos": len(e.get("photo_urls") or []),
                }
                for e in entries
            ])

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Entries", len(df))
            c2.metric("Total Cost", f"₹{df['Cost (₹)'].sum():,.0f}")
            c3.metric("Total Workers", int(df["Workers"].sum()))
            c4.metric("Farms Active", df["Farm"].nunique())

            # By-farm breakdown
            st.markdown("#### Breakdown by Farm")
            by_farm = (
                df.groupby("Farm")
                .agg(
                    Entries=("Date", "count"),
                    **{"Total Cost (₹)": ("Cost (₹)", "sum")},
                    **{"Total Workers": ("Workers", "sum")},
                )
                .reset_index()
                .sort_values("Total Cost (₹)", ascending=False)
            )
            st.dataframe(by_farm, use_container_width=True, hide_index=True)

            with st.expander("📋 All entries"):
                st.dataframe(df, use_container_width=True, hide_index=True)

            sheets = {
                "Summary": pd.DataFrame({
                    "Metric": ["Entries", "Total Cost", "Total Workers", "Active Farms"],
                    "Value": [
                        len(df),
                        df["Cost (₹)"].sum(),
                        int(df["Workers"].sum()),
                        df["Farm"].nunique(),
                    ],
                }),
                "By Farm": by_farm,
                "Entries": df,
            }
            c1, c2 = st.columns(2)
            c1.download_button(
                "⬇️ Download Excel",
                to_excel_bytes(sheets),
                f"work_summary_{start}_to_{end}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            c2.download_button(
                "⬇️ Download CSV (entries)",
                df.to_csv(index=False).encode("utf-8"),
                f"work_entries_{start}_to_{end}.csv",
                "text/csv",
                use_container_width=True,
            )

    # ═══════════════════════════════════════════════════════════
    # ASSET REGISTER
    # ═══════════════════════════════════════════════════════════
    elif report == "🏞️ Asset Register":
        st.subheader("Asset Register (snapshot)")
        st.caption("Full list of all registered assets — no date filter applied.")

        assets = (
            client.table("farm_assets")
            .select("*")
            .order("short_name")
            .execute()
            .data
        )

        if not assets:
            st.info("No assets registered.")
        else:
            df = pd.DataFrame([
                {
                    "Short Name": a["short_name"],
                    "Survey No.": a.get("survey_no") or "",
                    "Area": a.get("area") or "",
                    "Unit": a.get("area_unit") or "",
                    "Passbook": a.get("passbook_details") or "",
                    "Notes": a.get("notes") or "",
                    "Documents": len(a.get("document_urls") or []),
                }
                for a in assets
            ])

            c1, c2 = st.columns(2)
            c1.metric("Total Assets", len(df))
            try:
                total_area = pd.to_numeric(df["Area"], errors="coerce").fillna(0).sum()
                c2.metric("Total Area (mixed units)", f"{total_area:,.2f}")
            except Exception:
                pass

            st.markdown("#### Full Register")
            st.dataframe(df, use_container_width=True, hide_index=True)

            sheets = {"Asset Register": df}
            c1, c2 = st.columns(2)
            c1.download_button(
                "⬇️ Download Excel",
                to_excel_bytes(sheets),
                f"asset_register_{date.today()}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            c2.download_button(
                "⬇️ Download CSV",
                df.to_csv(index=False).encode("utf-8"),
                f"asset_register_{date.today()}.csv",
                "text/csv",
                use_container_width=True,
            )
