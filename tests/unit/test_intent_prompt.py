"""Tests for intent classification + intent-specific prompt block."""

from __future__ import annotations

from api.routes._grounded_reasoning import GroundedFraming, _classify_intent_bucket


def _frame(scope: str, goal: str) -> GroundedFraming:
    return GroundedFraming(scope_type=scope, question_goal=goal)


def test_supply_scope_routes_to_supply_bucket():
    assert _classify_intent_bucket(_frame("supply_unit", "source_proxy")) == "supply"


def test_compare_goal_routes_to_comparison_bucket():
    assert _classify_intent_bucket(_frame("well", "compare")) == "comparison"


def test_cross_well_scope_routes_to_comparison_bucket():
    assert _classify_intent_bucket(_frame("cross_well", "explain")) == "comparison"


def test_well_explain_routes_to_trend_bucket():
    assert _classify_intent_bucket(_frame("well", "explain")) == "trend"


def test_aquifer_rank_routes_to_trend_bucket():
    assert _classify_intent_bucket(_frame("aquifer", "rank")) == "trend"


def test_unknown_scope_falls_back_to_general():
    assert _classify_intent_bucket(_frame("unknown", "general")) == "general"
