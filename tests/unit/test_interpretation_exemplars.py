"""Tests for the interpretation exemplar loader."""

from __future__ import annotations

import json

import pytest

from api.routes.answering.reasoning import _load_interpretation_exemplars


@pytest.fixture(autouse=True)
def _clear_exemplar_cache():
    _load_interpretation_exemplars.cache_clear()
    yield
    _load_interpretation_exemplars.cache_clear()


def test_loader_returns_dict_keyed_by_intent():
    exemplars = _load_interpretation_exemplars()
    assert isinstance(exemplars, dict)
    # Registry shipped in Task 1 has these four buckets.
    assert {"general", "comparison", "supply", "trend"}.issubset(exemplars.keys())
    assert all(isinstance(v, list) for v in exemplars.values())


def test_loader_returns_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "api.routes.answering.reasoning._INTERPRETATION_EXEMPLARS_PATH",
        tmp_path / "missing.json",
    )
    _load_interpretation_exemplars.cache_clear()
    assert _load_interpretation_exemplars() == {}


def test_loader_returns_empty_when_json_malformed(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    monkeypatch.setattr(
        "api.routes.answering.reasoning._INTERPRETATION_EXEMPLARS_PATH",
        bad,
    )
    _load_interpretation_exemplars.cache_clear()
    assert _load_interpretation_exemplars() == {}


def test_loader_skips_entries_missing_required_keys(tmp_path, monkeypatch):
    f = tmp_path / "ex.json"
    f.write_text(
        json.dumps(
            {
                "general": [
                    {"question": "ok", "answer": "ok", "why": "n/a"},
                    {"question": "missing answer"},
                    {"answer": "missing question"},
                ]
            }
        )
    )
    monkeypatch.setattr(
        "api.routes.answering.reasoning._INTERPRETATION_EXEMPLARS_PATH",
        f,
    )
    _load_interpretation_exemplars.cache_clear()
    out = _load_interpretation_exemplars()
    assert len(out["general"]) == 1
    assert out["general"][0]["question"] == "ok"
