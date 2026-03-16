"""Tests for the AI chat API endpoint.

Session 7 — Agent ↔ API Integration tests.
Validates:
 • Rule-based fallback KB structure and matching
 • POST /api/chat  (agent + fallback path)
 • POST /api/research (deep research + fallback path)
 • GET  /api/chat/status
 • Input validation (empty / missing fields → 400)
"""

import re
import sys
from pathlib import Path

import pytest

# Add project root to path so ``api`` package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# FastAPI test client — avoids starting a real server
from fastapi.testclient import TestClient  # noqa: E402

from api.main import GROUNDWATER_KB, _fallback_response, _get_site_context, app  # noqa: E402

client = TestClient(app)


# ===================================================================
# Knowledge Base unit tests
# ===================================================================


class TestGroundwaterKnowledgeBase:
    """Test the groundwater knowledge base structure."""

    def test_kb_has_required_topics(self):
        """Verify KB contains essential groundwater topics."""
        required_topics = [
            "irrigation",
            "crops",
            "aquifer",
            "seasonal",
            "well",
            "drought_resilience",
            "fertigation",
            "frost_protection",
        ]
        for topic in required_topics:
            assert topic in GROUNDWATER_KB, f"Missing KB topic: {topic}"

    def test_kb_has_at_least_ten_topics(self):
        """Farmer KB should maintain at least 10 topic entries."""
        assert len(GROUNDWATER_KB) >= 10

    def test_kb_entries_have_keywords(self):
        """Verify each KB entry has keywords for matching."""
        for topic, data in GROUNDWATER_KB.items():
            assert "keywords" in data, f"Topic '{topic}' missing keywords"
            assert len(data["keywords"]) > 0, f"Topic '{topic}' has no keywords"

    def test_kb_entries_have_info(self):
        """Verify each KB entry has information content."""
        for topic, data in GROUNDWATER_KB.items():
            assert "info" in data, f"Topic '{topic}' missing info"
            assert len(data["info"]) > 50, f"Topic '{topic}' info too short"


# ===================================================================
# Fallback response unit tests
# ===================================================================


class TestFallbackResponse:
    """Test the rule-based fallback response system."""

    def test_irrigation_query(self):
        """Test response to irrigation question."""
        response = _fallback_response("How should I plan irrigation for my farm?")
        assert "response" in response
        assert (
            "irrigation" in response["response"].lower() or "water" in response["response"].lower()
        )

    def test_crop_query(self):
        """Test response to crop-related question."""
        response = _fallback_response("What water depth is good for citrus trees?")
        assert "response" in response
        assert "citrus" in response["response"].lower() or "crop" in response["response"].lower()

    def test_aquifer_query(self):
        """Test response to aquifer question."""
        response = _fallback_response("Tell me about the Floridan aquifer")
        assert "response" in response
        assert (
            "floridan" in response["response"].lower() or "aquifer" in response["response"].lower()
        )

    def test_seasonal_query(self):
        """Test response to seasonal patterns question."""
        response = _fallback_response("How do water levels change in dry season?")
        assert "response" in response
        assert "season" in response["response"].lower() or "wet" in response["response"].lower()

    def test_unknown_query_returns_help(self):
        """Test that unknown queries return helpful guidance."""
        response = _fallback_response("Tell me about quantum physics")
        assert "response" in response
        assert (
            "help" in response["response"].lower() or "irrigation" in response["response"].lower()
        )

    def test_response_has_sources(self):
        """Verify responses include source attribution."""
        response = _fallback_response("What about saltwater intrusion?")
        assert "sources" in response
        assert isinstance(response["sources"], list)

    def test_response_has_mode_field(self):
        """Verify responses include mode indicator."""
        response = _fallback_response("irrigation planning")
        assert response.get("mode") == "fallback"
        assert response.get("status") == "ok"

    def test_county_context_extraction(self):
        """Test that county mentions are detected in context."""
        response = _fallback_response("What about wells in Lee County?")
        assert "response" in response
        assert "context" in response


# ===================================================================
# Site context unit tests
# ===================================================================


class TestSiteContext:
    """Test the site context generation."""

    def test_get_site_context_without_county(self):
        """Test context generation without county filter."""
        context = _get_site_context()
        assert "Monitoring" in context or "sites" in context.lower()

    def test_get_site_context_with_valid_county(self):
        """Test context generation with valid county."""
        context = _get_site_context("Miami-Dade")
        assert "Miami-Dade" in context or "sites" in context.lower()


# ===================================================================
# POST /api/chat  endpoint integration tests
# ===================================================================


class TestChatEndpoint:
    """Integration tests for the POST /api/chat endpoint."""

    def test_chat_returns_200(self):
        """Basic chat request returns 200 with expected fields."""
        resp = client.post("/api/chat", json={"message": "Tell me about irrigation"})
        assert resp.status_code == 200
        body = resp.json()
        assert "response" in body
        assert "sources" in body
        assert "mode" in body
        assert body["mode"] in ("agent", "fallback")

    def test_chat_empty_message_returns_400(self):
        """Empty message string must return 400."""
        resp = client.post("/api/chat", json={"message": ""})
        assert resp.status_code == 400

    def test_chat_missing_message_returns_400(self):
        """Missing 'message' key must return 400."""
        resp = client.post("/api/chat", json={"unrelated": "data"})
        assert resp.status_code == 400

    def test_chat_irrigation_content(self):
        """Chat response to irrigation query should mention water/irrigation."""
        resp = client.post("/api/chat", json={"message": "How should I plan irrigation?"})
        body = resp.json()
        text = body["response"].lower()
        assert "irrigation" in text or "water" in text

    def test_chat_sources_is_list(self):
        """Sources field should always be a list."""
        resp = client.post("/api/chat", json={"message": "aquifer info"})
        body = resp.json()
        assert isinstance(body["sources"], list)


# ===================================================================
# POST /api/research  endpoint integration tests
# ===================================================================


class TestResearchEndpoint:
    """Integration tests for the POST /api/research endpoint."""

    def test_research_returns_200(self):
        """Basic research request returns 200 with expected fields."""
        resp = client.post(
            "/api/research",
            json={"question": "Saltwater intrusion trends in Miami-Dade"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "report" in body
        assert "insights" in body
        assert "sources" in body
        assert "mode" in body
        assert body["mode"] in ("deep_research", "fallback")

    def test_research_empty_question_returns_400(self):
        """Empty question string must return 400."""
        resp = client.post("/api/research", json={"question": ""})
        assert resp.status_code == 400

    def test_research_missing_question_returns_400(self):
        """Missing 'question' key must return 400."""
        resp = client.post("/api/research", json={"topic": "something"})
        assert resp.status_code == 400

    def test_research_optional_params(self):
        """Optional max_depth and timeout should be accepted."""
        resp = client.post(
            "/api/research",
            json={"question": "aquifer recharge", "max_depth": 2, "timeout": 30},
        )
        assert resp.status_code == 200

    def test_research_has_structural_fields(self):
        """Response should contain structural report fields."""
        resp = client.post(
            "/api/research",
            json={"question": "seasonal water patterns in Lee County"},
        )
        body = resp.json()
        assert "search_history" in body
        assert "depth_reached" in body
        assert "elapsed_seconds" in body
        assert "claim_citations" in body
        assert "claim_verdicts" in body
        assert "claim_verdict_summary" in body
        assert "citation_summary" in body
        assert "section_confidence" in body
        assert "hallucination_guardrail" in body
        assert "citation_integrity" in body
        assert isinstance(body["claim_citations"], list)
        assert isinstance(body["claim_verdicts"], list)
        assert isinstance(body["claim_verdict_summary"], dict)
        assert isinstance(body["citation_summary"], dict)
        assert isinstance(body["section_confidence"], dict)
        assert isinstance(body["hallucination_guardrail"], dict)
        assert isinstance(body["citation_integrity"], dict)

    def test_research_claim_citation_shape(self):
        """Claim-citation schema should include claim text and citations list."""
        resp = client.post(
            "/api/research",
            json={"question": "Groundwater trends in Estero over 30 years"},
        )
        assert resp.status_code == 200
        body = resp.json()
        claims = body.get("claim_citations", [])
        if claims:
            first = claims[0]
            assert "claim_id" in first
            assert "claim" in first
            assert "citations" in first
            assert isinstance(first["citations"], list)
        summary = body.get("citation_summary", {})
        assert "total_claims" in summary
        assert "cited_claims" in summary
        assert "citation_coverage" in summary
        verdicts = body.get("claim_verdicts", [])
        if verdicts:
            first_verdict = verdicts[0]
            assert "claim_id" in first_verdict
            assert "verdict" in first_verdict
            assert "risk_score" in first_verdict
            assert first_verdict["verdict"] in (
                "supported",
                "contradicted",
                "insufficient_evidence",
            )
        verdict_summary = body.get("claim_verdict_summary", {})
        assert "total_claims" in verdict_summary
        assert "supported_claims" in verdict_summary
        assert "contradicted_claims" in verdict_summary
        assert "high_risk_claim_rate" in verdict_summary
        integrity = body.get("citation_integrity", {})
        assert "claim_citation_coverage" in integrity
        assert "section_citation_coverage" in integrity
        assert "passed" in integrity

    def test_research_estero_benchmark_fields(self):
        """Estero benchmark query should include reproducible IDs, dates, and citations."""
        resp = client.post(
            "/api/research",
            json={
                "question": (
                    "What has been the change in groundwater level in Estero "
                    "over the last 30 years?"
                )
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        combined = f"{body.get('report', '')}\n" + "\n".join(
            str(s) for s in body.get("sources", [])
        )

        assert re.search(r"\b\d{15}\b", combined)
        assert re.search(r"\b\d{4}-\d{2}-\d{2}\b", combined)
        assert "usgs" in combined.lower()
        assert body.get("citation_summary", {}).get("citation_coverage", 0) >= 0.9
        assert body.get("citation_integrity", {}).get("passed", False) is True


# ===================================================================
# GET /api/chat/status  endpoint tests
# ===================================================================


class TestChatStatus:
    """Tests for the GET /api/chat/status endpoint."""

    def test_status_returns_200(self):
        """Status endpoint should always return 200."""
        resp = client.get("/api/chat/status")
        assert resp.status_code == 200

    def test_status_has_required_keys(self):
        """Status response must include expected keys."""
        body = client.get("/api/chat/status").json()
        assert "status" in body
        assert "version" in body
        assert "agent_available" in body
        assert "research_available" in body
        assert "features" in body
        assert "degraded_reasons" in body
        assert "runtime_checks" in body
        assert body["status"] in ("ok", "fallback")

    def test_status_agent_flags_are_bool(self):
        """agent_available and research_available must be booleans."""
        body = client.get("/api/chat/status").json()
        assert isinstance(body["agent_available"], bool)
        assert isinstance(body["research_available"], bool)

    def test_status_features_is_list(self):
        """Features field should be a non-empty list of strings."""
        body = client.get("/api/chat/status").json()
        assert isinstance(body["features"], list)
        assert len(body["features"]) > 0
        assert all(isinstance(f, str) for f in body["features"])

    def test_status_degraded_reasons_and_runtime_checks_shape(self):
        """Degraded reasons and runtime checks should always have stable shape."""
        body = client.get("/api/chat/status").json()
        assert isinstance(body["degraded_reasons"], list)
        assert isinstance(body["runtime_checks"], dict)
        checks = body["runtime_checks"]
        assert "skip_agent_init" in checks
        assert "web_search_enabled" in checks
        assert "last_chat_error" in checks
        assert "last_research_error" in checks

    def test_status_tracks_latest_chat_runtime_error(self, monkeypatch):
        """chat/status should expose latest chat runtime error metadata."""
        from api.routes import chat as chat_routes

        class _BoomAgent:
            def chat(self, _query):
                raise RuntimeError("simulated chat failure")

        monkeypatch.setattr(chat_routes, "_chat_agent", _BoomAgent())
        resp = client.post("/api/chat", json={"message": "test runtime failure path"})
        assert resp.status_code == 200
        body = client.get("/api/chat/status").json()
        last_error = body["runtime_checks"]["last_chat_error"]
        assert isinstance(last_error, dict)
        assert "simulated chat failure" in str(last_error.get("message", ""))


# ===================================================================
# Farmer use-case tests (via /api/chat)
# ===================================================================


class TestFarmerUseCases:
    """Test specific farmer/agriculture use cases through the API."""

    def test_farmer_soil_moisture_query(self):
        """Farmer asking about soil moisture."""
        resp = client.post(
            "/api/chat",
            json={"message": "Is my soil too wet for planting vegetables?"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["response"]) > 20

    def test_farmer_crop_selection(self):
        """Farmer asking which crops suit water table."""
        resp = client.post(
            "/api/chat",
            json={"message": "Which vegetables can grow with shallow water table?"},
        )
        assert resp.status_code == 200

    def test_farmer_well_planning(self):
        """Farmer asking about well installation."""
        resp = client.post(
            "/api/chat",
            json={"message": "How deep should I drill my irrigation well?"},
        )
        body = resp.json()
        text = body["response"].lower()
        assert "well" in text or "depth" in text

    def test_farmer_seasonal_planning(self):
        """Farmer asking about seasonal water availability."""
        resp = client.post(
            "/api/chat",
            json={"message": "When is the best time to plant considering groundwater?"},
        )
        assert resp.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
