"""Tests for inline chart payloads in chat/research responses."""

import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.main import app  # noqa: E402
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
                "site_001", "Well A", ["2024-01-01", "2024-02-01", "2024-03-01"], [10.0, 11.0, 12.0]
            ),
            _make_site(
                "site_002", "Well B", ["2024-01-01", "2024-02-01", "2024-03-01"], [30.0, 28.0, 26.0]
            ),
            _make_site(
                "site_003", "Well C", ["2024-01-01", "2024-02-01", "2024-03-01"], [20.0, 20.5, 21.0]
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

    def test_chat_endpoint_returns_chart(self):
        _first_site_id()
        resp = client.post("/api/chat", json={"message": "Estero trends"})
        assert resp.status_code == 200
        body = resp.json()
        assert "chart" in body
        assert body["chart"] is not None
        assert "series" in body["chart"]
        assert "insights" in body["chart"]
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
        assert len(body["chart"]["data"]) > 0
