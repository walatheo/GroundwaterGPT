"""Regression tests for _merge_chart_specs in api.routes.chat.

The research-fallback path emits a lightweight ``trend-comparison`` chart_spec
(site_ids + chart_ref, no renderable ``spec``) that previously shadowed the
renderable ``trend-comparison`` emitted by _build_research_visual_bundle because
_augment_research_payload preserved existing ids first. ResearchChartsPanel
filters to entries with a real ``spec`` object, so the trend tab could
disappear entirely.
"""

from __future__ import annotations

from api.routes.chat import _has_renderable_spec, _merge_chart_specs


def test_renderable_bundle_spec_wins_over_lightweight_ref():
    lightweight = {
        "id": "trend-comparison",
        "site_ids": ["263335081394301"],
        "chart_ref": "estero-monthly",
    }
    renderable = {
        "id": "trend-comparison",
        "kind": "trend_comparison",
        "title": "Trend Comparison",
        "site_ids": ["263335081394301"],
        "spec": {"type": "line", "data": []},
    }

    merged = _merge_chart_specs([lightweight], [renderable])

    assert len(merged) == 1
    assert merged[0] is renderable
    assert _has_renderable_spec(merged[0])


def test_existing_renderable_is_preserved_over_bundle_duplicate():
    existing = {
        "id": "trend-comparison",
        "title": "Custom Trend",
        "spec": {"type": "line", "data": [{"id": "custom"}]},
    }
    bundle = {
        "id": "trend-comparison",
        "title": "Default Trend",
        "spec": {"type": "line", "data": []},
    }

    merged = _merge_chart_specs([existing], [bundle])

    assert merged == [existing]


def test_non_overlapping_bundle_specs_are_appended():
    existing = [{"id": "a", "site_ids": ["x"]}]
    bundle = [
        {"id": "b", "spec": {"type": "bar", "data": []}},
        {"id": "c", "spec": {"type": "line", "data": []}},
    ]

    merged = _merge_chart_specs(existing, bundle)

    assert [spec["id"] for spec in merged] == ["a", "b", "c"]


def test_merge_preserves_existing_order():
    existing = [
        {"id": "alpha", "spec": {"type": "line", "data": []}},
        {"id": "beta", "site_ids": ["x"]},
    ]
    bundle = [
        {"id": "beta", "spec": {"type": "bar", "data": []}},
        {"id": "gamma", "spec": {"type": "scatter", "data": []}},
    ]

    merged = _merge_chart_specs(existing, bundle)

    assert [spec["id"] for spec in merged] == ["alpha", "beta", "gamma"]
    assert _has_renderable_spec(merged[1])


def test_has_renderable_spec_rejects_non_dict_spec():
    assert not _has_renderable_spec({"id": "x", "spec": "line"})
    assert not _has_renderable_spec({"id": "x"})
    assert not _has_renderable_spec(None)
    assert _has_renderable_spec({"id": "x", "spec": {"type": "line"}})
