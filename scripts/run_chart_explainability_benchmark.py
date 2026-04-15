"""Benchmark the hybrid chart-explainability LLM path.

This is intentionally narrower than ``run_agent_benchmark.py``. It keeps the
DeepResearchAgent disabled for demo stability, routes questions through the
deterministic USGS chart pipeline, and verifies that optional Ollama narration
can explain the chart without becoming the source of measured facts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CASES = [
    {
        "id": "chart_llm_estero_student",
        "message": "Interpret Estero groundwater chart risk like I am a student.",
        "max_seconds": 150.0,
    }
]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "chart_llm_benchmark_report.json",
        help="Output JSON report path",
    )
    parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Exit non-zero if the chart LLM smoke fails",
    )
    return parser.parse_args()


def _prepare_env() -> None:
    """Pin runtime to deterministic routing with hybrid LLM narration enabled."""
    os.environ["GROUNDWATERGPT_SKIP_AGENT_INIT"] = "1"
    os.environ.pop("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", None)
    os.environ.setdefault("SYNTHESIS_MODEL", "llama3.2")


def _coverage(body: dict[str, Any]) -> float:
    citation_summary = body.get("citation_summary") or {}
    try:
        return float(citation_summary.get("citation_coverage", 0.0))
    except (TypeError, ValueError):
        return 0.0


def evaluate_case(
    case: dict[str, Any], body: dict[str, Any], status_code: int, elapsed: float
) -> dict:
    """Evaluate one chart-explainability response."""
    chart = body.get("chart") or {}
    explainability = chart.get("explainability") or {}
    guardrail = body.get("hallucination_guardrail") or {}
    claim_verdict_summary = body.get("claim_verdict_summary") or {}
    total_claims = int(claim_verdict_summary.get("total_claims", 0) or 0)
    verdict_count = (
        int(claim_verdict_summary.get("supported_claims", 0) or 0)
        + int(claim_verdict_summary.get("contradicted_claims", 0) or 0)
        + int(claim_verdict_summary.get("insufficient_evidence_claims", 0) or 0)
    )
    verdict_coverage = float(verdict_count / total_claims) if total_claims else 0.0

    checks = {
        "ok_status": status_code == 200 and body.get("status") == "ok",
        "has_chart": bool(chart.get("data") and chart.get("series")),
        "has_chart_explainability": bool(explainability.get("summary")),
        "has_student_prompts": bool(explainability.get("student_prompts")),
        "has_llm_synthesis": bool(body.get("llm_synthesis")),
        "guardrail_all_cited": guardrail.get("all_factual_claims_cited") is True,
        "citation_coverage": _coverage(body) >= 0.9,
        "claim_verdict_coverage": verdict_coverage >= 0.95,
        "within_time_budget": elapsed <= float(case.get("max_seconds", 90.0)),
    }
    passed = all(checks.values())
    return {
        "case_id": case["id"],
        "message": case["message"],
        "mode": body.get("mode", "unknown"),
        "status_code": status_code,
        "elapsed_seconds": round(elapsed, 3),
        "passed": passed,
        "checks": checks,
        "citation_coverage": round(_coverage(body), 3),
        "claim_verdict_coverage": round(verdict_coverage, 3),
        "llm_synthesis_preview": str(body.get("llm_synthesis", ""))[:300],
    }


def main() -> int:
    """Run the benchmark."""
    args = parse_args()
    _prepare_env()

    from api.main import app

    client = TestClient(app)
    results = []
    for case in DEFAULT_CASES:
        start = time.perf_counter()
        resp = client.post("/api/chat", json={"message": case["message"]})
        elapsed = time.perf_counter() - start
        try:
            body = resp.json()
        except Exception:
            body = {"status": "error", "response": resp.text}
        results.append(evaluate_case(case, body, resp.status_code, elapsed))

    passed = all(result["passed"] for result in results)
    report = {
        "metadata": {
            "benchmark": "chart_explainability_llm",
            "synthesis_model": os.environ.get("SYNTHESIS_MODEL", "llama3.2"),
            "case_count": len(results),
        },
        "results": results,
        "summary": {
            "passed": passed,
            "average_elapsed_seconds": round(
                sum(r["elapsed_seconds"] for r in results) / len(results),
                3,
            ),
            "llm_synthesis_coverage": round(
                sum(1 for r in results if r["checks"]["has_llm_synthesis"]) / len(results),
                3,
            ),
            "chart_explainability_coverage": round(
                sum(1 for r in results if r["checks"]["has_chart_explainability"]) / len(results),
                3,
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))

    print("Chart LLM benchmark complete")
    print(f"- Cases: {len(results)}")
    print(f"- Passed: {passed}")
    print(f"- LLM synthesis coverage: {report['summary']['llm_synthesis_coverage']:.3f}")
    print(
        "- Chart explainability coverage: "
        f"{report['summary']['chart_explainability_coverage']:.3f}"
    )
    print(f"- Average elapsed: {report['summary']['average_elapsed_seconds']:.3f} s")
    print(f"- Report: {args.output}")

    if args.enforce_thresholds and not passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
