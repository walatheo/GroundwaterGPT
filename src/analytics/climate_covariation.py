"""Load ``data/climate.csv`` and compute lagged correlation with a well.

The file contains daily temperature and precipitation for the Estero region
(2014–2024). We aggregate to monthly means, align with the well's monthly
chart bins, and expose:

    - ``load_monthly_climate()`` — returns ``{month_iso: {"precip_mm", "temp_c"}}``
    - ``precip_correlation(values_by_month, lag_months=0..6)`` — Pearson + Spearman
    - ``best_lag_correlation(values_by_month)`` — picks the lag with strongest |r|

Correlation is computed on monthly means. Lag positive means precipitation
leads water levels (e.g. lag=2 means rainfall 2 months before a reading).
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CLIMATE_CSV = Path(__file__).resolve().parents[2] / "data" / "climate.csv"
_MAX_LAG = 6


@lru_cache(maxsize=1)
def load_monthly_climate(path: Optional[str] = None) -> dict[str, dict[str, float]]:
    """Return monthly-mean climate series keyed by ``YYYY-MM``."""
    csv_path = Path(path) if path else CLIMATE_CSV
    if not csv_path.exists():
        return {}

    precip_bins: dict[str, list[float]] = defaultdict(list)
    temp_bins: dict[str, list[float]] = defaultdict(list)

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = str(row.get("date", ""))[:7]
            if not date or len(date) != 7:
                continue
            try:
                precip = float(row.get("precipitation_mm", 0.0))
                temp = float(row.get("temperature_c", 0.0))
            except (TypeError, ValueError):
                continue
            precip_bins[date].append(precip)
            temp_bins[date].append(temp)

    out: dict[str, dict[str, float]] = {}
    for month, precip_values in precip_bins.items():
        out[month] = {
            "precip_mm": sum(precip_values) / len(precip_values) * 30.0,
            "temp_c": sum(temp_bins.get(month, [])) / max(len(temp_bins.get(month, [])), 1),
        }
    return out


def precip_correlation(
    values_by_month: dict[str, float],
    *,
    lag: int = 0,
    climate: Optional[dict[str, dict[str, float]]] = None,
) -> Optional[dict[str, float]]:
    """Correlate monthly well values against monthly precipitation at ``lag``.

    ``lag`` is measured in months; positive means precipitation leads the
    well reading.
    """
    if not values_by_month:
        return None
    climate = climate if climate is not None else load_monthly_climate()
    if not climate:
        return None

    paired: list[tuple[float, float]] = []
    months = sorted(values_by_month)
    month_to_index = {m: i for i, m in enumerate(months)}
    for month, value in values_by_month.items():
        idx = month_to_index[month]
        lagged_idx = idx - lag
        if lagged_idx < 0 or lagged_idx >= len(months):
            continue
        lagged_month = months[lagged_idx]
        entry = climate.get(lagged_month)
        if entry is None:
            continue
        paired.append((float(value), float(entry["precip_mm"])))

    if len(paired) < 6:
        return None

    try:
        import numpy as np
        from scipy import stats as _stats

        xs = np.asarray([p[0] for p in paired], dtype=float)
        ys = np.asarray([p[1] for p in paired], dtype=float)
        pearson_r, pearson_p = _stats.pearsonr(xs, ys)
        spearman_r, spearman_p = _stats.spearmanr(xs, ys)
    except Exception as exc:
        logger.debug("climate correlation failed: %s", exc)
        return None

    return {
        "lag_months": lag,
        "n_months": len(paired),
        "pearson_r": float(pearson_r),
        "pearson_p": float(pearson_p),
        "spearman_r": float(spearman_r),
        "spearman_p": float(spearman_p),
    }


def best_lag_correlation(
    values_by_month: dict[str, float],
    *,
    max_lag: int = _MAX_LAG,
    climate: Optional[dict[str, dict[str, float]]] = None,
) -> Optional[dict[str, float]]:
    """Return the correlation at the lag with largest |Pearson r|."""
    if not values_by_month:
        return None
    climate = climate if climate is not None else load_monthly_climate()
    best: Optional[dict[str, float]] = None
    for lag in range(0, max_lag + 1):
        res = precip_correlation(values_by_month, lag=lag, climate=climate)
        if res is None:
            continue
        if best is None or abs(res["pearson_r"]) > abs(best["pearson_r"]):
            best = res
    return best


def climate_series_payload(
    months: list[str],
    climate: Optional[dict[str, dict[str, float]]] = None,
) -> list[dict[str, float]]:
    """Return a list of ``{month, precip_mm, temp_c}`` aligned with ``months``."""
    climate = climate if climate is not None else load_monthly_climate()
    out: list[dict[str, float]] = []
    for month in months:
        entry = climate.get(month)
        if entry is None:
            continue
        out.append(
            {
                "month": month,
                "precip_mm": round(entry["precip_mm"], 2),
                "temp_c": round(entry["temp_c"], 2),
            }
        )
    return out
