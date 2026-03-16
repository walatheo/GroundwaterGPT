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


def evaluate_case_response(
    case: dict[str, Any],
    response: dict[str, Any],
    elapsed_seconds: float,
    status_code: int,
) -> dict[str, Any]:
    """Evaluate one benchmark case against one research response."""
    text = response_text_blob(response)
    claim_citations = response.get("claim_citations") or []
    claim_verdicts = response.get("claim_verdicts") or []
    claim_verdict_summary = response.get("claim_verdict_summary") or {}
    citation_summary = response.get("citation_summary") or {}
    citation_integrity = response.get("citation_integrity") or {}
    section_confidence = response.get("section_confidence") or {}
    sources = response.get("sources") or []

    cited_claims = 0
    for claim in claim_citations:
        if isinstance(claim, dict) and claim.get("citations"):
            cited_claims += 1
    inferred_coverage = float(cited_claims / len(claim_citations)) if claim_citations else 0.0
    claim_citation_coverage = float(citation_summary.get("citation_coverage", inferred_coverage))
    sections = (
        section_confidence.get("sections", []) if isinstance(section_confidence, dict) else []
    )
    if sections:
        cited_sections = sum(
            1 for section in sections if int(section.get("citation_count", 0) or 0) > 0
        )
        inferred_section_coverage = float(cited_sections / len(sections))
    else:
        inferred_section_coverage = 0.0
    section_citation_coverage = float(
        citation_integrity.get("section_citation_coverage", inferred_section_coverage)
    )
    claim_ids = [
        str(claim.get("claim_id", "")).strip()
        for claim in claim_citations
        if isinstance(claim, dict) and str(claim.get("claim_id", "")).strip()
    ]
    verdict_ids = {
        str(verdict.get("claim_id", "")).strip()
        for verdict in claim_verdicts
        if isinstance(verdict, dict) and str(verdict.get("claim_id", "")).strip()
    }
    matched_verdicts = sum(1 for claim_id in claim_ids if claim_id in verdict_ids)
    claim_verdict_coverage = float(matched_verdicts / len(claim_ids)) if claim_ids else 0.0
    contradicted_claims = sum(
        1
        for verdict in claim_verdicts
        if isinstance(verdict, dict) and verdict.get("verdict") == "contradicted"
    )
    high_risk_claims = sum(
        1
        for verdict in claim_verdicts
        if isinstance(verdict, dict) and float(verdict.get("risk_score", 0.0) or 0.0) >= 0.75
    )
    contradicted_claim_rate = (
        float(contradicted_claims / len(claim_verdicts)) if claim_verdicts else 0.0
    )
    high_risk_claim_rate = float(high_risk_claims / len(claim_verdicts)) if claim_verdicts else 0.0
    min_claim_coverage = float(case.get("min_claim_citation_coverage", 0.90))
    min_section_coverage = float(case.get("min_section_citation_coverage", 0.90))
    min_claim_verdict_coverage = float(case.get("min_claim_verdict_coverage", 0.95))

    check_catalog = {
        "ok_status": status_code == 200 and response.get("status") == "ok",
        "has_report": bool(str(response.get("report", "")).strip()),
        "has_sources": bool(sources),
        "has_claim_citations": bool(claim_citations),
        "has_claim_verdicts": bool(claim_verdicts)
        and all(
            isinstance(verdict, dict)
            and verdict.get("verdict") in {"supported", "contradicted", "insufficient_evidence"}
            for verdict in claim_verdicts
        ),
        "has_claim_verdict_summary": isinstance(claim_verdict_summary, dict),
        "claim_verdict_coverage_ok": claim_verdict_coverage >= min_claim_verdict_coverage,
        "has_citation_summary": isinstance(citation_summary, dict),
        "has_section_confidence": isinstance(section_confidence, dict)
        and isinstance(section_confidence.get("sections", []), list),
        "is_live_mode": response.get("mode") != "fallback",
        "claim_citation_coverage_ok": claim_citation_coverage >= min_claim_coverage,
        "section_citation_coverage_ok": section_citation_coverage >= min_section_coverage,
        "mentions_usgs": bool(USGS_RE.search(text)),
        "has_date_reference": bool(DATE_RE.search(text)),
        "has_well_id": bool(SITE_ID_RE.search(text)),
        "has_trend_language": bool(TREND_RE.search(text)),
        "has_aquifer_language": bool(AQUIFER_RE.search(text)),
        "has_implications": bool(IMPLICATIONS_RE.search(text)),
        "within_time_budget": elapsed_seconds <= float(case.get("max_seconds", 120)),
    }

    required_checks = case.get("required_checks") or [
        "ok_status",
        "has_report",
        "has_sources",
        "has_claim_citations",
        "has_trend_language",
    ]
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
        "citation_coverage": round(claim_citation_coverage, 3),
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
    avg_claim_citation_coverage = (
        statistics.mean(r["claim_citation_coverage"] for r in case_results) if case_results else 0.0
    )
    avg_section_citation_coverage = (
        statistics.mean(r["section_citation_coverage"] for r in case_results)
        if case_results
        else 0.0
    )
    avg_claim_verdict_coverage = (
        statistics.mean(r["claim_verdict_coverage"] for r in case_results) if case_results else 0.0
    )
    avg_contradicted_claim_rate = (
        statistics.mean(r["contradicted_claim_rate"] for r in case_results) if case_results else 0.0
    )
    avg_high_risk_claim_rate = (
        statistics.mean(r["high_risk_claim_rate"] for r in case_results) if case_results else 0.0
    )
    max_elapsed = max((r["elapsed_seconds"] for r in case_results), default=0.0)

    min_overall_score = float(thresholds.get("min_overall_score", 0.0))
    min_case_score = float(thresholds.get("min_case_score", 0.0))
    min_avg_citation_coverage = float(thresholds.get("min_avg_citation_coverage", 0.0))
    min_avg_claim_citation_coverage = float(
        thresholds.get("min_avg_claim_citation_coverage", min_avg_citation_coverage)
    )
    min_avg_section_citation_coverage = float(
        thresholds.get("min_avg_section_citation_coverage", 0.0)
    )
    min_avg_claim_verdict_coverage = float(thresholds.get("min_avg_claim_verdict_coverage", 0.0))
    max_avg_contradicted_claim_rate = float(thresholds.get("max_avg_contradicted_claim_rate", 1.0))
    max_avg_high_risk_claim_rate = float(thresholds.get("max_avg_high_risk_claim_rate", 1.0))
    require_live_mode = bool(thresholds.get("require_live_mode", False))
    max_response_seconds = float(thresholds.get("max_response_seconds", 9999.0))

    failed_reasons: list[str] = []
    if overall_score < min_overall_score:
        failed_reasons.append(
            f"overall_score={overall_score:.3f} < min_overall_score={min_overall_score:.3f}"
        )
    if avg_claim_citation_coverage < min_avg_claim_citation_coverage:
        coverage_reason = (
            f"{avg_claim_citation_coverage:.3f} < "
            f"min_avg_claim_citation_coverage={min_avg_claim_citation_coverage:.3f}"
        )
        failed_reasons.append(f"average_claim_citation_coverage={coverage_reason}")
    if avg_section_citation_coverage < min_avg_section_citation_coverage:
        section_reason = (
            f"{avg_section_citation_coverage:.3f} < "
            f"min_avg_section_citation_coverage={min_avg_section_citation_coverage:.3f}"
        )
        failed_reasons.append(f"average_section_citation_coverage={section_reason}")
    if avg_claim_verdict_coverage < min_avg_claim_verdict_coverage:
        verdict_reason = (
            f"{avg_claim_verdict_coverage:.3f} < "
            f"min_avg_claim_verdict_coverage={min_avg_claim_verdict_coverage:.3f}"
        )
        failed_reasons.append(f"average_claim_verdict_coverage={verdict_reason}")
    if avg_contradicted_claim_rate > max_avg_contradicted_claim_rate:
        contradicted_reason = (
            f"{avg_contradicted_claim_rate:.3f} > "
            f"max_avg_contradicted_claim_rate={max_avg_contradicted_claim_rate:.3f}"
        )
        failed_reasons.append(f"average_contradicted_claim_rate={contradicted_reason}")
    if avg_high_risk_claim_rate > max_avg_high_risk_claim_rate:
        high_risk_reason = (
            f"{avg_high_risk_claim_rate:.3f} > "
            f"max_avg_high_risk_claim_rate={max_avg_high_risk_claim_rate:.3f}"
        )
        failed_reasons.append(f"average_high_risk_claim_rate={high_risk_reason}")

    low_cases = [r["case_id"] for r in case_results if r["score"] < min_case_score]
    if low_cases:
        failed_reasons.append(
            f"case_scores below min_case_score={min_case_score:.3f}: {', '.join(low_cases)}"
        )

    if max_elapsed > max_response_seconds:
        failed_reasons.append(
            f"max_elapsed={max_elapsed:.3f}s > max_response_seconds={max_response_seconds:.3f}s"
        )
    if require_live_mode:
        fallback_cases = [r["case_id"] for r in case_results if r.get("mode") == "fallback"]
        if fallback_cases:
            failed_reasons.append(
                "live_mode_required but fallback responses observed in cases: "
                + ", ".join(fallback_cases)
            )

    return {
        "passed": not failed_reasons,
        "overall_score": round(overall_score, 3),
        "average_citation_coverage": round(avg_claim_citation_coverage, 3),
        "average_claim_citation_coverage": round(avg_claim_citation_coverage, 3),
        "average_section_citation_coverage": round(avg_section_citation_coverage, 3),
        "average_claim_verdict_coverage": round(avg_claim_verdict_coverage, 3),
        "average_contradicted_claim_rate": round(avg_contradicted_claim_rate, 3),
        "average_high_risk_claim_rate": round(avg_high_risk_claim_rate, 3),
        "max_elapsed_seconds": round(max_elapsed, 3),
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
            "require_live_mode": require_live_mode,
            "max_response_seconds": max_response_seconds,
        },
    }


def run_chat_benchmark(
    cases_path: Path = DEFAULT_CASES_PATH,
    thresholds_path: Path = DEFAULT_THRESHOLDS_PATH,
    mode: str | None = None,
) -> dict[str, Any]:
    """Execute the benchmark suite by calling the local FastAPI app."""
    cases = load_json_file(cases_path)
    thresholds = load_json_file(thresholds_path)
    if not isinstance(cases, list):
        raise ValueError("Benchmark cases file must contain a JSON array.")
    if not isinstance(thresholds, dict):
        raise ValueError("Benchmark thresholds file must contain a JSON object.")

    configured_force_fallback = bool(thresholds.get("force_fallback_mode", False))
    requested_mode = mode or ("fallback" if configured_force_fallback else "live")
    if requested_mode not in {"fallback", "live", "both"}:
        raise ValueError("mode must be one of: fallback, live, both")

    # Preserve existing behavior for deterministic fallback-only runs.
    if requested_mode == "fallback" and configured_force_fallback:
        os.environ["GROUNDWATERGPT_SKIP_AGENT_INIT"] = "1"

    from api.main import app
    from api.routes import chat as chat_routes

    original_chat_agent = chat_routes._chat_agent
    original_research_agent = chat_routes._research_agent
    client = TestClient(app)
    modes_to_run = ["fallback", "live"] if requested_mode == "both" else [requested_mode]
    mode_runs: dict[str, dict[str, Any]] = {}

    try:
        for current_mode in modes_to_run:
            if current_mode == "fallback":
                chat_routes._chat_agent = None
                chat_routes._research_agent = None
            else:
                chat_routes._chat_agent = original_chat_agent
                chat_routes._research_agent = original_research_agent

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

            mode_runs[current_mode] = {
                "results": case_results,
                "summary": evaluate_thresholds(case_results, thresholds),
            }
    finally:
        chat_routes._chat_agent = original_chat_agent
        chat_routes._research_agent = original_research_agent

    primary_mode = "fallback" if "fallback" in mode_runs else modes_to_run[0]
    primary_run = mode_runs[primary_mode]

    return {
        "metadata": {
            "cases_path": str(cases_path),
            "thresholds_path": str(thresholds_path),
            "case_count": len(primary_run["results"]),
            "requested_mode": requested_mode,
            "primary_mode": primary_mode,
        },
        "results": primary_run["results"],
        "summary": primary_run["summary"],
        "mode_runs": {
            name: {
                "summary": run["summary"],
                "case_count": len(run["results"]),
            }
            for name, run in mode_runs.items()
        },
        "threshold_policy": {
            "enforce_in_ci": bool(thresholds.get("enforce_in_ci", False)),
            "configured_force_fallback_mode": configured_force_fallback,
            "notes": thresholds.get("notes", ""),
        },
    }
