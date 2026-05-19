# Pipeline Notes

Practical notes on which scripts are current, which are legacy, where
the outputs go, and how to regenerate them. For the *how it works*
explanation, see [methodology.md](methodology.md).

## v1 vs v2 at a glance

The repository contains two pipelines of which **only v2 feeds the
deployed Streamlit dashboard**. v1 is retained for audit / provenance
of how the non-congregate scope was established and how the lookup
structure evolved.

| | v1 (legacy) | v2 (current) |
|---|---|---|
| Scripts | `01` → `08` | `09` → `12` (+ `run_v2_pipeline.py`) |
| Time window | mixed years per script | continuous program years 2020–2025 |
| Canonical meal master | `data/clean/summer_meals_master.csv` | `data/clean_v2/summer_meals_5yr_master.csv` |
| App lookup | `data/lookup/ce_site_search_master_enriched_all_nc.csv` | `data/lookup_v2/ce_site_search_master_v2.csv` |
| NC verified count | 34 | **46** |
| NC source matched | 4,896 | **5,276** (100% capture of NC source) |
| Search-master rows | 15,855 | **25,459** |
| Distinct CEs | 1,378 | 1,366 |
| Reads `app.py`? | no | **yes** |

## Scripts 01–08 (legacy / development / audit)

These scripts are kept because they document *how the project got
here*. The deployed dashboard does not depend on them.

| # | Purpose | Status |
|---|---|---|
| 01 | First ingest of meal-count + reimbursement datasets | Superseded by 10/11 |
| 02 | Discovery of summer + SNP contact datasets | Established field shapes |
| 03 | First CE/Site lookup builder | Superseded by 12 |
| 04 | First NC field probe (`8ih4-zp65` only) | Provenance — yields 11 verified NC |
| 05 | First NC enrichment | Superseded by 07 → then by 12 |
| 06 | Confirmed three MST sources (`8ih4-zp65`, `24ie-9cft`, `82b8-iuvu`) | Foundational discovery |
| 07 | All-source NC enrichment over the v1 lookup | Superseded by 12 |
| 08 | Catalog search of all of `data.texas.gov` | **Evidence** for "no MST outside 2022–2023" — still valuable |

Script 08 in particular is *not* dead code: it is the audit trail
that proves the NC scope claim. Re-run it if you ever want to
re-validate that no new MST-bearing dataset has been published on
the portal.

## Scripts 09–12 (current primary pipeline)

| # | Purpose | Key output |
|---|---|---|
| 09 | Writes the 37-entry / 36-unique-ID v2 dataset registry | `config/tda_5yr_dataset_registry.json` |
| 10 | Paginated Socrata fetch for every registry entry | `data/raw_v2/{category}/{dataset_id}.csv` + ingestion audit + schema profile |
| 11 | Normalizes raw v2 pulls into five canonical masters | `data/clean_v2/*.csv` |
| 12 | Builds the v2 CE/Site lookup + validation report | `data/lookup_v2/*.csv` + `data/audit/tda_5yr_pipeline_validation_report.md` |

## `scripts/run_v2_pipeline.py` is the recommended entry point

Use the wrapper rather than calling 09 / 10 / 11 / 12 individually:

```powershell
python scripts\run_v2_pipeline.py
```

It runs the four steps in order with `subprocess.run(..., check=True)`,
prints a clear section header before each step, and stops on the
first failure. At the end it prints a manifest of the key output
paths the dashboard depends on, with present/missing status.

## v2 output folders

```
config/
  tda_5yr_dataset_registry.json     # script 09

data/
  raw_v2/                            # script 10 (gitignored after initial commit)
    summer_meal_counts/              (6 files)
    summer_reimbursements/           (12 files, SSO + SFSP)
    summer_contacts/                 (6 files)
    snp_contacts/                    (5 files)
    snp_reimbursements/              (5 files)
    non_congregate_sources/          (3 files; 24ie-9cft cross-listed from summer_contacts)

  clean_v2/                          # script 11
    summer_meals_5yr_master.csv      (232,254 rows)
    summer_reimbursements_5yr_master.csv ( 26,069 rows)
    summer_contacts_5yr_master.csv   ( 55,396 rows)
    snp_contacts_5yr_master.csv      ( 43,375 rows)
    snp_reimbursements_5yr_master.csv (321,170 rows)

  lookup_v2/                         # script 12
    ce_lookup_master_v2.csv          (  1,366 CEs)
    site_lookup_master_v2.csv        ( 25,459 sites)
    ce_site_search_master_v2.csv     ( 25,459 rows -- app reads this)

  audit/                             # ingestion, schema, join, validation outputs
    tda_5yr_ingestion_audit.csv
    tda_5yr_schema_profile.csv
    tda_5yr_canonical_build_audit.csv
    tda_5yr_lookup_v2_join_audit.csv
    tda_5yr_pipeline_validation_report.md
```

## Regenerating outputs

All v2 outputs are fully regenerable from the registry — the raw,
clean, and lookup CSVs are committed only for demo convenience.

| To regenerate | Run |
|---|---|
| Just the lookup (cheapest, uses existing clean_v2) | `python scripts/12_build_ce_site_lookup_v2.py` |
| Lookup + canonical masters (if raw_v2 is intact) | `python scripts/11_build_5yr_canonical_tables.py && python scripts/12_build_ce_site_lookup_v2.py` |
| Everything end-to-end (including re-fetch from Socrata) | `python scripts/run_v2_pipeline.py` |

A full end-to-end run takes 8–15 minutes depending on Socrata
throttling (no app token in use). The fetch step (10) is the slowest.

## Data size / committed-CSV note

`data/clean_v2/` and `data/lookup_v2/` are committed (totaling roughly
~95 MB across 8 files) so that anyone who clones the repo can run
`streamlit run app.py` immediately without first re-fetching from
Socrata. `data/raw_v2/` was committed once (~234 MB across 37 files)
and is now gitignored so that re-running script 10 does not produce
noisy diffs every time the pipeline is exercised.

The Streamlit Cloud deployment relies on the committed
`ce_site_search_master_v2.csv` being present in the repo at deploy
time; it does *not* run the pipeline itself.

## When to re-run vs trust committed outputs

- **Re-fetching changes nothing immediately useful for 2020–2024**:
  TDA's archived datasets for completed program years don't change.
- **For the current program year (2025)** TDA may add records as
  the season progresses. If you want fresh data, re-run the full
  pipeline with `python scripts/run_v2_pipeline.py`.
- **If you suspect a new MST-bearing dataset has been published**,
  re-run `python scripts/08_catalog_discover_meal_service_type_years.py`
  and inspect the `catalog_meal_service_type_year_coverage.csv`
  output. As of the last run, only the three known 2022–2023
  sources existed.
