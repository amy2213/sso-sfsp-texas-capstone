# SSO vs SFSP Texas Capstone

A public-sector data analytics capstone comparing the **Seamless Summer
Option (SSO)** and the **Summer Food Service Program (SFSP)** in Texas,
using public datasets published by the Texas Department of Agriculture
on the Texas Open Data Portal (`data.texas.gov`).

The repository currently contains:

1. A reproducible ingest / cleaning / audit pipeline for the underlying
   meal-count and reimbursement data.
2. A multi-source CE/Site lookup table that merges meal activity with
   contact, address, geolocation, and program-participation data.
3. A verified public-source **non-congregate** enrichment limited to the
   SFSP 2022–2023 contact datasets — the only program year for which
   TDA published a `MealServiceType` field.
4. A **Streamlit CE/Site Lookup Dashboard** that searches the universe,
   filters by NC status / rural-urban / program type / year / source
   dataset, and shows a per-site detail panel with provenance.

## Research question

> How have reported meals served, sponsor participation, and reimbursement
> per reported meal evolved across SSO and SFSP in Texas, and what does
> the available public data tell us about how the two programs serve
> different populations and operate at different scales?

## Two caveats to read first

**Reported meals are not unique children served.** A child receiving
breakfast and lunch on the same day counts as two reported meals. All
charts, tables, SQL queries, and the Streamlit app use the phrase
"reported meals" to make this clear. Do not interpret any output of
this pipeline as a count of children fed.

**Non-congregate status is verified for one program year only.** TDA
only published the `MealServiceType` field for **program year 2022–2023**
(the COVID-era non-congregate flexibility window). Earlier and later
contact datasets do not carry the field at all. Every site outside that
window stays marked **Unknown**, and `Unknown` explicitly does *not*
mean the site was congregate — it means no public-source field exists
for that site/year.

## Tools

- **Python 3** (pandas, sodapy, requests) for ingest, cleaning,
  audit, lookup building, and NC enrichment.
- **Streamlit** for the interactive CE/Site Lookup Dashboard
  ([app.py](app.py)).
- **SQL** (portable ANSI dialect — runs in DuckDB, SQLite, or Postgres)
  for the headline analysis queries on the clean masters.
- **Tableau** for additional dashboards consuming the clean master CSVs
  (placeholder folder).
- **Texas Open Data Portal** (Socrata API + Discovery API) as the data
  source.

## Pipeline

The pipeline is organized as eight numbered scripts that run independently
and write to disk. Each script can be re-run in isolation, and each
documents its inputs/outputs in a docstring.

| # | Script | Purpose |
|---|---|---|
| 01 | [scripts/01_ingest_clean_audit.py](scripts/01_ingest_clean_audit.py) | Pulls meal-count + reimbursement datasets, writes `data/clean/summer_meals_master.csv`, `reimbursements_master.csv`, `approved_sites_master.csv`, and audit outputs. |
| 02 | [scripts/02_discover_contact_participation_datasets.py](scripts/02_discover_contact_participation_datasets.py) | Discovery for summer + SNP contact / program-participation datasets. Produces field inventory + schema profile. |
| 03 | [scripts/03_build_ce_site_lookup_tables.py](scripts/03_build_ce_site_lookup_tables.py) | Builds `data/lookup/{ce_lookup_master, site_lookup_master, site_program_flags, ce_site_search_master}.csv` — one row per (CE, site) in the broadest universe. |
| 04 | [scripts/04_discover_non_congregate_fields.py](scripts/04_discover_non_congregate_fields.py) | First-pass NC discovery (single-source: `8ih4-zp65`). |
| 05 | [scripts/05_enrich_lookup_with_non_congregate.py](scripts/05_enrich_lookup_with_non_congregate.py) | First-pass NC enrichment. Produced 11 verified NC sites — later superseded by script 07. |
| 06 | [scripts/06_discover_all_meal_service_type_sources.py](scripts/06_discover_all_meal_service_type_sources.py) | Combines three MST sources (`8ih4-zp65`, `24ie-9cft`, `82b8-iuvu`) into `data/lookup/non_congregate_public_source_master.csv`. |
| 07 | [scripts/07_enrich_lookup_with_all_public_non_congregate.py](scripts/07_enrich_lookup_with_all_public_non_congregate.py) | Final NC enrichment using all 3 sources. Produces `data/lookup/ce_site_search_master_enriched_all_nc.csv` (used by the app). |
| 08 | [scripts/08_catalog_discover_meal_service_type_years.py](scripts/08_catalog_discover_meal_service_type_years.py) | Catalog search across the full TX Open Data domain (452 candidates) to confirm no MST-bearing datasets exist for other years. |

### Pipeline flow

```
01 → data/clean/{summer_meals_master, reimbursements_master}.csv
02 → data/raw/contact_participation/*.csv (+ field inventory)
03 → data/lookup/ce_site_search_master.csv         (15,855 rows)
04 → first NC probe (8ih4-zp65 only)
05 → data/lookup/ce_site_search_master_enriched.csv (11 verified NC)
06 → data/lookup/non_congregate_public_source_master.csv (3 sources)
07 → data/lookup/ce_site_search_master_enriched_all_nc.csv (34 verified NC)
08 → confirms no later-year MST sources exist on data.texas.gov
                            │
                            ▼
                        app.py (Streamlit)
```

## How to run

```powershell
# from the repo root
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# (re)build everything end-to-end
python scripts\01_ingest_clean_audit.py
python scripts\02_discover_contact_participation_datasets.py
python scripts\03_build_ce_site_lookup_tables.py
python scripts\07_enrich_lookup_with_all_public_non_congregate.py

# launch the dashboard
streamlit run app.py
```

Scripts 04, 05, 06, and 08 are diagnostic / discovery scripts. Re-running
them is optional; they are kept in the repo so the provenance of script
07's enrichment scope is reproducible.

## Streamlit CE/Site Lookup Dashboard

The dashboard ([app.py](app.py)) reads
`data/lookup/ce_site_search_master_enriched_all_nc.csv` and provides:

- **Search box** that AND-matches whitespace-separated tokens against a
  pre-computed `search_key` (CE id/name, site id/name, city, county).
- **Sidebar filters**: CE name, program type, latest program year,
  data-quality flag, non-congregate status, rural/urban, public meal
  service type, program years verified, verified source dataset, +
  two boolean filters (only with reported meals / only with lat-lon).
- **10 summary metrics** in three rows, including verified-NC
  source-matched (**4,896**), confirmed non-congregate (**34**),
  rural (**170**), and Unknown NC (**10,959**) — so the size of the
  unverified bucket is visible, not hidden.
- **Results table** with the headline columns.
- **`st.map`** of sites that have parsed lat/lon (~12,300 of 15,855).
- **Selected-site detail panel** organized into five sections (CE,
  Site, Programs and Operations, SNP / Eligibility Context, Activity
  and Data Quality) with provenance fields (`source_dataset_ids`,
  `program_years_verified`) for any matched site.
- **CSV download** of the filtered subset.
- A persistent **caveat banner** stating the "reported meals" wording
  and the 2022–2023 NC verification scope, including the explicit
  reminder that *Unknown does not mean the site was congregate*.

## Current status

- Ingest, cleaning, and audit pipeline running end-to-end.
- Six tabular meal-count / reimbursement datasets fetch successfully;
  five "approved sites" / "approved CEs" datasets return `403 Forbidden`
  through the Socrata API and are logged-and-skipped without breaking
  the pipeline.
- The 2021–2022 meal-count dataset (`m23c-22mm`) is paginated so its
  ~70k rows are fully fetched (previously truncated at 50,000).
- CE/Site lookup tables built from meal activity + summer-contact
  (7ae2-5muh, 12,092 rows) + SNP-contact (5ejx-uftk, 8,683 rows). Final
  search master: 15,855 unique (ce_id, site_id) keys.
- Public-source NC enrichment from three MST-bearing datasets
  (`8ih4-zp65`, `24ie-9cft`, `82b8-iuvu`): 4,896 verified rows
  (30.9% of the search master), 34 confirmed non-congregate sites
  (9 grab-and-go, 3 mobile route, 2 home delivery — plus 20 from
  prior-version columns), 170 rural / 1,795 urban (rural/urban
  available from `8ih4-zp65` only).
- Catalog discovery (script 08) confirmed no further MST-bearing
  datasets exist on `data.texas.gov` for other program years.
- Streamlit dashboard wired to the all-source enriched lookup and
  surfaces the verified subset accurately.

## Known data limitations

- **Reported meals ≠ children served.** See the caveat above.
- **Verified NC is 2022–2023 only.** Every other program year is
  Unknown by construction — the field doesn't exist in the source
  schemas. `Unknown` is therefore not informative about whether a
  site was congregate.
- **Approved-site/CE datasets return 403** through the public Socrata
  API. We log the failure and continue. `data/clean/approved_sites_master.csv`
  may therefore be empty.
- **2021–2022 pagination risk.** The Socrata hard cap per request is
  50,000. Without pagination the 2021–2022 meal-count dataset silently
  truncates at exactly that. The current pipeline pages with
  `limit=50000` and loops on `offset` until a short page is returned.
- **Schema drift between years.** Different program years use different
  column names (`breakfasttotal` vs `breakfast`, `totalmealssnacks` vs
  `totalmeals_snacks`, `program` only present in combined datasets,
  no `mealservicetype` outside 2022–2023). The standardization layer
  prefers the more specific columns and falls back to the bare names.
- **Program-type inference.** Single-program datasets (e.g.,
  `SSO Meal Counts 2019`) are tagged from the registry. Combined
  datasets (`pxzu-afsv`, `4axx-sfpm`) read the `program` column and
  classify each row as `SSO`, `SFSP`, or `UNKNOWN`.
- **Rural/Urban coverage is incomplete.** Only `8ih4-zp65` carries
  `ruralorurbancode`, so 1,965 of 15,855 sites have a rural/urban
  label and the rest are NA.
- **Meal-service-method ≠ non-congregate.** The `*_meal_service_method`
  fields describe meal production / sourcing (e.g., "Self-Prep on site",
  "Vended by FSMC") and are surfaced separately. They are not used to
  infer congregate vs non-congregate.

## Repository layout

```
.
├── app.py                          # Streamlit CE/Site Lookup Dashboard
├── requirements.txt
├── README.md
├── data/
│   ├── raw/                        # one CSV per fetched dataset, by source
│   │   ├── contact_participation/        (script 02)
│   │   ├── non_congregate/               (script 04)
│   │   ├── non_congregate_all_sources/   (script 06)
│   │   └── meal_service_type_year_discovery/  (script 08)
│   ├── clean/                      # script 01 outputs
│   │   ├── summer_meals_master.csv
│   │   ├── reimbursements_master.csv
│   │   └── approved_sites_master.csv
│   ├── lookup/                     # script 03/05/06/07 outputs
│   │   ├── ce_lookup_master.csv
│   │   ├── site_lookup_master.csv
│   │   ├── site_program_flags.csv
│   │   ├── ce_site_search_master.csv             # base
│   │   ├── ce_site_search_master_enriched.csv    # NC v1 (8ih4-zp65)
│   │   ├── ce_site_search_master_enriched_all_nc.csv  # NC v2 (app reads this)
│   │   └── non_congregate_public_source_master.csv     # combined NC source
│   └── audit/                      # schema profiles, value samples, join audits
├── docs/
│   ├── methodology.md
│   ├── limitations.md
│   ├── data_dictionary.md
│   └── executive_summary.md
├── scripts/
│   ├── 01_ingest_clean_audit.py
│   ├── 02_discover_contact_participation_datasets.py
│   ├── 03_build_ce_site_lookup_tables.py
│   ├── 04_discover_non_congregate_fields.py
│   ├── 05_enrich_lookup_with_non_congregate.py
│   ├── 06_discover_all_meal_service_type_sources.py
│   ├── 07_enrich_lookup_with_all_public_non_congregate.py
│   └── 08_catalog_discover_meal_service_type_years.py
├── sql/
│   ├── create_tables.sql
│   └── analysis_queries.sql
└── tableau/
```
