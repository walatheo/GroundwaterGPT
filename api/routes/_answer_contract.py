"""Canonical answer contract for all chat surfaces.

Phase 0 of the grounded-chat refactor fixes a single product-level vocabulary:

- ``answer_type`` — what the reply is, from the user's perspective.
- ``route_mode`` — how we selected this reply (coarse intent).
- ``grounding_status`` — how strongly the reply is tied to deterministic evidence.

Every chat response (``/api/chat``, ``/api/interpret``, ``/api/research``) is
expected to carry these three top-level fields after ``_augment_chat_payload``
runs. Call sites should read from here, not hard-code strings, so future
tightening flows through one module.

The existing envelope is not restructured in Phase 0 — this module *derives*
the triad from the payload that ``_build_chat_payload`` / interpreter already
produces, and stamps it on the envelope. Phases 1 and 2 will make the triad
the source-of-truth instead of a derived view.
"""

from __future__ import annotations

from typing import Any, Optional

# ---------------------------------------------------------------------------
# Enum values — strings, so they serialize unchanged into JSON responses.
# ---------------------------------------------------------------------------


class AnswerType:
    """What the reply *is*, from the user's perspective."""

    DATA_ANSWER = "data_answer"
    INTERPRETATION_ANSWER = "interpretation_answer"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

    ALL = frozenset({DATA_ANSWER, INTERPRETATION_ANSWER, INSUFFICIENT_EVIDENCE})


class RouteMode:
    """How the backend selected this reply (coarse intent)."""

    EXACT_WELL = "exact_well"
    COHORT = "cohort"
    CHART_FOLLOWUP = "chart_followup"
    INTERPRETATION = "interpretation"
    NETWORK = "network"
    RESEARCH = "research"
    UNSUPPORTED = "unsupported"
    FALLBACK = "fallback"

    ALL = frozenset(
        {
            EXACT_WELL,
            COHORT,
            CHART_FOLLOWUP,
            INTERPRETATION,
            NETWORK,
            RESEARCH,
            UNSUPPORTED,
            FALLBACK,
        }
    )


class GroundingStatus:
    """How tightly the reply is bound to deterministic evidence."""

    GROUNDED = "grounded"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    REFUSED = "refused"

    ALL = frozenset({GROUNDED, PARTIAL, INSUFFICIENT, REFUSED})


# ---------------------------------------------------------------------------
# Mapping between existing internal ``mode`` tags and canonical ``route_mode``.
# Keep this table tight — every new internal mode must land here or the stamp
# falls back to ``FALLBACK`` and ``derive_answer_type`` will notice.
# ---------------------------------------------------------------------------

_ROUTE_MODE_BY_INTERNAL: dict[str, str] = {
    "site_fallback": RouteMode.EXACT_WELL,
    "site_lookup": RouteMode.EXACT_WELL,
    "aquifer_fallback": RouteMode.COHORT,
    "location_fallback": RouteMode.COHORT,
    "multi_location_fallback": RouteMode.COHORT,
    "network_fallback": RouteMode.NETWORK,
    "chart_interpreter": RouteMode.CHART_FOLLOWUP,
    "chart_followup": RouteMode.CHART_FOLLOWUP,
    "interpret": RouteMode.INTERPRETATION,
    "interpretation": RouteMode.INTERPRETATION,
    "deep_research": RouteMode.RESEARCH,
    "research": RouteMode.RESEARCH,
    "research_agent": RouteMode.RESEARCH,
    "research_chat": RouteMode.RESEARCH,
    "fallback": RouteMode.FALLBACK,
    "kb_fallback": RouteMode.FALLBACK,
    "chat": RouteMode.FALLBACK,
}


def canonical_route_mode(internal_mode: Optional[str]) -> str:
    """Map the existing ``payload['mode']`` tag to a canonical ``RouteMode``.

    Anything that starts with ``interpret_`` (produced by ``/api/interpret``)
    collapses to ``INTERPRETATION`` regardless of the wrapped inner mode —
    the user asked for interpretation, that is the product-level intent.
    """
    if not internal_mode:
        return RouteMode.FALLBACK
    tag = str(internal_mode).strip().lower()
    if tag.startswith("interpret_") or tag == "interpret":
        return RouteMode.INTERPRETATION
    return _ROUTE_MODE_BY_INTERNAL.get(tag, RouteMode.FALLBACK)


# ---------------------------------------------------------------------------
# Derivation — read the existing payload and produce the triad.
# ---------------------------------------------------------------------------


def _has_deterministic_evidence(payload: dict[str, Any]) -> bool:
    """True when the reply is backed by at least one grounded evidence source."""
    if payload.get("chart"):
        return True
    if payload.get("wells"):
        return True
    if payload.get("claim_citations"):
        return True
    details = payload.get("interpretation_details") or {}
    if details.get("supply_interpretation") or details.get("meaning_brief"):
        return True
    interp = payload.get("interpretation_response") or {}
    if interp.get("data_references") or interp.get("evidence"):
        return True
    return False


def _has_interpretive_content(payload: dict[str, Any]) -> bool:
    """True when the reply includes narrative interpretation, not just metrics."""
    if payload.get("llm_synthesis"):
        return True
    if payload.get("interpretation_response"):
        return True
    details = payload.get("interpretation_details") or {}
    if details.get("meaning_brief") or details.get("supply_interpretation"):
        return True
    return False


def derive_answer_type(payload: dict[str, Any]) -> str:
    """Pick the canonical ``AnswerType`` from the existing envelope.

    Rules (product-level, not implementation-coupled):

    - No deterministic evidence at all → ``INSUFFICIENT_EVIDENCE``.
    - Evidence present but interpretive narrative is included → ``INTERPRETATION_ANSWER``.
    - Evidence present and reply is deterministic metrics only → ``DATA_ANSWER``.
    """
    if not _has_deterministic_evidence(payload):
        return AnswerType.INSUFFICIENT_EVIDENCE
    if _has_interpretive_content(payload):
        return AnswerType.INTERPRETATION_ANSWER
    return AnswerType.DATA_ANSWER


def derive_grounding_status(payload: dict[str, Any]) -> str:
    """Normalize the many existing grounding signals to a single enum string.

    Precedence:

    1. If the interpreter already produced an explicit string
       (``interpretation_response.grounding_status`` as ``"grounded" | "partial" | "refused"``
       or a dict carrying those flags), prefer it.
    2. Otherwise derive from envelope: no evidence → ``INSUFFICIENT``;
       citation integrity passed → ``GROUNDED``;
       evidence present but no integrity signal → ``PARTIAL``.
    """
    interp = payload.get("interpretation_response") or {}
    raw_status = interp.get("grounding_status")
    if isinstance(raw_status, str):
        status = raw_status.strip().lower()
        if status in GroundingStatus.ALL:
            return status

    integrity = payload.get("citation_integrity") or {}
    if integrity.get("passed") is True:
        return GroundingStatus.GROUNDED

    if not _has_deterministic_evidence(payload):
        return GroundingStatus.INSUFFICIENT

    # We have some evidence but no integrity gate — honest answer is "partial".
    return GroundingStatus.PARTIAL


def stamp_contract_fields(
    payload: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Attach ``answer_type``, ``route_mode`` and top-level ``grounding_status``.

    Idempotent by default: if fields are already present and valid, they're
    left alone. Pass ``force=True`` to recompute — useful when upstream code
    rewrites ``payload['mode']`` after a previous stamp (e.g. ``/api/interpret``
    wrapping a chat result).
    """
    if force or payload.get("answer_type") not in AnswerType.ALL:
        payload["answer_type"] = derive_answer_type(payload)

    if force or payload.get("route_mode") not in RouteMode.ALL:
        # Prefer the RouteDecision's canonical value when the resolver already
        # stamped it on the payload — its answer is more specific than the
        # internal-mode mapping (e.g. multi-location comparison uses the
        # "network_fallback" internal tag but should be COHORT).
        decision = payload.get("route_decision") or {}
        decision_mode = decision.get("route_mode") if isinstance(decision, dict) else None
        if decision_mode in RouteMode.ALL:
            payload["route_mode"] = decision_mode
        else:
            payload["route_mode"] = canonical_route_mode(payload.get("mode"))

    # ``grounding_status`` lives in two places in the existing envelope:
    # - inside ``interpretation_response`` as a rich dict of booleans (kept as-is).
    # - newly added here, top-level, as a single string enum.
    if force or payload.get("grounding_status") not in GroundingStatus.ALL:
        payload["grounding_status"] = derive_grounding_status(payload)

    return payload


__all__ = [
    "AnswerType",
    "GroundingStatus",
    "RouteMode",
    "canonical_route_mode",
    "derive_answer_type",
    "derive_grounding_status",
    "stamp_contract_fields",
]
