"""
================================================================================
DASHBOARD.PY - Interactive Groundwater Trend Dashboard
================================================================================

Creates an interactive HTML dashboard for exploring groundwater trends.

Uses Plotly for interactivity (zoom, pan, hover).
Output: Self-contained HTML file that can be shared without Python.

GROUNDWATER ONLY - No climate correlations.
Data: USGS NWIS real measurements from Fort Myers area.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

from config import DATA_DIR, PLOTS_DIR

# Check for plotly
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    print("⚠️  plotly not installed. Install with: pip install plotly")


def load_groundwater_data() -> pd.DataFrame:
    """Load groundwater data only."""
    gw = pd.read_csv(DATA_DIR / "groundwater.csv", parse_dates=["date"])
    
    if "water_level_ft" in gw.columns and "water_level_m" not in gw.columns:
        gw["water_level_m"] = gw["water_level_ft"] * 0.3048
    
    gw = gw.set_index("date").sort_index()
    return gw


def create_dashboard() -> str:
    """
    Create interactive HTML dashboard for groundwater analysis.
    
    GROUNDWATER ONLY - no climate correlations.
    """
    if not PLOTLY_AVAILABLE:
        raise ImportError("plotly required. Install: pip install plotly")
    
    print("📊 Loading groundwater data...")
    gw = load_groundwater_data()
    
    start_year = gw.index.min().year
    end_year = gw.index.max().year
    years_span = (gw.index.max() - gw.index.min()).days / 365.25
    
    print(f"   ✓ Loaded {len(gw):,} days")
    print(f"   ✓ Period: {gw.index.min().date()} to {gw.index.max().date()}")
    
    # Calculate trend
    x = np.arange(len(gw))
    mask = ~np.isnan(gw["water_level_m"].values)
    slope, intercept = np.polyfit(x[mask], gw["water_level_m"].values[mask], 1)
    trend_line = slope * x + intercept
    annual_change = slope * 365
    total_change = slope * len(gw)
    
    # Add calculated columns
    gw = gw.copy()
    gw["roll_30"] = gw["water_level_m"].rolling(30, min_periods=7).mean()
    gw["roll_365"] = gw["water_level_m"].rolling(365, min_periods=30).mean()
    gw["trend"] = trend_line
    gw["anomaly"] = gw["water_level_m"] - trend_line
    gw["month"] = gw.index.month
    gw["year"] = gw.index.year
    
    # Monthly stats
    monthly = gw.groupby("month")["water_level_m"].agg(["mean", "std"]).reset_index()
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    # Yearly stats
    yearly = gw.groupby("year")["water_level_m"].agg(["mean", "std"]).reset_index()
    
    # Rate of change (3-year rolling for shorter dataset)
    window = 3 * 365
    rates, rate_dates = [], []
    for i in range(window, len(gw), 30):
        w = gw.iloc[i-window:i]
        xi = np.arange(len(w))
        yi = w["water_level_m"].values
        m = ~np.isnan(yi)
        if m.sum() > 100:
            s, _ = np.polyfit(xi[m], yi[m], 1)
            rates.append(s * 365)
            rate_dates.append(gw.index[i])
    
    print("🎨 Building dashboard...")
    
    # Create 6-panel dashboard - GROUNDWATER ONLY
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            f"Water Level Trend ({start_year}-{end_year})",
            "Annual Averages",
            "Seasonal Pattern (Monthly)",
            "Year-over-Year Comparison",
            "Anomalies (Detrended)",
            "Rate of Change (3-Year Rolling)"
        ),
        specs=[
            [{"type": "scatter"}, {"type": "bar"}],
            [{"type": "bar"}, {"type": "scatter"}],
            [{"type": "scatter"}, {"type": "scatter"}]
        ],
        vertical_spacing=0.10,
        horizontal_spacing=0.10
    )
    
    # 1. Time series with trend
    fig.add_trace(
        go.Scatter(
            x=gw.index, y=gw["water_level_m"],
            mode="lines", name="Daily",
            line=dict(color="#1f77b4", width=0.5),
            opacity=0.4,
            hovertemplate="Date: %{x}<br>Level: %{y:.2f}m<extra></extra>"
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=gw.index, y=gw["roll_365"],
            mode="lines", name="365-day avg",
            line=dict(color="#1f77b4", width=2.5),
            hovertemplate="Date: %{x}<br>365d avg: %{y:.2f}m<extra></extra>"
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=gw.index, y=gw["trend"],
            mode="lines", name="Linear trend",
            line=dict(color="#d62728", width=2, dash="dash"),
            hovertemplate="Trend: %{y:.2f}m<extra></extra>"
        ),
        row=1, col=1
    )
    
    # 2. Annual averages
    fig.add_trace(
        go.Bar(
            x=yearly["year"], y=yearly["mean"],
            error_y=dict(type="data", array=yearly["std"]),
            marker_color="#2ca02c", name="Annual avg",
            hovertemplate="Year: %{x}<br>Avg: %{y:.2f}m<extra></extra>"
        ),
        row=1, col=2
    )
    
    # 3. Seasonal pattern (wet vs dry season colors)
    season_colors = ["#ff7f0e" if m in [1,2,3,4,5,11,12] else "#1f77b4" 
                     for m in monthly["month"]]
    fig.add_trace(
        go.Bar(
            x=month_names, y=monthly["mean"],
            error_y=dict(type="data", array=monthly["std"]),
            marker_color=season_colors, name="Monthly avg",
            hovertemplate="%{x}: %{y:.2f}m<extra></extra>"
        ),
        row=2, col=1
    )
    
    # 4. Year-over-year comparison (overlay each year)
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
              "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
    for i, year in enumerate(sorted(gw["year"].unique())):
        year_data = gw[gw["year"] == year].copy()
        year_data["doy"] = year_data.index.dayofyear
        fig.add_trace(
            go.Scatter(
                x=year_data["doy"], y=year_data["water_level_m"],
                mode="lines", name=str(year),
                line=dict(color=colors[i % len(colors)], width=1.5),
                opacity=0.7,
                hovertemplate=f"{year}<br>Day %{{x}}: %{{y:.2f}}m<extra></extra>"
            ),
            row=2, col=2
        )
    
    # 5. Anomaly
    fig.add_trace(
        go.Scatter(
            x=gw.index, y=gw["anomaly"],
            mode="lines", name="Anomaly",
            line=dict(color="#9467bd", width=1),
            fill="tozeroy",
            fillcolor="rgba(148, 103, 189, 0.3)",
            hovertemplate="Date: %{x}<br>Anomaly: %{y:.3f}m<extra></extra>"
        ),
        row=3, col=1
    )
    fig.add_hline(y=0, line_color="black", line_width=1, row=3, col=1)
    
    # 6. Rate of change
    fig.add_trace(
        go.Scatter(
            x=rate_dates, y=rates,
            mode="lines", name="3yr rate",
            line=dict(color="#17becf", width=2),
            fill="tozeroy",
            fillcolor="rgba(23, 190, 207, 0.3)",
            hovertemplate="Date: %{x}<br>Rate: %{y:.4f} m/yr<extra></extra>"
        ),
        row=3, col=2
    )
    fig.add_hline(y=0, line_color="black", line_width=1, row=3, col=2)
    
    # Trend text
    if annual_change > 0.005:
        trend_text = f"Declining ({annual_change:.4f} m/yr)"
    elif annual_change < -0.005:
        trend_text = f"Rising ({abs(annual_change):.4f} m/yr)"
    else:
        trend_text = "Stable"
    
    # Layout
    fig.update_layout(
        title=dict(
            text=f"<b>Fort Myers Groundwater Analysis ({start_year}-{end_year})</b><br>"
                 f"<sub>USGS Data | {years_span:.1f} Years | {len(gw):,} days | "
                 f"Trend: {trend_text} | Change: {total_change:.2f}m</sub>",
            x=0.5,
            font=dict(size=18)
        ),
        height=950,
        showlegend=False,
        template="plotly_white",
        margin=dict(t=100, b=50, l=60, r=60)
    )
    
    # Y-axis labels (invert so deeper = lower)
    fig.update_yaxes(title_text="Water Level (m)", row=1, col=1, autorange="reversed")
    fig.update_yaxes(title_text="Water Level (m)", row=1, col=2, autorange="reversed")
    fig.update_yaxes(title_text="Water Level (m)", row=2, col=1, autorange="reversed")
    fig.update_yaxes(title_text="Water Level (m)", row=2, col=2, autorange="reversed")
    fig.update_yaxes(title_text="Anomaly (m)", row=3, col=1)
    fig.update_yaxes(title_text="Rate (m/year)", row=3, col=2)
    
    # X-axis labels
    fig.update_xaxes(title_text="Date", row=1, col=1)
    fig.update_xaxes(title_text="Year", row=1, col=2)
    fig.update_xaxes(title_text="Month", row=2, col=1)
    fig.update_xaxes(title_text="Day of Year", row=2, col=2)
    fig.update_xaxes(title_text="Date", row=3, col=1)
    fig.update_xaxes(title_text="Date", row=3, col=2)
    
    # Save
    PLOTS_DIR.mkdir(exist_ok=True)
    output_path = PLOTS_DIR / "dashboard.html"
    fig.write_html(str(output_path), full_html=True, include_plotlyjs=True)
    print(f"   ✓ Saved: {output_path}")
    
    return str(output_path)


def generate_trend_report() -> str:
    """Generate text report on groundwater trends."""
    gw = load_groundwater_data()
    
    x = np.arange(len(gw))
    mask = ~np.isnan(gw["water_level_m"].values)
    slope, intercept = np.polyfit(x[mask], gw["water_level_m"].values[mask], 1)
    annual_change = slope * 365
    total_change = slope * len(gw)
    
    gw = gw.copy()
    gw["month"] = gw.index.month
    gw["year"] = gw.index.year
    monthly = gw.groupby("month")["water_level_m"].mean()
    yearly = gw.groupby("year")["water_level_m"].mean()
    
    month_names = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    
    if annual_change > 0.005:
        trend_text = f"DECLINING ({annual_change:.4f} m/year)"
    elif annual_change < -0.005:
        trend_text = f"RISING ({abs(annual_change):.4f} m/year)"
    else:
        trend_text = "STABLE"
    
    years_span = (gw.index.max() - gw.index.min()).days / 365.25
    
    report = f"""
================================================================================
    FORT MYERS GROUNDWATER TREND REPORT
    Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
================================================================================

DATA SOURCE
-----------
Source: USGS National Water Information System (NWIS)
Location: Fort Myers, FL area (Lee County)
URL: https://waterservices.usgs.gov/

DATA SUMMARY
------------
Period: {gw.index.min().strftime('%Y-%m-%d')} to {gw.index.max().strftime('%Y-%m-%d')}
Total Days: {len(gw):,}
Years: {years_span:.1f}

WATER LEVEL STATISTICS
----------------------
Average: {gw['water_level_m'].mean():.3f} m (below land surface)
Std Dev: {gw['water_level_m'].std():.3f} m
Minimum: {gw['water_level_m'].min():.3f} m (shallowest)
Maximum: {gw['water_level_m'].max():.3f} m (deepest)

TREND ANALYSIS
--------------
Overall Trend: {trend_text}
Annual Change: {annual_change:.4f} m/year
Total Change: {total_change:.2f} m

SEASONAL PATTERN
----------------
Shallowest: {month_names[monthly.idxmin() - 1]} ({monthly.min():.3f} m)
Deepest: {month_names[monthly.idxmax() - 1]} ({monthly.max():.3f} m)
Seasonal Range: {monthly.max() - monthly.min():.3f} m

YEARLY BREAKDOWN
----------------"""
    
    for year in sorted(yearly.index):
        report += f"\n{year}: {yearly[year]:.3f} m"
    
    report += f"""

================================================================================
Data: Real USGS measurements
Report: GroundwaterGPT
================================================================================
"""
    
    output_path = PLOTS_DIR / "trend_report.txt"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(report)
    
    return str(output_path)


def main():
    """Generate dashboard and trend report (groundwater only)."""
    print("\n" + "=" * 60)
    print("GROUNDWATER DASHBOARD GENERATOR")
    print("(Groundwater only - no climate correlations)")
    print("=" * 60)
    
    print("\n📝 Generating trend report...")
    report_path = generate_trend_report()
    print(f"   ✓ Saved: {report_path}")
    
    if PLOTLY_AVAILABLE:
        print("\n🎨 Creating interactive dashboard...")
        dashboard_path = create_dashboard()
        print(f"\n💡 Open: {dashboard_path}")
    else:
        print("\n⚠️  Install plotly: pip install plotly")
    
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
