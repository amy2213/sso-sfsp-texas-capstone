"""
SSO vs SFSP Texas Capstone
07_enrich_lookup_with_all_public_non_congregate.py

Enrich ce_site_search_master.csv with verified public-source meal
service type / rural-urban / production-method fields from the
combined Texas Open Data SFSP 2022-2023 contact datasets:

  8ih4-zp65 + 24ie-9cft + 82b8-iuvu

Source = data/lookup/non_congregate_public_source_master.csv
(long-form, one row per source_dataset_id x ce_id x site_id x year).

This script:
- Deduplicates the combined source to one row per (ce_id, site_id),
  preserving source attribution as comma-separated lists.
- Left-joins onto the search master (no row drops).
- Overwrites non_congregate_status / non_congregate_source for matched
  rows; leaves unmatched rows as "Unknown" / "Not available in public
  source".
- Updates data_quality_flags consistently.

Outputs:
  data/lookup/ce_site_search_master_enriched_all_nc.csv
  data/audit/all_non_congregate_enrichment_audit.csv

This script does NOT modify scripts 01-06 or app.py.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Optional

import pandas as pd


DATA_LOOKUP = "data/lookup"
DATA_AUDIT = "data/audit"

SEARCH_MASTER = os.path.join(DATA_LOOKUP, "ce_site_search_master.csv")
COMBINED_NC = os.path.join(DATA_LOOKUP, "non_congregate_public_source_master.csv")

ENRICHED_OUT = os.path.join(DATA_LOOKUP, "ce_site_search_master_enriched_all_nc.csv")
AUDIT_OUT = os.path.join(DATA_AUDIT, "all_non_congregate_enrichment_audit.csv")

NC_SOURCE_LABEL = (
    "public-source meal service type "
    "(TX Open Data 8ih4-zp65, 24ie-9cft, 82b8-iuvu, SFSP 2022-2023)"
)
RU_SOURCE_LABEL = (
    "public-source rural/urban indicator "
    "(TX Open Data 8ih4-zp65, SFSP 2022-2023)"
)
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


def is_blank(value) -> bool:
    if pd.isna(value):
        return True
    s = str(value).strip()
    return s == "" or s.lower() in {"nan", "none", "<na>"}


def normalize_text(value):
    if pd.isna(value):
        return value
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s if s else pd.NA


def first_non_null(series: pd.Series):
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    return s.iloc[0] if len(s) else pd.NA


def unique_joined(series: pd.Series, sep: str = ",") -> Optional[str]:
    """Sorted, deduplicated, comma-joined string across non-null values."""
    vals = set()
    for v in series.dropna():
        s = str(v).strip()
        if s and s.lower() not in {"nan", "none", "<na>"}:
            vals.add(s)
    return sep.join(sorted(vals)) if vals else pd.NA


def fix_replacement_char(value):
    """Replace U+FFFD with an em-dash for display stability. Leaves
    legitimate non-ASCII characters (e.g. U+2013 en-dash) alone."""
    if pd.isna(value):
        return value
    return str(value).replace("�", "—")


# Short labels used only for the meal_service_methods_summary string.
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
# Build deduped NC enrichment table
# --------------------------------------------------------------------

# Columns in the combined long-form master -> target name after dedup
RENAME_FOR_TARGET = {
    "meal_types_served": "meal_types_served_public",
    "breakfast_time": "breakfast_time_public",
    "lunch_time": "lunch_time_public",
    "supper_time": "supper_time_public",
    "am_snack_time": "am_snack_time_public",
    "pm_snack_time": "pm_snack_time_public",
}


def build_deduped_nc(combined: pd.DataFrame) -> pd.DataFrame:
    d = normalize_columns(combined)
    d["ce_id"] = to_id_str(d["ce_id"])
    d["site_id"] = to_id_str(d["site_id"])

    # Rename time / meal_types columns to the "_public" target names
    for src, tgt in RENAME_FOR_TARGET.items():
        if src in d.columns:
            d[tgt] = d[src]

    # Apply whitespace + replacement-char cleanup to text fields
    text_cols_to_clean = [
        "meal_service_type_public", "rural_urban_status", "sfsp_site_type_public",
        "meal_types_served_public",
        "breakfast_time_public", "lunch_time_public", "supper_time_public",
        "am_snack_time_public", "pm_snack_time_public",
        "breakfast_meal_service_method", "lunch_meal_service_method",
        "supper_meal_service_method", "am_snack_meal_service_method",
        "pm_snack_meal_service_method",
    ]
    for c in text_cols_to_clean:
        if c in d.columns:
            d[c] = d[c].apply(normalize_text).apply(fix_replacement_char)

    grp = d.groupby(["ce_id", "site_id"], dropna=False)

    agg_kwargs = {
        "source_dataset_ids": ("source_dataset_id", unique_joined),
        "source_labels": ("source_label", unique_joined),
        "program_years_verified": ("program_year", unique_joined),
        "meal_service_type_public": ("meal_service_type_public", first_non_null),
        "rural_urban_status": ("rural_urban_status", first_non_null),
        "sfsp_site_type_public": ("sfsp_site_type_public", first_non_null),
        "meal_types_served_public": ("meal_types_served_public", first_non_null),
        "breakfast_time_public": ("breakfast_time_public", first_non_null),
        "lunch_time_public": ("lunch_time_public", first_non_null),
        "supper_time_public": ("supper_time_public", first_non_null),
        "am_snack_time_public": ("am_snack_time_public", first_non_null),
        "pm_snack_time_public": ("pm_snack_time_public", first_non_null),
        "breakfast_meal_service_method": ("breakfast_meal_service_method", first_non_null),
        "lunch_meal_service_method": ("lunch_meal_service_method", first_non_null),
        "supper_meal_service_method": ("supper_meal_service_method", first_non_null),
        "am_snack_meal_service_method": ("am_snack_meal_service_method", first_non_null),
        "pm_snack_meal_service_method": ("pm_snack_meal_service_method", first_non_null),
    }
    out = grp.agg(**agg_kwargs).reset_index()

    # Re-derive verified status from the deduped value (defensive — values
    # should agree across sources, but re-derive anyway)
    out["non_congregate_status_verified"] = (
        out["meal_service_type_public"].apply(derive_verified_status)
    )

    # Method summary string
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
# Enrich search master
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

    join_cols = [
        "ce_id", "site_id",
        "source_dataset_ids", "source_labels", "program_years_verified",
        "meal_service_type_public", "rural_urban_status", "sfsp_site_type_public",
        "meal_types_served_public",
        "breakfast_time_public", "lunch_time_public", "supper_time_public",
        "am_snack_time_public", "pm_snack_time_public",
        "breakfast_meal_service_method", "lunch_meal_service_method",
        "supper_meal_service_method", "am_snack_meal_service_method",
        "pm_snack_meal_service_method",
        "meal_service_methods_summary",
        "non_congregate_status_verified",
    ]
    nc_for_join = nc[[c for c in join_cols if c in nc.columns]]

    out = out.merge(nc_for_join, on=["ce_id", "site_id"], how="left", indicator="_nc_merge")

    matched_mask = out["_nc_merge"] == "both"

    # Matched: overwrite NC status + source from public source.
    out.loc[matched_mask, "non_congregate_status"] = out.loc[matched_mask, "non_congregate_status_verified"]
    out.loc[matched_mask, "non_congregate_source"] = NC_SOURCE_LABEL

    # Unmatched: keep existing; fill blanks with defaults.
    blank_status = out["non_congregate_status"].apply(is_blank)
    out.loc[blank_status & ~matched_mask, "non_congregate_status"] = "Unknown"
    blank_src = out["non_congregate_source"].apply(is_blank)
    out.loc[blank_src & ~matched_mask, "non_congregate_source"] = UNKNOWN_NC_SOURCE

    # rural_urban_source: filled only where rural_urban_status is present
    out["rural_urban_source"] = out["rural_urban_status"].apply(
        lambda v: RU_SOURCE_LABEL if not is_blank(v) else pd.NA
    )

    # Defensive cleanup on the two NC-bearing columns post-merge
    for col in ("meal_service_type_public", "non_congregate_status"):
        if col in out.columns:
            out[col] = out[col].apply(fix_replacement_char)

    # Update data-quality flags
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

def build_audit(combined_rows: int, nc: pd.DataFrame,
                master_rows: int, enriched: pd.DataFrame) -> pd.DataFrame:
    nc_keys = set(zip(nc["ce_id"].astype(str), nc["site_id"].astype(str)))
    enriched_keys = list(zip(enriched["ce_id"].astype(str), enriched["site_id"].astype(str)))
    matched = sum(1 for k in enriched_keys if k in nc_keys)
    unmatched = len(enriched_keys) - matched

    statuses = enriched["non_congregate_status"].fillna("Unknown").astype(str)
    grab_go = int(statuses.str.contains("Grab-and-go", na=False).sum())
    mobile = int(statuses.str.contains("Mobile route", na=False).sum())
    home_del = int(statuses.str.contains("Home delivery", na=False).sum())
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
        "source_rows": combined_rows,
        "source_distinct_ce_site_keys": len(nc_keys),
        "search_master_rows": master_rows,
        "matched_rows": matched,
        "unmatched_rows": unmatched,
        "matched_pct": round(matched / master_rows * 100, 2) if master_rows else 0.0,
        "congregate_count": congregate,
        "non_congregate_grab_go_count": grab_go,
        "non_congregate_mobile_route_count": mobile,
        "non_congregate_home_delivery_count": home_del,
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
    print("SSO vs SFSP Texas Capstone - All-public-source NC enrichment")
    print("=" * 80)

    if not os.path.exists(SEARCH_MASTER):
        print(f"ERROR: {SEARCH_MASTER} not found. Run scripts/03 first.")
        return
    if not os.path.exists(COMBINED_NC):
        print(f"ERROR: {COMBINED_NC} not found. Run scripts/06 first.")
        return

    print(f"\nLoading {SEARCH_MASTER} ...")
    master = pd.read_csv(SEARCH_MASTER, dtype={"ce_id": str, "site_id": str})
    print(f"  {len(master):,} rows, {len(master.columns)} columns")

    print(f"\nLoading {COMBINED_NC} ...")
    combined = pd.read_csv(COMBINED_NC, dtype={"ce_id": str, "site_id": str})
    print(f"  {len(combined):,} rows, {len(combined.columns)} columns")

    nc = build_deduped_nc(combined)
    print(f"\nDeduped NC table: {len(nc):,} unique (ce_id, site_id)")

    enriched = enrich_search_master(master, nc)
    audit = build_audit(len(combined), nc, len(master), enriched)

    enriched.to_csv(ENRICHED_OUT, index=False)
    audit.to_csv(AUDIT_OUT, index=False)

    print("\nOutputs:")
    print(f"  {ENRICHED_OUT}  ({len(enriched):,} rows, {len(enriched.columns)} columns)")
    print(f"  {AUDIT_OUT}")

    print("\nAudit:")
    print(audit.to_string(index=False))

    print("\nCounts by non_congregate_status:")
    print(enriched["non_congregate_status"].fillna("(missing)")
          .value_counts(dropna=False).to_string())

    if "rural_urban_status" in enriched.columns:
        print("\nCounts by rural_urban_status:")
        print(enriched["rural_urban_status"].fillna("(none)")
              .value_counts(dropna=False).to_string())

    print("\nDONE")


if __name__ == "__main__":
    main()
