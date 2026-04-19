"""Tests for DeepResearchAgent and related helpers.

Uses a mock LLM so tests run without local model runtimes or API keys.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.agent.llm_factory import LLMProvider  # noqa: E402
from src.agent.research_agent import DeepResearchAgent  # noqa: E402
from src.agent.research_agent import (  # noqa: E402
    ResearchContext,
    ResearchInsight,
    _llm_invoke_with_retry,
)


def _mock_llm():
    """Return a mock LLM that always responds with a fixed string."""
    llm = MagicMock()
    resp = MagicMock()
    resp.content = "Mock LLM response about groundwater levels."
    llm.invoke.return_value = resp
    llm.stream.return_value = iter([resp])
    return llm


class TestLlmRetry:
    """Test _llm_invoke_with_retry logic."""

    def test_success_first_try(self):
        llm = _mock_llm()
        result = _llm_invoke_with_retry(llm, "test", retries=0)
        assert result == "Mock LLM response about groundwater levels."

    def test_retries_on_failure(self):
        llm = MagicMock()
        resp = MagicMock()
        resp.content = "success"
        llm.invoke.side_effect = [RuntimeError("transient"), resp]
        result = _llm_invoke_with_retry(llm, "test", retries=1)
        assert result == "success"
        assert llm.invoke.call_count == 2

    def test_raises_after_exhausted_retries(self):
        llm = MagicMock()
        llm.invoke.side_effect = RuntimeError("persistent")
        with pytest.raises(RuntimeError, match="persistent"):
            _llm_invoke_with_retry(llm, "test", retries=1)
        assert llm.invoke.call_count == 2


class TestResearchContext:
    """Test ResearchContext control flow."""

    def test_should_continue(self):
        ctx = ResearchContext(
            original_query="test",
            current_query="test",
            max_depth=3,
            timeout_seconds=60,
        )
        assert ctx.should_continue() is True

    def test_stop_requested(self):
        ctx = ResearchContext(
            original_query="test",
            current_query="test",
            max_depth=3,
            timeout_seconds=60,
        )
        ctx.request_stop()
        assert ctx.is_stopped() is True

    def test_add_insight(self):
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


class TestResearchAgentConstruction:
    """Test DeepResearchAgent init."""

    @patch("src.agent.research_agent.get_llm")
    def test_creates_successfully(self, mock_get_llm):
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
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False)
        status = agent.get_status()
        assert status["running"] is False
        assert status["status"] == "idle"

    @patch("src.agent.research_agent.get_llm")
    def test_stop_when_idle(self, mock_get_llm):
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False)
        assert agent.stop() is False


class TestResearchSectionConfidence:
    """Test section-level confidence/trust aggregation for research output."""

    @patch("src.agent.research_agent.get_llm")
    def test_build_section_confidence(self, mock_get_llm):
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


class TestStructuredResearchSynthesis:
    """Test evidence-ID structured response helpers."""

    @patch("src.agent.research_agent.get_llm")
    def test_structured_response_renders_evidence_ids(self, mock_get_llm):
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False)
        insights = [
            ResearchInsight(
                content="USGS site 262724081260701 shows a monitored groundwater trend.",
                source_url="https://waterdata.usgs.gov/monitoring-location/262724081260701",
                confidence=0.85,
                verified=True,
                trust_level="verified",
            )
        ]
        claims, _summary = agent._build_claim_citations(insights)
        evidence = agent._build_evidence_items(claims)
        structured = agent._heuristic_structured_response(
            "What does the well show?",
            claims,
            [],
            evidence,
        )
        report = agent._render_structured_report(structured)

        assert structured["schema_version"] == "evidence_response_v1"
        assert structured["claims"][0]["claim_ids"] == ["claim_001"]
        assert structured["claims"][0]["evidence_ids"] == ["evidence_001_source_1"]
        assert "[claim_001" in report
        assert "evidence_001_source_1" in report

    @patch("src.agent.research_agent.get_llm")
    def test_parse_structured_response_dedupes_and_drops_invalid_claims(self, mock_get_llm):
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False)
        claim_citations = [
            {
                "claim_id": "claim_001",
                "claim": "A cited groundwater trend claim.",
                "confidence": 0.9,
                "citations": [
                    {
                        "evidence_id": "evidence_001_source_1",
                        "url": "https://example.com/usgs",
                        "verified": True,
                        "trust_level": "verified",
                    }
                ],
            }
        ]
        evidence_items = agent._build_evidence_items(claim_citations)
        parsed = agent._parse_structured_response(
            raw_response="""
            {
              "answer": "  Parsed answer  ",
              "claims": [
                {
                  "claim": "  A cited groundwater trend claim.  ",
                  "claim_type": "trend",
                  "claim_ids": ["claim_001", "claim_001", "claim_999"],
                  "evidence_ids": ["evidence_001_source_1", "evidence_001_source_1"],
                  "confidence": "0.95",
                  "uncertainty": "  bounded  "
                },
                {
                  "claim": "",
                  "claim_ids": ["claim_999"],
                  "evidence_ids": ["evidence_999_source_1"]
                }
              ],
              "limitations": [" one ", "one", ""],
              "recommended_followup": [" next step ", ""]
            }
            """,
            question="Test question",
            claim_citations=claim_citations,
            claim_verdicts=[],
            evidence_items=evidence_items,
        )

        assert parsed["answer"] == "Parsed answer"
        assert len(parsed["claims"]) == 1
        assert parsed["claims"][0]["claim_ids"] == ["claim_001"]
        assert parsed["claims"][0]["evidence_ids"] == ["evidence_001_source_1"]
        assert parsed["claims"][0]["uncertainty"] == "bounded"


class TestClaimVerdicts:
    """Test claim-level disagreement verdict generation in research outputs."""

    @patch("src.agent.research_agent.get_llm")
    def test_research_returns_claim_verdicts(self, mock_get_llm, monkeypatch):
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
            lambda _context, _claims, _verdicts=None: (
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
        mock_get_llm.return_value = _mock_llm()
        agent = DeepResearchAgent(use_web_search=False)
        report = (
            "Groundwater declined by 2.3 ft in 2024. "
            "This suggests pressure on aquifer storage [claim_001]."
        )
        cleaned, removed = agent._strip_uncited_factual_sentences(report)
        assert removed >= 1
        assert "[claim_001]" in cleaned


class TestLlmFactory:
    """Test llm_factory.py enums and config."""

    def test_providers_enum(self):
        assert LLMProvider.OLLAMA.value == "ollama"
        assert LLMProvider.QWEN.value == "qwen"
        # Anthropic / OpenAI / Gemini were removed — Qwen-only by policy.
        assert not hasattr(LLMProvider, "ANTHROPIC")
        assert not hasattr(LLMProvider, "OPENAI")
        assert not hasattr(LLMProvider, "GEMINI")
