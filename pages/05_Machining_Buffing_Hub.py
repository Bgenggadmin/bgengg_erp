import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')

def get_today_ist():
    return datetime.datetime.now(IST).date()
    
# 1. Setup & Style
st.set_page_config(page_title="B&G ERP BETA", layout="wide")
conn = st.connection("supabase", type=SupabaseConnection)

st.markdown("""<style>div.stButton > button { border-radius: 50px; font-weight: 600; }</style>""", unsafe_allow_html=True)

if 'hub' not in st.session_state:
    st.session_state.hub = "Machining Hub"

# --- HUB SELECTION ---
c1, c2, _ = st.columns([1, 1, 2])
if c1.button("⚙️ MACHINING HUB", use_container_width=True, type="primary" if st.session_state.hub == "Machining Hub" else "secondary"):
    st.session_state.hub = "Machining Hub"; st.rerun()
if c2.button("✨ BUFFING HUB", use_container_width=True, type="primary" if st.session_state.hub == "Buffing Hub" else "secondary"):
    st.session_state.hub = "Buffing Hub"; st.rerun()

# --- CONFIGURATION ---
if st.session_state.hub == "Machining Hub":
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_machining_logs", "master_machines", "name", "Machine"
    ACTIVITIES = ["Turning", "Drilling", "Milling", "Keyway", "Dishbending"]
    IS_BUFFING = False
else:
    DB_TABLE, MASTER_TABLE, MASTER_COL, RES_LABEL = "beta_buffing_logs", "master_machines", "name", "Buffing Station"
    ACTIVITIES = ["Rough Buffing", "Mirror Polishing", "Satin Finish", "RA Value Check"]
    IS_BUFFING = True

OP_MASTER, VN_MASTER, VH_MASTER = "master_workers", "beta_vendor_master", "master_vehicles"

# --- 2. Data Fetching ---
def get_all_data():
    try:
        m_data = conn.table(MASTER_TABLE).select(MASTER_COL).execute().data or []
        o_data = conn.table(OP_MASTER).select("name").execute().data or []
        v_raw = conn.table(VN_MASTER).select("vendor_name").execute().data or []
        v_list = [v['vendor_name'] for v in v_raw]
        j_master = conn.table("anchor_projects").select("job_no").execute().data or []
        job_list = sorted(list(set([j['job_no'] for j in j_master if j.get('job_no')])))
        vh_list = [v['reg_no'] for v in (conn.table(VH_MASTER).select("reg_no").execute().data or [])] if not IS_BUFFING else []
        logs = conn.table(DB_TABLE).select("*").order("created_at", desc=True).execute().data or []
        df = pd.DataFrame(logs)
        return [r[MASTER_COL] for r in m_data], [o['name'] for o in o_data], v_list, vh_list, df, job_list
    except Exception as e:
        st.error(f"Sync Error: {e}")
        return [], [], [], [], pd.DataFrame(), []

res_list, op_list, vendor_list, vh_list, df_main, master_jobs = get_all_data()
tabs = st.tabs(["📝 Production Request", "👨‍💻 Incharge Entry Desk", "🚨 Daily Command", "📊 Executive Analytics", "🛠️ Masters"])

# --- TAB 1: REQUEST ---
with tabs[0]:
    st.subheader(f"New {st.session_state.hub} Entry")
    with st.form("req_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        u_no = c1.selectbox("Unit", [1, 2, 3])
        j_code = c1.selectbox("Job Code", [""] + master_jobs) 
        part = c2.text_input("Part Name")
        act = c2.selectbox("Activity", ACTIVITIES)
        req_d = c3.date_input("Required Date")
        prio = c3.selectbox("Priority", ["Low", "Medium", "High", "URGENT"])
        
        if st.form_submit_button("Submit Request"):
            if not j_code or not part:
                st.error("🚨 Selection Required: Job Code and Part Name are mandatory.")
            else:
                payload = {
                    "unit_no": u_no, "job_code": j_code, "part_name": part, "activity_type": act, 
                    "required_date": req_d.isoformat(), "request_date": get_today_ist().isoformat(),
                    "status": "Pending", "priority": prio
                }
                conn.table(DB_TABLE).insert(payload).execute()
                st.success(f"✅ Request Logged: {j_code}")
                st.rerun()

    st.divider()
    if not df_main.empty:
        df_sum = df_main.copy()
        df_sum['required_date'] = pd.to_datetime(df_sum['required_date'], errors='coerce')
        df_sum['Days Left'] = (df_sum['required_date'] - pd.Timestamp(get_today_ist())).dt.days
        u_filt = st.radio("Unit Filter", [1, 2, 3], horizontal=True)
        st.dataframe(df_sum[df_sum['unit_no'] == u_filt][['job_code', 'part_name', 'status', 'priority', 'required_date', 'Days Left']], use_container_width=True, hide_index=True)

# --- TAB 2: INCHARGE ENTRY DESK (UPDATED) ---
with tabs[1]:
    # Filter for jobs that are not Finished
    active = df_main[df_main['status'] != "Finished"].to_dict('records') if not df_main.empty else []
    
    if not active:
        st.info("No active production requests found.")
    
    for job in active:
        # Use a status-based emoji for the expander label
        prio_emoji = "🔴" if job.get('priority') == "URGENT" else "🟡" if job.get('priority') == "High" else "📌"
        
        with st.expander(f"{prio_emoji} {job['job_code']} | {job['part_name']} ({job['status']})"):
            # --- DATE DISPLAY SECTION ---
            # Formatting dates for better readability
            req_dt = job.get('request_date', 'N/A')
            due_dt = job.get('required_date', 'N/A')
            
            d_col1, d_col2, d_col3 = st.columns(3)
            d_col1.markdown(f"**📅 Requested:** {req_dt}")
            d_col2.markdown(f"**🎯 Required:** {due_dt}")
            
            # Add a small countdown/overdue badge
            if due_dt != 'N/A':
                days_left = (pd.to_datetime(due_dt).date() - get_today_ist()).days
                if days_left < 0:
                    d_col3.error(f"⚠️ {abs(days_left)} Days Overdue")
                else:
                    d_col3.success(f"⏳ {days_left} Days Remaining")
            
            st.divider()

            # --- ENTRY SECTION ---
            c1, c2 = st.columns(2)
            dr = c1.text_input("Delay Reason", value=job.get('delay_reason') or '', key=f"dr_{job['id']}")
            inote = c2.text_area("Incharge Note", value=job.get('intervention_note') or '', key=f"in_{job['id']}")
            
            if job['status'] == "Pending":
                mode = st.radio("Allotment", ["In-House", "Outsource"], key=f"rad_{job['id']}", horizontal=True)
                if mode == "In-House":
                    m = st.selectbox(f"Assign {RES_LABEL}", res_list, key=f"sel_{job['id']}")
                    # Toggle multiselect for Buffing Hub, single select for Machining
                    o = st.multiselect("Assign Operators", op_list, key=f"o_{job['id']}") if IS_BUFFING else st.selectbox("Assign Operator", op_list, key=f"o_{job['id']}")
                    
                    if st.button("🚀 Start Production", key=f"btn_{job['id']}", use_container_width=True):
                        operator_val = ", ".join(o) if isinstance(o, list) else o
                        conn.table(DB_TABLE).update({
                            "status": "In-House", 
                            "machine_id": m, 
                            "operator_id": operator_val, 
                            "delay_reason": dr, 
                            "intervention_note": inote
                        }).eq("id", job['id']).execute()
                        st.rerun()
                else: 
                    v = st.selectbox("Select Vendor", vendor_list, key=f"v_{job['id']}")
                    st.markdown("---")
                    c_gp, c_bn = st.columns(2)
                    gp_no = c_gp.text_input("Gate Pass No.", value=job.get('gate_pass_no') or '', key=f"gp_{job['id']}")
                    bill_no = c_bn.text_input("Bill No.", value=job.get('bill_no') or '', key=f"bn_{job['id']}")
                    
                    if st.button("🚚 Dispatch to Vendor", key=f"d_{job['id']}", use_container_width=True):
                        if not gp_no: 
                            st.warning("Please enter Gate Pass No.")
                        else:
                            conn.table(DB_TABLE).update({
                                "status": "Outsourced", 
                                "vendor_id": v, 
                                "delay_reason": dr, 
                                "intervention_note": inote, 
                                "gate_pass_no": gp_no, 
                                "bill_no": bill_no
                            }).eq("id", job['id']).execute()
                            st.rerun()
            
            # Allow "Finish" for any job already in progress (In-House or Outsourced)
            elif job['status'] in ["In-House", "Outsourced"]:
                if st.button("🏁 Mark as Finished", key=f"f_{job['id']}", use_container_width=True, type="primary"):
                    conn.table(DB_TABLE).update({
                        "status": "Finished", 
                        "delay_reason": dr, 
                        "intervention_note": inote
                    }).eq("id", job['id']).execute()
                    st.rerun()

# =====================================================================
# --- TAB 3: DAILY COMMAND CENTRE  (NEW) ---
# Purpose: one screen the founder/incharge opens every morning.
# Answers 3 questions fast: What moved yesterday? What is burning?
# What falls due today/next 3 days?
# =====================================================================
with tabs[2]:

    # ---------------- tiny helpers ----------------
    def _clean(v):
        """Return a safe display string. Treats None / NaN / the literal
        text 'nan' (a legacy import artefact in delay_reason) as blank,
        and neutralises < > so stray characters cannot break our HTML."""
        if v is None:
            return ""
        s = str(v).strip()
        if s.lower() in ("nan", "none", "nat"):
            return ""
        return s.replace("<", "&lt;").replace(">", "&gt;")

    def kpi_tile(col, label, value, colour, sub=""):
        """Draw one large coloured metric tile inside a given column.
        NOTE: the HTML is emitted as ONE unbroken line on purpose.
        Indented multi-line HTML gets treated by Streamlit as a markdown
        code block and shows up as raw text instead of rendering."""
        col.markdown(
            f"<div style='background:{colour};border-radius:14px;padding:16px 8px;"
            f"text-align:center;color:#fff;box-shadow:0 2px 6px rgba(0,0,0,.18)'>"
            f"<div style='font-size:34px;font-weight:800;line-height:1'>{value}</div>"
            f"<div style='font-size:13px;font-weight:700;letter-spacing:.3px;margin-top:4px'>{label}</div>"
            f"<div style='font-size:11px;opacity:.85;margin-top:2px'>{sub}&nbsp;</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    def where_text(row):
        """Human readable 'where is this job sitting right now'."""
        if row.get("status") == "Outsourced":
            return "🚚 " + (_clean(row.get("vendor_id")) or "Vendor not set")
        mc = _clean(row.get("machine_id"))
        op = _clean(row.get("operator_id"))
        if mc or op:
            return f"⚙️ {mc or '-'} · 👷 {op or '-'}"
        return "⏳ Not allotted"

    today = get_today_ist()
    yday = today - datetime.timedelta(days=1)

    st.subheader(f"🚨 {st.session_state.hub} — Daily Command Centre")
    st.caption(f"Live as on {today.strftime('%d %b %Y')} (IST)  •  “Yesterday” = {yday.strftime('%d %b %Y')}")

    if df_main.empty:
        st.info("No production data yet for this hub.")
    else:
        d = df_main.copy()

        # ---------- 1. Normalise every date column ----------
        # required_date / request_date are plain DATE columns in Postgres.
        d["required_date"] = pd.to_datetime(d["required_date"], errors="coerce").dt.date
        # created_at is a timestamptz stored in UTC. Convert to IST FIRST,
        # then take the calendar date - otherwise anything logged after
        # 5:30 AM IST... (i.e. an evening entry) can land on the wrong day.
        # format="ISO8601" is essential: Supabase returns timestamps with
        # VARIABLE microsecond precision ("...:59.30701+00" vs "...:00+00").
        # Without it pandas locks onto the format of the first row and
        # silently turns every other row into NaT - rows just vanish.
        d["created_day"] = (
            pd.to_datetime(d["created_at"], format="ISO8601", errors="coerce", utc=True)
            .dt.tz_convert(IST).dt.date
        )

        # These two only exist AFTER the schema patch. Code works either way.
        has_fin = "finished_at" in d.columns
        has_start = "started_at" in d.columns
        if has_fin:
            d["finished_day"] = (
                pd.to_datetime(d["finished_at"], format="ISO8601", errors="coerce", utc=True)
                .dt.tz_convert(IST).dt.date
            )
        if has_start:
            d["started_day"] = (
                pd.to_datetime(d["started_at"], format="ISO8601", errors="coerce", utc=True)
                .dt.tz_convert(IST).dt.date
            )

        # ---------- 2. Split open vs finished, compute lateness ----------
        open_df = d[d["status"] != "Finished"].copy()

        def days_late(dt):
            """Positive = overdue by N days. 0 = due today. Negative = time left."""
            return (today - dt).days if pd.notna(dt) else None

        open_df["days_late"] = open_df["required_date"].apply(days_late)
        # age = how long this request has been alive in the system
        open_df["age_days"] = open_df["created_day"].apply(
            lambda x: (today - x).days if pd.notna(x) else None
        )

        overdue = open_df[open_df["days_late"].fillna(-999) > 0].sort_values(
            "days_late", ascending=False
        )
        due_today = open_df[open_df["days_late"] == 0]
        due_soon = open_df[open_df["days_late"].fillna(-999).between(-3, -1)]
        no_target = open_df[open_df["required_date"].isna()]

        # ---------- 3. KPI STRIP ----------
        k = st.columns(6)
        kpi_tile(k[0], "OVERDUE", len(overdue), "#B71C1C",
                 f"worst {int(overdue['days_late'].max())}d" if len(overdue) else "clear")
        kpi_tile(k[1], "DUE TODAY", len(due_today), "#E65100", "must close")
        kpi_tile(k[2], "DUE IN 3 DAYS", len(due_soon), "#F9A825", "plan now")
        kpi_tile(k[3], "OPEN JOBS", len(open_df), "#1565C0", "total live")

        if has_fin:
            fin_y = d[(d["status"] == "Finished") & (d["finished_day"] == yday)]
            kpi_tile(k[4], "CLOSED YDAY", len(fin_y), "#2E7D32", "completed")
        else:
            fin_y = pd.DataFrame()
            kpi_tile(k[4], "CLOSED YDAY", "—", "#616161", "needs patch")

        new_y = d[d["created_day"] == yday]
        kpi_tile(k[5], "RAISED YDAY", len(new_y), "#4527A0", "new requests")

        st.divider()

        # ---------- 4. RED ZONE : overdue jobs, worst first ----------
        st.markdown("#### 🔴 RED ZONE — Overdue Work Orders")
        if overdue.empty:
            st.success("✅ Nothing overdue in this hub. All target dates are being met.")
        else:
            rows = []
            for _, r in overdue.iterrows():
                dl = int(r["days_late"])
                # Colour band by severity so the eye jumps to the worst ones
                if dl >= 7:
                    bg, bar = "#7F0000", "#FF5252"
                elif dl >= 3:
                    bg, bar = "#C62828", "#FF8A80"
                else:
                    bg, bar = "#EF6C00", "#FFCC80"
                reason = _clean(r.get("delay_reason"))
                note = _clean(r.get("intervention_note"))
                tail = f" · 📝 {reason or note}" if (reason or note) else ""
                rows.append(
                    f"<div style='background:{bg};color:#fff;border-left:8px solid {bar};"
                    f"border-radius:8px;padding:8px 12px;margin-bottom:6px;"
                    f"display:flex;align-items:center;gap:12px;flex-wrap:wrap'>"
                    f"<div style='font-size:20px;font-weight:800;min-width:78px'>{dl}d LATE</div>"
                    f"<div style='flex:1;min-width:240px'>"
                    f"<b>{_clean(r.get('job_code'))}</b> — {_clean(r.get('part_name'))}"
                    f"<div style='font-size:12px;opacity:.9'>Unit {_clean(r.get('unit_no'))} · "
                    f"{_clean(r.get('activity_type'))} · {where_text(r)}{tail}</div></div>"
                    f"<div style='font-size:12px;text-align:right;min-width:120px'>"
                    f"Target {r['required_date'].strftime('%d %b')}<br>"
                    f"Priority {_clean(r.get('priority'))}</div></div>"
                )
            st.markdown("".join(rows), unsafe_allow_html=True)

            # Where is the pain concentrated? In-house vs vendor.
            by_mode = overdue["status"].value_counts()
            st.caption(
                "Breakdown: "
                + " · ".join([f"**{s}** {n}" for s, n in by_mode.items()])
            )

        st.divider()

        # ---------- 5. TODAY + NEXT 3 DAYS ----------
        c_a, c_b = st.columns(2)
        with c_a:
            st.markdown("##### 🟠 Falling Due TODAY")
            if due_today.empty:
                st.caption("Nothing due today.")
            else:
                st.dataframe(
                    due_today[["job_code", "part_name", "unit_no", "activity_type", "status"]],
                    hide_index=True, use_container_width=True,
                )
        with c_b:
            st.markdown("##### 🟡 Due within 3 Days")
            if due_soon.empty:
                st.caption("Nothing due in the next 3 days.")
            else:
                nxt = due_soon.copy()
                nxt["Days Left"] = -nxt["days_late"]
                st.dataframe(
                    nxt[["job_code", "part_name", "unit_no", "Days Left", "status"]]
                    .sort_values("Days Left"),
                    hide_index=True, use_container_width=True,
                )

        st.divider()

        # ---------- 6. YESTERDAY'S MOVEMENT ----------
        st.markdown("#### 🕐 Yesterday's Movement")
        y1, y2 = st.columns(2)

        with y1:
            st.markdown("##### 🏁 Closed Yesterday")
            if not has_fin:
                st.warning(
                    "Completion tracking is not switched on yet. The table stores a "
                    "`status` of 'Finished' but never records **when** it was finished, "
                    "so yesterday's output cannot be measured. Apply the schema patch "
                    "(2 columns) to light this panel up."
                )
            elif fin_y.empty:
                st.caption("No jobs were closed yesterday.")
            else:
                st.dataframe(
                    fin_y[["job_code", "part_name", "unit_no", "activity_type", "operator_id"]],
                    hide_index=True, use_container_width=True,
                )
                st.caption(f"👷 Operators involved: {fin_y['operator_id'].dropna().nunique()}")

        with y2:
            st.markdown("##### 🆕 Raised Yesterday")
            if new_y.empty:
                st.caption("No new requests were raised yesterday.")
            else:
                st.dataframe(
                    new_y[["job_code", "part_name", "unit_no", "activity_type", "priority", "status"]],
                    hide_index=True, use_container_width=True,
                )

        if has_start:
            st.markdown("##### 🚀 Put on Machine / Dispatched Yesterday")
            st_y = d[d.get("started_day") == yday]
            if st_y.empty:
                st.caption("Nothing was started yesterday.")
            else:
                st.dataframe(
                    st_y[["job_code", "part_name", "unit_no", "status", "machine_id", "operator_id", "vendor_id"]],
                    hide_index=True, use_container_width=True,
                )

        st.divider()

        # ---------- 7. VENDOR WATCH — material lying outside the factory ----------
        out_open = open_df[open_df["status"] == "Outsourced"]
        if not out_open.empty:
            st.markdown("#### 🚚 Vendor Watch — Material Outside the Factory")
            v = out_open.copy()
            v["Days Out"] = v["age_days"]
            v["Late By"] = v["days_late"].apply(lambda x: max(x, 0) if x is not None else 0)
            vend = (
                v.groupby("vendor_id")
                .agg(Jobs=("id", "count"), Overdue=("Late By", lambda s: int((s > 0).sum())),
                     Worst=("Late By", "max"))
                .reset_index().sort_values("Overdue", ascending=False)
            )
            st.dataframe(
                vend, hide_index=True, use_container_width=True,
                column_config={"vendor_id": "Vendor", "Worst": "Worst Delay (days)"},
            )
            st.caption("Chase the top row first — that vendor is holding the most delayed material.")

        # ---------- 8. UNIT-WISE PRESSURE + housekeeping ----------
        st.markdown("#### 🏢 Unit-wise Pressure")
        u_cols = st.columns(3)
        for i, u in enumerate([1, 2, 3]):
            u_open = len(open_df[open_df["unit_no"] == u])
            u_late = len(overdue[overdue["unit_no"] == u])
            u_cols[i].metric(f"Unit {u}", f"{u_open} open",
                             delta=f"{u_late} overdue" if u_late else "clear",
                             delta_color="inverse" if u_late else "normal")

        stale = open_df[open_df["age_days"].fillna(0) > 14]
        if not stale.empty or not no_target.empty:
            with st.expander(f"🧹 Housekeeping — {len(stale)} ageing (>14 days) · {len(no_target)} without target date"):
                if not stale.empty:
                    st.markdown("**Open more than 14 days — close them or state why**")
                    st.dataframe(
                        stale[["job_code", "part_name", "unit_no", "status", "age_days"]]
                        .sort_values("age_days", ascending=False),
                        hide_index=True, use_container_width=True,
                    )
                if not no_target.empty:
                    st.markdown("**No target date set — these are invisible to every delay report**")
                    st.dataframe(
                        no_target[["job_code", "part_name", "unit_no", "status"]],
                        hide_index=True, use_container_width=True,
                    )

        st.download_button(
            "📥 Export Today's Action List (overdue + due today)",
            pd.concat([overdue, due_today])[
                ["job_code", "part_name", "unit_no", "activity_type", "status",
                 "priority", "required_date", "days_late", "delay_reason"]
            ].to_csv(index=False).encode("utf-8"),
            f"BG_{st.session_state.hub.replace(' ', '_')}_ActionList_{today}.csv",
            "text/csv",
        )

# --- TAB 4: EXECUTIVE ANALYTICS ---
with tabs[3]:
    st.subheader(f"📊 {st.session_state.hub} Executive Dashboard")
    if not df_main.empty:
        df_ana = df_main.copy()
        df_ana['required_date'] = pd.to_datetime(df_ana['required_date'], errors='coerce').dt.date
        today = get_today_ist()

        # 1. Health Logic
        def check_delay(row):
            if row['status'] != "Finished" and row['required_date'] and row['required_date'] < today:
                return "🚩 DELAYED"
            return "✅ On Track"
        df_ana['Health'] = df_ana.apply(check_delay, axis=1)

        # 2. Top-Level Metrics
        total_active = len(df_ana[df_ana['status'] != "Finished"])
        delayed_df = df_ana[df_ana['Health'] == "🚩 DELAYED"]
        delayed_count = len(delayed_df)
        ontrack_count = total_active - delayed_count

        m1, m2, m3 = st.columns(3)
        m1.metric("Active Work Orders", total_active)
        m2.metric("Critical Delays", delayed_count, delta=f"{delayed_count} overdue", delta_color="inverse")
        m3.metric("Healthy Jobs", ontrack_count)
        
        st.divider()

        # 3. Unit-wise Summary Section
        st.markdown("#### 🏢 Unit-wise Overdue Analysis")
        if delayed_count > 0:
            unit_delay = delayed_df.groupby('unit_no').size().reset_index(name='Count')
            # Ensure all units 1, 2, 3 are present for the chart
            all_units = pd.DataFrame({'unit_no': [1, 2, 3]})
            unit_delay = all_units.merge(unit_delay, on='unit_no', how='left').fillna(0)
            
            st.bar_chart(unit_delay.set_index('unit_no'), height=200, color="#FF4B4B")
        else:
            st.success("🎉 All units are currently on track!")

        st.divider()

        # 4. Advanced Filtering
        c_f1, c_f2 = st.columns(2)
        search_q = c_f1.text_input("🔍 Search Job/Part", "").lower()
        status_f = c_f2.multiselect("Filter by Status", sorted(df_ana['status'].unique()))

        if search_q:
            df_ana = df_ana[df_ana['job_code'].str.lower().str.contains(search_q) | df_ana['part_name'].str.lower().str.contains(search_q)]
        if status_f:
            df_ana = df_ana[df_ana['status'].isin(status_f)]

        # 5. UI: Table Rendering
        display_cols = ['Health', 'unit_no', 'job_code', 'part_name', 'activity_type', 'operator_id', 'status', 'priority', 'required_date', 'intervention_note', 'delay_reason']
        existing_cols = [c for c in display_cols if c in df_ana.columns]
        
        st.dataframe(
            df_ana[existing_cols], 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Health": st.column_config.TextColumn("Status Health"),
                "unit_no": "Unit", "job_code": "Job Code", "part_name": "Part Name",
                "activity_type": "Process", "operator_id": "Operators", "status": "Status",
                "priority": "Priority", "required_date": "Target Date",
                "intervention_note": "Incharge Remarks", "delay_reason": "Delay Reason"
            }
        )
        st.download_button("📥 Export CSV", df_ana[existing_cols].to_csv(index=False).encode('utf-8'), "BG_ERP_Report.csv", "text/csv")
    else: st.info("No data available.")

# --- TAB 5: MASTERS ---
with tabs[4]:
    m_opt = {MASTER_TABLE: "Machine/Station", OP_MASTER: "Operator", VN_MASTER: "Vendor"}
    if not IS_BUFFING: m_opt[VH_MASTER] = "Vehicle"
    sel = st.segmented_control("Registry", options=list(m_opt.keys()), format_func=lambda x: m_opt[x], default=MASTER_TABLE)
    col_name = "vendor_name" if sel == VN_MASTER else "reg_no" if sel == VH_MASTER else "name"
    v_col, a_col = st.columns([2, 1])
    with v_col:
        r = conn.table(sel).select("*").execute().data
        if r: st.dataframe(pd.DataFrame(r)[[col_name]], use_container_width=True)
    with a_col:
        new_v = st.text_input(f"New {m_opt[sel]}")
        if st.button("Register") and new_v:
            conn.table(sel).insert({col_name: new_v}).execute(); st.rerun()
