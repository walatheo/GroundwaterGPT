"""Data collection and processing module.

Canonical entry points:
- run_pipeline(): Main orchestrator for USGS data fetching
- fetch_usgs_groundwater(): Legacy single-site fetch (uses pipeline internally)
- ContinuousLearner: Knowledge base integration
"""

from .pipeline import run_pipeline


# Lazy imports for heavy dependencies
def __getattr__(name):
    if name == "fetch_usgs_groundwater":
        from .download_data import fetch_usgs_groundwater
        return fetch_usgs_groundwater
    elif name == "ContinuousLearner":
        from .continuous_learning import ContinuousLearner
        return ContinuousLearner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "run_pipeline",
    "fetch_usgs_groundwater",
    "ContinuousLearner",
]
