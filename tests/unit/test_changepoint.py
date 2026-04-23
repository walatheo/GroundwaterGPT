"""Unit tests for PELT changepoint detection."""

import numpy as np

from src.analytics.changepoint import detect_pelt_changepoints


def test_pelt_detects_obvious_step_change():
    rng = np.random.default_rng(0)
    a = np.linspace(0.0, 1.0, 60) + rng.normal(0, 0.05, 60)
    b = np.linspace(1.0, -4.0, 60) + rng.normal(0, 0.05, 60)
    series = np.concatenate([a, b]).tolist()

    breaks = detect_pelt_changepoints(series, min_size=12)
    assert breaks, "expected at least one changepoint"
    # first break should land somewhere near the midpoint (index 60)
    assert 45 <= breaks[0]["index"] <= 85
    assert breaks[0]["method"] == "pelt"
    # post slope should be more negative than pre slope
    assert breaks[0]["post_slope"] < breaks[0]["pre_slope"]


def test_pelt_attaches_dates_when_provided():
    rng = np.random.default_rng(1)
    series = (
        np.concatenate([np.full(40, 5.0), np.full(40, -5.0)]) + rng.normal(0, 0.1, 80)
    ).tolist()
    dates = [f"2015-{(i % 12) + 1:02d}-01" for i in range(80)]
    breaks = detect_pelt_changepoints(series, dates=dates, min_size=8)
    assert breaks
    assert "date" in breaks[0]


def test_pelt_returns_empty_for_short_series():
    assert detect_pelt_changepoints([1.0, 2.0, 3.0]) == []


def test_pelt_handles_flat_series():
    # flat signal: algorithm may or may not report breaks, but must not crash
    breaks = detect_pelt_changepoints([1.0] * 60, min_size=12)
    assert isinstance(breaks, list)
