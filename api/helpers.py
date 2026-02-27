"""Shared data-loading helpers for the API layer.

Provides ``load_site_data()`` and ``calculate_stats()`` so that multiple
route modules can reuse them without duplicating logic.
"""

from pathlib import Path

import pandas as pd
from fastapi import HTTPException

DATA_DIR = Path(__file__).parent.parent / "data"


def load_site_data(site_id: str) -> pd.DataFrame:
    """Load and parse the CSV for a single USGS site.

    Returns a DataFrame sorted by ``datetime`` with that column
    already converted to ``pd.Timestamp``.
    """
    csv_path = DATA_DIR / f"usgs_{site_id}.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"Data not found for site {site_id}")

    df = pd.read_csv(csv_path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")
    return df


def calculate_stats(df: pd.DataFrame) -> dict:
    """Calculate summary statistics for a site DataFrame.

    Expects columns ``datetime`` and ``value``.
    """
    values = df["value"].dropna()

    if len(values) == 0:
        return {"min": 0, "max": 0, "mean": 0, "annualChange": 0, "count": 0}

    # Annual change via simple linear regression
    df_copy = df.copy()
    df_copy["days"] = (df_copy["datetime"] - df_copy["datetime"].min()).dt.days

    if len(df_copy) > 1:
        x = df_copy["days"].values.astype(float)
        y = df_copy["value"].values.astype(float)
        n = len(x)
        denom = n * (x**2).sum() - x.sum() ** 2
        slope = (n * (x * y).sum() - x.sum() * y.sum()) / denom if denom else 0
        annual_change = slope * 365
    else:
        annual_change = 0

    return {
        "min": round(float(values.min()), 2),
        "max": round(float(values.max()), 2),
        "mean": round(float(values.mean()), 2),
        "annualChange": round(float(annual_change), 3),
        "count": int(len(values)),
        "dateRange": {
            "start": df["datetime"].min().isoformat(),
            "end": df["datetime"].max().isoformat(),
        },
    }
