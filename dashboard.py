"""Interactive groundwater trend dashboard with real USGS data.

Creates an interactive HTML dashboard for exploring groundwater trends.

Uses Plotly for interactivity (zoom, pan, hover).
Output: Self-contained HTML file that can be shared without Python.

GROUNDWATER ONLY - No climate correlations.
Data Source: USGS NWIS (National Water Information System)
Site: 262724081260701 - Lee County, FL (Fort Myers area)
"""

from datetime import datetime

import numpy as np
import pandas as pd

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
    """Load groundwater data from USGS NWIS CSV."""
    gw = pd.read_csv(DATA_DIR / "groundwater.csv", parse_dates=["date"])

    # Keep data in feet (original USGS units)
    gw = gw.set_index("date").sort_index()

    # Get site ID for display
    if "site_id" in gw.columns:
        gw["site_id"] = gw["site_id"].astype(str)

    return gw


def create_dashboard() -> str:
    """Create comprehensive interactive HTML dashboard with 8 panels.

    All visualizations use REAL USGS groundwater measurements.
    """
    if not PLOTLY_AVAILABLE:
        raise ImportError("plotly required. Install: pip install plotly")

    print("📊 Loading USGS groundwater data...")
    gw = load_groundwater_data()

    site_id = gw["site_id"].iloc[0] if "site_id" in gw.columns else "Unknown"
    start_date = gw.index.min()
    end_date = gw.index.max()
    start_year = start_date.year
    end_year = end_date.year
    years_span = (end_date - start_date).days / 365.25

    print(f"   ✓ USGS Site: {site_id}")
    print(f"   ✓ Loaded {len(gw):,} days of REAL measurements")
    print(f"   ✓ Period: {start_date.date()} to {end_date.date()}")
    print(
        f"   ✓ Water levels: {gw['water_level_ft'].min():.2f} to {gw['water_level_ft'].max():.2f} ft"
    )

    # Calculate trend
    x = np.arange(len(gw))
    mask = ~np.isnan(gw["water_level_ft"].values)
    slope, intercept = np.polyfit(x[mask], gw["water_level_ft"].values[mask], 1)
    trend_line = slope * x + intercept
    annual_change_ft = slope * 365
    total_change_ft = slope * len(gw)

    # Add calculated columns
    gw = gw.copy()
    gw["roll_7"] = gw["water_level_ft"].rolling(7, min_periods=1).mean()
    gw["roll_30"] = gw["water_level_ft"].rolling(30, min_periods=7).mean()
    gw["roll_90"] = gw["water_level_ft"].rolling(90, min_periods=14).mean()
    gw["roll_365"] = gw["water_level_ft"].rolling(365, min_periods=30).mean()
    gw["trend"] = trend_line
    gw["anomaly"] = gw["water_level_ft"] - trend_line
    gw["month"] = gw.index.month
    gw["year"] = gw.index.year
    gw["day_of_year"] = gw.index.dayofyear
    gw["week"] = gw.index.isocalendar().week

    # Daily change
    gw["daily_change"] = gw["water_level_ft"].diff()

    # Monthly stats
    monthly = gw.groupby("month")["water_level_ft"].agg(["mean", "std", "min", "max"]).reset_index()
    month_names = [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    # Yearly stats
    yearly = (
        gw.groupby("year")["water_level_ft"]
        .agg(["mean", "std", "min", "max", "count"])
        .reset_index()
    )

    # Rate of change (2-year rolling)
    window = 2 * 365
    rates, rate_dates = [], []
    for i in range(window, len(gw), 14):  # Every 2 weeks
        w = gw.iloc[i - window : i]
        xi = np.arange(len(w))
        yi = w["water_level_ft"].values
        m = ~np.isnan(yi)
        if m.sum() > 100:
            s, _ = np.polyfit(xi[m], yi[m], 1)
            rates.append(s * 365)
            rate_dates.append(gw.index[i])

    # Volatility (30-day rolling std)
    gw["volatility"] = gw["water_level_ft"].rolling(30, min_periods=7).std()

    print("🎨 Building 8-panel dashboard...")

    # Create 8-panel dashboard (4x2)
    fig = make_subplots(
        rows=4,
        cols=2,
        subplot_titles=(
            f"📈 Water Level Time Series ({start_year}-{end_year})",
            "📊 Annual Statistics",
            "🌊 Seasonal Pattern",
            "📅 Year-over-Year Comparison",
            "📉 Anomalies from Trend",
            "🔄 Rate of Change (2-Year Rolling)",
            "📐 Daily Changes Distribution",
            "📋 Data Quality & Coverage",
        ),
        specs=[
            [{"type": "scatter"}, {"type": "bar"}],
            [{"type": "bar"}, {"type": "scatter"}],
            [{"type": "scatter"}, {"type": "scatter"}],
            [{"type": "histogram"}, {"type": "bar"}],
        ],
        vertical_spacing=0.08,
        horizontal_spacing=0.08,
    )

    # Color palette
    BLUE = "#1f77b4"
    ORANGE = "#ff7f0e"
    GREEN = "#2ca02c"
    RED = "#d62728"
    PURPLE = "#9467bd"
    CYAN = "#17becf"

    # =========================================================================
    # Panel 1: Time Series with Multiple Averages
    # =========================================================================
    fig.add_trace(
        go.Scatter(
            x=gw.index,
            y=gw["water_level_ft"],
            mode="lines",
            name="Daily",
            line=dict(color=BLUE, width=0.5),
            opacity=0.3,
            hovertemplate="Date: %{x|%Y-%m-%d}<br>Level: %{y:.2f} ft<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=gw.index,
            y=gw["roll_30"],
            mode="lines",
            name="30-day avg",
            line=dict(color=ORANGE, width=1.5),
            hovertemplate="30d avg: %{y:.2f} ft<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=gw.index,
            y=gw["roll_365"],
            mode="lines",
            name="365-day avg",
            line=dict(color=BLUE, width=2.5),
            hovertemplate="365d avg: %{y:.2f} ft<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=gw.index,
            y=gw["trend"],
            mode="lines",
            name="Linear Trend",
            line=dict(color=RED, width=2, dash="dash"),
            hovertemplate="Trend: %{y:.2f} ft<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # =========================================================================
    # Panel 2: Annual Statistics (Box-like bars)
    # =========================================================================
    fig.add_trace(
        go.Bar(
            x=yearly["year"],
            y=yearly["mean"],
            error_y=dict(type="data", array=yearly["std"]),
            marker_color=GREEN,
            name="Annual Mean",
            hovertemplate="Year: %{x}<br>Mean: %{y:.2f} ft<br>±%{error_y.array:.2f}<extra></extra>",
        ),
        row=1,
        col=2,
    )
    # Add min/max range as error bars
    fig.add_trace(
        go.Scatter(
            x=yearly["year"],
            y=yearly["min"],
            mode="markers",
            name="Annual Min",
            marker=dict(color=CYAN, size=8, symbol="triangle-up"),
            hovertemplate="%{x} Min: %{y:.2f} ft<extra></extra>",
        ),
        row=1,
        col=2,
    )
    fig.add_trace(
        go.Scatter(
            x=yearly["year"],
            y=yearly["max"],
            mode="markers",
            name="Annual Max",
            marker=dict(color=RED, size=8, symbol="triangle-down"),
            hovertemplate="%{x} Max: %{y:.2f} ft<extra></extra>",
        ),
        row=1,
        col=2,
    )

    # =========================================================================
    # Panel 3: Seasonal Pattern with Range
    # =========================================================================
    # Dry season (Nov-May) vs Wet season (Jun-Oct) coloring
    season_colors = [ORANGE if m in [11, 12, 1, 2, 3, 4, 5] else BLUE for m in monthly["month"]]
    fig.add_trace(
        go.Bar(
            x=month_names,
            y=monthly["mean"],
            error_y=dict(type="data", array=monthly["std"]),
            marker_color=season_colors,
            name="Monthly Avg",
            hovertemplate="%{x}<br>Mean: %{y:.2f} ft<extra></extra>",
        ),
        row=2,
        col=1,
    )
    # Add annotation for seasons
    fig.add_annotation(
        x=2.5,
        y=monthly["mean"].max() + 1,
        text="🌵 Dry Season",
        showarrow=False,
        font=dict(size=10, color=ORANGE),
        row=2,
        col=1,
    )
    fig.add_annotation(
        x=7.5,
        y=monthly["mean"].max() + 1,
        text="🌧️ Wet Season",
        showarrow=False,
        font=dict(size=10, color=BLUE),
        row=2,
        col=1,
    )

    # =========================================================================
    # Panel 4: Year-over-Year Comparison
    # =========================================================================
    year_colors = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    for i, year in enumerate(sorted(gw["year"].unique())):
        year_data = gw[gw["year"] == year]
        fig.add_trace(
            go.Scatter(
                x=year_data["day_of_year"],
                y=year_data["water_level_ft"],
                mode="lines",
                name=str(year),
                line=dict(color=year_colors[i % len(year_colors)], width=1.5),
                opacity=0.8,
                hovertemplate=f"{year}<br>Day %{{x}}: %{{y:.2f}} ft<extra></extra>",
            ),
            row=2,
            col=2,
        )

    # =========================================================================
    # Panel 5: Anomalies (Detrended)
    # =========================================================================
    # Color by sign
    pos_mask = gw["anomaly"] >= 0
    neg_mask = gw["anomaly"] < 0

    fig.add_trace(
        go.Scatter(
            x=gw.index[pos_mask],
            y=gw["anomaly"][pos_mask],
            mode="lines",
            name="Above Trend",
            line=dict(color=RED, width=1),
            fill="tozeroy",
            fillcolor="rgba(214, 39, 40, 0.3)",
        ),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=gw.index[neg_mask],
            y=gw["anomaly"][neg_mask],
            mode="lines",
            name="Below Trend",
            line=dict(color=BLUE, width=1),
            fill="tozeroy",
            fillcolor="rgba(31, 119, 180, 0.3)",
        ),
        row=3,
        col=1,
    )
    fig.add_hline(y=0, line_color="black", line_width=1, row=3, col=1)

    # =========================================================================
    # Panel 6: Rate of Change
    # =========================================================================
    fig.add_trace(
        go.Scatter(
            x=rate_dates,
            y=rates,
            mode="lines+markers",
            name="Rate",
            line=dict(color=PURPLE, width=2),
            marker=dict(size=3),
            hovertemplate="Date: %{x|%Y-%m-%d}<br>Rate: %{y:.3f} ft/yr<extra></extra>",
        ),
        row=3,
        col=2,
    )
    fig.add_hline(y=0, line_color="black", line_width=1, row=3, col=2)
    # Add overall trend line
    fig.add_hline(
        y=annual_change_ft,
        line_color=RED,
        line_width=2,
        line_dash="dash",
        annotation_text=f"Overall: {annual_change_ft:.3f} ft/yr",
        row=3,
        col=2,
    )

    # =========================================================================
    # Panel 7: Daily Changes Distribution
    # =========================================================================
    daily_changes = gw["daily_change"].dropna()
    fig.add_trace(
        go.Histogram(
            x=daily_changes,
            nbinsx=100,
            marker_color=CYAN,
            name="Daily Change",
            hovertemplate="Change: %{x:.2f} ft<br>Count: %{y}<extra></extra>",
        ),
        row=4,
        col=1,
    )
    fig.add_vline(x=0, line_color="black", line_width=2, row=4, col=1)
    fig.add_vline(
        x=daily_changes.mean(),
        line_color=RED,
        line_width=2,
        line_dash="dash",
        annotation_text=f"Mean: {daily_changes.mean():.3f}",
        row=4,
        col=1,
    )

    # =========================================================================
    # Panel 8: Data Coverage by Year
    # =========================================================================
    coverage = yearly[["year", "count"]].copy()
    coverage["expected"] = 365
    coverage["pct"] = (coverage["count"] / coverage["expected"] * 100).clip(upper=100)

    fig.add_trace(
        go.Bar(
            x=coverage["year"],
            y=coverage["count"],
            marker_color=[
                GREEN if p >= 95 else ORANGE if p >= 80 else RED for p in coverage["pct"]
            ],
            name="Days with Data",
            hovertemplate="Year: %{x}<br>Days: %{y}<br>Coverage: %{customdata:.1f}%<extra></extra>",
            customdata=coverage["pct"],
        ),
        row=4,
        col=2,
    )
    fig.add_hline(
        y=365,
        line_color="black",
        line_width=1,
        line_dash="dot",
        annotation_text="365 days",
        row=4,
        col=2,
    )

    # =========================================================================
    # Layout
    # =========================================================================
    # Trend description
    if annual_change_ft > 0.01:
        trend_desc = f"📈 Declining {annual_change_ft:.3f} ft/yr"
    elif annual_change_ft < -0.01:
        trend_desc = f"📉 Rising {abs(annual_change_ft):.3f} ft/yr"
    else:
        trend_desc = "➡️ Stable"

    fig.update_layout(
        title=dict(
            text=(
                f"<b>🌊 USGS Groundwater Analysis Dashboard</b><br>"
                f"<sub>Site: {site_id} | Lee County, FL | "
                f"<b>{len(gw):,} REAL measurements</b> | "
                f"{years_span:.1f} years ({start_year}-{end_year}) | "
                f"Trend: {trend_desc} | Total Δ: {total_change_ft:.2f} ft</sub>"
            ),
            x=0.5,
            font=dict(size=16),
        ),
        height=1400,
        showlegend=False,
        template="plotly_white",
        margin=dict(t=120, b=60, l=70, r=70),
    )

    # Y-axis labels
    fig.update_yaxes(title_text="Water Level (ft)", row=1, col=1)
    fig.update_yaxes(title_text="Water Level (ft)", row=1, col=2)
    fig.update_yaxes(title_text="Water Level (ft)", row=2, col=1)
    fig.update_yaxes(title_text="Water Level (ft)", row=2, col=2)
    fig.update_yaxes(title_text="Anomaly (ft)", row=3, col=1)
    fig.update_yaxes(title_text="Rate (ft/year)", row=3, col=2)
    fig.update_yaxes(title_text="Frequency", row=4, col=1)
    fig.update_yaxes(title_text="Days with Data", row=4, col=2)

    # X-axis labels
    fig.update_xaxes(title_text="Date", row=1, col=1)
    fig.update_xaxes(title_text="Year", row=1, col=2)
    fig.update_xaxes(title_text="Month", row=2, col=1)
    fig.update_xaxes(title_text="Day of Year", row=2, col=2)
    fig.update_xaxes(title_text="Date", row=3, col=1)
    fig.update_xaxes(title_text="Date", row=3, col=2)
    fig.update_xaxes(title_text="Daily Change (ft)", row=4, col=1)
    fig.update_xaxes(title_text="Year", row=4, col=2)

    # Save
    PLOTS_DIR.mkdir(exist_ok=True)
    output_path = PLOTS_DIR / "dashboard.html"
    fig.write_html(str(output_path), full_html=True, include_plotlyjs=True)
    print(f"\n   ✅ Saved: {output_path}")

    return str(output_path)


def generate_trend_report() -> str:
    """Generate text report on groundwater trends using real USGS data."""
    gw = load_groundwater_data()

    x = np.arange(len(gw))
    mask = ~np.isnan(gw["water_level_ft"].values)
    slope, intercept = np.polyfit(x[mask], gw["water_level_ft"].values[mask], 1)
    annual_change = slope * 365
    total_change = slope * len(gw)

    gw = gw.copy()
    gw["month"] = gw.index.month
    gw["year"] = gw.index.year
    monthly = gw.groupby("month")["water_level_ft"].mean()
    yearly = gw.groupby("year")["water_level_ft"].mean()

    site_id = gw["site_id"].iloc[0] if "site_id" in gw.columns else "Unknown"

    month_names = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]

    if annual_change > 0.01:
        trend_text = f"DECLINING ({annual_change:.3f} ft/year)"
    elif annual_change < -0.01:
        trend_text = f"RISING ({abs(annual_change):.3f} ft/year)"
    else:
        trend_text = "STABLE"

    years_span = (gw.index.max() - gw.index.min()).days / 365.25

    report = f"""
================================================================================
    USGS GROUNDWATER TREND REPORT
    Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
================================================================================

DATA SOURCE
-----------
Source: USGS National Water Information System (NWIS)
Site ID: {site_id}
Location: Lee County, FL (Fort Myers area)
URL: https://waterdata.usgs.gov/nwis/uv?site_no={site_id}

DATA SUMMARY
------------
Period: {gw.index.min().strftime('%Y-%m-%d')} to {gw.index.max().strftime('%Y-%m-%d')}
Total Days: {len(gw):,} REAL measurements
Years: {years_span:.1f}

WATER LEVEL STATISTICS (ft below land surface)
----------------------------------------------
Average: {gw['water_level_ft'].mean():.2f} ft
Std Dev: {gw['water_level_ft'].std():.2f} ft
Minimum: {gw['water_level_ft'].min():.2f} ft (shallowest)
Maximum: {gw['water_level_ft'].max():.2f} ft (deepest)
Range: {gw['water_level_ft'].max() - gw['water_level_ft'].min():.2f} ft

TREND ANALYSIS
--------------
Overall Trend: {trend_text}
Annual Change: {annual_change:.3f} ft/year
Total Change: {total_change:.2f} ft over {years_span:.1f} years

SEASONAL PATTERN (Florida wet/dry seasons)
------------------------------------------
Dry Season (Nov-May): Higher water table (recharge from winter rain)
Wet Season (Jun-Oct): Variable, influenced by storms

Shallowest: {month_names[monthly.idxmin() - 1]} ({monthly.min():.2f} ft)
Deepest: {month_names[monthly.idxmax() - 1]} ({monthly.max():.2f} ft)
Seasonal Range: {monthly.max() - monthly.min():.2f} ft

YEARLY BREAKDOWN
----------------"""

    for year in sorted(yearly.index):
        year_data = gw[gw["year"] == year]["water_level_ft"]
        report += f"\n{year}: Mean {yearly[year]:.2f} ft | Range {year_data.min():.2f}-{year_data.max():.2f} ft | {len(year_data)} days"

    report += f"""

================================================================================
Data Source: REAL USGS measurements (not modeled)
Generated by: GroundwaterGPT
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
