"""
SSO vs SFSP Texas Capstone
06_discover_all_meal_service_type_sources.py

Pulls and profiles ALL candidate Texas Open Data datasets that may
expose MealServiceType / non-congregate flags, not just 8ih4-zp65.
Output is a combined long-form master with one row per
(source_dataset_id, ce_id, site_id, program_year) plus per-source
audits so we can see whether 8ih4-zp65 was undercounting verified
non-congregate sites.

This script DOES NOT modify the existing app, the enriched lookup,
or any prior script. It only writes:

  data/lookup/non_congregate_public_source_master.csv
  data/audit/all_meal_service_type_schema_profile.csv
  data/audit/all_meal_service_type_value_counts.csv
  data/audit/all_meal_service_type_join_audit.csv
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from sodapy import Socrata


DATA_RAW = "data/raw/non_congregate_all_sources"
DATA_AUDIT = "data/audit"
DATA_LOOKUP = "data/lookup"

SEARCH_MASTER = os.path.join(DATA_LOOKUP, "ce_site_search_master.csv")
COMBINED_OUT = os.path.join(DATA_LOOKUP, "non_congregate_public_source_master.csv")
SCHEMA_OUT = os.path.join(DATA_AUDIT, "all_meal_service_type_schema_profile.csv")
VC_OUT = os.path.join(DATA_AUDIT, "all_meal_service_type_value_counts.csv")
JOIN_OUT = os.path.join(DATA_AUDIT, "all_meal_service_type_join_audit.csv")

for folder in [DATA_RAW, DATA_AUDIT, DATA_LOOKUP]:
    os.makedirs(folder, exist_ok=True)

CLIENT = Socrata("data.texas.gov", None)
CLIENT.timeout = 180

DATASETS = [
    {"dataset_id": "8ih4-zp65", "label": "TX Open Data 8ih4-zp65 (SFSPCONTACTS 2022-2023)"},
    {"dataset_id": "24ie-9cft", "label": "TX Open Data 24ie-9cft"},
    {"dataset_id": "82b8-iuvu", "label": "TX Open Data 82b8-iuvu"},
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


def normalize_text(value):
    if pd.isna(value):
        return value
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s if s else pd.NA


def first_non_null(series: pd.Series):
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    return s.iloc[0] if len(s) else pd.NA


def first_present(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def latest_year_from_text(val) -> Optional[int]:
    if pd.isna(val):
        return None
    years = re.findall(r"(19|20)\d{2}", str(val))
    raw = re.findall(r"(?:19|20)\d{2}", str(val))
    return int(max(raw)) if raw else None


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
# Source-column candidates (canonical target -> list of candidate names)
# --------------------------------------------------------------------

COL_CANDIDATES = {
    "ce_id": ["ceid", "ce_id"],
    "site_id": ["siteid", "site_id"],
    "program_year_text": ["programyear", "program_year", "year"],
    "meal_service_type_public": ["mealservicetype", "meal_service_type"],
    "rural_urban_status": ["ruralorurbancode", "rural_urban_code", "ruralurban",
                           "rural_or_urban", "rural_or_urban_code"],
    "sfsp_site_type_public": ["sitetype", "site_type"],
    "meal_types_served": ["mealtypesserved", "meal_types_served"],
    "breakfast_time": ["breakfasttime", "breakfast_time"],
    "lunch_time": ["lunchtime", "lunch_time"],
    "supper_time": ["suppertime", "supper_time"],
    "am_snack_time": ["amsnacktime", "am_snack_time"],
    "pm_snack_time": ["pmsnacktime", "pm_snack_time"],
    "breakfast_meal_service_method": ["breakfastmealservicemethod", "breakfast_meal_service_method"],
    "lunch_meal_service_method": ["lunchmealservicemethod", "lunch_meal_service_method"],
    "supper_meal_service_method": ["suppermealservicemethod", "supper_meal_service_method"],
    "am_snack_meal_service_method": ["amsnackmealservicemethod", "am_snack_meal_service_method"],
    "pm_snack_meal_service_method": ["pmsnackmealservicemethod", "pm_snack_meal_service_method"],
}


PRESENCE_CHECKS = ["ceid", "siteid", "programyear", "mealservicetype",
                   "ruralorurbancode", "sitetype"]


def derive_verified_status(value) -> str:
    if pd.isna(value):
        return "Unknown"
    s = str(value)
    if "Non-Congregate" in s:
        return s
    if "Congregate" in s:
        return "Congregate"
    return "Unknown"


# --------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------

def ingest_all() -> Dict[str, pd.DataFrame]:
    print("\nSTEP 1: INGEST CANDIDATE DATASETS")
    print("=" * 80)
    frames = {}
    for item in DATASETS:
        df = fetch_dataset(item["dataset_id"], item["label"])
        if df.empty:
            continue
        path = os.path.join(DATA_RAW, f"{item['dataset_id']}.csv")
        df.to_csv(path, index=False)
        print(f"  saved -> {path}")
        frames[item["dataset_id"]] = df
    print(f"\nSaved {len(frames)} datasets to {DATA_RAW}/")
    return frames


def per_dataset_preview(frames: Dict[str, pd.DataFrame]) -> None:
    print("\nSTEP 2: PER-DATASET PREVIEW")
    print("=" * 80)
    for dsid, df in frames.items():
        d = normalize_columns(df)
        print(f"\n--- {dsid} ---")
        print(f"rows: {len(d):,}")
        print(f"cols: {len(d.columns)}")
        print(f"columns: {list(d.columns)}")
        print("column presence:")
        for col in PRESENCE_CHECKS:
            print(f"  {col:18s} : {'YES' if col in d.columns else 'no'}")

        if "programyear" in d.columns:
            yrs = sorted(d["programyear"].dropna().astype(str).unique().tolist())
            print(f"distinct programyear values: {yrs}")
        if "mealservicetype" in d.columns:
            print("mealservicetype value counts:")
            print(d["mealservicetype"].fillna("<<NULL>>").value_counts(dropna=False).to_string())
        if "ruralorurbancode" in d.columns:
            print("ruralorurbancode value counts:")
            print(d["ruralorurbancode"].fillna("<<NULL>>").value_counts(dropna=False).to_string())
        if "sitetype" in d.columns:
            print("sitetype value counts:")
            print(d["sitetype"].fillna("<<NULL>>").value_counts(dropna=False).to_string())


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
            })
    profile = pd.DataFrame(rows)
    profile.to_csv(SCHEMA_OUT, index=False)
    print(f"Saved -> {SCHEMA_OUT}")
    return profile


def build_value_counts_audit(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    print("\nSTEP 4: VALUE COUNTS (mealservicetype / ruralorurbancode / sitetype)")
    print("=" * 80)
    rows = []
    for dsid, df in frames.items():
        d = normalize_columns(df)
        for col in ("mealservicetype", "ruralorurbancode", "sitetype"):
            if col not in d.columns:
                continue
            vc = d[col].fillna("<<NULL>>").astype(str).value_counts(dropna=False)
            for val, cnt in vc.items():
                rows.append({
                    "dataset_id": dsid,
                    "column_name": col,
                    "value": val,
                    "record_count": int(cnt),
                })
    out = pd.DataFrame(rows)
    out.to_csv(VC_OUT, index=False)
    print(f"Saved -> {VC_OUT}")
    return out


def normalize_to_target_schema(dsid: str, label: str, raw: pd.DataFrame) -> pd.DataFrame:
    """Map a raw dataset onto the target combined schema. One row per
    (ce_id, site_id, program_year), with first_non_null per field."""
    d = normalize_columns(raw)
    if "ceid" not in d.columns and "ce_id" not in d.columns:
        return pd.DataFrame()
    if "siteid" not in d.columns and "site_id" not in d.columns:
        return pd.DataFrame()

    # Pull canonical columns into target names
    for tgt, candidates in COL_CANDIDATES.items():
        src = first_present(d, candidates)
        if src is None:
            d[tgt] = pd.NA
        elif src != tgt:
            d[tgt] = d[src]

    d["ce_id"] = to_id_str(d["ce_id"])
    d["site_id"] = to_id_str(d["site_id"])
    d["program_year"] = d["program_year_text"].apply(latest_year_from_text)

    # Apply whitespace normalization to text fields (preserve source values)
    text_cols = [
        "meal_service_type_public", "rural_urban_status", "sfsp_site_type_public",
        "meal_types_served", "breakfast_time", "lunch_time", "supper_time",
        "am_snack_time", "pm_snack_time",
        "breakfast_meal_service_method", "lunch_meal_service_method",
        "supper_meal_service_method", "am_snack_meal_service_method",
        "pm_snack_meal_service_method",
    ]
    for c in text_cols:
        d[c] = d[c].apply(normalize_text)

    keep = ["ce_id", "site_id", "program_year"] + text_cols
    sub = d[keep].copy()

    # Deduplicate to one row per (ce_id, site_id, program_year)
    agg = {c: (c, first_non_null) for c in sub.columns if c not in {"ce_id", "site_id", "program_year"}}
    out = sub.groupby(["ce_id", "site_id", "program_year"], dropna=False).agg(**agg).reset_index()

    out.insert(0, "source_label", label)
    out.insert(0, "source_dataset_id", dsid)

    out["non_congregate_status_verified"] = out["meal_service_type_public"].apply(derive_verified_status)
    out["non_congregate_source"] = f"public-source meal service type (TX Open Data {dsid})"
    out["rural_urban_source"] = out["rural_urban_status"].apply(
        lambda v: f"public-source rural/urban indicator (TX Open Data {dsid})" if pd.notna(v) and str(v).strip() else pd.NA
    )

    final_order = [
        "source_dataset_id", "source_label",
        "ce_id", "site_id", "program_year",
        "meal_service_type_public", "rural_urban_status", "sfsp_site_type_public",
        "meal_types_served",
        "breakfast_time", "lunch_time", "supper_time", "am_snack_time", "pm_snack_time",
        "breakfast_meal_service_method", "lunch_meal_service_method",
        "supper_meal_service_method", "am_snack_meal_service_method",
        "pm_snack_meal_service_method",
        "non_congregate_status_verified",
        "non_congregate_source", "rural_urban_source",
    ]
    return out[final_order]


def build_combined_master(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    print("\nSTEP 5: BUILD COMBINED LONG-FORM MASTER")
    print("=" * 80)
    parts = []
    for dsid, df in frames.items():
        label = next(it["label"] for it in DATASETS if it["dataset_id"] == dsid)
        sub = normalize_to_target_schema(dsid, label, df)
        if sub.empty:
            print(f"  {dsid}: no ce_id/site_id columns - skipped")
            continue
        print(f"  {dsid}: {len(sub):,} rows after dedup")
        parts.append(sub)
    if not parts:
        return pd.DataFrame()
    combined = pd.concat(parts, ignore_index=True)
    combined.to_csv(COMBINED_OUT, index=False)
    print(f"\nSaved -> {COMBINED_OUT}  ({len(combined):,} rows, {len(combined.columns)} columns)")
    return combined


def build_join_audit(combined: pd.DataFrame) -> pd.DataFrame:
    print("\nSTEP 6: JOIN COVERAGE vs ce_site_search_master.csv")
    print("=" * 80)
    if combined.empty:
        print("  combined master is empty - nothing to audit")
        return pd.DataFrame()
    if not os.path.exists(SEARCH_MASTER):
        print(f"  {SEARCH_MASTER} not found - skipping join audit")
        return pd.DataFrame()

    sm = pd.read_csv(SEARCH_MASTER, dtype={"ce_id": str, "site_id": str},
                     usecols=["ce_id", "site_id"])
    sm["ce_id"] = to_id_str(sm["ce_id"])
    sm["site_id"] = to_id_str(sm["site_id"])
    master_keys = set(zip(sm["ce_id"].astype(str), sm["site_id"].astype(str)))
    print(f"  search master distinct (ce_id, site_id): {len(master_keys):,}")

    rows = []
    for dsid in combined["source_dataset_id"].unique():
        sub = combined[combined["source_dataset_id"] == dsid]
        ds_keys = set(zip(sub["ce_id"].astype(str), sub["site_id"].astype(str)))
        joined = len(ds_keys & master_keys)
        verified_nc = int(sub["non_congregate_status_verified"]
                          .astype(str).str.contains("Non-Congregate").sum())
        verified_nc_matched_keys = {
            k for k in ds_keys
            if k in master_keys
            and not sub[(sub["ce_id"].astype(str) == k[0]) &
                        (sub["site_id"].astype(str) == k[1])
                        & sub["non_congregate_status_verified"].astype(str).str.contains("Non-Congregate")]
            .empty
        }
        rows.append({
            "source_dataset_id": dsid,
            "rows_in_combined": len(sub),
            "distinct_ce_id": sub["ce_id"].dropna().nunique(),
            "distinct_site_id": sub["site_id"].dropna().nunique(),
            "distinct_keys": len(ds_keys),
            "keys_joined_to_search_master": joined,
            "join_pct": round(joined / len(ds_keys) * 100, 2) if ds_keys else 0.0,
            "verified_non_congregate_rows": verified_nc,
            "verified_nc_keys_joined": len(verified_nc_matched_keys),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
    audit = pd.DataFrame(rows)
    audit.to_csv(JOIN_OUT, index=False)
    print(f"Saved -> {JOIN_OUT}")
    print(audit.to_string(index=False))
    return audit


def print_summaries(combined: pd.DataFrame) -> None:
    print("\nSTEP 7: SUMMARY COUNTS")
    print("=" * 80)
    if combined.empty:
        print("  combined master is empty")
        return

    print("\nRow count by source dataset:")
    print(combined.groupby("source_dataset_id").size().rename("rows").to_string())

    print("\nRow count by program year:")
    print(combined.groupby("program_year", dropna=False).size().rename("rows").to_string())

    print("\nValue counts: meal_service_type_public (across all sources):")
    print(combined["meal_service_type_public"].fillna("(missing)").value_counts(dropna=False).to_string())

    print("\nValue counts: non_congregate_status_verified (across all sources):")
    print(combined["non_congregate_status_verified"].fillna("(missing)").value_counts(dropna=False).to_string())

    print("\nValue counts: rural_urban_status (across all sources):")
    print(combined["rural_urban_status"].fillna("(missing)").value_counts(dropna=False).to_string())


def main() -> None:
    print("SSO vs SFSP Texas Capstone - All MealServiceType sources discovery")
    print("=" * 80)

    frames = ingest_all()
    if not frames:
        print("\nNo datasets fetched.")
        return

    per_dataset_preview(frames)
    build_schema_profile(frames)
    build_value_counts_audit(frames)
    combined = build_combined_master(frames)
    build_join_audit(combined)
    print_summaries(combined)

    print("\nDONE")


if __name__ == "__main__":
    main()
