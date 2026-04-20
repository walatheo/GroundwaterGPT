"""Query detection chain, geo utilities, and site lookup helpers.

Extracted from ``chat.py`` to keep that module focused on endpoint handlers.
All public names are re-exported from ``chat.py`` for backward compatibility.

Detection order:
  1. Site-name  → specific wells (G-3336, C-1224, 15-digit IDs)
  2. Aquifer    → all cohort sites (Biscayne, Floridan, Tamiami, etc.)
  3. Location   → nearest sites (Estero, Miami-Dade, Naples, etc.)
  4. Network    → all 40 sites ("all wells", "which county", etc.)
"""

from __future__ import annotations

import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import pandas as pd

from api.site_metadata import SITE_METADATA

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
ESTERO_REFERENCE_LAT = 26.4381
ESTERO_REFERENCE_LNG = -81.8068


# ---------------------------------------------------------------------------
# Aquifer zone reference — loaded once at import time
# ---------------------------------------------------------------------------


def _load_aquifer_zones() -> dict[str, list[dict]]:
    json_path = _CONFIG_DIR / "usgs_sites.json"
    if not json_path.exists():
        return {}
    try:
        with open(json_path) as fh:
            raw = json.load(fh)
        return {aq.get("name", ""): aq.get("zones", []) for aq in raw.get("aquifers", {}).values()}
    except Exception:
        return {}


_AQUIFER_ZONES_REFERENCE: dict[str, list[dict]] = _load_aquifer_zones()


# ---------------------------------------------------------------------------
# Water supply sources — municipality → supply aquifer mappings
# ---------------------------------------------------------------------------


def _load_water_supply_sources() -> dict:
    json_path = _CONFIG_DIR / "water_supply_sources.json"
    if not json_path.exists():
        return {}
    try:
        with open(json_path) as fh:
            raw = json.load(fh)
        return raw.get("municipalities", {})
    except Exception:
        return {}


_WATER_SUPPLY_SOURCES: dict = _load_water_supply_sources()

_SUPPLY_QUERY_RE = re.compile(
    r"\b(water\s*supply|drinking\s*water|supply\s*source|municipal\s*supply"
    r"|water\s*source|supply\s*aquifer|where\s+does.*get.*water"
    r"|what\s+aquifer.*supply|what\s+are\s+the\s+groundwater\s+sources"
    r"|what\s+groundwater\s+sources)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# USGS URL helper
# ---------------------------------------------------------------------------


def _usgs_site_url(site_id: str) -> str:
    """Return canonical USGS page for a monitoring site."""
    return f"https://waterdata.usgs.gov/monitoring-location/{site_id}/"


# ---------------------------------------------------------------------------
# Location keyword → (ref_lat, ref_lng, display_name, county_hint)
# ---------------------------------------------------------------------------

_LOCATION_REFERENCE_POINTS: dict[str, tuple[float, float, str, Optional[str]]] = {
    # Lee County
    "estero": (26.4381, -81.8068, "Estero", "lee"),
    "fort myers": (26.6406, -81.8723, "Fort Myers", "lee"),
    "cape coral": (26.5629, -81.9495, "Cape Coral", "lee"),
    "bonita springs": (26.3398, -81.7787, "Bonita Springs", "lee"),
    "lee county": (26.5, -81.8, "Lee County", "lee"),
    "lee": (26.5, -81.7, "Lee County", "lee"),
    "charlotte harbor": (26.58, -82.04, "Charlotte Harbor Area", "lee"),
    # Collier County
    "naples": (26.1420, -81.7948, "Naples", "collier"),
    "marco island": (25.9406, -81.7223, "Marco Island", "collier"),
    "collier county": (26.0, -81.5, "Collier County", "collier"),
    "collier": (26.0, -81.5, "Collier County", "collier"),
    "immokalee": (26.4194, -81.4160, "Immokalee", "collier"),
    # Miami-Dade County
    "miami": (25.7617, -80.1918, "Miami", "miami-dade"),
    "miami-dade": (25.7617, -80.1918, "Miami-Dade", "miami-dade"),
    "miami dade": (25.7617, -80.1918, "Miami-Dade", "miami-dade"),
    "biscayne": (25.5, -80.4, "Biscayne Aquifer Area", "miami-dade"),
    "homestead": (25.4687, -80.4776, "Homestead", "miami-dade"),
    "florida city": (25.4477, -80.4787, "Florida City", "miami-dade"),
    "kendall": (25.6751, -80.4201, "Kendall", "miami-dade"),
    # Sarasota County
    "sarasota": (27.3364, -82.5307, "Sarasota", "sarasota"),
    "verna": (27.3390, -82.3301, "Verna", "sarasota"),
    # Hendry County
    "hendry": (26.5, -81.1, "Hendry County", "hendry"),
    "hendry county": (26.5, -81.1, "Hendry County", "hendry"),
    "labelle": (26.7637, -81.4395, "LaBelle", "hendry"),
    "clewiston": (26.7534, -80.9351, "Clewiston", "hendry"),
    # General / aquifer
    "everglades": (25.9, -80.7, "Everglades Area", None),
    "florida": (26.5, -81.0, "Florida", None),
}


def _detect_location(question: str) -> Optional[tuple[float, float, str, Optional[str]]]:
    """Return (lat, lng, display_name, county_hint) for the first location keyword found.

    Uses word-boundary matching so "florida" does not match inside "floridan",
    and prefers longer keywords to avoid "miami" shadowing "miami-dade".
    """
    matches = _detect_locations(question, max_matches=1)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Aquifer keyword → (aquifer_key, display_name)
# ---------------------------------------------------------------------------

_AQUIFER_DETECTION_MAP: dict[str, tuple[str, str]] = {
    "biscayne aquifer": ("biscayne", "Biscayne Aquifer"),
    "biscanye aquifer": ("biscayne", "Biscayne Aquifer"),
    "biscayne": ("biscayne", "Biscayne Aquifer"),
    "biscanye": ("biscayne", "Biscayne Aquifer"),
    "surficial aquifer system": ("surficial", "Surficial Aquifer"),
    "surficial aquifer": ("surficial", "Surficial Aquifer"),
    "surficial": ("surficial", "Surficial Aquifer"),
    "water table aquifer": ("surficial", "Surficial Aquifer"),
    "tamiami aquifer system": ("tamiami", "Tamiami Aquifer System"),
    "tamiami aquifer": ("tamiami", "Tamiami Aquifer System"),
    "lower tamiami": ("tamiami", "Tamiami Aquifer System"),
    "tamiami": ("tamiami", "Tamiami Aquifer System"),
    "intermediate aquifer system": ("intermediate", "Intermediate Aquifer System"),
    "intermediate aquifer": ("intermediate", "Intermediate Aquifer System"),
    "sand and shell": ("intermediate", "Intermediate Aquifer System"),
    "hawthorn group": ("hawthorn", "Hawthorn Group"),
    "hawthorn formation": ("hawthorn", "Hawthorn Group"),
    "hawthorn": ("hawthorn", "Hawthorn Group"),
    "floridan aquifer system": ("floridan", "Floridan Aquifer System"),
    "floridan aquifer": ("floridan", "Floridan Aquifer System"),
    "upper floridan": ("floridan", "Floridan Aquifer System"),
    "lower floridan": ("floridan", "Floridan Aquifer System"),
    "tampa limestone": ("floridan", "Floridan Aquifer System"),
    "floridan": ("floridan", "Floridan Aquifer System"),
}

_AQUIFER_NEEDLE: dict[str, str] = {
    "biscayne": "biscayne",
    "surficial": "surficial",
    "tamiami": "tamiami",
    "intermediate": "intermediate",
    "hawthorn": "hawthorn",
    "floridan": "floridan",
}


def _detect_aquifer(question: str) -> Optional[tuple[str, str]]:
    """Return (aquifer_key, display_name) for the first aquifer name found.

    Uses word-boundary matching and longest-first ordering.
    Returns None when no aquifer keyword is matched.
    """
    q = question.lower()
    for keyword in sorted(_AQUIFER_DETECTION_MAP, key=len, reverse=True):
        if re.search(r"\b" + re.escape(keyword) + r"\b", q):
            return _AQUIFER_DETECTION_MAP[keyword]
    return None


def _detect_locations(
    question: str, max_matches: int = 4
) -> list[tuple[float, float, str, Optional[str]]]:
    """Return multiple non-overlapping location matches in query order."""
    q = question.lower()
    matches: list[tuple[int, int, tuple[float, float, str, Optional[str]]]] = []
    occupied_spans: list[tuple[int, int]] = []
    seen_labels: set[str] = set()

    for keyword in sorted(_LOCATION_REFERENCE_POINTS, key=len, reverse=True):
        for hit in re.finditer(r"\b" + re.escape(keyword) + r"\b", q):
            start, end = hit.span()
            if any(
                not (end <= occ_start or start >= occ_end) for occ_start, occ_end in occupied_spans
            ):
                continue
            candidate = _LOCATION_REFERENCE_POINTS[keyword]
            label = candidate[2].lower()
            if label in seen_labels:
                continue
            matches.append((start, end, candidate))
            occupied_spans.append((start, end))
            seen_labels.add(label)
            break

    matches.sort(key=lambda item: item[0])
    ordered = [candidate for _, _, candidate in matches]

    # Drop generic statewide catch-alls when a more specific location is present.
    generic_labels = {"florida", "everglades area"}
    if any(candidate[2].lower() not in generic_labels for candidate in ordered):
        ordered = [candidate for candidate in ordered if candidate[2].lower() not in generic_labels]

    return ordered[:max_matches]


# ---------------------------------------------------------------------------
# Geo utilities
# ---------------------------------------------------------------------------


def _distance_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Approximate distance using lat/lng deltas (no projection needed for proximity ranking)."""
    return ((lat1 - lat2) ** 2 + (lng1 - lng2) ** 2) ** 0.5


def _distance_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Approximate distance in miles using Haversine formula."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing_label(lat1: float, lng1: float, lat2: float, lng2: float) -> str:
    """Cardinal direction from point 1 to point 2."""
    dlng = math.radians(lng2 - lng1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlng) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlng)
    bearing = (math.degrees(math.atan2(x, y)) + 360) % 360
    dirs = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    return dirs[int((bearing + 11.25) / 22.5) % 16]


# ---------------------------------------------------------------------------
# Site timeseries loading (cached)
# ---------------------------------------------------------------------------

_SITE_SERIES_CACHE: dict[str, Optional[pd.DataFrame]] = {}
_SITE_RECORD_CACHE: dict[str, dict] = {}
_ALL_SITES_WITH_DATA_CACHE: list[dict] | None = None


def _load_site_timeseries(site_id: str) -> Optional[pd.DataFrame]:
    """Load per-site groundwater series, returning cached copy when available."""
    if site_id in _SITE_SERIES_CACHE:
        return _SITE_SERIES_CACHE[site_id]

    csv_path = DATA_DIR / f"usgs_{site_id}.csv"
    if not csv_path.exists():
        _SITE_SERIES_CACHE[site_id] = None
        return None

    try:
        df = pd.read_csv(csv_path)
        if "datetime" not in df.columns or "value" not in df.columns:
            _SITE_SERIES_CACHE[site_id] = None
            return None
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["datetime", "value"]).sort_values("datetime")
        result: Optional[pd.DataFrame] = df if not df.empty else None
        _SITE_SERIES_CACHE[site_id] = result
        return result
    except Exception:
        _SITE_SERIES_CACHE[site_id] = None
        return None


def _base_site_record(site_id: str) -> Optional[dict]:
    """Return cached site metadata + loaded series for repeated routing calls."""
    cached = _SITE_RECORD_CACHE.get(site_id)
    if cached is not None:
        return cached

    series = _load_site_timeseries(site_id)
    if series is None:
        return None

    meta = SITE_METADATA[site_id]
    record = {
        "site_id": site_id,
        "name": meta.get("name", site_id),
        "county": meta.get("county", "Florida"),
        "aquifer": meta.get("aquifer", "Unknown Aquifer"),
        "aquifer_type": meta.get("aquifer_type", "unconfined"),
        "confined": meta.get("confined", False),
        "aquifer_zone": meta.get("aquifer_zone", ""),
        "aquifer_zone_depth_range_ft": meta.get("aquifer_zone_depth_range_ft", [0, 100]),
        "aquifer_description": meta.get("aquifer_description", ""),
        "well_depth_ft": meta.get("well_depth_ft"),
        "lat": meta.get("lat"),
        "lng": meta.get("lng"),
        "series": series,
    }
    _SITE_RECORD_CACHE[site_id] = record
    return record


def warm_detection_caches(*, max_workers: int = 8) -> None:
    """Preload local USGS series and derived site records for lower cold-start latency."""
    site_ids = list(SITE_METADATA.keys())
    if not site_ids:
        return

    workers = max(1, min(max_workers, len(site_ids)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gw-prewarm") as executor:
        list(executor.map(_load_site_timeseries, site_ids))

    for site_id in site_ids:
        _base_site_record(site_id)

    global _ALL_SITES_WITH_DATA_CACHE
    _ALL_SITES_WITH_DATA_CACHE = [
        record
        for site_id in sorted(
            site_ids,
            key=lambda sid: (
                str(SITE_METADATA[sid].get("county", "Florida")),
                str(SITE_METADATA[sid].get("name", sid)),
            ),
        )
        if (record := _base_site_record(site_id)) is not None
    ]


# ---------------------------------------------------------------------------
# Site selection helpers
# ---------------------------------------------------------------------------


def _best_sites_near(
    ref_lat: float,
    ref_lng: float,
    county_hint: Optional[str] = None,
    max_sites: int = 3,
) -> list[dict]:
    """Select nearest available sites to an arbitrary reference point.

    ``county_hint`` (lowercase county name) gives a small proximity bonus so
    sites in the expected county are preferred when equidistant.
    """
    candidates = []
    for site_id, meta in SITE_METADATA.items():
        lat = meta.get("lat")
        lng = meta.get("lng")
        if lat is None or lng is None:
            continue
        base = _base_site_record(site_id)
        if base is None:
            continue

        county = str(meta.get("county", "")).strip().lower()
        county_bonus = -0.3 if county_hint and county == county_hint else 0.0
        distance_score = _distance_between(float(lat), float(lng), ref_lat, ref_lng) + county_bonus
        candidates.append(
            {**base, "distance_score": distance_score, "lat": float(lat), "lng": float(lng)}
        )

    candidates = sorted(candidates, key=lambda item: item["distance_score"])
    return candidates[:max_sites]


def _best_estero_sites(max_sites: int = 3) -> list[dict]:
    """Backwards-compatible wrapper — selects nearest sites to Estero."""
    return _best_sites_near(ESTERO_REFERENCE_LAT, ESTERO_REFERENCE_LNG, "lee", max_sites)


def _sites_for_aquifer(aquifer_key: str, max_sites: int = 8) -> list[dict]:
    """Return up to max_sites sites belonging to aquifer_key, with loaded timeseries.

    Each returned dict has the same shape as ``_best_sites_near()`` output so it
    is a drop-in argument for ``_site_research_fallback()``.
    """
    needle = _AQUIFER_NEEDLE.get(aquifer_key, aquifer_key)
    candidates = []
    for site_id, meta in SITE_METADATA.items():
        if needle not in meta.get("aquifer", "").lower():
            continue
        base = _base_site_record(site_id)
        if base is None:
            continue
        candidates.append(base)
    candidates.sort(key=lambda s: (s["county"], s["name"]))
    return candidates[:max_sites]


# ---------------------------------------------------------------------------
# Aquifer query keywords
# ---------------------------------------------------------------------------

_AQUIFER_QUERY_KEYWORDS = [
    "which aquifer",
    "what aquifer",
    "aquifer type",
    "aquifer zone",
    "confined",
    "unconfined",
    "artesian",
    "aquifer depth",
    "well depth",
    "how deep",
]


def _is_aquifer_query(question: str) -> bool:
    """Return True when the question is specifically about aquifer type or well depth."""
    q = question.lower()
    return any(kw in q for kw in _AQUIFER_QUERY_KEYWORDS)


# ---------------------------------------------------------------------------
# Site-name detection
# ---------------------------------------------------------------------------

_WELL_NAME_RE = re.compile(r"\b([A-Za-z]{1,3})[\s\-]?(\d{3,5})\b")
_RAW_SITE_ID_RE = re.compile(r"\b(\d{15})\b")


def _detect_site_names(question: str) -> list[dict]:
    """Extract well names / site IDs from query and return matching site dicts.

    Handles formats: G-3336, G 3336, G3336, C-1224, 252007080335701.
    Returns site dicts in the same shape as ``_best_sites_near()`` output.
    """
    matched_ids: list[str] = []

    # Build a quick lookup: normalised well-name → site_id
    name_to_id: dict[str, str] = {}
    for site_id, meta in SITE_METADATA.items():
        name = meta.get("name", "")
        parts = name.split()
        for part in parts:
            normalised = part.lower().replace("-", "")
            if normalised and any(c.isdigit() for c in normalised):
                name_to_id[normalised] = site_id

    # Match well-name patterns in the query
    for m in _WELL_NAME_RE.finditer(question):
        prefix = m.group(1).lower()
        digits = m.group(2)
        normalised = prefix + digits
        if normalised in name_to_id:
            sid = name_to_id[normalised]
            if sid not in matched_ids:
                matched_ids.append(sid)

    # Match raw 15-digit site IDs
    for m in _RAW_SITE_ID_RE.finditer(question):
        sid = m.group(1)
        if sid in SITE_METADATA and sid not in matched_ids:
            matched_ids.append(sid)

    # Build site dicts with timeseries
    results: list[dict] = []
    for sid in matched_ids:
        base = _base_site_record(sid)
        if base is None:
            continue
        results.append(base)
    return results


# ---------------------------------------------------------------------------
# Network-wide query detection
# ---------------------------------------------------------------------------

_NETWORK_WIDE_KEYWORDS = [
    "all wells",
    "all monitoring",
    "all available",
    "all sites",
    "monitoring network",
    "entire network",
    "across the network",
    "every well",
    "every site",
    "every county",
    "which county",
    "compare counties",
    "comparing counties",
    "county comparison",
    "confined vs unconfined",
    "confined versus unconfined",
    "unconfined vs confined",
    "deeper than",
    "wells deeper",
    "deepest well",
    "shallowest well",
    "all county",
    "all counties",
    "network-wide",
    "statewide",
    "across florida",
    "florida-wide",
    "state of florida",
    "florida network",
    "florida groundwater",
]


def _is_network_wide_query(question: str) -> bool:
    """Return True when the query asks about the full monitoring network."""
    q = question.lower()
    return any(kw in q for kw in _NETWORK_WIDE_KEYWORDS)


def _all_sites_with_data(max_sites: int = 36) -> list[dict]:
    """Load all sites that have available timeseries data.

    Returns the same dict shape as ``_best_sites_near()`` so the result
    can be passed directly to ``_site_research_fallback()``.
    """
    global _ALL_SITES_WITH_DATA_CACHE
    if _ALL_SITES_WITH_DATA_CACHE is None:
        candidates = []
        for site_id in SITE_METADATA:
            base = _base_site_record(site_id)
            if base is None:
                continue
            candidates.append(base)
        candidates.sort(key=lambda s: (s["county"], s["name"]))
        _ALL_SITES_WITH_DATA_CACHE = candidates
    return _ALL_SITES_WITH_DATA_CACHE[:max_sites]


# ---------------------------------------------------------------------------
# Wells payload + aquifer info builders
# ---------------------------------------------------------------------------


def _build_wells_payload(sites: list[dict]) -> list[dict]:
    """Convert _best_sites_near() results to the structured wells wire format."""
    wells = []
    for site in sites:
        site_id = site["site_id"]
        meta = SITE_METADATA.get(site_id, {})

        series = site.get("series")
        zone_range = meta.get("aquifer_zone_depth_range_ft", [0, 100])
        sat_margin: Optional[float] = None
        site_is_artesian = False
        if series is not None and not series.empty:
            last_val = float(series.iloc[-1]["value"])
            site_is_artesian = bool(series["value"].min() < 0)
            if zone_range and len(zone_range) >= 1:
                sat_margin = round(float(zone_range[0]) - last_val, 2)

        wells.append(
            {
                "site_id": site_id,
                "name": site.get("name", site_id),
                "county": site.get("county", "Florida"),
                "lat": site.get("lat"),
                "lng": site.get("lng"),
                "well_depth_ft": meta.get("well_depth_ft", meta.get("depth", 50)),
                "aquifer": site.get("aquifer", "Unknown"),
                "aquifer_type": meta.get("aquifer_type", "unconfined"),
                "confined": meta.get("confined", False),
                "aquifer_zone": meta.get("aquifer_zone", ""),
                "aquifer_zone_depth_range_ft": meta.get("aquifer_zone_depth_range_ft", [0, 100]),
                "aquifer_description": meta.get("aquifer_description", ""),
                "usgs_url": _usgs_site_url(site_id),
                "saturation_margin_ft": sat_margin,
                "is_artesian": site_is_artesian,
            }
        )
    return wells


def _build_aquifer_info(aquifer_name: str) -> dict:
    """Return structured aquifer metadata for a given aquifer display name."""
    matching = [m for m in SITE_METADATA.values() if m.get("aquifer", "") == aquifer_name]
    if not matching:
        return {"name": aquifer_name, "aquifer_type": "unknown", "confined": False, "zones": []}

    first = matching[0]
    depths = [m["well_depth_ft"] for m in matching if m.get("well_depth_ft") is not None]
    counties = sorted({m.get("county", "Florida") for m in matching})

    return {
        "name": aquifer_name,
        "aquifer_type": first.get("aquifer_type", "unconfined"),
        "confined": first.get("confined", False),
        "zones": _AQUIFER_ZONES_REFERENCE.get(aquifer_name, []),
        "monitored_wells": len(matching),
        "well_depth_range_ft": [min(depths), max(depths)] if depths else None,
        "counties": counties,
    }
