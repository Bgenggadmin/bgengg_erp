# MEE Vertical — Estimation & Costing Module

Slots into your existing `Bgenggadmin/bgengg_erp` repo as **page 12**, sitting
between Process Design (page 10) and Offer Generator (page 11) in the MEE pipeline.

```
Page 10                  Page 12 (NEW)             Page 11
bg_process_design  ──►  bg_estimation_costing  ──►  bg_offer_generator
   (sizing)              (cost build-up)             (customer quote)
        │                       │                          ▲
        ▼                       ▼                          │
  mee_projects         mee_qps_costings                    │
  mee_design_equipment mee_qps_costing_lines  ─────────────┘
                                ▲
                                │ reads master prices
                                │
              ┌─────────────────┴─────────────────┐
              │   est_rm_master  (RM + BO items)  │  ← shared with Pharma module
              │   est_oh_master  (LABOUR + OH)    │     (extended by migration 02)
              └───────────────────────────────────┘
```

> **Page numbering note:** Process Design (10) and Offer Generator (11) keep
> their existing numbers — no renaming needed. The new MEE Costing page sits
> at 12 in the sidebar but logically operates between them in the workflow.

## Folder layout in your repo

```
bgengg_erp/                            ← existing repo root
├── bg_offer_generator/                ← existing
├── bg_process_design/                 ← existing
├── bg_estimation_costing/             ← NEW (sibling of the above two)
│   ├── __init__.py
│   ├── db.py
│   ├── modules/qps_calculators.py
│   ├── ui/                            ← 11 tab + widget files
│   ├── utils/                         ← state, totals, templates, persistence
│   └── assets/
├── pages/
│   ├── 09_Estimation_Costing.py       ← existing (Pharma vertical)
│   ├── 10_Process_Design.py           ← existing
│   ├── 11_Offer_Generator.py          ← existing
│   ├── 12_MEE_Estimation_Costing.py   ← NEW
│   └── ...
├── migrations/                        ← NEW folder (or merge with your existing)
│   ├── 01_mee_costing_schema.sql
│   └── 02_extend_masters_for_mee.sql
├── app.py
├── database_utils.py
├── requirements.txt
└── ...
```

## Push commands (Windows)

```bat
cd C:\Users\<You>\Documents\bgengg_erp

git checkout main
git pull origin main
git checkout -b feat/mee-estimation-costing

REM Extract zip into repo root
powershell -command "Expand-Archive -Force '%USERPROFILE%\Downloads\bg_estimation_costing_module.zip' '.'"

git status
REM should show:
REM   new file:   bg_estimation_costing/...   (~22 files)
REM   new file:   pages/12_MEE_Estimation_Costing.py
REM   new file:   migrations/01_mee_costing_schema.sql
REM   new file:   migrations/02_extend_masters_for_mee.sql

python -m py_compile pages\12_MEE_Estimation_Costing.py
REM silent = OK

git add bg_estimation_costing\ pages\12_MEE_Estimation_Costing.py migrations\

git commit -m "feat(mee): add Estimation & Costing module as page 12" -m "- New package bg_estimation_costing/ (sibling of bg_process_design)" -m "- pages/12_MEE_Estimation_Costing.py wires up 8 tabs" -m "- Reads est_rm_master + est_oh_master (shared with Pharma estimation)" -m "- Migration 02: extend masters with sub_type/vendor/material columns" -m "- Migration 02: seed ~50 BO instruments/pumps/valves + ~25 OH labour rates" -m "- BO-master picker on EIA + Equipment tabs" -m "- Five parametric calculators with DB-backed rates" -m "- Slots between page 10 (Process Design) and page 11 (Offer Generator)"

git push -u origin feat/mee-estimation-costing
```

After GitHub shows the PR URL, open it, review the diff, and merge to `main`.
Streamlit Cloud auto-deploys — the new "MEE Estimation & Costing" page will
appear in the sidebar within a minute.

## Supabase setup — run BOTH migrations in order

In Supabase Dashboard → **SQL Editor**:

1. **First:** paste contents of `migrations/01_mee_costing_schema.sql` → Run.
   Creates the four MEE-specific tables.

2. **Second:** paste contents of `migrations/02_extend_masters_for_mee.sql` → Run.
   Extends the existing `est_rm_master` + `est_oh_master` tables with new
   columns and seeds bought-out items + labour rates.

Both migrations are **idempotent** (safe to re-run).

## ⚠️ Wiring the existing 10 and 11 pages

The MEE costing module reads from `mee_projects` + `mee_design_equipment` and
writes to `mee_qps_costings` + `mee_qps_costing_lines`. For end-to-end
hand-off to work, **`10_Process_Design.py` and `11_Offer_Generator.py` need
small adjustments**:

### `10_Process_Design.py` — add table writes
At the point where a process design is finalised, write to the two upstream
tables. If your Process Design module already saves to its own tables,
either:

**Option A — add a "Send to Costing" button:**
```python
# Inside the existing 10_Process_Design.py:
if st.button("📤 Send to Costing"):
    pid = sb_insert("mee_projects", {
        "client_name":  current_design["client_name"],
        "project_name": current_design["project_name"],
        "capacity":     current_design["capacity"],
        "plant_type":   "MEE",
        "design_basis": json.dumps(current_design),
    }, returning=True)[0]["id"]

    for line_no, eq in enumerate(designed_equipment, 1):
        sb_insert("mee_design_equipment", {
            "project_id": pid, "line_no": line_no,
            "section": eq["section"], "sub_section": eq["sub_section"],
            "equipment": eq["name"], "description": eq["description"],
            "moc": eq["moc"], "qty": eq.get("qty", 1),
            "hta_m2": eq.get("hta_m2"),
            "shell_dia_mm": eq.get("shell_dia_mm"),
            "capacity_kl": eq.get("capacity_kl"),
        })
    st.success(f"✓ Sent to Costing as project #{pid}")
```

**Option B — view-shim the existing tables:**
If 10 already has a project-headers table (e.g. `process_design_projects`),
create SQL views aliasing it:
```sql
CREATE OR REPLACE VIEW public.mee_projects AS
    SELECT id, client_name, project_name, project_no, capacity,
           'MEE' AS plant_type, location, NULL::jsonb AS design_basis,
           status, created_by, created_at, updated_at
    FROM public.process_design_projects
    WHERE plant_type = 'MEE' OR vertical = 'MEE';
```
Same for `mee_design_equipment` aliasing whatever table 10 already populates.

### `11_Offer_Generator.py` — read costings
Add a "Pull from Costing" picker that queries `mee_qps_costings` where
`status = 'Issued'`:
```python
from bg_estimation_costing import db as costing_db

issued = [c for c in costing_db.list_costings()
          if c.get("status") == "Issued"]
opts = [f"#{c['id']}  ·  {c['client_name']}  ·  ₹{c['quote_price']/1e5:,.1f} L"
        for c in issued]
chosen = st.selectbox("Pick an Issued costing", opts)
if chosen:
    cid = int(chosen.split("·")[0].replace("#", "").strip())
    header = costing_db.get_costing(cid)
    lines  = costing_db.get_costing_lines(cid)
    # ... use header["quote_price"], lines[*]["unit_cost"], etc.
    # to populate the offer document
```

Want me to write either of these wiring changes for you in a follow-up? Just
share the relevant section of `10_Process_Design.py` or `11_Offer_Generator.py`
and I'll match it precisely.

## Master-table integration (already wired)

The new module reads the **same master tables** the Pharma estimation
already uses. Migration 02 extends both tables and seeds them with MEE-relevant items.

### `est_rm_master`
| category | What it holds | Used by |
|----------|---------------|---------|
| `RM`     | Sheet/plate materials with ₹/kg rate | Parametric calculators |
| `BO`     | Pre-priced instruments, pumps, valves, motors, panels, cables | "Pick from BO Master" expanders on EIA + Equipment tabs |

### New columns in `est_rm_master` (migration 02)
- `sub_type` — finer category (`Temperature`, `Pressure`, `Flow`, `Drive`, `Panel`...)
- `vendor` — supplier name (Yokogawa, E+H, Crompton, etc.)
- `last_updated` — date stamp

### Seed data (~75 rows total)

**~50 BO rows** — Transmitters · Control valves · Manual valves · Pumps · Motors/Gearboxes/Seals · PLC/MCC/VFD panels · Cabling · Sight glasses

**~25 OH rows** — Labour ₹/kg for every material (MS / SS304 / SS316 / SS316L / SS316Ti / Duplex 2205/2507 / Super Duplex / Hastelloy / Hastelloy C22 / Ti Gr2), plus buffing, welding consumables, hydro/DP/RT testing, QA dossier, packing, transport, electro-polish

All seeds use `ON CONFLICT DO NOTHING` — safe to re-run, won't overwrite
anything you've already added manually.

## Five parametric calculators

`bg_estimation_costing/modules/qps_calculators.py` — modelled on B&G reference Excels.

| Calculator              | Reference workbook                         |
|-------------------------|--------------------------------------------|
| `stripper_column_cost`  | `1__Stripper_Column_Costing.xlsx`          |
| `heat_exchanger_cost`   | `2__Reboiler` / `3__Stripper_Condenser` / `5__Calandria` / `8__Surface_Condenser` / `11__ATFD_Condenser` |
| `vls_cost`              | `9__VLS_Costing.xlsx`                      |
| `tank_cost`             | `12__Tank_Costing.xlsx`                    |
| `atfd_cost`             | `10__ATFD_Costing__duplex.xlsx`            |

Each takes kwargs (HTA, dia, MOC, etc.) and returns a dict with cost
breakdown, weight breakdown, and (for HE) component-level rows. Rates come
from the `rm_rates` and `lab_rates` dicts which are populated from
`est_rm_master` and `est_oh_master` at the start of each costing.

## Page sidebar appearance after deploy

```
🏠 app
─────────────────────
📊 00 Founder Analytics
⚓ 01 Anchor Portal
🛒 02 Purchase Console
📈 04 Project Reporting
🔧 05 Machining Buffing Hub
💰 09 Estimation Costing       ← Pharma vertical
📐 10 Process Design           ← MEE vertical
📄 11 Offer Generator          ← MEE vertical
🧾 12 MEE Estimation Costing   ← NEW
... (other existing pages)
```
