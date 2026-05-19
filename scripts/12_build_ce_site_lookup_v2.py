"""
SSO vs SFSP Texas Capstone
12_build_ce_site_lookup_v2.py

Builds the v2 CE/site lookup tables from the 5-year canonical masters
produced by scripts/11, plus the three 2022-2023 NC source datasets
ingested by scripts/10. Designed to be drop-in for the Streamlit app
once you point LOOKUP_CSV at the v2 file.

Inputs:
  data/clean_v2/{summer_meals, summer_reimbursements, summer_contacts,
                 snp_contacts, snp_reimbursements}_5yr_master.csv
  data/raw_v2/non_congregate_sources/{8ih4-zp65, 24ie-9cft, 82b8-iuvu}.csv

Outputs:
  data/lookup_v2/ce_lookup_master_v2.csv
  data/lookup_v2/site_lookup_master_v2.csv
  data/lookup_v2/ce_site_search_master_v2.csv
  data/audit/tda_5yr_lookup_v2_join_audit.csv
  data/audit/tda_5yr_pipeline_validation_report.md

Wording: "reported meals" throughout. NC verification scope is
2022-2023 only; Unknown does not mean Congregate.
"""

from __future__ import annotations

import ast
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


DATA_CLEAN_V2 = "data/clean_v2"
DATA_RAW_V2 = "data/raw_v2"
DATA_LOOKUP_V2 = "data/lookup_v2"
DATA_AUDIT = "data/audit"

IN_MEALS = os.path.join(DATA_CLEAN_V2, "summer_meals_5yr_master.csv")
IN_REIMB = os.path.join(DATA_CLEAN_V2, "summer_reimbursements_5yr_master.csv")
IN_SUMMER_CONTACTS = os.path.join(DATA_CLEAN_V2, "summer_contacts_5yr_master.csv")
IN_SNP_CONTACTS = os.path.join(DATA_CLEAN_V2, "snp_contacts_5yr_master.csv")
IN_SNP_REIMB = os.path.join(DATA_CLEAN_V2, "snp_reimbursements_5yr_master.csv")
IN_NC_DIR = os.path.join(DATA_RAW_V2, "non_congregate_sources")

OUT_CE = os.path.join(DATA_LOOKUP_V2, "ce_lookup_master_v2.csv")
OUT_SITE = os.path.join(DATA_LOOKUP_V2, "site_lookup_master_v2.csv")
OUT_SEARCH = os.path.join(DATA_LOOKUP_V2, "ce_site_search_master_v2.csv")
OUT_AUDIT = os.path.join(DATA_AUDIT, "tda_5yr_lookup_v2_join_audit.csv")
OUT_REPORT = os.path.join(DATA_AUDIT, "tda_5yr_pipeline_validation_report.md")

for folder in [DATA_LOOKUP_V2, DATA_AUDIT]:
    os.makedirs(folder, exist_ok=True)

NC_SOURCE_LABEL = (
    "public-source meal service type "
    "(TX Open Data 8ih4-zp65, 24ie-9cft, 82b8-iuvu, SFSP 2022-2023)"
)
RU_SOURCE_LABEL = (
    "public-source rural/urban indicator "
    "(TX Open Data 8ih4-zp65, SFSP 2022-2023)"
)
UNKNOWN_NC_SOURCE = "Not available in public source"


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


def standardize_id(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    return s.where(~s.isin(["nan", "None", "NaT", "", "<NA>"]), pd.NA)


def to_number(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def is_blank(value) -> bool:
    if pd.isna(value):
        return True
    s = str(value).strip()
    return s == "" or s.lower() in {"nan", "none", "<na>"}


def normalize_text(value):
    if pd.isna(value):
        return value
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s if s and s.lower() not in {"nan", "none", "<na>"} else pd.NA


def first_non_null(series: pd.Series):
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    return s.iloc[0] if len(s) else pd.NA


def unique_joined(series: pd.Series, sep: str = ",") -> Optional[str]:
    vals = set()
    for v in series.dropna():
        s = str(v).strip()
        if s and s.lower() not in {"nan", "none", "<na>"}:
            vals.add(s)
    return sep.join(sorted(vals)) if vals else pd.NA


def fix_replacement_char(value):
    if pd.isna(value):
        return value
    return str(value).replace("�", "—")


def derive_verified_nc_status(value) -> str:
    if pd.isna(value):
        return "Unknown"
    s = str(value)
    if "Non-Congregate" in s:
        return s
    if "Congregate" in s:
        return "Congregate"
    return "Unknown"


def parse_geo(val):
    if pd.isna(val):
        return (pd.NA, pd.NA)
    s = str(val).strip()
    if not s:
        return (pd.NA, pd.NA)
    try:
        obj = ast.literal_eval(s)
        if isinstance(obj, dict):
            coords = obj.get("coordinates")
            if coords and len(coords) >= 2:
                return (float(coords[1]), float(coords[0]))
    except Exception:
        pass
    nums = re.findall(r"-?\d+\.\d+", s)
    if len(nums) >= 2:
        return (float(nums[1]), float(nums[0]))
    return (pd.NA, pd.NA)


METHOD_SHORT_LABELS = {
    "Self-Prep - Prepares on site": "Self-Prep on site",
    "Self-Prep - Receives meals (Central Kitchen)": "Self-Prep from Central Kitchen",
    "Vended by Food Service Management Company (FSMC)": "Vended by FSMC",
    "Vended by another SFSP Contracting Entity": "Vended by another SFSP CE",
}


def short_method(value):
    if pd.isna(value):
        return None
    s = normalize_text(value)
    if not s:
        return None
    return METHOD_SHORT_LABELS.get(s, s)


# --------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------

def load_csv_with_ids(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df = normalize_columns(df)
    for c in ("ce_id", "site_id"):
        if c in df.columns:
            df[c] = standardize_id(df[c])
    if "canonical_year" in df.columns:
        df["canonical_year"] = pd.to_numeric(df["canonical_year"], errors="coerce").astype("Int64")
    if "total_meals" in df.columns:
        df["total_meals"] = pd.to_numeric(df["total_meals"], errors="coerce")
    if "total_reimbursement" in df.columns:
        df["total_reimbursement"] = pd.to_numeric(df["total_reimbursement"], errors="coerce")
    if "nc_from_site_name" in df.columns:
        # CSV round-trip turns booleans into strings; coerce back.
        df["nc_from_site_name"] = (
            df["nc_from_site_name"].astype(str).str.strip().str.lower()
            .isin({"true", "1", "yes"})
        )
    return df


# --------------------------------------------------------------------
# NC-from-name aggregation across all three canonical sources
# --------------------------------------------------------------------

def aggregate_nc_from_name(*sources: pd.DataFrame) -> pd.DataFrame:
    """For each (ce_id, site_id), find the union of canonical_years
    across the provided canonical tables where nc_from_site_name was
    True. Returns one row per (ce_id, site_id) that had NC_ in ANY year,
    with `nc_flag_from_name=True` and `nc_name_years` as a sorted
    comma-joined year list."""
    parts = []
    for src in sources:
        if src is None or src.empty:
            continue
        if "nc_from_site_name" not in src.columns:
            continue
        flag = src["nc_from_site_name"]
        if flag.dtype != bool:
            flag = (
                flag.astype(str).str.strip().str.lower()
                .isin({"true", "1", "yes"})
            )
        sub = src.loc[
            flag.fillna(False) & src["ce_id"].notna() & src["site_id"].notna(),
            ["ce_id", "site_id", "canonical_year"],
        ].copy()
        if not sub.empty:
            parts.append(sub)

    if not parts:
        return pd.DataFrame(columns=["ce_id", "site_id", "nc_flag_from_name", "nc_name_years"])

    all_nc = pd.concat(parts, ignore_index=True)

    def _years_join(s):
        years = sorted({int(v) for v in s.dropna()})
        return ", ".join(str(y) for y in years) if years else pd.NA

    out = (
        all_nc.groupby(["ce_id", "site_id"], dropna=False)
        .agg(nc_name_years=("canonical_year", _years_join))
        .reset_index()
    )
    out["nc_flag_from_name"] = True
    return out[["ce_id", "site_id", "nc_flag_from_name", "nc_name_years"]]


# --------------------------------------------------------------------
# Per-site / per-CE meal aggregation
# --------------------------------------------------------------------

def summarize_meals_by_site(meals: pd.DataFrame) -> pd.DataFrame:
    g = meals.groupby(["ce_id", "site_id"], dropna=False)
    return g.agg(
        total_reported_meals=("total_meals", "sum"),
        years_active=("canonical_year", lambda s: s.dropna().nunique()),
        latest_program_year=("canonical_year", "max"),
        program_types_observed=("program_type", unique_joined),
        ce_name_from_meals=("ce_name", first_non_null),
        site_name_from_meals=("site_name", first_non_null),
        site_name_base_from_meals=("site_name_base", first_non_null),
        ce_county_from_meals=("ce_county", first_non_null),
        site_county_from_meals=("site_county", first_non_null),
        region_from_meals=("region", first_non_null),
    ).reset_index()


def summarize_meals_by_ce(meals: pd.DataFrame) -> pd.DataFrame:
    g = meals.groupby("ce_id", dropna=False)
    return g.agg(
        total_reported_meals_ce=("total_meals", "sum"),
        latest_program_year_ce=("canonical_year", "max"),
        years_active_ce=("canonical_year", lambda s: s.dropna().nunique()),
        programs_observed_from_meals=("program_type", unique_joined),
        ce_name_from_meals=("ce_name", first_non_null),
        ce_county_from_meals=("ce_county", first_non_null),
        region_from_meals=("region", first_non_null),
    ).reset_index()


# --------------------------------------------------------------------
# Latest-record dedup for contacts (prefer most recent canonical_year)
# --------------------------------------------------------------------

def dedup_latest(df: pd.DataFrame, key_cols: List[str], year_col: str = "canonical_year") -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    # Sort so that the LATEST year for each key comes first; then take
    # first-non-null per field across the sorted group.
    d = d.sort_values([*key_cols, year_col], ascending=[True] * len(key_cols) + [False])
    agg = {c: (c, first_non_null) for c in d.columns if c not in set(key_cols)}
    # Special handling — collapse certain fields by unique-join
    return d.groupby(key_cols, dropna=False).agg(**agg).reset_index()


def dedup_summer_contacts(summer_contacts: pd.DataFrame) -> pd.DataFrame:
    return dedup_latest(summer_contacts, key_cols=["ce_id", "site_id"])


def dedup_snp_contacts(snp_contacts: pd.DataFrame) -> pd.DataFrame:
    return dedup_latest(snp_contacts, key_cols=["ce_id", "site_id"])


# --------------------------------------------------------------------
# Build NC enrichment from 3 sources
# --------------------------------------------------------------------

def build_nc_enrichment_from_raw() -> pd.DataFrame:
    nc_files = {
        "8ih4-zp65": "TX Open Data 8ih4-zp65 (SFSP Contacts 2022-2023)",
        "24ie-9cft": "TX Open Data 24ie-9cft (All Summer Sites Contacts 2022-2023)",
        "82b8-iuvu": "TX Open Data 82b8-iuvu (SSO Contacts 2022-2023)",
    }
    parts = []
    for dsid, label in nc_files.items():
        path = os.path.join(IN_NC_DIR, f"{dsid}.csv")
        if not os.path.exists(path):
            print(f"  NC source {dsid}: file missing at {path}")
            continue
        df = pd.read_csv(path, dtype=str, low_memory=False)
        d = normalize_columns(df)
        sub = pd.DataFrame()
        sub["source_dataset_id"] = [dsid] * len(d)
        sub["source_label"] = [label] * len(d)
        sub["program_year"] = ["2023"] * len(d)
        sub["ce_id"] = standardize_id(d["ceid"]) if "ceid" in d.columns else pd.NA
        sub["site_id"] = standardize_id(d["siteid"]) if "siteid" in d.columns else pd.NA
        sub["meal_service_type_public"] = (
            d["mealservicetype"].apply(normalize_text).apply(fix_replacement_char)
            if "mealservicetype" in d.columns
            else pd.NA
        )
        sub["rural_urban_status"] = (
            d["ruralorurbancode"].apply(normalize_text)
            if "ruralorurbancode" in d.columns
            else pd.NA
        )
        sub["sfsp_site_type_public"] = (
            d["sitetype"].apply(normalize_text)
            if "sitetype" in d.columns
            else pd.NA
        )
        for src, tgt in [
            ("breakfastmealservicemethod", "breakfast_meal_service_method"),
            ("lunchmealservicemethod", "lunch_meal_service_method"),
            ("suppermealservicemethod", "supper_meal_service_method"),
            ("amsnackmealservicemethod", "am_snack_meal_service_method"),
            ("pmsnackmealservicemethod", "pm_snack_meal_service_method"),
        ]:
            sub[tgt] = d[src].apply(normalize_text) if src in d.columns else pd.NA
        parts.append(sub)

    if not parts:
        return pd.DataFrame()
    combined = pd.concat(parts, ignore_index=True)

    grp = combined.groupby(["ce_id", "site_id"], dropna=False)
    agg_kwargs = {
        "source_dataset_ids": ("source_dataset_id", unique_joined),
        "source_labels": ("source_label", unique_joined),
        "program_years_verified": ("program_year", unique_joined),
        "meal_service_type_public": ("meal_service_type_public", first_non_null),
        "rural_urban_status": ("rural_urban_status", first_non_null),
        "sfsp_site_type_public": ("sfsp_site_type_public", first_non_null),
        "breakfast_meal_service_method": ("breakfast_meal_service_method", first_non_null),
        "lunch_meal_service_method": ("lunch_meal_service_method", first_non_null),
        "supper_meal_service_method": ("supper_meal_service_method", first_non_null),
        "am_snack_meal_service_method": ("am_snack_meal_service_method", first_non_null),
        "pm_snack_meal_service_method": ("pm_snack_meal_service_method", first_non_null),
    }
    out = grp.agg(**agg_kwargs).reset_index()

    out["non_congregate_status_verified"] = (
        out["meal_service_type_public"].apply(derive_verified_nc_status)
    )

    def method_summary(row):
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
    out["meal_service_methods_summary"] = out.apply(method_summary, axis=1)
    return out


# --------------------------------------------------------------------
# Build site lookup
# --------------------------------------------------------------------

def build_site_lookup(
    summer_contacts_d: pd.DataFrame,
    snp_contacts_d: pd.DataFrame,
    meals_site_summary: pd.DataFrame,
    snp_reimb: pd.DataFrame,
    nc: pd.DataFrame,
    nc_name_agg: pd.DataFrame,
) -> pd.DataFrame:
    # Universe: union of (ce_id, site_id) across summer-contacts, snp-contacts,
    # meals, and snp-reimbursements (since SNP reimb has site_id and may add sites).
    universe = pd.concat([
        summer_contacts_d[["ce_id", "site_id"]],
        snp_contacts_d[["ce_id", "site_id"]],
        meals_site_summary[["ce_id", "site_id"]],
        snp_reimb[["ce_id", "site_id"]].dropna(subset=["site_id"]),
    ], ignore_index=True).drop_duplicates(subset=["ce_id", "site_id"]).reset_index(drop=True)

    s = summer_contacts_d.rename(columns={c: f"{c}_s" for c in summer_contacts_d.columns if c not in {"ce_id", "site_id"}})
    n = snp_contacts_d.rename(columns={c: f"{c}_n" for c in snp_contacts_d.columns if c not in {"ce_id", "site_id"}})

    merged = (
        universe
        .merge(s, on=["ce_id", "site_id"], how="left")
        .merge(n, on=["ce_id", "site_id"], how="left")
        .merge(meals_site_summary, on=["ce_id", "site_id"], how="left")
        .merge(nc, on=["ce_id", "site_id"], how="left", indicator="_nc_merge")
        .merge(nc_name_agg, on=["ce_id", "site_id"], how="left")
    )

    out = pd.DataFrame({"ce_id": merged["ce_id"], "site_id": merged["site_id"]})

    def pick(field):
        s_col, n_col = f"{field}_s", f"{field}_n"
        s_series = merged[s_col] if s_col in merged.columns else pd.Series([pd.NA] * len(merged))
        n_series = merged[n_col] if n_col in merged.columns else pd.Series([pd.NA] * len(merged))
        # row-wise: prefer summer (latest summer-contact wins), then snp
        result = s_series.copy()
        mask = result.isna() | (result.astype(str).str.strip().isin(["", "nan", "<NA>"]))
        result = result.where(~mask, n_series)
        return result

    shared = [
        "ce_name",
        "ce_street_address_line_1", "ce_street_address_line_2",
        "ce_city", "ce_state", "ce_zip",
        "ce_county", "region",
        "site_name", "site_name_base", "site_county",
        "site_street_address_line_1", "site_street_address_line_2",
        "site_city", "site_state", "site_zip",
        "type_of_agency", "type_of_org",
        "latitude", "longitude",
    ]
    for f in shared:
        out[f] = pick(f)

    summer_only = [
        "site_type",
        "program_administrator_name", "program_administrator_email", "program_administrator_phone",
        "program_coordinator_name", "program_coordinator_email", "program_coordinator_phone",
        "site_contact_name", "site_contact_title", "site_contact_email", "site_contact_phone",
        "operation_start_date", "operation_end_date",
        "site_start_date", "site_end_date",
        "days_of_operation", "meal_types_served",
        "breakfast_time", "lunch_time", "supper_time", "am_snack_time", "pm_snack_time",
    ]
    for f in summer_only:
        col = f"{f}_s"
        out[f] = merged[col] if col in merged.columns else pd.NA

    snp_only = [
        "superintendent_name", "superintendent_email", "superintendent_phone",
        "child_nutrition_director_name", "child_nutrition_director_email", "child_nutrition_director_phone",
        "school_breakfast_program", "national_school_lunch_program",
        "afterschool_care_program", "special_milk_program",
        "ffvp_approved", "severe_need_breakfast", "universal_free_breakfast",
        "managed_by_fsmc", "breakfast_pricing", "lunch_pricing", "snack_pricing",
        "area_eligible_snack", "site_isp", "cep", "provision2", "grade_span",
    ]
    for f in snp_only:
        col = f"{f}_n"
        out[f] = merged[col] if col in merged.columns else pd.NA

    # Fallbacks from meals
    out["ce_name"] = out["ce_name"].combine_first(merged.get("ce_name_from_meals", pd.Series([pd.NA] * len(out))))
    out["site_name"] = out["site_name"].combine_first(merged.get("site_name_from_meals", pd.Series([pd.NA] * len(out))))
    out["site_name_base"] = out["site_name_base"].combine_first(merged.get("site_name_base_from_meals", pd.Series([pd.NA] * len(out))))
    out["site_county"] = out["site_county"].combine_first(merged.get("site_county_from_meals", pd.Series([pd.NA] * len(out))))
    out["region"] = out["region"].combine_first(merged.get("region_from_meals", pd.Series([pd.NA] * len(out))))

    # Meal activity
    out["total_reported_meals"] = pd.to_numeric(merged.get("total_reported_meals"), errors="coerce").fillna(0)
    out["years_active"] = pd.to_numeric(merged.get("years_active"), errors="coerce").fillna(0).astype(int)
    out["latest_program_year"] = pd.to_numeric(merged.get("latest_program_year"), errors="coerce").astype("Int64")
    out["program_types_observed"] = merged.get("program_types_observed")

    # NC enrichment fields (MealServiceType-based)
    out["source_dataset_ids"] = merged.get("source_dataset_ids")
    out["source_labels"] = merged.get("source_labels")
    out["program_years_verified"] = merged.get("program_years_verified")
    out["meal_service_type_public"] = merged.get("meal_service_type_public").apply(fix_replacement_char) if "meal_service_type_public" in merged.columns else pd.NA
    out["rural_urban_status"] = merged.get("rural_urban_status")
    out["sfsp_site_type_public"] = merged.get("sfsp_site_type_public")
    out["meal_service_methods_summary"] = merged.get("meal_service_methods_summary")

    # NC-from-name fields (aggregated across all canonical sources)
    out["nc_flag_from_name"] = merged.get(
        "nc_flag_from_name", pd.Series([pd.NA] * len(merged))
    ).fillna(False).astype(bool)
    out["nc_name_years"] = merged.get("nc_name_years", pd.Series([pd.NA] * len(merged)))

    # Composite non-congregate status. Priority:
    #   1. MealServiceType says a specific Non-Congregate subtype  (most specific)
    #   2. site name begins with NC_                                (from name)
    #   3. MealServiceType says Congregate
    #   4. Unknown
    mst_status = merged.get("non_congregate_status_verified", pd.Series([pd.NA] * len(merged)))
    mst_status_str = mst_status.astype("string").fillna("")
    mst_specific_nc = mst_status_str.str.contains("Non-Congregate", na=False)
    mst_congregate = mst_status_str.str.strip() == "Congregate"
    name_nc = out["nc_flag_from_name"].fillna(False).astype(bool)

    out["non_congregate_status"] = "Unknown"
    out.loc[mst_congregate, "non_congregate_status"] = "Congregate"
    out.loc[name_nc, "non_congregate_status"] = "Non-Congregate (from site name)"
    out.loc[mst_specific_nc, "non_congregate_status"] = (
        mst_status[mst_specific_nc].apply(fix_replacement_char)
    )

    # Composite source string. Order mirrors the status priority above.
    MST_SOURCE = "MealServiceType (8ih4-zp65, 24ie-9cft, 82b8-iuvu)"
    NAME_SOURCE = "site name NC_ prefix"
    BOTH_SOURCE = "MealServiceType + site name NC_ prefix"

    def _compose_source(mst_nc, mst_cong, name_only):
        if mst_nc and name_only:
            return BOTH_SOURCE
        if mst_nc:
            return MST_SOURCE
        if name_only:
            return NAME_SOURCE
        if mst_cong:
            return MST_SOURCE
        return UNKNOWN_NC_SOURCE

    out["non_congregate_source"] = [
        _compose_source(a, b, c)
        for a, b, c in zip(mst_specific_nc.tolist(), mst_congregate.tolist(), name_nc.tolist())
    ]

    out["rural_urban_source"] = out["rural_urban_status"].apply(
        lambda v: RU_SOURCE_LABEL if not is_blank(v) else pd.NA
    )

    # data_quality_flags
    def quality_flags(row):
        flags = []
        if is_blank(row.get("ce_id")):
            flags.append("missing_ce_id")
        if is_blank(row.get("site_id")):
            flags.append("missing_site_id")
        if is_blank(row.get("site_street_address_line_1")):
            flags.append("missing_site_address")
        if is_blank(row.get("site_contact_name")) and is_blank(row.get("site_contact_email")) and is_blank(row.get("site_contact_phone")):
            flags.append("missing_site_contact")
        if is_blank(row.get("operation_start_date")) and is_blank(row.get("operation_end_date")):
            flags.append("missing_operation_dates")
        if is_blank(row.get("meal_types_served")):
            flags.append("missing_meal_types_served")
        if float(row.get("total_reported_meals") or 0) == 0:
            flags.append("no_reported_meal_activity")
        if str(row.get("non_congregate_status", "")).strip() == "Unknown":
            flags.append("non_congregate_unknown")
        if is_blank(row.get("rural_urban_status")):
            flags.append("rural_urban_unknown")
        return "|".join(flags) if flags else "ok"
    out["data_quality_flags"] = out.apply(quality_flags, axis=1)
    return out


# --------------------------------------------------------------------
# CE lookup
# --------------------------------------------------------------------

def build_ce_lookup(site_lookup: pd.DataFrame, meals_ce_summary: pd.DataFrame,
                    summer_contacts_d: pd.DataFrame, snp_contacts_d: pd.DataFrame) -> pd.DataFrame:
    # CE-level addresses + contacts: take from a CE-level dedup of summer + SNP contacts.
    ce_summer = summer_contacts_d.sort_values(["ce_id", "canonical_year"], ascending=[True, False]) \
        .groupby("ce_id", dropna=False).agg(
            ce_name_s=("ce_name", first_non_null),
            ce_street_address_line_1_s=("ce_street_address_line_1", first_non_null),
            ce_city_s=("ce_city", first_non_null),
            ce_state_s=("ce_state", first_non_null),
            ce_zip_s=("ce_zip", first_non_null),
            ce_county_s=("ce_county", first_non_null),
            region_s=("region", first_non_null),
            program_administrator_name_s=("program_administrator_name", first_non_null),
            program_administrator_email_s=("program_administrator_email", first_non_null),
            program_administrator_phone_s=("program_administrator_phone", first_non_null),
            program_coordinator_name_s=("program_coordinator_name", first_non_null),
            program_coordinator_email_s=("program_coordinator_email", first_non_null),
            program_coordinator_phone_s=("program_coordinator_phone", first_non_null),
            summer_sites_count=("site_id", lambda s: s.dropna().nunique()),
        ).reset_index()

    ce_snp = snp_contacts_d.sort_values(["ce_id", "canonical_year"], ascending=[True, False]) \
        .groupby("ce_id", dropna=False).agg(
            ce_name_n=("ce_name", first_non_null),
            ce_street_address_line_1_n=("ce_street_address_line_1", first_non_null),
            ce_city_n=("ce_city", first_non_null),
            ce_state_n=("ce_state", first_non_null),
            ce_zip_n=("ce_zip", first_non_null),
            superintendent_name_n=("superintendent_name", first_non_null),
            superintendent_email_n=("superintendent_email", first_non_null),
            superintendent_phone_n=("superintendent_phone", first_non_null),
            child_nutrition_director_name_n=("child_nutrition_director_name", first_non_null),
            child_nutrition_director_email_n=("child_nutrition_director_email", first_non_null),
            child_nutrition_director_phone_n=("child_nutrition_director_phone", first_non_null),
            snp_sites_count=("site_id", lambda s: s.dropna().nunique()),
        ).reset_index()

    universe = pd.concat([
        ce_summer[["ce_id"]], ce_snp[["ce_id"]], meals_ce_summary[["ce_id"]],
    ], ignore_index=True).drop_duplicates(subset=["ce_id"]).reset_index(drop=True)

    merged = (
        universe
        .merge(ce_summer, on="ce_id", how="left")
        .merge(ce_snp, on="ce_id", how="left")
        .merge(meals_ce_summary, on="ce_id", how="left")
    )

    out = pd.DataFrame({"ce_id": merged["ce_id"]})
    def pick(base):
        s_col, n_col = f"{base}_s", f"{base}_n"
        s_series = merged[s_col] if s_col in merged.columns else pd.Series([pd.NA] * len(merged))
        n_series = merged[n_col] if n_col in merged.columns else pd.Series([pd.NA] * len(merged))
        result = s_series.copy()
        mask = result.isna() | (result.astype(str).str.strip().isin(["", "nan", "<NA>"]))
        return result.where(~mask, n_series)

    for f in ["ce_name", "ce_street_address_line_1", "ce_city", "ce_state", "ce_zip"]:
        out[f] = pick(f)
    out["ce_county"] = merged.get("ce_county_s", pd.Series([pd.NA] * len(merged))).combine_first(
        merged.get("ce_county_from_meals", pd.Series([pd.NA] * len(merged)))
    )
    out["region"] = merged.get("region_s", pd.Series([pd.NA] * len(merged))).combine_first(
        merged.get("region_from_meals", pd.Series([pd.NA] * len(merged)))
    )
    out["ce_name"] = out["ce_name"].combine_first(merged.get("ce_name_from_meals", pd.Series([pd.NA] * len(merged))))

    for f in ["program_administrator_name", "program_administrator_email", "program_administrator_phone",
              "program_coordinator_name", "program_coordinator_email", "program_coordinator_phone"]:
        out[f] = merged.get(f"{f}_s")
    for f in ["superintendent_name", "superintendent_email", "superintendent_phone",
              "child_nutrition_director_name", "child_nutrition_director_email", "child_nutrition_director_phone"]:
        out[f] = merged.get(f"{f}_n")

    site_counts = site_lookup.groupby("ce_id", dropna=False).size().rename("total_sites").reset_index()
    out = out.merge(site_counts, on="ce_id", how="left")
    out["total_sites"] = out["total_sites"].fillna(0).astype(int)
    out["summer_sites_count"] = pd.to_numeric(merged.get("summer_sites_count", 0), errors="coerce").fillna(0).astype(int)
    out["snp_sites_count"] = pd.to_numeric(merged.get("snp_sites_count", 0), errors="coerce").fillna(0).astype(int)

    out["total_reported_meals"] = pd.to_numeric(merged.get("total_reported_meals_ce"), errors="coerce").fillna(0)
    out["latest_program_year"] = pd.to_numeric(merged.get("latest_program_year_ce"), errors="coerce").astype("Int64")
    out["programs_observed"] = merged.get("programs_observed_from_meals")
    return out


# --------------------------------------------------------------------
# Search master
# --------------------------------------------------------------------

def fmt_address(line1, line2, city, state, zipc):
    parts1 = [str(x).strip() for x in (line1, line2) if not is_blank(x)]
    line_a = " ".join(parts1)
    parts2 = [str(x).strip() for x in (city, state) if not is_blank(x)]
    line_b = ", ".join(parts2)
    if not is_blank(zipc):
        line_b = (line_b + " " + str(zipc).strip()).strip()
    joined = ", ".join([p for p in (line_a, line_b) if p])
    return joined if joined else pd.NA


def contact_summary(name, title, email, phone):
    bits = []
    if not is_blank(name):
        s = str(name).strip()
        if not is_blank(title):
            s += f" ({str(title).strip()})"
        bits.append(s)
    if not is_blank(email):
        bits.append(str(email).strip())
    if not is_blank(phone):
        bits.append(str(phone).strip())
    return " | ".join(bits) if bits else pd.NA


def build_search_master(site_lookup: pd.DataFrame, ce_lookup: pd.DataFrame) -> pd.DataFrame:
    base = site_lookup.copy()

    ce_for_join = ce_lookup[[
        "ce_id",
        "ce_street_address_line_1",
        "ce_city", "ce_state", "ce_zip",
        "program_administrator_name", "program_administrator_email", "program_administrator_phone",
        "program_coordinator_name", "program_coordinator_email", "program_coordinator_phone",
        "superintendent_name", "superintendent_email", "superintendent_phone",
        "child_nutrition_director_name", "child_nutrition_director_email", "child_nutrition_director_phone",
    ]].copy().add_suffix("_ce").rename(columns={"ce_id_ce": "ce_id"})
    base = base.merge(ce_for_join, on="ce_id", how="left")

    base["site_address_full"] = [
        fmt_address(a, b, c, s, z) for a, b, c, s, z in zip(
            base["site_street_address_line_1"], base["site_street_address_line_2"],
            base["site_city"], base["site_state"], base["site_zip"],
        )
    ]
    base["ce_address_full"] = [
        fmt_address(a, pd.NA, c, s, z) for a, c, s, z in zip(
            base["ce_street_address_line_1_ce"],
            base["ce_city_ce"], base["ce_state_ce"], base["ce_zip_ce"],
        )
    ]
    base["site_contact_summary"] = [
        contact_summary(n, t, e, p) for n, t, e, p in zip(
            base["site_contact_name"], base["site_contact_title"],
            base["site_contact_email"], base["site_contact_phone"],
        )
    ]

    def ce_contact_summary_row(row):
        bits = []
        for label, name_c, email_c, phone_c in [
            ("Admin", "program_administrator_name_ce", "program_administrator_email_ce", "program_administrator_phone_ce"),
            ("Coord", "program_coordinator_name_ce", "program_coordinator_email_ce", "program_coordinator_phone_ce"),
            ("Super", "superintendent_name_ce", "superintendent_email_ce", "superintendent_phone_ce"),
            ("CND", "child_nutrition_director_name_ce", "child_nutrition_director_email_ce", "child_nutrition_director_phone_ce"),
        ]:
            s = contact_summary(row.get(name_c), None, row.get(email_c), row.get(phone_c))
            if not is_blank(s):
                bits.append(f"{label}: {s}")
        return " || ".join(bits) if bits else pd.NA
    base["ce_contact_summary"] = base.apply(ce_contact_summary_row, axis=1)

    def operation_dates_summary(op_s, op_e, ss, se):
        parts = []
        if not is_blank(op_s) or not is_blank(op_e):
            parts.append(f"Operates {op_s or '?'} to {op_e or '?'}")
        if not is_blank(ss) or not is_blank(se):
            parts.append(f"Site {ss or '?'} to {se or '?'}")
        return " | ".join(parts) if parts else pd.NA
    base["operation_dates_summary"] = [
        operation_dates_summary(a, b, c, d) for a, b, c, d in zip(
            base["operation_start_date"], base["operation_end_date"],
            base["site_start_date"], base["site_end_date"],
        )
    ]

    def serving_dates_summary(days_op, types):
        parts = []
        if not is_blank(days_op):
            parts.append(f"Days: {days_op}")
        if not is_blank(types):
            parts.append(f"Meal types: {types}")
        return " | ".join(parts) if parts else pd.NA
    base["serving_dates_summary"] = [
        serving_dates_summary(a, b) for a, b in zip(
            base["days_of_operation"], base["meal_types_served"]
        )
    ]

    def service_times_summary(b, l, su, am, pm):
        parts = []
        if not is_blank(b): parts.append(f"B: {b}")
        if not is_blank(l): parts.append(f"L: {l}")
        if not is_blank(su): parts.append(f"Su: {su}")
        if not is_blank(am): parts.append(f"AM: {am}")
        if not is_blank(pm): parts.append(f"PM: {pm}")
        return " | ".join(parts) if parts else pd.NA
    base["service_times_summary"] = [
        service_times_summary(*t) for t in zip(
            base["breakfast_time"], base["lunch_time"], base["supper_time"],
            base["am_snack_time"], base["pm_snack_time"],
        )
    ]

    def snp_flags_row(row):
        parts = []
        for label, col in [
            ("SBP", "school_breakfast_program"),
            ("NSLP", "national_school_lunch_program"),
            ("ASCP", "afterschool_care_program"),
            ("SMP", "special_milk_program"),
            ("FFVP", "ffvp_approved"),
            ("SNB", "severe_need_breakfast"),
            ("UFB", "universal_free_breakfast"),
            ("FSMC", "managed_by_fsmc"),
        ]:
            v = row.get(col)
            if not is_blank(v):
                parts.append(f"{label}={v}")
        return " | ".join(parts) if parts else pd.NA
    base["snp_flags_summary"] = base.apply(snp_flags_row, axis=1)

    def eligibility_row(row):
        parts = []
        for label, col in [("ISP", "site_isp"), ("CEP", "cep"),
                           ("Provision2", "provision2"),
                           ("AreaEligibleSnack", "area_eligible_snack")]:
            v = row.get(col)
            if not is_blank(v):
                parts.append(f"{label}={v}")
        return " | ".join(parts) if parts else pd.NA
    base["eligibility_indicators_summary"] = base.apply(eligibility_row, axis=1)

    def make_search_key(row):
        parts = [row.get(c) for c in ["ce_id", "ce_name", "site_id", "site_name",
                                       "site_city", "site_county", "ce_county"]]
        bits = []
        for p in parts:
            if not is_blank(p):
                s = re.sub(r"\s+", " ", str(p)).strip()
                if s:
                    bits.append(s.lower())
        return " ".join(bits)
    base["search_key"] = base.apply(make_search_key, axis=1)

    spec_cols = [
        "search_key", "ce_id", "ce_name", "site_id", "site_name", "site_name_base",
        "site_address_full", "ce_address_full",
        "site_contact_summary", "ce_contact_summary",
        "program_types_observed", "site_type",
        "operation_dates_summary", "serving_dates_summary",
        "meal_types_served", "service_times_summary",
        "total_reported_meals", "latest_program_year", "years_active",
        "snp_flags_summary", "eligibility_indicators_summary",
        "non_congregate_status", "non_congregate_source",
        "nc_flag_from_name", "nc_name_years",
        "meal_service_type_public", "rural_urban_status", "rural_urban_source",
        "sfsp_site_type_public", "meal_service_methods_summary",
        "source_dataset_ids", "source_labels", "program_years_verified",
        "data_quality_flags", "latitude", "longitude",
    ]
    return base[[c for c in spec_cols if c in base.columns]]


# --------------------------------------------------------------------
# Audit + validation report
# --------------------------------------------------------------------

def build_join_audit(meals: pd.DataFrame, reimb: pd.DataFrame,
                     summer_contacts: pd.DataFrame, snp_contacts: pd.DataFrame,
                     snp_reimb: pd.DataFrame, nc: pd.DataFrame,
                     ce_lookup: pd.DataFrame, site_lookup: pd.DataFrame,
                     search_master: pd.DataFrame) -> pd.DataFrame:
    rows = []
    def add(name, df, ce_col="ce_id", site_col="site_id"):
        row = {"source_table": name, "row_count": len(df)}
        if ce_col in df.columns:
            row["distinct_ce_id"] = int(df[ce_col].dropna().astype(str).nunique())
        else:
            row["distinct_ce_id"] = None
        if site_col in df.columns:
            row["distinct_site_id"] = int(df[site_col].dropna().astype(str).nunique())
        else:
            row["distinct_site_id"] = None
        row["created_at"] = datetime.now().isoformat(timespec="seconds")
        rows.append(row)
    add("summer_meals_5yr_master", meals)
    add("summer_reimbursements_5yr_master", reimb, site_col="ce_id")
    add("summer_contacts_5yr_master", summer_contacts)
    add("snp_contacts_5yr_master", snp_contacts)
    add("snp_reimbursements_5yr_master", snp_reimb)
    add("nc_enrichment_deduped", nc)
    add("ce_lookup_master_v2", ce_lookup, site_col="ce_id")
    add("site_lookup_master_v2", site_lookup)
    add("ce_site_search_master_v2", search_master)
    return pd.DataFrame(rows)


def write_validation_report(meals: pd.DataFrame, reimb: pd.DataFrame,
                            summer_contacts: pd.DataFrame, snp_contacts: pd.DataFrame,
                            snp_reimb: pd.DataFrame, nc: pd.DataFrame,
                            ce_lookup: pd.DataFrame, site_lookup: pd.DataFrame,
                            search_master: pd.DataFrame) -> None:
    def years_breakdown(df, year_col, value_col=None, agg="sum"):
        if df.empty or year_col not in df.columns:
            return "_(no data)_\n"
        if value_col and value_col in df.columns:
            g = df.groupby(year_col, dropna=False)[value_col].agg(agg)
        else:
            g = df.groupby(year_col, dropna=False).size()
        lines = ["| Year | Value |", "|---|---:|"]
        for k, v in g.items():
            try:
                vv = f"{int(v):,}"
            except Exception:
                vv = str(v)
            lines.append(f"| {k} | {vv} |")
        return "\n".join(lines) + "\n"

    nc_status_counts = search_master["non_congregate_status"].fillna("Unknown").value_counts()
    nc_lines = ["| Status | Count |", "|---|---:|"]
    for k, v in nc_status_counts.items():
        nc_lines.append(f"| {k} | {int(v):,} |")
    nc_table = "\n".join(nc_lines) + "\n"

    md = []
    md.append("# TDA 5-Year Pipeline Validation Report\n")
    md.append(f"_Generated {datetime.now().isoformat(timespec='seconds')}_\n")
    md.append("## Wording\n")
    md.append("This pipeline reports **reported meals served**, not unique children served. ")
    md.append("Verified non-congregate status is available only where public TX Open Data ")
    md.append("includes meal service type, currently limited to the 2022–2023 contact ")
    md.append("datasets. **Unknown does not mean congregate.**\n\n")

    md.append("## Row counts by category\n")
    md.append("| Table | Rows | Distinct CEs | Distinct sites |\n|---|---:|---:|---:|\n")
    md.append(f"| summer_meals_5yr_master | {len(meals):,} | {meals['ce_id'].dropna().nunique():,} | {meals['site_id'].dropna().nunique():,} |\n")
    md.append(f"| summer_reimbursements_5yr_master | {len(reimb):,} | {reimb['ce_id'].dropna().nunique():,} | — |\n")
    md.append(f"| summer_contacts_5yr_master | {len(summer_contacts):,} | {summer_contacts['ce_id'].dropna().nunique():,} | {summer_contacts['site_id'].dropna().nunique():,} |\n")
    md.append(f"| snp_contacts_5yr_master | {len(snp_contacts):,} | {snp_contacts['ce_id'].dropna().nunique():,} | {snp_contacts['site_id'].dropna().nunique():,} |\n")
    md.append(f"| snp_reimbursements_5yr_master | {len(snp_reimb):,} | {snp_reimb['ce_id'].dropna().nunique():,} | {snp_reimb['site_id'].dropna().nunique():,} |\n")
    md.append(f"| ce_lookup_master_v2 | {len(ce_lookup):,} | {ce_lookup['ce_id'].dropna().nunique():,} | — |\n")
    md.append(f"| site_lookup_master_v2 | {len(site_lookup):,} | {site_lookup['ce_id'].dropna().nunique():,} | {site_lookup['site_id'].dropna().nunique():,} |\n")
    md.append(f"| ce_site_search_master_v2 | {len(search_master):,} | {search_master['ce_id'].dropna().nunique():,} | {search_master['site_id'].dropna().nunique():,} |\n\n")

    md.append("## Dataset fetch summary\n")
    md.append("See `data/audit/tda_5yr_ingestion_audit.csv` for the per-dataset row.\n\n")

    md.append("## Summer meal reported meals by canonical_year and program_type\n")
    if not meals.empty and "canonical_year" in meals.columns:
        m2 = meals.groupby(["canonical_year", "program_type"], dropna=False)["total_meals"].sum().reset_index()
        md.append("| Year | Program | Reported meals |\n|---|---|---:|\n")
        for _, r in m2.iterrows():
            md.append(f"| {r['canonical_year']} | {r['program_type']} | {int(r['total_meals']):,} |\n")
        md.append("\n")

    md.append("## Summer reimbursements by canonical_year and program_type\n")
    if not reimb.empty:
        r2 = reimb.groupby(["canonical_year", "program_type"], dropna=False)["total_reimbursement"].sum().reset_index()
        md.append("| Year | Program | Total reimbursement |\n|---|---|---:|\n")
        for _, r in r2.iterrows():
            md.append(f"| {r['canonical_year']} | {r['program_type']} | ${int(r['total_reimbursement']):,} |\n")
        md.append("\n")

    md.append("## Summer contact records by canonical_year\n")
    md.append(years_breakdown(summer_contacts, "canonical_year"))
    md.append("\n## SNP contact records by canonical_year (school year end)\n")
    md.append(years_breakdown(snp_contacts, "canonical_year"))
    md.append("\n## SNP reimbursement records by canonical_year (school year end)\n")
    md.append(years_breakdown(snp_reimb, "canonical_year"))

    md.append("\n## Non-congregate status distribution (search master)\n")
    md.append(nc_table)
    md.append(f"\nTotal sites with verified NC source match: **{int((search_master['non_congregate_status'].astype(str).str.strip() != 'Unknown').sum()):,}**\n")
    md.append(f"Total confirmed non-congregate sites: **{int(search_master['non_congregate_status'].astype(str).str.contains('Non-Congregate', na=False).sum()):,}**\n")

    # --- NC-from-name diagnostics ---
    md.append("\n## NC_ prefix detection (site_name)\n")
    if "nc_flag_from_name" in search_master.columns:
        name_nc_mask = search_master["nc_flag_from_name"].fillna(False).astype(bool)
        name_nc_count = int(name_nc_mask.sum())
        md.append(f"Distinct (ce_id, site_id) keys with NC_ prefix in ANY year: **{name_nc_count:,}**\n\n")

        # Year-by-year prefix appearances aggregated across canonical sources
        per_year_counts = {}
        for src_name, src in [
            ("summer_meal_counts", meals),
            ("summer_contacts", summer_contacts),
            ("snp_contacts", snp_contacts),
        ]:
            if src is None or src.empty or "nc_from_site_name" not in src.columns:
                continue
            flag = src["nc_from_site_name"]
            if flag.dtype != bool:
                flag = (
                    flag.astype(str).str.strip().str.lower()
                    .isin({"true", "1", "yes"})
                )
            year_counts = (
                src.loc[flag.fillna(False), "canonical_year"]
                .dropna().astype(int).value_counts().sort_index()
            )
            per_year_counts[src_name] = year_counts

        if per_year_counts:
            years = sorted({y for s in per_year_counts.values() for y in s.index})
            md.append("| Year | summer_meal_counts | summer_contacts | snp_contacts |\n|---|---:|---:|---:|\n")
            for y in years:
                mc = int(per_year_counts.get("summer_meal_counts", {}).get(y, 0))
                sc = int(per_year_counts.get("summer_contacts", {}).get(y, 0))
                snc = int(per_year_counts.get("snp_contacts", {}).get(y, 0))
                md.append(f"| {y} | {mc:,} | {sc:,} | {snc:,} |\n")
            md.append("\n")

        # Overlap with MealServiceType-derived NC
        mst_nc_mask = search_master["non_congregate_status"].astype(str).str.contains("Non-Congregate", na=False)
        # mst-specific NC sites are those whose status was set from the MealServiceType
        # field rather than from the site name. Approximation: source string contains "MealServiceType".
        if "non_congregate_source" in search_master.columns:
            mst_source_mask = (
                search_master["non_congregate_source"].astype(str)
                .str.contains("MealServiceType", na=False)
            )
            overlap_count = int((name_nc_mask & mst_source_mask).sum())
            mst_only_count = int((mst_source_mask & ~name_nc_mask & mst_nc_mask).sum())
            name_only_count = int((name_nc_mask & ~mst_source_mask).sum())
            md.append("### Overlap with MealServiceType-derived NC\n")
            md.append("| Detection | Sites |\n|---|---:|\n")
            md.append(f"| MealServiceType non-congregate AND NC_ prefix (both signals agree) | {overlap_count:,} |\n")
            md.append(f"| MealServiceType non-congregate only | {mst_only_count:,} |\n")
            md.append(f"| NC_ prefix only | {name_only_count:,} |\n\n")

    md.append("## Known limitations\n")
    md.append("- Verified non-congregate status from `MealServiceType` is available only where public TX Open Data includes that field, currently limited to the 2022–2023 contact datasets. The NC_ prefix convention extends NC detection to other years but is still a TDA naming convention, not an exhaustive list. **Unknown does not mean congregate.**\n")
    md.append("- Reported meals are not unique children served.\n")
    md.append("- Rural/Urban indicator (`rural_urban_status`) is available only from `8ih4-zp65`, so coverage is limited to ~1,965 SFSP 2022–2023 sites.\n")
    md.append("- 24ie-9cft (All Summer Sites 2023) is cross-listed: it serves both as the 2023 summer contact source and as one of the three NC sources. It is fetched once and saved into both category folders.\n")
    md.append("- For each site in the lookup, address/contact/operation fields are taken from the *latest* available summer contact record; SNP flags from the *latest* available SNP contact record. Older years' values are used only when the latest year's value is missing.\n")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("".join(md))
    print(f"Wrote validation report -> {OUT_REPORT}")


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main() -> None:
    print("SSO vs SFSP Texas Capstone - v2 lookup build")
    print("=" * 80)

    print("\nLoading canonical tables ...")
    meals = load_csv_with_ids(IN_MEALS)
    reimb = load_csv_with_ids(IN_REIMB)
    summer_contacts = load_csv_with_ids(IN_SUMMER_CONTACTS)
    snp_contacts = load_csv_with_ids(IN_SNP_CONTACTS)
    snp_reimb = load_csv_with_ids(IN_SNP_REIMB)
    print(f"  meals: {len(meals):,}  reimb: {len(reimb):,}  "
          f"summer_contacts: {len(summer_contacts):,}  "
          f"snp_contacts: {len(snp_contacts):,}  snp_reimb: {len(snp_reimb):,}")

    print("\nDeduplicating contacts (latest year per (ce_id, site_id)) ...")
    summer_contacts_d = dedup_summer_contacts(summer_contacts)
    snp_contacts_d = dedup_snp_contacts(snp_contacts)
    print(f"  summer_contacts_d: {len(summer_contacts_d):,}  snp_contacts_d: {len(snp_contacts_d):,}")

    print("\nSummarizing meals by site / CE ...")
    meals_site = summarize_meals_by_site(meals)
    meals_ce = summarize_meals_by_ce(meals)
    print(f"  meals_site: {len(meals_site):,}  meals_ce: {len(meals_ce):,}")

    print("\nBuilding NC enrichment from 3 sources ...")
    nc = build_nc_enrichment_from_raw()
    print(f"  NC deduped: {len(nc):,} unique (ce_id, site_id)")

    print("\nAggregating NC_ prefix flag across canonical sources ...")
    nc_name_agg = aggregate_nc_from_name(meals, summer_contacts, snp_contacts)
    print(f"  NC_-prefix sites (any year): {len(nc_name_agg):,}")

    print("\nBuilding site lookup ...")
    site_lookup = build_site_lookup(summer_contacts_d, snp_contacts_d, meals_site, snp_reimb, nc, nc_name_agg)
    print(f"  site_lookup_master_v2: {len(site_lookup):,} rows")
    site_lookup.to_csv(OUT_SITE, index=False)
    print(f"  wrote {OUT_SITE}")

    print("\nBuilding CE lookup ...")
    ce_lookup = build_ce_lookup(site_lookup, meals_ce, summer_contacts_d, snp_contacts_d)
    ce_lookup.to_csv(OUT_CE, index=False)
    print(f"  ce_lookup_master_v2: {len(ce_lookup):,} rows -> {OUT_CE}")

    print("\nBuilding search master ...")
    search_master = build_search_master(site_lookup, ce_lookup)
    search_master.to_csv(OUT_SEARCH, index=False)
    print(f"  ce_site_search_master_v2: {len(search_master):,} rows -> {OUT_SEARCH}")

    print("\nBuilding join audit ...")
    audit = build_join_audit(meals, reimb, summer_contacts, snp_contacts, snp_reimb,
                              nc, ce_lookup, site_lookup, search_master)
    audit.to_csv(OUT_AUDIT, index=False)
    print(f"  wrote {OUT_AUDIT}")
    print(audit.to_string(index=False))

    print("\nWriting validation report ...")
    write_validation_report(meals, reimb, summer_contacts, snp_contacts, snp_reimb,
                            nc, ce_lookup, site_lookup, search_master)

    # Quick diagnostics
    nc_status_counts = search_master["non_congregate_status"].fillna("Unknown").value_counts()
    print("\nSearch master non_congregate_status counts:")
    print(nc_status_counts.to_string())

    print("\nDONE")


if __name__ == "__main__":
    main()
