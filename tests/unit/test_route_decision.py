"""Phase 1 routing tests — resolve_route produces the correct decision."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from api.routes._answer_contract import RouteMode
from api.routes._route_decision import _detect_unsupported_reason, resolve_route


def _detectors(
    *,
    should_prefer_chart_context: bool = False,
    is_contextual_followup: bool = False,
    recovered_chart: Optional[dict[str, Any]] = None,
    named_sites: Optional[list[dict[str, Any]]] = None,
    aquifer_hit: Optional[tuple[str, str]] = None,
    locations: Optional[list[tuple[float, float, str, Optional[str]]]] = None,
    is_multi_location_compare_query: bool = False,
    location_hit: Optional[tuple[float, float, str, Optional[str]]] = None,
    is_network_wide_query: bool = False,
    kb_matches: Optional[list[tuple[str, str]]] = None,
) -> dict[str, Any]:
    """Build a detector dict with trivial callables for resolve_route."""
    return {
        "should_prefer_chart_context": lambda _q, _c: should_prefer_chart_context,
        "is_contextual_followup": lambda _q: is_contextual_followup,
        "chart_context_from_turn_history": lambda _h: recovered_chart,
        "detect_site_names": lambda _q: named_sites or [],
        "detect_aquifer": lambda _q: aquifer_hit,
        "detect_locations": lambda _q, _n: locations or [],
        "is_multi_location_compare_query": lambda _q: is_multi_location_compare_query,
        "detect_location": lambda _q: location_hit,
        "is_network_wide_query": lambda _q: is_network_wide_query,
        "kb_topic_matches": lambda _q: kb_matches or [],
    }


class TestChartContextRouting:
    def test_caller_chart_context_wins(self):
        ctx = {"chart_id": "x", "site_ids": ["G-3336"]}
        decision = resolve_route(
            "why is this trending down?",
            ctx,
            [],
            detectors=_detectors(should_prefer_chart_context=True),
        )
        assert decision.route_mode == RouteMode.CHART_FOLLOWUP
        assert decision.internal_mode == "chart_interpreter"
        assert decision.chart_context_to_use == ctx
        assert decision.intent == "chart_followup_with_active_chart"

    def test_recovered_chart_context_when_none_supplied(self):
        recovered = {"chart_id": "recovered", "site_ids": ["G-3336"]}
        decision = resolve_route(
            "why is this declining?",
            None,
            [{"site_ids": ["G-3336"]}],
            detectors=_detectors(
                is_contextual_followup=True,
                recovered_chart=recovered,
            ),
        )
        assert decision.route_mode == RouteMode.CHART_FOLLOWUP
        assert decision.chart_context_to_use == recovered
        assert decision.intent == "chart_followup_recovered_from_history"

    def test_no_recovery_when_not_contextual_followup(self):
        decision = resolve_route(
            "compare G-3336 and G-5004",
            None,
            [],
            detectors=_detectors(
                is_contextual_followup=False,
                recovered_chart={"chart_id": "x"},  # should not be used
                named_sites=[{"site_id": "G-3336", "name": "G-3336"}],
            ),
        )
        assert decision.route_mode == RouteMode.EXACT_WELL


class TestDeterministicRouting:
    def test_named_sites_route_to_exact_well(self):
        decision = resolve_route(
            "tell me about G-3336",
            None,
            [],
            detectors=_detectors(
                named_sites=[{"site_id": "G-3336", "name": "G-3336"}],
            ),
        )
        assert decision.route_mode == RouteMode.EXACT_WELL
        assert decision.internal_mode == "site_fallback"
        assert decision.intent == "exact_well_lookup"
        assert len(decision.named_sites) == 1

    def test_aquifer_hit_routes_to_cohort(self):
        decision = resolve_route(
            "how is the Biscayne aquifer?",
            None,
            [],
            detectors=_detectors(aquifer_hit=("biscayne", "Biscayne Aquifer")),
        )
        assert decision.route_mode == RouteMode.COHORT
        assert decision.internal_mode == "aquifer_fallback"
        assert decision.aquifer_hit == ("biscayne", "Biscayne Aquifer")

    def test_multi_location_compare_routes_to_cohort(self):
        decision = resolve_route(
            "compare Estero and Naples",
            None,
            [],
            detectors=_detectors(
                locations=[
                    (26.5, -81.8, "Estero", "Lee"),
                    (26.1, -81.7, "Naples", "Collier"),
                ],
                is_multi_location_compare_query=True,
            ),
        )
        assert decision.route_mode == RouteMode.COHORT
        assert decision.intent == "multi_location_comparison"
        assert decision.is_multi_location is True
        assert len(decision.locations) == 2

    def test_single_location_routes_to_cohort(self):
        decision = resolve_route(
            "wells near Estero",
            None,
            [],
            detectors=_detectors(
                location_hit=(26.5, -81.8, "Estero", "Lee"),
            ),
        )
        assert decision.route_mode == RouteMode.COHORT
        assert decision.location_hit is not None

    def test_network_wide_query(self):
        decision = resolve_route(
            "which county has the most wells?",
            None,
            [],
            detectors=_detectors(is_network_wide_query=True),
        )
        assert decision.route_mode == RouteMode.NETWORK
        assert decision.is_network_wide is True

    def test_kb_match_routes_to_fallback(self):
        decision = resolve_route(
            "how does irrigation affect groundwater?",
            None,
            [],
            detectors=_detectors(kb_matches=[("irrigation", "info")]),
        )
        assert decision.route_mode == RouteMode.FALLBACK
        assert decision.intent == "kb_topic_match"

    def test_open_ended_routes_to_research(self):
        decision = resolve_route(
            "tell me about groundwater science",
            None,
            [],
            detectors=_detectors(),
        )
        assert decision.route_mode == RouteMode.RESEARCH
        assert decision.intent == "open_ended_research"


class TestUnsupportedDetection:
    @pytest.mark.parametrize(
        "question",
        [
            "how's the groundwater in Antarctica?",
            "aquifer levels in Sahara",
            "what about Europe's aquifers",
        ],
    )
    def test_out_of_scope_geography(self, question):
        assert _detect_unsupported_reason(question) == "out_of_scope_geography"

    @pytest.mark.parametrize(
        "question",
        [
            "will it drop next year?",
            "forecast the trend for 2030",
            "should I drill a well here?",
            "predict water levels in 2035",
        ],
    )
    def test_future_prediction(self, question):
        assert _detect_unsupported_reason(question) == "future_prediction"

    def test_in_scope_question_is_none(self):
        assert _detect_unsupported_reason("what does G-3336 show?") is None

    def test_unsupported_upgrades_route_mode_when_no_other_match(self):
        decision = resolve_route(
            "will aquifers fall next year?",
            None,
            [],
            detectors=_detectors(),
        )
        assert decision.route_mode == RouteMode.UNSUPPORTED
        assert decision.intent == "unsupported_question"
        assert decision.unsupported_reason == "future_prediction"

    def test_out_of_scope_with_named_site_still_marked_unsupported(self):
        # Geography refusal overrides the deterministic route.
        decision = resolve_route(
            "tell me about G-3336 in Antarctica",
            None,
            [],
            detectors=_detectors(
                named_sites=[{"site_id": "G-3336", "name": "G-3336"}],
            ),
        )
        assert decision.route_mode == RouteMode.UNSUPPORTED
        assert decision.unsupported_reason == "out_of_scope_geography"
        # But the branch metadata is still available for the handler.
        assert decision.named_sites


class TestToObservable:
    def test_observable_dict_shape(self):
        decision = resolve_route(
            "tell me about G-3336",
            None,
            [],
            detectors=_detectors(
                named_sites=[{"site_id": "G-3336", "name": "G-3336"}],
            ),
        )
        obs = decision.to_observable()
        assert obs["route_mode"] == RouteMode.EXACT_WELL
        assert obs["internal_mode"] == "site_fallback"
        assert obs["named_sites"] == ["G-3336"]
        assert obs["has_chart_context"] is False
        assert obs["is_multi_location"] is False
        assert obs["unsupported_reason"] is None

    def test_observable_reports_chart_context_flag(self):
        decision = resolve_route(
            "why declining?",
            {"chart_id": "x", "site_ids": []},
            [],
            detectors=_detectors(should_prefer_chart_context=True),
        )
        obs = decision.to_observable()
        assert obs["has_chart_context"] is True


class TestOrderingAndPrecedence:
    def test_chart_context_beats_named_sites(self):
        decision = resolve_route(
            "why is G-3336 declining?",
            {"chart_id": "x", "site_ids": ["G-3336"]},
            [],
            detectors=_detectors(
                should_prefer_chart_context=True,
                named_sites=[{"site_id": "G-3336", "name": "G-3336"}],
            ),
        )
        assert decision.route_mode == RouteMode.CHART_FOLLOWUP

    def test_named_sites_beat_aquifer(self):
        decision = resolve_route(
            "G-3336 in Biscayne",
            None,
            [],
            detectors=_detectors(
                named_sites=[{"site_id": "G-3336", "name": "G-3336"}],
                aquifer_hit=("biscayne", "Biscayne"),
            ),
        )
        assert decision.route_mode == RouteMode.EXACT_WELL

    def test_aquifer_beats_location(self):
        decision = resolve_route(
            "Biscayne near Estero",
            None,
            [],
            detectors=_detectors(
                aquifer_hit=("biscayne", "Biscayne"),
                location_hit=(26.5, -81.8, "Estero", "Lee"),
            ),
        )
        assert decision.route_mode == RouteMode.COHORT
        assert decision.aquifer_hit is not None

    def test_multi_location_beats_single_location(self):
        decision = resolve_route(
            "Estero vs Naples",
            None,
            [],
            detectors=_detectors(
                locations=[
                    (26.5, -81.8, "Estero", "Lee"),
                    (26.1, -81.7, "Naples", "Collier"),
                ],
                is_multi_location_compare_query=True,
                location_hit=(26.5, -81.8, "Estero", "Lee"),
            ),
        )
        assert decision.is_multi_location is True
