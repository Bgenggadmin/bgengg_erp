import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime
import pytz
import base64
from io import BytesIO
from PIL import Image

# --- 1. SETUP ---
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="B&G Maintenance Master", layout="wide")

try:
    conn = st.connection("supabase", type=SupabaseConnection)
except Exception as e:
    st.error("❌ Supabase Connection Failed!"); st.stop()

# --- 2. DYNAMIC MASTER DATA ---
@st.cache_data(ttl=600)
def get_mdm_list(table, col):
    try:
        res = conn.table(table).select(col).order(col).execute()
        return [item[col] for item in res.data] if res.data else []
    except: return []

@st.cache_data(ttl=60) 
def get_spares_with_stock(machine_name):
    if not machine_name: return []
    try:
        m_res = conn.table("master_machines").select("category").eq("name", machine_name).execute()
        category = m_res.data[0]['category'] if m_res.data else "ALL"
        s_res = conn.table("master_spares").select("part_name, stock_qty")\
            .or_(f"machine_category.eq.{category},machine_category.eq.ALL").execute()
        if s_res.data:
            return [f"{item['part_name']} (Qty: {item['stock_qty']})" if item['stock_qty'] > 0 
                    else f"{item['part_name']} (OUT OF STOCK)" for item in s_res.data]
        return []
    except: return []

# --- 2b. MACHINE MASTER HELPERS ---
@st.cache_data(ttl=600)
def get_machines_full():
    try:
        res = conn.table("master_machines").select("*").order("name").execute()
        return res.data or []
    except Exception:
        return []

@st.cache_data(ttl=60)
def get_log_counts():
    try:
        res = conn.table("maintenance_logs").select("equipment").execute()
        if not res.data:
            return {}
        return pd.DataFrame(res.data)["equipment"].value_counts().to_dict()
    except Exception:
        return {}

def machine_filter(query, row):
    if row.get("id") is not None:
        return query.eq("id", row["id"])
    return query.eq("name", row["name"])

# Pre-fetch lists
machine_list = get_mdm_list("master_machines", "name")
staff_list = get_mdm_list("master_staff", "name")

st.title("🔧 B&G Maintenance Master")

# --- 3. TABS STRUCTURE ---
tab_entry, tab_history, tab_master = st.tabs(["📝 New Log Entry", "📜 History & Alerts", "🛠️ Machine Master"])

# --- 4. TAB: NEW LOG ENTRY ---
with tab_entry:
    # --- FORM SECTION ---
    with st.form("maint_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            equipment = st.selectbox("Select Machine", machine_list if machine_list else ["No Machines Found"])
            technician = st.selectbox("Technician", staff_list if staff_list else ["Select Staff"])
            
            suggested_spares = get_spares_with_stock(equipment)
            spares_used = st.multiselect("🔧 Select Spares Used", suggested_spares)
            
        with col2:
            m_type = st.selectbox("Type", ["Breakdown Repair", "Preventive (PM)", "Spare Replacement"])
            status = st.radio("Post-Service Status", ["🟢 Operational", "🔴 Down"], horizontal=True)
        
        remarks_input = st.text_area("Work Details / Additional Notes")
        cam_photo = st.camera_input("Capture Proof")

        if st.form_submit_button("🚀 Submit Log"):
            if equipment and (remarks_input or spares_used):
                img_str = "" 
                if cam_photo:
                    img = Image.open(cam_photo); img.thumbnail((400, 400))
                    buf = BytesIO(); img.save(buf, format="JPEG", quality=50)
                    img_str = base64.b64encode(buf.getvalue()).decode()

                clean_spares = [s.split(" (")[0] for s in spares_used]
                final_remarks = f"SPARES: {', '.join(clean_spares)} | NOTES: {remarks_input}"

                new_row = {
                    "created_at": datetime.now(IST).strftime('%Y-%m-%d %H:%M'),
                    "equipment": equipment, 
                    "technician": technician,
                    "m_type": m_type, 
                    "status": status, 
                    "remarks": final_remarks, 
                    "photo": img_str
                }
                
                try:
                    conn.table("maintenance_logs").insert(new_row).execute()
                    st.cache_data.clear()
                    st.success("✅ Log Saved Successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")

    # --- NEW: RECENT LOGS SUMMARY (Under the Form) ---
    st.divider()
    st.subheader("📋 Recent Submissions")
    try:
        # Fetch only the last 5 entries for a quick preview
        recent_res = conn.table("maintenance_logs").select("created_at, equipment, technician, m_type, status")\
            .order("created_at", desc=True).limit(5).execute()
        
        if recent_res.data:
            summary_df = pd.DataFrame(recent_res.data)
            # Display as a clean table
            st.dataframe(
                summary_df, 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "created_at": "Date/Time",
                    "equipment": "Machine",
                    "technician": "Staff",
                    "m_type": "Type",
                    "status": "Final Status"
                }
            )
        else:
            st.info("No recent logs to display.")
    except Exception as e:
        st.caption(f"Could not load quick summary: {e}")

# --- 5. TAB: HISTORY & ALERTS ---
with tab_history:
    try:
        res = conn.table("maintenance_logs").select("*").order("created_at", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df['created_at'] = pd.to_datetime(df['created_at'])

            # --- ALERTS ---
            st.subheader("⚠️ Maintenance Alerts")
            pm_data = df[df['m_type'] == 'Preventive (PM)']
            overdue_machines = []
            
            for m in machine_list:
                latest_pm = pm_data[pm_data['equipment'] == m]
                if latest_pm.empty:
                    overdue_machines.append({"Machine": m, "Last PM": "Never", "Days": ">30"})
                else:
                    last_date = latest_pm.iloc[0]['created_at'].replace(tzinfo=None)
                    days_since = (datetime.now() - last_date).days
                    if days_since > 30:
                        overdue_machines.append({"Machine": m, "Last PM": last_date.strftime('%Y-%m-%d'), "Days": days_since})

            if overdue_machines:
                st.warning(f"Found {len(overdue_machines)} machines overdue for PM.")
                st.dataframe(pd.DataFrame(overdue_machines), use_container_width=True, hide_index=True)
            else:
                st.success("All machines are up to date.")

            # --- METRICS ---
            st.divider()
            st.subheader("📊 Performance Summary")
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Total Records", len(df))
            s2.metric("Breakdowns", len(df[df['m_type'] == 'Breakdown Repair']))
            s3.metric("PMs Done", len(pm_data))
            
            # Machine Status Logic
            current_down = len(df.sort_values('created_at').groupby('equipment').tail(1).query("status == '🔴 Down'"))
            s4.metric("Currently Down", current_down, delta_color="inverse")

            # --- EXPORT & TABLE ---
            csv = df.drop(columns=['photo', 'id']).to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV Report", csv, "maint_report.csv", "text/csv")
            st.dataframe(df.drop(columns=["photo", "id"]), use_container_width=True, hide_index=True)
            
        else:
            st.info("No records found.")
    except Exception as e:
        st.error(f"Error loading history: {e}")

# --- 6. TAB: MACHINE MASTER ---
with tab_master:
    st.subheader("🛠️ Machine Master")
    st.caption("Machines added here feed the 'Select Machine' dropdown, the spares matching, and the PM alerts.")

    machines = get_machines_full()
    log_counts = get_log_counts()
    existing_names = [m["name"] for m in machines]
    existing_cats = sorted({m.get("category") for m in machines if m.get("category")})
    NEW_CAT = "➕ New category..."

    # --- 6a. ADD A MACHINE ---
    with st.expander("➕ Add New Machine", expanded=not machines):
        with st.form("add_machine_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                add_name = st.text_input("Machine Name *", placeholder="e.g. Lathe-02")
            with c2:
                add_cat_pick = st.selectbox("Category *", existing_cats + [NEW_CAT])
            add_cat_new = st.text_input("New category name", placeholder=f"Fill this only if you picked '{NEW_CAT}'")

            if st.form_submit_button("Save Machine"):
                name_clean = add_name.strip()
                cat_clean = add_cat_new.strip() if add_cat_pick == NEW_CAT else add_cat_pick

                # Name is the link key to maintenance_logs, so it must be unique and non-blank.
                if not name_clean:
                    st.error("Machine name cannot be blank.")
                elif not cat_clean:
                    st.error("Category cannot be blank.")
                elif name_clean.lower() in [n.lower() for n in existing_names]:
                    st.error(f"'{name_clean}' already exists. Machine names must be unique.")
                else:
                    try:
                        conn.table("master_machines").insert(
                            {"name": name_clean, "category": cat_clean}
                        ).execute()
                        st.cache_data.clear()
                        st.success(f"✅ Added '{name_clean}'.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Add failed: {e}")

    st.divider()

    if not machines:
        st.info("No machines in the master yet — add the first one above.")
    else:
        # --- 6b. CURRENT LIST ---
        st.markdown("**Current Machines**")
        list_df = pd.DataFrame([
            {
                "Machine": m["name"],
                "Category": m.get("category") or "—",
                "Logs": log_counts.get(m["name"], 0),
            }
            for m in machines
        ])
        st.dataframe(list_df, use_container_width=True, hide_index=True)

        # --- 6c. EDIT / REMOVE ---
        st.divider()
        st.markdown("**Edit or Remove a Machine**")
        pick = st.selectbox("Select machine", existing_names, key="mm_pick")
        row = next(m for m in machines if m["name"] == pick)
        # Tie widget keys to the selected row, otherwise Streamlit keeps the
        # previous machine's text in the boxes when you change the selection.
        row_key = row.get("id") or row["name"]
        used = log_counts.get(pick, 0)

        e1, e2 = st.columns(2)
        with e1:
            up_name = st.text_input("Machine Name", value=row["name"], key=f"mm_name_{row_key}")
        with e2:
            cur_cat = row.get("category") or ""
            cat_opts = existing_cats + [NEW_CAT]
            cat_idx = cat_opts.index(cur_cat) if cur_cat in cat_opts else len(cat_opts) - 1
            up_cat_pick = st.selectbox("Category", cat_opts, index=cat_idx, key=f"mm_cat_{row_key}")
        up_cat_new = st.text_input(
            "New category name", key=f"mm_catnew_{row_key}",
            placeholder=f"Fill this only if you picked '{NEW_CAT}'"
        )

        cascade = False
        if used > 0:
            st.caption(f"ℹ️ '{pick}' has {used} maintenance log(s). Logs store the machine NAME, not its ID.")
            cascade = st.checkbox(
                f"If I rename it, also update those {used} log(s) to the new name",
                value=True, key=f"mm_cascade_{row_key}"
            )

        if st.button("💾 Save Changes", key=f"mm_save_{row_key}"):
            new_name = up_name.strip()
            new_cat = up_cat_new.strip() if up_cat_pick == NEW_CAT else up_cat_pick
            other_names = [n.lower() for n in existing_names if n != pick]

            if not new_name:
                st.error("Machine name cannot be blank.")
            elif not new_cat:
                st.error("Category cannot be blank.")
            elif new_name.lower() in other_names:
                st.error(f"'{new_name}' already exists.")
            else:
                try:
                    machine_filter(
                        conn.table("master_machines").update({"name": new_name, "category": new_cat}),
                        row
                    ).execute()
                    # Keep history pointing at the machine after a rename.
                    if new_name != pick and cascade and used > 0:
                        conn.table("maintenance_logs").update(
                            {"equipment": new_name}
                        ).eq("equipment", pick).execute()
                    st.cache_data.clear()
                    st.success(f"✅ Saved '{new_name}'.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Update failed: {e}")

        with st.expander("🗑️ Remove this machine"):
            if used > 0:
                st.warning(
                    f"'{pick}' has {used} maintenance log(s). Deleting the machine does NOT delete those logs — "
                    "they stay visible in History, but the machine disappears from the dropdown and from PM alerts."
                )
            confirm_del = st.checkbox(f"Yes, remove '{pick}' from the master", key=f"mm_del_{row_key}")
            if st.button("🗑️ Delete Machine", key=f"mm_delbtn_{row_key}", disabled=not confirm_del):
                try:
                    machine_filter(conn.table("master_machines").delete(), row).execute()
                    st.cache_data.clear()
                    st.success(f"Removed '{pick}'.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Delete failed: {e}")
