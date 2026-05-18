"""
SSO vs SFSP Texas Capstone
03_build_ce_site_lookup_tables.py

Build dashboard-ready CE / site lookup tables from:
- data/clean/summer_meals_master.csv
- data/clean/reimbursements_master.csv
- data/raw/contact_participation/summer_site_contact_participation_7ae2-5muh.csv
- data/raw/contact_participation/snp_site_contact_participation_5ejx-uftk.csv

Outputs:
- data/lookup/ce_lookup_master.csv
- data/lookup/site_lookup_master.csv
- data/lookup/site_program_flags.csv
- data/lookup/ce_site_search_master.csv
- data/audit/lookup_join_audit.csv

Wording note: "reported meals" throughout. The non_congregate_status
column is always "Unknown" because no explicit non-congregate / rural
indicator exists in the public Socrata sources used here.
"""

from __future__ import annotations

import ast
import os
import re
from datetime import datetime
from typing import Optional

import pandas as pd


DATA_CLEAN = "data/clean"
DATA_RAW_CONTACTS = "data/raw/contact_participation"
DATA_LOOKUP = "data/lookup"
DATA_AUDIT = "data/audit"

for folder in [DATA_LOOKUP, DATA_AUDIT]:
    os.makedirs(folder, exist_ok=True)

SUMMER_RAW = os.path.join(DATA_RAW_CONTACTS, "summer_site_contact_participation_7ae2-5muh.csv")
SNP_RAW = os.path.join(DATA_RAW_CONTACTS, "snp_site_contact_participation_5ejx-uftk.csv")
MEALS_MASTER = os.path.join(DATA_CLEAN, "summer_meals_master.csv")
REIMB_MASTER = os.path.join(DATA_CLEAN, "reimbursements_master.csv")


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
    s = s.where(~s.isin(["nan", "None", "NaT", "", "<NA>"]), pd.NA)
    return s


def is_blank(value) -> bool:
    if pd.isna(value):
        return True
    s = str(value).strip()
    return s == "" or s.lower() in {"nan", "none", "<na>"}


def first_non_null(series: pd.Series):
    s = series.dropna()
    s = s[s.astype(str).str.strip() != ""]
    return s.iloc[0] if len(s) else pd.NA


def unique_joined(series: pd.Series, sep: str = ", ") -> Optional[str]:
    vals = (
        series.dropna()
        .astype(str)
        .str.strip()
        .replace({"": pd.NA})
        .dropna()
        .unique()
    )
    return sep.join(sorted(vals)) if len(vals) else pd.NA


def coalesce(*series_args: pd.Series) -> pd.Series:
    result = series_args[0].copy()
    for s in series_args[1:]:
        mask = result.isna() | (result.astype(str).str.strip().isin(["", "nan", "<NA>"]))
        result = result.where(~mask, s)
    return result


def join_name(*parts):
    bits = []
    for p in parts:
        if pd.isna(p):
            continue
        s = str(p).strip()
        if s and s.lower() not in {"nan", "none", "<na>"}:
            bits.append(s)
    return " ".join(bits) if bits else pd.NA


def latest_year_from_text(val) -> Optional[int]:
    if pd.isna(val):
        return None
    years = re.findall(r"(20\d{2})", str(val))
    return int(max(years)) if years else None


def parse_geolocation(val):
    if pd.isna(val):
        return (None, None)
    s = str(val).strip()
    if not s:
        return (None, None)
    try:
        obj = ast.literal_eval(s)
        if isinstance(obj, dict):
            coords = obj.get("coordinates")
            if coords and len(coords) >= 2:
                return (float(coords[1]), float(coords[0]))  # (lat, lon)
    except Exception:
        pass
    nums = re.findall(r"-?\d+\.\d+", s)
    if len(nums) >= 2:
        # Heuristic: Texas longitudes are negative; the first numeric pair in
        # the GeoJSON Point is [lon, lat]. Stick with that ordering.
        return (float(nums[1]), float(nums[0]))
    return (None, None)


def max_year(*years):
    candidates = []
    for y in years:
        if pd.isna(y):
            continue
        try:
            candidates.append(int(float(y)))
        except (TypeError, ValueError):
            pass
    return max(candidates) if candidates else pd.NA


# --------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------

def load_meals() -> pd.DataFrame:
    df = pd.read_csv(MEALS_MASTER, dtype={"ce_id": str, "site_id": str})
    df = normalize_columns(df)
    df["ce_id"] = to_id_str(df["ce_id"])
    df["site_id"] = to_id_str(df["site_id"])
    df["total_meals"] = pd.to_numeric(df["total_meals"], errors="coerce")
    df["program_year"] = pd.to_numeric(df["program_year"], errors="coerce")
    return df


def load_reimbursements() -> pd.DataFrame:
    df = pd.read_csv(REIMB_MASTER, dtype={"ce_id": str})
    df = normalize_columns(df)
    df["ce_id"] = to_id_str(df["ce_id"])
    return df


def load_summer_raw() -> pd.DataFrame:
    df = pd.read_csv(SUMMER_RAW, dtype={"ceid": str, "siteid": str})
    df = normalize_columns(df)
    df["ce_id"] = to_id_str(df["ceid"])
    df["site_id"] = to_id_str(df["siteid"])
    return df


def load_snp_raw() -> pd.DataFrame:
    df = pd.read_csv(SNP_RAW, dtype={"ceid": str, "siteid": str})
    df = normalize_columns(df)
    df["ce_id"] = to_id_str(df["ceid"])
    df["site_id"] = to_id_str(df["siteid"])
    return df


# --------------------------------------------------------------------
# Aggregations from meals
# --------------------------------------------------------------------

def summarize_meals_by_site(meals: pd.DataFrame) -> pd.DataFrame:
    g = meals.groupby(["ce_id", "site_id"], dropna=False)
    return g.agg(
        total_reported_meals=("total_meals", "sum"),
        years_active=("program_year", lambda s: s.dropna().nunique()),
        latest_program_year_meals=("program_year", "max"),
        program_types_observed=("program_type", unique_joined),
        ce_name_from_meals=("ce_name", first_non_null),
        site_name_from_meals=("site_name", first_non_null),
        site_county_from_meals=("county", first_non_null),
        region_from_meals=("region", first_non_null),
    ).reset_index()


def summarize_meals_by_ce(meals: pd.DataFrame) -> pd.DataFrame:
    g = meals.groupby("ce_id", dropna=False)
    return g.agg(
        total_reported_meals_ce=("total_meals", "sum"),
        latest_program_year_meals_ce=("program_year", "max"),
        programs_observed_from_meals=("program_type", unique_joined),
        ce_name_from_meals=("ce_name", first_non_null),
        ce_county_from_meals=("county", first_non_null),
        region_from_meals=("region", first_non_null),
    ).reset_index()


# --------------------------------------------------------------------
# Standardize raw contact datasets to one row per (ce_id, site_id)
# --------------------------------------------------------------------

def build_summer_site_records(raw: pd.DataFrame) -> pd.DataFrame:
    d = raw.copy()
    d["summer_program_year"] = d["programyear"].apply(latest_year_from_text)

    d["program_administrator_name"] = [
        join_name(a, b, c)
        for a, b, c in zip(
            d.get("progradministratorsalutation", pd.Series([pd.NA] * len(d))),
            d.get("progradministratorfirstname", pd.Series([pd.NA] * len(d))),
            d.get("progradministratorlastname", pd.Series([pd.NA] * len(d))),
        )
    ]
    d["program_coordinator_name"] = [
        join_name(a, b, c)
        for a, b, c in zip(
            d.get("progrcoordinatorsalutation", pd.Series([pd.NA] * len(d))),
            d.get("progrcoordinatorfirstname", pd.Series([pd.NA] * len(d))),
            d.get("progrcoordinatorlastname", pd.Series([pd.NA] * len(d))),
        )
    ]
    d["site_contact_name"] = [
        join_name(a, b, c)
        for a, b, c in zip(
            d.get("sitecontactsalutation", pd.Series([pd.NA] * len(d))),
            d.get("sitecontactfirstname", pd.Series([pd.NA] * len(d))),
            d.get("sitecontactlastname", pd.Series([pd.NA] * len(d))),
        )
    ]

    lats, lons = [], []
    for v in d.get("geolocation", pd.Series([pd.NA] * len(d))):
        lat, lon = parse_geolocation(v)
        lats.append(lat)
        lons.append(lon)
    d["latitude"] = lats
    d["longitude"] = lons

    src_to_target = {
        "cename": "ce_name",
        "cestreetaddressline1": "ce_street_address_line_1",
        "cestreetaddressline2": "ce_street_address_line_2",
        "cestreetaddresscity": "ce_city",
        "cestreetaddressstate": "ce_state",
        "cestreetaddresszipcode": "ce_zip",
        "cemailingaddressline1": "ce_mailing_address_line_1",
        "cemailingaddressline2": "ce_mailing_address_line_2",
        "cemailingaddresscity": "ce_mailing_city",
        "cemailingaddressstate": "ce_mailing_state",
        "cemailingaddresszipcode": "ce_mailing_zip",
        "cecounty": "ce_county",
        "tdaregion": "region",
        "sitename": "site_name",
        "sitecounty": "site_county",
        "sitestreetaddressline1": "site_street_address_line_1",
        "sitestreetaddressline2": "site_street_address_line_2",
        "sitestreetaddresscity": "site_city",
        "sitestreetaddressstate": "site_state",
        "sitestreetaddresszipcode": "site_zip",
        "sitetype": "site_type",
        "typeofagency": "type_of_agency",
        "typeoforg": "type_of_org",
        "progradministratortitlep": "program_administrator_title",
        "progradministratoremail": "program_administrator_email",
        "progradministratorphone": "program_administrator_phone",
        "progrcoordinatortitleposition": "program_coordinator_title",
        "progrcoordinatoremail": "program_coordinator_email",
        "progrcoordinatorphone": "program_coordinator_phone",
        "sitecontacttitleposition": "site_contact_title",
        "sitecontactemail": "site_contact_email",
        "sitecontactphone": "site_contact_phone",
        "operationstartdate": "operation_start_date",
        "operationenddate": "operation_end_date",
        "sitestartdate": "site_start_date",
        "siteenddate": "site_end_date",
        "daysofoperation": "days_of_operation",
        "mealtypesserved": "meal_types_served",
        "breakfasttime": "breakfast_time",
        "lunchtime": "lunch_time",
        "suppertime": "supper_time",
        "amsnacktime": "am_snack_time",
        "pmsnacktime": "pm_snack_time",
        "breakfastdaysserved": "breakfast_days_served",
        "lunchdaysserved": "lunch_days_served",
        "supperdaysserved": "supper_days_served",
        "amsnackdaysserved": "am_snack_days_served",
        "pmsnackdaysserved": "pm_snack_days_served",
    }
    for src, tgt in src_to_target.items():
        if src in d.columns:
            d[tgt] = d[src]
        else:
            d[tgt] = pd.NA

    keep_cols = (
        ["ce_id", "site_id"]
        + list(src_to_target.values())
        + ["program_administrator_name", "program_coordinator_name", "site_contact_name",
           "latitude", "longitude", "summer_program_year", "program"]
    )
    d = d[[c for c in keep_cols if c in d.columns]]

    agg_kwargs = {col: (col, first_non_null) for col in d.columns if col not in {"ce_id", "site_id"}}
    # Override: "program" should be joined uniquely
    agg_kwargs["summer_programs"] = ("program", unique_joined)
    if "program" in agg_kwargs:
        del agg_kwargs["program"]
    agg_kwargs["summer_program_year"] = ("summer_program_year", "max")

    out = d.groupby(["ce_id", "site_id"], dropna=False).agg(**agg_kwargs).reset_index()
    return out


def build_snp_site_records(raw: pd.DataFrame) -> pd.DataFrame:
    d = raw.copy()
    d["snp_program_year"] = d["programyear"].apply(latest_year_from_text)

    d["superintendent_name"] = [
        join_name(a, b, c)
        for a, b, c in zip(
            d.get("superintendentsalutation", pd.Series([pd.NA] * len(d))),
            d.get("superintendentfirstname", pd.Series([pd.NA] * len(d))),
            d.get("superintendentlastname", pd.Series([pd.NA] * len(d))),
        )
    ]
    d["child_nutrition_director_name"] = [
        join_name(a, b, c)
        for a, b, c in zip(
            d.get("childnutdirsalutation", pd.Series([pd.NA] * len(d))),
            d.get("childnutdirfirstname", pd.Series([pd.NA] * len(d))),
            d.get("childnutdirlastname", pd.Series([pd.NA] * len(d))),
        )
    ]

    lats, lons = [], []
    for v in d.get("geolocation", pd.Series([pd.NA] * len(d))):
        lat, lon = parse_geolocation(v)
        lats.append(lat)
        lons.append(lon)
    d["latitude"] = lats
    d["longitude"] = lons

    src_to_target = {
        "cename": "ce_name",
        "cestreetaddressline1": "ce_street_address_line_1",
        "cestreetaddressline2": "ce_street_address_line_2",
        "cestreetaddresscity": "ce_city",
        "cestreetaddressstate": "ce_state",
        "cestreetaddresszipcode": "ce_zip",
        "cemailingaddressline1": "ce_mailing_address_line_1",
        "cemailingaddressline2": "ce_mailing_address_line_2",
        "cemailingaddresscity": "ce_mailing_city",
        "cemailingaddressstate": "ce_mailing_state",
        "cemailingaddresszipcode": "ce_mailing_zip",
        "cecounty": "ce_county",
        "tdaregion": "region",
        "sitename": "site_name",
        "sitecounty": "site_county",
        "sitestreetaddressline1": "site_street_address_line_1",
        "sitestreetaddressline2": "site_street_address_line_2",
        "sitestreetaddresscity": "site_city",
        "sitestreetaddressstate": "site_state",
        "sitestreetaddresszipcode": "site_zip",
        "typeofagency": "type_of_agency",
        "typeoforg": "type_of_org",
        "superintendentemail": "superintendent_email",
        "superintendentphone": "superintendent_phone",
        "childnutdiremail": "child_nutrition_director_email",
        "childnutdirphone": "child_nutrition_director_phone",
        "operationstartdate": "operation_start_date",
        "operationenddate": "operation_end_date",
    }
    for src, tgt in src_to_target.items():
        if src in d.columns:
            d[tgt] = d[src]
        else:
            d[tgt] = pd.NA

    keep_cols = (
        ["ce_id", "site_id"]
        + list(src_to_target.values())
        + ["superintendent_name", "child_nutrition_director_name",
           "latitude", "longitude", "snp_program_year"]
    )
    d = d[[c for c in keep_cols if c in d.columns]]

    agg_kwargs = {col: (col, first_non_null) for col in d.columns if col not in {"ce_id", "site_id"}}
    agg_kwargs["snp_program_year"] = ("snp_program_year", "max")

    out = d.groupby(["ce_id", "site_id"], dropna=False).agg(**agg_kwargs).reset_index()
    return out


# --------------------------------------------------------------------
# Site lookup master
# --------------------------------------------------------------------

SITE_SHARED_FIELDS = [
    "ce_name",
    "ce_street_address_line_1", "ce_street_address_line_2",
    "ce_city", "ce_state", "ce_zip",
    "ce_mailing_address_line_1", "ce_mailing_address_line_2",
    "ce_mailing_city", "ce_mailing_state", "ce_mailing_zip",
    "ce_county", "region",
    "site_name", "site_county",
    "site_street_address_line_1", "site_street_address_line_2",
    "site_city", "site_state", "site_zip",
    "type_of_agency", "type_of_org",
    "latitude", "longitude",
    "operation_start_date", "operation_end_date",
]

SITE_SUMMER_ONLY = [
    "site_type",
    "program_administrator_name", "program_administrator_title",
    "program_administrator_email", "program_administrator_phone",
    "program_coordinator_name", "program_coordinator_title",
    "program_coordinator_email", "program_coordinator_phone",
    "site_contact_name", "site_contact_title",
    "site_contact_email", "site_contact_phone",
    "site_start_date", "site_end_date",
    "days_of_operation", "meal_types_served",
    "breakfast_time", "lunch_time", "supper_time", "am_snack_time", "pm_snack_time",
    "breakfast_days_served", "lunch_days_served", "supper_days_served",
    "am_snack_days_served", "pm_snack_days_served",
]

SITE_SNP_ONLY = [
    "superintendent_name", "superintendent_email", "superintendent_phone",
    "child_nutrition_director_name", "child_nutrition_director_email",
    "child_nutrition_director_phone",
]


def build_site_lookup(
    summer_site: pd.DataFrame,
    snp_site: pd.DataFrame,
    meals_site_summary: pd.DataFrame,
) -> pd.DataFrame:
    universe = pd.concat(
        [
            summer_site[["ce_id", "site_id"]],
            snp_site[["ce_id", "site_id"]],
            meals_site_summary[["ce_id", "site_id"]],
        ],
        ignore_index=True,
    ).drop_duplicates(subset=["ce_id", "site_id"]).reset_index(drop=True)

    s = summer_site.rename(columns={c: f"{c}_s" for c in summer_site.columns if c not in {"ce_id", "site_id"}})
    n = snp_site.rename(columns={c: f"{c}_n" for c in snp_site.columns if c not in {"ce_id", "site_id"}})

    merged = (
        universe
        .merge(s, on=["ce_id", "site_id"], how="left")
        .merge(n, on=["ce_id", "site_id"], how="left")
        .merge(meals_site_summary, on=["ce_id", "site_id"], how="left")
    )

    def pick_shared(field):
        s_col, n_col = f"{field}_s", f"{field}_n"
        s_series = merged[s_col] if s_col in merged.columns else pd.Series([pd.NA] * len(merged))
        n_series = merged[n_col] if n_col in merged.columns else pd.Series([pd.NA] * len(merged))
        return coalesce(s_series, n_series)

    out = pd.DataFrame({"ce_id": merged["ce_id"], "site_id": merged["site_id"]})

    for f in SITE_SHARED_FIELDS:
        out[f] = pick_shared(f)

    for f in SITE_SUMMER_ONLY:
        col = f"{f}_s"
        out[f] = merged[col] if col in merged.columns else pd.NA

    for f in SITE_SNP_ONLY:
        col = f"{f}_n"
        out[f] = merged[col] if col in merged.columns else pd.NA

    # ce_name / site_name fallback from meals master
    out["ce_name"] = coalesce(out["ce_name"], merged.get("ce_name_from_meals", pd.Series([pd.NA] * len(out))))
    out["site_name"] = coalesce(out["site_name"], merged.get("site_name_from_meals", pd.Series([pd.NA] * len(out))))
    out["site_county"] = coalesce(out["site_county"], merged.get("site_county_from_meals", pd.Series([pd.NA] * len(out))))
    out["region"] = coalesce(out["region"], merged.get("region_from_meals", pd.Series([pd.NA] * len(out))))

    # program_year (latest across all sources)
    out["program_year"] = [
        max_year(a, b, c)
        for a, b, c in zip(
            merged.get("latest_program_year_meals", pd.Series([pd.NA] * len(merged))),
            merged.get("summer_program_year_s", pd.Series([pd.NA] * len(merged))),
            merged.get("snp_program_year_n", pd.Series([pd.NA] * len(merged))),
        )
    ]

    # program_type: prefer summer "program" join (SSO/SFSP labels), then meals
    summer_programs = merged.get("summer_programs_s", pd.Series([pd.NA] * len(merged)))
    meals_program_types = merged.get("program_types_observed", pd.Series([pd.NA] * len(merged)))
    out["program_type"] = coalesce(summer_programs, meals_program_types)

    # Reported meal activity
    out["total_reported_meals"] = pd.to_numeric(merged.get("total_reported_meals"), errors="coerce").fillna(0)
    out["years_active"] = pd.to_numeric(merged.get("years_active"), errors="coerce").fillna(0).astype(int)

    # data_sources
    summer_keys = set(zip(summer_site["ce_id"], summer_site["site_id"]))
    snp_keys = set(zip(snp_site["ce_id"], snp_site["site_id"]))
    meals_keys = set(zip(meals_site_summary["ce_id"], meals_site_summary["site_id"]))

    def site_data_sources(ce, site):
        srcs = []
        key = (ce, site)
        if key in summer_keys:
            srcs.append("summer_contact_2022")
        if key in snp_keys:
            srcs.append("snp_2024_2025")
        if key in meals_keys:
            srcs.append("meals_master")
        return "|".join(srcs)

    out["data_sources"] = [site_data_sources(c, s) for c, s in zip(out["ce_id"], out["site_id"])]

    out["non_congregate_status"] = "Unknown"
    out["non_congregate_source"] = "Not available in public source"

    spec_order = [
        "ce_id", "ce_name", "site_id", "site_name",
        "program_year", "program_type", "site_type",
        "type_of_agency", "type_of_org",
        "site_street_address_line_1", "site_street_address_line_2",
        "site_city", "site_state", "site_zip", "site_county",
        "region", "latitude", "longitude",
        "site_contact_name", "site_contact_title",
        "site_contact_email", "site_contact_phone",
        "operation_start_date", "operation_end_date",
        "site_start_date", "site_end_date",
        "days_of_operation", "meal_types_served",
        "breakfast_time", "lunch_time", "supper_time",
        "am_snack_time", "pm_snack_time",
        "breakfast_days_served", "lunch_days_served",
        "supper_days_served", "am_snack_days_served", "pm_snack_days_served",
        "total_reported_meals", "years_active", "data_sources",
        "non_congregate_status", "non_congregate_source",
    ]
    extras = [c for c in out.columns if c not in spec_order]
    return out[spec_order + extras]


# --------------------------------------------------------------------
# Site program flags from SNP raw
# --------------------------------------------------------------------

def build_site_program_flags(snp_raw: pd.DataFrame) -> pd.DataFrame:
    d = snp_raw.copy()
    d["program_year"] = d["programyear"].apply(latest_year_from_text)

    grade_cols = [c for c in d.columns if c.startswith("grade")]

    def grade_span(row):
        labels = []
        for c in grade_cols:
            v = row.get(c)
            if pd.notna(v) and str(v).strip().upper() == "Y":
                label = c.replace("grade", "")
                labels.append(label.upper() if label else "ALL")
        return ", ".join(labels) if labels else pd.NA

    d["grade_span"] = d.apply(grade_span, axis=1)

    src_to_target = {
        "cename": "ce_name",
        "sitename": "site_name",
        "schoolbreakfastprogram": "school_breakfast_program",
        "nationalschoollunchprogram": "national_school_lunch_program",
        "afterschoolcareprogram": "afterschool_care_program",
        "specialmilkprogram": "special_milk_program",
        "ffvpapproved": "ffvp_approved",
        "severeneedbreakfast": "severe_need_breakfast",
        "universalfreebreakfast": "universal_free_breakfast",
        "managedbyfsmc": "managed_by_fsmc",
        "mealspurchasedfromsfa": "meals_purchased_from_sfa",
        "mealspurchasedfromvendorotherthansfa": "meals_purchased_from_vendor_other_than_sfa",
        "vendmealstosfa": "vends_meals_to_sfa",
        "breakfastpricing": "breakfast_pricing",
        "lunchpricing": "lunch_pricing",
        "snackpricing": "snack_pricing",
        "areaeligiblesnack": "area_eligible_snack",
        "siteisp": "site_isp",
        "cep": "cep",
        "provision2": "provision2",
    }
    for src, tgt in src_to_target.items():
        d[tgt] = d[src] if src in d.columns else pd.NA

    keep_cols = ["ce_id", "site_id", "program_year"] + list(src_to_target.values()) + ["grade_span"]
    d = d[[c for c in keep_cols if c in d.columns]]

    agg_kwargs = {col: (col, first_non_null) for col in d.columns if col not in {"ce_id", "site_id"}}
    agg_kwargs["program_year"] = ("program_year", "max")
    out = d.groupby(["ce_id", "site_id"], dropna=False).agg(**agg_kwargs).reset_index()

    final_order = ["ce_id", "ce_name", "site_id", "site_name", "program_year"] + [
        v for v in src_to_target.values() if v not in {"ce_name", "site_name"}
    ] + ["grade_span"]
    return out[[c for c in final_order if c in out.columns]]


# --------------------------------------------------------------------
# CE lookup master
# --------------------------------------------------------------------

CE_SHARED_FIELDS = [
    "ce_name",
    "ce_street_address_line_1", "ce_street_address_line_2",
    "ce_city", "ce_state", "ce_zip",
    "ce_mailing_address_line_1", "ce_mailing_address_line_2",
    "ce_mailing_city", "ce_mailing_state", "ce_mailing_zip",
    "ce_county", "region",
]

CE_SUMMER_ONLY_CONTACT = [
    "program_administrator_name", "program_administrator_title",
    "program_administrator_email", "program_administrator_phone",
    "program_coordinator_name", "program_coordinator_title",
    "program_coordinator_email", "program_coordinator_phone",
]

CE_SNP_ONLY_CONTACT = [
    "superintendent_name", "superintendent_email", "superintendent_phone",
    "child_nutrition_director_name", "child_nutrition_director_email",
    "child_nutrition_director_phone",
]


def aggregate_ce_from_site_table(site_df: pd.DataFrame, fields: list, sites_col_name: str,
                                 program_year_col: str, programs_col: Optional[str]) -> pd.DataFrame:
    agg_kwargs = {f: (f, first_non_null) for f in fields if f in site_df.columns}
    agg_kwargs[sites_col_name] = ("site_id", lambda s: s.dropna().nunique())
    agg_kwargs[program_year_col] = (program_year_col, "max") if program_year_col in site_df.columns else None
    agg_kwargs = {k: v for k, v in agg_kwargs.items() if v is not None}
    if programs_col and programs_col in site_df.columns:
        agg_kwargs["_programs_joined"] = (programs_col, unique_joined)
    return site_df.groupby("ce_id", dropna=False).agg(**agg_kwargs).reset_index()


def build_ce_lookup(
    summer_site: pd.DataFrame,
    snp_site: pd.DataFrame,
    site_lookup: pd.DataFrame,
    meals_ce_summary: pd.DataFrame,
) -> pd.DataFrame:
    summer_fields = CE_SHARED_FIELDS + CE_SUMMER_ONLY_CONTACT
    snp_fields = CE_SHARED_FIELDS + CE_SNP_ONLY_CONTACT

    summer_ce = aggregate_ce_from_site_table(
        summer_site, summer_fields,
        sites_col_name="summer_sites_count",
        program_year_col="summer_program_year",
        programs_col="summer_programs",
    )
    summer_ce = summer_ce.rename(columns={c: f"{c}_s" for c in summer_ce.columns if c != "ce_id"})

    snp_ce = aggregate_ce_from_site_table(
        snp_site, snp_fields,
        sites_col_name="snp_sites_count",
        program_year_col="snp_program_year",
        programs_col=None,
    )
    snp_ce = snp_ce.rename(columns={c: f"{c}_n" for c in snp_ce.columns if c != "ce_id"})

    universe = pd.concat(
        [summer_ce[["ce_id"]], snp_ce[["ce_id"]], meals_ce_summary[["ce_id"]]],
        ignore_index=True,
    ).drop_duplicates(subset=["ce_id"]).reset_index(drop=True)

    merged = (
        universe
        .merge(summer_ce, on="ce_id", how="left")
        .merge(snp_ce, on="ce_id", how="left")
        .merge(meals_ce_summary, on="ce_id", how="left")
    )

    out = pd.DataFrame({"ce_id": merged["ce_id"]})

    def pick(field):
        s_col, n_col = f"{field}_s", f"{field}_n"
        s_series = merged[s_col] if s_col in merged.columns else pd.Series([pd.NA] * len(merged))
        n_series = merged[n_col] if n_col in merged.columns else pd.Series([pd.NA] * len(merged))
        return coalesce(s_series, n_series)

    for f in CE_SHARED_FIELDS:
        out[f] = pick(f)

    # ce_name fallback to meals
    out["ce_name"] = coalesce(out["ce_name"], merged.get("ce_name_from_meals", pd.Series([pd.NA] * len(merged))))
    out["ce_county"] = coalesce(out["ce_county"], merged.get("ce_county_from_meals", pd.Series([pd.NA] * len(merged))))
    out["region"] = coalesce(out["region"], merged.get("region_from_meals", pd.Series([pd.NA] * len(merged))))

    for f in CE_SUMMER_ONLY_CONTACT:
        out[f] = merged.get(f"{f}_s", pd.Series([pd.NA] * len(merged)))
    for f in CE_SNP_ONLY_CONTACT:
        out[f] = merged.get(f"{f}_n", pd.Series([pd.NA] * len(merged)))

    # programs_observed: combine summer + meals
    summer_programs = merged.get("_programs_joined_s", pd.Series([pd.NA] * len(merged)))
    meals_programs = merged.get("programs_observed_from_meals", pd.Series([pd.NA] * len(merged)))

    def combine_programs(a, b):
        vals = set()
        for v in (a, b):
            if pd.notna(v):
                for piece in re.split(r"[,|]", str(v)):
                    p = piece.strip()
                    if p:
                        vals.add(p)
        return ", ".join(sorted(vals)) if vals else pd.NA

    out["programs_observed"] = [combine_programs(a, b) for a, b in zip(summer_programs, meals_programs)]

    # Site counts
    out["summer_sites_count"] = pd.to_numeric(
        merged.get("summer_sites_count_s", pd.Series([0] * len(merged))), errors="coerce"
    ).fillna(0).astype(int)
    out["snp_sites_count"] = pd.to_numeric(
        merged.get("snp_sites_count_n", pd.Series([0] * len(merged))), errors="coerce"
    ).fillna(0).astype(int)

    site_counts = site_lookup.groupby("ce_id", dropna=False).size().rename("total_sites").reset_index()
    out = out.merge(site_counts, on="ce_id", how="left")
    out["total_sites"] = out["total_sites"].fillna(0).astype(int)

    out["total_reported_meals"] = pd.to_numeric(
        merged.get("total_reported_meals_ce", pd.Series([0] * len(merged))), errors="coerce"
    ).fillna(0)

    out["latest_program_year"] = [
        max_year(a, b, c)
        for a, b, c in zip(
            merged.get("latest_program_year_meals_ce", pd.Series([pd.NA] * len(merged))),
            merged.get("summer_program_year_s", pd.Series([pd.NA] * len(merged))),
            merged.get("snp_program_year_n", pd.Series([pd.NA] * len(merged))),
        )
    ]

    summer_ce_ids = set(summer_site["ce_id"].dropna())
    snp_ce_ids = set(snp_site["ce_id"].dropna())
    meals_ce_ids = set(meals_ce_summary["ce_id"].dropna())

    def ce_data_sources(cid):
        srcs = []
        if cid in summer_ce_ids:
            srcs.append("summer_contact_2022")
        if cid in snp_ce_ids:
            srcs.append("snp_2024_2025")
        if cid in meals_ce_ids:
            srcs.append("meals_master")
        return "|".join(srcs)

    out["data_sources"] = out["ce_id"].apply(ce_data_sources)

    spec_order = [
        "ce_id", "ce_name",
        "ce_street_address_line_1", "ce_street_address_line_2",
        "ce_city", "ce_state", "ce_zip",
        "ce_mailing_address_line_1", "ce_mailing_address_line_2",
        "ce_mailing_city", "ce_mailing_state", "ce_mailing_zip",
        "ce_county", "region",
        "program_administrator_name", "program_administrator_title",
        "program_administrator_email", "program_administrator_phone",
        "program_coordinator_name", "program_coordinator_title",
        "program_coordinator_email", "program_coordinator_phone",
        "superintendent_name", "superintendent_email", "superintendent_phone",
        "child_nutrition_director_name", "child_nutrition_director_email",
        "child_nutrition_director_phone",
        "programs_observed", "total_sites",
        "summer_sites_count", "snp_sites_count",
        "total_reported_meals", "latest_program_year", "data_sources",
    ]
    return out[[c for c in spec_order if c in out.columns]]


# --------------------------------------------------------------------
# Search master (dashboard-ready)
# --------------------------------------------------------------------

def fmt_address(line1, line2, city, state, zipc):
    parts1 = [str(x).strip() for x in (line1, line2) if pd.notna(x) and str(x).strip()]
    line_a = " ".join(parts1)
    parts2 = [str(x).strip() for x in (city, state) if pd.notna(x) and str(x).strip()]
    line_b = ", ".join(parts2)
    if pd.notna(zipc) and str(zipc).strip():
        line_b = (line_b + " " + str(zipc).strip()).strip()
    joined = ", ".join([p for p in (line_a, line_b) if p])
    return joined if joined else pd.NA


def contact_summary(name, title, email, phone):
    bits = []
    if pd.notna(name) and str(name).strip():
        s = str(name).strip()
        if pd.notna(title) and str(title).strip():
            s += f" ({str(title).strip()})"
        bits.append(s)
    if pd.notna(email) and str(email).strip():
        bits.append(str(email).strip())
    if pd.notna(phone) and str(phone).strip():
        bits.append(str(phone).strip())
    return " | ".join(bits) if bits else pd.NA


def build_search_master(
    site_lookup: pd.DataFrame,
    site_flags: pd.DataFrame,
    ce_lookup: pd.DataFrame,
) -> pd.DataFrame:
    base = site_lookup.copy()

    # Pull CE address + CE contacts from ce_lookup for ce_address_full / ce_contact_summary
    ce_for_join = ce_lookup[[
        "ce_id",
        "ce_street_address_line_1", "ce_street_address_line_2",
        "ce_city", "ce_state", "ce_zip",
        "program_administrator_name", "program_administrator_email", "program_administrator_phone",
        "program_coordinator_name", "program_coordinator_email", "program_coordinator_phone",
        "superintendent_name", "superintendent_email", "superintendent_phone",
        "child_nutrition_director_name", "child_nutrition_director_email", "child_nutrition_director_phone",
    ]].copy().add_suffix("_ce").rename(columns={"ce_id_ce": "ce_id"})

    base = base.merge(ce_for_join, on="ce_id", how="left")

    base["site_address_full"] = [
        fmt_address(a, b, c, s, z)
        for a, b, c, s, z in zip(
            base["site_street_address_line_1"], base["site_street_address_line_2"],
            base["site_city"], base["site_state"], base["site_zip"],
        )
    ]
    base["ce_address_full"] = [
        fmt_address(a, b, c, s, z)
        for a, b, c, s, z in zip(
            base["ce_street_address_line_1_ce"], base["ce_street_address_line_2_ce"],
            base["ce_city_ce"], base["ce_state_ce"], base["ce_zip_ce"],
        )
    ]

    base["site_contact_summary"] = [
        contact_summary(n, t, e, p)
        for n, t, e, p in zip(
            base["site_contact_name"], base["site_contact_title"],
            base["site_contact_email"], base["site_contact_phone"],
        )
    ]

    def ce_contact_summary_row(row):
        bits = []
        for label, name_col, email_col, phone_col in [
            ("Admin", "program_administrator_name_ce", "program_administrator_email_ce", "program_administrator_phone_ce"),
            ("Coord", "program_coordinator_name_ce", "program_coordinator_email_ce", "program_coordinator_phone_ce"),
            ("Super", "superintendent_name_ce", "superintendent_email_ce", "superintendent_phone_ce"),
            ("CND", "child_nutrition_director_name_ce", "child_nutrition_director_email_ce", "child_nutrition_director_phone_ce"),
        ]:
            summary = contact_summary(row.get(name_col), None, row.get(email_col), row.get(phone_col))
            if pd.notna(summary):
                bits.append(f"{label}: {summary}")
        return " || ".join(bits) if bits else pd.NA

    base["ce_contact_summary"] = base.apply(ce_contact_summary_row, axis=1)

    base["program_types_observed"] = base["program_type"]

    def operation_dates_summary(op_s, op_e, ss, se):
        parts = []
        if pd.notna(op_s) or pd.notna(op_e):
            parts.append(f"Operates {op_s or '?'} to {op_e or '?'}")
        if pd.notna(ss) or pd.notna(se):
            parts.append(f"Site {ss or '?'} to {se or '?'}")
        return " | ".join(parts) if parts else pd.NA

    base["operation_dates_summary"] = [
        operation_dates_summary(a, b, c, d)
        for a, b, c, d in zip(
            base["operation_start_date"], base["operation_end_date"],
            base["site_start_date"], base["site_end_date"],
        )
    ]

    def serving_dates_summary(days_op, types, bd, ld, sd, amd, pmd):
        parts = []
        if pd.notna(days_op):
            parts.append(f"Days: {days_op}")
        if pd.notna(types):
            parts.append(f"Meal types: {types}")
        if pd.notna(bd):
            parts.append(f"B days: {bd}")
        if pd.notna(ld):
            parts.append(f"L days: {ld}")
        if pd.notna(sd):
            parts.append(f"Su days: {sd}")
        if pd.notna(amd):
            parts.append(f"AM days: {amd}")
        if pd.notna(pmd):
            parts.append(f"PM days: {pmd}")
        return " | ".join(parts) if parts else pd.NA

    base["serving_dates_summary"] = [
        serving_dates_summary(a, b, c, d, e, f, g)
        for a, b, c, d, e, f, g in zip(
            base["days_of_operation"], base["meal_types_served"],
            base["breakfast_days_served"], base["lunch_days_served"],
            base["supper_days_served"], base["am_snack_days_served"],
            base["pm_snack_days_served"],
        )
    ]

    def service_times_summary(b, l, su, am, pm):
        parts = []
        if pd.notna(b):
            parts.append(f"B: {b}")
        if pd.notna(l):
            parts.append(f"L: {l}")
        if pd.notna(su):
            parts.append(f"Su: {su}")
        if pd.notna(am):
            parts.append(f"AM: {am}")
        if pd.notna(pm):
            parts.append(f"PM: {pm}")
        return " | ".join(parts) if parts else pd.NA

    base["service_times_summary"] = [
        service_times_summary(*t)
        for t in zip(
            base["breakfast_time"], base["lunch_time"], base["supper_time"],
            base["am_snack_time"], base["pm_snack_time"],
        )
    ]

    flag_cols = [
        "ce_id", "site_id",
        "school_breakfast_program", "national_school_lunch_program",
        "afterschool_care_program", "special_milk_program",
        "ffvp_approved", "severe_need_breakfast", "universal_free_breakfast",
        "managed_by_fsmc", "area_eligible_snack", "site_isp", "cep", "provision2",
    ]
    flag_cols = [c for c in flag_cols if c in site_flags.columns]
    base = base.merge(site_flags[flag_cols], on=["ce_id", "site_id"], how="left")

    def snp_flags_summary_row(row):
        flag_map = [
            ("SBP", "school_breakfast_program"),
            ("NSLP", "national_school_lunch_program"),
            ("ASCP", "afterschool_care_program"),
            ("SMP", "special_milk_program"),
            ("FFVP", "ffvp_approved"),
            ("SNB", "severe_need_breakfast"),
            ("UFB", "universal_free_breakfast"),
            ("FSMC", "managed_by_fsmc"),
        ]
        parts = []
        for label, col in flag_map:
            v = row.get(col)
            if pd.notna(v) and str(v).strip():
                parts.append(f"{label}={str(v).strip()}")
        return " | ".join(parts) if parts else pd.NA

    base["snp_flags_summary"] = base.apply(snp_flags_summary_row, axis=1)

    def eligibility_summary_row(row):
        parts = []
        for label, col in [
            ("ISP", "site_isp"),
            ("CEP", "cep"),
            ("Provision2", "provision2"),
            ("AreaEligibleSnack", "area_eligible_snack"),
        ]:
            v = row.get(col)
            if pd.notna(v) and str(v).strip():
                parts.append(f"{label}={str(v).strip()}")
        return " | ".join(parts) if parts else pd.NA

    base["eligibility_indicators_summary"] = base.apply(eligibility_summary_row, axis=1)

    base["latest_program_year"] = base["program_year"]

    def quality_flags(row):
        flags = []
        if is_blank(row.get("ce_id")):
            flags.append("missing_ce_id")
        if is_blank(row.get("site_id")):
            flags.append("missing_site_id")
        if pd.isna(row.get("site_address_full")):
            flags.append("missing_site_address")
        if pd.isna(row.get("site_contact_summary")):
            flags.append("missing_site_contact")
        if pd.isna(row.get("operation_dates_summary")):
            flags.append("missing_operation_dates")
        if pd.isna(row.get("meal_types_served")):
            flags.append("missing_meal_types_served")
        total = row.get("total_reported_meals")
        try:
            total_val = float(total) if pd.notna(total) else 0.0
        except (TypeError, ValueError):
            total_val = 0.0
        if total_val == 0:
            flags.append("no_reported_meal_activity")
        if str(row.get("non_congregate_status", "")).strip() == "Unknown":
            flags.append("non_congregate_unknown")
        return "|".join(flags) if flags else "ok"

    base["data_quality_flags"] = base.apply(quality_flags, axis=1)

    def make_search_key(row):
        parts = [row.get(c) for c in ["ce_id", "ce_name", "site_id", "site_name",
                                       "site_city", "site_county", "ce_county"]]
        bits = []
        for p in parts:
            if pd.notna(p):
                s = re.sub(r"\s+", " ", str(p)).strip()
                if s:
                    bits.append(s.lower())
        return " ".join(bits)

    base["search_key"] = base.apply(make_search_key, axis=1)

    spec_cols = [
        "search_key", "ce_id", "ce_name", "site_id", "site_name",
        "site_address_full", "ce_address_full",
        "site_contact_summary", "ce_contact_summary",
        "program_types_observed", "site_type",
        "operation_dates_summary", "serving_dates_summary",
        "meal_types_served", "service_times_summary",
        "total_reported_meals", "latest_program_year",
        "snp_flags_summary", "eligibility_indicators_summary",
        "non_congregate_status", "non_congregate_source",
        "data_quality_flags",
    ]
    map_extras = ["latitude", "longitude", "site_county", "region"]
    return base[spec_cols + [c for c in map_extras if c in base.columns]]


# --------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------

def build_audit(
    meals: pd.DataFrame,
    reimbursements: pd.DataFrame,
    summer_raw: pd.DataFrame,
    snp_raw: pd.DataFrame,
    ce_lookup: pd.DataFrame,
    site_lookup: pd.DataFrame,
    site_flags: pd.DataFrame,
    search_master: pd.DataFrame,
) -> pd.DataFrame:
    meals_keys = set(
        zip(meals["ce_id"].astype(str), meals["site_id"].astype(str))
    )

    def per_table(name, df, ce_col="ce_id", site_col="site_id"):
        row = {"source_table": name, "row_count": len(df)}

        if ce_col and ce_col in df.columns:
            ce_series = df[ce_col]
            row["distinct_ce_id"] = ce_series.dropna().astype(str).str.strip().replace({"": pd.NA}).dropna().nunique()
            row["missing_ce_id"] = int(
                (ce_series.isna() | (ce_series.astype(str).str.strip() == "")).sum()
            )
        else:
            row["distinct_ce_id"] = None
            row["missing_ce_id"] = None

        if site_col and site_col in df.columns:
            site_series = df[site_col]
            row["distinct_site_id"] = site_series.dropna().astype(str).str.strip().replace({"": pd.NA}).dropna().nunique()
            row["missing_site_id"] = int(
                (site_series.isna() | (site_series.astype(str).str.strip() == "")).sum()
            )
        else:
            row["distinct_site_id"] = None
            row["missing_site_id"] = None

        if ce_col in df.columns and site_col in df.columns:
            keys = set(zip(df[ce_col].astype(str), df[site_col].astype(str)))
            row["joined_to_meals_count"] = len(keys & meals_keys)
        else:
            row["joined_to_meals_count"] = None

        row["created_at"] = datetime.now().isoformat(timespec="seconds")
        return row

    rows = [
        per_table("summer_meals_master", meals),
        per_table("reimbursements_master", reimbursements, site_col=None),
        per_table("summer_contact_7ae2-5muh", summer_raw),
        per_table("snp_contact_5ejx-uftk", snp_raw),
        per_table("ce_lookup_master", ce_lookup, site_col=None),
        per_table("site_lookup_master", site_lookup),
        per_table("site_program_flags", site_flags),
        per_table("ce_site_search_master", search_master),
    ]

    cols = ["source_table", "row_count", "distinct_ce_id", "distinct_site_id",
            "joined_to_meals_count", "missing_ce_id", "missing_site_id", "created_at"]
    return pd.DataFrame(rows)[cols]


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main() -> None:
    print("SSO vs SFSP Texas Capstone - CE/Site lookup builder")
    print("=" * 80)

    print("\nLoading inputs ...")
    meals = load_meals()
    reimb = load_reimbursements()
    summer_raw = load_summer_raw()
    snp_raw = load_snp_raw()
    print(f"  meals master       : {len(meals):,} rows")
    print(f"  reimbursements     : {len(reimb):,} rows")
    print(f"  summer contact raw : {len(summer_raw):,} rows")
    print(f"  snp contact raw    : {len(snp_raw):,} rows")

    print("\nSummarizing meals ...")
    meals_site_summary = summarize_meals_by_site(meals)
    meals_ce_summary = summarize_meals_by_ce(meals)
    print(f"  meals -> distinct (ce, site): {len(meals_site_summary):,}")
    print(f"  meals -> distinct ce        : {len(meals_ce_summary):,}")

    print("\nStandardizing contact datasets ...")
    summer_site = build_summer_site_records(summer_raw)
    snp_site = build_snp_site_records(snp_raw)
    print(f"  summer_site records: {len(summer_site):,}")
    print(f"  snp_site records   : {len(snp_site):,}")

    print("\nBuilding site_lookup_master ...")
    site_lookup = build_site_lookup(summer_site, snp_site, meals_site_summary)
    print(f"  site_lookup_master rows: {len(site_lookup):,}")

    print("\nBuilding site_program_flags ...")
    site_flags = build_site_program_flags(snp_raw)
    print(f"  site_program_flags rows: {len(site_flags):,}")

    print("\nBuilding ce_lookup_master ...")
    ce_lookup = build_ce_lookup(summer_site, snp_site, site_lookup, meals_ce_summary)
    print(f"  ce_lookup_master rows: {len(ce_lookup):,}")

    print("\nBuilding ce_site_search_master ...")
    search_master = build_search_master(site_lookup, site_flags, ce_lookup)
    print(f"  ce_site_search_master rows: {len(search_master):,}")

    # Save outputs
    ce_lookup_path = os.path.join(DATA_LOOKUP, "ce_lookup_master.csv")
    site_lookup_path = os.path.join(DATA_LOOKUP, "site_lookup_master.csv")
    site_flags_path = os.path.join(DATA_LOOKUP, "site_program_flags.csv")
    search_master_path = os.path.join(DATA_LOOKUP, "ce_site_search_master.csv")
    audit_path = os.path.join(DATA_AUDIT, "lookup_join_audit.csv")

    ce_lookup.to_csv(ce_lookup_path, index=False)
    site_lookup.to_csv(site_lookup_path, index=False)
    site_flags.to_csv(site_flags_path, index=False)
    search_master.to_csv(search_master_path, index=False)

    print("\nSaved outputs:")
    for p in (ce_lookup_path, site_lookup_path, site_flags_path, search_master_path):
        print(f"  {p}")

    print("\nBuilding audit ...")
    audit = build_audit(meals, reimb, summer_raw, snp_raw,
                        ce_lookup, site_lookup, site_flags, search_master)
    audit.to_csv(audit_path, index=False)
    print(f"  {audit_path}")
    print(audit.to_string(index=False))

    # Diagnostics
    print("\nDiagnostics:")
    print("-" * 80)

    print("\nTop 10 columns by missing-rate in ce_site_search_master:")
    missing = (search_master.isna().mean() * 100).sort_values(ascending=False).head(10)
    for col, pct in missing.items():
        print(f"  {col}: {pct:.1f}% missing")

    print("\nRecords by non_congregate_status:")
    print(search_master["non_congregate_status"].value_counts(dropna=False).to_string())

    print("\nRecords flagged no_reported_meal_activity:")
    flagged = search_master["data_quality_flags"].astype(str).str.contains("no_reported_meal_activity").sum()
    print(f"  {flagged:,} of {len(search_master):,} ({flagged / max(len(search_master), 1) * 100:.1f}%)")

    print("\nLatitude / longitude parsing:")
    lat_parsed = pd.to_numeric(site_lookup["latitude"], errors="coerce").notna().sum()
    lon_parsed = pd.to_numeric(site_lookup["longitude"], errors="coerce").notna().sum()
    print(f"  latitude parsed:  {lat_parsed:,} of {len(site_lookup):,}")
    print(f"  longitude parsed: {lon_parsed:,} of {len(site_lookup):,}")

    print("\nDONE")


if __name__ == "__main__":
    main()
