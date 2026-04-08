"""Citation quality, verdict, and guardrail helpers.

Extracted from ``chat.py`` to keep that module focused on endpoint handlers.
All public names are re-exported from ``chat.py`` for backward compatibility.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.claim_disagreement import clamp_confidence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------

MIN_CLAIM_CITATION_COVERAGE = float(os.getenv("GROUNDWATERGPT_MIN_CLAIM_COVERAGE", "0.90"))
MIN_SECTION_CITATION_COVERAGE = float(os.getenv("GROUNDWATERGPT_MIN_SECTION_COVERAGE", "0.90"))

TRUST_LEVEL_RANK: dict[str, int] = {
    "unknown": 0,
    "untrusted": 0,
    "moderate": 1,
    "trusted": 2,
    "verified": 3,
}
RANK_TO_TRUST_LEVEL: dict[int, str] = {
    0: "unknown",
    1: "moderate",
    2: "trusted",
    3: "verified",
}

# ---------------------------------------------------------------------------
# Claim disagreement engine (singleton, imported once)
# ---------------------------------------------------------------------------

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
# Trust / confidence helpers
# ---------------------------------------------------------------------------


def _highest_trust_level(citations: list[dict[str, Any]]) -> str:
    """Select the highest trust level present in claim citations."""
    best_rank = 0
    for citation in citations:
        trust_level = str(citation.get("trust_level", "unknown")).lower()
        best_rank = max(best_rank, TRUST_LEVEL_RANK.get(trust_level, 0))
    return RANK_TO_TRUST_LEVEL.get(best_rank, "unknown")


def _build_section_confidence_from_claims(
    claim_citations: list[dict[str, Any]],
) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# Citation summary + integrity
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Claim verdicts
# ---------------------------------------------------------------------------


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
        "high_risk_claim_rate": (
            round(float(len(high_risk_claim_ids) / total), 3) if total else 0.0
        ),
    }
