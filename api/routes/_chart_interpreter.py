"""Grounded chart-context interpreter for conversational follow-ups."""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from api.routes._citation import (
    _build_citation_integrity,
    _build_citation_summary,
    _build_claim_verdict_summary,
    _build_claim_verdicts,
    _build_section_confidence_from_claims,
)
from api.routes._detection import _build_wells_payload, _load_site_timeseries, _usgs_site_url
from api.routes._site_analysis import (
    _build_chart_explainability,
    _build_chart_insights,
    _cross_well_analysis,
    _seasonal_decomposition,
)
from api.site_metadata import SITE_METADATA

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HYDRO_INTERPRETATION_BANK_PATH = PROJECT_ROOT / "config" / "interpretation_answer_bank.json"
TRUSTED_RAG_LEVELS = {"verified", "primary", "trusted", "curated"}

INTERPRETER_PROMPT_HEAD = """You are a groundwater chart interpreter.

Use only the supplied EvidencePack. Quote numeric values only when they appear
in the EvidencePack. Every factual sentence must be anchored to a citation URL
or a deterministic chart metric. If a user asks for a cause, say the available
record does not prove causation unless pumping, rainfall, recharge, and model
context are supplied. Do not invent measurements, forecasts, or site metadata.

Example trend answer:
Question: which well is changing fastest?
Answer: The fastest decline is the well with the most negative annual_change_ft_yr
in the EvidencePack. Cite the USGS URL and include a NumericClaim with unit ft/yr.

Example guardrail answer:
Question: is this caused by pumping?
Answer: The chart shows an observed trend, but the available record does not
prove pumping caused it. Pumping attribution would require pumping records,
rainfall/recharge data, and groundwater-flow model context.
"""

HEDGE_PHRASES = (
    "does not prove",
    "available record does not show",
    "cannot attribute",
    "would require",
    "not enough evidence",
)


@lru_cache(maxsize=1)
def _load_hydro_interpretation_bank() -> list[dict[str, Any]]:
    """Load curated hydrogeology concepts used as fast local RAG fallback."""
    try:
        with HYDRO_INTERPRETATION_BANK_PATH.open() as fh:
            payload = json.load(fh)
    except Exception as exc:
        logger.debug("Hydro interpretation bank unavailable: %s", exc)
        return []
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _unique_terms(values: list[Any], limit: int = 28) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        terms.append(text)
        seen.add(key)
        if len(terms) >= limit:
            break
    return terms


def _trend_terms(cross_well: dict[str, Any] | None) -> list[str]:
    if not isinstance(cross_well, dict):
        return []
    terms: list[str] = []
    mean = cross_well.get("mean_annual_change_ft_yr")
    try:
        mean_value = float(mean)
    except (TypeError, ValueError):
        mean_value = 0.0
    if mean_value < -0.02:
        terms.extend(["declining groundwater levels", "drawdown", "negative trend"])
    elif mean_value > 0.02:
        terms.extend(["rising groundwater levels", "recovery", "positive trend"])
    trend_distribution = cross_well.get("trend_distribution") or {}
    if isinstance(trend_distribution, dict):
        if trend_distribution.get("decreasing") or trend_distribution.get("falling"):
            terms.extend(["declining wells", "pumping stress"])
        if trend_distribution.get("increasing") or trend_distribution.get("rising"):
            terms.append("rising wells")
    risk = str(cross_well.get("risk_level") or "").strip()
    if risk:
        terms.append(f"{risk} screening risk")
    return terms


def _context_terms_from_sites(
    sites: list[dict[str, Any]] | None,
    cross_well: dict[str, Any] | None,
    turn_history: list[dict[str, Any]] | None,
) -> list[str]:
    values: list[Any] = []
    for site in sites or []:
        values.extend(
            [
                site.get("name"),
                site.get("site_id"),
                site.get("aquifer"),
                site.get("aquifer_type"),
                site.get("aquifer_zone"),
                site.get("aquifer_description"),
                site.get("county"),
                "confined aquifer" if site.get("confined") else "unconfined aquifer",
            ]
        )
    for metric in (cross_well or {}).get("per_site_metrics", []) or []:
        values.extend([metric.get("name"), metric.get("aquifer"), metric.get("county")])
    values.extend(_trend_terms(cross_well))
    for turn in list(turn_history or [])[-4:]:
        if not isinstance(turn, dict):
            continue
        values.extend([turn.get("aquifer"), turn.get("cohort_risk_level")])
        for well in turn.get("wells") or []:
            if isinstance(well, dict):
                values.extend([well.get("name"), well.get("aquifer"), well.get("site_id")])
    return _unique_terms(values)


def _build_enriched_rag_query(
    question: str,
    sites: list[dict[str, Any]] | None = None,
    cross_well: dict[str, Any] | None = None,
    turn_history: list[dict[str, Any]] | None = None,
) -> str:
    """Build a retrieval query grounded in the active chart context."""
    terms = _context_terms_from_sites(sites, cross_well, turn_history)
    query_parts = _unique_terms([question, *terms, "groundwater interpretation"], limit=32)
    return " ".join(query_parts)


def _score_hydro_bank_entry(entry: dict[str, Any], search_text: str) -> int:
    score = 0
    for term in entry.get("trigger_terms") or []:
        term_text = str(term).strip().lower()
        if term_text and term_text in search_text:
            score += 4
    for tag in entry.get("tags") or []:
        tag_text = str(tag).strip().lower()
        if tag_text and tag_text in search_text:
            score += 3
    if "declin" in search_text and "decline" in entry.get("tags", []):
        score += 3
    if "season" in search_text and "seasonal" in entry.get("tags", []):
        score += 3
    if "supply" in search_text and "supply" in entry.get("tags", []):
        score += 3
    if "salt" in search_text and "saltwater" in entry.get("tags", []):
        score += 3
    if "confined" in search_text and "confined" in entry.get("tags", []):
        score += 2
    return score


def _select_hydro_bank_snippets(
    question: str,
    sites: list[dict[str, Any]] | None = None,
    cross_well: dict[str, Any] | None = None,
    turn_history: list[dict[str, Any]] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Select curated hydro concept snippets for the active interpretation."""
    query = _build_enriched_rag_query(question, sites, cross_well, turn_history)
    search_text = query.lower()
    question_text = str(question or "").lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in _load_hydro_interpretation_bank():
        score = _score_hydro_bank_entry(entry, search_text)
        for term in entry.get("trigger_terms") or []:
            term_text = str(term).strip().lower()
            if term_text and term_text in question_text:
                score += 16
                if term_text != "why":
                    score += 40
        for tag in entry.get("tags") or []:
            tag_text = str(tag).strip().lower()
            if tag_text and tag_text in question_text:
                score += 5
        if score <= 0:
            continue
        scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
    snippets: list[dict[str, Any]] = []
    for score, entry in scored[:limit]:
        content_parts = [str(entry.get("summary", "")).strip()]
        caveat = str(entry.get("caveat", "")).strip()
        if caveat:
            content_parts.append(f"Caveat: {caveat}")
        snippets.append(
            {
                "doc_id": f"hydro_bank:{entry.get('id')}",
                "content": " ".join(part for part in content_parts if part)[:700],
                "url": "local://eagle/hydro-interpretation-bank",
                "trust_level": "curated",
                "similarity_score": round(min(score / 12.0, 1.0), 3),
                "tags": entry.get("tags", []),
                "interpretive_move": entry.get("interpretive_move"),
                "evidence_needed": entry.get("evidence_needed", []),
                "implication": entry.get("implication"),
                "follow_up_questions": entry.get("follow_up_questions", []),
                "source_type": "curated_hydro_context",
            }
        )
    return snippets


class NumericClaim(BaseModel):
    """One numeric statement that must map to deterministic evidence."""

    site: str
    value: float
    unit: Literal["ft/yr", "ft", "ft_bls", "yr"]
    source: str

    @model_validator(mode="after")
    def _source_unit_must_match(self) -> "NumericClaim":
        source = str(self.source)
        expected_by_source = {
            "annual_change_ft_yr": "ft/yr",
            "mean_annual_change_ft_yr": "ft/yr",
            "net_change_ft": "ft",
            "well_depth_ft": "ft",
            "record_years": "yr",
            "latest_depth_to_water_ft": "ft_bls",
        }
        expected = expected_by_source.get(source)
        if expected and self.unit != expected:
            raise ValueError(f"{source} claims must use {expected}")
        return self


class InterpretationResult(BaseModel):
    """Structured chart interpretation result."""

    answer: str
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    evidence_used: dict[str, Any] = Field(default_factory=dict)
    grounding_status: Literal["grounded", "partial", "refused"]
    follow_up_questions: list[str] = Field(default_factory=list)
    guardrail_flags: list[str] = Field(default_factory=list)


def _site_ids_from_chart_context(chart_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(chart_context, dict):
        return []
    raw_site_ids = chart_context.get("site_ids") or []
    if not raw_site_ids and isinstance(chart_context.get("summary_metrics"), dict):
        raw_site_ids = chart_context["summary_metrics"].get("site_ids") or []
    site_ids = []
    for raw in raw_site_ids:
        site_id = str(raw).strip()
        if site_id and site_id not in site_ids:
            site_ids.append(site_id)
    return site_ids[:12]


def _sites_from_chart_context(chart_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    sites: list[dict[str, Any]] = []
    for site_id in _site_ids_from_chart_context(chart_context):
        meta = SITE_METADATA.get(site_id)
        if not meta:
            continue
        series = _load_site_timeseries(site_id)
        if series is None or series.empty:
            continue
        sites.append(
            {
                "site_id": site_id,
                "name": meta.get("name", site_id),
                "county": meta.get("county", "Florida"),
                "aquifer": meta.get("aquifer", "Unknown"),
                "aquifer_type": meta.get("aquifer_type", "unconfined"),
                "confined": meta.get("confined", False),
                "aquifer_zone": meta.get("aquifer_zone", ""),
                "aquifer_zone_depth_range_ft": meta.get("aquifer_zone_depth_range_ft", [0, 100]),
                "aquifer_description": meta.get("aquifer_description", ""),
                "well_depth_ft": meta.get("well_depth_ft", meta.get("depth")),
                "lat": meta.get("lat"),
                "lng": meta.get("lng"),
                "series": series,
            }
        )
    return sites


def _highlighted_site_ids(cross_well: dict[str, Any]) -> set[str]:
    highlighted: set[str] = set()
    for pair in cross_well.get("divergent_pairs", []) or []:
        for side in ("site_a", "site_b"):
            site_id = str((pair.get(side) or {}).get("site_id", "")).strip()
            if site_id:
                highlighted.add(site_id)
    per_site = cross_well.get("per_site_metrics", []) or []
    if per_site:
        fastest_decline = min(per_site, key=lambda item: item["annual_change_ft_yr"])
        strongest_rise = max(per_site, key=lambda item: item["annual_change_ft_yr"])
        highlighted.add(str(fastest_decline["site_id"]))
        if strongest_rise["annual_change_ft_yr"] > 0:
            highlighted.add(str(strongest_rise["site_id"]))
    return highlighted


def _rag_snippets(question: str) -> list[dict[str, Any]]:
    if os.getenv("GROUNDWATERGPT_ENABLE_INTERPRETER_VECTOR_RAG", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return []
    if os.getenv("GROUNDWATERGPT_DISABLE_INTERPRETER_RAG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return []
    try:
        from src.agent.knowledge import search_knowledge

        docs = search_knowledge(question, k=5, score_threshold=0.45)
    except Exception as exc:
        logger.debug("Chart interpreter KB search unavailable: %s", exc)
        return []

    snippets = []
    for idx, doc in enumerate(docs):
        metadata = dict(getattr(doc, "metadata", {}) or {})
        snippets.append(
            {
                "doc_id": metadata.get("doc_id") or f"rag_{idx + 1}",
                "content": str(getattr(doc, "page_content", ""))[:700],
                "url": metadata.get("source_url")
                or metadata.get("url")
                or metadata.get("source")
                or "",
                "trust_level": metadata.get("trust_level", "unknown"),
                "similarity_score": metadata.get("similarity_score"),
            }
        )
    return snippets[:3]


def _rag_snippets_with_context(
    question: str,
    sites: list[dict[str, Any]] | None = None,
    cross_well: dict[str, Any] | None = None,
    turn_history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve curated and vector KB snippets using chart-aware context."""
    if os.getenv("GROUNDWATERGPT_DISABLE_INTERPRETER_RAG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return []
    curated = _select_hydro_bank_snippets(question, sites, cross_well, turn_history, limit=3)
    enriched_query = _build_enriched_rag_query(question, sites, cross_well, turn_history)
    try:
        vector_snippets = _rag_snippets(enriched_query)
    except Exception as exc:
        logger.debug("Contextual KB search failed: %s", exc)
        vector_snippets = []
    snippets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for snippet in [*curated, *vector_snippets]:
        doc_id = str(snippet.get("doc_id") or snippet.get("content", "")[:80])
        if doc_id in seen:
            continue
        snippets.append(snippet)
        seen.add(doc_id)
        if len(snippets) >= 5:
            break
    return snippets


def build_evidence_pack(
    question: str,
    chart_context: dict[str, Any] | None,
    turn_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build deterministic chart evidence for interpreter prompts and tests."""
    sites = _sites_from_chart_context(chart_context)
    if not sites:
        return {
            "question": question,
            "chart_context": chart_context or {},
            "turn_history": list(turn_history or [])[-4:],
            "sites": [],
            "site_ids": [],
            "wells": [],
            "cross_well": {},
            "insights": [],
            "explainability": {},
            "rag_snippets": _rag_snippets_with_context(question, turn_history=turn_history),
            "enriched_rag_query": _build_enriched_rag_query(question, turn_history=turn_history),
        }

    cross_well = _cross_well_analysis(sites)
    highlighted = _highlighted_site_ids(cross_well)
    explainability = _build_chart_explainability(cross_well, highlighted, len(sites))
    insights = _build_chart_insights(cross_well, highlighted)
    wells = _build_wells_payload(sites)
    return {
        "question": question,
        "chart_context": chart_context or {},
        "turn_history": list(turn_history or [])[-4:],
        "sites": [
            {
                "site_id": site["site_id"],
                "name": site["name"],
                "aquifer": site.get("aquifer"),
                "aquifer_type": site.get("aquifer_type"),
                "aquifer_zone": site.get("aquifer_zone"),
                "county": site.get("county"),
                "confined": bool(site.get("confined", False)),
                "well_depth_ft": site.get("well_depth_ft"),
                "seasonal": _seasonal_decomposition(site.get("series")),
            }
            for site in sites
        ],
        "site_ids": [site["site_id"] for site in sites],
        "wells": wells,
        "cross_well": cross_well,
        "insights": insights,
        "explainability": explainability,
        "rag_snippets": _rag_snippets_with_context(question, sites, cross_well, turn_history),
        "enriched_rag_query": _build_enriched_rag_query(question, sites, cross_well, turn_history),
    }


def _numeric_claims_from_pack(pack: dict[str, Any]) -> list[NumericClaim]:
    claims: list[NumericClaim] = []
    for metric in pack.get("cross_well", {}).get("per_site_metrics", []) or []:
        claims.append(
            NumericClaim(
                site=str(metric["name"]),
                value=float(metric["annual_change_ft_yr"]),
                unit="ft/yr",
                source="annual_change_ft_yr",
            )
        )
        claims.append(
            NumericClaim(
                site=str(metric["name"]),
                value=float(metric["net_change_ft"]),
                unit="ft",
                source="net_change_ft",
            )
        )
    mean = pack.get("cross_well", {}).get("mean_annual_change_ft_yr")
    if mean is not None:
        claims.append(
            NumericClaim(
                site="cohort",
                value=float(mean),
                unit="ft/yr",
                source="mean_annual_change_ft_yr",
            )
        )
    return claims


def _citations_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    citations = [
        {
            "url": _usgs_site_url(str(site_id)),
            "trust_level": "verified",
            "anchor": str(site_id),
            "verified": True,
        }
        for site_id in pack.get("site_ids", [])[:10]
    ]
    for snippet in pack.get("rag_snippets", []) or []:
        if snippet.get("url"):
            citations.append(
                {
                    "url": snippet["url"],
                    "trust_level": snippet.get("trust_level", "unknown"),
                    "anchor": snippet.get("doc_id", "knowledge_base"),
                    "verified": snippet.get("trust_level") in TRUSTED_RAG_LEVELS,
                }
            )
    return citations


def _hydro_concepts_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    concepts: list[dict[str, Any]] = []
    for snippet in pack.get("rag_snippets", []) or []:
        if snippet.get("source_type") != "curated_hydro_context":
            continue
        concepts.append(
            {
                "id": snippet.get("doc_id"),
                "summary": snippet.get("content"),
                "tags": snippet.get("tags", []),
                "interpretive_move": snippet.get("interpretive_move"),
                "evidence_needed": snippet.get("evidence_needed", []),
                "implication": snippet.get("implication"),
                "source": snippet.get("url"),
            }
        )
    return concepts[:4]


def _hydro_caveats_from_pack(pack: dict[str, Any]) -> list[str]:
    caveats: list[str] = []
    for concept in _hydro_concepts_from_pack(pack):
        text = str(concept.get("summary") or "")
        marker = "Caveat:"
        if marker not in text:
            continue
        caveat = text.split(marker, 1)[1].strip()
        if caveat and caveat not in caveats:
            caveats.append(caveat)
    return caveats[:4]


def _followups_from_hydro_context(pack: dict[str, Any]) -> list[str]:
    followups: list[str] = []
    if pack.get("site_ids"):
        followups.extend(
            [
                "Explain the decline using these wells.",
                "Which well is changing fastest?",
                "What caveats should I mention?",
                "Is this seasonal or long-term?",
            ]
        )
    for snippet in pack.get("rag_snippets", []) or []:
        for question in snippet.get("follow_up_questions") or []:
            text = str(question).strip()
            if text and text not in followups:
                followups.append(text)
    return followups[:4]


def _is_causal_question(question: str) -> bool:
    return bool(
        re.search(
            r"\b(why|pumping|climate change|run dry|prove|forecast|by 2030"
            r"|management claim)\b|caus\w*|overpump\w*",
            question,
            re.I,
        )
    )


def _select_relevant_claims(
    question: str,
    numeric_claims: list[NumericClaim],
) -> list[NumericClaim]:
    lowered = question.lower()
    selected = [
        claim
        for claim in numeric_claims
        if claim.unit == "ft/yr"
        and claim.site.lower() != "cohort"
        and claim.site.lower() in lowered
    ]
    if selected:
        return selected[:4]
    annual = [
        claim
        for claim in numeric_claims
        if claim.unit == "ft/yr" and claim.site.lower() != "cohort"
    ]
    if not annual:
        return numeric_claims[:4]
    fastest_decline = min(annual, key=lambda claim: claim.value)
    strongest_rise = max(annual, key=lambda claim: claim.value)
    selected = [fastest_decline]
    if strongest_rise.site != fastest_decline.site:
        selected.append(strongest_rise)
    cohort = next((claim for claim in numeric_claims if claim.site == "cohort"), None)
    if cohort:
        selected.append(cohort)
    return selected[:4]


def _concept_summary(concept: dict[str, Any]) -> str:
    return str(concept.get("summary", "")).split("Caveat:", 1)[0].strip()


def _concept_tags(pack: dict[str, Any]) -> set[str]:
    tags: set[str] = set()
    for concept in _hydro_concepts_from_pack(pack):
        for tag in concept.get("tags", []) or []:
            text = str(tag).strip().lower()
            if text:
                tags.add(text)
    return tags


def _observed_signal_text(selected_claims: list[NumericClaim], pack: dict[str, Any]) -> str:
    if not selected_claims:
        return (
            "The available chart context does not contain enough deterministic trend "
            "metrics to summarize the observed signal."
        )
    rate_text = "; ".join(
        f"{claim.site}: {claim.value:+.3f} {claim.unit}"
        for claim in selected_claims
        if claim.unit == "ft/yr"
    )
    if not rate_text:
        rate_text = "; ".join(
            f"{claim.site}: {claim.value:+.2f} {claim.unit}" for claim in selected_claims
        )
    risk = str((pack.get("cross_well") or {}).get("risk_level") or "").strip().lower()
    risk_text = f" The cohort screening risk is {risk}." if risk else ""
    return f"The chart-backed signal is {rate_text}.{risk_text}"


def _possible_driver_texts(pack: dict[str, Any]) -> list[str]:
    tags = _concept_tags(pack)
    drivers: list[str] = []
    if {"decline", "drawdown", "stress"} & tags:
        drivers.append("drawdown or reduced aquifer pressure")
    if {"seasonal", "recharge", "wet season", "dry season"} & tags:
        drivers.append("seasonal recharge and dry-season variability")
    if {"pumping", "demand", "causality"} & tags:
        drivers.append("pumping stress or changing water demand")
    if {"confined", "artesian", "pressure"} & tags:
        drivers.append("pressure-head change in confined aquifer units")
    if {"shallow", "deep", "aquifer comparison", "confinement"} & tags:
        drivers.append("different responses between shallow and deeper monitored zones")
    if {"saltwater", "coastal", "intrusion", "risk"} & tags:
        drivers.append("coastal saltwater-intrusion concern if supported by water-quality data")
    if {"supply", "proxy", "monitoring well", "aquifer source"} & tags:
        drivers.append("proxy mismatch between monitoring wells and production wells")
    if not drivers:
        drivers.append(
            "site-specific recharge, withdrawals, aquifer confinement, or record-length effects"
        )
    return drivers[:5]


def _evidence_needed_texts(pack: dict[str, Any]) -> list[str]:
    tags = _concept_tags(pack)
    needed: list[str] = []
    for concept in _hydro_concepts_from_pack(pack):
        for item in concept.get("evidence_needed") or []:
            text = str(item).strip()
            if text:
                needed.append(text)
    needed.extend(
        [
            "pumping or withdrawal records",
            "rainfall, recharge, and drought-period data",
            "well construction, screened interval, and aquifer-unit documentation",
            "nearby monitoring wells to test whether the signal is local or regional",
        ]
    )
    if {"saltwater", "coastal", "intrusion", "risk"} & tags:
        needed.extend(
            [
                "chloride, salinity, or conductivity records",
                "coastal boundary, canal-stage, or tidal context",
            ]
        )
    if {"supply", "proxy", "monitoring well", "aquifer source"} & tags:
        needed.append("production-well or utility supply-source documentation")
    if {"seasonal", "recharge", "wet season", "dry season"} & tags:
        needed.append("seasonality-aware trend checks over multiple wet and dry cycles")
    return list(dict.fromkeys(needed))[:7]


def _build_interpretive_sections(
    question: str,
    pack: dict[str, Any],
    selected_claims: list[NumericClaim],
) -> dict[str, Any]:
    concepts = _hydro_concepts_from_pack(pack)
    tags = _concept_tags(pack)
    primary_concept = _concept_summary(concepts[0]) if concepts else ""
    observed_signal = _observed_signal_text(selected_claims, pack)
    possible_drivers = _possible_driver_texts(pack)
    evidence_needed = _evidence_needed_texts(pack)
    risk = str((pack.get("cross_well") or {}).get("risk_level") or "").strip().lower()

    if primary_concept:
        hydro_meaning = primary_concept
    elif selected_claims:
        hydro_meaning = (
            "The pattern is useful as a groundwater screening signal, but its meaning depends on "
            "aquifer setting, seasonality, record length, and nearby well behavior."
        )
    else:
        hydro_meaning = (
            "The available chart context is not sufficient for a hydrogeologic interpretation."
        )

    if "saltwater" in tags:
        implication = (
            "For a coastal or supply-planning discussion, this is a prompt to check water-quality "
            "and pumping evidence before making an intrusion claim."
        )
    elif {"supply", "proxy", "monitoring well", "aquifer source"} & tags:
        implication = (
            "For supply interpretation, the chart can support a proxy-based screening discussion, "
            "but production-well documentation is needed before treating the monitoring wells "
            "as the utility source."
        )
    elif {"decline", "drawdown", "stress"} & tags or risk in {"moderate", "high"}:
        implication = (
            "For students, sponsors, or analysts, this is a screening flag: the wells deserve "
            "follow-up because persistent decline can matter for sustainability, drawdown, "
            "and monitoring priorities."
        )
    else:
        implication = (
            "The result is most useful as an auditable starting point for comparing monitored "
            "wells and deciding which outside evidence to collect next."
        )

    confidence_note = (
        "Confidence is strongest for the observed USGS trend metrics and weaker for causes; "
        "the chart does not prove pumping, recharge change, saltwater intrusion, or "
        "management impact without external covariates."
    )
    if "seasonal" in tags:
        confidence_note += (
            " Seasonal and long-term signals should be separated before making a trend claim."
        )
    if "confined" in tags:
        confidence_note += (
            " In confined units, water-level change is interpreted as pressure-head change, "
            "not simple water-table drainage."
        )

    findings = [
        {"label": "Observed signal", "text": observed_signal},
        {"label": "Hydrogeologic meaning", "text": hydro_meaning},
        {"label": "Possible explanations", "text": "; ".join(possible_drivers) + "."},
        {"label": "Evidence needed", "text": "; ".join(evidence_needed) + "."},
        {"label": "Implication", "text": implication},
        {"label": "Confidence note", "text": confidence_note},
    ]

    return {
        "observed_signal": observed_signal,
        "hydrogeologic_meaning": hydro_meaning,
        "possible_drivers": possible_drivers,
        "evidence_needed": evidence_needed,
        "management_implications": [implication],
        "confidence_notes": [confidence_note],
        "interpretive_findings": findings,
        "question_intent": str(question or "").strip(),
    }


def _format_rate(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{numeric:+.3f} ft/yr"


def _metric_context_by_site(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}
    for site in pack.get("sites", []) or []:
        site_id = str(site.get("site_id") or "").strip()
        if site_id:
            context[site_id] = dict(site)
    return context


def _enriched_metrics(pack: dict[str, Any]) -> list[dict[str, Any]]:
    site_context = _metric_context_by_site(pack)
    enriched: list[dict[str, Any]] = []
    for metric in (pack.get("cross_well") or {}).get("per_site_metrics", []) or []:
        site_id = str(metric.get("site_id") or "").strip()
        merged = {**metric, **site_context.get(site_id, {})}
        merged["site_id"] = site_id or metric.get("site_id")
        enriched.append(merged)
    return enriched


def _mean_rate(metrics: list[dict[str, Any]]) -> float | None:
    values = []
    for metric in metrics:
        try:
            values.append(float(metric["annual_change_ft_yr"]))
        except (KeyError, TypeError, ValueError):
            continue
    return sum(values) / len(values) if values else None


def _mean_seasonal_amplitude(metrics: list[dict[str, Any]]) -> float | None:
    values = []
    for metric in metrics:
        seasonal = metric.get("seasonal") or {}
        if not seasonal.get("has_seasonal"):
            continue
        try:
            values.append(float(seasonal.get("seasonal_amplitude_ft")))
        except (TypeError, ValueError):
            continue
    return sum(values) / len(values) if values else None


def _group_metrics_by_confinement(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = {
        "shallow_unconfined": {
            "label": "shallow/unconfined",
            "metrics": [],
        },
        "deep_confined": {
            "label": "deep/confined",
            "metrics": [],
        },
    }
    for metric in _enriched_metrics(pack):
        key = "deep_confined" if metric.get("confined") else "shallow_unconfined"
        groups[key]["metrics"].append(metric)
    for key, group in groups.items():
        metrics = group["metrics"]
        group["count"] = len(metrics)
        group["mean_annual_change_ft_yr"] = _mean_rate(metrics)
        group["mean_seasonal_amplitude_ft"] = _mean_seasonal_amplitude(metrics)
        group["well_names"] = [str(metric.get("name")) for metric in metrics if metric.get("name")]
        group["site_ids"] = [
            str(metric.get("site_id")) for metric in metrics if metric.get("site_id")
        ]
        group.pop("metrics", None)
    return groups


def _largest_rate_gap(metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(metrics) < 2:
        return None
    sorted_metrics = sorted(metrics, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
    low = sorted_metrics[0]
    high = sorted_metrics[-1]
    return {
        "site_a": low,
        "site_b": high,
        "gap_ft_yr": abs(
            float(high.get("annual_change_ft_yr", 0.0)) - float(low.get("annual_change_ft_yr", 0.0))
        ),
    }


def _detect_question_intent(question: str, pack: dict[str, Any]) -> str:
    del pack
    text = str(question or "").lower()
    if re.search(r"\b(shallow|deep|confined|unconfined|diverge|divergent|aquifer wells?)\b", text):
        return "shallow_deep_comparison"
    if re.search(
        r"\b(fastest|most|which well|which one|steepest|largest change|changing fastest)\b", text
    ):
        return "fastest_changing"
    if re.search(r"\b(risk|screening|what does this mean|why does this matter|concern)\b", text):
        return "risk_explanation"
    if re.search(
        r"\b(cohort|average|mean annual|mean rate|mean change|what does the average mean)\b", text
    ):
        return "cohort_meaning"
    return "general"


def _shallow_deep_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    metrics = _enriched_metrics(pack)
    groups = _group_metrics_by_confinement(pack)
    shallow = groups["shallow_unconfined"]
    deep = groups["deep_confined"]
    if not shallow["count"] or not deep["count"]:
        present = shallow if shallow["count"] else deep
        direct = (
            "This chart does not contain both shallow/unconfined and deep/confined groups, "
            f"so it cannot support a true shallow-vs-deep divergence comparison. It contains "
            f"{present['count']} {present['label']} well{'s' if present['count'] != 1 else ''}."
        )
        return direct, [direct], {"comparison_groups": groups}

    shallow_rate = float(shallow["mean_annual_change_ft_yr"])
    deep_rate = float(deep["mean_annual_change_ft_yr"])
    gap = abs(shallow_rate - deep_rate)
    diverges = gap >= 0.05
    direction = "Yes, they diverge" if diverges else "They differ, but only modestly"
    direct = (
        f"{direction}: the {shallow['count']} shallow/unconfined well"
        f"{'s' if shallow['count'] != 1 else ''} average {_format_rate(shallow_rate)}, "
        f"while the {deep['count']} deep/confined well{'s' if deep['count'] != 1 else ''} "
        f"average {_format_rate(deep_rate)}."
    )
    largest_gap = _largest_rate_gap(metrics)
    evidence = []
    if largest_gap:
        a = largest_gap["site_a"]
        b = largest_gap["site_b"]
        evidence.append(
            f"The largest well-level gap is between {a.get('name')} "
            f"({_format_rate(a.get('annual_change_ft_yr'))}) "
            f"and {b.get('name')} ({_format_rate(b.get('annual_change_ft_yr'))})."
        )
    if (
        shallow.get("mean_seasonal_amplitude_ft") is not None
        or deep.get("mean_seasonal_amplitude_ft") is not None
    ):
        shallow_amp = shallow.get("mean_seasonal_amplitude_ft")
        deep_amp = deep.get("mean_seasonal_amplitude_ft")
        amp_parts = []
        if shallow_amp is not None:
            amp_parts.append(f"shallow seasonal amplitude averages {shallow_amp:.1f} ft")
        if deep_amp is not None:
            amp_parts.append(f"deep/confined amplitude averages {deep_amp:.1f} ft")
        evidence.append("; ".join(amp_parts) + ".")
    return direct, evidence, {"comparison_groups": groups, "largest_gap": largest_gap}


def _fastest_changing_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    metrics = _enriched_metrics(pack)
    annual = [m for m in metrics if m.get("annual_change_ft_yr") is not None]
    if not annual:
        direct = (
            "The chart does not include enough rate information to identify the "
            "fastest-changing well."
        )
        return direct, [direct], {}
    by_decline = sorted(annual, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
    fastest_decline = by_decline[0]
    strongest_rise = by_decline[-1]
    direct = (
        f"{fastest_decline.get('name')} is declining fastest at "
        f"{_format_rate(fastest_decline.get('annual_change_ft_yr'))}."
    )
    evidence = []
    if len(by_decline) > 1:
        second = by_decline[1]
        evidence.append(
            f"Next most negative is {second.get('name')} at "
            f"{_format_rate(second.get('annual_change_ft_yr'))}."
        )
    if (
        strongest_rise is not fastest_decline
        and float(strongest_rise.get("annual_change_ft_yr", 0.0)) > 0
    ):
        evidence.append(
            f"The strongest rising well is {strongest_rise.get('name')} at "
            f"{_format_rate(strongest_rise.get('annual_change_ft_yr'))}."
        )
    return direct, evidence, {"fastest_decline": fastest_decline, "strongest_rise": strongest_rise}


def _cohort_meaning_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    cross_well = pack.get("cross_well") or {}
    metrics = _enriched_metrics(pack)
    mean = cross_well.get("mean_annual_change_ft_yr")
    n_total = int(cross_well.get("n_total") or len(metrics))
    dist = cross_well.get("trend_distribution") or {}
    try:
        mean_value = float(mean)
    except (TypeError, ValueError):
        mean_value = None
    if mean_value is None:
        direct = "The chart does not include enough wells to compute a meaningful cohort average."
        return direct, [direct], {}
    below = [m for m in metrics if float(m.get("annual_change_ft_yr", 0.0)) < mean_value]
    above = [m for m in metrics if float(m.get("annual_change_ft_yr", 0.0)) >= mean_value]
    direct = (
        f"The cohort average is the mean annual change across the {n_total} wells in this chart; "
        f"here it is {_format_rate(mean_value)}."
    )
    evidence = [
        (
            f"{dist.get('falling', 0)} wells are falling, "
            f"{dist.get('stable', 0)} are stable, and "
            f"{dist.get('rising', 0)} are rising."
        ),
        f"{len(below)} wells are below the cohort average and {len(above)} are at or above it.",
    ]
    return (
        direct,
        evidence,
        {"cohort_meaning": {"below_average": len(below), "at_or_above_average": len(above)}},
    )


def _risk_explanation_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    cross_well = pack.get("cross_well") or {}
    metrics = _enriched_metrics(pack)
    dist = cross_well.get("trend_distribution") or {}
    n_total = int(cross_well.get("n_total") or len(metrics) or 0)
    falling = int(dist.get("falling", 0))
    pct = float(falling / n_total) if n_total else 0.0
    risk = str(cross_well.get("risk_level") or "unknown").lower()
    direct = (
        f"The {risk} screening risk means {falling} of {n_total} wells "
        f"({pct:.0%}) are falling or the cohort has enough decline to warrant follow-up."
    )
    annual = [m for m in metrics if m.get("annual_change_ft_yr") is not None]
    evidence = []
    if annual:
        worst = min(annual, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
        evidence.append(
            f"The strongest contributor to concern is {worst.get('name')} at "
            f"{_format_rate(worst.get('annual_change_ft_yr'))}."
        )
    mean = cross_well.get("mean_annual_change_ft_yr")
    if mean is not None:
        evidence.append(f"The cohort mean is {_format_rate(mean)}.")
    return (
        direct,
        evidence,
        {
            "risk_summary": {
                "risk_level": risk,
                "falling_count": falling,
                "n_total": n_total,
                "pct_falling": pct,
            }
        },
    )


def _general_answer(
    pack: dict[str, Any], interpretive_sections: dict[str, Any]
) -> tuple[str, list[str], dict[str, Any]]:
    direct = interpretive_sections["hydrogeologic_meaning"]
    evidence = [interpretive_sections["observed_signal"]]
    return direct, evidence, {}


def _build_intent_answer(
    question: str,
    pack: dict[str, Any],
    interpretive_sections: dict[str, Any],
) -> dict[str, Any]:
    intent = _detect_question_intent(question, pack)
    builders = {
        "shallow_deep_comparison": _shallow_deep_answer,
        "fastest_changing": _fastest_changing_answer,
        "cohort_meaning": _cohort_meaning_answer,
        "risk_explanation": _risk_explanation_answer,
    }
    if intent in builders:
        direct_answer, supporting_evidence, extra = builders[intent](pack)
    else:
        direct_answer, supporting_evidence, extra = _general_answer(pack, interpretive_sections)
    caveat = interpretive_sections["confidence_notes"][0]
    answer = " ".join(
        [
            direct_answer,
            " ".join(supporting_evidence[:2]),
            caveat,
        ]
    )
    observations = [direct_answer, *supporting_evidence]
    return {
        "question_intent": intent,
        "direct_answer": direct_answer,
        "supporting_evidence": supporting_evidence,
        "answer_relevant_observations": observations[:5],
        "caveat": caveat,
        "answer": answer,
        **extra,
    }


def _deterministic_result_from_pack(
    question: str,
    pack: dict[str, Any],
) -> InterpretationResult:
    numeric_claims = _numeric_claims_from_pack(pack)
    citations = _citations_from_pack(pack)
    if not pack.get("site_ids") or not numeric_claims:
        return InterpretationResult(
            answer=(
                "The available evidence does not support a confident "
                "interpretation at this time."
            ),
            numeric_claims=[],
            citations=citations,
            evidence_used={"metric_keys": [], "rag_doc_ids": []},
            grounding_status="refused",
            follow_up_questions=[
                "Which chart or wells should I use as evidence?",
                "Can you first generate a chart for the location or wells?",
            ],
            guardrail_flags=["missing_chart_context"],
        )

    selected_claims = _select_relevant_claims(question, numeric_claims)
    interpretive_sections = _build_interpretive_sections(question, pack, selected_claims)
    intent_answer = _build_intent_answer(question, pack, interpretive_sections)
    guardrail_flags: list[str] = []
    if _is_causal_question(question):
        guardrail_flags.append("causation_not_supported")

    return InterpretationResult(
        answer=intent_answer["answer"],
        numeric_claims=selected_claims,
        citations=citations,
        evidence_used={
            "metric_keys": sorted(
                {claim.source for claim in selected_claims} | {"cross_well", "chart_explainability"}
            ),
            "rag_doc_ids": [
                snippet.get("doc_id") for snippet in pack.get("rag_snippets", []) if snippet
            ],
            "site_ids": pack.get("site_ids", []),
            **intent_answer,
        },
        grounding_status="grounded",
        follow_up_questions=(
            _followups_from_hydro_context(pack)
            or pack.get("explainability", {}).get(
                "suggested_questions",
                [
                    "Which highlighted well is changing fastest?",
                    "What outside data would help test a possible cause?",
                ],
            )
        )[:4],
        guardrail_flags=guardrail_flags,
    )


def _reconcile_llm_numeric_claims(
    llm_claims: list[NumericClaim],
    pack: dict[str, Any],
    tolerance: float = 0.1,
) -> tuple[list[NumericClaim], list[str]]:
    """Cross-check LLM numeric claims against the deterministic EvidencePack.

    Replaces any value that disagrees with the deterministic metric by more
    than ``tolerance`` with the deterministic value and records a guardrail flag.
    Drops claims whose ``source`` has no deterministic counterpart.
    """
    cross_well = pack.get("cross_well", {}) or {}
    truth: dict[tuple[str, str], float] = {}
    for metric in cross_well.get("per_site_metrics", []) or []:
        name = str(metric.get("name", "")).strip()
        if not name:
            continue
        truth[(name, "annual_change_ft_yr")] = float(metric.get("annual_change_ft_yr", 0.0))
        truth[(name, "net_change_ft")] = float(metric.get("net_change_ft", 0.0))
    cohort_mean = cross_well.get("mean_annual_change_ft_yr")
    if cohort_mean is not None:
        truth[("cohort", "mean_annual_change_ft_yr")] = float(cohort_mean)

    reconciled: list[NumericClaim] = []
    flags: list[str] = []
    for claim in llm_claims:
        key = (str(claim.site).strip(), str(claim.source).strip())
        anchor = truth.get(key)
        if anchor is None:
            flags.append(f"llm_claim_unknown_source:{claim.source}")
            continue
        if abs(float(claim.value) - anchor) > tolerance:
            flags.append(f"llm_claim_value_mismatch:{claim.site}:{claim.source}")
            reconciled.append(
                NumericClaim(
                    site=claim.site,
                    value=anchor,
                    unit=claim.unit,
                    source=claim.source,
                )
            )
        else:
            reconciled.append(claim)
    return reconciled, flags


def _coerce_structured_response(raw: Any) -> InterpretationResult:
    if isinstance(raw, InterpretationResult):
        return raw
    if hasattr(raw, "dict"):
        raw = raw.dict()
    elif hasattr(raw, "content") and isinstance(raw.content, dict):
        raw = raw.content
    if isinstance(raw, dict):
        return InterpretationResult(**raw)
    raise ValueError("LLM did not return an InterpretationResult")


def _invoke_structured_llm(question: str, pack: dict[str, Any]) -> InterpretationResult | None:
    providers = []
    if os.getenv("DASHSCOPE_API_KEY"):
        providers.append(("qwen", os.getenv("GROUNDWATERGPT_INTERPRETER_MODEL", "qwen-plus")))
    providers.append(("ollama", os.getenv("SYNTHESIS_MODEL", "llama3.2")))

    for provider_name, model in providers:
        try:
            from src.agent.llm_factory import LLMProvider, get_llm

            provider = LLMProvider(provider_name)
            llm = get_llm(provider=provider, model=model, temperature=0)
            if hasattr(llm, "with_structured_output"):
                structured_llm = llm.with_structured_output(InterpretationResult)
                raw = structured_llm.invoke(
                    [
                        ("system", INTERPRETER_PROMPT_HEAD),
                        (
                            "human",
                            (
                                f"Question: {question}\n\n"
                                f"EvidencePack:\n{pack}\n\n"
                                "Return a grounded InterpretationResult."
                            ),
                        ),
                    ]
                )
                return _coerce_structured_response(raw)
        except Exception as exc:
            logger.debug("Chart interpreter %s path unavailable: %s", provider_name, exc)
            continue
    return None


def _claim_citations_from_result(
    result: InterpretationResult,
    pack: dict[str, Any],
) -> list[dict[str, Any]]:
    citations = result.citations or _citations_from_pack(pack)
    primary_citation = citations[0] if citations else {}
    claims = [
        {
            "claim_id": "claim_001",
            "claim": result.answer,
            "claim_type": "chart_interpretation",
            "confidence": 0.72 if result.grounding_status == "grounded" else 0.45,
            "citations": citations[:5],
        }
    ]
    for idx, claim in enumerate(result.numeric_claims[:8], start=2):
        site_id = None
        for site in pack.get("sites", []):
            if site.get("name") == claim.site:
                site_id = site.get("site_id")
                break
        citation = (
            {
                "url": _usgs_site_url(str(site_id)),
                "trust_level": "verified",
                "verified": True,
            }
            if site_id
            else primary_citation
        )
        claims.append(
            {
                "claim_id": f"claim_{idx:03d}",
                "claim": f"{claim.site} {claim.source}: {claim.value:+.3f} {claim.unit}.",
                "claim_type": "chart_numeric",
                "confidence": 0.85,
                "citations": [citation] if citation else [],
            }
        )
    return claims


def interpret_with_context(
    question: str,
    chart_context: dict | None,
    turn_history: list[dict] | None,
    audience: str | None = None,
    allow_llm_synthesis: bool = True,
) -> dict[str, Any]:
    """Interpret a chart-bound follow-up using deterministic evidence and optional LLM."""
    del audience  # The 5.4 prompt is deliberately tone-neutral.
    clean_question = str(question or "").strip()
    trimmed_history = list(turn_history or [])[-4:]
    pack = build_evidence_pack(clean_question, chart_context, trimmed_history)

    try:
        llm_result = _invoke_structured_llm(clean_question, pack) if allow_llm_synthesis else None
    except Exception as exc:
        logger.debug("Chart interpreter structured LLM failed: %s", exc)
        llm_result = None
    if llm_result is not None:
        reconciled_claims, reconciliation_flags = _reconcile_llm_numeric_claims(
            llm_result.numeric_claims, pack
        )
        llm_result.numeric_claims = reconciled_claims
        if reconciliation_flags:
            llm_result.guardrail_flags = list(llm_result.guardrail_flags) + reconciliation_flags
        if not llm_result.answer.strip():
            llm_result = None
    result = llm_result or _deterministic_result_from_pack(clean_question, pack)

    claim_citations = _claim_citations_from_result(result, pack)
    claim_verdicts = _build_claim_verdicts(claim_citations)
    section_confidence = _build_section_confidence_from_claims(claim_citations)
    citation_integrity = _build_citation_integrity(claim_citations, section_confidence)
    numeric_claims = [claim.model_dump() for claim in result.numeric_claims]
    citations = result.citations or _citations_from_pack(pack)
    hydro_concepts = _hydro_concepts_from_pack(pack)
    hydro_caveats = _hydro_caveats_from_pack(pack)
    rag_doc_ids = [snippet.get("doc_id") for snippet in pack.get("rag_snippets", []) if snippet]
    selected_claims = result.numeric_claims or _select_relevant_claims(
        clean_question,
        _numeric_claims_from_pack(pack),
    )
    interpretive_sections = _build_interpretive_sections(clean_question, pack, selected_claims)
    intent_payload = _build_intent_answer(clean_question, pack, interpretive_sections)
    intent_fields = {key: value for key, value in intent_payload.items() if key != "answer"}
    interpretation_response = {
        "schema_version": "interpretation_response_v1",
        "question": clean_question,
        "audience": "general",
        "interpretation": result.answer,
        "answer": result.answer,
        "numeric_claims": numeric_claims,
        "citations": citations,
        "evidence": citations,
        "evidence_used": {
            **(result.evidence_used or {}),
            "rag_doc_ids": (result.evidence_used or {}).get("rag_doc_ids") or rag_doc_ids,
            "enriched_rag_query": pack.get("enriched_rag_query"),
        },
        "grounding_status": {
            "uses_chart_context": bool(pack.get("site_ids")),
            "uses_usgs_data": bool(pack.get("site_ids")),
            "invented_measurements_allowed": False,
            "interpreter_status": result.grounding_status,
            "has_llm_synthesis": llm_result is not None,
            "citation_integrity_passed": citation_integrity.get("passed", False),
        },
        "guardrail_flags": result.guardrail_flags,
        "follow_up_questions": result.follow_up_questions[:4],
        "groundwater_concepts": hydro_concepts,
        **interpretive_sections,
        **intent_fields,
        "chart_context": {
            "summary": pack.get("explainability", {}).get("summary"),
            "how_to_read": pack.get("explainability", {}).get("how_to_read", []),
            "data_contract": pack.get("explainability", {}).get("data_contract", []),
            "llm_role": pack.get("explainability", {}).get("llm_role"),
        },
        "key_observations": pack.get("insights", [])[:6],
        "data_references": [
            {
                "site_id": well.get("site_id"),
                "well_name": well.get("name"),
                "aquifer": well.get("aquifer"),
                "county": well.get("county"),
                "source": "USGS NWIS",
                "url": _usgs_site_url(str(well.get("site_id"))),
            }
            for well in pack.get("wells", [])[:8]
        ],
        "limits": [
            "This is a chart-bound interpretation of observed monitoring records.",
            "The available record does not show causation by itself.",
            "Causal attribution requires external covariates and modeling evidence.",
            *hydro_caveats,
        ],
    }
    return {
        "response": result.answer,
        "context": "Chart-context interpretation",
        "sources": [citation.get("url") for citation in citations if citation.get("url")],
        "mode": "chart_interpreter",
        "status": "ok",
        "wells": pack.get("wells", []),
        "claim_citations": claim_citations,
        "claim_verdicts": claim_verdicts,
        "claim_verdict_summary": _build_claim_verdict_summary(claim_verdicts),
        "citation_summary": _build_citation_summary(claim_citations),
        "section_confidence": section_confidence,
        "citation_integrity": citation_integrity,
        "hallucination_guardrail": {
            "strategy": "chart_context_interpreter",
            "removed_uncited_factual_sentences": 0,
            "all_factual_claims_cited": bool(claim_citations),
            "has_llm_synthesis": llm_result is not None,
            "guardrail_flags": result.guardrail_flags,
        },
        "interpretation_response": interpretation_response,
        "numeric_claims": numeric_claims,
        "chart_context_used": chart_context or {},
        "turn_history_used": trimmed_history,
    }
