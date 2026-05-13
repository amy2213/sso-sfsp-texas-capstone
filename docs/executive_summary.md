# Executive Summary — placeholder

> This is a placeholder. It will be replaced once the analysis layer
> and Tableau dashboards are stable.

## Headline (to be filled in)

- Total reported meals served by program and year (2018, 2019, 2022, 2024)
- SSO year-over-year reported-meal growth
- Reimbursement per reported meal, by year, for the years where
  reimbursement data is available (2019, 2022)
- Geographic concentration of CEs / sites

## Caveats to repeat in every version of this summary

- "Meals" everywhere means **reported meals served**, not unique
  children served.
- Approved-site / approved-CE Socrata datasets currently return 403,
  so coverage comparisons (approved vs reporting) are not yet
  possible.
- Years 2020 and 2021 are absent from the public meal-count data
  surfaced here.

## Next analytical steps

1. Sanity-check `data/audit/data_quality_audit.csv` and explain the
   `unknown_program_type` rows in the 2018 and 2024 combined datasets.
2. Build the Tableau dashboards from the clean master CSVs.
3. Retry the approved-site / approved-CE datasets via a different
   access path (CSV download from the portal page, or a direct request
   to TDA), so we can compute approved-vs-reporting coverage.
