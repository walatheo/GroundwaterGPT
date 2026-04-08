"""Chat & research routes -- AI agent endpoints and rule-based fallback.

Endpoints:
 - POST /api/chat             -- Conversational agent
 - POST /api/research         -- Deep iterative research (blocking)
 - POST /api/research/stream  -- Deep iterative research with SSE progress stream
 - GET  /api/chat/status      -- System health for chat subsystem
"""

import json
import logging
import math
import os
import queue
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

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
    _detect_site_names,
    _is_aquifer_query,
    _is_network_wide_query,
    _sites_for_aquifer,
    _usgs_site_url,
)
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

router = APIRouter(prefix="/api", tags=["chat"])


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
    return f"Monitoring {n_sites} USGS sites across {n_counties} Florida counties."


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean environment flag with a safe default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
            "Could not initialise LLM agents -- " "falling back to rule-based chat. Reason: %s",
            exc,
        )
        _chat_agent = None
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
            "divergent_pairs": ns_result.get("divergent_pairs", []),
            "cohort_risk_level": ns_result.get("cohort_risk_level"),
            "llm_synthesis": ns_result.get("llm_synthesis"),
            "hallucination_guardrail": ns_result.get("hallucination_guardrail"),
            "citation_integrity": _build_citation_integrity(
                ns_result["claim_citations"], ns_result.get("section_confidence", {})
            ),
        }

    # --- Aquifer fast path: named aquifer -> all cohort sites (runs before location) ---
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
            "divergent_pairs": aq_result.get("divergent_pairs", []),
            "cohort_risk_level": aq_result.get("cohort_risk_level"),
            "llm_synthesis": aq_result.get("llm_synthesis"),
            "hallucination_guardrail": aq_result.get("hallucination_guardrail"),
            "citation_integrity": _build_citation_integrity(
                aq_result["claim_citations"], aq_result.get("section_confidence", {})
            ),
        }

    # --- Location fast path: return deterministic USGS-backed answer immediately ---
    loc = _detect_location(user_query)
    if loc is not None:
        ref_lat, ref_lng, loc_name, county_hint = loc
        sites = _best_sites_near(ref_lat, ref_lng, county_hint, max_sites=10)
        result = _site_research_fallback(
            user_query, sites, loc_name, ref_lat=ref_lat, ref_lng=ref_lng
        )
        wells_payload = _build_wells_payload(sites)
        response_dict: dict[str, Any] = {
            "response": result["report"],
            "context": _get_site_context(county_hint.title() if county_hint else None),
            "sources": result["sources"],
            "mode": "site_fallback",
            "status": "ok",
            "wells": wells_payload,
            "divergent_pairs": result.get("divergent_pairs", []),
            "cohort_risk_level": result.get("cohort_risk_level"),
            "llm_synthesis": result.get("llm_synthesis"),
            "hallucination_guardrail": result.get("hallucination_guardrail"),
            "citation_integrity": _build_citation_integrity(
                result["claim_citations"], result.get("section_confidence", {})
            ),
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
                "divergent_pairs": nw_result.get("divergent_pairs", []),
                "cohort_risk_level": nw_result.get("cohort_risk_level"),
                "llm_synthesis": nw_result.get("llm_synthesis"),
                "hallucination_guardrail": nw_result.get("hallucination_guardrail"),
                "citation_integrity": _build_citation_integrity(
                    nw_result["claim_citations"], nw_result.get("section_confidence", {})
                ),
            }

    # --- Try real agent first ---
    if _chat_agent is not None:
        try:
            response_text = _chat_agent.chat(user_query)
            _clear_runtime_error("chat")
            result: dict[str, Any] = {
                "response": response_text,
                "context": _get_site_context(),
                "sources": ["GroundwaterGPT Agent (LLM-backed)"],
                "mode": "agent",
                "status": "ok",
            }
            return _enrich_with_usgs_data(user_query, result)
        except Exception as exc:
            logger.error("Agent chat error: %s", exc)
            _set_runtime_error("chat", exc)
            # Fall through to rule-based fallback

    # --- Fallback ---
    return _enrich_with_usgs_data(user_query, _fallback_response(user_query))


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
    question = query.get("question", "")
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
            "llm_synthesis": ns_result.get("llm_synthesis"),
        }

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
            "llm_synthesis": aq_result.get("llm_synthesis"),
        }

    # --- Fallback: location-aware deterministic USGS response ---
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
            "llm_synthesis": site_result.get("llm_synthesis"),
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
                "llm_synthesis": nw_result.get("llm_synthesis"),
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
# POST /api/research/stream -- streaming deep research via SSE
# ---------------------------------------------------------------------------

# SSE stream timeout: slightly longer than the agent's own 120s ceiling so
# the generator never hangs indefinitely if the research thread crashes.
_STREAM_QUEUE_TIMEOUT = 135  # seconds


def _stream_fallback_result(question: str) -> dict:
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
            "cohort_risk_level": site_result.get("cohort_risk_level"),
        }

    # 1. Site-name detection
    named = _detect_site_names(question)
    if named:
        label = " vs ".join(s["name"] for s in named)
        return _wrap(
            _site_research_fallback(question, named, label),
            "site_fallback",
            named,
        )

    # 2. Aquifer detection
    aq_hit = _detect_aquifer(question)
    if aq_hit is not None:
        aq_key, aq_name = aq_hit
        aq_sites = _sites_for_aquifer(aq_key, max_sites=8)
        if aq_sites:
            result = _wrap(
                _site_research_fallback(question, aq_sites, aq_name),
                "aquifer_fallback",
                aq_sites,
            )
            result["aquifer_info"] = _build_aquifer_info(aq_name)
            return result

    # 3. Location detection
    loc = _detect_location(question)
    if loc is not None:
        ref_lat, ref_lng, loc_name, county_hint = loc
        loc_sites = _best_sites_near(ref_lat, ref_lng, county_hint, max_sites=10)
        if loc_sites:
            result = _wrap(
                _site_research_fallback(
                    question,
                    loc_sites,
                    loc_name,
                    ref_lat=ref_lat,
                    ref_lng=ref_lng,
                ),
                "fallback",
                loc_sites,
            )
            if loc_sites:
                result["aquifer_info"] = _build_aquifer_info(loc_sites[0]["aquifer"])
            return result

    # 4. Network-wide detection
    if _is_network_wide_query(question):
        nw_sites = _all_sites_with_data(max_sites=36)
        if nw_sites:
            return _wrap(
                _site_research_fallback(question, nw_sites, "Florida monitoring network"),
                "network_fallback",
                nw_sites,
            )

    # 5. Generic KB
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
    return {
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
    }


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

    def progress_callback(message: str, progress: float) -> None:
        """Bridge the agent's callback to the SSE queue."""
        event_queue.put(
            {
                "type": "progress",
                "message": message,
                "progress": round(progress, 2),
            }
        )

    try:
        if _research_agent is not None:
            # Real LLM-backed research -- progress events will flow.
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
            # Fallback mode -- use same routing chain as /api/research.
            event_queue.put(_stream_fallback_result(question))
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
