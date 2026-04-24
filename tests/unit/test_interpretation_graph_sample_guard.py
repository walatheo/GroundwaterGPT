"""Tests for the 32B sample-count guard in the LangGraph interpreter."""

from __future__ import annotations

import pytest

from src.agent import interpretation_graph as ig


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("qwen3:8b", 3),
        ("qwen3:32b", 2),
        ("qwen3:32b-instruct", 2),
        ("qwen2.5:7b", 3),
    ],
)
def test_effective_sample_count_caps_for_32b_models(model_id, expected):
    assert ig._effective_sample_count(3, model_id) == expected


def test_effective_sample_count_respects_explicit_lower_request():
    # Caller explicitly asked for 1 — never widen it for any model.
    assert ig._effective_sample_count(1, "qwen3:32b") == 1
