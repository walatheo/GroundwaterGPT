"""Non-parametric trend tests: Mann-Kendall and Sen's slope.

Both are standard in hydrology publications and make no distributional
assumption about the residuals (unlike OLS). Results accompany — they do not
replace — the existing OLS rate.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

import numpy as np


def mann_kendall(values: Sequence[float]) -> dict:
    """Return Mann-Kendall tau and two-sided p-value.

    Uses scipy.stats.kendalltau on the (index, value) pairs so the tau captures
    monotonic trend with the step index as the independent variable. NaNs and
    non-finite values are dropped.
    """
    import scipy.stats as stats  # local import keeps module import cheap

    cleaned = _clean(values)
    if len(cleaned) < 4:
        return {"tau": None, "p_value": None, "n": len(cleaned)}

    x = np.arange(len(cleaned), dtype=float)
    result = stats.kendalltau(x, cleaned)
    tau = float(result.correlation) if result.correlation is not None else None
    p_value = float(result.pvalue) if result.pvalue is not None else None
    return {"tau": tau, "p_value": p_value, "n": len(cleaned)}


_MAX_SEN_POINTS = 800


def sens_slope(
    values: Sequence[float], step: float = 1.0, max_points: int = _MAX_SEN_POINTS
) -> Optional[float]:
    """Return Sen's slope (median of pairwise slopes).

    ``step`` is the x-interval between consecutive values (e.g. 1/12 for
    monthly data expressed in per-year units). Series longer than ``max_points``
    are uniformly subsampled first — pairwise slope enumeration is O(n²) and
    would otherwise stall cohort assembly on long daily records.
    """
    cleaned = _clean(values)
    n = len(cleaned)
    if n < 2:
        return None

    stride = max(1, n // max_points)
    if stride > 1:
        cleaned = cleaned[::stride]
        n = len(cleaned)
        step = step * stride

    arr = np.asarray(cleaned, dtype=float)
    i_idx, j_idx = np.triu_indices(n, k=1)
    denom = (j_idx - i_idx).astype(float) * step
    slopes = (arr[j_idx] - arr[i_idx]) / denom
    if slopes.size == 0:
        return None
    return float(np.median(slopes))


def _clean(values: Iterable[float]) -> list[float]:
    out: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            out.append(fv)
    return out
