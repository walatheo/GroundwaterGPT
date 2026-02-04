"""Tests for the AI chat API endpoint.

These tests verify the rule-based chat system responds correctly
to various groundwater and agriculture queries.
"""

import sys
from pathlib import Path

import pytest

# Add api directory to path for imports (must be before main import)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "api"))

from main import GROUNDWATER_KB, get_site_context, simple_ai_response  # noqa: E402


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


class TestSimpleAIResponse:
    """Test the rule-based AI response system."""

    def test_irrigation_query(self):
        """Test response to irrigation question."""
        response = simple_ai_response("How should I plan irrigation for my farm?")
        assert "response" in response
        assert (
            "irrigation" in response["response"].lower() or "water" in response["response"].lower()
        )

    def test_crop_query(self):
        """Test response to crop-related question."""
        response = simple_ai_response("What water depth is good for citrus trees?")
        assert "response" in response
        assert "citrus" in response["response"].lower() or "crop" in response["response"].lower()

    def test_aquifer_query(self):
        """Test response to aquifer question."""
        response = simple_ai_response("Tell me about the Floridan aquifer")
        assert "response" in response
        assert (
            "floridan" in response["response"].lower() or "aquifer" in response["response"].lower()
        )

    def test_seasonal_query(self):
        """Test response to seasonal patterns question."""
        response = simple_ai_response("How do water levels change in dry season?")
        assert "response" in response
        assert "season" in response["response"].lower() or "wet" in response["response"].lower()

    def test_unknown_query_returns_help(self):
        """Test that unknown queries return helpful guidance."""
        response = simple_ai_response("Tell me about quantum physics")
        assert "response" in response
        assert (
            "help" in response["response"].lower() or "irrigation" in response["response"].lower()
        )

    def test_response_has_sources(self):
        """Verify responses include source attribution."""
        response = simple_ai_response("What about saltwater intrusion?")
        assert "sources" in response
        assert isinstance(response["sources"], list)

    def test_response_has_beta_status(self):
        """Verify responses indicate beta status."""
        response = simple_ai_response("irrigation planning")
        assert response.get("status") == "beta"

    def test_county_context_extraction(self):
        """Test that county mentions are detected."""
        response = simple_ai_response("What about wells in Lee County?")
        # Should mention available sites or county context
        assert "response" in response


class TestSiteContext:
    """Test the site context generation."""

    def test_get_site_context_without_county(self):
        """Test context generation without county filter."""
        context = get_site_context()
        assert "Monitoring" in context or "sites" in context.lower()

    def test_get_site_context_with_valid_county(self):
        """Test context generation with valid county."""
        context = get_site_context("Miami-Dade")
        assert "Miami-Dade" in context or "sites" in context.lower()


class TestFarmerUseCases:
    """Test specific farmer/agriculture use cases."""

    def test_farmer_soil_moisture_query(self):
        """Farmer asking about soil moisture."""
        response = simple_ai_response("Is my soil too wet for planting vegetables?")
        assert "response" in response
        # Should match soil_moisture or irrigation topic
        assert len(response["response"]) > 20

    def test_farmer_crop_selection(self):
        """Farmer asking which crops suit water table."""
        response = simple_ai_response("Which vegetables can grow with shallow water table?")
        assert "response" in response

    def test_farmer_well_planning(self):
        """Farmer asking about well installation."""
        response = simple_ai_response("How deep should I drill my irrigation well?")
        assert "response" in response
        assert "well" in response["response"].lower() or "depth" in response["response"].lower()

    def test_farmer_seasonal_planning(self):
        """Farmer asking about seasonal water availability."""
        response = simple_ai_response("When is the best time to plant considering groundwater?")
        assert "response" in response


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
