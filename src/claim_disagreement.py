"""Claim disagreement engine for adversarial evidence checks.

This module performs lightweight, deterministic claim verification to flag
possible internal disagreements in a research response.
"""

from __future__ import annotations

import re
from typing import Any

SITE_ID_RE = re.compile(r"\b\d{15}\b")
WELL_NAME_RE = re.compile(r"\b(?:HE|G|C|L|S)[\s-]?\d{3,5}[A-Z]?\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"\b[a-z][a-z0-9_-]{2,}\b", re.IGNORECASE)

UPWARD_TERMS = (
    "rising",
    "increase",
    "increasing",
    "improve",
    "higher",
    "upward",
    "gain",
)
DOWNWARD_TERMS = (
    "falling",
    "decline",
    "declining",
    "decrease",
    "decreasing",
    "lower",
    "downward",
    "drop",
    "drawdown",
)
TREND_TERMS = set(UPWARD_TERMS) | set(DOWNWARD_TERMS)
SUBJECT_TERMS = {
    "aquifer",
    "biscayne",
    "floridan",
    "tamiami",
    "hawthorn",
    "estero",
    "groundwater",
    "saltwater",
    "intrusion",
    "waterlevel",
    "water",
    "level",
    "trend",
}
STOP_WORDS = {
    "about",
    "after",
    "again",
    "against",
    "below",
    "between",
    "claim",
    "confidence",
    "could",
    "during",
    "from",
    "have",
    "includes",
    "include",
    "into",
    "more",
    "over",
    "records",
    "record",
    "shows",
    "show",
    "this",
    "that",
    "their",
    "there",
    "these",
    "those",
    "under",
    "using",
    "with",
    "without",
    "years",
    "year",
}
VALID_VERDICTS = {"supported", "contradicted", "insufficient_evidence"}


def clamp_confidence(value: Any) -> float:
    """Clamp confidence values to a bounded float in [0.0, 1.0]."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return round(max(0.0, min(1.0, numeric)), 3)


def _safe_citations(raw_citations: Any) -> list[dict[str, Any]]:
    """Normalize citations to a list of dictionaries."""
    if not isinstance(raw_citations, list):
        return []
    return [item for item in raw_citations if isinstance(item, dict)]


def _trend_polarity(text: str) -> int:
    """Return trend polarity (-1, 0, +1) inferred from claim text."""
    lowered = text.lower()
    up_hits = sum(1 for term in UPWARD_TERMS if term in lowered)
    down_hits = sum(1 for term in DOWNWARD_TERMS if term in lowered)
    if up_hits > down_hits:
        return 1
    if down_hits > up_hits:
        return -1
    return 0


def _subject_tokens(text: str) -> set[str]:
    """Extract coarse subject tokens used for overlap tests."""
    tokens = set()
    normalized = text.lower().replace("water level", "waterlevel")
    for token in TOKEN_RE.findall(normalized):
        if token in STOP_WORDS or token in TREND_TERMS:
            continue
        if len(token) < 4 and token not in SUBJECT_TERMS:
            continue
        tokens.add(token)
    return tokens


def _well_names(text: str) -> set[str]:
    """Extract normalized local well identifiers such as G-3336 or L-5667."""
    names = set()
    for match in WELL_NAME_RE.findall(text):
        names.add(re.sub(r"[\s-]+", "", match).upper())
    return names


def _citation_for_view(citation: dict[str, Any]) -> dict[str, Any]:
    """Normalize citation fields for claim verdict outputs."""
    return {
        "url": str(citation.get("url", "")).strip(),
        "verified": bool(citation.get("verified", False)),
        "trust_level": str(citation.get("trust_level", "unknown")).lower(),
    }


def summarize_claim_verdicts(claim_verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    """Build aggregate summary metrics from claim verdict records."""
    total = len(claim_verdicts)
    supported = 0
    contradicted = 0
    insufficient = 0
    high_risk_claim_ids: list[str] = []

    for verdict in claim_verdicts:
        verdict_label = str(verdict.get("verdict", "")).strip().lower()
        claim_id = str(verdict.get("claim_id", ""))
        try:
            risk_score = float(verdict.get("risk_score", 0.0))
        except (TypeError, ValueError):
            risk_score = 0.0

        if verdict_label == "supported":
            supported += 1
        elif verdict_label == "contradicted":
            contradicted += 1
        elif verdict_label == "insufficient_evidence":
            insufficient += 1

        if risk_score >= 0.75 and claim_id:
            high_risk_claim_ids.append(claim_id)

    contradicted_rate = float(contradicted / total) if total else 0.0
    high_risk_rate = float(len(high_risk_claim_ids) / total) if total else 0.0
    return {
        "total_claims": total,
        "supported_claims": supported,
        "contradicted_claims": contradicted,
        "insufficient_evidence_claims": insufficient,
        "contradicted_claim_rate": round(contradicted_rate, 3),
        "high_risk_claim_ids": high_risk_claim_ids,
        "high_risk_claim_rate": round(high_risk_rate, 3),
    }


class ClaimDisagreementEngine:
    """Evaluate claim support status and internal contradictions."""

    def evaluate_claims(self, claim_citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Generate claim verdict metadata for each cited claim."""
        normalized_claims = []
        for index, claim in enumerate(claim_citations, start=1):
            claim_id = str(claim.get("claim_id", f"claim_{index:03d}"))
            claim_text = str(claim.get("claim", "")).strip()
            normalized_claims.append(
                {
                    "claim_id": claim_id,
                    "claim": claim_text,
                    "confidence": clamp_confidence(claim.get("confidence", 0.0)),
                    "citations": _safe_citations(claim.get("citations")),
                    "site_ids": set(SITE_ID_RE.findall(claim_text)),
                    "well_names": _well_names(claim_text),
                    "trend": _trend_polarity(claim_text),
                    "subject_tokens": _subject_tokens(claim_text),
                }
            )

        verdicts: list[dict[str, Any]] = []
        for index, claim in enumerate(normalized_claims):
            counter_claims = self._find_counter_claims(index, normalized_claims)
            verdict = self._choose_verdict(claim, counter_claims)
            risk_score = self._risk_score(claim, verdict, counter_claims)

            evidence_for = [_citation_for_view(c) for c in claim["citations"][:3]]
            counter_evidence = [
                {
                    "claim_id": counter["claim_id"],
                    "claim": counter["claim"][:200],
                    "citations": [_citation_for_view(c) for c in counter["citations"][:2]],
                }
                for counter in counter_claims[:3]
            ]

            verdicts.append(
                {
                    "claim_id": claim["claim_id"],
                    "claim": claim["claim"],
                    "verdict": verdict,
                    "risk_score": risk_score,
                    "confidence": round(claim["confidence"], 3),
                    "evidence_for": evidence_for,
                    "counter_evidence": counter_evidence,
                    "rationale": self._rationale_text(verdict, counter_claims),
                }
            )

        return verdicts

    def _find_counter_claims(
        self, claim_index: int, claims: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Find claims that appear to contradict the target claim."""
        target = claims[claim_index]
        counters: list[dict[str, Any]] = []
        if target["trend"] == 0:
            return counters

        for index, candidate in enumerate(claims):
            if index == claim_index or candidate["trend"] == 0:
                continue
            if target["trend"] + candidate["trend"] != 0:
                continue
            if self._shares_subject(target, candidate):
                counters.append(candidate)
        return counters

    def _shares_subject(self, a: dict[str, Any], b: dict[str, Any]) -> bool:
        """Check whether two claims likely describe the same subject."""
        site_ids_a = a["site_ids"]
        site_ids_b = b["site_ids"]
        if site_ids_a or site_ids_b:
            return bool(site_ids_a & site_ids_b)

        well_names_a = a["well_names"]
        well_names_b = b["well_names"]
        if well_names_a or well_names_b:
            return bool(well_names_a & well_names_b)

        overlap = a["subject_tokens"] & b["subject_tokens"]
        return len(overlap) >= 2

    def _choose_verdict(
        self,
        claim: dict[str, Any],
        counter_claims: list[dict[str, Any]],
    ) -> str:
        """Assign supported / contradicted / insufficient evidence."""
        if not claim["citations"]:
            return "insufficient_evidence"
        if counter_claims:
            return "contradicted"
        return "supported"

    def _risk_score(
        self,
        claim: dict[str, Any],
        verdict: str,
        counter_claims: list[dict[str, Any]],
    ) -> float:
        """Compute bounded risk score where 1.0 is highest risk."""
        confidence = claim["confidence"]
        citation_count = len(claim["citations"])

        if verdict == "supported":
            score = 0.18 + (1.0 - confidence) * 0.35
            if citation_count <= 1:
                score += 0.08
        elif verdict == "contradicted":
            score = 0.72 + (1.0 - confidence) * 0.2 + min(0.08, len(counter_claims) * 0.03)
        else:
            score = 0.78 + (1.0 - confidence) * 0.18

        return round(max(0.0, min(1.0, score)), 3)

    def _rationale_text(self, verdict: str, counter_claims: list[dict[str, Any]]) -> str:
        """Build concise rationale for each verdict."""
        if verdict == "supported":
            return "Cited evidence is present and no internal counter-claim was detected."
        if verdict == "insufficient_evidence":
            return "No citations were attached to this claim, so support is insufficient."

        counter_ids = ", ".join(counter["claim_id"] for counter in counter_claims[:3])
        return "Detected conflicting trend evidence in related claims" + (
            f" ({counter_ids})." if counter_ids else "."
        )
