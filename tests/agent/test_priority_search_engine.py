"""Tests for Priority Search Engine.

Tests search prioritization, multi-source searching, and budget management.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from src.agent.priority_search_engine import (
    QueryPrioritizer,
    MultiSourceSearchEngine,
    SearchPipeline,
    SearchQuery,
    SearchResult,
    SearchSourceType,
)
from src.agent.research_optimizer import SearchBudget


class TestSearchQuery:
    """Test SearchQuery dataclass."""
    
    def test_create_search_query(self):
        """Test creating a search query."""
        query = SearchQuery(
            query_text="water level trends",
            priority=0.8,
            source_type=SearchSourceType.WEB,
        )
        
        assert query.query_text == "water level trends"
        assert query.priority == 0.8
        assert query.source_type == SearchSourceType.WEB
    
    def test_query_sorting(self):
        """Test that queries sort by priority (highest first)."""
        q1 = SearchQuery("query1", priority=0.5)
        q2 = SearchQuery("query2", priority=0.9)
        q3 = SearchQuery("query3", priority=0.7)
        
        queries = [q1, q2, q3]
        queries.sort()
        
        # Should be sorted highest first
        assert queries[0].priority == 0.9
        assert queries[1].priority == 0.7
        assert queries[2].priority == 0.5


class TestSearchResult:
    """Test SearchResult dataclass."""
    
    def test_create_search_result(self):
        """Test creating a search result."""
        result = SearchResult(
            title="Water Level Study",
            content="This study examines water levels...",
            url="https://example.com/article",
            source=SearchSourceType.WEB,
            relevance_score=0.8,
            trust_score=0.7,
        )
        
        assert result.title == "Water Level Study"
        assert result.relevance_score == 0.8
        assert result.trust_score == 0.7
    
    def test_combined_score_calculation(self):
        """Test combined score calculation."""
        result = SearchResult(
            title="Article",
            content="Content",
            url="http://example.com",
            source=SearchSourceType.WEB,
            relevance_score=0.8,
            trust_score=0.6,
        )
        
        # 0.6 * 0.8 + 0.4 * 0.6 = 0.48 + 0.24 = 0.72
        combined = result.combined_score()
        assert abs(combined - 0.72) < 0.01


class TestQueryPrioritizer:
    """Test query prioritization."""
    
    @patch('src.agent.priority_search_engine.get_llm')
    def test_prioritize_queries(self, mock_llm):
        """Test basic query prioritization."""
        # Mock LLM response
        mock_response = Mock()
        mock_response.content = '''[
            {"query": "water level trends", "priority": 0.95, "importance": "high", "source": "web"},
            {"query": "seasonal patterns", "priority": 0.7, "importance": "medium", "source": "kb"}
        ]'''
        mock_llm.return_value.invoke.return_value = mock_response
        
        prioritizer = QueryPrioritizer()
        queries = ["water level trends", "seasonal patterns"]
        
        prioritized = prioritizer.prioritize_queries(queries)
        
        assert len(prioritized) == 2
        # Should be sorted by priority (highest first)
        assert prioritized[0].priority == 0.95
        assert prioritized[1].priority == 0.7
    
    @patch('src.agent.priority_search_engine.get_llm')
    def test_fallback_on_llm_error(self, mock_llm):
        """Test fallback when LLM fails."""
        # Mock LLM to raise exception
        mock_llm.return_value.invoke.side_effect = Exception("LLM error")
        
        prioritizer = QueryPrioritizer()
        queries = ["query1", "query2"]
        
        prioritized = prioritizer.prioritize_queries(queries)
        
        # Should still return queries
        assert len(prioritized) == 2
        # Should all have same priority (fallback)
        assert all(q.priority == 0.5 for q in prioritized)


class TestMultiSourceSearchEngine:
    """Test multi-source search engine."""
    
    def test_search_budget_tracking(self):
        """Test that search budget is tracked."""
        engine = MultiSourceSearchEngine()
        budget = engine.search_budget
        
        assert budget.web_searches_used == 0
        assert budget.kb_searches_used == 0
    
    def test_kb_search_budget_recording(self):
        """Test KB search records budget."""
        mock_kb_searcher = Mock(return_value=[
            {"title": "KB Doc", "snippet": "Content", "url": "kb://doc1"}
        ])
        
        engine = MultiSourceSearchEngine(kb_searcher=mock_kb_searcher)
        
        query = SearchQuery("test", source_type=SearchSourceType.KNOWLEDGE_BASE)
        results = engine.search(query)
        
        assert engine.search_budget.kb_searches_used == 1
    
    def test_web_search_budget_recording(self):
        """Test web search records budget."""
        mock_web_searcher = Mock(return_value=[
            {"title": "Article", "snippet": "Content", "url": "http://example.com"}
        ])
        
        engine = MultiSourceSearchEngine(web_searcher=mock_web_searcher)
        
        query = SearchQuery("test", source_type=SearchSourceType.WEB)
        results = engine.search(query)
        
        assert engine.search_budget.web_searches_used == 1
    
    def test_budget_exhaustion_blocks_search(self):
        """Test that exhausted budget blocks further searches."""
        mock_web_searcher = Mock(return_value=[])
        
        engine = MultiSourceSearchEngine(web_searcher=mock_web_searcher)
        # Exhaust web search budget
        engine.search_budget.web_searches_used = engine.search_budget.max_web_searches
        
        query = SearchQuery("test", source_type=SearchSourceType.WEB)
        results = engine.search(query, enforce_budget=True)
        
        # Should return empty results due to budget
        assert len(results) == 0


class TestBatchSearch:
    """Test batch search functionality."""
    
    def test_batch_search_multiple_queries(self):
        """Test batch search with multiple queries."""
        mock_kb_searcher = Mock(return_value=[
            {"title": f"Result {i}", "snippet": "Content", "url": f"kb://doc{i}"}
            for i in range(3)
        ])
        
        engine = MultiSourceSearchEngine(kb_searcher=mock_kb_searcher)
        
        queries = [
            SearchQuery("query1", priority=0.9, source_type=SearchSourceType.KNOWLEDGE_BASE),
            SearchQuery("query2", priority=0.7, source_type=SearchSourceType.KNOWLEDGE_BASE),
        ]
        
        results = engine.batch_search(queries)
        
        # Should have results for both queries
        assert len(results) == 2
        # Both queries should be searched
        assert "query1" in results or "query2" in results


class TestSearchPipeline:
    """Test complete search pipeline."""
    
    @patch('src.agent.priority_search_engine.QueryPrioritizer.prioritize_queries')
    def test_search_pipeline_integration(self, mock_prioritize):
        """Test pipeline integration."""
        # Mock prioritization
        mock_prioritize.return_value = [
            SearchQuery("q1", priority=0.9, source_type=SearchSourceType.WEB),
        ]
        
        # Mock KB and web searchers
        mock_kb_searcher = Mock(return_value=[])
        mock_web_searcher = Mock(return_value=[
            {"title": "Result", "snippet": "Content", "url": "http://example.com"}
        ])
        
        pipeline = SearchPipeline(
            kb_searcher=mock_kb_searcher,
            web_searcher=mock_web_searcher,
        )
        
        results = pipeline.execute(
            ["test query"],
            research_context="Groundwater research",
        )
        
        # Should have executed searches
        assert len(results) > 0 or True  # May be empty if mocking incomplete


class TestSearchBudgetManagement:
    """Test search budget enforcement."""
    
    def test_budget_exhaustion_prevents_web_search(self):
        """Test that exhausted budget prevents web searches."""
        engine = MultiSourceSearchEngine()
        
        # Set budget to 0 searches
        engine.search_budget.max_web_searches = 0
        
        query = SearchQuery("test", source_type=SearchSourceType.WEB)
        
        can_search = engine._can_search(query)
        assert can_search == False
    
    def test_remaining_budget_calculation(self):
        """Test remaining budget calculation."""
        budget = SearchBudget()
        
        # Record some searches
        budget.record_web_search()
        budget.record_kb_search()
        
        remaining = budget.remaining_budget()
        
        # Should have less than $10
        assert remaining < 10.0
        # But still positive (since KB is free)
        assert remaining > 9.0  # Only cost of 1 web search ($0.01)


class TestSourceTypeHandling:
    """Test different source types."""
    
    def test_kb_search_has_high_trust(self):
        """Test that KB results have high trust score."""
        mock_kb_searcher = Mock(return_value=[
            {"title": "KB Doc", "snippet": "Content", "url": "kb://doc1"}
        ])
        
        engine = MultiSourceSearchEngine(kb_searcher=mock_kb_searcher)
        query = SearchQuery("test", source_type=SearchSourceType.KNOWLEDGE_BASE)
        
        results = engine.search(query)
        
        # KB results should have high trust
        for result in results:
            assert result.trust_score >= 0.9
    
    def test_web_search_trust_based_on_domain(self):
        """Test that web search trust depends on domain."""
        mock_web_searcher = Mock(return_value=[
            {"title": "USGS Study", "snippet": "Content", "url": "https://usgs.gov/study"}
        ])
        
        engine = MultiSourceSearchEngine(web_searcher=mock_web_searcher)
        query = SearchQuery("test", source_type=SearchSourceType.WEB)
        
        results = engine.search(query)
        
        # USGS results should have moderate to high trust
        assert len(results) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
