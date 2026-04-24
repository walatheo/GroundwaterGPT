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


from api.routes import _grounded_reasoning as gr  # noqa: E402
from api.routes._grounded_reasoning import _build_intent_specific_prompt  # noqa: E402


def test_intent_block_renders_worked_examples():
    gr._load_interpretation_exemplars.cache_clear()
    block = _build_intent_specific_prompt("general")
    assert "### Worked example" in block
    # The first general exemplar in the shipped registry mentions Estero.
    assert "Estero" in block


def test_intent_block_includes_intent_specific_paragraph_for_supply():
    gr._load_interpretation_exemplars.cache_clear()
    block = _build_intent_specific_prompt("supply")
    assert "regulatory authority" in block.lower()


def test_intent_block_includes_intent_specific_paragraph_for_comparison():
    gr._load_interpretation_exemplars.cache_clear()
    block = _build_intent_specific_prompt("comparison")
    assert "largest gap" in block.lower()


def test_intent_block_empty_when_registry_empty(tmp_path, monkeypatch):
    empty = tmp_path / "empty.json"
    empty.write_text("{}")
    monkeypatch.setattr(gr, "_INTERPRETATION_EXEMPLARS_PATH", empty)
    monkeypatch.setattr(gr, "_INTENT_GUIDANCE", {})
    gr._load_interpretation_exemplars.cache_clear()
    assert _build_intent_specific_prompt("general") == ""


def test_intent_block_empty_for_unknown_bucket():
    gr._load_interpretation_exemplars.cache_clear()
    assert _build_intent_specific_prompt("nonsense") == ""
