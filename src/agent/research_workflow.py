"""Agentic Deep Research Workflow for Groundwater Research.

Orchestrates multi-phase research combining:
- Research planning (decompose complex queries)
- Priority ranking (SmartSearch pattern)
- Budget-aware searching (ReSeek pattern)
- Self-reflection (WebSeer pattern)
- Domain validation (groundwater-specific)

Implements patterns from Awesome-Deep-Research:
https://github.com/DavidZWZ/Awesome-Deep-Research
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .llm_factory import get_llm
from .research_agent import DeepResearchAgent
from .research_optimizer import (
    ResearchPlanner,
    PriorityRanker,
    SelfReflectionEvaluator,
    StructuredReportBuilder,
    ResearchSessionPersistence,
    SearchBudget,
    ResearchPlan,
)
from .source_verification import verify_source

logger = logging.getLogger(__name__)


@dataclass
class GroundwaterResearchContext:
    """Context for a groundwater research operation."""

    query: str
    session_id: str
    created_at: datetime = field(default_factory=datetime.now)
    domain: str = "groundwater"
    
    # Planning phase
    research_plan: Optional[ResearchPlan] = None
    plan_created_at: Optional[datetime] = None
    
    # Search phase
    search_budget: SearchBudget = field(default_factory=SearchBudget)
    search_results: dict = field(default_factory=dict)  # query -> [results]
    visited_urls: set = field(default_factory=set)
    insights: list = field(default_factory=list)
    
    # Reflection & iteration
    reflection_results: list = field(default_factory=list)
    iteration_count: int = 0
    max_iterations: int = 3
    
    # Report
    final_report: Optional[dict] = None
    report_generated_at: Optional[datetime] = None
    
    # Metadata
    total_elapsed_time: float = 0.0
    progress_messages: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Serialize to dict for persistence."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        if self.plan_created_at:
            data["plan_created_at"] = self.plan_created_at.isoformat()
        if self.report_generated_at:
            data["report_generated_at"] = self.report_generated_at.isoformat()
        data["visited_urls"] = list(self.visited_urls)
        data["search_budget"] = self.search_budget.to_dict()
        if self.research_plan:
            data["research_plan"] = self.research_plan.to_dict()
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> GroundwaterResearchContext:
        """Deserialize from dict."""
        # Handle datetime fields
        for field_name in ["created_at", "plan_created_at", "report_generated_at"]:
            if field_name in data and isinstance(data[field_name], str):
                data[field_name] = datetime.fromisoformat(data[field_name])
        
        # Handle complex fields
        if "search_budget" in data:
            data["search_budget"] = SearchBudget.from_dict(data["search_budget"])
        if "research_plan" in data and data["research_plan"]:
            data["research_plan"] = ResearchPlan.from_dict(data["research_plan"])
        if "visited_urls" in data:
            data["visited_urls"] = set(data["visited_urls"])
        
        return cls(**data)


class GroundwaterResearchWorkflow:
    """
    Orchestrates agentic deep research for groundwater questions.
    
    Combines research optimization, domain knowledge, and data integration
    to produce high-quality research reports about groundwater topics.
    """
    
    def __init__(
        self,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        max_iterations: int = 3,
        session_dir: Path | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ):
        """Initialize the groundwater research workflow.
        
        Args:
            llm_provider: LLM provider (openai, anthropic, etc.)
            llm_model: LLM model name
            max_iterations: Max research iterations for reflection loop
            session_dir: Directory for session persistence
            progress_callback: Optional callback for progress updates
        """
        self.llm = get_llm(provider=llm_provider, model=llm_model)
        self.max_iterations = max_iterations
        self.progress_callback = progress_callback or self._default_progress
        
        # Initialize components
        self.planner = ResearchPlanner(llm_provider=llm_provider, llm_model=llm_model)
        self.ranker = PriorityRanker(llm_provider=llm_provider, llm_model=llm_model)
        self.evaluator = SelfReflectionEvaluator(
            llm_provider=llm_provider, llm_model=llm_model
        )
        self.report_builder = StructuredReportBuilder(
            llm_provider=llm_provider, llm_model=llm_model
        )
        self.persistence = ResearchSessionPersistence(session_dir=session_dir)
        
        # Deep research agent (with web search)
        self.research_agent = DeepResearchAgent(
            use_web_search=True,
            llm_provider=llm_provider,
            llm_model=llm_model,
            auto_learn=True,
        )
    
    def _default_progress(self, message: str) -> None:
        """Default progress callback - just log."""
        logger.info(f"📊 {message}")
    
    def _update_progress(self, context: GroundwaterResearchContext, message: str) -> None:
        """Update progress and call callback."""
        context.progress_messages.append(message)
        self.progress_callback(message)
    
    def research(self, query: str, session_id: str | None = None) -> dict:
        """
        Conduct comprehensive groundwater research.
        
        Args:
            query: The groundwater research question
            session_id: Optional ID for session resumption
        
        Returns:
            Dict with research results, report, and metadata
        """
        # Initialize context
        if session_id and (context := self.persistence.load_session(session_id)):
            logger.info(f"📂 Resuming session: {session_id}")
            context = GroundwaterResearchContext.from_dict(context)
        else:
            session_id = self._generate_session_id()
            context = GroundwaterResearchContext(query=query, session_id=session_id)
        
        start_time = datetime.now()
        
        try:
            # Phase 1: Research Planning
            self._update_progress(context, "📋 Decomposing research question...")
            context.research_plan = self.planner.plan_research(query, domain="groundwater")
            context.plan_created_at = datetime.now()
            
            logger.info(f"📋 Main Question: {context.research_plan.main_question}")
            logger.info(f"📋 Sub-Questions: {context.research_plan.sub_questions}")
            logger.info(f"📋 Search Priority: {context.research_plan.search_priority}")
            
            # Phase 2: Iterative Search & Reflection
            while context.iteration_count < context.max_iterations:
                iteration_num = context.iteration_count + 1
                logger.info(f"\n🔄 ITERATION {iteration_num}/{context.max_iterations}")
                
                # 2a: Execute prioritized searches
                self._update_progress(
                    context, 
                    f"🔍 Searching (iteration {iteration_num})..."
                )
                self._execute_searches(context)
                
                # 2b: Extract and verify insights
                self._update_progress(context, "🔬 Extracting insights...")
                self._extract_insights(context)
                
                # 2c: Build report
                self._update_progress(context, "📄 Building report...")
                report = self.report_builder.build_report(
                    query=query,
                    insights=context.insights,
                    research_plan=context.research_plan,
                    visited_urls=context.visited_urls,
                )
                
                # 2d: Self-reflect
                self._update_progress(context, "🤔 Evaluating research quality...")
                reflection = self.evaluator.evaluate_synthesis(
                    synthesis=json.dumps(report, indent=2),
                    research_plan=context.research_plan,
                    insights=context.insights,
                )
                context.reflection_results.append(reflection)
                
                logger.info(f"🤔 Quality Score: {reflection.confidence_score:.2f}/1.0")
                logger.info(f"🤔 Coverage Score: {reflection.coverage_score:.2f}/1.0")
                
                # Check if we should stop or continue
                if reflection.is_high_quality or context.iteration_count >= context.max_iterations:
                    context.final_report = report
                    context.report_generated_at = datetime.now()
                    logger.info("✅ Research quality threshold met")
                    break
                
                # Plan follow-up searches based on gaps
                if reflection.follow_up_queries:
                    logger.info(f"⚠️  Gaps identified. Follow-up queries:")
                    for q in reflection.follow_up_queries[:3]:
                        logger.info(f"  - {q}")
                    # Add follow-up queries to search priority
                    context.research_plan.search_priority.extend(
                        reflection.follow_up_queries[:3]
                    )
                
                context.iteration_count += 1
            
            # Phase 3: Finalize Results
            if not context.final_report:
                context.final_report = self.report_builder.build_report(
                    query=query,
                    insights=context.insights,
                    research_plan=context.research_plan,
                    visited_urls=context.visited_urls,
                )
                context.report_generated_at = datetime.now()
            
            # Save session
            self._update_progress(context, "💾 Saving session...")
            self.persistence.save_session(session_id, context.to_dict())
            
            # Calculate elapsed time
            context.total_elapsed_time = (datetime.now() - start_time).total_seconds()
            
            # Build result
            result = {
                "session_id": session_id,
                "query": query,
                "research_plan": context.research_plan.to_dict() if context.research_plan else None,
                "report": context.final_report,
                "insights_count": len(context.insights),
                "sources_count": len(context.visited_urls),
                "iterations": context.iteration_count,
                "total_time_seconds": context.total_elapsed_time,
                "budget_used": {
                    "web_searches": context.search_budget.web_searches_used,
                    "kb_searches": context.search_budget.kb_searches_used,
                    "total_cost": context.search_budget.total_cost,
                },
                "quality_metrics": {
                    "final_confidence": context.reflection_results[-1].confidence_score 
                        if context.reflection_results else 0.0,
                    "final_coverage": context.reflection_results[-1].coverage_score 
                        if context.reflection_results else 0.0,
                },
                "progress": context.progress_messages,
            }
            
            self._update_progress(context, f"✅ Research complete ({context.total_elapsed_time:.1f}s)")
            return result
            
        except Exception as e:
            logger.error(f"❌ Research failed: {e}", exc_info=True)
            raise
    
    def _execute_searches(self, context: GroundwaterResearchContext) -> None:
        """Execute prioritized searches across KB and web."""
        # Get remaining budget
        budget = context.search_budget
        
        # Use only queries from research plan that haven't been searched yet
        queries_to_search = [
            q for q in context.research_plan.search_priority 
            if q not in context.search_results
        ]
        
        for query in queries_to_search:
            if not budget.can_do_web_search():
                logger.warning("⚠️  Web search budget exhausted")
                break
            
            logger.info(f"🔍 Searching: {query}")
            
            # Use the deep research agent to search
            search_results = self.research_agent._web_search(query)[:5]  # Top 5
            
            if search_results:
                # Rank results by priority
                ranked = self.ranker.rank_results(search_results, query)
                context.search_results[query] = [asdict(r) for r in ranked]
                
                # Track visited URLs
                for result in ranked:
                    context.visited_urls.add(result.url)
                
                budget.record_web_search()
            
            # Also search knowledge base (free)
            kb_results = self._kb_search(query)
            if kb_results:
                context.search_results[f"{query}__kb"] = kb_results
                budget.record_kb_search()
    
    def _kb_search(self, query: str) -> list[dict]:
        """Search internal knowledge base."""
        try:
            from .knowledge import search_knowledge
            
            docs = search_knowledge(query, k=5, score_threshold=0.3)
            results = []
            for doc in docs:
                results.append({
                    "title": doc.metadata.get("source_file", "KB Doc"),
                    "url": f"knowledge_base://{doc.metadata.get('source_file', 'unknown')}",
                    "snippet": doc.page_content[:300],
                    "source": "knowledge_base",
                })
            return results
        except Exception as e:
            logger.warning(f"KB search failed: {e}")
            return []
    
    def _extract_insights(self, context: GroundwaterResearchContext) -> None:
        """Extract and verify insights from search results."""
        for query, results in context.search_results.items():
            if query.endswith("__kb"):
                continue  # Skip KB-specific keys
            
            for result in results:
                if isinstance(result, dict):
                    # Verify source if it's a web URL
                    confidence = 0.7  # Default
                    if result.get("source") == "web":
                        try:
                            verified = verify_source(result.get("url", ""))
                            confidence = verified.trust_score if verified else 0.5
                        except Exception:
                            confidence = 0.5
                    elif result.get("source") == "knowledge_base":
                        confidence = 0.95
                    
                    insight = {
                        "query": query,
                        "title": result.get("title", ""),
                        "content": result.get("snippet", ""),
                        "source_url": result.get("url", ""),
                        "source_type": result.get("source", "web"),
                        "confidence": confidence,
                        "extracted_at": datetime.now().isoformat(),
                    }
                    
                    context.insights.append(insight)
    
    def _generate_session_id(self) -> str:
        """Generate unique session ID."""
        import uuid
        return f"gwa_{datetime.now():%Y%m%d_%H%M%S}_{str(uuid.uuid4())[:8]}"
    
    def list_sessions(self) -> list[str]:
        """List available research sessions."""
        return self.persistence.list_sessions()
    
    def get_session(self, session_id: str) -> dict | None:
        """Load a saved session."""
        data = self.persistence.load_session(session_id)
        if data:
            context = GroundwaterResearchContext.from_dict(data)
            return context.to_dict()
        return None


async def research_async(
    query: str,
    max_iterations: int = 3,
    progress_callback: Callable[[str], None] | None = None,
) -> dict:
    """
    Async wrapper for groundwater research.
    
    Args:
        query: Research question
        max_iterations: Max research iterations
        progress_callback: Progress callback
    
    Returns:
        Research results dict
    """
    workflow = GroundwaterResearchWorkflow(max_iterations=max_iterations)
    
    # Run in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: workflow.research(query),
    )
    
    return result


def conduct_groundwater_research(
    query: str,
    max_iterations: int = 3,
    session_id: str | None = None,
) -> dict:
    """
    Convenience function for groundwater research.
    
    Args:
        query: Groundwater research question
        max_iterations: Maximum research iterations
        session_id: Optional session ID for resumption
    
    Returns:
        Complete research results including report
    """
    workflow = GroundwaterResearchWorkflow(max_iterations=max_iterations)
    return workflow.research(query, session_id=session_id)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Example research query
    example_query = (
        "How has water level in the Biscayne Aquifer changed over the past 5 years? "
        "What are the main drivers (climate, human use, seasonal patterns)?"
    )
    
    print("\n" + "=" * 80)
    print(f"📚 Starting groundwater research: {example_query}")
    print("=" * 80 + "\n")
    
    workflow = GroundwaterResearchWorkflow(max_iterations=2)
    results = workflow.research(example_query)
    
    print("\n" + "=" * 80)
    print("📄 RESEARCH RESULTS")
    print("=" * 80)
    print(f"Session ID: {results['session_id']}")
    print(f"Iterations: {results['iterations']}")
    print(f"Time: {results['total_time_seconds']:.1f}s")
    print(f"Sources: {results['sources_count']}")
    print(f"Quality (Confidence): {results['quality_metrics']['final_confidence']:.2f}")
    print(f"Quality (Coverage): {results['quality_metrics']['final_coverage']:.2f}")
    
    if results.get("report"):
        print(f"\n📋 Report Title: {results['report'].get('title', 'N/A')}")
        print(f"📋 Summary: {results['report'].get('executive_summary', 'N/A')[:200]}...")
