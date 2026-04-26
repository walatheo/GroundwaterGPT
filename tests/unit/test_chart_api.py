"""Tests for Session 8 — Data Visualization Layer.

Validates:
 • GET  /api/sites/{id}/chart  (single-site Recharts JSON)
 • GET  /api/compare/chart     (multi-site comparison JSON)
 • Chart JSON schema (chart_type, series, data arrays)
 • Rolling average calculation
 • Date filtering
 • Error handling (404 for unknown sites / empty ranges)
"""

import sys
from numbers import Real
from pathlib import Path

import pytest

# Add project root to path so ``api`` package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import SITE_METADATA, app  # noqa: E402

client = TestClient(app)


# Helper — grab the first real site id for data-dependent tests
def _first_site_id():
    """Return the first site_id that has a CSV on disk."""
    data_dir = Path(__file__).parent.parent.parent / "data"
    for sid in SITE_METADATA:
        if (data_dir / f"usgs_{sid}.csv").exists():
            return sid
    pytest.skip("No site CSV files on disk")


# ===================================================================
# GET /api/sites/{id}/chart
# ===================================================================


class TestSiteChartEndpoint:
    """Tests for the single-site chart endpoint."""

    def test_returns_valid_chart_json(self):
        """Chart response contains required keys."""
        sid = _first_site_id()
        resp = client.get(f"/api/sites/{sid}/chart")
        assert resp.status_code == 200
        body = resp.json()
        assert body["chart_type"] == "time_series"
        assert "title" in body
        assert "series" in body
        assert "data" in body
        assert isinstance(body["data"], list)
        assert len(body["data"]) > 0

    def test_series_keys_match_data(self):
        """Every series key should appear in at least one data record."""
        sid = _first_site_id()
        resp = client.get(f"/api/sites/{sid}/chart")
        assert resp.status_code == 200
        body = resp.json()
        keys = {s["key"] for s in body["series"]}
        data_keys = set()
        for row in body["data"]:
            data_keys.update(k for k in row if k != "date")
        missing_keys = keys - data_keys
        assert not missing_keys, f"Series keys missing from chart data: {missing_keys}"

    def test_data_has_date_and_level(self):
        """Each data row has date and level fields."""
        sid = _first_site_id()
        body = client.get(f"/api/sites/{sid}/chart").json()
        for row in body["data"][:5]:
            assert "date" in row
            assert isinstance(row["date"], str)
            assert row["date"]
            assert "level" in row
            assert isinstance(row["level"], Real)

    def test_rolling_avg_present(self):
        """Default rolling average is included after window fills."""
        sid = _first_site_id()
        body = client.get(f"/api/sites/{sid}/chart").json()
        rows = body["data"]
        assert len(rows) >= 30
        assert all("rollingAvg" not in row for row in rows[:29])
        expected = round(sum(row["level"] for row in rows[:30]) / 30, 2)
        assert rows[29]["rollingAvg"] == pytest.approx(expected, abs=0.05)

    def test_custom_rolling_window(self):
        """Custom rolling window param is accepted."""
        sid = _first_site_id()
        resp = client.get(f"/api/sites/{sid}/chart?rolling_window=7")
        assert resp.status_code == 200
        body = resp.json()
        names = [s["name"] for s in body["series"]]
        assert any("7" in n for n in names), f"Expected '7' in series names: {names}"
        rows = body["data"]
        assert len(rows) >= 7
        assert all("rollingAvg" not in row for row in rows[:6])
        expected = round(sum(row["level"] for row in rows[:7]) / 7, 2)
        assert rows[6]["rollingAvg"] == pytest.approx(expected, abs=0.05)

    def test_date_filter(self):
        """start_date / end_date narrow the result."""
        sid = _first_site_id()
        full = client.get(f"/api/sites/{sid}/chart").json()
        mid = full["data"][len(full["data"]) // 2]["date"]
        filtered = client.get(f"/api/sites/{sid}/chart?start_date={mid}").json()
        dates = [row["date"] for row in filtered["data"]]
        assert dates
        assert all(date >= mid for date in dates)
        assert len(dates) < len(full["data"])

    def test_unknown_site_404(self):
        """Unknown site_id returns 404."""
        resp = client.get("/api/sites/000000000000000/chart")
        assert resp.status_code == 404

    def test_site_metadata_in_response(self):
        """Response includes site metadata."""
        sid = _first_site_id()
        body = client.get(f"/api/sites/{sid}/chart").json()
        assert "site" in body
        assert body["site"]["id"] == sid
        assert body["site"]["name"] == SITE_METADATA[sid]["name"]


# ===================================================================
# GET /api/compare/chart
# ===================================================================


class TestComparisonChartEndpoint:
    """Tests for the multi-site comparison chart endpoint."""

    def _two_site_ids(self):
        data_dir = Path(__file__).parent.parent.parent / "data"
        ids = []
        for sid in SITE_METADATA:
            if (data_dir / f"usgs_{sid}.csv").exists():
                ids.append(sid)
            if len(ids) == 2:
                return ids
        pytest.skip("Need at least 2 site CSVs")

    def test_returns_valid_comparison_json(self):
        ids = self._two_site_ids()
        resp = client.get(f"/api/compare/chart?site_ids={','.join(ids)}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["chart_type"] == "comparison"
        assert len(body["series"]) >= 1
        assert len(body["data"]) > 0

    def test_series_per_site(self):
        ids = self._two_site_ids()
        body = client.get(f"/api/compare/chart?site_ids={','.join(ids)}").json()
        series_keys = {s["key"] for s in body["series"]}
        for sid in ids:
            assert sid in series_keys, f"Missing series for {sid}"

    def test_date_filter_comparison(self):
        ids = self._two_site_ids()
        full = client.get(f"/api/compare/chart?site_ids={','.join(ids)}").json()
        mid = full["data"][len(full["data"]) // 2]["date"]
        filtered = client.get(
            f"/api/compare/chart?site_ids={','.join(ids)}&start_date={mid}"
        ).json()
        dates = [row["date"] for row in filtered["data"]]
        assert dates
        assert all(date >= mid for date in dates)
        assert len(dates) < len(full["data"])

    def test_max_five_sites(self):
        """Only the first 5 site IDs are processed."""
        data_dir = Path(__file__).parent.parent.parent / "data"
        ids = [sid for sid in SITE_METADATA if (data_dir / f"usgs_{sid}.csv").exists()][:7]
        if len(ids) < 6:
            pytest.skip("Need 6+ site CSVs")
        body = client.get(f"/api/compare/chart?site_ids={','.join(ids)}").json()
        assert len(body["series"]) <= 5

    def test_all_unknown_sites_404(self):
        resp = client.get("/api/compare/chart?site_ids=000000000000001,000000000000002")
        assert resp.status_code == 404

    def test_partial_unknown_succeeds(self):
        """If at least one site is valid, we still get data."""
        sid = _first_site_id()
        body = client.get(f"/api/compare/chart?site_ids={sid},000000000000099").json()
        assert len(body["series"]) == 1
        assert body["series"][0]["key"] == sid


# ===================================================================
# Chart data integrity
# ===================================================================


class TestChartDataIntegrity:
    """Cross-check chart endpoint output against raw data endpoint."""

    def test_chart_level_matches_data_endpoint(self):
        """Spot-check: chart level values agree with /api/sites/{id}/data."""
        sid = _first_site_id()
        chart = client.get(f"/api/sites/{sid}/chart").json()
        data = client.get(f"/api/sites/{sid}/data").json()

        # Build lookup from data endpoint — collect *all* levels per
        # truncated date to account for multiple readings per day.
        from collections import defaultdict

        day_levels: dict[str, list[float]] = defaultdict(list)
        for r in data["data"][:200]:
            day_levels[r["date"][:10]].append(r["level"])

        mismatches = 0
        for row in chart["data"][:50]:
            d = row["date"]
            if d in day_levels:
                # Accept if the chart value matches *any* reading that day
                if not any(abs(row["level"] - lv) <= 0.01 for lv in day_levels[d]):
                    mismatches += 1

        assert mismatches == 0, f"{mismatches} level mismatches between chart and data endpoints"
