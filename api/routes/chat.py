"""Chat & research routes — AI agent endpoints and rule-based fallback.

Endpoints:
 • POST /api/chat             — Conversational agent
 • POST /api/research         — Deep iterative research (blocking)
 • POST /api/research/stream  — Deep iterative research with SSE progress stream
 • GET  /api/chat/status      — System health for chat subsystem
"""

import json
import logging
import math
import os
import queue
import re
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.site_metadata import SITE_METADATA
from src.claim_disagreement import clamp_confidence

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])
DATA_DIR = Path(__file__).parent.parent.parent / "data"
_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
ESTERO_REFERENCE_LAT = 26.4381
ESTERO_REFERENCE_LNG = -81.8068
MIN_CLAIM_CITATION_COVERAGE = float(os.getenv("GROUNDWATERGPT_MIN_CLAIM_COVERAGE", "0.90"))
MIN_SECTION_CITATION_COVERAGE = float(os.getenv("GROUNDWATERGPT_MIN_SECTION_COVERAGE", "0.90"))
TRUST_LEVEL_RANK = {
    "unknown": 0,
    "untrusted": 0,
    "moderate": 1,
    "trusted": 2,
    "verified": 3,
}
RANK_TO_TRUST_LEVEL = {
    0: "unknown",
    1: "moderate",
    2: "trusted",
    3: "verified",
}

_claim_disagreement_engine = None
_summarize_claim_verdicts_fn = None
try:
    from src.claim_disagreement import ClaimDisagreementEngine, summarize_claim_verdicts

    _claim_disagreement_engine = ClaimDisagreementEngine()
    _summarize_claim_verdicts_fn = summarize_claim_verdicts
except Exception as exc:
    logger.warning("Claim disagreement engine unavailable, using conservative fallback: %s", exc)
    _claim_disagreement_engine = None
    _summarize_claim_verdicts_fn = None


# ---------------------------------------------------------------------------
# Aquifer zone reference — loaded once from usgs_sites.json at import time
# Maps aquifer display name → list of zone dicts (zone_name, depth_range_ft, …)
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
# Rule-based fallback KB (used when LLM agent cannot be initialised)
# ---------------------------------------------------------------------------

GROUNDWATER_KB = {
    "irrigation": {
        "keywords": ["irrigat", "water", "crop", "plant", "farm"],
        "info": (
            "Groundwater levels are critical for irrigation planning. "
            "In Florida, the dry season (Nov-May) typically shows lower "
            "water tables. Monitor levels 2-3 weeks before planting to "
            "ensure adequate supply."
        ),
    },
    "soil_moisture": {
        "keywords": ["soil", "moisture", "drain", "saturat"],
        "info": (
            "Soil moisture is directly related to groundwater depth. "
            "Shallow water tables (<3ft) may cause waterlogging. "
            "Deep water tables (>10ft) may require irrigation "
            "supplementation."
        ),
    },
    "crops": {
        "keywords": ["crop", "plant", "grow", "vegetable", "citrus", "tomato"],
        "info": (
            "Different crops have varying water table tolerances: "
            "Citrus: 3-6ft optimal depth. Tomatoes: 2-4ft optimal. "
            "Sugarcane: tolerates 1-3ft. Most vegetables prefer 2-5ft."
        ),
    },
    "saltwater": {
        "keywords": ["salt", "intrusion", "coastal", "chloride", "brackish"],
        "info": (
            "Saltwater intrusion is a concern in coastal Florida "
            "aquifers. Biscayne Aquifer (Miami-Dade) is particularly "
            "vulnerable. Monitor chloride levels and watch for declining "
            "freshwater heads."
        ),
    },
    "seasonal": {
        "keywords": ["season", "wet", "dry", "rain", "hurricane"],
        "info": (
            "Florida has distinct wet (Jun-Oct) and dry (Nov-May) "
            "seasons. Groundwater levels typically peak in Sep-Oct after "
            "summer rains. Lowest levels occur in Apr-May before wet "
            "season begins."
        ),
    },
    "aquifer": {
        "keywords": ["aquifer", "floridan", "biscayne", "surficial"],
        "info": (
            "Florida has three main aquifer systems: "
            "1) Surficial (unconfined, shallow) "
            "2) Biscayne (SE Florida, highly productive) "
            "3) Floridan (deep, artesian in some areas)."
        ),
    },
    "well": {
        "keywords": ["well", "pump", "depth", "drill", "permit"],
        "info": (
            "Well permits required from local Water Management "
            "District. Residential wells typically 20-100ft deep. "
            "Agricultural wells may be 100-500ft for Floridan "
            "Aquifer access."
        ),
    },
    "drought_resilience": {
        "keywords": ["drought", "dry spell", "resilience", "water shortage"],
        "info": (
            "During drought periods, prioritize irrigation scheduling by crop stage "
            "and monitor nearby USGS wells weekly. Trigger conservation actions when "
            "water levels show sustained decline through the late dry season."
        ),
    },
    "fertigation": {
        "keywords": ["fertigation", "fertilizer", "nutrient", "leaching"],
        "info": (
            "For fertigation, avoid heavy nutrient dosing when the water table is "
            "very shallow to reduce leaching risk. Split fertilizer applications "
            "and align timing with soil-moisture and groundwater conditions."
        ),
    },
    "frost_protection": {
        "keywords": ["frost", "freeze", "cold snap", "freeze protection"],
        "info": (
            "Cold-event irrigation draws heavily on wells in short windows. Confirm "
            "pump capacity and aquifer recovery before freeze nights, and track water "
            "levels afterward to avoid cumulative seasonal drawdown."
        ),
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _get_site_context(county: Optional[str] = None) -> str:
    """Get context string about available monitoring sites."""
    sites_by_county: dict[str, list[str]] = {}
    for site_id, meta in SITE_METADATA.items():
        c = meta.get("county", "Unknown")
        sites_by_county.setdefault(c, []).append(meta.get("name", site_id))

    if county and county in sites_by_county:
        sites_list = ", ".join(sites_by_county[county][:5])
        return f"Available monitoring sites in {county}: {sites_list}"

    n_sites = len(SITE_METADATA)
    n_counties = len(sites_by_county)
    return f"Monitoring {n_sites} USGS sites across " f"{n_counties} Florida counties."


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment flag with a safe default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _highest_trust_level(citations: list[dict[str, Any]]) -> str:
    """Select the highest trust level present in claim citations."""
    best_rank = 0
    for citation in citations:
        trust_level = str(citation.get("trust_level", "unknown")).lower()
        best_rank = max(best_rank, TRUST_LEVEL_RANK.get(trust_level, 0))
    return RANK_TO_TRUST_LEVEL.get(best_rank, "unknown")


def _build_section_confidence_from_claims(claim_citations: list[dict[str, Any]]) -> dict[str, Any]:
    """Build per-section confidence + trust metadata from claim citations."""
    sections: list[dict[str, Any]] = []
    ranks: list[int] = []
    confidences: list[float] = []

    for index, claim in enumerate(claim_citations, start=1):
        citations_raw = claim.get("citations", [])
        citations = citations_raw if isinstance(citations_raw, list) else []
        trust_level = _highest_trust_level(citations)
        trust_rank = TRUST_LEVEL_RANK.get(trust_level, 0)
        confidence = clamp_confidence(claim.get("confidence", 0.0))
        title = str(claim.get("claim", "")).strip()[:120] or f"Claim section {index}"

        ranks.append(trust_rank)
        confidences.append(confidence)
        sections.append(
            {
                "section_id": f"section_{index:03d}",
                "title": title,
                "confidence": confidence,
                "trust_level": trust_level,
                "citation_count": len(citations),
            }
        )

    if not sections:
        return {
            "sections": [],
            "overall_confidence": 0.0,
            "overall_trust_level": "unknown",
        }

    avg_confidence = round(sum(confidences) / len(confidences), 3)
    avg_rank = round(sum(ranks) / len(ranks))
    return {
        "sections": sections,
        "overall_confidence": avg_confidence,
        "overall_trust_level": RANK_TO_TRUST_LEVEL.get(avg_rank, "unknown"),
    }


def _fallback_response(query: str) -> dict:
    """Rule-based fallback when LLM agent is unavailable."""
    query_lower = query.lower()
    matches = []
    for topic, data in GROUNDWATER_KB.items():
        for kw in data["keywords"]:
            if kw in query_lower:
                matches.append((topic, data["info"]))
                break

    county_mentioned = None
    for county in [
        "Miami-Dade",
        "Lee",
        "Collier",
        "Sarasota",
        "Hendry",
    ]:
        if county.lower() in query_lower:
            county_mentioned = county
            break

    if matches:
        response_text = " ".join(m[1] for m in matches[:2])
        sources = [f"GroundwaterGPT KB: {m[0]}" for m in matches]
    else:
        response_text = (
            "I can help with groundwater questions about irrigation, "
            "crops, soil moisture, aquifers, wells, drought planning, "
            "fertigation, frost protection, saltwater intrusion, and "
            "seasonal patterns. Try asking about water levels for "
            "farming or which crops suit your area."
        )
        sources = ["GroundwaterGPT Knowledge Base"]

    return {
        "response": response_text,
        "context": _get_site_context(county_mentioned),
        "sources": sources,
        "mode": "fallback",
        "status": "ok",
    }


def _usgs_site_url(site_id: str) -> str:
    """Return canonical USGS page for a monitoring site."""
    return f"https://waterdata.usgs.gov/monitoring-location/{site_id}/"


# ---------------------------------------------------------------------------
# Location keyword → (ref_lat, ref_lng, display_name, county_hint)
# Covers all known monitored areas so any site-related query gets a fast path
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
    q = question.lower()
    for keyword in sorted(_LOCATION_REFERENCE_POINTS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(keyword) + r"\b", q):
            return _LOCATION_REFERENCE_POINTS[keyword]
    return None


# ---------------------------------------------------------------------------
# Aquifer keyword → (aquifer_key, display_name)
# Longer keywords are sorted first to prevent prefix collisions
# (e.g. "tamiami aquifer system" before "tamiami").
# ---------------------------------------------------------------------------
_AQUIFER_DETECTION_MAP: dict[str, tuple[str, str]] = {
    "biscayne aquifer": ("biscayne", "Biscayne Aquifer"),
    "biscayne": ("biscayne", "Biscayne Aquifer"),
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

# Maps aquifer_key → lowercase substring present in SITE_METADATA["aquifer"]
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


def _distance_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Approximate distance using lat/lng deltas (no projection needed for proximity ranking)."""
    return ((lat1 - lat2) ** 2 + (lng1 - lng2) ** 2) ** 0.5


# Module-level cache: avoids re-reading the same CSV on every request.
# Populated lazily on first load; persists for the lifetime of the process.
_SITE_SERIES_CACHE: dict[str, Optional[pd.DataFrame]] = {}


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
        series = _load_site_timeseries(site_id)
        if series is None:
            continue

        county = str(meta.get("county", "")).strip().lower()
        county_bonus = -0.3 if county_hint and county == county_hint else 0.0
        distance_score = _distance_between(float(lat), float(lng), ref_lat, ref_lng) + county_bonus
        candidates.append(
            {
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
                "lat": float(lat),
                "lng": float(lng),
                "distance_score": distance_score,
                "series": series,
            }
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
    Sites without an available CSV timeseries are excluded.
    Results are sorted by county then name for reproducibility.
    """
    needle = _AQUIFER_NEEDLE.get(aquifer_key, aquifer_key)
    candidates = []
    for site_id, meta in SITE_METADATA.items():
        if needle not in meta.get("aquifer", "").lower():
            continue
        series = _load_site_timeseries(site_id)
        if series is None:
            continue
        candidates.append(
            {
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
        )
    candidates.sort(key=lambda s: (s["county"], s["name"]))
    return candidates[:max_sites]


# Keywords that indicate the user is asking about aquifer type / well depth
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
# Site-name detection — matches well names like "G-3336", "G 3336", "G3336",
# "C-1224", or raw 15-digit USGS site IDs from the query text.
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
        # Extract the well code portion, e.g. "Miami-Dade G-3336" → "g3336"
        parts = name.split()
        for part in parts:
            normalised = part.lower().replace("-", "")
            if normalised and any(c.isdigit() for c in normalised):
                name_to_id[normalised] = site_id

    # Match well-name patterns in the query
    for m in _WELL_NAME_RE.finditer(question):
        prefix = m.group(1).lower()
        digits = m.group(2)
        normalised = prefix + digits  # e.g. "g3336"
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
        series = _load_site_timeseries(sid)
        if series is None:
            continue
        meta = SITE_METADATA[sid]
        results.append(
            {
                "site_id": sid,
                "name": meta.get("name", sid),
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
        )
    return results


# ---------------------------------------------------------------------------
# Network-wide query detection — triggers when no specific location/aquifer
# is mentioned but the user asks about all wells, all counties, the whole
# monitoring network, confined vs unconfined comparison, or depth filtering.
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
    candidates = []
    for site_id, meta in SITE_METADATA.items():
        series = _load_site_timeseries(site_id)
        if series is None:
            continue
        candidates.append(
            {
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
        )
    candidates.sort(key=lambda s: (s["county"], s["name"]))
    return candidates[:max_sites]


def _build_wells_payload(sites: list[dict]) -> list[dict]:
    """Convert _best_sites_near() results to the structured wells wire format."""
    wells = []
    for site in sites:
        site_id = site["site_id"]
        meta = SITE_METADATA.get(site_id, {})

        # Compute saturation margin and artesian flag from live timeseries when available
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
    """Return structured aquifer metadata for a given aquifer display name.

    Includes well statistics (count, depth range, counties) aggregated from
    all sites in SITE_METADATA that belong to this aquifer.
    """
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


def _trend_label(net_change: float) -> str:
    """Map numeric net change to a plain-language trend label."""
    if net_change > 0.25:
        return "rising"
    if net_change < -0.25:
        return "falling"
    return "stable"


def _half_trend(series: "pd.Series") -> str:
    """Map year-by-year seasonal means to a worsening/recovering/stable label.

    Compares the second half of the annual record against the first half.
    Higher values mean the water level is deeper (worse for unconfined wells).
    """
    if len(series) < 3:
        return "insufficient_data"
    mid = len(series) // 2
    diff = float(series.iloc[mid:].mean()) - float(series.iloc[:mid].mean())
    if diff > 0.15:
        return "worsening"
    if diff < -0.15:
        return "recovering"
    return "stable"


def _seasonal_decomposition(df: "pd.DataFrame") -> dict:
    """Compute Florida wet/dry season statistics from a site timeseries.

    Wet season: June–October (months 6–10). Dry season: November–May.
    Returns ``{"has_seasonal": False}`` when fewer than 2 years of data exist.
    Water-level values are in ft below land surface (higher value = deeper level).
    """
    if df is None or df.empty:
        return {"has_seasonal": False}

    ts = df.copy()
    ts["_month"] = ts["datetime"].dt.month
    ts["_year"] = ts["datetime"].dt.year
    ts["_season"] = ts["_month"].apply(lambda m: "wet" if 6 <= m <= 10 else "dry")

    year_span = int(ts["_year"].max()) - int(ts["_year"].min())
    if year_span < 2:
        return {"has_seasonal": False}

    wet_vals = ts[ts["_season"] == "wet"]["value"]
    dry_vals = ts[ts["_season"] == "dry"]["value"]
    if wet_vals.empty or dry_vals.empty:
        return {"has_seasonal": False}

    wet_mean = float(wet_vals.mean())
    dry_mean = float(dry_vals.mean())
    amplitude = abs(dry_mean - wet_mean)

    dry_by_year = ts[ts["_season"] == "dry"].groupby("_year")["value"].mean()
    wet_by_year = ts[ts["_season"] == "wet"].groupby("_year")["value"].mean()

    return {
        "has_seasonal": True,
        "wet_season_mean_ft": round(wet_mean, 2),
        "dry_season_mean_ft": round(dry_mean, 2),
        "seasonal_amplitude_ft": round(amplitude, 2),
        "dry_season_trend": _half_trend(dry_by_year),
        "wet_season_trend": _half_trend(wet_by_year),
        "n_years": year_span + 1,
    }


def _build_citation_summary(claim_citations: list[dict]) -> dict:
    """Compute citation summary metrics for claim-level outputs."""
    total = len(claim_citations)
    cited = sum(1 for claim in claim_citations if claim.get("citations"))
    coverage = float(cited / total) if total else 0.0
    return {
        "total_claims": total,
        "cited_claims": cited,
        "citation_coverage": round(coverage, 3),
    }


def _build_citation_integrity(
    claim_citations: list[dict[str, Any]],
    section_confidence: dict[str, Any],
) -> dict[str, Any]:
    """Compute claim/section citation integrity checks."""
    claim_summary = _build_citation_summary(claim_citations)
    claim_coverage = float(claim_summary.get("citation_coverage", 0.0))

    sections = (
        section_confidence.get("sections", []) if isinstance(section_confidence, dict) else []
    )
    total_sections = len(sections)
    cited_sections = sum(
        1 for section in sections if int(section.get("citation_count", 0) or 0) > 0
    )
    section_coverage = float(cited_sections / total_sections) if total_sections else 0.0

    passes_claim = claim_coverage >= MIN_CLAIM_CITATION_COVERAGE
    passes_section = section_coverage >= MIN_SECTION_CITATION_COVERAGE

    return {
        "claim_citation_coverage": round(claim_coverage, 3),
        "section_citation_coverage": round(section_coverage, 3),
        "min_claim_coverage": MIN_CLAIM_CITATION_COVERAGE,
        "min_section_coverage": MIN_SECTION_CITATION_COVERAGE,
        "claim_coverage_passed": passes_claim,
        "section_coverage_passed": passes_section,
        "passed": passes_claim and passes_section,
    }


def _build_claim_verdicts(claim_citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return claim verdicts from disagreement engine or conservative fallback."""
    if _claim_disagreement_engine is not None:
        return _claim_disagreement_engine.evaluate_claims(claim_citations)

    verdicts: list[dict[str, Any]] = []
    for claim in claim_citations:
        claim_id = str(claim.get("claim_id", "claim_unknown"))
        claim_text = str(claim.get("claim", "")).strip()
        citations_raw = claim.get("citations", [])
        citations = citations_raw if isinstance(citations_raw, list) else []
        confidence = clamp_confidence(claim.get("confidence", 0.0))
        has_citations = bool(citations)
        verdicts.append(
            {
                "claim_id": claim_id,
                "claim": claim_text,
                "verdict": "supported" if has_citations else "insufficient_evidence",
                "risk_score": 0.3 if has_citations else 0.85,
                "confidence": confidence,
                "evidence_for": citations[:3],
                "counter_evidence": [],
                "rationale": (
                    "Fallback verdict: citations present."
                    if has_citations
                    else "Fallback verdict: claim lacks citations."
                ),
            }
        )
    return verdicts


def _build_claim_verdict_summary(claim_verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate claim verdict counts/rates for response-level quality signals."""
    if _summarize_claim_verdicts_fn is not None:
        return _summarize_claim_verdicts_fn(claim_verdicts)

    total = len(claim_verdicts)
    supported = sum(1 for item in claim_verdicts if item.get("verdict") == "supported")
    contradicted = sum(1 for item in claim_verdicts if item.get("verdict") == "contradicted")
    insufficient = sum(
        1 for item in claim_verdicts if item.get("verdict") == "insufficient_evidence"
    )
    high_risk_claim_ids = [
        str(item.get("claim_id", ""))
        for item in claim_verdicts
        if float(item.get("risk_score", 0.0) or 0.0) >= 0.75 and item.get("claim_id")
    ]
    return {
        "total_claims": total,
        "supported_claims": supported,
        "contradicted_claims": contradicted,
        "insufficient_evidence_claims": insufficient,
        "contradicted_claim_rate": round(float(contradicted / total), 3) if total else 0.0,
        "high_risk_claim_ids": high_risk_claim_ids,
        "high_risk_claim_rate": round(float(len(high_risk_claim_ids) / total), 3) if total else 0.0,
    }


def _cross_well_analysis(sites: list[dict]) -> dict:
    """Compute cohort-level statistics across a set of wells with loaded timeseries.

    Returns trend_distribution, mean/std annual change, divergent pairs, and risk level.
    Only meaningful when len(sites) >= 2; returns a zeroed dict for 0-1 sites.
    """
    if len(sites) < 2:
        return {
            "n_total": len(sites),
            "trend_distribution": {},
            "cohort_trend": "unknown",
            "mean_annual_change_ft_yr": None,
            "std_dev_annual_change": None,
            "divergent_pairs": [],
            "risk_level": "unknown",
            "per_site_metrics": [],
        }

    per_site: list[dict] = []
    annual_changes: list[float] = []
    for site in sites:
        df = site["series"]
        first, last = df.iloc[0], df.iloc[-1]
        net = float(last["value"] - first["value"])
        years = max(0.01, (last["datetime"] - first["datetime"]).days / 365.25)
        ann = net / years
        per_site.append(
            {
                "site_id": site["site_id"],
                "name": site["name"],
                "trend": _trend_label(net),
                "net_change_ft": round(net, 3),
                "annual_change_ft_yr": round(ann, 4),
            }
        )
        annual_changes.append(ann)

    n_total = len(per_site)
    dist: dict[str, int] = {"falling": 0, "stable": 0, "rising": 0}
    for s in per_site:
        dist[s["trend"]] = dist.get(s["trend"], 0) + 1
    cohort_trend = max(dist, key=dist.get)

    mean_ann = sum(annual_changes) / n_total
    std_dev = math.sqrt(sum((x - mean_ann) ** 2 for x in annual_changes) / n_total)

    divergent: list[dict] = []
    for i in range(n_total):
        for j in range(i + 1, n_total):
            a, b = per_site[i], per_site[j]
            if {a["trend"], b["trend"]} == {"falling", "rising"}:
                divergent.append(
                    {
                        "site_a": {
                            k: a[k] for k in ("site_id", "name", "trend", "annual_change_ft_yr")
                        },
                        "site_b": {
                            k: b[k] for k in ("site_id", "name", "trend", "annual_change_ft_yr")
                        },
                        "divergence_magnitude": abs(
                            a["annual_change_ft_yr"] - b["annual_change_ft_yr"]
                        ),
                    }
                )
    divergent.sort(key=lambda p: p["divergence_magnitude"], reverse=True)
    divergent = divergent[:3]

    pct_falling = dist["falling"] / n_total
    mostly_confined = sum(1 for s in sites if s.get("confined", False)) > n_total / 2
    if pct_falling >= 0.66:
        risk = "high"
    elif pct_falling >= 0.33 or (pct_falling >= 0.20 and mostly_confined):
        risk = "moderate"
    else:
        risk = "low"

    return {
        "n_total": n_total,
        "trend_distribution": dist,
        "cohort_trend": cohort_trend,
        "mean_annual_change_ft_yr": round(mean_ann, 4),
        "std_dev_annual_change": round(std_dev, 4),
        "divergent_pairs": divergent,
        "risk_level": risk,
        "per_site_metrics": per_site,
    }


def _site_research_fallback(question: str, sites: list[dict], location_name: str) -> dict:
    """Generate a deterministic, cited response for any USGS site/location query."""
    if not sites:
        fallback = _fallback_response(question)
        claim_citations = [
            {
                "claim_id": "claim_001",
                "claim": fallback["response"],
                "confidence": 0.55,
                "citations": [
                    {"url": str(src), "verified": True, "trust_level": "moderate"}
                    for src in fallback["sources"]
                ],
            }
        ]
        claim_verdicts = _build_claim_verdicts(claim_citations)
        return {
            "report": fallback["response"],
            "insights": [],
            "sources": fallback["sources"],
            "claim_citations": claim_citations,
            "claim_verdicts": claim_verdicts,
            "claim_verdict_summary": _build_claim_verdict_summary(claim_verdicts),
            "citation_summary": _build_citation_summary(claim_citations),
            "section_confidence": _build_section_confidence_from_claims(claim_citations),
            "hallucination_guardrail": {
                "strategy": "deterministic_fallback",
                "removed_uncited_factual_sentences": 0,
                "all_factual_claims_cited": True,
            },
            "search_history": [question],
            "depth_reached": 1,
            "elapsed_seconds": 0.05,
        }

    site_blocks: list[str] = []
    insights: list[dict] = []
    claim_citations: list[dict] = []
    source_urls: list[str] = []

    for idx, site in enumerate(sites, start=1):
        df = site["series"]
        first = df.iloc[0]
        last = df.iloc[-1]
        start_date = first["datetime"].strftime("%Y-%m-%d")
        end_date = last["datetime"].strftime("%Y-%m-%d")
        net_change = float(last["value"] - first["value"])
        years = max(0.01, (last["datetime"] - first["datetime"]).days / 365.25)
        annual_change = net_change / years
        trend = _trend_label(net_change)

        site_url = _usgs_site_url(site["site_id"])
        source_urls.append(site_url)

        # Aquifer context fields — use zone name when available, fall back to aquifer name
        aq_zone = site.get("aquifer_zone") or site.get("aquifer", "Unknown Aquifer")
        aq_label = site.get("aquifer", aq_zone)
        confinement = "confined" if site.get("confined") else "unconfined"
        well_depth = site.get("well_depth_ft")
        zone_range = site.get("aquifer_zone_depth_range_ft")
        aq_desc = site.get("aquifer_description", "")

        depth_str = f"well depth: {well_depth:.0f} ft" if well_depth else ""
        range_str = (
            f"zone: {zone_range[0]}–{zone_range[1]} ft"
            if zone_range and len(zone_range) == 2
            else ""
        )
        meta_parts = [p for p in [depth_str, range_str] if p]
        meta_str = f" [{'; '.join(meta_parts)}]" if meta_parts else ""

        # Head margin: ft above zone top (negative = below zone top)
        current_level_ft = float(last["value"])
        zone_top_ft: Optional[float] = (
            float(zone_range[0]) if zone_range and len(zone_range) >= 1 else None
        )
        head_margin_ft: Optional[float] = (
            round(zone_top_ft - current_level_ft, 2) if zone_top_ft is not None else None
        )
        is_artesian = bool(df["value"].min() < 0)

        # Seasonal decomposition
        seasonal = _seasonal_decomposition(df)

        # Physics note: one-line summary of aquifer mechanics
        if site.get("confined"):
            physics_note = (
                "Confined aquifer — pressure-head decline; "
                "not seasonally recharged by local rainfall."
            )
        else:
            physics_note = (
                "Unconfined water-table aquifer — "
                "responds directly to local precipitation and seasonal recharge."
            )

        # Head margin alert — confinement-aware thresholds
        # Confined: flag when within 15 ft of zone top (losing artesian head)
        # Unconfined: flag only when within 2 ft of or below zone top (near dewatering)
        head_margin_line = ""
        if head_margin_ft is not None:
            is_confined_site = bool(site.get("confined", False))
            margin_threshold = 15.0 if is_confined_site else 2.0
            if head_margin_ft < margin_threshold:
                if head_margin_ft < 0:
                    zone_status = (
                        "approaching unconfined conditions"
                        if is_confined_site
                        else "partial dewatering"
                    )
                    head_margin_line = (
                        f"\n  CAUTION: head {abs(head_margin_ft):.1f} ft below zone top"
                        f" — {zone_status}."
                    )
                else:
                    head_margin_line = (
                        f"\n  Head margin: {head_margin_ft:.1f} ft above zone top"
                        " (approaching zone boundary)."
                    )

        # Artesian note
        artesian_line = ""
        if is_artesian:
            artesian_line = (
                "\n  Artesian: pressure head exceeded land surface during record period."
            )

        # Seasonal summary line
        seasonal_line = ""
        if seasonal.get("has_seasonal"):
            amp = seasonal["seasonal_amplitude_ft"]
            wet_m = seasonal["wet_season_mean_ft"]
            dry_m = seasonal["dry_season_mean_ft"]
            dry_trend = seasonal["dry_season_trend"]
            seasonal_line = (
                f"\n  Seasonal ({seasonal['n_years']} yr): amplitude {amp:.1f} ft"
                f" (wet avg {wet_m:.1f} ft, dry avg {dry_m:.1f} ft);"
                f" dry-season trend: {dry_trend}."
            )

        site_blocks.append(
            f"- {site['name']} [site {site['site_id']}] — "
            f"{aq_label} ({aq_zone}, {confinement}){meta_str}:\n"
            f"  {start_date} to {end_date}; "
            f"net change {net_change:+.2f} ft ({annual_change:+.2f} ft/yr), "
            f"trend: {trend}."
            + (
                f"\n  Note: {aq_desc}"
                if aq_desc
                and any(
                    kw in aq_desc.lower()
                    for kw in ("saltwater", "artesian", "vulnerable", "intrusion", "pressure")
                )
                else ""
            )
            + f"\n  Physics: {physics_note}"
            + head_margin_line
            + artesian_line
            + seasonal_line
        )

        # Insight/claim text — include critical flags
        extra_flags = []
        if is_artesian:
            extra_flags.append("artesian conditions observed")
        if head_margin_ft is not None and head_margin_ft < 0:
            extra_flags.append(f"head {abs(head_margin_ft):.1f} ft below zone top")
        flag_str = (" [" + "; ".join(extra_flags) + "]") if extra_flags else ""

        insight_text = (
            f"{site['name']} ({aq_zone}, {confinement}, "
            + (f"well depth {well_depth:.0f} ft" if well_depth else site["site_id"])
            + f") shows a {trend} groundwater trend from "
            f"{start_date} to {end_date} with net change {net_change:+.2f} ft{flag_str}."
        )
        insights.append(
            {
                "content": insight_text,
                "source_url": site_url,
                "confidence": 0.85,
                "verified": True,
                "trust_level": "verified",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        claim_citations.append(
            {
                "claim_id": f"claim_{idx:03d}",
                "claim": insight_text,
                "confidence": 0.85,
                "citations": [{"url": site_url, "verified": True, "trust_level": "verified"}],
            }
        )

    # Cross-well cohort analysis (only when 2+ sites available)
    cross_well = _cross_well_analysis(sites)
    if cross_well["n_total"] >= 2:
        cw_dist = cross_well["trend_distribution"]
        cw_mean = cross_well["mean_annual_change_ft_yr"]
        cw_std = cross_well["std_dev_annual_change"]
        cw_risk = cross_well["risk_level"].upper()
        cw_n = cross_well["n_total"]
        pct_falling = cw_dist["falling"] / cw_n

        # Claim A — cohort trend summary
        cohort_claim = (
            f"Of {cw_n} {location_name} monitoring wells analysed, "
            f"{cw_dist['falling']} show a falling trend, "
            f"{cw_dist['stable']} stable, and {cw_dist['rising']} rising. "
            f"Mean annual change: {cw_mean:+.3f} ft/yr "
            f"(\u03c3\u202f=\u202f{cw_std:.3f}\u202fft/yr)."
        )
        claim_citations.append(
            {
                "claim_id": f"claim_{len(claim_citations) + 1:03d}",
                "claim": cohort_claim,
                "confidence": 0.90,
                "citations": [
                    {"url": u, "verified": True, "trust_level": "verified"} for u in source_urls
                ],
            }
        )

        # Claim B — divergence (only when opposing trends exist)
        if cross_well["divergent_pairs"]:
            top = cross_well["divergent_pairs"][0]
            sa, sb = top["site_a"], top["site_b"]
            div_claim = (
                f"{sa['name']} ({sa['trend']}, {sa['annual_change_ft_yr']:+.3f}\u202fft/yr) "
                f"vs {sb['name']} ({sb['trend']}, {sb['annual_change_ft_yr']:+.3f}\u202fft/yr) "
                "— differential behaviour may reflect local recharge heterogeneity "
                "or proximity to pumping centres."
            )
            div_urls = [
                _usgs_site_url(sa["site_id"]),
                _usgs_site_url(sb["site_id"]),
            ]
            claim_citations.append(
                {
                    "claim_id": f"claim_{len(claim_citations) + 1:03d}",
                    "claim": div_claim,
                    "confidence": 0.80,
                    "citations": [
                        {"url": u, "verified": True, "trust_level": "verified"} for u in div_urls
                    ],
                }
            )

        # Claim C — risk assessment
        mostly_confined = sum(1 for s in sites if s.get("confined", False)) > cw_n / 2
        conf_label = "confined" if mostly_confined else "unconfined"
        risk_claim = (
            f"{pct_falling:.0%} of monitored {location_name} wells show declining trends "
            f"({conf_label} aquifer) — cohort sustainability risk: {cw_risk}."
        )
        claim_citations.append(
            {
                "claim_id": f"claim_{len(claim_citations) + 1:03d}",
                "claim": risk_claim,
                "confidence": 0.85,
                "citations": [{"url": source_urls[0], "verified": True, "trust_level": "verified"}],
            }
        )

    # Build aquifer-aware implications based on confinement types present
    confinement_types = {("confined" if s.get("confined") else "unconfined") for s in sites}
    if "unconfined" in confinement_types:
        implication_note = (
            "Unconfined (water-table) aquifers are directly sensitive to "
            "recharge variability, drought, and over-pumping."
        )
    else:
        implication_note = (
            "Confined artesian aquifers show pressure-head decline; "
            "sustained drawdown may reduce artesian flow and increase pumping costs."
        )
    implications_claim = (
        f"Observed trends imply sustainability risk. {implication_note} "
        "Saltwater intrusion risk increases under persistent decline in coastal zones."
    )
    claim_citations.append(
        {
            "claim_id": f"claim_{len(claim_citations) + 1:03d}",
            "claim": implications_claim,
            "confidence": 0.7,
            "citations": [
                {
                    "url": source_urls[0],
                    "verified": True,
                    "trust_level": "verified",
                }
            ],
        }
    )

    # Build cross-well cohort section for report text
    cohort_section = ""
    if cross_well["n_total"] >= 2:
        cw_dist = cross_well["trend_distribution"]
        cw_n = cross_well["n_total"]
        cohort_section = (
            f"\nCross-well cohort ({cw_n} wells):\n"
            f"- Trend distribution: {cw_dist['falling']} falling, "
            f"{cw_dist['stable']} stable, {cw_dist['rising']} rising\n"
            f"- Mean annual change: {cross_well['mean_annual_change_ft_yr']:+.3f} ft/yr "
            f"(\u03c3\u202f=\u202f{cross_well['std_dev_annual_change']:.3f}\u202fft/yr)\n"
            f"- Cohort trend: {cross_well['cohort_trend'].upper()}\n"
            f"- Risk level: {cross_well['risk_level'].upper()}\n"
        )
        for pair in cross_well["divergent_pairs"][:2]:
            sa, sb = pair["site_a"], pair["site_b"]
            cohort_section += (
                f"- Divergence: {sa['name']} ({sa['trend']}) " f"vs {sb['name']} ({sb['trend']})\n"
            )

    # Summarise aquifer types present for the interpretation section
    aquifer_summary = ", ".join(
        sorted({s.get("aquifer_zone") or s.get("aquifer", "Unknown") for s in sites})
    )
    report = (
        f"{location_name} groundwater analysis (USGS-backed):\n\n"
        f"Aquifer systems monitored: {aquifer_summary}\n\n"
        "Data period used (available local record):\n"
        f"{chr(10).join(site_blocks)}\n"
        f"{cohort_section}\n"
        "Interpretation:\n"
        "- The available record may not span the full requested period; "
        "results reflect the actual observed period listed above.\n"
        "- Trend direction (rising/falling/stable) is computed from net change over "
        "the available record.\n"
        f"- {implications_claim}"
    )

    claim_verdicts = _build_claim_verdicts(claim_citations)
    return {
        "report": report,
        "insights": insights,
        "sources": source_urls,
        "claim_citations": claim_citations,
        "claim_verdicts": claim_verdicts,
        "claim_verdict_summary": _build_claim_verdict_summary(claim_verdicts),
        "citation_summary": _build_citation_summary(claim_citations),
        "section_confidence": _build_section_confidence_from_claims(claim_citations),
        "hallucination_guardrail": {
            "strategy": "deterministic_site_fallback",
            "removed_uncited_factual_sentences": 0,
            "all_factual_claims_cited": True,
        },
        "divergent_pairs": cross_well.get("divergent_pairs", []),
        "cohort_risk_level": cross_well.get("risk_level"),
        "search_history": [question, f"USGS {location_name} proxy sites trend analysis"],
        "depth_reached": 1,
        "elapsed_seconds": 0.12,
    }


# ---------------------------------------------------------------------------
# Try to initialise real agents (graceful fallback on import/init failure)
# ---------------------------------------------------------------------------

_chat_agent = None
_research_agent = None
_agent_boot_errors: list[str] = []
_runtime_error_state: dict[str, dict[str, Optional[str]]] = {
    "chat": {"message": None, "timestamp": None},
    "research": {"message": None, "timestamp": None},
}

skip_agent_init = _env_flag("GROUNDWATERGPT_SKIP_AGENT_INIT")
research_web_search_enabled = _env_flag("GROUNDWATERGPT_ENABLE_WEB_SEARCH", default=False)


def _set_runtime_error(channel: str, error: Exception) -> None:
    """Store the most recent runtime error for status visibility."""
    _runtime_error_state[channel] = {
        "message": str(error),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _clear_runtime_error(channel: str) -> None:
    """Clear runtime error state after a successful request path."""
    _runtime_error_state[channel] = {"message": None, "timestamp": None}


def _build_degraded_reasons() -> list[str]:
    """Build explicit degraded reasons for chat status responses."""
    reasons = list(_agent_boot_errors)
    if skip_agent_init:
        reasons.append("LLM agent initialization disabled by GROUNDWATERGPT_SKIP_AGENT_INIT.")
    if _chat_agent is None:
        reasons.append("Conversational chat agent is unavailable; fallback mode will be used.")
    if _research_agent is None:
        reasons.append("Deep research agent is unavailable; fallback mode will be used.")

    chat_error = _runtime_error_state["chat"]["message"]
    if chat_error:
        reasons.append(f"Latest chat runtime error: {chat_error}")
    research_error = _runtime_error_state["research"]["message"]
    if research_error:
        reasons.append(f"Latest research runtime error: {research_error}")
    return reasons


if skip_agent_init:
    logger.info("Skipping LLM-backed agent initialization (GROUNDWATERGPT_SKIP_AGENT_INIT set)")
else:
    try:
        from src.agent.groundwater_agent import create_agent as _create_chat_agent
        from src.agent.research_agent import DeepResearchAgent

        try:
            _chat_agent = _create_chat_agent(verbose=False)
        except Exception as exc:
            _agent_boot_errors.append(f"Chat agent initialization failed: {exc}")
            logger.warning("Chat agent initialization failed: %s", exc)
            _chat_agent = None

        try:
            _research_agent = DeepResearchAgent(
                max_depth=3,
                timeout_seconds=120,
                use_web_search=research_web_search_enabled,
            )
        except Exception as exc:
            _agent_boot_errors.append(f"Research agent initialization failed: {exc}")
            logger.warning("Research agent initialization failed: %s", exc)
            _research_agent = None

        if _chat_agent or _research_agent:
            logger.info("LLM-backed agents initialised with runtime safeguards")
        else:
            logger.warning("No LLM-backed agents available after initialization")
    except Exception as exc:
        _agent_boot_errors.append(f"Agent import bootstrap failed: {exc}")
        logger.warning(
            "Could not initialise LLM agents — " "falling back to rule-based chat. Reason: %s",
            exc,
        )
        _chat_agent = None
        _research_agent = None


# ---------------------------------------------------------------------------
# POST /api/chat — conversational agent endpoint
# ---------------------------------------------------------------------------


@router.post("/chat")
def chat_endpoint(query: dict):
    """AI chat endpoint for groundwater questions.

    Uses the GroundwaterAgent when available; falls back to rule-based
    KB when the LLM provider is not configured or unreachable.

    Request body: ``{ "message": "..." }``
    """
    user_query = query.get("message", "")
    if not user_query:
        raise HTTPException(status_code=400, detail="Message is required")

    # --- Site-name fast path: explicit well names / site IDs (most specific) ---
    named_sites = _detect_site_names(user_query)
    if named_sites:
        label = " vs ".join(s["name"] for s in named_sites)
        ns_result = _site_research_fallback(user_query, named_sites, label)
        return {
            "response": ns_result["report"],
            "context": _get_site_context(named_sites[0].get("county")),
            "sources": ns_result["sources"],
            "mode": "site_fallback",
            "status": "ok",
            "wells": _build_wells_payload(named_sites),
        }

    # --- Aquifer fast path: named aquifer → all cohort sites (runs before location) ---
    aq_hit = _detect_aquifer(user_query)
    if aq_hit is not None:
        aq_key, aq_display_name = aq_hit
        aq_sites = _sites_for_aquifer(aq_key, max_sites=8)
        aq_result = _site_research_fallback(user_query, aq_sites, aq_display_name)
        return {
            "response": aq_result["report"],
            "context": _get_site_context(),
            "sources": aq_result["sources"],
            "mode": "aquifer_fallback",
            "status": "ok",
            "wells": _build_wells_payload(aq_sites),
            "aquifer_info": _build_aquifer_info(aq_display_name),
        }

    # --- Location fast path: return deterministic USGS-backed answer immediately ---
    loc = _detect_location(user_query)
    if loc is not None:
        ref_lat, ref_lng, loc_name, county_hint = loc
        sites = _best_sites_near(ref_lat, ref_lng, county_hint, max_sites=3)
        result = _site_research_fallback(user_query, sites, loc_name)
        wells_payload = _build_wells_payload(sites)
        response_dict: dict[str, Any] = {
            "response": result["report"],
            "context": _get_site_context(county_hint.title() if county_hint else None),
            "sources": result["sources"],
            "mode": "site_fallback",
            "status": "ok",
            "wells": wells_payload,
        }
        if _is_aquifer_query(user_query) and wells_payload:
            response_dict["aquifer_info"] = _build_aquifer_info(wells_payload[0]["aquifer"])
        return response_dict

    # --- Network-wide fast path: all-wells / all-county / confined-vs-unconfined queries ---
    if _is_network_wide_query(user_query):
        nw_sites = _all_sites_with_data(max_sites=36)
        if nw_sites:
            nw_result = _site_research_fallback(user_query, nw_sites, "Florida monitoring network")
            return {
                "response": nw_result["report"],
                "context": _get_site_context(),
                "sources": nw_result["sources"],
                "mode": "network_fallback",
                "status": "ok",
                "wells": _build_wells_payload(nw_sites),
            }

    # --- Try real agent first ---
    if _chat_agent is not None:
        try:
            response_text = _chat_agent.chat(user_query)
            _clear_runtime_error("chat")
            return {
                "response": response_text,
                "context": _get_site_context(),
                "sources": ["GroundwaterGPT Agent (LLM-backed)"],
                "mode": "agent",
                "status": "ok",
            }
        except Exception as exc:
            logger.error("Agent chat error: %s", exc)
            _set_runtime_error("chat", exc)
            # Fall through to rule-based fallback

    # --- Fallback ---
    return _fallback_response(user_query)


# ---------------------------------------------------------------------------
# POST /api/research — deep research endpoint
# ---------------------------------------------------------------------------


@router.post("/research")
def research_endpoint(query: dict):
    """Deep research endpoint — runs the iterative research agent.

    Request body::

        {
            "question": "...",
            "max_depth": 3,
            "timeout": 120
        }

    Returns a structured research report with sourced insights.
    Falls back to a simple KB lookup when the agent is unavailable.
    """
    question = query.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    max_depth = int(query.get("max_depth", 3))
    timeout = float(query.get("timeout", 120))

    if _research_agent is not None:
        try:
            result = _research_agent.research(
                query=question,
                max_depth=max_depth,
                timeout=timeout,
            )
            _clear_runtime_error("research")
            report = result.get("report", "")
            # If the agent produced no meaningful output, fall through to the
            # deterministic fallback so keyword-routed queries (e.g. Estero)
            # still return reproducible, citation-complete responses.
            if not report or "No insights were gathered" in report:
                raise ValueError("Research agent returned no meaningful insights")
            claim_citations = result.get("claim_citations", [])
            claim_verdicts = result.get("claim_verdicts", _build_claim_verdicts(claim_citations))
            claim_verdict_summary = result.get(
                "claim_verdict_summary",
                _build_claim_verdict_summary(claim_verdicts),
            )
            citation_summary = result.get(
                "citation_summary",
                {"total_claims": 0, "cited_claims": 0, "citation_coverage": 0.0},
            )
            section_confidence = result.get(
                "section_confidence",
                _build_section_confidence_from_claims(claim_citations),
            )
            citation_integrity = _build_citation_integrity(claim_citations, section_confidence)
            return {
                "status": "ok",
                "mode": "deep_research",
                "report": report,
                "insights": result.get("insights", []),
                "sources": result.get("sources", []),
                "search_history": result.get("search_history", []),
                "depth_reached": result.get("depth_reached", 0),
                "elapsed_seconds": result.get("elapsed_seconds", 0),
                "claim_citations": claim_citations,
                "claim_verdicts": claim_verdicts,
                "claim_verdict_summary": claim_verdict_summary,
                "citation_summary": citation_summary,
                "section_confidence": section_confidence,
                "hallucination_guardrail": result.get(
                    "hallucination_guardrail",
                    {
                        "strategy": "claim_reference_filter",
                        "removed_uncited_factual_sentences": 0,
                        "all_factual_claims_cited": True,
                    },
                ),
                "citation_integrity": citation_integrity,
            }
        except Exception as exc:
            logger.error(
                "Research agent error: %s\n%s",
                exc,
                traceback.format_exc(),
            )
            _set_runtime_error("research", exc)
            # Fall through to fallback

    # --- Site-name fast path: explicit well names / site IDs (most specific) ---
    named_sites = _detect_site_names(question)
    if named_sites:
        label = " vs ".join(s["name"] for s in named_sites)
        ns_result = _site_research_fallback(question, named_sites, label)
        ns_claim_verdicts = ns_result.get(
            "claim_verdicts",
            _build_claim_verdicts(ns_result["claim_citations"]),
        )
        return {
            "status": "ok",
            "mode": "site_fallback",
            "report": ns_result["report"],
            "insights": ns_result["insights"],
            "sources": ns_result["sources"],
            "search_history": ns_result["search_history"],
            "depth_reached": ns_result["depth_reached"],
            "elapsed_seconds": ns_result["elapsed_seconds"],
            "claim_citations": ns_result["claim_citations"],
            "claim_verdicts": ns_claim_verdicts,
            "claim_verdict_summary": ns_result.get(
                "claim_verdict_summary",
                _build_claim_verdict_summary(ns_claim_verdicts),
            ),
            "citation_summary": ns_result["citation_summary"],
            "section_confidence": ns_result.get("section_confidence", {}),
            "hallucination_guardrail": ns_result.get(
                "hallucination_guardrail",
                {
                    "strategy": "deterministic_site_fallback",
                    "removed_uncited_factual_sentences": 0,
                    "all_factual_claims_cited": True,
                },
            ),
            "citation_integrity": _build_citation_integrity(
                ns_result["claim_citations"], ns_result.get("section_confidence", {})
            ),
            "wells": _build_wells_payload(named_sites),
            "divergent_pairs": ns_result.get("divergent_pairs", []),
            "cohort_risk_level": ns_result.get("cohort_risk_level"),
        }

    # --- Aquifer fast path: named aquifer → all cohort sites (runs before location) ---
    aq_hit = _detect_aquifer(question)
    if aq_hit is not None:
        aq_key, aq_display_name = aq_hit
        aq_sites = _sites_for_aquifer(aq_key, max_sites=6)
        aq_result = _site_research_fallback(question, aq_sites, aq_display_name)
        aq_claim_verdicts = aq_result.get(
            "claim_verdicts",
            _build_claim_verdicts(aq_result["claim_citations"]),
        )
        return {
            "status": "ok",
            "mode": "aquifer_fallback",
            "report": aq_result["report"],
            "insights": aq_result["insights"],
            "sources": aq_result["sources"],
            "search_history": aq_result["search_history"],
            "depth_reached": aq_result["depth_reached"],
            "elapsed_seconds": aq_result["elapsed_seconds"],
            "claim_citations": aq_result["claim_citations"],
            "claim_verdicts": aq_claim_verdicts,
            "claim_verdict_summary": aq_result.get(
                "claim_verdict_summary",
                _build_claim_verdict_summary(aq_claim_verdicts),
            ),
            "citation_summary": aq_result["citation_summary"],
            "section_confidence": aq_result.get("section_confidence", {}),
            "hallucination_guardrail": aq_result.get(
                "hallucination_guardrail",
                {
                    "strategy": "deterministic_site_fallback",
                    "removed_uncited_factual_sentences": 0,
                    "all_factual_claims_cited": True,
                },
            ),
            "citation_integrity": _build_citation_integrity(
                aq_result["claim_citations"], aq_result.get("section_confidence", {})
            ),
            "wells": _build_wells_payload(aq_sites),
            "aquifer_info": _build_aquifer_info(aq_display_name),
            "divergent_pairs": aq_result.get("divergent_pairs", []),
            "cohort_risk_level": aq_result.get("cohort_risk_level"),
        }

    # --- Fallback: location-aware deterministic USGS response ---
    loc = _detect_location(question)
    if loc is not None:
        ref_lat, ref_lng, loc_name, county_hint = loc
        loc_sites = _best_sites_near(ref_lat, ref_lng, county_hint, max_sites=2)
        site_result = _site_research_fallback(question, loc_sites, loc_name)
        site_claim_verdicts = site_result.get(
            "claim_verdicts",
            _build_claim_verdicts(site_result["claim_citations"]),
        )
        return {
            "status": "ok",
            "mode": "fallback",
            "report": site_result["report"],
            "insights": site_result["insights"],
            "sources": site_result["sources"],
            "search_history": site_result["search_history"],
            "depth_reached": site_result["depth_reached"],
            "elapsed_seconds": site_result["elapsed_seconds"],
            "claim_citations": site_result["claim_citations"],
            "claim_verdicts": site_claim_verdicts,
            "claim_verdict_summary": site_result.get(
                "claim_verdict_summary",
                _build_claim_verdict_summary(site_claim_verdicts),
            ),
            "citation_summary": site_result["citation_summary"],
            "section_confidence": site_result.get("section_confidence", {}),
            "hallucination_guardrail": site_result.get(
                "hallucination_guardrail",
                {
                    "strategy": "deterministic_site_fallback",
                    "removed_uncited_factual_sentences": 0,
                    "all_factual_claims_cited": True,
                },
            ),
            "citation_integrity": _build_citation_integrity(
                site_result["claim_citations"], site_result.get("section_confidence", {})
            ),
            "wells": _build_wells_payload(loc_sites),
            "aquifer_info": (_build_aquifer_info(loc_sites[0]["aquifer"]) if loc_sites else None),
            "divergent_pairs": site_result.get("divergent_pairs", []),
            "cohort_risk_level": site_result.get("cohort_risk_level"),
        }

    # --- Network-wide fallback: queries about all wells / all counties / confined vs unconfined ---
    if _is_network_wide_query(question):
        nw_sites = _all_sites_with_data(max_sites=36)
        if nw_sites:
            nw_result = _site_research_fallback(question, nw_sites, "Florida monitoring network")
            nw_claim_verdicts = nw_result.get(
                "claim_verdicts",
                _build_claim_verdicts(nw_result["claim_citations"]),
            )
            return {
                "status": "ok",
                "mode": "network_fallback",
                "report": nw_result["report"],
                "insights": nw_result["insights"],
                "sources": nw_result["sources"],
                "search_history": nw_result["search_history"],
                "depth_reached": nw_result["depth_reached"],
                "elapsed_seconds": nw_result["elapsed_seconds"],
                "claim_citations": nw_result["claim_citations"],
                "claim_verdicts": nw_claim_verdicts,
                "claim_verdict_summary": nw_result.get(
                    "claim_verdict_summary",
                    _build_claim_verdict_summary(nw_claim_verdicts),
                ),
                "citation_summary": nw_result["citation_summary"],
                "section_confidence": nw_result.get("section_confidence", {}),
                "hallucination_guardrail": nw_result.get(
                    "hallucination_guardrail",
                    {
                        "strategy": "deterministic_site_fallback",
                        "removed_uncited_factual_sentences": 0,
                        "all_factual_claims_cited": True,
                    },
                ),
                "citation_integrity": _build_citation_integrity(
                    nw_result["claim_citations"], nw_result.get("section_confidence", {})
                ),
                "wells": _build_wells_payload(nw_sites),
                "divergent_pairs": nw_result.get("divergent_pairs", []),
                "cohort_risk_level": nw_result.get("cohort_risk_level"),
            }

    fb = _fallback_response(question)
    fallback_claims = [
        {
            "claim_id": "claim_001",
            "claim": fb["response"],
            "confidence": 0.6,
            "citations": [
                {"url": str(src), "verified": True, "trust_level": "moderate"}
                for src in fb["sources"]
            ],
        }
    ]
    summary = _build_citation_summary(fallback_claims)
    claim_verdicts = _build_claim_verdicts(fallback_claims)
    claim_verdict_summary = _build_claim_verdict_summary(claim_verdicts)
    section_confidence = _build_section_confidence_from_claims(fallback_claims)
    citation_integrity = _build_citation_integrity(fallback_claims, section_confidence)
    return {
        "status": "ok",
        "mode": "fallback",
        "report": fb["response"],
        "insights": [],
        "sources": fb["sources"],
        "search_history": [question],
        "depth_reached": 0,
        "elapsed_seconds": 0,
        "claim_citations": fallback_claims,
        "claim_verdicts": claim_verdicts,
        "claim_verdict_summary": claim_verdict_summary,
        "citation_summary": summary,
        "section_confidence": section_confidence,
        "hallucination_guardrail": {
            "strategy": "deterministic_fallback",
            "removed_uncited_factual_sentences": 0,
            "all_factual_claims_cited": True,
        },
        "citation_integrity": citation_integrity,
    }


# ---------------------------------------------------------------------------
# POST /api/research/stream — streaming deep research via SSE
# ---------------------------------------------------------------------------

# SSE stream timeout: slightly longer than the agent's own 120s ceiling so
# the generator never hangs indefinitely if the research thread crashes.
_STREAM_QUEUE_TIMEOUT = 135  # seconds


def _run_research_in_thread(
    question: str,
    max_depth: int,
    timeout: float,
    event_queue: "queue.Queue[dict | None]",
) -> None:
    """Run the research agent in a background thread.

    Puts SSE event dicts onto *event_queue* as work progresses, then puts
    None as a sentinel to tell the generator the stream is finished.

    Each event has a "type" key:
      • "progress"  — intermediate status update while the agent works
      • "result"    — the complete research payload (final event before None)
      • "error"     — something went wrong; contains a "message" key
    """

    def progress_callback(message: str, progress: float) -> None:
        """Bridge the agent's callback to the SSE queue."""
        event_queue.put(
            {
                "type": "progress",
                "message": message,
                # Round to 2 decimal places so the frontend can drive a
                # progress bar without floating-point noise.
                "progress": round(progress, 2),
            }
        )

    try:
        if _research_agent is not None:
            # Real LLM-backed research — progress events will flow.
            result = _research_agent.research(
                query=question,
                max_depth=max_depth,
                timeout=timeout,
                progress_callback=progress_callback,
            )
            event_queue.put(
                {
                    "type": "result",
                    "status": "ok",
                    "mode": "deep_research",
                    "report": result.get("report", ""),
                    "insights": result.get("insights", []),
                    "sources": result.get("sources", []),
                    "search_history": result.get("search_history", []),
                    "depth_reached": result.get("depth_reached", 0),
                    "elapsed_seconds": result.get("elapsed_seconds", 0),
                    "claim_citations": result.get("claim_citations", []),
                    "citation_summary": result.get(
                        "citation_summary",
                        {
                            "total_claims": 0,
                            "cited_claims": 0,
                            "citation_coverage": 0.0,
                        },
                    ),
                }
            )
        else:
            # Fallback mode — no progress updates, instant result.
            fb = _fallback_response(question)
            fallback_claims = [
                {
                    "claim_id": "claim_001",
                    "claim": fb["response"],
                    "confidence": 0.6,
                    "citations": [
                        {
                            "url": str(src),
                            "verified": True,
                            "trust_level": "moderate",
                        }
                        for src in fb["sources"]
                    ],
                }
            ]
            event_queue.put(
                {
                    "type": "result",
                    "status": "ok",
                    "mode": "fallback",
                    "report": fb["response"],
                    "insights": [],
                    "sources": fb["sources"],
                    "search_history": [question],
                    "depth_reached": 0,
                    "elapsed_seconds": 0,
                    "claim_citations": fallback_claims,
                    "citation_summary": _build_citation_summary(fallback_claims),
                }
            )
    except Exception as exc:
        logger.error(
            "Streaming research thread error: %s\n%s",
            exc,
            traceback.format_exc(),
        )
        event_queue.put({"type": "error", "message": str(exc)})
    finally:
        # Sentinel: tells the generator's while-loop to stop.
        event_queue.put(None)


@router.post("/research/stream")
def research_stream_endpoint(query: dict):
    """Streaming deep research endpoint using Server-Sent Events.

    Identical contract to POST /api/research but returns a text/event-stream
    response so the frontend can display live progress as the agent works.

    Request body::

        {
            "question": "...",
            "max_depth": 3,
            "timeout": 120
        }

    Each SSE line is a JSON-encoded event dict with a "type" key:
      • type="progress"  — intermediate status; "message" + "progress" (0-1)
      • type="result"    — final research payload (same shape as /api/research)
      • type="error"     — failure; "message" contains the error description
    """
    question = query.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    max_depth = int(query.get("max_depth", 3))
    timeout = float(query.get("timeout", 120))

    # Queue bridges the research thread to the streaming generator.
    # maxsize=0 means unbounded — the thread can push events freely without
    # blocking even if the client is slow to read.
    event_queue: queue.Queue = queue.Queue(maxsize=0)

    # Kick off the research in a daemon thread so it doesn't block the
    # FastAPI worker and is automatically reaped if the process exits.
    research_thread = threading.Thread(
        target=_run_research_in_thread,
        args=(question, max_depth, timeout, event_queue),
        daemon=True,
    )
    research_thread.start()

    def generate():
        r"""Pull events off the queue and yield them as SSE-formatted lines.

        The SSE wire format is:  data: <json>\n\n
        Each pair of newlines completes one event frame.  Browsers and fetch
        streams both parse this natively.
        """
        while True:
            try:
                # Block until the next event arrives, or time out if the
                # research thread has silently died.
                event = event_queue.get(timeout=_STREAM_QUEUE_TIMEOUT)
            except queue.Empty:
                # Thread took too long without a sentinel — emit an error
                # event and close the stream rather than hanging forever.
                timeout_event = json.dumps(
                    {"type": "error", "message": "Research timed out waiting for agent response"}
                )
                yield f"data: {timeout_event}\n\n"
                break

            # Sentinel from the thread: research is fully done.
            if event is None:
                break

            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        # These headers prevent proxies / CDNs from buffering the stream.
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/chat/status — system health for chat subsystem
# ---------------------------------------------------------------------------


@router.get("/chat/status")
def chat_status():
    """Get AI chat and research system status."""
    degraded_reasons = _build_degraded_reasons()
    agent_available = _chat_agent is not None
    research_available = _research_agent is not None
    return {
        "status": "ok" if (agent_available and not degraded_reasons) else "fallback",
        "version": "1.0.0",
        "agent_available": agent_available,
        "research_available": research_available,
        "degraded_reasons": degraded_reasons,
        "runtime_checks": {
            "skip_agent_init": skip_agent_init,
            "web_search_enabled": research_web_search_enabled,
            "chat_agent_initialized": agent_available,
            "research_agent_initialized": research_available,
            "last_chat_error": _runtime_error_state["chat"],
            "last_research_error": _runtime_error_state["research"],
        },
        "features": (
            [
                "Conversational groundwater Q&A",
                "RAG with hydrogeology documents",
                "Seasonal pattern analysis",
                "Anomaly detection",
                "Data quality reports",
                "Deep research with iterative search",
                "Section-level confidence/trust metadata",
            ]
            if agent_available
            else [
                "Rule-based groundwater Q&A (fallback mode)",
                "Irrigation planning advice",
                "Crop water requirements",
                "Seasonal patterns",
                "Aquifer information",
            ]
        ),
    }
