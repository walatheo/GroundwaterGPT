"""
GroundwaterGPT Visualization Module.

Integrated Plotly visualizations for Streamlit.
Phase 3: Visualization Integration - Embedded directly in the app.

Features:
- Site selector dropdown (all 6 Florida USGS sites)
- Time range picker
- Real-time data visualization
- Interactive Plotly charts (no external HTML)

Usage:
    streamlit run src/ui/visualization.py --server.port 8503
    # Or integrate into research_chat.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# Add parent directories to path for imports
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from config import DATA_DIR

# If config.DATA_DIR is wrong (points to config/data), use correct path
if not (DATA_DIR / "usgs_251241080385301.csv").exists():
    DATA_DIR = ROOT_DIR / "data"

# Check for plotly
try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# Site metadata for all Florida USGS monitoring sites
FLORIDA_SITES = {
    "251241080385301": {
        "name": "Miami-Dade G-3764",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "description": "Urban monitoring well in Miami-Dade County",
    },
    "251457080395802": {
        "name": "Miami-Dade G-3759",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "description": "Monitoring well near Miami",
    },
    "251922080340701": {
        "name": "Miami-Dade G-3855",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "description": "Eastern Miami-Dade monitoring well",
    },
    "252007080335701": {
        "name": "Miami-Dade G-561",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "description": "Historic monitoring site",
    },
    "252036080293501": {
        "name": "Miami-Dade G-1251",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "description": "Coastal monitoring well",
    },
    "262724081260701": {
        "name": "Lee County - Fort Myers",
        "aquifer": "Floridan Aquifer",
        "county": "Lee",
        "description": "Deep aquifer monitoring in Fort Myers",
    },
}


def get_available_sites() -> list:
    """Get list of available USGS sites with data files."""
    available = []
    for site_id in FLORIDA_SITES.keys():
        csv_path = DATA_DIR / f"usgs_{site_id}.csv"
        if csv_path.exists():
            available.append(site_id)
    return available


def load_site_data(site_id: str) -> pd.DataFrame:
    """Load USGS data for a specific site.

    Args:
        site_id: USGS site number

    Returns:
        DataFrame with datetime index and water level data
    """
    csv_path = DATA_DIR / f"usgs_{site_id}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No data file for site {site_id}")

    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    df = df.sort_values("datetime")
    df = df.set_index("datetime")

    # Rename value column for clarity
    df = df.rename(columns={"value": "water_level_ft"})

    return df


def load_all_sites() -> dict:
    """Load data for all available sites.

    Returns:
        Dictionary mapping site_id to DataFrame
    """
    data = {}
    for site_id in get_available_sites():
        try:
            data[site_id] = load_site_data(site_id)
        except Exception as e:
            st.warning(f"Could not load site {site_id}: {e}")
    return data


def calculate_statistics(df: pd.DataFrame) -> dict:
    """Calculate summary statistics for a site.

    Args:
        df: DataFrame with water_level_ft column

    Returns:
        Dictionary of statistics
    """
    wl = df["water_level_ft"]

    # Linear trend
    x = np.arange(len(df))
    mask = ~np.isnan(wl.values)
    if mask.sum() > 2:
        slope, intercept = np.polyfit(x[mask], wl.values[mask], 1)
        annual_change = slope * 365
        trend = "rising" if slope > 0 else "falling" if slope < 0 else "stable"
    else:
        annual_change = 0
        trend = "unknown"

    return {
        "record_count": len(df),
        "date_range": f"{df.index.min().strftime('%Y-%m-%d')} to {df.index.max().strftime('%Y-%m-%d')}",
        "min_level": wl.min(),
        "max_level": wl.max(),
        "mean_level": wl.mean(),
        "std_level": wl.std(),
        "latest_level": wl.iloc[-1] if len(wl) > 0 else None,
        "annual_change_ft": annual_change,
        "trend": trend,
    }


def create_time_series_plot(
    df: pd.DataFrame, site_info: dict, show_trend: bool = True, show_rolling_avg: bool = True
) -> go.Figure:
    """Create interactive time series plot.

    Args:
        df: DataFrame with water_level_ft
        site_info: Site metadata dict
        show_trend: Whether to show linear trend line
        show_rolling_avg: Whether to show rolling average

    Returns:
        Plotly figure
    """
    fig = go.Figure()

    # Raw data points
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["water_level_ft"],
            mode="markers",
            name="Measurements",
            marker=dict(size=6, color="#1f77b4", opacity=0.6),
            hovertemplate="%{x|%Y-%m-%d}<br>Level: %{y:.2f} ft<extra></extra>",
        )
    )

    # Rolling average (30-day)
    if show_rolling_avg and len(df) > 30:
        df["roll_30"] = df["water_level_ft"].rolling(30, min_periods=1, center=True).mean()
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["roll_30"],
                mode="lines",
                name="30-day Average",
                line=dict(color="#ff7f0e", width=2),
                hovertemplate="30d avg: %{y:.2f} ft<extra></extra>",
            )
        )

    # Linear trend
    if show_trend and len(df) > 2:
        x = np.arange(len(df))
        mask = ~np.isnan(df["water_level_ft"].values)
        if mask.sum() > 2:
            slope, intercept = np.polyfit(x[mask], df["water_level_ft"].values[mask], 1)
            trend_line = slope * x + intercept
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=trend_line,
                    mode="lines",
                    name="Linear Trend",
                    line=dict(color="#d62728", width=2, dash="dash"),
                    hovertemplate="Trend: %{y:.2f} ft<extra></extra>",
                )
            )

    fig.update_layout(
        title=f"📈 {site_info['name']} - Water Levels",
        xaxis_title="Date",
        yaxis_title="Water Level (ft below land surface)",
        template="plotly_white",
        hovermode="x unified",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
    )

    # Note: Lower values = higher water table
    fig.update_yaxes(autorange="reversed")

    return fig


def create_seasonal_plot(df: pd.DataFrame, site_info: dict) -> go.Figure:
    """Create seasonal pattern analysis plot.

    Args:
        df: DataFrame with water_level_ft
        site_info: Site metadata dict

    Returns:
        Plotly figure
    """
    df = df.copy()
    df["month"] = df.index.month

    monthly = df.groupby("month")["water_level_ft"].agg(["mean", "std", "min", "max"]).reset_index()

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

    # Color by season (dry vs wet in Florida)
    # Dry: Nov-May (orange), Wet: Jun-Oct (blue)
    colors = ["#ff7f0e" if m in [11, 12, 1, 2, 3, 4, 5] else "#1f77b4" for m in monthly["month"]]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=month_names,
            y=monthly["mean"],
            error_y=dict(type="data", array=monthly["std"]),
            marker_color=colors,
            name="Monthly Average",
            hovertemplate="%{x}<br>Mean: %{y:.2f} ft<br>±%{error_y.array:.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        title=f"🌊 {site_info['name']} - Seasonal Pattern",
        xaxis_title="Month",
        yaxis_title="Water Level (ft below land surface)",
        template="plotly_white",
        annotations=[
            dict(
                x=2,
                y=monthly["mean"].max() + 1,
                text="🌵 Dry Season",
                showarrow=False,
                font=dict(color="#ff7f0e"),
            ),
            dict(
                x=7,
                y=monthly["mean"].max() + 1,
                text="🌧️ Wet Season",
                showarrow=False,
                font=dict(color="#1f77b4"),
            ),
        ],
    )

    fig.update_yaxes(autorange="reversed")

    return fig


def create_annual_comparison_plot(df: pd.DataFrame, site_info: dict) -> go.Figure:
    """Create year-over-year comparison plot.

    Args:
        df: DataFrame with water_level_ft
        site_info: Site metadata dict

    Returns:
        Plotly figure
    """
    df = df.copy()
    df["year"] = df.index.year
    df["day_of_year"] = df.index.dayofyear

    years = sorted(df["year"].unique())

    fig = go.Figure()

    # Color scale from oldest (light) to newest (dark)
    n_years = len(years)
    colors = px.colors.sequential.Blues[3:] if n_years <= 6 else px.colors.sequential.Blues

    for i, year in enumerate(years):
        year_data = df[df["year"] == year]
        color_idx = min(i, len(colors) - 1)
        fig.add_trace(
            go.Scatter(
                x=year_data["day_of_year"],
                y=year_data["water_level_ft"],
                mode="lines",
                name=str(year),
                line=dict(width=2 if year == years[-1] else 1),
                opacity=0.5 + (i / n_years) * 0.5,
                hovertemplate=f"{year}<br>Day %{{x}}<br>Level: %{{y:.2f}} ft<extra></extra>",
            )
        )

    fig.update_layout(
        title=f"📅 {site_info['name']} - Year-over-Year Comparison",
        xaxis_title="Day of Year",
        yaxis_title="Water Level (ft below land surface)",
        template="plotly_white",
        legend=dict(title="Year"),
        xaxis=dict(
            tickmode="array", tickvals=[1, 91, 182, 274], ticktext=["Jan", "Apr", "Jul", "Oct"]
        ),
    )

    fig.update_yaxes(autorange="reversed")

    return fig


def create_multi_site_comparison(all_data: dict) -> go.Figure:
    """Create comparison chart across all sites.

    Args:
        all_data: Dict mapping site_id to DataFrame

    Returns:
        Plotly figure
    """
    fig = go.Figure()

    for site_id, df in all_data.items():
        site_info = FLORIDA_SITES.get(site_id, {"name": site_id})

        # Use 30-day rolling average for cleaner comparison
        if len(df) > 30:
            df["roll_30"] = df["water_level_ft"].rolling(30, min_periods=1).mean()
            y_data = df["roll_30"]
        else:
            y_data = df["water_level_ft"]

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=y_data,
                mode="lines",
                name=f"{site_info['name']} ({site_info.get('aquifer', 'Unknown')})",
                hovertemplate=f"{site_info['name']}<br>%{{x|%Y-%m-%d}}<br>Level: %{{y:.2f}} ft<extra></extra>",
            )
        )

    fig.update_layout(
        title="📊 Multi-Site Comparison (30-day Rolling Average)",
        xaxis_title="Date",
        yaxis_title="Water Level (ft below land surface)",
        template="plotly_white",
        hovermode="x unified",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=1.02),
    )

    fig.update_yaxes(autorange="reversed")

    return fig


def create_dashboard_page():
    """Create the main Streamlit visualization dashboard."""
    if not PLOTLY_AVAILABLE:
        st.error("Plotly is required for visualizations. Install with: pip install plotly")
        return

    st.set_page_config(page_title="GroundwaterGPT Visualization", page_icon="📊", layout="wide")

    st.title("📊 Florida Groundwater Visualization")
    st.markdown("Interactive visualization of USGS groundwater monitoring data")

    # Sidebar controls
    st.sidebar.title("🎛️ Controls")

    # Get available sites
    available_sites = get_available_sites()

    if not available_sites:
        st.error("No USGS data files found in the data directory.")
        return

    # Site selector
    st.sidebar.markdown("### 📍 Site Selection")

    # Create display names for dropdown
    site_options = {
        f"{FLORIDA_SITES[sid]['name']} ({FLORIDA_SITES[sid]['aquifer']})": sid
        for sid in available_sites
    }

    selected_display = st.sidebar.selectbox(
        "Select Monitoring Site", options=list(site_options.keys()), index=0
    )

    selected_site = site_options[selected_display]
    site_info = FLORIDA_SITES[selected_site]

    # Load data
    with st.spinner(f"Loading data for {site_info['name']}..."):
        df = load_site_data(selected_site)

    # Time range picker
    st.sidebar.markdown("### 📅 Time Range")

    min_date = df.index.min().date()
    max_date = df.index.max().date()

    date_range = st.sidebar.date_input(
        "Select Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date
    )

    # Handle single date selection
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = min_date, max_date

    # Filter data by date range
    df_filtered = df[(df.index.date >= start_date) & (df.index.date <= end_date)]

    # Visualization options
    st.sidebar.markdown("### ⚙️ Options")
    show_trend = st.sidebar.checkbox("Show Trend Line", value=True)
    show_rolling = st.sidebar.checkbox("Show Rolling Average", value=True)

    # Quick date range buttons
    st.sidebar.markdown("### ⏱️ Quick Ranges")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("Last Year"):
            one_year_ago = max_date - timedelta(days=365)
            st.session_state["date_range"] = (one_year_ago, max_date)
            st.rerun()
    with col2:
        if st.button("All Time"):
            st.session_state["date_range"] = (min_date, max_date)
            st.rerun()

    # Main content area
    # Site info header
    st.markdown(f"## 📍 {site_info['name']}")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Aquifer", site_info["aquifer"])
    with col2:
        st.metric("County", site_info["county"])
    with col3:
        st.metric("Records", f"{len(df_filtered):,}")
    with col4:
        stats = calculate_statistics(df_filtered)
        trend_emoji = (
            "📈" if stats["trend"] == "rising" else "📉" if stats["trend"] == "falling" else "➡️"
        )
        st.metric("Trend", f"{trend_emoji} {stats['trend'].title()}")

    # Statistics summary
    with st.expander("📊 Summary Statistics", expanded=True):
        stats = calculate_statistics(df_filtered)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Min Level", f"{stats['min_level']:.2f} ft")
        with col2:
            st.metric("Max Level", f"{stats['max_level']:.2f} ft")
        with col3:
            st.metric("Mean Level", f"{stats['mean_level']:.2f} ft")
        with col4:
            st.metric("Annual Change", f"{stats['annual_change_ft']:.3f} ft/yr")

        st.caption(f"Date range: {stats['date_range']}")

    # Main visualizations
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📈 Time Series", "🌊 Seasonal Pattern", "📅 Year Comparison", "🗺️ Multi-Site"]
    )

    with tab1:
        fig = create_time_series_plot(
            df_filtered, site_info, show_trend=show_trend, show_rolling_avg=show_rolling
        )
        st.plotly_chart(fig, use_container_width=True)

        st.info(
            """
        **Reading the chart:**
        - Lower values = higher water table (closer to surface)
        - Higher values = deeper water table (further from surface)
        - Orange line: 30-day rolling average smooths daily variations
        - Red dashed line: Linear trend over selected period
        """
        )

    with tab2:
        fig = create_seasonal_plot(df_filtered, site_info)
        st.plotly_chart(fig, use_container_width=True)

        st.info(
            """
        **Florida Seasons:**
        - 🌵 **Dry Season** (Nov-May): Lower rainfall, typically deeper water levels
        - 🌧️ **Wet Season** (Jun-Oct): Hurricane season, higher rainfall, shallower water levels
        """
        )

    with tab3:
        fig = create_annual_comparison_plot(df_filtered, site_info)
        st.plotly_chart(fig, use_container_width=True)

        st.info(
            """
        **Year-over-Year Analysis:**
        - Compare seasonal patterns across different years
        - Newer years shown with bolder lines
        - Helps identify long-term changes in aquifer behavior
        """
        )

    with tab4:
        st.markdown("### Compare All Florida Monitoring Sites")

        with st.spinner("Loading all sites..."):
            all_data = load_all_sites()

        if len(all_data) > 1:
            fig = create_multi_site_comparison(all_data)
            st.plotly_chart(fig, use_container_width=True)

            st.info(
                """
            **Multi-Site Comparison:**
            - Compare water levels across different aquifers
            - Biscayne Aquifer (Miami-Dade): Shallow, quick response to rainfall
            - Floridan Aquifer (Lee County): Deep, slower changes
            """
            )

            # Site summary table
            st.markdown("### 📋 Site Summary")
            summary_data = []
            for site_id, df in all_data.items():
                info = FLORIDA_SITES[site_id]
                stats = calculate_statistics(df)
                summary_data.append(
                    {
                        "Site": info["name"],
                        "Aquifer": info["aquifer"],
                        "County": info["county"],
                        "Records": stats["record_count"],
                        "Min (ft)": f"{stats['min_level']:.2f}",
                        "Max (ft)": f"{stats['max_level']:.2f}",
                        "Mean (ft)": f"{stats['mean_level']:.2f}",
                        "Trend": stats["trend"],
                    }
                )

            st.dataframe(pd.DataFrame(summary_data), use_container_width=True)
        else:
            st.warning("Need at least 2 sites for comparison.")

    # Footer
    st.markdown("---")
    st.caption("Data source: USGS National Water Information System (NWIS)")


# For standalone use
if __name__ == "__main__":
    create_dashboard_page()
