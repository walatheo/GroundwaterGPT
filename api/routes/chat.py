"""Chat & research routes -- AI agent endpoints and rule-based fallback.

Endpoints:
 - POST /api/chat             -- Conversational agent
 - POST /api/interpret        -- Evidence-bound chart/data interpretation
 - POST /api/research         -- Deep iterative research (blocking)
 - POST /api/research/stream  -- Deep iterative research with SSE progress stream
 - GET  /api/chat/status      -- System health for chat subsystem
"""

import copy
import hashlib
import json
import logging
import math
import os
import queue
import re
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.helpers import calculate_stats, load_site_data
from api.routes import _chart_interpreter
from api.routes._agent_chart_hook import attach_chart_from_agent_result
from api.routes._citation import (  # noqa: E402
    MIN_CLAIM_CITATION_COVERAGE,
    MIN_SECTION_CITATION_COVERAGE,
    RANK_TO_TRUST_LEVEL,
    TRUST_LEVEL_RANK,
    _build_citation_integrity,
    _build_citation_summary,
    _build_claim_verdict_summary,
    _build_claim_verdicts,
    _build_section_confidence_from_claims,
    _highest_trust_level,
)
from api.routes._detection import (  # noqa: E402
    _all_sites_with_data,
    _best_sites_near,
    _build_aquifer_info,
    _build_wells_payload,
    _detect_aquifer,
    _detect_location,
    _detect_locations,
    _detect_site_names,
    _is_aquifer_query,
    _is_network_wide_query,
    _sites_for_aquifer,
    _usgs_site_url,
)
from api.routes._provenance import build_research_provenance
from api.routes._site_analysis import (  # noqa: E402
    _cross_well_analysis,
    _half_trend,
    _seasonal_decomposition,
    _site_research_fallback,
    _trend_label,
)
from api.site_metadata import SITE_METADATA

# ---------------------------------------------------------------------------
# Sub-module imports — extracted helpers (Phase 1 refactor)
# ---------------------------------------------------------------------------

__all__ = [
    "GROUNDWATER_KB",
    "MIN_CLAIM_CITATION_COVERAGE",
    "MIN_SECTION_CITATION_COVERAGE",
    "RANK_TO_TRUST_LEVEL",
    "TRUST_LEVEL_RANK",
    "_build_citation_integrity",
    "_build_citation_summary",
    "_build_claim_verdict_summary",
    "_build_claim_verdicts",
    "_build_section_confidence_from_claims",
    "_cross_well_analysis",
    "_detect_aquifer",
    "_detect_location",
    "_detect_site_names",
    "_fallback_response",
    "_get_site_context",
    "_half_trend",
    "_highest_trust_level",
    "_is_aquifer_query",
    "_is_network_wide_query",
    "_seasonal_decomposition",
    "_site_research_fallback",
    "_trend_label",
    "_usgs_site_url",
]


logger = logging.getLogger(__name__)
_MONTHLY_SITE_CACHE: dict[str, pd.DataFrame | None] = {}
_INTERPRETATION_CACHE: dict[tuple[str, str, bool, str], dict[str, Any]] = {}
_INTERPRETATION_CACHE_MAX = 24

router = APIRouter(prefix="/api", tags=["chat"])


# ---------------------------------------------------------------------------
# Rule-based fallback KB (used when LLM agent cannot be initialised)
# ---------------------------------------------------------------------------

GROUNDWATER_KB = {
    "irrigation": {
        "keywords": ["irrigat", "farm", "agricultur", "planting window"],
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
    "groundwater_basics": {
        "keywords": ["groundwater", "water table", "water level", "monitoring", "hydrology"],
        "info": (
            "Groundwater levels in this project are interpreted from Florida USGS "
            "monitoring wells and reported in feet below land surface. Smaller values "
            "usually indicate shallower water tables, while larger values indicate deeper levels."
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
    return f"Monitoring {n_sites} USGS sites across {n_counties} Florida counties."


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment flag with a safe default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _payload_bool(value: Any, *, default: bool) -> bool:
    """Parse a request-body boolean without treating arbitrary strings as true."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


def _trim_turn_history(raw_history: Any) -> list[dict[str, Any]]:
    """Normalize the last four chat turns for chart-bound follow-ups."""
    if not isinstance(raw_history, list):
        return []
    turns: list[dict[str, Any]] = []
    for item in raw_history[-4:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user"))[:20]
        preview = str(item.get("content_preview") or item.get("content") or "")[:500]
        chart_id = item.get("chart_id")
        turns.append(
            {
                "role": role,
                "content_preview": preview,
                "chart_id": str(chart_id)[:120] if chart_id else None,
            }
        )
    return turns


def _context_hash(chart_context: Any, turn_history: list[dict[str, Any]]) -> str:
    """Stable hash for cache keys that depend on chart and turn context."""
    if not chart_context and not turn_history:
        return ""
    raw = json.dumps([chart_context or {}, turn_history], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _is_open_ended_chart_followup(question: str) -> bool:
    """Return true for chart-context questions that need interpretation."""
    return bool(
        re.search(
            r"\b(why|how|explain|interpret|what does|does this|which is|what should"
            r"|which well|which wells|fastest|highlighted|cohort|average|trend line"
            r"|diverge|divergent|proxy|source|supply|compare)\b"
            r"|\b(this chart|the chart|on the chart|using the chart)\b"
            r"|caus\w*|overpump\w*|\bpumping\b|\bclimate change\b|\brun dry\b"
            r"|\bmanagement claim\b",
            question,
            re.I,
        )
    )


def _fallback_response(query: str) -> dict:
    """Rule-based fallback when LLM agent is unavailable."""
    query_lower = query.lower()
    matches = _kb_topic_matches(query)

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

    if "antarctica" in query_lower:
        response_text = (
            "This project is scoped to Florida groundwater monitoring and related "
            "hydrogeology questions. I do not have Antarctica monitoring data in this "
            "workspace, so I should not invent groundwater levels there. If you want, "
            "I can help with Florida wells, aquifers, seasonal patterns, or site-level USGS trends."
        )
        sources = ["EAGLE Florida monitoring scope"]
    elif query_lower.strip() in {"water", "groundwater"}:
        response_text = (
            "Groundwater questions work best when you include a Florida location, aquifer, "
            "well name, or use case. In this project I can explain water-table depth, "
            "seasonal wet-vs-dry behavior, irrigation implications, saltwater-intrusion risk, "
            "and monitored trends from USGS wells across Florida counties."
        )
        sources = ["EAGLE quick-start guidance"]
    elif matches:
        topic_lines = [
            f"- **{topic.replace('_', ' ').title()}**: {info}" for topic, info in matches[:3]
        ]
        response_text = (
            "## Quick Groundwater Answer\n"
            "The question matches Florida groundwater topics that this project can "
            "answer well.\n\n"
            + "\n".join(topic_lines)
            + "\n\n"
            + "Useful next step: ask for a county, aquifer, or monitoring well "
            "if you want a more data-backed answer."
        )
        sources = [f"Florida Aquifer Analysis KB: {m[0]}" for m in matches]
    else:
        response_text = (
            "I can help with Florida groundwater questions about irrigation, "
            "crops, soil moisture, aquifers, wells, drought planning, "
            "fertigation, frost protection, saltwater intrusion, seasonal patterns, "
            "and monitored USGS well trends. Try asking about a county, aquifer system, "
            "or a specific well such as G-3764 or G-3336."
        )
        sources = ["Florida Aquifer Analysis Knowledge Base"]

    return {
        "response": response_text,
        "context": _get_site_context(county_mentioned),
        "sources": sources,
        "mode": "fallback",
        "status": "ok",
    }


def _kb_topic_matches(query: str) -> list[tuple[str, str]]:
    """Return matching KB topics for a user query."""
    query_lower = query.lower()
    matches: list[tuple[str, str]] = []
    for topic, data in GROUNDWATER_KB.items():
        for kw in data["keywords"]:
            if kw in query_lower:
                matches.append((topic, data["info"]))
                break
    return matches


def _is_multi_location_compare_query(question: str) -> bool:
    """Return True for county/location comparison questions."""
    q = question.lower()
    comparison_markers = [
        " compare ",
        " versus ",
        " vs ",
        " between ",
        "which area",
        "more decline",
        "more drawdown",
        "differ",
        "difference",
    ]
    padded = f" {q} "
    return any(marker in padded or marker in q for marker in comparison_markers)


def _sites_for_multiple_locations(
    locations: list[tuple[float, float, str, Optional[str]]],
    max_sites_per_location: int = 5,
) -> tuple[list[dict[str, Any]], str]:
    """Collect a deduplicated site cohort across multiple referenced locations."""
    combined_sites: list[dict[str, Any]] = []
    seen_site_ids: set[str] = set()
    labels: list[str] = []

    for ref_lat, ref_lng, label, county_hint in locations:
        labels.append(label)
        for site in _best_sites_near(
            ref_lat, ref_lng, county_hint, max_sites=max_sites_per_location
        ):
            site_id = site.get("site_id")
            if site_id in seen_site_ids:
                continue
            seen_site_ids.add(site_id)
            combined_sites.append(site)

    return combined_sites, " vs ".join(labels[:3])


# ---------------------------------------------------------------------------
# Try to initialise real agents (graceful fallback on import/init failure)
# ---------------------------------------------------------------------------

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
    if _research_agent is None:
        reasons.append(
            "Evidence-linked synthesis agent is unavailable; "
            "deterministic fallback mode will be used."
        )

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
        from src.agent.research_agent import DeepResearchAgent

        try:
            _research_agent = DeepResearchAgent(
                max_depth=3,
                timeout_seconds=120,
                use_web_search=research_web_search_enabled,
            )
            if getattr(_research_agent, "llm", None) is None:
                _agent_boot_errors.append(
                    "Research agent initialized without an available LLM; "
                    "using deterministic fallback."
                )
                _research_agent = None
        except Exception as exc:
            _agent_boot_errors.append(f"Research agent initialization failed: {exc}")
            logger.warning("Research agent initialization failed: %s", exc)
            _research_agent = None

        if _research_agent:
            logger.info("Evidence-linked synthesis agent initialised with runtime safeguards")
        else:
            logger.warning("No evidence-linked synthesis agent available after initialization")
    except Exception as exc:
        _agent_boot_errors.append(f"Agent import bootstrap failed: {exc}")
        logger.warning(
            "Could not initialise LLM agents -- " "falling back to rule-based chat. Reason: %s",
            exc,
        )
        _research_agent = None


# ---------------------------------------------------------------------------
# POST /api/chat -- conversational agent endpoint
# ---------------------------------------------------------------------------


def _enrich_with_usgs_data(question: str, response: dict) -> dict:
    """Attach relevant USGS well data to any response.

    Runs site-name / aquifer / location detection against the original
    question.  If matching sites are found, the structured ``wells``,
    ``divergent_pairs``, and ``cohort_risk_level`` fields are added so
    the frontend can render data cards alongside the text answer.
    """
    if response.get("wells"):
        return response  # already enriched by a deterministic path

    # Try to find relevant sites from the question text
    sites: list[dict] = []
    named = _detect_site_names(question)
    if named:
        sites = named
    else:
        aq_hit = _detect_aquifer(question)
        if aq_hit is not None:
            sites = _sites_for_aquifer(aq_hit[0], max_sites=6)
        else:
            loc = _detect_location(question)
            if loc is not None:
                ref_lat, ref_lng, _, county_hint = loc
                sites = _best_sites_near(ref_lat, ref_lng, county_hint, max_sites=3)

    if not sites:
        return response

    # Attach structured data
    response["wells"] = _build_wells_payload(sites)

    # Run cross-well analysis for divergence / risk if 2+ sites
    if len(sites) >= 2:
        cross_well = _cross_well_analysis(sites)
        response["divergent_pairs"] = cross_well.get("divergent_pairs", [])
        response["cohort_risk_level"] = cross_well.get("risk_level")

    return response


def _parse_research_limits(query: dict[str, Any]) -> tuple[int, float]:
    """Parse and clamp research limits, rejecting bools and non-finite values."""
    raw_max_depth = query.get("max_depth", 3)
    raw_timeout = query.get("timeout", 120)

    if isinstance(raw_max_depth, bool) or isinstance(raw_timeout, bool):
        raise HTTPException(
            status_code=400,
            detail="max_depth must be an integer, timeout must be a number",
        )

    try:
        max_depth = int(raw_max_depth)
        timeout = float(raw_timeout)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(
            status_code=400,
            detail="max_depth must be an integer, timeout must be a number",
        )

    if not math.isfinite(timeout):
        raise HTTPException(
            status_code=400,
            detail="max_depth must be an integer, timeout must be a number",
        )

    return max(1, min(max_depth, 10)), max(10.0, min(timeout, 300.0))


def _heuristic_research_plan(question: str, max_depth: int) -> dict[str, Any]:
    """Create a lightweight fallback research plan."""
    query_lower = question.lower()
    recommended_tools = ["knowledge_base_search"]
    if research_web_search_enabled:
        recommended_tools.append("web_search")
    if any(term in query_lower for term in ["trend", "compare", "change", "long-term"]):
        recommended_tools.append("trend_analysis")
    if any(term in query_lower for term in ["season", "wet", "dry"]):
        recommended_tools.append("seasonal_analysis")
    if any(term in query_lower for term in ["anomal", "outlier", "extreme"]):
        recommended_tools.append("anomaly_scan")
    if any(term in query_lower for term in ["aquifer", "well", "site", "county"]):
        recommended_tools.append("cohort_summary")
    return {
        "original_query": question,
        "main_question": question,
        "sub_questions": [
            f"What is the direct answer to: {question}?",
            "Which sites, aquifers, or counties are most relevant?",
            "What evidence best supports the answer?",
        ],
        "research_areas": ["groundwater conditions", "site evidence", "trend analysis"],
        "expected_sections": ["Direct Answer", "Evidence", "Caveats"],
        "search_priority": [question, f"{question} groundwater trends", f"{question} USGS"],
        "estimated_depth": max_depth,
        "recommended_tools": list(dict.fromkeys(recommended_tools)),
        "expected_outputs": [
            "report",
            "claim citations",
            "budget trace",
            "chart specs",
        ],
        "effort_level": "deep" if max_depth >= 4 else "moderate" if max_depth >= 2 else "quick",
    }


def _build_budget_status(
    *,
    max_depth: int,
    depth_reached: int,
    elapsed_seconds: float,
    status: str,
    insights_count: int,
    timed_out: bool = False,
    partial_completion_available: bool = False,
) -> dict[str, Any]:
    """Build a stable research budget payload."""
    return {
        "max_depth": max_depth,
        "depth_reached": depth_reached,
        "elapsed_seconds": round(float(elapsed_seconds), 2),
        "remaining_seconds": 0.0,
        "insights_gathered": insights_count,
        "web_searches_used": 0,
        "web_searches_max": max(3, max_depth * 2 + 2),
        "kb_searches_used": 0,
        "kb_searches_max": max(6, max_depth * 4),
        "api_calls_used": 0,
        "api_calls_max": max(10, max_depth * 6),
        "total_cost": 0.0,
        "remaining_budget": 10.0,
        "status": status,
        "continuing": False,
        "timed_out": timed_out,
        "partial_completion_available": partial_completion_available,
    }


def _infer_research_sites(question: str, max_sites: int = 6) -> tuple[list[dict], dict | None]:
    """Infer the most relevant sites for research charts."""
    named_sites = _detect_site_names(question)
    if named_sites:
        return named_sites[:max_sites], None

    aq_hit = _detect_aquifer(question)
    if aq_hit is not None:
        aq_key, aq_name = aq_hit
        aq_sites = _sites_for_aquifer(aq_key, max_sites=max_sites)
        return aq_sites, _build_aquifer_info(aq_name)

    loc = _detect_location(question)
    if loc is not None:
        ref_lat, ref_lng, _, county_hint = loc
        loc_sites = _best_sites_near(ref_lat, ref_lng, county_hint, max_sites=max_sites)
        aquifer_info = _build_aquifer_info(loc_sites[0]["aquifer"]) if loc_sites else None
        return loc_sites, aquifer_info

    if _is_network_wide_query(question):
        return _all_sites_with_data(max_sites=max_sites), None

    return [], None


def _site_monthly_dataframe(site_id: str) -> pd.DataFrame | None:
    """Load a site's data and normalize it to monthly averages."""
    if site_id in _MONTHLY_SITE_CACHE:
        cached = _MONTHLY_SITE_CACHE[site_id]
        return None if cached is None else cached.copy()

    try:
        df = load_site_data(site_id)
    except HTTPException:
        _MONTHLY_SITE_CACHE[site_id] = None
        return None
    if df.empty:
        _MONTHLY_SITE_CACHE[site_id] = None
        return None
    monthly = df.copy()
    monthly["month_start"] = monthly["datetime"].dt.to_period("M").dt.to_timestamp()
    monthly = monthly.groupby("month_start", as_index=False)["value"].mean()
    monthly = monthly.rename(columns={"month_start": "datetime", "value": "level"})
    monthly = monthly.tail(60)
    _MONTHLY_SITE_CACHE[site_id] = monthly
    return monthly.copy()


def _build_research_visual_bundle(question: str) -> dict[str, Any]:
    """Build deterministic VChart-ready research visuals from site data."""
    sites, aquifer_info = _infer_research_sites(question, max_sites=6)
    if not sites:
        return {"recommended_views": ["report", "citations", "tool_trace"], "chart_specs": []}
    site_ids = [site["site_id"] for site in sites if site.get("site_id")]

    trend_rows: list[dict[str, Any]] = []
    seasonal_rows: list[dict[str, Any]] = []
    anomaly_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []

    for site in sites:
        site_id = site["site_id"]
        monthly = _site_monthly_dataframe(site_id)
        if monthly is None or monthly.empty:
            continue

        meta = SITE_METADATA.get(site_id, {})
        site_name = meta.get("name", site.get("name", site_id))

        monthly["rolling_mean"] = monthly["level"].rolling(window=6, min_periods=3).mean()
        monthly["delta_from_rolling"] = (monthly["level"] - monthly["rolling_mean"]).round(2)
        monthly["month_label"] = monthly["datetime"].dt.strftime("%Y-%m")
        monthly["month_name"] = monthly["datetime"].dt.strftime("%b")

        for row in monthly.tail(36).itertuples():
            trend_rows.append(
                {
                    "date": row.month_label,
                    "level": round(float(row.level), 2),
                    "site": site_name,
                }
            )
            if pd.notna(row.delta_from_rolling):
                anomaly_rows.append(
                    {
                        "date_index": row.datetime.to_pydatetime().timestamp(),
                        "delta": round(float(row.delta_from_rolling), 2),
                        "magnitude": round(abs(float(row.delta_from_rolling)), 2),
                        "site": site_name,
                        "label": row.month_label,
                    }
                )

        seasonal = (
            monthly.groupby("month_name", as_index=False)["level"]
            .mean()
            .rename(columns={"level": "average_level"})
        )
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
        seasonal["month_name"] = pd.Categorical(seasonal["month_name"], month_order, ordered=True)
        seasonal = seasonal.sort_values("month_name")
        for row in seasonal.itertuples():
            seasonal_rows.append(
                {
                    "month": str(row.month_name),
                    "average_level": round(float(row.average_level), 2),
                    "site": site_name,
                }
            )

        stats = calculate_stats(monthly.rename(columns={"datetime": "datetime", "level": "value"}))
        summary_rows.append(
            {
                "site": site_name,
                "annual_change": stats.get("annualChange", 0.0),
                "mean_level": stats.get("mean", 0.0),
                "record_count": stats.get("count", 0),
            }
        )

    chart_specs: list[dict[str, Any]] = []

    if trend_rows:
        chart_specs.append(
            {
                "id": "trend-comparison",
                "kind": "trend_comparison",
                "title": "Trend Comparison",
                "description": (
                    "Monthly groundwater level comparison across the inferred " "research sites."
                ),
                "site_ids": site_ids,
                "spec": {
                    "type": "line",
                    "data": [{"id": "trendData", "values": trend_rows}],
                    "xField": "date",
                    "yField": "level",
                    "seriesField": "site",
                    "legends": {"visible": True, "orient": "top"},
                    "axes": [
                        {"orient": "bottom", "type": "band", "label": {"visible": True}},
                        {"orient": "left", "type": "linear", "nice": True},
                    ],
                },
            }
        )

    if anomaly_rows:
        chart_specs.append(
            {
                "id": "anomaly-scatter",
                "kind": "anomaly_scatter",
                "title": "Rolling Anomaly Scan",
                "description": "Deviation from the 6-month rolling mean for each research site.",
                "site_ids": site_ids,
                "spec": {
                    "type": "scatter",
                    "data": [{"id": "anomalyData", "values": anomaly_rows}],
                    "xField": "date_index",
                    "yField": "delta",
                    "seriesField": "site",
                    "sizeField": "magnitude",
                    "axes": [
                        {"orient": "bottom", "type": "linear"},
                        {"orient": "left", "type": "linear", "nice": True},
                    ],
                },
            }
        )

    if seasonal_rows:
        chart_specs.append(
            {
                "id": "seasonal-profile",
                "kind": "seasonal_profile",
                "title": "Seasonal Profile",
                "description": "Average monthly groundwater level by site.",
                "site_ids": site_ids,
                "spec": {
                    "type": "bar",
                    "data": [{"id": "seasonalData", "values": seasonal_rows}],
                    "xField": "month",
                    "yField": "average_level",
                    "seriesField": "site",
                    "legends": {"visible": True, "orient": "top"},
                    "axes": [
                        {"orient": "bottom", "type": "band"},
                        {"orient": "left", "type": "linear", "nice": True},
                    ],
                },
            }
        )

    if summary_rows:
        chart_specs.append(
            {
                "id": "cohort-summary",
                "kind": "cohort_summary",
                "title": "Cohort Summary",
                "description": "Annualized change and mean level across the selected wells.",
                "site_ids": site_ids,
                "spec": {
                    "type": "bar",
                    "data": [{"id": "summaryData", "values": summary_rows}],
                    "xField": "site",
                    "yField": "annual_change",
                    "seriesField": "site",
                    "axes": [
                        {"orient": "bottom", "type": "band", "label": {"visible": True}},
                        {"orient": "left", "type": "linear", "nice": True},
                    ],
                },
                "metrics": summary_rows,
            }
        )

    recommended_views = ["report", "citations", "tool_trace"]
    recommended_views.extend(spec["id"] for spec in chart_specs)
    if aquifer_info:
        recommended_views.append("aquifer-context")

    return {
        "recommended_views": recommended_views,
        "chart_specs": chart_specs,
        "aquifer_info": aquifer_info,
    }


def _build_structured_evidence_items(
    claim_citations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a compact evidence registry from claim-level citations."""
    evidence_items: list[dict[str, Any]] = []
    for claim in claim_citations:
        claim_id = str(claim.get("claim_id", "claim_unknown"))
        for idx, citation in enumerate(claim.get("citations", []), start=1):
            source = citation.get("url") or citation.get("source") or "unknown"
            evidence_items.append(
                {
                    "evidence_id": str(
                        citation.get("evidence_id") or f"evidence_{claim_id[-3:]}_source_{idx}"
                    ),
                    "claim_id": claim_id,
                    "url": source,
                    "trust_level": citation.get("trust_level", "unknown"),
                    "verified": bool(citation.get("verified", False)),
                }
            )
    return evidence_items


def _clean_structured_text(value: Any, *, max_len: int = 400) -> str:
    """Trim and cap free-text values emitted in structured responses."""
    text = str(value or "").strip()
    return text[:max_len].strip()


def _dedupe_string_list(
    values: Any,
    *,
    valid_values: Optional[set[str]] = None,
    max_items: int = 8,
) -> list[str]:
    """Normalize, validate, and deduplicate a list of string identifiers."""
    if not isinstance(values, list):
        return []

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        if valid_values is not None and text not in valid_values:
            continue
        deduped.append(text)
        seen.add(text)
        if len(deduped) >= max_items:
            break
    return deduped


def _safe_confidence(value: Any, *, default: float = 0.5) -> float:
    """Coerce confidence-like values to a bounded float."""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


def _build_structured_response_from_claims(
    question: str,
    claim_citations: list[dict[str, Any]],
    claim_verdicts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derive a manuscript-friendly structured response from cited claims."""
    evidence_items = _build_structured_evidence_items(claim_citations)
    evidence_by_claim: dict[str, list[str]] = {}
    for item in evidence_items:
        evidence_by_claim.setdefault(str(item["claim_id"]), []).append(str(item["evidence_id"]))

    verdict_by_claim = {
        str(verdict.get("claim_id", "")): str(verdict.get("verdict", "insufficient_evidence"))
        for verdict in claim_verdicts
    }

    structured_claims: list[dict[str, Any]] = []
    omitted_uncited_claims = 0
    for claim in claim_citations[:8]:
        claim_id = str(claim.get("claim_id", "claim_unknown"))
        claim_text = _clean_structured_text(claim.get("claim", ""), max_len=500)
        evidence_ids = _dedupe_string_list(
            evidence_by_claim.get(claim_id, []),
            max_items=8,
        )
        if not evidence_ids:
            omitted_uncited_claims += 1
            continue
        if not claim_text:
            omitted_uncited_claims += 1
            continue

        verdict = verdict_by_claim.get(claim_id, "insufficient_evidence")
        uncertainty = ""
        if verdict == "contradicted":
            uncertainty = "This claim is contradicted by other sources."
        elif verdict == "insufficient_evidence":
            uncertainty = "Evidence is limited for this claim."

        structured_claims.append(
            {
                "claim": claim_text,
                "claim_type": _clean_structured_text(
                    claim.get("claim_type", "retrieved_insight"),
                    max_len=64,
                )
                or "retrieved_insight",
                "claim_ids": [claim_id],
                "evidence_ids": evidence_ids,
                "confidence": _safe_confidence(claim.get("confidence", 0.5)),
                "is_interpretive": str(claim.get("claim_type", "")).lower() == "interpretation",
                "uncertainty": uncertainty,
            }
        )

    answer = " ".join(
        claim["claim"] for claim in structured_claims[:2] if str(claim.get("claim", "")).strip()
    ).strip()
    if not answer:
        answer = "The available cited evidence was insufficient for a structured answer."

    limitations = [
        (
            "This response is constrained to cited claims backed by local "
            "groundwater data and verified sources where available."
        ),
    ]
    if omitted_uncited_claims:
        limitations.append(
            f"{omitted_uncited_claims} uncited claim(s) were excluded from the structured response."
        )

    return {
        "schema_version": "evidence_response_v1",
        "question": question,
        "answer": answer,
        "claims": structured_claims,
        "limitations": _dedupe_string_list(limitations, max_items=6),
        "recommended_followup": [
            (
                "Review the cited evidence registry and deterministic cohort "
                "metrics before drafting manuscript conclusions."
            ),
        ],
        "evidence": [
            item
            for item in evidence_items
            if _clean_structured_text(item.get("claim_id"), max_len=32)
            and _clean_structured_text(item.get("evidence_id"), max_len=64)
            and _clean_structured_text(item.get("url"), max_len=500)
        ],
    }


def _augment_research_payload(
    payload: dict[str, Any],
    *,
    question: str,
    max_depth: int,
    default_mode: str,
    trace_summary: str,
) -> dict[str, Any]:
    """Ensure every research response exposes the new typed session contract."""
    if not payload.get("session_id"):
        payload["session_id"] = f"{default_mode}_{abs(hash((question, default_mode))) % 10**10}"
    if not payload.get("research_plan"):
        payload["research_plan"] = _heuristic_research_plan(question, max_depth)
    if not payload.get("budget_status"):
        payload["budget_status"] = _build_budget_status(
            max_depth=max_depth,
            depth_reached=payload.get("depth_reached", 0),
            elapsed_seconds=payload.get("elapsed_seconds", 0),
            status=payload.get("mode", default_mode),
            insights_count=len(payload.get("insights", [])),
            timed_out=bool(payload.get("timed_out", False)),
            partial_completion_available=bool(payload.get("insights")),
        )
    if not payload.get("checkpoints"):
        payload["checkpoints"] = [
            {
                "checkpoint_id": "cp_001",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": "response_ready",
                "summary": trace_summary,
                "depth": payload.get("depth_reached", 0),
                "phase": default_mode,
                "status": "complete",
                "insights_gathered": len(payload.get("insights", [])),
                "budget_status": payload.get("budget_status"),
                "details": {},
            }
        ]
    if not payload.get("tool_trace"):
        payload["tool_trace"] = [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "phase": default_mode,
                "depth": payload.get("depth_reached", 0),
                "tool": "research_router",
                "status": "completed",
                "details": {"summary": trace_summary},
            }
        ]

    visual_bundle = _build_research_visual_bundle(question)
    if not payload.get("recommended_views"):
        payload["recommended_views"] = visual_bundle["recommended_views"]
    if not payload.get("chart_specs"):
        payload["chart_specs"] = visual_bundle["chart_specs"]
    if payload.get("aquifer_info") is None and visual_bundle.get("aquifer_info") is not None:
        payload["aquifer_info"] = visual_bundle["aquifer_info"]
    if not payload.get("structured_response"):
        claim_citations = payload.get("claim_citations", [])
        claim_verdicts = payload.get("claim_verdicts") or _build_claim_verdicts(claim_citations)
        payload["structured_response"] = _build_structured_response_from_claims(
            question,
            claim_citations,
            claim_verdicts,
        )
    payload.setdefault("changepoints", [])
    payload.setdefault("cross_well_clusters", [])
    payload["provenance"] = build_research_provenance(
        payload,
        question=question,
        route_mode=payload.get("mode", default_mode),
    )

    return payload


def _build_chat_payload(
    *,
    response_text: str,
    context: str,
    sources: list[Any],
    mode: str,
    answer_brief: Optional[str] = None,
    raw_report: Optional[str] = None,
    interpretation_details: Optional[dict[str, Any]] = None,
    chart: Any = None,
    wells: Optional[list[dict[str, Any]]] = None,
    aquifer_info: Optional[dict[str, Any]] = None,
    divergent_pairs: Optional[list[dict[str, Any]]] = None,
    cohort_risk_level: Optional[str] = None,
    llm_synthesis: Optional[str] = None,
    hallucination_guardrail: Optional[dict[str, Any]] = None,
    claim_citations: Optional[list[dict[str, Any]]] = None,
    claim_verdicts: Optional[list[dict[str, Any]]] = None,
    claim_verdict_summary: Optional[dict[str, Any]] = None,
    citation_summary: Optional[dict[str, Any]] = None,
    section_confidence: Optional[dict[str, Any]] = None,
    citation_integrity: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Normalize chat responses so quick-chat exposes the same grounding signals."""
    claim_citations = claim_citations or []
    claim_verdicts = claim_verdicts or _build_claim_verdicts(claim_citations)
    claim_verdict_summary = claim_verdict_summary or _build_claim_verdict_summary(claim_verdicts)
    section_confidence = section_confidence or _build_section_confidence_from_claims(
        claim_citations
    )
    citation_summary = citation_summary or _build_citation_summary(claim_citations)
    citation_integrity = citation_integrity or _build_citation_integrity(
        claim_citations,
        section_confidence,
    )
    hallucination_guardrail = hallucination_guardrail or {
        "strategy": "deterministic_chat_grounding",
        "removed_uncited_factual_sentences": 0,
        "all_factual_claims_cited": True,
        "has_llm_synthesis": bool(llm_synthesis),
    }

    return {
        "response": response_text,
        "answer_brief": answer_brief,
        "raw_report": raw_report,
        "interpretation_details": interpretation_details,
        "context": context,
        "sources": sources,
        "chart": chart,
        "mode": mode,
        "status": "ok",
        "wells": wells or [],
        "aquifer_info": aquifer_info,
        "divergent_pairs": divergent_pairs or [],
        "cohort_risk_level": cohort_risk_level,
        "llm_synthesis": llm_synthesis,
        "hallucination_guardrail": hallucination_guardrail,
        "claim_citations": claim_citations,
        "claim_verdicts": claim_verdicts,
        "claim_verdict_summary": claim_verdict_summary,
        "citation_summary": citation_summary,
        "section_confidence": section_confidence,
        "citation_integrity": citation_integrity,
    }


def _augment_chat_payload(payload: dict[str, Any], *, question: str) -> dict[str, Any]:
    """Attach manuscript-safe structured response and provenance to chat outputs."""
    claim_citations = payload.get("claim_citations", [])
    claim_verdicts = payload.get("claim_verdicts") or _build_claim_verdicts(claim_citations)
    payload["claim_verdicts"] = claim_verdicts
    payload["claim_verdict_summary"] = payload.get(
        "claim_verdict_summary"
    ) or _build_claim_verdict_summary(claim_verdicts)
    payload["citation_summary"] = payload.get("citation_summary") or _build_citation_summary(
        claim_citations
    )
    payload["section_confidence"] = payload.get(
        "section_confidence"
    ) or _build_section_confidence_from_claims(claim_citations)
    payload["citation_integrity"] = payload.get("citation_integrity") or _build_citation_integrity(
        claim_citations,
        payload["section_confidence"],
    )
    payload["structured_response"] = payload.get(
        "structured_response"
    ) or _build_structured_response_from_claims(
        question,
        claim_citations,
        claim_verdicts,
    )
    payload["provenance"] = build_research_provenance(
        payload,
        question=question,
        route_mode=payload.get("mode", "chat"),
    )
    return payload


def _build_interpretation_response(
    payload: dict[str, Any],
    *,
    question: str,
    audience: str = "general",
) -> dict[str, Any]:
    """Build an evidence-bound interpretation object from a grounded chat payload."""
    chart = payload.get("chart") or {}
    explainability = chart.get("explainability") or {}
    wells = payload.get("wells") or []
    claim_citations = payload.get("claim_citations") or []
    sources = payload.get("sources") or []

    key_observations: list[str] = []
    for item in chart.get("insights") or []:
        if isinstance(item, str) and item.strip():
            key_observations.append(item.strip())
    for claim in claim_citations[:4]:
        claim_text = str(claim.get("claim", "")).strip()
        if claim_text and claim_text not in key_observations:
            key_observations.append(claim_text)

    concepts: list[str] = []
    concept_terms = [
        ("monthly mean", "monthly mean"),
        ("cohort average", "cohort average"),
        ("trend", "trend line"),
        ("confined", "confined aquifer"),
        ("unconfined", "unconfined aquifer"),
        ("depth-to-water", "depth to water"),
        ("saltwater", "saltwater intrusion risk"),
    ]
    text_blob = " ".join(
        [
            str(payload.get("response", "")),
            str(explainability.get("summary", "")),
            " ".join(str(item) for item in explainability.get("how_to_read", []) or []),
        ]
    ).lower()
    for needle, label in concept_terms:
        if needle in text_blob and label not in concepts:
            concepts.append(label)

    evidence = []
    for claim in claim_citations[:8]:
        for citation in claim.get("citations", []) or []:
            url = str(citation.get("url") or citation.get("source") or "").strip()
            if url:
                evidence.append(
                    {
                        "claim_id": claim.get("claim_id"),
                        "url": url,
                        "trust_level": citation.get("trust_level", "unknown"),
                        "verified": bool(citation.get("verified", False)),
                    }
                )
    if not evidence:
        evidence = [
            {
                "claim_id": None,
                "url": str(source),
                "trust_level": "unknown",
                "verified": False,
            }
            for source in sources[:5]
        ]

    interpretation_details = payload.get("interpretation_details") or {}
    explanation = (
        payload.get("answer_brief")
        or payload.get("llm_synthesis")
        or explainability.get("summary")
        or ""
    )
    if not explanation:
        explanation = str(payload.get("response", "")).split("\n\n", 1)[0]
    if re.search(r"\b(prove|caus|overpump|pumping|why)\b", question, re.I):
        causation_note = (
            "The chart shows observed monitoring-record patterns; it does not "
            "prove a single cause such as overpumping without pumping, rainfall, "
            "recharge, and groundwater-flow model context."
        )
        if causation_note not in explanation:
            explanation = f"{explanation} {causation_note}".strip()
        if causation_note not in key_observations:
            key_observations.insert(0, causation_note)

    follow_up_questions = list(
        explainability.get("suggested_questions") or explainability.get("follow_up_questions") or []
    )
    if not follow_up_questions:
        follow_up_questions = [
            "Which highlighted well is changing fastest, and why might that matter?",
            "Do nearby wells in different aquifers move together or diverge?",
            "What outside data would help test a possible cause, such as pumping or rainfall?",
        ]

    return {
        "schema_version": "interpretation_response_v1",
        "question": question,
        "audience": audience,
        "interpretation": explanation,
        "chart_context": {
            "title": chart.get("title"),
            "summary": explainability.get("summary"),
            "how_to_read": explainability.get("how_to_read", []),
            "data_contract": explainability.get("data_contract", []),
            "llm_role": explainability.get("llm_role"),
        },
        "key_observations": key_observations[:6],
        "groundwater_concepts": concepts[:6],
        "interpretation_details": interpretation_details,
        "supply_interpretation": interpretation_details.get("supply_interpretation"),
        "data_references": [
            {
                "site_id": well.get("site_id") or well.get("id"),
                "well_name": well.get("name"),
                "aquifer": well.get("aquifer"),
                "county": well.get("county"),
                "source": "USGS NWIS",
                "url": _usgs_site_url(str(well.get("site_id") or well.get("id"))),
            }
            for well in wells[:8]
            if well.get("site_id") or well.get("id")
        ],
        "evidence": evidence[:10],
        "follow_up_questions": follow_up_questions[:4],
        "limits": [
            (
                "This is an interpretation of observed monitoring records, "
                "not a groundwater-flow model."
            ),
            "Trend lines are screening summaries over available records, not forecasts.",
            "The LLM may explain deterministic outputs but must not invent measurements.",
        ],
        "grounding_status": {
            "uses_chart_context": bool(explainability),
            "uses_usgs_data": bool(wells or sources or claim_citations),
            "invented_measurements_allowed": False,
            "has_llm_synthesis": bool(payload.get("llm_synthesis")),
            "citation_integrity_passed": bool(
                (payload.get("citation_integrity") or {}).get("passed", False)
            ),
        },
    }


def _chart_from(result: Optional[dict], *, path: str) -> Optional[dict]:
    """Single source of truth for extracting chart payloads from result dicts."""
    chart = None if not result else result.get("chart")
    logger.debug("chart_decision path=%s emitted=%s", path, chart is not None)
    return chart


def _ground_fallback_chat_response(fallback: dict[str, Any]) -> dict[str, Any]:
    """Wrap the lightweight KB fallback in the richer chat response shape."""
    fallback_claims = [
        {
            "claim_id": "claim_001",
            "claim": fallback["response"],
            "confidence": 0.65,
            "citations": [
                {
                    "url": str(src),
                    "verified": True,
                    "trust_level": "moderate",
                }
                for src in fallback.get("sources", [])
            ],
        }
    ]
    return _build_chat_payload(
        response_text=fallback["response"],
        context=fallback.get("context", _get_site_context()),
        sources=fallback.get("sources", []),
        chart=None,
        mode=fallback.get("mode", "fallback"),
        claim_citations=fallback_claims,
        citation_summary=_build_citation_summary(fallback_claims),
        hallucination_guardrail={
            "strategy": "deterministic_kb_fallback",
            "removed_uncited_factual_sentences": 0,
            "all_factual_claims_cited": True,
            "has_llm_synthesis": False,
        },
    )


@router.post("/chat")
def chat_endpoint(query: dict):
    """AI chat endpoint for groundwater questions.

    Uses deterministic routing first, then the evidence-bound research
    agent for open-ended narration, and finally a rule-based KB fallback.

    Request body: ``{ "message": "..." }``
    """
    raw_message = query.get("message", "")
    user_query = raw_message.strip() if isinstance(raw_message, str) else ""
    if not user_query:
        raise HTTPException(status_code=400, detail="Message is required")
    allow_llm_synthesis = _payload_bool(
        query.get("allow_llm_synthesis"),
        default=True,
    )
    chart_context = query.get("chart_context")
    if not isinstance(chart_context, dict):
        chart_context = None
    turn_history = _trim_turn_history(query.get("turn_history"))

    def _finalize(response_payload: dict[str, Any]) -> dict[str, Any]:
        enriched = _enrich_with_usgs_data(user_query, response_payload)
        return _augment_chat_payload(enriched, question=user_query)

    # --- Site-name fast path: explicit well names / site IDs (most specific) ---
    named_sites = _detect_site_names(user_query)
    if named_sites:
        label = " vs ".join(s["name"] for s in named_sites)
        ns_result = _site_research_fallback(
            user_query,
            named_sites,
            label,
            allow_llm_synthesis=allow_llm_synthesis,
        )
        return _finalize(
            _build_chat_payload(
                response_text=ns_result["report"],
                answer_brief=ns_result.get("answer_brief"),
                raw_report=ns_result.get("report"),
                interpretation_details=ns_result.get("interpretation_details"),
                context=_get_site_context(named_sites[0].get("county")),
                sources=ns_result["sources"],
                chart=_chart_from(ns_result, path="chat.site_fallback"),
                mode="site_fallback",
                wells=_build_wells_payload(named_sites),
                divergent_pairs=ns_result.get("divergent_pairs", []),
                cohort_risk_level=ns_result.get("cohort_risk_level"),
                llm_synthesis=ns_result.get("llm_synthesis"),
                hallucination_guardrail=ns_result.get("hallucination_guardrail"),
                claim_citations=ns_result.get("claim_citations", []),
                claim_verdicts=ns_result.get("claim_verdicts"),
                claim_verdict_summary=ns_result.get("claim_verdict_summary"),
                citation_summary=ns_result.get("citation_summary"),
                section_confidence=ns_result.get("section_confidence", {}),
                citation_integrity=_build_citation_integrity(
                    ns_result["claim_citations"],
                    ns_result.get("section_confidence", {}),
                ),
            )
        )

    # --- Aquifer fast path: named aquifer -> all cohort sites (runs before location) ---
    aq_hit = _detect_aquifer(user_query)
    if aq_hit is not None:
        aq_key, aq_display_name = aq_hit
        aq_sites = _sites_for_aquifer(aq_key, max_sites=8)
        aq_result = _site_research_fallback(
            user_query,
            aq_sites,
            aq_display_name,
            allow_llm_synthesis=allow_llm_synthesis,
        )
        return _finalize(
            _build_chat_payload(
                response_text=aq_result["report"],
                answer_brief=aq_result.get("answer_brief"),
                raw_report=aq_result.get("report"),
                interpretation_details=aq_result.get("interpretation_details"),
                context=_get_site_context(),
                sources=aq_result["sources"],
                chart=_chart_from(aq_result, path="chat.aquifer_fallback"),
                mode="aquifer_fallback",
                wells=_build_wells_payload(aq_sites),
                aquifer_info=_build_aquifer_info(aq_display_name),
                divergent_pairs=aq_result.get("divergent_pairs", []),
                cohort_risk_level=aq_result.get("cohort_risk_level"),
                llm_synthesis=aq_result.get("llm_synthesis"),
                hallucination_guardrail=aq_result.get("hallucination_guardrail"),
                claim_citations=aq_result.get("claim_citations", []),
                claim_verdicts=aq_result.get("claim_verdicts"),
                claim_verdict_summary=aq_result.get("claim_verdict_summary"),
                citation_summary=aq_result.get("citation_summary"),
                section_confidence=aq_result.get("section_confidence", {}),
                citation_integrity=_build_citation_integrity(
                    aq_result["claim_citations"],
                    aq_result.get("section_confidence", {}),
                ),
            )
        )

    # --- Multi-location comparison fast path: compare counties/areas in one answer ---
    locations = _detect_locations(user_query, max_matches=4)
    if len(locations) >= 2 and _is_multi_location_compare_query(user_query):
        multi_sites, multi_label = _sites_for_multiple_locations(
            locations, max_sites_per_location=4
        )
        if multi_sites:
            multi_result = _site_research_fallback(
                user_query,
                multi_sites,
                multi_label,
                allow_llm_synthesis=allow_llm_synthesis,
            )
            return _finalize(
                _build_chat_payload(
                    response_text=multi_result["report"],
                    answer_brief=multi_result.get("answer_brief"),
                    raw_report=multi_result.get("report"),
                    interpretation_details=multi_result.get("interpretation_details"),
                    context=_get_site_context(),
                    sources=multi_result["sources"],
                    chart=_chart_from(multi_result, path="chat.multi_location_fallback"),
                    mode="network_fallback",
                    wells=_build_wells_payload(multi_sites),
                    divergent_pairs=multi_result.get("divergent_pairs", []),
                    cohort_risk_level=multi_result.get("cohort_risk_level"),
                    llm_synthesis=multi_result.get("llm_synthesis"),
                    hallucination_guardrail=multi_result.get("hallucination_guardrail"),
                    claim_citations=multi_result.get("claim_citations", []),
                    claim_verdicts=multi_result.get("claim_verdicts"),
                    claim_verdict_summary=multi_result.get("claim_verdict_summary"),
                    citation_summary=multi_result.get("citation_summary"),
                    section_confidence=multi_result.get("section_confidence", {}),
                    citation_integrity=_build_citation_integrity(
                        multi_result["claim_citations"],
                        multi_result.get("section_confidence", {}),
                    ),
                )
            )

    # --- Location fast path: return deterministic USGS-backed answer immediately ---
    loc = _detect_location(user_query)
    if loc is not None:
        ref_lat, ref_lng, loc_name, county_hint = loc
        sites = _best_sites_near(ref_lat, ref_lng, county_hint, max_sites=10)
        result = _site_research_fallback(
            user_query,
            sites,
            loc_name,
            ref_lat=ref_lat,
            ref_lng=ref_lng,
            allow_llm_synthesis=allow_llm_synthesis,
        )
        wells_payload = _build_wells_payload(sites)
        response_dict = _build_chat_payload(
            response_text=result["report"],
            answer_brief=result.get("answer_brief"),
            raw_report=result.get("report"),
            interpretation_details=result.get("interpretation_details"),
            context=_get_site_context(county_hint.title() if county_hint else None),
            sources=result["sources"],
            chart=_chart_from(result, path="chat.location_fallback"),
            mode="site_fallback",
            wells=wells_payload,
            divergent_pairs=result.get("divergent_pairs", []),
            cohort_risk_level=result.get("cohort_risk_level"),
            llm_synthesis=result.get("llm_synthesis"),
            hallucination_guardrail=result.get("hallucination_guardrail"),
            claim_citations=result.get("claim_citations", []),
            claim_verdicts=result.get("claim_verdicts"),
            claim_verdict_summary=result.get("claim_verdict_summary"),
            citation_summary=result.get("citation_summary"),
            section_confidence=result.get("section_confidence", {}),
            citation_integrity=_build_citation_integrity(
                result["claim_citations"],
                result.get("section_confidence", {}),
            ),
        )
        if _is_aquifer_query(user_query) and wells_payload:
            response_dict["aquifer_info"] = _build_aquifer_info(wells_payload[0]["aquifer"])
        return _finalize(response_dict)

    # --- Network-wide fast path: all-wells / all-county / confined-vs-unconfined queries ---
    if _is_network_wide_query(user_query):
        nw_sites = _all_sites_with_data(max_sites=36)
        if nw_sites:
            nw_result = _site_research_fallback(
                user_query,
                nw_sites,
                "Florida monitoring network",
                allow_llm_synthesis=allow_llm_synthesis,
            )
            return _finalize(
                _build_chat_payload(
                    response_text=nw_result["report"],
                    answer_brief=nw_result.get("answer_brief"),
                    raw_report=nw_result.get("report"),
                    interpretation_details=nw_result.get("interpretation_details"),
                    context=_get_site_context(),
                    sources=nw_result["sources"],
                    chart=_chart_from(nw_result, path="chat.network_fallback"),
                    mode="network_fallback",
                    wells=_build_wells_payload(nw_sites),
                    divergent_pairs=nw_result.get("divergent_pairs", []),
                    cohort_risk_level=nw_result.get("cohort_risk_level"),
                    llm_synthesis=nw_result.get("llm_synthesis"),
                    hallucination_guardrail=nw_result.get("hallucination_guardrail"),
                    claim_citations=nw_result.get("claim_citations", []),
                    claim_verdicts=nw_result.get("claim_verdicts"),
                    claim_verdict_summary=nw_result.get("claim_verdict_summary"),
                    citation_summary=nw_result.get("citation_summary"),
                    section_confidence=nw_result.get("section_confidence", {}),
                    citation_integrity=_build_citation_integrity(
                        nw_result["claim_citations"],
                        nw_result.get("section_confidence", {}),
                    ),
                )
            )

    # --- Chart-context interpretation: open-ended follow-up about the prior chart ---
    if chart_context is not None and _is_open_ended_chart_followup(user_query):
        interpreted = _chart_interpreter.interpret_with_context(
            user_query,
            chart_context,
            turn_history,
            allow_llm_synthesis=allow_llm_synthesis,
        )
        return _finalize(interpreted)

    # --- Groundwater KB fast path: keep lightweight chat queries deterministic ---
    if _kb_topic_matches(user_query):
        return _finalize(_ground_fallback_chat_response(_fallback_response(user_query)))

    # --- Evidence-bound synthesis path for generic open-ended questions ---
    if _research_agent is not None:
        try:
            result = _research_agent.research(
                query=user_query,
                max_depth=1,
                timeout=45,
            )
            result = attach_chart_from_agent_result(result)
            response_text = str(result.get("report", "")).strip()
            if not response_text or "No insights were gathered" in response_text:
                raise ValueError("Research agent returned no meaningful insights")

            claim_citations = result.get("claim_citations", [])
            claim_verdicts = result.get("claim_verdicts", _build_claim_verdicts(claim_citations))
            section_confidence = result.get(
                "section_confidence",
                _build_section_confidence_from_claims(claim_citations),
            )
            _clear_runtime_error("chat")
            return _finalize(
                _build_chat_payload(
                    response_text=response_text,
                    answer_brief=result.get("answer_brief"),
                    raw_report=result.get("report"),
                    interpretation_details=result.get("interpretation_details"),
                    context=_get_site_context(),
                    sources=result.get("sources", []),
                    chart=_chart_from(result, path="chat.evidence_bound_research"),
                    mode="research_chat",
                    wells=result.get("wells", []),
                    aquifer_info=result.get("aquifer_info"),
                    divergent_pairs=result.get("divergent_pairs", []),
                    cohort_risk_level=result.get("cohort_risk_level"),
                    llm_synthesis=result.get("llm_synthesis"),
                    hallucination_guardrail=result.get(
                        "hallucination_guardrail",
                        {
                            "strategy": "evidence_bound_research_chat",
                            "removed_uncited_factual_sentences": 0,
                            "all_factual_claims_cited": True,
                            "has_llm_synthesis": bool(getattr(_research_agent, "llm", None)),
                        },
                    ),
                    claim_citations=claim_citations,
                    claim_verdicts=claim_verdicts,
                    claim_verdict_summary=result.get(
                        "claim_verdict_summary",
                        _build_claim_verdict_summary(claim_verdicts),
                    ),
                    citation_summary=result.get(
                        "citation_summary",
                        _build_citation_summary(claim_citations),
                    ),
                    section_confidence=section_confidence,
                    citation_integrity=result.get(
                        "citation_integrity",
                        _build_citation_integrity(claim_citations, section_confidence),
                    ),
                ),
            )
        except Exception as exc:
            logger.error("Evidence-bound chat synthesis error: %s", exc)
            _set_runtime_error("chat", exc)
            # Fall through to rule-based fallback

    # --- Fallback ---
    return _finalize(_ground_fallback_chat_response(_fallback_response(user_query)))


# ---------------------------------------------------------------------------
# POST /api/interpret -- evidence-bound chart/data interpretation endpoint
# ---------------------------------------------------------------------------


@router.post("/interpret")
def interpret_endpoint(query: dict):
    """Interpret groundwater chart/data context without making the LLM the source."""
    raw_question = query.get("question", query.get("message", ""))
    question = raw_question.strip() if isinstance(raw_question, str) else ""
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    audience_raw = query.get("audience", "general")
    audience = audience_raw.strip() if isinstance(audience_raw, str) else "general"
    use_llm = _payload_bool(
        query.get("use_llm"),
        default=not _payload_bool(query.get("fast"), default=False),
    )
    chart_context = query.get("chart_context")
    if not isinstance(chart_context, dict):
        chart_context = None
    turn_history = _trim_turn_history(query.get("turn_history"))
    cache_key = (
        " ".join(question.lower().split()),
        audience.lower(),
        use_llm,
        _context_hash(chart_context, turn_history),
    )
    cached = _INTERPRETATION_CACHE.get(cache_key)
    if cached is not None:
        cached_payload = copy.deepcopy(cached)
        grounding = cached_payload.get("interpretation_response", {}).setdefault(
            "grounding_status", {}
        )
        grounding["cache_hit"] = True
        return cached_payload

    needs_interpret_prompt = not re.search(
        r"\b(explain|interpret|read|meaning|means|what should|what does)\b",
        question,
        re.I,
    )
    routed_question = (
        f"Interpret this groundwater chart and data: {question}"
        if needs_interpret_prompt
        else question
    )
    payload = chat_endpoint(
        {
            "message": routed_question,
            "allow_llm_synthesis": use_llm,
            "chart_context": chart_context,
            "turn_history": turn_history,
        }
    )
    if not payload.get("interpretation_response"):
        payload["interpretation_response"] = _build_interpretation_response(
            payload,
            question=question,
            audience=audience or "general",
        )
    else:
        payload["interpretation_response"]["question"] = question
        payload["interpretation_response"]["audience"] = audience or "general"
    payload["interpretation_response"]["grounding_status"]["llm_requested"] = use_llm
    payload["interpretation_response"]["grounding_status"]["cache_hit"] = False
    payload["mode"] = f"interpret_{payload.get('mode', 'chat')}"
    payload["provenance"] = build_research_provenance(
        payload,
        question=question,
        route_mode=payload["mode"],
    )
    if len(_INTERPRETATION_CACHE) >= _INTERPRETATION_CACHE_MAX:
        _INTERPRETATION_CACHE.pop(next(iter(_INTERPRETATION_CACHE)))
    _INTERPRETATION_CACHE[cache_key] = copy.deepcopy(payload)
    return payload


# ---------------------------------------------------------------------------
# POST /api/research -- deep research endpoint
# ---------------------------------------------------------------------------


@router.post("/research")
def research_endpoint(query: dict):
    """Deep research endpoint -- runs the iterative research agent.

    Request body::

        {
            "question": "...",
            "max_depth": 3,
            "timeout": 120
        }

    Returns a structured research report with sourced insights.
    Falls back to a simple KB lookup when the agent is unavailable.
    """
    raw_question = query.get("question", "")
    question = raw_question.strip() if isinstance(raw_question, str) else ""
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    max_depth, timeout = _parse_research_limits(query)

    if _research_agent is not None:
        try:
            result = _research_agent.research(
                query=question,
                max_depth=max_depth,
                timeout=timeout,
            )
            result = attach_chart_from_agent_result(result)
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
            return _augment_research_payload(
                {
                    "status": "ok",
                    "mode": "deep_research",
                    "report": report,
                    "chart": _chart_from(result, path="research.agent"),
                    "insights": result.get("insights", []),
                    "sources": result.get("sources", []),
                    "session_id": result.get("session_id"),
                    "research_plan": result.get("research_plan"),
                    "budget_status": result.get("budget_status"),
                    "checkpoints": result.get("checkpoints"),
                    "tool_trace": result.get("tool_trace"),
                    "recommended_views": result.get("recommended_views"),
                    "chart_specs": result.get("chart_specs"),
                    "structured_response": result.get("structured_response"),
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
                },
                question=question,
                max_depth=max_depth,
                default_mode="deep_research",
                trace_summary="LLM-backed research completed.",
            )
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
        return _augment_research_payload(
            {
                "status": "ok",
                "mode": "site_fallback",
                "report": ns_result["report"],
                "chart": _chart_from(ns_result, path="research.site_fallback"),
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
                "changepoints": ns_result.get("changepoints", []),
                "cross_well_clusters": ns_result.get("cross_well_clusters", []),
                "cohort_risk_level": ns_result.get("cohort_risk_level"),
                "llm_synthesis": ns_result.get("llm_synthesis"),
            },
            question=question,
            max_depth=max_depth,
            default_mode="site_fallback",
            trace_summary="Deterministic site research fallback completed.",
        )

    # --- Aquifer fast path: named aquifer -> all cohort sites (runs before location) ---
    aq_hit = _detect_aquifer(question)
    if aq_hit is not None:
        aq_key, aq_display_name = aq_hit
        aq_sites = _sites_for_aquifer(aq_key, max_sites=6)
        aq_result = _site_research_fallback(question, aq_sites, aq_display_name)
        aq_claim_verdicts = aq_result.get(
            "claim_verdicts",
            _build_claim_verdicts(aq_result["claim_citations"]),
        )
        return _augment_research_payload(
            {
                "status": "ok",
                "mode": "aquifer_fallback",
                "report": aq_result["report"],
                "chart": _chart_from(aq_result, path="research.aquifer_fallback"),
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
                "changepoints": aq_result.get("changepoints", []),
                "cross_well_clusters": aq_result.get("cross_well_clusters", []),
                "cohort_risk_level": aq_result.get("cohort_risk_level"),
                "llm_synthesis": aq_result.get("llm_synthesis"),
            },
            question=question,
            max_depth=max_depth,
            default_mode="aquifer_fallback",
            trace_summary="Deterministic aquifer research fallback completed.",
        )

    # --- Fallback: location-aware deterministic USGS response ---
    locations = _detect_locations(question, max_matches=4)
    if len(locations) >= 2 and _is_multi_location_compare_query(question):
        multi_sites, multi_label = _sites_for_multiple_locations(
            locations, max_sites_per_location=4
        )
        if multi_sites:
            multi_result = _site_research_fallback(question, multi_sites, multi_label)
            multi_claim_verdicts = multi_result.get(
                "claim_verdicts",
                _build_claim_verdicts(multi_result["claim_citations"]),
            )
            return _augment_research_payload(
                {
                    "status": "ok",
                    "mode": "network_fallback",
                    "report": multi_result["report"],
                    "chart": _chart_from(multi_result, path="research.multi_location_fallback"),
                    "insights": multi_result["insights"],
                    "sources": multi_result["sources"],
                    "search_history": multi_result["search_history"],
                    "depth_reached": multi_result["depth_reached"],
                    "elapsed_seconds": multi_result["elapsed_seconds"],
                    "claim_citations": multi_result["claim_citations"],
                    "claim_verdicts": multi_claim_verdicts,
                    "claim_verdict_summary": multi_result.get(
                        "claim_verdict_summary",
                        _build_claim_verdict_summary(multi_claim_verdicts),
                    ),
                    "citation_summary": multi_result["citation_summary"],
                    "section_confidence": multi_result.get("section_confidence", {}),
                    "hallucination_guardrail": multi_result.get(
                        "hallucination_guardrail",
                        {
                            "strategy": "deterministic_site_fallback",
                            "removed_uncited_factual_sentences": 0,
                            "all_factual_claims_cited": True,
                        },
                    ),
                    "citation_integrity": _build_citation_integrity(
                        multi_result["claim_citations"],
                        multi_result.get("section_confidence", {}),
                    ),
                    "wells": _build_wells_payload(multi_sites),
                    "divergent_pairs": multi_result.get("divergent_pairs", []),
                    "changepoints": multi_result.get("changepoints", []),
                    "cross_well_clusters": multi_result.get("cross_well_clusters", []),
                    "cohort_risk_level": multi_result.get("cohort_risk_level"),
                    "llm_synthesis": multi_result.get("llm_synthesis"),
                },
                question=question,
                max_depth=max_depth,
                default_mode="network_fallback",
                trace_summary="Multi-location deterministic comparison completed.",
            )

    loc = _detect_location(question)
    if loc is not None:
        ref_lat, ref_lng, loc_name, county_hint = loc
        loc_sites = _best_sites_near(ref_lat, ref_lng, county_hint, max_sites=10)
        site_result = _site_research_fallback(
            question, loc_sites, loc_name, ref_lat=ref_lat, ref_lng=ref_lng
        )
        site_claim_verdicts = site_result.get(
            "claim_verdicts",
            _build_claim_verdicts(site_result["claim_citations"]),
        )
        return _augment_research_payload(
            {
                "status": "ok",
                "mode": "fallback",
                "report": site_result["report"],
                "chart": _chart_from(site_result, path="research.location_fallback"),
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
                "aquifer_info": (
                    _build_aquifer_info(loc_sites[0]["aquifer"]) if loc_sites else None
                ),
                "divergent_pairs": site_result.get("divergent_pairs", []),
                "changepoints": site_result.get("changepoints", []),
                "cross_well_clusters": site_result.get("cross_well_clusters", []),
                "cohort_risk_level": site_result.get("cohort_risk_level"),
                "llm_synthesis": site_result.get("llm_synthesis"),
            },
            question=question,
            max_depth=max_depth,
            default_mode="fallback",
            trace_summary="Location-aware deterministic fallback completed.",
        )

    # --- Network-wide fallback: queries about all wells / all counties / confined vs unconfined ---
    if _is_network_wide_query(question):
        nw_sites = _all_sites_with_data(max_sites=36)
        if nw_sites:
            nw_result = _site_research_fallback(question, nw_sites, "Florida monitoring network")
            nw_claim_verdicts = nw_result.get(
                "claim_verdicts",
                _build_claim_verdicts(nw_result["claim_citations"]),
            )
            return _augment_research_payload(
                {
                    "status": "ok",
                    "mode": "network_fallback",
                    "report": nw_result["report"],
                    "chart": _chart_from(nw_result, path="research.network_fallback"),
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
                    "changepoints": nw_result.get("changepoints", []),
                    "cross_well_clusters": nw_result.get("cross_well_clusters", []),
                    "cohort_risk_level": nw_result.get("cohort_risk_level"),
                    "llm_synthesis": nw_result.get("llm_synthesis"),
                },
                question=question,
                max_depth=max_depth,
                default_mode="network_fallback",
                trace_summary="Network-wide deterministic fallback completed.",
            )

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
    return _augment_research_payload(
        {
            "status": "ok",
            "mode": "fallback",
            "report": fb["response"],
            "chart": None,
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
        },
        question=question,
        max_depth=max_depth,
        default_mode="fallback",
        trace_summary="Generic deterministic fallback completed.",
    )


# ---------------------------------------------------------------------------
# POST /api/research/stream -- streaming deep research via SSE
# ---------------------------------------------------------------------------

# SSE stream timeout: slightly longer than the agent's own 120s ceiling so
# the generator never hangs indefinitely if the research thread crashes.
_STREAM_QUEUE_TIMEOUT = 135  # seconds


def _stream_fallback_result(question: str, max_depth: int = 3) -> dict:
    """Build a streaming-compatible result using the same routing as /api/research.

    Detection order: site-name -> aquifer -> location -> network-wide -> generic KB.
    Returns a dict ready to push onto the SSE event queue.
    """

    def _wrap(site_result: dict, mode: str, sites: list) -> dict:
        verdicts = site_result.get(
            "claim_verdicts",
            _build_claim_verdicts(site_result["claim_citations"]),
        )
        return {
            "type": "result",
            "status": "ok",
            "mode": mode,
            "report": site_result["report"],
            "chart": _chart_from(site_result, path=f"research.stream.{mode}"),
            "insights": site_result["insights"],
            "sources": site_result["sources"],
            "search_history": site_result["search_history"],
            "depth_reached": site_result["depth_reached"],
            "elapsed_seconds": site_result["elapsed_seconds"],
            "claim_citations": site_result["claim_citations"],
            "claim_verdicts": verdicts,
            "claim_verdict_summary": site_result.get(
                "claim_verdict_summary",
                _build_claim_verdict_summary(verdicts),
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
            "llm_synthesis": site_result.get("llm_synthesis"),
            "wells": _build_wells_payload(sites),
            "divergent_pairs": site_result.get("divergent_pairs", []),
            "changepoints": site_result.get("changepoints", []),
            "cross_well_clusters": site_result.get("cross_well_clusters", []),
            "cohort_risk_level": site_result.get("cohort_risk_level"),
        }

    # 1. Site-name detection
    named = _detect_site_names(question)
    if named:
        label = " vs ".join(s["name"] for s in named)
        return _augment_research_payload(
            _wrap(
                _site_research_fallback(question, named, label),
                "site_fallback",
                named,
            ),
            question=question,
            max_depth=max_depth,
            default_mode="site_fallback",
            trace_summary="Streaming site fallback completed.",
        )

    # 2. Aquifer detection
    aq_hit = _detect_aquifer(question)
    if aq_hit is not None:
        aq_key, aq_name = aq_hit
        aq_sites = _sites_for_aquifer(aq_key, max_sites=8)
        if aq_sites:
            result = _augment_research_payload(
                _wrap(
                    _site_research_fallback(question, aq_sites, aq_name),
                    "aquifer_fallback",
                    aq_sites,
                ),
                question=question,
                max_depth=max_depth,
                default_mode="aquifer_fallback",
                trace_summary="Streaming aquifer fallback completed.",
            )
            result["aquifer_info"] = _build_aquifer_info(aq_name)
            return result

    # 3. Multi-location comparison
    locations = _detect_locations(question, max_matches=4)
    if len(locations) >= 2 and _is_multi_location_compare_query(question):
        multi_sites, multi_label = _sites_for_multiple_locations(
            locations, max_sites_per_location=4
        )
        if multi_sites:
            return _augment_research_payload(
                _wrap(
                    _site_research_fallback(question, multi_sites, multi_label),
                    "network_fallback",
                    multi_sites,
                ),
                question=question,
                max_depth=max_depth,
                default_mode="network_fallback",
                trace_summary="Streaming multi-location comparison completed.",
            )

    # 4. Location detection
    loc = _detect_location(question)
    if loc is not None:
        ref_lat, ref_lng, loc_name, county_hint = loc
        loc_sites = _best_sites_near(ref_lat, ref_lng, county_hint, max_sites=10)
        if loc_sites:
            result = _augment_research_payload(
                _wrap(
                    _site_research_fallback(
                        question,
                        loc_sites,
                        loc_name,
                        ref_lat=ref_lat,
                        ref_lng=ref_lng,
                    ),
                    "fallback",
                    loc_sites,
                ),
                question=question,
                max_depth=max_depth,
                default_mode="fallback",
                trace_summary="Streaming location fallback completed.",
            )
            if loc_sites:
                result["aquifer_info"] = _build_aquifer_info(loc_sites[0]["aquifer"])
            return result

    # 5. Network-wide detection
    if _is_network_wide_query(question):
        nw_sites = _all_sites_with_data(max_sites=36)
        if nw_sites:
            return _augment_research_payload(
                _wrap(
                    _site_research_fallback(question, nw_sites, "Florida monitoring network"),
                    "network_fallback",
                    nw_sites,
                ),
                question=question,
                max_depth=max_depth,
                default_mode="network_fallback",
                trace_summary="Streaming network fallback completed.",
            )

    # 6. Generic KB
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
    claim_verdicts = _build_claim_verdicts(fallback_claims)
    section_confidence = _build_section_confidence_from_claims(fallback_claims)
    return _augment_research_payload(
        {
            "type": "result",
            "status": "ok",
            "mode": "fallback",
            "report": fb["response"],
            "chart": None,
            "insights": [],
            "sources": fb["sources"],
            "search_history": [question],
            "depth_reached": 0,
            "elapsed_seconds": 0,
            "claim_citations": fallback_claims,
            "claim_verdicts": claim_verdicts,
            "claim_verdict_summary": _build_claim_verdict_summary(claim_verdicts),
            "citation_summary": _build_citation_summary(fallback_claims),
            "section_confidence": section_confidence,
            "hallucination_guardrail": {
                "strategy": "deterministic_fallback",
                "removed_uncited_factual_sentences": 0,
                "all_factual_claims_cited": True,
            },
            "citation_integrity": _build_citation_integrity(fallback_claims, section_confidence),
        },
        question=question,
        max_depth=max_depth,
        default_mode="fallback",
        trace_summary="Streaming generic fallback completed.",
    )


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
      - "progress"  -- intermediate status update while the agent works
      - "result"    -- the complete research payload (final event before None)
      - "error"     -- something went wrong; contains a "message" key
    """

    def progress_callback(
        message: str, progress: float, snapshot: dict[str, Any] | None = None
    ) -> None:
        """Bridge the agent's callback to the SSE queue."""
        event_queue.put(
            {
                "type": "progress",
                "message": message,
                "progress": round(progress, 2),
                "snapshot": snapshot or {},
            }
        )

    try:
        progress_callback("Initializing research session...", 0.03)
        if _research_agent is not None:
            # Real LLM-backed research -- progress events will flow.
            result = _research_agent.research(
                query=question,
                max_depth=max_depth,
                timeout=timeout,
                progress_callback=progress_callback,
            )
            result = attach_chart_from_agent_result(result)
            claim_citations = result.get("claim_citations", [])
            section_confidence = result.get("section_confidence", {})
            event_queue.put(
                _augment_research_payload(
                    {
                        "type": "result",
                        "status": "ok",
                        "mode": "deep_research",
                        "report": result.get("report", ""),
                        "chart": _chart_from(result, path="research.stream.agent"),
                        "insights": result.get("insights", []),
                        "sources": result.get("sources", []),
                        "session_id": result.get("session_id"),
                        "research_plan": result.get("research_plan"),
                        "budget_status": result.get("budget_status"),
                        "checkpoints": result.get("checkpoints"),
                        "tool_trace": result.get("tool_trace"),
                        "recommended_views": result.get("recommended_views"),
                        "chart_specs": result.get("chart_specs"),
                        "structured_response": result.get("structured_response"),
                        "search_history": result.get("search_history", []),
                        "depth_reached": result.get("depth_reached", 0),
                        "elapsed_seconds": result.get("elapsed_seconds", 0),
                        "claim_citations": claim_citations,
                        "claim_verdicts": result.get("claim_verdicts", []),
                        "claim_verdict_summary": result.get("claim_verdict_summary", {}),
                        "citation_summary": result.get(
                            "citation_summary",
                            {
                                "total_claims": 0,
                                "cited_claims": 0,
                                "citation_coverage": 0.0,
                            },
                        ),
                        "section_confidence": section_confidence,
                        "hallucination_guardrail": result.get("hallucination_guardrail", {}),
                        "citation_integrity": result.get(
                            "citation_integrity",
                            _build_citation_integrity(claim_citations, section_confidence),
                        ),
                    },
                    question=question,
                    max_depth=max_depth,
                    default_mode="deep_research",
                    trace_summary="Streaming LLM-backed research completed.",
                )
            )
        else:
            # Fallback mode -- use same routing chain as /api/research.
            progress_callback(
                "Routing to deterministic groundwater analysis...",
                0.2,
                {
                    "session_id": "",
                    "phase": "routing",
                    "research_plan": _heuristic_research_plan(question, max_depth),
                    "budget_status": {
                        "max_depth": max_depth,
                        "depth_reached": 0,
                        "elapsed_seconds": 0,
                        "insights_gathered": 0,
                        "status": "routing",
                    },
                    "checkpoints": [],
                    "tool_trace": [
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "phase": "routing",
                            "depth": 0,
                            "tool": "research_router",
                            "status": "started",
                            "details": {"summary": "Selecting deterministic fallback path."},
                        }
                    ],
                },
            )
            progress_callback(
                "Building cited groundwater response...",
                0.72,
                {
                    "session_id": "",
                    "phase": "synthesizing",
                    "research_plan": _heuristic_research_plan(question, max_depth),
                    "budget_status": {
                        "max_depth": max_depth,
                        "depth_reached": max(0, min(1, max_depth - 1)),
                        "elapsed_seconds": 0,
                        "insights_gathered": 0,
                        "status": "synthesizing",
                    },
                    "checkpoints": [],
                    "tool_trace": [
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "phase": "synthesizing",
                            "depth": 0,
                            "tool": "deterministic_fallback",
                            "status": "completed",
                            "details": {"summary": "Compiling deterministic groundwater analysis."},
                        }
                    ],
                },
            )
            event_queue.put(_stream_fallback_result(question, max_depth=max_depth))
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
      - type="progress"  -- intermediate status; "message" + "progress" (0-1)
      - type="result"    -- final research payload (same shape as /api/research)
      - type="error"     -- failure; "message" contains the error description
    """
    question = query.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    max_depth, timeout = _parse_research_limits(query)

    # Queue bridges the research thread to the streaming generator.
    event_queue: queue.Queue = queue.Queue(maxsize=0)

    # Kick off the research in a daemon thread.
    research_thread = threading.Thread(
        target=_run_research_in_thread,
        args=(question, max_depth, timeout, event_queue),
        daemon=True,
    )
    research_thread.start()

    def generate():
        r"""Pull events off the queue and yield them as SSE-formatted lines.

        The SSE wire format is:  data: <json>\n\n
        """
        while True:
            try:
                event = event_queue.get(timeout=_STREAM_QUEUE_TIMEOUT)
            except queue.Empty:
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /api/chat/status -- system health for chat subsystem
# ---------------------------------------------------------------------------


@router.get("/chat/status")
def chat_status():
    """Get AI chat and research system status."""
    degraded_reasons = _build_degraded_reasons()
    synthesis_available = _research_agent is not None
    return {
        "status": "ok" if (synthesis_available and not degraded_reasons) else "fallback",
        "version": "1.0.0",
        "agent_available": synthesis_available,
        "research_available": synthesis_available,
        "degraded_reasons": degraded_reasons,
        "runtime_checks": {
            "skip_agent_init": skip_agent_init,
            "web_search_enabled": research_web_search_enabled,
            "chat_agent_initialized": synthesis_available,
            "research_agent_initialized": synthesis_available,
            "last_chat_error": _runtime_error_state["chat"],
            "last_research_error": _runtime_error_state["research"],
        },
        "features": (
            [
                "Deterministic groundwater Q&A",
                "Evidence-linked research synthesis",
                "Hydrogeology document grounding",
                "Structured responses with claim and evidence IDs",
                "Reproducibility metadata and provenance hashes",
                "Deep research with iterative search",
                "Section-level confidence and trust metadata",
            ]
            if synthesis_available
            else [
                "Deterministic groundwater Q&A (fallback mode)",
                "Evidence-linked cited responses",
                "USGS well and aquifer context",
                "Research provenance metadata",
                "Aquifer information",
            ]
        ),
    }
