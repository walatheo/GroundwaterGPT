"""Phase 4 tests — structured insufficient-evidence / refusal answers."""

from __future__ import annotations

import pytest

from api.routes._answer_contract import GroundingStatus, RouteMode
from api.routes._grounded_answer import GroundedAnswer
from api.routes._insufficient_evidence import (
    attach_insufficient_answer,
    build_insufficient_answer,
    build_insufficient_from_decision,
    is_insufficient_answer,
    should_short_circuit_explainer,
)
from api.routes._route_decision import RouteDecision


class TestBuildInsufficientAnswer:
    def test_out_of_scope_geography_is_refused(self):
        answer = build_insufficient_answer(
            question="how's groundwater in Antarctica?",
            reason="out_of_scope_geography",
        )
        assert answer.grounding_status == GroundingStatus.REFUSED
        assert "Florida" in answer.direct_answer
        assert "antarctica" in answer.direct_answer.lower()
        assert answer.grounded_findings == []
        assert answer.next_best_question is not None
        assert any("Antarctica" in line for line in answer.limits)

    def test_future_prediction_is_refused(self):
        answer = build_insufficient_answer(
            question="will it drop next year?",
            reason="future_prediction",
        )
        assert answer.grounding_status == GroundingStatus.REFUSED
        assert "forecast" in answer.direct_answer.lower()
        assert "projections" in " ".join(answer.limits).lower()

    def test_no_evidence_is_insufficient(self):
        answer = build_insufficient_answer(
            question="tell me about nothing",
            reason="no_evidence",
        )
        assert answer.grounding_status == GroundingStatus.INSUFFICIENT
        assert "deterministic evidence" in answer.direct_answer

    def test_unknown_reason_falls_back_to_no_evidence(self):
        answer = build_insufficient_answer(question="whatever", reason="something_unusual")
        assert answer.grounding_status == GroundingStatus.INSUFFICIENT

    def test_none_reason_falls_back_to_no_evidence(self):
        answer = build_insufficient_answer(question="whatever", reason=None)
        assert answer.grounding_status == GroundingStatus.INSUFFICIENT

    def test_result_is_a_grounded_answer(self):
        answer = build_insufficient_answer(question="q", reason="no_evidence")
        assert isinstance(answer, GroundedAnswer)


class TestBuildFromDecision:
    def test_unsupported_decision_produces_refusal(self):
        decision = RouteDecision(
            route_mode=RouteMode.UNSUPPORTED,
            internal_mode="fallback",
            intent="unsupported_question",
            unsupported_reason="future_prediction",
        )
        answer = build_insufficient_from_decision(decision, question="will it rise?")
        assert answer is not None
        assert answer.grounding_status == GroundingStatus.REFUSED

    def test_normal_decision_returns_none(self):
        decision = RouteDecision(
            route_mode=RouteMode.EXACT_WELL,
            internal_mode="site_fallback",
            intent="exact_well_lookup",
        )
        assert build_insufficient_from_decision(decision, question="G-3336") is None

    def test_unsupported_without_reason_falls_back(self):
        decision = RouteDecision(
            route_mode=RouteMode.UNSUPPORTED,
            internal_mode="fallback",
            intent="unsupported_question",
            unsupported_reason=None,
        )
        answer = build_insufficient_from_decision(decision, question="???")
        assert answer is not None
        # Missing reason collapses to the generic no-evidence template.
        assert answer.grounding_status == GroundingStatus.INSUFFICIENT


class TestClassificationHelpers:
    @pytest.mark.parametrize(
        "status,expected",
        [
            (GroundingStatus.INSUFFICIENT, True),
            (GroundingStatus.REFUSED, True),
            (GroundingStatus.PARTIAL, False),
            (GroundingStatus.GROUNDED, False),
        ],
    )
    def test_is_insufficient_answer(self, status, expected):
        answer = GroundedAnswer(grounding_status=status)
        assert is_insufficient_answer(answer) is expected

    def test_short_circuit_matches_insufficient(self):
        refused = GroundedAnswer(grounding_status=GroundingStatus.REFUSED)
        grounded = GroundedAnswer(grounding_status=GroundingStatus.GROUNDED)
        assert should_short_circuit_explainer(refused) is True
        assert should_short_circuit_explainer(grounded) is False


class TestAttach:
    def test_attach_stamps_payload_and_response(self):
        answer = build_insufficient_answer(question="q", reason="no_evidence")
        payload: dict = {}
        attach_insufficient_answer(payload, answer)
        assert payload["grounded_answer"]["grounding_status"] == GroundingStatus.INSUFFICIENT
        assert payload["response"] == answer.direct_answer

    def test_attach_overrides_existing_response_by_default(self):
        answer = build_insufficient_answer(question="q", reason="future_prediction")
        payload: dict = {"response": "stale speculative text"}
        attach_insufficient_answer(payload, answer)
        assert payload["response"] == answer.direct_answer

    def test_attach_force_false_preserves_existing_grounded_answer(self):
        answer = build_insufficient_answer(question="q", reason="no_evidence")
        payload: dict = {"grounded_answer": {"marker": "earlier"}}
        attach_insufficient_answer(payload, answer, force=False)
        assert payload["grounded_answer"] == {"marker": "earlier"}
