"""Tests for the chat benchmark scoring harness."""

import json
from pathlib import Path

from src.evaluation.chat_benchmark import (evaluate_case_response,
                                           evaluate_thresholds)


def test_benchmark_case_set_has_30_plus_cases():
    """Benchmark corpus should maintain at least 30 cases for evaluation breadth."""
    path = Path("tests/benchmark/chat_eval_cases.json")
    with open(path) as fh:
        cases = json.load(fh)

    assert isinstance(cases, list)
    assert len(cases) >= 30

    ids = [case["id"] for case in cases if isinstance(case, dict) and "id" in case]
    assert len(ids) == len(set(ids))


def test_case_scoring_full_pass():
    """A fully structured response should satisfy all required checks."""
    case = {
        "id": "demo",
        "level": "L1",
        "max_seconds": 10,
        "required_checks": [
            "ok_status",
            "has_report",
            "has_sources",
            "has_claim_citations",
            "has_date_reference",
            "has_trend_language",
            "has_aquifer_language",
        ],
    }
    response = {
        "status": "ok",
        "mode": "deep_research",
        "report": (
            "USGS records from 1994-01-10 to 2024-12-31 show a declining trend "
            "in the Floridan aquifer near Estero."
        ),
        "sources": ["https://waterdata.usgs.gov/monitoring-location/262724081260701"],
        "claim_citations": [
            {
                "claim_id": "claim_001",
                "claim": "Long-term decline observed",
                "citations": [
                    {
                        "url": "https://waterdata.usgs.gov/monitoring-location/262724081260701",
                        "verified": True,
                        "trust_level": "verified",
                    }
                ],
            }
        ],
        "citation_summary": {
            "total_claims": 1,
            "cited_claims": 1,
            "citation_coverage": 1.0,
        },
    }

    result = evaluate_case_response(case, response, elapsed_seconds=1.2, status_code=200)
    assert result["score"] == 1.0
    assert result["failed_checks"] == []
    assert result["citation_coverage"] == 1.0


def test_threshold_evaluation_failure_reasons():
    """Threshold evaluation should provide explicit failure reasons."""
    case_results = [
        {"case_id": "l1", "score": 0.4, "citation_coverage": 0.5, "elapsed_seconds": 4.1},
        {"case_id": "l2", "score": 0.6, "citation_coverage": 0.4, "elapsed_seconds": 5.2},
    ]
    thresholds = {
        "min_overall_score": 0.85,
        "min_case_score": 0.80,
        "min_avg_citation_coverage": 0.90,
        "max_response_seconds": 3.0,
    }

    summary = evaluate_thresholds(case_results, thresholds)
    assert summary["passed"] is False
    assert len(summary["failed_reasons"]) >= 3
    assert any("overall_score" in reason for reason in summary["failed_reasons"])
    assert any("average_citation_coverage" in reason for reason in summary["failed_reasons"])
    assert any("max_elapsed" in reason for reason in summary["failed_reasons"])
