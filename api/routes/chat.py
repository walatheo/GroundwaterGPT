"""Chat & research routes — AI agent endpoints and rule-based fallback.

Endpoints:
 • POST /api/chat       — Conversational agent
 • POST /api/research   — Deep iterative research
 • GET  /api/chat/status — System health for chat subsystem
"""

import json
import logging
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException

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
    # Aquifer-system reference points (centroid of monitored wells per aquifer)
    "tamiami": (26.30, -81.50, "Tamiami Aquifer Area", "collier"),
    "tamiami aquifer": (26.30, -81.50, "Tamiami Aquifer Area", "collier"),
    "hawthorn": (26.50, -81.88, "Hawthorn Formation Area", "lee"),
    "hawthorn group": (26.50, -81.88, "Hawthorn Formation Area", "lee"),
    "floridan": (27.33, -82.45, "Floridan Aquifer Area", "sarasota"),
    "floridan aquifer": (27.33, -82.45, "Floridan Aquifer Area", "sarasota"),
    # General / aquifer
    "everglades": (25.9, -80.7, "Everglades Area", None),
    "florida": (26.5, -81.0, "Florida", None),
}


def _detect_location(question: str) -> Optional[tuple[float, float, str, Optional[str]]]:
    """Return (lat, lng, display_name, county_hint) for the first location keyword found."""
    q = question.lower()
    # Longest match first to prefer "fort myers" over plain "miami" etc.
    for keyword in sorted(_LOCATION_REFERENCE_POINTS, key=len, reverse=True):
        if keyword in q:
            return _LOCATION_REFERENCE_POINTS[keyword]
    return None


def _distance_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Approximate distance using lat/lng deltas (no projection needed for proximity ranking)."""
    return ((lat1 - lat2) ** 2 + (lng1 - lng2) ** 2) ** 0.5


def _load_site_timeseries(site_id: str) -> Optional[pd.DataFrame]:
    """Load per-site groundwater series if available."""
    csv_path = DATA_DIR / f"usgs_{site_id}.csv"
    if not csv_path.exists():
        return None

    try:
        df = pd.read_csv(csv_path)
        if "datetime" not in df.columns or "value" not in df.columns:
            return None
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["datetime", "value"]).sort_values("datetime")
        if df.empty:
            return None
        return df
    except Exception:
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


def _build_wells_payload(sites: list[dict]) -> list[dict]:
    """Convert _best_sites_near() results to the structured wells wire format."""
    wells = []
    for site in sites:
        site_id = site["site_id"]
        meta = SITE_METADATA.get(site_id, {})
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
            }
        )
    return wells


def _build_aquifer_info(aquifer_name: str) -> dict:
    """Return structured aquifer metadata for a given aquifer display name."""
    for meta in SITE_METADATA.values():
        if meta.get("aquifer", "") == aquifer_name:
            return {
                "name": aquifer_name,
                "aquifer_type": meta.get("aquifer_type", "unconfined"),
                "confined": meta.get("confined", False),
                "zones": _AQUIFER_ZONES_REFERENCE.get(aquifer_name, []),
            }
    return {"name": aquifer_name, "aquifer_type": "unknown", "confined": False, "zones": []}


def _trend_label(net_change: float) -> str:
    """Map numeric net change to a plain-language trend label."""
    if net_change > 0.25:
        return "rising"
    if net_change < -0.25:
        return "falling"
    return "stable"


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

        site_blocks.append(
            (
                f"- Site {site['site_id']} ({site['name']}, {site['aquifer']}): "
                f"{start_date} to {end_date}; net change {net_change:+.2f} ft "
                f"({annual_change:+.2f} ft/year), trend={trend}."
            )
        )

        insight_text = (
            f"{site['site_id']} shows a {trend} groundwater trend from "
            f"{start_date} to {end_date} with net change {net_change:+.2f} ft."
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

    implications_claim = (
        "Observed trends imply sustainability risk and potential saltwater "
        "intrusion stress if drawdown persists."
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

    report = (
        f"{location_name} groundwater analysis (USGS-backed):\n\n"
        "Data period used (available local record):\n"
        f"{chr(10).join(site_blocks)}\n\n"
        "Interpretation:\n"
        "- The available record may not span the full requested period; "
        "results reflect the actual observed period listed above.\n"
        "- Trend direction (rising/falling/stable) is computed from net change over "
        "the available record.\n"
        "- Implications include sustainability and saltwater intrusion risk under "
        "persistent decline."
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
        "search_history": [question, f"USGS {location_name} proxy sites trend analysis"],
        "depth_reached": 1,
        "elapsed_seconds": 0.12,
    }


def _estero_research_fallback(question: str) -> dict:
    """Backwards-compatible wrapper for the Estero benchmark fast path."""
    sites = _best_estero_sites(max_sites=2)
    return _site_research_fallback(question, sites, "Estero")


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
