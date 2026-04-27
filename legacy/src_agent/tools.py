"""Custom tools for researcher-facing groundwater analysis workflows."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from langchain_core.tools import tool

# Project root: src/agent/tools.py -> src/agent -> src -> <project root>
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"


# ---------------------------------------------------------------------------
# Module-level caches — avoid re-reading files on every tool invocation
# ---------------------------------------------------------------------------
_SITE_METADATA_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
_SITE_CSV_CACHE: Dict[str, Optional[pd.DataFrame]] = {}


# ---------------------------------------------------------------------------
# Visualization tools (Session 8)
# ---------------------------------------------------------------------------


def _load_site_csv(site_id: str) -> pd.DataFrame:
    """Load CSV for a single USGS site and return a date-indexed DataFrame.

    The per-site CSVs use columns ``datetime`` and ``value``.
    This helper normalises them to ``date`` and ``water_level_ft``
    so that downstream tools can use a consistent schema.

    Results are cached in ``_SITE_CSV_CACHE``.
    """
    if site_id in _SITE_CSV_CACHE:
        cached = _SITE_CSV_CACHE[site_id]
        if cached is None:
            raise FileNotFoundError(f"No data file for site {site_id}")
        return cached

    csv_path = DATA_DIR / f"usgs_{site_id}.csv"
    if not csv_path.exists():
        _SITE_CSV_CACHE[site_id] = None
        raise FileNotFoundError(f"No data file for site {site_id}")
    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    df = df.rename(columns={"datetime": "date", "value": "water_level_ft"})
    df = df.sort_values("date")
    _SITE_CSV_CACHE[site_id] = df
    return df


@tool
def generate_time_series_plot(
    site_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_rolling_avg: bool = True,
) -> str:
    """Generate time-series chart data for a USGS site.

    Returns a JSON string with ``type: "chart"`` that the frontend can
    render as an interactive Recharts line chart.

    Args:
        site_id: USGS site number (e.g. "262724081260701")
        start_date: Optional start date YYYY-MM-DD
        end_date: Optional end date YYYY-MM-DD
        include_rolling_avg: Include a 30-day rolling average line

    Returns:
        JSON string with chart_type, title, series, and data arrays.
    """
    try:
        df = _load_site_csv(site_id)

        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]

        if df.empty:
            return json.dumps({"type": "chart", "error": "No data for the requested range."})

        records = []
        levels = df["water_level_ft"].tolist()
        dates = df["date"].dt.strftime("%Y-%m-%d").tolist()

        window = 30
        for i, (d, lvl) in enumerate(zip(dates, levels)):
            entry: Dict[str, Any] = {"date": d, "level": round(lvl, 2)}
            if include_rolling_avg and i >= window - 1:
                avg = float(np.mean(levels[max(0, i - window + 1) : i + 1]))
                entry["rollingAvg"] = round(avg, 2)
            records.append(entry)

        chart = {
            "type": "chart",
            "chart_type": "time_series",
            "title": f"Water Level — Site {site_id}",
            "x_label": "Date",
            "y_label": "Water Level (ft)",
            "series": [
                {"key": "level", "name": "Water Level", "color": "#3b82f6"},
            ],
            "data": records,
        }
        if include_rolling_avg:
            chart["series"].append({"key": "rollingAvg", "name": "30-Day Avg", "color": "#f59e0b"})

        return json.dumps(chart)

    except FileNotFoundError as exc:
        return json.dumps({"type": "chart", "error": str(exc)})
    except Exception as exc:
        return json.dumps({"type": "chart", "error": f"Chart generation failed: {exc}"})


@tool
def generate_comparison_chart(
    site_ids: List[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """Generate a multi-site comparison chart overlaying water levels.

    Args:
        site_ids: List of USGS site numbers to compare (max 5).
        start_date: Optional start date YYYY-MM-DD.
        end_date: Optional end date YYYY-MM-DD.

    Returns:
        JSON string with chart data for all requested sites.
    """
    COLORS = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6"]

    try:
        if len(site_ids) > 5:
            site_ids = site_ids[:5]

        # Collect data per site
        all_dates: set = set()
        site_data: Dict[str, Dict[str, float]] = {}

        for sid in site_ids:
            try:
                df = _load_site_csv(sid)
                if start_date:
                    df = df[df["date"] >= pd.Timestamp(start_date)]
                if end_date:
                    df = df[df["date"] <= pd.Timestamp(end_date)]
                mapping = dict(
                    zip(
                        df["date"].dt.strftime("%Y-%m-%d"),
                        df["water_level_ft"].round(2),
                    )
                )
                site_data[sid] = mapping
                all_dates.update(mapping.keys())
            except FileNotFoundError:
                continue

        if not site_data:
            return json.dumps({"type": "chart", "error": "No data found for any site."})

        sorted_dates = sorted(all_dates)
        records = []
        for d in sorted_dates:
            entry: Dict[str, Any] = {"date": d}
            for sid in site_data:
                if d in site_data[sid]:
                    entry[sid] = site_data[sid][d]
            records.append(entry)

        series = [
            {"key": sid, "name": f"Site {sid[-6:]}", "color": COLORS[i % len(COLORS)]}
            for i, sid in enumerate(site_data)
        ]

        chart = {
            "type": "chart",
            "chart_type": "comparison",
            "title": f"Water Level Comparison — {len(site_data)} Sites",
            "x_label": "Date",
            "y_label": "Water Level (ft)",
            "series": series,
            "data": records,
        }
        return json.dumps(chart)

    except Exception as exc:
        return json.dumps({"type": "chart", "error": f"Comparison failed: {exc}"})


# ---------------------------------------------------------------------------
# Site-aware tools (Agent Enhancement Session)
# ---------------------------------------------------------------------------


def _load_site_metadata() -> Dict[str, Dict[str, Any]]:
    """Load site metadata from config/usgs_sites.json.

    Returns a flat ``{site_id: {name, aquifer, county, lat, lng}}`` dict.
    Results are cached in ``_SITE_METADATA_CACHE``.
    """
    global _SITE_METADATA_CACHE
    if _SITE_METADATA_CACHE is not None:
        return _SITE_METADATA_CACHE

    meta_path = CONFIG_DIR / "usgs_sites.json"
    if not meta_path.exists():
        return {}
    with open(meta_path) as fh:
        raw = json.load(fh)
    flat: Dict[str, Dict[str, Any]] = {}
    for _aq_key, aq_info in raw.get("aquifers", {}).items():
        aquifer_name = aq_info.get("name", _aq_key)
        aquifer_type = aq_info.get("aquifer_type", "unconfined")
        aq_confined = aquifer_type == "confined"
        aq_depth_range = aq_info.get("depth_range_ft", [0, 100])
        aq_description = aq_info.get("description", "")
        zones_by_name = {z["zone_name"]: z for z in aq_info.get("zones", [])}

        for site in aq_info.get("sites", []):
            sid = site["site_id"]
            site_zone = site.get("aquifer_zone", "")
            zone_detail = zones_by_name.get(site_zone, {})
            flat[sid] = {
                "name": site.get("name", sid),
                "aquifer": aquifer_name,
                "aquifer_type": aquifer_type,
                "county": site.get("county", "Unknown"),
                "lat": site.get("lat"),
                "lng": site.get("lng"),
                "well_depth_ft": site.get("well_depth_ft"),
                "aquifer_zone": site_zone,
                "confined": site.get("confined", aq_confined),
                "aquifer_description": zone_detail.get("description", aq_description),
                "depth_range_ft": zone_detail.get("depth_range_ft", aq_depth_range),
            }
    _SITE_METADATA_CACHE = flat
    return flat


@tool
def list_available_sites(
    county: Optional[str] = None,
    aquifer: Optional[str] = None,
) -> str:
    """List available USGS groundwater monitoring sites.

    Use this tool to discover which sites exist, then use
    ``query_site_data`` for detailed data about a specific site.

    Args:
        county: Optional filter by county name (e.g. "Lee", "Miami-Dade").
        aquifer: Optional filter by aquifer (e.g. "Biscayne", "Floridan").

    Returns:
        Formatted list of sites with name, county, aquifer, zone,
        confined/unconfined status, well depth, and coordinates.
    """
    meta = _load_site_metadata()
    if not meta:
        return "No site metadata available."

    sites = list(meta.items())

    if county:
        county_lower = county.lower()
        sites = [(sid, m) for sid, m in sites if county_lower in m.get("county", "").lower()]
    if aquifer:
        aq_lower = aquifer.lower()
        sites = [(sid, m) for sid, m in sites if aq_lower in m.get("aquifer", "").lower()]

    if not sites:
        return "No sites match the given filters."

    lines = [f"📍 **Available Sites** ({len(sites)} total):\n"]
    for sid, m in sites:
        has_data = (DATA_DIR / f"usgs_{sid}.csv").exists()
        status = "✅" if has_data else "⬜"
        confined_label = "confined" if m.get("confined") else "unconfined"
        depth_str = f", depth {m['well_depth_ft']} ft" if m.get("well_depth_ft") else ""
        zone_str = f" [{m['aquifer_zone']}]" if m.get("aquifer_zone") else ""
        coords = ""
        if m.get("lat") and m.get("lng"):
            coords = f" ({m['lat']:.3f}°N, {abs(m['lng']):.3f}°W)"
        lines.append(
            f"  {status} **{m['name']}** ({sid})"
            f" — {m['county']}, {m['aquifer']}{zone_str}"
            f" ({confined_label}{depth_str}){coords}"
        )
    return "\n".join(lines)


@tool
def query_site_data(
    site_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    stat_type: str = "summary",
) -> str:
    """Query data for a specific USGS monitoring site.

    This tool operates on per-site CSV files (``usgs_<site_id>.csv``).
    Use ``list_available_sites`` first to find valid site IDs.

    Args:
        site_id: USGS site number (e.g. "262724081260701").
        start_date: Optional start date YYYY-MM-DD.
        end_date: Optional end date YYYY-MM-DD.
        stat_type: 'summary', 'monthly', 'yearly', or 'raw'.

    Returns:
        Formatted string with full well card (aquifer, zone, confined
        status, well depth, depth range, coordinates, description)
        plus site-specific groundwater analysis.
    """
    try:
        df = _load_site_csv(site_id)
    except FileNotFoundError:
        return f"No data file found for site {site_id}."

    meta = _load_site_metadata().get(site_id, {})
    site_name = meta.get("name", site_id)

    if start_date:
        df = df[df["date"] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df["date"] <= pd.Timestamp(end_date)]

    if df.empty:
        return f"No data for site {site_name} in the requested range."

    col = "water_level_ft"

    if stat_type == "summary":
        tail30 = df.tail(30)
        recent_chg = tail30.iloc[-1][col] - tail30.iloc[0][col] if len(tail30) > 1 else 0.0
        confined_label = "Confined" if meta.get("confined") else "Unconfined"
        well_card = (
            f"📊 **{site_name}** (site {site_id})\n"
            f"   Aquifer: {meta.get('aquifer', 'N/A')} ({confined_label})\n"
            f"   Zone: {meta.get('aquifer_zone') or 'N/A'}\n"
            f"   County: {meta.get('county', 'N/A')}\n"
            f"   Well Depth: {meta.get('well_depth_ft', 'N/A')} ft\n"
            f"   Aquifer Depth Range: {meta.get('depth_range_ft', 'N/A')} ft\n"
        )
        if meta.get("lat") and meta.get("lng"):
            well_card += f"   Coordinates: {meta['lat']:.5f}°N, {abs(meta['lng']):.5f}°W\n"
        if meta.get("aquifer_description"):
            well_card += f"   Description: {meta['aquifer_description']}\n"
        well_card += (
            f"   Date range: "
            f"{df['date'].min():%Y-%m-%d} → {df['date'].max():%Y-%m-%d}\n"
            f"   Records: {len(df):,}\n"
            f"   Mean: {df[col].mean():.2f} ft | "
            f"Min: {df[col].min():.2f} ft | "
            f"Max: {df[col].max():.2f} ft\n"
            f"   Std Dev: {df[col].std():.2f} ft\n"
            f"   Recent 30-day change: {recent_chg:+.2f} ft"
        )
        return well_card

    if stat_type == "monthly":
        df["month"] = df["date"].dt.to_period("M")
        monthly = df.groupby("month")[col].agg(["mean", "min", "max"])
        lines = [f"📅 **Monthly** — {site_name}:"]
        for month, row in monthly.tail(12).iterrows():
            lines.append(
                f"  {month}: {row['mean']:.2f} ft " f"(range {row['min']:.2f}–{row['max']:.2f})"
            )
        return "\n".join(lines)

    if stat_type == "yearly":
        df["year"] = df["date"].dt.year
        yearly = df.groupby("year")[col].agg(["mean", "count"])
        lines = [f"📆 **Yearly** — {site_name}:"]
        for year, row in yearly.iterrows():
            lines.append(f"  {year}: avg {row['mean']:.2f} ft " f"({int(row['count'])} records)")
        return "\n".join(lines)

    if stat_type == "raw":
        lines = [f"📋 **Recent 10 records** — {site_name}:"]
        for _, row in df.tail(10).iterrows():
            lines.append(f"  {row['date']:%Y-%m-%d}: {row[col]:.2f} ft")
        return "\n".join(lines)

    return f"Unknown stat_type: {stat_type}. " "Use 'summary', 'monthly', 'yearly', or 'raw'."


# ---------------------------------------------------------------------------
# Tool registry — exposed to the LangGraph agent.
# ---------------------------------------------------------------------------
GROUNDWATER_TOOLS = [
    generate_time_series_plot,
    generate_comparison_chart,
    list_available_sites,
    query_site_data,
]
