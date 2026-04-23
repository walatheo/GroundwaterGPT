"""Publication-grade analytics for groundwater time series.

Additive layer on top of the deterministic metrics in api/routes/_site_analysis.py.
Every function returns pure numbers/dicts — no LLM, no side effects — so results
feed directly into the evidence pack and can be cited by the interpreter.
"""

from src.analytics.changepoint import detect_pelt_changepoints
from src.analytics.climate_covariation import (
    best_lag_correlation,
    climate_series_payload,
    load_monthly_climate,
    precip_correlation,
)
from src.analytics.rigorous_trend import mann_kendall, sens_slope

__all__ = [
    "mann_kendall",
    "sens_slope",
    "detect_pelt_changepoints",
    "load_monthly_climate",
    "precip_correlation",
    "best_lag_correlation",
    "climate_series_payload",
]
