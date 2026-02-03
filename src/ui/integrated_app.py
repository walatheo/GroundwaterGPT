"""
GroundwaterGPT - Integrated Application.

Combines Research Chat and Data Visualization in a single interface.
Phase 3: Visualization Integration

Features:
- 📚 Query Mode: Fast knowledge base search
- 🔬 Research Mode: Deep web research
- 📊 Visualization: Interactive Plotly charts
- 📍 Multi-site support: All 6 Florida USGS sites

Usage:
    streamlit run src/ui/integrated_app.py --server.port 8501
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Add parent directories to path for imports
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR / "config"))

import streamlit as st

# Data directory (relative to project root, not config)
DATA_DIR = ROOT_DIR / "data"

from src.agent.knowledge import get_knowledge_stats, search_knowledge
from src.agent.research_agent import DeepResearchAgent

# Check for plotly
try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# SITE METADATA (with coordinates for mapping)
# ============================================================================

FLORIDA_SITES = {
    "251241080385301": {
        "name": "Miami-Dade G-3764",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.2114,
        "lon": -80.6481,
        "description": "Urban monitoring well in Miami-Dade County",
    },
    "251457080395802": {
        "name": "Miami-Dade G-3759",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.2492,
        "lon": -80.6661,
        "description": "Monitoring well near Miami",
    },
    "251922080340701": {
        "name": "Miami-Dade G-3855",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.3228,
        "lon": -80.5686,
        "description": "Eastern Miami-Dade monitoring well",
    },
    "252007080335701": {
        "name": "Miami-Dade G-561",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.3353,
        "lon": -80.5658,
        "description": "Historic monitoring site",
    },
    "252036080293501": {
        "name": "Miami-Dade G-1251",
        "aquifer": "Biscayne Aquifer",
        "county": "Miami-Dade",
        "lat": 25.3433,
        "lon": -80.4931,
        "description": "Coastal monitoring well",
    },
    "262724081260701": {
        "name": "Lee County - Fort Myers",
        "aquifer": "Floridan Aquifer",
        "county": "Lee",
        "lat": 26.4567,
        "lon": -81.4353,
        "description": "Deep aquifer monitoring in Fort Myers",
    },
}

# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title="GroundwaterGPT",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown(
    """
<style>
.research-insight {
    background-color: #e8f4ea;
    padding: 10px;
    border-radius: 5px;
    margin: 5px 0;
    border-left: 4px solid #2e7d32;
}
.source-badge {
    background-color: #1976d2;
    color: white;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8em;
}
.metric-card {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 15px;
    border-radius: 10px;
    color: white;
    text-align: center;
}
.site-header {
    background: #f0f2f6;
    padding: 15px;
    border-radius: 10px;
    margin-bottom: 20px;
}
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================================
# SESSION STATE
# ============================================================================

if "research_history" not in st.session_state:
    st.session_state.research_history = []
if "agent" not in st.session_state:
    st.session_state.agent = None
if "current_research" not in st.session_state:
    st.session_state.current_research = None
if "current_query_results" not in st.session_state:
    st.session_state.current_query_results = None
if "is_researching" not in st.session_state:
    st.session_state.is_researching = False
if "selected_site" not in st.session_state:
    st.session_state.selected_site = None

# ============================================================================
# DATA LOADING FUNCTIONS
# ============================================================================


def get_available_sites() -> list:
    """Get list of available USGS sites with data files."""
    available = []
    for site_id in FLORIDA_SITES.keys():
        csv_path = DATA_DIR / f"usgs_{site_id}.csv"
        if csv_path.exists():
            available.append(site_id)
    return available


def load_site_data(site_id: str) -> pd.DataFrame:
    """Load USGS data for a specific site."""
    csv_path = DATA_DIR / f"usgs_{site_id}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No data file for site {site_id}")

    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    df = df.sort_values("datetime")
    df = df.set_index("datetime")
    df = df.rename(columns={"value": "water_level_ft"})

    return df


def load_all_sites() -> dict:
    """Load data for all available sites."""
    data = {}
    for site_id in get_available_sites():
        try:
            data[site_id] = load_site_data(site_id)
        except Exception:
            pass
    return data


def calculate_statistics(df: pd.DataFrame) -> dict:
    """Calculate summary statistics for a site."""
    wl = df["water_level_ft"]

    x = np.arange(len(df))
    mask = ~np.isnan(wl.values)
    if mask.sum() > 2:
        slope, intercept = np.polyfit(x[mask], wl.values[mask], 1)
        annual_change = slope * 365
        trend = "rising" if slope > 0.001 else "falling" if slope < -0.001 else "stable"
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
        "years_span": (df.index.max() - df.index.min()).days / 365.25,
    }


def prepare_data_for_viz(df: pd.DataFrame) -> pd.DataFrame:
    """Add calculated columns for visualization."""
    df = df.copy()

    # Rolling averages
    df["roll_7"] = df["water_level_ft"].rolling(7, min_periods=1).mean()
    df["roll_30"] = df["water_level_ft"].rolling(30, min_periods=7).mean()
    df["roll_90"] = df["water_level_ft"].rolling(90, min_periods=14).mean()
    df["roll_365"] = df["water_level_ft"].rolling(365, min_periods=30).mean()

    # Linear trend
    x = np.arange(len(df))
    mask = ~np.isnan(df["water_level_ft"].values)
    if mask.sum() > 2:
        slope, intercept = np.polyfit(x[mask], df["water_level_ft"].values[mask], 1)
        df["trend"] = slope * x + intercept
        df["anomaly"] = df["water_level_ft"] - df["trend"]

    # Time components
    df["month"] = df.index.month
    df["year"] = df.index.year
    df["day_of_year"] = df.index.dayofyear

    # Daily change
    df["daily_change"] = df["water_level_ft"].diff()

    # Volatility (30-day rolling std)
    df["volatility"] = df["water_level_ft"].rolling(30, min_periods=7).std()

    return df


# ============================================================================
# RESEARCH AGENT FUNCTIONS
# ============================================================================


def initialize_agent(
    max_depth: int,
    use_web: bool,
    timeout: float,
    auto_learn: bool = True,
    min_confidence: float = 0.7,
):
    """Initialize the Deep Research Agent."""
    st.session_state.agent = DeepResearchAgent(
        max_depth=max_depth,
        use_web_search=use_web,
        timeout_seconds=timeout,
        auto_learn=auto_learn,
        min_confidence_for_learning=min_confidence,
    )


def query_knowledge_base(query: str, num_results: int = 10) -> dict:
    """Query the knowledge base directly for fast results."""
    results = search_knowledge(query, k=num_results, score_threshold=0.2)

    usgs_results = []
    pdf_results = []
    other_results = []

    for doc in results:
        doc_type = doc.metadata.get("doc_type", "unknown")
        result_item = {
            "content": doc.page_content,
            "doc_type": doc_type,
            "source": doc.metadata.get("source_file", doc.metadata.get("site_name", "Unknown")),
            "metadata": doc.metadata,
            "similarity": doc.metadata.get("similarity_score", 0),
        }

        if doc_type == "usgs_groundwater_data":
            usgs_results.append(result_item)
        elif doc_type == "hydrogeology_reference":
            pdf_results.append(result_item)
        else:
            other_results.append(result_item)

    return {
        "query": query,
        "total_results": len(results),
        "usgs_data": usgs_results,
        "pdf_references": pdf_results,
        "other": other_results,
        "timestamp": datetime.now().isoformat(),
    }


# ============================================================================
# VISUALIZATION FUNCTIONS
# ============================================================================


def create_time_series_plot(
    df: pd.DataFrame, site_info: dict, show_trend: bool = True, show_rolling_avg: bool = True
) -> go.Figure:
    """Create interactive time series plot."""
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
        df = df.copy()
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
        height=500,
    )

    fig.update_yaxes(autorange="reversed")

    return fig


def create_seasonal_plot(df: pd.DataFrame, site_info: dict) -> go.Figure:
    """Create seasonal pattern analysis plot."""
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

    colors = ["#ff7f0e" if m in [11, 12, 1, 2, 3, 4, 5] else "#1f77b4" for m in monthly["month"]]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=month_names,
            y=monthly["mean"],
            error_y=dict(type="data", array=monthly["std"]),
            marker_color=colors,
            name="Monthly Average",
            hovertemplate="%{x}<br>Mean: %{y:.2f} ft<extra></extra>",
        )
    )

    fig.update_layout(
        title=f"🌊 {site_info['name']} - Seasonal Pattern",
        xaxis_title="Month",
        yaxis_title="Water Level (ft below land surface)",
        template="plotly_white",
        height=400,
    )

    fig.update_yaxes(autorange="reversed")

    return fig


def create_multi_site_comparison(all_data: dict) -> go.Figure:
    """Create comparison chart across all sites."""
    fig = go.Figure()

    for site_id, df in all_data.items():
        site_info = FLORIDA_SITES.get(site_id, {"name": site_id})

        if len(df) > 30:
            df = df.copy()
            df["roll_30"] = df["water_level_ft"].rolling(30, min_periods=1).mean()
            y_data = df["roll_30"]
        else:
            y_data = df["water_level_ft"]

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=y_data,
                mode="lines",
                name=f"{site_info['name']}",
                hovertemplate=f"{site_info['name']}<br>%{{x|%Y-%m-%d}}<br>Level: %{{y:.2f}} ft<extra></extra>",
            )
        )

    fig.update_layout(
        title="📊 Multi-Site Comparison (30-day Rolling Average)",
        xaxis_title="Date",
        yaxis_title="Water Level (ft below land surface)",
        template="plotly_white",
        hovermode="x unified",
        height=500,
    )

    fig.update_yaxes(autorange="reversed")

    return fig


def create_geographic_map(all_data: dict) -> go.Figure:
    """Create interactive geographic map of monitoring sites.

    Shows all USGS monitoring sites on a Florida map with:
    - Color coding by aquifer type
    - Size based on data availability
    - Hover info with latest water level
    """
    # Prepare data for map
    map_data = []

    for site_id in FLORIDA_SITES.keys():
        info = FLORIDA_SITES[site_id]

        # Get latest data if available
        if site_id in all_data:
            df = all_data[site_id]
            latest_level = df["water_level_ft"].iloc[-1]
            record_count = len(df)
            latest_date = df.index[-1].strftime("%Y-%m-%d")
            has_data = True
        else:
            latest_level = None
            record_count = 0
            latest_date = "No data"
            has_data = False

        map_data.append(
            {
                "site_id": site_id,
                "name": info["name"],
                "aquifer": info["aquifer"],
                "county": info["county"],
                "lat": info["lat"],
                "lon": info["lon"],
                "latest_level": latest_level,
                "record_count": record_count,
                "latest_date": latest_date,
                "has_data": has_data,
            }
        )

    df_map = pd.DataFrame(map_data)

    # Color by aquifer type
    color_map = {"Biscayne Aquifer": "#1f77b4", "Floridan Aquifer": "#ff7f0e"}

    fig = go.Figure()

    for aquifer in df_map["aquifer"].unique():
        df_aq = df_map[df_map["aquifer"] == aquifer]

        # Create hover text
        hover_text = []
        for _, row in df_aq.iterrows():
            if row["has_data"]:
                text = (
                    f"<b>{row['name']}</b><br>"
                    f"Aquifer: {row['aquifer']}<br>"
                    f"County: {row['county']}<br>"
                    f"Latest Level: {row['latest_level']:.2f} ft<br>"
                    f"Date: {row['latest_date']}<br>"
                    f"Records: {row['record_count']:,}"
                )
            else:
                text = (
                    f"<b>{row['name']}</b><br>"
                    f"Aquifer: {row['aquifer']}<br>"
                    f"County: {row['county']}<br>"
                    f"No data available"
                )
            hover_text.append(text)

        fig.add_trace(
            go.Scattergeo(
                lon=df_aq["lon"],
                lat=df_aq["lat"],
                text=hover_text,
                hoverinfo="text",
                name=aquifer,
                marker=dict(
                    size=df_aq["record_count"].apply(lambda x: max(15, min(30, x / 10))),
                    color=color_map.get(aquifer, "#999999"),
                    line=dict(width=2, color="white"),
                    opacity=0.8,
                ),
            )
        )

    fig.update_layout(
        title="🗺️ Florida Groundwater Monitoring Sites",
        geo=dict(
            scope="usa",
            projection_type="albers usa",
            showland=True,
            landcolor="rgb(243, 243, 243)",
            showocean=True,
            oceancolor="rgb(204, 229, 255)",
            showlakes=True,
            lakecolor="rgb(204, 229, 255)",
            showrivers=True,
            rivercolor="rgb(204, 229, 255)",
            center=dict(lat=26.0, lon=-81.0),
            lonaxis=dict(range=[-82.5, -79.5]),
            lataxis=dict(range=[24.5, 27.5]),
        ),
        height=600,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(255,255,255,0.8)"),
    )

    return fig


def create_heatmap(df: pd.DataFrame, site_info: dict) -> go.Figure:
    """Create a heatmap of water levels by month and year.

    Shows temporal patterns in water level data with:
    - X-axis: Months (Jan-Dec)
    - Y-axis: Years
    - Color: Mean water level
    """
    df = df.copy()
    df["month"] = df.index.month
    df["year"] = df.index.year

    # Create pivot table (mean water level by month/year)
    pivot = df.pivot_table(values="water_level_ft", index="year", columns="month", aggfunc="mean")

    # Month names for x-axis
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

    # Create heatmap
    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values,
            x=month_names,
            y=pivot.index.astype(str),
            colorscale="RdYlBu_r",  # Red=deep, Blue=shallow
            colorbar=dict(title="Water Level (ft)", titleside="right"),
            hovertemplate="Year: %{y}<br>Month: %{x}<br>Level: %{z:.2f} ft<extra></extra>",
        )
    )

    fig.update_layout(
        title=f"🌡️ {site_info['name']} - Water Level Heatmap",
        xaxis_title="Month",
        yaxis_title="Year",
        template="plotly_white",
        height=500,
        yaxis=dict(autorange="reversed"),  # Most recent year at top
    )

    return fig


def create_interactive_time_series(df: pd.DataFrame, site_info: dict) -> go.Figure:
    """Create a fully interactive time series with range slider and buttons.

    Features:
    - Range slider for zooming
    - Preset buttons (1M, 6M, 1Y, ALL)
    - Multiple traces (raw, rolling avg, trend)
    """
    df = df.copy()

    # Calculate rolling averages
    df["roll_7"] = df["water_level_ft"].rolling(7, min_periods=1, center=True).mean()
    df["roll_30"] = df["water_level_ft"].rolling(30, min_periods=1, center=True).mean()
    df["roll_90"] = df["water_level_ft"].rolling(90, min_periods=1, center=True).mean()

    # Calculate trend line
    x = np.arange(len(df))
    mask = ~np.isnan(df["water_level_ft"].values)
    if mask.sum() > 2:
        slope, intercept = np.polyfit(x[mask], df["water_level_ft"].values[mask], 1)
        df["trend"] = slope * x + intercept
    else:
        df["trend"] = df["water_level_ft"].mean()

    fig = go.Figure()

    # Raw data (scatter)
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["water_level_ft"],
            mode="markers",
            name="Daily Measurements",
            marker=dict(size=5, color="#1f77b4", opacity=0.4),
            hovertemplate="%{x|%Y-%m-%d}<br>Level: %{y:.2f} ft<extra></extra>",
        )
    )

    # 7-day rolling average
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["roll_7"],
            mode="lines",
            name="7-day Avg",
            line=dict(color="#2ca02c", width=1),
            visible="legendonly",
            hovertemplate="7d avg: %{y:.2f} ft<extra></extra>",
        )
    )

    # 30-day rolling average
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["roll_30"],
            mode="lines",
            name="30-day Avg",
            line=dict(color="#ff7f0e", width=2),
            hovertemplate="30d avg: %{y:.2f} ft<extra></extra>",
        )
    )

    # 90-day rolling average
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["roll_90"],
            mode="lines",
            name="90-day Avg",
            line=dict(color="#9467bd", width=2),
            visible="legendonly",
            hovertemplate="90d avg: %{y:.2f} ft<extra></extra>",
        )
    )

    # Trend line
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["trend"],
            mode="lines",
            name="Linear Trend",
            line=dict(color="#d62728", width=2, dash="dash"),
            hovertemplate="Trend: %{y:.2f} ft<extra></extra>",
        )
    )

    # Layout with range slider and buttons
    fig.update_layout(
        title=f"📈 {site_info['name']} - Interactive Time Series",
        xaxis_title="Date",
        yaxis_title="Water Level (ft below land surface)",
        template="plotly_white",
        hovermode="x unified",
        height=600,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(
            rangeselector=dict(
                buttons=list(
                    [
                        dict(count=1, label="1M", step="month", stepmode="backward"),
                        dict(count=6, label="6M", step="month", stepmode="backward"),
                        dict(count=1, label="1Y", step="year", stepmode="backward"),
                        dict(count=2, label="2Y", step="year", stepmode="backward"),
                        dict(step="all", label="ALL"),
                    ]
                )
            ),
            rangeslider=dict(visible=True),
            type="date",
        ),
    )

    fig.update_yaxes(autorange="reversed")

    return fig


def create_box_plot_by_year(df: pd.DataFrame, site_info: dict) -> go.Figure:
    """Create box plots showing water level distribution by year."""
    df = df.copy()
    df["year"] = df.index.year

    fig = go.Figure()

    years = sorted(df["year"].unique())

    for year in years:
        year_data = df[df["year"] == year]["water_level_ft"]
        fig.add_trace(
            go.Box(
                y=year_data,
                name=str(year),
                boxmean=True,
                hovertemplate=f"{year}<br>Level: %{{y:.2f}} ft<extra></extra>",
            )
        )

    fig.update_layout(
        title=f"📊 {site_info['name']} - Distribution by Year",
        xaxis_title="Year",
        yaxis_title="Water Level (ft below land surface)",
        template="plotly_white",
        height=500,
        showlegend=False,
    )

    fig.update_yaxes(autorange="reversed")

    return fig


# ============================================================================
# DISPLAY FUNCTIONS
# ============================================================================


def display_query_results(results: dict):
    """Display knowledge base query results."""
    st.markdown(f"### 📚 Results for: *{results['query']}*")
    st.markdown(f"Found **{results['total_results']}** relevant documents")

    usgs_data = results.get("usgs_data", [])
    if usgs_data:
        st.markdown("#### 📊 USGS Groundwater Data")
        for i, item in enumerate(usgs_data, 1):
            with st.expander(f"📍 {item['source']}", expanded=(i <= 2)):
                st.markdown(item["content"])
                st.caption(f"Similarity: {item['similarity']:.2%}")

    pdf_refs = results.get("pdf_references", [])
    if pdf_refs:
        st.markdown("#### 📖 Hydrogeology References")
        for i, item in enumerate(pdf_refs[:5], 1):
            with st.expander(f"📄 {item['source']}", expanded=False):
                st.markdown(item["content"])

    other = results.get("other", [])
    if other:
        st.markdown("#### 🔍 Other Sources")
        for item in other[:3]:
            with st.expander(f"📝 {item['source']}", expanded=False):
                st.markdown(item["content"])

    if results["total_results"] == 0:
        st.warning("No results found. Try different keywords or use Research Mode.")


def display_research_result(result: dict):
    """Display a research result."""
    st.markdown("### 📝 Research Report")
    st.markdown(result.get("report", "No report generated."))

    insights = result.get("insights", [])
    if insights:
        with st.expander(f"🔍 Research Insights ({len(insights)} found)", expanded=True):
            for i, insight in enumerate(insights, 1):
                confidence = insight.get("confidence", 0)
                verified = insight.get("verified", False)

                if confidence >= 0.8:
                    color = "#2e7d32"
                elif confidence >= 0.5:
                    color = "#f57c00"
                else:
                    color = "#d32f2f"

                st.markdown(
                    f"""
                <div class="research-insight">
                    <strong>Insight {i}</strong>
                    <span class="source-badge">{'✓ Verified' if verified else '? Unverified'}</span>
                    <span style="color: {color}">Confidence: {confidence:.0%}</span>
                    <br>{insight.get('content', '')}
                </div>
                """,
                    unsafe_allow_html=True,
                )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Research Depth", f"{result.get('depth_reached', 0)} / 3")
    with col2:
        st.metric("Sources", len(result.get("sources", [])))
    with col3:
        st.metric("Time", f"{result.get('elapsed_seconds', 0):.1f}s")


# ============================================================================
# MAIN TABS
# ============================================================================


def render_research_tab():
    """Render the research/query tab."""
    st.markdown("## 🔬 Research Assistant")

    # Mode selection
    mode = st.radio(
        "Select mode:",
        ["📚 Query Mode (Fast)", "🔬 Research Mode (Deep)"],
        horizontal=True,
        help="Query Mode searches your knowledge base. Research Mode does deep web research.",
    )

    is_query_mode = "Query" in mode

    if is_query_mode:
        st.info("**Query Mode**: Instantly search USGS data and hydrogeology references")
    else:
        st.info("**Research Mode**: Deep research with web search (takes longer)")

    # Query input
    query = st.text_area(
        "🔍 Your Question",
        placeholder="e.g., What are the groundwater levels in the Biscayne Aquifer?",
        height=80,
    )

    if is_query_mode:
        col1, col2 = st.columns([2, 1])
        with col1:
            search_btn = st.button("🔍 Search", type="primary", use_container_width=True)
        with col2:
            num_results = st.selectbox("Results:", [5, 10, 20], index=1)

        if search_btn and query:
            with st.spinner("Searching..."):
                results = query_knowledge_base(query, num_results=num_results)
                st.session_state.current_query_results = results

        if st.session_state.current_query_results:
            display_query_results(st.session_state.current_query_results)

    else:
        # Research mode
        if st.session_state.agent is None:
            initialize_agent(3, True, 180, True, 0.7)

        if st.button("🚀 Start Research", type="primary") and query:
            with st.spinner("Researching (up to 3 minutes)..."):
                try:
                    result = st.session_state.agent.research(query, max_depth=3, timeout=180)
                    st.session_state.current_research = result
                    st.success("✅ Research complete!")
                except Exception as e:
                    st.error(f"Research failed: {e}")

        if st.session_state.current_research:
            display_research_result(st.session_state.current_research)


def render_visualization_tab():
    """Render the visualization tab with enhanced charts."""
    if not PLOTLY_AVAILABLE:
        st.error("Plotly required. Install with: `pip install plotly`")
        return

    st.markdown("## 📊 Data Visualization")

    available_sites = get_available_sites()

    if not available_sites:
        st.error("No USGS data files found.")
        return

    # Load all data for map and comparisons
    all_data = load_all_sites()

    # Main visualization tabs
    viz_main_tabs = st.tabs(["🗺️ Geographic Map", "📈 Time Series", "🌡️ Heatmap", "📊 Analysis"])

    # ============================================================
    # TAB 1: GEOGRAPHIC MAP
    # ============================================================
    with viz_main_tabs[0]:
        st.markdown("### 🗺️ Florida Monitoring Sites")
        st.markdown("Interactive map showing all USGS groundwater monitoring sites")

        fig_map = create_geographic_map(all_data)
        st.plotly_chart(fig_map, use_container_width=True)

        # Site summary table
        st.markdown("### 📋 Site Details")
        summary_data = []
        for sid in available_sites:
            info = FLORIDA_SITES[sid]
            if sid in all_data:
                s = calculate_statistics(all_data[sid])
                summary_data.append(
                    {
                        "Site": info["name"],
                        "Aquifer": info["aquifer"],
                        "County": info["county"],
                        "Records": s["record_count"],
                        "Latest (ft)": f"{all_data[sid]['water_level_ft'].iloc[-1]:.2f}",
                        "Mean (ft)": f"{s['mean_level']:.2f}",
                        "Trend": s["trend"],
                    }
                )

        st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)

        st.info(
            """
        **About the Map:**
        - 🔵 **Blue markers**: Biscayne Aquifer (shallow, Miami-Dade County)
        - 🟠 **Orange markers**: Floridan Aquifer (deep, Lee County)
        - Marker size indicates amount of data available
        - Hover over markers for details
        """
        )

    # ============================================================
    # TAB 2: INTERACTIVE TIME SERIES
    # ============================================================
    with viz_main_tabs[1]:
        st.markdown("### 📈 Interactive Time Series")

        # Site selector
        col1, col2 = st.columns([3, 1])

        with col1:
            site_options = {
                f"{FLORIDA_SITES[sid]['name']} ({FLORIDA_SITES[sid]['aquifer']})": sid
                for sid in available_sites
            }

            selected_display = st.selectbox(
                "📍 Select Monitoring Site", options=list(site_options.keys()), key="ts_site_select"
            )

            selected_site = site_options[selected_display]
            site_info = FLORIDA_SITES[selected_site]

        with col2:
            compare_mode = st.checkbox("Compare All Sites", key="ts_compare")

        if compare_mode:
            # Multi-site comparison
            fig = create_multi_site_comparison(all_data)
            st.plotly_chart(fig, use_container_width=True)
        else:
            # Load selected site data
            df = load_site_data(selected_site)
            stats = calculate_statistics(df)

            # Stats header
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Aquifer", site_info["aquifer"].replace(" Aquifer", ""))
            with col2:
                st.metric("Records", f"{stats['record_count']:,}")
            with col3:
                st.metric("Min", f"{stats['min_level']:.2f} ft")
            with col4:
                st.metric("Max", f"{stats['max_level']:.2f} ft")
            with col5:
                trend_emoji = (
                    "📈"
                    if stats["trend"] == "rising"
                    else "📉" if stats["trend"] == "falling" else "➡️"
                )
                st.metric("Trend", f"{trend_emoji} {stats['trend'].title()}")

            # Interactive time series with range slider
            fig = create_interactive_time_series(df, site_info)
            st.plotly_chart(fig, use_container_width=True)

            st.info(
                """
            **Controls:**
            - Use the **range slider** at the bottom to zoom
            - Click **1M, 6M, 1Y, 2Y, ALL** buttons to quick-select time ranges
            - Toggle traces in the legend (click to show/hide)
            - Hover for detailed values
            """
            )

    # ============================================================
    # TAB 3: HEATMAP
    # ============================================================
    with viz_main_tabs[2]:
        st.markdown("### 🌡️ Water Level Heatmap")
        st.markdown("Visualize temporal patterns in water levels by month and year")

        # Site selector for heatmap
        site_options_hm = {f"{FLORIDA_SITES[sid]['name']}": sid for sid in available_sites}

        selected_hm = st.selectbox(
            "📍 Select Site for Heatmap", options=list(site_options_hm.keys()), key="hm_site_select"
        )

        selected_site_hm = site_options_hm[selected_hm]
        site_info_hm = FLORIDA_SITES[selected_site_hm]
        df_hm = load_site_data(selected_site_hm)

        # Create heatmap
        fig_hm = create_heatmap(df_hm, site_info_hm)
        st.plotly_chart(fig_hm, use_container_width=True)

        st.info(
            """
        **Reading the Heatmap:**
        - **Red/Orange**: Deeper water levels (further from surface)
        - **Blue/Cyan**: Shallower water levels (closer to surface)
        - Look for seasonal patterns (horizontal bands)
        - Look for long-term trends (vertical gradients)
        """
        )

        # Add seasonal pattern below
        st.markdown("### 🌊 Seasonal Pattern")
        fig_seasonal = create_seasonal_plot(df_hm, site_info_hm)
        st.plotly_chart(fig_seasonal, use_container_width=True)

    # ============================================================
    # TAB 4: ANALYSIS (Box Plots, Statistics)
    # ============================================================
    with viz_main_tabs[3]:
        st.markdown("### � Statistical Analysis")

        # Site selector for analysis
        site_options_an = {f"{FLORIDA_SITES[sid]['name']}": sid for sid in available_sites}

        selected_an = st.selectbox(
            "📍 Select Site for Analysis",
            options=list(site_options_an.keys()),
            key="an_site_select",
        )

        selected_site_an = site_options_an[selected_an]
        site_info_an = FLORIDA_SITES[selected_site_an]
        df_an = load_site_data(selected_site_an)
        stats_an = calculate_statistics(df_an)

        # Detailed statistics
        st.markdown("#### 📋 Summary Statistics")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Water Level Statistics**")
            stats_df = pd.DataFrame(
                {
                    "Metric": ["Minimum", "Maximum", "Mean", "Std Dev", "Latest"],
                    "Value (ft)": [
                        f"{stats_an['min_level']:.2f}",
                        f"{stats_an['max_level']:.2f}",
                        f"{stats_an['mean_level']:.2f}",
                        f"{stats_an['std_level']:.2f}",
                        f"{stats_an['latest_level']:.2f}" if stats_an["latest_level"] else "N/A",
                    ],
                }
            )
            st.dataframe(stats_df, hide_index=True, use_container_width=True)

        with col2:
            st.markdown("**Data Coverage**")
            coverage_df = pd.DataFrame(
                {
                    "Metric": ["Total Records", "Date Range", "Annual Change", "Trend"],
                    "Value": [
                        f"{stats_an['record_count']:,}",
                        stats_an["date_range"],
                        f"{stats_an['annual_change_ft']:.4f} ft/year",
                        stats_an["trend"].title(),
                    ],
                }
            )
            st.dataframe(coverage_df, hide_index=True, use_container_width=True)

        # Box plot by year
        st.markdown("#### 📦 Distribution by Year")
        fig_box = create_box_plot_by_year(df_an, site_info_an)
        st.plotly_chart(fig_box, use_container_width=True)

        st.info(
            """
        **Reading Box Plots:**
        - **Box**: Shows the interquartile range (IQR, 25th-75th percentile)
        - **Line inside box**: Median value
        - **Diamond**: Mean value
        - **Whiskers**: Extend to 1.5x IQR
        - **Points beyond whiskers**: Outliers
        """
        )


def render_sidebar():
    """Render the sidebar."""
    st.sidebar.title("🌊 GroundwaterGPT")

    # Knowledge base stats
    try:
        kb_stats = get_knowledge_stats()
        st.sidebar.markdown("### 📚 Knowledge Base")
        st.sidebar.info(f"**{kb_stats.get('total_documents', 0):,}** documents")
    except Exception:
        st.sidebar.warning("KB unavailable")

    # Data stats
    st.sidebar.markdown("### 📊 Data Coverage")
    available = get_available_sites()
    st.sidebar.info(f"**{len(available)}** USGS monitoring sites")

    # Quick links
    st.sidebar.markdown("### 🔗 Quick Links")
    st.sidebar.markdown(
        """
    - [USGS NWIS](https://waterdata.usgs.gov/nwis)
    - [Florida Aquifers](https://floridadep.gov/fgs/aquifer)
    """
    )

    st.sidebar.markdown("---")
    st.sidebar.caption("Phase 3: Visualization Integration")


# ============================================================================
# MAIN APP
# ============================================================================


def main():
    render_sidebar()

    # Main tabs
    tab1, tab2 = st.tabs(["🔬 Research", "📊 Visualization"])

    with tab1:
        render_research_tab()

    with tab2:
        render_visualization_tab()


if __name__ == "__main__":
    main()
