"""Data routes — USGS site listing, time-series, heatmap, comparison, charts.

All endpoints under ``/api/sites`` and ``/api/compare`` live here.
"""

from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException

from api.helpers import calculate_stats, load_site_data
from api.site_metadata import DATA_DIR, SITE_METADATA

router = APIRouter(prefix="/api", tags=["data"])


# ------------------------------------------------------------------
# Site listing & detail
# ------------------------------------------------------------------


@router.get("/sites")
def get_sites():
    """Get list of all monitoring sites with metadata."""
    sites = []
    for site_id, metadata in SITE_METADATA.items():
        csv_path = DATA_DIR / f"usgs_{site_id}.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            metadata_copy = metadata.copy()
            metadata_copy["recordCount"] = len(df)
            sites.append(metadata_copy)
    return {"sites": sites}


@router.get("/sites/{site_id}")
def get_site(site_id: str):
    """Get metadata and statistics for a specific site."""
    if site_id not in SITE_METADATA:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")

    df = load_site_data(site_id)
    stats = calculate_stats(df)
    return {"site": SITE_METADATA[site_id], "stats": stats}


@router.get("/sites/{site_id}/data")
def get_site_data(
    site_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """Get time series data for a specific site."""
    df = load_site_data(site_id)

    if start_date:
        df = df[df["datetime"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["datetime"] <= pd.to_datetime(end_date)]

    data = []
    for _, row in df.iterrows():
        data.append(
            {
                "date": row["datetime"].isoformat(),
                "level": round(float(row["value"]), 2),
                "year": int(row["year"]),
                "month": row["datetime"].month,
            }
        )

    stats = calculate_stats(df)
    return {"site": SITE_METADATA.get(site_id, {}), "data": data, "stats": stats}


@router.get("/sites/{site_id}/heatmap")
def get_heatmap_data(site_id: str):
    """Get heatmap data with monthly averages by year."""
    df = load_site_data(site_id)

    df["month"] = df["datetime"].dt.month
    df["year"] = df["datetime"].dt.year

    monthly = df.groupby(["year", "month"])["value"].mean().reset_index()

    heatmap_data = []
    for _, row in monthly.iterrows():
        heatmap_data.append(
            {
                "year": int(row["year"]),
                "month": int(row["month"]),
                "value": round(float(row["value"]), 2),
            }
        )

    values = monthly["value"]
    return {
        "data": heatmap_data,
        "min": round(float(values.min()), 2),
        "max": round(float(values.max()), 2),
    }


@router.get("/compare")
def compare_sites(site_ids: str):
    """Compare multiple sites by their statistics."""
    ids = site_ids.split(",")
    comparison = []

    for site_id in ids:
        sid = site_id.strip()
        if sid in SITE_METADATA:
            try:
                df = load_site_data(sid)
                stats = calculate_stats(df)
                comparison.append({"site": SITE_METADATA[sid], "stats": stats})
            except HTTPException:
                pass

    return {"comparison": comparison}


# ------------------------------------------------------------------
# Chart endpoints (Session 8)
# ------------------------------------------------------------------


@router.get("/sites/{site_id}/chart")
def get_site_chart(
    site_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    rolling_window: int = 30,
):
    """Return Recharts-ready time-series JSON for a single site."""
    if site_id not in SITE_METADATA:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")

    df = load_site_data(site_id)
    if start_date:
        df = df[df["datetime"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["datetime"] <= pd.to_datetime(end_date)]

    if df.empty:
        raise HTTPException(status_code=404, detail="No data for date range")

    levels = df["value"].tolist()
    dates = df["datetime"].dt.strftime("%Y-%m-%d").tolist()

    records = []
    for i, (d, lvl) in enumerate(zip(dates, levels)):
        entry = {"date": d, "level": round(float(lvl), 2)}
        if i >= rolling_window - 1:
            window = levels[max(0, i - rolling_window + 1) : i + 1]
            entry["rollingAvg"] = round(sum(window) / len(window), 2)
        records.append(entry)

    meta = SITE_METADATA[site_id]
    return {
        "chart_type": "time_series",
        "title": f"{meta.get('name', site_id)} — Water Level",
        "x_label": "Date",
        "y_label": "Water Level (ft)",
        "series": [
            {"key": "level", "name": "Water Level", "color": "#3b82f6"},
            {
                "key": "rollingAvg",
                "name": f"{rolling_window}-Day Avg",
                "color": "#f59e0b",
            },
        ],
        "data": records,
        "site": meta,
    }


@router.get("/compare/chart")
def get_comparison_chart(
    site_ids: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """Return Recharts-ready multi-site overlay JSON."""
    ids = [s.strip() for s in site_ids.split(",") if s.strip()][:5]
    colors = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6"]

    all_dates: set = set()
    site_data: dict = {}

    for sid in ids:
        if sid not in SITE_METADATA:
            continue
        try:
            df = load_site_data(sid)
            if start_date:
                df = df[df["datetime"] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df["datetime"] <= pd.to_datetime(end_date)]
            mapping = dict(
                zip(
                    df["datetime"].dt.strftime("%Y-%m-%d"),
                    df["value"].round(2),
                )
            )
            site_data[sid] = mapping
            all_dates.update(mapping.keys())
        except HTTPException:
            continue

    if not site_data:
        raise HTTPException(status_code=404, detail="No data for any site")

    sorted_dates = sorted(all_dates)
    records = []
    for d in sorted_dates:
        entry: dict = {"date": d}
        for sid in site_data:
            if d in site_data[sid]:
                entry[sid] = float(site_data[sid][d])
        records.append(entry)

    series = [
        {
            "key": sid,
            "name": SITE_METADATA.get(sid, {}).get("name", sid[-6:]),
            "color": colors[i % len(colors)],
        }
        for i, sid in enumerate(site_data)
    ]

    return {
        "chart_type": "comparison",
        "title": f"Water Level Comparison — {len(site_data)} Sites",
        "x_label": "Date",
        "y_label": "Water Level (ft)",
        "series": series,
        "data": records,
    }
