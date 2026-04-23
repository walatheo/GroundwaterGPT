"""PELT changepoint detection via the ``ruptures`` library.

Returns structural break points in a 1-D series with per-segment slopes so the
interpreter can cite "break near 2017 with slope changing from +0.08 to -0.32
ft/yr" directly from the evidence pack.
"""

from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence

import numpy as np

_MAX_PELT_POINTS = 800


def detect_pelt_changepoints(
    values: Sequence[float],
    dates: Optional[Sequence[str]] = None,
    min_size: int = 12,
    penalty: Optional[float] = None,
    max_points: int = _MAX_PELT_POINTS,
) -> List[dict]:
    """Return PELT changepoints as ``[{index, date, pre_slope, post_slope}]``.

    ``penalty`` defaults to ``log(n) * sigma^2`` (a BIC-style penalty). ``min_size``
    is expressed in samples and should correspond to roughly one year at the
    caller's sampling cadence. Series longer than ``max_points`` are uniformly
    subsampled before PELT — the O(n²)-ish worst case on long daily records would
    otherwise stall evidence-pack assembly.
    """
    try:
        import ruptures as rpt
    except ImportError:  # pragma: no cover - surfaced at install time
        return []

    cleaned, kept_idx = _clean_with_index(values)
    if len(cleaned) < max(min_size * 2, 4):
        return []

    stride = max(1, len(cleaned) // max_points)
    if stride > 1:
        cleaned = cleaned[::stride]
        kept_idx = kept_idx[::stride]

    arr = np.asarray(cleaned, dtype=float)
    sigma2 = float(np.var(arr)) if arr.size else 0.0
    pen = penalty if penalty is not None else max(math.log(len(arr)) * sigma2, 1e-6)

    jump = max(1, len(arr) // 200)
    algo = rpt.Pelt(model="l2", min_size=min_size, jump=jump).fit(arr)
    try:
        breaks = algo.predict(pen=pen)
    except Exception:  # pragma: no cover
        return []

    results: List[dict] = []
    prev = 0
    for bkp in breaks[:-1]:  # last entry is always len(arr)
        pre = arr[prev:bkp]
        post = arr[bkp:]
        if pre.size < 2 or post.size < 2:
            prev = bkp
            continue
        pre_slope = _ols_slope(pre)
        post_slope = _ols_slope(post)
        original_index = kept_idx[bkp] if bkp < len(kept_idx) else kept_idx[-1]
        entry = {
            "index": int(original_index),
            "pre_slope": pre_slope,
            "post_slope": post_slope,
            "method": "pelt",
        }
        if dates is not None and 0 <= original_index < len(dates):
            entry["date"] = dates[original_index]
        results.append(entry)
        prev = bkp

    return results


def _ols_slope(arr: np.ndarray) -> float:
    x = np.arange(arr.size, dtype=float)
    if arr.size < 2:
        return 0.0
    slope, _intercept = np.polyfit(x, arr, 1)
    return float(slope)


def _clean_with_index(values: Iterable[float]):
    cleaned: List[float] = []
    kept: List[int] = []
    for i, v in enumerate(values):
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            cleaned.append(fv)
            kept.append(i)
    return cleaned, kept
