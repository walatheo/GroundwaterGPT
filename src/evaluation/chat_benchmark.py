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
    citation_summary = response.get("citation_summary") or {}
    sources = response.get("sources") or []

    cited_claims = 0
    for claim in claim_citations:
        if isinstance(claim, dict) and claim.get("citations"):
            cited_claims += 1
    inferred_coverage = float(cited_claims / len(claim_citations)) if claim_citations else 0.0
    citation_coverage = float(citation_summary.get("citation_coverage", inferred_coverage))

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
        "citation_coverage": round(citation_coverage, 3),
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
    max_elapsed = max((r["elapsed_seconds"] for r in case_results), default=0.0)

    min_overall_score = float(thresholds.get("min_overall_score", 0.0))
    min_case_score = float(thresholds.get("min_case_score", 0.0))
    min_avg_citation_coverage = float(thresholds.get("min_avg_citation_coverage", 0.0))
    max_response_seconds = float(thresholds.get("max_response_seconds", 9999.0))

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

    low_cases = [r["case_id"] for r in case_results if r["score"] < min_case_score]
    if low_cases:
        failed_reasons.append(
            f"case_scores below min_case_score={min_case_score:.3f}: {', '.join(low_cases)}"
        )

    if max_elapsed > max_response_seconds:
        failed_reasons.append(
            f"max_elapsed={max_elapsed:.3f}s > max_response_seconds={max_response_seconds:.3f}s"
        )

    return {
        "passed": not failed_reasons,
        "overall_score": round(overall_score, 3),
        "average_citation_coverage": round(avg_citation_coverage, 3),
        "max_elapsed_seconds": round(max_elapsed, 3),
        "failed_reasons": failed_reasons,
        "thresholds": {
            "min_overall_score": min_overall_score,
            "min_case_score": min_case_score,
            "min_avg_citation_coverage": min_avg_citation_coverage,
            "max_response_seconds": max_response_seconds,
        },
    }


def run_chat_benchmark(
    cases_path: Path = DEFAULT_CASES_PATH,
    thresholds_path: Path = DEFAULT_THRESHOLDS_PATH,
) -> dict[str, Any]:
    """Execute the benchmark suite by calling the local FastAPI app."""
    cases = load_json_file(cases_path)
    thresholds = load_json_file(thresholds_path)
    if not isinstance(cases, list):
        raise ValueError("Benchmark cases file must contain a JSON array.")
    if not isinstance(thresholds, dict):
        raise ValueError("Benchmark thresholds file must contain a JSON object.")

    if bool(thresholds.get("force_fallback_mode", False)):
        os.environ["GROUNDWATERGPT_SKIP_AGENT_INIT"] = "1"

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
            "case_count": len(case_results),
        },
        "results": case_results,
        "summary": threshold_eval,
        "threshold_policy": {
            "enforce_in_ci": bool(thresholds.get("enforce_in_ci", False)),
            "notes": thresholds.get("notes", ""),
        },
    }
