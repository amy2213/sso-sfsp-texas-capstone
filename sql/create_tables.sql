DROP TABLE IF EXISTS summer_meals_master;
CREATE TABLE summer_meals_master (
    source_dataset TEXT,
    source_dataset_id TEXT,
    program_year INTEGER,
    program_type TEXT,
    ce_id TEXT,
    ce_name TEXT,
    site_id TEXT,
    site_name TEXT,
    county TEXT,
    region TEXT,
    site_type TEXT,
    service_days NUMERIC,
    breakfast_meals NUMERIC,
    lunch_meals NUMERIC,
    snack_meals NUMERIC,
    supper_meals NUMERIC,
    total_meals NUMERIC,
    covid_site_flag TEXT,
    claim_date TEXT,
    record_match_key TEXT,
    data_quality_flags TEXT
);

DROP TABLE IF EXISTS reimbursements_master;
CREATE TABLE reimbursements_master (
    source_dataset TEXT,
    source_dataset_id TEXT,
    program_year INTEGER,
    program_type TEXT,
    ce_id TEXT,
    ce_name TEXT,
    county TEXT,
    region TEXT,
    claim_date TEXT,
    total_meals NUMERIC,
    reimbursement_amount NUMERIC,
    reimbursement_per_meal NUMERIC,
    data_quality_flags TEXT
);

DROP TABLE IF EXISTS approved_sites_master;
CREATE TABLE approved_sites_master (
    source_dataset TEXT,
    source_dataset_id TEXT,
    approval_year INTEGER,
    program_type TEXT,
    ce_id TEXT,
    ce_name TEXT,
    site_id TEXT,
    site_name TEXT,
    county TEXT,
    site_type TEXT,
    record_match_key TEXT,
    data_quality_flags TEXT
);
