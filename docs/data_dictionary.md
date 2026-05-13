# Data Dictionary

This document describes the fields in the two master tables produced by
`scripts/01_ingest_clean_audit.py`. Everywhere in this project, "meals"
means **reported meals served**, not unique children served.

## `summer_meals_master`

| Column | Type | Source / definition |
|---|---|---|
| `source_dataset` | text | Human-readable dataset label from the registry. |
| `source_dataset_id` | text | Socrata four-by-four ID. |
| `program_year` | int | From the dataset's `programyear` column when present; otherwise the registry value. |
| `program_type` | text | `SSO`, `SFSP`, or `UNKNOWN`. From the row's `program` column when present; otherwise the registry default. |
| `ce_id` | text | Contracting Entity ID. From `ceid`. |
| `ce_name` | text | Contracting Entity name. From `cename`. |
| `site_id` | text | From `siteid`. |
| `site_name` | text | From `sitename`. |
| `county` | text | From `sitecounty`; falls back to `cecounty`. |
| `region` | text | From `tdaregion`; falls back to `esc`. |
| `site_type` | text | From `typeofagency` / `typeoforg`. |
| `service_days` | numeric | From `lunchdays`, `breakfastdays`, or `supperdays` — whichever is present first. |
| `breakfast_meals` | numeric | Reported breakfasts. From `breakfasttotal`; falls back to `breakfast`. |
| `lunch_meals` | numeric | Reported lunches. From `lunchtotal`; falls back to `lunch`. |
| `snack_meals` | numeric | `amsnacktotal + pmsnacktotal` when present, otherwise `totalsnacks`. |
| `supper_meals` | numeric | Reported suppers. From `suppertotal`; falls back to `supper`. |
| `total_meals` | numeric | Reported total. Prefer `totalmealssnacks`, then `totalmeals_snacks`, otherwise the sum of the four columns above. |
| `covid_site_flag` | text | Single-character flag where the source dataset exposes one; otherwise `N`. |
| `claim_date` | text | From `claimdate` when present. |
| `record_match_key` | text | Pipe-joined, upper-cased, alphanumeric-only key from `program_year`, `ce_id`, `site_id`, `site_name`, `county`, `claim_date`. Used for duplicate detection. |
| `data_quality_flags` | text | Pipe-joined flags (see below) or `ok`. |

### Row-level data-quality flags — meals

- `missing_ce_id`
- `missing_site_id`
- `missing_site_name`
- `missing_county`
- `unknown_program_type`
- `zero_total_meals`
- `negative_total_meals`

## `reimbursements_master`

| Column | Type | Source / definition |
|---|---|---|
| `source_dataset` | text | Human-readable dataset label. |
| `source_dataset_id` | text | Socrata four-by-four ID. |
| `program_year` | int | From `programyear` when present; otherwise registry value. |
| `program_type` | text | `SSO`, `SFSP`, or `UNKNOWN`. |
| `ce_id` | text | From `ceid`. |
| `ce_name` | text | From `cename`. |
| `county` | text | From `cecounty`. |
| `region` | text | From `tdaregion`. |
| `claim_date` | text | From `claimdate` when present. |
| `total_meals` | numeric | Sum of `breakfastmealsreimbursed + amsnackmealsreimbursed + lunchmealsreimbursed + pmsnackmealsreimbursed + suppermealsreimbursed`. Reported (claimed) meals, not unique children. |
| `reimbursement_amount` | numeric | From `totalreimbursement`. |
| `reimbursement_per_meal` | numeric | `reimbursement_amount / total_meals` when `total_meals > 0`. |
| `data_quality_flags` | text | Pipe-joined flags (see below) or `ok`. |

### Row-level data-quality flags — reimbursements

- `missing_ce_id`
- `missing_ce_name`
- `missing_reimbursement_amount`
- `zero_total_meals`
- `negative_reimbursement_amount`
- `suspicious_reimbursement_per_meal_over_20` (raw `reimbursement_per_meal` greater than $20)

## `approved_sites_master`

Currently empty in normal runs because the underlying Socrata
endpoints return 403. Schema is preserved so downstream tooling does
not need to special-case the empty case.

| Column | Type | Notes |
|---|---|---|
| `source_dataset`, `source_dataset_id`, `approval_year`, `program_type` | — | Registry-derived. |
| `ce_id`, `ce_name`, `site_id`, `site_name`, `county`, `site_type` | — | From the columns of the same name. |
| `record_match_key` | text | Same recipe as in `summer_meals_master`. |
| `data_quality_flags` | text | `ok` placeholder until the underlying datasets are available. |
