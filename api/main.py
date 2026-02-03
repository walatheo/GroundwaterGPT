"""
FastAPI backend for GroundwaterGPT Dashboard
Serves real USGS groundwater data to the React frontend
"""

import json
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="GroundwaterGPT API", version="1.0.0")

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data directory
DATA_DIR = Path(__file__).parent.parent / "data"

# Site metadata with coordinates (approximate locations in Florida)
SITE_METADATA = {
    "251241080385301": {
        "id": "251241080385301",
        "name": "Miami-Dade G-3764",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.2114,
        "lng": -80.6481,
        "depth": 50,
        "description": "Monitoring well in the Biscayne Aquifer, Miami-Dade County",
    },
    "251457080395802": {
        "id": "251457080395802",
        "name": "Miami-Dade G-3777",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.2492,
        "lng": -80.6661,
        "depth": 45,
        "description": "Monitoring well in the Biscayne Aquifer, Miami-Dade County",
    },
    "251922080340701": {
        "id": "251922080340701",
        "name": "Miami-Dade G-1251",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.3228,
        "lng": -80.5686,
        "depth": 60,
        "description": "Long-term monitoring well in the Biscayne Aquifer",
    },
    "252007080335701": {
        "id": "252007080335701",
        "name": "Miami-Dade G-3336",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.3353,
        "lng": -80.5658,
        "depth": 55,
        "description": "Monitoring well in the Biscayne Aquifer, Miami-Dade County",
    },
    "252036080293501": {
        "id": "252036080293501",
        "name": "Miami-Dade G-5004",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.3433,
        "lng": -80.4931,
        "depth": 40,
        "description": "Newer monitoring well in the Biscayne Aquifer",
    },
    "262724081260701": {
        "id": "262724081260701",
        "name": "Lee County - Fort Myers",
        "aquifer": "Floridan Aquifer",
        "county": "Lee",
        "lat": 26.4567,
        "lng": -81.4353,
        "depth": 800,
        "description": "Deep monitoring well in the Floridan Aquifer System",
    },
}


def load_site_data(site_id: str) -> pd.DataFrame:
    """Load CSV data for a specific site"""
    csv_path = DATA_DIR / f"usgs_{site_id}.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"Data not found for site {site_id}")

    df = pd.read_csv(csv_path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime")
    return df


def calculate_stats(df: pd.DataFrame) -> dict:
    """Calculate statistics for site data"""
    values = df["value"].dropna()

    if len(values) == 0:
        return {"min": 0, "max": 0, "mean": 0, "annualChange": 0, "count": 0}

    # Calculate annual change using linear regression
    df_copy = df.copy()
    df_copy["days"] = (df_copy["datetime"] - df_copy["datetime"].min()).dt.days

    if len(df_copy) > 1:
        # Simple linear regression
        x = df_copy["days"].values
        y = df_copy["value"].values
        n = len(x)
        slope = (n * (x * y).sum() - x.sum() * y.sum()) / (n * (x**2).sum() - x.sum() ** 2)
        annual_change = slope * 365  # Convert daily rate to annual
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


@app.get("/")
def root():
    return {"message": "GroundwaterGPT API", "version": "1.0.0"}


@app.get("/api/sites")
def get_sites():
    """Get list of all monitoring sites with metadata"""
    sites = []
    for site_id, metadata in SITE_METADATA.items():
        csv_path = DATA_DIR / f"usgs_{site_id}.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path)
            metadata_copy = metadata.copy()
            metadata_copy["recordCount"] = len(df)
            sites.append(metadata_copy)
    return {"sites": sites}


@app.get("/api/sites/{site_id}")
def get_site(site_id: str):
    """Get metadata and statistics for a specific site"""
    if site_id not in SITE_METADATA:
        raise HTTPException(status_code=404, detail=f"Site {site_id} not found")

    df = load_site_data(site_id)
    stats = calculate_stats(df)

    return {"site": SITE_METADATA[site_id], "stats": stats}


@app.get("/api/sites/{site_id}/data")
def get_site_data(site_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Get time series data for a specific site"""
    df = load_site_data(site_id)

    # Filter by date range if provided
    if start_date:
        df = df[df["datetime"] >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df["datetime"] <= pd.to_datetime(end_date)]

    # Format data for frontend
    data = []
    for _, row in df.iterrows():
        data.append(
            {
                "date": row["datetime"].isoformat(),
                "level": round(float(row["value"]), 2),
                "year": int(row["year"]),
                "month": row["datetime"].month,
            }
        )

    stats = calculate_stats(df)

    return {"site": SITE_METADATA.get(site_id, {}), "data": data, "stats": stats}


@app.get("/api/sites/{site_id}/heatmap")
def get_heatmap_data(site_id: str):
    """Get heatmap data (monthly averages by year)"""
    df = load_site_data(site_id)

    # Calculate monthly averages by year
    df["month"] = df["datetime"].dt.month
    df["year"] = df["datetime"].dt.year

    monthly = df.groupby(["year", "month"])["value"].mean().reset_index()

    heatmap_data = []
    for _, row in monthly.iterrows():
        heatmap_data.append(
            {
                "year": int(row["year"]),
                "month": int(row["month"]),
                "value": round(float(row["value"]), 2),
            }
        )

    # Get min/max for color scale
    values = monthly["value"]

    return {
        "data": heatmap_data,
        "min": round(float(values.min()), 2),
        "max": round(float(values.max()), 2),
    }


@app.get("/api/compare")
def compare_sites(site_ids: str):
    """Compare multiple sites"""
    ids = site_ids.split(",")
    comparison = []

    for site_id in ids:
        if site_id.strip() in SITE_METADATA:
            try:
                df = load_site_data(site_id.strip())
                stats = calculate_stats(df)
                comparison.append({"site": SITE_METADATA[site_id.strip()], "stats": stats})
            except:
                pass

    return {"comparison": comparison}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
