"""
Advanced Research Optimization for Agentic Deep Research.

Implements patterns from Awesome-Deep-Research:
- Research planning (multi-step decomposition)
- Priority ranking (SmartSearch)
- Self-reflection (WebSeer pattern)
- Search budget management (efficiency)
- Session persistence (resume capability)

Reference:
- https://github.com/DavidZWZ/Awesome-Deep-Research
- SmartSearch (iterative query optimization)
- ReSeek (budget-aware search)
- WebSeer (self-reflection quality control)
- O-Researcher (multi-agent decomposition)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .llm_factory import get_llm

logger = logging.getLogger(__name__)


@dataclass
class ResearchPlan:
    """Structured research plan decomposed from complex query."""

    original_query: str
    main_question: str
    sub_questions: list[str] = field(default_factory=list)
    research_areas: list[str] = field(default_factory=list)  # e.g., "hydrology", "climate"
    expected_sections: list[str] = field(default_factory=list)  # Report structure
    search_priority: list[str] = field(default_factory=list)  # Ordered search queries
    estimated_depth: int = 3
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Serialize to dict for persistence."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> ResearchPlan:
        """Deserialize from dict."""
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


@dataclass
class RankedSearchResult:
    """Search result with calculated relevance score."""

    title: str
    url: str
    snippet: str
    source: str  # "knowledge_base" | "web"
    relevance_score: float = 0.5  # 0.0-1.0
    trust_score: float = 0.5  # Based on source verification
    recency_score: float = 0.5  # Based on publish date
    combined_score: float = 0.5  # Weighted combination
    reasoning: str = ""

    def __lt__(self, other: RankedSearchResult) -> bool:
        """Support sorting (highest score first)."""
        return self.combined_score > other.combined_score


@dataclass
class ReflectionResult:
    """Output from self-reflection evaluation."""

    is_high_quality: bool
    confidence_score: float  # 0.0-1.0
    coverage_score: float  # How well all questions are answered
    missing_areas: list[str] = field(default_factory=list)
    follow_up_queries: list[str] = field(default_factory=list)
    reasoning: str = ""
    sections_requiring_more_research: list[str] = field(default_factory=list)


@dataclass
class SearchBudget:
    """Tracks search API usage and costs."""

    max_web_searches: int = 10
    max_kb_searches: int = 20
    max_api_calls: int = 50
    cost_per_web_search: float = 0.01
    cost_per_kb_search: float = 0.0  # Knowledge base is local
    cost_per_api_call: float = 0.001

    # Usage tracking
    web_searches_used: int = 0
    kb_searches_used: int = 0
    api_calls_used: int = 0
    total_cost: float = 0.0

    def remaining_budget(self) -> float:
        """Calculate remaining budget."""
        spent = self.web_searches_used * self.cost_per_web_search
        spent += self.kb_searches_used * self.cost_per_kb_search
        spent += self.api_calls_used * self.cost_per_api_call
        return 10.0 - spent  # Assume $10 budget

    def can_do_web_search(self) -> bool:
        """Check if can perform web search."""
        return (
            self.web_searches_used < self.max_web_searches
            and self.remaining_budget() > self.cost_per_web_search
        )

    def record_web_search(self) -> None:
        """Record a web search."""
        self.web_searches_used += 1
        self.total_cost += self.cost_per_web_search

    def record_kb_search(self) -> None:
        """Record a knowledge base search."""
        self.kb_searches_used += 1
        self.total_cost += self.cost_per_kb_search

    def record_api_call(self) -> None:
        """Record an API call."""
        self.api_calls_used += 1
        self.total_cost += self.cost_per_api_call

    def to_dict(self) -> dict:
        """Serialize for persistence."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SearchBudget:
        """Deserialize from dict."""
        return cls(**data)


class ResearchPlanner:
    """
    Decomposes complex research questions into structured plans.

    Implements multi-step planning pattern from O-Researcher.
    """

    def __init__(self, llm_provider: str | None = None, llm_model: str | None = None):
        self.llm = get_llm(provider=llm_provider, model=llm_model)

    def plan_research(self, query: str, domain: str = "groundwater") -> ResearchPlan:
        """
        Break down a complex query into a structured research plan.

        Args:
            query: Main research question
            domain: Research domain (e.g., "groundwater", "hydrogeology")

        Returns:
            ResearchPlan with sub-questions and prioritized search terms
        """
        prompt = f"""You are a research planning expert in {domain}.

Given the following complex research question, break it down into a structured plan.

RESEARCH QUESTION: {query}

Provide:
1. A clear main question (refined version of the above)
2. 3-5 specific sub-questions that together answer the main question
3. Key research areas to investigate (e.g., "hydrology", "climate change")
4. Expected sections for a comprehensive report
5. Priority-ordered search queries (most important first)

Format your response as JSON:
{{
    "main_question": "...",
    "sub_questions": ["...", "...", "..."],
    "research_areas": ["...", "...", "..."],
    "expected_sections": ["...", "...", "..."],
    "search_priority": ["query1", "query2", "query3"],
    "estimated_depth": 3
}}

Be specific and concrete."""

        try:
            response = self.llm.invoke(prompt)
            data = json.loads(response.content)

            plan = ResearchPlan(
                original_query=query,
                main_question=data.get("main_question", query),
                sub_questions=data.get("sub_questions", []),
                research_areas=data.get("research_areas", []),
                expected_sections=data.get("expected_sections", []),
                search_priority=data.get("search_priority", [query]),
                estimated_depth=data.get("estimated_depth", 3),
            )
            logger.info(f"📋 Research plan created with {len(plan.sub_questions)} sub-questions")
            return plan
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse plan JSON: {e}")
            # Fallback to simple plan
            return ResearchPlan(
                original_query=query,
                main_question=query,
                sub_questions=[query],
                search_priority=[query],
            )
        except Exception as e:
            logger.error(f"Research planning failed: {e}")
            return ResearchPlan(original_query=query, main_question=query, search_priority=[query])


class PriorityRanker:
    """
    Ranks search results by relevance, trust, and recency.

    Implements SmartSearch pattern for intelligent result ordering.
    """

    def __init__(self, llm_provider: str | None = None, llm_model: str | None = None):
        self.llm = get_llm(provider=llm_provider, model=llm_model)

    def rank_results(
        self,
        results: list[dict],
        query: str,
        research_context: str = "",
    ) -> list[RankedSearchResult]:
        """
        Rank search results by combined relevance, trust, and recency scores.

        Args:
            results: List of search result dicts with title, url, snippet, source
            query: The search query used
            research_context: Additional context about the research

        Returns:
            List of RankedSearchResult sorted by combined_score (highest first)
        """
        ranked = []

        for result in results:
            ranked_result = self._calculate_scores(
                result, query, research_context
            )
            ranked.append(ranked_result)

        # Sort by combined score (highest first)
        ranked.sort()

        logger.info(f"📊 Ranked {len(ranked)} results. Top score: {ranked[0].combined_score:.2f}")
        return ranked

    def _calculate_scores(
        self, result: dict, query: str, research_context: str
    ) -> RankedSearchResult:
        """Calculate individual scores for a result."""
        title = result.get("title", "")
        url = result.get("url", "")
        snippet = result.get("snippet", "")
        source = result.get("source", "web")

        # Relevance: How well does content match query
        relevance_score = self._score_relevance(title, snippet, query)

        # Trust: Based on source type
        trust_score = self._score_trust(source, url)

        # Recency: Newer is better (simple heuristic)
        recency_score = self._score_recency(url, snippet)

        # Combined: Weighted average
        combined_score = (relevance_score * 0.5 + trust_score * 0.3 + recency_score * 0.2)

        reasoning = f"Relevance: {relevance_score:.2f}, Trust: {trust_score:.2f}, Recency: {recency_score:.2f}"

        return RankedSearchResult(
            title=title,
            url=url,
            snippet=snippet,
            source=source,
            relevance_score=relevance_score,
            trust_score=trust_score,
            recency_score=recency_score,
            combined_score=combined_score,
            reasoning=reasoning,
        )

    def _score_relevance(self, title: str, snippet: str, query: str) -> float:
        """Score how relevant content is to query."""
        query_words = set(query.lower().split())
        text = (title + " " + snippet).lower()

        matches = sum(1 for word in query_words if word in text)
        max_matches = len(query_words)

        if max_matches == 0:
            return 0.5

        return min(1.0, matches / max_matches)

    def _score_trust(self, source: str, url: str) -> float:
        """Score trust level based on source and domain."""
        if source == "knowledge_base":
            return 0.95  # Local KB is highly trusted

        # Check domain
        trusted_domains = {
            "usgs.gov": 0.9,
            "noaa.gov": 0.9,
            "epa.gov": 0.85,
            "geology.gov": 0.85,
            ".edu": 0.7,
            "researchgate.net": 0.6,
        }

        url_lower = url.lower()
        for domain, score in trusted_domains.items():
            if domain in url_lower:
                return score

        # Default medium trust for web sources
        return 0.5

    def _score_recency(self, url: str, snippet: str) -> float:
        """Score based on recency (heuristic - no real date parsing needed)."""
        # Simple heuristic: if year 2024-2025 mentioned, higher score
        text = (url + " " + snippet).lower()

        recent_years = ["2025", "2024", "2023"]
        for year in recent_years:
            if year in text:
                return 0.8

        # Default medium recency
        return 0.5


class SelfReflectionEvaluator:
    """
    Evaluates research quality and identifies gaps.

    Implements WebSeer pattern for quality control and guided re-search.
    """

    def __init__(self, llm_provider: str | None = None, llm_model: str | None = None):
        self.llm = get_llm(provider=llm_provider, model=llm_model)
        self.min_quality_threshold = 0.7

    def evaluate_synthesis(
        self, synthesis: str, research_plan: ResearchPlan, insights: list[dict]
    ) -> ReflectionResult:
        """
        Evaluate a research synthesis for quality and completeness.

        Args:
            synthesis: The synthesized report/answer
            research_plan: The original research plan with questions
            insights: List of insights gathered

        Returns:
            ReflectionResult with quality assessment
        """
        prompt = f"""You are a research quality evaluator.

ORIGINAL RESEARCH QUESTION: {research_plan.main_question}

SUB-QUESTIONS TO ANSWER:
{chr(10).join(f"- {q}" for q in research_plan.sub_questions)}

SYNTHESIZED ANSWER:
{synthesis}

INSIGHTS GATHERED: {len(insights)} insights with average confidence {sum(i.get('confidence', 0.5) for i in insights) / len(insights):.2f}

Evaluate the synthesis on:
1. **Coverage**: Do all sub-questions get answered?
2. **Confidence**: Is the answer well-supported by evidence?
3. **Completeness**: Is the answer comprehensive?
4. **Clarity**: Is the answer clear and well-structured?

Respond in JSON format:
{{
    "is_high_quality": true/false,
    "confidence_score": 0.0-1.0,
    "coverage_score": 0.0-1.0,
    "overall_quality": 0.0-1.0,
    "missing_areas": ["area1", "area2"],
    "follow_up_queries": ["query1", "query2"],
    "sections_requiring_more_research": ["section1"],
    "reasoning": "..."
}}

Be critical and honest."""

        try:
            response = self.llm.invoke(prompt)
            data = json.loads(response.content)

            result = ReflectionResult(
                is_high_quality=data.get("overall_quality", 0.5) >= self.min_quality_threshold,
                confidence_score=data.get("confidence_score", 0.5),
                coverage_score=data.get("coverage_score", 0.5),
                missing_areas=data.get("missing_areas", []),
                follow_up_queries=data.get("follow_up_queries", []),
                sections_requiring_more_research=data.get(
                    "sections_requiring_more_research", []
                ),
                reasoning=data.get("reasoning", ""),
            )

            logger.info(
                f"🔍 Reflection: Quality={result.confidence_score:.2f}, "
                f"Coverage={result.coverage_score:.2f}"
            )
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse reflection JSON: {e}")
            # Default to moderate quality
            return ReflectionResult(
                is_high_quality=False,
                confidence_score=0.5,
                coverage_score=0.5,
                reasoning="Reflection evaluation failed - using conservative estimate",
            )
        except Exception as e:
            logger.error(f"Self-reflection failed: {e}")
            return ReflectionResult(
                is_high_quality=False,
                confidence_score=0.5,
                coverage_score=0.5,
                reasoning=f"Reflection failed: {e}",
            )


class StructuredReportBuilder:
    """
    Builds multi-section structured reports with per-section citations.

    Replaces simple prose synthesis with organized, cited sections.
    """

    def __init__(self, llm_provider: str | None = None, llm_model: str | None = None):
        self.llm = get_llm(provider=llm_provider, model=llm_model)

    def build_report(
        self,
        query: str,
        insights: list[dict],
        research_plan: ResearchPlan,
        visited_urls: set[str],
    ) -> dict:
        """
        Build a structured multi-section report.

        Args:
            query: Original query
            insights: List of insights with metadata
            research_plan: ResearchPlan with expected sections
            visited_urls: Set of sources consulted

        Returns:
            Dict with report structure:
            {
                "title": "...",
                "executive_summary": "...",
                "sections": [
                    {
                        "heading": "...",
                        "content": "...",
                        "confidence": 0.8,
                        "citations": ["url1", "url2"]
                    },
                    ...
                ],
                "source_summary": {
                    "total_sources": 10,
                    "verified_sources": 8,
                    "source_list": [...]
                },
                "confidence_overall": 0.75
            }
        """
        sections = []

        # Create insights text for context
        insights_text = json.dumps(insights, indent=2)

        prompt = f"""You are a professional research report writer for groundwater science.

RESEARCH QUESTION: {query}

MAIN QUESTION: {research_plan.main_question}

EXPECTED REPORT SECTIONS:
{chr(10).join(f"- {s}" for s in research_plan.expected_sections)}

GATHERED INSIGHTS:
{insights_text}

Create a structured research report with multiple sections.
For each section:
1. Provide a clear heading
2. Write substantive content (2-3 paragraphs)
3. Rate confidence 0.0-1.0
4. List which insights support this section

Format response as JSON:
{{
    "title": "...",
    "executive_summary": "...",
    "sections": [
        {{
            "heading": "...",
            "content": "...",
            "confidence": 0.8,
            "supporting_insight_indices": [0, 2, 5]
        }},
        ...
    ],
    "conclusion": "...",
    "further_research": "..."
}}

Be comprehensive and well-organized."""

        try:
            response = self.llm.invoke(prompt)
            report_data = json.loads(response.content)

            # Build sections with citations
            for section in report_data.get("sections", []):
                insight_indices = section.get("supporting_insight_indices", [])
                citations = []

                for idx in insight_indices:
                    if 0 <= idx < len(insights):
                        insight = insights[idx]
                        if "source_url" in insight:
                            citations.append(insight["source_url"])

                # Remove duplicates while preserving order
                citations = list(dict.fromkeys(citations))

                sections.append(
                    {
                        "heading": section.get("heading", ""),
                        "content": section.get("content", ""),
                        "confidence": section.get("confidence", 0.5),
                        "citations": citations,
                    }
                )

            # Calculate overall confidence
            if sections:
                avg_confidence = sum(s["confidence"] for s in sections) / len(sections)
            else:
                avg_confidence = 0.5

            report = {
                "title": report_data.get(
                    "title", f"Research Report: {research_plan.main_question}"
                ),
                "executive_summary": report_data.get("executive_summary", ""),
                "sections": sections,
                "conclusion": report_data.get("conclusion", ""),
                "further_research": report_data.get("further_research", ""),
                "source_summary": {
                    "total_sources": len(visited_urls),
                    "sources": sorted(list(visited_urls)),
                },
                "confidence_overall": avg_confidence,
                "generated_at": datetime.now().isoformat(),
            }

            logger.info(f"📄 Built structured report with {len(sections)} sections")
            return report
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse report JSON: {e}")
            # Fallback to simple section
            return {
                "title": f"Research Report: {query}",
                "executive_summary": "Report generation failed",
                "sections": [
                    {
                        "heading": "Overview",
                        "content": "Report generation encountered an error.",
                        "confidence": 0.3,
                        "citations": list(visited_urls)[:5],
                    }
                ],
                "source_summary": {"total_sources": len(visited_urls), "sources": list(visited_urls)},
                "confidence_overall": 0.3,
                "generated_at": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Report building failed: {e}")
            return {
                "title": f"Research Report: {query}",
                "executive_summary": f"Error: {e}",
                "sections": [],
                "source_summary": {"total_sources": len(visited_urls), "sources": list(visited_urls)},
                "confidence_overall": 0.0,
                "generated_at": datetime.now().isoformat(),
            }


class ResearchSessionPersistence:
    """
    Save and restore research sessions for resumability.

    Enables pausing and resuming long research operations.
    """

    def __init__(self, session_dir: Path = Path("./research_sessions")):
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(exist_ok=True)

    def save_session(self, session_id: str, session_data: dict) -> Path:
        """
        Save a research session to disk.

        Args:
            session_id: Unique session identifier
            session_data: Session state dict

        Returns:
            Path to saved session file
        """
        session_file = self.session_dir / f"{session_id}.json"

        # Serialize datetime objects
        data = self._serialize_session(session_data)

        try:
            with open(session_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"💾 Session saved: {session_file}")
            return session_file
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            raise

    def load_session(self, session_id: str) -> dict | None:
        """
        Load a research session from disk.

        Args:
            session_id: Unique session identifier

        Returns:
            Session state dict, or None if not found
        """
        session_file = self.session_dir / f"{session_id}.json"

        if not session_file.exists():
            logger.warning(f"Session not found: {session_id}")
            return None

        try:
            with open(session_file, "r") as f:
                data = json.load(f)
            logger.info(f"📂 Session loaded: {session_file}")
            return self._deserialize_session(data)
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return None

    def list_sessions(self) -> list[str]:
        """List all available session IDs."""
        sessions = []
        for f in self.session_dir.glob("*.json"):
            sessions.append(f.stem)
        return sorted(sessions)

    def delete_session(self, session_id: str) -> bool:
        """Delete a saved session."""
        session_file = self.session_dir / f"{session_id}.json"
        if session_file.exists():
            try:
                session_file.unlink()
                logger.info(f"🗑️  Session deleted: {session_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete session: {e}")
                return False
        return False

    def _serialize_session(self, data: dict) -> dict:
        """Serialize session data for JSON storage."""
        serialized = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                serialized[key] = value.isoformat()
            elif isinstance(value, set):
                serialized[key] = list(value)
            elif isinstance(value, dict):
                serialized[key] = self._serialize_session(value)
            elif isinstance(value, list):
                serialized[key] = [
                    self._serialize_session({"item": item})["item"]
                    if isinstance(item, dict)
                    else self._serialize_session({"item": item})["item"]
                    if isinstance(item, datetime)
                    else item
                    for item in value
                ]
            else:
                serialized[key] = value
        return serialized

    def _deserialize_session(self, data: dict) -> dict:
        """Deserialize session data from JSON storage."""
        # Simple pass-through - can be enhanced to restore types as needed
        return data
