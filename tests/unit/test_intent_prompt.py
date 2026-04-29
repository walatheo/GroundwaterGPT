"""Tests for intent classification + intent-specific prompt block."""

from __future__ import annotations

import pytest

from api.routes.answering import reasoning as gr
from api.routes.answering.reasoning import GroundedFraming, _classify_intent_bucket


@pytest.fixture(autouse=True)
def _clear_exemplar_cache():
    gr._load_interpretation_exemplars.cache_clear()
    yield
    gr._load_interpretation_exemplars.cache_clear()


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


from api.routes.answering.reasoning import _build_intent_specific_prompt  # noqa: E402


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


from api.routes.answering.reasoning import (  # noqa: E402
    _build_multistage_reasoning_prompt,
    _build_raw_evidence_prompt,
)


def _minimal_pack() -> dict:
    return {
        "site_ids": ["A1"],
        "sites": [{"site_id": "A1", "name": "Lee L-100"}],
    }


def test_raw_evidence_prompt_appends_intent_block():
    gr._load_interpretation_exemplars.cache_clear()
    messages = _build_raw_evidence_prompt(
        "Compare Lee L-581 and Lee L-588.",
        _minimal_pack(),
        None,
        None,
    )
    system = messages[0][1]
    # Should still contain the base system prompt header...
    assert "groundwater monitoring interpreter" in system.lower()
    # ...AND the comparison guidance from Task 4.
    assert "largest gap" in system.lower()


def test_multistage_prompt_appends_intent_block():
    gr._load_interpretation_exemplars.cache_clear()
    messages = _build_multistage_reasoning_prompt(
        "Which aquifer supplies Estero?",
        _minimal_pack(),
        None,
        None,
        GroundedFraming(scope_type="supply_unit", question_goal="source_proxy"),
        provider_name="ollama",
        model="qwen3:8b",
    )
    system = messages[0][1]
    assert "regulatory authority" in system.lower()


def test_prompt_unchanged_when_registry_empty(tmp_path, monkeypatch):
    empty = tmp_path / "empty.json"
    empty.write_text("{}")
    monkeypatch.setattr(gr, "_INTERPRETATION_EXEMPLARS_PATH", empty)
    monkeypatch.setattr(gr, "_INTENT_GUIDANCE", {})
    gr._load_interpretation_exemplars.cache_clear()
    messages = _build_raw_evidence_prompt(
        "anything",
        _minimal_pack(),
        None,
        None,
    )
    # Base prompt only, no trailing augmentation.
    assert messages[0][1].rstrip() == gr._RAW_EVIDENCE_SYSTEM_PROMPT.rstrip()
