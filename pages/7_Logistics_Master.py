import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz

# ── 1. SETUP ──────────────────────────────────────────────────────────────────
IST = pytz.timezone("Asia/Kolkata")
st.set_page_config(page_title="B&G Logistics | Fleet Tracker", layout="wide")

try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception:
    st.error("❌ Supabase connection failed. Check your `.streamlit/secrets.toml` for [connections.supabase] entries.")
    st.stop()

# ── 2. DATA HELPERS ───────────────────────────────────────────────────────────

def _safe_to_ist(series: pd.Series) -> pd.Series:
    """Convert a timestamp series to IST, handling both naive (UTC) and tz-aware inputs."""
    dt = pd.to_datetime(series, errors="coerce", utc=True)
    return dt.dt.tz_convert("Asia/Kolkata")


@st.cache_data(ttl=600)
def get_staff_master() -> list[str]:
    try:
        res = conn.table("master_staff").select("name").order("name").execute()
        return [r["name"] for r in res.data] if res.data else ["Admin"]
    except Exception:
        return ["Admin", "Staff"]


@st.cache_data(ttl=600)
def get_vehicle_master() -> list[str]:
    try:
        res = conn.table("master_vehicles").select("reg_no").order("reg_no").execute()
        return [r["reg_no"] for r in res.data] if res.data else ["AP07-XXXX"]
    except Exception:
        return ["AP07-XXXX", "TS09-XXXX"]


@st.cache_data(ttl=60)
def load_logistics_data() -> pd.DataFrame:
    try:
        res = conn.table("logistics_logs").select("*").order("timestamp", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            for col in ("distance", "fuel_ltrs", "start_km", "end_km"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            return df
    except Exception:
        pass
    return pd.DataFrame(columns=["timestamp", "vehicle", "end_km", "distance", "fuel_ltrs"])


@st.cache_data(ttl=30)
def load_requests() -> pd.DataFrame:
    """Cached version of logistics_requests (short TTL – operational data)."""
    try:
        res = conn.table("logistics_requests").select("*").order("created_at", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def get_last_km(veh_name: str, dataframe: pd.DataFrame) -> int:
    try:
        if not dataframe.empty and "vehicle" in dataframe.columns:
            veh_logs = dataframe[dataframe["vehicle"] == veh_name]
            if not veh_logs.empty:
                val = veh_logs.iloc[0]["end_km"]
                if pd.notnull(val):
                    return int(float(val))
    except Exception:
        pass
    return 0


def clear_operational_cache():
    """Clear only the short-lived caches; keep master data."""
    load_logistics_data.clear()
    load_requests.clear()


# ── 3. GLOBAL STATE ───────────────────────────────────────────────────────────
staff_list   = get_staff_master()
vehicle_list = get_vehicle_master()
df           = load_logistics_data()

PURPOSE_LIST = [
    "Site Delivery", "Material Pickup", "Material Dropping",
    "Material Pickup & Drop", "Inter-Unit Transfer",
    "Client Pickup & Drop", "Vendor Visit", "Fueling", "Maintenance", "Other",
]

# ── 4. UI ─────────────────────────────────────────────────────────────────────
st.title("🚛 B&G Logistics Management System")

with st.sidebar:
    if st.button("🔄 Sync Master Data"):
        st.cache_data.clear()   # Full clear only on explicit master-data sync
        st.rerun()

tabs = st.tabs([
    "📅 Staff Booking",
    "👨‍✈️ Brahmiah's Desk",
    "📝 Trip Logger",
    "📊 Analytics",
    "📥 Export & Reports",
])

# ── TAB 1: STAFF BOOKING ──────────────────────────────────────────────────────
with tabs[0]:
    with st.form("request_form", clear_on_submit=True):
        st.subheader("Request Vehicle for Work")
        c1, c2 = st.columns(2)
        req_by      = c1.selectbox("Staff Name", staff_list, key="bk_staff")
        req_veh     = c1.selectbox("Preferred Vehicle", vehicle_list, key="bk_veh")
        dest        = c1.text_input("Destination / Site")
        r_date      = c2.date_input("Required Date", min_value=date.today())
        r_time      = c2.text_input("Required Time (e.g. 9:00 AM)")
        req_purpose = c2.selectbox("Purpose", PURPOSE_LIST, key="bk_purpose")

        if st.form_submit_button("Submit Request"):
            dest_clean = dest.strip().upper()
            if not dest_clean:
                st.warning("Please enter a destination.")
            else:
                new_req = {
                    "requested_by":    req_by,
                    "destination":     dest_clean[:200],       # length guard
                    "req_date":        str(r_date),
                    "req_time":        r_time.strip()[:20],
                    "purpose":         req_purpose,
                    "assigned_vehicle": req_veh,
                    "status":          "Pending",
                }
                conn.table("logistics_requests").insert(new_req).execute()
                clear_operational_cache()
                st.success("Request logged!")
                st.rerun()

    st.divider()
    st.subheader("📋 Complete Booking History")
    ardf = load_requests()
    if not ardf.empty:
        display = ardf.copy()
        # Show "created at" in IST – keep column name honest
        display["created_at_ist"] = (
            _safe_to_ist(display["created_at"]).dt.strftime("%d %b, %I:%M %p")
        )
        st.dataframe(
            display[["requested_by", "destination", "req_date", "created_at_ist", "assigned_vehicle", "status"]],
            column_config={"created_at_ist": "Submitted At"},
            use_container_width=True,
            hide_index=True,
        )

# ── TAB 2: BRAHMIAH'S DESK ────────────────────────────────────────────────────
with tabs[1]:
    st.subheader("👨‍✈️ Operations & Manual Controls")
    ardf = load_requests()

    if not ardf.empty:
        today_ist = datetime.now(IST).date()

        pending_df  = ardf[ardf["status"] == "Pending"]
        assigned_df = ardf[ardf["status"] == "Assigned"]
        closed_today_df = ardf[
            (ardf["status"] == "Trip Closed") &
            (_safe_to_ist(ardf["created_at"]).dt.date == today_ist)
        ]

        m1, m2, m3 = st.columns(3)
        m1.metric("Pending Approval",   len(pending_df))
        m2.metric("In-Trip (Assigned)", len(assigned_df))
        m3.metric("Closed Today",       len(closed_today_df))
    else:
        pending_df  = pd.DataFrame()
        assigned_df = pd.DataFrame()

    # Approvals
    st.markdown("### 📬 Pending Approvals")
    if not pending_df.empty:
        for _, r in pending_df.iterrows():
            with st.expander(f"🚩 APPROVE: {r['requested_by']} → {r['destination']}"):
                v_assign = st.selectbox("Assign Vehicle", vehicle_list, key=f"v{r['id']}")
                if st.button("Confirm Assignment", key=f"btn{r['id']}"):
                    conn.table("logistics_requests") \
                        .update({"status": "Assigned", "assigned_vehicle": v_assign}) \
                        .eq("id", r["id"]).execute()
                    clear_operational_cache()
                    st.rerun()
    else:
        st.info("No pending requests.")

    st.divider()

    # Live trips
    st.markdown("### 🚚 Live Trips & Activity Switch")
    activity_df = ardf[ardf["status"].isin(["Assigned", "Trip Closed"])].head(20) \
        if not ardf.empty else pd.DataFrame()

    if not activity_df.empty:
        for _, r in activity_df.iterrows():
            c1, c2, c3, c4 = st.columns([3, 1.2, 1.8, 1])
            icon = "🟢" if r["status"] == "Assigned" else "✅"
            c1.write(f"{icon} **{r['assigned_vehicle']}** | {r['requested_by']} ➔ {r['destination']}")
            c2.write(f"**{r['status']}**")

            try:
                clean_ts = _safe_to_ist(pd.Series([r["created_at"]])) \
                    .dt.strftime("%d %b, %I:%M %p").iloc[0]
            except Exception:
                clean_ts = "---"
            c3.write(f"🕒 {clean_ts}")

            if r["status"] == "Assigned":
                if c4.button("Close", key=f"close_br{r['id']}", use_container_width=True):
                    conn.table("logistics_requests") \
                        .update({"status": "Trip Closed"}) \
                        .eq("id", r["id"]).execute()
                    clear_operational_cache()
                    st.toast(f"Trip for {r['assigned_vehicle']} is now CLOSED.")
                    st.rerun()
            else:
                c4.write("Done")
    else:
        st.info("No recent trip activity.")

# ── TAB 3: TRIP LOGGER ────────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("📝 Driver Log & Trip Closure")

    active_res = conn.table("logistics_requests") \
        .select("assigned_vehicle, destination, requested_by, created_at") \
        .eq("status", "Assigned").execute()

    if active_res.data:
        active_df = pd.DataFrame(active_res.data)
        active_df["assigned_at"] = _safe_to_ist(active_df["created_at"]) \
            .dt.strftime("%H:%M (%d %b)")
        st.write("**Vehicles currently out:**")
        st.dataframe(
            active_df[["assigned_vehicle", "destination", "requested_by", "assigned_at"]],
            use_container_width=True,
            hide_index=True,
        )

    # Vehicle selection outside the form so start_km reacts immediately
    selected_vehicle = st.selectbox("Vehicle", vehicle_list, key="log_veh_sel")
    default_start_km = get_last_km(selected_vehicle, df)

    with st.form("logistics_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            vehicle  = st.selectbox("Confirm Vehicle", vehicle_list,
                                    index=vehicle_list.index(selected_vehicle), key="log_veh")
            driver   = st.selectbox("Driver Name", staff_list, key="log_driver")
        with col2:
            start_km = st.number_input("Start KM", min_value=0,
                                       value=default_start_km, step=1)
            end_km   = st.number_input("End KM", min_value=0, step=1)
        with col3:
            fuel_qty = st.number_input("Fuel Added (Ltrs)", min_value=0.0, step=0.5)
            auth_by  = st.selectbox("Authorized By", staff_list, key="log_auth")

        location     = st.text_input("Current Location / Final Destination")
        odometer_img = st.camera_input("Capture Odometer Reading")

        if st.form_submit_button("🚀 SUBMIT LOG & CLOSE TRIP"):
            location_clean = location.strip().upper()
            if end_km <= start_km:
                st.warning("End KM must be greater than Start KM.")
            elif not location_clean:
                st.warning("Please enter a location.")
            else:
                finish_time = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
                new_entry = {
                    "timestamp": finish_time,
                    "vehicle":   vehicle,
                    "driver":    driver,
                    "start_km":  start_km,
                    "end_km":    end_km,
                    "distance":  end_km - start_km,
                    "fuel_ltrs": fuel_qty,
                    "location":  location_clean[:200],
                    "auth_by":   auth_by,
                    # NOTE: to store the odometer photo, upload odometer_img.getvalue()
                    # to Supabase Storage here and save the URL in this record.
                }
                try:
                    conn.table("logistics_logs").insert(new_entry).execute()
                    # Close only the specific assigned record for this vehicle
                    conn.table("logistics_requests") \
                        .update({"status": "Trip Closed"}) \
                        .eq("assigned_vehicle", vehicle) \
                        .eq("status", "Assigned") \
                        .execute()
                    clear_operational_cache()
                    st.success(f"✅ Logged at {finish_time} & Trip Closed!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving log: {e}")

# ── TAB 4: ANALYTICS ──────────────────────────────────────────────────────────
with tabs[3]:
    st.subheader("📊 Fleet Performance")
    if not df.empty:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total KM Covered", f"{df['distance'].sum():,.0f}")
        col2.metric("Total Fuel (Ltrs)", f"{df['fuel_ltrs'].sum():,.1f}")
        col3.metric("Trips Logged",      len(df))
        st.dataframe(
            df[["timestamp", "vehicle", "driver", "distance", "fuel_ltrs", "location"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No trip data yet.")

# ── TAB 5: EXPORT & REPORTS ───────────────────────────────────────────────────
with tabs[4]:
    st.subheader("📥 Export Reports")

    target = st.radio(
        "Select Data to Export",
        ["Full Trip Logs", "All Booking Requests"],
        horizontal=True,
        key="export_data_selector",
    )

    if target == "Full Trip Logs":
        t_name, ts_col, ts_is_ist = "logistics_logs",    "timestamp",  True
    else:
        t_name, ts_col, ts_is_ist = "logistics_requests", "created_at", False

    try:
        res_exp = conn.table(t_name).select("*").order(ts_col, desc=True).execute()
        if res_exp.data:
            export_df = pd.DataFrame(res_exp.data)

            if ts_col in export_df.columns:
                if ts_is_ist:
                    # Stored as IST string – parse as-is, no conversion needed
                    export_df[ts_col] = pd.to_datetime(
                        export_df[ts_col], errors="coerce"
                    ).dt.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    # Stored as UTC by Supabase – convert to IST
                    export_df[ts_col] = (
                        _safe_to_ist(export_df[ts_col])
                        .dt.strftime("%Y-%m-%d %H:%M:%S")
                    )

            st.write(f"📊 {len(export_df)} records from `{t_name}` (IST):")
            st.dataframe(export_df, use_container_width=True, hide_index=True)

            csv_data = export_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label=f"💾 Download {target} (CSV)",
                data=csv_data,
                file_name=f"BG_Logistics_{t_name}_{date.today()}.csv",
                mime="text/csv",
                key="final_export_button",
            )
        else:
            st.info(f"No data found in `{t_name}` yet.")

    except Exception as e:
        st.error(f"Export error: {e}")
        st.info(f"Tip: verify that the column `{ts_col}` exists in `{t_name}` on Supabase.")
