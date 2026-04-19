"""Tests for extracted evidence-guided structured synthesis helpers.

These functions were refactored out of research_agent.py into
src/agent/evidence_guided_synthesis.py. This file validates they
produce correct output independently, covering the contract that
the research agent depends on.
"""

import json

import pytest

from src.agent.evidence_guided_synthesis import (
    build_evidence_items,
    clean_structured_text,
    dedupe_string_list,
    heuristic_structured_response,
    parse_structured_response,
    render_structured_report,
    safe_confidence,
)

# -- fixtures ---------------------------------------------------------------

SAMPLE_CLAIM_CITATIONS = [
    {
        "claim_id": "claim_001",
        "claim": "Lee L-729 is declining at -0.355 ft/yr.",
        "claim_type": "retrieved_insight",
        "confidence": 0.85,
        "citations": [
            {
                "evidence_id": "ev_001",
                "url": "https://waterdata.usgs.gov/nwis/uv?site_no=263226081445801",
                "trust_level": "verified",
                "verified": True,
            },
        ],
    },
    {
        "claim_id": "claim_002",
        "claim": "The cohort mean annual change is -0.12 ft/yr.",
        "claim_type": "retrieved_insight",
        "confidence": 0.70,
        "citations": [
            {
                "evidence_id": "ev_002",
                "url": "https://waterdata.usgs.gov/",
                "trust_level": "verified",
                "verified": True,
            },
            {
                "source": "local_metric",
                "trust_level": "primary",
                "verified": False,
            },
        ],
    },
]

SAMPLE_VERDICTS = [
    {"claim_id": "claim_001", "verdict": "supported"},
    {"claim_id": "claim_002", "verdict": "insufficient_evidence"},
]


# -- build_evidence_items ----------------------------------------------------


def test_build_evidence_items_maps_citations_to_flat_list():
    items = build_evidence_items(SAMPLE_CLAIM_CITATIONS)
    assert len(items) == 3
    assert items[0]["evidence_id"] == "ev_001"
    assert items[0]["claim_id"] == "claim_001"
    assert items[0]["verified"] is True
    assert items[1]["evidence_id"] == "ev_002"
    assert items[1]["claim_id"] == "claim_002"


def test_build_evidence_items_generates_id_when_missing():
    citations = [
        {
            "claim_id": "claim_099",
            "citations": [{"url": "https://example.com", "trust_level": "unknown"}],
        },
    ]
    items = build_evidence_items(citations)
    assert len(items) == 1
    assert items[0]["evidence_id"].startswith("evidence_")


def test_build_evidence_items_empty_input():
    assert build_evidence_items([]) == []


# -- heuristic_structured_response -------------------------------------------


def test_heuristic_response_has_required_schema_keys():
    resp = heuristic_structured_response(
        "What is happening at Lee L-729?",
        SAMPLE_CLAIM_CITATIONS,
        SAMPLE_VERDICTS,
    )
    assert resp["schema_version"] == "evidence_response_v1"
    assert resp["question"] == "What is happening at Lee L-729?"
    assert resp["answer"]
    assert isinstance(resp["claims"], list)
    assert len(resp["claims"]) <= 6
    assert resp["limitations"]
    assert resp["recommended_followup"]
    assert resp["evidence"]


def test_heuristic_response_marks_insufficient_evidence():
    resp = heuristic_structured_response(
        "question",
        SAMPLE_CLAIM_CITATIONS,
        SAMPLE_VERDICTS,
    )
    claim_002 = next(c for c in resp["claims"] if "claim_002" in c["claim_ids"])
    assert "limited" in claim_002["uncertainty"].lower()


def test_heuristic_response_with_no_claims():
    resp = heuristic_structured_response("question", [], [])
    assert "insufficient" in resp["answer"].lower()
    assert resp["claims"] == []


# -- parse_structured_response -----------------------------------------------


def test_parse_structured_response_valid_json():
    evidence_items = build_evidence_items(SAMPLE_CLAIM_CITATIONS)
    raw = json.dumps(
        {
            "answer": "Lee L-729 is declining.",
            "claims": [
                {
                    "claim": "Declining at -0.355 ft/yr",
                    "claim_type": "interpretation",
                    "claim_ids": ["claim_001"],
                    "evidence_ids": ["ev_001"],
                    "confidence": 0.9,
                    "is_interpretive": False,
                    "uncertainty": "",
                },
            ],
            "limitations": ["Data limited to USGS records."],
            "recommended_followup": ["Check pumping records."],
        }
    )
    resp = parse_structured_response(
        raw,
        question="What is happening?",
        claim_citations=SAMPLE_CLAIM_CITATIONS,
        claim_verdicts=SAMPLE_VERDICTS,
        evidence_items=evidence_items,
    )
    assert resp["schema_version"] == "evidence_response_v1"
    assert resp["answer"] == "Lee L-729 is declining."
    assert len(resp["claims"]) == 1
    assert resp["claims"][0]["claim_ids"] == ["claim_001"]


def test_parse_structured_response_fenced_json():
    evidence_items = build_evidence_items(SAMPLE_CLAIM_CITATIONS)
    raw = '```json\n{"answer":"ok","claims":[{"claim":"test","claim_ids":["claim_001"],"evidence_ids":["ev_001"],"confidence":0.8}]}\n```'  # noqa: E501
    resp = parse_structured_response(
        raw,
        question="test",
        claim_citations=SAMPLE_CLAIM_CITATIONS,
        claim_verdicts=SAMPLE_VERDICTS,
        evidence_items=evidence_items,
    )
    assert resp["claims"][0]["claim"] == "test"


def test_parse_structured_response_raises_on_invalid_json():
    with pytest.raises(Exception):
        parse_structured_response(
            "not json at all",
            question="test",
            claim_citations=SAMPLE_CLAIM_CITATIONS,
            claim_verdicts=SAMPLE_VERDICTS,
        )


def test_parse_rejects_invalid_claim_ids():
    evidence_items = build_evidence_items(SAMPLE_CLAIM_CITATIONS)
    raw = json.dumps(
        {
            "answer": "answer",
            "claims": [
                {
                    "claim": "hallucinated",
                    "claim_ids": ["fake_id"],
                    "evidence_ids": ["ev_001"],
                    "confidence": 0.9,
                },
            ],
        }
    )
    resp = parse_structured_response(
        raw,
        question="test",
        claim_citations=SAMPLE_CLAIM_CITATIONS,
        claim_verdicts=SAMPLE_VERDICTS,
        evidence_items=evidence_items,
    )
    # Invalid claim_id "fake_id" should be filtered, causing fallback to heuristic
    assert resp["schema_version"] == "evidence_response_v1"


# -- render_structured_report ------------------------------------------------


def test_render_structured_report_contains_claims():
    structured = heuristic_structured_response(
        "test question",
        SAMPLE_CLAIM_CITATIONS,
        SAMPLE_VERDICTS,
    )
    report = render_structured_report(structured)
    assert "Evidence-Linked Claims" in report
    assert "claim_001" in report
    assert "Limitations" in report


def test_render_structured_report_empty_claims():
    report = render_structured_report(
        {"answer": "No data.", "claims": [], "limitations": [], "recommended_followup": []}
    )
    assert "No data." in report
    assert "Evidence-Linked Claims" not in report


# -- utility helpers ---------------------------------------------------------


def test_clean_structured_text_caps_length():
    assert len(clean_structured_text("x" * 500, max_len=100)) == 100


def test_safe_confidence_clamps():
    assert safe_confidence(1.5) == 1.0
    assert safe_confidence(-0.3) == 0.0
    assert safe_confidence("invalid") == 0.5
    assert safe_confidence(None, default=0.7) == 0.7


def test_dedupe_string_list_filters_invalid():
    result = dedupe_string_list(
        ["a", "b", "a", "c", "d"],
        valid_values={"a", "b", "c"},
    )
    assert result == ["a", "b", "c"]


def test_dedupe_string_list_non_list_input():
    assert dedupe_string_list("not a list") == []
