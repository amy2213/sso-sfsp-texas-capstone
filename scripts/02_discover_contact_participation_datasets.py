"""
SSO vs SFSP Texas Capstone
02_discover_contact_participation_datasets.py

Discovery script for additional Texas Open Data datasets that may
carry site address, CE / district address, contact information,
operation dates, serving dates, site model, program participation,
and site-level program details.

This script does NOT touch the clean master tables produced by
scripts/01_ingest_clean_audit.py. It only ingests the new datasets
into a separate raw folder and emits two audit files so we can decide
how to wire them in later.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

import pandas as pd
from sodapy import Socrata


DATA_RAW_CONTACTS = "data/raw/contact_participation"
DATA_AUDIT = "data/audit"
DATA_CLEAN = "data/clean"

for folder in [DATA_RAW_CONTACTS, DATA_AUDIT]:
    os.makedirs(folder, exist_ok=True)

CLIENT = Socrata("data.texas.gov", None)
CLIENT.timeout = 180


DATASETS = [
    {
        "dataset_id": "7ae2-5muh",
        "label": (
            "Summer Meal Programs - All Summer Sites Contact and Program "
            "Participation - Program Period 2022"
        ),
        "dataset_type": "summer_site_contact_participation",
    },
    {
        "dataset_id": "5ejx-uftk",
        "label": (
            "School Nutrition Programs - Contact Information and Site-Level "
            "Program Participation - Program Year 2024-2025"
        ),
        "dataset_type": "snp_site_contact_participation",
    },
]


def clean_colname(col: str) -> str:
    col = str(col).strip().lower()
    col = re.sub(r"[^a-z0-9]+", "_", col)
    col = re.sub(r"_+", "_", col)
    return col.strip("_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [clean_colname(c) for c in d.columns]
    return d


def fetch_dataset(dataset_id: str, label: str, page_size: int = 50000) -> pd.DataFrame:
    print(f"Fetching {label}\n  id={dataset_id} ...", end=" ", flush=True)

    pages = []
    offset = 0
    try:
        while True:
            page = CLIENT.get(dataset_id, limit=page_size, offset=offset)
            if not page:
                break
            pages.append(pd.DataFrame.from_records(page))
            if len(page) < page_size:
                break
            offset += page_size
    except Exception as exc:
        print(f"FAILED ({type(exc).__name__}): {exc}")
        return pd.DataFrame()

    if not pages:
        print("OK: 0 rows")
        return pd.DataFrame()

    df = pd.concat(pages, ignore_index=True)
    print(f"OK: {len(df):,} rows, {len(df.columns)} columns")
    return df


CE_PREFIXES = ("ce_", "cestreet", "cemailing", "ceaddress", "cephone", "ceemail",
               "cecontact", "cefax", "cecounty", "cestatus", "ceapplication",
               "cetermination", "ceterminated")
SITE_PREFIXES = ("site_", "sitestreet", "sitemailing", "siteaddress", "sitephone",
                 "siteemail", "sitecontact", "sitefax", "sitecounty", "sitestatus",
                 "siteapplication", "sitetermination", "siteterminated", "sitetype",
                 "siteisp", "sitename", "siteid")
CE_CONTACT_PEOPLE = ("progradministrator", "progrcoordinator", "programadministrator",
                     "programcoordinator", "superintendent", "childnutdir", "childnutrition",
                     "directorcontact", "sponsorcontact")
SITE_CONTACT_PEOPLE = ("sitecontact",)
ADDRESS_TERMS = ("address", "addr", "street", "city", "zip", "zipcode", "state", "physical")
CONTACT_TERMS = ("phone", "email", "fax", "contact")
CONTACT_PERSON_TERMS = ("salutation", "firstname", "lastname", "title", "name")


def _starts_with_any(s: str, prefixes) -> bool:
    return any(s.startswith(p) for p in prefixes)


def classify_column(col: str) -> str:
    """
    Heuristic single-label classification of a normalized column name into
    one of the discovery categories. First match wins; order is from most
    specific to least specific.
    """
    c = col.lower()

    # 1. CE / district address (address wins over contact so "cemailingaddress*"
    #    isn't mis-routed by the "email" substring in "mailing")
    if _starts_with_any(c, CE_PREFIXES) and any(t in c for t in ADDRESS_TERMS):
        return "CE/district address"
    if (c.startswith("sponsor") or c.startswith("district") or "mailing" in c) and any(t in c for t in ADDRESS_TERMS):
        return "CE/district address"

    # 2. Site address
    if _starts_with_any(c, SITE_PREFIXES) and any(t in c for t in ADDRESS_TERMS):
        return "site address"
    if c in {"physical_address", "physicaladdress", "street", "city", "zip", "zipcode",
             "state_code", "geolocation", "latitude", "longitude"}:
        return "site address"

    # 3. CE / district contact (people + phone/email/fax/contact)
    if _starts_with_any(c, CE_CONTACT_PEOPLE):
        if any(t in c for t in CONTACT_TERMS) or any(t in c for t in CONTACT_PERSON_TERMS):
            return "CE/district contact"
    if _starts_with_any(c, CE_PREFIXES) and any(t in c for t in CONTACT_TERMS):
        return "CE/district contact"
    if (c.startswith("sponsor") or c.startswith("district")) and any(t in c for t in CONTACT_TERMS):
        return "CE/district contact"

    # 4. Site contact
    if _starts_with_any(c, SITE_CONTACT_PEOPLE) and (
        any(t in c for t in CONTACT_TERMS) or any(t in c for t in CONTACT_PERSON_TERMS)
    ):
        return "site contact"
    if _starts_with_any(c, SITE_PREFIXES) and any(t in c for t in CONTACT_TERMS):
        return "site contact"

    # 5. CE identity
    ce_identity_exact = {
        "ceid", "ce_id", "cename", "ce_name",
        "contracting_entity_id", "contracting_entity_name", "contracting_entity",
        "sponsor_id", "sponsor_name", "sponsor",
        "ce_number", "ce_no",
        "cestatus", "ceapplicationcycle", "ceterminationstatus", "ceterminatedasofdate",
        "cecounty",
    }
    if c in ce_identity_exact:
        return "CE identity"
    if "contracting_entity" in c and not any(t in c for t in ADDRESS_TERMS + CONTACT_TERMS):
        return "CE identity"

    # 6. Site identity
    site_identity_exact = {
        "siteid", "site_id", "sitename", "site_name",
        "site_number", "site_no", "site_code",
        "sitestatus", "siteapplicationcycle", "siteterminationstatus", "siteterminatedasofdate",
        "sitecounty", "covidmealsite",
    }
    if c in site_identity_exact:
        return "site identity"

    # 7. Service times
    if "time" in c and any(t in c for t in ("breakfast", "lunch", "snack", "supper", "service", "meal")):
        return "service times"
    if c.endswith("_start_time") or c.endswith("_end_time") or c.endswith("_starttime") or c.endswith("_endtime"):
        return "service times"

    # 8. Serving dates (per-meal serving days/dates)
    if any(t in c for t in ("daysserved", "daysofoperation", "mealtypesserved",
                            "first_meal", "last_meal", "meal_service_start",
                            "meal_service_end", "first_serving", "last_serving")):
        return "serving dates"
    if "serving" in c and ("date" in c or "start" in c or "end" in c or "first" in c or "last" in c):
        return "serving dates"

    # 9. Operation dates
    if "operat" in c and ("date" in c or "start" in c or "end" in c):
        return "operation dates"
    if any(t in c for t in ("start_date", "end_date", "open_date", "close_date",
                            "begin_date", "begindate", "enddate", "startdate")):
        return "operation dates"
    if c in {"season", "session_start", "session_end", "program_start", "program_end",
             "sitestartdate", "siteenddate", "operationstartdate", "operationenddate"}:
        return "operation dates"

    # 10. Non-congregate / rural
    if "non_congregate" in c or "noncongregate" in c or c == "ncs" or "rural" in c:
        return "non-congregate / rural indicators"

    # 11. Site model
    if "site_model" in c or c == "model" or "congregate" in c:
        return "site model"
    if c in {"site_type", "type_of_site", "typeofagency", "typeoforg", "site_category", "sitetype"}:
        return "site model"
    # Grade-level flags describe what kind of site this is
    if c.startswith("grade") or c in {"gradeprek", "gradekinder", "gradeheadstart",
                                       "gradeearlyeducation"}:
        return "site model"

    # 12. Qualification / eligibility (CEP / Provision 2 / ISP / area-eligible)
    if any(t in c for t in ("eligib", "qualif", "free_reduced", "frpe", "isp",
                            "area_eligible", "areaeligible", "percent_free",
                            "fr_eligible", "provision2")):
        return "qualification / eligibility fields"
    if c == "cep":
        return "qualification / eligibility fields"

    # 13. Program participation
    if c in {"program", "programs", "program_name", "program_type"}:
        return "program participation"
    if any(t in c for t in ("nslp", "sbp", "snp", "sso", "sfsp", "cacfp", "afterschool",
                            "participat", "_offered", "_participation",
                            "schoolbreakfast", "nationalschoollunch", "specialmilk",
                            "ffvp", "severeneed", "universalfree", "pricing",
                            "managedbyfsmc", "mealspurchased", "vendmeals", "claims")):
        return "program participation"

    # 14. Meal types (flags / indicators only)
    if c in {"breakfast", "lunch", "supper", "snack", "am_snack", "pm_snack",
             "breakfast_offered", "lunch_offered", "supper_offered", "snack_offered"}:
        return "meal types"

    return "unknown"


def ingest_all() -> Dict[str, pd.DataFrame]:
    frames = {}

    print("\nSTEP 1: INGEST CONTACT / PARTICIPATION DATASETS")
    print("=" * 80)

    for item in DATASETS:
        dataset_id = item["dataset_id"]
        label = item["label"]
        dtype = item["dataset_type"]

        df = fetch_dataset(dataset_id, label)
        if df.empty:
            continue

        raw_filename = f"{dtype}_{dataset_id}.csv"
        raw_path = os.path.join(DATA_RAW_CONTACTS, raw_filename)
        df.to_csv(raw_path, index=False)
        print(f"  saved -> {raw_path}")

        key = f"{dtype}_{dataset_id}"
        frames[key] = df

    print(f"\nSaved {len(frames)} datasets to {DATA_RAW_CONTACTS}/")
    return frames


def per_dataset_preview(frames: Dict[str, pd.DataFrame]) -> None:
    print("\nSTEP 2: PER-DATASET PREVIEW")
    print("=" * 80)

    for key, df in frames.items():
        d = normalize_columns(df)
        print(f"\n--- {key} ---")
        print(f"rows: {len(d):,}")
        print(f"cols: {len(d.columns)}")
        print(f"columns: {list(d.columns)}")
        print("first 3 rows:")
        with pd.option_context("display.max_columns", None,
                               "display.width", 200,
                               "display.max_colwidth", 40):
            print(d.head(3).to_string(index=False))


def build_schema_profile(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    print("\nSTEP 3: SCHEMA PROFILE")
    print("=" * 80)

    rows = []
    for key, df in frames.items():
        d = normalize_columns(df)
        for col in d.columns:
            non_null = d[col].dropna()
            sample = non_null.iloc[0] if len(non_null) else None
            null_pct = round(d[col].isna().mean() * 100, 2)
            rows.append({
                "dataset_key": key,
                "column_name": col,
                "sample_value": sample,
                "null_pct": null_pct,
                "dtype_inferred": str(d[col].dtype),
            })

    profile = pd.DataFrame(rows)
    outpath = os.path.join(DATA_AUDIT, "contact_participation_schema_profile.csv")
    profile.to_csv(outpath, index=False)
    print(f"Saved schema profile -> {outpath}")
    return profile


def build_field_inventory(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    print("\nSTEP 4: FIELD INVENTORY (categorized)")
    print("=" * 80)

    rows = []
    for key, df in frames.items():
        d = normalize_columns(df)
        for col in d.columns:
            non_null = d[col].dropna()
            sample = non_null.iloc[0] if len(non_null) else None
            rows.append({
                "dataset_key": key,
                "column_name": col,
                "category": classify_column(col),
                "sample_value": sample,
                "null_pct": round(d[col].isna().mean() * 100, 2),
            })

    inventory = pd.DataFrame(rows)
    outpath = os.path.join(DATA_AUDIT, "contact_participation_field_inventory.csv")
    inventory.to_csv(outpath, index=False)
    print(f"Saved field inventory -> {outpath}")

    counts = inventory.groupby(["dataset_key", "category"]).size().reset_index(name="n_columns")
    print("\nColumns per category, per dataset:")
    print(counts.to_string(index=False))

    return inventory


def summarize_categories(inventory: pd.DataFrame, dataset_key: str, categories: List[str]) -> Dict[str, List[str]]:
    out = {}
    sub = inventory[inventory["dataset_key"] == dataset_key]
    for cat in categories:
        cols = sub.loc[sub["category"] == cat, "column_name"].tolist()
        out[cat] = cols
    return out


def join_check_against_meals(frames: Dict[str, pd.DataFrame]) -> None:
    print("\nSTEP 5: JOIN CHECK AGAINST summer_meals_master.csv")
    print("=" * 80)

    meals_path = os.path.join(DATA_CLEAN, "summer_meals_master.csv")
    if not os.path.exists(meals_path):
        print(f"  {meals_path} not found - skipping join check")
        return

    meals = pd.read_csv(meals_path, usecols=["ce_id", "site_id"], dtype=str)
    meals_ce = set(meals["ce_id"].dropna().astype(str).str.strip())
    meals_site = set(meals["site_id"].dropna().astype(str).str.strip())
    print(f"  meals master: {len(meals_ce):,} distinct ce_id, {len(meals_site):,} distinct site_id")

    for key, df in frames.items():
        d = normalize_columns(df)
        has_ceid = "ceid" in d.columns or "ce_id" in d.columns
        has_siteid = "siteid" in d.columns or "site_id" in d.columns
        ceid_col = "ceid" if "ceid" in d.columns else ("ce_id" if "ce_id" in d.columns else None)
        siteid_col = "siteid" if "siteid" in d.columns else ("site_id" if "site_id" in d.columns else None)

        print(f"\n  {key}")
        print(f"    has CEID col   : {has_ceid}  ({ceid_col})")
        print(f"    has SiteID col : {has_siteid}  ({siteid_col})")

        if ceid_col:
            ce_vals = set(d[ceid_col].dropna().astype(str).str.strip())
            overlap = ce_vals & meals_ce
            print(f"    distinct CEID in this dataset : {len(ce_vals):,}")
            print(f"    CEIDs also in meals master    : {len(overlap):,}")

        if siteid_col:
            site_vals = set(d[siteid_col].dropna().astype(str).str.strip())
            overlap = site_vals & meals_site
            print(f"    distinct SiteID in this dataset : {len(site_vals):,}")
            print(f"    SiteIDs also in meals master    : {len(overlap):,}")


def print_category_findings(inventory: pd.DataFrame) -> None:
    print("\nSTEP 6: CATEGORY FINDINGS")
    print("=" * 80)

    interesting = [
        "CE/district address",
        "site address",
        "CE/district contact",
        "site contact",
        "operation dates",
        "serving dates",
        "service times",
        "site model",
        "non-congregate / rural indicators",
        "program participation",
        "qualification / eligibility fields",
        "meal types",
    ]

    for key in inventory["dataset_key"].unique():
        print(f"\n--- {key} ---")
        buckets = summarize_categories(inventory, key, interesting)
        for cat, cols in buckets.items():
            if cols:
                print(f"  {cat}:")
                for c in cols:
                    print(f"    - {c}")
        unknown_cols = inventory.loc[
            (inventory["dataset_key"] == key) & (inventory["category"] == "unknown"),
            "column_name",
        ].tolist()
        if unknown_cols:
            print(f"  unknown (not auto-classified):")
            for c in unknown_cols:
                print(f"    - {c}")


def main() -> None:
    print("SSO vs SFSP Texas Capstone - Contact / Participation discovery")
    print("=" * 80)

    frames = ingest_all()
    if not frames:
        print("\nNo datasets fetched - nothing to do.")
        return

    per_dataset_preview(frames)
    build_schema_profile(frames)
    inventory = build_field_inventory(frames)
    print_category_findings(inventory)
    join_check_against_meals(frames)

    print("\nDONE")
    print("Next steps:")
    print("  - Review data/audit/contact_participation_schema_profile.csv")
    print("  - Review data/audit/contact_participation_field_inventory.csv")
    print("  - Decide which columns to enrich summer_meals_master with")


if __name__ == "__main__":
    main()
