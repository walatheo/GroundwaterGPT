"""
Tests for Deep Research Agent v2 - Agentic Deep Research with Advanced Optimization.

Tests patterns from Awesome-Deep-Research:
- Research planning (multi-step decomposition)
- Priority ranking (SmartSearch)
- Self-reflection (WebSeer)
- Search budget management (ReSeek)
- Session persistence (resumability)
"""

import json
import tempfile
from pathlib import Path

import pytest

from src.agent.research_agent import DeepResearchAgent
from src.agent.research_optimizer import (PriorityRanker, RankedSearchResult,
                                          ReflectionResult, ResearchPlan,
                                          ResearchPlanner,
                                          ResearchSessionPersistence,
                                          SearchBudget,
                                          SelfReflectionEvaluator,
                                          StructuredReportBuilder)


class TestResearchPlan:
    """Test research plan creation and serialization."""

    def test_research_plan_creation(self) -> None:
        """Test creating a research plan."""
        plan = ResearchPlan(
            original_query="What is saltwater intrusion?",
            main_question="What causes saltwater intrusion in coastal aquifers?",
            sub_questions=["What is saltwater intrusion?", "How does it affect wells?"],
            search_priority=[
                "saltwater intrusion mechanism",
                "Florida aquifer saltwater",
            ],
        )

        assert plan.original_query == "What is saltwater intrusion?"
        assert len(plan.sub_questions) == 2
        assert len(plan.search_priority) == 2

    def test_research_plan_serialization(self) -> None:
        """Test serializing and deserializing a plan."""
        plan = ResearchPlan(
            original_query="Test query",
            main_question="Test main question",
            sub_questions=["Sub 1", "Sub 2"],
        )

        # Serialize
        data = plan.to_dict()
        assert isinstance(data, dict)
        assert data["original_query"] == "Test query"

        # Deserialize
        restored = ResearchPlan.from_dict(data)
        assert restored.original_query == plan.original_query
        assert restored.sub_questions == plan.sub_questions


class TestPriorityRanker:
    """Test search result ranking."""

    def test_ranker_initialization(self) -> None:
        """Test ranker can be initialized."""
        ranker = PriorityRanker()
        assert ranker is not None

    def test_score_trust(self) -> None:
        """Test trust scoring for different sources."""
        ranker = PriorityRanker()

        # USGS sources are highly trusted
        usgs_score = ranker._score_trust("web", "https://usgs.gov/data")
        assert usgs_score >= 0.85

        # Knowledge base is most trusted
        kb_score = ranker._score_trust("knowledge_base", "local://kb")
        assert kb_score >= 0.9

        # Unknown sources have lower trust
        unknown_score = ranker._score_trust("web", "https://example.com/data")
        assert unknown_score <= 0.6

    def test_score_relevance(self) -> None:
        """Test relevance scoring."""
        ranker = PriorityRanker()
        query = "groundwater aquifer"

        # High relevance
        title = "Groundwater Aquifer Analysis"
        snippet = "This study examines aquifer dynamics"
        high_relevance = ranker._score_relevance(title, snippet, query)
        assert high_relevance >= 0.5

        # Low relevance
        title = "Weather patterns"
        snippet = "Clouds and rain"
        low_relevance = ranker._score_relevance(title, snippet, query)
        assert low_relevance < high_relevance

    def test_rank_results(self) -> None:
        """Test ranking multiple results."""
        ranker = PriorityRanker()

        results = [
            {
                "title": "USGS Groundwater Data",
                "url": "https://usgs.gov/data",
                "snippet": "Groundwater aquifer information 2024",
                "source": "web",
            },
            {
                "title": "Random blog",
                "url": "https://example.com/blog",
                "snippet": "Just some information",
                "source": "web",
            },
        ]

        ranked = ranker.rank_results(results, "groundwater aquifer")
        assert len(ranked) == 2
        # USGS should rank higher
        assert ranked[0].url == "https://usgs.gov/data"


class TestSearchBudget:
    """Test search budget tracking."""

    def test_budget_initialization(self) -> None:
        """Test budget can be created."""
        budget = SearchBudget()
        assert budget.web_searches_used == 0
        assert budget.total_cost == 0.0

    def test_budget_tracking(self) -> None:
        """Test recording searches."""
        budget = SearchBudget(max_web_searches=5)

        assert budget.can_do_web_search()

        budget.record_web_search()
        assert budget.web_searches_used == 1

        budget.record_kb_search()
        assert budget.kb_searches_used == 1

    def test_budget_limits(self) -> None:
        """Test budget constraints."""
        budget = SearchBudget(max_web_searches=2)

        assert budget.can_do_web_search()

        budget.record_web_search()
        budget.record_web_search()

        # Should be at limit now
        assert not budget.can_do_web_search()

    def test_budget_serialization(self) -> None:
        """Test serializing budget."""
        budget = SearchBudget()
        budget.record_web_search()

        data = budget.to_dict()
        assert data["web_searches_used"] == 1

        restored = SearchBudget.from_dict(data)
        assert restored.web_searches_used == 1


class TestResearchSessionPersistence:
    """Test session save/load functionality."""

    def test_persistence_initialization(self) -> None:
        """Test creating persistence manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = ResearchSessionPersistence(Path(tmpdir))
            assert persistence.session_dir.exists()

    def test_save_and_load_session(self) -> None:
        """Test saving and loading a session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = ResearchSessionPersistence(Path(tmpdir))

            session_data = {
                "query": "Test query",
                "insights": 5,
                "status": "complete",
            }

            # Save
            persistence.save_session("test_session_123", session_data)

            # Load
            loaded = persistence.load_session("test_session_123")
            assert loaded is not None
            assert loaded["query"] == "Test query"

    def test_list_sessions(self) -> None:
        """Test listing sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = ResearchSessionPersistence(Path(tmpdir))

            persistence.save_session("session1", {"query": "q1"})
            persistence.save_session("session2", {"query": "q2"})

            sessions = persistence.list_sessions()
            assert len(sessions) == 2
            assert "session1" in sessions
            assert "session2" in sessions

    def test_delete_session(self) -> None:
        """Test deleting a session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence = ResearchSessionPersistence(Path(tmpdir))

            persistence.save_session("to_delete", {"query": "q"})
            assert len(persistence.list_sessions()) == 1

            persistence.delete_session("to_delete")
            assert len(persistence.list_sessions()) == 0


class TestDeepResearchAgentV2:
    """Test enhanced DeepResearchAgent with v2 features."""

    def test_agent_initialization_with_features(self) -> None:
        """Test initializing agent with advanced features."""
        agent = DeepResearchAgent(
            enable_planning=True,
            enable_reflection=True,
            enable_budget_management=True,
            enable_persistence=True,
        )

        assert agent.enable_planning
        assert agent.enable_reflection
        assert agent.enable_budget_management
        assert agent.enable_persistence

    def test_agent_components_initialized(self) -> None:
        """Test all components are created."""
        agent = DeepResearchAgent()

        assert agent.planner is not None
        assert agent.ranker is not None
        assert agent.reflector is not None
        assert agent.report_builder is not None
        assert agent.persistence is not None
        assert agent.search_budget is not None

    def test_list_sessions(self) -> None:
        """Test listing sessions from agent."""
        agent = DeepResearchAgent()
        sessions = agent.list_sessions()
        assert isinstance(sessions, list)

    def test_get_search_budget_status(self) -> None:
        """Test getting budget status."""
        agent = DeepResearchAgent()
        status = agent.get_search_budget_status()

        assert "web_searches_used" in status
        assert "web_searches_max" in status
        assert "total_cost" in status
        assert "remaining_budget" in status


class TestAcceptanceCriteria:
    """Test acceptance criteria from Session 13."""

    def test_complex_query_handling(self) -> None:
        """Test handling complex questions (acceptance criterion 1)."""
        query = (
            "What are the long-term impacts of sea level rise on the Biscayne Aquifer?"
        )

        planner = ResearchPlanner()
        plan = planner.plan_research(query, domain="groundwater")

        assert plan.original_query == query
        assert len(plan.sub_questions) > 0
        assert len(plan.search_priority) > 0
        # Should have expected sections for a comprehensive answer
        assert len(plan.expected_sections) > 0

    def test_self_reflection_quality_detection(self) -> None:
        """Test self-reflection can detect quality (acceptance criterion 2)."""
        reflector = SelfReflectionEvaluator()
        plan = ResearchPlan(
            original_query="Test question",
            main_question="Test",
            sub_questions=["Sub1", "Sub2"],
        )

        # Mediocre synthesis
        weak_synthesis = "Some information but not comprehensive"
        weak_result = reflector.evaluate_synthesis(weak_synthesis, plan, [])

        assert isinstance(weak_result, ReflectionResult)
        # Low quality synthesis should be detected
        assert weak_result.confidence_score < 0.8

    def test_research_session_resumability(self) -> None:
        """Test research can be saved and resumed (acceptance criterion 3)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent = DeepResearchAgent(enable_persistence=True)
            agent.persistence.session_dir = Path(tmpdir)

            session_id = "test_resume_session"

            # Save a session
            session_data = {
                "original_query": "What is groundwater?",
                "current_query": "groundwater definition",
                "max_depth": 3,
                "insights_count": 5,
                "sources_count": 3,
            }

            agent.persistence.save_session(session_id, session_data)

            # Load and verify
            loaded = agent.persistence.load_session(session_id)
            assert loaded is not None
            assert loaded["original_query"] == "What is groundwater?"
            assert loaded["insights_count"] == 5


class TestAwesomeDeepResearchPatterns:
    """Test implementations of Awesome-Deep-Research patterns."""

    def test_smart_search_pattern(self) -> None:
        """Test SmartSearch (iterative query optimization)."""
        agent = DeepResearchAgent(enable_planning=True)

        query = "What agricultural practices affect groundwater in Florida?"
        plan = agent.planner.plan_research(query)

        # Should break into specific sub-questions
        assert len(plan.search_priority) > 1
        # First queries should be broader, can narrow based on results
        first_query = plan.search_priority[0]
        assert len(first_query) > 0

    def test_webseeker_pattern(self) -> None:
        """Test WebSeer (quality control via reflection)."""
        reflector = SelfReflectionEvaluator()
        plan = ResearchPlan(
            original_query="Complex research question",
            main_question="Main Q",
            sub_questions=["Q1", "Q2", "Q3"],
        )

        comprehensive_answer = """
        This comprehensive answer addresses all aspects:
        1. First sub-question thoroughly answered with evidence
        2. Second sub-question explained with examples
        3. Third sub-question covered with citations
        
        Key findings supported by multiple sources.
        """

        result = reflector.evaluate_synthesis(
            comprehensive_answer, plan, [{"confidence": 0.8}] * 3
        )

        # Comprehensive answer should score higher
        assert result.confidence_score > 0.5

    def test_budget_aware_search_pattern(self) -> None:
        """Test ReSeek (budget-aware tool use)."""
        budget = SearchBudget(max_web_searches=3, cost_per_web_search=0.05)

        # Should have budget initially
        assert budget.can_do_web_search()

        # Simulate searches until budget exhausted
        budget.record_web_search()  # $0.05
        budget.record_web_search()  # $0.10
        budget.record_web_search()  # $0.15

        # Now at limit
        assert not budget.can_do_web_search()
        assert budget.total_cost == 0.15

    def test_multi_agent_decomposition_pattern(self) -> None:
        """Test O-Researcher (multi-agent decomposition)."""
        # The planner acts as decomposition agent
        planner = ResearchPlanner()

        complex_query = (
            "Compare water availability trends across different Florida aquifer systems"
        )

        plan = planner.plan_research(complex_query)

        # Should decompose into research areas
        assert len(plan.research_areas) > 0

        # Each area becomes its own sub-research
        assert len(plan.sub_questions) >= len(plan.research_areas)

        # Should have structured report expectations
        assert len(plan.expected_sections) > 0


if __name__ == "__main__":
    # Quick test run
    pytest.main([__file__, "-v"])
