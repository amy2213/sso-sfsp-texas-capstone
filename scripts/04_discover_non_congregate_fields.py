"""
SSO vs SFSP Texas Capstone
04_discover_non_congregate_fields.py

Discovery-only script. Pulls Texas Open Data candidates that may carry
explicit non-congregate / meal service model / rural-urban / mobile-
route fields and profiles them. Does NOT modify the clean masters or
the dashboard. Outputs four audit files:

  data/audit/non_congregate_schema_profile.csv
  data/audit/non_congregate_field_inventory.csv
  data/audit/non_congregate_value_samples.csv
  data/audit/non_congregate_join_audit.csv

Failure handling: any dataset that errors (e.g., 403 / 404 from the
Socrata API) is logged and skipped. The rest of the run continues.

Wording note: when a dataset really does carry a `mealservicetype` or
`ruralorurbancode` column, we label those as "public-source meal
service type" and "public-source rural/urban indicator" respectively.
We do NOT infer non-congregate status from vague text — only from
values that explicitly say "Non-Congregate".
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from sodapy import Socrata


DATA_RAW_NC = "data/raw/non_congregate"
DATA_AUDIT = "data/audit"
DATA_LOOKUP = "data/lookup"

SEARCH_MASTER = os.path.join(DATA_LOOKUP, "ce_site_search_master.csv")

for folder in [DATA_RAW_NC, DATA_AUDIT]:
    os.makedirs(folder, exist_ok=True)

CLIENT = Socrata("data.texas.gov", None)
CLIENT.timeout = 180


DATASETS = [
    {
        "dataset_id": "8ih4-zp65",
        "label": "TX Open Data candidate 8ih4-zp65 (MealServiceType expected)",
    },
    {
        "dataset_id": "temp-7qi5",
        "label": "TX Open Data candidate temp-7qi5 (rural / non-congregate expected)",
    },
]

NC_VALUE_KEYWORDS = [
    "non", "congregate", "mealservice", "service_type", "rural", "urban",
    "mobile", "route", "pickup", "pick", "delivery", "grab",
    "site_type", "sitetype", "model",
]


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def clean_colname(col: str) -> str:
    col = str(col).strip().lower()
    col = re.sub(r"[^a-z0-9]+", "_", col)
    col = re.sub(r"_+", "_", col)
    return col.strip("_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [clean_colname(c) for c in d.columns]
    return d


def to_id_str(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    return s.where(~s.isin(["nan", "None", "NaT", "", "<NA>"]), pd.NA)


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


# --------------------------------------------------------------------
# Column classifier (single-label, first match wins)
# --------------------------------------------------------------------

def classify_column(col: str) -> str:
    c = col.lower()

    # Order matters: more specific buckets first.

    # 1. Meal service type (the explicit public-source field we hope to find)
    if any(t in c for t in ("mealservicetype", "meal_service_type",
                            "meal_service", "service_type",
                            "servicetype", "mealtype")):
        return "meal service type"

    # 2. Explicit non-congregate indicator column name
    if "non_congregate" in c or "noncongregate" in c or c.endswith("_nc"):
        return "non-congregate indicator"

    # 3. Rural / urban indicator
    if any(t in c for t in ("ruralorurban", "rural_urban", "rurality",
                            "rural_code", "urban_code", "ruralurban")):
        return "rural / urban indicator"
    if c == "rural" or c == "urban":
        return "rural / urban indicator"

    # 4. Mobile route / delivery / pickup
    if any(t in c for t in ("mobile", "route", "grab", "pickup", "pick_up",
                            "delivery", "delivers", "dropoff", "drop_off")):
        return "mobile route / delivery / pickup indicator"

    # 5. Site type
    if c in {"sitetype", "site_type", "type_of_site", "site_category"}:
        return "site type"
    if c in {"typeofagency", "typeoforg"}:
        return "site type"

    # 6. CE identity
    if c in {"ceid", "ce_id", "cename", "ce_name", "contracting_entity",
             "contracting_entity_id", "contracting_entity_name",
             "sponsor_id", "sponsor_name"}:
        return "CE identity"
    if "contracting_entity" in c:
        return "CE identity"

    # 7. Site identity
    if c in {"siteid", "site_id", "sitename", "site_name",
             "site_number", "site_no", "site_code"}:
        return "site identity"

    # 8. Program year / program type
    if c in {"programyear", "program_year", "year"}:
        return "program year"
    if c in {"program", "programs", "program_type", "program_name"}:
        return "program type"

    # 9. Address
    if any(t in c for t in ("address", "addr", "street", "city", "zip",
                            "zipcode", "state", "physical")):
        return "address"

    # 10. Contact
    if any(t in c for t in ("phone", "email", "fax", "contact")):
        return "contact"

    # 11. Dates
    if any(t in c for t in ("date", "start", "end", "operation", "claim")):
        return "dates"

    return "unknown"


# --------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------

def ingest_all() -> Dict[str, pd.DataFrame]:
    frames = {}
    print("\nSTEP 1: INGEST CANDIDATE DATASETS")
    print("=" * 80)
    for item in DATASETS:
        df = fetch_dataset(item["dataset_id"], item["label"])
        if df.empty:
            continue
        raw_path = os.path.join(DATA_RAW_NC, f"{item['dataset_id']}.csv")
        df.to_csv(raw_path, index=False)
        print(f"  saved -> {raw_path}")
        frames[item["dataset_id"]] = df
    print(f"\nSaved {len(frames)} datasets to {DATA_RAW_NC}/")
    return frames


COLUMN_PRESENCE_CHECKS = ["ceid", "siteid", "programyear", "program",
                          "mealservicetype", "ruralorurbancode", "sitetype"]


def per_dataset_preview(frames: Dict[str, pd.DataFrame]) -> None:
    print("\nSTEP 2: PER-DATASET PREVIEW")
    print("=" * 80)
    for dsid, df in frames.items():
        d = normalize_columns(df)
        print(f"\n--- {dsid} ---")
        print(f"rows: {len(d):,}")
        print(f"cols: {len(d.columns)}")
        print(f"columns: {list(d.columns)}")
        print("first 3 rows:")
        with pd.option_context("display.max_columns", None,
                               "display.width", 220,
                               "display.max_colwidth", 50):
            print(d.head(3).to_string(index=False))
        print("column presence:")
        for col in COLUMN_PRESENCE_CHECKS:
            present = col in d.columns
            print(f"  {col:18s} : {'YES' if present else 'no'}")


def build_schema_profile(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    print("\nSTEP 3: SCHEMA PROFILE")
    print("=" * 80)
    rows = []
    for dsid, df in frames.items():
        d = normalize_columns(df)
        for col in d.columns:
            non_null = d[col].dropna()
            sample = non_null.iloc[0] if len(non_null) else None
            rows.append({
                "dataset_id": dsid,
                "column_name": col,
                "sample_value": sample,
                "null_pct": round(d[col].isna().mean() * 100, 2),
                "dtype_inferred": str(d[col].dtype),
            })
    profile = pd.DataFrame(rows)
    outpath = os.path.join(DATA_AUDIT, "non_congregate_schema_profile.csv")
    profile.to_csv(outpath, index=False)
    print(f"Saved -> {outpath}")
    return profile


def build_field_inventory(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    print("\nSTEP 4: FIELD INVENTORY")
    print("=" * 80)
    rows = []
    for dsid, df in frames.items():
        d = normalize_columns(df)
        for col in d.columns:
            non_null = d[col].dropna()
            sample = non_null.iloc[0] if len(non_null) else None
            rows.append({
                "dataset_id": dsid,
                "column_name": col,
                "category": classify_column(col),
                "sample_value": sample,
                "null_pct": round(d[col].isna().mean() * 100, 2),
            })
    inventory = pd.DataFrame(rows)
    outpath = os.path.join(DATA_AUDIT, "non_congregate_field_inventory.csv")
    inventory.to_csv(outpath, index=False)
    print(f"Saved -> {outpath}")

    counts = inventory.groupby(["dataset_id", "category"]).size().reset_index(name="n_columns")
    print("\nColumns per category, per dataset:")
    print(counts.to_string(index=False))
    return inventory


def is_candidate_nc_column(col: str) -> bool:
    c = col.lower()
    return any(kw in c for kw in NC_VALUE_KEYWORDS)


def build_value_samples(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    print("\nSTEP 5: VALUE SAMPLES FOR NC / MODEL / RURAL / URBAN COLUMNS")
    print("=" * 80)
    rows = []
    for dsid, df in frames.items():
        d = normalize_columns(df)
        candidate_cols = [c for c in d.columns if is_candidate_nc_column(c)]
        if not candidate_cols:
            print(f"\n--- {dsid}: no NC/model candidate columns ---")
            continue
        print(f"\n--- {dsid}: candidate columns -> {candidate_cols} ---")
        for col in candidate_cols:
            vc = d[col].fillna("<<NULL>>").astype(str).value_counts(dropna=False).head(25)
            print(f"\n  {col} value counts (top 25):")
            for val, cnt in vc.items():
                print(f"    {cnt:>8,}  {val}")
                rows.append({
                    "dataset_id": dsid,
                    "column_name": col,
                    "value": val,
                    "record_count": int(cnt),
                })
    samples = pd.DataFrame(rows)
    outpath = os.path.join(DATA_AUDIT, "non_congregate_value_samples.csv")
    samples.to_csv(outpath, index=False)
    print(f"\nSaved -> {outpath}")
    return samples


def build_join_audit(frames: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    print("\nSTEP 6: JOIN COVERAGE vs ce_site_search_master")
    print("=" * 80)
    if not os.path.exists(SEARCH_MASTER):
        print(f"  {SEARCH_MASTER} not found - skipping join check.")
        return None

    search = pd.read_csv(SEARCH_MASTER, dtype={"ce_id": str, "site_id": str},
                         usecols=["ce_id", "site_id"])
    search["ce_id"] = to_id_str(search["ce_id"])
    search["site_id"] = to_id_str(search["site_id"])
    master_keys = set(zip(search["ce_id"].astype(str), search["site_id"].astype(str)))
    print(f"  ce_site_search_master keys: {len(master_keys):,}")

    rows = []
    for item in DATASETS:
        dsid = item["dataset_id"]
        label = item["label"]

        if dsid not in frames:
            rows.append({
                "source_dataset_id": dsid,
                "source_label": label,
                "row_count": 0,
                "distinct_ce_id": 0,
                "distinct_site_id": 0,
                "keys_joined_to_search_master": 0,
                "join_pct": 0.0,
                "has_meal_service_type": False,
                "has_rural_urban": False,
                "has_site_type": False,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })
            continue

        d = normalize_columns(frames[dsid])
        ce_col = "ceid" if "ceid" in d.columns else ("ce_id" if "ce_id" in d.columns else None)
        site_col = "siteid" if "siteid" in d.columns else ("site_id" if "site_id" in d.columns else None)

        distinct_ce = (
            to_id_str(d[ce_col]).dropna().astype(str).nunique() if ce_col else 0
        )
        distinct_site = (
            to_id_str(d[site_col]).dropna().astype(str).nunique() if site_col else 0
        )

        keys_joined = 0
        join_pct = 0.0
        if ce_col and site_col:
            ce_vals = to_id_str(d[ce_col]).astype(str)
            site_vals = to_id_str(d[site_col]).astype(str)
            dataset_keys = set(zip(ce_vals, site_vals))
            keys_joined = len(dataset_keys & master_keys)
            if dataset_keys:
                join_pct = round(keys_joined / len(dataset_keys) * 100, 2)

        has_mst = any(c in d.columns for c in ("mealservicetype", "meal_service_type"))
        has_ru = any(
            c in d.columns
            for c in ("ruralorurbancode", "ruralorurban", "rural_urban",
                      "rural", "urban", "rurality")
        )
        has_st = any(c in d.columns for c in ("sitetype", "site_type"))

        rows.append({
            "source_dataset_id": dsid,
            "source_label": label,
            "row_count": len(d),
            "distinct_ce_id": distinct_ce,
            "distinct_site_id": distinct_site,
            "keys_joined_to_search_master": keys_joined,
            "join_pct": join_pct,
            "has_meal_service_type": has_mst,
            "has_rural_urban": has_ru,
            "has_site_type": has_st,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    audit = pd.DataFrame(rows)
    outpath = os.path.join(DATA_AUDIT, "non_congregate_join_audit.csv")
    audit.to_csv(outpath, index=False)
    print(f"Saved -> {outpath}")
    print(audit.to_string(index=False))
    return audit


def main() -> None:
    print("SSO vs SFSP Texas Capstone - Non-Congregate field discovery")
    print("=" * 80)

    frames = ingest_all()
    if not frames:
        print("\nNo datasets fetched - nothing more to do.")
        # Still write empty audit files so downstream tooling sees them
        return

    per_dataset_preview(frames)
    build_schema_profile(frames)
    build_field_inventory(frames)
    build_value_samples(frames)
    build_join_audit(frames)

    print("\nDONE")
    print("Next steps:")
    print("  - Inspect non_congregate_value_samples.csv to confirm the")
    print("    mealservicetype / ruralorurbancode value vocabularies are stable.")
    print("  - If join coverage is high, consider scripts/05 to enrich the")
    print("    lookup table with these public-source fields.")


if __name__ == "__main__":
    main()
