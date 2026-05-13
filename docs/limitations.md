# Limitations

## 1. Reported meals are not unique children served

The single most important caveat in this project.

The TDA datasets count **reported meals served**. A child receiving
breakfast and lunch on the same day counts as two reported meals; a
child attending the same site every day for a month contributes many
reported meals. Reported-meal totals therefore measure *program
throughput*, not *participation reach*.

Any chart, summary, or sentence that uses the word "meals" in this
project refers to reported meals. Do not report any number from this
pipeline as the number of children fed.

## 2. Approved-site / approved-CE datasets currently return 403

These five datasets fail the Socrata API call with `403 Forbidden`:

- `4z3r-huup` Approved SFSP and SSO Sites 2023
- `j2sd-a7ir` Approved SFSP and SSO Sites 2024
- `t3jr-vyxe` Approved SFSP and SSO Sites 2025
- `4tpe-vtdp` Approved CEs 2025
- `4zvx-6dyc` Approved CEs 2026

They are likely registered on the portal as non-tabular assets (PDFs,
viewer-only). The pipeline logs the failure and skips them so the rest
of the project still runs. As a consequence,
`data/clean/approved_sites_master.csv` may be empty, and we cannot
compute "share of *approved* sites that actually reported meals" until
this resolves. The capstone does not currently depend on these
datasets.

## 3. Socrata silent truncation in 2021–2022

Without pagination, `m23c-22mm` returned exactly 50,000 rows — the
Socrata default hard cap. This is invisible to a naive caller: the
response looks complete. The current ingest paginates with
`limit=50000` and loops on `offset` until a page returns fewer rows
than the limit, which removes the truncation.

## 4. Schema drift between program years

Different TDA datasets use different column names:

- `breakfasttotal` vs `breakfast`
- `totalmealssnacks` vs `totalmeals_snacks`
- `program` column present only in combined-program datasets
- Snack split (`amsnack*` + `pmsnack*`) vs combined `totalsnacks`

The standardization layer prefers the more specific column and falls
back to the bare name. This makes year-over-year totals comparable
but introduces a *definitional* risk: a "lunch_meals" number for 2018
may be derived from a slightly differently defined raw column than
the same number for 2024. Treat single-percent-level differences with
caution.

## 5. Program-type inference for combined datasets

For `pxzu-afsv` (2018) and `4axx-sfpm` (2024), program type is
inferred from the `program` column on each row. Rows whose `program`
value is missing or unrecognized are tagged `UNKNOWN` and flagged in
`data_quality_flags`. The SQL summaries surface this so it can be
inspected before any analysis depends on it.

## 6. No deduplication across sources

The two master tables concatenate per-source records without
deduplication. The `record_match_key` column makes duplicate detection
easy (and the audit reports `duplicate_match_keys`), but the
de-duplication itself is a downstream decision left to the analyst.

## 7. Date coverage is uneven

We have meal counts for 2018, 2019, 2022, and 2024, and reimbursement
data for 2019 and 2022 only. Year-over-year comparisons are therefore
*ragged*: 2020 and 2021 are absent (likely COVID-era reporting
changes), and reimbursement data does not cover the same span as
meal-count data.

## 8. The Socrata API is not authoritative

`data.texas.gov` is a public mirror, not the system of record. Any
*final* claim should ideally be cross-checked against TDA's published
reports.
