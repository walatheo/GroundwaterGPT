"""Tests for the GROUNDWATERGPT_LLM_MODEL env override chain."""

from __future__ import annotations

import importlib


def test_groundwatergpt_llm_model_overrides_default(monkeypatch):
    monkeypatch.setenv("GROUNDWATERGPT_LLM_MODEL", "qwen3:32b")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    import src.agent.llm_factory as factory

    importlib.reload(factory)
    assert factory.LLM_CONFIG["model"] == "qwen3:32b"


def test_legacy_llm_model_still_honored(monkeypatch):
    monkeypatch.delenv("GROUNDWATERGPT_LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
    import src.agent.llm_factory as factory

    importlib.reload(factory)
    assert factory.LLM_CONFIG["model"] == "qwen3:8b"


def test_groundwatergpt_takes_precedence(monkeypatch):
    monkeypatch.setenv("GROUNDWATERGPT_LLM_MODEL", "qwen3:32b")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")
    import src.agent.llm_factory as factory

    importlib.reload(factory)
    assert factory.LLM_CONFIG["model"] == "qwen3:32b"


def test_reasoning_providers_use_groundwatergpt_llm_model(monkeypatch):
    monkeypatch.setenv("GROUNDWATERGPT_LLM_MODEL", "qwen3:32b")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("SYNTHESIS_MODEL", raising=False)
    monkeypatch.delenv("GROUNDWATERGPT_REASONING_MODEL", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    from api.routes._grounded_reasoning import _reasoning_providers

    providers = _reasoning_providers()
    assert providers == [("ollama", "qwen3:32b")]
