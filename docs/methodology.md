# Methodology

This document describes how the **v2 five-year TDA pipeline** ingests,
normalizes, and joins Texas Open Data publications about the Summer
Food Service Program (SFSP), Seamless Summer Option (SSO), and School
Nutrition Programs (SNP). It covers data-source choices, normalization
logic, the verified non-congregate scope, and known limitations.

## Scope

- **Time window:** program years 2020 through 2025 (summer programs)
  and school years 2020-21 through 2024-25 (SNP programs).
- **Domain:** `data.texas.gov` (Texas Department of Agriculture
  publications via the Socrata API and Discovery API).
- **Geography:** statewide Texas; no geographic filtering beyond what
  TDA publishes.

## Data source strategy

The registry that governs ingest is
[config/tda_5yr_dataset_registry.json](../config/tda_5yr_dataset_registry.json)
(37 entries, 36 unique dataset IDs — `24ie-9cft` is cross-listed in
both `summer_contacts` and `non_congregate_sources` because it
doubles as the 2022–2023 All-Summer-Sites contact dataset *and* one
of the three MealServiceType-bearing sources).

### Why combined summer meal-count datasets are preferred

For each summer period (2020, 2020-21, 2021-22, 2023, 2024, 2025) TDA
publishes:

- a **combined SFSP+SSO** meal-count dataset (e.g., `fjpc-icjc` for
  2020, `8tne-ysan` for 2020-21, `ihhh-b9xf` for 2023), and
- separate **SSO-only** and **SFSP-only** meal-count datasets.

The v2 pipeline marks only the **combined** datasets as
`use_for_canonical=true` and excludes the single-program copies from
the canonical summer meal master. This avoids double-counting (the
same site-claim shows up in both the combined and the program-specific
datasets) and uses the `program` column on each row to classify the
record as `SSO` or `SFSP`.

### Summer reimbursements: separate SSO and SFSP

TDA does not publish a combined reimbursement table. The pipeline
therefore ingests both the SSO and SFSP reimbursement files per
period (12 datasets across 2020 → 2025) and tags each row's
`program_type` from the registry entry (since these files don't
carry a `program` column).

### Contacts use All Summer Sites where available

The All-Summer-Sites contact datasets carry the broadest coverage
(both SSO and SFSP sites for each period), so they are the canonical
contact source per period. The 2022–2023 SFSP-specific (`8ih4-zp65`)
and SSO-specific (`82b8-iuvu`) contact datasets *additionally* carry
the `MealServiceType` field, so they are pulled into the
`non_congregate_sources` category for the NC enrichment.

### SNP contacts and reimbursements added for school-year context

SNP (NSLP / SBP / SMP / CACFP-adjacent) contact and reimbursement
datasets are ingested per school year (2020-21 → 2024-25). They join
to the summer data on `ce_id` (and `site_id` where present), letting
the dashboard show which CEs participate in school-year programs as
well as summer programs and what their program flags / pricing /
eligibility classifications look like.

## Ingest layer (script 10)

Every dataset is fetched with paginated Socrata calls
(`limit=50000`, looping on `offset` until a short page returns) to
avoid the 50,000-row silent truncation that affected the v1
`m23c-22mm` pull. Each fetch lands in
`data/raw_v2/{category}/{dataset_id}.csv`. Datasets that fail (e.g.,
non-tabular assets that return 403) are logged in
`data/audit/tda_5yr_ingestion_audit.csv` and skipped without
crashing the pipeline.

In the current build, **37 of 37 entries fetched successfully**.

## Normalization layer (script 11)

Five canonical masters are built from the raw v2 pulls:

- `summer_meals_5yr_master.csv` (232,254 rows)
- `summer_reimbursements_5yr_master.csv` (26,069 rows)
- `summer_contacts_5yr_master.csv` (55,396 rows)
- `snp_contacts_5yr_master.csv` (43,375 rows)
- `snp_reimbursements_5yr_master.csv` (321,170 rows)

Schema drift between program years is absorbed via candidate-column
lookups (`find_first_col`):

- **Meal counts:** prefer `breakfasttotal`/`lunchtotal`/`suppertotal`
  when present, fall back to `breakfast`/`lunch`/`supper`. Snacks =
  `amsnacktotal + pmsnacktotal` when split, else `totalsnacks`. Total
  meals = `totalmealssnacks` → `totalmeals_snacks` → sum of parts.
- **Reimbursements:** prefer `totalreimbursement`; fall back to sum
  of per-meal-type reimbursements. Same for `total_meals_reimbursed`.
- **Program type:** read from the `program` column on combined
  datasets (`SEAMLESS_SUMMER_OPTION_MEALS` → SSO,
  `SUMMER_FOOD_SERVICE_PROG_MEALS` → SFSP); otherwise inherited from
  the registry entry.
- **IDs:** `ce_id` and `site_id` are read as strings to preserve
  leading zeros (`"0001"` ≠ `1`).
- **Dates:** stripped to the leading `YYYY-MM-DD` slice for display
  stability.

A per-row `data_quality_flags` column accumulates issues like
`missing_ce_id`, `missing_site_id`, `unknown_program_type`,
`zero_total_meals`, etc.

## Lookup layer (script 12)

The CE/Site lookup builder consumes the five canonical masters and
produces:

- `data/lookup_v2/ce_lookup_master_v2.csv` (1,366 CEs)
- `data/lookup_v2/site_lookup_master_v2.csv` (25,459 sites)
- `data/lookup_v2/ce_site_search_master_v2.csv` (25,459 rows — what
  the dashboard reads)

### Freshness policy

- **Address, contact, operation dates:** for each (ce_id, site_id),
  take the value from the **latest** summer-contact record by
  `canonical_year`. Older years fill in only when the latest year's
  value is missing.
- **SNP flags (CEP, Provision 2, ISP, pricing, grade span, etc.):**
  same recipe applied to SNP contacts.
- **Meal activity (total_reported_meals, years_active,
  latest_program_year, program_types_observed):** aggregated across
  *all* five years of meal-count data.

### Non-congregate enrichment scope

Verified non-congregate status comes from the three 2022–2023
contact datasets that carry `MealServiceType` (`8ih4-zp65`,
`24ie-9cft`, `82b8-iuvu`). For matched `(ce_id, site_id)` rows the
exact value is preserved (`Congregate`, `Non-Congregate - Grab-and-go
at central site`, `Non-Congregate - Mobile route ...`, or
`Non-Congregate - Home delivery`). Rural/Urban comes from
`8ih4-zp65` only.

All 5,276 unique NC source keys now match into the search master
(100% capture). Counts: **5,230 Congregate**, **39 Non-Congregate
grab-and-go**, **5 Non-Congregate mobile route**, **2 Non-Congregate
home delivery** = **46 confirmed non-congregate sites**.

Catalog discovery via the Socrata Discovery API (script 08 in v1)
confirmed that **no `MealServiceType`-bearing dataset exists for any
program year other than 2022–2023** on `data.texas.gov`. Verification
of this scope is therefore exhaustive within the public-data window;
it is not a sampling artifact.

## COVID-era interpretation

USDA pandemic waivers allowed SSO to operate **year-round** in many
Texas districts during the 2020 and 2020-21 program years, and parts
of 2021-22. As a consequence:

- SSO meal counts for 2020, 2020-21, and parts of 2021-22 reflect
  **all-year SSO operations** that effectively substituted for NSLP/
  SBP service during school closures and hybrid schedules, not the
  normal summer-only June–August footprint.
- SSO reimbursements for those same periods are correspondingly
  inflated relative to typical summer SSO.
- Year-over-year SSO comparisons that span the waiver window
  (2019 → 2020, 2020 → 2021, 2021 → 2022) should be qualified
  accordingly; 2023+ returns closer to a normal summer-only scale.
- SFSP activity in the same window is less distorted but still
  affected by congregate flexibility waivers in 2020-21 and 2021-22.

The dashboard's "Latest program year" filter exposes these years
explicitly so users can isolate them.

## Wording conventions

- **"Reported meals"** everywhere — not unique children, not
  participation reach.
- **"Verified non-congregate"** applies only to 2022–2023 sources;
  every other site is marked **Unknown**, and Unknown does *not*
  mean Congregate.
- **"Reimbursement per reported meal"** is `total_reimbursement /
  total_meals_reimbursed` for rows where both are present.
- **"Sites"** = unique `(ce_id, site_id)` keys, not unique site_id
  values (the same site_id can appear under multiple CEs).

## Limitations

- **Reported meals are not unique children.** See the caveat above.
- **Verified NC is 2022–2023 only.** Public data does not fully
  verify NC status across all years; it doesn't exist in the source
  schemas for any other window.
- **Rural/Urban coverage is incomplete.** Only `8ih4-zp65` (SFSP
  2022–2023) carries `ruralorurbancode`. 198 rural + 1,795 urban of
  the 25,459 sites have a label.
- **Contact/address freshness depends on the latest available
  public source.** A site that was last in the All-Summer-Sites
  publication in 2022 carries its 2022 address; if it has since
  moved, the lookup will be stale until TDA publishes a 2024 or
  2025 record for it.
- **Reimbursement data is not full operating cost.** USDA
  reimbursement rates pay a per-meal amount that is intentionally
  less than full meal cost; districts cover the gap from local
  funds. Do not interpret reimbursement totals as program cost.
- **Approved-site/CE Socrata endpoints return 403** for the older
  PDFs (`4z3r-huup`, etc.) and are logged-and-skipped by v1
  ingest. v2 doesn't depend on them.
- **Meal-service-method ≠ non-congregate.** The
  `*_meal_service_method` fields describe meal production /
  sourcing (e.g., Self-Prep on site, Vended by FSMC). They are not
  used to infer congregate vs non-congregate.

## What's out of scope

- Income, demographics, school enrollment, and SNAP/WIC overlap.
- USDA Federal-side claims data (different schema, federal reporting
  cadence, not on `data.texas.gov`).
- Local funding contributions to meal program operating costs.
- Pre-2020 program years (the v1 pipeline covers some of these for
  comparison but they are not the v2 focus).
