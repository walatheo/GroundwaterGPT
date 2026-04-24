"""LangGraph state machine for grounded chart interpretation.

The graph wraps the existing deterministic pipeline in
``api.routes._grounded_reasoning`` with three additions that matter for
publication-quality reasoning:

    frame  →  sample_reason (self-consistency)  →  critic  →  synthesize

* **frame** records the question frame via ``derive_question_frame`` so the
  downstream graph always has an explicit goal + scope.
* **sample_reason** invokes ``invoke_grounded_reasoning`` ``N`` times with
  temperature ``>0`` and keeps every candidate.  A majority vote on
  ``grounding_status`` and the intent label gives a cheap self-consistency
  signal; the draft with the fewest validator flags is promoted.
* **critic** re-runs ``validate_against_pack`` (and optionally calls the LLM
  as an adversarial judge) so any unanchored claim is escalated before the
  answer escapes the graph.
* **synthesize** emits the final ``GroundedInterpretation`` and attaches an
  execution trace that can be serialized into a paper figure.

The whole graph is feature-flagged behind
``GROUNDWATERGPT_ENABLE_LANGGRAPH_INTERPRETER``; callers fall back to the
single-turn path whenever the flag is off or LangGraph raises.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


_DEFAULT_SAMPLES = 3
_DEFAULT_TEMPS = (0.0, 0.5, 0.8)


def langgraph_interpreter_enabled() -> bool:
    """Return True when the LangGraph interpreter should be used.

    Defaults ON so chat + chart-interpreter both get self-consistency.
    Set GROUNDWATERGPT_ENABLE_LANGGRAPH_INTERPRETER=false to disable.
    """
    raw = os.getenv("GROUNDWATERGPT_ENABLE_LANGGRAPH_INTERPRETER", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


@dataclass
class GraphState:
    """Mutable state carried between LangGraph nodes in the interpretation graph."""

    question: str
    pack: dict[str, Any]
    rubric: Optional[dict[str, Any]] = None
    hydro_context: Optional[dict[str, Any]] = None
    rubric_moves: Optional[list[str]] = None
    samples: list[Any] = field(default_factory=list)
    sample_flags: list[list[str]] = field(default_factory=list)
    best: Optional[Any] = None
    critic_flags: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)


def run_interpretation_graph(
    question: str,
    pack: dict[str, Any],
    *,
    rubric: Optional[dict[str, Any]] = None,
    hydro_context: Optional[dict[str, Any]] = None,
    rubric_moves: Optional[list[str]] = None,
    n_samples: int = _DEFAULT_SAMPLES,
    deadline: Optional[float] = None,
) -> Optional[Any]:
    """Execute the interpretation graph and return the best grounded answer.

    Returns ``None`` when every sampled reasoning path fails so the caller can
    fall back to the deterministic pipeline.
    """
    try:
        from langgraph.graph import END, StateGraph
    except Exception:  # pragma: no cover - langgraph is a hard dep
        logger.debug("langgraph unavailable; falling back to single-turn interpreter")
        return None

    from api.routes._grounded_reasoning import (
        derive_question_frame,
        invoke_grounded_reasoning,
        validate_against_pack,
    )

    state = GraphState(
        question=question,
        pack=pack,
        rubric=rubric,
        hydro_context=hydro_context,
        rubric_moves=rubric_moves,
    )

    def _frame_node(s: GraphState) -> dict:
        framing = derive_question_frame(s.question, s.pack)
        s.trace.append(
            {"node": "frame", "scope": framing.scope_type, "goal": framing.question_goal}
        )
        return {"pack": {**s.pack, "_frame": framing.model_dump()}}

    def _sample_reason_node(s: GraphState) -> dict:
        import time as _time

        samples: list[Any] = []
        flags: list[list[str]] = []
        temps = _DEFAULT_TEMPS[:n_samples] or (0.0,)
        for temp in temps:
            if deadline is not None and _time.monotonic() >= deadline - 5:
                logger.debug("LangGraph sample loop bailed at T=%s: budget exhausted", temp)
                break
            try:
                interp = invoke_grounded_reasoning(
                    s.question,
                    s.pack,
                    rubric=s.rubric,
                    hydro_context=s.hydro_context,
                    rubric_moves=s.rubric_moves,
                    deadline=deadline,
                    temperature=float(temp),
                )
            except Exception as exc:
                logger.debug("sample reasoning failed at T=%s: %s", temp, exc)
                interp = None
            if interp is None:
                continue
            sample_flags = validate_against_pack(interp, s.pack)
            samples.append(interp)
            flags.append(sample_flags)
        s.trace.append(
            {
                "node": "sample_reason",
                "n_attempted": len(temps),
                "n_returned": len(samples),
                "flag_counts": [len(f) for f in flags],
            }
        )
        return {"samples": samples, "sample_flags": flags}

    def _aggregate_node(s: GraphState) -> dict:
        if not s.samples:
            s.trace.append({"node": "aggregate", "status": "no_samples"})
            return {"best": None}

        status_votes = Counter(getattr(sample, "grounding_status", "") for sample in s.samples)
        majority_status = status_votes.most_common(1)[0][0] if status_votes else ""
        ranked = sorted(
            zip(s.samples, s.sample_flags),
            key=lambda pair: (
                len(pair[1]),
                0 if pair[0].grounding_status == majority_status else 1,
            ),
        )
        best = ranked[0][0]

        seen_claims: set[tuple] = set()
        merged = []
        for sample in s.samples:
            for claim in sample.numeric_claims:
                key = (claim.site, round(claim.value, 4), claim.unit, claim.source)
                if key in seen_claims:
                    continue
                seen_claims.add(key)
                merged.append(claim)
        best.numeric_claims = merged

        s.trace.append(
            {
                "node": "aggregate",
                "status_votes": dict(status_votes),
                "best_flag_count": len(ranked[0][1]),
                "n_merged_claims": len(merged),
            }
        )
        return {"best": best}

    def _critic_node(s: GraphState) -> dict:
        if s.best is None:
            return {"critic_flags": []}
        flags = validate_against_pack(s.best, s.pack)
        if flags:
            logger.info("LangGraph critic flagged %d issues: %s", len(flags), flags)
        s.trace.append({"node": "critic", "n_flags": len(flags), "flags": flags[:5]})
        return {"critic_flags": flags}

    def _synthesize_node(s: GraphState) -> dict:
        if s.best is None:
            return {}
        if s.critic_flags:
            limits = list(s.best.important_limits)
            note = "validator flags: " + ", ".join(sorted(set(s.critic_flags))[:3])
            if note not in limits:
                limits.append(note)
            s.best.important_limits = limits
        try:
            object.__setattr__(s.best, "langgraph_trace", list(s.trace))
        except Exception:
            pass
        s.trace.append({"node": "synthesize", "emitted": s.best is not None})
        return {}

    graph = StateGraph(GraphState)
    graph.add_node("frame", _frame_node)
    graph.add_node("sample_reason", _sample_reason_node)
    graph.add_node("aggregate", _aggregate_node)
    graph.add_node("critic", _critic_node)
    graph.add_node("synthesize", _synthesize_node)

    graph.set_entry_point("frame")
    graph.add_edge("frame", "sample_reason")
    graph.add_edge("sample_reason", "aggregate")
    graph.add_edge("aggregate", "critic")
    graph.add_edge("critic", "synthesize")
    graph.add_edge("synthesize", END)

    compiled = graph.compile()
    final_state = compiled.invoke(state)
    best = (
        final_state.get("best")
        if isinstance(final_state, dict)
        else getattr(final_state, "best", None)
    )
    if best is None:
        return None
    return best
