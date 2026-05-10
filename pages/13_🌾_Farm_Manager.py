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
    st.caption("Petty cash · Daily work · Assets · Vehicles")
with header_r:
    st.write("")
    st.write("")
    if st.button("🔒 Lock", use_container_width=True):
        st.session_state.pop("farm_authed", None)
        st.rerun()

tab_cash, tab_work, tab_assets, tab_vehicles = st.tabs([
    "💰 Petty Cash",
    "🌾 Daily Work",
    "🏞️ Assets",
    "🚜 Vehicles",
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
        if vehicles:
            df = pd.DataFrame(vehicles)[
                ["id", "name", "vehicle_type", "registration_no", "notes"]
            ]
            st.dataframe(df, use_container_width=True, hide_index=True)

            with st.expander("🗑️ Delete a vehicle (also deletes its trip/fuel/maintenance history)"):
                to_del = st.selectbox(
                    "Select vehicle",
                    options=vehicles,
                    format_func=lambda v: f"{v['name']} ({v['vehicle_type']})",
                    key="del_vehicle",
                )
                if st.button("Delete vehicle", type="secondary", key="btn_del_vehicle"):
                    client.table("farm_vehicles").delete().eq("id", to_del["id"]).execute()
                    st.success("Deleted.")
                    st.rerun()
        else:
            st.info("No vehicles yet. Add one above to start logging trips, fuel, and maintenance.")

    vehicles = client.table("farm_vehicles").select("*").order("name").execute().data

    # --- Log Trip ---
    with sub_v_trip:
        if not vehicles:
            st.warning("Add a vehicle first in the 'Vehicles' tab.")
        else:
            with st.form("trip_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    t_date = st.date_input("Date", value=date.today(), key="trip_date")
                    t_vehicle = st.selectbox(
                        "Vehicle", options=vehicles, format_func=lambda v: v["name"], key="trip_v"
                    )
                    t_driver = st.text_input("Driver")
                with c2:
                    t_from = st.text_input("From")
                    t_to = st.text_input("To")
                    t_km = st.number_input("Distance (km)", min_value=0.0, step=1.0, format="%.2f")

                t_purpose = st.text_area("Purpose / notes", height=80)

                if st.form_submit_button("Save Trip", type="primary", use_container_width=True):
                    client.table("farm_vehicle_trips").insert({
                        "trip_date": str(t_date),
                        "vehicle_id": t_vehicle["id"],
                        "from_place": t_from or None,
                        "to_place": t_to or None,
                        "km": float(t_km) if t_km else None,
                        "purpose": t_purpose or None,
                        "driver": t_driver or None,
                    }).execute()
                    st.success(f"✅ Trip logged for {t_vehicle['name']}.")
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
                    df = pd.DataFrame(trips)[
                        ["trip_date", "from_place", "to_place", "km", "driver", "purpose"]
                    ].rename(columns={
                        "trip_date": "Date", "from_place": "From", "to_place": "To",
                        "km": "KM", "driver": "Driver", "purpose": "Purpose",
                    })
                    st.metric("Total KM", f"{df['KM'].sum():,.1f}")
                    st.dataframe(df, use_container_width=True, hide_index=True)

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
                    df = pd.DataFrame(fuel)[
                        ["fuel_date", "liters", "amount", "odometer", "remarks"]
                    ].rename(columns={
                        "fuel_date": "Date", "liters": "Liters", "amount": "Amount (₹)",
                        "odometer": "Odometer", "remarks": "Remarks",
                    })
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total Liters", f"{df['Liters'].sum():,.2f}")
                    c2.metric("Total Spent", f"₹{df['Amount (₹)'].sum():,.0f}")
                    avg_rate = (
                        df["Amount (₹)"].sum() / df["Liters"].sum()
                        if df["Liters"].sum() > 0 else 0
                    )
                    c3.metric("Avg ₹/L", f"₹{avg_rate:,.2f}")
                    st.dataframe(df, use_container_width=True, hide_index=True)

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
                            st.write(f"**Vendor:** {m.get('vendor') or '—'}")
                            if m.get("notes"):
                                st.write(f"**Notes:** {m['notes']}")
                            urls = m.get("bill_urls") or []
                            if urls:
                                st.write(f"**Bills ({len(urls)}):**")
                                for i, url in enumerate(urls, 1):
                                    st.markdown(f"- [Bill {i}]({url})")

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
