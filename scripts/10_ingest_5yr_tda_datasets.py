"""
SSO vs SFSP Texas Capstone
10_ingest_5yr_tda_datasets.py

Reads config/tda_5yr_dataset_registry.json and fetches each dataset
via sodapy with paginated calls. Each dataset is fetched once over the
network and saved into data/raw_v2/{category}/{dataset_id}.csv for
EVERY category it belongs to (e.g., 24ie-9cft lands in both
summer_contacts/ and non_congregate_sources/).

Failures are logged and the rest of the pipeline continues.

Outputs:
  data/raw_v2/{category}/{dataset_id}.csv  (one file per category-membership)
  data/audit/tda_5yr_ingestion_audit.csv
  data/audit/tda_5yr_schema_profile.csv
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
from sodapy import Socrata


CONFIG_PATH = os.path.join("config", "tda_5yr_dataset_registry.json")
DATA_RAW_V2 = "data/raw_v2"
DATA_AUDIT = "data/audit"

INGEST_AUDIT_OUT = os.path.join(DATA_AUDIT, "tda_5yr_ingestion_audit.csv")
SCHEMA_PROFILE_OUT = os.path.join(DATA_AUDIT, "tda_5yr_schema_profile.csv")

for folder in [DATA_RAW_V2, DATA_AUDIT]:
    os.makedirs(folder, exist_ok=True)

CLIENT = Socrata("data.texas.gov", None)
CLIENT.timeout = 180


def clean_colname(col: str) -> str:
    col = str(col).strip().lower()
    col = re.sub(r"[^a-z0-9]+", "_", col)
    col = re.sub(r"_+", "_", col)
    return col.strip("_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d.columns = [clean_colname(c) for c in d.columns]
    return d


def fetch_dataset(dataset_id: str, label: str, page_size: int = 50000):
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
        msg = f"{type(exc).__name__}: {exc}"
        print(f"FAILED ({msg})")
        return None, msg
    if not pages:
        print("OK: 0 rows")
        return pd.DataFrame(), None
    df = pd.concat(pages, ignore_index=True)
    print(f"OK: {len(df):,} rows, {len(df.columns)} columns")
    return df, None


def main() -> None:
    print("SSO vs SFSP Texas Capstone - v2 ingest")
    print("=" * 80)

    if not os.path.exists(CONFIG_PATH):
        print(f"ERROR: {CONFIG_PATH} not found. Run scripts/09 first.")
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        registry = json.load(f)
    entries: List[dict] = registry["datasets"]
    print(f"Loaded registry with {len(entries)} entries")

    # Group entries by dataset_id so we fetch each network resource once
    by_id: Dict[str, List[dict]] = defaultdict(list)
    for e in entries:
        by_id[e["dataset_id"]].append(e)

    print(f"Unique dataset IDs to fetch: {len(by_id)}\n")

    audit_rows = []
    schema_rows = []

    for dsid in sorted(by_id.keys()):
        entries_for_id = by_id[dsid]
        # Use the first entry's label for the fetch print
        df, err = fetch_dataset(dsid, entries_for_id[0]["label"])

        for entry in entries_for_id:
            cat = entry["category"]
            cat_dir = os.path.join(DATA_RAW_V2, cat)
            os.makedirs(cat_dir, exist_ok=True)
            raw_path = os.path.join(cat_dir, f"{dsid}.csv")

            if err is not None or df is None:
                audit_rows.append({
                    "dataset_id": dsid,
                    "label": entry["label"],
                    "category": cat,
                    "period": entry.get("period"),
                    "canonical_year": entry.get("canonical_year"),
                    "row_count": 0,
                    "column_count": 0,
                    "fetch_status": "failed",
                    "error_message": err,
                    "raw_path": "",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                })
                continue

            df.to_csv(raw_path, index=False)
            print(f"  saved -> {raw_path}")
            audit_rows.append({
                "dataset_id": dsid,
                "label": entry["label"],
                "category": cat,
                "period": entry.get("period"),
                "canonical_year": entry.get("canonical_year"),
                "row_count": len(df),
                "column_count": len(df.columns),
                "fetch_status": "ok" if len(df) > 0 else "empty",
                "error_message": None,
                "raw_path": raw_path,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })

            # Schema profile per (category, dataset, column)
            d_norm = normalize_columns(df)
            for col in d_norm.columns:
                non_null = d_norm[col].dropna()
                sample = non_null.iloc[0] if len(non_null) else None
                schema_rows.append({
                    "dataset_id": dsid,
                    "label": entry["label"],
                    "category": cat,
                    "column_name": col,
                    "sample_value": sample,
                    "null_pct": round(d_norm[col].isna().mean() * 100, 2),
                    "inferred_dtype": str(d_norm[col].dtype),
                })

    audit_df = pd.DataFrame(audit_rows)
    schema_df = pd.DataFrame(schema_rows)
    audit_df.to_csv(INGEST_AUDIT_OUT, index=False)
    schema_df.to_csv(SCHEMA_PROFILE_OUT, index=False)

    print(f"\nWrote {INGEST_AUDIT_OUT}  ({len(audit_df):,} rows)")
    print(f"Wrote {SCHEMA_PROFILE_OUT}  ({len(schema_df):,} rows)")

    # Headline summary
    ok = (audit_df["fetch_status"] == "ok").sum()
    failed = (audit_df["fetch_status"] == "failed").sum()
    empty = (audit_df["fetch_status"] == "empty").sum()
    print(f"\nFetch summary: ok={ok}  failed={failed}  empty={empty}")

    by_cat = audit_df[audit_df["fetch_status"] == "ok"].groupby("category")["row_count"].sum()
    print("Rows fetched per category:")
    for cat, rows in by_cat.items():
        print(f"  {cat:28s} : {int(rows):,}")

    if failed:
        print("\nFailures:")
        for _, r in audit_df[audit_df["fetch_status"] == "failed"].iterrows():
            print(f"  {r['dataset_id']:12s} ({r['category']:22s}) -> {r['error_message']}")


if __name__ == "__main__":
    main()
