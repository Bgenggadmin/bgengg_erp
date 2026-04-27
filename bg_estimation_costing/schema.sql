-- ════════════════════════════════════════════════════════════════════════════
-- B&G ENGINEERING — MEE Vertical · Estimation & Costing tables
-- ════════════════════════════════════════════════════════════════════════════
-- This file defines the Supabase tables consumed and produced by
-- 10_MEE_Estimation_Costing.py.
--
-- DATA FLOW
--   process_design.py     →  mee_projects        (1 row per project)
--                            mee_design_equipment (n rows per project)
--   estimation_costing.py →  reads above, writes:
--                            mee_qps_costings     (1 row per costing/revision)
--                            mee_qps_costing_lines (n rows per costing)
--   offer_generator.py    ←  reads mee_qps_costings + lines (status='Issued')
-- ════════════════════════════════════════════════════════════════════════════

-- ────────────────────────────────────────────────────────────────────────────
-- 1.  mee_projects  (header — one row per process-design project)
-- ────────────────────────────────────────────────────────────────────────────
-- Created by process_design.py. Costing module only READS from this.
CREATE TABLE IF NOT EXISTS public.mee_projects (
    id              BIGSERIAL PRIMARY KEY,
    client_name     TEXT NOT NULL,
    project_name    TEXT,
    project_no      TEXT,
    capacity        TEXT,                  -- e.g. "150 KLD"
    plant_type      TEXT,                  -- ZLD / MEE / Stripping / ...
    location        TEXT,
    design_basis    JSONB,                 -- whole process-design payload
    status          TEXT DEFAULT 'In Design',
    created_by      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ────────────────────────────────────────────────────────────────────────────
-- 2.  mee_design_equipment  (n rows per project — equipment list from sizing)
-- ────────────────────────────────────────────────────────────────────────────
-- Created by process_design.py. Shape mirrors the QPS reference.
CREATE TABLE IF NOT EXISTS public.mee_design_equipment (
    id              BIGSERIAL PRIMARY KEY,
    project_id      BIGINT NOT NULL REFERENCES public.mee_projects(id)
                                    ON DELETE CASCADE,
    line_no         INT NOT NULL,
    -- QPS classification
    section         TEXT NOT NULL,         -- Evaporator/Stripper/Dryer/Common
    sub_section     TEXT,                  -- HEAT EXCHANGER / TANK / SEPARATORS / ...
    equipment       TEXT NOT NULL,
    description     TEXT,
    moc             TEXT,
    qty             INT DEFAULT 1,
    unit_cost       NUMERIC(14,2) DEFAULT 0,   -- usually 0 from process design
    category        TEXT DEFAULT 'B&G-MFG',
    item_type       TEXT DEFAULT 'MECH_EQP',
    -- Parametric sizing (any subset, used by costing calculators)
    hta_m2          NUMERIC(10,2),
    shell_dia_mm    NUMERIC(10,2),
    shell_height_m  NUMERIC(10,2),
    shell_length_m  NUMERIC(10,2),
    tube_length_m   NUMERIC(10,2),
    tube_od_mm      NUMERIC(10,2),
    tube_thk_mm     NUMERIC(10,2),
    n_tubes         INT,
    capacity_kl     NUMERIC(10,3),
    L_over_D        NUMERIC(6,3),
    h_over_d        NUMERIC(6,3),
    gross_volume_m3 NUMERIC(10,3),
    n_blades        INT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (project_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_design_eq_project
    ON public.mee_design_equipment(project_id);

-- ────────────────────────────────────────────────────────────────────────────
-- 3.  mee_qps_costings  (header — 1 row per costing revision)
-- ────────────────────────────────────────────────────────────────────────────
-- Written by 10_MEE_Estimation_Costing.py.
-- offer_generator.py reads from here when status = 'Issued'.
CREATE TABLE IF NOT EXISTS public.mee_qps_costings (
    id              BIGSERIAL PRIMARY KEY,
    project_id      BIGINT REFERENCES public.mee_projects(id) ON DELETE SET NULL,
    qps_no          TEXT NOT NULL,
    revision        TEXT DEFAULT 'R0',
    status          TEXT DEFAULT 'Draft',  -- Draft / Issued / Won / Lost / On Hold
    -- Customer / project (snapshotted at costing time so offer is reproducible
    -- even if the source project changes later)
    client_name     TEXT,
    project_name    TEXT,
    project_no      TEXT,
    location        TEXT,
    capacity        TEXT,
    plant_type      TEXT,
    costing_date    DATE,
    prepared_by     TEXT,
    approved_by     TEXT,
    scope_summary   TEXT,
    -- Full state snapshot — eia_lines, pipeline_lines, manhour_lines, %s,
    -- cashflow pattern, rm_rates, lab_rates  — enables exact reproduction
    state_json      JSONB,
    -- Roll-up totals — offer_generator pulls these directly
    op_cost         NUMERIC(14,2),
    soft_cost       NUMERIC(14,2),
    supply_cost     NUMERIC(14,2),
    quote_price     NUMERIC(14,2),
    target_price    NUMERIC(14,2),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_costings_project
    ON public.mee_qps_costings(project_id);
CREATE INDEX IF NOT EXISTS idx_costings_status
    ON public.mee_qps_costings(status);

-- ────────────────────────────────────────────────────────────────────────────
-- 4.  mee_qps_costing_lines  (n rows per costing — one per equipment item)
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.mee_qps_costing_lines (
    id              BIGSERIAL PRIMARY KEY,
    costing_id      BIGINT NOT NULL REFERENCES public.mee_qps_costings(id)
                                    ON DELETE CASCADE,
    line_no         INT NOT NULL,
    section         TEXT,
    sub_section     TEXT,
    equipment       TEXT,
    description     TEXT,
    moc             TEXT,
    qty             INT DEFAULT 1,
    unit_cost       NUMERIC(14,2) DEFAULT 0,
    category        TEXT,
    item_type       TEXT,
    calc_source     TEXT,                  -- 'Manual' / 'process_design' / calculator name
    design_payload  JSONB,                 -- sizing inputs, so a calculator can re-cost
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (costing_id, line_no)
);
CREATE INDEX IF NOT EXISTS idx_costing_lines_costing
    ON public.mee_qps_costing_lines(costing_id);

-- ────────────────────────────────────────────────────────────────────────────
-- ROW-LEVEL SECURITY (optional — enable if you use Supabase Auth)
-- ────────────────────────────────────────────────────────────────────────────
-- ALTER TABLE public.mee_projects             ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.mee_design_equipment     ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.mee_qps_costings         ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.mee_qps_costing_lines    ENABLE ROW LEVEL SECURITY;
--
-- CREATE POLICY "MEE team can read"  ON public.mee_qps_costings
--     FOR SELECT TO authenticated USING (true);
-- CREATE POLICY "MEE team can write" ON public.mee_qps_costings
--     FOR INSERT TO authenticated WITH CHECK (true);
--   ... (similar for the other tables)

-- ────────────────────────────────────────────────────────────────────────────
-- updated_at trigger (Supabase pattern)
-- ────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_costings_updated ON public.mee_qps_costings;
CREATE TRIGGER trg_costings_updated
    BEFORE UPDATE ON public.mee_qps_costings
    FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();

DROP TRIGGER IF EXISTS trg_projects_updated ON public.mee_projects;
CREATE TRIGGER trg_projects_updated
    BEFORE UPDATE ON public.mee_projects
    FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
