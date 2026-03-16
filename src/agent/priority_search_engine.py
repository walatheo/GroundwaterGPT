"""Priority-Based Search Engine for Groundwater Research.

Implements SmartSearch pattern for intelligent search execution:
- Query prioritization based on research plan
- Multi-source searching (KB, web, data)
- Priority ranking of results
- Budget-aware search management

Reference: Awesome-Deep-Research SmartSearch pattern
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional, Tuple, Callable
from datetime import datetime

from .research_optimizer import (
    RankedSearchResult,
    SearchBudget,
    PriorityRanker,
)
from .llm_factory import get_llm

logger = logging.getLogger(__name__)


class SearchSourceType(Enum):
    """Types of search sources."""

    KNOWLEDGE_BASE = "knowledge_base"
    WEB = "web"
    DATA = "data"  # USGS pipeline data


@dataclass
class SearchQuery:
    """A prioritized search query."""

    query_text: str
    priority: float = 0.5  # 0.0-1.0
    source_type: SearchSourceType = SearchSourceType.WEB
    importance: str = "medium"  # low, medium, high
    context: str = ""  # Additional context for the search

    def __lt__(self, other: SearchQuery) -> bool:
        """Higher priority first."""
        return self.priority > other.priority

    def __repr__(self) -> str:
        return f"Q({self.priority:.2f}): {self.query_text[:50]}"


@dataclass
class SearchResult:
    """A search result from any source."""

    title: str
    content: str
    url: str
    source: SearchSourceType
    relevance_score: float = 0.5
    trust_score: float = 0.5
    retrieved_at: datetime = None
    metadata: Dict = None

    def __post_init__(self):
        if self.retrieved_at is None:
            self.retrieved_at = datetime.now()
        if self.metadata is None:
            self.metadata = {}

    def combined_score(self) -> float:
        """Compute combined relevance score."""
        return 0.6 * self.relevance_score + 0.4 * self.trust_score


class QueryPrioritizer:
    """
    Prioritizes search queries based on research importance.

    Implements intelligent query ordering to maximize research value
    within budget constraints.
    """

    def __init__(self, llm_provider: str | None = None, llm_model: str | None = None):
        self.llm = get_llm(provider=llm_provider, model=llm_model)

    def prioritize_queries(
        self,
        queries: List[str],
        research_context: str = "",
        budget: SearchBudget | None = None,
    ) -> List[SearchQuery]:
        """
        Prioritize a list of search queries.

        Args:
            queries: List of search query strings
            research_context: Context about the research
            budget: Optional budget constraints

        Returns:
            List of SearchQuery objects, sorted by priority (highest first)
        """
        if not queries:
            return []

        if not budget:
            budget = SearchBudget()

        # User structured prompting to prioritize
        queries_str = "\n".join(f"{i+1}. {q}" for i, q in enumerate(queries))

        prompt = f"""You are a research prioritization expert.

RESEARCH CONTEXT: {research_context}

SEARCH QUERIES TO PRIORITIZE:
{queries_str}

For each query, determine:
1. Priority (0.0-1.0): How important is this query to the overall research?
2. Importance level: "low", "medium", "high"
3. Best source: "knowledge_base", "web", or "data"

Research queries addressing main questions and gaps should be highest priority.

Respond as JSON list:
[
  {{"query": "query text", "priority": 0.95, "importance": "high", "source": "web"}},
  ...
]

Be strategic - limited budget means we need the most impactful queries first."""

        try:
            response = self.llm.invoke(prompt)

            # Parse JSON response
            import json

            data = json.loads(response.content)

            search_queries = []
            for item in data:
                source_map = {
                    "knowledge_base": SearchSourceType.KNOWLEDGE_BASE,
                    "web": SearchSourceType.WEB,
                    "data": SearchSourceType.DATA,
                }

                sq = SearchQuery(
                    query_text=item.get("query", ""),
                    priority=float(item.get("priority", 0.5)),
                    source_type=source_map.get(item.get("source", "web")),
                    importance=item.get("importance", "medium"),
                )
                search_queries.append(sq)

            # Sort by priority
            search_queries.sort()

            logger.info(f"📊 Prioritized {len(search_queries)} queries")
            for sq in search_queries[:5]:
                logger.info(f"  {sq}")

            return search_queries

        except Exception as e:
            logger.warning(f"Failed to prioritize queries with LLM: {e}")
            # Fallback: return queries in original order with equal priority
            return [
                SearchQuery(
                    query_text=q,
                    priority=0.5,
                    source_type=SearchSourceType.WEB,
                )
                for q in queries
            ]


class MultiSourceSearchEngine:
    """
    Executes searches across multiple sources with budget management.

    Implements ReSeek pattern for budget-aware knowledge seeking.
    """

    def __init__(
        self,
        kb_searcher: Callable[[str], List[Dict]] | None = None,
        web_searcher: Callable[[str], List[Dict]] | None = None,
        data_searcher: Callable[[str], List[Dict]] | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ):
        """
        Initialize multi-source search engine.

        Args:
            kb_searcher: Function to search knowledge base
            web_searcher: Function to search web
            data_searcher: Function to search USGS data
            llm_provider: LLM provider for ranking
            llm_model: LLM model for ranking
        """
        self.kb_searcher = kb_searcher
        self.web_searcher = web_searcher
        self.data_searcher = data_searcher

        self.ranker = PriorityRanker(llm_provider=llm_provider, llm_model=llm_model)
        self.budget = SearchBudget()
        self.search_history: List[Tuple[SearchQuery, List[SearchResult]]] = []

    def search(
        self,
        query: SearchQuery,
        num_results: int = 5,
        enforce_budget: bool = True,
    ) -> List[SearchResult]:
        """
        Execute search for a single prioritized query.

        Args:
            query: SearchQuery with priority and source info
            num_results: Number of results to return
            enforce_budget: Whether to enforce budget constraints

        Returns:
            List of SearchResult objects, ranked by relevance
        """
        if enforce_budget and not self._can_search(query):
            logger.warning(f"❌ Search budget exhausted for {query.source_type.value}")
            return []

        logger.info(f"🔍 Searching [{query.source_type.value}]: {query.query_text}")

        results = []

        # Execute search based on source type
        if query.source_type == SearchSourceType.KNOWLEDGE_BASE:
            results = self._search_kb(query.query_text, num_results)
            self.budget.record_kb_search()
        elif query.source_type == SearchSourceType.WEB:
            results = self._search_web(query.query_text, num_results)
            self.budget.record_web_search()
        elif query.source_type == SearchSourceType.DATA:
            results = self._search_data(query.query_text, num_results)
            self.budget.record_api_call()

        # Rank results
        if results:
            ranked = self._rank_results(results, query.query_text)
            self.search_history.append((query, ranked))
            logger.info(
                f"📊 Got {len(ranked)} results (top score: {ranked[0].combined_score():.2f})"
            )
            return ranked[:num_results]

        return []

    def batch_search(
        self,
        queries: List[SearchQuery],
        num_results: int = 5,
        enforce_budget: bool = True,
    ) -> Dict[str, List[SearchResult]]:
        """
        Execute multiple searches with budget management.

        Args:
            queries: List of SearchQuery objects
            num_results: Results per query
            enforce_budget: Whether to enforce budget constraints

        Returns:
            Dict mapping query text -> search results
        """
        results = {}

        # Sort by priority
        sorted_queries = sorted(queries)

        for query in sorted_queries:
            if enforce_budget and not self._can_search(query):
                logger.warning(f"⚠️  Budget exhausted. Stopping search.")
                break

            search_results = self.search(query, num_results, enforce_budget)
            results[query.query_text] = search_results

        logger.info(f"📊 Batch search complete: {len(results)} queries executed")
        logger.info(f"💰 Budget used: ${self.budget.total_cost:.2f}")

        return results

    def _can_search(self, query: SearchQuery) -> bool:
        """Check if we can perform this search given budget."""
        if query.source_type == SearchSourceType.KNOWLEDGE_BASE:
            return self.budget.kb_searches_used < self.budget.max_kb_searches
        elif query.source_type == SearchSourceType.WEB:
            return (
                self.budget.web_searches_used < self.budget.max_web_searches
                and self.budget.can_do_web_search()
            )
        elif query.source_type == SearchSourceType.DATA:
            return (
                self.budget.api_calls_used < self.budget.max_api_calls
                and self.budget.remaining_budget() > self.budget.cost_per_api_call
            )
        return False

    def _search_kb(self, query_text: str, limit: int) -> List[SearchResult]:
        """Search knowledge base."""
        if not self.kb_searcher:
            return []

        try:
            kb_results = self.kb_searcher(query_text)

            results = []
            for item in kb_results[:limit]:
                result = SearchResult(
                    title=item.get("title", ""),
                    content=item.get("snippet", "") or item.get("content", ""),
                    url=item.get("url", ""),
                    source=SearchSourceType.KNOWLEDGE_BASE,
                    relevance_score=item.get("relevance_score", 0.7),
                    trust_score=0.95,  # KB is highly trusted
                )
                results.append(result)

            return results
        except Exception as e:
            logger.error(f"KB search failed: {e}")
            return []

    def _search_web(self, query_text: str, limit: int) -> List[SearchResult]:
        """Search web."""
        if not self.web_searcher:
            return []

        try:
            web_results = self.web_searcher(query_text)

            results = []
            for item in web_results[:limit]:
                result = SearchResult(
                    title=item.get("title", ""),
                    content=item.get("snippet", ""),
                    url=item.get("url", ""),
                    source=SearchSourceType.WEB,
                    relevance_score=item.get("relevance_score", 0.5),
                    trust_score=item.get("trust_score", 0.5),
                )
                results.append(result)

            return results
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return []

    def _search_data(self, query_text: str, limit: int) -> List[SearchResult]:
        """Search USGS data."""
        if not self.data_searcher:
            return []

        try:
            data_results = self.data_searcher(query_text)

            results = []
            for item in data_results[:limit]:
                result = SearchResult(
                    title=item.get("title", ""),
                    content=item.get("summary", ""),
                    url=item.get("url", ""),
                    source=SearchSourceType.DATA,
                    relevance_score=item.get("relevance_score", 0.8),
                    trust_score=0.9,  # USGS is highly trusted
                )
                results.append(result)

            return results
        except Exception as e:
            logger.error(f"Data search failed: {e}")
            return []

    def _rank_results(
        self,
        results: List[SearchResult],
        query: str,
    ) -> List[SearchResult]:
        """Rank results by relevance and trust."""
        # Convert to format expected by ranker
        result_dicts = [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.content,
                "source": r.source.value,
            }
            for r in results
        ]

        try:
            ranked = self.ranker.rank_results(result_dicts, query)

            # Convert back to SearchResult with scores
            for r in results:
                for ranked_r in ranked:
                    if r.url == ranked_r.url:
                        r.relevance_score = ranked_r.relevance_score
                        r.trust_score = ranked_r.trust_score

            # Sort by combined score
            results.sort(key=lambda r: r.combined_score(), reverse=True)

        except Exception as e:
            logger.warning(f"Ranking failed: {e}")

        return results

    def get_budget_status(self) -> Dict[str, any]:
        """Get current budget status."""
        return {
            "web_searches_used": self.budget.web_searches_used,
            "web_searches_max": self.budget.max_web_searches,
            "kb_searches_used": self.budget.kb_searches_used,
            "kb_searches_max": self.budget.max_kb_searches,
            "api_calls_used": self.budget.api_calls_used,
            "api_calls_max": self.budget.max_api_calls,
            "total_cost": self.budget.total_cost,
            "remaining_budget": self.budget.remaining_budget(),
        }

    def reset_budget(self) -> None:
        """Reset budget for new research session."""
        self.budget = SearchBudget()
        self.search_history = []


class SearchPipeline:
    """
    Complete search pipeline combining prioritization and multi-source searching.

    Orchestrates the full SmartSearch + ReSeek workflow.
    """

    def __init__(
        self,
        kb_searcher: Callable[[str], List[Dict]] | None = None,
        web_searcher: Callable[[str], List[Dict]] | None = None,
        data_searcher: Callable[[str], List[Dict]] | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ):
        """Initialize search pipeline."""
        self.prioritizer = QueryPrioritizer(
            llm_provider=llm_provider, llm_model=llm_model
        )
        self.search_engine = MultiSourceSearchEngine(
            kb_searcher=kb_searcher,
            web_searcher=web_searcher,
            data_searcher=data_searcher,
            llm_provider=llm_provider,
            llm_model=llm_model,
        )

    def execute(
        self,
        research_queries: List[str],
        research_context: str = "",
        num_results_per_query: int = 5,
    ) -> Dict[str, List[SearchResult]]:
        """
        Execute complete search pipeline.

        Args:
            research_queries: List of search queries
            research_context: Research context
            num_results_per_query: Number of results per query

        Returns:
            Dict mapping query -> results
        """
        logger.info(f"🔍 Starting search pipeline for {len(research_queries)} queries")

        # Prioritize queries
        prioritized = self.prioritizer.prioritize_queries(
            research_queries,
            research_context=research_context,
            budget=self.search_engine.budget,
        )

        # Execute batch search
        results = self.search_engine.batch_search(
            prioritized,
            num_results=num_results_per_query,
        )

        return results

    def get_statistics(self) -> Dict[str, any]:
        """Get search pipeline statistics."""
        return {
            "total_queries": len(self.search_engine.search_history),
            "total_results": sum(
                len(results) for _, results in self.search_engine.search_history
            ),
            "budget": self.search_engine.get_budget_status(),
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example usage
    prioritizer = QueryPrioritizer()
    queries = [
        "Biscayne Aquifer water level trends",
        "drought impact Florida",
        "seasonal groundwater patterns",
        "sea level rise aquifer",
    ]

    prioritized = prioritizer.prioritize_queries(
        queries,
        research_context="Studying water level changes in Florida aquifers",
    )

    print("\nPrioritized Queries:")
    for pq in prioritized:
        print(f"  {pq.priority:.2f} [{pq.importance}] {pq.query_text}")
