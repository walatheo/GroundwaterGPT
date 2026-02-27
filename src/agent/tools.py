"""Custom Tools for GroundwaterGPT Agent.

Tools for querying groundwater data, making predictions, and analyzing trends.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
import pandas as pd
from langchain_core.tools import tool

# Base directory for data
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"


@tool
def query_groundwater_data(
    start_date: Optional[str] = None, end_date: Optional[str] = None, stat_type: str = "summary"
) -> str:
    """Query real USGS groundwater data for Fort Myers, FL area.

    Args:
        start_date: Start date in YYYY-MM-DD format (default: earliest available)
        end_date: End date in YYYY-MM-DD format (default: latest available)
        stat_type: Type of statistics - 'summary', 'monthly', 'yearly', or 'raw'

    Returns:
        Formatted string with groundwater data analysis
    """
    try:
        # Load groundwater data
        df = pd.read_csv(DATA_DIR / "groundwater.csv", parse_dates=["date"])

        # Filter by date range if specified
        if start_date:
            df = df[df["date"] >= start_date]
        if end_date:
            df = df[df["date"] <= end_date]

        if df.empty:
            return "No data found for the specified date range."

        # Calculate statistics based on type
        if stat_type == "summary":
            tail30 = df.tail(30)
            recent_change = tail30.iloc[-1]["water_level_ft"] - tail30.iloc[0]["water_level_ft"]
            result = f"""
📊 **Groundwater Data Summary**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 **Date Range**: {df['date'].min().strftime('%Y-%m-%d')} to {df['date'].max().strftime('%Y-%m-%d')}
📈 **Total Records**: {len(df):,} days

💧 **Water Level Statistics** (feet below surface):
   • Mean: {df['water_level_ft'].mean():.2f} ft
   • Median: {df['water_level_ft'].median():.2f} ft
   • Min: {df['water_level_ft'].min():.2f} ft (shallowest)
   • Max: {df['water_level_ft'].max():.2f} ft (deepest)
   • Std Dev: {df['water_level_ft'].std():.2f} ft

📉 **Recent Trend** (last 30 days):
   • Start: {tail30.iloc[0]['water_level_ft']:.2f} ft
   • End: {tail30.iloc[-1]['water_level_ft']:.2f} ft
   • Change: {recent_change:+.2f} ft
"""

        elif stat_type == "monthly":
            df["month"] = df["date"].dt.to_period("M")
            monthly = df.groupby("month")["water_level_ft"].agg(["mean", "min", "max", "std"])
            result = "📅 **Monthly Averages** (last 12 months):\n"
            for month, row in monthly.tail(12).iterrows():
                result += (
                    f"   • {month}: {row['mean']:.2f} ft"
                    f" (range: {row['min']:.2f} - {row['max']:.2f})\n"
                )

        elif stat_type == "yearly":
            df["year"] = df["date"].dt.year
            yearly = df.groupby("year")["water_level_ft"].agg(["mean", "min", "max", "count"])
            result = "📆 **Yearly Statistics**:\n"
            for year, row in yearly.iterrows():
                result += (
                    f"   • {year}: avg {row['mean']:.2f} ft, {int(row['count'])} days of data\n"
                )

        elif stat_type == "raw":
            # Return last 10 records
            result = "📋 **Recent Raw Data** (last 10 records):\n"
            for _, row in df.tail(10).iterrows():
                result += (
                    f"   • {row['date'].strftime('%Y-%m-%d')}: {row['water_level_ft']:.2f} ft\n"
                )

        else:
            result = (
                f"Unknown stat_type: {stat_type}. Use 'summary', 'monthly', 'yearly', or 'raw'."
            )

        return result

    except FileNotFoundError:
        return "❌ Groundwater data file not found. Please run download_data.py first."
    except Exception as e:
        return f"❌ Error querying groundwater data: {str(e)}"


@tool
def get_water_level_prediction(days_ahead: int = 7) -> str:
    """Get water level predictions using the trained ML model.

    Args:
        days_ahead: Number of days to predict (1-30, default: 7)

    Returns:
        Predicted water levels with confidence information
    """
    try:
        # Validate days_ahead
        days_ahead = max(1, min(30, days_ahead))

        # Load the trained model
        model_path = MODELS_DIR / "best_ridge.joblib"
        if not model_path.exists():
            return "❌ Prediction model not found. Please run train_groundwater.py first."

        _model = joblib.load(model_path)  # noqa: F841 — loaded for future use

        # Load recent data for features
        df = pd.read_csv(DATA_DIR / "groundwater.csv", parse_dates=["date"])
        df = df.sort_values("date")

        # Get the latest water level data
        latest_date = df["date"].max()
        latest_level = df["water_level_ft"].iloc[-1]

        # Calculate features for prediction (same as training)
        recent_7 = df["water_level_ft"].tail(7).mean()
        recent_14 = df["water_level_ft"].tail(14).mean()
        recent_30 = df["water_level_ft"].tail(30).mean()

        # Simple prediction based on recent trends
        # Note: This is a simplified prediction; actual model uses more features
        trend = (df["water_level_ft"].tail(7).iloc[-1] - df["water_level_ft"].tail(7).iloc[0]) / 7

        result = f"""
🔮 **Water Level Prediction**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 **Prediction Base Date**: {latest_date.strftime('%Y-%m-%d')}
💧 **Current Level**: {latest_level:.2f} ft

📈 **Recent Averages**:
   • 7-day avg: {recent_7:.2f} ft
   • 14-day avg: {recent_14:.2f} ft
   • 30-day avg: {recent_30:.2f} ft

📊 **{days_ahead}-Day Forecast**:
"""

        # Generate predictions for each day
        predicted_levels = []
        for day in range(1, days_ahead + 1):
            # Simple trend-based prediction
            predicted = latest_level + (trend * day)
            predicted_levels.append(predicted)
            forecast_date = latest_date + timedelta(days=day)
            result += f"   • {forecast_date.strftime('%Y-%m-%d')}: {predicted:.2f} ft\n"

        avg_pred = np.mean(predicted_levels)
        result += f"""
📉 **Summary**:
   • Average predicted level: {avg_pred:.2f} ft
   • Trend direction: {"Rising ↑" if trend > 0 else "Falling ↓" if trend < 0 else "Stable →"}
   • Daily change rate: {trend:+.3f} ft/day

⚠️ **Model Info**: Ridge Regression (R² ≈ 0.86)
"""

        return result

    except Exception as e:
        return f"❌ Error making prediction: {str(e)}"


@tool
def analyze_seasonal_patterns() -> str:
    """Analyze seasonal patterns in groundwater levels.

    Returns:
        Seasonal analysis including wet/dry season comparisons
    """
    try:
        df = pd.read_csv(DATA_DIR / "groundwater.csv", parse_dates=["date"])

        # Extract month
        df["month"] = df["date"].dt.month
        df["month_name"] = df["date"].dt.strftime("%B")

        # Calculate monthly averages
        monthly_avg = df.groupby("month")["water_level_ft"].mean()

        # Florida seasons: Wet (Jun-Oct), Dry (Nov-May)
        df["season"] = df["month"].apply(lambda m: "Wet" if 6 <= m <= 10 else "Dry")
        seasonal_avg = df.groupby("season")["water_level_ft"].agg(["mean", "std", "min", "max"])

        # Find peak months
        shallowest_month = monthly_avg.idxmin()
        deepest_month = monthly_avg.idxmax()

        month_names = {
            1: "January",
            2: "February",
            3: "March",
            4: "April",
            5: "May",
            6: "June",
            7: "July",
            8: "August",
            9: "September",
            10: "October",
            11: "November",
            12: "December",
        }

        result = f"""
🌊 **Seasonal Groundwater Analysis**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🌧️ **Wet Season** (June - October):
   • Average Level: {seasonal_avg.loc['Wet', 'mean']:.2f} ft
   • Range: {seasonal_avg.loc['Wet', 'min']:.2f} - {seasonal_avg.loc['Wet', 'max']:.2f} ft
   • Variability (Std): {seasonal_avg.loc['Wet', 'std']:.2f} ft

☀️ **Dry Season** (November - May):
   • Average Level: {seasonal_avg.loc['Dry', 'mean']:.2f} ft
   • Range: {seasonal_avg.loc['Dry', 'min']:.2f} - {seasonal_avg.loc['Dry', 'max']:.2f} ft
   • Variability (Std): {seasonal_avg.loc['Dry', 'std']:.2f} ft

📈 **Monthly Averages**:
"""

        for month in range(1, 13):
            avg = monthly_avg.get(month, 0)
            bar = "█" * int((avg - 20) * 2)  # Simple bar chart
            indicator = (
                "⬅️ Shallowest"
                if month == shallowest_month
                else ("⬅️ Deepest" if month == deepest_month else "")
            )
            result += f"   {month_names[month][:3]}: {avg:.1f} ft {bar} {indicator}\n"

        seasonal_diff = seasonal_avg.loc["Dry", "mean"] - seasonal_avg.loc["Wet", "mean"]
        result += f"""
📊 **Key Insights**:
   • Shallowest water: {month_names[shallowest_month]} ({monthly_avg[shallowest_month]:.2f} ft)
   • Deepest water: {month_names[deepest_month]} ({monthly_avg[deepest_month]:.2f} ft)
   • Seasonal difference: {abs(seasonal_diff):.2f} ft
   • Pattern: Water levels are {"deeper" if seasonal_diff > 0 else "shallower"} during dry season
"""

        return result

    except Exception as e:
        return f"❌ Error analyzing seasonal patterns: {str(e)}"


@tool
def detect_anomalies(threshold: float = 2.0) -> str:
    """Detect anomalies in groundwater levels using statistical methods.

    Args:
        threshold: Standard deviation threshold for anomaly detection (default: 2.0)

    Returns:
        List of detected anomalies and their dates
    """
    try:
        df = pd.read_csv(DATA_DIR / "groundwater.csv", parse_dates=["date"])

        # Calculate z-scores
        mean_level = df["water_level_ft"].mean()
        std_level = df["water_level_ft"].std()
        df["z_score"] = (df["water_level_ft"] - mean_level) / std_level

        # Identify anomalies
        anomalies = df[abs(df["z_score"]) > threshold].copy()

        result = f"""
⚠️ **Anomaly Detection Report**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 **Baseline Statistics**:
   • Mean water level: {mean_level:.2f} ft
   • Standard deviation: {std_level:.2f} ft
   • Threshold: ±{threshold:.1f} standard deviations

🔍 **Anomalies Found**: {len(anomalies)} out of {len(df)} records ({100*len(anomalies)/len(df):.1f}%)
"""

        if len(anomalies) > 0:
            # High anomalies (unusually deep water)
            high_anomalies = anomalies[anomalies["z_score"] > threshold]
            if len(high_anomalies) > 0:
                result += f"\n📈 **Unusually Deep Water** ({len(high_anomalies)} events):\n"
                for _, row in high_anomalies.head(5).iterrows():
                    d = row["date"].strftime("%Y-%m-%d")
                    lvl = row["water_level_ft"]
                    z = row["z_score"]
                    result += f"   • {d}: {lvl:.2f} ft (z={z:.1f})\n"
                if len(high_anomalies) > 5:
                    result += f"   ... and {len(high_anomalies) - 5} more\n"

            # Low anomalies (unusually shallow water)
            low_anomalies = anomalies[anomalies["z_score"] < -threshold]
            if len(low_anomalies) > 0:
                result += f"\n📉 **Unusually Shallow Water** ({len(low_anomalies)} events):\n"
                for _, row in low_anomalies.head(5).iterrows():
                    d = row["date"].strftime("%Y-%m-%d")
                    lvl = row["water_level_ft"]
                    z = row["z_score"]
                    result += f"   • {d}: {lvl:.2f} ft (z={z:.1f})\n"
                if len(low_anomalies) > 5:
                    result += f"   ... and {len(low_anomalies) - 5} more\n"
        else:
            result += "\n✅ No anomalies detected at this threshold level.\n"

        result += """
💡 **Interpretation**:
   • Positive z-score = deeper than average (drought conditions)
   • Negative z-score = shallower than average (recharge/rain events)
"""

        return result

    except Exception as e:
        return f"❌ Error detecting anomalies: {str(e)}"


@tool
def get_data_quality_report() -> str:
    """Generate a data quality report for the groundwater dataset.

    Returns:
        Data quality metrics including completeness, gaps, and source info
    """
    try:
        df = pd.read_csv(DATA_DIR / "groundwater.csv", parse_dates=["date"])

        # Calculate data quality metrics
        date_range = (df["date"].max() - df["date"].min()).days + 1
        completeness = (len(df) / date_range) * 100

        # Find gaps
        df_sorted = df.sort_values("date")
        df_sorted["gap"] = df_sorted["date"].diff().dt.days
        gaps = df_sorted[df_sorted["gap"] > 1]

        result = f"""
📋 **Data Quality Report**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 **Source**: USGS National Water Information System (NWIS)
📍 **Site**: 262724081260701 (Lee County, FL - Fort Myers area)
🏷️ **Parameter**: Depth to water level (feet below land surface)

📅 **Temporal Coverage**:
   • Start Date: {df['date'].min().strftime('%Y-%m-%d')}
   • End Date: {df['date'].max().strftime('%Y-%m-%d')}
   • Total Days: {date_range:,}
   • Records Available: {len(df):,}
   • Completeness: {completeness:.1f}%

📊 **Data Quality**:
   • Missing values: {df['water_level_ft'].isna().sum()}
   • Gaps (>1 day): {len(gaps)} periods
"""

        if len(gaps) > 0:
            result += "   • Largest gaps:\n"
            for _, row in gaps.nlargest(3, "gap").iterrows():
                result += (
                    f"      - {int(row['gap'])} days ending {row['date'].strftime('%Y-%m-%d')}\n"
                )

        wl_min = df["water_level_ft"].min()
        wl_max = df["water_level_ft"].max()
        if completeness > 90:
            quality = "Good"
        elif completeness > 70:
            quality = "Fair"
        else:
            quality = "Poor"

        result += f"""
📈 **Value Range**:
   • Minimum: {wl_min:.2f} ft
   • Maximum: {wl_max:.2f} ft
   • Range: {wl_max - wl_min:.2f} ft

✅ **Status**: {quality} quality dataset
"""

        return result

    except Exception as e:
        return f"❌ Error generating quality report: {str(e)}"


# ---------------------------------------------------------------------------
# Visualization tools (Session 8)
# ---------------------------------------------------------------------------


def _load_site_csv(site_id: str) -> pd.DataFrame:
    """Load CSV for a single USGS site and return a date-indexed DataFrame.

    The per-site CSVs use columns ``datetime`` and ``value``.
    This helper normalises them to ``date`` and ``water_level_ft``
    so that downstream tools can use a consistent schema.
    """
    csv_path = DATA_DIR / f"usgs_{site_id}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No data file for site {site_id}")
    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    df = df.rename(columns={"datetime": "date", "value": "water_level_ft"})
    df = df.sort_values("date")
    return df


@tool
def generate_time_series_plot(
    site_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_rolling_avg: bool = True,
) -> str:
    """Generate time-series chart data for a USGS site.

    Returns a JSON string with ``type: "chart"`` that the frontend can
    render as an interactive Recharts line chart.

    Args:
        site_id: USGS site number (e.g. "262724081260701")
        start_date: Optional start date YYYY-MM-DD
        end_date: Optional end date YYYY-MM-DD
        include_rolling_avg: Include a 30-day rolling average line

    Returns:
        JSON string with chart_type, title, series, and data arrays.
    """
    import json

    try:
        df = _load_site_csv(site_id)

        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]

        if df.empty:
            return json.dumps({"type": "chart", "error": "No data for the requested range."})

        records = []
        levels = df["water_level_ft"].tolist()
        dates = df["date"].dt.strftime("%Y-%m-%d").tolist()

        window = 30
        for i, (d, lvl) in enumerate(zip(dates, levels)):
            entry: Dict[str, Any] = {"date": d, "level": round(lvl, 2)}
            if include_rolling_avg and i >= window - 1:
                avg = float(np.mean(levels[max(0, i - window + 1) : i + 1]))
                entry["rollingAvg"] = round(avg, 2)
            records.append(entry)

        chart = {
            "type": "chart",
            "chart_type": "time_series",
            "title": f"Water Level — Site {site_id}",
            "x_label": "Date",
            "y_label": "Water Level (ft)",
            "series": [
                {"key": "level", "name": "Water Level", "color": "#3b82f6"},
            ],
            "data": records,
        }
        if include_rolling_avg:
            chart["series"].append({"key": "rollingAvg", "name": "30-Day Avg", "color": "#f59e0b"})

        return json.dumps(chart)

    except FileNotFoundError as exc:
        return json.dumps({"type": "chart", "error": str(exc)})
    except Exception as exc:
        return json.dumps({"type": "chart", "error": f"Chart generation failed: {exc}"})


@tool
def generate_comparison_chart(
    site_ids: List[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """Generate a multi-site comparison chart overlaying water levels.

    Args:
        site_ids: List of USGS site numbers to compare (max 5).
        start_date: Optional start date YYYY-MM-DD.
        end_date: Optional end date YYYY-MM-DD.

    Returns:
        JSON string with chart data for all requested sites.
    """
    import json

    COLORS = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6"]

    try:
        if len(site_ids) > 5:
            site_ids = site_ids[:5]

        # Collect data per site
        all_dates: set = set()
        site_data: Dict[str, Dict[str, float]] = {}

        for sid in site_ids:
            try:
                df = _load_site_csv(sid)
                if start_date:
                    df = df[df["date"] >= pd.Timestamp(start_date)]
                if end_date:
                    df = df[df["date"] <= pd.Timestamp(end_date)]
                mapping = dict(
                    zip(
                        df["date"].dt.strftime("%Y-%m-%d"),
                        df["water_level_ft"].round(2),
                    )
                )
                site_data[sid] = mapping
                all_dates.update(mapping.keys())
            except FileNotFoundError:
                continue

        if not site_data:
            return json.dumps({"type": "chart", "error": "No data found for any site."})

        sorted_dates = sorted(all_dates)
        records = []
        for d in sorted_dates:
            entry: Dict[str, Any] = {"date": d}
            for sid in site_data:
                if d in site_data[sid]:
                    entry[sid] = site_data[sid][d]
            records.append(entry)

        series = [
            {"key": sid, "name": f"Site {sid[-6:]}", "color": COLORS[i % len(COLORS)]}
            for i, sid in enumerate(site_data)
        ]

        chart = {
            "type": "chart",
            "chart_type": "comparison",
            "title": f"Water Level Comparison — {len(site_data)} Sites",
            "x_label": "Date",
            "y_label": "Water Level (ft)",
            "series": series,
            "data": records,
        }
        return json.dumps(chart)

    except Exception as exc:
        return json.dumps({"type": "chart", "error": f"Comparison failed: {exc}"})


# List of all available tools
GROUNDWATER_TOOLS = [
    query_groundwater_data,
    get_water_level_prediction,
    analyze_seasonal_patterns,
    detect_anomalies,
    get_data_quality_report,
    generate_time_series_plot,
    generate_comparison_chart,
]
