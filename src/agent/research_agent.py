"""Deep Research Agent for Groundwater Analysis.

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
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ..claim_disagreement import ClaimDisagreementEngine, summarize_claim_verdicts
from .knowledge import add_document, search_knowledge
from .llm_factory import get_llm
from .research_optimizer import (
    PriorityRanker,
    ResearchPlan,
    ResearchPlanner,
    ResearchSessionPersistence,
    SearchBudget,
    SelfReflectionEvaluator,
    StructuredReportBuilder,
)
from .source_verification import SourceVerification, verify_source

logger = logging.getLogger(__name__)
CLAIM_REF_RE = re.compile(r"\[claim_\d{3}(?:[;\],\s][^\]]*)?\]")
FACTUAL_SIGNAL_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d+(\.\d+)?\s*(ft|feet|%|year|years)|\d{15}|usgs|trend|declin\w*|"
    r"increas\w*|rising|falling|aquifer)\b",
    re.IGNORECASE,
)
BASE_DIR = Path(__file__).resolve().parents[2]
RESEARCH_SESSION_DIR = BASE_DIR / "outputs" / "research" / "sessions"


def _llm_invoke_with_retry(llm, prompt: str, retries: int = 2) -> str:
    """Invoke the LLM with retry logic for transient failures.

    Args:
        llm: LangChain chat model instance.
        prompt: The prompt string to send.
        retries: Number of retry attempts (default 2).

    Returns:
        The text content of the LLM response.

    Raises:
        The last exception if all retries fail.
    """
    last_exc: Exception | None = None
    for attempt in range(1 + retries):
        try:
            response = llm.invoke(prompt)
            return response.content
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                wait = 2**attempt
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s — " "retrying in %ds",
                    attempt + 1,
                    1 + retries,
                    exc,
                    wait,
                )
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


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
        """Convert insight to a serializable dictionary."""
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
    session_id: str = ""
    current_query: str = ""
    insights: list[ResearchInsight] = field(default_factory=list)
    visited_urls: set[str] = field(default_factory=set)
    rejected_urls: set[str] = field(default_factory=set)  # Unverified sources
    current_depth: int = 0
    max_depth: int = 3
    search_history: list[str] = field(default_factory=list)
    research_plan: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    search_budget: SearchBudget = field(default_factory=SearchBudget)
    recommended_views: list[str] = field(default_factory=list)
    chart_specs: list[dict[str, Any]] = field(default_factory=list)
    structured_response: dict[str, Any] = field(default_factory=dict)
    partial_completion_available: bool = False
    phase: str = "planning"

    # Timeout and stop controls
    start_time: float = field(default_factory=time.time)
    timeout_seconds: float = 300.0  # 5 minutes default
    stop_requested: bool = False
    status: str = "idle"
    progress_callback: Callable[..., None] | None = None

    def progress_fraction(self) -> float:
        """Estimate progress with finer-grained phase awareness."""
        phase_offsets = {
            "planning": 0.06,
            "research_loop": 0.12,
            "query_optimization": 0.18,
            "searching": 0.28,
            "extracting_insights": 0.42,
            "follow_up_generation": 0.56,
            "synthesizing": 0.82,
            "learning": 0.9,
            "timed_out": 0.94,
            "stopped": 0.94,
            "complete": 1.0,
        }
        depth_weight = 0.0
        if self.max_depth > 0:
            depth_weight = min(0.6, 0.6 * (self.current_depth / self.max_depth))
        phase_weight = phase_offsets.get(self.phase, 0.1)
        insight_bonus = min(0.08, len(self.insights) * 0.01)
        if self.phase == "complete":
            return 1.0
        return min(0.98, max(0.03, phase_weight + depth_weight + insight_bonus))

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

    def update_progress(self, message: str, snapshot: dict[str, Any] | None = None) -> None:
        """Update progress via callback if set."""
        progress = self.progress_fraction()
        self.status = message
        if self.progress_callback:
            try:
                self.progress_callback(message, progress, snapshot or {})
            except TypeError:
                self.progress_callback(message, progress)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")


class DeepResearchAgent:
    """Deep Research Agent for comprehensive groundwater research.

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
        enable_planning: bool = True,
        enable_reflection: bool = True,
        enable_budget_management: bool = True,
        enable_persistence: bool = True,
    ):
        """Initialize the Deep Research Agent.

        Args:
            max_depth: Maximum depth of research iterations
            max_results_per_search: Max search results per query
            use_web_search: Whether to use web search (requires duckduckgo-search)
            llm_provider: Override default LLM provider
            llm_model: Override default LLM model
            auto_learn: Whether to automatically add verified insights to knowledge base
            min_confidence_for_learning: Minimum confidence for auto-learning (0.0-1.0)
            timeout_seconds: Maximum time for research in seconds (default 5 min)
            enable_planning: Build a structured research plan before searching.
            enable_reflection: Evaluate coverage quality during and after research.
            enable_budget_management: Track search/tool budgets and stop if exhausted.
            enable_persistence: Persist checkpoints and session snapshots to disk.
        """
        self.max_depth = max_depth
        self.max_results_per_search = max_results_per_search
        self.use_web_search = use_web_search
        self.auto_learn = auto_learn
        self.min_confidence_for_learning = min_confidence_for_learning
        self.timeout_seconds = timeout_seconds
        self.enable_planning = enable_planning
        self.enable_reflection = enable_reflection
        self.enable_budget_management = enable_budget_management
        self.enable_persistence = enable_persistence
        self.claim_disagreement_engine = ClaimDisagreementEngine()

        # Active research context (for stop control)
        self._active_context: ResearchContext | None = None
        self._research_lock = threading.Lock()

        # Initialize LLM
        try:
            self.llm = get_llm(provider=llm_provider, model=llm_model)
        except Exception as exc:
            logger.warning(
                "DeepResearchAgent LLM unavailable; using deterministic fallbacks: %s", exc
            )
            self.llm = None

        self.planner = ResearchPlanner(llm_provider=llm_provider, llm_model=llm_model)
        self.ranker = PriorityRanker(llm_provider=llm_provider, llm_model=llm_model)
        self.reflector = SelfReflectionEvaluator(llm_provider=llm_provider, llm_model=llm_model)
        self.report_builder = StructuredReportBuilder(
            llm_provider=llm_provider, llm_model=llm_model
        )
        self.persistence = ResearchSessionPersistence(RESEARCH_SESSION_DIR)
        self.search_budget = self._create_search_budget(max_depth, timeout_seconds)

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
            except Exception as e:
                logger.warning("Web search disabled due to DDGS runtime error: %s", e)
                self._ddg_available = False

    def stop(self) -> bool:
        """Stop the currently running research.

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

    def list_sessions(self) -> list[str]:
        """List saved research sessions."""
        return self.persistence.list_sessions()

    def get_search_budget_status(self) -> dict[str, Any]:
        """Return current or default search-budget status."""
        budget = self._active_context.search_budget if self._active_context else self.search_budget
        return {
            "web_searches_used": budget.web_searches_used,
            "web_searches_max": budget.max_web_searches,
            "kb_searches_used": budget.kb_searches_used,
            "kb_searches_max": budget.max_kb_searches,
            "api_calls_used": budget.api_calls_used,
            "api_calls_max": budget.max_api_calls,
            "total_cost": budget.total_cost,
            "remaining_budget": budget.remaining_budget(),
        }

    def _create_search_budget(self, max_depth: int, timeout_seconds: float) -> SearchBudget:
        """Create a budget tuned to the current research effort."""
        depth = max(1, int(max_depth))
        return SearchBudget(
            max_web_searches=max(3, depth * 2 + 2),
            max_kb_searches=max(6, depth * 4),
            max_api_calls=max(10, depth * 6),
            max_total_cost=max(5.0, min(15.0, timeout_seconds / 20)),
            cost_per_web_search=0.05,
            cost_per_kb_search=0.0,
            cost_per_api_call=0.005,
        )

    def _build_research_plan(self, query: str, depth: int) -> dict[str, Any]:
        """Create a lightweight research plan for the current query."""
        plan: ResearchPlan = self.planner.plan_research(query, domain="groundwater")
        plan_dict = plan.to_dict()
        plan_dict["recommended_tools"] = self._recommend_tools(query)
        plan_dict["expected_outputs"] = [
            "source-backed report",
            "claim citations",
            "budget trace",
            "checkpoint history",
        ]
        plan_dict["effort_level"] = "deep" if depth >= 4 else "moderate" if depth >= 2 else "quick"
        return plan_dict

    def _recommend_tools(self, query: str) -> list[str]:
        """Heuristically recommend tool families for the session."""
        query_lower = query.lower()
        tools = ["knowledge_base_search"]
        if self.use_web_search:
            tools.append("web_search")
        if any(term in query_lower for term in ["trend", "compare", "change", "long-term"]):
            tools.append("trend_analysis")
        if any(term in query_lower for term in ["season", "wet", "dry"]):
            tools.append("seasonal_analysis")
        if any(term in query_lower for term in ["anomal", "outlier", "extreme"]):
            tools.append("anomaly_scan")
        if any(term in query_lower for term in ["aquifer", "site", "well", "county"]):
            tools.append("cohort_summary")
        return list(dict.fromkeys(tools))

    def _budget_status(self, context: ResearchContext) -> dict[str, Any]:
        """Build a serializable budget snapshot for the session."""
        budget = context.search_budget
        return {
            "max_depth": context.max_depth,
            "depth_reached": context.current_depth,
            "elapsed_seconds": round(context.elapsed_time(), 2),
            "remaining_seconds": round(context.remaining_time(), 2),
            "insights_gathered": len(context.insights),
            "web_searches_used": budget.web_searches_used,
            "web_searches_max": budget.max_web_searches,
            "kb_searches_used": budget.kb_searches_used,
            "kb_searches_max": budget.max_kb_searches,
            "api_calls_used": budget.api_calls_used,
            "api_calls_max": budget.max_api_calls,
            "total_cost": budget.total_cost,
            "remaining_budget": budget.remaining_budget(),
            "status": context.status,
            "continuing": (
                context.current_depth < context.max_depth
                and not context.stop_requested
                and not context.is_timed_out()
            ),
            "timed_out": context.is_timed_out(),
            "partial_completion_available": context.partial_completion_available,
        }

    def _progress_snapshot(self, context: ResearchContext) -> dict[str, Any]:
        """Build a snapshot for live progress streaming."""
        return {
            "session_id": context.session_id,
            "phase": context.phase,
            "research_plan": context.research_plan,
            "budget_status": self._budget_status(context),
            "checkpoints": context.checkpoints[-5:],
            "tool_trace": context.tool_trace[-10:],
        }

    def _persist_session_state(self, context: ResearchContext) -> None:
        """Persist session state for resumability and debugging."""
        if not self.enable_persistence:
            return
        self.persistence.save_session(
            context.session_id,
            {
                "session_id": context.session_id,
                "query": context.original_query,
                "current_query": context.current_query,
                "phase": context.phase,
                "status": context.status,
                "max_depth": context.max_depth,
                "depth_reached": context.current_depth,
                "research_plan": context.research_plan,
                "search_history": context.search_history,
                "checkpoints": context.checkpoints,
                "tool_trace": context.tool_trace,
                "budget_status": self._budget_status(context),
                "visited_urls": sorted(list(context.visited_urls)),
                "insights": [insight.to_dict() for insight in context.insights],
            },
        )

    def _save_checkpoint(
        self,
        context: ResearchContext,
        stage: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append and persist a session checkpoint."""
        checkpoint = {
            "checkpoint_id": f"cp_{len(context.checkpoints) + 1:03d}",
            "timestamp": datetime.now().isoformat(),
            "stage": stage,
            "summary": summary,
            "depth": context.current_depth,
            "phase": context.phase,
            "status": context.status,
            "insights_gathered": len(context.insights),
            "budget_status": self._budget_status(context),
            "details": details or {},
        }
        context.checkpoints.append(checkpoint)
        self._persist_session_state(context)

    def _record_tool_event(
        self,
        context: ResearchContext,
        tool_name: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Track observable tool usage for the frontend demo surface."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "phase": context.phase,
            "depth": context.current_depth,
            "tool": tool_name,
            "status": status,
            "details": details or {},
        }
        context.tool_trace.append(event)
        context.tool_trace = context.tool_trace[-50:]

    def research(
        self,
        query: str,
        max_depth: int | None = None,
        timeout: float | None = None,
        progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, Any]:
        """Conduct deep research on a query.

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
        session_id = f"research_{uuid4().hex[:12]}"
        research_plan = self._build_research_plan(query, depth)
        search_budget = self._create_search_budget(depth, timeout_secs)
        self.search_budget = search_budget

        context = ResearchContext(
            original_query=query,
            session_id=session_id,
            current_query=query,
            max_depth=depth,
            timeout_seconds=timeout_secs,
            progress_callback=progress_callback,
            research_plan=research_plan,
            search_budget=search_budget,
            recommended_views=["report", "citations", "tool_trace", "budget"],
        )

        # Register active context for stop control
        with self._research_lock:
            self._active_context = context

        try:
            logger.info(f"Starting deep research: {query} (timeout: {timeout_secs}s)")
            context.phase = "planning"
            context.status = "starting"
            self._save_checkpoint(
                context,
                stage="planning",
                summary="Created research session and initial plan.",
                details={"research_plan": research_plan},
            )
            context.update_progress("Starting research...", self._progress_snapshot(context))

            # Execute research graph
            try:
                self._research_graph(context)
            except Exception as e:
                logger.error("Research graph execution failed: %s", e)
                context.partial_completion_available = bool(context.insights)
                self._save_checkpoint(
                    context,
                    stage="runtime_error",
                    summary="Research graph failed; returning partial output.",
                    details={"error": str(e)},
                )
                context.update_progress(
                    "Research graph failed; returning partial output.",
                    self._progress_snapshot(context),
                )

            # Check if we were stopped
            claim_citations, citation_summary = self._build_claim_citations(context.insights)
            claim_verdicts = self.claim_disagreement_engine.evaluate_claims(claim_citations)
            # Pass verdicts so contradicted sections get confidence penalties.
            section_confidence = self._build_section_confidence(context.insights, claim_verdicts)
            claim_verdict_summary = summarize_claim_verdicts(claim_verdicts)

            if context.stop_requested:
                context.phase = "stopped"
                context.partial_completion_available = bool(context.insights)
                context.update_progress(
                    "Research stopped by user", self._progress_snapshot(context)
                )
                report = (
                    self._synthesize_report(context, claim_citations, claim_verdicts)
                    if context.insights
                    else "Research was stopped before completion."
                )
            elif context.is_timed_out():
                context.phase = "timed_out"
                context.partial_completion_available = bool(context.insights)
                context.update_progress("Research timed out", self._progress_snapshot(context))
                report = (
                    self._synthesize_report(context, claim_citations, claim_verdicts)
                    if context.insights
                    else "Research timed out before completion."
                )
            else:
                context.phase = "synthesizing"
                context.update_progress("Synthesizing report...", self._progress_snapshot(context))
                report = self._synthesize_report(context, claim_citations, claim_verdicts)

            # Auto-learn: Add high-confidence insights to knowledge base
            learned_count = 0
            if self.auto_learn and context.insights:
                context.phase = "learning"
                context.update_progress("Saving learnings...", self._progress_snapshot(context))
                learned_count = self._save_learnings(context)

            report, removed_factual_sentences = self._strip_uncited_factual_sentences(report)

            if context.insights and self.enable_reflection:
                provisional_synthesis = "\n".join(insight.content for insight in context.insights)
                plan_data = context.research_plan
                reflection = self.reflector.evaluate_synthesis(
                    provisional_synthesis,
                    ResearchPlan(
                        original_query=plan_data.get("original_query", context.original_query),
                        main_question=plan_data.get("main_question", context.original_query),
                        sub_questions=plan_data.get("sub_questions", []),
                        research_areas=plan_data.get("research_areas", []),
                        expected_sections=plan_data.get("expected_sections", []),
                        search_priority=plan_data.get("search_priority", [context.original_query]),
                        estimated_depth=plan_data.get("estimated_depth", context.max_depth),
                    ),
                    [insight.to_dict() for insight in context.insights],
                )
                self._record_tool_event(
                    context,
                    "self_reflection",
                    "completed",
                    {
                        "confidence_score": reflection.confidence_score,
                        "coverage_score": reflection.coverage_score,
                        "is_high_quality": reflection.is_high_quality,
                    },
                )
            context.phase = "complete"
            context.update_progress("Complete", self._progress_snapshot(context))
            context.status = "complete"
            self._save_checkpoint(
                context,
                stage="complete",
                summary="Research session completed.",
                details={"removed_uncited_factual_sentences": removed_factual_sentences},
            )

            return {
                "session_id": context.session_id,
                "query": query,
                "research_plan": context.research_plan,
                "insights": [i.to_dict() for i in context.insights],
                "search_history": context.search_history,
                "depth_reached": context.current_depth,
                "report": report,
                "sources": list(context.visited_urls),
                "learned_insights": learned_count,
                "elapsed_seconds": context.elapsed_time(),
                "stopped": context.stop_requested,
                "timed_out": context.is_timed_out(),
                "budget_status": self._budget_status(context),
                "checkpoints": context.checkpoints,
                "tool_trace": context.tool_trace,
                "recommended_views": context.recommended_views,
                "chart_specs": context.chart_specs,
                "structured_response": context.structured_response,
                "claim_citations": claim_citations,
                "claim_verdicts": claim_verdicts,
                "claim_verdict_summary": claim_verdict_summary,
                "citation_summary": citation_summary,
                "section_confidence": section_confidence,
                "hallucination_guardrail": {
                    "strategy": "claim_reference_filter",
                    "removed_uncited_factual_sentences": removed_factual_sentences,
                    "all_factual_claims_cited": removed_factual_sentences == 0,
                },
            }
        finally:
            # Clear active context
            with self._research_lock:
                self._active_context = None

    def _save_learnings(self, context: ResearchContext) -> int:
        """Save high-confidence verified insights to the knowledge base.

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
        """Execute the research graph - iterative search and analysis.

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
            context.phase = "research_loop"

            context.update_progress(
                f"Depth {context.current_depth}/{context.max_depth} "
                f"({elapsed:.0f}s elapsed, {remaining:.0f}s remaining)",
                self._progress_snapshot(context),
            )
            logger.info(
                f"Research depth: {context.current_depth}/{context.max_depth} "
                f"[{elapsed:.1f}s elapsed, {remaining:.1f}s remaining]"
            )
            self._save_checkpoint(
                context,
                stage="depth_start",
                summary=f"Starting depth {context.current_depth}.",
            )

            # Check timeout before expensive operations
            if context.is_stopped():
                break
            if self.enable_budget_management and context.search_budget.remaining_budget() <= 0:
                context.status = "budget_exhausted"
                self._save_checkpoint(
                    context,
                    stage="budget_exhausted",
                    summary="Stopped research because the search budget was exhausted.",
                )
                break

            # Step 1: Optimize query based on current context
            if context.current_depth > 1:
                context.phase = "query_optimization"
                context.update_progress(
                    f"Optimizing query (depth {context.current_depth})...",
                    self._progress_snapshot(context),
                )
                context.current_query = self._generate_optimized_query(context)
                if context.is_stopped():
                    break

            context.search_history.append(context.current_query)

            # Step 2: Search multiple sources
            context.phase = "searching"
            context.update_progress(
                f"Searching: {context.current_query[:50]}...",
                self._progress_snapshot(context),
            )
            results = self._search(context.current_query, context)
            if context.is_stopped():
                break

            if not results:
                logger.info("No new results found, ending research")
                break

            # Step 3: Extract insights from results
            context.phase = "extracting_insights"
            context.update_progress(
                f"Extracting insights from {len(results)} results...",
                self._progress_snapshot(context),
            )
            new_insights = self._extract_insights(results, context)
            if context.is_stopped():
                break

            for insight in new_insights:
                context.add_insight(insight)

            context.partial_completion_available = bool(context.insights)
            self._save_checkpoint(
                context,
                stage="insight_update",
                summary=f"Collected {len(new_insights)} new insights.",
                details={
                    "new_insights": len(new_insights),
                    "total_insights": len(context.insights),
                },
            )
            context.update_progress(
                f"Found {len(context.insights)} total insights",
                self._progress_snapshot(context),
            )

            # Step 4: Check if we have enough information
            if self._is_research_complete(context):
                logger.info("Research complete - sufficient insights gathered")
                self._save_checkpoint(
                    context,
                    stage="research_complete",
                    summary="Research loop finished because coverage was sufficient.",
                )
                break

            # Step 5: Generate follow-up queries for next iteration
            if context.should_continue():
                context.phase = "follow_up_generation"
                context.update_progress(
                    "Generating follow-up queries...",
                    self._progress_snapshot(context),
                )
                follow_ups = self._generate_follow_ups(context)
                if context.is_stopped():
                    break
                if follow_ups:
                    context.current_query = follow_ups[0]
                    self._save_checkpoint(
                        context,
                        stage="follow_up_selected",
                        summary="Selected follow-up query for next depth.",
                        details={"next_query": context.current_query, "candidates": follow_ups},
                    )
                else:
                    break

    def _generate_optimized_query(self, context: ResearchContext) -> str:
        """Generate an optimized search query based on current research state."""
        self._record_tool_event(
            context,
            "query_optimizer",
            "started",
            {"previous_queries": len(context.search_history)},
        )
        if self.llm is None:
            query = next(
                (
                    candidate
                    for candidate in context.research_plan.get("search_priority", [])
                    if candidate not in context.search_history
                ),
                context.original_query,
            )
            self._record_tool_event(
                context,
                "query_optimizer",
                "completed",
                {"mode": "heuristic", "query": query},
            )
            return query

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
            query = _llm_invoke_with_retry(self.llm, prompt).strip().strip("\"'")
            self._record_tool_event(
                context,
                "query_optimizer",
                "completed",
                {"mode": "llm", "query": query},
            )
            return query
        except Exception as e:
            logger.error(f"Query optimization failed: {e}")
            self._record_tool_event(
                context,
                "query_optimizer",
                "failed",
                {"error": str(e)},
            )
            return context.original_query

    def _search(self, query: str, context: ResearchContext) -> list[SearchResult]:
        """Search multiple sources for information."""
        results = []

        # Search local knowledge base first
        try:
            context.search_budget.record_kb_search()
            kb_docs = search_knowledge(query, k=3, score_threshold=0.0)
            self._record_tool_event(
                context,
                "knowledge_base_search",
                "completed",
                {"query": query, "result_count": len(kb_docs)},
            )
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
            self._record_tool_event(
                context,
                "knowledge_base_search",
                "failed",
                {"query": query, "error": str(e)},
            )

        # Web search if available
        if (
            self._ddg_available
            and self.use_web_search
            and (not self.enable_budget_management or context.search_budget.can_do_web_search())
        ):
            try:
                web_results = self._search_web(query, context)
                if web_results:
                    results.extend(web_results)
            except Exception as e:
                logger.error(f"Web search failed: {e}")
                self._record_tool_event(
                    context,
                    "web_search",
                    "failed",
                    {"query": query, "error": str(e)},
                )

        if results and self.ranker is not None:
            ranked = self.ranker.rank_results(
                [
                    {
                        "title": result.title,
                        "url": result.url,
                        "snippet": result.snippet,
                        "source": result.source,
                    }
                    for result in results
                ],
                query,
                context.original_query,
            )
            score_by_url = {item.url: item for item in ranked}
            results.sort(
                key=lambda item: (
                    score_by_url.get(item.url).combined_score if item.url in score_by_url else 0.0
                ),
                reverse=True,
            )
            self._record_tool_event(
                context,
                "priority_ranker",
                "completed",
                {"query": query, "result_count": len(results)},
            )

        return results

    def _search_web(self, query: str, context: ResearchContext) -> list[SearchResult]:
        """Search the web using DuckDuckGo."""
        if not self._ddg_available:
            return []

        results = []
        try:
            # Add groundwater context to query
            enhanced_query = f"groundwater hydrogeology {query}"
            context.search_budget.record_web_search()

            search_results = self._ddg.text(enhanced_query, max_results=self.max_results_per_search)
            if not search_results:
                self._record_tool_event(
                    context,
                    "web_search",
                    "completed",
                    {"query": enhanced_query, "result_count": 0},
                )
                return []

            for result in search_results:
                if not isinstance(result, dict):
                    continue
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
            self._record_tool_event(
                context,
                "web_search",
                "completed",
                {"query": enhanced_query, "result_count": len(results)},
            )
        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}")
            self._record_tool_event(
                context,
                "web_search",
                "failed",
                {"query": query, "error": str(e)},
            )
            return []

        return results

    def _extract_insights(
        self, results: list[SearchResult], context: ResearchContext
    ) -> list[ResearchInsight]:
        """Extract key insights from VERIFIED search results using LLM.

        Only processes results that passed source verification.
        """
        # Filter to only verified results
        verified_results = [r for r in results if r.is_verified or r.source == "knowledge_base"]

        if not verified_results:
            logger.warning("No verified sources to extract insights from")
            self._record_tool_event(
                context,
                "insight_extractor",
                "completed",
                {"verified_results": 0, "insights": 0},
            )
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
            if self.llm is None:
                insights = self._heuristic_insights(verified_results)
            else:
                content = _llm_invoke_with_retry(self.llm, prompt)
                insights = self._parse_insights(content, results)
            self._record_tool_event(
                context,
                "insight_extractor",
                "completed",
                {"verified_results": len(verified_results), "insights": len(insights)},
            )
            return insights
        except Exception as e:
            logger.error(f"Insight extraction failed: {e}")
            self._record_tool_event(
                context,
                "insight_extractor",
                "failed",
                {"error": str(e)},
            )
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

    def _heuristic_insights(self, results: list[SearchResult]) -> list[ResearchInsight]:
        """Fallback insight extraction when no synthesis LLM is available."""
        insights: list[ResearchInsight] = []
        for result in results[:3]:
            snippet = (result.snippet or "").strip()
            sentence = re.split(r"(?<=[.!?])\s+", snippet)[0].strip() if snippet else ""
            content = sentence or result.title or "Relevant groundwater source identified."
            trust_level = (
                result.verification.trust_level.value
                if result.verification is not None
                else "verified"
            )
            insights.append(
                ResearchInsight(
                    content=content[:280],
                    source_url=result.url,
                    confidence=0.72 if result.source == "knowledge_base" else 0.66,
                    verified=result.source == "knowledge_base" or result.is_verified,
                    trust_level=trust_level,
                )
            )
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
        """Generate follow-up queries based on current research state."""
        self._record_tool_event(
            context,
            "follow_up_generator",
            "started",
            {"search_history_count": len(context.search_history)},
        )
        if self.llm is None:
            follow_ups = [
                candidate
                for candidate in context.research_plan.get("search_priority", [])[1:]
                if candidate not in context.search_history
            ]
            self._record_tool_event(
                context,
                "follow_up_generator",
                "completed",
                {"mode": "heuristic", "follow_ups": follow_ups[:2]},
            )
            return follow_ups[:2]

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
            content = _llm_invoke_with_retry(self.llm, prompt)

            if "COMPLETE" in content.upper():
                return []

            follow_ups = []
            for line in content.strip().split("\n"):
                line = line.strip()
                if line and line[0].isdigit():
                    query = line.lstrip("0123456789.)-] ").strip()
                    if query and query not in context.search_history:
                        follow_ups.append(query)

            follow_ups = follow_ups[:2]
            self._record_tool_event(
                context,
                "follow_up_generator",
                "completed",
                {"mode": "llm", "follow_ups": follow_ups},
            )
            return follow_ups
        except Exception as e:
            logger.error(f"Follow-up generation failed: {e}")
            self._record_tool_event(
                context,
                "follow_up_generator",
                "failed",
                {"error": str(e)},
            )
            return []

    def _is_research_complete(self, context: ResearchContext) -> bool:
        """Determine if we have gathered enough insights."""
        # Need at least some insights
        if len(context.insights) < 2:
            return False

        if self.enable_reflection and context.current_depth >= 2:
            plan_data = context.research_plan
            research_plan = ResearchPlan(
                original_query=plan_data.get("original_query", context.original_query),
                main_question=plan_data.get("main_question", context.original_query),
                sub_questions=plan_data.get("sub_questions", []),
                research_areas=plan_data.get("research_areas", []),
                expected_sections=plan_data.get("expected_sections", []),
                search_priority=plan_data.get("search_priority", [context.original_query]),
                estimated_depth=plan_data.get("estimated_depth", context.max_depth),
            )
            reflection = self.reflector.evaluate_synthesis(
                "\n".join(insight.content for insight in context.insights),
                research_plan,
                [insight.to_dict() for insight in context.insights],
            )
            self._record_tool_event(
                context,
                "self_reflection",
                "completed",
                {
                    "confidence_score": reflection.confidence_score,
                    "coverage_score": reflection.coverage_score,
                    "is_high_quality": reflection.is_high_quality,
                },
            )
            if reflection.is_high_quality and reflection.coverage_score >= 0.65:
                return True

        # Check if high-confidence insights exist
        high_confidence = [i for i in context.insights if i.confidence >= 0.7]
        if len(high_confidence) >= 3:
            return True

        # Continue if we haven't hit max depth
        return False

    def _build_claim_citations(
        self,
        insights: list[ResearchInsight],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Build claim-level citation records from extracted insights."""
        claims: list[dict[str, Any]] = []
        cited_claims = 0

        for index, insight in enumerate(insights, start=1):
            source_url = (insight.source_url or "").strip()
            has_source = bool(source_url and source_url != "unknown")
            if has_source:
                cited_claims += 1

            citation_entry = (
                [
                    {
                        "evidence_id": f"evidence_{index:03d}_source_1",
                        "url": source_url,
                        "verified": bool(insight.verified),
                        "trust_level": insight.trust_level,
                    }
                ]
                if has_source
                else []
            )

            claims.append(
                {
                    "claim_id": f"claim_{index:03d}",
                    "claim_type": "retrieved_insight",
                    "claim": insight.content,
                    "confidence": insight.confidence,
                    "evidence_ids": [f"evidence_{index:03d}_source_1"] if has_source else [],
                    "citations": citation_entry,
                }
            )

        total_claims = len(claims)
        coverage = float(cited_claims / total_claims) if total_claims else 0.0
        summary = {
            "total_claims": total_claims,
            "cited_claims": cited_claims,
            "citation_coverage": coverage,
        }
        return claims, summary

    def _build_section_confidence(
        self,
        insights: list[ResearchInsight],
        claim_verdicts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build section-level confidence and trust metadata from insights.

        If claim_verdicts is provided, contradicted claims have their confidence
        halved so the overall section trust score reflects detected conflicts.
        """
        trust_rank = {
            "unknown": 0,
            "untrusted": 0,
            "moderate": 1,
            "trusted": 2,
            "verified": 3,
        }
        rank_to_trust = {
            0: "unknown",
            1: "moderate",
            2: "trusted",
            3: "verified",
        }

        # Build a claim_id → verdict lookup for O(1) access below.
        verdict_by_claim: dict[str, str] = {}
        for v in claim_verdicts or []:
            cid = str(v.get("claim_id", ""))
            if cid:
                verdict_by_claim[cid] = str(v.get("verdict", "")).lower()

        sections: list[dict[str, Any]] = []
        confidence_values: list[float] = []
        trust_values: list[int] = []

        for index, insight in enumerate(insights, start=1):
            confidence = max(0.0, min(1.0, float(insight.confidence)))
            trust_level = str(insight.trust_level or "unknown").lower()
            trust = trust_rank.get(trust_level, 0)
            citation_count = 1 if (insight.source_url and insight.source_url != "unknown") else 0

            # Contradicted claims get their confidence penalised by 50% so the
            # overall section score reflects the detected conflict.
            claim_id = f"claim_{index:03d}"
            verdict = verdict_by_claim.get(claim_id, "")
            if verdict == "contradicted":
                confidence = round(confidence * 0.5, 3)

            confidence_values.append(confidence)
            trust_values.append(trust)
            sections.append(
                {
                    "section_id": f"section_{index:03d}",
                    "title": insight.content[:120] or f"Insight section {index}",
                    "confidence": round(confidence, 3),
                    "trust_level": rank_to_trust.get(trust, "unknown"),
                    "citation_count": citation_count,
                    # Expose the verdict so the frontend can style the section.
                    "verdict": verdict or "insufficient_evidence",
                }
            )

        if not sections:
            return {
                "sections": [],
                "overall_confidence": 0.0,
                "overall_trust_level": "unknown",
            }

        avg_confidence = round(sum(confidence_values) / len(confidence_values), 3)
        avg_trust_rank = round(sum(trust_values) / len(trust_values))
        return {
            "sections": sections,
            "overall_confidence": avg_confidence,
            "overall_trust_level": rank_to_trust.get(avg_trust_rank, "unknown"),
        }

    def _is_factual_sentence(self, sentence: str) -> bool:
        """Return True when a sentence looks like a factual claim."""
        return bool(FACTUAL_SIGNAL_RE.search(sentence))

    def _strip_uncited_factual_sentences(self, report: str) -> tuple[str, int]:
        """Remove factual sentences lacking claim references.

        Guardrail rule:
        - factual sentence must include `[claim_###]`
        - non-factual narrative text is kept as-is
        """
        if not report.strip():
            return report, 0

        cleaned_lines: list[str] = []
        removed = 0

        for line in report.splitlines():
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue

            sentences = re.split(r"(?<=[.!?])\s+", stripped)
            kept_sentences: list[str] = []
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                if self._is_factual_sentence(sentence) and not CLAIM_REF_RE.search(sentence):
                    removed += 1
                    continue
                kept_sentences.append(sentence)

            if kept_sentences:
                cleaned_lines.append(" ".join(kept_sentences))

        cleaned = "\n".join(cleaned_lines).strip()
        if cleaned:
            return cleaned, removed
        return "No citation-safe factual claims were available in this response.", removed

    def _build_evidence_items(self, claim_citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build a compact evidence registry for structured LLM synthesis."""
        evidence_items: list[dict[str, Any]] = []
        for claim in claim_citations:
            claim_id = str(claim.get("claim_id", "claim_unknown"))
            for idx, citation in enumerate(claim.get("citations", []), start=1):
                evidence_id = str(
                    citation.get("evidence_id") or f"evidence_{claim_id[-3:]}_source_{idx}"
                )
                evidence_items.append(
                    {
                        "evidence_id": evidence_id,
                        "claim_id": claim_id,
                        "url": citation.get("url") or citation.get("source") or "unknown",
                        "trust_level": citation.get("trust_level", "unknown"),
                        "verified": bool(citation.get("verified", False)),
                    }
                )
        return evidence_items

    def _heuristic_structured_response(
        self,
        question: str,
        claim_citations: list[dict[str, Any]],
        claim_verdicts: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a structured response without an LLM or when JSON parsing fails."""
        verdict_by_claim = {
            str(verdict.get("claim_id", "")): str(verdict.get("verdict", "insufficient_evidence"))
            for verdict in claim_verdicts
        }
        evidence_by_claim: dict[str, list[str]] = {}
        for item in evidence_items:
            evidence_by_claim.setdefault(str(item["claim_id"]), []).append(str(item["evidence_id"]))

        claims = []
        for claim in claim_citations[:6]:
            claim_id = str(claim.get("claim_id", "claim_unknown"))
            evidence_ids = evidence_by_claim.get(claim_id, [])
            claims.append(
                {
                    "claim": str(claim.get("claim", "")),
                    "claim_type": str(claim.get("claim_type", "retrieved_insight")),
                    "claim_ids": [claim_id],
                    "evidence_ids": evidence_ids,
                    "confidence": float(claim.get("confidence", 0.5)),
                    "is_interpretive": False,
                    "uncertainty": (
                        "Evidence is limited for this claim."
                        if not evidence_ids
                        or verdict_by_claim.get(claim_id) == "insufficient_evidence"
                        else ""
                    ),
                }
            )

        answer_claims = [claim["claim"] for claim in claims[:2] if claim.get("claim")]
        return {
            "schema_version": "evidence_response_v1",
            "question": question,
            "answer": " ".join(answer_claims)
            or "The available verified evidence was insufficient for a detailed answer.",
            "claims": claims,
            "limitations": [
                (
                    "This response is constrained to verified retrieved "
                    "evidence and local data artifacts."
                ),
            ],
            "recommended_followup": [
                (
                    "Compare the answer against deterministic site metrics "
                    "when the question references monitored wells."
                ),
            ],
            "evidence": evidence_items,
        }

    def _parse_structured_response(
        self,
        raw_response: str,
        question: str,
        claim_citations: list[dict[str, Any]],
        claim_verdicts: list[dict[str, Any]],
        evidence_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Parse and validate the LLM's evidence-ID JSON response."""

        def _clean_text(value: Any, *, max_len: int = 400) -> str:
            return str(value or "").strip()[:max_len].strip()

        def _safe_confidence(value: Any, *, default: float = 0.5) -> float:
            try:
                confidence = float(value)
            except (TypeError, ValueError):
                confidence = default
            return max(0.0, min(1.0, confidence))

        def _dedupe_ids(
            values: Any,
            *,
            valid_ids: set[str],
            max_items: int = 8,
        ) -> list[str]:
            if not isinstance(values, list):
                return []

            deduped: list[str] = []
            seen: set[str] = set()
            for value in values:
                text = str(value).strip()
                if not text or text in seen or text not in valid_ids:
                    continue
                deduped.append(text)
                seen.add(text)
                if len(deduped) >= max_items:
                    break
            return deduped

        text = raw_response.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if fenced:
            text = fenced.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]

        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("structured response is not a JSON object")

        valid_claim_ids = {str(claim.get("claim_id")) for claim in claim_citations}
        valid_evidence_ids = {str(item.get("evidence_id")) for item in evidence_items}
        sanitized_claims: list[dict[str, Any]] = []
        for item in parsed.get("claims", []):
            if not isinstance(item, dict):
                continue
            claim_text = _clean_text(item.get("claim", ""), max_len=500)
            claim_ids = _dedupe_ids(item.get("claim_ids", []), valid_ids=valid_claim_ids)
            evidence_ids = _dedupe_ids(item.get("evidence_ids", []), valid_ids=valid_evidence_ids)
            if not claim_ids or not evidence_ids:
                continue
            if not claim_text:
                continue
            sanitized_claims.append(
                {
                    "claim": claim_text,
                    "claim_type": _clean_text(item.get("claim_type", "interpretation"), max_len=64)
                    or "interpretation",
                    "claim_ids": claim_ids,
                    "evidence_ids": evidence_ids,
                    "confidence": _safe_confidence(item.get("confidence", 0.5)),
                    "is_interpretive": bool(item.get("is_interpretive", False)),
                    "uncertainty": _clean_text(item.get("uncertainty", "")),
                }
            )

        if not sanitized_claims:
            return self._heuristic_structured_response(
                question,
                claim_citations,
                claim_verdicts,
                evidence_items,
            )

        return {
            "schema_version": "evidence_response_v1",
            "question": question,
            "answer": _clean_text(parsed.get("answer", ""), max_len=700),
            "claims": sanitized_claims,
            "limitations": [
                _clean_text(item) for item in parsed.get("limitations", []) if _clean_text(item)
            ],
            "recommended_followup": [
                _clean_text(item)
                for item in parsed.get("recommended_followup", [])
                if _clean_text(item)
            ],
            "evidence": evidence_items,
        }

    def _render_structured_report(self, structured: dict[str, Any]) -> str:
        """Render evidence-structured synthesis as citation-safe markdown."""
        claims = structured.get("claims", [])
        answer = str(structured.get("answer", "")).strip()
        if answer and claims and not CLAIM_REF_RE.search(answer):
            first_claim_ids = claims[0].get("claim_ids", [])
            if first_claim_ids:
                answer = f"{answer} [{first_claim_ids[0]}]"
        lines = [answer]
        if claims:
            lines.append("\n## Evidence-Linked Claims")
            for item in claims:
                claim_ids = ", ".join(item.get("claim_ids", []))
                evidence_ids = ", ".join(item.get("evidence_ids", []))
                uncertainty = str(item.get("uncertainty", "")).strip()
                suffix = f" Uncertainty: {uncertainty}" if uncertainty else ""
                lines.append(
                    f"- {item.get('claim', '')} [{claim_ids}; evidence: {evidence_ids}]{suffix}"
                )

        limitations = structured.get("limitations", [])
        if limitations:
            lines.append("\n## Limitations")
            lines.extend(f"- {item}" for item in limitations)

        followup = structured.get("recommended_followup", [])
        if followup:
            lines.append("\n## Recommended Follow-Up")
            lines.extend(f"- {item}" for item in followup)

        return "\n".join(line for line in lines if str(line).strip())

    def _synthesize_report(
        self,
        context: ResearchContext,
        claim_citations: list[dict[str, Any]],
        claim_verdicts: list[dict[str, Any]] | None = None,
    ) -> str:
        """Synthesize all insights into a comprehensive research report.

        When claim_verdicts is supplied the LLM is told which claims are
        contradicted so it can flag them inline with [⚠ contradicted by …].
        A deterministic "Conflicting Evidence" section is appended in Python
        (no extra LLM call) when the contradicted rate exceeds 15%.
        """
        if not context.insights:
            return "No insights were gathered during research. Try a different query."

        evidence_items = self._build_evidence_items(claim_citations)

        if self.llm is None:
            context.structured_response = self._heuristic_structured_response(
                context.original_query,
                claim_citations,
                claim_verdicts or [],
                evidence_items,
            )
            return self._render_structured_report(context.structured_response)

        # Build a verdict lookup: claim_id → verdict string
        verdict_map: dict[str, str] = {}
        for v in claim_verdicts or []:
            cid = str(v.get("claim_id", ""))
            if cid:
                verdict_map[cid] = str(v.get("verdict", "")).lower()

        # Separate contradicted from supported/insufficient claims so we can
        # present them differently in the prompt and in the appended section.
        contradicted_claims = [
            c
            for c in claim_citations
            if verdict_map.get(str(c.get("claim_id", ""))) == "contradicted"
        ]
        contradicted_rate = (
            len(contradicted_claims) / len(claim_citations) if claim_citations else 0.0
        )

        insights_text = "\n".join(
            [
                f"- {i.content} (confidence: {i.confidence:.1f})"
                for i in sorted(context.insights, key=lambda x: x.confidence, reverse=True)
            ]
        )

        evidence_json = json.dumps(evidence_items, indent=2)

        # Build the claim list with verdict labels so the LLM can cite them
        # correctly and flag contradictions inline.
        claim_lines = []
        for claim in claim_citations:
            claim_id = str(claim.get("claim_id", "claim_unknown"))
            claim_text = str(claim.get("claim", "")).strip()
            confidence = float(claim.get("confidence", 0.0))
            verdict = verdict_map.get(claim_id, "insufficient_evidence")
            evidence_ids = ", ".join(claim.get("evidence_ids", [])) or "no_evidence_id"

            # Append a warning marker on contradicted claims so the LLM knows
            # to flag them with [⚠ contradicted] when it cites them.
            flag = " ⚠ CONTRADICTED — flag this inline" if verdict == "contradicted" else ""
            claim_lines.append(
                f"- [{claim_id}] {claim_text} "
                f"(confidence={confidence:.2f}; evidence={evidence_ids}){flag}"
            )

        contradiction_instruction = ""
        if contradicted_claims:
            contradiction_instruction = (
                "\n- For any claim marked ⚠ CONTRADICTED, append "
                "[⚠ contradicted by <claim_id>] immediately after citing it."
            )

        prompt = f"""You are a groundwater science expert synthesizing research findings.

Original Question: {context.original_query}

Research Insights:
{insights_text}

Evidence-backed claims (use these claim IDs as citations):
{chr(10).join(claim_lines)}

Evidence ID registry:
{evidence_json}

Sources Consulted: {len(context.visited_urls)} web sources + local knowledge base

Return ONLY valid JSON with this schema:
{{
  "answer": "direct answer in 2-4 sentences",
  "claims": [
    {{
      "claim": "one factual or interpretive statement",
      "claim_type": "trend|metadata|literature|interpretation|limitation",
      "claim_ids": ["claim_001"],
      "evidence_ids": ["evidence_001_source_1"],
      "confidence": 0.0,
      "is_interpretive": false,
      "uncertainty": "short caveat"
    }}
  ],
  "limitations": ["data or method limitation"],
  "recommended_followup": ["specific follow-up analysis"]
}}

Hard constraints:
- Every factual claim object MUST include at least one claim_id and one
  evidence_id from the registry.
- Use no quantitative values unless they appear in the evidence-backed claims.
- Put caveats in "limitations" rather than inventing extra factual claims.
{contradiction_instruction}"""

        try:
            raw_response = _llm_invoke_with_retry(self.llm, prompt)
            structured = self._parse_structured_response(
                raw_response,
                context.original_query,
                claim_citations,
                claim_verdicts or [],
                evidence_items,
            )
            context.structured_response = structured
            report = self._render_structured_report(structured)
        except Exception as e:
            logger.error(f"Report synthesis failed: {e}")
            context.structured_response = self._heuristic_structured_response(
                context.original_query,
                claim_citations,
                claim_verdicts or [],
                evidence_items,
            )
            return self._render_structured_report(context.structured_response)

        # Append a deterministic "Conflicting Evidence" section when the
        # contradicted rate exceeds 15% — no extra LLM call needed.
        if contradicted_rate > 0.15 and contradicted_claims:
            conflict_lines = [
                "\n\n---\n## ⚠ Conflicting Evidence\n",
                f"**{len(contradicted_claims)} of {len(claim_citations)} claims "
                f"({contradicted_rate:.0%}) were flagged as contradicted by other sources.**\n",
            ]
            for claim in contradicted_claims:
                cid = claim.get("claim_id", "")
                text = str(claim.get("claim", "")).strip()
                confidence = float(claim.get("confidence", 0.0))
                conflict_lines.append(f"- **[{cid}]** {text} *(confidence: {confidence:.2f})*")
            conflict_lines.append(
                "\nInterpret findings in this section with caution. "
                "Cross-check with primary USGS data sources before drawing conclusions."
            )
            report += "\n".join(conflict_lines)
            logger.info(
                "Appended Conflicting Evidence section: %d/%d claims contradicted (%.0f%%)",
                len(contradicted_claims),
                len(claim_citations),
                contradicted_rate * 100,
            )

        return report

    def quick_research(self, query: str) -> str:
        """Quick research mode - single depth, returns just the report."""
        result = self.research(query, max_depth=1)
        return result.get("report", "Research failed.")


# Convenience function
def deep_research(query: str, max_depth: int = 3) -> dict[str, Any]:
    """Conduct deep research on a groundwater topic.

    Args:
        query: Research question
        max_depth: Maximum depth of research iterations

    Returns:
        Research results including report and sources
    """
    agent = DeepResearchAgent(max_depth=max_depth)
    return agent.research(query)
