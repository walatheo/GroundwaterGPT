"""Answer-composition subsystem for the chat / interpret routes.

This package collects the four files that together compose every chat
response. They have distinct responsibilities — not interchangeable
strategies — so they live as siblings rather than a strategy registry:

* :mod:`composer` — the canonical ``GroundedAnswer`` envelope and its
  builders (``compose_grounded_answer``, ``attach_grounded_answer``).
* :mod:`reasoning` — LLM-driven hydrologic reasoning, entity framing,
  Pydantic claim/interpretation models, and timeout-aware LLM invocation.
* :mod:`followups` — evidence-guided "next questions" generator plus the
  shared sentence-cleanup helpers (``clean_sentence``, ``questionize``)
  that ``composer`` reuses.
* :mod:`refusal` — refusal templates and builders for insufficient-evidence
  / out-of-scope responses; wraps the ``GroundedAnswer`` envelope.

Callers should prefer ``from api.routes.answering import X`` over reaching
into individual submodules where convenient. Submodule paths remain stable
and may be patched directly in tests.
"""

from api.routes.answering.composer import (
    GroundedAnswer,
    attach_grounded_answer,
    compose_grounded_answer,
)
from api.routes.answering.followups import (
    FollowUpGroup,
    ProgressionRewrite,
    build_evidence_guided_progression,
    clean_sentence,
    flatten_follow_up_groups,
    questionize,
)
from api.routes.answering.refusal import (
    attach_insufficient_answer,
    build_insufficient_answer,
    build_insufficient_from_decision,
    is_insufficient_answer,
    should_short_circuit_explainer,
)

__all__ = [
    "GroundedAnswer",
    "attach_grounded_answer",
    "compose_grounded_answer",
    "FollowUpGroup",
    "ProgressionRewrite",
    "build_evidence_guided_progression",
    "clean_sentence",
    "flatten_follow_up_groups",
    "questionize",
    "attach_insufficient_answer",
    "build_insufficient_answer",
    "build_insufficient_from_decision",
    "is_insufficient_answer",
    "should_short_circuit_explainer",
]
