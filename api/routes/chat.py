"""Chat & research routes — AI agent endpoints and rule-based fallback.

Endpoints:
 • POST /api/chat       — Conversational agent
 • POST /api/research   — Deep iterative research
 • GET  /api/chat/status — System health for chat subsystem
"""

import logging
import sys
import traceback
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from api.site_metadata import SITE_METADATA

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
            "crops, soil moisture, aquifers, wells, saltwater "
            "intrusion, and seasonal patterns. Try asking about water "
            "levels for farming or which crops suit your area."
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

try:
    _src_dir = str(Path(__file__).parent.parent.parent / "src")
    if _src_dir not in sys.path:
        sys.path.insert(0, _src_dir)

    from src.agent.groundwater_agent import create_agent as _create_chat_agent  # noqa: E402
    from src.agent.research_agent import DeepResearchAgent  # noqa: E402

    _chat_agent = _create_chat_agent(verbose=False)
    _research_agent = DeepResearchAgent(
        max_depth=3,
        timeout_seconds=120,
    )
    logger.info("LLM-backed agents initialised successfully")
except Exception as exc:
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

    # --- Try real agent first ---
    if _chat_agent is not None:
        try:
            response_text = _chat_agent.chat(user_query)
            return {
                "response": response_text,
                "context": _get_site_context(),
                "sources": ["GroundwaterGPT Agent (LLM-backed)"],
                "mode": "agent",
                "status": "ok",
            }
        except Exception as exc:
            logger.error("Agent chat error: %s", exc)
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
            return {
                "status": "ok",
                "mode": "deep_research",
                "report": result.get("report", ""),
                "insights": result.get("insights", []),
                "sources": result.get("sources", []),
                "search_history": result.get("search_history", []),
                "depth_reached": result.get("depth_reached", 0),
                "elapsed_seconds": result.get("elapsed_seconds", 0),
            }
        except Exception as exc:
            logger.error(
                "Research agent error: %s\n%s",
                exc,
                traceback.format_exc(),
            )
            # Fall through to fallback

    # --- Fallback ---
    fb = _fallback_response(question)
    return {
        "status": "ok",
        "mode": "fallback",
        "report": fb["response"],
        "insights": [],
        "sources": fb["sources"],
        "search_history": [],
        "depth_reached": 0,
        "elapsed_seconds": 0,
    }


# ---------------------------------------------------------------------------
# GET /api/chat/status — system health for chat subsystem
# ---------------------------------------------------------------------------


@router.get("/chat/status")
def chat_status():
    """Get AI chat and research system status."""
    agent_available = _chat_agent is not None
    research_available = _research_agent is not None
    return {
        "status": "ok" if agent_available else "fallback",
        "version": "1.0.0",
        "agent_available": agent_available,
        "research_available": research_available,
        "features": (
            [
                "Conversational groundwater Q&A",
                "RAG with hydrogeology documents",
                "Seasonal pattern analysis",
                "Anomaly detection",
                "Data quality reports",
                "Deep research with iterative search",
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
