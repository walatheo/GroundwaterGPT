"""
Data Explorer - Interactive tool for researchers to explore groundwater data.

Provides:
- USGS data exploration
- Trend analysis
- Data quality assessment
- Export capabilities
"""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from agent.knowledge import get_knowledge_stats

# Page configuration
st.set_page_config(page_title="GroundwaterGPT Data Explorer", page_icon="📊", layout="wide")

# Data paths
DATA_DIR = Path(__file__).parent / "data"


@st.cache_data
def load_groundwater_data():
    """Load groundwater data from CSV."""
    gw_path = DATA_DIR / "groundwater.csv"
    if gw_path.exists():
        df = pd.read_csv(gw_path)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        elif "date" in df.columns:
            df["datetime"] = pd.to_datetime(df["date"])
        return df
    return None


@st.cache_data
def load_climate_data():
    """Load climate data from CSV."""
    climate_path = DATA_DIR / "climate.csv"
    if climate_path.exists():
        df = pd.read_csv(climate_path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    return None


def calculate_statistics(df: pd.DataFrame, value_col: str) -> dict:
    """Calculate basic statistics for a column."""
    return {
        "count": len(df),
        "mean": df[value_col].mean(),
        "std": df[value_col].std(),
        "min": df[value_col].min(),
        "max": df[value_col].max(),
        "median": df[value_col].median(),
        "missing": df[value_col].isna().sum(),
    }


def main():
    st.title("📊 GroundwaterGPT Data Explorer")
    st.markdown(
        """
    Explore and analyze groundwater data from USGS and other verified sources.
    Use this tool to understand trends, patterns, and data quality.
    """
    )

    # Sidebar
    st.sidebar.title("🔧 Options")

    # Data source selection
    data_source = st.sidebar.selectbox(
        "Data Source", ["Groundwater Levels", "Climate Data", "Knowledge Base"]
    )

    # Main content based on selection
    if data_source == "Groundwater Levels":
        show_groundwater_explorer()
    elif data_source == "Climate Data":
        show_climate_explorer()
    else:
        show_knowledge_explorer()


def show_groundwater_explorer():
    """Display groundwater data exploration interface."""
    st.header("🌊 Groundwater Level Data")

    df = load_groundwater_data()

    if df is None:
        st.warning("No groundwater data found. Run `download_data.py` to fetch USGS data.")
        return

    # Data overview
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Records", f"{len(df):,}")
    with col2:
        if "datetime" in df.columns:
            date_range = (df["datetime"].max() - df["datetime"].min()).days
            st.metric("Date Range", f"{date_range:,} days")
    with col3:
        if "value" in df.columns:
            st.metric("Mean Level", f"{df['value'].mean():.2f} ft")
    with col4:
        if "site_no" in df.columns:
            st.metric("USGS Site", df["site_no"].iloc[0] if len(df) > 0 else "N/A")

    # Visualization options
    st.subheader("📈 Time Series Visualization")

    if "datetime" in df.columns and "value" in df.columns:
        # Date range filter
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", value=df["datetime"].min().date())
        with col2:
            end_date = st.date_input("End Date", value=df["datetime"].max().date())

        # Filter data
        mask = (df["datetime"].dt.date >= start_date) & (df["datetime"].dt.date <= end_date)
        filtered_df = df[mask]

        # Plot
        fig = px.line(
            filtered_df,
            x="datetime",
            y="value",
            title="Groundwater Levels Over Time",
            labels={"datetime": "Date", "value": "Water Level (ft below surface)"},
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)

        # Statistics
        st.subheader("📊 Statistics")
        stats = calculate_statistics(filtered_df, "value")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Mean", f"{stats['mean']:.2f} ft")
        with col2:
            st.metric("Std Dev", f"{stats['std']:.2f} ft")
        with col3:
            st.metric("Min", f"{stats['min']:.2f} ft")
        with col4:
            st.metric("Max", f"{stats['max']:.2f} ft")

        # Monthly aggregation
        st.subheader("📅 Monthly Patterns")
        filtered_df["month"] = filtered_df["datetime"].dt.month
        monthly_avg = filtered_df.groupby("month")["value"].mean().reset_index()
        monthly_avg["month_name"] = monthly_avg["month"].apply(
            lambda x: datetime(2000, x, 1).strftime("%B")
        )

        fig2 = px.bar(
            monthly_avg,
            x="month_name",
            y="value",
            title="Average Water Level by Month",
            labels={"month_name": "Month", "value": "Avg Water Level (ft)"},
        )
        st.plotly_chart(fig2, use_container_width=True)

        # Trend analysis
        st.subheader("📈 Trend Analysis")
        filtered_df["year"] = filtered_df["datetime"].dt.year
        yearly_avg = filtered_df.groupby("year")["value"].mean().reset_index()

        fig3 = px.scatter(
            yearly_avg,
            x="year",
            y="value",
            trendline="ols",
            title="Yearly Average with Trend Line",
            labels={"year": "Year", "value": "Avg Water Level (ft)"},
        )
        st.plotly_chart(fig3, use_container_width=True)

    # Data table
    st.subheader("📋 Raw Data")
    with st.expander("View Data Table"):
        st.dataframe(df.head(100))

    # Export
    st.subheader("💾 Export Data")
    col1, col2 = st.columns(2)
    with col1:
        csv = df.to_csv(index=False)
        st.download_button(
            label="Download CSV", data=csv, file_name="groundwater_data.csv", mime="text/csv"
        )


def show_climate_explorer():
    """Display climate data exploration interface."""
    st.header("🌤️ Climate Data")

    df = load_climate_data()

    if df is None:
        st.warning("No climate data found.")
        return

    st.dataframe(df.head(100))


def show_knowledge_explorer():
    """Display knowledge base exploration interface."""
    st.header("📚 Knowledge Base Explorer")

    try:
        stats = get_knowledge_stats()

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Document Chunks", f"{stats.get('total_chunks', 0):,}")
        with col2:
            st.metric("PDF Files Indexed", stats.get("pdf_files", 0))

        st.subheader("📄 Indexed Documents")
        pdf_names = stats.get("pdf_names", [])
        for name in pdf_names:
            st.markdown(f"- {name}")

        # Search interface
        st.subheader("🔍 Search Knowledge Base")
        from agent.knowledge import search_knowledge

        query = st.text_input("Search query")
        if query:
            with st.spinner("Searching..."):
                results = search_knowledge(query, k=5, score_threshold=0.3)

            if results:
                st.success(f"Found {len(results)} results")
                for i, doc in enumerate(results, 1):
                    with st.expander(f"Result {i}: {doc.metadata.get('source_file', 'Unknown')}"):
                        st.markdown(doc.page_content)
                        st.json(doc.metadata)
            else:
                st.info("No results found")

    except Exception as e:
        st.error(f"Error loading knowledge base: {e}")


if __name__ == "__main__":
    main()
