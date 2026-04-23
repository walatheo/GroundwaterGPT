"""Unit tests for rainfall co-variation helpers."""

from src.analytics import climate_covariation
from src.analytics.climate_covariation import (
    best_lag_correlation,
    climate_series_payload,
    precip_correlation,
)


def _fake_climate():
    # 18 months of synthetic precipitation (wet May-Oct, dry rest)
    months = [f"2020-{m:02d}" for m in range(1, 13)] + [f"2021-{m:02d}" for m in range(1, 7)]
    return {
        month: {
            "precip_mm": 200.0 if int(month[5:]) in (5, 6, 7, 8, 9, 10) else 40.0,
            "temp_c": 22.0,
        }
        for month in months
    }


def test_precip_correlation_detects_anti_correlated_levels():
    climate = _fake_climate()
    # Water levels drop in dry season, rise in wet season — positive lag correlation
    levels = {month: (10.0 - climate[month]["precip_mm"] / 40.0) for month in climate}
    result = precip_correlation(levels, lag=0, climate=climate)
    assert result is not None
    assert result["n_months"] == len(levels)
    assert abs(result["pearson_r"]) > 0.9


def test_best_lag_picks_strongest_correlation():
    climate = _fake_climate()
    # Inject a lag-3 signal: levels lag precipitation by 3 months
    months = sorted(climate)
    levels = {}
    for i, month in enumerate(months):
        lagged = months[i - 3] if i >= 3 else months[0]
        levels[month] = climate[lagged]["precip_mm"] / 100.0
    best = best_lag_correlation(levels, max_lag=5, climate=climate)
    assert best is not None
    assert best["lag_months"] in {2, 3, 4}


def test_precip_correlation_returns_none_for_short_history():
    climate = _fake_climate()
    levels = {m: 1.0 for m in list(climate)[:3]}
    assert precip_correlation(levels, lag=0, climate=climate) is None


def test_climate_series_payload_aligns_months():
    climate = _fake_climate()
    payload = climate_series_payload(["2020-05", "2020-06", "missing"], climate=climate)
    assert [row["month"] for row in payload] == ["2020-05", "2020-06"]
    assert payload[0]["precip_mm"] > payload[0]["temp_c"]


def test_load_monthly_climate_cache_respects_override(tmp_path):
    climate_covariation.load_monthly_climate.cache_clear()
    tmp_csv = tmp_path / "climate.csv"
    tmp_csv.write_text(
        "date,temperature_c,precipitation_mm\n" "2019-01-01,20.0,1.0\n" "2019-01-15,20.5,3.0\n"
    )
    result = climate_covariation.load_monthly_climate(str(tmp_csv))
    assert "2019-01" in result
    assert result["2019-01"]["precip_mm"] > 0
