"""Unit tests for Mann-Kendall and Sen's slope."""

import math

import numpy as np

from src.analytics.rigorous_trend import mann_kendall, sens_slope


def test_mann_kendall_detects_declining_trend():
    values = np.linspace(10.0, 0.0, 80).tolist()
    result = mann_kendall(values)
    assert result["n"] == 80
    assert result["tau"] is not None and result["tau"] < -0.9
    assert result["p_value"] is not None and result["p_value"] < 0.01


def test_mann_kendall_handles_short_series():
    assert mann_kendall([1.0, 2.0])["tau"] is None


def test_mann_kendall_drops_non_finite():
    values = [1.0, float("nan"), None, 2.0, 3.0, 4.0]
    result = mann_kendall(values)
    assert result["n"] == 4
    assert result["tau"] is not None


def test_sens_slope_matches_linear_slope_within_tolerance():
    # pure linear ramp should give Sen slope = true slope
    values = [2.0 * i for i in range(40)]
    slope = sens_slope(values, step=1.0)
    assert slope is not None
    assert math.isclose(slope, 2.0, rel_tol=1e-6)


def test_sens_slope_returns_none_for_too_short():
    assert sens_slope([1.0]) is None


def test_sens_slope_respects_step():
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    # step of 1/12 (monthly->yearly) should scale slope by 12
    slope = sens_slope(values, step=1.0 / 12.0)
    assert slope is not None
    assert math.isclose(slope, 12.0, rel_tol=1e-6)
