"""Phase 0 contract tests — every chat payload carries the canonical triad."""

from __future__ import annotations

import pytest

from api.routes._answer_contract import (
    AnswerType,
    GroundingStatus,
    RouteMode,
    canonical_route_mode,
    derive_answer_type,
    derive_grounding_status,
    stamp_contract_fields,
)


class TestRouteModeMapping:
    def test_known_internal_modes_map_to_canonical(self):
        assert canonical_route_mode("site_fallback") == RouteMode.EXACT_WELL
        assert canonical_route_mode("aquifer_fallback") == RouteMode.COHORT
        assert canonical_route_mode("location_fallback") == RouteMode.COHORT
        assert canonical_route_mode("chart_interpreter") == RouteMode.CHART_FOLLOWUP
        assert canonical_route_mode("deep_research") == RouteMode.RESEARCH
        assert canonical_route_mode("fallback") == RouteMode.FALLBACK

    def test_interpret_prefix_collapses_to_interpretation(self):
        assert canonical_route_mode("interpret_site_fallback") == RouteMode.INTERPRETATION
        assert canonical_route_mode("interpret_chart_interpreter") == RouteMode.INTERPRETATION
        assert canonical_route_mode("interpret_anything") == RouteMode.INTERPRETATION

    def test_unknown_modes_default_to_fallback(self):
        assert canonical_route_mode(None) == RouteMode.FALLBACK
        assert canonical_route_mode("") == RouteMode.FALLBACK
        assert canonical_route_mode("something_new") == RouteMode.FALLBACK


class TestAnswerTypeDerivation:
    def test_no_evidence_returns_insufficient(self):
        payload = {"response": "I'm not sure.", "chart": None, "wells": []}
        assert derive_answer_type(payload) == AnswerType.INSUFFICIENT_EVIDENCE

    def test_evidence_only_is_data_answer(self):
        payload = {
            "chart": {"title": "x"},
            "wells": [{"site_id": "G-3336"}],
            "claim_citations": [{"claim": "c", "citations": []}],
        }
        assert derive_answer_type(payload) == AnswerType.DATA_ANSWER

    def test_evidence_plus_narrative_is_interpretation(self):
        payload = {
            "wells": [{"site_id": "G-3336"}],
            "llm_synthesis": "Narrative about the trend...",
        }
        assert derive_answer_type(payload) == AnswerType.INTERPRETATION_ANSWER

    def test_interpretation_response_counts_as_narrative(self):
        payload = {
            "wells": [{"site_id": "G-3336"}],
            "interpretation_response": {"interpretation": "..."},
        }
        assert derive_answer_type(payload) == AnswerType.INTERPRETATION_ANSWER


class TestGroundingStatusDerivation:
    def test_explicit_string_is_honored(self):
        payload = {
            "wells": [{"site_id": "X"}],
            "interpretation_response": {"grounding_status": "refused"},
        }
        assert derive_grounding_status(payload) == GroundingStatus.REFUSED

    def test_citation_integrity_passed_yields_grounded(self):
        payload = {
            "wells": [{"site_id": "X"}],
            "citation_integrity": {"passed": True},
        }
        assert derive_grounding_status(payload) == GroundingStatus.GROUNDED

    def test_no_evidence_yields_insufficient(self):
        assert derive_grounding_status({}) == GroundingStatus.INSUFFICIENT

    def test_evidence_without_integrity_yields_partial(self):
        payload = {"wells": [{"site_id": "X"}]}
        assert derive_grounding_status(payload) == GroundingStatus.PARTIAL


class TestStampContractFields:
    def test_stamps_all_three_fields(self):
        payload = {
            "mode": "site_fallback",
            "wells": [{"site_id": "G-3336"}],
            "citation_integrity": {"passed": True},
        }
        stamp_contract_fields(payload)
        assert payload["answer_type"] == AnswerType.DATA_ANSWER
        assert payload["route_mode"] == RouteMode.EXACT_WELL
        assert payload["grounding_status"] == GroundingStatus.GROUNDED

    def test_is_idempotent(self):
        payload = {
            "mode": "site_fallback",
            "wells": [{"site_id": "G-3336"}],
            "answer_type": AnswerType.INTERPRETATION_ANSWER,
            "route_mode": RouteMode.INTERPRETATION,
            "grounding_status": GroundingStatus.PARTIAL,
        }
        stamp_contract_fields(payload)
        assert payload["answer_type"] == AnswerType.INTERPRETATION_ANSWER
        assert payload["route_mode"] == RouteMode.INTERPRETATION
        assert payload["grounding_status"] == GroundingStatus.PARTIAL

    def test_force_recomputes(self):
        payload = {
            "mode": "interpret_site_fallback",
            "wells": [{"site_id": "G-3336"}],
            "answer_type": AnswerType.DATA_ANSWER,
            "route_mode": RouteMode.EXACT_WELL,
            "grounding_status": GroundingStatus.PARTIAL,
        }
        stamp_contract_fields(payload, force=True)
        assert payload["route_mode"] == RouteMode.INTERPRETATION

    def test_insufficient_evidence_is_stamped(self):
        payload = {"mode": "fallback", "response": "I don't know."}
        stamp_contract_fields(payload)
        assert payload["answer_type"] == AnswerType.INSUFFICIENT_EVIDENCE
        assert payload["route_mode"] == RouteMode.FALLBACK
        assert payload["grounding_status"] == GroundingStatus.INSUFFICIENT


@pytest.mark.parametrize(
    "mode,expected_route",
    [
        ("site_fallback", RouteMode.EXACT_WELL),
        ("aquifer_fallback", RouteMode.COHORT),
        ("location_fallback", RouteMode.COHORT),
        ("multi_location_fallback", RouteMode.COHORT),
        ("network_fallback", RouteMode.NETWORK),
        ("chart_interpreter", RouteMode.CHART_FOLLOWUP),
        ("deep_research", RouteMode.RESEARCH),
        ("fallback", RouteMode.FALLBACK),
        ("interpret_chart_interpreter", RouteMode.INTERPRETATION),
    ],
)
def test_every_documented_mode_has_canonical_route(mode, expected_route):
    assert canonical_route_mode(mode) == expected_route
