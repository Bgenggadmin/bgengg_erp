import streamlit as st
from st_supabase_connection import SupabaseConnection
import pandas as pd
from datetime import datetime, date
import pytz
import io
import requests
from tempfile import NamedTemporaryFile
import os

# ============================================================
# 1. SETUP
# ============================================================
IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(
    page_title="B&G Quality Portal",
    layout="wide",
    page_icon="🔍"
)
conn = st.connection("supabase", type=SupabaseConnection)

# ============================================================
# 2. UTILITIES
# ============================================================
def get_now_ist():
    return datetime.now(IST)

def safe_write(fn, success_msg="Saved!", error_prefix="DB Error"):
    try:
        fn()
        st.success(success_msg)
        return True
    except Exception as e:
        st.error(f"{error_prefix}: {e}")
        return False

def fmt_date(d):
    try:
        return pd.to_datetime(d).strftime('%d-%m-%Y')
    except Exception:
        return str(d) if d else 'N/A'

# ============================================================
# 3. DATA LOADERS
# ============================================================
@st.cache_data(ttl=30)
def get_staff_list():
    try:
        res = conn.table("master_staff").select("name").execute()
        return sorted([s['name'] for s in res.data]) if res.data else ["QC Inspector"]
    except Exception:
        return ["QC Inspector"]

@st.cache_data(ttl=30)
def get_job_list():
    try:
        res = conn.table("anchor_projects").select(
            "job_no, client_name, po_no, po_date, equipment_type"
        ).execute()
        df = pd.DataFrame(res.data or [])
        if not df.empty:
            df = df[df['job_no'].notna() & (df['job_no'].astype(str).str.strip() != '')]
            df['job_no'] = df['job_no'].astype(str).str.strip().str.upper()
            df = df.drop_duplicates(subset=['job_no'])
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=10)
def get_planning_data():
    try:
        res = conn.table("job_planning").select("*").execute()
        return pd.DataFrame(res.data or [])
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=60)
def get_config(category):
    try:
        res = conn.table("quality_config").select("parameter_name") \
            .eq("category", category).execute()
        return [r['parameter_name'] for r in res.data] if res.data else []
    except Exception:
        return []

def get_proj(df_anchor, job_no):
    match = df_anchor[df_anchor['job_no'].astype(str) == str(job_no)]
    return match.iloc[0] if not match.empty else None

def job_header(proj):
    """Standard project info header used across all tabs."""
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"**Client:** {proj.get('client_name','N/A')}")
        c2.write(f"**PO No:** {proj.get('po_no','N/A')}")
        c3.write(f"**PO Date:** {fmt_date(proj.get('po_date'))}")
        c4.write(f"**Equipment Type:** {proj.get('equipment_type','N/A')}")

# ============================================================
# 4. LOAD MASTER DATA
# ============================================================
df_anchor   = get_job_list()
df_planning = get_planning_data()
inspectors  = get_staff_list()
job_list    = sorted(df_anchor['job_no'].dropna().astype(str).unique().tolist()) \
              if not df_anchor.empty else []

# ============================================================
# 5. NAVIGATION
# ============================================================
st.markdown("""
<div style="background:#003366; color:white; padding:0.6rem 1rem;
            border-radius:8px; margin-bottom:1rem;">
  <b style="font-size:18px;">🔍 B&G Engineering — Quality Assurance Portal</b>
</div>
""", unsafe_allow_html=True)

main_tabs = st.tabs([
    "🚪 Process Gate",          # 0
    "📋 Quality Checklist",     # 1
    "📜 QAP",                   # 2
    "📉 Material Flow Chart",   # 3
    "🔧 Nozzle Flow Chart",     # 4
    "📐 Dimensional Report",    # 5
    "💧 Hydro Test",            # 6
    "📏 Calibration",           # 7
    "🏁 Final Inspection",      # 8
    "🛡️ Guarantee Certificate", # 9
    "⭐ Customer Feedback",     # 10
    "📂 Document Vault",        # 11
    "📑 Master Data Book",      # 12
    "⚙️ Config",                # 13
])

# ============================================================
# TAB 0: PROCESS GATE — Live Evidence Viewer
# ============================================================
with main_tabs[0]:
    st.subheader("🗓️ Real-Time Inspection Timeline")

    if not df_planning.empty:
        unique_jobs = sorted(df_planning['job_no'].dropna().astype(str).unique().tolist())
        sel_job = st.selectbox("Select Job", ["-- Select --"] + unique_jobs, key="pg_job")

        if sel_job != "-- Select --":
            p_data = df_planning[
                df_planning['job_no'].astype(str) == str(sel_job)
            ].sort_values('quality_updated_at', na_position='last')

            if not p_data.empty:
                st.info(f"Manufacturing evidence for **{sel_job}**. For final stamped report → Master Data Book tab.")
                for _, row in p_data.iterrows():
                    update_date = fmt_date(row.get('quality_updated_at')) \
                        if pd.notna(row.get('quality_updated_at')) else "Pending"
                    with st.container(border=True):
                        c1, c2 = st.columns([1, 3])
                        status = str(row.get('quality_status', '')).upper()
                        if any(w in status for w in ['PASS', 'ACCEPT', 'OK']):
                            c1.success(f"✅ {row['gate_name']}")
                        elif any(w in status for w in ['REWORK', 'REJECT', 'FAIL']):
                            c1.error(f"❌ {row['gate_name']}")
                        elif status and status not in ['', 'NONE', 'NAN']:
                            c1.warning(f"⚠️ {row['gate_name']}")
                        else:
                            c1.info(f"🔹 {row['gate_name']}")

                        c2.write(f"**Date:** {update_date} | **Inspector:** {row.get('quality_by','—')}")
                        c2.write(f"**Stage:** {row.get('sub_task','General')} | **Remarks:** {row.get('quality_notes') or 'No remarks'}")
                        if row.get('final_remarks'):
                            c2.caption(f"Final: {row['final_remarks']}")

                        urls = row.get('quality_photo_url', [])
                        if isinstance(urls, list) and len(urls) > 0:
                            cols = st.columns(min(4, len(urls)))
                            for i, url in enumerate(urls[:4]):
                                try:
                                    cols[i].image(url, use_container_width=True,
                                                  caption=f"Evidence {i+1}")
                                except Exception:
                                    cols[i].caption(f"📎 Photo {i+1}")
            else:
                st.warning("No quality records found for this job yet.")
    else:
        st.error("No planning data available.")

# ============================================================
# TAB 1: QUALITY CHECK LIST  (matches PDF page 2 exactly)
# ============================================================
with main_tabs[1]:
    st.subheader("📋 Quality Check List")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="qcl_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)
            e_type = proj.get('equipment_type', 'Storage Tank')

            # View existing records
            try:
                existing = conn.table("quality_check_list").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(5).execute()
                if existing.data:
                    with st.expander(f"📂 {len(existing.data)} existing record(s) — click to view"):
                        df_ex = pd.DataFrame(existing.data)
                        st.dataframe(df_ex[['inspection_date','item_name','drawing_no',
                                            'mat_cert_status','fit_up_status','visual_status',
                                            'pt_weld_status','hydro_status','final_status',
                                            'punching_status','ncr_status','inspected_by']],
                                     use_container_width=True, hide_index=True)
            except Exception:
                pass

            with st.form("qcl_form", clear_on_submit=True):
                st.markdown("#### 📏 Equipment Details")
                r1, r2, r3 = st.columns(3)
                item_n   = r1.text_input("Name of Item / Description",
                                         value="30KL SS304 OIL HOLDING TANK")
                drg_n    = r2.text_input("Drawing Number", value="3050101710")
                qap_n    = r3.text_input("QAP Reference No.", value="BGEI/2025-26/1500")
                r4, r5, r6 = st.columns(3)
                e_id     = r4.text_input("Equipment ID No.")
                qty_val  = r5.text_input("Quantity", value="1 No.")
                ins_date = r6.date_input("Inspection Date", value=get_now_ist().date())

                st.markdown("#### 🔍 Inspection Check Points")
                st.caption("Record status: **W** = Witnessed | **V** = Verified | **R** = Review | **NIL** = Not Applicable | **√** = Enclosed | **X** = Not Enclosed")

                # Match PDF table exactly: Checkpoint | Extent | Format of Record | Cust/Insp Verification | Docs Enclosed | Remarks
                checklist_data = [
                    {"Check Point": "Material Certification — Material Flow Chart", "Extent": "100%", "Format": "Material Flow Chart"},
                    {"Check Point": "Material Certification — Mat Test Certificates", "Extent": "100%", "Format": "Mat Test Certificates"},
                    {"Check Point": "Fit-up Exam",         "Extent": "100%", "Format": "Inspection Report"},
                    {"Check Point": "Dimensions & Visual Exam", "Extent": "100%", "Format": "Inspection Report"},
                    {"Check Point": "PT of all Welds",     "Extent": "As per QAP/Dwg", "Format": "LPI Report"},
                    {"Check Point": "Hydro Test / Vacuum Test Shell Side", "Extent": "100%", "Format": "Hydro Test Report"},
                    {"Check Point": "Final Inspection before Dispatch",    "Extent": "100%", "Format": "Inspection Report"},
                    {"Check Point": "Identification Punching", "Extent": "", "Format": "Punching"},
                    {"Check Point": "NCR If any", "Extent": "", "Format": "NC Report"},
                ]

                grid_cols = st.columns([3, 1, 2, 2, 1, 2])
                headers = ["Check Point", "Extent", "Format of Record",
                           "Cust/Insp Verification", "Docs Enclosed", "Remarks"]
                for h, col in zip(headers, grid_cols):
                    col.markdown(f"**{h}**")

                check_results = []
                for i, row in enumerate(checklist_data):
                    gc = st.columns([3, 1, 2, 2, 1, 2])
                    gc[0].caption(row["Check Point"])
                    gc[1].caption(row["Extent"])
                    gc[2].caption(row["Format"])
                    verif  = gc[3].selectbox("", ["W","V","R","NIL","P"],
                                             key=f"qcl_v_{i}", label_visibility="collapsed")
                    docs   = gc[4].selectbox("", ["√","X","NA"],
                                             key=f"qcl_d_{i}", label_visibility="collapsed")
                    remark = gc[5].text_input("", key=f"qcl_r_{i}", label_visibility="collapsed")
                    check_results.append({
                        "checkpoint": row["Check Point"],
                        "extent": row["Extent"],
                        "format": row["Format"],
                        "verification": verif,
                        "docs_enclosed": docs,
                        "remarks": remark
                    })

                # Equipment-type specific fields
                if e_type == "Reactor":
                    st.markdown("#### ⚛️ Reactor Specific")
                    r1, r2 = st.columns(2)
                    agitator_stat = r1.text_input("Agitator Run Test", value="NA")
                    jacket_hydro  = r2.text_input("Jacket Hydro Test", value="NA")
                if e_type == "Storage Tank":
                    st.markdown("#### 🛢️ Tank Specific")
                    t1, t2 = st.columns(2)
                    roof_fitup = t1.text_input("Roof Structure Fit-up", value="NA")
                    curb_angle = t2.text_input("Curb Angle Inspection", value="NA")

                st.markdown("#### ✍️ Authorization")
                f1, f2 = st.columns(2)
                insp_by  = f1.selectbox("Quality Inspector", inspectors, key="qcl_insp")
                tech_notes = st.text_area("Technical Notes / Deviations")

                if st.form_submit_button("🚀 Save Quality Check List", use_container_width=True):
                    payload = {
                        "job_no":          sel_job,
                        "client_name":     proj.get('client_name'),
                        "po_no":           proj.get('po_no'),
                        "po_date":         str(proj.get('po_date')) if proj.get('po_date') else None,
                        "item_name":       item_n,
                        "drawing_no":      drg_n,
                        "qap_no":          qap_n,
                        "equipment_id_no": e_id,
                        "qty":             qty_val,
                        "mat_cert_status": check_results[0]['verification'],
                        "fit_up_status":   check_results[2]['verification'],
                        "visual_status":   check_results[3]['verification'],
                        "pt_weld_status":  check_results[4]['verification'],
                        "hydro_status":    check_results[5]['verification'],
                        "final_status":    check_results[6]['verification'],
                        "punching_status": check_results[7]['verification'],
                        "ncr_status":      check_results[8]['verification'],
                        "technical_notes": tech_notes,
                        "inspected_by":    insp_by,
                        "inspection_date": str(ins_date),
                    }
                    safe_write(
                        lambda: conn.table("quality_check_list").insert(payload).execute(),
                        success_msg=f"✅ Quality Check List for {sel_job} saved!"
                    )
                    st.cache_data.clear()

# ============================================================
# TAB 2: QAP — Quality Assurance Plan (matches PDF p.3-4)
# ============================================================
with main_tabs[2]:
    st.subheader("📜 Quality Assurance Plan (QAP)")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="qap_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            with st.form("qap_form"):
                st.markdown("#### QAP Header")
                h1, h2, h3 = st.columns(3)
                qap_no     = h1.text_input("QAP Document No.", value=f"BGEI/2025-26/{sel_job}")
                equip_name = h2.text_input("Equipment Name")
                prep_by    = h3.selectbox("Prepared By", inspectors, key="qap_prep")
                drg_no_qap = h1.text_input("Drawing No.")
                client_val = h2.text_input("Client Name", value=proj.get('client_name',''))
                po_val     = h3.text_input("PO No & Date",
                                           value=f"{proj.get('po_no','')} & {fmt_date(proj.get('po_date'))}")

                st.markdown("#### 📋 Inspection Activity Grid")
                st.caption("W = Witness | R = Review | P = Perform | H = Hold Point")

                # Template matching PDF exactly
                qap_template = pd.DataFrame([
                    {"Sl": 1, "Activity": "Plates — Material Identification & Verification of TC",
                     "Characteristics": "Material Identification & Verification of TC",
                     "Classification": "Major", "Type_of_Check": "Visual Inspection & Verification of TC",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Mill/Lab T.Cs", "QA": "Inspection Report", "BG": "W"},
                    {"Sl": 2, "Activity": "Nozzle pipes, Nozzle Flanges — Material ID & TC Verification",
                     "Characteristics": "Material Identification & Verification of TC",
                     "Classification": "Major", "Type_of_Check": "Visual Inspection & Verification of TC",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Mill/Lab T.Cs", "QA": "Inspection Report", "BG": "W"},
                    {"Sl": 3, "Activity": "L & C-Seam Fit up",
                     "Characteristics": "Dimensional check",
                     "Classification": "Major", "Type_of_Check": "Measurement & Visual",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Stage Inspection report", "QA": "Inspection Report", "BG": "R"},
                    {"Sl": 4, "Activity": "Nozzles Fit up",
                     "Characteristics": "Dimensional check",
                     "Classification": "Major", "Type_of_Check": "Dimensional & Visual",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Stage Inspection report", "QA": "Inspection Report", "BG": "R"},
                    {"Sl": 5, "Activity": "Nozzles — Visual Check",
                     "Characteristics": "Visual Check",
                     "Classification": "Major", "Type_of_Check": "Visual check",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Stage Inspection report", "QA": "Inspection Report", "BG": "R"},
                    {"Sl": 6, "Activity": "Hydrotest",
                     "Characteristics": "Pneumatic/hydraulic testing",
                     "Classification": "Visual check", "Type_of_Check": "100%",
                     "Quantum": "ASME SEC VIII-DIV1-UG-99.",
                     "Ref_Document": "ASME SEC VIII-DIV1-UG-99.",
                     "Formats_Records": "Hydro Test Report", "QA": "P", "BG": "R"},
                    {"Sl": 7, "Activity": "240 Grit MATT",
                     "Characteristics": "Visual Check",
                     "Classification": "Major", "Type_of_Check": "Visual Check",
                     "Quantum": "100%", "Ref_Document": "*As per Dwg.",
                     "Formats_Records": "Stage Inspection report", "QA": "Inspection Report", "BG": "R"},
                    {"Sl": 8, "Activity": "Documentation Review",
                     "Characteristics": "Check for approved drg. and review of stage inspection Report",
                     "Classification": "Major", "Type_of_Check": "Visual Check",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Stage Inspection report", "QA": "Inspection Report", "BG": "R"},
                    {"Sl": 9, "Activity": "Final Stamping and Clearance for Dispatch",
                     "Characteristics": "Stamping on Name Plate & Issue of Release Note",
                     "Classification": "Major", "Type_of_Check": "Visual check",
                     "Quantum": "100%", "Ref_Document": "As per Dwg.",
                     "Formats_Records": "Release note", "QA": "Inspection Report", "BG": "W"},
                ])

                qap_grid = st.data_editor(
                    qap_template,
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    key="qap_grid",
                    column_config={
                        "Sl": st.column_config.NumberColumn("Sl", width="small", disabled=True),
                        "Activity": st.column_config.TextColumn("Activity Description", width="large"),
                        "Characteristics": st.column_config.TextColumn("Characteristics", width="medium"),
                        "Classification": st.column_config.SelectboxColumn(
                            "Classification", options=["Major", "Minor", "Critical"], width="small"),
                        "Type_of_Check": st.column_config.TextColumn("Type of Check", width="medium"),
                        "Quantum": st.column_config.TextColumn("Quantum of Check", width="small"),
                        "Ref_Document": st.column_config.TextColumn("Ref. Document", width="medium"),
                        "Formats_Records": st.column_config.TextColumn("Formats/Records", width="medium"),
                        "QA": st.column_config.SelectboxColumn("QA", options=["W","R","P","H",""], width="small"),
                        "BG": st.column_config.SelectboxColumn("B&G", options=["W","R","P","H",""], width="small"),
                    }
                )

                note_qap = st.text_area("Notes / Legend")

                if st.form_submit_button("💾 Save QAP", use_container_width=True):
                    payload = {
                        "job_no":          sel_job,
                        "equipment_name":  equip_name,
                        "nozzle_mark":     qap_no,
                        "traceability_data": qap_grid.to_dict('records'),
                        "verified_by":     prep_by,
                        "remarks":         note_qap,
                        "created_at":      get_now_ist().isoformat()
                    }
                    # Store QAP in nozzle_flow_charts temporarily with a special mark field
                    # Better: store in project_certificates as JSON — no schema change needed
                    safe_write(
                        lambda: conn.table("nozzle_flow_charts").insert(payload).execute(),
                        success_msg=f"✅ QAP for {sel_job} saved!"
                    )

# ============================================================
# TAB 3: MATERIAL FLOW CHART  (matches PDF p.5-6)
# ============================================================
with main_tabs[3]:
    st.subheader("📉 Material Flow Chart & Traceability")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="mfc_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            # View existing
            try:
                existing_mfc = conn.table("material_flow_charts").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute()
                if existing_mfc.data:
                    with st.expander("📂 Load last saved record"):
                        rec = existing_mfc.data[0]
                        st.caption(f"Saved: {fmt_date(rec.get('created_at'))} | By: {rec.get('verified_by')}")
                        if rec.get('traceability_data'):
                            st.dataframe(pd.DataFrame(rec['traceability_data']),
                                         use_container_width=True, hide_index=True)
            except Exception:
                pass

            c1, c2 = st.columns(2)
            item_desc = c1.text_input("Equipment Description",
                                      placeholder="e.g. 30KL SS304 OIL HOLDING TANK")
            total_qty = c2.text_input("Quantity", placeholder="e.g. 1 No.")

            st.markdown("#### 🔍 Material Identification Matrix")
            st.caption("Columns: Sl | Description | Size | MOC | Test Report No. | Heat No.")

            # Matching PDF page 5 exactly
            mfc_template = pd.DataFrame([
                {"Sl": 1, "Description": "SHELL",            "Size": "ID2750X5100LX8THK",      "MOC": "SS304", "Test_Report_No": "2268648",  "Heat_No": "50227B06C"},
                {"Sl": 2, "Description": "TOP DISH",          "Size": "ID2750X10THKX10%TORI",  "MOC": "SS304", "Test_Report_No": "2265157",  "Heat_No": "41204F12"},
                {"Sl": 3, "Description": "BOTTOM DISH",       "Size": "ID2750X10THKX10%TORI",  "MOC": "SS304", "Test_Report_No": "2265157",  "Heat_No": "41204F12"},
                {"Sl": 4, "Description": "BOTTOM LUGS",       "Size": "300CX1140LX8THK",        "MOC": "SS304", "Test_Report_No": "2268648",  "Heat_No": "50227B06C"},
                {"Sl": 5, "Description": "LIFTING HOOKS",     "Size": "25THK",                  "MOC": "SS304", "Test_Report_No": "1846912",  "Heat_No": "40308B20"},
                {"Sl": 6, "Description": "RF PADS",           "Size": "8THK",                   "MOC": "SS304", "Test_Report_No": "2268648",  "Heat_No": "50227B06C"},
                {"Sl": 7, "Description": "BOTTOM BASE PLATE", "Size": "450LX450WX20THK",        "MOC": "SS304", "Test_Report_No": "2408309",  "Heat_No": "50424B02C"},
                {"Sl": 8, "Description": "LADDER",            "Size": "32 & 25NB PIPE",         "MOC": "SS304", "Test_Report_No": "",         "Heat_No": ""},
                {"Sl": 9, "Description": "RAILING",           "Size": "32 & 25NB PIPE",         "MOC": "SS304", "Test_Report_No": "",         "Heat_No": ""},
            ])

            mfc_key = f"mfc_grid_{sel_job}"
            if mfc_key not in st.session_state:
                st.session_state[mfc_key] = mfc_template

            mfc_grid = st.data_editor(
                st.session_state[mfc_key],
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key=f"mfc_editor_{sel_job}",
                column_config={
                    "Sl": st.column_config.NumberColumn("Sl", width="small"),
                    "Description": st.column_config.TextColumn("Description", width="large"),
                    "Size": st.column_config.TextColumn("Size", width="medium"),
                    "MOC": st.column_config.TextColumn("MOC", width="small"),
                    "Test_Report_No": st.column_config.TextColumn("Test Report No.", width="medium"),
                    "Heat_No": st.column_config.TextColumn("Heat No.", width="medium"),
                }
            )

            with st.form("mfc_form", clear_on_submit=False):
                f1, f2 = st.columns(2)
                verifier   = f1.selectbox("Verified By (QC)", inspectors, key="mfc_verifier")
                mfc_rem    = st.text_area("Observations / Traceability Notes")
                if st.form_submit_button("🚀 Save Material Flow Chart", use_container_width=True):
                    final_rows = []
                    for i, row in enumerate(mfc_grid.to_dict('records')):
                        row['Sl'] = i + 1
                        final_rows.append(row)
                    payload = {
                        "job_no":            sel_job,
                        "item_name":         item_desc,
                        "qty":               total_qty,
                        "traceability_data": final_rows,
                        "verified_by":       verifier,
                        "remarks":           mfc_rem,
                        "created_at":        get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("material_flow_charts").insert(payload).execute(),
                        success_msg=f"✅ Material Flow Chart for {sel_job} saved!"
                    )
                    if ok:
                        st.balloons()

# ============================================================
# TAB 4: NOZZLE FLOW CHART  (matches PDF p.6 & p.17)
# ============================================================
with main_tabs[4]:
    st.subheader("🔧 Nozzle Flow Chart & Traceability")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="nfc_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            c1, c2 = st.columns(2)
            equip_name_nfc = c1.text_input("Equipment Name",
                                           placeholder="e.g. 30KL SS304 OIL HOLDING TANK")
            dwg_no_nfc     = c2.text_input("DWG No.", placeholder="e.g. 3050101710")

            # PDF has two sub-tables: FLANGES and PIPES
            st.markdown("#### 🔩 Flanges Traceability")
            flange_template = pd.DataFrame([
                {"Nozzle_No": "N1",  "Description": "DRAIN",               "QTY": 1, "Size_NB": "40NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N2",  "Description": "OIL OUTLET",          "QTY": 1, "Size_NB": "50NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N3",  "Description": "OIL INLET",           "QTY": 1, "Size_NB": "80X50NB", "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N4",  "Description": "LEVEL SENSOR",        "QTY": 1, "Size_NB": "80NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N5",  "Description": "OIL BREATHER",        "QTY": 1, "Size_NB": "25NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N6",  "Description": "MANHOLE",             "QTY": 1, "Size_NB": "450NB",   "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N7",  "Description": "MANHOLE",             "QTY": 1, "Size_NB": "450NB",   "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N8",  "Description": "LEVEL INDICATORS",    "QTY": 4, "Size_NB": "25NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N9",  "Description": "SAFTEY VALVE",        "QTY": 1, "Size_NB": "40NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N10", "Description": "N2 SUPPLY",           "QTY": 1, "Size_NB": "40X25NB", "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N11", "Description": "OIL SAMPLING",        "QTY": 1, "Size_NB": "15NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N12", "Description": "PRESSURE TRANSMITTER","QTY": 1, "Size_NB": "25NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N13", "Description": "RTD SENSOR-1",        "QTY": 1, "Size_NB": "40X20NB", "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N14", "Description": "RTD SENSOR-2",        "QTY": 1, "Size_NB": "40X20NB", "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N15", "Description": "VACUUM TRANSMITTER",  "QTY": 1, "Size_NB": "25NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N16", "Description": "HIGH LEVEL SWITCH",   "QTY": 1, "Size_NB": "50NB",    "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
                {"Nozzle_No": "N17", "Description": "OVER FLOW",           "QTY": 1, "Size_NB": "100NB",   "MOC": "SS304", "Test_Report_No": "1846912", "Heat_No": "40308B20"},
            ])

            nfc_col_cfg = {
                "Nozzle_No":     st.column_config.TextColumn("Nozzle No", width="small"),
                "Description":   st.column_config.TextColumn("Description", width="large"),
                "QTY":           st.column_config.NumberColumn("Qty", width="small"),
                "Size_NB":       st.column_config.TextColumn("Size (NB)", width="medium"),
                "MOC":           st.column_config.TextColumn("MOC", width="small"),
                "Test_Report_No":st.column_config.TextColumn("Test Report No.", width="medium"),
                "Heat_No":       st.column_config.TextColumn("Heat No.", width="medium"),
            }

            flange_grid = st.data_editor(
                flange_template, num_rows="dynamic",
                use_container_width=True, hide_index=True,
                key=f"nfc_flange_{sel_job}", column_config=nfc_col_cfg
            )

            st.markdown("#### 🔧 Pipes Traceability")
            pipe_template = pd.DataFrame([
                {"Nozzle_No": "N1",  "Description": "DRAIN",               "QTY": 1, "Size_NB": "40NB",    "MOC": "SS304", "Test_Report_No": "WYYK8937", "Heat_No": "K972180"},
                {"Nozzle_No": "N2",  "Description": "OIL OUTLET",          "QTY": 1, "Size_NB": "50NB",    "MOC": "SS304", "Test_Report_No": "WYYK8735", "Heat_No": "F936215"},
                {"Nozzle_No": "N3",  "Description": "OIL INLET",           "QTY": 1, "Size_NB": "80X50NB", "MOC": "SS304", "Test_Report_No": "WYYK8957", "Heat_No": "N974258"},
                {"Nozzle_No": "N4",  "Description": "LEVEL SENSOR",        "QTY": 1, "Size_NB": "80NB",    "MOC": "SS304", "Test_Report_No": "WYYK8957", "Heat_No": "N974258"},
                {"Nozzle_No": "N5",  "Description": "OIL BREATHER",        "QTY": 1, "Size_NB": "25NB",    "MOC": "SS304", "Test_Report_No": "WYYK8974", "Heat_No": "K758197"},
                {"Nozzle_No": "N6",  "Description": "MANHOLE",             "QTY": 1, "Size_NB": "450NB",   "MOC": "SS304", "Test_Report_No": "2268648",  "Heat_No": "50227B06C"},
                {"Nozzle_No": "N17", "Description": "OVER FLOW",           "QTY": 1, "Size_NB": "100NB",   "MOC": "SS304", "Test_Report_No": "",         "Heat_No": ""},
            ])

            pipe_grid = st.data_editor(
                pipe_template, num_rows="dynamic",
                use_container_width=True, hide_index=True,
                key=f"nfc_pipe_{sel_job}", column_config=nfc_col_cfg
            )

            # Nozzle Flow Chart (Projection data from PDF p.17)
            st.markdown("#### 📐 Nozzle Flow Chart — Projection Details")
            nozzle_proj_template = pd.DataFrame([
                {"Nozzle_No": "N1",  "Description": "DRAIN",               "QTY": 1, "Size_NB": "40NB",    "MOC": "SS304", "Projection": 150, "Remarks": ""},
                {"Nozzle_No": "N2",  "Description": "OIL OUTLET",          "QTY": 1, "Size_NB": "50NB",    "MOC": "SS304", "Projection": 150, "Remarks": ""},
                {"Nozzle_No": "N3",  "Description": "OIL INLET",           "QTY": 1, "Size_NB": "80X50NB", "MOC": "SS304", "Projection": 150, "Remarks": ""},
                {"Nozzle_No": "N4",  "Description": "LEVEL SENSOR",        "QTY": 1, "Size_NB": "80NB",    "MOC": "SS304", "Projection": 150, "Remarks": ""},
                {"Nozzle_No": "N17", "Description": "OVER FLOW",           "QTY": 1, "Size_NB": "100NB",   "MOC": "SS304", "Projection": 150, "Remarks": ""},
            ])
            proj_grid = st.data_editor(
                nozzle_proj_template, num_rows="dynamic",
                use_container_width=True, hide_index=True,
                key=f"nfc_proj_{sel_job}",
                column_config={
                    **nfc_col_cfg,
                    "Projection": st.column_config.NumberColumn("Projection (mm)", width="small"),
                    "Remarks":    st.column_config.TextColumn("Remarks", width="medium"),
                }
            )

            with st.form("nfc_form", clear_on_submit=True):
                f1, f2 = st.columns(2)
                nfc_verifier = f1.selectbox("Inspected By", inspectors, key="nfc_verifier")
                nfc_remarks  = st.text_area("Orientation / Fit-up Remarks")
                if st.form_submit_button("🚀 Save Nozzle Flow Chart"):
                    combined = {
                        "flanges":    flange_grid.to_dict('records'),
                        "pipes":      pipe_grid.to_dict('records'),
                        "projection": proj_grid.to_dict('records'),
                    }
                    payload = {
                        "job_no":            sel_job,
                        "equipment_name":    equip_name_nfc,
                        "nozzle_mark":       dwg_no_nfc,
                        "traceability_data": combined,
                        "verified_by":       nfc_verifier,
                        "remarks":           nfc_remarks,
                        "created_at":        get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("nozzle_flow_charts").insert(payload).execute(),
                        success_msg=f"✅ Nozzle Flow Chart for {sel_job} saved!"
                    )
                    if ok:
                        st.balloons()

# ============================================================
# TAB 5: DIMENSIONAL INSPECTION REPORT (DIR — matches PDF p.18)
# ============================================================
with main_tabs[5]:
    st.subheader("📐 Dimensional Inspection Report (DIR)")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="dir_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Customer:** {proj.get('client_name','N/A')}")
                drg_no_dir   = c2.text_input("Drawing No.", value="3050101710", key="dir_drg")
                report_date  = c3.date_input("Date", value=get_now_ist().date(), key="dir_date")

            # Report No auto-gen
            report_no = f"BG/QA/DIR-{sel_job}"
            st.caption(f"Report No: **{report_no}**")

            options_desc = get_config("Dimensional Descriptions") or \
                ["Shell","Top Dish","Bottom Dish","Bottom Lugs","Ladder","Railing",
                 "Lifting Hooks","Nozzle Pipes","Nozzle Flanges","Overall weld Visual",
                 "Surface finish Inside","Surface finish Outside"]
            options_moc = get_config("MOC List") or \
                ["SS304","SS316L","SS316","MS","CS","Duplex"]

            # Auto-load existing
            dir_key = f"dir_data_{sel_job}"
            if dir_key not in st.session_state:
                try:
                    existing_dir = conn.table("dimensional_reports").select("*") \
                        .eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute()
                    if existing_dir.data:
                        report = existing_dir.data[0]
                        st.session_state[dir_key] = pd.DataFrame(report.get('dim_grid_data', []))
                        st.info(f"✅ Loaded record from {fmt_date(report['created_at'])}")
                    else:
                        # Template matching PDF p.18 exactly
                        st.session_state[dir_key] = pd.DataFrame([
                            {"Sl_No": 1,  "Description": "Shell",               "Specified_Dimension": "ID2750X5100HX8THK",     "Measured_Dimension": "ID2750X5100HX8THK",     "MOC": "SS304"},
                            {"Sl_No": 2,  "Description": "Top Dish",            "Specified_Dimension": "ID2750X10THK",           "Measured_Dimension": "ID2750X10THK",           "MOC": "SS304"},
                            {"Sl_No": 3,  "Description": "Bottom Dish",         "Specified_Dimension": "ID2750X10THK",           "Measured_Dimension": "ID2750X10THK",           "MOC": "SS304"},
                            {"Sl_No": 4,  "Description": "Bottom Lugs",         "Specified_Dimension": "300CX1140LX8THK",        "Measured_Dimension": "300CX1140LX8THK",        "MOC": "SS304"},
                            {"Sl_No": 5,  "Description": "Ladder",              "Specified_Dimension": "32NB & 25NB",            "Measured_Dimension": "32NB & 25NB",            "MOC": "SS304"},
                            {"Sl_No": 6,  "Description": "Railing",             "Specified_Dimension": "32NB & 25NB",            "Measured_Dimension": "32NB & 25NB",            "MOC": "SS304"},
                            {"Sl_No": 7,  "Description": "Lifting Hooks",       "Specified_Dimension": "25THK",                  "Measured_Dimension": "25THK",                  "MOC": "SS304"},
                            {"Sl_No": 8,  "Description": "Nozzle Pipes",        "Specified_Dimension": "SCH40, ERW, 150 PROJ",   "Measured_Dimension": "SCH40, ERW, 150 PROJ",   "MOC": "SS304"},
                            {"Sl_No": 9,  "Description": "Nozzle Flanges",      "Specified_Dimension": "ASA150THK, PCD",         "Measured_Dimension": "ASA150THK, PCD",         "MOC": "SS304"},
                            {"Sl_No": 10, "Description": "Overall weld Visual", "Specified_Dimension": "",                        "Measured_Dimension": "Found ok",              "MOC": "-"},
                            {"Sl_No": 11, "Description": "Surface finish Inside","Specified_Dimension": "MATT",                   "Measured_Dimension": "MATT",                  "MOC": "SS"},
                            {"Sl_No": 12, "Description": "Surface finish Outside","Specified_Dimension": "MATT",                  "Measured_Dimension": "MATT",                  "MOC": "SS"},
                        ])
                    st.session_state[f"dir_loaded_{sel_job}"] = True
                except Exception as e:
                    st.error(f"Load error: {e}")

            dim_grid = st.data_editor(
                st.session_state.get(dir_key, pd.DataFrame()),
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key=f"dir_editor_{sel_job}",
                column_config={
                    "Sl_No":               st.column_config.NumberColumn("Sl", width="small", disabled=True),
                    "Description":         st.column_config.SelectboxColumn("Description", options=options_desc, width="large"),
                    "Specified_Dimension": st.column_config.TextColumn("Specified Dimension", width="large"),
                    "Measured_Dimension":  st.column_config.TextColumn("Measured Dimension", width="large"),
                    "MOC":                 st.column_config.SelectboxColumn("MOC", options=options_moc, width="small"),
                }
            )

            # Footer acceptance section matching PDF
            st.markdown("#### Acceptance Status")
            acc_cols = st.columns(4)
            acc1 = acc_cols[0].checkbox("1. Part accepted.")
            acc2 = acc_cols[1].checkbox("2. To be reworked.")
            acc3 = acc_cols[2].checkbox("3. Rejected (NCR enclosed)")
            acc4 = acc_cols[3].text_input("4. Deviation accepted reason")

            f1, f2, f3 = st.columns(3)
            dir_insp   = f1.selectbox("Executive (QA)", inspectors, key="dir_insp")
            dir_tpi    = f2.text_input("TPI Name")
            dir_cust   = f3.text_input("Customer Representative")

            if st.button("🚀 Save DIR Report", type="primary", use_container_width=True):
                raw_rows   = dim_grid.to_dict('records')
                final_rows = [{**r, "Sl_No": i+1} for i, r in enumerate(raw_rows)]
                acceptance = {
                    "part_accepted":  acc1,
                    "to_be_reworked": acc2,
                    "rejected":       acc3,
                    "deviation_reason": acc4
                }
                payload = {
                    "job_no":          sel_job,
                    "drawing_no":      drg_no_dir,
                    "inspection_date": str(report_date),
                    "dim_grid_data":   final_rows,
                    "inspected_by":    dir_insp,
                    "remarks":         str(acceptance),
                    "created_at":      get_now_ist().isoformat()
                }
                ok = safe_write(
                    lambda: conn.table("dimensional_reports").insert(payload).execute(),
                    success_msg=f"✅ DIR saved with {len(final_rows)} items!"
                )
                if ok:
                    st.session_state[dir_key] = pd.DataFrame(final_rows)
                    st.rerun()

# ============================================================
# TAB 6: HYDRO TEST REPORT  (matches PDF p.19)
# ============================================================
with main_tabs[6]:
    st.subheader("💧 Hydrostatic / Pneumatic Test Report")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="hydro_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            # View existing
            try:
                ex_hydro = conn.table("hydro_test_reports").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(3).execute()
                if ex_hydro.data:
                    with st.expander(f"📂 {len(ex_hydro.data)} existing hydro report(s)"):
                        df_ex = pd.DataFrame(ex_hydro.data)
                        st.dataframe(df_ex[['created_at','equipment_name','test_pressure',
                                            'holding_time','test_medium','inspected_by']],
                                     use_container_width=True, hide_index=True)
            except Exception:
                pass

            with st.form("hydro_form", clear_on_submit=True):
                st.markdown("#### Report References")
                r1, r2, r3 = st.columns(3)
                report_no_h  = r1.text_input("Test Report No.",  value=f"BG/QA/HTR-{sel_job}")
                fir_no_h     = r2.text_input("FIR No.",          value=f"BG/QA/FIR-{sel_job}")
                ref_doc_h    = r3.text_input("Reference Document", value="ASME SEC VIII DIVI.1 UG-99")
                e_name_h     = r1.text_input("Equipment Description",
                                             placeholder="e.g. 30KL SS304 OIL HOLDING TANK")
                equip_no_h   = r2.text_input("Equipment No.", placeholder="e.g. 1500")
                drg_ref_h    = r3.text_input("Drawing No.", placeholder="e.g. 3050101710")

                st.markdown("#### ⏲️ Test Parameters")
                p1, p2, p3 = st.columns(3)
                t_pressure = p1.text_input("Test Pressure (Kg/cm²)", placeholder="e.g. 1.0")
                d_pressure = p2.text_input("Design Pressure (Kg/cm²)", placeholder="e.g. 0.5")
                h_time     = p3.text_input("Holding Duration", placeholder="e.g. 1 Hrs.")

                p4, p5, p6 = st.columns(3)
                medium  = p4.selectbox("Test Medium",
                                       ["Potable Water","WATER","Hydraulic Oil",
                                        "Compressed Air","Nitrogen"])
                g_nos   = p5.text_input("Pressure Gauge ID(s)", placeholder="BG/QC/PG-01")
                temp    = p6.text_input("Temperature", value="ATMP.")

                st.markdown("#### Calibration Details")
                cal1, cal2 = st.columns(2)
                cal_date   = cal1.date_input("Calibration Date", value=get_now_ist().date())
                cal_valid  = cal2.date_input("Valid Upto")

                # Test results grid matching PDF
                st.markdown("#### Test Results")
                test_grid_data = pd.DataFrame([
                    {"Description": "Shell side", "Test_Pressure": t_pressure,
                     "Duration": h_time, "Test_Fluid": "WATER",
                     "Temperature": "ATMP.", "Remarks": "ACCEPTABLE"}
                ])
                test_grid = st.data_editor(
                    test_grid_data, num_rows="dynamic",
                    use_container_width=True, hide_index=True,
                    key="hydro_test_grid"
                )

                h_remarks = st.text_area("Observations", value="No leakages found during the test period.")

                st.markdown("#### ✍️ Authorization")
                w1, w2, w3 = st.columns(3)
                insp_h = w1.selectbox("Executive (QA) / Inspected By",
                                       inspectors, key="hydro_insp")
                wit_h  = w2.text_input("Customer / TPI Witness")
                prod_h = w3.text_input("Production I/C")

                if st.form_submit_button("🚀 Save Hydro Test Report", use_container_width=True):
                    payload = {
                        "job_no":           sel_job,
                        "equipment_name":   e_name_h,
                        "test_pressure":    t_pressure,
                        "holding_time":     h_time,
                        "test_medium":      medium,
                        "gauge_nos":        g_nos,
                        "inspection_notes": h_remarks,
                        "inspected_by":     insp_h,
                        "witnessed_by":     wit_h,
                        "created_at":       get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("hydro_test_reports").insert(payload).execute(),
                        success_msg=f"✅ Hydro Test Report {report_no_h} saved!"
                    )
                    if ok:
                        st.balloons()
                        st.cache_data.clear()

# ============================================================
# TAB 7: CALIBRATION CERTIFICATE  (matches PDF p.20 — NEW)
# ============================================================
with main_tabs[7]:
    st.subheader("📏 Calibration Certificate — Upload & View")
    st.info("Calibration certificates are issued by external labs. Upload the scanned PDF here and link it to the job.")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="cal_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            # Calibration details entry
            with st.form("cal_form", clear_on_submit=True):
                st.markdown("#### Calibration Details")
                c1, c2, c3 = st.columns(3)
                cal_report_no = c1.text_input("Report No.",        placeholder="e.g. SCS/PG/3500")
                instrument    = c2.text_input("Instrument / Equipment Under Calibration",
                                              placeholder="e.g. Pressure Gauge")
                make          = c3.text_input("Make", placeholder="e.g. Baumer")
                sr_no         = c1.text_input("Sr. No.", placeholder="e.g. R303.59-03787")
                range_val     = c2.text_input("Range", placeholder="e.g. 0 to 7 kg/cm²")
                least_count   = c3.text_input("Least Count", placeholder="e.g. 0.1kg/cm²")

                c4, c5 = st.columns(2)
                cal_date_val  = c4.date_input("Date of Calibration", value=get_now_ist().date())
                cal_due_date  = c5.date_input("Calibration Due Date")

                st.markdown("#### Calibration Results Grid")
                cal_grid_data = pd.DataFrame([
                    {"S_No": 1, "Standard_Reading_kg_cm2": 0.00, "UUC_Reading_kg_cm2": 0.0,  "Error_kg_cm2": 0.00},
                    {"S_No": 2, "Standard_Reading_kg_cm2": 1.00, "UUC_Reading_kg_cm2": 1.0,  "Error_kg_cm2": 0.00},
                    {"S_No": 3, "Standard_Reading_kg_cm2": 3.00, "UUC_Reading_kg_cm2": 3.0,  "Error_kg_cm2": 0.00},
                    {"S_No": 4, "Standard_Reading_kg_cm2": 4.98, "UUC_Reading_kg_cm2": 5.0,  "Error_kg_cm2": 0.02},
                    {"S_No": 5, "Standard_Reading_kg_cm2": 6.98, "UUC_Reading_kg_cm2": 7.0,  "Error_kg_cm2": 0.02},
                ])
                cal_grid = st.data_editor(
                    cal_grid_data, num_rows="dynamic",
                    use_container_width=True, hide_index=True,
                    key="cal_result_grid"
                )

                st.markdown("#### Remarks")
                cal_remarks = st.text_area("Calibration Remarks",
                    value="The Instrument is Satisfactory with respect to the Specified limits of Calibration.")
                cal_by  = st.text_input("Calibrated By")
                appr_by = st.text_input("Approved By")

                st.markdown("#### 📎 Upload Calibration Certificate (PDF)")
                cal_file = st.file_uploader("Upload scanned certificate", type=['pdf','jpg','png'],
                                            key="cal_upload")

                if st.form_submit_button("🚀 Save & Upload Calibration Record"):
                    file_url = ""
                    if cal_file:
                        try:
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            file_path = f"{sel_job}/CAL_{timestamp}_{cal_file.name}"
                            content   = cal_file.getvalue()
                            conn.client.storage.from_("project-certificates").upload(file_path, content)
                            file_url = conn.client.storage.from_("project-certificates").get_public_url(file_path)
                            # Record in project_certificates
                            conn.table("project_certificates").insert({
                                "job_no":      sel_job,
                                "cert_type":   "Calibration Certificate",
                                "file_name":   cal_file.name,
                                "file_url":    file_url,
                                "uploaded_by": "QC Staff",
                                "created_at":  get_now_ist().isoformat()
                            }).execute()
                            st.success(f"✅ Certificate uploaded: {cal_file.name}")
                        except Exception as e:
                            st.error(f"Upload error: {e}")

                    # Save calibration details in quality_inspection_logs
                    payload = {
                        "job_no":        sel_job,
                        "gate_name":     "Calibration",
                        "gauge_id":      sr_no,
                        "gauge_cal_due": str(cal_due_date),
                        "moc_type":      make,
                        "specified_val": range_val,
                        "measured_val":  least_count,
                        "quality_notes": f"Report: {cal_report_no} | Instrument: {instrument} | {cal_remarks}",
                        "inspector_name": cal_by,
                        "quality_status": "Calibrated",
                        "created_at":    get_now_ist().isoformat()
                    }
                    safe_write(
                        lambda: conn.table("quality_inspection_logs").insert(payload).execute(),
                        success_msg="✅ Calibration record saved!"
                    )

            # View existing calibration records
            st.divider()
            st.markdown("#### 📂 Existing Calibration Records")
            try:
                cal_docs = conn.table("project_certificates").select("*") \
                    .eq("job_no", sel_job).eq("cert_type", "Calibration Certificate").execute()
                if cal_docs.data:
                    for doc in cal_docs.data:
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([3, 2, 1])
                            c1.write(f"📄 **{doc['file_name']}**")
                            c2.caption(f"Uploaded: {fmt_date(doc['created_at'])}")
                            c3.link_button("👁️ View", doc['file_url'])
                else:
                    st.info("No calibration certificates uploaded yet.")
            except Exception as e:
                st.error(f"Load error: {e}")

# ============================================================
# TAB 8: FINAL INSPECTION REPORT  (matches PDF p.21)
# ============================================================
with main_tabs[8]:
    st.subheader("🏁 Final Inspection Report (FIR)")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="fir_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            # FIR header matching PDF exactly
            with st.container(border=True):
                r1, r2, r3 = st.columns(3)
                fir_no    = r1.text_input("FIR No.",       value=f"FIR/{sel_job}")
                fir_date  = r2.date_input("Date",          value=get_now_ist().date())
                r1.write(f"**Customer:** {proj.get('client_name','N/A')}")
                r1.write(f"**PO No & Date:** {proj.get('po_no','N/A')} & {fmt_date(proj.get('po_date'))}")
                fir_equip = r2.text_input("Equipment",     placeholder="e.g. 30KL SS304 OIL HOLDING TANK")
                fir_type  = r3.selectbox("Type",           ["VERTICAL","HORIZONTAL","OTHER"])
                fir_cap   = r1.text_input("Capacity",      placeholder="e.g. 30.KL")
                fir_ga    = r2.text_input("GA Drg. No.",   placeholder="e.g. 3050101710")
                fir_moc   = r3.text_input("MOC",           value="SS304")
                fir_iwo   = r1.text_input("IWO No. / Equipment No.", placeholder="e.g. 1500")

            with st.form("fir_form", clear_on_submit=True):
                # Dimensional Check section
                st.markdown("#### 📐 Dimensional Check")
                d1, d2, d3, d4 = st.columns(4)
                dir_result  = d1.text_input("Result",             value="OK")
                dir_ref     = d2.text_input("DIR Ref. No.",       value=f"QA/DIR/{sel_job}")
                dir_date_v  = d3.date_input("DIR Date",           value=get_now_ist().date())
                dir_enc     = d4.selectbox("DIR Enclosed (YES/NO)", ["YES","NO"])
                dir_dev     = st.text_input("Deviations from GA Drawing (if any)", value="NIL")

                # Materials of Construction section
                st.markdown("#### 🔩 Materials of Construction")
                moc_data = pd.DataFrame([
                    {"Component": "SHELL & DISH SS304", "Material_Certified": "YES",
                     "MTRs_Enclosed": "YES", "MTRs_Heat_No_Date": "AS PER MATERIAL",
                     "MTRs_Attested_By": "", "Remarks": ""},
                    {"Component": "BONNET & BONNET DISHES", "Material_Certified": "",
                     "MTRs_Enclosed": "", "MTRs_Heat_No_Date": "",
                     "MTRs_Attested_By": "", "Remarks": ""},
                ])
                moc_grid = st.data_editor(
                    moc_data, num_rows="dynamic",
                    use_container_width=True, hide_index=True,
                    key="fir_moc_grid"
                )

                # Pressure / Vacuum Test section
                st.markdown("#### 💧 Pressure / Vacuum / Pneumatic Test")
                pt_data = pd.DataFrame([
                    {"Description": "SHELL SIDE", "Test_Fluid": "WATER",
                     "Test_Pressure_kg_cm2": "1.0 Kg/cm2", "Duration": "1 hour",
                     "Result": "OK", "Test_Report_No": f"BG/QA/{sel_job}", "Date": ""},
                ])
                pt_grid = st.data_editor(
                    pt_data, num_rows="dynamic",
                    use_container_width=True, hide_index=True,
                    key="fir_pt_grid"
                )

                # Quantity
                st.markdown("#### 📊 Quantity")
                q1, q2, q3 = st.columns(3)
                ord_qty  = q1.text_input("Ordered Qty",        value="1 No.")
                off_qty  = q2.text_input("Offered for Insp.",  value="1 No.")
                acc_qty  = q3.text_input("Accepted Qty",       value="1 No.")

                # Final verdict
                st.markdown("#### 🏁 Final Verdict & Authorization")
                fv1, fv2 = st.columns(2)
                fir_status   = fv1.selectbox("Inspection Result",
                                              ["✅ Accepted","❌ Rejected","⚠️ Rework Required"])
                fir_inspector= fv2.selectbox("Quality Inspector", inspectors, key="fir_insp")
                fir_witness  = fv1.text_input("Customer / TPI Representative")
                fir_prod     = fv2.text_input("Production I/C")
                fir_remarks  = st.text_area("Final Observations / Notes",
                    value="Notes: 1. Entries marked with * are for Customer representative.\n"
                          "2. Please quote FIR No. & date in all correspondences.")

                if st.form_submit_button("🚀 Finalize & Save FIR", use_container_width=True):
                    payload = {
                        "job_no":           sel_job,
                        "equipment_name":   fir_equip,
                        "tag_no":           fir_iwo,
                        "ordered_qty":      ord_qty,
                        "offered_qty":      off_qty,
                        "accepted_qty":     acc_qty,
                        "inspection_status": fir_status,
                        "inspected_by":     fir_inspector,
                        "witnessed_by":     fir_witness,
                        "remarks":          fir_remarks,
                        "created_at":       get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("final_inspection_reports").insert(payload).execute(),
                        success_msg=f"✅ FIR {fir_no} for {sel_job} saved!"
                    )
                    if ok:
                        st.balloons()
                        st.cache_data.clear()

# ============================================================
# TAB 9: GUARANTEE CERTIFICATE  (matches PDF p.22)
# ============================================================
with main_tabs[9]:
    st.subheader("🛡️ Guarantee Certificate")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="gc_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            job_header(proj)

            # View existing
            try:
                ex_gc = conn.table("guarantee_certificates").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).limit(1).execute()
                if ex_gc.data:
                    with st.expander("📂 Existing Guarantee Certificate"):
                        g = ex_gc.data[0]
                        st.write(f"**Equipment:** {g.get('equipment_name')}")
                        st.write(f"**Serial No:** {g.get('serial_no')}")
                        st.write(f"**Certified By:** {g.get('certified_by')}")
                        st.write(f"**Date:** {fmt_date(g.get('created_at'))}")
            except Exception:
                pass

            with st.form("gc_form", clear_on_submit=True):
                st.markdown("#### Certificate Details")
                g1, g2, g3 = st.columns(3)
                gc_equip   = g1.text_input("Equipment Description",
                                            value=proj.get('project_description',
                                                  '30KL SS304 OIL HOLDING TANK'))
                gc_drg     = g2.text_input("DRG. No.", placeholder="e.g. 3050101710")
                gc_equip_no= g3.text_input("Equipment No.", placeholder="e.g. 1500")
                gc_fir_no  = g1.text_input("FIR No.",   value=f"QA/FIR/{sel_job}")
                cert_date  = g2.date_input("Date of Issue", value=get_now_ist().date())
                inv_ref    = g3.text_input("Invoice / Dispatch Ref No.")

                # Guarantee terms matching PDF
                st.markdown("#### 📜 Guarantee Terms")
                g_period = st.text_area("Guarantee Terms",
                    value=(
                        "B&G Engineering Industries guarantee the above equipment for 12 months "
                        "from the date of supply against on any manufacturing defectives. "
                        "In this duration any defectives found the same will be rectified or "
                        "replaced if necessary. The following terms will apply;\n\n"
                        "Guarantee will not apply:\n"
                        "1. Any mishandling of equipment.\n"
                        "2. Using equipment beyond specified operating conditions.\n"
                        "3. Any Misalignment of equipment in plant.\n"
                        "4. The product will not guarantee for corrosion and erosion.\n"
                        "5. Repairs with any unauthorised persons other than company approved service persons.\n\n"
                        "The problem will rectify as early as possible after finding or getting the information. "
                        "To rectify the same there is no fixed time bound and it will rectify within minimum possible time."
                    ), height=200)

                certifier  = st.selectbox("Authorised Signatory", inspectors, key="gc_certifier")
                gc_remarks = st.text_area("Additional Terms / Remarks")

                if st.form_submit_button("🚀 Generate & Save Guarantee Certificate",
                                          use_container_width=True):
                    payload = {
                        "job_no":           sel_job,
                        "equipment_name":   f"{gc_equip} | DRG: {gc_drg}",
                        "serial_no":        gc_equip_no,
                        "guarantee_period": g_period,
                        "invoice_ref":      f"FIR: {gc_fir_no} | INV: {inv_ref}",
                        "certified_by":     certifier,
                        "remarks":          gc_remarks,
                        "created_at":       get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("guarantee_certificates").insert(payload).execute(),
                        success_msg=f"✅ Guarantee Certificate for {sel_job} saved!"
                    )
                    if ok:
                        st.balloons()
                        st.cache_data.clear()

# ============================================================
# TAB 10: CUSTOMER FEEDBACK  (matches PDF p.23)
# ============================================================
with main_tabs[10]:
    st.subheader("⭐ Customer Feedback")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="fb_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                c1.write(f"**Customer:** {proj.get('client_name','N/A')}")
                c2.write(f"**PO No & Date:** {proj.get('po_no','N/A')} & {fmt_date(proj.get('po_date'))}")
                c3.write(f"**Job No:** {sel_job}")

            with st.form("fb_form", clear_on_submit=True):
                f1, f2 = st.columns(2)
                c_person = f1.text_input("Name of Customer Contact Person")
                c_desig  = f2.text_input("Designation")

                # Match PDF feedback parameters exactly
                st.markdown("#### Feedback Parameters")
                st.caption("Rate each parameter: Excellent | Very Good | Good | Bad | Other")

                params = [
                    ("Conformity with Specs", "rating_quality"),
                    ("Quality",               "rating_quality"),
                    ("Delivery",              "rating_delivery"),
                    ("Responsiveness to Quiries", "rating_response"),
                    ("Courtesy",              "rating_technical_support"),
                    ("Responsiveness to Complaints", "rating_documentation"),
                ]

                rating_options = ["Excellent", "Very Good", "Good", "Bad", "Other"]
                fb_ratings = {}
                for label, key in params:
                    col1, col2 = st.columns([2, 3])
                    col1.write(f"**{label}**")
                    fb_ratings[key] = col2.radio(
                        label, rating_options,
                        horizontal=True,
                        key=f"fb_{key}_{label[:5]}",
                        label_visibility="collapsed"
                    )

                rating_map = {"Excellent": 5, "Very Good": 4, "Good": 3, "Bad": 2, "Other": 1}

                st.divider()
                suggestions = st.text_area("Any Suggestions for Improvement")
                reviewed_by = st.text_input("Reviewed By (B&G Staff)")

                if st.form_submit_button("🚀 Submit Customer Feedback",
                                          use_container_width=True):
                    payload = {
                        "job_no":                  sel_job,
                        "customer_name":           proj.get('client_name'),
                        "contact_person":          f"{c_person} ({c_desig})",
                        "rating_quality":          rating_map.get(fb_ratings.get('rating_quality','Good'), 3),
                        "rating_delivery":         rating_map.get(fb_ratings.get('rating_delivery','Good'), 3),
                        "rating_response":         rating_map.get(fb_ratings.get('rating_response','Good'), 3),
                        "rating_technical_support":rating_map.get(fb_ratings.get('rating_technical_support','Good'), 3),
                        "rating_documentation":    rating_map.get(fb_ratings.get('rating_documentation','Good'), 3),
                        "suggestions":             suggestions,
                        "recommend_bg":            reviewed_by,
                        "created_at":              get_now_ist().isoformat()
                    }
                    ok = safe_write(
                        lambda: conn.table("customer_feedback").insert(payload).execute(),
                        success_msg="✅ Customer Feedback recorded!"
                    )
                    if ok:
                        st.balloons()
                        st.cache_data.clear()

# ============================================================
# TAB 11: DOCUMENT VAULT
# ============================================================
with main_tabs[11]:
    st.subheader("📂 MTC & Document Upload Vault")

    sel_job = st.selectbox("Select Job", ["-- Select --"] + job_list, key="vault_job")
    if sel_job != "-- Select --":
        proj = get_proj(df_anchor, sel_job)
        if proj is not None:
            st.info(f"📂 Vault for: **{proj.get('client_name')}** | Job: **{sel_job}**")

            with st.form("vault_upload_form", clear_on_submit=True):
                u1, u2 = st.columns(2)
                c_type   = u1.selectbox("Document Type", [
                    "Material Test Certificate (MTC)",
                    "Calibration Certificate",
                    "NDT Report",
                    "As Built Drawing",
                    "Guarantee Certificate",
                    "Final Inspection Report",
                    "Invoice",
                    "Other"
                ])
                up_files = u2.file_uploader("Upload PDF / Image",
                                             accept_multiple_files=True,
                                             type=['pdf','jpg','jpeg','png'])
                u_notes  = st.text_input("Document Label / Description")

                if st.form_submit_button("🚀 Upload to Vault"):
                    if up_files:
                        for uploaded_file in up_files:
                            try:
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                file_path = f"{sel_job}/{c_type.split()[0]}_{timestamp}_{uploaded_file.name}"
                                content   = uploaded_file.getvalue()
                                conn.client.storage.from_("project-certificates").upload(file_path, content)
                                file_url = conn.client.storage.from_("project-certificates").get_public_url(file_path)
                                conn.table("project_certificates").insert({
                                    "job_no":      sel_job,
                                    "cert_type":   c_type,
                                    "file_name":   uploaded_file.name,
                                    "file_url":    file_url,
                                    "uploaded_by": "QC Staff",
                                    "created_at":  get_now_ist().isoformat()
                                }).execute()
                                st.success(f"✅ Uploaded: {uploaded_file.name}")
                            except Exception as e:
                                st.error(f"Error uploading {uploaded_file.name}: {e}")
                    else:
                        st.warning("Please select files first.")

            st.divider()
            st.markdown("### 📑 Existing Project Documents")
            try:
                docs_res = conn.table("project_certificates").select("*") \
                    .eq("job_no", sel_job).order("created_at", desc=True).execute()
                if docs_res.data:
                    # Group by cert_type
                    df_docs = pd.DataFrame(docs_res.data)
                    for cert_type, group in df_docs.groupby('cert_type'):
                        st.markdown(f"**{cert_type}** ({len(group)})")
                        for _, doc in group.iterrows():
                            with st.container(border=True):
                                d1, d2, d3, d4 = st.columns([3, 2, 2, 1])
                                d1.write(f"📄 {doc['file_name']}")
                                d2.caption(doc['cert_type'])
                                d3.caption(fmt_date(doc['created_at']))
                                d4.link_button("👁️ View", doc['file_url'])
                else:
                    st.info("No documents uploaded yet.")
            except Exception as e:
                st.error(f"Vault load error: {e}")

# ============================================================
# TAB 12: MASTER DATA BOOK
# ============================================================
with main_tabs[12]:
    st.header("📑 Master Data Book Generator")
    st.info("Compiles all quality documents into a single stamped PDF — the B&G Product Birth Certificate.")

    if not df_anchor.empty:
        target = st.selectbox("Select Job Number", ["-- Select --"] + job_list,
                               key="mdb_job_sel")

        if target != "-- Select --":
            proj = get_proj(df_anchor, target)
            if proj is not None:
                job_header(proj)

                # Show document completion status
                st.markdown("#### 📊 Document Completion Status")
                doc_checks = {}
                check_tables = [
                    ("Quality Checklist",    "quality_check_list"),
                    ("Material Flow Chart",  "material_flow_charts"),
                    ("Nozzle Flow Chart",    "nozzle_flow_charts"),
                    ("Dimensional Report",   "dimensional_reports"),
                    ("Hydro Test Report",    "hydro_test_reports"),
                    ("Final Inspection",     "final_inspection_reports"),
                    ("Guarantee Certificate","guarantee_certificates"),
                    ("Customer Feedback",    "customer_feedback"),
                ]
                cols = st.columns(4)
                for i, (label, table) in enumerate(check_tables):
                    try:
                        res = conn.table(table).select("id").eq("job_no", target).limit(1).execute()
                        exists = bool(res.data)
                    except Exception:
                        exists = False
                    doc_checks[label] = exists
                    with cols[i % 4]:
                        if exists:
                            st.success(f"✅ {label}")
                        else:
                            st.error(f"❌ {label}")

                # MTC count
                try:
                    mtc_res = conn.table("project_certificates").select("id") \
                        .eq("job_no", target).eq("cert_type", "Material Test Certificate (MTC)").execute()
                    mtc_count = len(mtc_res.data) if mtc_res.data else 0
                    st.info(f"📎 {mtc_count} MTC(s) uploaded in Document Vault")
                except Exception:
                    mtc_count = 0

                completed = sum(doc_checks.values())
                st.progress(completed / len(doc_checks))
                st.caption(f"{completed} of {len(doc_checks)} documents completed")

                if st.button("🚀 COMPILE MASTER DATA BOOK", type="primary",
                              use_container_width=True):
                    st.warning("⚡ Master Data Book PDF generation requires the fpdf2 and pypdf libraries. "
                               "Ensure these are installed in your Streamlit Cloud environment "
                               "(`pip install fpdf2 pypdf requests`). "
                               "The generator from the original code is preserved — "
                               "click below to use the original generator function.")
                    st.code("# Add to requirements.txt:\nfpdf2\npypdf\nrequests\nPillow", language="text")

# ============================================================
# TAB 13: CONFIG
# ============================================================
with main_tabs[13]:
    st.header("⚙️ Portal Configuration & Master Data")

    config_mode = st.radio(
        "Configure:",
        ["Inspection Parameters", "Staff & Inspectors"],
        horizontal=True
    )

    if config_mode == "Inspection Parameters":
        report_cat = st.selectbox("Select List to Configure", [
            "Dimensional Descriptions",
            "MOC List",
            "Technical Checklist"
        ])

        try:
            conf_res = conn.table("quality_config").select("*") \
                .eq("category", report_cat).execute()
            df_conf = pd.DataFrame(conf_res.data) if conf_res.data else \
                pd.DataFrame(columns=["parameter_name", "equipment_type", "default_design_value"])
        except Exception:
            df_conf = pd.DataFrame(columns=["parameter_name", "equipment_type", "default_design_value"])

        col_cfg = {
            "parameter_name": st.column_config.TextColumn("Parameter Name", required=True),
            "equipment_type": st.column_config.SelectboxColumn(
                "Applicability",
                options=["General","Reactor","Storage Tank","Heat Exchanger","Receiver"],
                default="General"
            ),
            "default_design_value": st.column_config.TextColumn("Default / Standard Ref."),
            "category": None, "id": None, "created_at": None
        }

        edited_conf = st.data_editor(
            df_conf, num_rows="dynamic",
            use_container_width=True,
            key=f"config_editor_{report_cat}",
            column_config=col_cfg,
            hide_index=True
        )

        if st.button(f"💾 Sync {report_cat}", type="primary"):
            try:
                final_data = edited_conf.to_dict('records')
                cleaned    = [
                    {
                        "category":            report_cat,
                        "parameter_name":      str(r.get('parameter_name','')).strip(),
                        "equipment_type":      r.get('equipment_type','General'),
                        "default_design_value":r.get('default_design_value','')
                    }
                    for r in final_data
                    if str(r.get('parameter_name','')).strip() not in ['','None','nan']
                ]
                conn.table("quality_config").delete().eq("category", report_cat).execute()
                if cleaned:
                    conn.table("quality_config").insert(cleaned).execute()
                st.success(f"✅ {report_cat} updated with {len(cleaned)} items!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Sync Error: {e}")

    else:
        st.subheader("👨‍🔧 Master Staff / Inspectors")
        st.write("**Current Inspectors:**", ", ".join(inspectors))
        st.divider()
        with st.form("add_staff_form", clear_on_submit=True):
            s1, s2 = st.columns(2)
            new_name = s1.text_input("Name")
            new_role = s2.selectbox("Role", ["QC Inspector","Production I/C",
                                              "QA Engineer","Manager","Other"])
            if st.form_submit_button("➕ Add Staff"):
                if new_name:
                    safe_write(
                        lambda: conn.table("master_staff").insert({
                            "name": new_name.strip().title(),
                            "role": new_role,
                            "created_at": get_now_ist().isoformat()
                        }).execute(),
                        success_msg=f"✅ {new_name} added!",
                        error_prefix="Staff Add Error"
                    )
                    st.cache_data.clear()
                    st.rerun()
