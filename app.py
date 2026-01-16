"""
GroundwaterGPT - Main Application Launcher

A self-sustaining groundwater research agent with user-facing tools.

Components:
1. Deep Research Agent - Autonomous researcher (core)
2. Research Chat - User interface for queries
3. Data Explorer - Explore USGS/groundwater data
4. Dashboard - Visualize trends and forecasts
"""

from pathlib import Path

import streamlit as st

# Page configuration
st.set_page_config(
    page_title="GroundwaterGPT", page_icon="💧", layout="wide", initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown(
    """
<style>
.feature-card {
    background-color: #f0f2f6;
    padding: 20px;
    border-radius: 10px;
    margin: 10px 0;
    border-left: 5px solid #1976d2;
}
.status-badge {
    background-color: #4caf50;
    color: white;
    padding: 3px 10px;
    border-radius: 15px;
    font-size: 0.8em;
}
</style>
""",
    unsafe_allow_html=True,
)


def main():
    # Header
    st.title("💧 GroundwaterGPT")
    st.markdown(
        """
    **A self-sustaining AI research agent for groundwater science.**

    This system combines a deep research agent with user-friendly tools for
    researchers and the general public to explore groundwater data and research.
    """
    )

    st.markdown("---")

    # System status
    st.header("📊 System Status")

    col1, col2, col3 = st.columns(3)

    # Knowledge Base Status
    with col1:
        try:
            from agent.knowledge import get_knowledge_stats

            stats = get_knowledge_stats()
            doc_count = stats.get("total_chunks", 0)
            st.metric("📚 Knowledge Base", f"{doc_count:,} docs", "Active")
        except Exception as e:
            st.metric("📚 Knowledge Base", "Error", str(e))

    # Data Status
    with col2:
        try:
            import pandas as pd

            data_path = Path(__file__).parent / "data" / "groundwater.csv"
            if data_path.exists():
                df = pd.read_csv(data_path)
                st.metric("📊 USGS Data", f"{len(df):,} records", "Loaded")
            else:
                st.metric("📊 USGS Data", "Not found", "Run download_data.py")
        except Exception as e:
            st.metric("📊 USGS Data", "Error", str(e))

    # LLM Status
    with col3:
        try:
            from agent.llm_factory import get_llm

            llm = get_llm()
            st.metric("🤖 LLM (Ollama)", "Connected", "llama3.2")
        except Exception as e:
            st.metric("🤖 LLM", "Not connected", "Start Ollama")

    st.markdown("---")

    # Features
    st.header("🚀 Features")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown(
            """
        <div class="feature-card">
            <h3>🔬 Deep Research Agent</h3>
            <span class="status-badge">Core</span>
            <p>The self-sustaining autonomous researcher. It:</p>
            <ul>
                <li>Searches the knowledge base (PDFs, USGS data)</li>
                <li>Conducts web research from verified sources</li>
                <li>Iterates to deepen understanding</li>
                <li><strong>Auto-learns</strong>: Adds verified insights to knowledge base</li>
            </ul>
        </div>
        """,
            unsafe_allow_html=True,
        )

        if st.button("🔬 Open Research Chat", use_container_width=True):
            st.info("Run: `streamlit run research_chat.py --server.port 8502`")

        st.markdown(
            """
        <div class="feature-card">
            <h3>📊 Dashboard</h3>
            <span class="status-badge">Visualization</span>
            <p>Interactive visualizations of groundwater data:</p>
            <ul>
                <li>Water level time series</li>
                <li>Seasonal patterns</li>
                <li>Trend analysis</li>
                <li>Forecasts</li>
            </ul>
        </div>
        """,
            unsafe_allow_html=True,
        )

        if st.button("📊 Open Dashboard", use_container_width=True):
            import webbrowser

            dashboard_path = Path(__file__).parent / "plots" / "dashboard.html"
            if dashboard_path.exists():
                webbrowser.open(f"file://{dashboard_path}")
            else:
                st.warning("Dashboard not found. Run `python dashboard.py` first.")

    with col2:
        st.markdown(
            """
        <div class="feature-card">
            <h3>📈 Data Explorer</h3>
            <span class="status-badge">Analysis</span>
            <p>For researchers to explore and analyze data:</p>
            <ul>
                <li>USGS groundwater data exploration</li>
                <li>Statistical analysis</li>
                <li>Trend detection</li>
                <li>Data export</li>
            </ul>
        </div>
        """,
            unsafe_allow_html=True,
        )

        if st.button("📈 Open Data Explorer", use_container_width=True):
            st.info("Run: `streamlit run data_explorer.py --server.port 8503`")

        st.markdown(
            """
        <div class="feature-card">
            <h3>🎯 Source Verification</h3>
            <span class="status-badge">Quality</span>
            <p>Ensures data quality and accuracy:</p>
            <ul>
                <li>USGS numerical data (priority: 1.0)</li>
                <li>Research papers/DOI (priority: 0.95)</li>
                <li>Government sources (priority: 0.9)</li>
                <li>Academic institutions (priority: 0.85)</li>
            </ul>
        </div>
        """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # Architecture
    st.header("🏗️ Architecture")

    st.markdown(
        """
    ```
    ┌─────────────────────────────────────────────────────────────────┐
    │                    DEEP RESEARCH AGENT                          │
    │         (Self-sustaining autonomous researcher)                 │
    │                                                                 │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
    │  │ Knowledge   │  │ Web Search  │  │ Source      │             │
    │  │ Base (RAG)  │◄─┤ (DuckDuckGo)│◄─┤ Verification│             │
    │  └──────┬──────┘  └─────────────┘  └─────────────┘             │
    │         │                                                       │
    │         ▼                                                       │
    │  ┌─────────────────────────────────────────────────┐           │
    │  │            AUTO-LEARNING (NEW)                   │           │
    │  │  - Adds verified research to knowledge base      │           │
    │  │  - Only high-confidence insights (≥70%)          │           │
    │  │  - Grows smarter with each query                 │           │
    │  └─────────────────────────────────────────────────┘           │
    └─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                    USER-FACING FEATURES                         │
    │                                                                 │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
    │  │ Research    │  │ Dashboard   │  │ Data        │             │
    │  │ Chat        │  │             │  │ Explorer    │             │
    │  └─────────────┘  └─────────────┘  └─────────────┘             │
    └─────────────────────────────────────────────────────────────────┘
    ```
    """
    )

    st.markdown("---")

    # Quick start
    st.header("🚀 Quick Start")

    st.markdown(
        """
    **Terminal Commands:**
    ```bash
    # Start Research Chat (main interface)
    streamlit run research_chat.py --server.port 8502

    # Start Data Explorer
    streamlit run data_explorer.py --server.port 8503

    # Generate Dashboard
    python dashboard.py

    # Download fresh USGS data
    python download_data.py
    ```
    """
    )

    # Training data
    st.markdown("---")
    st.header("📚 Training Data Sources")

    st.markdown(
        """
    The agent is trained on:

    | Source | Type | Status |
    |--------|------|--------|
    | USGS NWIS | Groundwater measurements | ✅ 3,641 records |
    | Hydrogeology Glossary | PDF reference | ✅ Indexed |
    | Age Dating Young Groundwater | PDF research | ✅ Indexed |
    | Brines and Evaporites | PDF research | ✅ Indexed |
    | Web Research | Verified sources | ✅ Auto-learning |
    """
    )


if __name__ == "__main__":
    main()
