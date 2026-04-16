"""Grounded chart-context interpreter for conversational follow-ups."""

from __future__ import annotations

import logging
import os
import re
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
)
from api.site_metadata import SITE_METADATA

logger = logging.getLogger(__name__)

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
    if os.getenv("GROUNDWATERGPT_ENABLE_INTERPRETER_RAG", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return []
    try:
        from src.agent.knowledge import search_knowledge

        docs = search_knowledge(question, k=5, score_threshold=0.5)
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
            "rag_snippets": _rag_snippets(question),
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
                "county": site.get("county"),
            }
            for site in sites
        ],
        "site_ids": [site["site_id"] for site in sites],
        "wells": wells,
        "cross_well": cross_well,
        "insights": insights,
        "explainability": explainability,
        "rag_snippets": _rag_snippets(question),
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
                    "verified": snippet.get("trust_level") in {"verified", "primary"},
                }
            )
    return citations


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
    cross_well = pack.get("cross_well", {})
    insights = pack.get("insights", []) or []
    lead = (
        pack.get("explainability", {}).get("summary")
        or f"This chart contains {len(pack.get('site_ids', []))} USGS wells."
    )
    claim_text = "; ".join(
        f"{claim.site}: {claim.value:+.3f} {claim.unit}"
        for claim in selected_claims
        if claim.unit == "ft/yr"
    )
    if not claim_text and selected_claims:
        claim_text = "; ".join(
            f"{claim.site}: {claim.value:+.2f} {claim.unit}" for claim in selected_claims
        )
    answer_parts = [lead]
    site_ids = pack.get("site_ids", [])
    if site_ids:
        answer_parts.append(f"Context site IDs include {', '.join(site_ids[:3])}.")
    if claim_text:
        answer_parts.append(f"Key deterministic rates are {claim_text}.")
    if insights:
        answer_parts.append(str(insights[0]))
    guardrail_flags: list[str] = []
    if _is_causal_question(question):
        answer_parts.append(
            "The available record does not prove a cause; attribution would require "
            "pumping, rainfall, recharge, and groundwater-flow model evidence."
        )
        guardrail_flags.append("causation_not_supported")
    elif cross_well.get("risk_level"):
        answer_parts.append(
            f"Screening risk is {str(cross_well['risk_level']).lower()}, not a forecast."
        )

    return InterpretationResult(
        answer=" ".join(answer_parts),
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
        },
        grounding_status="grounded",
        follow_up_questions=pack.get("explainability", {}).get(
            "suggested_questions",
            [
                "Which highlighted well is changing fastest?",
                "What outside data would help test a possible cause?",
            ],
        )[:4],
        guardrail_flags=guardrail_flags,
    )


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
    result = llm_result or _deterministic_result_from_pack(clean_question, pack)
    if result.grounding_status != "refused":
        result = (
            _deterministic_result_from_pack(clean_question, pack) if not result.answer else result
        )

    claim_citations = _claim_citations_from_result(result, pack)
    claim_verdicts = _build_claim_verdicts(claim_citations)
    section_confidence = _build_section_confidence_from_claims(claim_citations)
    citation_integrity = _build_citation_integrity(claim_citations, section_confidence)
    numeric_claims = [claim.model_dump() for claim in result.numeric_claims]
    citations = result.citations or _citations_from_pack(pack)
    interpretation_response = {
        "schema_version": "interpretation_response_v1",
        "question": clean_question,
        "audience": "general",
        "interpretation": result.answer,
        "answer": result.answer,
        "numeric_claims": numeric_claims,
        "citations": citations,
        "evidence": citations,
        "evidence_used": result.evidence_used,
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
            "Causal attribution requires external covariates and modeling evidence.",
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
