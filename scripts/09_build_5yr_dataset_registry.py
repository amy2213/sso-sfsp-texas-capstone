"""
SSO vs SFSP Texas Capstone
09_build_5yr_dataset_registry.py

Writes a machine-readable registry of all TX Open Data datasets that
the v2 (5-year) pipeline should ingest. The registry is consumed by
scripts/10 (ingest) and scripts/11 (canonical builder).

Output:
  config/tda_5yr_dataset_registry.json

Categories:
- summer_meal_counts        (one canonical combined dataset per period)
- summer_reimbursements     (separate SSO + SFSP per period)
- summer_contacts           (one all-summer-sites dataset per period)
- snp_contacts              (one SNP dataset per school year)
- snp_reimbursements        (one SNP dataset per school year)
- non_congregate_sources    (only the 2022-2023 datasets that carry
                             MealServiceType / RuralOrUrbanCode)

Notes on canonical scope:
- 24ie-9cft (All Summer Sites 2022-2023) appears in BOTH summer_contacts
  and non_congregate_sources. Script 10 deduplicates the network fetch
  and saves the raw CSV to every category folder the dataset belongs to.
- Non-congregate verification is bounded to 2022-2023 because no later-
  year contact dataset carries the field at all (see scripts/08).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List


CONFIG_DIR = "config"
REGISTRY_OUT = os.path.join(CONFIG_DIR, "tda_5yr_dataset_registry.json")
os.makedirs(CONFIG_DIR, exist_ok=True)


def E(dataset_id, label, category, period, canonical_year,
      program_type=None, source_priority=1, use_for_canonical=True,
      notes="") -> dict:
    return {
        "dataset_id": dataset_id,
        "label": label,
        "category": category,
        "period": period,
        "canonical_year": canonical_year,
        "program_type": program_type,
        "source_priority": source_priority,
        "use_for_canonical": use_for_canonical,
        "notes": notes,
    }


# --------------------------------------------------------------------
# A. Summer Meal Counts — canonical combined per period
# --------------------------------------------------------------------
SUMMER_MEAL_COUNTS: List[dict] = [
    E("fjpc-icjc", "SFSP + SSO Meal Counts - 2020",
      "summer_meal_counts", "2020", 2020,
      notes="Combined SFSP+SSO. Canonical for 2020."),
    E("8tne-ysan", "SFSP + SSO Meal Counts - 2020-2021",
      "summer_meal_counts", "2020-2021", 2021,
      notes="Combined SFSP+SSO. Canonical for 2020-21."),
    E("ram8-hjmh", "SFSP + SSO Meal Counts - 2021-2022",
      "summer_meal_counts", "2021-2022", 2022,
      notes="Combined SFSP+SSO. Canonical for 2021-22."),
    E("ihhh-b9xf", "All Summer Sites - Meal Count - 2023",
      "summer_meal_counts", "2023", 2023,
      notes="Combined. Canonical for 2023."),
    E("4axx-sfpm", "All Summer Sites - Meal Count - 2024",
      "summer_meal_counts", "2024", 2024,
      notes="Combined. Canonical for 2024. Re-pulled in v2."),
    E("7z9t-futv", "All Summer Sites - Meal Count - 2025",
      "summer_meal_counts", "2025", 2025,
      notes="Combined. Canonical for 2025."),
]


# --------------------------------------------------------------------
# B. Summer Reimbursements — separate SSO + SFSP per period
# --------------------------------------------------------------------
SUMMER_REIMBURSEMENTS: List[dict] = [
    # SSO
    E("krb3-22yq", "SSO Reimbursements - 2020",
      "summer_reimbursements", "2020", 2020, program_type="SSO"),
    E("kvxp-4a2s", "SSO Reimbursements - 2020-2021",
      "summer_reimbursements", "2020-2021", 2021, program_type="SSO"),
    E("ti35-mz6c", "SSO Reimbursements - 2021-2022",
      "summer_reimbursements", "2021-2022", 2022, program_type="SSO"),
    E("iyyi-2unc", "SSO Reimbursements - 2023",
      "summer_reimbursements", "2023", 2023, program_type="SSO"),
    E("2npc-xpe8", "SSO Reimbursements - 2024",
      "summer_reimbursements", "2024", 2024, program_type="SSO"),
    E("u4fj-has6", "SSO Reimbursements - 2025",
      "summer_reimbursements", "2025", 2025, program_type="SSO"),
    # SFSP
    E("pjew-sxuw", "SFSP Reimbursements - 2020",
      "summer_reimbursements", "2020", 2020, program_type="SFSP"),
    E("6agh-k7hx", "SFSP Reimbursements - 2020-2021",
      "summer_reimbursements", "2020-2021", 2021, program_type="SFSP"),
    E("csqa-694h", "SFSP Reimbursements - 2022",
      "summer_reimbursements", "2022", 2022, program_type="SFSP"),
    E("w6ij-kxxu", "SFSP Reimbursements - 2023",
      "summer_reimbursements", "2023", 2023, program_type="SFSP"),
    E("y6fr-r3cf", "SFSP Reimbursements - 2024",
      "summer_reimbursements", "2024", 2024, program_type="SFSP"),
    E("cuhf-bpya", "SFSP Reimbursements - 2025",
      "summer_reimbursements", "2025", 2025, program_type="SFSP"),
]


# --------------------------------------------------------------------
# C. Summer Contacts & Program Participation — All Summer Sites per year
# --------------------------------------------------------------------
SUMMER_CONTACTS: List[dict] = [
    E("c8jp-i4jb", "All Summer Sites - Contact and Program Participation - 2020",
      "summer_contacts", "2020", 2020),
    E("ixpn-g9tj", "All Summer Sites - Contact and Program Participation - 2021",
      "summer_contacts", "2021", 2021),
    E("7ae2-5muh", "All Summer Sites - Contact and Program Participation - 2022",
      "summer_contacts", "2022", 2022),
    E("24ie-9cft", "All Summer Sites - Contact and Program Participation - 2023",
      "summer_contacts", "2023", 2023,
      notes="Also a non-congregate source (carries MealServiceType)."),
    E("m6ah-wwj6", "All Summer Sites - Contact and Program Participation - 2024",
      "summer_contacts", "2024", 2024),
    E("dj2r-c9rw", "All Summer Sites - Contact and Program Participation - 2025",
      "summer_contacts", "2025", 2025),
]


# --------------------------------------------------------------------
# D. SNP Contact & Participation — per school year
# --------------------------------------------------------------------
SNP_CONTACTS: List[dict] = [
    E("3369-uxbk", "SNP Contact and Program Participation - 2020-2021",
      "snp_contacts", "2020-2021", 2021),
    E("shme-pbr8", "SNP Contact and Program Participation - 2021-2022",
      "snp_contacts", "2021-2022", 2022),
    E("h87y-vai4", "SNP Contact and Program Participation - 2022-2023",
      "snp_contacts", "2022-2023", 2023),
    E("38xr-8xxu", "SNP Contact and Program Participation - 2023-2024",
      "snp_contacts", "2023-2024", 2024),
    E("5ejx-uftk", "SNP Contact and Program Participation - 2024-2025",
      "snp_contacts", "2024-2025", 2025),
]


# --------------------------------------------------------------------
# E. SNP Meal Reimbursements — per school year
# --------------------------------------------------------------------
SNP_REIMBURSEMENTS: List[dict] = [
    E("i674-5yp3", "SNP Meal Reimbursements - 2020-2021",
      "snp_reimbursements", "2020-2021", 2021),
    E("9bfr-4jjm", "SNP Meal Reimbursements - 2021-2022",
      "snp_reimbursements", "2021-2022", 2022),
    E("t9bs-zxkh", "SNP Meal Reimbursements - 2022-2023",
      "snp_reimbursements", "2022-2023", 2023),
    E("kde6-bnft", "SNP Meal Reimbursements - 2023-2024",
      "snp_reimbursements", "2023-2024", 2024),
    E("i9vs-cqmu", "SNP Meal Reimbursements - 2024-2025",
      "snp_reimbursements", "2024-2025", 2025),
]


# --------------------------------------------------------------------
# F. Non-Congregate / MealServiceType public sources (2022-2023 only)
# --------------------------------------------------------------------
NON_CONGREGATE_SOURCES: List[dict] = [
    E("8ih4-zp65", "SFSP Contacts (SFSPCONTACTS) - 2022-2023 [MST source]",
      "non_congregate_sources", "2022-2023", 2023,
      notes="Carries mealservicetype + ruralorurbancode."),
    E("24ie-9cft", "All Summer Sites Contacts - 2022-2023 [MST source]",
      "non_congregate_sources", "2022-2023", 2023,
      notes="Also listed in summer_contacts. Carries mealservicetype."),
    E("82b8-iuvu", "SSO Contacts (SSOCONTACTS) - 2022-2023 [MST source]",
      "non_congregate_sources", "2022-2023", 2023,
      notes="Carries mealservicetype."),
]


def main() -> None:
    all_entries: List[dict] = (
        SUMMER_MEAL_COUNTS
        + SUMMER_REIMBURSEMENTS
        + SUMMER_CONTACTS
        + SNP_CONTACTS
        + SNP_REIMBURSEMENTS
        + NON_CONGREGATE_SOURCES
    )

    payload = {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "domain": "data.texas.gov",
        "scope": (
            "5-year canonical TDA Open Data registry for the SSO/SFSP "
            "capstone v2 pipeline. Non-congregate verification is "
            "available only where public TX Open Data includes "
            "MealServiceType, currently limited to the 2022-2023 contact "
            "datasets. Unknown does not mean congregate."
        ),
        "datasets": all_entries,
    }

    with open(REGISTRY_OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote registry: {REGISTRY_OUT}")
    print(f"Total dataset entries: {len(all_entries)}")
    from collections import Counter
    cat_counts = Counter(e["category"] for e in all_entries)
    for cat, n in sorted(cat_counts.items()):
        print(f"  {cat:28s} : {n}")

    # Unique dataset IDs (counting cross-listed once)
    unique_ids = {e["dataset_id"] for e in all_entries}
    print(f"\nUnique dataset IDs (some are cross-listed): {len(unique_ids)}")
    cross_listed = [
        dsid for dsid in unique_ids
        if sum(1 for e in all_entries if e["dataset_id"] == dsid) > 1
    ]
    if cross_listed:
        print(f"Cross-listed dataset IDs: {sorted(cross_listed)}")


if __name__ == "__main__":
    main()
