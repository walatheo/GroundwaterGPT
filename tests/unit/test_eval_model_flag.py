"""CLI wiring tests for the --model flag in run_langchain_eval."""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GROUNDWATERGPT_LLM_MODEL", raising=False)
    yield


def test_model_flag_sets_env_for_run(monkeypatch):
    """When --model is passed, the run sets GROUNDWATERGPT_LLM_MODEL."""
    captured: dict[str, str | None] = {}

    def _fake_load(path, limit):  # type: ignore[no-untyped-def]
        captured["env_at_load_time"] = os.environ.get("GROUNDWATERGPT_LLM_MODEL")
        return []

    sys.path.insert(0, ".")
    import scripts.run_langchain_eval as ev

    monkeypatch.setattr(ev, "_load_cases", _fake_load)
    monkeypatch.setattr(ev, "_get_judge_llm", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run_langchain_eval", "--model", "qwen3:32b"])

    with patch("builtins.print"):
        ev.main()

    assert captured["env_at_load_time"] == "qwen3:32b"


def test_no_model_flag_leaves_env_unset(monkeypatch):
    captured: dict[str, str | None] = {}

    def _fake_load(path, limit):  # type: ignore[no-untyped-def]
        captured["env_at_load_time"] = os.environ.get("GROUNDWATERGPT_LLM_MODEL")
        return []

    import scripts.run_langchain_eval as ev

    monkeypatch.setattr(ev, "_load_cases", _fake_load)
    monkeypatch.setattr(ev, "_get_judge_llm", lambda: None)
    monkeypatch.setattr(sys, "argv", ["run_langchain_eval"])

    with patch("builtins.print"):
        ev.main()

    assert captured["env_at_load_time"] is None
