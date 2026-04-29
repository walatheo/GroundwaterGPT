"""Phase 2: single grounded-answer composer.

Every chat branch historically produced a bespoke payload shape — site, aquifer,
location, network, chart-followup, research, fallback. Downstream code had to
duck-type through ten fields to figure out "what did we actually tell the user,
and what evidence did we tie it to?"

``compose_grounded_answer`` derives one canonical six-field view from whatever
the branch produced:

- ``direct_answer`` — one-line reply the user sees first.
- ``grounded_findings`` — deterministic bullets backed by the chart / wells /
  claim citations.
- ``limits`` — honest caveats (screening summaries, historical observation,
  LLM-may-explain-not-originate).
- ``next_best_question`` — one follow-up that moves the user forward.
- ``supporting_evidence`` — the wells / sources / URLs the reply leans on.
- ``grounding_status`` — normalized enum string from the Phase 0 contract.

Phase 2 is additive. Each branch still assembles its own envelope; the composer
reads that envelope and attaches ``payload['grounded_answer']``. Phases 3 and 4
will make branches feed this builder as their source of truth instead.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from api.routes._answer_contract import GroundingStatus, derive_grounding_status
from api.routes.answering.followups import clean_sentence, questionize

# Default limits we always want on the record. The chart / wells story is
# observational — these caveats keep the reply honest when the branch forgot
# to supply its own.
_DEFAULT_LIMITS: tuple[str, ...] = (
    "Readings are observed USGS monitoring records, not a groundwater-flow model.",
    "Trend lines are screening summaries over the available record, not forecasts.",
    "The LLM may explain deterministic outputs but must not invent measurements.",
)

_MAX_FINDINGS = 4
_MAX_EVIDENCE = 6


@dataclass
class GroundedAnswer:
    """The canonical answer shape every chat branch converges on."""

    direct_answer: str = ""
    grounded_findings: list[str] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    next_best_question: Optional[str] = None
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    grounding_status: str = GroundingStatus.INSUFFICIENT

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict view for JSON serialization onto the payload."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Field-level derivation helpers — each reads the existing envelope.
# ---------------------------------------------------------------------------


def _first_sentence(text: str) -> str:
    """Return the first sentence of ``text`` as a cleaned single line."""
    if not text:
        return ""
    # Split on paragraph break first, then take the first sentence inside.
    head = text.split("\n\n", 1)[0]
    head = head.split("\n", 1)[0]
    for terminator in (". ", "! ", "? "):
        idx = head.find(terminator)
        if idx != -1:
            return clean_sentence(head[: idx + 1])
    return clean_sentence(head)


def _strip_answer_label(text: Any) -> str:
    """Remove lightweight formatting / labels from answer-brief lines."""
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*[-*]\s*", "", cleaned)
    cleaned = re.sub(r"^\*\*(.+?)\*\*:\s*", "", cleaned)
    cleaned = re.sub(
        r"^(?:plain-language answer|direct answer|answer)\s*:\s*", "", cleaned, flags=re.I
    )
    return cleaned.strip()


def _brief_lines(text: Any) -> list[str]:
    """Return cleaned non-empty lines from an answer brief."""
    lines: list[str] = []
    seen: set[str] = set()
    for raw in str(text or "").splitlines():
        cleaned = _strip_answer_label(raw)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        lines.append(cleaned)
        seen.add(key)
    return lines


def _derive_direct_answer(payload: dict[str, Any]) -> str:
    """Pick the best one-line answer already present in the envelope.

    Preference order walks from "most intentional" (learner brief) to
    "what the user will see anyway" (first line of response).
    """
    interp = payload.get("interpretation_response") or {}
    if interp.get("direct_answer"):
        return clean_sentence(interp["direct_answer"])

    learner_brief = interp.get("learner_brief") or {}
    if learner_brief.get("direct_answer"):
        return clean_sentence(learner_brief["direct_answer"])

    if payload.get("answer_brief"):
        brief_lines = _brief_lines(payload["answer_brief"])
        if brief_lines:
            return _first_sentence(brief_lines[0])

    details = payload.get("interpretation_details") or {}
    meaning_brief = details.get("meaning_brief") or {}
    if meaning_brief.get("headline"):
        return clean_sentence(meaning_brief["headline"])

    if payload.get("llm_synthesis"):
        return _first_sentence(str(payload["llm_synthesis"]))

    if payload.get("response"):
        return _first_sentence(str(payload["response"]))

    return ""


def _derive_grounded_findings(payload: dict[str, Any]) -> list[str]:
    """Pull deterministic bullets: chart insights first, then claim citations."""
    findings: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        text = clean_sentence(str(raw or ""))
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        findings.append(text)
        seen.add(key)

    chart = payload.get("chart") or {}
    for item in chart.get("insights") or []:
        _add(item)
        if len(findings) >= _MAX_FINDINGS:
            return findings

    for claim in payload.get("claim_citations") or []:
        _add(claim.get("claim"))
        if len(findings) >= _MAX_FINDINGS:
            return findings

    for line in _brief_lines(payload.get("answer_brief"))[1:]:
        _add(line)
        if len(findings) >= _MAX_FINDINGS:
            return findings

    # Fallback: meaning_brief headline/plain_language when a branch skipped
    # insights entirely (e.g. site-fallback without an active chart).
    details = payload.get("interpretation_details") or {}
    meaning_brief = details.get("meaning_brief") or {}
    for key in ("plain_language", "why_it_matters"):
        _add(meaning_brief.get(key))
        if len(findings) >= _MAX_FINDINGS:
            return findings

    return findings


def _derive_limits(payload: dict[str, Any]) -> list[str]:
    """Merge branch-declared limits with the standing defaults, deduped."""
    limits: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        text = clean_sentence(str(raw or ""))
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        limits.append(text)
        seen.add(key)

    interp = payload.get("interpretation_response") or {}
    for item in interp.get("limits") or []:
        _add(item)

    details = payload.get("interpretation_details") or {}
    for item in details.get("confidence_notes") or []:
        _add(item)
    supply = details.get("supply_interpretation") or {}
    for item in supply.get("limitations") or []:
        _add(item)

    # Always anchor the reply in the honest defaults. A branch that already
    # named the observational caveat contributes nothing extra; dedupe handles it.
    for item in _DEFAULT_LIMITS:
        _add(item)

    return limits


def _derive_next_best_question(payload: dict[str, Any]) -> Optional[str]:
    """Pick a single follow-up that advances the user's inquiry.

    Prefers the interpretation response's curated follow-up, then the
    top-level progression fields, then the meaning_brief's next-best check.
    """
    interp = payload.get("interpretation_response") or {}
    learner_brief = interp.get("learner_brief") or {}
    if learner_brief.get("next_best_question"):
        return questionize(learner_brief["next_best_question"])

    for key in ("follow_up_questions",):
        for candidate in interp.get(key) or []:
            text = questionize(candidate)
            if text:
                return text

    for candidate in payload.get("follow_up_questions") or []:
        text = questionize(candidate)
        if text:
            return text

    if payload.get("next_goal"):
        return questionize(payload["next_goal"])

    details = payload.get("interpretation_details") or {}
    meaning_brief = details.get("meaning_brief") or {}
    if meaning_brief.get("next_best_check"):
        return questionize(meaning_brief["next_best_check"])

    return None


def _evidence_from_well(well: dict[str, Any]) -> Optional[dict[str, Any]]:
    site_id = well.get("site_id") or well.get("id")
    if not site_id:
        return None
    entry = {
        "kind": "well",
        "site_id": str(site_id),
        "name": well.get("name") or well.get("well_name"),
        "aquifer": well.get("aquifer"),
        "county": well.get("county"),
        "source": "USGS NWIS",
    }
    url = well.get("usgs_url") or well.get("url")
    if url:
        entry["url"] = str(url)
    return entry


def _derive_supporting_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Compile the wells and source URLs the reply actually leans on."""
    evidence: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for well in payload.get("wells") or []:
        if not isinstance(well, dict):
            continue
        entry = _evidence_from_well(well)
        if not entry:
            continue
        key = f"well::{entry['site_id']}"
        if key in seen_keys:
            continue
        evidence.append(entry)
        seen_keys.add(key)
        if len(evidence) >= _MAX_EVIDENCE:
            return evidence

    # The interpretation response's curated evidence list is richer than
    # top-level sources (trust level, verified flag) so prefer it when present.
    interp = payload.get("interpretation_response") or {}
    for item in interp.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        key = f"url::{url}"
        if key in seen_keys:
            continue
        evidence.append(
            {
                "kind": "citation",
                "url": url,
                "trust_level": item.get("trust_level", "unknown"),
                "verified": bool(item.get("verified", False)),
            }
        )
        seen_keys.add(key)
        if len(evidence) >= _MAX_EVIDENCE:
            return evidence

    for src in payload.get("sources") or []:
        url = str(src).strip()
        if not url:
            continue
        key = f"url::{url}"
        if key in seen_keys:
            continue
        evidence.append({"kind": "citation", "url": url})
        seen_keys.add(key)
        if len(evidence) >= _MAX_EVIDENCE:
            return evidence

    return evidence


# ---------------------------------------------------------------------------
# The composer.
# ---------------------------------------------------------------------------


def compose_grounded_answer(
    payload: dict[str, Any],
    *,
    question: Optional[str] = None,
) -> GroundedAnswer:
    """Build the canonical grounded answer from an existing chat envelope.

    ``question`` is accepted for Phase 3/4 symmetry (the collapsed explainer
    will want it); Phase 2 doesn't currently use it, but threading it now
    avoids a signature change when branches start calling this directly.
    """
    del question  # reserved for Phase 3; keeps call sites stable.

    return GroundedAnswer(
        direct_answer=_derive_direct_answer(payload),
        grounded_findings=_derive_grounded_findings(payload),
        limits=_derive_limits(payload),
        next_best_question=_derive_next_best_question(payload),
        supporting_evidence=_derive_supporting_evidence(payload),
        grounding_status=derive_grounding_status(payload),
    )


def attach_grounded_answer(
    payload: dict[str, Any],
    *,
    question: Optional[str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Attach ``payload['grounded_answer']`` in place and return the payload.

    Idempotent by default so branches that pre-populate the key keep their
    value (Phase 3 will use this to let the collapsed explainer be the
    producer instead of the consumer).
    """
    if not force and isinstance(payload.get("grounded_answer"), dict):
        return payload

    payload["grounded_answer"] = compose_grounded_answer(payload, question=question).to_dict()
    return payload


__all__ = [
    "GroundedAnswer",
    "attach_grounded_answer",
    "compose_grounded_answer",
]
