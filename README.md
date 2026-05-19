# SSO vs SFSP Texas Capstone

A public-sector data analytics capstone comparing the **Seamless Summer
Option (SSO)** and the **Summer Food Service Program (SFSP)** in Texas,
using public datasets published by the Texas Department of Agriculture
on the Texas Open Data Portal (`data.texas.gov`).

**Deployed dashboard:** https://app-sfsp-texas.streamlit.app/

The repository currently contains:

1. A **5-year TDA Open Data pipeline (v2)** covering program years
   2020–2025: summer meal counts, summer reimbursements (SSO + SFSP),
   summer contacts, SNP contacts, and SNP reimbursements.
2. A multi-source **CE/Site lookup table** that merges meal activity
   with contact, address, geolocation, and program-participation data.
3. A verified public-source **non-congregate** enrichment limited to
   the SFSP 2022–2023 contact datasets — the only program year for
   which TDA published a `MealServiceType` field.
4. A **Streamlit CE/Site Lookup Dashboard** that searches the universe,
   filters by NC status / rural-urban / program type / year / source
   dataset, and shows a per-site detail panel with provenance.
5. The original **v1 pipeline (scripts 01–08)** retained for
   reproducibility and as the provenance trail for how the NC scope
   was established.

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

The pipeline is organized as twelve numbered scripts. Scripts 01–08
are the original v1 pipeline kept for provenance; scripts 09–12 are
the active v2 pipeline that the deployed Streamlit app uses.

### v2 pipeline (active — feeds the dashboard)

| # | Script | Purpose |
|---|---|---|
| 09 | [scripts/09_build_5yr_dataset_registry.py](scripts/09_build_5yr_dataset_registry.py) | Writes `config/tda_5yr_dataset_registry.json` — 37 entries covering 6 canonical meal-count datasets (one combined dataset per period to avoid double-counting), 12 reimbursement datasets (SSO + SFSP per period), 6 summer-contact datasets, 5 SNP-contact datasets, 5 SNP-reimbursement datasets, and 3 NC sources. |
| 10 | [scripts/10_ingest_5yr_tda_datasets.py](scripts/10_ingest_5yr_tda_datasets.py) | Paginated Socrata fetch for every dataset in the registry. Saves raw CSVs to `data/raw_v2/{category}/{dataset_id}.csv` and writes `tda_5yr_ingestion_audit.csv` + `tda_5yr_schema_profile.csv`. |
| 11 | [scripts/11_build_5yr_canonical_tables.py](scripts/11_build_5yr_canonical_tables.py) | Normalizes the raw files into five canonical masters in `data/clean_v2/` (summer meals, summer reimbursements, summer contacts, SNP contacts, SNP reimbursements). Absorbs schema drift across years via candidate-column lookups. |
| 12 | [scripts/12_build_ce_site_lookup_v2.py](scripts/12_build_ce_site_lookup_v2.py) | Builds the v2 lookup tables (`ce_lookup_master_v2.csv`, `site_lookup_master_v2.csv`, `ce_site_search_master_v2.csv`) plus the join audit and a markdown validation report. This is what `app.py` reads. |

### v1 pipeline (legacy — retained for provenance)

| # | Script | Purpose |
|---|---|---|
| 01 | [scripts/01_ingest_clean_audit.py](scripts/01_ingest_clean_audit.py) | Original ingest: writes `data/clean/{summer_meals_master,reimbursements_master}.csv`. Superseded by 10/11 for the live pipeline, but still re-runnable. |
| 02 | [scripts/02_discover_contact_participation_datasets.py](scripts/02_discover_contact_participation_datasets.py) | Discovery script that established the SNP and summer-contact dataset shape. |
| 03 | [scripts/03_build_ce_site_lookup_tables.py](scripts/03_build_ce_site_lookup_tables.py) | Original CE/site lookup builder. Produced `data/lookup/ce_site_search_master.csv` (15,855 rows); now superseded by script 12 (25,459 rows). |
| 04 | [scripts/04_discover_non_congregate_fields.py](scripts/04_discover_non_congregate_fields.py) | First NC field probe (single source: `8ih4-zp65`). |
| 05 | [scripts/05_enrich_lookup_with_non_congregate.py](scripts/05_enrich_lookup_with_non_congregate.py) | First NC enrichment pass. 11 verified NC sites — later superseded by 07 and then by 12. |
| 06 | [scripts/06_discover_all_meal_service_type_sources.py](scripts/06_discover_all_meal_service_type_sources.py) | Established that three datasets (`8ih4-zp65`, `24ie-9cft`, `82b8-iuvu`) carry MealServiceType. |
| 07 | [scripts/07_enrich_lookup_with_all_public_non_congregate.py](scripts/07_enrich_lookup_with_all_public_non_congregate.py) | All-source NC enrichment over the v1 lookup. 34 verified NC sites — superseded by 12. |
| 08 | [scripts/08_catalog_discover_meal_service_type_years.py](scripts/08_catalog_discover_meal_service_type_years.py) | Catalog search across all of `data.texas.gov` (452 candidates) that confirmed no MST-bearing datasets exist for any year other than 2022–2023. This is the *evidence* behind the "Unknown does not mean congregate" caveat. |

### v2 pipeline flow

```
09  config/tda_5yr_dataset_registry.json
       │
       ▼
10  data/raw_v2/{category}/{dataset_id}.csv  (37 files, 688K rows total)
       │
       ▼
11  data/clean_v2/summer_meals_5yr_master.csv         (232,254 rows)
    data/clean_v2/summer_reimbursements_5yr_master.csv ( 26,069 rows)
    data/clean_v2/summer_contacts_5yr_master.csv       ( 55,396 rows)
    data/clean_v2/snp_contacts_5yr_master.csv          ( 43,375 rows)
    data/clean_v2/snp_reimbursements_5yr_master.csv    (321,170 rows)
       │
       ▼
12  data/lookup_v2/ce_lookup_master_v2.csv          (  1,366 CEs)
    data/lookup_v2/site_lookup_master_v2.csv        ( 25,459 sites)
    data/lookup_v2/ce_site_search_master_v2.csv     ( 25,459 rows)
       │
       ▼
   app.py (Streamlit)  →  https://app-sfsp-texas.streamlit.app/
```

## How to run

```powershell
# from the repo root
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# (re)build the v2 pipeline end-to-end — this is what the dashboard reads
python scripts\09_build_5yr_dataset_registry.py
python scripts\10_ingest_5yr_tda_datasets.py
python scripts\11_build_5yr_canonical_tables.py
python scripts\12_build_ce_site_lookup_v2.py

# launch the dashboard
streamlit run app.py
```

The v1 scripts (01–08) are still runnable for historical comparison
or to regenerate the v1 lookup chain, but the dashboard does not
depend on them.

## Streamlit CE/Site Lookup Dashboard

The dashboard ([app.py](app.py)) reads
`data/lookup_v2/ce_site_search_master_v2.csv` and provides:

- **Search box** that AND-matches whitespace-separated tokens against a
  pre-computed `search_key` (CE id/name, site id/name, city, county).
- **Sidebar filters**: CE name, program type, latest program year,
  data-quality flag, non-congregate status, rural/urban, public meal
  service type, program years verified, verified source dataset, +
  two boolean filters (only with reported meals / only with lat-lon).
- **10 summary metrics** in three rows, including verified-NC
  source-matched (**5,276**), confirmed non-congregate (**46**),
  rural (**198**), and Unknown NC (**20,183**) — so the size of the
  unverified bucket is visible, not hidden.
- **Results table** with the headline columns.
- **`st.map`** of sites that have parsed lat/lon (~25,164 of 25,459).
- **Selected-site detail panel** organized into five sections (CE,
  Site, Programs and Operations, SNP / Eligibility Context, Activity
  and Data Quality) including `Years Active` and provenance fields
  (`source_dataset_ids`, `program_years_verified`).
- **CSV download** of the filtered subset.
- A persistent **caveat banner** stating the "reported meals" wording
  and the 2022–2023 NC verification scope, including the explicit
  reminder that *Unknown does not mean the site was congregate*.

## Current status

- v2 pipeline running end-to-end. **37/37 datasets fetched
  successfully**, zero failures.
- Five canonical masters cover program years **2020–2025** continuously
  (no year gaps inside that window).
- v2 CE/site lookup: **1,366 CEs**, **3,148 distinct site IDs**,
  **25,459 unique (ce_id, site_id) rows** in the search master.
- Public-source NC enrichment from the three 2022–2023 MST-bearing
  datasets (`8ih4-zp65`, `24ie-9cft`, `82b8-iuvu`): **all 5,276 NC
  source keys now match into the search master** (100% capture), with
  **46 confirmed non-congregate sites** (39 grab-and-go + 5 mobile
  route + 2 home delivery). Rural/Urban from `8ih4-zp65`: 198 rural,
  1,795 urban (the only source for that field).
- Catalog discovery (script 08) confirmed no further MST-bearing
  datasets exist on `data.texas.gov` for other program years.
- Streamlit dashboard wired to `ce_site_search_master_v2.csv` and
  deployed at https://app-sfsp-texas.streamlit.app/ via Streamlit
  Community Cloud (auto-redeploys on `git push origin main`).
- v1 lookup chain is preserved in `data/clean/` and `data/lookup/`
  for historical comparison.

## Known data limitations

- **Reported meals ≠ children served.** See the caveat above.
- **Verified NC is 2022–2023 only.** Every other program year is
  Unknown by construction — the field doesn't exist in the source
  schemas. `Unknown` is therefore not informative about whether a
  site was congregate.
- **Approved-site/CE datasets return 403** through the public Socrata
  API. Logged and skipped in v1; `data/clean/approved_sites_master.csv`
  may therefore be empty.
- **Pagination is required.** The Socrata hard cap per request is
  50,000. Both v1 and v2 page with `limit=50000` and loop on `offset`
  until a short page returns, removing the silent-truncation risk.
- **Schema drift between years.** Different program years use different
  column names (`breakfasttotal` vs `breakfast`, `totalmealssnacks` vs
  `totalmeals_snacks`, `program` only present in combined datasets,
  no `mealservicetype` outside 2022–2023). The standardization layer
  prefers the more specific columns and falls back to the bare names.
- **Combined meal-count datasets are canonical.** v2 deliberately
  uses only one *combined* meal-count dataset per period (SFSP+SSO
  together) to avoid double-counting from separate SSO-only / SFSP-only
  pulls. SSO-only and SFSP-only meal-count datasets exist on the
  portal but are excluded from the canonical meal master.
- **Program-type inference.** Single-program datasets are tagged from
  the registry. Combined datasets read the `program` column and
  classify each row as `SSO`, `SFSP`, or `UNKNOWN`.
- **Rural/Urban coverage is incomplete.** Only `8ih4-zp65` carries
  `ruralorurbancode`, so **198 rural + 1,795 urban** of the 25,459
  sites have a label and the rest are NA.
- **Meal-service-method ≠ non-congregate.** The `*_meal_service_method`
  fields describe meal production / sourcing (e.g., "Self-Prep on site",
  "Vended by FSMC") and are surfaced separately. They are not used to
  infer congregate vs non-congregate.

## Repository layout

```
.
├── app.py                              # Streamlit CE/Site Lookup Dashboard
├── requirements.txt
├── README.md
├── .gitignore
├── config/
│   └── tda_5yr_dataset_registry.json   # v2 dataset registry (script 09)
├── data/
│   ├── raw/                            # v1 raw pulls (one CSV per dataset)
│   │   ├── contact_participation/             (script 02)
│   │   ├── non_congregate/                    (script 04)
│   │   ├── non_congregate_all_sources/        (script 06)
│   │   └── meal_service_type_year_discovery/  (script 08)
│   ├── raw_v2/                         # v2 raw pulls (script 10; gitignored after initial commit)
│   │   ├── summer_meal_counts/                (6 files)
│   │   ├── summer_reimbursements/             (12 files — SSO + SFSP)
│   │   ├── summer_contacts/                   (6 files)
│   │   ├── snp_contacts/                      (5 files)
│   │   ├── snp_reimbursements/                (5 files)
│   │   └── non_congregate_sources/            (3 files; 24ie-9cft cross-listed)
│   ├── clean/                          # v1 canonical (script 01)
│   │   ├── summer_meals_master.csv
│   │   ├── reimbursements_master.csv
│   │   └── approved_sites_master.csv
│   ├── clean_v2/                       # v2 canonical (script 11)
│   │   ├── summer_meals_5yr_master.csv          (232,254 rows)
│   │   ├── summer_reimbursements_5yr_master.csv ( 26,069 rows)
│   │   ├── summer_contacts_5yr_master.csv       ( 55,396 rows)
│   │   ├── snp_contacts_5yr_master.csv          ( 43,375 rows)
│   │   └── snp_reimbursements_5yr_master.csv    (321,170 rows)
│   ├── lookup/                         # v1 lookups (scripts 03/05/06/07)
│   │   ├── ce_lookup_master.csv
│   │   ├── site_lookup_master.csv
│   │   ├── site_program_flags.csv
│   │   ├── ce_site_search_master.csv
│   │   ├── ce_site_search_master_enriched.csv
│   │   ├── ce_site_search_master_enriched_all_nc.csv
│   │   └── non_congregate_public_source_master.csv
│   ├── lookup_v2/                      # v2 lookups (script 12)
│   │   ├── ce_lookup_master_v2.csv              (  1,366 CEs)
│   │   ├── site_lookup_master_v2.csv            ( 25,459 sites)
│   │   └── ce_site_search_master_v2.csv         ( 25,459 rows — app reads this)
│   └── audit/                          # schema profiles, value samples, join audits, validation report
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
│   ├── 08_catalog_discover_meal_service_type_years.py
│   ├── 09_build_5yr_dataset_registry.py
│   ├── 10_ingest_5yr_tda_datasets.py
│   ├── 11_build_5yr_canonical_tables.py
│   └── 12_build_ce_site_lookup_v2.py
├── sql/
│   ├── create_tables.sql
│   └── analysis_queries.sql
└── tableau/
```
