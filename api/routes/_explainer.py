"""Phase 3: single sanctioned LLM explainer.

Before Phase 3, narrative LLM calls lived in four places — grounded synthesis,
chart interpretation, progression rewrite, and an ad-hoc Ollama httpx block.
Each site built its own prompt, its own parsing, and its own idea of what the
LLM was allowed to say. There was no single enforcement point for the project's
core policy:

    The LLM may explain deterministic outputs. It may NOT originate
    measurements, dates, site IDs, or counts that the deterministic pipeline
    did not emit.

``explain_grounded_answer`` is that enforcement point. Given a ``GroundedAnswer``
built by Phase 2, it:

1. Renders a bounded system prompt that lists the allowed evidence verbatim.
2. Invokes the configured LLM at temperature 0.
3. Runs ``validate_explanation`` — rejecting narratives that introduce numbers,
   dates, or site IDs that are not in the evidence set.

Phases 4 and onward migrate the remaining narrative call sites onto this
entry point. For Phase 3 the explainer is additive and opt-in; the validator
works standalone (no LLM dependency) so integration tests and CI can gate on it
immediately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from api.routes._grounded_answer import GroundedAnswer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy constants — the prompt and the validator share these so drift is
# impossible. If you loosen one, you must loosen the other.
# ---------------------------------------------------------------------------


EXPLAINER_SYSTEM_PROMPT = """\
You are the GroundwaterGPT explainer. Your job is to produce a short, honest
narrative that helps the user understand a deterministic result.

POLICY (non-negotiable):
- You may explain, contextualize, and restate findings in plain language.
- You may NOT introduce new numbers, dates, well counts, or site IDs that are
  not already in the supplied evidence. If you want to cite a value, it must
  appear verbatim in the findings or supporting evidence below.
- You may NOT forecast, predict, or project. The dataset is observed history.
- If the evidence is insufficient to answer the question, say so plainly in
  one sentence. Do not fill the gap with generic hydrogeology.

FORMAT:
- 3 to 6 sentences.
- First sentence restates the direct_answer.
- Middle sentences weave in the grounded_findings.
- Close with the most important limit, or the next_best_question if the
  evidence is thin.
"""


_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# Site IDs in the USGS dataset look like "G-3336" or "G3336" — uppercase letter,
# optional hyphen, digits. Kept tight so everyday acronyms don't trip it.
_SITE_ID_RE = re.compile(r"\b[A-Z]-?\d{3,5}\b")


# ---------------------------------------------------------------------------
# Result and validator types.
# ---------------------------------------------------------------------------


@dataclass
class ExplainerResult:
    """Outcome of a single explainer invocation."""

    narrative: str = ""
    accepted: bool = False
    violations: list[str] = field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe view for attaching to the chat payload."""
        return {
            "narrative": self.narrative,
            "accepted": self.accepted,
            "violations": list(self.violations),
            "provider": self.provider,
            "model": self.model,
        }


# ---------------------------------------------------------------------------
# Evidence-set extraction and validator.
# ---------------------------------------------------------------------------


def _evidence_text_blob(answer: GroundedAnswer) -> str:
    """Concatenate every piece of evidence the narrative is allowed to draw from."""
    parts: list[str] = [answer.direct_answer]
    parts.extend(answer.grounded_findings)
    parts.extend(answer.limits)
    if answer.next_best_question:
        parts.append(answer.next_best_question)
    for entry in answer.supporting_evidence:
        for key in ("site_id", "name", "aquifer", "county", "url"):
            value = entry.get(key)
            if value:
                parts.append(str(value))
    return " ".join(parts)


def _extract_tokens(text: str) -> dict[str, set[str]]:
    """Pull the measurement-bearing tokens out of ``text`` in a dedupe-friendly form."""
    text = text or ""
    site_ids = {match.upper().replace("-", "") for match in _SITE_ID_RE.findall(text)}
    # Strip site-ID spans before number extraction so the digits inside a site
    # code (``G-9999``) don't get re-reported as a bare measurement.
    text_for_numbers = _SITE_ID_RE.sub(" ", text)
    numbers = set(_NUMBER_RE.findall(text_for_numbers))
    years = set(_YEAR_RE.findall(text_for_numbers))
    # Every year matches the number regex — separate so the validator can report
    # them distinctly and so we can allow year-only narrative without exposing
    # the user to bare magnitudes.
    numbers -= years
    return {"numbers": numbers, "years": years, "site_ids": site_ids}


def validate_explanation(narrative: str, answer: GroundedAnswer) -> list[str]:
    """Return a list of policy violations; empty list means the narrative is clean.

    A violation is a measurement-bearing token (number, year, or site ID) that
    appears in ``narrative`` but not in the evidence set derived from ``answer``.
    """
    if not narrative:
        return []

    narrative_tokens = _extract_tokens(narrative)
    evidence_tokens = _extract_tokens(_evidence_text_blob(answer))

    violations: list[str] = []
    for kind in ("numbers", "years", "site_ids"):
        stray = narrative_tokens[kind] - evidence_tokens[kind]
        for token in sorted(stray):
            violations.append(
                f"unsupported_{kind[:-1] if kind != 'site_ids' else 'site_id'}:{token}"
            )
    return violations


# ---------------------------------------------------------------------------
# Prompt assembly.
# ---------------------------------------------------------------------------


def build_explainer_messages(
    answer: GroundedAnswer,
    *,
    question: str,
) -> list[tuple[str, str]]:
    """Render the user-facing half of the explainer prompt.

    Kept separate from ``explain_grounded_answer`` so tests can snapshot the
    prompt without invoking an LLM.
    """
    findings_block = "\n".join(f"- {item}" for item in answer.grounded_findings) or "- (none)"
    limits_block = "\n".join(f"- {item}" for item in answer.limits) or "- (none)"
    evidence_block = (
        "\n".join(
            f"- {entry.get('site_id') or entry.get('url') or '(unnamed)'}:"
            f" {entry.get('name') or entry.get('url') or ''}"
            for entry in answer.supporting_evidence
        )
        or "- (none)"
    )

    user = (
        f"QUESTION:\n{question.strip()}\n\n"
        f"DIRECT ANSWER:\n{answer.direct_answer or '(not yet determined)'}\n\n"
        f"GROUNDED FINDINGS:\n{findings_block}\n\n"
        f"LIMITS:\n{limits_block}\n\n"
        f"SUPPORTING EVIDENCE:\n{evidence_block}\n\n"
        f"NEXT BEST QUESTION:\n{answer.next_best_question or '(none)'}\n"
    )
    return [("system", EXPLAINER_SYSTEM_PROMPT), ("human", user)]


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def explain_grounded_answer(
    answer: GroundedAnswer,
    *,
    question: str,
    llm: Optional[Any] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> ExplainerResult:
    """Generate a validated narrative from a deterministic ``GroundedAnswer``.

    ``llm`` may be injected for tests or when the caller has already resolved
    a provider. If absent, ``src.agent.llm_factory.get_llm`` is used at
    temperature 0.

    On LLM failure the function returns an ``ExplainerResult`` with
    ``accepted=False`` and a single ``"llm_unavailable"`` violation. On policy
    violations the function returns the narrative AS-IS with the violations
    list populated — callers decide whether to drop the narrative or annotate it.
    """
    messages = build_explainer_messages(answer, question=question)

    if llm is None:
        try:
            from src.agent.llm_factory import LLMProvider, get_llm

            provider_enum = LLMProvider(provider) if provider else None
            llm = get_llm(provider=provider_enum, model=model, temperature=0)
        except Exception as exc:
            logger.debug("Explainer LLM init failed: %s", exc)
            return ExplainerResult(violations=["llm_unavailable"])

    try:
        raw = llm.invoke(messages)
    except Exception as exc:
        logger.debug("Explainer invoke failed: %s", exc)
        return ExplainerResult(violations=["llm_invoke_failed"])

    narrative = (getattr(raw, "content", None) or str(raw) or "").strip()
    violations = validate_explanation(narrative, answer)

    return ExplainerResult(
        narrative=narrative,
        accepted=not violations,
        violations=violations,
        provider=provider,
        model=model,
    )


__all__ = [
    "EXPLAINER_SYSTEM_PROMPT",
    "ExplainerResult",
    "build_explainer_messages",
    "explain_grounded_answer",
    "validate_explanation",
]
