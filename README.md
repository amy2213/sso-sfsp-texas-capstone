# SSO vs SFSP Texas Capstone

A public-sector data analytics capstone comparing the **Seamless Summer
Option (SSO)** and the **Summer Food Service Program (SFSP)** in Texas,
using public datasets published by the Texas Department of Agriculture
on the Texas Open Data Portal (`data.texas.gov`).

## Research question

> How have reported meals served, sponsor participation, and reimbursement
> per reported meal evolved across SSO and SFSP in Texas, and what does
> the available public data tell us about how the two programs serve
> different populations and operate at different scales?

## Important data caveat

This pipeline reports **REPORTED MEALS SERVED**, not unique children
served. A child receiving both breakfast and lunch on the same day
counts as two reported meals. All charts, tables, and SQL queries use
the phrase "reported meals" to make this clear. Do not interpret any
output of this pipeline as a count of children fed.

## Tools

- **Python 3** (pandas, sodapy) for ingest, cleaning, and audit
- **SQL** (portable ANSI dialect — runs in DuckDB, SQLite, or Postgres)
  for analysis
- **Tableau** for the final dashboard
- **Texas Open Data Portal** (Socrata API) as the data source

## Pipeline

1. `scripts/01_ingest_clean_audit.py`
   - Fetches each dataset in `DATASETS` with paginated Socrata calls
     (`limit=50000`, looping on `offset`)
   - Writes raw CSVs to `data/raw/`
   - Profiles every column of every fetched dataset to
     `data/audit/schema_profile.csv`
   - Standardizes meal-count and reimbursement records into two master
     tables in `data/clean/`
   - Computes a per-row `data_quality_flags` column and a per-dataset
     audit summary in `data/audit/data_quality_audit.csv`
   - Emits `sql/create_tables.sql`
2. `sql/analysis_queries.sql` — headline analysis queries.
3. Tableau dashboards consume the clean master CSVs.

## How to run

```powershell
# from the repo root
.\.venv\Scripts\Activate.ps1
python scripts\01_ingest_clean_audit.py
```

## Current status

- Ingest, cleaning, and audit are working end-to-end.
- Six tabular datasets fetch successfully (four meal-count, two
  reimbursement).
- Five "approved sites" / "approved CEs" datasets currently return
  `403 Forbidden` from the Socrata API. They are kept in the registry
  but logged-and-skipped so they do not break the pipeline.
- The 2021–2022 meal-count dataset (`m23c-22mm`) previously returned
  exactly 50,000 rows under the default API limit. Pagination is now
  in place so the true row count is fetched.

## Known data limitations

- **Reported meals ≠ children served.** See the caveat above.
- **Approved-site/CE datasets return 403** through the public Socrata
  API. We log the failure and continue. `data/clean/approved_sites_master.csv`
  may therefore be empty.
- **2021–2022 pagination risk.** The Socrata default page limit is 1,000
  and the hard cap per request can be 50,000. Without pagination the
  2021–2022 meal-count dataset silently truncates at 50,000 rows. The
  current pipeline pages with `limit=50000` and loops on `offset` until
  a short page is returned, which removes that silent truncation.
- **Schema drift between years.** Different program years use different
  column names (`breakfasttotal` vs `breakfast`, `totalmealssnacks` vs
  `totalmeals_snacks`, `program` only present in combined datasets).
  The standardization layer prefers the more specific columns and
  falls back to the bare names.
- **Program-type inference.** Single-program datasets (e.g.,
  `SSO Meal Counts 2019`) are tagged from the registry. Combined
  datasets (`pxzu-afsv`, `4axx-sfpm`) read the `program` column and
  classify each row as `SSO`, `SFSP`, or `UNKNOWN`.

## Repository layout

```
.
├── data/
│   ├── raw/      # one CSV per fetched dataset
│   ├── clean/    # summer_meals_master.csv, reimbursements_master.csv, approved_sites_master.csv
│   └── audit/    # schema_profile.csv, data_quality_audit.csv
├── docs/
│   ├── methodology.md
│   ├── limitations.md
│   ├── data_dictionary.md
│   └── executive_summary.md
├── scripts/
│   └── 01_ingest_clean_audit.py
├── sql/
│   ├── create_tables.sql
│   └── analysis_queries.sql
├── tableau/
├── requirements.txt
└── README.md
```
