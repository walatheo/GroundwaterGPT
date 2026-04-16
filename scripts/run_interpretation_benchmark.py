"""Run the evidence-bound groundwater interpretation benchmark."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CASES_PATH = PROJECT_ROOT / "tests" / "benchmark" / "interpretation_eval_cases.json"
DEFAULT_THRESHOLDS_PATH = (
    PROJECT_ROOT / "tests" / "benchmark" / "interpretation_eval_thresholds.json"
)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "interpretation_benchmark_report.json",
    )
    parser.add_argument(
        "--disable-llm",
        action="store_true",
        help="Disable optional local LLM synthesis for deterministic benchmark runs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Run only the first N cases for a quick smoke check.",
    )
    parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Exit non-zero when threshold policy fails.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> Any:
    with open(path) as fh:
        return json.load(fh)


def _text_blob(body: dict[str, Any]) -> str:
    interpretation = body.get("interpretation_response") or {}
    chart_context = interpretation.get("chart_context") or {}
    return "\n".join(
        [
            str(body.get("response", "")),
            str(body.get("llm_synthesis", "")),
            str(interpretation.get("interpretation", "")),
            str(interpretation.get("direct_answer", "")),
            " ".join(str(item) for item in interpretation.get("supporting_evidence", []) or []),
            " ".join(
                str(item) for item in interpretation.get("answer_relevant_observations", []) or []
            ),
            str(interpretation.get("hydrogeologic_meaning", "")),
            " ".join(str(item) for item in interpretation.get("possible_drivers", []) or []),
            " ".join(str(item) for item in interpretation.get("evidence_needed", []) or []),
            " ".join(str(item) for item in interpretation.get("management_implications", []) or []),
            " ".join(str(item) for item in interpretation.get("confidence_notes", []) or []),
            str(chart_context.get("summary", "")),
            " ".join(str(item) for item in interpretation.get("key_observations", []) or []),
            " ".join(str(item) for item in interpretation.get("groundwater_concepts", []) or []),
            " ".join(str(item) for item in interpretation.get("limits", []) or []),
        ]
    )


def _chart_context_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    chart = body.get("chart") or {}
    series = chart.get("series") or []
    site_ids = []
    for item in series:
        key = str((item or {}).get("key", ""))
        if key and key != "avg" and not key.endswith("_trend"):
            site_ids.append(key)
    if not site_ids:
        return None
    return {
        "chart_id": chart.get("title")
        or f"{chart.get('chart_type', 'chart')}:{','.join(site_ids)}",
        "site_ids": list(dict.fromkeys(site_ids)),
        "chart_type": chart.get("chart_type", "comparison"),
        "summary_metrics": {
            "title": chart.get("title", ""),
            "summary": (chart.get("explainability") or {}).get("summary", ""),
            "insights": chart.get("insights", []),
            "site_ids": list(dict.fromkeys(site_ids)),
        },
    }


def _numeric_match(case: dict[str, Any], interpretation: dict[str, Any]) -> bool:
    expected = case.get("expected_numeric_claims") or []
    if not expected:
        return True
    numeric_claims = interpretation.get("numeric_claims") or []
    for target in expected:
        target_site = str(target.get("site", "")).lower()
        target_unit = str(target.get("unit", "ft/yr"))
        target_value = float(target.get("value", 0.0))
        tolerance = float(target.get("tolerance", 0.1))
        found = False
        for claim in numeric_claims:
            claim_site = str(claim.get("site", "")).lower()
            if target_site and target_site not in claim_site:
                continue
            if str(claim.get("unit")) != target_unit:
                continue
            try:
                value = float(claim.get("value"))
            except (TypeError, ValueError):
                continue
            if abs(value - target_value) <= tolerance:
                found = True
                break
        if not found:
            return False
    return True


def _free_text_numbers_are_claimed(interpretation: dict[str, Any]) -> bool:
    answer = str(interpretation.get("answer") or interpretation.get("interpretation") or "")
    inline_values = [float(match) for match in re.findall(r"([+-]?\d+(?:\.\d+)?)\s*ft/yr", answer)]
    if not inline_values:
        return True
    numeric_values = [
        float(claim.get("value"))
        for claim in interpretation.get("numeric_claims", []) or []
        if claim.get("unit") == "ft/yr"
    ]
    return all(
        any(abs(value - claimed) <= 0.01 for claimed in numeric_values) for value in inline_values
    )


def _guardrail_compliant(
    case: dict[str, Any], interpretation: dict[str, Any], text_lower: str
) -> bool:
    if not case.get("must_hedge"):
        return True
    hedge_phrases = [
        "does not prove",
        "available record does not show",
        "cannot attribute",
        "would require",
        "not enough evidence",
    ]
    flags = [str(flag).lower() for flag in interpretation.get("guardrail_flags", []) or []]
    return any(phrase in text_lower for phrase in hedge_phrases) or bool(flags)


def _not_generic_contextual(case: dict[str, Any], text_lower: str) -> bool:
    if not case.get("prior_turn") and str(case.get("level", "")) != "hydro-context":
        return True
    generic_phrases = [
        "well permits required",
        "a well is a hole",
        "a groundwater well is",
        "wells are structures",
        "a well provides access",
    ]
    return not any(phrase in text_lower for phrase in generic_phrases)


def _not_data_only(case: dict[str, Any], interpretation: dict[str, Any], text_lower: str) -> bool:
    level = str(case.get("level", "")).lower()
    if level == "numeric":
        return True
    if not case.get("prior_turn") and level != "hydro-context":
        return True
    interpretive_fields = [
        interpretation.get("hydrogeologic_meaning"),
        interpretation.get("interpretive_findings"),
        interpretation.get("possible_drivers"),
        interpretation.get("evidence_needed"),
        interpretation.get("management_implications"),
        interpretation.get("confidence_notes"),
    ]
    if any(bool(item) for item in interpretive_fields):
        return True
    interpretive_terms = [
        "what this may mean",
        "possible explanations",
        "what would confirm",
        "drawdown",
        "recharge",
        "seasonal",
        "proxy",
        "evidence needed",
        "would require",
        "does not prove",
        "confidence note",
    ]
    return any(term in text_lower for term in interpretive_terms)


def evaluate_case(
    case: dict[str, Any],
    body: dict[str, Any],
    status_code: int,
    elapsed_seconds: float,
    outbound_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one interpretation response."""
    interpretation = body.get("interpretation_response") or {}
    chart_context = interpretation.get("chart_context") or {}
    grounding = interpretation.get("grounding_status") or {}
    data_references = interpretation.get("data_references") or []
    evidence = interpretation.get("evidence") or []
    suggested_questions = interpretation.get("follow_up_questions") or []
    text = _text_blob(body)
    text_lower = text.lower()

    expected_terms = [str(term).lower() for term in case.get("expected_terms", [])]
    expected_site_ids = [str(site_id) for site_id in case.get("expected_site_ids", [])]
    expected_concepts = [str(term).lower() for term in case.get("expected_concepts", [])]
    must_not_contain = [str(term).lower() for term in case.get("must_not_contain", [])]
    prior_site_ids = [
        str(site_id)
        for site_id in ((outbound_body or {}).get("chart_context") or {}).get("site_ids", [])
    ]

    concept_text = " ".join(
        str(item).lower() for item in interpretation.get("groundwater_concepts", []) or []
    )
    checks = {
        "ok_status": status_code == 200 and body.get("status") == "ok",
        "has_schema": interpretation.get("schema_version") == "interpretation_response_v1",
        "has_interpretation": bool(str(interpretation.get("interpretation", "")).strip()),
        "has_chart_context": bool(chart_context.get("summary")),
        "has_data_references": len(data_references) >= int(case.get("min_data_references", 1)),
        "has_evidence": bool(evidence),
        "has_suggested_questions": bool(suggested_questions),
        "uses_chart_context": grounding.get("uses_chart_context") is True,
        "uses_usgs_data": grounding.get("uses_usgs_data") is True,
        "no_invented_measurements_policy": (
            grounding.get("invented_measurements_allowed") is False
        ),
        "expected_terms_present": all(term in text_lower for term in expected_terms),
        "expected_site_ids_present": all(site_id in text for site_id in expected_site_ids),
        "expected_concepts_present": all(
            term in concept_text or term in text_lower for term in expected_concepts
        ),
        "must_not_contain_absent": all(term not in text_lower for term in must_not_contain),
        "numeric_match": _numeric_match(case, interpretation),
        "free_text_numbers_claimed": _free_text_numbers_are_claimed(interpretation),
        "not_generic_contextual": _not_generic_contextual(case, text_lower),
        "not_data_only": _not_data_only(case, interpretation, text_lower),
        "turn_context_bound": (
            not case.get("prior_turn")
            or (
                bool((outbound_body or {}).get("chart_context"))
                and any(site_id in text for site_id in prior_site_ids)
            )
        ),
        "guardrail_compliant": _guardrail_compliant(case, interpretation, text_lower),
        "within_time_budget": elapsed_seconds <= float(case.get("max_seconds", 90.0)),
    }

    passed_count = sum(1 for passed in checks.values() if passed)
    score = passed_count / len(checks)
    return {
        "case_id": case.get("id"),
        "level": case.get("level"),
        "question": case.get("question"),
        "mode": body.get("mode", "unknown"),
        "status_code": status_code,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "score": round(score, 3),
        "passed": score >= 0.75,
        "checks": checks,
        "llm_synthesis_present": bool(body.get("llm_synthesis")),
        "outbound_had_chart_context": bool((outbound_body or {}).get("chart_context")),
    }


def evaluate_thresholds(
    results: list[dict[str, Any]], thresholds: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate aggregate threshold policy."""
    overall_score = statistics.mean(r["score"] for r in results) if results else 0.0
    median_seconds = statistics.median(r["elapsed_seconds"] for r in results) if results else 0.0
    max_seconds = max((r["elapsed_seconds"] for r in results), default=0.0)

    def coverage(check_name: str) -> float:
        return (
            sum(1 for result in results if result["checks"].get(check_name)) / len(results)
            if results
            else 0.0
        )

    min_overall_score = float(thresholds.get("min_overall_score", 0.0))
    min_case_score = float(thresholds.get("min_case_score", 0.0))
    failed_reasons: list[str] = []
    if overall_score < min_overall_score:
        failed_reasons.append(
            f"overall_score={overall_score:.3f} < min_overall_score={min_overall_score:.3f}"
        )
    low_cases = [r["case_id"] for r in results if r["score"] < min_case_score]
    if low_cases:
        failed_reasons.append(
            f"case_scores below min_case_score={min_case_score:.3f}: {', '.join(low_cases)}"
        )

    coverage_thresholds = {
        "grounding_coverage": ("uses_usgs_data", thresholds.get("min_grounding_coverage", 0.0)),
        "chart_context_coverage": (
            "has_chart_context",
            thresholds.get("min_chart_context_coverage", 0.0),
        ),
        "data_reference_coverage": (
            "has_data_references",
            thresholds.get("min_data_reference_coverage", 0.0),
        ),
        "suggested_question_coverage": (
            "has_suggested_questions",
            thresholds.get("min_suggested_question_coverage", 0.0),
        ),
        "numeric_match_rate": (
            "numeric_match",
            thresholds.get("min_numeric_match_rate", 0.0),
        ),
        "guardrail_pass_rate": (
            "guardrail_compliant",
            thresholds.get("min_guardrail_pass_rate", 0.0),
        ),
    }
    coverage_summary: dict[str, float] = {}
    for label, (check_name, threshold) in coverage_thresholds.items():
        value = coverage(check_name)
        coverage_summary[label] = round(value, 3)
        if value < float(threshold):
            failed_reasons.append(f"{label}={value:.3f} < threshold={float(threshold):.3f}")

    fake_policy_fail_rate = 1.0 - coverage("no_invented_measurements_policy")
    max_fake_policy_fail_rate = float(thresholds.get("max_fake_measurement_policy_fail_rate", 1.0))
    if fake_policy_fail_rate > max_fake_policy_fail_rate:
        failed_reasons.append(
            "fake_measurement_policy_fail_rate="
            f"{fake_policy_fail_rate:.3f} > {max_fake_policy_fail_rate:.3f}"
        )

    max_median_seconds = float(thresholds.get("max_median_seconds", 9999.0))
    max_response_seconds = float(thresholds.get("max_response_seconds", 9999.0))
    if median_seconds > max_median_seconds:
        failed_reasons.append(
            f"median_elapsed={median_seconds:.3f}s > max_median_seconds={max_median_seconds:.3f}s"
        )
    if max_seconds > max_response_seconds:
        failed_reasons.append(
            f"max_elapsed={max_seconds:.3f}s > max_response_seconds={max_response_seconds:.3f}s"
        )

    return {
        "passed": not failed_reasons,
        "overall_score": round(overall_score, 3),
        "median_elapsed_seconds": round(median_seconds, 3),
        "max_elapsed_seconds": round(max_seconds, 3),
        "fake_measurement_policy_fail_rate": round(fake_policy_fail_rate, 3),
        **coverage_summary,
        "failed_reasons": failed_reasons,
        "thresholds": thresholds,
    }


def main() -> int:
    """Run the benchmark and write a report."""
    args = parse_args()
    os.environ["GROUNDWATERGPT_SKIP_AGENT_INIT"] = "1"
    if args.disable_llm:
        os.environ["GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS"] = "1"
    else:
        os.environ.pop("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", None)

    cases = _load_json(args.cases)
    thresholds = _load_json(args.thresholds)
    if not isinstance(cases, list):
        raise ValueError("Interpretation cases file must be a JSON array.")
    if args.limit > 0:
        cases = cases[: args.limit]
    if not isinstance(thresholds, dict):
        raise ValueError("Interpretation thresholds file must be a JSON object.")

    from api.main import app

    client = TestClient(app)
    results = []
    for case in cases:
        chart_context = None
        turn_history = []
        if case.get("prior_turn"):
            prior = case["prior_turn"]
            prior_response = client.post(
                "/api/interpret",
                json={
                    "question": prior.get("question", ""),
                    "audience": prior.get("audience", "general"),
                    "use_llm": False,
                },
            )
            try:
                prior_body = prior_response.json()
            except Exception:
                prior_body = {}
            chart_context = _chart_context_from_body(prior_body)
            turn_history = [
                {
                    "role": "user",
                    "content_preview": prior.get("question", ""),
                    "chart_id": None,
                },
                {
                    "role": "assistant",
                    "content_preview": str(prior_body.get("response", ""))[:260],
                    "chart_id": (chart_context or {}).get("chart_id"),
                },
            ]
        outbound_body = {
            "question": case.get("question", ""),
            "audience": case.get("audience", "general"),
            "use_llm": not args.disable_llm,
        }
        if chart_context:
            outbound_body["chart_context"] = chart_context
            outbound_body["turn_history"] = turn_history
        start = time.perf_counter()
        response = client.post("/api/interpret", json=outbound_body)
        elapsed = time.perf_counter() - start
        try:
            body = response.json()
        except Exception:
            body = {"status": "error", "response": response.text}
        results.append(evaluate_case(case, body, response.status_code, elapsed, outbound_body))

    summary = evaluate_thresholds(results, thresholds)
    report = {
        "metadata": {
            "cases_path": str(args.cases),
            "thresholds_path": str(args.thresholds),
            "case_count": len(results),
            "llm_synthesis_enabled": not args.disable_llm,
        },
        "results": results,
        "summary": summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))

    print("Interpretation benchmark complete")
    print(f"- Cases: {len(results)}")
    print(f"- Overall score: {summary['overall_score']:.3f}")
    print(f"- Grounding coverage: {summary['grounding_coverage']:.3f}")
    print(f"- Chart context coverage: {summary['chart_context_coverage']:.3f}")
    print(f"- Median latency: {summary['median_elapsed_seconds']:.3f} s")
    print(f"- Threshold pass: {summary['passed']}")
    print(f"- Report: {args.output}")
    if args.enforce_thresholds and not summary["passed"]:
        for reason in summary["failed_reasons"]:
            print(f"  * {reason}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
