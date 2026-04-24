"""Regression tests for the fallback chart_specs producer."""

from __future__ import annotations

from api.routes._site_analysis import _chart_specs_from_payload


def test_chart_specs_empty_when_no_payload():
    assert _chart_specs_from_payload(None, "Estero") == []


def test_chart_specs_empty_when_payload_has_no_series():
    payload = {"id": "chart-1", "title": "Empty", "series": []}
    assert _chart_specs_from_payload(payload, "Estero") == []


def test_chart_specs_emits_trend_comparison_with_site_ids():
    payload = {
        "id": "estero-monthly",
        "title": "Estero Monthly Groundwater Levels",
        "series": [
            {"key": "263335081394301", "name": "L-1"},
            {"key": "262538082045701", "name": "L-2"},
            {"key": "", "name": "skip-me"},
        ],
    }

    specs = _chart_specs_from_payload(payload, "Estero")

    assert len(specs) == 1
    spec = specs[0]
    assert spec["id"] == "trend-comparison"
    assert spec["kind"] == "trend_comparison"
    assert spec["site_ids"] == ["263335081394301", "262538082045701"]
    assert spec["chart_ref"] == "estero-monthly"
    assert spec["title"] == "Estero Monthly Groundwater Levels"
    assert "Estero" in spec["description"]


def test_chart_specs_falls_back_to_location_title():
    payload = {"id": "x", "series": [{"key": "abc"}]}
    specs = _chart_specs_from_payload(payload, "Lee County")
    assert specs[0]["title"] == "Lee County groundwater trends"


def test_chart_specs_excludes_synthetic_overlay_keys():
    """avg, *_trend, and avg_trend are chart overlays, not real USGS site IDs."""
    payload = {
        "id": "estero-monthly",
        "title": "Estero Monthly Groundwater Levels",
        "series": [
            {"key": "263335081394301", "name": "L-1"},
            {"key": "avg", "name": "Cohort Average"},
            {"key": "avg_trend", "name": "Cohort Trend"},
            {"key": "263335081394301_trend", "name": "L-1 Trend"},
            {"key": "262538082045701", "name": "L-2"},
        ],
    }

    specs = _chart_specs_from_payload(payload, "Estero")

    assert len(specs) == 1
    assert specs[0]["site_ids"] == ["263335081394301", "262538082045701"]


def test_chart_specs_returns_empty_when_only_synthetic_series():
    payload = {
        "id": "x",
        "series": [
            {"key": "avg"},
            {"key": "avg_trend"},
        ],
    }
    assert _chart_specs_from_payload(payload, "Estero") == []
