"""Tests for research workbench analysis and API route."""

import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.main import app  # noqa: E402
from api.routes import _research_workbench as workbench  # noqa: E402

client = TestClient(app)


def _site_df(start: str, periods: int, *, freq: str = "D", base: float = 10.0, step: float = 0.1):
    dates = pd.date_range(start=start, periods=periods, freq=freq)
    values = [base + step * idx for idx in range(len(dates))]
    return pd.DataFrame({"datetime": dates, "value": values})


@pytest.fixture
def synthetic_workbench_data(monkeypatch):
    """Install synthetic site metadata and loaders for workbench tests."""
    data_map = {
        "site_001": _site_df("2024-01-01", 366, base=10.0, step=0.02),
        "site_002": _site_df("2024-01-01", 366, base=20.0, step=-0.015),
    }

    def fake_load_site_data(site_id):
        return data_map[site_id].copy()

    monkeypatch.setattr(workbench, "load_site_data", fake_load_site_data)
    monkeypatch.setitem(
        workbench.SITE_METADATA,
        "site_001",
        {
            "id": "site_001",
            "name": "Well A",
            "county": "Lee",
            "aquifer": "Surficial Aquifer",
            "confined": False,
        },
    )
    monkeypatch.setitem(
        workbench.SITE_METADATA,
        "site_002",
        {
            "id": "site_002",
            "name": "Well B",
            "county": "Lee",
            "aquifer": "Surficial Aquifer",
            "confined": False,
        },
    )
    return data_map


class TestResearchWorkbenchHelper:
    """Tests for the analysis helper used by the workbench API."""

    def test_build_research_workbench_payload_returns_required_sections(
        self, synthetic_workbench_data
    ):
        payload = workbench.build_research_workbench_payload(
            site_ids=["site_001", "site_002"],
            filters={"county": ["Lee"], "aquifer": [], "confined": None},
            date_window={"preset": "full_record"},
            aggregation="monthly",
            normalization="raw",
        )

        assert payload["status"] == "ok"
        assert payload["mode"] == "research_workbench"
        assert len(payload["resolved_sites"]) == 2
        assert payload["primary_chart"]["chart_type"] == "comparison"
        assert payload["chart_specs"]
        assert payload["metrics_table"]
        assert payload["methods"]["normalization_applies_to_chart_only"] is True
        assert "series_csv" in payload["export_bundle"]
        assert "metrics_csv" in payload["export_bundle"]
        assert "methods_json" in payload["export_bundle"]

    @pytest.mark.parametrize(
        ("aggregation", "expected_rows"),
        [("monthly", 12), ("quarterly", 4), ("annual", 1)],
    )
    def test_aggregation_changes_primary_chart_row_count(
        self, synthetic_workbench_data, aggregation, expected_rows
    ):
        payload = workbench.build_research_workbench_payload(
            site_ids=["site_001", "site_002"],
            filters={},
            date_window={"preset": "full_record"},
            aggregation=aggregation,
            normalization="raw",
        )

        assert len(payload["primary_chart"]["data"]) == expected_rows
        assert all(row["record_count"] == expected_rows for row in payload["metrics_table"])

    def test_normalization_changes_chart_not_metrics(self, synthetic_workbench_data):
        raw_payload = workbench.build_research_workbench_payload(
            site_ids=["site_001", "site_002"],
            filters={},
            date_window={"preset": "full_record"},
            aggregation="monthly",
            normalization="raw",
        )
        delta_payload = workbench.build_research_workbench_payload(
            site_ids=["site_001", "site_002"],
            filters={},
            date_window={"preset": "full_record"},
            aggregation="monthly",
            normalization="delta_from_first",
        )

        assert raw_payload["metrics_table"] == delta_payload["metrics_table"]
        assert (
            raw_payload["primary_chart"]["data"][0]["site_001"]
            != delta_payload["primary_chart"]["data"][0]["site_001"]
        )


class TestResearchWorkbenchEndpoint:
    """Tests for POST /api/research/workbench."""

    def test_endpoint_returns_200_with_valid_payload(self, synthetic_workbench_data):
        resp = client.post(
            "/api/research/workbench",
            json={
                "site_ids": ["site_001", "site_002"],
                "filters": {"county": ["Lee"]},
                "date_window": {"preset": "full_record"},
                "aggregation": "monthly",
                "normalization": "raw",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "research_workbench"
        assert len(body["metrics_table"]) == 2

    def test_custom_window_missing_bound_returns_400(self, synthetic_workbench_data):
        resp = client.post(
            "/api/research/workbench",
            json={
                "site_ids": ["site_001"],
                "date_window": {"preset": "custom", "start_date": "2024-01-01"},
                "aggregation": "monthly",
                "normalization": "raw",
            },
        )

        assert resp.status_code == 400

    def test_malformed_dates_return_400(self, synthetic_workbench_data):
        resp = client.post(
            "/api/research/workbench",
            json={
                "site_ids": ["site_001"],
                "date_window": {
                    "preset": "custom",
                    "start_date": "2024-01-01",
                    "end_date": "not-a-date",
                },
                "aggregation": "monthly",
                "normalization": "raw",
            },
        )

        assert resp.status_code == 400

    def test_more_than_eight_sites_returns_400(self, synthetic_workbench_data):
        resp = client.post(
            "/api/research/workbench",
            json={
                "site_ids": [f"site_{idx:03d}" for idx in range(1, 10)],
                "date_window": {"preset": "full_record"},
                "aggregation": "monthly",
                "normalization": "raw",
            },
        )

        assert resp.status_code == 400

    def test_empty_after_filter_returns_404(self, synthetic_workbench_data):
        resp = client.post(
            "/api/research/workbench",
            json={
                "site_ids": ["site_001"],
                "date_window": {
                    "preset": "custom",
                    "start_date": "2030-01-01",
                    "end_date": "2030-12-31",
                },
                "aggregation": "monthly",
                "normalization": "raw",
            },
        )

        assert resp.status_code == 404
