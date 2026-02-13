"""Tests for the AI chat API endpoint.

Session 7 — Agent ↔ API Integration tests.
Validates:
 • Rule-based fallback KB structure and matching
 • POST /api/chat  (agent + fallback path)
 • POST /api/research (deep research + fallback path)
 • GET  /api/chat/status
 • Input validation (empty / missing fields → 400)
"""

import sys
from pathlib import Path

import pytest

# Add api directory to path for imports (must be before main import)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))

# FastAPI test client — avoids starting a real server
from fastapi.testclient import TestClient  # noqa: E402

from main import GROUNDWATER_KB, _fallback_response, _get_site_context, app  # noqa: E402

client = TestClient(app)


# ===================================================================
# Knowledge Base unit tests
# ===================================================================


class TestGroundwaterKnowledgeBase:
    """Test the groundwater knowledge base structure."""

    def test_kb_has_required_topics(self):
        """Verify KB contains essential groundwater topics."""
        required_topics = ["irrigation", "crops", "aquifer", "seasonal", "well"]
        for topic in required_topics:
            assert topic in GROUNDWATER_KB, f"Missing KB topic: {topic}"

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
