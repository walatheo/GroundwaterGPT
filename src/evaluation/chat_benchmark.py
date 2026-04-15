"""Automated benchmark harness for research/chat response quality."""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_PATH = PROJECT_ROOT / "tests" / "benchmark" / "chat_eval_cases.json"
DEFAULT_THRESHOLDS_PATH = PROJECT_ROOT / "tests" / "benchmark" / "chat_eval_thresholds.json"

SITE_ID_RE = re.compile(r"\b\d{15}\b")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
TREND_RE = re.compile(r"\b(rising|falling|declin\w*|increas\w*|stable|trend\w*)\b", re.I)
AQUIFER_RE = re.compile(
    r"\b(aquifer|biscayne|floridan|lower tamiami|hawthorn|upper floridan|surficial)\b",
    re.I,
)
USGS_RE = re.compile(r"\busgs\b|waterdata\.usgs\.gov|waterservices\.usgs\.gov", re.I)
IMPLICATIONS_RE = re.compile(
    r"\b(risk|sustainab\w*|intrusion|drawdown|stress\w*|management|implication\w*)\b",
    re.I,
)
WELL_DEPTH_RE = re.compile(r"\b\d+(\.\d+)?\s*(ft|feet)\b", re.I)
COORDINATES_RE = re.compile(r"\b\d{2}\.\d+°?[NS]?\b", re.I)
CONFINED_RE = re.compile(r"\b(confined|unconfined|artesian|water.table)\b", re.I)
NET_CHANGE_RE = re.compile(r"[+-]?\d+\.\d+\s*ft", re.I)
FT_YR_RE = re.compile(r"[+-]?\d+\.\d+\s*ft/yr", re.I)


def load_json_file(path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    """Load a JSON file with UTF-8 encoding."""
    with open(path) as fh:
        return json.load(fh)


def response_text_blob(response: dict[str, Any]) -> str:
    """Build a single searchable text blob from a research response."""
    report = str(response.get("report", ""))
    insights = response.get("insights", [])
    insight_text = "\n".join(
        str(item.get("content", "")) for item in insights if isinstance(item, dict)
    )
    sources = response.get("sources", [])
    source_text = "\n".join(str(source) for source in sources)
    return f"{report}\n{insight_text}\n{source_text}"


def _eval_assertions(
    text: str,
    response: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> list[tuple[str, bool]]:
    """Evaluate case-specific content assertions.

    Each assertion dict has:
      - ``type``: "contains", "not_contains", "matches_re",
                  "min_wells", "min_claims", "min_sources",
                  "expected_mode", "min_report_length"
      - ``value``: the string / pattern / int to check
      - ``label``: human-readable name for the check

    Returns list of (label, passed) tuples.
    """
    results: list[tuple[str, bool]] = []
    text_lower = text.lower()
    wells = response.get("wells") or []
    claims = response.get("claim_citations") or []
    sources = response.get("sources") or []

    for a in assertions:
        atype = a.get("type", "")
        value = a.get("value", "")
        label = a.get("label", atype)

        if atype == "contains":
            results.append((label, str(value).lower() in text_lower))
        elif atype == "not_contains":
            results.append((label, str(value).lower() not in text_lower))
        elif atype == "matches_re":
            results.append((label, bool(re.search(str(value), text, re.I))))
        elif atype == "min_wells":
            results.append((label, len(wells) >= int(value)))
        elif atype == "min_claims":
            results.append((label, len(claims) >= int(value)))
        elif atype == "min_sources":
            results.append((label, len(sources) >= int(value)))
        elif atype == "expected_mode":
            results.append((label, response.get("mode") == str(value)))
        elif atype == "min_report_length":
            report = str(response.get("report", ""))
            results.append((label, len(report) >= int(value)))
        elif atype == "has_net_change":
            results.append((label, bool(NET_CHANGE_RE.search(text))))
        elif atype == "has_annual_rate":
            results.append((label, bool(FT_YR_RE.search(text))))
        elif atype == "has_cross_well":
            results.append(
                (
                    label,
                    "cross-well" in text_lower or "cohort" in text_lower,
                )
            )
        elif atype == "has_divergent_pairs":
            dp = response.get("divergent_pairs") or []
            results.append((label, len(dp) >= int(value or 1)))
        elif atype == "has_aquifer_grouping":
            # Response contains aquifer section headers (## Aquifer Name)
            n_headers = len(re.findall(r"##\s+\w.*(?:Aquifer|Hawthorn|Floridan|Surficial)", text))
            results.append((label, n_headers >= int(value or 2)))
        elif atype == "has_cross_aquifer":
            results.append(
                (
                    label,
                    "cross-aquifer" in text_lower
                    or ("shallow" in text_lower and "deep" in text_lower),
                )
            )
        elif atype == "has_period_transparency":
            results.append(
                (
                    label,
                    "requested period" in text_lower
                    or "available usgs record" in text_lower
                    or re.search(r"\d+.{0,5}years?\b.*\brecord", text_lower) is not None,
                )
            )
        elif atype == "has_supply_context":
            results.append(
                (
                    label,
                    "water supply" in text_lower
                    and "utility" in text_lower.replace("utilities", "utility"),
                )
            )
        elif atype == "has_implications":
            results.append(
                (
                    label,
                    bool(IMPLICATIONS_RE.search(text)),
                )
            )
        elif atype == "has_proxy_justification":
            # Contains distance/direction proxy text like "X.X mi NNE"
            results.append(
                (
                    label,
                    bool(re.search(r"\d+\.\d+\s*mi\s+[NSEW]{1,3}", text)),
                )
            )
        elif atype == "has_guardrail":
            guardrail = response.get("hallucination_guardrail") or {}
            results.append(
                (
                    label,
                    isinstance(guardrail, dict) and "all_factual_claims_cited" in guardrail,
                )
            )
        elif atype == "has_citation_integrity":
            ci = response.get("citation_integrity") or {}
            results.append((label, isinstance(ci, dict) and "passed" in ci))
        elif atype == "guardrail_all_cited":
            guardrail = response.get("hallucination_guardrail") or {}
            results.append((label, guardrail.get("all_factual_claims_cited") is True))

    return results


def evaluate_case_response(
    case: dict[str, Any],
    response: dict[str, Any],
    elapsed_seconds: float,
    status_code: int,
) -> dict[str, Any]:
    """Evaluate one benchmark case against one research response."""
    text = response_text_blob(response)
    claim_citations = response.get("claim_citations") or []
    citation_summary = response.get("citation_summary") or {}
    citation_integrity = response.get("citation_integrity") or {}
    claim_verdict_summary = response.get("claim_verdict_summary") or {}
    sources = response.get("sources") or []

    cited_claims = 0
    for claim in claim_citations:
        if isinstance(claim, dict) and claim.get("citations"):
            cited_claims += 1
    inferred_coverage = float(cited_claims / len(claim_citations)) if claim_citations else 0.0
    citation_coverage = float(citation_summary.get("citation_coverage", inferred_coverage))
    claim_citation_coverage = float(
        citation_integrity.get(
            "claim_citation_coverage",
            citation_summary.get("citation_coverage", inferred_coverage),
        )
    )
    section_citation_coverage = float(
        citation_integrity.get(
            "section_citation_coverage",
            1.0 if citation_integrity.get("passed") is True else 0.0,
        )
    )
    total_verdict_claims = float(claim_verdict_summary.get("total_claims", 0) or 0)
    verdict_claims = (
        float(claim_verdict_summary.get("supported_claims", 0) or 0)
        + float(claim_verdict_summary.get("contradicted_claims", 0) or 0)
        + float(claim_verdict_summary.get("insufficient_evidence_claims", 0) or 0)
    )
    claim_verdict_coverage = verdict_claims / total_verdict_claims if total_verdict_claims else 0.0
    contradicted_claim_rate = float(
        claim_verdict_summary.get("contradicted_claim_rate", 0.0) or 0.0
    )
    high_risk_claim_rate = float(claim_verdict_summary.get("high_risk_claim_rate", 0.0) or 0.0)

    check_catalog = {
        "ok_status": status_code == 200 and response.get("status") == "ok",
        "has_report": bool(str(response.get("report", "")).strip()),
        "has_sources": bool(sources),
        "has_claim_citations": bool(claim_citations),
        "has_citation_summary": isinstance(citation_summary, dict),
        "mentions_usgs": bool(USGS_RE.search(text)),
        "has_date_reference": bool(DATE_RE.search(text)),
        "has_well_id": bool(SITE_ID_RE.search(text)),
        "has_trend_language": bool(TREND_RE.search(text)),
        "has_aquifer_language": bool(AQUIFER_RE.search(text)),
        "has_implications": bool(IMPLICATIONS_RE.search(text)),
        "has_well_depth": bool(WELL_DEPTH_RE.search(text)),
        "has_coordinates": bool(COORDINATES_RE.search(text)),
        "has_confined_language": bool(CONFINED_RE.search(text)),
        "within_time_budget": elapsed_seconds <= float(case.get("max_seconds", 120)),
    }

    # --- Case-specific content assertions ---
    assertions = case.get("assertions") or []
    assertion_results = _eval_assertions(text, response, assertions)
    for label, passed in assertion_results:
        check_catalog[label] = passed

    required_checks = case.get("required_checks") or [
        "ok_status",
        "has_report",
        "has_sources",
        "has_claim_citations",
        "has_trend_language",
    ]
    # Assertion labels are auto-required when present
    required_checks = list(required_checks) + [label for label, _ in assertion_results]

    passed = [name for name in required_checks if check_catalog.get(name)]
    failed = [name for name in required_checks if not check_catalog.get(name)]

    score = float(len(passed) / len(required_checks)) if required_checks else 0.0

    return {
        "case_id": case.get("id"),
        "level": case.get("level"),
        "question": case.get("question"),
        "mode": response.get("mode", "unknown"),
        "status_code": status_code,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "score": round(score, 3),
        "required_checks": required_checks,
        "passed_checks": passed,
        "failed_checks": failed,
        "checks": check_catalog,
        "citation_coverage": round(citation_coverage, 3),
        "claim_citation_coverage": round(claim_citation_coverage, 3),
        "section_citation_coverage": round(section_citation_coverage, 3),
        "claim_verdict_coverage": round(claim_verdict_coverage, 3),
        "contradicted_claim_rate": round(contradicted_claim_rate, 3),
        "high_risk_claim_rate": round(high_risk_claim_rate, 3),
    }


def evaluate_thresholds(
    case_results: list[dict[str, Any]],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate aggregate benchmark results against configured thresholds."""
    overall_score = statistics.mean(r["score"] for r in case_results) if case_results else 0.0
    avg_citation_coverage = (
        statistics.mean(r["citation_coverage"] for r in case_results) if case_results else 0.0
    )
    avg_claim_citation_coverage = (
        statistics.mean(r.get("claim_citation_coverage", 0.0) for r in case_results)
        if case_results
        else 0.0
    )
    avg_section_citation_coverage = (
        statistics.mean(r.get("section_citation_coverage", 0.0) for r in case_results)
        if case_results
        else 0.0
    )
    avg_claim_verdict_coverage = (
        statistics.mean(r.get("claim_verdict_coverage", 0.0) for r in case_results)
        if case_results
        else 0.0
    )
    avg_contradicted_claim_rate = (
        statistics.mean(r.get("contradicted_claim_rate", 0.0) for r in case_results)
        if case_results
        else 0.0
    )
    avg_high_risk_claim_rate = (
        statistics.mean(r.get("high_risk_claim_rate", 0.0) for r in case_results)
        if case_results
        else 0.0
    )
    max_elapsed = max((r["elapsed_seconds"] for r in case_results), default=0.0)
    median_elapsed = (
        statistics.median(r["elapsed_seconds"] for r in case_results) if case_results else 0.0
    )

    min_overall_score = float(thresholds.get("min_overall_score", 0.0))
    min_case_score = float(thresholds.get("min_case_score", 0.0))
    min_avg_citation_coverage = float(thresholds.get("min_avg_citation_coverage", 0.0))
    min_avg_claim_citation_coverage = float(thresholds.get("min_avg_claim_citation_coverage", 0.0))
    min_avg_section_citation_coverage = float(
        thresholds.get("min_avg_section_citation_coverage", 0.0)
    )
    min_avg_claim_verdict_coverage = float(thresholds.get("min_avg_claim_verdict_coverage", 0.0))
    max_avg_contradicted_claim_rate = float(thresholds.get("max_avg_contradicted_claim_rate", 1.0))
    max_avg_high_risk_claim_rate = float(thresholds.get("max_avg_high_risk_claim_rate", 1.0))
    max_response_seconds = float(thresholds.get("max_response_seconds", 9999.0))
    max_median_seconds = float(thresholds.get("max_median_seconds", 9999.0))
    require_live_mode = bool(thresholds.get("require_live_mode", False))

    failed_reasons: list[str] = []
    if overall_score < min_overall_score:
        failed_reasons.append(
            f"overall_score={overall_score:.3f} < min_overall_score={min_overall_score:.3f}"
        )
    if avg_citation_coverage < min_avg_citation_coverage:
        coverage_reason = (
            f"{avg_citation_coverage:.3f} < "
            f"min_avg_citation_coverage={min_avg_citation_coverage:.3f}"
        )
        failed_reasons.append(f"average_citation_coverage={coverage_reason}")
    if avg_claim_citation_coverage < min_avg_claim_citation_coverage:
        failed_reasons.append(
            "average_claim_citation_coverage="
            f"{avg_claim_citation_coverage:.3f} < "
            f"min_avg_claim_citation_coverage={min_avg_claim_citation_coverage:.3f}"
        )
    if avg_section_citation_coverage < min_avg_section_citation_coverage:
        failed_reasons.append(
            "average_section_citation_coverage="
            f"{avg_section_citation_coverage:.3f} < "
            f"min_avg_section_citation_coverage={min_avg_section_citation_coverage:.3f}"
        )
    if avg_claim_verdict_coverage < min_avg_claim_verdict_coverage:
        failed_reasons.append(
            "average_claim_verdict_coverage="
            f"{avg_claim_verdict_coverage:.3f} < "
            f"min_avg_claim_verdict_coverage={min_avg_claim_verdict_coverage:.3f}"
        )
    if avg_contradicted_claim_rate > max_avg_contradicted_claim_rate:
        failed_reasons.append(
            "average_contradicted_claim_rate="
            f"{avg_contradicted_claim_rate:.3f} > "
            f"max_avg_contradicted_claim_rate={max_avg_contradicted_claim_rate:.3f}"
        )
    if avg_high_risk_claim_rate > max_avg_high_risk_claim_rate:
        failed_reasons.append(
            "average_high_risk_claim_rate="
            f"{avg_high_risk_claim_rate:.3f} > "
            f"max_avg_high_risk_claim_rate={max_avg_high_risk_claim_rate:.3f}"
        )

    low_cases = [r["case_id"] for r in case_results if r["score"] < min_case_score]
    if low_cases:
        failed_reasons.append(
            f"case_scores below min_case_score={min_case_score:.3f}: {', '.join(low_cases)}"
        )

    if max_elapsed > max_response_seconds:
        failed_reasons.append(
            f"max_elapsed={max_elapsed:.3f}s > max_response_seconds={max_response_seconds:.3f}s"
        )
    if median_elapsed > max_median_seconds:
        failed_reasons.append(
            f"median_elapsed={median_elapsed:.3f}s > "
            f"max_median_seconds={max_median_seconds:.3f}s"
        )
    if require_live_mode:
        fallback_cases = [
            r["case_id"] for r in case_results if "fallback" in str(r.get("mode", "")).lower()
        ]
        if fallback_cases:
            failed_reasons.append(
                "require_live_mode=true but fallback responses were returned: "
                + ", ".join(fallback_cases[:10])
                + (" ..." if len(fallback_cases) > 10 else "")
            )

    return {
        "passed": not failed_reasons,
        "overall_score": round(overall_score, 3),
        "average_citation_coverage": round(avg_citation_coverage, 3),
        "average_claim_citation_coverage": round(avg_claim_citation_coverage, 3),
        "average_section_citation_coverage": round(avg_section_citation_coverage, 3),
        "average_claim_verdict_coverage": round(avg_claim_verdict_coverage, 3),
        "average_contradicted_claim_rate": round(avg_contradicted_claim_rate, 3),
        "average_high_risk_claim_rate": round(avg_high_risk_claim_rate, 3),
        "max_elapsed_seconds": round(max_elapsed, 3),
        "median_elapsed_seconds": round(median_elapsed, 3),
        "failed_reasons": failed_reasons,
        "thresholds": {
            "min_overall_score": min_overall_score,
            "min_case_score": min_case_score,
            "min_avg_citation_coverage": min_avg_citation_coverage,
            "min_avg_claim_citation_coverage": min_avg_claim_citation_coverage,
            "min_avg_section_citation_coverage": min_avg_section_citation_coverage,
            "min_avg_claim_verdict_coverage": min_avg_claim_verdict_coverage,
            "max_avg_contradicted_claim_rate": max_avg_contradicted_claim_rate,
            "max_avg_high_risk_claim_rate": max_avg_high_risk_claim_rate,
            "max_response_seconds": max_response_seconds,
            "max_median_seconds": max_median_seconds,
            "require_live_mode": require_live_mode,
        },
    }


def run_chat_benchmark(
    cases_path: Path = DEFAULT_CASES_PATH,
    thresholds_path: Path = DEFAULT_THRESHOLDS_PATH,
    mode: str = "auto",
) -> dict[str, Any]:
    """Execute the benchmark suite by calling the local FastAPI app."""
    cases = load_json_file(cases_path)
    thresholds = load_json_file(thresholds_path)
    if not isinstance(cases, list):
        raise ValueError("Benchmark cases file must contain a JSON array.")
    if not isinstance(thresholds, dict):
        raise ValueError("Benchmark thresholds file must contain a JSON object.")
    if mode not in {"auto", "fallback", "live"}:
        raise ValueError("mode must be one of: auto, fallback, live")

    thresholds = dict(thresholds)
    if mode == "fallback":
        thresholds["force_fallback_mode"] = True
        thresholds["require_live_mode"] = False
    elif mode == "live":
        thresholds["force_fallback_mode"] = False

    if bool(thresholds.get("force_fallback_mode", False)):
        os.environ["GROUNDWATERGPT_SKIP_AGENT_INIT"] = "1"
    elif mode == "live":
        os.environ.pop("GROUNDWATERGPT_SKIP_AGENT_INIT", None)

    from api.main import app

    force_fallback = bool(thresholds.get("force_fallback_mode", False))
    if force_fallback:
        from api.routes import chat as chat_routes

        chat_routes._research_agent = None
        chat_routes._chat_agent = None

    client = TestClient(app)
    case_results: list[dict[str, Any]] = []

    for case in cases:
        question = str(case.get("question", "")).strip()
        if not question:
            continue

        payload = {
            "question": question,
            "max_depth": int(case.get("max_depth", 3)),
            "timeout": float(case.get("timeout", 120)),
        }

        start = time.perf_counter()
        resp = client.post("/api/research", json=payload)
        elapsed = time.perf_counter() - start

        body: dict[str, Any]
        try:
            parsed = resp.json()
            body = parsed if isinstance(parsed, dict) else {"report": str(parsed)}
        except Exception:
            body = {"report": resp.text, "status": "error", "mode": "unknown"}

        case_results.append(
            evaluate_case_response(
                case=case,
                response=body,
                elapsed_seconds=elapsed,
                status_code=resp.status_code,
            )
        )

    threshold_eval = evaluate_thresholds(case_results, thresholds)
    return {
        "metadata": {
            "cases_path": str(cases_path),
            "thresholds_path": str(thresholds_path),
            "mode": mode,
            "case_count": len(case_results),
        },
        "results": case_results,
        "summary": threshold_eval,
        "threshold_policy": {
            "enforce_in_ci": bool(thresholds.get("enforce_in_ci", False)),
            "notes": thresholds.get("notes", ""),
        },
    }
