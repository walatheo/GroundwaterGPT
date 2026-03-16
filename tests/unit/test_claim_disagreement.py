"""Unit tests for claim disagreement verification logic."""

from src.claim_disagreement import ClaimDisagreementEngine, summarize_claim_verdicts


def test_supported_verdict_with_cited_claim():
    engine = ClaimDisagreementEngine()
    verdicts = engine.evaluate_claims(
        [
            {
                "claim_id": "claim_001",
                "claim": "USGS site 262724081260701 shows a rising groundwater trend.",
                "confidence": 0.9,
                "citations": [
                    {
                        "url": "https://waterdata.usgs.gov/monitoring-location/262724081260701",
                        "verified": True,
                        "trust_level": "verified",
                    }
                ],
            }
        ]
    )
    assert len(verdicts) == 1
    assert verdicts[0]["verdict"] == "supported"
    assert 0.0 <= verdicts[0]["risk_score"] <= 1.0


def test_insufficient_evidence_without_citation():
    engine = ClaimDisagreementEngine()
    verdicts = engine.evaluate_claims(
        [
            {
                "claim_id": "claim_001",
                "claim": "Groundwater conditions are improving in Estero.",
                "confidence": 0.6,
                "citations": [],
            }
        ]
    )
    assert verdicts[0]["verdict"] == "insufficient_evidence"
    assert verdicts[0]["counter_evidence"] == []


def test_contradicted_when_opposite_trends_share_same_site():
    engine = ClaimDisagreementEngine()
    verdicts = engine.evaluate_claims(
        [
            {
                "claim_id": "claim_001",
                "claim": "USGS site 262724081260701 shows a rising trend in groundwater level.",
                "confidence": 0.82,
                "citations": [
                    {
                        "url": "https://waterdata.usgs.gov/monitoring-location/262724081260701",
                        "verified": True,
                        "trust_level": "verified",
                    }
                ],
            },
            {
                "claim_id": "claim_002",
                "claim": "USGS site 262724081260701 shows a declining trend in groundwater level.",
                "confidence": 0.79,
                "citations": [
                    {
                        "url": "https://waterdata.usgs.gov/monitoring-location/262724081260701",
                        "verified": True,
                        "trust_level": "verified",
                    }
                ],
            },
        ]
    )
    verdict_by_id = {item["claim_id"]: item for item in verdicts}
    assert verdict_by_id["claim_001"]["verdict"] == "contradicted"
    assert verdict_by_id["claim_002"]["verdict"] == "contradicted"
    assert verdict_by_id["claim_001"]["counter_evidence"]


def test_claim_verdict_summary_counts_and_rates():
    engine = ClaimDisagreementEngine()
    verdicts = engine.evaluate_claims(
        [
            {
                "claim_id": "claim_001",
                "claim": "USGS site 262724081260701 shows a rising groundwater trend.",
                "confidence": 0.9,
                "citations": [
                    {
                        "url": "https://waterdata.usgs.gov/monitoring-location/262724081260701",
                        "verified": True,
                        "trust_level": "verified",
                    }
                ],
            },
            {
                "claim_id": "claim_002",
                "claim": "Groundwater conditions are improving in Estero.",
                "confidence": 0.5,
                "citations": [],
            },
        ]
    )
    summary = summarize_claim_verdicts(verdicts)
    assert summary["total_claims"] == 2
    assert summary["supported_claims"] == 1
    assert summary["insufficient_evidence_claims"] == 1
    assert "high_risk_claim_rate" in summary
