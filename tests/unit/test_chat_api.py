"""Tests for the AI chat API endpoint.

Session 7 — Agent ↔ API Integration tests.
Validates:
 • Rule-based fallback KB structure and matching
 • POST /api/chat  (research-assisted + fallback path)
 • POST /api/research (deep research + fallback path)
 • GET  /api/chat/status
 • Input validation (empty / missing fields → 400)
"""

import json
import re
import sys
from pathlib import Path

import pytest

# Add project root to path so ``api`` package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# FastAPI test client — avoids starting a real server
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from api.routes.chat import GROUNDWATER_KB, _fallback_response, _get_site_context  # noqa: E402

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

    def setup_method(self):
        from api.routes import chat as chat_routes

        chat_routes._CHAT_CACHE.clear()

    def test_chat_returns_200(self):
        """Basic chat request returns 200 with expected fields."""
        resp = client.post("/api/chat", json={"message": "Tell me about irrigation"})
        assert resp.status_code == 200
        body = resp.json()
        assert "response" in body
        assert "sources" in body
        assert "mode" in body
        assert body["mode"] in ("research_chat", "fallback")

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

    def test_chat_site_fallback_has_citation_integrity(self):
        """Deterministic chat responses should forward citation integrity."""
        resp = client.post("/api/chat", json={"message": "Estero trends"})
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("mode") == "site_fallback"
        assert "hallucination_guardrail" in body
        assert "citation_integrity" in body
        assert isinstance(body["citation_integrity"], dict)
        assert "passed" in body["citation_integrity"]

    def test_chat_supply_question_returns_brief_and_evidence_report(self):
        """Supply/source prompts should get a natural-language brief, not only a data dump."""
        resp = client.post(
            "/api/chat",
            json={
                "message": (
                    "What are the groundwater sources the Village of Estero uses for "
                    "water supply and what have been changes in groundwater levels "
                    "there over the last 30 years?"
                ),
                "allow_llm_synthesis": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        brief = body.get("answer_brief", "")
        raw_report = body.get("raw_report", "")
        supply = (body.get("interpretation_details") or {}).get("supply_interpretation")

        assert brief
        assert raw_report
        assert len(brief) < len(raw_report)
        assert "Village of Estero" in brief
        assert "Sand and Shell" in brief
        assert "Hawthorn" in brief
        assert "Floridan" in brief
        assert "proxy" in brief.lower()
        assert supply
        assert len(supply["supply_units"]) >= 3
        assert body.get("next_goal")
        assert body.get("follow_up_groups")

    def test_chat_supply_interpretation_is_not_estero_only(self):
        """The supply brief should use the configured municipality mapping generically."""
        resp = client.post(
            "/api/chat",
            json={
                "message": (
                    "What groundwater sources does Naples use for supply, and how "
                    "are monitored groundwater levels changing?"
                ),
                "allow_llm_synthesis": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        brief = body.get("answer_brief", "")
        supply = (body.get("interpretation_details") or {}).get("supply_interpretation")

        assert "City of Naples" in brief
        assert "Lower Tamiami" in brief
        assert "Floridan" in brief
        assert supply["municipality"] == "City of Naples"
        assert any(unit["zone"] == "Lower Tamiami" for unit in supply["supply_units"])

    def test_chat_kb_query_skips_research_agent_for_fast_fallback(self, monkeypatch):
        """KB-matched chat queries should not invoke the slower research-agent path."""
        from api.routes import chat as chat_routes

        class _BoomAgent:
            def research(self, **_kwargs):
                raise AssertionError("research agent should not be called for KB fast path")

        monkeypatch.setattr(chat_routes, "_research_agent", _BoomAgent())
        resp = client.post(
            "/api/chat",
            json={"message": "When is the best time to plant considering groundwater?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "fallback"

    def test_chat_includes_structured_response_and_provenance(self):
        """Chat responses should expose the same audit fields as research responses."""
        resp = client.post("/api/chat", json={"message": "Estero trends"})
        assert resp.status_code == 200
        body = resp.json()
        assert "structured_response" in body
        assert "provenance" in body
        assert body["structured_response"]["schema_version"] == "evidence_response_v1"
        assert body["provenance"]["schema_version"] == "research_provenance_v1"
        assert body["structured_response"]["question"] == "Estero trends"
        assert "response_sha256" in body["provenance"]

    def test_chat_site_analysis_allows_llm_synthesis_by_default(self, monkeypatch):
        """Chat site-analysis paths must leave hybrid LLM synthesis enabled.

        The benchmark suppresses it via GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS,
        but the live demo path should default to the hybrid hydrogeologist
        narration so the deterministic findings get a natural-language layer.
        """
        from api.routes import chat as chat_routes

        captured: dict[str, object] = {}

        def _fake_site_fallback(*args, **kwargs):
            captured["allow_llm_synthesis"] = kwargs.get("allow_llm_synthesis", True)
            return {
                "report": "Synthetic site analysis",
                "sources": ["https://example.com/usgs"],
                "chart": None,
                "divergent_pairs": [],
                "cohort_risk_level": "low",
                "llm_synthesis": None,
                "hallucination_guardrail": {"all_factual_claims_cited": True},
                "claim_citations": [],
                "section_confidence": {},
            }

        monkeypatch.delenv("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", raising=False)
        monkeypatch.setattr(chat_routes, "_site_research_fallback", _fake_site_fallback)
        resp = client.post(
            "/api/chat",
            json={"message": "Assess Estero groundwater source reliability."},
        )
        assert resp.status_code == 200
        assert captured["allow_llm_synthesis"] is not False

    def test_chat_can_skip_chart_payload_for_fast_text_turns(self, monkeypatch):
        """Fast chat should be able to suppress chart building on ordinary text turns."""
        from api.routes import chat as chat_routes

        captured: dict[str, object] = {}

        def _fake_site_fallback(*args, **kwargs):
            captured["include_chart"] = kwargs.get("include_chart", True)
            return {
                "report": "Synthetic site analysis",
                "sources": ["https://example.com/usgs"],
                "chart": None,
                "divergent_pairs": [],
                "cohort_risk_level": "low",
                "llm_synthesis": None,
                "hallucination_guardrail": {"all_factual_claims_cited": True},
                "claim_citations": [],
                "section_confidence": {},
            }

        monkeypatch.setattr(chat_routes, "_site_research_fallback", _fake_site_fallback)
        resp = client.post(
            "/api/chat",
            json={
                "message": "What is happening at G-3336?",
                "allow_llm_synthesis": False,
                "include_chart": False,
            },
        )
        assert resp.status_code == 200
        assert captured["include_chart"] is False

    def test_chat_typo_aquifer_query_fuzzy_matches(self):
        """Common aquifer misspellings should still route to the right deterministic answer."""
        resp = client.post(
            "/api/chat", json={"message": "Tell me about the Biscanye aquifer trends"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "biscayne" in body["response"].lower()
        assert body["mode"] in {"aquifer_fallback", "fallback"}

    def test_chat_out_of_scope_query_avoids_fake_groundwater_data(self):
        """Out-of-scope locations should return scoped guidance instead of invented measurements."""
        resp = client.post(
            "/api/chat", json={"message": "What are groundwater levels in Antarctica?"}
        )
        assert resp.status_code == 200
        body = resp.json()
        text = body["response"].lower()
        assert "antarctica" in text
        assert "florida" in text or "outside" in text or "scope" in text
        assert "net change" not in text
        assert "ft/yr" not in text

    def test_chat_multi_location_compare_returns_network_context(self):
        """County-vs-county comparison prompts should not collapse to a single-location answer."""
        resp = client.post(
            "/api/chat",
            json={
                "message": (
                    "Compare Miami-Dade wells to Sarasota wells - " "which area has more decline?"
                )
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "network_fallback"
        assert len(body.get("wells", [])) >= 2

    def test_chat_repeated_question_uses_cache(self):
        """Repeated deterministic chat prompts should hit the short-lived chat cache."""
        payload = {
            "message": "What is happening at G-3336?",
            "allow_llm_synthesis": False,
        }

        first = client.post("/api/chat", json=payload)
        second = client.post("/api/chat", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json().get("cache_hit") is not True
        assert second.json().get("cache_hit") is True

    def test_chat_cache_distinguishes_chart_requests(self):
        """Charted and non-charted chat requests should not share cache entries."""
        base_payload = {
            "message": "What is happening at G-3336?",
            "allow_llm_synthesis": False,
        }

        no_chart = client.post("/api/chat", json={**base_payload, "include_chart": False})
        with_chart = client.post("/api/chat", json={**base_payload, "include_chart": True})

        assert no_chart.status_code == 200
        assert with_chart.status_code == 200
        assert no_chart.json().get("cache_hit") is not True
        assert with_chart.json().get("cache_hit") is not True

    def test_chat_dataset_fastest_well_names_well_and_rate(self):
        """Dataset-wide ranking should answer with a named well and annual rate."""
        resp = client.post(
            "/api/chat",
            json={
                "message": "Which well is changing fastest in this dataset?",
                "allow_llm_synthesis": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        text = (body.get("answer_brief") or body.get("response") or "").lower()
        assert body["route_mode"] == "network"
        assert "ft/yr" in text
        assert re.search(r"\b[a-z]-\d{3,5}\b", text) or re.search(
            r"\b[a-z][a-z-]+(?:\s+[a-z][a-z-]+)*\s+[a-z]-\d+\b", text
        )

    def test_chat_most_stressed_aquifer_uses_screening_language(self):
        """Stress ranking should stay comparative and explicitly screening-oriented."""
        resp = client.post(
            "/api/chat",
            json={
                "message": "Which aquifer looks most stressed in this dataset?",
                "allow_llm_synthesis": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        text = (body.get("answer_brief") or body.get("response") or "").lower()
        assert body["route_mode"] == "network"
        assert "ft/yr" in text
        assert "screening" in text or "not proof" in text
        assert "aquifer" in text

    def test_chart_context_which_wells_followup_routes_to_interpreter(self, monkeypatch):
        """Follow-up chips like 'which wells' should not fall through to the well KB."""
        from api.routes import chat as chat_routes

        def _stub_interpreter(question, chart_context, turn_history, **_kwargs):
            return {
                "response": "Stubbed chart-context interpretation.",
                "context": "Chart-context interpretation",
                "sources": [],
                "mode": "chart_interpreter",
                "status": "ok",
                "claim_citations": [],
                "interpretation_response": {
                    "schema_version": "interpretation_response_v1",
                    "question": question,
                    "audience": "general",
                    "interpretation": "The fastest well is identified from chart context.",
                    "follow_up_questions": [],
                    "grounding_status": {
                        "uses_chart_context": True,
                        "uses_usgs_data": True,
                        "invented_measurements_allowed": False,
                    },
                    "chart_context": {"summary": "Stub chart"},
                    "data_references": [],
                },
                "chart_context_used": chart_context,
                "turn_history_used": turn_history,
            }

        monkeypatch.setattr(
            chat_routes._chart_interpreter,
            "interpret_with_context",
            _stub_interpreter,
        )
        resp = client.post(
            "/api/chat",
            json={
                "message": "Which wells on this chart are changing fastest?",
                "chart_context": {
                    "chart_id": "Estero Monthly Groundwater Levels",
                    "site_ids": ["263335081394301", "263532081592201"],
                    "chart_type": "comparison",
                    "summary_metrics": {"title": "Estero Monthly Groundwater Levels"},
                },
                "allow_llm_synthesis": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "chart_interpreter"
        assert body["interpretation_response"]["grounding_status"]["uses_chart_context"] is True

    def test_chart_context_named_well_followup_stays_in_chart_interpreter(self, monkeypatch):
        """Named wells inside an active chart should keep cross-well chart context."""
        from api.routes import chat as chat_routes

        def _stub_interpreter(question, chart_context, turn_history, **_kwargs):
            return {
                "response": "Stubbed named-well chart interpretation.",
                "context": "Chart-context interpretation",
                "sources": [],
                "mode": "chart_interpreter",
                "status": "ok",
                "claim_citations": [],
                "interpretation_response": {
                    "schema_version": "interpretation_response_v1",
                    "question": question,
                    "audience": "general",
                    "interpretation": "The named well is compared against the rest of the chart.",
                    "follow_up_questions": [],
                    "grounding_status": {
                        "uses_chart_context": True,
                        "uses_usgs_data": True,
                        "invented_measurements_allowed": False,
                    },
                    "chart_context": {"summary": "Stub chart"},
                    "data_references": [],
                },
                "chart_context_used": chart_context,
                "turn_history_used": turn_history,
            }

        def _stub_site_fallback(*_args, **_kwargs):
            raise AssertionError("site fallback should not run for named well chart follow-ups")

        monkeypatch.setattr(
            chat_routes._chart_interpreter,
            "interpret_with_context",
            _stub_interpreter,
        )
        monkeypatch.setattr(chat_routes, "_site_research_fallback", _stub_site_fallback)
        resp = client.post(
            "/api/chat",
            json={
                "message": "On G-3764, explain how it compares to the other wells in this chart.",
                "chart_context": {
                    "chart_id": "Miami-Dade comparison",
                    "site_ids": ["251241080385301", "251922080340701"],
                    "chart_type": "comparison",
                    "summary_metrics": {"title": "Miami-Dade comparison"},
                },
                "allow_llm_synthesis": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "chart_interpreter"
        assert body["interpretation_response"]["grounding_status"]["uses_chart_context"] is True

    def test_named_well_divergence_followup_recovers_recent_chart_context(self, monkeypatch):
        """Named-well comparison follow-ups should recover recent chart context from history."""
        from api.routes import chat as chat_routes

        def _stub_interpreter(question, chart_context, turn_history, **_kwargs):
            return {
                "response": "Stubbed recovered chart interpretation.",
                "context": "Recovered chart context",
                "sources": [],
                "mode": "chart_interpreter",
                "status": "ok",
                "claim_citations": [],
                "interpretation_response": {
                    "schema_version": "interpretation_response_v1",
                    "question": question,
                    "audience": "general",
                    "interpretation": "Recovered chart context was used.",
                    "follow_up_questions": [],
                    "grounding_status": {
                        "uses_chart_context": True,
                        "uses_usgs_data": True,
                        "invented_measurements_allowed": False,
                    },
                    "chart_context": {"summary": "Recovered chart"},
                    "data_references": [],
                },
                "chart_context_used": chart_context,
                "turn_history_used": turn_history,
            }

        def _stub_site_fallback(*_args, **_kwargs):
            raise AssertionError("site fallback should not run when chart context is recovered")

        monkeypatch.setattr(
            chat_routes._chart_interpreter,
            "interpret_with_context",
            _stub_interpreter,
        )
        monkeypatch.setattr(chat_routes, "_site_research_fallback", _stub_site_fallback)
        resp = client.post(
            "/api/chat",
            json={
                "message": "Why do Lee L-1998 and Lee L-729 diverge?",
                "turn_history": [
                    {
                        "role": "assistant",
                        "content": "Recent Lee County chart",
                        "chart_id": "Estero Monthly Groundwater Levels",
                        "wells": [
                            {"site_id": "263041081433102", "name": "Lee L-1998"},
                            {"site_id": "263335081394301", "name": "Lee L-729"},
                        ],
                    }
                ],
                "allow_llm_synthesis": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "chart_interpreter"
        assert body["interpretation_response"]["grounding_status"]["uses_chart_context"] is True

    def test_chart_context_named_aquifer_followup_stays_in_chart_interpreter(self, monkeypatch):
        """Named aquifers inside an active chart should stay in chart interpretation mode."""
        from api.routes import chat as chat_routes

        def _stub_interpreter(question, chart_context, turn_history, **_kwargs):
            return {
                "response": "Stubbed aquifer chart interpretation.",
                "context": "Chart-context interpretation",
                "sources": [],
                "mode": "chart_interpreter",
                "status": "ok",
                "claim_citations": [],
                "interpretation_response": {
                    "schema_version": "interpretation_response_v1",
                    "question": question,
                    "audience": "general",
                    "interpretation": "The named aquifer is interpreted inside the active chart.",
                    "follow_up_questions": [],
                    "grounding_status": {
                        "uses_chart_context": True,
                        "uses_usgs_data": True,
                        "invented_measurements_allowed": False,
                    },
                    "chart_context": {"summary": "Stub chart"},
                    "data_references": [],
                },
            }

        def _stub_site_fallback(*_args, **_kwargs):
            raise AssertionError("site fallback should not run for named aquifer chart follow-ups")

        monkeypatch.setattr(
            chat_routes._chart_interpreter,
            "interpret_with_context",
            _stub_interpreter,
        )
        monkeypatch.setattr(chat_routes, "_site_research_fallback", _stub_site_fallback)
        resp = client.post(
            "/api/chat",
            json={
                "message": "Why is Upper Floridan the most stressed supply unit in this dataset?",
                "chart_context": {
                    "chart_id": "Estero Monthly Groundwater Levels",
                    "site_ids": ["263335081394301", "263532081592201", "262538082045701"],
                    "chart_type": "comparison",
                    "summary_metrics": {"title": "Estero Monthly Groundwater Levels"},
                },
                "allow_llm_synthesis": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "chart_interpreter"
        assert body["interpretation_response"]["grounding_status"]["uses_chart_context"] is True


# ===================================================================
# POST /api/interpret endpoint integration tests
# ===================================================================


class TestInterpretEndpoint:
    """Integration tests for evidence-bound chart/data interpretation."""

    def setup_method(self):
        from api.routes import chat as chat_routes

        chat_routes._INTERPRETATION_CACHE.clear()

    def test_interpret_returns_grounded_contract(self):
        """Interpretation response should expose chart context and USGS references."""
        resp = client.post(
            "/api/interpret",
            json={
                "question": "Interpret the Estero groundwater chart for a sponsor.",
                "audience": "sponsor",
                "use_llm": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        interpretation = body["interpretation_response"]
        grounding = interpretation["grounding_status"]

        assert body["mode"].startswith("interpret_")
        assert interpretation["schema_version"] == "interpretation_response_v1"
        assert interpretation["audience"] == "sponsor"
        assert interpretation["chart_context"]["summary"]
        assert interpretation["chart_context"]["how_to_read"]
        assert interpretation["data_references"]
        assert interpretation["follow_up_questions"]
        assert interpretation["next_goal"]
        assert interpretation["follow_up_groups"]
        assert grounding["uses_chart_context"] is True
        assert grounding["uses_usgs_data"] is True
        assert grounding["invented_measurements_allowed"] is False
        assert grounding["llm_requested"] is False
        assert grounding["cache_hit"] is False
        assert interpretation["learner_brief"]["direct_answer"]
        assert interpretation["learner_brief"]["why_it_matters"]

    def test_interpret_empty_question_returns_400(self):
        """Blank interpretation questions are rejected."""
        resp = client.post("/api/interpret", json={"question": ""})
        assert resp.status_code == 400

    def test_interpret_repeated_question_uses_cache(self):
        """Repeated sponsor-demo prompts should be served from the short-lived cache."""
        payload = {
            "question": "Interpret Lee County groundwater trends for a demo.",
            "audience": "sponsor",
            "use_llm": False,
        }

        first = client.post("/api/interpret", json=payload)
        second = client.post("/api/interpret", json=payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["interpretation_response"]["grounding_status"]["cache_hit"] is False
        assert second.json()["interpretation_response"]["grounding_status"]["cache_hit"] is True

    def test_interpret_supply_question_uses_answer_brief(self):
        """Open supply/source questions should expose the same brief in interpretation mode."""
        resp = client.post(
            "/api/interpret",
            json={
                "question": (
                    "What are the groundwater sources the Village of Estero uses for "
                    "water supply and what have been changes in groundwater levels "
                    "there over the last 30 years?"
                ),
                "audience": "sponsor",
                "use_llm": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        interpretation = body["interpretation_response"]

        assert body.get("answer_brief")
        assert "Village of Estero" in interpretation["interpretation"]
        assert interpretation["supply_interpretation"]["municipality"] == "Village of Estero"
        assert interpretation["grounding_status"]["uses_usgs_data"] is True

    def test_interpret_exposes_terms_and_misconceptions_for_learner_queries(self):
        """Learner-oriented interpretation responses should expose definitions and caveats."""
        resp = client.post(
            "/api/interpret",
            json={
                "question": "What does screening risk mean in plain English?",
                "audience": "general",
                "use_llm": False,
            },
        )
        assert resp.status_code == 200
        interpretation = resp.json()["interpretation_response"]
        assert interpretation["terms_to_know"]
        assert interpretation["misconceptions_to_avoid"]
        assert any(item["term"] == "screening risk" for item in interpretation["terms_to_know"])
        assert "High screening risk is not a forecast." in interpretation["misconceptions_to_avoid"]


class TestLearnerEventsEndpoint:
    """Integration tests for lightweight learner-event storage."""

    def test_learner_events_endpoint_requires_event_type(self):
        resp = client.post("/api/learner-events", json={})
        assert resp.status_code == 400

    def test_learner_events_endpoint_persists_event(self):
        resp = client.post(
            "/api/learner-events",
            json={
                "event_type": "learner_brief_shown",
                "question": "What does this chart mean?",
                "message_id": "msg_test_001",
                "chart_id": "Estero Monthly Groundwater Levels",
                "details": {"has_terms_to_know": True},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["event_id"].startswith("learner_")


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
        assert "session_id" in body
        assert "research_plan" in body
        assert "budget_status" in body
        assert "checkpoints" in body
        assert "tool_trace" in body
        assert "recommended_views" in body
        assert "chart_specs" in body
        assert "structured_response" in body
        assert "provenance" in body
        assert "changepoints" in body
        assert "cross_well_clusters" in body
        assert isinstance(body["claim_citations"], list)
        assert isinstance(body["claim_verdicts"], list)
        assert isinstance(body["claim_verdict_summary"], dict)
        assert isinstance(body["citation_summary"], dict)
        assert isinstance(body["section_confidence"], dict)
        assert isinstance(body["hallucination_guardrail"], dict)
        assert isinstance(body["citation_integrity"], dict)
        assert isinstance(body["research_plan"], dict)
        assert isinstance(body["budget_status"], dict)
        assert isinstance(body["checkpoints"], list)
        assert isinstance(body["tool_trace"], list)
        assert isinstance(body["recommended_views"], list)
        assert isinstance(body["chart_specs"], list)
        assert isinstance(body["structured_response"], dict)
        assert isinstance(body["provenance"], dict)
        assert body["structured_response"]["schema_version"] == "evidence_response_v1"
        assert "claims" in body["structured_response"]
        assert "evidence" in body["structured_response"]
        assert body["provenance"]["schema_version"] == "research_provenance_v1"
        assert "response_sha256" in body["provenance"]
        assert body["provenance"]["methodology"]["external_covariates"]["included"] is False

    def test_research_stream_emits_snapshot_and_result_contract(self):
        """Streaming endpoint should emit progress snapshots and a typed final result."""
        resp = client.post(
            "/api/research/stream",
            json={"question": "Estero trends"},
        )
        assert resp.status_code == 200
        chunks = [line for line in resp.text.split("\n\n") if line.strip().startswith("data:")]
        assert chunks, "Expected SSE data frames in response body"

        parsed = []
        for chunk in chunks:
            payload = chunk.replace("data:", "", 1).strip()
            parsed.append(json.loads(payload))

        final = next(event for event in parsed if event.get("type") == "result")
        assert "session_id" in final
        assert "research_plan" in final
        assert "budget_status" in final
        assert "checkpoints" in final
        assert "tool_trace" in final
        assert "recommended_views" in final
        assert "chart_specs" in final
        assert "structured_response" in final
        assert "provenance" in final

    def test_research_structured_response_links_claims_to_evidence_ids(self):
        """Research responses should expose manuscript-friendly claim/evidence links."""
        resp = client.post(
            "/api/research",
            json={"question": "Estero trends"},
        )
        assert resp.status_code == 200
        body = resp.json()
        structured = body["structured_response"]

        assert structured["schema_version"] == "evidence_response_v1"
        assert structured["question"] == "Estero trends"
        assert structured["claims"]
        assert structured["evidence"]
        assert all(item["claim_ids"] for item in structured["claims"])
        assert all(item["evidence_ids"] for item in structured["claims"])
        assert all(
            str(evidence["evidence_id"]).startswith("evidence_")
            for evidence in structured["evidence"]
        )

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

    def test_research_invalid_max_depth_returns_400(self):
        """Non-numeric max_depth should return 400."""
        resp = client.post(
            "/api/research",
            json={"question": "Estero trends", "max_depth": "abc"},
        )
        assert resp.status_code == 400

    def test_research_invalid_timeout_returns_400(self):
        """Non-numeric timeout should return 400."""
        resp = client.post(
            "/api/research",
            json={"question": "Estero trends", "timeout": "not_a_number"},
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize("timeout_value", ["nan", "inf", "-inf", True, False])
    def test_research_nonfinite_or_bool_timeout_returns_400(self, timeout_value):
        """Non-finite or boolean timeout values should be rejected."""
        resp = client.post(
            "/api/research",
            json={"question": "Estero trends", "timeout": timeout_value},
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize("timeout_value", ["nan", "inf", "-inf", True, False])
    def test_research_stream_nonfinite_or_bool_timeout_returns_400(self, timeout_value):
        """Streaming research should use the same timeout validation."""
        resp = client.post(
            "/api/research/stream",
            json={"question": "Estero trends", "timeout": timeout_value},
        )
        assert resp.status_code == 400

    def test_research_clamps_extreme_params(self):
        """Extreme max_depth and timeout should be clamped, not rejected."""
        resp = client.post(
            "/api/research",
            json={"question": "Estero trends", "max_depth": 999, "timeout": 9999},
        )
        assert resp.status_code == 200


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
            def research(self, **_kwargs):
                raise RuntimeError("simulated chat failure")

        monkeypatch.setattr(chat_routes, "_research_agent", _BoomAgent())
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
        """Practical 'how deep should I drill' questions should answer, not refuse."""
        resp = client.post(
            "/api/chat",
            json={"message": "How deep should I drill my irrigation well?"},
        )
        body = resp.json()
        text = body["response"].lower()
        assert "well" in text or "depth" in text or "aquifer" in text

    def test_farmer_seasonal_planning(self):
        """Farmer asking about seasonal water availability."""
        resp = client.post(
            "/api/chat",
            json={"message": "When is the best time to plant considering groundwater?"},
        )
        assert resp.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
