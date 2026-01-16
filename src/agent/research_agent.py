"""
Deep Research Agent for Groundwater Analysis.

Inspired by SkyworkAI/DeepResearchAgent architecture.
Implements iterative web search, query optimization, and insight synthesis.
Includes source verification to ensure data quality and accuracy.

Features:
- Timeout controls to prevent getting stuck
- Stop functionality for user control
- Progress callbacks for real-time updates
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .knowledge import add_document, get_vectorstore, search_knowledge
from .llm_factory import get_llm
from .source_verification import SourceVerification, TrustLevel, is_source_approved, verify_source

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    source: str = "web"
    verification: SourceVerification | None = None

    @property
    def is_verified(self) -> bool:
        """Check if source is verified."""
        if self.verification is None:
            return False
        return self.verification.is_approved


@dataclass
class ResearchInsight:
    """An insight extracted from research."""

    content: str
    source_url: str
    confidence: float
    verified: bool = False
    trust_level: str = "unknown"
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "source_url": self.source_url,
            "confidence": self.confidence,
            "verified": self.verified,
            "trust_level": self.trust_level,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ResearchContext:
    """Tracks the state of a research session."""

    original_query: str
    current_query: str = ""
    insights: list[ResearchInsight] = field(default_factory=list)
    visited_urls: set[str] = field(default_factory=set)
    rejected_urls: set[str] = field(default_factory=set)  # Unverified sources
    current_depth: int = 0
    max_depth: int = 3
    search_history: list[str] = field(default_factory=list)

    # Timeout and stop controls
    start_time: float = field(default_factory=time.time)
    timeout_seconds: float = 300.0  # 5 minutes default
    stop_requested: bool = False
    status: str = "idle"
    progress_callback: Callable[[str, float], None] | None = None

    def add_insight(self, insight: ResearchInsight) -> None:
        """Add an insight, avoiding duplicates. Only add verified insights."""
        if not insight.verified:
            logger.warning(f"Rejecting unverified insight from: {insight.source_url}")
            return
        existing_contents = {i.content for i in self.insights}
        if insight.content not in existing_contents:
            self.insights.append(insight)

    def get_insights_summary(self) -> str:
        """Get a summary of all insights collected."""
        if not self.insights:
            return "No insights collected yet."

        summaries = []
        for i, insight in enumerate(self.insights, 1):
            summaries.append(f"{i}. {insight.content[:200]}...")
        return "\n".join(summaries)

    def should_continue(self) -> bool:
        """Check if research should continue."""
        return self.current_depth < self.max_depth and not self.is_stopped()

    def is_stopped(self) -> bool:
        """Check if research has been stopped or timed out."""
        if self.stop_requested:
            self.status = "stopped"
            return True
        if self.is_timed_out():
            self.status = "timeout"
            return True
        return False

    def is_timed_out(self) -> bool:
        """Check if research has exceeded timeout."""
        elapsed = time.time() - self.start_time
        return elapsed > self.timeout_seconds

    def elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time

    def remaining_time(self) -> float:
        """Get remaining time before timeout."""
        return max(0, self.timeout_seconds - self.elapsed_time())

    def request_stop(self) -> None:
        """Request the research to stop."""
        self.stop_requested = True
        self.status = "stop_requested"
        logger.info("Stop requested by user")

    def update_progress(self, message: str) -> None:
        """Update progress via callback if set."""
        progress = min(1.0, self.current_depth / self.max_depth)
        self.status = message
        if self.progress_callback:
            try:
                self.progress_callback(message, progress)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")


class DeepResearchAgent:
    """
    Deep Research Agent for comprehensive groundwater research.

    Uses iterative search, query optimization, and insight synthesis
    to produce well-researched answers to complex questions.

    Features:
    - Configurable timeout to prevent getting stuck
    - Stop functionality for user control
    - Progress callbacks for real-time updates
    """

    def __init__(
        self,
        max_depth: int = 3,
        max_results_per_search: int = 5,
        use_web_search: bool = True,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        auto_learn: bool = True,
        min_confidence_for_learning: float = 0.7,
        timeout_seconds: float = 300.0,  # 5 minutes default
    ):
        """
        Initialize the Deep Research Agent.

        Args:
            max_depth: Maximum depth of research iterations
            max_results_per_search: Max search results per query
            use_web_search: Whether to use web search (requires duckduckgo-search)
            llm_provider: Override default LLM provider
            llm_model: Override default LLM model
            auto_learn: Whether to automatically add verified insights to knowledge base
            min_confidence_for_learning: Minimum confidence for auto-learning (0.0-1.0)
            timeout_seconds: Maximum time for research in seconds (default 5 min)
        """
        self.max_depth = max_depth
        self.max_results_per_search = max_results_per_search
        self.use_web_search = use_web_search
        self.auto_learn = auto_learn
        self.min_confidence_for_learning = min_confidence_for_learning
        self.timeout_seconds = timeout_seconds

        # Active research context (for stop control)
        self._active_context: ResearchContext | None = None
        self._research_lock = threading.Lock()

        # Initialize LLM
        self.llm = get_llm(provider=llm_provider, model=llm_model)

        # Web search availability
        self._ddg_available = False
        if use_web_search:
            try:
                from ddgs import DDGS

                self._ddg_available = True
                self._ddg = DDGS()
            except ImportError:
                try:
                    # Fallback to old package name
                    from duckduckgo_search import DDGS

                    self._ddg_available = True
                    self._ddg = DDGS()
                except ImportError:
                    logger.warning("ddgs not installed. " "Install with: pip install ddgs")

    def stop(self) -> bool:
        """
        Stop the currently running research.

        Returns:
            True if a research was stopped, False if none was running
        """
        with self._research_lock:
            if self._active_context:
                self._active_context.request_stop()
                logger.info("Research stop requested")
                return True
            return False

    def is_running(self) -> bool:
        """Check if research is currently running."""
        with self._research_lock:
            return self._active_context is not None and not self._active_context.is_stopped()

    def get_status(self) -> dict[str, Any]:
        """Get current research status."""
        with self._research_lock:
            if self._active_context:
                return {
                    "running": True,
                    "status": self._active_context.status,
                    "depth": self._active_context.current_depth,
                    "max_depth": self._active_context.max_depth,
                    "insights": len(self._active_context.insights),
                    "elapsed": self._active_context.elapsed_time(),
                    "remaining": self._active_context.remaining_time(),
                }
            return {"running": False, "status": "idle"}

    def research(
        self,
        query: str,
        max_depth: int | None = None,
        timeout: float | None = None,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> dict[str, Any]:
        """
        Conduct deep research on a query.

        Args:
            query: The research question
            max_depth: Override default max depth
            timeout: Override default timeout in seconds
            progress_callback: Optional callback for progress updates (message, progress 0-1)

        Returns:
            Dict containing research results and synthesis
        """
        depth = max_depth or self.max_depth
        timeout_secs = timeout or self.timeout_seconds

        context = ResearchContext(
            original_query=query,
            current_query=query,
            max_depth=depth,
            timeout_seconds=timeout_secs,
            progress_callback=progress_callback,
        )

        # Register active context for stop control
        with self._research_lock:
            self._active_context = context

        try:
            logger.info(f"Starting deep research: {query} (timeout: {timeout_secs}s)")
            context.update_progress("Starting research...")

            # Execute research graph
            self._research_graph(context)

            # Check if we were stopped
            if context.stop_requested:
                context.update_progress("Research stopped by user")
                report = (
                    self._synthesize_report(context)
                    if context.insights
                    else "Research was stopped before completion."
                )
            elif context.is_timed_out():
                context.update_progress("Research timed out")
                report = (
                    self._synthesize_report(context)
                    if context.insights
                    else "Research timed out before completion."
                )
            else:
                context.update_progress("Synthesizing report...")
                report = self._synthesize_report(context)

            # Auto-learn: Add high-confidence insights to knowledge base
            learned_count = 0
            if self.auto_learn and context.insights:
                context.update_progress("Saving learnings...")
                learned_count = self._save_learnings(context)

            context.update_progress("Complete")
            context.status = "complete"

            return {
                "query": query,
                "insights": [i.to_dict() for i in context.insights],
                "search_history": context.search_history,
                "depth_reached": context.current_depth,
                "report": report,
                "sources": list(context.visited_urls),
                "learned_insights": learned_count,
                "elapsed_seconds": context.elapsed_time(),
                "stopped": context.stop_requested,
                "timed_out": context.is_timed_out(),
            }
        finally:
            # Clear active context
            with self._research_lock:
                self._active_context = None

    def _save_learnings(self, context: ResearchContext) -> int:
        """
        Save high-confidence verified insights to the knowledge base.
        This enables continuous learning from research.

        Args:
            context: Research context with insights

        Returns:
            Number of insights added to knowledge base
        """
        learned = 0

        for insight in context.insights:
            # Only save high-confidence verified insights
            if insight.verified and insight.confidence >= self.min_confidence_for_learning:

                # Format content for knowledge base
                content = f"""Research Insight: {insight.content}

Original Query: {context.original_query}
Source: {insight.source_url}
Confidence: {insight.confidence:.0%}
Trust Level: {insight.trust_level}
Date: {insight.timestamp.isoformat()}
"""

                metadata = {
                    "doc_type": "research_insight",
                    "source_url": insight.source_url,
                    "confidence": insight.confidence,
                    "trust_level": insight.trust_level,
                    "query": context.original_query,
                    "auto_learned": True,
                }

                try:
                    # Add to knowledge base (verification already done)
                    success = add_document(
                        content=content,
                        metadata=metadata,
                        source_url=insight.source_url,
                        require_verification=False,  # Already verified during research
                    )
                    if success:
                        learned += 1
                        logger.info(f"📚 Learned: {insight.content[:50]}...")
                except Exception as e:
                    logger.error(f"Failed to save learning: {e}")

        if learned > 0:
            logger.info(f"✅ Added {learned} insights to knowledge base (auto-learning)")

        return learned

    async def research_async(self, query: str, max_depth: int | None = None) -> dict[str, Any]:
        """Async version of research."""
        return await asyncio.to_thread(self.research, query, max_depth)

    def _research_graph(self, context: ResearchContext) -> None:
        """
        Execute the research graph - iterative search and analysis.

        This implements the core research loop:
        1. Optimize query
        2. Search (knowledge base + web)
        3. Extract insights
        4. Generate follow-up queries
        5. Repeat until max depth, sufficient insights, timeout, or stop
        """
        while context.should_continue():
            # Check for stop/timeout at start of each iteration
            if context.is_stopped():
                logger.info(f"Research stopped: {context.status}")
                break

            context.current_depth += 1
            elapsed = context.elapsed_time()
            remaining = context.remaining_time()

            context.update_progress(
                f"Depth {context.current_depth}/{context.max_depth} "
                f"({elapsed:.0f}s elapsed, {remaining:.0f}s remaining)"
            )
            logger.info(
                f"Research depth: {context.current_depth}/{context.max_depth} "
                f"[{elapsed:.1f}s elapsed, {remaining:.1f}s remaining]"
            )

            # Check timeout before expensive operations
            if context.is_stopped():
                break

            # Step 1: Optimize query based on current context
            if context.current_depth > 1:
                context.update_progress(f"Optimizing query (depth {context.current_depth})...")
                context.current_query = self._generate_optimized_query(context)
                if context.is_stopped():
                    break

            context.search_history.append(context.current_query)

            # Step 2: Search multiple sources
            context.update_progress(f"Searching: {context.current_query[:50]}...")
            results = self._search(context.current_query, context)
            if context.is_stopped():
                break

            if not results:
                logger.info("No new results found, ending research")
                break

            # Step 3: Extract insights from results
            context.update_progress(f"Extracting insights from {len(results)} results...")
            new_insights = self._extract_insights(results, context)
            if context.is_stopped():
                break

            for insight in new_insights:
                context.add_insight(insight)

            context.update_progress(f"Found {len(context.insights)} total insights")

            # Step 4: Check if we have enough information
            if self._is_research_complete(context):
                logger.info("Research complete - sufficient insights gathered")
                break

            # Step 5: Generate follow-up queries for next iteration
            if context.should_continue():
                context.update_progress("Generating follow-up queries...")
                follow_ups = self._generate_follow_ups(context)
                if context.is_stopped():
                    break
                if follow_ups:
                    context.current_query = follow_ups[0]
                else:
                    break

    def _generate_optimized_query(self, context: ResearchContext) -> str:
        """
        Generate an optimized search query based on current research state.
        """
        prompt = f"""You are a research query optimizer for groundwater science.

Original research question: {context.original_query}

Previous searches:
{chr(10).join(f'- {q}' for q in context.search_history)}

Insights collected so far:
{context.get_insights_summary()}

Generate ONE new search query that will help fill in gaps in our knowledge.
The query should:
1. Be specific and focused on groundwater/hydrogeology
2. Not repeat previous searches
3. Target information we're still missing

Return ONLY the search query, nothing else."""

        try:
            response = self.llm.invoke(prompt)
            return response.content.strip().strip("\"'")
        except Exception as e:
            logger.error(f"Query optimization failed: {e}")
            return context.original_query

    def _search(self, query: str, context: ResearchContext) -> list[SearchResult]:
        """
        Search multiple sources for information.
        """
        results = []

        # Search local knowledge base first
        try:
            kb_docs = search_knowledge(query, k=3, score_threshold=0.0)
            for doc in kb_docs:
                results.append(
                    SearchResult(
                        title=doc.metadata.get("source_file", "Knowledge Base"),
                        url="local://knowledge_base",
                        snippet=doc.page_content[:500],
                        source="knowledge_base",
                    )
                )
        except Exception as e:
            logger.error(f"Knowledge base search failed: {e}")

        # Web search if available
        if self._ddg_available and self.use_web_search:
            try:
                web_results = self._search_web(query, context)
                results.extend(web_results)
            except Exception as e:
                logger.error(f"Web search failed: {e}")

        return results

    def _search_web(self, query: str, context: ResearchContext) -> list[SearchResult]:
        """
        Search the web using DuckDuckGo.
        """
        if not self._ddg_available:
            return []

        results = []
        try:
            # Add groundwater context to query
            enhanced_query = f"groundwater hydrogeology {query}"

            search_results = self._ddg.text(enhanced_query, max_results=self.max_results_per_search)

            for result in search_results:
                url = result.get("href", "")
                if url not in context.visited_urls:
                    # Verify source before adding
                    verification = verify_source(url)

                    if verification.is_approved:
                        context.visited_urls.add(url)
                        results.append(
                            SearchResult(
                                title=result.get("title", ""),
                                url=url,
                                snippet=result.get("body", ""),
                                source="duckduckgo",
                                verification=verification,
                            )
                        )
                        logger.info(f"✓ Verified source: {url} ({verification.trust_level.value})")
                    else:
                        context.rejected_urls.add(url)
                        logger.warning(
                            f"✗ Rejected unverified source: {url} - {verification.reason}"
                        )
        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}")

        return results

    def _extract_insights(
        self, results: list[SearchResult], context: ResearchContext
    ) -> list[ResearchInsight]:
        """
        Extract key insights from VERIFIED search results using LLM.
        Only processes results that passed source verification.
        """
        # Filter to only verified results
        verified_results = [r for r in results if r.is_verified or r.source == "knowledge_base"]

        if not verified_results:
            logger.warning("No verified sources to extract insights from")
            return []

        # Prepare content for analysis
        content_parts = []
        for r in verified_results:
            trust_info = ""
            if r.verification:
                trust_info = f" [Trust: {r.verification.trust_level.value}]"
            content_parts.append(
                f"Source: {r.title}{trust_info}\nURL: {r.url}\nContent: {r.snippet}\n"
            )

        combined_content = "\n---\n".join(content_parts)

        prompt = f"""You are a groundwater science researcher analyzing VERIFIED search results.
All sources below have been verified as trusted scientific/government sources.

Original research question: {context.original_query}
Current search query: {context.current_query}

Verified Search Results:
{combined_content}

Extract the most important and relevant insights for answering the research question.
For each insight:
1. State the key finding clearly and concisely
2. Rate confidence from 0.0 to 1.0

Format as:
INSIGHT: [insight text]
CONFIDENCE: [0.0-1.0]
SOURCE: [source url or title]

Extract up to 3 insights. Only include genuinely useful information."""

        try:
            response = self.llm.invoke(prompt)
            return self._parse_insights(response.content, results)
        except Exception as e:
            logger.error(f"Insight extraction failed: {e}")
            return []

    def _parse_insights(
        self, llm_response: str, results: list[SearchResult]
    ) -> list[ResearchInsight]:
        """Parse LLM response into ResearchInsight objects."""
        insights = []

        lines = llm_response.strip().split("\n")
        current_insight = {}

        for line in lines:
            line = line.strip()
            if line.startswith("INSIGHT:"):
                if current_insight.get("content"):
                    insights.append(self._create_insight(current_insight, results))
                current_insight = {"content": line[8:].strip()}
            elif line.startswith("CONFIDENCE:"):
                try:
                    current_insight["confidence"] = float(line[11:].strip())
                except ValueError:
                    current_insight["confidence"] = 0.5
            elif line.startswith("SOURCE:"):
                current_insight["source"] = line[7:].strip()

        # Add last insight
        if current_insight.get("content"):
            insights.append(self._create_insight(current_insight, results))

        return insights

    def _create_insight(self, data: dict, results: list[SearchResult]) -> ResearchInsight:
        """Create a ResearchInsight from parsed data with verification status."""
        source_url = data.get("source", "")
        verification = None

        # Try to match source to actual URL and get verification
        if not source_url.startswith("http"):
            for r in results:
                if r.title and data.get("source", "") in r.title:
                    source_url = r.url
                    verification = r.verification
                    break
            else:
                if results:
                    source_url = results[0].url
                    verification = results[0].verification
                else:
                    source_url = "unknown"
        else:
            # Find verification for this URL
            for r in results:
                if r.url == source_url:
                    verification = r.verification
                    break

        # Determine verification status
        is_verified = False
        trust_level = "unknown"

        if source_url == "local://knowledge_base":
            is_verified = True
            trust_level = "verified"
        elif verification:
            is_verified = verification.is_approved
            trust_level = verification.trust_level.value

        return ResearchInsight(
            content=data.get("content", ""),
            source_url=source_url,
            confidence=data.get("confidence", 0.5),
            verified=is_verified,
            trust_level=trust_level,
        )

    def _generate_follow_ups(self, context: ResearchContext) -> list[str]:
        """
        Generate follow-up queries based on current research state.
        """
        prompt = f"""You are a research assistant identifying knowledge gaps.

Original question: {context.original_query}

Insights gathered so far:
{context.get_insights_summary()}

Previous searches:
{chr(10).join(f'- {q}' for q in context.search_history)}

What information is still missing to fully answer the original question?
Generate 1-2 follow-up search queries that would help fill these gaps.
Focus on groundwater/hydrogeology topics.

Format:
1. [first follow-up query]
2. [second follow-up query]

If the research seems complete, respond with: COMPLETE"""

        try:
            response = self.llm.invoke(prompt)

            if "COMPLETE" in response.content.upper():
                return []

            follow_ups = []
            for line in response.content.strip().split("\n"):
                line = line.strip()
                if line and line[0].isdigit():
                    query = line.lstrip("0123456789.)-] ").strip()
                    if query and query not in context.search_history:
                        follow_ups.append(query)

            return follow_ups[:2]
        except Exception as e:
            logger.error(f"Follow-up generation failed: {e}")
            return []

    def _is_research_complete(self, context: ResearchContext) -> bool:
        """
        Determine if we have gathered enough insights.
        """
        # Need at least some insights
        if len(context.insights) < 2:
            return False

        # Check if high-confidence insights exist
        high_confidence = [i for i in context.insights if i.confidence >= 0.7]
        if len(high_confidence) >= 3:
            return True

        # Continue if we haven't hit max depth
        return False

    def _synthesize_report(self, context: ResearchContext) -> str:
        """
        Synthesize all insights into a comprehensive research report.
        """
        if not context.insights:
            return "No insights were gathered during research. Try a different query."

        insights_text = "\n".join(
            [
                f"- {i.content} (confidence: {i.confidence:.1f})"
                for i in sorted(context.insights, key=lambda x: x.confidence, reverse=True)
            ]
        )

        prompt = f"""You are a groundwater science expert synthesizing research findings.

Original Question: {context.original_query}

Research Insights:
{insights_text}

Sources Consulted: {len(context.visited_urls)} web sources + local knowledge base

Write a comprehensive answer to the original question based on these insights.
Structure your response with:
1. Direct answer to the question
2. Key supporting details
3. Any caveats or limitations
4. Suggestions for further research if applicable

Be informative, accurate, and cite the level of confidence where relevant."""

        try:
            response = self.llm.invoke(prompt)
            return response.content
        except Exception as e:
            logger.error(f"Report synthesis failed: {e}")
            return f"Research gathered {len(context.insights)} insights but synthesis failed: {e}"

    def quick_research(self, query: str) -> str:
        """
        Quick research mode - single depth, returns just the report.
        """
        result = self.research(query, max_depth=1)
        return result.get("report", "Research failed.")


# Convenience function
def deep_research(query: str, max_depth: int = 3) -> dict[str, Any]:
    """
    Conduct deep research on a groundwater topic.

    Args:
        query: Research question
        max_depth: Maximum depth of research iterations

    Returns:
        Research results including report and sources
    """
    agent = DeepResearchAgent(max_depth=max_depth)
    return agent.research(query)
