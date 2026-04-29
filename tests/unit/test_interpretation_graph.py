"""Unit tests for the LangGraph interpretation engine."""

from __future__ import annotations

from unittest.mock import patch

from api.routes.answering.reasoning import (
    GroundedFraming,
    GroundedInterpretation,
    GroundedNumericClaim,
    ReasoningStep,
)
from src.agent import interpretation_graph


def _pack():
    return {
        "site_ids": ["G-1"],
        "sites": [
            {
                "site_id": "G-1",
                "name": "Lee L-1",
                "annual_change_ft_yr": -0.45,
                "net_change_ft": -6.0,
                "trend_label": "falling",
                "record_start": "2015-01-01",
                "record_end": "2024-12-31",
                "aquifer": "Biscayne",
                "aquifer_zone": "Biscayne",
            }
        ],
        "wells": [
            {
                "site_id": "G-1",
                "name": "Lee L-1",
                "annual_change_ft_yr": -0.45,
                "trend_label": "falling",
            }
        ],
        "cross_well": {"n_total": 1, "trend_distribution": {"falling": 1}},
    }


def _make_interp(grounding: str = "grounded", steps: int = 1) -> GroundedInterpretation:
    return GroundedInterpretation(
        intent="fastest_decline",
        framing=GroundedFraming(
            scope_type="well",
            focus_entities=["Lee L-1"],
            question_goal="rank",
            required_evidence_sections=["wells"],
        ),
        reasoning_steps=[
            ReasoningStep(
                step_label="observe",
                observation="L-1 is falling at 0.45 ft/yr",
                evidence_keys=["wells.L-1.annual_change_ft_yr"],
                inference="L-1 is declining fastest in the cohort.",
                confidence="high",
            )
            for _ in range(steps)
        ],
        direct_answer="Lee L-1 is declining fastest at 0.45 ft/yr.",
        grounding_status=grounding,
        numeric_claims=[
            GroundedNumericClaim(
                site="Lee L-1", value=-0.45, unit="ft/yr", source="annual_change_ft_yr"
            )
        ],
    )


def test_graph_runs_self_consistency_and_returns_best():
    pack = _pack()
    draft_a = _make_interp(grounding="grounded")
    draft_b = _make_interp(grounding="partial")
    draft_c = _make_interp(grounding="grounded")

    with patch(
        "api.routes.answering.reasoning.invoke_grounded_reasoning",
        side_effect=[draft_a, draft_b, draft_c],
    ), patch("api.routes.answering.reasoning.validate_against_pack", return_value=[]):
        result = interpretation_graph.run_interpretation_graph("which well is fastest?", pack)

    assert result is not None
    # Majority "grounded" should win
    assert result.grounding_status == "grounded"
    # Graph trace attached
    assert hasattr(result, "langgraph_trace")
    nodes = [step["node"] for step in result.langgraph_trace]
    assert "frame" in nodes and "sample_reason" in nodes and "critic" in nodes


def test_graph_returns_none_when_all_samples_fail():
    pack = _pack()
    with patch(
        "api.routes.answering.reasoning.invoke_grounded_reasoning",
        return_value=None,
    ):
        result = interpretation_graph.run_interpretation_graph("fastest?", pack)
    assert result is None


def test_graph_appends_critic_flags_to_limits():
    pack = _pack()
    draft = _make_interp()
    with patch(
        "api.routes.answering.reasoning.invoke_grounded_reasoning",
        return_value=draft,
    ), patch(
        "api.routes.answering.reasoning.validate_against_pack",
        return_value=["grounded_reasoning_missing_evidence_keys"],
    ):
        result = interpretation_graph.run_interpretation_graph("fastest?", pack, n_samples=1)

    assert result is not None
    combined = " ".join(result.important_limits).lower()
    assert "validator flags" in combined


def test_feature_flag_on_by_default(monkeypatch):
    monkeypatch.delenv("GROUNDWATERGPT_ENABLE_LANGGRAPH_INTERPRETER", raising=False)
    assert interpretation_graph.langgraph_interpreter_enabled() is True


def test_feature_flag_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("GROUNDWATERGPT_ENABLE_LANGGRAPH_INTERPRETER", "false")
    assert interpretation_graph.langgraph_interpreter_enabled() is False


def test_feature_flag_on_when_set(monkeypatch):
    monkeypatch.setenv("GROUNDWATERGPT_ENABLE_LANGGRAPH_INTERPRETER", "1")
    assert interpretation_graph.langgraph_interpreter_enabled() is True
