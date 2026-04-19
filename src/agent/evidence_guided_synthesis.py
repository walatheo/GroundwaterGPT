"""Shared helpers for evidence-guided structured synthesis."""

from __future__ import annotations

import json
import re
from typing import Any

CLAIM_REF_RE = re.compile(r"\[claim_\d{3}(?:[;\],\s][^\]]*)?\]")


def clean_structured_text(value: Any, *, max_len: int = 400) -> str:
    """Trim and cap free-text values emitted in structured responses."""
    text = str(value or "").strip()
    return text[:max_len].strip()


def dedupe_string_list(
    values: Any,
    *,
    valid_values: set[str] | None = None,
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


def safe_confidence(value: Any, *, default: float = 0.5) -> float:
    """Coerce confidence-like values to a bounded float."""
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


def build_evidence_items(claim_citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a compact evidence registry for structured synthesis."""
    evidence_items: list[dict[str, Any]] = []
    for claim in claim_citations:
        claim_id = str(claim.get("claim_id", "claim_unknown"))
        for idx, citation in enumerate(claim.get("citations", []), start=1):
            evidence_id = str(
                citation.get("evidence_id") or f"evidence_{claim_id[-3:]}_source_{idx}"
            )
            evidence_items.append(
                {
                    "evidence_id": evidence_id,
                    "claim_id": claim_id,
                    "url": citation.get("url") or citation.get("source") or "unknown",
                    "trust_level": citation.get("trust_level", "unknown"),
                    "verified": bool(citation.get("verified", False)),
                }
            )
    return evidence_items


def heuristic_structured_response(
    question: str,
    claim_citations: list[dict[str, Any]],
    claim_verdicts: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a structured response without an LLM or when JSON parsing fails."""
    evidence_items = evidence_items or build_evidence_items(claim_citations)
    verdict_by_claim = {
        str(verdict.get("claim_id", "")): str(verdict.get("verdict", "insufficient_evidence"))
        for verdict in claim_verdicts
    }
    evidence_by_claim: dict[str, list[str]] = {}
    for item in evidence_items:
        evidence_by_claim.setdefault(str(item["claim_id"]), []).append(str(item["evidence_id"]))

    claims = []
    for claim in claim_citations[:6]:
        claim_id = str(claim.get("claim_id", "claim_unknown"))
        evidence_ids = evidence_by_claim.get(claim_id, [])
        claims.append(
            {
                "claim": str(claim.get("claim", "")),
                "claim_type": str(claim.get("claim_type", "retrieved_insight")),
                "claim_ids": [claim_id],
                "evidence_ids": evidence_ids,
                "confidence": float(claim.get("confidence", 0.5)),
                "is_interpretive": False,
                "uncertainty": (
                    "Evidence is limited for this claim."
                    if not evidence_ids or verdict_by_claim.get(claim_id) == "insufficient_evidence"
                    else ""
                ),
            }
        )

    answer_claims = [claim["claim"] for claim in claims[:2] if claim.get("claim")]
    return {
        "schema_version": "evidence_response_v1",
        "question": question,
        "answer": " ".join(answer_claims)
        or "The available verified evidence was insufficient for a detailed answer.",
        "claims": claims,
        "limitations": [
            "This response is constrained to verified retrieved evidence and local data artifacts.",
        ],
        "recommended_followup": [
            "Compare the answer against deterministic site metrics when the question references monitored wells.",  # noqa: E501
        ],
        "evidence": evidence_items,
    }


def parse_structured_response(
    raw_response: str,
    *,
    question: str,
    claim_citations: list[dict[str, Any]],
    claim_verdicts: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Parse and validate the LLM's evidence-ID JSON response."""
    evidence_items = evidence_items or build_evidence_items(claim_citations)
    text = raw_response.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("structured response is not a JSON object")

    valid_claim_ids = {str(claim.get("claim_id")) for claim in claim_citations}
    valid_evidence_ids = {str(item.get("evidence_id")) for item in evidence_items}
    sanitized_claims: list[dict[str, Any]] = []
    for item in parsed.get("claims", []):
        if not isinstance(item, dict):
            continue
        claim_text = clean_structured_text(item.get("claim", ""), max_len=500)
        claim_ids = dedupe_string_list(item.get("claim_ids", []), valid_values=valid_claim_ids)
        evidence_ids = dedupe_string_list(
            item.get("evidence_ids", []),
            valid_values=valid_evidence_ids,
        )
        if not claim_ids or not evidence_ids or not claim_text:
            continue
        sanitized_claims.append(
            {
                "claim": claim_text,
                "claim_type": clean_structured_text(
                    item.get("claim_type", "interpretation"), max_len=64
                )
                or "interpretation",
                "claim_ids": claim_ids,
                "evidence_ids": evidence_ids,
                "confidence": safe_confidence(item.get("confidence", 0.5)),
                "is_interpretive": bool(item.get("is_interpretive", False)),
                "uncertainty": clean_structured_text(item.get("uncertainty", "")),
            }
        )

    if not sanitized_claims:
        return heuristic_structured_response(
            question,
            claim_citations,
            claim_verdicts,
            evidence_items,
        )

    return {
        "schema_version": "evidence_response_v1",
        "question": question,
        "answer": clean_structured_text(parsed.get("answer", ""), max_len=700),
        "claims": sanitized_claims,
        "limitations": [
            clean_structured_text(item)
            for item in parsed.get("limitations", [])
            if clean_structured_text(item)
        ],
        "recommended_followup": [
            clean_structured_text(item)
            for item in parsed.get("recommended_followup", [])
            if clean_structured_text(item)
        ],
        "evidence": evidence_items,
    }


def render_structured_report(structured: dict[str, Any]) -> str:
    """Render evidence-structured synthesis as citation-safe markdown."""
    claims = structured.get("claims", [])
    answer = str(structured.get("answer", "")).strip()
    if answer and claims and not CLAIM_REF_RE.search(answer):
        first_claim_ids = claims[0].get("claim_ids", [])
        if first_claim_ids:
            answer = f"{answer} [{first_claim_ids[0]}]"
    lines = [answer]
    if claims:
        lines.append("\n## Evidence-Linked Claims")
        for item in claims:
            claim_ids = ", ".join(item.get("claim_ids", []))
            evidence_ids = ", ".join(item.get("evidence_ids", []))
            uncertainty = str(item.get("uncertainty", "")).strip()
            suffix = f" Uncertainty: {uncertainty}" if uncertainty else ""
            lines.append(
                f"- {item.get('claim', '')} [{claim_ids}; evidence: {evidence_ids}]{suffix}"
            )

    limitations = structured.get("limitations", [])
    if limitations:
        lines.append("\n## Limitations")
        lines.extend(f"- {item}" for item in limitations)

    followup = structured.get("recommended_followup", [])
    if followup:
        lines.append("\n## Recommended Follow-Up")
        lines.extend(f"- {item}" for item in followup)

    return "\n".join(line for line in lines if str(line).strip())
