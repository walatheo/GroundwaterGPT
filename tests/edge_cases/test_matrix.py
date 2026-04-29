"""Phase 5 edge-case matrix.

Three categorized fixtures live alongside this test file:

- ``routing_cases.json`` — real questions paired with the canonical
  ``route_mode`` the resolver must produce. Target >=95% pass rate.
- ``guardrail_cases.json`` — evidence sets + candidate LLM narratives,
  paired with the violations ``validate_explanation`` must raise.
  Target 100%.
- ``refusal_cases.json`` — out-of-scope / future-prediction questions that
  must route to UNSUPPORTED and produce an insufficient/refused
  ``GroundedAnswer``. Target 100%.

The routing matrix runs the real detectors from ``api.routes.chat`` so the
numbers reflect production behavior. That means importing chat.py once at
module load time (~13s cold). The guardrail and refusal matrices are
detector-free and run in milliseconds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from api.routes._answer_contract import GroundingStatus, RouteMode
from api.routes._explainer import validate_explanation
from api.routes._route_decision import resolve_route
from api.routes.answering.composer import GroundedAnswer
from api.routes.answering.refusal import build_insufficient_from_decision

FIXTURES = Path(__file__).parent

ROUTE_PASS_TARGET = 0.95
GUARDRAIL_PASS_TARGET = 1.00
REFUSAL_PASS_TARGET = 1.00


# ---------------------------------------------------------------------------
# Fixtures — load once per session to keep the slow chat.py import amortized.
# ---------------------------------------------------------------------------


def _load_cases(filename: str) -> list[dict[str, Any]]:
    data = json.loads((FIXTURES / filename).read_text())
    return data["cases"]


@pytest.fixture(scope="session")
def real_detectors() -> dict[str, Any]:
    """Bind the real chat.py detectors once per test session."""
    from api.routes.chat import (
        _chart_context_from_turn_history,
        _detect_aquifer,
        _detect_location,
        _detect_locations,
        _detect_site_names,
        _is_contextual_followup,
        _is_multi_location_compare_query,
        _is_network_wide_query,
        _kb_topic_matches,
        _should_prefer_chart_context,
    )

    return {
        "should_prefer_chart_context": _should_prefer_chart_context,
        "is_contextual_followup": _is_contextual_followup,
        "chart_context_from_turn_history": _chart_context_from_turn_history,
        "detect_site_names": _detect_site_names,
        "detect_aquifer": _detect_aquifer,
        "detect_locations": _detect_locations,
        "is_multi_location_compare_query": _is_multi_location_compare_query,
        "detect_location": _detect_location,
        "is_network_wide_query": _is_network_wide_query,
        "kb_topic_matches": _kb_topic_matches,
    }


# ---------------------------------------------------------------------------
# Route-accuracy matrix
# ---------------------------------------------------------------------------


class TestRoutingMatrix:
    def test_route_mode_accuracy_meets_target(self, real_detectors):
        cases = _load_cases("routing_cases.json")
        failures: list[str] = []
        for case in cases:
            decision = resolve_route(case["question"], None, [], detectors=real_detectors)
            if decision.route_mode != case["expected_route_mode"]:
                failures.append(
                    f"{case['id']}: expected {case['expected_route_mode']!r} "
                    f"got {decision.route_mode!r} for {case['question']!r}"
                )
        pass_rate = 1.0 - (len(failures) / len(cases))
        assert pass_rate >= ROUTE_PASS_TARGET, (
            f"route_mode pass rate {pass_rate:.1%} below target "
            f"{ROUTE_PASS_TARGET:.0%}. Failures:\n" + "\n".join(failures)
        )

    def test_intent_accuracy_reported_but_not_gated(self, real_detectors):
        """Intent is finer-grained than route_mode — we track drift, don't gate on it."""
        cases = _load_cases("routing_cases.json")
        mismatches: list[str] = []
        for case in cases:
            decision = resolve_route(case["question"], None, [], detectors=real_detectors)
            if decision.intent != case["expected_intent"]:
                mismatches.append(
                    f"{case['id']}: intent {decision.intent!r} != expected "
                    f"{case['expected_intent']!r} (route_mode {decision.route_mode!r} "
                    f"for {case['question']!r})"
                )
        # Informational — no assertion. If every intent is wrong that's a real
        # signal; the test_route_mode gate will have caught it by then.
        if mismatches:
            print(f"\n[intent drift — {len(mismatches)}/{len(cases)}]")
            for line in mismatches:
                print(f"  {line}")

    def test_every_route_mode_has_at_least_one_case(self):
        """Regression guard: the matrix must cover every canonical route_mode."""
        cases = _load_cases("routing_cases.json")
        covered = {case["expected_route_mode"] for case in cases}
        # The matrix uses resolve_route, which emits 6 of the 8 canonical modes.
        # CHART_FOLLOWUP needs prior turn history; RESEARCH needs an LLM to be
        # available; INTERPRETATION is applied by /api/interpret *after* the
        # resolver runs. All three are covered by unit tests instead.
        required = RouteMode.ALL - {
            RouteMode.RESEARCH,
            RouteMode.CHART_FOLLOWUP,
            RouteMode.INTERPRETATION,
        }
        missing = required - covered
        assert not missing, f"routing matrix missing coverage for: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Guardrail matrix (numeric / site-ID / year policy)
# ---------------------------------------------------------------------------


class TestGuardrailMatrix:
    def test_validator_flags_match_fixtures(self):
        cases = _load_cases("guardrail_cases.json")
        failures: list[str] = []
        for case in cases:
            answer = GroundedAnswer(**case["evidence"])
            actual = sorted(validate_explanation(case["narrative"], answer))
            expected = sorted(case["expected_violations"])
            if actual != expected:
                failures.append(
                    f"{case['id']}: expected {expected} got {actual} "
                    f"for narrative {case['narrative']!r}"
                )
        pass_rate = 1.0 - (len(failures) / len(cases))
        assert pass_rate >= GUARDRAIL_PASS_TARGET, (
            f"guardrail pass rate {pass_rate:.1%} below target "
            f"{GUARDRAIL_PASS_TARGET:.0%}. Failures:\n" + "\n".join(failures)
        )


# ---------------------------------------------------------------------------
# Refusal matrix (UNSUPPORTED → insufficient answer)
# ---------------------------------------------------------------------------


class TestRefusalMatrix:
    def test_unsupported_questions_produce_refusal(self, real_detectors):
        cases = _load_cases("refusal_cases.json")
        failures: list[str] = []
        for case in cases:
            decision = resolve_route(case["question"], None, [], detectors=real_detectors)
            if decision.route_mode != RouteMode.UNSUPPORTED:
                failures.append(
                    f"{case['id']}: expected UNSUPPORTED got {decision.route_mode!r} "
                    f"for {case['question']!r}"
                )
                continue
            if decision.unsupported_reason != case["expected_reason"]:
                failures.append(
                    f"{case['id']}: expected reason {case['expected_reason']!r} "
                    f"got {decision.unsupported_reason!r}"
                )
                continue
            answer = build_insufficient_from_decision(decision, question=case["question"])
            if answer is None:
                failures.append(f"{case['id']}: build_insufficient_from_decision returned None")
                continue
            if answer.grounding_status != case["expected_grounding_status"]:
                failures.append(
                    f"{case['id']}: expected grounding_status "
                    f"{case['expected_grounding_status']!r} got {answer.grounding_status!r}"
                )
        pass_rate = 1.0 - (len(failures) / len(cases))
        assert pass_rate >= REFUSAL_PASS_TARGET, (
            f"refusal pass rate {pass_rate:.1%} below target "
            f"{REFUSAL_PASS_TARGET:.0%}. Failures:\n" + "\n".join(failures)
        )

    def test_every_refusal_reason_covered(self):
        cases = _load_cases("refusal_cases.json")
        reasons = {case["expected_reason"] for case in cases}
        assert "out_of_scope_geography" in reasons
        assert "future_prediction" in reasons

    def test_refused_answers_short_circuit_explainer(self):
        """Sanity check: every refusal case's grounding_status is in {refused, insufficient}."""
        for case in _load_cases("refusal_cases.json"):
            status = case["expected_grounding_status"]
            assert status in {GroundingStatus.REFUSED, GroundingStatus.INSUFFICIENT}
