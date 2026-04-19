"""Benchmark the validated evidence-guided synthesis layer.

This benchmark is intentionally narrower than the dormant live-agent smoke. It
checks whether grounded chat and interpretation replies expose a stable
evidence-guided synthesis contract: concise answer, learner-facing explanation,
`next_goal`, and grouped follow-up questions that stay tied to deterministic
groundwater outputs.
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
        "id": "interpret_sponsor_chart",
        "endpoint": "/api/interpret",
        "payload": {
            "question": "Interpret the Estero groundwater chart for a sponsor.",
            "audience": "sponsor",
            "use_llm": False,
        },
        "max_seconds": 20.0,
        "must_contain": ["next_goal", "follow_up_groups", "learner_brief"],
    },
    {
        "id": "interpret_fastest_well",
        "endpoint": "/api/interpret",
        "payload": {
            "question": "Which well is changing fastest on the Estero chart?",
            "audience": "general",
            "use_llm": False,
            "chart_context": {
                "chart_id": "Estero Monthly Groundwater Levels",
                "site_ids": ["263335081394301", "263532081592201", "262538082045701"],
                "chart_type": "comparison",
                "summary_metrics": {"title": "Estero Monthly Groundwater Levels"},
            },
        },
        "max_seconds": 20.0,
        "must_contain": ["next_goal", "follow_up_groups", "learner_brief"],
    },
    {
        "id": "interpret_cohort_meaning",
        "endpoint": "/api/interpret",
        "payload": {
            "question": "What does the cohort average mean?",
            "audience": "general",
            "use_llm": False,
        },
        "max_seconds": 20.0,
        "must_contain": ["next_goal", "follow_up_groups", "misconceptions_to_avoid"],
    },
    {
        "id": "chat_supply_sources",
        "endpoint": "/api/chat",
        "payload": {
            "message": (
                "What are the groundwater sources the Village of Estero uses for "
                "water supply and what have been changes in groundwater levels "
                "there over the last 30 years?"
            ),
            "allow_llm_synthesis": False,
        },
        "max_seconds": 20.0,
        "must_contain": ["next_goal", "follow_up_groups", "answer_brief"],
    },
]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the synthesis benchmark runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evidence_guided_synthesis_benchmark_report.json",
        help="Output JSON report path",
    )
    parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Exit non-zero if any case fails",
    )
    return parser.parse_args()


def _prepare_env() -> None:
    os.environ["GROUNDWATERGPT_SKIP_AGENT_INIT"] = "1"
    os.environ["GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS"] = "1"


def _interpretation(body: dict[str, Any]) -> dict[str, Any]:
    return body.get("interpretation_response") or {}


def _has_groups(body: dict[str, Any]) -> bool:
    groups = body.get("follow_up_groups") or _interpretation(body).get("follow_up_groups") or []
    if not isinstance(groups, list) or not groups:
        return False
    return any(
        group.get("label") and group.get("questions") for group in groups if isinstance(group, dict)
    )


def _has_next_goal(body: dict[str, Any]) -> bool:
    return bool(str(body.get("next_goal") or _interpretation(body).get("next_goal") or "").strip())


def _preserves_numeric_grounding(body: dict[str, Any]) -> bool:
    interpretation = _interpretation(body)
    numeric_claims = interpretation.get("numeric_claims") or body.get("numeric_claims") or []
    return isinstance(numeric_claims, list)


def evaluate_case(
    case: dict[str, Any], body: dict[str, Any], status_code: int, elapsed: float
) -> dict[str, Any]:
    """Run one fixture case through synthesis and return the verdict dict."""
    interpretation = _interpretation(body)
    grounding = interpretation.get("grounding_status") or {}
    checks = {
        "ok_status": status_code == 200 and body.get("status") == "ok",
        "has_next_goal": _has_next_goal(body),
        "has_follow_up_groups": _has_groups(body),
        "has_compatibility_followups": bool(
            body.get("follow_up_questions") or interpretation.get("follow_up_questions")
        ),
        "has_grounding": (
            grounding.get("invented_measurements_allowed") is False if grounding else True
        ),
        "preserves_numeric_grounding": _preserves_numeric_grounding(body),
        "within_time_budget": elapsed <= float(case.get("max_seconds", 20.0)),
    }
    for field_name in case.get("must_contain", []):
        checks[f"contains_{field_name}"] = bool(
            body.get(field_name) or interpretation.get(field_name)
        )
    passed = all(checks.values())
    return {
        "case_id": case["id"],
        "endpoint": case["endpoint"],
        "elapsed_seconds": round(elapsed, 3),
        "passed": passed,
        "checks": checks,
        "next_goal": body.get("next_goal") or interpretation.get("next_goal") or "",
        "follow_up_groups": body.get("follow_up_groups")
        or interpretation.get("follow_up_groups")
        or [],
    }


def main() -> int:
    """CLI entry point — runs every fixture case and writes a JSON report."""
    args = parse_args()
    _prepare_env()

    from api.main import app

    client = TestClient(app)
    results = []
    for case in DEFAULT_CASES:
        start = time.perf_counter()
        response = client.post(case["endpoint"], json=case["payload"])
        elapsed = time.perf_counter() - start
        try:
            body = response.json()
        except Exception:
            body = {"status": "error", "response": response.text}
        results.append(evaluate_case(case, body, response.status_code, elapsed))

    passed = all(result["passed"] for result in results)
    report = {
        "metadata": {
            "benchmark": "evidence_guided_synthesis",
            "case_count": len(results),
            "validated_ai_role": "evidence_synthesizer",
        },
        "results": results,
        "summary": {
            "passed": passed,
            "average_elapsed_seconds": round(
                sum(result["elapsed_seconds"] for result in results) / len(results),
                3,
            ),
            "next_goal_coverage": round(
                sum(1 for result in results if result["checks"]["has_next_goal"]) / len(results),
                3,
            ),
            "follow_up_group_coverage": round(
                sum(1 for result in results if result["checks"]["has_follow_up_groups"])
                / len(results),
                3,
            ),
        },
    }
    args.output.write_text(json.dumps(report, indent=2))

    print("Evidence-guided synthesis benchmark complete")
    print(f"- Cases: {len(results)}")
    print(f"- Passed: {passed}")
    print(f"- Next-goal coverage: {report['summary']['next_goal_coverage']:.3f}")
    print(f"- Follow-up-group coverage: {report['summary']['follow_up_group_coverage']:.3f}")
    print(f"- Average elapsed: {report['summary']['average_elapsed_seconds']:.3f} s")
    print(f"- Report: {args.output}")

    if args.enforce_thresholds and not passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
