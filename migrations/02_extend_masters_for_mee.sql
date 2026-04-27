-- ════════════════════════════════════════════════════════════════════════════
-- Migration 2 — extend shared masters for MEE costing module
-- ════════════════════════════════════════════════════════════════════════════
-- Run this AFTER mee_costing_schema.sql is applied.
-- Idempotent — safe to re-run (uses IF NOT EXISTS / ON CONFLICT).
--
-- Changes
-- ───────
-- 1. est_rm_master  → add `sub_type`, `vendor`, `last_updated` columns
-- 2. est_rm_master  → seed BO rows for typical MEE bought-out items
--                      (instruments, pumps, valves, panels, motors)
-- 3. est_oh_master  → add `material` column for cleaner labour-rate lookups
-- 4. est_oh_master  → seed labour rates for all materials the calculators use
-- ════════════════════════════════════════════════════════════════════════════


-- ────────────────────────────────────────────────────────────────────────────
-- 1.  est_rm_master — add columns
-- ────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.est_rm_master
    ADD COLUMN IF NOT EXISTS sub_type     TEXT,
    ADD COLUMN IF NOT EXISTS vendor       TEXT,
    ADD COLUMN IF NOT EXISTS last_updated DATE DEFAULT CURRENT_DATE;

-- Index for quick filtering on the BO picker
CREATE INDEX IF NOT EXISTS idx_rm_master_category
    ON public.est_rm_master (category);
CREATE INDEX IF NOT EXISTS idx_rm_master_rm_type
    ON public.est_rm_master (rm_type);
CREATE INDEX IF NOT EXISTS idx_rm_master_sub_type
    ON public.est_rm_master (sub_type);


-- ────────────────────────────────────────────────────────────────────────────
-- 2.  est_rm_master — seed BO rows for MEE
-- ────────────────────────────────────────────────────────────────────────────
-- Uses ON CONFLICT (ref_code) DO NOTHING — won't overwrite existing rows.
-- If your existing table doesn't have a UNIQUE constraint on ref_code, this
-- will be a no-op for duplicates so insert is safe.
DO $$
BEGIN
    -- Add UNIQUE on ref_code if it doesn't already exist (ignore failure)
    BEGIN
        ALTER TABLE public.est_rm_master
            ADD CONSTRAINT est_rm_master_ref_code_key UNIQUE (ref_code);
    EXCEPTION WHEN duplicate_table OR duplicate_object THEN NULL;
    END;
END $$;

INSERT INTO public.est_rm_master
    (ref_code, description, category, rm_type, sub_type, material, spec, size,
     uom, rate, vendor, active)
VALUES
    -- ═════════════ INSTRUMENTS — TRANSMITTERS ═════════════
    ('INST-TT-FLP-01', 'Temperature Transmitter — FLP, Pt100', 'BO',
        'Transmitter', 'Temperature', NULL, 'FLP', '0–200°C',
        'Nos', 5000, 'Yokogawa / E+H', 'Yes'),
    ('INST-TT-FLP-02', 'Temperature Transmitter — FLP, RTD',  'BO',
        'Transmitter', 'Temperature', NULL, 'FLP', '0–300°C',
        'Nos', 6500, 'Yokogawa / E+H', 'Yes'),
    ('INST-PT-FLP-01', 'Pressure Transmitter — FLP, gauge',   'BO',
        'Transmitter', 'Pressure',    NULL, 'FLP', '0–10 bar',
        'Nos', 30000, 'Yokogawa / Honeywell', 'Yes'),
    ('INST-PT-FLP-02', 'Vacuum Transmitter — FLP, abs',       'BO',
        'Transmitter', 'Pressure',    NULL, 'FLP', '0–1 bar abs',
        'Nos', 35000, 'Yokogawa / Honeywell', 'Yes'),
    ('INST-LT-FLP-01', 'Level Transmitter — FLP, radar',      'BO',
        'Transmitter', 'Level',       NULL, 'FLP', 'Up to 6 m',
        'Nos', 100000, 'E+H / Vega', 'Yes'),
    ('INST-LT-FLP-02', 'Level Transmitter — FLP, DP-type',    'BO',
        'Transmitter', 'Level',       NULL, 'FLP', 'Up to 4 m',
        'Nos', 75000, 'Yokogawa', 'Yes'),
    ('INST-FT-VTX-01', 'Vortex Flow Meter — DN50',            'BO',
        'Transmitter', 'Flow',        NULL, 'FLP', 'DN50',
        'Nos', 150000, 'E+H / KROHNE', 'Yes'),
    ('INST-FT-VTX-02', 'Vortex Flow Meter — DN80',            'BO',
        'Transmitter', 'Flow',        NULL, 'FLP', 'DN80',
        'Nos', 180000, 'E+H / KROHNE', 'Yes'),
    ('INST-FT-MAG-01', 'Mag Flow Meter — DN50',               'BO',
        'Transmitter', 'Flow',        NULL, 'FLP', 'DN50',
        'Nos', 80000, 'KROHNE / E+H', 'Yes'),
    ('INST-RM-01',     'Rota-meter — DN25, glass tube',       'BO',
        'Transmitter', 'Flow',        NULL, 'NA',  'DN25',
        'Nos', 25000, 'Eureka / Placka', 'Yes'),
    ('INST-RM-02',     'Metal-tube Rotameter — DN50',         'BO',
        'Transmitter', 'Flow',        NULL, 'FLP', 'DN50',
        'Nos', 80000, 'Eureka', 'Yes'),

    -- ═════════════ INSTRUMENTS — CONTROL VALVES ═════════════
    ('INST-CV-FLP-50', 'Control Valve — DN50, FLP, pneumatic','BO',
        'Valve', 'Control',           NULL, 'FLP', 'DN50',
        'Nos', 75000, 'Forbes Marshall / Spirax', 'Yes'),
    ('INST-CV-FLP-80', 'Control Valve — DN80, FLP, pneumatic','BO',
        'Valve', 'Control',           NULL, 'FLP', 'DN80',
        'Nos', 110000, 'Forbes Marshall', 'Yes'),
    ('INST-CV-LV-01',  'Level Control Valve — DN50',          'BO',
        'Valve', 'Control',           NULL, 'FLP', 'DN50',
        'Nos', 70000, 'Forbes Marshall', 'Yes'),
    ('INST-CV-FV-01',  'Flow Control Valve — DN50',           'BO',
        'Valve', 'Control',           NULL, 'FLP', 'DN50',
        'Nos', 70000, 'Forbes Marshall', 'Yes'),

    -- ═════════════ MANUAL VALVES ═════════════
    ('VLV-BFV-50',     'Butterfly Valve — DN50, SS316',       'BO',
        'Valve', 'Manual',            'SS316', 'NA',  'DN50',
        'Nos', 4500, 'Audco / Intervalve', 'Yes'),
    ('VLV-BFV-80',     'Butterfly Valve — DN80, SS316',       'BO',
        'Valve', 'Manual',            'SS316', 'NA',  'DN80',
        'Nos', 7500, 'Audco / Intervalve', 'Yes'),
    ('VLV-BFV-100',    'Butterfly Valve — DN100, SS316',      'BO',
        'Valve', 'Manual',            'SS316', 'NA',  'DN100',
        'Nos', 11000, 'Audco / Intervalve', 'Yes'),
    ('VLV-BFV-150',    'Butterfly Valve — DN150, SS316',      'BO',
        'Valve', 'Manual',            'SS316', 'NA',  'DN150',
        'Nos', 18000, 'Audco / Intervalve', 'Yes'),
    ('VLV-BFV-200',    'Butterfly Valve — DN200, SS316',      'BO',
        'Valve', 'Manual',            'SS316', 'NA',  'DN200',
        'Nos', 28000, 'Audco / Intervalve', 'Yes'),
    ('VLV-BV-25',      'Ball Valve — DN25, SS316',            'BO',
        'Valve', 'Manual',            'SS316', 'NA',  'DN25',
        'Nos', 3500, 'Audco', 'Yes'),
    ('VLV-BV-50',      'Ball Valve — DN50, SS316',            'BO',
        'Valve', 'Manual',            'SS316', 'NA',  'DN50',
        'Nos', 6500, 'Audco', 'Yes'),
    ('VLV-NRV-50',     'Non-Return Valve — DN50, SS316',      'BO',
        'Valve', 'Manual',            'SS316', 'NA',  'DN50',
        'Nos', 8000, 'Audco', 'Yes'),
    ('VLV-NRV-80',     'Non-Return Valve — DN80, SS316',      'BO',
        'Valve', 'Manual',            'SS316', 'NA',  'DN80',
        'Nos', 12000, 'Audco', 'Yes'),

    -- ═════════════ PUMPS ═════════════
    ('PMP-CF-FEED-01', 'Centrifugal Pump — Feed, 8 m³/h × 60 m', 'BO',
        'Pump', 'Centrifugal',        'SS316L', 'NA',  '8 m³/h × 60 m',
        'Nos', 100000, 'Kirloskar / KSB', 'Yes'),
    ('PMP-CF-RCP-150', 'Centrifugal Pump — RCP, 150 m³/h × 12 m', 'BO',
        'Pump', 'Centrifugal',        'SS316', 'NA',  '150 m³/h × 12 m',
        'Nos', 300000, 'Kirloskar / KSB', 'Yes'),
    ('PMP-CF-RCP-225', 'Centrifugal Pump — RCP, 225 m³/h × 12 m', 'BO',
        'Pump', 'Centrifugal',        'SS316', 'NA',  '225 m³/h × 12 m',
        'Nos', 360000, 'Kirloskar / KSB', 'Yes'),
    ('PMP-CF-PROD-01', 'Centrifugal Pump — Product, 0.5 m³/h × 15 m', 'BO',
        'Pump', 'Centrifugal',        'SS316', 'NA',  '0.5 m³/h × 15 m',
        'Nos', 55000, 'Kirloskar', 'Yes'),
    ('PMP-CF-PCT-01',  'Centrifugal Pump — Process Cond, 2 m³/h × 15 m', 'BO',
        'Pump', 'Centrifugal',        'SS304', 'NA',  '2 m³/h × 15 m',
        'Nos', 60000, 'Kirloskar', 'Yes'),
    ('PMP-CF-SCT-01',  'Centrifugal Pump — Steam Cond, 1 m³/h × 12 m', 'BO',
        'Pump', 'Centrifugal',        'SS304', 'NA',  '1 m³/h × 12 m',
        'Nos', 50000, 'Kirloskar', 'Yes'),
    ('PMP-VAC-01',     'Vacuum Pump — LRVP, 200 m³/h',         'BO',
        'Pump', 'Vacuum',             'SS316', 'NA',  '200 m³/h',
        'Nos', 450000, 'Everest', 'Yes'),
    ('PMP-VAC-02',     'Vacuum Pump — LRVP, 400 m³/h',         'BO',
        'Pump', 'Vacuum',             'SS316', 'NA',  '400 m³/h',
        'Nos', 750000, 'Everest', 'Yes'),

    -- ═════════════ MOTORS / GEARBOXES (ATFD drives) ═════════════
    ('DRV-MTR-15',     'Motor — 15 kW, FLP, 1450 RPM',         'BO',
        'Motor', 'Drive',             NULL, 'FLP', '15 kW',
        'Nos', 110000, 'Crompton / ABB', 'Yes'),
    ('DRV-MTR-22',     'Motor — 22 kW, FLP, 1450 RPM',         'BO',
        'Motor', 'Drive',             NULL, 'FLP', '22 kW',
        'Nos', 150000, 'Crompton / ABB', 'Yes'),
    ('DRV-MTR-30',     'Motor — 30 kW, FLP, 1450 RPM',         'BO',
        'Motor', 'Drive',             NULL, 'FLP', '30 kW',
        'Nos', 200000, 'Crompton / ABB', 'Yes'),
    ('DRV-GBX-01',     'Gearbox — Helical, 1:30, 22 kW',       'BO',
        'Gearbox', 'Drive',           NULL, 'NA', '1:30 × 22 kW',
        'Nos', 250000, 'Bonfiglioli / Premium', 'Yes'),
    ('DRV-MS-01',      'Mechanical Seal — Single, SS316',      'BO',
        'Seal', 'Drive',              'SS316', 'NA', 'Single',
        'Nos', 35000, 'EagleBurgmann', 'Yes'),
    ('DRV-MS-02',      'Mechanical Seal — Double, SS316',      'BO',
        'Seal', 'Drive',              'SS316', 'NA', 'Double',
        'Nos', 75000, 'EagleBurgmann', 'Yes'),

    -- ═════════════ AUTOMATION PANELS ═════════════
    ('PNL-PLC-AB',     'PLC + HMI Panel — Allen-Bradley',      'BO',
        'PLC', 'Panel',               NULL, 'NA', 'CompactLogix + 12" HMI',
        'Nos', 1500000, 'Rockwell / Allen-Bradley', 'Yes'),
    ('PNL-PLC-SIE',    'PLC + HMI Panel — Siemens S7-1500',    'BO',
        'PLC', 'Panel',               NULL, 'NA', 'S7-1500 + 15" HMI',
        'Nos', 1800000, 'Siemens', 'Yes'),
    ('PNL-PLC-MICRO',  'PLC + HMI Panel — Micrologix',         'BO',
        'PLC', 'Panel',               NULL, 'NA', 'MicroLogix + 7" HMI',
        'Nos', 700000, 'Rockwell', 'Yes'),
    ('PNL-MCC-50',     'MCC Panel — 50 kW, with VFD + DOL',    'BO',
        'MCC', 'Panel',               NULL, 'NA', '50 kW',
        'Nos', 800000, 'L&T / Siemens', 'Yes'),
    ('PNL-MCC-100',    'MCC Panel — 100 kW, VFD + DOL',        'BO',
        'MCC', 'Panel',               NULL, 'NA', '100 kW',
        'Nos', 1200000, 'L&T / Siemens', 'Yes'),
    ('PNL-MCC-200',    'MCC Panel — 200 kW, VFD + DOL',        'BO',
        'MCC', 'Panel',               NULL, 'NA', '200 kW',
        'Nos', 1900000, 'L&T / Siemens', 'Yes'),
    ('PNL-VFD-15',     'VFD — 15 kW, FLP-rated',               'BO',
        'VFD', 'Panel',               NULL, 'NA', '15 kW',
        'Nos', 80000, 'Danfoss / ABB', 'Yes'),
    ('PNL-VFD-22',     'VFD — 22 kW, FLP-rated',               'BO',
        'VFD', 'Panel',               NULL, 'NA', '22 kW',
        'Nos', 110000, 'Danfoss / ABB', 'Yes'),

    -- ═════════════ FIELD WIRING / CABLES ═════════════
    ('CBL-CT-01',      'Cable Tray — GI, 300mm wide perforated','BO',
        'Cable', 'Tray',              'GI', 'NA', '300mm × 50mm',
        'M',   850, 'Profab', 'Yes'),
    ('CBL-CT-02',      'Cable Tray — GI, 200mm wide',          'BO',
        'Cable', 'Tray',              'GI', 'NA', '200mm × 50mm',
        'M',   650, 'Profab', 'Yes'),
    ('CBL-PWR-25',     'Power Cable — 25 sq.mm Cu, FRLS',      'BO',
        'Cable', 'Power',             'Cu', 'NA', '25 sq.mm × 4C',
        'M',   320, 'Polycab / Havells', 'Yes'),
    ('CBL-PWR-10',     'Power Cable — 10 sq.mm Cu, FRLS',      'BO',
        'Cable', 'Power',             'Cu', 'NA', '10 sq.mm × 4C',
        'M',   180, 'Polycab / Havells', 'Yes'),
    ('CBL-CTRL-01',    'Control Cable — 1.5 sq.mm × 12C',      'BO',
        'Cable', 'Control',           'Cu', 'NA', '1.5 sq.mm × 12C',
        'M',   85, 'Polycab', 'Yes'),
    ('CBL-INSTR-01',   'Instrument Cable — 0.5 sq.mm twisted shielded', 'BO',
        'Cable', 'Instrument',        'Cu', 'NA', '0.5 sq × 2 pair',
        'M',   45, 'Polycab', 'Yes'),
    ('FLD-WIRE-LS',    'Field Wiring — Lump-sum installation', 'BO',
        'Cable', 'Service',           NULL, 'NA', 'Per project',
        'LS',  700000, 'In-house EIA team', 'Yes'),

    -- ═════════════ SIGHT GLASSES / MISC ═════════════
    ('MISC-SG-01',     'Sight Glass — DN80, full-view',        'BO',
        'Sight Glass', 'Vessel',      'SS316L', 'NA', 'DN80',
        'Nos', 5000, 'Pune Techtrol', 'Yes'),
    ('MISC-SG-02',     'Sight Glass — DN100, illuminated',     'BO',
        'Sight Glass', 'Vessel',      'SS316L', 'NA', 'DN100',
        'Nos', 8500, 'Pune Techtrol', 'Yes'),
    ('MISC-PG-01',     'Pressure Gauge — bourdon, 0–10 bar',   'BO',
        'Gauge', 'Local',             NULL, 'NA', '100 mm dial',
        'Nos', 800, 'Forbes / Wika', 'Yes'),
    ('MISC-TG-01',     'Temperature Gauge — bimetal, 0–200°C', 'BO',
        'Gauge', 'Local',             NULL, 'NA', '100 mm dial',
        'Nos', 1500, 'Forbes / Wika', 'Yes')
ON CONFLICT (ref_code) DO NOTHING;


-- ────────────────────────────────────────────────────────────────────────────
-- 3.  est_oh_master — add `material` column for cleaner labour-rate lookups
-- ────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.est_oh_master
    ADD COLUMN IF NOT EXISTS material     TEXT,
    ADD COLUMN IF NOT EXISTS last_updated DATE DEFAULT CURRENT_DATE;

CREATE INDEX IF NOT EXISTS idx_oh_master_oh_type
    ON public.est_oh_master (oh_type);
CREATE INDEX IF NOT EXISTS idx_oh_master_material
    ON public.est_oh_master (material);

DO $$
BEGIN
    BEGIN
        ALTER TABLE public.est_oh_master
            ADD CONSTRAINT est_oh_master_oh_code_key UNIQUE (oh_code);
    EXCEPTION WHEN duplicate_table OR duplicate_object THEN NULL;
    END;
END $$;


-- ────────────────────────────────────────────────────────────────────────────
-- 4.  est_oh_master — seed labour rates for all calculator materials
-- ────────────────────────────────────────────────────────────────────────────
INSERT INTO public.est_oh_master
    (oh_code, description, oh_type, material, uom, rate, source)
VALUES
    -- Fabrication labour by material (₹/kg)
    ('LAB-MS',          'MS',           'LABOUR', 'MS',           'Kg', 35,  'Internal'),
    ('LAB-SS304',       'SS304',        'LABOUR', 'SS304',        'Kg', 50,  'Internal'),
    ('LAB-SS316',       'SS316',        'LABOUR', 'SS316',        'Kg', 50,  'Internal'),
    ('LAB-SS316L',      'SS316L',       'LABOUR', 'SS316L',       'Kg', 50,  'Internal'),
    ('LAB-SS316Ti',     'SS316Ti',      'LABOUR', 'SS316Ti',      'Kg', 80,  'Internal'),
    ('LAB-DUPLEX-2205', 'Duplex 2205',  'LABOUR', 'Duplex 2205',  'Kg', 100, 'Internal'),
    ('LAB-DUPLEX-2507', 'Duplex 2507',  'LABOUR', 'Duplex 2507',  'Kg', 120, 'Internal'),
    ('LAB-SUPER-DUPLEX','Super Duplex', 'LABOUR', 'Super Duplex', 'Kg', 120, 'Internal'),
    ('LAB-HASTELLOY',   'Hastelloy',    'LABOUR', 'Hastelloy',    'Kg', 150, 'Internal'),
    ('LAB-HASTELLOY-C', 'Hastelloy C22','LABOUR', 'Hastelloy C22','Kg', 150, 'Internal'),
    ('LAB-TI-GR2',      'Ti Gr2',       'LABOUR', 'Ti Gr2',       'Kg', 120, 'Internal'),

    -- Buffing / polishing labour (Ra ≤ 0.8 µm finish)
    ('LAB-BUFF-SS304',  'SS304 Buff',   'LABOUR_BUFF', 'SS304',  'Sq.M', 250, 'Internal'),
    ('LAB-BUFF-SS316L', 'SS316L Buff',  'LABOUR_BUFF', 'SS316L', 'Sq.M', 350, 'Internal'),

    -- Other overhead types
    ('CONS-WELD-01',    'Welding consumables', 'CONSUMABLES', NULL, 'Kg', 250, 'Internal'),
    ('CONS-GAS-01',     'Argon / shielding gas','CONSUMABLES', NULL, 'Hr', 80, 'Internal'),
    ('TEST-DP-01',      'Dye Penetrant Test',  'TESTING',     NULL, 'Sq.M', 150, 'Internal'),
    ('TEST-RT-01',      'Radiographic Test',   'TESTING',     NULL, 'Joint', 1200, 'Outsourced'),
    ('TEST-HYDRO-01',   'Hydro Test',          'TESTING',     NULL, 'LS',   25000, 'Internal'),
    ('DOC-QA-01',       'QA Dossier preparation','DOCS',      NULL, 'LS',   15000, 'Internal'),
    ('PACK-WOOD-01',    'Wooden crate packing','PACKING',     NULL, 'Cu.M', 3500, 'Outsourced'),
    ('TRSP-LCL-01',     'Local transport',     'TRANSPORT',   NULL, 'Trip', 8000, 'Outsourced'),
    ('TRSP-INTER-01',   'Interstate transport','TRANSPORT',   NULL, 'KM',   45,  'Outsourced'),
    ('EP-INT-01',       'Electro-polish — internal','ELECTRO_POLISH', 'SS316L', 'Sq.M', 1200, 'Outsourced'),
    ('EP-EXT-01',       'Electro-polish — external','ELECTRO_POLISH', 'SS316L', 'Sq.M', 800,  'Outsourced')
ON CONFLICT (oh_code) DO NOTHING;


-- ────────────────────────────────────────────────────────────────────────────
-- 5.  Verify with a quick row count
-- ────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    bo_count   INT;
    rm_count   INT;
    lab_count  INT;
BEGIN
    SELECT COUNT(*) INTO bo_count
        FROM public.est_rm_master WHERE category = 'BO' AND active != 'No';
    SELECT COUNT(*) INTO rm_count
        FROM public.est_rm_master WHERE category = 'RM' AND active != 'No';
    SELECT COUNT(*) INTO lab_count
        FROM public.est_oh_master WHERE oh_type IN ('LABOUR','LABOUR_BUFF');
    RAISE NOTICE 'Migration 2 complete:';
    RAISE NOTICE '  est_rm_master  RM rows:     %', rm_count;
    RAISE NOTICE '  est_rm_master  BO rows:     %', bo_count;
    RAISE NOTICE '  est_oh_master  LABOUR rows: %', lab_count;
END $$;
