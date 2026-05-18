"""
SSO vs SFSP Texas Capstone - CE/Site Lookup Dashboard

Streamlit app over data/lookup/ce_site_search_master.csv. Lets a user
search by CE ID, CE name, Site ID, Site name, city, or county and
returns matching sites with addresses, contacts, program details,
operation/serving dates, service times, SNP flags, eligibility
indicators, total reported meals, and data-quality flags.

Wording note: "reported meals" throughout. This dashboard never claims
a site is verified non-congregate unless an explicit public-source
field exists.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional

import pandas as pd
import streamlit as st


LOOKUP_CSV = os.path.join("data", "lookup", "ce_site_search_master.csv")

PHONE_SUFFIX_PATTERN = re.compile(r"(\d{7,})\.0(?=\D|$)")
SPLIT_PATTERN = re.compile(r"[,|]")

PAGE_TITLE = "CE/Site Lookup Dashboard"
WARNING_TEXT = (
    "This dashboard uses **reported meals**, not unique children served. "
    "Non-congregate status is only shown as verified if explicitly available "
    "in public source data. In the current data sources, no such field exists, "
    "so non-congregate status is marked **Unknown** for every site."
)

TABLE_COLUMNS = [
    "ce_id", "ce_name", "site_id", "site_name",
    "site_address_full", "program_types_observed", "site_type",
    "operation_dates_summary", "serving_dates_summary",
    "meal_types_served", "service_times_summary",
    "total_reported_meals", "latest_program_year",
    "non_congregate_status", "data_quality_flags",
]

DETAIL_FIELDS = [
    ("CE ID", "ce_id"),
    ("CE name", "ce_name"),
    ("Site ID", "site_id"),
    ("Site name", "site_name"),
    ("Site address", "site_address_full"),
    ("CE address", "ce_address_full"),
    ("Site contact", "site_contact_summary"),
    ("CE contacts", "ce_contact_summary"),
    ("Program types observed", "program_types_observed"),
    ("Site type", "site_type"),
    ("Operation dates", "operation_dates_summary"),
    ("Serving dates", "serving_dates_summary"),
    ("Meal types served", "meal_types_served"),
    ("Service times", "service_times_summary"),
    ("SNP flags", "snp_flags_summary"),
    ("Eligibility indicators", "eligibility_indicators_summary"),
    ("Total reported meals", "total_reported_meals"),
    ("Latest program year", "latest_program_year"),
    ("Non-congregate status", "non_congregate_status"),
    ("Non-congregate source", "non_congregate_source"),
    ("Data-quality flags", "data_quality_flags"),
]


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------

def clean_phone_text(value):
    if pd.isna(value):
        return value
    return PHONE_SUFFIX_PATTERN.sub(r"\1", str(value))


def get_col(df: pd.DataFrame, name: str, default=pd.NA) -> pd.Series:
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index, dtype="object")


def unique_split_values(series: pd.Series) -> List[str]:
    vals = set()
    for v in series.dropna():
        for piece in SPLIT_PATTERN.split(str(v)):
            p = piece.strip()
            if p:
                vals.add(p)
    return sorted(vals)


def value_contains_any(series: pd.Series, selected: Iterable[str]) -> pd.Series:
    selected = [s for s in selected if s]
    if not selected:
        return pd.Series(True, index=series.index)
    mask = pd.Series(False, index=series.index)
    for sel in selected:
        pattern = rf"(^|[,|]\s*){re.escape(sel)}(\s*[,|]|$)"
        mask = mask | series.fillna("").astype(str).str.contains(pattern, regex=True)
    return mask


def display_value(value) -> str:
    if pd.isna(value):
        return "—"
    s = str(value).strip()
    return s if s else "—"


def format_meals(value) -> str:
    if pd.isna(value):
        return "—"
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return str(value)


# --------------------------------------------------------------------
# Data load
# --------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_data(path: str = LOOKUP_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"ce_id": str, "site_id": str})
    for col in (
        "site_contact_summary", "ce_contact_summary",
        "snp_flags_summary", "eligibility_indicators_summary",
    ):
        if col in df.columns:
            df[col] = df[col].apply(clean_phone_text)
    for col in ("latitude", "longitude"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "total_reported_meals" in df.columns:
        df["total_reported_meals"] = pd.to_numeric(df["total_reported_meals"], errors="coerce")
    if "latest_program_year" in df.columns:
        df["latest_program_year"] = pd.to_numeric(df["latest_program_year"], errors="coerce").astype("Int64")
    return df


# --------------------------------------------------------------------
# Search and filtering
# --------------------------------------------------------------------

def apply_search(df: pd.DataFrame, query: str) -> pd.DataFrame:
    q = (query or "").lower().strip()
    if not q:
        return df

    if "search_key" in df.columns:
        haystack = df["search_key"].fillna("").astype(str).str.lower()
    else:
        fallback_cols = [c for c in ("ce_id", "ce_name", "site_id", "site_name",
                                     "site_address_full", "site_county", "ce_county")
                         if c in df.columns]
        if not fallback_cols:
            return df
        haystack = df[fallback_cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()

    tokens = [t for t in re.split(r"\s+", q) if t]
    mask = pd.Series(True, index=df.index)
    for t in tokens:
        mask = mask & haystack.str.contains(re.escape(t), na=False)
    return df[mask]


def apply_filters(df: pd.DataFrame, selections: dict) -> pd.DataFrame:
    out = df

    if selections.get("ce_names"):
        out = out[out["ce_name"].isin(selections["ce_names"])]

    if selections.get("program_types") and "program_types_observed" in out.columns:
        out = out[value_contains_any(out["program_types_observed"], selections["program_types"])]

    if selections.get("program_years") and "latest_program_year" in out.columns:
        years = [int(y) for y in selections["program_years"]]
        out = out[out["latest_program_year"].isin(years)]

    if selections.get("flag_filters") and "data_quality_flags" in out.columns:
        out = out[value_contains_any(out["data_quality_flags"].str.replace("|", ",", regex=False),
                                     selections["flag_filters"])]

    if selections.get("only_with_meals") and "total_reported_meals" in out.columns:
        out = out[pd.to_numeric(out["total_reported_meals"], errors="coerce").fillna(0) > 0]

    if selections.get("only_with_latlon") and {"latitude", "longitude"}.issubset(out.columns):
        out = out[out["latitude"].notna() & out["longitude"].notna()]

    return out


# --------------------------------------------------------------------
# UI sections
# --------------------------------------------------------------------

def render_metrics(df: pd.DataFrame) -> None:
    cols = st.columns(3)
    cols[0].metric("Matching sites", f"{len(df):,}")
    cols[1].metric("Distinct CEs", f"{get_col(df, 'ce_id').dropna().nunique():,}")
    cols[2].metric("Distinct site IDs", f"{get_col(df, 'site_id').dropna().nunique():,}")

    cols2 = st.columns(3)
    total_meals = pd.to_numeric(get_col(df, "total_reported_meals"), errors="coerce").fillna(0).sum()
    cols2[0].metric("Total reported meals", f"{int(total_meals):,}")

    if "latitude" in df.columns and "longitude" in df.columns:
        with_latlon = (df["latitude"].notna() & df["longitude"].notna()).sum()
    else:
        with_latlon = 0
    cols2[1].metric("Records with lat/lon", f"{with_latlon:,}")

    flags = get_col(df, "data_quality_flags").fillna("").astype(str)
    no_activity = flags.str.contains("no_reported_meal_activity").sum()
    cols2[2].metric("No reported meal activity", f"{no_activity:,}")


def render_detail_cards(df: pd.DataFrame, limit: int = 25) -> None:
    if df.empty:
        return
    st.markdown(f"### Detail view (first {min(limit, len(df))} of {len(df):,})")
    subset = df.head(limit)
    for _, row in subset.iterrows():
        title = f"{display_value(row.get('ce_name'))} — {display_value(row.get('site_name'))} (site {display_value(row.get('site_id'))})"
        with st.expander(title):
            for label, col in DETAIL_FIELDS:
                if col not in row.index:
                    continue
                raw = row.get(col)
                if col == "total_reported_meals":
                    pretty = format_meals(raw)
                else:
                    pretty = display_value(raw)
                st.markdown(f"**{label}:** {pretty}")


def render_map(df: pd.DataFrame) -> None:
    if not {"latitude", "longitude"}.issubset(df.columns):
        return
    map_df = (
        df[["latitude", "longitude"]]
        .dropna()
        .rename(columns={"latitude": "lat", "longitude": "lon"})
    )
    if map_df.empty:
        st.info("No latitude/longitude available for this selection — map hidden.")
        return
    st.markdown(f"### Map ({len(map_df):,} sites with coordinates)")
    st.map(map_df, use_container_width=True)


def render_download(df: pd.DataFrame) -> None:
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=f"Download filtered CSV ({len(df):,} rows)",
        data=csv_bytes,
        file_name="ce_site_search_filtered.csv",
        mime="text/csv",
    )


# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    st.title(PAGE_TITLE)
    st.warning(WARNING_TEXT)

    if not os.path.exists(LOOKUP_CSV):
        st.error(
            f"Lookup file not found at `{LOOKUP_CSV}`. "
            "Run `python scripts/03_build_ce_site_lookup_tables.py` first."
        )
        st.stop()

    try:
        data = load_data()
    except Exception as exc:
        st.error(f"Failed to load `{LOOKUP_CSV}`: {exc}")
        st.stop()

    # ----- Sidebar -----
    st.sidebar.header("Filters")

    if "ce_name" in data.columns:
        ce_options = sorted(data["ce_name"].dropna().astype(str).str.strip().replace({"": pd.NA}).dropna().unique())
        selected_ce_names = st.sidebar.multiselect("CE name", ce_options, placeholder="All CEs")
    else:
        selected_ce_names = []

    if "program_types_observed" in data.columns:
        program_options = unique_split_values(data["program_types_observed"])
        selected_programs = st.sidebar.multiselect("Program type", program_options, placeholder="All programs")
    else:
        selected_programs = []

    if "latest_program_year" in data.columns:
        year_options = sorted({int(y) for y in data["latest_program_year"].dropna().tolist()})
        selected_years = st.sidebar.multiselect(
            "Latest program year", year_options, placeholder="All years"
        )
    else:
        selected_years = []

    if "data_quality_flags" in data.columns:
        flag_options = unique_split_values(data["data_quality_flags"].str.replace("|", ",", regex=False))
        selected_flags = st.sidebar.multiselect(
            "Data-quality flag", flag_options, placeholder="No filter"
        )
    else:
        selected_flags = []

    only_with_meals = st.sidebar.checkbox("Only sites with reported meal activity", value=False)
    only_with_latlon = st.sidebar.checkbox("Only sites with latitude/longitude", value=False)

    # ----- Search -----
    query = st.text_input(
        "Search",
        placeholder="Search by CE ID, CE name, Site ID, Site name, city, or county. "
                    "Multiple words = AND search (e.g., `katy houston`).",
    )

    filtered = apply_search(data, query)
    filtered = apply_filters(filtered, {
        "ce_names": selected_ce_names,
        "program_types": selected_programs,
        "program_years": selected_years,
        "flag_filters": selected_flags,
        "only_with_meals": only_with_meals,
        "only_with_latlon": only_with_latlon,
    })

    # ----- Output -----
    render_metrics(filtered)

    st.markdown("---")

    if filtered.empty:
        st.info("No results match the current search and filters. Try widening the filters or clearing the search box.")
        return

    render_download(filtered)

    display_cols = [c for c in TABLE_COLUMNS if c in filtered.columns]
    if display_cols:
        st.markdown(f"### Results table ({len(filtered):,} sites)")
        table_view = filtered[display_cols].copy()
        if "total_reported_meals" in table_view.columns:
            table_view["total_reported_meals"] = pd.to_numeric(
                table_view["total_reported_meals"], errors="coerce"
            ).fillna(0).astype(int)
        st.dataframe(table_view, use_container_width=True, hide_index=True)

    render_map(filtered)
    render_detail_cards(filtered, limit=25)


if __name__ == "__main__":
    main()
