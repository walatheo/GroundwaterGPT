"""Smoke tests for the LangChain eval harness."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_langchain_eval.py"


@pytest.fixture(scope="module")
def eval_module():
    """Load the script as a module for direct function calls."""
    spec = importlib.util.spec_from_file_location("run_langchain_eval", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_langchain_eval"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def invoke(self, _prompt):
        self.calls += 1
        return json.dumps(self.payload)


def test_criteria_keys_cover_publication_axes(eval_module):
    assert set(eval_module.CRITERIA) == {"grounding", "hedge", "completeness", "clarity"}


def test_score_one_criterion_parses_fake_llm(eval_module):
    llm = _FakeLLM({"score": 0.82, "reasoning": "well grounded"})
    result = eval_module._score_one_criterion(llm, "draft text", "grounding", "desc")
    assert result.score == 0.82
    assert "well grounded" in result.reasoning


def test_score_one_criterion_returns_unavailable_without_llm(eval_module):
    result = eval_module._score_one_criterion(None, "draft", "grounding", "desc")
    assert result.score == 0.0
    assert "unavailable" in result.reasoning.lower()


def test_score_interpretation_handles_empty_draft(eval_module):
    class _Empty:
        direct_answer = ""
        reasoning_steps = []
        limitations = []

    results = eval_module.score_interpretation(_Empty(), None)
    assert len(results) == 4
    assert all(r.score == 0.0 for r in results)


def test_score_interpretation_scores_every_criterion(eval_module):
    class _Draft:
        direct_answer = "Lee L-1 is declining at 0.45 ft/yr per USGS."
        reasoning_steps = []
        limitations = ["no pumping data"]

    llm = _FakeLLM({"score": 0.9, "reasoning": "great"})
    results = eval_module.score_interpretation(_Draft(), llm)
    assert len(results) == 4
    assert {r.name for r in results} == {"grounding", "hedge", "completeness", "clarity"}
    assert all(r.score == 0.9 for r in results)
    assert llm.calls == 4


def test_draft_text_collapses_grounded_interpretation(eval_module):
    class _Step:
        step_label = "observe"
        observation = "l-1 falling"
        inference = "declining"

    class _Draft:
        direct_answer = "L-1 falling"
        why_it_matters = "supply risk"
        what_matters_most = ""
        implications = ""
        reasoning_steps = [_Step()]
        limitations = ["no pumping"]

    text = eval_module._draft_text(_Draft())
    assert "L-1 falling" in text
    assert "supply risk" in text
    assert "step: observe" in text
    assert "limits: no pumping" in text
