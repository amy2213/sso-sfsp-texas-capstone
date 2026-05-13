# Methodology

## Scope

This project compares the **Seamless Summer Option (SSO)** and the
**Summer Food Service Program (SFSP)** in Texas, using publicly
available datasets published by the Texas Department of Agriculture
(TDA) through the Texas Open Data Portal (Socrata, `data.texas.gov`).

## Datasets in scope

| Dataset ID | Label | Year(s) | Type |
|---|---|---|---|
| `ckuq-8u2b` | SSO Meal Counts 2019 | 2019 | meal_counts |
| `m23c-22mm` | SSO Meal Counts 2021-2022 | 2022 | meal_counts |
| `pxzu-afsv` | SFSP + SSO Meal Counts 2018 | 2018 | meal_counts |
| `4axx-sfpm` | All Summer Sites Meal Count 2024 | 2024 | meal_counts |
| `rbdj-agw7` | SSO Reimbursements 2019 | 2019 | reimbursements |
| `ti35-mz6c` | SSO Reimbursements 2021-2022 | 2022 | reimbursements |
| `4z3r-huup` | Approved SFSP and SSO Sites 2023 | 2023 | approved_sites (currently 403) |
| `j2sd-a7ir` | Approved SFSP and SSO Sites 2024 | 2024 | approved_sites (currently 403) |
| `t3jr-vyxe` | Approved SFSP and SSO Sites 2025 | 2025 | approved_sites (currently 403) |
| `4tpe-vtdp` | Approved CEs 2025 | 2025 | approved_ces (currently 403) |
| `4zvx-6dyc` | Approved CEs 2026 | 2026 | approved_ces (currently 403) |

## Ingestion

- A single Python script (`scripts/01_ingest_clean_audit.py`) drives the
  whole pipeline.
- Datasets are fetched with `sodapy.Socrata`. Each fetch is paginated:
  `limit=50000`, looping on `offset` until a page returns fewer rows
  than the limit. This avoids the silent 50,000-row truncation that
  affected the 2021–2022 dataset.
- Datasets that fail (e.g., approved-site datasets currently return 403)
  are logged and skipped. The rest of the pipeline still runs.

## Standardization

Two clean master tables are produced:

### `summer_meals_master`

Built from the meal-count datasets. Column mappings:

- `ce_id`            ← `ceid`
- `ce_name`          ← `cename`
- `site_id`          ← `siteid`
- `site_name`        ← `sitename`
- `county`           ← `sitecounty`, falling back to `cecounty`
- `region`           ← `tdaregion`, falling back to `esc`
- `program_year`     ← `programyear`, falling back to registry value
- `program_type`     ← derived from `program` column when present;
                        otherwise the registry `default_program_type`
- `site_type`        ← `typeofagency` / `typeoforg`
- `service_days`     ← `lunchdays` (or `breakfastdays`, `supperdays`)
- `breakfast_meals`  ← `breakfasttotal`, falling back to `breakfast`
- `lunch_meals`      ← `lunchtotal`, falling back to `lunch`
- `snack_meals`      ← `amsnacktotal + pmsnacktotal` when present,
                        otherwise `totalsnacks`
- `supper_meals`     ← `suppertotal`, falling back to `supper`
- `total_meals`      ← `totalmealssnacks`, then `totalmeals_snacks`,
                        otherwise the sum of the four per-meal-type
                        columns above

### `reimbursements_master`

Built from the reimbursement datasets. Column mappings:

- `ce_id`                  ← `ceid`
- `ce_name`                ← `cename`
- `county`                 ← `cecounty`
- `region`                 ← `tdaregion`
- `reimbursement_amount`   ← `totalreimbursement`
- `total_meals`            ← `breakfastmealsreimbursed + amsnackmealsreimbursed
                              + lunchmealsreimbursed + pmsnackmealsreimbursed
                              + suppermealsreimbursed`
- `reimbursement_per_meal` ← `reimbursement_amount / total_meals`
                              (when `total_meals > 0`)

## Program-type classification

For combined-program datasets (`pxzu-afsv`, `4axx-sfpm`), each row is
classified from the `program` column:

- Contains `SSO` or `SEAMLESS` → `SSO`
- Contains `SFSP` or `SUMMER FOOD` → `SFSP`
- Otherwise → `UNKNOWN` (and flagged in `data_quality_flags`)

## Data-quality flags

Each row in both master tables receives a pipe-joined
`data_quality_flags` string.

**Meals:** `missing_ce_id`, `missing_site_id`, `missing_site_name`,
`missing_county`, `unknown_program_type`, `zero_total_meals`,
`negative_total_meals`.

**Reimbursements:** `missing_ce_id`, `missing_ce_name`,
`missing_reimbursement_amount`, `zero_total_meals`,
`negative_reimbursement_amount`,
`suspicious_reimbursement_per_meal_over_20`.

A summary at the source-dataset × year grain is written to
`data/audit/data_quality_audit.csv`.

## Out of scope

- This pipeline does not attempt to count unique children served. See
  `docs/limitations.md`.
- Income, demographics, school enrollment, and SNAP/WIC overlap are
  not yet joined in. Those are candidate next steps once the meal
  master is stable.
