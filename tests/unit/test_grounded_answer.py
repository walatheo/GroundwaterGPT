"""Phase 2 tests — compose_grounded_answer produces the canonical six fields."""

from __future__ import annotations

from api.routes._answer_contract import GroundingStatus
from api.routes._grounded_answer import (
    GroundedAnswer,
    attach_grounded_answer,
    compose_grounded_answer,
)

# ---------------------------------------------------------------------------
# direct_answer
# ---------------------------------------------------------------------------


class TestDirectAnswer:
    def test_prefers_learner_brief(self):
        payload = {
            "response": "Long response text.",
            "answer_brief": "Backup brief.",
            "interpretation_response": {
                "learner_brief": {"direct_answer": "Water table fell 2 ft since 2018"},
            },
        }
        assert compose_grounded_answer(payload).direct_answer == "Water table fell 2 ft since 2018."

    def test_falls_back_to_answer_brief(self):
        payload = {
            "response": "Irrelevant long text.",
            "answer_brief": "G-3336 shows a 0.8 ft decline",
        }
        assert compose_grounded_answer(payload).direct_answer == "G-3336 shows a 0.8 ft decline."

    def test_falls_back_to_meaning_brief_headline(self):
        payload = {
            "response": "",
            "interpretation_details": {"meaning_brief": {"headline": "Trend is stable"}},
        }
        assert compose_grounded_answer(payload).direct_answer == "Trend is stable."

    def test_first_sentence_of_response_when_nothing_else(self):
        payload = {"response": "G-3336 trends down. More context follows here."}
        assert compose_grounded_answer(payload).direct_answer == "G-3336 trends down."

    def test_empty_payload_yields_empty_string(self):
        assert compose_grounded_answer({}).direct_answer == ""


# ---------------------------------------------------------------------------
# grounded_findings
# ---------------------------------------------------------------------------


class TestGroundedFindings:
    def test_chart_insights_come_first(self):
        payload = {
            "chart": {"insights": ["Monthly mean declined 0.5 ft", "Seasonal swing narrowed"]},
            "claim_citations": [{"claim": "Some cited claim"}],
        }
        findings = compose_grounded_answer(payload).grounded_findings
        assert findings[0] == "Monthly mean declined 0.5 ft."
        assert findings[1] == "Seasonal swing narrowed."
        assert findings[-1] == "Some cited claim."

    def test_dedupes_case_insensitive(self):
        payload = {
            "chart": {"insights": ["Trend is flat"]},
            "claim_citations": [{"claim": "trend is flat"}],
        }
        assert compose_grounded_answer(payload).grounded_findings == ["Trend is flat."]

    def test_caps_at_five(self):
        payload = {
            "chart": {"insights": [f"Insight {i}" for i in range(10)]},
        }
        assert len(compose_grounded_answer(payload).grounded_findings) == 5

    def test_fallback_to_meaning_brief_when_no_chart(self):
        payload = {
            "interpretation_details": {
                "meaning_brief": {
                    "plain_language": "Water level is stable over the record",
                    "why_it_matters": "Supply risk is low",
                }
            }
        }
        findings = compose_grounded_answer(payload).grounded_findings
        assert "Water level is stable over the record." in findings
        assert "Supply risk is low." in findings

    def test_no_evidence_yields_empty_list(self):
        assert compose_grounded_answer({}).grounded_findings == []


# ---------------------------------------------------------------------------
# limits
# ---------------------------------------------------------------------------


class TestLimits:
    def test_default_caveats_always_present(self):
        limits = compose_grounded_answer({}).limits
        assert any("monitoring records" in line.lower() for line in limits)
        assert any("screening" in line.lower() for line in limits)
        assert any("invent measurements" in line.lower() for line in limits)

    def test_branch_limits_come_first_and_defaults_dedupe(self):
        payload = {
            "interpretation_response": {
                "limits": [
                    "Only three wells available in this cohort",
                    "Trend lines are screening summaries over the available record, not forecasts.",  # noqa: E501 — matches default verbatim
                ]
            }
        }
        limits = compose_grounded_answer(payload).limits
        assert limits[0] == "Only three wells available in this cohort."
        assert len([line for line in limits if "screening summaries" in line]) == 1

    def test_confidence_notes_are_included(self):
        payload = {"interpretation_details": {"confidence_notes": ["Sparse post-2020 record"]}}
        assert "Sparse post-2020 record." in compose_grounded_answer(payload).limits


# ---------------------------------------------------------------------------
# next_best_question
# ---------------------------------------------------------------------------


class TestNextBestQuestion:
    def test_prefers_learner_brief_question(self):
        payload = {
            "interpretation_response": {
                "learner_brief": {"next_best_question": "What happened in 2018"},
                "follow_up_questions": ["Something else"],
            }
        }
        assert compose_grounded_answer(payload).next_best_question == "What happened in 2018?"

    def test_falls_back_to_top_level_follow_ups(self):
        payload = {"follow_up_questions": ["Compare G-3336 and G-5004."]}
        assert compose_grounded_answer(payload).next_best_question == "Compare G-3336 and G-5004?"

    def test_next_goal_as_last_resort_before_meaning_brief(self):
        payload = {"next_goal": "Pull pumping records for nearby wells"}
        assert (
            compose_grounded_answer(payload).next_best_question
            == "Pull pumping records for nearby wells?"
        )

    def test_returns_none_when_nothing_available(self):
        assert compose_grounded_answer({}).next_best_question is None


# ---------------------------------------------------------------------------
# supporting_evidence
# ---------------------------------------------------------------------------


class TestSupportingEvidence:
    def test_wells_become_evidence_entries(self):
        payload = {
            "wells": [
                {
                    "site_id": "G-3336",
                    "name": "Estero Monitor",
                    "aquifer": "Biscayne",
                    "county": "Lee",
                    "usgs_url": "https://waterdata.usgs.gov/nwis/uv?G-3336",
                }
            ]
        }
        evidence = compose_grounded_answer(payload).supporting_evidence
        assert evidence == [
            {
                "kind": "well",
                "site_id": "G-3336",
                "name": "Estero Monitor",
                "aquifer": "Biscayne",
                "county": "Lee",
                "source": "USGS NWIS",
                "url": "https://waterdata.usgs.gov/nwis/uv?G-3336",
            }
        ]

    def test_wells_without_site_id_are_skipped(self):
        payload = {"wells": [{"name": "no id"}, {"site_id": "G-1"}]}
        evidence = compose_grounded_answer(payload).supporting_evidence
        assert [e["site_id"] for e in evidence] == ["G-1"]

    def test_interpretation_evidence_adds_citations(self):
        payload = {
            "interpretation_response": {
                "evidence": [
                    {"url": "https://a", "trust_level": "high", "verified": True},
                    {"url": "https://b"},
                ]
            }
        }
        evidence = compose_grounded_answer(payload).supporting_evidence
        assert evidence[0]["url"] == "https://a"
        assert evidence[0]["trust_level"] == "high"
        assert evidence[0]["verified"] is True
        assert evidence[1]["url"] == "https://b"

    def test_sources_fallback_when_no_evidence_list(self):
        payload = {"sources": ["https://usgs.example/a", "https://usgs.example/b"]}
        evidence = compose_grounded_answer(payload).supporting_evidence
        assert [e["url"] for e in evidence] == [
            "https://usgs.example/a",
            "https://usgs.example/b",
        ]

    def test_url_deduplication(self):
        payload = {
            "interpretation_response": {"evidence": [{"url": "https://x"}]},
            "sources": ["https://x", "https://y"],
        }
        urls = [e["url"] for e in compose_grounded_answer(payload).supporting_evidence]
        assert urls == ["https://x", "https://y"]

    def test_cap_at_six_entries(self):
        payload = {
            "wells": [{"site_id": f"G-{i}"} for i in range(10)],
        }
        assert len(compose_grounded_answer(payload).supporting_evidence) == 6


# ---------------------------------------------------------------------------
# grounding_status + to_dict + attach wrapper
# ---------------------------------------------------------------------------


class TestGroundingAndWiring:
    def test_grounding_status_matches_contract_helper(self):
        payload = {"wells": [{"site_id": "G-1"}], "citation_integrity": {"passed": True}}
        assert compose_grounded_answer(payload).grounding_status == GroundingStatus.GROUNDED

    def test_empty_payload_is_insufficient(self):
        assert compose_grounded_answer({}).grounding_status == GroundingStatus.INSUFFICIENT

    def test_to_dict_round_trip(self):
        answer = GroundedAnswer(direct_answer="hi", grounded_findings=["a."])
        assert answer.to_dict()["direct_answer"] == "hi"
        assert answer.to_dict()["grounded_findings"] == ["a."]

    def test_attach_is_idempotent(self):
        payload: dict = {"wells": [{"site_id": "G-1"}]}
        attach_grounded_answer(payload)
        original = payload["grounded_answer"]
        payload["wells"] = [{"site_id": "G-2"}]  # change underlying evidence
        attach_grounded_answer(payload)
        # Idempotent — the earlier value is preserved.
        assert payload["grounded_answer"] is original

    def test_attach_force_recomputes(self):
        payload: dict = {"wells": [{"site_id": "G-1"}]}
        attach_grounded_answer(payload)
        payload["wells"] = [{"site_id": "G-2"}]
        attach_grounded_answer(payload, force=True)
        assert payload["grounded_answer"]["supporting_evidence"][0]["site_id"] == "G-2"

    def test_attach_returns_payload(self):
        payload: dict = {}
        assert attach_grounded_answer(payload) is payload
        assert "grounded_answer" in payload


# ---------------------------------------------------------------------------
# End-to-end: realistic envelope shape
# ---------------------------------------------------------------------------


class TestRealisticEnvelope:
    def test_full_site_fallback_envelope(self):
        payload = {
            "response": (
                "G-3336 has declined 0.8 ft over the record. "
                "This is consistent with coastal pumping pressure."
            ),
            "answer_brief": "G-3336 trends down 0.8 ft",
            "chart": {"insights": ["Monthly mean fell ~0.8 ft", "No seasonal recovery since 2020"]},
            "claim_citations": [{"claim": "Decline began in 2018"}],
            "wells": [
                {"site_id": "G-3336", "name": "G-3336", "aquifer": "Biscayne", "county": "Lee"}
            ],
            "sources": ["https://waterdata.usgs.gov/nwis/uv?G-3336"],
            "citation_integrity": {"passed": True},
            "follow_up_questions": ["What pumping wells are nearby?"],
        }
        answer = compose_grounded_answer(payload)
        assert answer.direct_answer == "G-3336 trends down 0.8 ft."
        assert "Monthly mean fell ~0.8 ft." in answer.grounded_findings
        assert answer.grounding_status == GroundingStatus.GROUNDED
        assert answer.next_best_question == "What pumping wells are nearby?"
        assert answer.supporting_evidence[0]["site_id"] == "G-3336"
        assert any("not a groundwater-flow model" in line for line in answer.limits)
