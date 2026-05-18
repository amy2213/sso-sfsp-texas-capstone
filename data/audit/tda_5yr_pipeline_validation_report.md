# TDA 5-Year Pipeline Validation Report
_Generated 2026-05-18T18:45:28_
## Wording
This pipeline reports **reported meals served**, not unique children served. Verified non-congregate status is available only where public TX Open Data includes meal service type, currently limited to the 2022–2023 contact datasets. **Unknown does not mean congregate.**

## Row counts by category
| Table | Rows | Distinct CEs | Distinct sites |
|---|---:|---:|---:|
| summer_meals_5yr_master | 232,254 | 1,269 | 2,985 |
| summer_reimbursements_5yr_master | 26,069 | 1,269 | — |
| summer_contacts_5yr_master | 55,396 | 1,287 | 3,119 |
| snp_contacts_5yr_master | 43,375 | 1,244 | 486 |
| snp_reimbursements_5yr_master | 321,170 | 1,241 | 476 |
| ce_lookup_master_v2 | 1,366 | 1,366 | — |
| site_lookup_master_v2 | 25,459 | 1,366 | 3,148 |
| ce_site_search_master_v2 | 25,459 | 1,366 | 3,148 |

## Dataset fetch summary
See `data/audit/tda_5yr_ingestion_audit.csv` for the per-dataset row.

## Summer meal reported meals by canonical_year and program_type
| Year | Program | Reported meals |
|---|---|---:|
| 2020 | SFSP | 50,503,746 |
| 2020 | SSO | 111,217,837 |
| 2021 | SFSP | 130,555,935 |
| 2021 | SSO | 469,332,466 |
| 2022 | SFSP | 6,395,823 |
| 2022 | SSO | 683,620,557 |
| 2023 | SFSP | 5,137,210 |
| 2023 | SSO | 8,146,054 |
| 2024 | SFSP | 4,165,054 |
| 2024 | SSO | 7,882,500 |
| 2025 | SFSP | 4,183,115 |
| 2025 | SSO | 7,666,394 |

## Summer reimbursements by canonical_year and program_type
| Year | Program | Total reimbursement |
|---|---|---:|
| 2020 | SFSP | $164,863,514 |
| 2020 | SSO | $319,842,375 |
| 2021 | SFSP | $459,908,716 |
| 2021 | SSO | $1,524,557,701 |
| 2022 | SFSP | $22,837,254 |
| 2022 | SSO | $2,361,252,132 |
| 2023 | SFSP | $19,857,653 |
| 2023 | SSO | $30,345,776 |
| 2024 | SFSP | $17,006,729 |
| 2024 | SSO | $29,203,632 |
| 2025 | SFSP | $17,392,472 |
| 2025 | SSO | $29,710,295 |

## Summer contact records by canonical_year
| Year | Value |
|---|---:|
| 2020 | 12,894 |
| 2021 | 15,756 |
| 2022 | 12,092 |
| 2023 | 5,278 |
| 2024 | 4,934 |
| 2025 | 4,442 |

## SNP contact records by canonical_year (school year end)
| Year | Value |
|---|---:|
| 2021 | 8,643 |
| 2022 | 8,656 |
| 2023 | 8,694 |
| 2024 | 8,699 |
| 2025 | 8,683 |

## SNP reimbursement records by canonical_year (school year end)
| Year | Value |
|---|---:|
| 2021 | 36,433 |
| 2022 | 20,514 |
| 2023 | 88,413 |
| 2024 | 88,116 |
| 2025 | 87,694 |

## Non-congregate status distribution (search master)
| Status | Count |
|---|---:|
| Unknown | 20,183 |
| Congregate | 5,230 |
| Non-Congregate - Grab-and-go at central site | 39 |
| Non-Congregate - Mobile route – Meals are picked up by children/parents directly from the vehicle. | 5 |
| Non-Congregate - Home delivery | 2 |

Total sites with verified NC source match: **5,276**
Total confirmed non-congregate sites: **46**

## Known limitations
- Verified non-congregate status is available only where public TX Open Data includes meal service type, currently limited to the 2022–2023 contact datasets. Unknown does not mean congregate.
- Reported meals are not unique children served.
- Rural/Urban indicator (`rural_urban_status`) is available only from `8ih4-zp65`, so coverage is limited to ~1,965 SFSP 2022–2023 sites.
- 24ie-9cft (All Summer Sites 2023) is cross-listed: it serves both as the 2023 summer contact source and as one of the three NC sources. It is fetched once and saved into both category folders.
- For each site in the lookup, address/contact/operation fields are taken from the *latest* available summer contact record; SNP flags from the *latest* available SNP contact record. Older years' values are used only when the latest year's value is missing.
