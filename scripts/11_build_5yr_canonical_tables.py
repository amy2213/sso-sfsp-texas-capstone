"""
SSO vs SFSP Texas Capstone
11_build_5yr_canonical_tables.py

Builds five normalized canonical tables from data/raw_v2/ (produced by
scripts/10). Uses the v2 registry for label/period/canonical_year
metadata. Schema differences across years are absorbed via candidate-
column lookups (find_first_col).

Outputs:
  data/clean_v2/summer_meals_5yr_master.csv
  data/clean_v2/summer_reimbursements_5yr_master.csv
  data/clean_v2/summer_contacts_5yr_master.csv
  data/clean_v2/snp_contacts_5yr_master.csv
  data/clean_v2/snp_reimbursements_5yr_master.csv
  data/audit/tda_5yr_canonical_build_audit.csv

Wording: "reported meals" throughout. NC verification scope is
2022-2023 only.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


CONFIG_PATH = os.path.join("config", "tda_5yr_dataset_registry.json")
DATA_RAW_V2 = "data/raw_v2"
DATA_CLEAN_V2 = "data/clean_v2"
DATA_AUDIT = "data/audit"

OUT_MEALS = os.path.join(DATA_CLEAN_V2, "summer_meals_5yr_master.csv")
OUT_REIMB = os.path.join(DATA_CLEAN_V2, "summer_reimbursements_5yr_master.csv")
OUT_SUMMER_CONTACTS = os.path.join(DATA_CLEAN_V2, "summer_contacts_5yr_master.csv")
OUT_SNP_CONTACTS = os.path.join(DATA_CLEAN_V2, "snp_contacts_5yr_master.csv")
OUT_SNP_REIMB = os.path.join(DATA_CLEAN_V2, "snp_reimbursements_5yr_master.csv")
OUT_AUDIT = os.path.join(DATA_AUDIT, "tda_5yr_canonical_build_audit.csv")

for folder in [DATA_CLEAN_V2, DATA_AUDIT]:
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


def find_first_col(d: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in d.columns:
            return c
    return None


def column_or_zero(d: pd.DataFrame, name: Optional[str]) -> pd.Series:
    if name and name in d.columns:
        return to_number(d[name]).fillna(0)
    return pd.Series([0.0] * len(d), index=d.index, dtype="float64")


def safe_date(value):
    if pd.isna(value):
        return pd.NA
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "<na>"}:
        return pd.NA
    # Strip any time component for stable display, but keep ISO-ish format
    return s.split("T")[0] if "T" in s else s


def normalize_text(value):
    if pd.isna(value):
        return value
    s = re.sub(r"\s+", " ", str(value)).strip()
    return s if s and s.lower() not in {"nan", "none", "<na>"} else pd.NA


def is_nc_prefix(value) -> bool:
    """True if the value (a site name) begins with the case-insensitive
    prefix `NC_`. Specifically matches `NC_` with the underscore so a name
    like `NCI CHARTER SCHOOL` is NOT flagged."""
    if pd.isna(value):
        return False
    return str(value).upper().startswith("NC_")


def strip_nc_prefix(value):
    """Return the site name with a leading `NC_` (case-insensitive)
    removed. Original casing of the remainder is preserved."""
    if pd.isna(value):
        return value
    s = str(value)
    if s.upper().startswith("NC_"):
        return s[3:].strip()
    return value


def classify_program_value(value) -> str:
    v = (str(value or "").upper()).replace("_", " ")
    if "SSO" in v or "SEAMLESS" in v:
        return "SSO"
    if "SFSP" in v or "SUMMER FOOD" in v:
        return "SFSP"
    return "UNKNOWN"


def derive_verified_nc_status(value) -> str:
    if pd.isna(value):
        return "Unknown"
    s = str(value)
    if "Non-Congregate" in s:
        return s
    if "Congregate" in s:
        return "Congregate"
    return "Unknown"


# --------------------------------------------------------------------
# Load registry
# --------------------------------------------------------------------

def load_registry() -> List[dict]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["datasets"]


def registry_for_category(reg: List[dict], category: str) -> List[dict]:
    return [e for e in reg if e["category"] == category]


# --------------------------------------------------------------------
# Builders — summer meal counts
# --------------------------------------------------------------------

def standardize_meal_counts_record(entry: dict, df: pd.DataFrame) -> pd.DataFrame:
    d = normalize_columns(df)

    ce_id_col = find_first_col(d, ["ceid", "ce_id"])
    ce_name_col = find_first_col(d, ["cename", "ce_name"])
    site_id_col = find_first_col(d, ["siteid", "site_id"])
    site_name_col = find_first_col(d, ["sitename", "site_name"])
    cecounty_col = find_first_col(d, ["cecounty", "ce_county"])
    sitecounty_col = find_first_col(d, ["sitecounty", "site_county"])
    region_col = find_first_col(d, ["tdaregion", "region", "esc"])
    claim_col = find_first_col(d, ["claimdate", "claim_date"])
    py_col = find_first_col(d, ["programyear", "program_year"])
    program_col = find_first_col(d, ["program", "program_type"])

    out = pd.DataFrame(index=d.index)
    out["source_dataset_id"] = entry["dataset_id"]
    out["source_label"] = entry["label"]
    out["period"] = entry["period"]
    out["canonical_year"] = entry["canonical_year"]
    out["program_year"] = d[py_col] if py_col else entry["period"]
    out["program_type"] = (
        d[program_col].apply(classify_program_value)
        if program_col
        else (entry.get("program_type") or "UNKNOWN")
    )
    out["ce_id"] = standardize_id(d[ce_id_col]) if ce_id_col else pd.NA
    out["ce_name"] = d[ce_name_col].apply(normalize_text) if ce_name_col else pd.NA
    out["site_id"] = standardize_id(d[site_id_col]) if site_id_col else pd.NA
    out["site_name"] = d[site_name_col].apply(normalize_text) if site_name_col else pd.NA
    out["nc_from_site_name"] = out["site_name"].apply(is_nc_prefix)
    out["site_name_base"] = out["site_name"].apply(strip_nc_prefix)
    out["ce_county"] = d[cecounty_col].apply(normalize_text) if cecounty_col else pd.NA
    out["site_county"] = d[sitecounty_col].apply(normalize_text) if sitecounty_col else pd.NA
    out["region"] = d[region_col] if region_col else pd.NA
    out["claim_date"] = d[claim_col].apply(safe_date) if claim_col else pd.NA

    # Meals
    breakfast_col = find_first_col(d, ["breakfasttotal", "breakfast"])
    lunch_col = find_first_col(d, ["lunchtotal", "lunch"])
    supper_col = find_first_col(d, ["suppertotal", "supper"])
    out["breakfast_meals"] = column_or_zero(d, breakfast_col)
    out["lunch_meals"] = column_or_zero(d, lunch_col)
    out["supper_meals"] = column_or_zero(d, supper_col)

    am_col = "amsnacktotal" if "amsnacktotal" in d.columns else None
    pm_col = "pmsnacktotal" if "pmsnacktotal" in d.columns else None
    if am_col or pm_col:
        out["snack_meals"] = column_or_zero(d, am_col) + column_or_zero(d, pm_col)
    elif "totalsnacks" in d.columns:
        out["snack_meals"] = column_or_zero(d, "totalsnacks")
    else:
        out["snack_meals"] = 0.0

    total_col = find_first_col(d, ["totalmealssnacks", "totalmeals_snacks", "total_meals", "totalmeals"])
    if total_col:
        out["total_meals"] = to_number(d[total_col]).fillna(0)
    else:
        out["total_meals"] = (
            out["breakfast_meals"] + out["lunch_meals"]
            + out["snack_meals"] + out["supper_meals"]
        )

    # Days
    out["breakfast_days"] = to_number(d["breakfastdays"]) if "breakfastdays" in d.columns else pd.NA
    out["lunch_days"] = to_number(d["lunchdays"]) if "lunchdays" in d.columns else pd.NA
    out["supper_days"] = to_number(d["supperdays"]) if "supperdays" in d.columns else pd.NA
    am_days = column_or_zero(d, "amsnackdays" if "amsnackdays" in d.columns else None)
    pm_days = column_or_zero(d, "pmsnackdays" if "pmsnackdays" in d.columns else None)
    out["snack_days"] = am_days + pm_days
    # Total service days: prefer lunch, then breakfast, then supper, then snack
    out["total_service_days"] = (
        out["lunch_days"]
        .fillna(out["breakfast_days"])
        .fillna(out["supper_days"])
        .fillna(out["snack_days"])
    )

    out["data_quality_flags"] = out.apply(_meal_row_flags, axis=1)
    return out


def _meal_row_flags(row: pd.Series) -> str:
    flags = []
    if pd.isna(row.get("ce_id")) or str(row.get("ce_id")).strip() == "":
        flags.append("missing_ce_id")
    if pd.isna(row.get("site_id")) or str(row.get("site_id")).strip() == "":
        flags.append("missing_site_id")
    if pd.isna(row.get("site_name")) or str(row.get("site_name")).strip() == "":
        flags.append("missing_site_name")
    if pd.isna(row.get("site_county")) or str(row.get("site_county")).strip() == "":
        flags.append("missing_site_county")
    if str(row.get("program_type", "")).upper() == "UNKNOWN":
        flags.append("unknown_program_type")
    total = row.get("total_meals")
    if pd.notna(total):
        if total == 0:
            flags.append("zero_total_meals")
        elif total < 0:
            flags.append("negative_total_meals")
    return "|".join(flags) if flags else "ok"


# --------------------------------------------------------------------
# Builders — summer reimbursements (SSO + SFSP)
# --------------------------------------------------------------------

def standardize_reimbursement_record(entry: dict, df: pd.DataFrame) -> pd.DataFrame:
    d = normalize_columns(df)

    ce_id_col = find_first_col(d, ["ceid", "ce_id"])
    ce_name_col = find_first_col(d, ["cename", "ce_name"])
    cecounty_col = find_first_col(d, ["cecounty", "ce_county"])
    region_col = find_first_col(d, ["tdaregion", "region", "esc"])
    claim_col = find_first_col(d, ["claimdate", "claim_date"])
    py_col = find_first_col(d, ["programyear", "program_year"])
    program_col = find_first_col(d, ["program", "program_type"])

    out = pd.DataFrame(index=d.index)
    out["source_dataset_id"] = entry["dataset_id"]
    out["source_label"] = entry["label"]
    out["period"] = entry["period"]
    out["canonical_year"] = entry["canonical_year"]
    out["program_year"] = d[py_col] if py_col else entry["period"]
    if program_col:
        out["program_type"] = d[program_col].apply(classify_program_value)
    else:
        out["program_type"] = entry.get("program_type") or "UNKNOWN"
    out["ce_id"] = standardize_id(d[ce_id_col]) if ce_id_col else pd.NA
    out["ce_name"] = d[ce_name_col].apply(normalize_text) if ce_name_col else pd.NA
    out["ce_county"] = d[cecounty_col].apply(normalize_text) if cecounty_col else pd.NA
    out["region"] = d[region_col] if region_col else pd.NA
    out["claim_date"] = d[claim_col].apply(safe_date) if claim_col else pd.NA

    bf_m = column_or_zero(d, "breakfastmealsreimbursed" if "breakfastmealsreimbursed" in d.columns else None)
    lu_m = column_or_zero(d, "lunchmealsreimbursed" if "lunchmealsreimbursed" in d.columns else None)
    am_m = column_or_zero(d, "amsnackmealsreimbursed" if "amsnackmealsreimbursed" in d.columns else None)
    pm_m = column_or_zero(d, "pmsnackmealsreimbursed" if "pmsnackmealsreimbursed" in d.columns else None)
    su_m = column_or_zero(d, "suppermealsreimbursed" if "suppermealsreimbursed" in d.columns else None)
    snack_m = am_m + pm_m

    has_any_m = any(c in d.columns for c in [
        "breakfastmealsreimbursed", "lunchmealsreimbursed",
        "amsnackmealsreimbursed", "pmsnackmealsreimbursed", "suppermealsreimbursed",
    ])
    out["breakfast_meals_reimbursed"] = bf_m
    out["lunch_meals_reimbursed"] = lu_m
    out["snack_meals_reimbursed"] = snack_m
    out["supper_meals_reimbursed"] = su_m
    out["total_meals_reimbursed"] = (
        bf_m + lu_m + snack_m + su_m if has_any_m else pd.NA
    )

    bf_r = column_or_zero(d, "breakfastreimbursement" if "breakfastreimbursement" in d.columns else None)
    lu_r = column_or_zero(d, "lunchreimbursement" if "lunchreimbursement" in d.columns else None)
    am_r = column_or_zero(d, "amsnackreimbursement" if "amsnackreimbursement" in d.columns else None)
    pm_r = column_or_zero(d, "pmsnackreimbursement" if "pmsnackreimbursement" in d.columns else None)
    su_r = column_or_zero(d, "supperreimbursement" if "supperreimbursement" in d.columns else None)
    snack_r = am_r + pm_r

    out["breakfast_reimbursement"] = bf_r
    out["lunch_reimbursement"] = lu_r
    out["snack_reimbursement"] = snack_r
    out["supper_reimbursement"] = su_r

    total_r_col = find_first_col(d, ["totalreimbursement", "total_reimbursement"])
    if total_r_col:
        out["total_reimbursement"] = to_number(d[total_r_col])
    else:
        out["total_reimbursement"] = bf_r + lu_r + snack_r + su_r

    denom = pd.to_numeric(out["total_meals_reimbursed"], errors="coerce").replace({0: pd.NA})
    out["reimbursement_per_meal"] = (
        pd.to_numeric(out["total_reimbursement"], errors="coerce") / denom
    )

    out["data_quality_flags"] = out.apply(_reimb_row_flags, axis=1)
    return out


def _reimb_row_flags(row: pd.Series) -> str:
    flags = []
    if pd.isna(row.get("ce_id")) or str(row.get("ce_id")).strip() == "":
        flags.append("missing_ce_id")
    if pd.isna(row.get("ce_name")) or str(row.get("ce_name")).strip() == "":
        flags.append("missing_ce_name")
    if pd.isna(row.get("total_reimbursement")):
        flags.append("missing_total_reimbursement")
    tm = row.get("total_meals_reimbursed")
    if pd.notna(tm) and tm == 0:
        flags.append("zero_total_meals_reimbursed")
    tr = row.get("total_reimbursement")
    if pd.notna(tr) and tr < 0:
        flags.append("negative_total_reimbursement")
    rpm = row.get("reimbursement_per_meal")
    if pd.notna(rpm) and rpm > 20:
        flags.append("suspicious_reimbursement_per_meal_over_20")
    return "|".join(flags) if flags else "ok"


# --------------------------------------------------------------------
# Builders — summer contacts
# --------------------------------------------------------------------

import ast


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


def join_name(*parts):
    bits = []
    for p in parts:
        if pd.isna(p):
            continue
        s = str(p).strip()
        if s and s.lower() not in {"nan", "none", "<na>"}:
            bits.append(s)
    return " ".join(bits) if bits else pd.NA


def standardize_summer_contact_record(entry: dict, df: pd.DataFrame) -> pd.DataFrame:
    d = normalize_columns(df)

    out = pd.DataFrame(index=d.index)
    out["source_dataset_id"] = entry["dataset_id"]
    out["source_label"] = entry["label"]
    out["period"] = entry["period"]
    out["canonical_year"] = entry["canonical_year"]

    py_col = find_first_col(d, ["programyear", "program_year"])
    out["program_year"] = d[py_col] if py_col else entry["period"]

    program_col = find_first_col(d, ["program", "program_type"])
    if program_col:
        out["program_type"] = d[program_col].apply(classify_program_value)
    else:
        out["program_type"] = entry.get("program_type") or "UNKNOWN"

    out["ce_id"] = standardize_id(d["ceid"]) if "ceid" in d.columns else pd.NA
    out["ce_name"] = d["cename"].apply(normalize_text) if "cename" in d.columns else pd.NA
    out["site_id"] = standardize_id(d["siteid"]) if "siteid" in d.columns else pd.NA
    out["site_name"] = d["sitename"].apply(normalize_text) if "sitename" in d.columns else pd.NA
    out["nc_from_site_name"] = out["site_name"].apply(is_nc_prefix)
    out["site_name_base"] = out["site_name"].apply(strip_nc_prefix)

    out["site_type"] = d["sitetype"].apply(normalize_text) if "sitetype" in d.columns else pd.NA
    out["type_of_agency"] = d["typeofagency"].apply(normalize_text) if "typeofagency" in d.columns else pd.NA
    out["type_of_org"] = d["typeoforg"].apply(normalize_text) if "typeoforg" in d.columns else pd.NA

    addr_map = {
        "ce_street_address_line_1": "cestreetaddressline1",
        "ce_street_address_line_2": "cestreetaddressline2",
        "ce_city": "cestreetaddresscity",
        "ce_state": "cestreetaddressstate",
        "ce_zip": "cestreetaddresszipcode",
        "ce_mailing_address_line_1": "cemailingaddressline1",
        "ce_mailing_address_line_2": "cemailingaddressline2",
        "ce_mailing_city": "cemailingaddresscity",
        "ce_mailing_state": "cemailingaddressstate",
        "ce_mailing_zip": "cemailingaddresszipcode",
        "site_street_address_line_1": "sitestreetaddressline1",
        "site_street_address_line_2": "sitestreetaddressline2",
        "site_city": "sitestreetaddresscity",
        "site_state": "sitestreetaddressstate",
        "site_zip": "sitestreetaddresszipcode",
    }
    for tgt, src in addr_map.items():
        out[tgt] = d[src].apply(normalize_text) if src in d.columns else pd.NA

    out["site_county"] = d["sitecounty"].apply(normalize_text) if "sitecounty" in d.columns else pd.NA
    out["ce_county"] = d["cecounty"].apply(normalize_text) if "cecounty" in d.columns else pd.NA
    out["region"] = d["tdaregion"] if "tdaregion" in d.columns else pd.NA

    geo_col = find_first_col(d, ["geolocation", "geoloc_data", "geocoded_column"])
    if geo_col:
        lats, lons = [], []
        for v in d[geo_col]:
            lat, lon = parse_geo(v)
            lats.append(lat)
            lons.append(lon)
        out["latitude"] = lats
        out["longitude"] = lons
    else:
        out["latitude"] = pd.NA
        out["longitude"] = pd.NA

    # Contact people - join salutation+first+last for the name, take title/email/phone as-is
    def has(c): return c in d.columns
    out["program_administrator_name"] = (
        [join_name(s, f, l) for s, f, l in zip(
            d.get("progradministratorsalutation", pd.Series([pd.NA]*len(d))),
            d.get("progradministratorfirstname", pd.Series([pd.NA]*len(d))),
            d.get("progradministratorlastname", pd.Series([pd.NA]*len(d))),
        )]
        if has("progradministratorfirstname") or has("progradministratorlastname")
        else [pd.NA]*len(d)
    )
    out["program_administrator_email"] = d["progradministratoremail"].apply(normalize_text) if has("progradministratoremail") else pd.NA
    out["program_administrator_phone"] = d["progradministratorphone"].apply(normalize_text) if has("progradministratorphone") else pd.NA

    out["program_coordinator_name"] = (
        [join_name(s, f, l) for s, f, l in zip(
            d.get("progrcoordinatorsalutation", pd.Series([pd.NA]*len(d))),
            d.get("progrcoordinatorfirstname", pd.Series([pd.NA]*len(d))),
            d.get("progrcoordinatorlastname", pd.Series([pd.NA]*len(d))),
        )]
        if has("progrcoordinatorfirstname") or has("progrcoordinatorlastname")
        else [pd.NA]*len(d)
    )
    out["program_coordinator_email"] = d["progrcoordinatoremail"].apply(normalize_text) if has("progrcoordinatoremail") else pd.NA
    out["program_coordinator_phone"] = d["progrcoordinatorphone"].apply(normalize_text) if has("progrcoordinatorphone") else pd.NA

    out["site_contact_name"] = (
        [join_name(s, f, l) for s, f, l in zip(
            d.get("sitecontactsalutation", pd.Series([pd.NA]*len(d))),
            d.get("sitecontactfirstname", pd.Series([pd.NA]*len(d))),
            d.get("sitecontactlastname", pd.Series([pd.NA]*len(d))),
        )]
        if has("sitecontactfirstname") or has("sitecontactlastname")
        else [pd.NA]*len(d)
    )
    out["site_contact_title"] = d["sitecontacttitleposition"].apply(normalize_text) if has("sitecontacttitleposition") else pd.NA
    out["site_contact_email"] = d["sitecontactemail"].apply(normalize_text) if has("sitecontactemail") else pd.NA
    out["site_contact_phone"] = d["sitecontactphone"].apply(normalize_text) if has("sitecontactphone") else pd.NA

    out["operation_start_date"] = d["operationstartdate"].apply(safe_date) if has("operationstartdate") else pd.NA
    out["operation_end_date"] = d["operationenddate"].apply(safe_date) if has("operationenddate") else pd.NA
    out["site_start_date"] = d["sitestartdate"].apply(safe_date) if has("sitestartdate") else pd.NA
    out["site_end_date"] = d["siteenddate"].apply(safe_date) if has("siteenddate") else pd.NA
    out["days_of_operation"] = d["daysofoperation"].apply(normalize_text) if has("daysofoperation") else pd.NA
    out["meal_types_served"] = d["mealtypesserved"].apply(normalize_text) if has("mealtypesserved") else pd.NA

    out["breakfast_time"] = d["breakfasttime"].apply(normalize_text) if has("breakfasttime") else pd.NA
    out["lunch_time"] = d["lunchtime"].apply(normalize_text) if has("lunchtime") else pd.NA
    out["supper_time"] = d["suppertime"].apply(normalize_text) if has("suppertime") else pd.NA
    out["am_snack_time"] = d["amsnacktime"].apply(normalize_text) if has("amsnacktime") else pd.NA
    out["pm_snack_time"] = d["pmsnacktime"].apply(normalize_text) if has("pmsnacktime") else pd.NA

    out["meal_service_type_public"] = d["mealservicetype"].apply(normalize_text) if has("mealservicetype") else pd.NA
    out["rural_urban_status"] = d["ruralorurbancode"].apply(normalize_text) if has("ruralorurbancode") else pd.NA

    out["data_quality_flags"] = "ok"
    return out


# --------------------------------------------------------------------
# Builders — SNP contacts
# --------------------------------------------------------------------

def standardize_snp_contact_record(entry: dict, df: pd.DataFrame) -> pd.DataFrame:
    d = normalize_columns(df)

    out = pd.DataFrame(index=d.index)
    out["source_dataset_id"] = entry["dataset_id"]
    out["source_label"] = entry["label"]
    out["school_year"] = entry["period"]
    out["canonical_year"] = entry["canonical_year"]

    out["ce_id"] = standardize_id(d["ceid"]) if "ceid" in d.columns else pd.NA
    out["ce_name"] = d["cename"].apply(normalize_text) if "cename" in d.columns else pd.NA
    out["site_id"] = standardize_id(d["siteid"]) if "siteid" in d.columns else pd.NA
    out["site_name"] = d["sitename"].apply(normalize_text) if "sitename" in d.columns else pd.NA
    out["nc_from_site_name"] = out["site_name"].apply(is_nc_prefix)
    out["site_name_base"] = out["site_name"].apply(strip_nc_prefix)

    addr_map = {
        "ce_street_address_line_1": "cestreetaddressline1",
        "ce_city": "cestreetaddresscity",
        "ce_state": "cestreetaddressstate",
        "ce_zip": "cestreetaddresszipcode",
        "site_street_address_line_1": "sitestreetaddressline1",
        "site_city": "sitestreetaddresscity",
        "site_state": "sitestreetaddressstate",
        "site_zip": "sitestreetaddresszipcode",
    }
    for tgt, src in addr_map.items():
        out[tgt] = d[src].apply(normalize_text) if src in d.columns else pd.NA

    out["site_county"] = d["sitecounty"].apply(normalize_text) if "sitecounty" in d.columns else pd.NA
    out["region"] = d["tdaregion"] if "tdaregion" in d.columns else pd.NA

    geo_col = find_first_col(d, ["geolocation", "geoloc_data", "geocoded_column"])
    if geo_col:
        lats, lons = [], []
        for v in d[geo_col]:
            lat, lon = parse_geo(v)
            lats.append(lat)
            lons.append(lon)
        out["latitude"] = lats
        out["longitude"] = lons
    else:
        out["latitude"] = pd.NA
        out["longitude"] = pd.NA

    def has(c): return c in d.columns
    out["superintendent_name"] = (
        [join_name(s, f, l) for s, f, l in zip(
            d.get("superintendentsalutation", pd.Series([pd.NA]*len(d))),
            d.get("superintendentfirstname", pd.Series([pd.NA]*len(d))),
            d.get("superintendentlastname", pd.Series([pd.NA]*len(d))),
        )]
        if has("superintendentfirstname") or has("superintendentlastname")
        else [pd.NA]*len(d)
    )
    out["superintendent_email"] = d["superintendentemail"].apply(normalize_text) if has("superintendentemail") else pd.NA
    out["superintendent_phone"] = d["superintendentphone"].apply(normalize_text) if has("superintendentphone") else pd.NA

    out["child_nutrition_director_name"] = (
        [join_name(s, f, l) for s, f, l in zip(
            d.get("childnutdirsalutation", pd.Series([pd.NA]*len(d))),
            d.get("childnutdirfirstname", pd.Series([pd.NA]*len(d))),
            d.get("childnutdirlastname", pd.Series([pd.NA]*len(d))),
        )]
        if has("childnutdirfirstname") or has("childnutdirlastname")
        else [pd.NA]*len(d)
    )
    out["child_nutrition_director_email"] = d["childnutdiremail"].apply(normalize_text) if has("childnutdiremail") else pd.NA
    out["child_nutrition_director_phone"] = d["childnutdirphone"].apply(normalize_text) if has("childnutdirphone") else pd.NA

    flag_map = {
        "school_breakfast_program": "schoolbreakfastprogram",
        "national_school_lunch_program": "nationalschoollunchprogram",
        "afterschool_care_program": "afterschoolcareprogram",
        "special_milk_program": "specialmilkprogram",
        "ffvp_approved": "ffvpapproved",
        "severe_need_breakfast": "severeneedbreakfast",
        "universal_free_breakfast": "universalfreebreakfast",
        "managed_by_fsmc": "managedbyfsmc",
        "breakfast_pricing": "breakfastpricing",
        "lunch_pricing": "lunchpricing",
        "snack_pricing": "snackpricing",
        "area_eligible_snack": "areaeligiblesnack",
        "site_isp": "siteisp",
        "cep": "cep",
        "provision2": "provision2",
    }
    for tgt, src in flag_map.items():
        out[tgt] = d[src].apply(normalize_text) if src in d.columns else pd.NA

    grade_cols = [c for c in d.columns if c.startswith("grade")]

    def grade_span(row):
        labels = []
        for c in grade_cols:
            v = row.get(c)
            if pd.notna(v) and str(v).strip().upper() == "Y":
                label = c.replace("grade", "")
                labels.append(label.upper() if label else "ALL")
        return ", ".join(labels) if labels else pd.NA

    if grade_cols:
        out["grade_span"] = d.apply(grade_span, axis=1)
    else:
        out["grade_span"] = pd.NA

    out["data_quality_flags"] = "ok"
    return out


# --------------------------------------------------------------------
# Builders — SNP reimbursements
# --------------------------------------------------------------------

def standardize_snp_reimbursement_record(entry: dict, df: pd.DataFrame) -> pd.DataFrame:
    d = normalize_columns(df)

    out = pd.DataFrame(index=d.index)
    out["source_dataset_id"] = entry["dataset_id"]
    out["source_label"] = entry["label"]
    out["school_year"] = entry["period"]
    out["canonical_year"] = entry["canonical_year"]

    out["ce_id"] = standardize_id(d["ceid"]) if "ceid" in d.columns else pd.NA
    out["ce_name"] = d["cename"].apply(normalize_text) if "cename" in d.columns else pd.NA
    out["site_id"] = standardize_id(d["siteid"]) if "siteid" in d.columns else pd.NA
    out["region"] = d["tdaregion"] if "tdaregion" in d.columns else pd.NA

    claim_col = find_first_col(d, ["claimdate", "claim_date"])
    out["claim_date"] = d[claim_col].apply(safe_date) if claim_col else pd.NA

    total_r_col = find_first_col(d, ["totalreimbursement", "total_reimbursement"])
    if total_r_col:
        out["total_reimbursement"] = to_number(d[total_r_col])
    else:
        # Sum per-meal reimbursements if individual columns are present
        bf_r = column_or_zero(d, "breakfastreimbursement" if "breakfastreimbursement" in d.columns else None)
        lu_r = column_or_zero(d, "lunchreimbursement" if "lunchreimbursement" in d.columns else None)
        sn_r = column_or_zero(d, "snackreimbursement" if "snackreimbursement" in d.columns else None)
        mi_r = column_or_zero(d, "milkreimbursement" if "milkreimbursement" in d.columns else None)
        out["total_reimbursement"] = bf_r + lu_r + sn_r + mi_r

    total_m_col = find_first_col(d, ["totalmealssnacks", "totalmeals_snacks", "total_meals"])
    if total_m_col:
        out["total_meals_reimbursed"] = to_number(d[total_m_col])
    else:
        bf = column_or_zero(d, "breakfasttotal" if "breakfasttotal" in d.columns else None)
        lu = column_or_zero(d, "lunchtotal" if "lunchtotal" in d.columns else None)
        sn = column_or_zero(d, "snacktotal" if "snacktotal" in d.columns else None)
        mi = column_or_zero(d, "milktotal" if "milktotal" in d.columns else None)
        out["total_meals_reimbursed"] = bf + lu + sn + mi

    denom = pd.to_numeric(out["total_meals_reimbursed"], errors="coerce").replace({0: pd.NA})
    out["reimbursement_per_meal"] = (
        pd.to_numeric(out["total_reimbursement"], errors="coerce") / denom
    )

    out["data_quality_flags"] = out.apply(_snp_reimb_row_flags, axis=1)
    return out


def _snp_reimb_row_flags(row: pd.Series) -> str:
    flags = []
    if pd.isna(row.get("ce_id")) or str(row.get("ce_id")).strip() == "":
        flags.append("missing_ce_id")
    if pd.isna(row.get("total_reimbursement")):
        flags.append("missing_total_reimbursement")
    tm = row.get("total_meals_reimbursed")
    if pd.notna(tm) and tm == 0:
        flags.append("zero_total_meals_reimbursed")
    tr = row.get("total_reimbursement")
    if pd.notna(tr) and tr < 0:
        flags.append("negative_total_reimbursement")
    rpm = row.get("reimbursement_per_meal")
    if pd.notna(rpm) and rpm > 20:
        flags.append("suspicious_reimbursement_per_meal_over_20")
    return "|".join(flags) if flags else "ok"


# --------------------------------------------------------------------
# Drivers
# --------------------------------------------------------------------

def build_category(reg: List[dict], category: str, standardize_fn,
                   skip_dup_dataset_ids=False) -> pd.DataFrame:
    print(f"\n=== Building {category} ===")
    entries = registry_for_category(reg, category)
    parts = []
    seen = set()
    for entry in entries:
        dsid = entry["dataset_id"]
        if skip_dup_dataset_ids and dsid in seen:
            continue
        seen.add(dsid)
        raw_path = os.path.join(DATA_RAW_V2, category, f"{dsid}.csv")
        if not os.path.exists(raw_path):
            print(f"  {dsid}: raw file missing at {raw_path}")
            continue
        df = pd.read_csv(raw_path, dtype=str, low_memory=False)
        print(f"  {dsid}: {len(df):,} raw rows", flush=True)
        out = standardize_fn(entry, df)
        parts.append(out)
    if not parts:
        return pd.DataFrame()
    combined = pd.concat(parts, ignore_index=True)
    print(f"  combined: {len(combined):,} rows, {len(combined.columns)} columns")
    return combined


def main() -> None:
    print("SSO vs SFSP Texas Capstone - v2 canonical build")
    print("=" * 80)

    reg = load_registry()
    audit_rows = []

    def write_and_audit(name: str, df: pd.DataFrame, path: str):
        df.to_csv(path, index=False)
        audit_rows.append({
            "table_name": name,
            "row_count": len(df),
            "distinct_ce_id": int(df["ce_id"].dropna().nunique()) if "ce_id" in df.columns else None,
            "distinct_site_id": int(df["site_id"].dropna().nunique()) if "site_id" in df.columns else None,
            "out_path": path,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        print(f"  wrote {path}")

    meals = build_category(reg, "summer_meal_counts", standardize_meal_counts_record)
    write_and_audit("summer_meals_5yr_master", meals, OUT_MEALS)

    reimb = build_category(reg, "summer_reimbursements", standardize_reimbursement_record)
    write_and_audit("summer_reimbursements_5yr_master", reimb, OUT_REIMB)

    summer_contacts = build_category(reg, "summer_contacts", standardize_summer_contact_record)
    write_and_audit("summer_contacts_5yr_master", summer_contacts, OUT_SUMMER_CONTACTS)

    snp_contacts = build_category(reg, "snp_contacts", standardize_snp_contact_record)
    write_and_audit("snp_contacts_5yr_master", snp_contacts, OUT_SNP_CONTACTS)

    snp_reimb = build_category(reg, "snp_reimbursements", standardize_snp_reimbursement_record)
    write_and_audit("snp_reimbursements_5yr_master", snp_reimb, OUT_SNP_REIMB)

    audit = pd.DataFrame(audit_rows)
    audit.to_csv(OUT_AUDIT, index=False)
    print(f"\nWrote {OUT_AUDIT}")
    print(audit.to_string(index=False))

    print("\nDONE")


if __name__ == "__main__":
    main()
