"""Multi-well comparison analysis helpers.

Builds comparison payloads with aggregated series, derived metrics,
provenance metadata, and export-ready text bundles for the multi-well
data viewer endpoint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from fastapi import HTTPException

from api.helpers import load_site_data
from api.routes._detection import _usgs_site_url
from api.routes._site_analysis import CHART_COLORS, _trend_label
from api.site_metadata import SITE_METADATA

Aggregation = Literal["monthly", "quarterly", "annual"]
Normalization = Literal["raw", "delta_from_first", "zscore"]

_FREQ_MAP: dict[Aggregation, str] = {
    "monthly": "MS",
    "quarterly": "QS",
    "annual": "YS",
}

_AGGREGATION_LABELS: dict[Aggregation, str] = {
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "annual": "Annual",
}


@dataclass
class MultiWellSiteResult:
    """Processed comparison inputs for one site."""

    site_id: str
    name: str
    county: str
    aquifer: str
    confined: bool
    filtered_raw: pd.DataFrame
    aggregated: pd.Series
    source_start: str
    source_end: str
    coverage_pct: float


def _parse_date_window(
    *,
    sites_data: list[pd.DataFrame],
    date_window: dict[str, Any],
) -> tuple[pd.Timestamp, pd.Timestamp, dict[str, Any]]:
    """Resolve the requested date window into concrete UTC-naive timestamps."""
    preset = str(date_window.get("preset", "last_10y"))
    valid_presets = {"last_5y", "last_10y", "full_record", "custom"}
    if preset not in valid_presets:
        raise ValueError(f"Unsupported date window preset: {preset}")

    latest_date = max(df["datetime"].max() for df in sites_data)
    earliest_date = min(df["datetime"].min() for df in sites_data)

    if preset == "full_record":
        start_date = earliest_date.normalize()
        end_date = latest_date.normalize()
    elif preset == "last_5y":
        end_date = latest_date.normalize()
        start_date = (end_date - pd.DateOffset(years=5)).normalize()
    elif preset == "last_10y":
        end_date = latest_date.normalize()
        start_date = (end_date - pd.DateOffset(years=10)).normalize()
    else:
        raw_start = date_window.get("start_date")
        raw_end = date_window.get("end_date")
        if not raw_start or not raw_end:
            raise ValueError("Custom date windows require both start_date and end_date.")
        try:
            start_date = pd.to_datetime(raw_start).normalize()
            end_date = pd.to_datetime(raw_end).normalize()
        except Exception as exc:  # pragma: no cover - pandas exception types vary
            raise ValueError("Malformed start_date or end_date.") from exc

    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")

    return (
        start_date,
        end_date,
        {
            "preset": preset,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
        },
    )


def _period_anchor(timestamp: pd.Timestamp, aggregation: Aggregation) -> pd.Timestamp:
    """Align a timestamp to the start of its aggregation period."""
    if aggregation == "monthly":
        return timestamp.to_period("M").start_time
    if aggregation == "quarterly":
        return timestamp.to_period("Q").start_time
    return timestamp.to_period("Y").start_time


def _expected_periods(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    aggregation: Aggregation,
) -> pd.DatetimeIndex:
    """Return the full expected aggregation bins for the selected window."""
    freq = _FREQ_MAP[aggregation]
    return pd.date_range(
        start=_period_anchor(start_date, aggregation),
        end=_period_anchor(end_date, aggregation),
        freq=freq,
    )


def _aggregate_site_series(
    df: pd.DataFrame,
    *,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    aggregation: Aggregation,
) -> tuple[pd.DataFrame, pd.Series]:
    """Filter raw data first, then aggregate to the requested cadence."""
    filtered = df[(df["datetime"] >= start_date) & (df["datetime"] <= end_date)].copy()
    if filtered.empty:
        return filtered, pd.Series(dtype=float)

    aggregated = (
        filtered.set_index("datetime")["value"].resample(_FREQ_MAP[aggregation]).mean().dropna()
    )
    return filtered, aggregated


def _annual_change_ft_yr(series: pd.Series) -> float:
    """Compute annualized change from the first and last aggregated values."""
    if len(series) < 2:
        return 0.0
    start = series.index[0]
    end = series.index[-1]
    years = max(0.01, (end - start).days / 365.25)
    return float((series.iloc[-1] - series.iloc[0]) / years)


def _seasonal_amplitude_ft(filtered_raw: pd.DataFrame) -> float:
    """Compute seasonal amplitude from filtered raw observations."""
    if filtered_raw.empty:
        return 0.0
    monthly_means = filtered_raw.groupby(filtered_raw["datetime"].dt.month)["value"].mean()
    if monthly_means.empty:
        return 0.0
    return float(monthly_means.max() - monthly_means.min())


def _normalize_series(series: pd.Series, normalization: Normalization) -> pd.Series:
    """Apply chart-only normalization to an aggregated series."""
    if normalization == "raw" or series.empty:
        return series
    if normalization == "delta_from_first":
        return series - float(series.iloc[0])
    std_dev = float(series.std(ddof=0))
    if std_dev == 0:
        return pd.Series(0.0, index=series.index)
    mean = float(series.mean())
    return (series - mean) / std_dev


def _build_primary_chart(
    site_results: list[MultiWellSiteResult],
    *,
    aggregation: Aggregation,
    normalization: Normalization,
    expected_periods: pd.DatetimeIndex,
) -> dict[str, Any]:
    """Build the primary Recharts-ready comparison payload."""
    normalized_maps: dict[str, dict[str, float]] = {}
    all_dates: set[str] = set()
    series: list[dict[str, Any]] = []

    for idx, site in enumerate(site_results):
        normalized = _normalize_series(site.aggregated, normalization)
        date_keys = normalized.index.strftime("%Y-%m-%d").tolist()
        normalized_maps[site.site_id] = {
            date_str: float(value) for date_str, value in zip(date_keys, normalized.tolist())
        }
        all_dates.update(date_keys)
        series.append(
            {
                "key": site.site_id,
                "name": site.name,
                "color": CHART_COLORS[idx % len(CHART_COLORS)],
                "strokeWidth": 2,
                "opacity": 0.9,
            }
        )

    sorted_dates = sorted(all_dates)
    records: list[dict[str, Any]] = []
    if len(site_results) >= 2:
        series.append(
            {
                "key": "avg",
                "name": "Cohort Average",
                "color": "#0f172a",
                "strokeWidth": 2,
                "strokeDasharray": "5 5",
            }
        )

    for date_str in sorted_dates:
        entry: dict[str, Any] = {"date": date_str}
        avg_values: list[float] = []
        for site in site_results:
            site_mapping = normalized_maps[site.site_id]
            if date_str in site_mapping:
                value = site_mapping[date_str]
                entry[site.site_id] = round(value, 3)
                avg_values.append(value)
        if len(site_results) >= 2 and avg_values:
            entry["avg"] = round(sum(avg_values) / len(avg_values), 3)
        records.append(entry)

    y_label = {
        "raw": "Water Level (ft)",
        "delta_from_first": "Change From First Aggregated Value (ft)",
        "zscore": "Standardized Water Level (z-score)",
    }[normalization]

    coverage_values = [site.coverage_pct for site in site_results]
    min_coverage = min(coverage_values) if coverage_values else 0.0
    max_coverage = max(coverage_values) if coverage_values else 0.0
    coverage_note = (
        f"Coverage spans {min_coverage:.1f}% to {max_coverage:.1f}% across selected wells."
    )

    return {
        "chart_type": "comparison",
        "title": f"{_AGGREGATION_LABELS[aggregation]} Groundwater Comparison",
        "x_label": "Date",
        "y_label": y_label,
        "series": series,
        "data": records,
        "insights": [
            (
                f"Normalization mode: {normalization.replace('_', ' ')}. "
                "Derived metrics remain computed from non-normalized aggregated values."
            ),
            (
                f"Expected {_AGGREGATION_LABELS[aggregation].lower()} bins in window: "
                f"{len(expected_periods)}."
            ),
            coverage_note,
        ],
    }


def _build_metrics_table(site_results: list[MultiWellSiteResult]) -> list[dict[str, Any]]:
    """Compute researcher-facing derived metrics from aggregated raw values."""
    rows: list[dict[str, Any]] = []
    for site in site_results:
        series = site.aggregated
        net_change = float(series.iloc[-1] - series.iloc[0]) if len(series) >= 2 else 0.0
        annual_change = _annual_change_ft_yr(series)
        rows.append(
            {
                "site_id": site.site_id,
                "name": site.name,
                "start_date": site.source_start,
                "end_date": site.source_end,
                "record_count": int(len(series)),
                "coverage_pct": round(site.coverage_pct, 1),
                "net_change_ft": round(net_change, 3),
                "annual_change_ft_yr": round(annual_change, 3),
                "mean_level_ft": round(float(series.mean()), 3),
                "std_dev_ft": round(float(series.std(ddof=0)) if len(series) > 1 else 0.0, 3),
                "seasonal_amplitude_ft": round(_seasonal_amplitude_ft(site.filtered_raw), 3),
                "trend": _trend_label(net_change),
            }
        )
    return rows


def _build_secondary_chart_specs(
    site_results: list[MultiWellSiteResult],
    metrics_table: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build secondary workbench views for annual change and seasonal profile."""
    annual_change_values = [
        {
            "site": row["name"],
            "annual_change_ft_yr": row["annual_change_ft_yr"],
            "trend": row["trend"],
        }
        for row in metrics_table
    ]

    seasonal_values: list[dict[str, Any]] = []
    month_order = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    for site in site_results:
        monthly = (
            site.filtered_raw.assign(month_name=site.filtered_raw["datetime"].dt.strftime("%b"))
            .groupby("month_name", as_index=False)["value"]
            .mean()
            .rename(columns={"value": "average_level_ft"})
        )
        monthly["month_name"] = pd.Categorical(monthly["month_name"], month_order, ordered=True)
        monthly = monthly.sort_values("month_name")
        for row in monthly.itertuples():
            seasonal_values.append(
                {
                    "month": str(row.month_name),
                    "average_level_ft": round(float(row.average_level_ft), 3),
                    "site": site.name,
                }
            )

    return [
        {
            "id": "annual-change",
            "kind": "annual_change",
            "title": "Annualized Change",
            "description": "Annualized change computed from the first and last aggregated values.",
            "spec": {
                "type": "bar",
                "data": [{"id": "annualChangeData", "values": annual_change_values}],
                "xField": "site",
                "yField": "annual_change_ft_yr",
                "seriesField": "site",
                "axes": [
                    {"orient": "bottom", "type": "band"},
                    {"orient": "left", "type": "linear", "nice": True},
                ],
            },
        },
        {
            "id": "seasonal-profile",
            "kind": "seasonal_profile",
            "title": "Seasonal Profile",
            "description": (
                "Monthly climatology from filtered raw observations for each selected site."
            ),
            "spec": {
                "type": "line",
                "data": [{"id": "seasonalProfileData", "values": seasonal_values}],
                "xField": "month",
                "yField": "average_level_ft",
                "seriesField": "site",
                "axes": [
                    {"orient": "bottom", "type": "band"},
                    {"orient": "left", "type": "linear", "nice": True},
                ],
                "legends": {"visible": True, "orient": "top"},
            },
        },
    ]


def _csv_from_rows(headers: list[str], rows: list[list[Any]]) -> str:
    """Serialize tabular rows into CSV text."""

    def escape(value: Any) -> str:
        if value is None:
            return ""
        text = str(value)
        if any(char in text for char in [",", '"', "\n"]):
            return '"' + text.replace('"', '""') + '"'
        return text

    return "\n".join(",".join(escape(item) for item in row) for row in [headers, *rows])


def _build_export_bundle(
    primary_chart: dict[str, Any],
    metrics_table: list[dict[str, Any]],
    methods: dict[str, Any],
) -> dict[str, str]:
    """Create client-downloadable CSV and JSON blobs."""
    series_headers = ["date", *[series["name"] for series in primary_chart["series"]]]
    series_rows = []
    for row in primary_chart["data"]:
        series_rows.append(
            [row.get("date"), *[row.get(series["key"]) for series in primary_chart["series"]]]
        )

    metric_headers = [
        "site_id",
        "name",
        "start_date",
        "end_date",
        "record_count",
        "coverage_pct",
        "net_change_ft",
        "annual_change_ft_yr",
        "mean_level_ft",
        "std_dev_ft",
        "seasonal_amplitude_ft",
        "trend",
    ]
    metric_rows = [[row.get(header) for header in metric_headers] for row in metrics_table]

    return {
        "series_csv": _csv_from_rows(series_headers, series_rows),
        "metrics_csv": _csv_from_rows(metric_headers, metric_rows),
        "methods_json": json.dumps(methods, indent=2),
    }


def build_multi_well_payload(
    *,
    site_ids: list[str],
    filters: dict[str, Any] | None,
    date_window: dict[str, Any] | None,
    aggregation: Aggregation,
    normalization: Normalization,
) -> dict[str, Any]:
    """Build the complete multi-well comparison response payload."""
    if not site_ids:
        raise ValueError("site_ids must include at least one site.")
    if len(site_ids) > 8:
        raise ValueError("site_ids may include at most 8 sites.")

    if aggregation not in _FREQ_MAP:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    if normalization not in {"raw", "delta_from_first", "zscore"}:
        raise ValueError(f"Unsupported normalization: {normalization}")

    unique_site_ids = []
    for site_id in site_ids:
        sid = str(site_id).strip()
        if sid and sid not in unique_site_ids:
            unique_site_ids.append(sid)

    sites_data: list[pd.DataFrame] = []
    available_ids: list[str] = []
    for site_id in unique_site_ids:
        if site_id not in SITE_METADATA:
            continue
        try:
            sites_data.append(load_site_data(site_id))
            available_ids.append(site_id)
        except HTTPException:
            continue

    if not sites_data:
        raise HTTPException(status_code=404, detail="No data for selected workbench sites.")

    start_date, end_date, resolved_window = _parse_date_window(
        sites_data=sites_data,
        date_window=date_window or {"preset": "last_10y"},
    )
    expected_periods = _expected_periods(start_date, end_date, aggregation)

    site_results: list[MultiWellSiteResult] = []
    resolved_sites: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []

    for site_id, df in zip(available_ids, sites_data):
        filtered_raw, aggregated = _aggregate_site_series(
            df,
            start_date=start_date,
            end_date=end_date,
            aggregation=aggregation,
        )
        if aggregated.empty:
            continue

        meta = SITE_METADATA[site_id]
        coverage_pct = (
            (len(aggregated) / len(expected_periods) * 100) if len(expected_periods) else 0.0
        )
        site_results.append(
            MultiWellSiteResult(
                site_id=site_id,
                name=meta.get("name", site_id),
                county=meta.get("county", "Florida"),
                aquifer=meta.get("aquifer", "Unknown Aquifer"),
                confined=bool(meta.get("confined", False)),
                filtered_raw=filtered_raw,
                aggregated=aggregated,
                source_start=filtered_raw["datetime"].min().strftime("%Y-%m-%d"),
                source_end=filtered_raw["datetime"].max().strftime("%Y-%m-%d"),
                coverage_pct=coverage_pct,
            )
        )
        resolved_sites.append(
            {
                "site_id": site_id,
                "name": meta.get("name", site_id),
                "county": meta.get("county", "Florida"),
                "aquifer": meta.get("aquifer", "Unknown Aquifer"),
                "confined": bool(meta.get("confined", False)),
                "start_date": filtered_raw["datetime"].min().strftime("%Y-%m-%d"),
                "end_date": filtered_raw["datetime"].max().strftime("%Y-%m-%d"),
                "record_count": int(len(aggregated)),
            }
        )
        citations.append(
            {
                "site_id": site_id,
                "name": meta.get("name", site_id),
                "url": _usgs_site_url(site_id),
            }
        )

    if not site_results:
        raise HTTPException(
            status_code=404,
            detail="No data remained after applying the selected date window.",
        )

    metrics_table = _build_metrics_table(site_results)
    primary_chart = _build_primary_chart(
        site_results,
        aggregation=aggregation,
        normalization=normalization,
        expected_periods=expected_periods,
    )
    chart_specs = _build_secondary_chart_specs(site_results, metrics_table)
    methods = {
        "aggregation": aggregation,
        "normalization": normalization,
        "date_window": resolved_window,
        "filters": filters or {},
        "source_granularity": (
            "Daily USGS observations aggregated to "
            f"{_AGGREGATION_LABELS[aggregation].lower()} bins."
        ),
        "metric_definitions": {
            "coverage_pct": "Percent of expected aggregation bins present in the selected window.",
            "net_change_ft": "Difference between the first and last aggregated raw value.",
            "annual_change_ft_yr": (
                "Net change annualized using elapsed time between the first "
                "and last aggregated bin."
            ),
            "mean_level_ft": "Mean of aggregated raw values within the selected date window.",
            "std_dev_ft": "Population standard deviation of aggregated raw values.",
            "seasonal_amplitude_ft": (
                "Difference between max and min monthly means from filtered raw observations."
            ),
        },
        "normalization_applies_to_chart_only": True,
        "trend_units": "ft/year",
        "caveats": [
            "Metrics table values are computed from filtered, non-normalized aggregated series.",
            "Exports contain aggregated series rather than raw daily observations.",
            "Coverage differences reflect the selected date window and aggregation cadence.",
        ],
    }
    export_bundle = _build_export_bundle(primary_chart, metrics_table, methods)

    return {
        "status": "ok",
        "mode": "multi_well",
        "resolved_sites": resolved_sites,
        "primary_chart": primary_chart,
        "chart_specs": chart_specs,
        "metrics_table": metrics_table,
        "methods": methods,
        "citations": citations,
        "export_bundle": export_bundle,
    }
