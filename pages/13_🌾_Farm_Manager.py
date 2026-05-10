"""
13_🌾_Farm_Manager.py

Farm Manager module for BG Engg ERP.
- Tab 1: Petty Cash (receipts/payments + custom heads)
- Tab 2: Daily Work Log (per-farm entries with photos)
- Tab 3: Assets Register (lands, barns, vehicles, sheds with documents)

Password-gated. Tables are prefixed `farm_` to coexist with the rest of the ERP schema.
"""

import uuid
from pathlib import Path
from datetime import date

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
# HEADER
# ─────────────────────────────────────────────────────────────
header_l, header_r = st.columns([4, 1])
with header_l:
    st.title("🌾 Farm Manager")
    st.caption("Petty cash · Daily work log · Assets register")
with header_r:
    st.write("")
    st.write("")
    if st.button("🔒 Lock", use_container_width=True):
        st.session_state.pop("farm_authed", None)
        st.rerun()

tab_cash, tab_work, tab_assets = st.tabs([
    "💰 Petty Cash",
    "🌾 Daily Work",
    "🏞️ Assets",
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
            with st.form("txn_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    txn_type = st.radio("Type", ["receipt", "payment"], horizontal=True)
                    txn_date = st.date_input("Date", value=date.today())
                with c2:
                    filtered = [h for h in heads if h["type"] == txn_type]
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
                    amount = st.number_input("Amount (₹)", min_value=0.01, step=100.0, format="%.2f")

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
            df = pd.DataFrame(heads)[["id", "name", "type"]]
            st.dataframe(df, use_container_width=True, hide_index=True)
            with st.expander("🗑️ Delete a head"):
                to_delete = st.selectbox(
                    "Select head to delete",
                    options=heads,
                    format_func=lambda h: f"{h['name']} ({h['type']})",
                    key="del_head",
                )
                if st.button("Delete", type="secondary", key="btn_del_head"):
                    try:
                        client.table("farm_heads").delete().eq("id", to_delete["id"]).execute()
                        st.success("Deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Cannot delete (in use?): {e}")

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
            rows = []
            for t in txns:
                rows.append({
                    "ID": t["id"],
                    "Date": t["txn_date"],
                    "Type": t["type"],
                    "Head": (t.get("farm_heads") or {}).get("name", "—"),
                    "Amount": t["amount"],
                    "Remarks": t.get("remarks") or "",
                })
            df = pd.DataFrame(rows)

            c1, c2, c3 = st.columns(3)
            receipts = df[df["Type"] == "receipt"]["Amount"].sum()
            payments = df[df["Type"] == "payment"]["Amount"].sum()
            c1.metric("Receipts", f"₹{receipts:,.0f}")
            c2.metric("Payments", f"₹{payments:,.0f}")
            c3.metric("Balance", f"₹{receipts - payments:,.0f}")

            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button(
                "⬇️ Download CSV",
                df.to_csv(index=False).encode("utf-8"),
                "farm_ledger.csv",
                "text/csv",
            )


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
            st.dataframe(pd.DataFrame(farms)[["id", "name"]], use_container_width=True, hide_index=True)

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


# ═════════════════════════════════════════════════════════════
# TAB 3 · ASSETS REGISTER
# ═════════════════════════════════════════════════════════════
with tab_assets:
    DEFAULT_CATEGORIES = [
        "Farm Land", "Mango Farm", "Tobacco Barn", "Tractor",
        "Jimney", "Shed", "House", "Other",
    ]

    # Seed defaults if empty
    existing_cats = client.table("farm_asset_categories").select("id").execute().data
    if not existing_cats:
        client.table("farm_asset_categories").insert(
            [{"name": n} for n in DEFAULT_CATEGORIES]
        ).execute()

    sub_a_add, sub_a_list, sub_a_cats = st.tabs(["➕ Add Asset", "📋 All Assets", "🏷️ Categories"])

    # --- Add Asset ---
    with sub_a_add:
        cats = client.table("farm_asset_categories").select("*").order("name").execute().data
        with st.form("asset_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                short_name = st.text_input("Short name *", placeholder="e.g. North Mango Farm")
                category = st.selectbox("Category *", options=cats, format_func=lambda c: c["name"])
                survey_no = st.text_input("Survey No.")
            with c2:
                area = st.number_input("Area", min_value=0.0, step=0.1, format="%.2f")
                area_unit = st.selectbox("Unit", ["acres", "sq.ft", "sq.m", "hectares", "guntas"])
                passbook = st.text_input("Passbook details")

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
                            "category_id": category["id"],
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
        cats = client.table("farm_asset_categories").select("*").order("name").execute().data
        cat_filter = st.selectbox(
            "Filter by category",
            options=[None] + cats,
            format_func=lambda c: "All categories" if c is None else c["name"],
            key="asset_cat_filter",
        )

        q = client.table("farm_assets").select("*, farm_asset_categories(name)").order("short_name")
        if cat_filter:
            q = q.eq("category_id", cat_filter["id"])
        assets = q.execute().data

        if not assets:
            st.info("No assets registered yet.")
        else:
            st.write(f"**{len(assets)} asset(s) found**")
            for a in assets:
                cat_name = (a.get("farm_asset_categories") or {}).get("name", "—")
                with st.expander(f"🏷️ {a['short_name']} — {cat_name}"):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.write(f"**Survey No:** {a.get('survey_no') or '—'}")
                        st.write(f"**Passbook:** {a.get('passbook_details') or '—'}")
                    with c2:
                        if a.get("area"):
                            st.write(f"**Area:** {a['area']} {a.get('area_unit') or ''}")
                        st.write(f"**Category:** {cat_name}")
                    if a.get("notes"):
                        st.write(f"**Notes:** {a['notes']}")
                    urls = a.get("document_urls") or []
                    if urls:
                        st.write(f"**Documents ({len(urls)}):**")
                        for i, url in enumerate(urls, 1):
                            st.markdown(f"- [Document {i}]({url})")
                    if st.button("🗑️ Delete", key=f"del_asset_{a['id']}"):
                        client.table("farm_assets").delete().eq("id", a["id"]).execute()
                        st.success("Deleted.")
                        st.rerun()

    # --- Categories ---
    with sub_a_cats:
        with st.form("cat_form", clear_on_submit=True):
            c1, c2 = st.columns([3, 1])
            new_cat = c1.text_input("New category", placeholder="e.g. Borewell, Pump House")
            c2.markdown("&nbsp;")
            if c2.form_submit_button("Add", use_container_width=True) and new_cat.strip():
                try:
                    client.table("farm_asset_categories").insert({"name": new_cat.strip()}).execute()
                    st.success(f"Added: {new_cat}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        cats = client.table("farm_asset_categories").select("*").order("name").execute().data
        if cats:
            st.dataframe(pd.DataFrame(cats)[["id", "name"]], use_container_width=True, hide_index=True)
