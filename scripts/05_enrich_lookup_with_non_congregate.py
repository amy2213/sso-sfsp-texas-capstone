"""
SSO vs SFSP Texas Capstone
05_enrich_lookup_with_non_congregate.py

Enrich ce_site_search_master.csv with verified public-source meal
service type and rural/urban indicator fields from TX Open Data
8ih4-zp65 (SFSP contacts dataset, program year 2022-2023).

Behavior:
- Matched (ce_id, site_id) rows have non_congregate_status overwritten
  with the verified value from mealservicetype (or "Congregate" /
  "Unknown" per the spec) and non_congregate_source set to the
  public-source label.
- Unmatched rows are left as-is (non_congregate_status stays "Unknown",
  non_congregate_source stays "Not available in public source").
- Per-meal *_meal_service_method values are NOT non-congregate flags;
  they describe production / sourcing model. They are added as separate
  columns plus a readable meal_service_methods_summary.

Outputs:
  data/lookup/ce_site_search_master_enriched.csv
  data/audit/non_congregate_enrichment_audit.csv

This script does NOT replace ce_site_search_master.csv — it writes a
separate "_enriched" file. Whether to swap it in for the Streamlit app
is a downstream decision.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

import pandas as pd


DATA_LOOKUP = "data/lookup"
DATA_RAW_NC = "data/raw/non_congregate"
DATA_AUDIT = "data/audit"

SEARCH_MASTER = os.path.join(DATA_LOOKUP, "ce_site_search_master.csv")
NC_SOURCE = os.path.join(DATA_RAW_NC, "8ih4-zp65.csv")

ENRICHED_OUT = os.path.join(DATA_LOOKUP, "ce_site_search_master_enriched.csv")
AUDIT_OUT = os.path.join(DATA_AUDIT, "non_congregate_enrichment_audit.csv")

NC_SOURCE_LABEL = "public-source meal service type (TX Open Data 8ih4-zp65, SFSP 2022-2023)"
RU_SOURCE_LABEL = "public-source rural/urban indicator (TX Open Data 8ih4-zp65, SFSP 2022-2023)"
UNKNOWN_NC_SOURCE = "Not available in public source"

for folder in [DATA_LOOKUP, DATA_AUDIT]:
    os.makedirs(folder, exist_ok=True)


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


def first_non_null(series: pd.Series):
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    return s.iloc[0] if len(s) else pd.NA


def normalize_text(value):
    """Strip whitespace, collapse internal whitespace runs, return NA
    for empty strings. Preserve legitimate source characters (we do
    not aggressively rewrite non-ASCII)."""
    if pd.isna(value):
        return value
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s if s else pd.NA


def is_blank(value) -> bool:
    if pd.isna(value):
        return True
    s = str(value).strip()
    return s == "" or s.lower() in {"nan", "none", "<na>"}


# Short labels used only for the meal_service_methods_summary string.
# The full source values are preserved in their individual columns.
METHOD_SHORT_LABELS = {
    "Self-Prep - Prepares on site": "Self-Prep on site",
    "Self-Prep - Receives meals (Central Kitchen)": "Self-Prep from Central Kitchen",
    "Vended by Food Service Management Company (FSMC)": "Vended by FSMC",
    "Vended by another SFSP Contracting Entity": "Vended by another SFSP CE",
}


def short_method(value) -> Optional[str]:
    if pd.isna(value):
        return None
    s = normalize_text(value)
    if not s:
        return None
    return METHOD_SHORT_LABELS.get(s, s)


# --------------------------------------------------------------------
# Build the NC enrichment table (one row per ce_id, site_id)
# --------------------------------------------------------------------

NC_RENAME_MAP = {
    "mealservicetype": "meal_service_type_public",
    "ruralorurbancode": "rural_urban_status",
    "sitetype": "sfsp_site_type_public",
    "breakfastmealservicemethod": "breakfast_meal_service_method",
    "lunchmealservicemethod": "lunch_meal_service_method",
    "suppermealservicemethod": "supper_meal_service_method",
    "amsnackmealservicemethod": "am_snack_meal_service_method",
    "pmsnackmealservicemethod": "pm_snack_meal_service_method",
}


def derive_verified_status(value) -> str:
    """Spec:
      - If meal_service_type_public contains "Non-Congregate",
        return the exact value (preserves grab-and-go vs mobile-route).
      - Else if it contains "Congregate" (and not "Non-Congregate"),
        return "Congregate".
      - Otherwise "Unknown"."""
    if pd.isna(value):
        return "Unknown"
    s = str(value)
    if "Non-Congregate" in s:
        return s
    if "Congregate" in s:
        return "Congregate"
    return "Unknown"


def build_nc_enrichment(raw: pd.DataFrame) -> pd.DataFrame:
    d = normalize_columns(raw)
    d["ce_id"] = to_id_str(d["ceid"])
    d["site_id"] = to_id_str(d["siteid"])

    # Rename + normalize-text the source columns
    for src, tgt in NC_RENAME_MAP.items():
        if src in d.columns:
            d[tgt] = d[src].apply(normalize_text)
        else:
            d[tgt] = pd.NA

    keep = ["ce_id", "site_id"]
    if "programyear" in d.columns:
        keep.append("programyear")
    keep.extend(NC_RENAME_MAP.values())
    sub = d[keep].copy()

    # Deduplicate to one row per (ce_id, site_id) — same site shouldn't
    # appear twice in one program year, but be defensive.
    agg = {c: (c, first_non_null) for c in sub.columns if c not in {"ce_id", "site_id"}}
    out = sub.groupby(["ce_id", "site_id"], dropna=False).agg(**agg).reset_index()

    out["non_congregate_status_verified"] = out["meal_service_type_public"].apply(derive_verified_status)
    out["rural_urban_source"] = out["rural_urban_status"].apply(
        lambda v: RU_SOURCE_LABEL if not is_blank(v) else pd.NA
    )

    # Readable per-meal summary
    def make_method_summary(row):
        bits = []
        for label, col in [
            ("Breakfast", "breakfast_meal_service_method"),
            ("Lunch", "lunch_meal_service_method"),
            ("Supper", "supper_meal_service_method"),
            ("AM snack", "am_snack_meal_service_method"),
            ("PM snack", "pm_snack_meal_service_method"),
        ]:
            v = short_method(row.get(col))
            if v:
                bits.append(f"{label}: {v}")
        return " | ".join(bits) if bits else pd.NA

    out["meal_service_methods_summary"] = out.apply(make_method_summary, axis=1)
    return out


# --------------------------------------------------------------------
# Data-quality flag manipulation
# --------------------------------------------------------------------

def update_flag_string(existing: str, ensure_present: set, ensure_absent: set) -> str:
    flags = []
    if not is_blank(existing):
        for token in re.split(r"[|,]", str(existing)):
            t = token.strip()
            if t and t.lower() != "ok":
                flags.append(t)
    flags = [f for f in flags if f not in ensure_absent]
    for f in ensure_present:
        if f not in flags:
            flags.append(f)
    return "|".join(flags) if flags else "ok"


# --------------------------------------------------------------------
# Enrich the search master
# --------------------------------------------------------------------

def enrich_search_master(master: pd.DataFrame, nc: pd.DataFrame) -> pd.DataFrame:
    out = master.copy()
    out["ce_id"] = to_id_str(out["ce_id"])
    out["site_id"] = to_id_str(out["site_id"])

    if "non_congregate_status" not in out.columns:
        out["non_congregate_status"] = "Unknown"
    if "non_congregate_source" not in out.columns:
        out["non_congregate_source"] = UNKNOWN_NC_SOURCE
    if "data_quality_flags" not in out.columns:
        out["data_quality_flags"] = "ok"

    nc_cols = [
        "ce_id", "site_id",
        "meal_service_type_public", "rural_urban_status", "rural_urban_source",
        "sfsp_site_type_public",
        "breakfast_meal_service_method", "lunch_meal_service_method",
        "supper_meal_service_method", "am_snack_meal_service_method",
        "pm_snack_meal_service_method",
        "meal_service_methods_summary",
        "non_congregate_status_verified",
    ]
    nc_for_join = nc[[c for c in nc_cols if c in nc.columns]]

    out = out.merge(nc_for_join, on=["ce_id", "site_id"], how="left", indicator="_nc_merge")

    matched_mask = out["_nc_merge"] == "both"

    # Matched: overwrite NC status + source from public source.
    out.loc[matched_mask, "non_congregate_status"] = out.loc[matched_mask, "non_congregate_status_verified"]
    out.loc[matched_mask, "non_congregate_source"] = NC_SOURCE_LABEL

    # Unmatched: keep existing; fill blanks with Unknown / Not available.
    blank_status = out["non_congregate_status"].apply(is_blank)
    out.loc[blank_status & ~matched_mask, "non_congregate_status"] = "Unknown"
    blank_src = out["non_congregate_source"].apply(is_blank)
    out.loc[blank_src & ~matched_mask, "non_congregate_source"] = UNKNOWN_NC_SOURCE

    # Update data-quality flags row-by-row
    def update_row_flags(row):
        present, absent = set(), set()
        status = str(row.get("non_congregate_status", "")).strip()
        if status == "Unknown":
            present.add("non_congregate_unknown")
        else:
            absent.add("non_congregate_unknown")
        if is_blank(row.get("rural_urban_status")):
            present.add("rural_urban_unknown")
        else:
            absent.add("rural_urban_unknown")
        return update_flag_string(row.get("data_quality_flags", ""), present, absent)

    out["data_quality_flags"] = out.apply(update_row_flags, axis=1)

    out = out.drop(columns=[c for c in ["_nc_merge", "non_congregate_status_verified"] if c in out.columns])
    return out


# --------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------

def build_audit(nc_raw_normalized: pd.DataFrame, nc: pd.DataFrame,
                master_rows: int, enriched: pd.DataFrame) -> pd.DataFrame:
    nc_keys = set(zip(nc["ce_id"].astype(str), nc["site_id"].astype(str)))
    enriched_keys = list(zip(enriched["ce_id"].astype(str), enriched["site_id"].astype(str)))
    matched = sum(1 for k in enriched_keys if k in nc_keys)
    unmatched = len(enriched_keys) - matched

    statuses = enriched["non_congregate_status"].fillna("Unknown").astype(str)
    grab_go = int(statuses.str.contains("Grab-and-go", na=False).sum())
    mobile = int(statuses.str.contains("Mobile route", na=False).sum())
    nc_total = int(statuses.str.contains("Non-Congregate", na=False).sum())
    congregate = int((statuses.str.strip() == "Congregate").sum())
    unknown_after = int((statuses.str.strip() == "Unknown").sum())

    if "rural_urban_status" in enriched.columns:
        ru = enriched["rural_urban_status"].fillna("").astype(str).str.strip()
        rural = int((ru == "Rural").sum())
        urban = int((ru == "Urban").sum())
    else:
        rural = urban = 0

    row = {
        "source_rows": len(nc_raw_normalized),
        "source_distinct_ce_id": int(nc_raw_normalized["ce_id"].dropna().nunique()),
        "source_distinct_site_id": int(nc_raw_normalized["site_id"].dropna().nunique()),
        "search_master_rows": master_rows,
        "matched_rows": matched,
        "unmatched_rows": unmatched,
        "matched_pct": round(matched / master_rows * 100, 2) if master_rows else 0.0,
        "congregate_count": congregate,
        "non_congregate_grab_go_count": grab_go,
        "non_congregate_mobile_route_count": mobile,
        "total_non_congregate_count": nc_total,
        "rural_count": rural,
        "urban_count": urban,
        "unknown_nc_count_after_enrichment": unknown_after,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    return pd.DataFrame([row])


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main() -> None:
    print("SSO vs SFSP Texas Capstone - NC enrichment")
    print("=" * 80)

    if not os.path.exists(SEARCH_MASTER):
        print(f"ERROR: {SEARCH_MASTER} not found. Run scripts/03 first.")
        return
    if not os.path.exists(NC_SOURCE):
        print(f"ERROR: {NC_SOURCE} not found. Run scripts/04 first.")
        return

    print(f"\nLoading {SEARCH_MASTER} ...")
    master = pd.read_csv(SEARCH_MASTER, dtype={"ce_id": str, "site_id": str})
    print(f"  {len(master):,} rows, {len(master.columns)} columns")

    print(f"\nLoading {NC_SOURCE} ...")
    nc_raw = pd.read_csv(NC_SOURCE, dtype={"ceid": str, "siteid": str})
    print(f"  {len(nc_raw):,} rows, {len(nc_raw.columns)} columns")

    nc = build_nc_enrichment(nc_raw)
    print(f"\nBuilt NC enrichment table: {len(nc):,} unique (ce_id, site_id)")

    nc_raw_normalized = normalize_columns(nc_raw)
    nc_raw_normalized["ce_id"] = to_id_str(nc_raw_normalized["ceid"])
    nc_raw_normalized["site_id"] = to_id_str(nc_raw_normalized["siteid"])

    enriched = enrich_search_master(master, nc)
    audit = build_audit(nc_raw_normalized, nc, len(master), enriched)

    enriched.to_csv(ENRICHED_OUT, index=False)
    audit.to_csv(AUDIT_OUT, index=False)

    print("\nOutputs:")
    print(f"  {ENRICHED_OUT}  ({len(enriched):,} rows, {len(enriched.columns)} columns)")
    print(f"  {AUDIT_OUT}")

    print("\nAudit:")
    print(audit.to_string(index=False))

    print("\nCounts by non_congregate_status:")
    print(enriched["non_congregate_status"].fillna("(missing)").value_counts(dropna=False).to_string())

    if "rural_urban_status" in enriched.columns:
        print("\nCounts by rural_urban_status:")
        print(enriched["rural_urban_status"].fillna("(none)").value_counts(dropna=False).to_string())

    print("\nDONE")


if __name__ == "__main__":
    main()
