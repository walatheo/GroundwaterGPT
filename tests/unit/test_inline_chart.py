"""Tests for inline chart payloads in chat/research responses."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.main import app  # noqa: E402
from api.routes import chat as chat_routes  # noqa: E402
from api.routes._agent_chart_hook import attach_chart_from_agent_result  # noqa: E402
from api.routes._site_analysis import (  # noqa: E402
    _build_chart_payload,
    _cross_well_analysis,
    _site_research_fallback,
)
from api.site_metadata import SITE_METADATA  # noqa: E402

client = TestClient(app)


def _make_site(site_id: str, name: str, dates: list[str], values: list[float]) -> dict:
    return {
        "site_id": site_id,
        "name": name,
        "county": "Test",
        "aquifer": "Test Aquifer",
        "aquifer_type": "unconfined",
        "confined": False,
        "aquifer_zone": "Test Zone",
        "aquifer_zone_depth_range_ft": [10, 50],
        "aquifer_description": "Synthetic test aquifer.",
        "well_depth_ft": 25.0,
        "lat": 26.0,
        "lng": -81.0,
        "series": pd.DataFrame(
            {
                "datetime": pd.to_datetime(dates),
                "value": values,
            }
        ),
    }


def _first_site_id():
    data_dir = Path(__file__).parent.parent.parent / "data"
    for sid in SITE_METADATA:
        if (data_dir / f"usgs_{sid}.csv").exists():
            return sid
    pytest.skip("No site CSV files on disk")


def _first_two_site_ids():
    data_dir = Path(__file__).parent.parent.parent / "data"
    site_ids = [sid for sid in SITE_METADATA if (data_dir / f"usgs_{sid}.csv").exists()]
    if len(site_ids) < 2:
        pytest.skip("Need at least two site CSV files on disk")
    return site_ids[:2]


class TestBuildChartPayload:
    def test_build_chart_payload_single_site(self):
        site = _make_site(
            "site_001",
            "Test Well A",
            ["2024-01-01", "2024-02-01", "2024-03-01"],
            [10.0, 11.0, 12.0],
        )

        chart = _build_chart_payload([site], "Test Area")

        assert chart is not None
        assert chart["chart_type"] == "time_series"
        assert len(chart["series"]) == 1
        assert chart["series"][0]["key"] == "site_001"
        assert all("avg" not in row for row in chart["data"])

    def test_build_chart_payload_multiple_has_avg(self):
        sites = [
            _make_site("site_001", "Well A", ["2024-01-01", "2024-02-01"], [10.0, 20.0]),
            _make_site("site_002", "Well B", ["2024-01-01", "2024-02-01"], [20.0, 30.0]),
            _make_site("site_003", "Well C", ["2024-01-01", "2024-02-01"], [30.0, 40.0]),
        ]

        chart = _build_chart_payload(sites, "Test Area")

        assert chart is not None
        assert chart["chart_type"] == "comparison"
        avg_series = next(series for series in chart["series"] if series["key"] == "avg")
        assert avg_series["strokeDasharray"] == "5 5"
        assert chart["data"][0]["avg"] == 20.0
        assert chart["data"][1]["avg"] == 30.0

    def test_build_chart_payload_adds_trend_and_insights(self):
        sites = [
            _make_site(
                "site_001",
                "Well A",
                ["2024-01-01", "2024-02-01", "2024-03-01"],
                [10.0, 11.0, 12.0],
            ),
            _make_site(
                "site_002",
                "Well B",
                ["2024-01-01", "2024-02-01", "2024-03-01"],
                [30.0, 28.0, 26.0],
            ),
            _make_site(
                "site_003",
                "Well C",
                ["2024-01-01", "2024-02-01", "2024-03-01"],
                [20.0, 20.5, 21.0],
            ),
        ]

        cross_well = _cross_well_analysis(sites)
        chart = _build_chart_payload(sites, "Test Area", cross_well=cross_well)

        assert chart is not None
        series_keys = {series["key"] for series in chart["series"]}
        assert "avg_trend" in series_keys
        assert "site_001_trend" in series_keys or "site_002_trend" in series_keys
        assert chart["cohort_risk_level"] in {"low", "moderate", "high"}
        assert chart["insights"]
        assert len(chart["insights"]) == 5
        assert chart["explainability"]["summary"]
        assert chart["explainability"]["how_to_read"]
        assert chart["explainability"]["student_prompts"]
        assert "LLM" in chart["explainability"]["llm_role"]
        assert any("Highlighted wells mark" in insight for insight in chart["insights"])
        assert any(
            series.get("highlight") for series in chart["series"] if not series.get("isTrend")
        )
        assert any("avg_trend" in row for row in chart["data"])

    def test_build_chart_payload_monthly_resampling(self):
        dates = pd.date_range("2025-01-01", "2025-12-31", freq="D")
        values = [float(i % 30) for i in range(len(dates))]
        site = _make_site(
            "site_001",
            "Daily Well",
            [d.strftime("%Y-%m-%d") for d in dates],
            values,
        )

        chart = _build_chart_payload([site], "Daily Area")

        assert chart is not None
        assert 12 <= len(chart["data"]) <= 13
        assert chart["data"][0]["date"].endswith("-01")

    def test_build_chart_payload_empty(self):
        assert _build_chart_payload([], "Nowhere") is None

    def test_build_chart_payload_surfaces_missing_metric_keys(self):
        sites = [
            _make_site("site_001", "Well A", ["2024-01-01", "2024-02-01"], [10.0, 9.0]),
            _make_site("site_002", "Well B", ["2024-01-01", "2024-02-01"], [10.0, 11.0]),
        ]
        broken_cross_well = {
            "per_site_metrics": [
                {"site_id": "site_001", "name": "Well A"},
                {"site_id": "site_002", "name": "Well B"},
            ],
            "divergent_pairs": [],
            "risk_level": "low",
            "cohort_trend": "stable",
            "n_total": 2,
        }

        with pytest.raises(KeyError):
            _build_chart_payload(sites, "Test Area", cross_well=broken_cross_well)

    def test_cross_well_analysis_adds_changepoints_and_clusters(self):
        dates = pd.date_range("2020-01-01", periods=60, freq="MS")
        date_labels = [date.strftime("%Y-%m-%d") for date in dates]
        sites = [
            _make_site(
                "site_001",
                "Step Change Well",
                date_labels,
                [10.0 + idx * 0.01 if idx < 30 else 10.3 + (idx - 30) * 0.18 for idx in range(60)],
            ),
            _make_site(
                "site_002",
                "Recovery Well",
                date_labels,
                [20.0 - idx * 0.04 for idx in range(60)],
            ),
            _make_site(
                "site_003",
                "Seasonal Stable Well",
                date_labels,
                [15.0 + (1.5 if idx % 12 in {5, 6, 7, 8, 9} else 0.0) for idx in range(60)],
            ),
        ]

        cross_well = _cross_well_analysis(sites)

        assert cross_well["changepoints"]
        assert cross_well["changepoints"][0]["detected"] is True
        assert cross_well["clusters"]
        assert sum(cluster["n_sites"] for cluster in cross_well["clusters"]) == 3


class TestInlineChartIntegration:
    def test_site_research_fallback_includes_chart(self):
        sites = [
            _make_site("site_001", "Well A", ["2024-01-01", "2024-02-01"], [10.0, 11.0]),
            _make_site("site_002", "Well B", ["2024-01-01", "2024-02-01"], [12.0, 13.0]),
        ]

        result = _site_research_fallback("compare the wells", sites, "Synthetic Area")

        assert "chart" in result
        assert result["chart"] is not None
        assert any(series["key"] == "avg" for series in result["chart"]["series"])
        assert result["chart"]["insights"]
        assert result["chart"]["explainability"]["data_contract"]

    def test_site_research_fallback_llm_synthesis_cites_chart_context(self, monkeypatch):
        sites = [
            _make_site("site_001", "Well A", ["2024-01-01", "2024-02-01"], [10.0, 11.0]),
            _make_site("site_002", "Well B", ["2024-01-01", "2024-02-01"], [12.0, 13.0]),
        ]

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "response": (
                        "The chart shows monthly USGS means and a cohort trend. "
                        "Students should compare the highlighted wells with the cohort average."
                    )
                }

        def _fake_post(*_args, **_kwargs):
            return _Response()

        import httpx

        monkeypatch.delenv("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", raising=False)
        monkeypatch.setattr(httpx, "post", _fake_post)

        result = _site_research_fallback(
            "interpret sustainability risk from this chart",
            sites,
            "Synthetic Area",
        )

        llm_claims = [
            claim
            for claim in result["claim_citations"]
            if claim.get("source_type") == "llm_synthesis"
        ]
        assert result["llm_synthesis"]
        assert llm_claims
        assert llm_claims[0]["citations"][0]["source"] == "deterministic_chart_context"
        assert result["hallucination_guardrail"]["all_factual_claims_cited"] is True

    def test_chat_endpoint_returns_chart(self):
        _first_site_id()
        resp = client.post("/api/chat", json={"message": "Estero trends"})
        assert resp.status_code == 200
        body = resp.json()
        assert "chart" in body
        assert body["chart"] is not None
        assert "series" in body["chart"]
        assert "insights" in body["chart"]
        assert "explainability" in body["chart"]
        assert len(body["chart"]["data"]) > 0

    def test_research_endpoint_returns_chart(self):
        _first_site_id()
        resp = client.post("/api/research", json={"question": "Estero trends"})
        assert resp.status_code == 200
        body = resp.json()
        assert "chart" in body
        assert body["chart"] is not None
        assert "series" in body["chart"]
        assert "insights" in body["chart"]
        assert "explainability" in body["chart"]
        assert len(body["chart"]["data"]) > 0

    def test_agent_path_attaches_chart_when_sites_identified(self, monkeypatch):
        site_ids = _first_two_site_ids()
        result = {
            "report": "Agent report",
            "chart_specs": [{"id": "trend-comparison", "site_ids": site_ids}],
            "tool_trace": [],
        }

        attached = attach_chart_from_agent_result(result)

        assert attached["chart"] is not None
        assert len(attached["chart"]["series"]) >= 2
        assert len(attached["chart"]["data"]) > 0

    def test_agent_path_no_sites_leaves_chart_none(self):
        result = {
            "report": "Agent report",
            "chart_specs": [{"id": "trend-comparison"}],
            "tool_trace": [{"tool": "research_router", "details": {"summary": "No sites"}}],
        }

        attached = attach_chart_from_agent_result(result)

        assert attached.get("chart") is None

    def test_streaming_agent_path_yields_chart_in_final_event(self, monkeypatch):
        site_ids = _first_two_site_ids()

        class _StubResearchAgent:
            def research(self, **_kwargs):
                return {
                    "report": "Stubbed agent research response",
                    "insights": [],
                    "sources": [],
                    "session_id": "session_stub",
                    "research_plan": {"main_question": "Compare selected wells"},
                    "budget_status": {"status": "complete", "depth_reached": 1, "max_depth": 1},
                    "checkpoints": [],
                    "tool_trace": [
                        {
                            "tool": "site_selector",
                            "status": "completed",
                            "details": {"site_ids": site_ids},
                        }
                    ],
                    "chart_specs": [{"id": "trend-comparison", "site_ids": site_ids}],
                    "search_history": [],
                    "depth_reached": 1,
                    "elapsed_seconds": 0.1,
                    "claim_citations": [],
                    "claim_verdicts": [],
                    "claim_verdict_summary": {},
                    "citation_summary": {
                        "total_claims": 0,
                        "cited_claims": 0,
                        "citation_coverage": 0.0,
                    },
                    "section_confidence": {},
                    "hallucination_guardrail": {},
                }

        monkeypatch.setattr(chat_routes, "_research_agent", _StubResearchAgent())

        resp = client.post(
            "/api/research/stream",
            json={"question": "Compare selected wells", "max_depth": 1, "timeout": 60},
        )

        assert resp.status_code == 200
        chunks = [line for line in resp.text.split("\n\n") if line.strip().startswith("data:")]
        events = [json.loads(chunk.replace("data:", "", 1).strip()) for chunk in chunks]
        final = next(event for event in events if event.get("type") == "result")

        assert final["chart"] is not None
        assert final["chart"]["series"]
        assert final["chart"]["data"]

    def test_build_chart_payload_trend_names_have_ft_yr_units(self):
        sites = [
            _make_site(
                "site_001", "Well A", ["2024-01-01", "2024-02-01", "2024-03-01"], [10.0, 11.0, 12.0]
            ),
            _make_site(
                "site_002", "Well B", ["2024-01-01", "2024-02-01", "2024-03-01"], [30.0, 28.0, 26.0]
            ),
        ]

        cross_well = _cross_well_analysis(sites)
        chart = _build_chart_payload(sites, "Test Area", cross_well=cross_well)

        trend_series_names = [series["name"] for series in chart["series"] if series.get("isTrend")]
        assert trend_series_names
        assert all("ft/yr" in name for name in trend_series_names)
