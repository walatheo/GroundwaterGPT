"""
GroundwaterGPT Research Chat Interface.

The primary interface for interacting with the Deep Research Agent.
This is the main application - it uses the knowledge base (PDFs, USGS data)
and conducts autonomous web research to answer groundwater questions.

Features:
- **Query Mode**: Fast lookup in knowledge base (instant answers)
- **Research Mode**: Deep research with web search (takes longer)
- Configurable timeout to prevent getting stuck
- Stop button for user control
- Progress updates during research

Architecture:
    This module serves as the presentation layer (UI) for the GroundwaterGPT system.
    It connects to:
    - agent.knowledge: Vector database (ChromaDB) for semantic search
    - agent.research_agent: LLM-powered research agent (Ollama/llama3.2)
    - agent.source_verification: Trust scoring for sources

Usage:
    streamlit run research_chat.py --server.port 8502
"""

import logging
from datetime import datetime

import streamlit as st

from agent.knowledge import get_knowledge_stats, search_knowledge
from agent.research_agent import DeepResearchAgent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="GroundwaterGPT Research",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for better styling
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
.verified-badge {
    background-color: #2e7d32;
    color: white;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8em;
}
.timeout-badge {
    background-color: #f57c00;
    color: white;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8em;
}
.stopped-badge {
    background-color: #d32f2f;
    color: white;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.8em;
}
</style>
""",
    unsafe_allow_html=True,
)

# Initialize session state
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
if "research_status" not in st.session_state:
    st.session_state.research_status = "idle"


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


def stop_research():
    """Stop the current research."""
    if st.session_state.agent:
        st.session_state.agent.stop()
        st.session_state.research_status = "stopping..."


def query_knowledge_base(query: str, num_results: int = 10) -> dict:
    """Query the knowledge base directly for fast results.
    
    Args:
        query: The search query
        num_results: Number of results to return
        
    Returns:
        Dictionary with results and metadata
    """
    results = search_knowledge(query, k=num_results, score_threshold=0.2)
    
    # Organize results by type
    usgs_results = []
    pdf_results = []
    other_results = []
    
    for doc in results:
        doc_type = doc.metadata.get('doc_type', 'unknown')
        result_item = {
            'content': doc.page_content,
            'doc_type': doc_type,
            'source': doc.metadata.get('source_file', doc.metadata.get('site_name', 'Unknown')),
            'metadata': doc.metadata,
            'similarity': doc.metadata.get('similarity_score', 0)
        }
        
        if doc_type == 'usgs_groundwater_data':
            usgs_results.append(result_item)
        elif doc_type == 'hydrogeology_reference':
            pdf_results.append(result_item)
        else:
            other_results.append(result_item)
    
    return {
        'query': query,
        'total_results': len(results),
        'usgs_data': usgs_results,
        'pdf_references': pdf_results,
        'other': other_results,
        'timestamp': datetime.now().isoformat()
    }


def display_query_results(results: dict):
    """Display knowledge base query results."""
    st.markdown("---")
    st.markdown(f"### 📚 Knowledge Base Results for: *{results['query']}*")
    st.markdown(f"Found **{results['total_results']}** relevant documents")
    
    # USGS Data Results (priority)
    usgs_data = results.get('usgs_data', [])
    if usgs_data:
        st.markdown("#### 📊 USGS Groundwater Data")
        for i, item in enumerate(usgs_data, 1):
            with st.expander(f"📍 {item['source']}", expanded=(i <= 2)):
                st.markdown(item['content'])
                st.caption(f"Similarity: {item['similarity']:.2%}")
    
    # PDF Reference Results
    pdf_refs = results.get('pdf_references', [])
    if pdf_refs:
        st.markdown("#### 📖 Hydrogeology References")
        for i, item in enumerate(pdf_refs[:5], 1):
            with st.expander(f"📄 {item['source']}", expanded=False):
                st.markdown(item['content'])
                st.caption(f"Similarity: {item['similarity']:.2%}")
    
    # Other Results
    other = results.get('other', [])
    if other:
        st.markdown("#### 🔍 Other Sources")
        for item in other[:3]:
            with st.expander(f"📝 {item['source']}", expanded=False):
                st.markdown(item['content'])
    
    if results['total_results'] == 0:
        st.warning("No results found in knowledge base. Try Research Mode for web search.")


def display_research_result(result: dict):
    """Display a research result in the UI."""
    st.markdown("---")

    # Main report
    st.markdown("### 📝 Research Report")
    st.markdown(result.get("report", "No report generated."))

    # Insights
    insights = result.get("insights", [])
    if insights:
        with st.expander(f"🔍 **Research Insights** ({len(insights)} found)", expanded=True):
            for i, insight in enumerate(insights, 1):
                confidence = insight.get("confidence", 0)
                verified = insight.get("verified", False)
                trust = insight.get("trust_level", "unknown")

                # Color code by confidence
                if confidence >= 0.8:
                    color = "#2e7d32"  # Green
                elif confidence >= 0.5:
                    color = "#f57c00"  # Orange
                else:
                    color = "#d32f2f"  # Red

                st.markdown(
                    f"""
                <div class="research-insight">
                    <strong>Insight {i}</strong>
                    <span class="verified-badge">{'✓ Verified' if verified else '? Unverified'}</span>
                    <span style="color: {color}">Confidence: {confidence:.0%}</span>
                    <br>
                    {insight.get('content', '')}
                    <br>
                    <small>Source: {insight.get('source_url', 'Unknown')} | Trust: {trust}</small>
                </div>
                """,
                    unsafe_allow_html=True,
                )

    # Search history
    search_history = result.get("search_history", [])
    if search_history:
        with st.expander("🔎 **Search Queries Used**"):
            for i, query in enumerate(search_history, 1):
                st.markdown(f"{i}. {query}")

    # Sources
    sources = result.get("sources", [])
    if sources:
        with st.expander(f"📚 **Sources Consulted** ({len(sources)})"):
            for source in sources:
                if source.startswith("http"):
                    st.markdown(f"- [{source}]({source})")
                else:
                    st.markdown(f"- {source}")

    # Metadata
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Research Depth", f"{result.get('depth_reached', 0)} / 3")
    with col2:
        st.metric("Verified Sources", len(sources))
    with col3:
        learned = result.get("learned_insights", 0)
        st.metric("📚 Auto-Learned", learned, help="Insights added to knowledge base")
    with col4:
        elapsed = result.get("elapsed_seconds", 0)
        st.metric("⏱️ Time", f"{elapsed:.1f}s")

    # Show if stopped or timed out
    if result.get("stopped"):
        st.warning("⚠️ Research was stopped by user")
    elif result.get("timed_out"):
        st.warning("⏱️ Research timed out - partial results shown")


def main():
    # Sidebar
    st.sidebar.title("🔬 Research Settings")

    # Knowledge base stats
    try:
        kb_stats = get_knowledge_stats()
        st.sidebar.markdown("### 📚 Knowledge Base")
        st.sidebar.info(
            f"""
        **Documents:** {kb_stats.get('total_documents', 0):,}

        Sources: Hydrogeology PDFs, USGS data
        """
        )
    except Exception as e:
        st.sidebar.warning(f"Knowledge base unavailable: {e}")

    # Research settings
    st.sidebar.markdown("### ⚙️ Research Settings")
    max_depth = st.sidebar.slider(
        "Research Depth",
        min_value=1,
        max_value=5,
        value=3,
        help="How many iterations of search to perform",
    )

    # Timeout settings
    timeout_minutes = st.sidebar.slider(
        "⏱️ Timeout (minutes)",
        min_value=1,
        max_value=10,
        value=3,
        help="Maximum time for research before auto-stopping",
    )
    timeout_seconds = timeout_minutes * 60

    use_web_search = st.sidebar.checkbox(
        "Enable Web Search", value=True, help="Search the web for additional information"
    )

    # Auto-learning settings
    st.sidebar.markdown("### 🧠 Auto-Learning")
    auto_learn = st.sidebar.checkbox(
        "Enable Auto-Learning",
        value=True,
        help="Automatically add high-confidence insights to knowledge base",
    )

    min_confidence = st.sidebar.slider(
        "Min Confidence for Learning",
        min_value=0.5,
        max_value=1.0,
        value=0.7,
        step=0.05,
        help="Only learn from insights with this confidence or higher",
    )

    # Initialize agent
    if st.sidebar.button("🔄 Initialize Agent"):
        with st.spinner("Initializing Deep Research Agent..."):
            initialize_agent(max_depth, use_web_search, timeout_seconds, auto_learn, min_confidence)
        st.sidebar.success("Agent ready!")

    # Auto-initialize if not done
    if st.session_state.agent is None:
        initialize_agent(max_depth, use_web_search, timeout_seconds, auto_learn, min_confidence)

    # Source priorities
    st.sidebar.markdown("### 🎯 Source Priorities")
    st.sidebar.markdown(
        """
    1. **USGS Data** (1.0) - Numerical data
    2. **Research Papers** (0.95) - DOI, journals
    3. **Government** (0.9) - .gov sources
    4. **Academic** (0.85) - Universities
    """
    )

    # Main content
    st.title("🌊 GroundwaterGPT Deep Research")
    
    # Mode selection
    st.markdown("### Choose Your Mode")
    mode = st.radio(
        "Select mode:",
        ["📚 Query Mode (Fast)", "🔬 Research Mode (Deep)"],
        horizontal=True,
        help="Query Mode searches your knowledge base instantly. Research Mode does deep web research."
    )
    
    is_query_mode = "Query" in mode
    
    if is_query_mode:
        st.info("**Query Mode**: Instantly search your knowledge base (USGS data, PDFs, learned insights)")
    else:
        st.info(f"""**Research Mode**: Deep research with web search
        - Searches knowledge base + web sources
        - Up to {max_depth} research iterations  
        - Auto-stops after {timeout_minutes} minutes""")

    # Research input
    query = st.text_area(
        "🔍 Your Question",
        placeholder="e.g., What are the groundwater levels in the Biscayne Aquifer?" if is_query_mode 
                    else "e.g., What factors affect groundwater recharge in Florida's coastal aquifers?",
        height=100,
    )

    # Different buttons based on mode
    if is_query_mode:
        col1, col2 = st.columns([1, 1])
        with col1:
            query_button = st.button("🔍 Search Knowledge Base", type="primary", use_container_width=True)
        with col2:
            num_results = st.selectbox("Results to show:", [5, 10, 20], index=1)
        
        # Execute query
        if query_button and query:
            with st.spinner("Searching knowledge base..."):
                results = query_knowledge_base(query, num_results=num_results)
                st.session_state.current_query_results = results
            
            if results['total_results'] > 0:
                st.success(f"✅ Found {results['total_results']} results!")
            else:
                st.warning("No results found. Try Research Mode for web search.")
        
        # Display query results
        if 'current_query_results' in st.session_state and st.session_state.current_query_results:
            display_query_results(st.session_state.current_query_results)
    
    else:
        # Research mode buttons
        col1, col2, col3 = st.columns([1, 1, 1])

        with col1:
            research_button = st.button("🚀 Start Research", type="primary", use_container_width=True)

        with col2:
            quick_button = st.button("⚡ Quick (1 min)", use_container_width=True)

        with col3:
            stop_button = st.button(
                "🛑 Stop Research",
                use_container_width=True,
                disabled=not st.session_state.is_researching,
            )

        # Handle stop button
        if stop_button and st.session_state.agent:
            stop_research()
            st.warning("⏹️ Stop requested - research will stop after current operation")

        # Execute research
        if research_button and query:
            st.session_state.is_researching = True
            progress_bar = st.progress(0, text="Starting research...")
            status_text = st.empty()

            def update_progress(message: str, progress: float):
                progress_bar.progress(progress, text=message)
                status_text.text(f"Status: {message}")

            try:
                status_text.text(f"🔍 Researching (timeout: {timeout_minutes} min)...")
                result = st.session_state.agent.research(
                    query,
                    max_depth=max_depth,
                    timeout=timeout_seconds,
                    progress_callback=update_progress,
                )
                st.session_state.current_research = result
                st.session_state.research_history.append(
                    {"query": query, "result": result, "timestamp": datetime.now().isoformat()}
                )

                if result.get("stopped"):
                    st.warning("⏹️ Research was stopped by user")
                elif result.get("timed_out"):
                    st.warning(f"⏱️ Research timed out after {timeout_minutes} minutes")
                else:
                    st.success("✅ Research complete!")

            except Exception as e:
                st.error(f"Research failed: {e}")
                logger.exception("Research error")
            finally:
                st.session_state.is_researching = False
                progress_bar.empty()
                status_text.empty()

        elif quick_button and query:
            with st.spinner("Quick research (1 min timeout)..."):
                try:
                    # Quick research with 60 second timeout
                    result = st.session_state.agent.research(query, max_depth=1, timeout=60)
                    st.session_state.current_research = result
                    st.success("✅ Quick answer ready!")
                except Exception as e:
                    st.error(f"Research failed: {e}")

        # Display current research
        if st.session_state.current_research:
            display_research_result(st.session_state.current_research)

    # Research history
    if st.session_state.research_history:
        st.markdown("---")
        with st.expander("📜 **Research History**"):
            for i, item in enumerate(reversed(st.session_state.research_history), 1):
                st.markdown(f"**{i}. {item['query'][:80]}...**")
                st.markdown(f"_Timestamp: {item['timestamp']}_")
                if st.button(f"View #{i}", key=f"history_{i}"):
                    st.session_state.current_research = item["result"]


if __name__ == "__main__":
    main()
