"""
SSO vs SFSP Texas Capstone
01_ingest_clean_audit.py

Pulls public Texas Open Data Portal datasets, saves raw CSVs,
creates clean master files, and generates basic audit outputs.

Note on terminology:
This pipeline reports MEAL COUNTS (i.e., reported meals served), not
unique children served. A child receiving breakfast and lunch on the
same day counts as two meals.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
from sodapy import Socrata


DATA_RAW = "data/raw"
DATA_CLEAN = "data/clean"
DATA_AUDIT = "data/audit"
SQL_DIR = "sql"
DOCS_DIR = "docs"

for folder in [DATA_RAW, DATA_CLEAN, DATA_AUDIT, SQL_DIR, DOCS_DIR]:
    os.makedirs(folder, exist_ok=True)

CLIENT = Socrata("data.texas.gov", None)
CLIENT.timeout = 180


DATASETS = [
    {
        "dataset_id": "ckuq-8u2b",
        "label": "SSO Meal Counts 2019",
        "program_year": 2019,
        "dataset_type": "meal_counts",
        "default_program_type": "SSO",
    },
    {
        "dataset_id": "m23c-22mm",
        "label": "SSO Meal Counts 2021-2022",
        "program_year": 2022,
        "dataset_type": "meal_counts",
        "default_program_type": "SSO",
    },
    {
        "dataset_id": "pxzu-afsv",
        "label": "SFSP + SSO Meal Counts 2018",
        "program_year": 2018,
        "dataset_type": "meal_counts",
        "default_program_type": None,
    },
    {
        "dataset_id": "4axx-sfpm",
        "label": "All Summer Sites Meal Count 2024",
        "program_year": 2024,
        "dataset_type": "meal_counts",
        "default_program_type": None,
    },
    {
        "dataset_id": "rbdj-agw7",
        "label": "SSO Reimbursements 2019",
        "program_year": 2019,
        "dataset_type": "reimbursements",
        "default_program_type": "SSO",
    },
    {
        "dataset_id": "ti35-mz6c",
        "label": "SSO Reimbursements 2021-2022",
        "program_year": 2022,
        "dataset_type": "reimbursements",
        "default_program_type": "SSO",
    },
    {
        "dataset_id": "4z3r-huup",
        "label": "Approved SFSP and SSO Sites 2023",
        "program_year": 2023,
        "dataset_type": "approved_sites",
        "default_program_type": None,
    },
    {
        "dataset_id": "j2sd-a7ir",
        "label": "Approved SFSP and SSO Sites 2024",
        "program_year": 2024,
        "dataset_type": "approved_sites",
        "default_program_type": None,
    },
    {
        "dataset_id": "t3jr-vyxe",
        "label": "Approved SFSP and SSO Sites 2025",
        "program_year": 2025,
        "dataset_type": "approved_sites",
        "default_program_type": None,
    },
    {
        "dataset_id": "4tpe-vtdp",
        "label": "Approved CEs 2025",
        "program_year": 2025,
        "dataset_type": "approved_ces",
        "default_program_type": None,
    },
    {
        "dataset_id": "4zvx-6dyc",
        "label": "Approved CEs 2026",
        "program_year": 2026,
        "dataset_type": "approved_ces",
        "default_program_type": None,
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


def first_present(d: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in d.columns:
            return c
    return None


def column_or_zero(d: pd.DataFrame, name: Optional[str]) -> pd.Series:
    if name and name in d.columns:
        return to_number(d[name]).fillna(0)
    return pd.Series([0] * len(d), index=d.index, dtype="float64")


def to_number(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def safe_upper(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.upper()


def build_match_key(*values) -> str:
    joined = "|".join("" if pd.isna(v) else str(v) for v in values)
    joined = joined.upper().strip()
    joined = re.sub(r"[^A-Z0-9]+", "_", joined)
    return joined.strip("_")


def fetch_dataset(dataset_id: str, label: str, page_size: int = 50000) -> pd.DataFrame:
    """
    Fetch a Socrata dataset with paginated requests to avoid silent truncation.
    Loops with limit/offset until a page returns fewer than page_size rows.
    Allows 403 (and other errors) to be logged and skipped without crashing.
    """
    print(f"Fetching {label} ({dataset_id})...", end=" ", flush=True)

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


def ingest_all() -> Tuple[Dict[str, pd.DataFrame], List[dict]]:
    frames = {}
    failures = []

    print("\nSTEP 1: INGEST DATASETS")
    print("=" * 80)

    for item in DATASETS:
        dataset_id = item["dataset_id"]
        label = item["label"]
        year = item["program_year"]
        dtype = item["dataset_type"]

        df = fetch_dataset(dataset_id, label)

        if df.empty:
            failures.append({"dataset_id": dataset_id, "label": label, "dataset_type": dtype})
            continue

        safe_label = clean_colname(label)
        raw_filename = f"{year}_{dtype}_{safe_label}_{dataset_id}.csv"
        raw_path = os.path.join(DATA_RAW, raw_filename)
        df.to_csv(raw_path, index=False)

        key = f"{year}_{dtype}_{dataset_id}"
        frames[key] = df

    print(f"\nSaved {len(frames)} raw datasets to {DATA_RAW}/")
    if failures:
        print(f"Skipped {len(failures)} datasets (likely non-tabular / 403):")
        for f in failures:
            print(f"  - {f['label']} ({f['dataset_id']}) [{f['dataset_type']}]")

    return frames, failures


def profile_schemas(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []

    print("\nSTEP 2: PROFILE SCHEMAS")
    print("=" * 80)

    for key, df in frames.items():
        d = normalize_columns(df)

        print(f"\n{key}")
        print(f"Shape: {d.shape}")
        print(f"Columns: {list(d.columns)}")

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
    outpath = os.path.join(DATA_AUDIT, "schema_profile.csv")
    profile.to_csv(outpath, index=False)

    print(f"\nSchema profile saved to {outpath}")
    return profile


def get_dataset_metadata(dataset_id: str) -> dict:
    for item in DATASETS:
        if item["dataset_id"] == dataset_id:
            return item
    raise ValueError(f"Dataset ID not found in registry: {dataset_id}")


def extract_dataset_id_from_key(key: str) -> str:
    return key.split("_")[-1]


def classify_program_value(value: str) -> str:
    v = (value or "").upper().replace("_", " ")
    if "SSO" in v or "SEAMLESS" in v:
        return "SSO"
    if "SFSP" in v or "SUMMER FOOD" in v:
        return "SFSP"
    return "UNKNOWN"


def standardize_program_type(d: pd.DataFrame, default_program_type: Optional[str]) -> pd.Series:
    program_col = first_present(d, ["program", "program_type", "program_name", "meal_program", "type"])

    if program_col:
        return safe_upper(d[program_col]).apply(classify_program_value)

    if default_program_type:
        return pd.Series([default_program_type] * len(d), index=d.index)

    return pd.Series(["UNKNOWN"] * len(d), index=d.index)


def standardize_meal_counts(key: str, df: pd.DataFrame) -> pd.DataFrame:
    dataset_id = extract_dataset_id_from_key(key)
    meta = get_dataset_metadata(dataset_id)

    d = normalize_columns(df)

    out = pd.DataFrame(index=d.index)

    out["source_dataset"] = meta["label"]
    out["source_dataset_id"] = dataset_id

    # program_year: from dataset column if present, otherwise registry value
    if "programyear" in d.columns:
        out["program_year"] = to_number(d["programyear"]).fillna(meta["program_year"]).astype(int)
    else:
        out["program_year"] = meta["program_year"]

    out["program_type"] = standardize_program_type(d, meta["default_program_type"])

    out["ce_id"] = d["ceid"] if "ceid" in d.columns else None
    out["ce_name"] = d["cename"] if "cename" in d.columns else None
    out["site_id"] = d["siteid"] if "siteid" in d.columns else None
    out["site_name"] = d["sitename"] if "sitename" in d.columns else None

    # county: sitecounty preferred, fall back to cecounty
    if "sitecounty" in d.columns:
        out["county"] = d["sitecounty"]
    elif "cecounty" in d.columns:
        out["county"] = d["cecounty"]
    else:
        out["county"] = None

    # region: tdaregion preferred, fall back to esc
    if "tdaregion" in d.columns:
        out["region"] = d["tdaregion"]
    elif "esc" in d.columns:
        out["region"] = d["esc"]
    else:
        out["region"] = None

    site_type_col = first_present(d, ["typeofagency", "typeoforg", "site_type", "type_of_site"])
    out["site_type"] = d[site_type_col] if site_type_col else None

    # Meal columns: prefer the *total variants (specific TX schema), fall back to bare names
    breakfast_col = first_present(d, ["breakfasttotal", "breakfast"])
    lunch_col = first_present(d, ["lunchtotal", "lunch"])
    supper_col = first_present(d, ["suppertotal", "supper"])

    out["breakfast_meals"] = column_or_zero(d, breakfast_col)
    out["lunch_meals"] = column_or_zero(d, lunch_col)
    out["supper_meals"] = column_or_zero(d, supper_col)

    # Snacks: combine AM + PM where the columns exist; otherwise fall back to totalsnacks
    am_snack = column_or_zero(d, "amsnacktotal" if "amsnacktotal" in d.columns else None)
    pm_snack = column_or_zero(d, "pmsnacktotal" if "pmsnacktotal" in d.columns else None)
    if "amsnacktotal" in d.columns or "pmsnacktotal" in d.columns:
        out["snack_meals"] = am_snack + pm_snack
    elif "totalsnacks" in d.columns:
        out["snack_meals"] = column_or_zero(d, "totalsnacks")
    else:
        out["snack_meals"] = 0.0

    # Service days: prefer lunchdays, then breakfastdays, then supperdays
    service_days_col = first_present(d, ["lunchdays", "breakfastdays", "supperdays", "service_days"])
    out["service_days"] = to_number(d[service_days_col]) if service_days_col else pd.NA

    # total_meals: prefer pre-computed totals, otherwise sum the parts
    if "totalmealssnacks" in d.columns:
        out["total_meals"] = to_number(d["totalmealssnacks"]).fillna(0)
    elif "totalmeals_snacks" in d.columns:
        out["total_meals"] = to_number(d["totalmeals_snacks"]).fillna(0)
    else:
        out["total_meals"] = (
            out["breakfast_meals"]
            + out["lunch_meals"]
            + out["snack_meals"]
            + out["supper_meals"]
        )

    covid_col = first_present(d, ["covid_site", "covid_meal_site", "covid", "covid_flag"])
    out["covid_site_flag"] = safe_upper(d[covid_col]).str[0] if covid_col else "N"

    out["claim_date"] = d["claimdate"] if "claimdate" in d.columns else None

    out["record_match_key"] = [
        build_match_key(py, ce, site, name, county, cd)
        for py, ce, site, name, county, cd in zip(
            out["program_year"],
            out["ce_id"],
            out["site_id"],
            out["site_name"],
            out["county"],
            out["claim_date"],
        )
    ]

    out["data_quality_flags"] = out.apply(meal_record_flags, axis=1)

    return out


def meal_record_flags(row: pd.Series) -> str:
    flags = []
    if pd.isna(row.get("ce_id")) or str(row.get("ce_id")).strip() == "":
        flags.append("missing_ce_id")
    if pd.isna(row.get("site_id")) or str(row.get("site_id")).strip() == "":
        flags.append("missing_site_id")
    if pd.isna(row.get("site_name")) or str(row.get("site_name")).strip() == "":
        flags.append("missing_site_name")
    if pd.isna(row.get("county")) or str(row.get("county")).strip() == "":
        flags.append("missing_county")
    if str(row.get("program_type", "")).upper() == "UNKNOWN":
        flags.append("unknown_program_type")
    total = row.get("total_meals")
    if pd.notna(total):
        if total == 0:
            flags.append("zero_total_meals")
        elif total < 0:
            flags.append("negative_total_meals")
    return "|".join(flags) if flags else "ok"


def standardize_reimbursements(key: str, df: pd.DataFrame) -> pd.DataFrame:
    dataset_id = extract_dataset_id_from_key(key)
    meta = get_dataset_metadata(dataset_id)

    d = normalize_columns(df)

    out = pd.DataFrame(index=d.index)

    out["source_dataset"] = meta["label"]
    out["source_dataset_id"] = dataset_id

    if "programyear" in d.columns:
        out["program_year"] = to_number(d["programyear"]).fillna(meta["program_year"]).astype(int)
    else:
        out["program_year"] = meta["program_year"]

    out["program_type"] = standardize_program_type(d, meta["default_program_type"])

    out["ce_id"] = d["ceid"] if "ceid" in d.columns else None
    out["ce_name"] = d["cename"] if "cename" in d.columns else None
    out["county"] = d["cecounty"] if "cecounty" in d.columns else None
    out["region"] = d["tdaregion"] if "tdaregion" in d.columns else None
    out["claim_date"] = d["claimdate"] if "claimdate" in d.columns else None

    # total_meals: sum of the per-meal-type reimbursed-meal counts
    breakfast_m = column_or_zero(d, "breakfastmealsreimbursed" if "breakfastmealsreimbursed" in d.columns else None)
    am_snack_m = column_or_zero(d, "amsnackmealsreimbursed" if "amsnackmealsreimbursed" in d.columns else None)
    lunch_m = column_or_zero(d, "lunchmealsreimbursed" if "lunchmealsreimbursed" in d.columns else None)
    pm_snack_m = column_or_zero(d, "pmsnackmealsreimbursed" if "pmsnackmealsreimbursed" in d.columns else None)
    supper_m = column_or_zero(d, "suppermealsreimbursed" if "suppermealsreimbursed" in d.columns else None)

    has_any_meal_col = any(
        c in d.columns
        for c in [
            "breakfastmealsreimbursed",
            "amsnackmealsreimbursed",
            "lunchmealsreimbursed",
            "pmsnackmealsreimbursed",
            "suppermealsreimbursed",
        ]
    )

    if has_any_meal_col:
        out["total_meals"] = breakfast_m + am_snack_m + lunch_m + pm_snack_m + supper_m
    else:
        out["total_meals"] = pd.NA

    if "totalreimbursement" in d.columns:
        out["reimbursement_amount"] = to_number(d["totalreimbursement"])
    else:
        out["reimbursement_amount"] = pd.NA

    # Denominator must be a numeric Series for the division
    denom = pd.to_numeric(out["total_meals"], errors="coerce").replace({0: pd.NA})
    out["reimbursement_per_meal"] = pd.to_numeric(out["reimbursement_amount"], errors="coerce") / denom

    out["data_quality_flags"] = out.apply(reimbursement_record_flags, axis=1)

    return out


def reimbursement_record_flags(row: pd.Series) -> str:
    flags = []
    if pd.isna(row.get("ce_id")) or str(row.get("ce_id")).strip() == "":
        flags.append("missing_ce_id")
    if pd.isna(row.get("ce_name")) or str(row.get("ce_name")).strip() == "":
        flags.append("missing_ce_name")
    if pd.isna(row.get("reimbursement_amount")):
        flags.append("missing_reimbursement_amount")
    total = row.get("total_meals")
    if pd.notna(total) and total == 0:
        flags.append("zero_total_meals")
    amt = row.get("reimbursement_amount")
    if pd.notna(amt) and amt < 0:
        flags.append("negative_reimbursement_amount")
    rpm = row.get("reimbursement_per_meal")
    if pd.notna(rpm) and rpm > 20:
        flags.append("suspicious_reimbursement_per_meal_over_20")
    return "|".join(flags) if flags else "ok"


def standardize_approved_sites(key: str, df: pd.DataFrame) -> pd.DataFrame:
    dataset_id = extract_dataset_id_from_key(key)
    meta = get_dataset_metadata(dataset_id)

    d = normalize_columns(df)

    out = pd.DataFrame(index=d.index)

    out["source_dataset"] = meta["label"]
    out["source_dataset_id"] = dataset_id
    out["approval_year"] = meta["program_year"]
    out["program_type"] = standardize_program_type(d, meta["default_program_type"])

    out["ce_id"] = d["ceid"] if "ceid" in d.columns else None
    out["ce_name"] = d["cename"] if "cename" in d.columns else None
    out["site_id"] = d["siteid"] if "siteid" in d.columns else None
    out["site_name"] = d["sitename"] if "sitename" in d.columns else None

    if "sitecounty" in d.columns:
        out["county"] = d["sitecounty"]
    elif "cecounty" in d.columns:
        out["county"] = d["cecounty"]
    else:
        out["county"] = None

    site_type_col = first_present(d, ["typeofagency", "typeoforg", "site_type", "type_of_site"])
    out["site_type"] = d[site_type_col] if site_type_col else None

    out["record_match_key"] = [
        build_match_key(ce, site, name, county)
        for ce, site, name, county in zip(
            out["ce_id"],
            out["site_id"],
            out["site_name"],
            out["county"],
        )
    ]

    out["data_quality_flags"] = "ok"
    return out


def build_clean_tables(frames: Dict[str, pd.DataFrame]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    meals = []
    reimbursements = []
    approved_sites = []

    print("\nSTEP 3: STANDARDIZE DATASETS")
    print("=" * 80)

    for key, df in frames.items():
        dataset_id = extract_dataset_id_from_key(key)
        meta = get_dataset_metadata(dataset_id)
        dtype = meta["dataset_type"]

        print(f"Standardizing {meta['label']} as {dtype}")

        if dtype == "meal_counts":
            meals.append(standardize_meal_counts(key, df))
        elif dtype == "reimbursements":
            reimbursements.append(standardize_reimbursements(key, df))
        elif dtype in ["approved_sites", "approved_ces"]:
            approved_sites.append(standardize_approved_sites(key, df))

    meals_master = pd.concat(meals, ignore_index=True) if meals else pd.DataFrame()
    reimbursements_master = pd.concat(reimbursements, ignore_index=True) if reimbursements else pd.DataFrame()
    approved_sites_master = pd.concat(approved_sites, ignore_index=True) if approved_sites else pd.DataFrame()

    meals_master.to_csv(os.path.join(DATA_CLEAN, "summer_meals_master.csv"), index=False)
    reimbursements_master.to_csv(os.path.join(DATA_CLEAN, "reimbursements_master.csv"), index=False)
    approved_sites_master.to_csv(os.path.join(DATA_CLEAN, "approved_sites_master.csv"), index=False)

    print(f"\nSaved {len(meals_master):,} reported-meal records")
    print(f"Saved {len(reimbursements_master):,} reimbursement records")
    print(f"Saved {len(approved_sites_master):,} approved site/CE records")

    return meals_master, reimbursements_master, approved_sites_master


def audit_meals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    rows = []
    grouped = df.groupby(["source_dataset", "program_year"], dropna=False)

    for (source_dataset, year), g in grouped:
        rows.append({
            "table_name": "summer_meals_master",
            "source_dataset": source_dataset,
            "year": year,
            "row_count": len(g),
            "missing_ce_id": int(g["ce_id"].isna().sum() + (g["ce_id"].astype(str).str.strip() == "").sum() - g["ce_id"].isna().sum()),
            "missing_site_id": int(g["site_id"].isna().sum() + (g["site_id"].astype(str).str.strip() == "").sum() - g["site_id"].isna().sum()),
            "missing_county": int(g["county"].isna().sum() + (g["county"].astype(str).str.strip() == "").sum() - g["county"].isna().sum()),
            "missing_total_meals": int(g["total_meals"].isna().sum()),
            "duplicate_match_keys": int(g["record_match_key"].duplicated().sum()),
            "negative_total_meals": int((pd.to_numeric(g["total_meals"], errors="coerce") < 0).sum()),
            "unknown_program_type": int((g["program_type"].astype(str).str.upper() == "UNKNOWN").sum()),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    return pd.DataFrame(rows)


def audit_reimbursements(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    rows = []
    grouped = df.groupby(["source_dataset", "program_year"], dropna=False)

    for (source_dataset, year), g in grouped:
        amt = pd.to_numeric(g["reimbursement_amount"], errors="coerce")
        meals = pd.to_numeric(g["total_meals"], errors="coerce")
        rpm = pd.to_numeric(g["reimbursement_per_meal"], errors="coerce")
        rows.append({
            "table_name": "reimbursements_master",
            "source_dataset": source_dataset,
            "year": year,
            "row_count": len(g),
            "missing_ce_id": int(g["ce_id"].isna().sum()),
            "missing_ce_name": int(g["ce_name"].isna().sum()),
            "missing_reimbursement_amount": int(amt.isna().sum()),
            "missing_total_meals": int(meals.isna().sum()),
            "zero_total_meals": int((meals == 0).sum()),
            "suspicious_reimbursement_per_meal_over_20": int((rpm > 20).sum()),
            "negative_reimbursement_amount": int((amt < 0).sum()),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    return pd.DataFrame(rows)


def build_data_quality_audit(meals, reimbursements) -> pd.DataFrame:
    print("\nSTEP 4: DATA QUALITY AUDIT")
    print("=" * 80)

    audits = [audit_meals(meals), audit_reimbursements(reimbursements)]
    audit = pd.concat([a for a in audits if not a.empty], ignore_index=True)

    outpath = os.path.join(DATA_AUDIT, "data_quality_audit.csv")
    audit.to_csv(outpath, index=False)

    print(f"Data quality audit saved to {outpath}")
    if not audit.empty:
        print(audit.to_string(index=False))

    return audit


def generate_sql() -> None:
    sql = """
DROP TABLE IF EXISTS summer_meals_master;
CREATE TABLE summer_meals_master (
    source_dataset TEXT,
    source_dataset_id TEXT,
    program_year INTEGER,
    program_type TEXT,
    ce_id TEXT,
    ce_name TEXT,
    site_id TEXT,
    site_name TEXT,
    county TEXT,
    region TEXT,
    site_type TEXT,
    service_days NUMERIC,
    breakfast_meals NUMERIC,
    lunch_meals NUMERIC,
    snack_meals NUMERIC,
    supper_meals NUMERIC,
    total_meals NUMERIC,
    covid_site_flag TEXT,
    claim_date TEXT,
    record_match_key TEXT,
    data_quality_flags TEXT
);

DROP TABLE IF EXISTS reimbursements_master;
CREATE TABLE reimbursements_master (
    source_dataset TEXT,
    source_dataset_id TEXT,
    program_year INTEGER,
    program_type TEXT,
    ce_id TEXT,
    ce_name TEXT,
    county TEXT,
    region TEXT,
    claim_date TEXT,
    total_meals NUMERIC,
    reimbursement_amount NUMERIC,
    reimbursement_per_meal NUMERIC,
    data_quality_flags TEXT
);

DROP TABLE IF EXISTS approved_sites_master;
CREATE TABLE approved_sites_master (
    source_dataset TEXT,
    source_dataset_id TEXT,
    approval_year INTEGER,
    program_type TEXT,
    ce_id TEXT,
    ce_name TEXT,
    site_id TEXT,
    site_name TEXT,
    county TEXT,
    site_type TEXT,
    record_match_key TEXT,
    data_quality_flags TEXT
);
"""

    outpath = os.path.join(SQL_DIR, "create_tables.sql")

    with open(outpath, "w", encoding="utf-8") as f:
        f.write(sql.strip() + "\n")

    print(f"\nSQL setup script saved to {outpath}")


def quick_preview(meals, reimbursements, approved_sites) -> None:
    print("\nSTEP 5: QUICK PREVIEW")
    print("=" * 80)

    if not meals.empty:
        print("\nReported meals by year and program:")
        print(
            meals.groupby(["program_year", "program_type"], dropna=False)
            .agg(
                records=("total_meals", "size"),
                total_reported_meals=("total_meals", "sum"),
                avg_meals_per_record=("total_meals", "mean"),
            )
            .reset_index()
            .to_string(index=False)
        )

    if not reimbursements.empty:
        print("\nReimbursement by year and program:")
        print(
            reimbursements.groupby(["program_year", "program_type"], dropna=False)
            .agg(
                records=("reimbursement_amount", "size"),
                total_reimbursement=("reimbursement_amount", "sum"),
                total_reported_meals=("total_meals", "sum"),
                avg_reimbursement_per_meal=("reimbursement_per_meal", "mean"),
            )
            .reset_index()
            .to_string(index=False)
        )

    if not approved_sites.empty:
        print("\nApproved sites/CE records by year and program:")
        print(
            approved_sites.groupby(["approval_year", "program_type"], dropna=False)
            .size()
            .reset_index(name="records")
            .to_string(index=False)
        )
    else:
        print("\nApproved sites/CE records: none (approved-site/CE datasets currently return 403 via Socrata API)")


def main() -> None:
    print("SSO vs SFSP Texas Capstone")
    print("=" * 80)

    frames, _failures = ingest_all()
    profile_schemas(frames)

    meals, reimbursements, approved_sites = build_clean_tables(frames)

    build_data_quality_audit(meals, reimbursements)
    generate_sql()
    quick_preview(meals, reimbursements, approved_sites)

    print("\nDONE")
    print("Next steps:")
    print("1. Review data/audit/schema_profile.csv")
    print("2. Investigate any UNKNOWN program_type rows")
    print("3. Inspect rows with data_quality_flags != 'ok'")
    print("4. Run sql/analysis_queries.sql for headline metrics")
    print("5. Build Tableau dashboards")


if __name__ == "__main__":
    main()
