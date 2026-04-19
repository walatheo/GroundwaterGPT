"""Phase 4: structured insufficient-evidence / refusal answers.

The geography template echoes the queried place when we can extract it, so
"how is groundwater in Antarctica?" gets a refusal that names Antarctica
(rather than a generic Florida-scope sentence). That keeps the refusal
specific without inventing data — we acknowledge what was asked and why we
can't serve it.

Previously, when a question had no deterministic evidence backing it (no
matched site, no aquifer hit, no chart context) or was out of scope, each
branch improvised a response. Sometimes it was an empty payload with a
``response`` string, sometimes a research-agent fallback that wandered off
into generic hydrogeology, sometimes a chart-less interpretation.

Phase 4 replaces that improvisation with one honest template. Given a
question and a ``RouteDecision``, ``build_insufficient_answer`` returns a
``GroundedAnswer`` with:

- the refusal stated plainly as ``direct_answer``;
- an empty ``grounded_findings`` (there is none — that's the whole point);
- reason-specific ``limits`` so the user knows why;
- a constructive ``next_best_question`` that redirects to something the
  system *can* answer;
- ``grounding_status`` set to ``refused`` for out-of-scope geography and
  future-prediction asks, and ``insufficient`` for "no evidence found" cases.

The Phase-3 explainer is short-circuited for these answers via
``should_short_circuit_explainer`` — there is no narrative to ground, so
invoking the LLM only risks paper-over.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

from api.routes._answer_contract import GroundingStatus, RouteMode
from api.routes._grounded_answer import GroundedAnswer
from api.routes._route_decision import RouteDecision, extract_out_of_scope_geo

# ---------------------------------------------------------------------------
# Reason-specific templates.
# ---------------------------------------------------------------------------


# Each entry shapes the full refusal:
#   - direct: one-sentence honest answer the user sees.
#   - limit: the single most important caveat to add (beyond the defaults
#     the composer always appends).
#   - redirect: a constructive follow-up question the system *can* serve.
#   - status: grounding_status enum value.
_TEMPLATES: dict[str, dict[str, str]] = {
    "out_of_scope_geography": {
        "direct": (
            "I don't have groundwater data for {geo} — this project covers "
            "Florida USGS NWIS sites only."
        ),
        "limit": (
            "{geo_caveat} is outside the Florida monitoring network this " "dataset is built on."
        ),
        "redirect": "Would you like to compare Florida wells in a specific county or aquifer?",
        "status": GroundingStatus.REFUSED,
    },
    "future_prediction": {
        "direct": (
            "I can describe what the monitoring record shows, but I can't forecast "
            "future groundwater levels."
        ),
        "limit": (
            "The dataset is observed history — projections require a "
            "groundwater-flow model, not this chart."
        ),
        "redirect": "Would you like the observed trend over the available record instead?",
        "status": GroundingStatus.REFUSED,
    },
    "no_evidence": {
        "direct": "I don't have deterministic evidence to ground an answer to that question.",
        "limit": (
            "No matching wells, aquifer, or chart context were detected for " "this question."
        ),
        "redirect": "Could you rephrase with a specific well ID, county, or aquifer?",
        "status": GroundingStatus.INSUFFICIENT,
    },
}


_DEFAULT_REASON = "no_evidence"


# ---------------------------------------------------------------------------
# Builders.
# ---------------------------------------------------------------------------


def _template_for(reason: Optional[str]) -> dict[str, str]:
    return _TEMPLATES.get(reason or "", _TEMPLATES[_DEFAULT_REASON])


def _format_template(text: str, *, question: str, reason: Optional[str]) -> str:
    """Substitute the ``{geo}`` placeholder for geography refusals."""
    if reason != "out_of_scope_geography" or "{" not in text:
        return text
    geo = extract_out_of_scope_geo(question) or "that location"
    geo_lower = geo.lower()
    return text.format(geo=geo_lower, geo_caveat=geo)


def build_insufficient_answer(
    *,
    question: str,
    reason: Optional[str] = None,
) -> GroundedAnswer:
    """Return a deterministic refusal/insufficient ``GroundedAnswer``.

    ``reason`` should match one of the template keys
    (``out_of_scope_geography``, ``future_prediction``, ``no_evidence``).
    Unknown reasons fall back to the generic no-evidence template. The
    geography template echoes the queried place so the refusal stays
    specific.
    """
    template = _template_for(reason)
    return GroundedAnswer(
        direct_answer=_format_template(template["direct"], question=question, reason=reason),
        grounded_findings=[],
        limits=[_format_template(template["limit"], question=question, reason=reason)],
        next_best_question=template["redirect"],
        supporting_evidence=[],
        grounding_status=template["status"],
    )


def build_insufficient_from_decision(
    decision: RouteDecision,
    *,
    question: str,
) -> Optional[GroundedAnswer]:
    """Return an insufficient-evidence answer when the decision demands one.

    Returns ``None`` when the decision is a normal routable intent — callers
    should then run the usual deterministic pipeline + explainer.
    """
    if decision.route_mode == RouteMode.UNSUPPORTED:
        return build_insufficient_answer(
            question=question,
            reason=decision.unsupported_reason or _DEFAULT_REASON,
        )
    return None


# ---------------------------------------------------------------------------
# Composer / explainer gates.
# ---------------------------------------------------------------------------


def is_insufficient_answer(answer: GroundedAnswer) -> bool:
    """True when ``answer`` represents the refusal / insufficient path."""
    return answer.grounding_status in {GroundingStatus.INSUFFICIENT, GroundingStatus.REFUSED}


def should_short_circuit_explainer(answer: GroundedAnswer) -> bool:
    """True when the explainer should be skipped entirely.

    The Phase-3 explainer adds value by rephrasing deterministic evidence for
    the user. When the evidence set is empty — refused or insufficient — the
    LLM has nothing to ground on, and the validator would reject almost any
    narrative it produced. Short-circuit so the deterministic template is
    what the user sees.
    """
    return is_insufficient_answer(answer)


def attach_insufficient_answer(
    payload: dict[str, Any],
    answer: GroundedAnswer,
    *,
    force: bool = True,
) -> dict[str, Any]:
    """Stamp the insufficient-evidence answer onto the payload.

    Unlike ``attach_grounded_answer``, the default here is ``force=True``:
    the insufficient path is produced deliberately by the router, and it
    should overwrite any speculative answer an earlier branch may have left
    behind.
    """
    if not force and isinstance(payload.get("grounded_answer"), dict):
        return payload
    payload["grounded_answer"] = replace(answer).__dict__.copy()
    # Keep the string ``response`` field in sync so legacy consumers that
    # read payload['response'] still see the refusal.
    if not payload.get("response") or force:
        payload["response"] = answer.direct_answer
    return payload


__all__ = [
    "attach_insufficient_answer",
    "build_insufficient_answer",
    "build_insufficient_from_decision",
    "is_insufficient_answer",
    "should_short_circuit_explainer",
]
