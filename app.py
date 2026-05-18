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


LOOKUP_CSV = os.path.join("data", "lookup_v2", "ce_site_search_master_v2.csv")

PHONE_SUFFIX_PATTERN = re.compile(r"(\d{7,})\.0(?=\D|$)")
SPLIT_PATTERN = re.compile(r"[,|]")

PAGE_TITLE = "CE/Site Lookup Dashboard"
WARNING_TEXT = (
    "This dashboard uses **reported meals served**, not unique children served. "
    "Verified non-congregate status is available only for sites covered by "
    "TX Open Data SFSP/SSO/All Summer Sites contact datasets for program year "
    "**2022–2023**. Sites outside those public-source fields remain marked "
    "**Unknown**; **Unknown does not mean the site was congregate**."
)

TABLE_COLUMNS = [
    "ce_id", "ce_name", "site_id", "site_name",
    "site_address_full", "program_types_observed", "site_type",
    "operation_dates_summary", "serving_dates_summary",
    "meal_types_served", "service_times_summary",
    "total_reported_meals", "latest_program_year",
    "non_congregate_status", "data_quality_flags",
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


def format_number(value) -> str:
    """Format a numeric value with thousands separators. Drops the decimal
    when the value is a whole number (so 71028.0 -> "71,028", and 44.76
    stays as "44.76"). Returns "—" for NaN / None and falls back to the
    display string for anything that won't parse as float."""
    if pd.isna(value):
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return display_value(value)
    if f.is_integer():
        return f"{int(f):,}"
    return f"{f:,.2f}"


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
    # Replace the U+FFFD replacement char that leaked from the source on the
    # "Non-Congregate - Mobile route" value with an em-dash for display.
    for col in ("meal_service_type_public", "non_congregate_status"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda v: v if pd.isna(v) else str(v).replace("�", "—")
            )
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

    if selections.get("nc_statuses") and "non_congregate_status" in out.columns:
        out = out[out["non_congregate_status"].astype(str).isin(selections["nc_statuses"])]

    if selections.get("ru_statuses") and "rural_urban_status" in out.columns:
        out = out[out["rural_urban_status"].astype(str).isin(selections["ru_statuses"])]

    if selections.get("meal_service_types") and "meal_service_type_public" in out.columns:
        out = out[out["meal_service_type_public"].astype(str).isin(selections["meal_service_types"])]

    if selections.get("years_verified") and "program_years_verified" in out.columns:
        out = out[value_contains_any(out["program_years_verified"], selections["years_verified"])]

    if selections.get("source_ids") and "source_dataset_ids" in out.columns:
        out = out[value_contains_any(out["source_dataset_ids"], selections["source_ids"])]

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

    # Row 3: public-source NC enrichment counts (2022-2023 verified subset)
    cols3 = st.columns(4)
    if "non_congregate_status" in df.columns:
        statuses = df["non_congregate_status"].fillna("Unknown").astype(str).str.strip()
        verified = int((statuses != "Unknown").sum())
        confirmed_nc = int(statuses.str.contains("Non-Congregate", na=False).sum())
        unknown_nc = int((statuses == "Unknown").sum())
    else:
        verified = 0
        confirmed_nc = 0
        unknown_nc = 0
    cols3[0].metric("Verified NC source-matched", f"{verified:,}")
    cols3[1].metric("Confirmed non-congregate", f"{confirmed_nc:,}")

    if "rural_urban_status" in df.columns:
        ru = df["rural_urban_status"].fillna("").astype(str).str.strip()
        rural = int((ru == "Rural").sum())
    else:
        rural = 0
    cols3[2].metric("Rural records", f"{rural:,}")
    cols3[3].metric("Unknown NC records", f"{unknown_nc:,}")

    st.caption(
        "Verified NC counts reflect only the public 2022–2023 meal service type "
        "sources. Unknown records may include sites from other years where TDA "
        "did not publish mealservicetype."
    )


def _build_selectbox_options(df: pd.DataFrame):
    """Build a list of (display_label, dataframe_index) tuples for the
    selected-site selectbox. Labels follow the spec format
    `CEID | CE Name | SiteID | Site Name | Latest Year` and are made
    unique by appending the dataframe row index when collisions occur."""
    base_labels = []
    for _, row in df.iterrows():
        base_labels.append(" | ".join([
            display_value(row.get("ce_id")),
            display_value(row.get("ce_name")),
            display_value(row.get("site_id")),
            display_value(row.get("site_name")),
            display_value(row.get("latest_program_year")),
        ]))

    seen = {}
    unique_labels = []
    for label, idx in zip(base_labels, df.index):
        if label in seen:
            unique_labels.append(f"{label}  [row {idx}]")
        else:
            seen[label] = True
            unique_labels.append(label)
    return list(zip(unique_labels, df.index.tolist()))


def _render_field_block(row: pd.Series, fields) -> None:
    for label, col in fields:
        if col not in row.index:
            continue
        raw = row.get(col)
        if col == "total_reported_meals":
            pretty = format_number(raw)
        elif col == "latest_program_year":
            pretty = format_number(raw) if pd.notna(raw) else "—"
        else:
            pretty = display_value(raw)
        st.markdown(f"**{label}:** {pretty}")


def render_selected_site_panel(df: pd.DataFrame) -> None:
    """Replace the old first-25-expanders with a single selectbox + clean
    detail panel for the chosen site. Sections follow the task spec."""
    if df.empty:
        return

    st.markdown("---")
    st.markdown("### Site details")

    options = _build_selectbox_options(df)
    labels = [lbl for lbl, _ in options]
    label_to_index = dict(options)

    selection = st.selectbox(
        "Select a site to view details",
        options=labels,
        index=0,
    )
    if selection is None or selection not in label_to_index:
        return

    row = df.loc[label_to_index[selection]]

    site_name = display_value(row.get("site_name"))
    ce_name = display_value(row.get("ce_name"))
    st.subheader(f"{site_name}  —  {ce_name}")

    col_ce, col_site = st.columns(2)

    with col_ce:
        st.markdown("#### CE / District")
        _render_field_block(row, [
            ("CE ID", "ce_id"),
            ("CE Name", "ce_name"),
            ("CE Address", "ce_address_full"),
            ("CE Contact Summary", "ce_contact_summary"),
        ])

    with col_site:
        st.markdown("#### Site")
        _render_field_block(row, [
            ("Site ID", "site_id"),
            ("Site Name", "site_name"),
            ("Site Address", "site_address_full"),
            ("Site Contact Summary", "site_contact_summary"),
        ])
        lat = row.get("latitude") if "latitude" in row.index else None
        lon = row.get("longitude") if "longitude" in row.index else None
        if (lat is not None and pd.notna(lat)) or (lon is not None and pd.notna(lon)):
            lat_str = format_number(lat) if pd.notna(lat) else "—"
            lon_str = format_number(lon) if pd.notna(lon) else "—"
            st.markdown(f"**Latitude / Longitude:** {lat_str} / {lon_str}")

    st.markdown("#### Programs and Operations")
    _render_field_block(row, [
        ("Program Types Observed", "program_types_observed"),
        ("Site Type", "site_type"),
        ("Operation Dates Summary", "operation_dates_summary"),
        ("Serving Dates Summary", "serving_dates_summary"),
        ("Meal Types Served", "meal_types_served"),
        ("Service Times Summary", "service_times_summary"),
        ("Public Meal Service Type", "meal_service_type_public"),
        ("SFSP Site Type Public Source", "sfsp_site_type_public"),
        ("Meal Service Methods", "meal_service_methods_summary"),
        ("Program Years Verified", "program_years_verified"),
        ("Source Dataset IDs", "source_dataset_ids"),
    ])

    st.markdown("#### SNP / Eligibility Context")
    _render_field_block(row, [
        ("SNP Flags Summary", "snp_flags_summary"),
        ("Eligibility Indicators Summary", "eligibility_indicators_summary"),
    ])

    st.markdown("#### Activity and Data Quality")
    _render_field_block(row, [
        ("Total Reported Meals", "total_reported_meals"),
        ("Latest Program Year", "latest_program_year"),
        ("Years Active", "years_active"),
        ("Non-Congregate Status", "non_congregate_status"),
        ("Non-Congregate Source", "non_congregate_source"),
        ("Rural / Urban Status", "rural_urban_status"),
        ("Rural / Urban Source", "rural_urban_source"),
        ("Data Quality Flags", "data_quality_flags"),
    ])


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
            "Run `python scripts/12_build_ce_site_lookup_v2.py` first."
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

    if "non_congregate_status" in data.columns:
        nc_options = sorted(data["non_congregate_status"].dropna().astype(str).unique())
        selected_nc_statuses = st.sidebar.multiselect(
            "Non-congregate status", nc_options, placeholder="All NC statuses"
        )
    else:
        selected_nc_statuses = []

    if "rural_urban_status" in data.columns:
        ru_options = sorted(data["rural_urban_status"].dropna().astype(str).unique())
        selected_ru_statuses = st.sidebar.multiselect(
            "Rural / Urban", ru_options, placeholder="All / unmatched"
        )
    else:
        selected_ru_statuses = []

    if "meal_service_type_public" in data.columns:
        mst_options = sorted(data["meal_service_type_public"].dropna().astype(str).unique())
        selected_mst = st.sidebar.multiselect(
            "Public meal service type", mst_options, placeholder="All / unmatched"
        )
    else:
        selected_mst = []

    if "program_years_verified" in data.columns:
        years_verified_options = unique_split_values(data["program_years_verified"])
        selected_years_verified = st.sidebar.multiselect(
            "Program years verified", years_verified_options, placeholder="All / unmatched"
        )
    else:
        selected_years_verified = []

    if "source_dataset_ids" in data.columns:
        source_id_options = unique_split_values(data["source_dataset_ids"])
        selected_source_ids = st.sidebar.multiselect(
            "Verified source dataset", source_id_options, placeholder="All / unmatched"
        )
    else:
        selected_source_ids = []

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
        "nc_statuses": selected_nc_statuses,
        "ru_statuses": selected_ru_statuses,
        "meal_service_types": selected_mst,
        "years_verified": selected_years_verified,
        "source_ids": selected_source_ids,
        "only_with_meals": only_with_meals,
        "only_with_latlon": only_with_latlon,
    })

    # ----- Output -----
    render_metrics(filtered)

    st.markdown("---")

    if filtered.empty:
        st.info("No matching sites found. Try broadening your search or clearing filters.")
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
    render_selected_site_panel(filtered)


if __name__ == "__main__":
    main()
