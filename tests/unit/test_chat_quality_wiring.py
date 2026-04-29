"""Wiring tests for Slices B and C.

These are narrow behavioral contracts, not end-to-end LLM tests:

* `invoke_grounded_synthesis` must route through `run_interpretation_graph`
  when the LangGraph flag is on (Slice B).
* `invoke_grounded_reasoning` must issue one repair retry when validators
  flag a fabrication on the deterministic (T=0) sample, and must mark the
  result `grounding_status="partial"` if the retry is still flagged
  (Slice C).
"""

from __future__ import annotations

from api.routes.answering import reasoning as gr
from api.routes.answering.reasoning import (
    DriverHypothesis,
    GroundedFraming,
    GroundedInterpretation,
    ReasoningStep,
    invoke_grounded_reasoning,
    invoke_grounded_synthesis,
)


def _fabricated_interp() -> GroundedInterpretation:
    return GroundedInterpretation(
        intent="explain",
        framing=GroundedFraming(
            scope_type="well",
            focus_entities=["Lee L-100"],
            question_goal="explain",
            required_evidence_sections=["well_summaries"],
        ),
        reasoning_steps=[
            ReasoningStep(
                step_label="Frame",
                observation="Lee L-100 is declining.",
                evidence_keys=["well_summaries"],
                inference="Lee L-100 is declining.",
                confidence="medium",
            )
        ],
        direct_answer=("Lee L-100 at -0.05 ft/yr over 2005 to 2023 with a 1974 baseline."),
        what_matters_most="Lee L-100 is declining.",
        why_it_matters="Supply implications.",
        grounding_status="grounded",
    )


def _clean_interp() -> GroundedInterpretation:
    return GroundedInterpretation(
        intent="explain",
        framing=GroundedFraming(
            scope_type="well",
            focus_entities=["Lee L-100"],
            question_goal="explain",
            required_evidence_sections=["well_summaries"],
        ),
        reasoning_steps=[
            ReasoningStep(
                step_label="Frame",
                observation="Lee L-100 is declining over 2005-2023.",
                evidence_keys=["well_summaries"],
                inference="Lee L-100 is declining.",
                confidence="medium",
            )
        ],
        direct_answer=("Lee L-100 at -0.05 ft/yr over 2005 to 2023."),
        what_matters_most="Lee L-100 is declining.",
        why_it_matters="Supply implications.",
        grounding_status="grounded",
        driver_hypotheses=[
            DriverHypothesis(
                claim="Dry-season pumping aligns with the 2017 break",
                mechanism="pumping",
                evidence_keys=["well_summaries"],
                confidence="medium",
                falsification_test=(
                    "A constant post-2017 pumping record with no water-level "
                    "change would disprove this."
                ),
            )
        ],
    )


def _pack() -> dict:
    return {
        "cohort_period_start": "2005-01-01",
        "cohort_period_end": "2023-12-31",
        "sites": [{"site_id": "A1", "name": "Lee L-100"}],
        "site_ids": ["A1"],
        "wells": [
            {
                "site_id": "A1",
                "name": "Lee L-100",
                "record_window": ["2005-01-01", "2023-12-31"],
                "mk_p": 0.03,
                "sens_ft_yr": -0.05,
            }
        ],
        "well_summaries": [
            {
                "name": "Lee L-100",
                "site_id": "A1",
                "record_start": "2005",
                "record_end": "2023",
            }
        ],
        "comparison_features": {"cohort_mean_annual_change_ft_yr": -0.05},
    }


class _StubLLM:
    """Minimal LLM stub that returns scheduled interpretations on each invoke."""

    def __init__(self, queue):
        self._queue = list(queue)

    def with_structured_output(self, schema):  # noqa: ARG002 - schema unused in stub
        return self

    def invoke(self, messages):  # noqa: ARG002 - messages unused in stub
        if not self._queue:
            raise RuntimeError("Stub LLM exhausted")
        return self._queue.pop(0)


def test_invoke_grounded_reasoning_repairs_on_flag(monkeypatch):
    """Deterministic fabrication → one retry → clean interpretation returned."""
    pack = _pack()
    stub = _StubLLM(queue=[_fabricated_interp(), _clean_interp()])

    monkeypatch.setattr(gr, "_reasoning_providers", lambda: [("qwen", "qwen-plus")])
    monkeypatch.setattr(
        "src.agent.llm_factory.get_llm",
        lambda **kwargs: stub,
    )

    result = invoke_grounded_reasoning(
        "What is the trend at Lee L-100?",
        pack,
    )
    assert result is not None
    assert result.grounding_status == "grounded"
    # Fabricated-year retry path must have drained both scheduled responses.
    assert stub._queue == []


def test_invoke_grounded_reasoning_marks_partial_when_retry_still_flagged(monkeypatch):
    """Two fabricated passes → result is marked partial, not returned clean."""
    pack = _pack()
    stub = _StubLLM(queue=[_fabricated_interp(), _fabricated_interp()])

    monkeypatch.setattr(gr, "_reasoning_providers", lambda: [("qwen", "qwen-plus")])
    monkeypatch.setattr(
        "src.agent.llm_factory.get_llm",
        lambda **kwargs: stub,
    )

    result = invoke_grounded_reasoning(
        "What is the trend at Lee L-100?",
        pack,
    )
    assert result is not None
    assert result.grounding_status == "partial"


def test_chat_synthesis_uses_langgraph_when_enabled(monkeypatch):
    """Chat synthesis must dispatch through `run_interpretation_graph`."""
    called = {}

    def _fake_graph(question, pack, **kwargs):
        called["question"] = question
        called["n_samples"] = kwargs.get("n_samples")
        called["deadline"] = kwargs.get("deadline")
        return _clean_interp()

    # LangGraph flag defaults on now; this confirms the dispatch path
    # without relying on real network LLM calls.
    monkeypatch.setattr("src.agent.interpretation_graph.run_interpretation_graph", _fake_graph)
    monkeypatch.setattr(
        "src.agent.interpretation_graph.langgraph_interpreter_enabled",
        lambda: True,
    )

    # Minimal chat inputs so _build_chat_synthesis_pack produces a valid pack.
    site_computed = [
        {
            "site_id": "A1",
            "name": "Lee L-100",
            "annual_change_ft_yr": -0.05,
            "mk_pvalue": 0.03,
            "sens_slope_ft_yr": -0.05,
            "aq_label": "surficial",
        }
    ]
    cross_well = {
        "mean_annual_change_ft_yr": -0.05,
        "per_site_metrics": site_computed,
    }

    result = invoke_grounded_synthesis(
        question="trends at Lee L-100",
        site_computed=site_computed,
        aquifer_summaries=[],
        cross_well=cross_well,
        supply_info=None,
        location_name="Lee County",
    )
    assert result is not None
    assert called["question"] == "trends at Lee L-100"
    assert called["n_samples"] == 2
