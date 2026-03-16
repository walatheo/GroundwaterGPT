"""Tests for GroundwaterAgent and DeepResearchAgent.

Uses a mock LLM so tests run without Ollama / API keys.
Validates agent construction, tool wiring, intent detection,
fallback paths, and research agent control flow.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.agent.groundwater_agent import SYSTEM_PROMPT, GroundwaterAgent, create_agent  # noqa: E402
from src.agent.llm_factory import LLMProvider  # noqa: E402
from src.agent.research_agent import (  # noqa: E402
    DeepResearchAgent,
    ResearchContext,
    ResearchInsight,
    _llm_invoke_with_retry,
)

# ===================================================================
# Helpers — mock LLM
# ===================================================================


def _mock_llm():
    """Return a mock LLM that always responds with a fixed string."""
    llm = MagicMock()
    resp = MagicMock()
    resp.content = "Mock LLM response about groundwater levels."
    llm.invoke.return_value = resp
    llm.stream.return_value = iter([resp])
    return llm


# ===================================================================
# SYSTEM_PROMPT checks
# ===================================================================


class TestSystemPrompt:
    """Validate the system prompt covers critical aspects."""

    def test_mentions_tools(self):
        """System prompt lists key tools."""
        assert "list_available_sites" in SYSTEM_PROMPT
        assert "query_site_data" in SYSTEM_PROMPT

    def test_mentions_workflow(self):
        """System prompt describes the expected workflow."""
        assert "Workflow" in SYSTEM_PROMPT

    def test_mentions_aquifers(self):
        """System prompt mentions Florida aquifer systems."""
        assert "Biscayne" in SYSTEM_PROMPT
        assert "Floridan" in SYSTEM_PROMPT


# ===================================================================
# GroundwaterAgent construction
# ===================================================================


class TestAgentConstruction:
    """Test agent initialization with mock LLM."""

    @patch("src.agent.groundwater_agent.get_llm")
    @patch("src.agent.groundwater_agent.create_react_agent")
    def test_creates_with_react(self, mock_react, mock_get_llm):
        """Agent creates a ReAct agent by default."""
        mock_get_llm.return_value = _mock_llm()
        mock_react.return_value = MagicMock()

        agent = GroundwaterAgent(use_react=True)
        assert agent.agent is not None
        mock_react.assert_called_once()

    @patch("src.agent.groundwater_agent.get_llm")
    def test_creates_without_react(self, mock_get_llm):
        """Agent can be created in simple mode."""
        mock_get_llm.return_value = _mock_llm()

        agent = GroundwaterAgent(use_react=False)
        assert agent.agent is None

    @patch("src.agent.groundwater_agent.get_llm")
    def test_has_all_tools(self, mock_get_llm):
        """Agent includes all GROUNDWATER_TOOLS + search_hydrogeology_docs."""
        mock_get_llm.return_value = _mock_llm()

        agent = GroundwaterAgent(use_react=False)
        names = {t.name for t in agent.tools}
        assert "query_site_data" in names
        assert "list_available_sites" in names
        assert "create_research_experiment_plan" in names
        assert "log_experiment_run" in names
        assert "draft_research_paper" in names
        assert "search_hydrogeology_docs" in names
        # Should have 13 registered tools + 1 doc search = 14
        assert len(agent.tools) == 14

    @patch("src.agent.groundwater_agent.get_llm")
    def test_factory_function(self, mock_get_llm):
        """create_agent() returns a GroundwaterAgent."""
        mock_get_llm.return_value = _mock_llm()

        agent = create_agent(use_react=False)
        assert isinstance(agent, GroundwaterAgent)


# ===================================================================
# Intent detection
# ===================================================================


class TestIntentDetection:
    """Test _detect_intent keyword matching."""

    @patch("src.agent.groundwater_agent.get_llm")
    def _agent(self, mock_get_llm):
        mock_get_llm.return_value = _mock_llm()
        return GroundwaterAgent(use_react=False)

    def test_prediction_intent(self):
        """Prediction keywords detected."""
        agent = self._agent()
        assert agent._detect_intent("predict levels next week") == "prediction"

    def test_seasonal_intent(self):
        """Seasonal keywords detected."""
        agent = self._agent()
        assert agent._detect_intent("wet season patterns") == "seasonal"

    def test_anomaly_intent(self):
        """Anomaly keywords detected."""
        agent = self._agent()
        assert agent._detect_intent("unusual outlier events") == "anomaly"

    def test_quality_intent(self):
        """Quality keywords detected."""
        agent = self._agent()
        assert agent._detect_intent("data quality coverage") == "quality"

    def test_knowledge_intent(self):
        """Knowledge keywords detected."""
        agent = self._agent()
        assert agent._detect_intent("what is an aquifer") == "knowledge"

    def test_default_data_intent(self):
        """Unrecognised query falls back to 'data'."""
        agent = self._agent()
        assert agent._detect_intent("hello world") == "data"


# ===================================================================
# Simple chat path
# ===================================================================


class TestSimpleChat:
    """Test the _chat_simple path (no ReAct)."""

    @patch("src.agent.groundwater_agent.get_llm")
    def test_chat_returns_string(self, mock_get_llm):
        """Simple chat returns the LLM response content."""
        mock_get_llm.return_value = _mock_llm()
        agent = GroundwaterAgent(use_react=False)
        response = agent.chat("What is the current water level?")
        assert isinstance(response, str)
        assert len(response) > 0

    @patch("src.agent.groundwater_agent.get_llm")
    def test_chat_updates_history(self, mock_get_llm):
        """Chat appends to chat_history."""
        mock_get_llm.return_value = _mock_llm()
        agent = GroundwaterAgent(use_react=False)
        agent.chat("test message")
        assert len(agent.chat_history) == 2  # Human + AI

    @patch("src.agent.groundwater_agent.get_llm")
    def test_clear_history(self, mock_get_llm):
        """clear_history empties the list."""
        mock_get_llm.return_value = _mock_llm()
        agent = GroundwaterAgent(use_react=False)
        agent.chat("test")
        agent.clear_history()
        assert len(agent.chat_history) == 0


# ===================================================================
# LLM retry helper
# ===================================================================


class TestLlmRetry:
    """Test _llm_invoke_with_retry logic."""

    def test_success_first_try(self):
        """Returns content on first successful call."""
        llm = _mock_llm()
        result = _llm_invoke_with_retry(llm, "test", retries=0)
        assert result == "Mock LLM response about groundwater levels."

    def test_retries_on_failure(self):
        """Retries on transient failure, then succeeds."""
        llm = MagicMock()
        resp = MagicMock()
        resp.content = "success"
        llm.invoke.side_effect = [
            RuntimeError("transient"),
            resp,
        ]
        result = _llm_invoke_with_retry(llm, "test", retries=1)
        assert result == "success"
        assert llm.invoke.call_count == 2

    def test_raises_after_exhausted_retries(self):
        """Raises after all retries are exhausted."""
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("persistent")
        with pytest.raises(RuntimeError, match="persistent"):
            _llm_invoke_with_retry(llm, "test", retries=1)
        assert llm.invoke.call_count == 2


# ===================================================================
# ResearchContext
# ===================================================================


class TestResearchContext:
    """Test ResearchContext control flow."""

    def test_should_continue(self):
        """Context allows continuation within limits."""
        ctx = ResearchContext(
            original_query="test",
            current_query="test",
            max_depth=3,
            timeout_seconds=60,
        )
        assert ctx.should_continue() is True

    def test_stop_requested(self):
        """request_stop terminates the loop."""
        ctx = ResearchContext(
            original_query="test",
            current_query="test",
            max_depth=3,
            timeout_seconds=60,
        )
        ctx.request_stop()
        assert ctx.is_stopped() is True

    def test_add_insight(self):
        """Insights accumulate."""
        ctx = ResearchContext(
            original_query="test",
            current_query="test",
            max_depth=3,
            timeout_seconds=60,
        )
        insight = ResearchInsight(
            content="test insight",
            source_url="http://example.com",
            confidence=0.8,
            verified=True,
            trust_level="verified",
        )
        ctx.add_insight(insight)
        assert len(ctx.insights) == 1


# ===================================================================
# DeepResearchAgent construction
# ===================================================================


class TestResearchAgentConstruction:
    """Test DeepResearchAgent init."""

    @patch("src.agent.research_agent.get_llm")
    def test_creates_successfully(self, mock_get_llm):
        """Agent constructs without error."""
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(
            max_depth=2,
            timeout_seconds=30,
            use_web_search=False,
        )
        assert agent.max_depth == 2
        assert agent.timeout_seconds == 30

    @patch("src.agent.research_agent.get_llm")
    def test_status_when_idle(self, mock_get_llm):
        """Status returns idle when not running."""
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False)
        status = agent.get_status()
        assert status["running"] is False
        assert status["status"] == "idle"

    @patch("src.agent.research_agent.get_llm")
    def test_stop_when_idle(self, mock_get_llm):
        """Stop returns False when nothing is running."""
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False)
        assert agent.stop() is False


class TestResearchSectionConfidence:
    """Test section-level confidence/trust aggregation for research output."""

    @patch("src.agent.research_agent.get_llm")
    def test_build_section_confidence(self, mock_get_llm):
        """Section metadata should include per-section + overall confidence/trust."""
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False)
        insights = [
            ResearchInsight(
                content="Insight A",
                source_url="https://example.com/a",
                confidence=0.9,
                verified=True,
                trust_level="verified",
            ),
            ResearchInsight(
                content="Insight B",
                source_url="https://example.com/b",
                confidence=0.5,
                verified=True,
                trust_level="moderate",
            ),
        ]
        section_data = agent._build_section_confidence(insights)
        assert "sections" in section_data
        assert "overall_confidence" in section_data
        assert "overall_trust_level" in section_data
        assert len(section_data["sections"]) == 2


class TestClaimVerdicts:
    """Test claim-level disagreement verdict generation in research outputs."""

    @patch("src.agent.research_agent.get_llm")
    def test_research_returns_claim_verdicts(self, mock_get_llm, monkeypatch):
        """Research result should include claim_verdicts aligned with claim_citations."""
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False, auto_learn=False)

        def _fake_graph(context):
            context.insights.append(
                ResearchInsight(
                    content="USGS site 262724081260701 shows a declining groundwater trend.",
                    source_url="https://waterdata.usgs.gov/monitoring-location/262724081260701",
                    confidence=0.85,
                    verified=True,
                    trust_level="verified",
                )
            )
            context.current_depth = 1

        monkeypatch.setattr(agent, "_research_graph", _fake_graph)
        monkeypatch.setattr(
            agent,
            "_synthesize_report",
            lambda _context, _claims: (
                "USGS site 262724081260701 shows a declining groundwater trend [claim_001]."
            ),
        )

        result = agent.research("Test research question", max_depth=1, timeout=30)
        assert "claim_citations" in result
        assert "claim_verdicts" in result
        assert "claim_verdict_summary" in result
        assert len(result["claim_verdicts"]) == len(result["claim_citations"])
        assert result["claim_verdicts"][0]["verdict"] in (
            "supported",
            "contradicted",
            "insufficient_evidence",
        )
        summary = result["claim_verdict_summary"]
        assert summary["total_claims"] == len(result["claim_verdicts"])


class TestHallucinationGuardrail:
    """Test uncited factual claim filtering in synthesized reports."""

    @patch("src.agent.research_agent.get_llm")
    def test_strip_uncited_factual_sentences(self, mock_get_llm):
        """Factual sentences without claim references should be removed."""
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False)
        report = (
            "Groundwater declined by 2.3 ft in 2024. "
            "This suggests pressure on aquifer storage [claim_001]."
        )
        cleaned, removed = agent._strip_uncited_factual_sentences(report)
        assert removed >= 1
        assert "[claim_001]" in cleaned


# ===================================================================
# LLM Factory
# ===================================================================


class TestLlmFactory:
    """Test llm_factory.py enums and config."""

    def test_providers_enum(self):
        """LLMProvider has expected members."""
        assert LLMProvider.OLLAMA.value == "ollama"
        assert LLMProvider.OPENAI.value == "openai"
        assert LLMProvider.ANTHROPIC.value == "anthropic"
        assert LLMProvider.GEMINI.value == "gemini"
