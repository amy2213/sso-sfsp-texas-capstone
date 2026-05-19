# Executive Summary

**Live dashboard:** https://app-sfsp-texas.streamlit.app/
**Repository:** https://github.com/amy2213/sso-sfsp-texas-capstone

## Project purpose

This capstone uses publicly available Texas Department of Agriculture
(TDA) datasets to compare the **Seamless Summer Option (SSO)** and the
**Summer Food Service Program (SFSP)** in Texas. It produces:

1. A five-year normalized data pipeline (program years 2020–2025)
   covering summer meal counts, summer reimbursements, summer
   contacts, and school-year SNP contacts + reimbursements.
2. A merged CE/Site lookup with addresses, contact info,
   geolocation, operation dates, meal-service times, SNP program
   flags, and verified non-congregate status where public sources
   permit.
3. A Streamlit dashboard that lets a user search, filter, map, and
   inspect any of the 25,459 sites in the universe with full
   provenance per row.

## Methodology summary

- All ingest is paginated Socrata against `data.texas.gov`. The v2
  registry ([config/tda_5yr_dataset_registry.json](../config/tda_5yr_dataset_registry.json))
  declares 37 entries / 36 unique dataset IDs across six categories.
- The canonical summer meal master uses only *combined* SFSP+SSO
  datasets to avoid double-counting.
- Summer reimbursements use separate SSO + SFSP files per period
  (TDA does not publish a combined reimbursement table).
- Verified non-congregate status is sourced from the three TDA
  contact datasets that carry `MealServiceType` (`8ih4-zp65`,
  `24ie-9cft`, `82b8-iuvu`) — all program year 2022–2023. Other
  years carry no public `MealServiceType` field, so other sites are
  marked `Unknown` (which is *not* the same as Congregate).
- Address, contact, and operation-date fields use the **latest
  available** public record per `(ce_id, site_id)`. Older years
  fill in only when the latest year is missing.

See [methodology.md](methodology.md) for full detail and
[pipeline_notes.md](pipeline_notes.md) for the script-by-script
walkthrough.

## Headline numbers (v2 pipeline)

### Fetch

| | |
|---|---:|
| Datasets in registry | 37 (36 unique IDs) |
| Datasets fetched successfully | **37 / 37** |
| Datasets failed | 0 |

### Canonical 5-year masters

| File | Rows |
|---|---:|
| `summer_meals_5yr_master.csv` | **232,254** |
| `summer_reimbursements_5yr_master.csv` | **26,069** |
| `summer_contacts_5yr_master.csv` | **55,396** |
| `snp_contacts_5yr_master.csv` | **43,375** |
| `snp_reimbursements_5yr_master.csv` | **321,170** |

### CE / Site universe

| | |
|---|---:|
| Distinct CEs | **1,366** |
| Distinct site IDs | **3,148** |
| Unique `(ce_id, site_id)` rows in search master | **25,459** |

### Verified non-congregate scope (SFSP 2022–2023 only)

| Status | Sites in search master |
|---|---:|
| **Verified NC source-matched** | **5,276** |
| Congregate | 5,230 |
| **Confirmed non-congregate** | **46** |
|   …Non-Congregate - Grab-and-go at central site | 39 |
|   …Non-Congregate - Mobile route | 5 |
|   …Non-Congregate - Home delivery | 2 |
| Rural (from `8ih4-zp65` only) | 198 |
| Urban (from `8ih4-zp65` only) | 1,795 |
| **Unknown NC (sites outside 2022–2023 scope)** | **20,183** |

Every `(ce_id, site_id)` key from the public NC source matched into
the search master (100% capture). 20,183 sites remain `Unknown`
because TDA did not publish a `MealServiceType` field for them —
*not* because we could not match. Unknown does not mean Congregate.

## Key findings / dashboard capabilities

- **Search** by CE id/name, site id/name, city, or county returns
  matching sites with full address, contact, operation, and meal-
  service detail in under a second on the deployed app.
- **9 sidebar filters** (CE name, program type, latest program year,
  data-quality flag, non-congregate status, rural/urban, public
  meal service type, program years verified, verified source
  dataset) compose together.
- **10 summary metrics** including verified NC source-matched
  (**5,276**), confirmed non-congregate (**46**), rural (**198**),
  and Unknown NC (**20,183**) so the unverified bucket is visible,
  not hidden.
- **Map view** of ~25,164 sites with parsed lat/lon (98.8% of the
  universe).
- **Selected-site detail panel** organized into five sections (CE,
  Site, Programs and Operations, SNP / Eligibility Context, Activity
  and Data Quality) with provenance fields (`source_dataset_ids`,
  `program_years_verified`, `years_active`) for any matched site.
- **CSV download** of the filtered subset for downstream analysis.
- **Persistent caveat banner** stating the reported-meals scope, the
  2022–2023 NC verification window, and the Unknown-vs-Congregate
  distinction.

## Caveats (read before quoting numbers)

- **Reported meals are not unique children served.** Treat every
  reported-meals figure as program throughput, not participation
  reach.
- **Verified non-congregate is 2022–2023 only.** Other years are
  Unknown by construction; do not treat Unknown as Congregate.
- **2020–2022 SSO scale reflects COVID waivers.** Under USDA's
  pandemic waivers SSO operated year-round in many districts, so
  2020 / 2020-21 / parts of 2021-22 are *all-year* operations rather
  than the normal June–August summer-only window. Compare with care.
- **Rural/Urban is incomplete.** Only `8ih4-zp65` carries the field
  (1,993 of 25,459 sites labeled).
- **Reimbursement ≠ total operating cost.** USDA reimbursement rates
  pay a per-meal amount intentionally below full meal cost; districts
  cover the gap from local funds.

## Next recommended improvements

1. **Pre-aggregate per-CE meal trend tables** so the dashboard can
   show a small 5-year sparkline per selected site without
   recomputing on every load.
2. **Add USDA federal claims data** (FNS data warehouse, not
   `data.texas.gov`) as a cross-check on TDA-published figures.
3. **Address geocoding fallback** for the ~300 sites that don't
   have a parsed lat/lon, so the map covers the full universe.
4. **PR-checked dataset registry**: move the 37-entry registry
   under a JSON Schema and CI-validate that every entry's
   `dataset_id` actually resolves on Socrata.
5. **External NC verification**: file a PIA request with TDA for
   the COVID-era waiver-site list to bridge the years that
   `MealServiceType` doesn't cover. Out of scope for this pipeline
   but the only path to broader NC coverage.
