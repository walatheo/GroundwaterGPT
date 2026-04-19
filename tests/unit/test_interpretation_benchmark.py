"""Tests for the interpretation benchmark suite expansion."""

import json
from pathlib import Path

from scripts.run_interpretation_benchmark import _expand_case_suite


def test_benchmark_suite_expands_to_at_least_100_cases():
    cases_path = Path("tests/benchmark/interpretation_eval_cases.json")
    cases = json.loads(cases_path.read_text())

    expanded = _expand_case_suite(cases, minimum=100)
    questions = {str(case.get("question", "")).strip().lower() for case in expanded}

    assert len(expanded) >= 100
    assert (
        "why is upper floridan the most stressed supply unit in this dataset?".lower() in questions
    )
    assert "on g-3764, what matters most in this chart and why?".lower() in questions
    assert "why do lee l-1998 and lee l-729 diverge?".lower() in questions
    assert "explain what matters most in this chart, not just the rates.".lower() in questions


def test_failure_case_preserves_hidden_semantic_expectations():
    cases_path = Path("tests/benchmark/interpretation_eval_cases.json")
    cases = json.loads(cases_path.read_text())

    expanded = _expand_case_suite(cases, minimum=100)
    target = next(case for case in expanded if case.get("id") == "INT_failure_lee_divergence_pair")

    assert target["expected_scope_type"] == "cross_well"
    assert "Lee L-1998" in target["expected_focus_entities"]
    assert "Lee L-729" in target["expected_focus_entities"]
    assert "shallow_deep_comparison" in target["forbidden_question_intents"]
