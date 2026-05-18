"""
SSO vs SFSP Texas Capstone
08_catalog_discover_meal_service_type_years.py

Catalog discovery for Texas Open Data datasets that may carry
MealServiceType / non-congregate / rural-urban fields across years
beyond 2022-2023 (which is what the three known datasets cover).

Strategy:
1. Hit the public Socrata Discovery API (catalog) with the user-given
   query terms, restricted to domain data.texas.gov.
2. Dedupe candidate dataset IDs and record which query terms hit them.
3. Probe each candidate with a small limit=5 sample to look for the
   target columns.
4. For any candidate that carries `mealservicetype`, do a full
   paginated fetch and save the raw CSV.
5. Emit four audit CSVs.
6. Print a comparison vs the known MST sources (8ih4-zp65, 24ie-9cft,
   82b8-iuvu) and a recommendation for whether to extend script 07.

Does NOT modify scripts 01-07 or app.py. Does NOT overwrite any
existing lookup file.
"""

from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional

import pandas as pd
import requests
from sodapy import Socrata


DOMAIN = "data.texas.gov"
DISCOVERY_URL = "https://api.us.socrata.com/api/catalog/v1"

DATA_RAW = "data/raw/meal_service_type_year_discovery"
DATA_AUDIT = "data/audit"

CANDIDATES_OUT = os.path.join(DATA_AUDIT, "catalog_meal_service_type_candidates.csv")
SCHEMA_OUT = os.path.join(DATA_AUDIT, "catalog_meal_service_type_schema_profile.csv")
VC_OUT = os.path.join(DATA_AUDIT, "catalog_meal_service_type_value_counts.csv")
YC_OUT = os.path.join(DATA_AUDIT, "catalog_meal_service_type_year_coverage.csv")

for folder in [DATA_RAW, DATA_AUDIT]:
    os.makedirs(folder, exist_ok=True)

CLIENT = Socrata(DOMAIN, None)
CLIENT.timeout = 180

KNOWN_NC_DATASETS = {"8ih4-zp65", "24ie-9cft", "82b8-iuvu"}

QUERY_TERMS = [
    "MealServiceType",
    '"Meal Service Type"',
    "SFSPCONTACTS",
    "SSOCONTACTS",
    '"Summer Sites"',
    '"All Summer Sites"',
    '"Contact and Program Participation"',
    '"Summer Meal Programs"',
    '"2023-2024"',
    '"2024-2025"',
    '"2025-2026"',
    '"non-congregate"',
    '"rural"',
]

TARGET_COLS = [
    "ceid", "siteid", "programyear", "reporttype", "program",
    "mealservicetype", "ruralorurbancode", "sitetype", "mealtypesserved",
    "operationstartdate", "operationenddate",
    "breakfasttime", "lunchtime", "suppertime", "amsnacktime", "pmsnacktime",
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


def discover_query(query: str, max_results: int = 300) -> List[dict]:
    """Page the Socrata Discovery API for one query term."""
    results: List[dict] = []
    offset = 0
    page_size = 100
    while len(results) < max_results:
        params = {
            "q": query,
            "domains": DOMAIN,
            "limit": min(page_size, max_results - len(results)),
            "offset": offset,
        }
        try:
            r = requests.get(DISCOVERY_URL, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            print(f"    discovery {query!r} failed: {exc}")
            return results
        page = data.get("results", [])
        if not page:
            break
        results.extend(page)
        offset += len(page)
        if len(page) < page_size:
            break
    return results


def fetch_sample(dataset_id: str, limit: int = 5):
    try:
        return pd.DataFrame.from_records(CLIENT.get(dataset_id, limit=limit)), None
    except Exception as exc:
        return pd.DataFrame(), f"{type(exc).__name__}: {exc}"


def fetch_full(dataset_id: str, page_size: int = 50000) -> pd.DataFrame:
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
        print(f"  FULL fetch {dataset_id} failed: {exc}")
        return pd.DataFrame()
    if not pages:
        return pd.DataFrame()
    return pd.concat(pages, ignore_index=True)


# --------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------

def collect_candidates() -> Dict[str, dict]:
    print("\nSTEP 1: CATALOG QUERIES")
    print("=" * 80)
    candidates: Dict[str, dict] = {}
    for q in QUERY_TERMS:
        print(f"\nQuery: {q}")
        page = discover_query(q)
        print(f"  -> {len(page)} hits")
        for item in page:
            res = item.get("resource", {}) or {}
            ds_id = res.get("id")
            if not ds_id:
                continue
            if ds_id not in candidates:
                candidates[ds_id] = {
                    "dataset_id": ds_id,
                    "title": res.get("name"),
                    "description": (res.get("description") or "")[:500],
                    "created_at": res.get("createdAt"),
                    "updated_at": res.get("updatedAt"),
                    "rows_updated_at": res.get("rows_updated_at"),
                    "permalink": item.get("permalink") or item.get("link"),
                    "matched_query_terms": set(),
                }
            candidates[ds_id]["matched_query_terms"].add(q)
        time.sleep(0.3)  # be polite to the catalog API
    return candidates


def probe_candidates(candidates: Dict[str, dict]) -> Dict[str, dict]:
    print("\nSTEP 2: PROBE CANDIDATES (limit=5 sample + target-column check)")
    print("=" * 80)
    for ds_id in sorted(candidates.keys()):
        c = candidates[ds_id]
        df, err = fetch_sample(ds_id)
        if df.empty:
            c["had_sample_fetch"] = False
            c["sample_fetch_error"] = err or "empty"
            c["columns_present"] = []
            c["has_mealservicetype"] = False
            c["has_ruralorurbancode"] = False
            c["has_sitetype"] = False
            print(f"  {ds_id} SAMPLE FAILED: {c['sample_fetch_error']}")
            continue
        d = normalize_columns(df)
        present = [col for col in TARGET_COLS if col in d.columns]
        c["had_sample_fetch"] = True
        c["sample_fetch_error"] = None
        c["columns_present"] = present
        c["has_mealservicetype"] = "mealservicetype" in present
        c["has_ruralorurbancode"] = "ruralorurbancode" in present
        c["has_sitetype"] = "sitetype" in present
        marker = " [MST]" if c["has_mealservicetype"] else ""
        ru = " [RU]" if c["has_ruralorurbancode"] else ""
        print(f"  {ds_id} OK: {len(d.columns)} cols, target-cols={len(present)}{marker}{ru}  {c['title']}")
    return candidates


def fetch_full_for_mst(candidates: Dict[str, dict]) -> Dict[str, pd.DataFrame]:
    print("\nSTEP 3: FULL FETCH for MealServiceType-bearing candidates")
    print("=" * 80)
    frames: Dict[str, pd.DataFrame] = {}
    mst_ids = [i for i, c in candidates.items() if c.get("has_mealservicetype")]
    if not mst_ids:
        print("  no MST-bearing candidates found")
        return frames
    print(f"  {len(mst_ids)} MST-bearing candidates to fetch in full")
    for ds_id in sorted(mst_ids):
        c = candidates[ds_id]
        print(f"\n  Full fetch {ds_id}: {c['title']}", flush=True)
        df = fetch_full(ds_id)
        if df.empty:
            print("    (empty)")
            continue
        out_path = os.path.join(DATA_RAW, f"{ds_id}.csv")
        df.to_csv(out_path, index=False)
        print(f"    saved -> {out_path}  ({len(df):,} rows, {len(df.columns)} cols)")
        frames[ds_id] = df
    return frames


def write_candidates_csv(candidates: Dict[str, dict]) -> pd.DataFrame:
    rows = []
    for ds_id, c in candidates.items():
        rows.append({
            "dataset_id": ds_id,
            "title": c.get("title"),
            "description": c.get("description"),
            "created_at": c.get("created_at"),
            "updated_at": c.get("updated_at"),
            "rows_updated_at": c.get("rows_updated_at"),
            "permalink": c.get("permalink"),
            "matched_query_terms": ", ".join(sorted(c.get("matched_query_terms", []))),
            "had_sample_fetch": c.get("had_sample_fetch", False),
            "sample_fetch_error": c.get("sample_fetch_error"),
            "columns_present": ", ".join(c.get("columns_present", [])),
            "has_mealservicetype": c.get("has_mealservicetype", False),
            "has_ruralorurbancode": c.get("has_ruralorurbancode", False),
            "has_sitetype": c.get("has_sitetype", False),
            "already_known_nc_source": ds_id in KNOWN_NC_DATASETS,
        })
    df = pd.DataFrame(rows).sort_values(
        ["has_mealservicetype", "already_known_nc_source", "dataset_id"],
        ascending=[False, True, True],
    )
    df.to_csv(CANDIDATES_OUT, index=False)
    print(f"  saved -> {CANDIDATES_OUT}  ({len(df):,} candidates)")
    return df


def write_schema_profile(mst_frames: Dict[str, pd.DataFrame]) -> None:
    rows = []
    for ds_id, df in mst_frames.items():
        d = normalize_columns(df)
        for col in d.columns:
            non_null = d[col].dropna()
            sample = non_null.iloc[0] if len(non_null) else None
            rows.append({
                "dataset_id": ds_id,
                "column_name": col,
                "sample_value": sample,
                "null_pct": round(d[col].isna().mean() * 100, 2),
            })
    df = pd.DataFrame(rows)
    df.to_csv(SCHEMA_OUT, index=False)
    print(f"  saved -> {SCHEMA_OUT}  ({len(df):,} rows)")


def write_value_counts(mst_frames: Dict[str, pd.DataFrame]) -> None:
    rows = []
    for ds_id, df in mst_frames.items():
        d = normalize_columns(df)
        for col in ("mealservicetype", "ruralorurbancode", "sitetype",
                    "reporttype", "program", "programyear"):
            if col not in d.columns:
                continue
            vc = d[col].fillna("<<NULL>>").astype(str).value_counts(dropna=False)
            for val, cnt in vc.items():
                rows.append({
                    "dataset_id": ds_id,
                    "column_name": col,
                    "value": val,
                    "record_count": int(cnt),
                })
    df = pd.DataFrame(rows)
    df.to_csv(VC_OUT, index=False)
    print(f"  saved -> {VC_OUT}  ({len(df):,} rows)")


def write_year_coverage(candidates: Dict[str, dict],
                        mst_frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for ds_id, df in mst_frames.items():
        d = normalize_columns(df)
        c = candidates[ds_id]
        prog_years = sorted(d["programyear"].dropna().astype(str).unique().tolist()) if "programyear" in d.columns else []
        rep_types = sorted(d["reporttype"].dropna().astype(str).unique().tolist()) if "reporttype" in d.columns else []
        prog_vals = sorted(d["program"].dropna().astype(str).unique().tolist()) if "program" in d.columns else []
        mst_vc = ""
        if "mealservicetype" in d.columns:
            vc = d["mealservicetype"].fillna("<<NULL>>").astype(str).value_counts(dropna=False)
            mst_vc = " | ".join(f"{val}={cnt}" for val, cnt in vc.items())
        earliest_op = ""
        latest_op = ""
        if "operationstartdate" in d.columns:
            non_null = d["operationstartdate"].dropna()
            earliest_op = str(non_null.min()) if len(non_null) else ""
        if "operationenddate" in d.columns:
            non_null = d["operationenddate"].dropna()
            latest_op = str(non_null.max()) if len(non_null) else ""
        rows.append({
            "dataset_id": ds_id,
            "title": c.get("title"),
            "row_count": len(d),
            "distinct_programyear_values": ", ".join(prog_years),
            "reporttype_values": ", ".join(rep_types),
            "program_values": ", ".join(prog_vals),
            "has_mealservicetype": "mealservicetype" in d.columns,
            "has_ruralorurbancode": "ruralorurbancode" in d.columns,
            "has_sitetype": "sitetype" in d.columns,
            "mealservicetype_value_counts": mst_vc,
            "earliest_operation_start_date": earliest_op,
            "latest_operation_end_date": latest_op,
            "already_known": ds_id in KNOWN_NC_DATASETS,
        })
    df = pd.DataFrame(rows).sort_values(["distinct_programyear_values", "dataset_id"])
    df.to_csv(YC_OUT, index=False)
    print(f"  saved -> {YC_OUT}  ({len(df):,} rows)")
    return df


def print_recommendation(year_coverage_df: pd.DataFrame) -> None:
    print("\nSTEP 5: SUMMARY / RECOMMENDATION")
    print("=" * 80)
    if year_coverage_df.empty:
        print("No MealServiceType-bearing datasets discovered via catalog.")
        return

    print("\nDataset → program-year coverage (MST-bearing only):")
    for _, row in year_coverage_df.iterrows():
        years = row["distinct_programyear_values"] or "(none)"
        flag = "KNOWN " if row["already_known"] else "NEW   "
        ru = " [+RU]" if row["has_ruralorurbancode"] else ""
        print(f"  {flag} {row['dataset_id']:12s} {years:25s}  {row['title']}{ru}")

    new_df = year_coverage_df[~year_coverage_df["already_known"]]
    if new_df.empty:
        print("\nNo NEW MST-bearing datasets beyond the three already known "
              "(8ih4-zp65, 24ie-9cft, 82b8-iuvu).")
        print("Recommendation: scripts/07 is already the maximal NC enrichment for "
              "publicly available data.")
    else:
        years_set = set()
        for v in new_df["distinct_programyear_values"]:
            for y in str(v).split(","):
                y = y.strip()
                if y:
                    years_set.add(y)
        print(f"\nNEW MST-bearing datasets: {len(new_df)} ({', '.join(new_df['dataset_id'].tolist())})")
        print(f"Additional program-year coverage: {', '.join(sorted(years_set))}")
        print("Recommendation: extend script 07 (or build script 09) to ingest these "
              "additional sources in the same way (rename to target schema, dedupe by "
              "(ce_id, site_id, program_year), preserve source attribution).")


def main() -> None:
    print("SSO vs SFSP Texas Capstone - Catalog discovery (MealServiceType across years)")
    print("=" * 80)
    candidates = collect_candidates()
    print(f"\nTotal unique candidate datasets: {len(candidates)}")

    candidates = probe_candidates(candidates)
    mst_frames = fetch_full_for_mst(candidates)

    print("\nSTEP 4: BUILD AUDIT OUTPUTS")
    print("=" * 80)
    write_candidates_csv(candidates)
    write_schema_profile(mst_frames)
    write_value_counts(mst_frames)
    yc_df = write_year_coverage(candidates, mst_frames)

    print_recommendation(yc_df)
    print("\nDONE")


if __name__ == "__main__":
    main()
