"""Run a curated chat-response review set and save human-readable artifacts.

This is deliberately lighter than the threshold benchmarks. It exists to
capture real responses for manual review, iteration, and gap analysis.

Artifacts written per run:
  - report.json       full structured output
  - responses.jsonl   one executed turn per line
  - responses.md      readable transcript + review scaffold
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_CASES_PATH = PROJECT_ROOT / "tests" / "benchmark" / "chat_review_cases.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "chat_review"


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the chat review runner."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--label",
        type=str,
        default="",
        help="Optional suffix to make the run easier to identify.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Run only the first N cases for a quick smoke check.",
    )
    parser.add_argument(
        "--enable-llm",
        action="store_true",
        help="Request LLM synthesis by default unless a turn overrides it.",
    )
    parser.add_argument(
        "--skip-agent-init",
        action="store_true",
        help="Set GROUNDWATERGPT_SKIP_AGENT_INIT=1 before importing the app.",
    )
    return parser.parse_args()


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open() as fh:
        loaded = json.load(fh)
    if not isinstance(loaded, list):
        raise ValueError("chat review cases must be a JSON array")
    return loaded


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _chart_context_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    chart = body.get("chart") or {}
    series = chart.get("series") or []
    site_ids: list[str] = []
    for item in series:
        key = str((item or {}).get("key", "")).strip()
        if key and key != "avg" and not key.endswith("_trend") and key not in site_ids:
            site_ids.append(key)
    if not site_ids:
        return None
    return {
        "chart_id": chart.get("title")
        or f"{chart.get('chart_type', 'chart')}:{','.join(site_ids)}",
        "site_ids": site_ids,
        "chart_type": chart.get("chart_type", "comparison"),
        "summary_metrics": {
            "title": chart.get("title", ""),
            "summary": (chart.get("explainability") or {}).get("summary", ""),
            "insights": chart.get("insights", []),
            "site_ids": site_ids,
        },
    }


def _assistant_turn_entry(
    question: str, body: dict[str, Any], chart_context: dict[str, Any] | None
) -> dict[str, Any]:
    interp = body.get("interpretation_response") or {}
    grounded = body.get("grounded_answer") or {}
    wells = body.get("wells") or []
    return {
        "role": "assistant",
        "content_preview": str(
            interp.get("direct_answer")
            or grounded.get("direct_answer")
            or interp.get("interpretation")
            or body.get("answer_brief")
            or body.get("response")
            or ""
        )[:260],
        "mode": body.get("mode", ""),
        "chart_id": (chart_context or {}).get("chart_id"),
        "site_ids": (chart_context or {}).get("site_ids", []),
        "wells": [
            {
                "site_id": well.get("site_id") or well.get("id"),
                "name": well.get("name") or well.get("well_name", ""),
                "aquifer": well.get("aquifer", ""),
                "county": well.get("county", ""),
            }
            for well in wells[:8]
            if isinstance(well, dict)
        ],
        "aquifer": (body.get("aquifer_info") or {}).get("name", ""),
        "cohort_risk_level": body.get("cohort_risk_level", ""),
        "question_intent": interp.get("question_intent", ""),
        "direct_answer": str(
            grounded.get("direct_answer")
            or interp.get("direct_answer")
            or body.get("answer_brief")
            or body.get("response")
            or ""
        )[:500],
        "question_asked": question,
    }


def _turn_history_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return messages[-6:]


def _response_excerpt(body: dict[str, Any]) -> str:
    grounded = body.get("grounded_answer") or {}
    interp = body.get("interpretation_response") or {}
    text = (
        interp.get("direct_answer")
        or grounded.get("direct_answer")
        or interp.get("interpretation")
        or body.get("answer_brief")
        or body.get("response")
        or ""
    )
    return " ".join(str(text).split())[:500]


def _auto_flags(
    turn: dict[str, Any],
    body: dict[str, Any],
    *,
    status_code: int,
) -> list[str]:
    flags: list[str] = []
    grounded = body.get("grounded_answer") or {}
    interp = body.get("interpretation_response") or {}
    direct_answer = str(
        grounded.get("direct_answer")
        or interp.get("direct_answer")
        or body.get("answer_brief")
        or body.get("response")
        or ""
    )
    next_best_question = str(grounded.get("next_best_question") or "")
    combined_text = " ".join(
        part
        for part in [direct_answer, str(body.get("response") or ""), next_best_question]
        if part
    )

    if status_code != 200:
        flags.append("http_error")
    if not isinstance(grounded, dict):
        flags.append("missing_grounded_answer")
    if not body.get("answer_type") or not body.get("route_mode"):
        flags.append("missing_contract_fields")
    if isinstance(grounded, dict) and not grounded.get("direct_answer"):
        flags.append("missing_direct_answer")
    if isinstance(grounded, dict) and not grounded.get("limits"):
        flags.append("missing_limits")
    if isinstance(grounded, dict) and not grounded.get("next_best_question"):
        flags.append("missing_next_best_question")
    if turn.get("expect_interpretation_response") and not isinstance(interp, dict):
        flags.append("missing_interpretation_response")
    if turn.get("expect_chart_context"):
        grounding = interp.get("grounding_status") or {}
        if not grounding.get("uses_chart_context"):
            flags.append("lost_chart_context")
    expected_route_mode = turn.get("expected_route_mode")
    if expected_route_mode and body.get("route_mode") != expected_route_mode:
        flags.append("unexpected_route_mode")
    expected_answer_type = turn.get("expected_answer_type")
    if expected_answer_type and body.get("answer_type") != expected_answer_type:
        flags.append("unexpected_answer_type")
    for forbidden in turn.get("must_not_contain", []):
        if forbidden and forbidden.lower() in combined_text.lower():
            flags.append("contains_forbidden_text")
            break
    must_contain_any = turn.get("must_contain_any") or []
    if must_contain_any and not any(
        str(item).lower() in combined_text.lower() for item in must_contain_any
    ):
        flags.append("missing_expected_text")
    for pattern in turn.get("must_match_regex", []):
        if pattern and not re.search(pattern, combined_text, re.I):
            flags.append("missing_expected_pattern")
            break

    if turn.get("require_named_entity"):
        if not re.search(
            r"\b(?:[A-Z]-\d{3,5}|[A-Z][a-z-]+(?:\s+[A-Z][a-z-]+)*\s+[A-Z]-\d+)\b",
            combined_text,
        ):
            flags.append("missing_named_entity")
    if turn.get("require_numeric_rate"):
        if not re.search(r"\b[+-]?\d+(?:\.\d+)?\s*ft/yr\b", combined_text, re.I):
            flags.append("missing_numeric_support")
    if turn.get("require_screening_caveat"):
        if not re.search(
            r"\b(screening|not proof|not a forecast|not proof of cause|not proof of pumping|not.*depletion)\b",  # noqa: E501
            combined_text,
            re.I,
        ):
            flags.append("weak_screening_caveat")
    if turn.get("require_next_best_question") and not next_best_question:
        flags.append("missing_next_best_question")
    if body.get("route_mode") == "fallback" and (
        turn.get("require_named_entity")
        or turn.get("require_numeric_rate")
        or turn.get("expected_route_mode") in {"network", "cohort", "exact_well", "chart_followup"}
    ):
        flags.append("fell_to_fallback_when_should_be_grounded")
    return flags


def _request_payload(
    turn: dict[str, Any],
    *,
    active_chart_context: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    default_use_llm: bool,
) -> tuple[str, dict[str, Any]]:
    endpoint = str(turn.get("endpoint") or "chat").strip().lower()
    use_llm = bool(turn.get("use_llm", default_use_llm))
    turn_history = _turn_history_from_messages(messages)
    prompt = str(turn.get("prompt") or "").strip()
    if endpoint == "interpret":
        payload: dict[str, Any] = {
            "question": prompt,
            "audience": str(turn.get("audience") or "general"),
            "use_llm": use_llm,
        }
        if active_chart_context is not None:
            payload["chart_context"] = active_chart_context
        if turn_history:
            payload["turn_history"] = turn_history
        return "/api/interpret", payload

    payload = {
        "message": prompt,
        "allow_llm_synthesis": use_llm,
    }
    if active_chart_context is not None:
        payload["chart_context"] = active_chart_context
    if turn_history:
        payload["turn_history"] = turn_history
    return "/api/chat", payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _markdown_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    metadata = report.get("metadata", {})
    lines.append("# Chat Review Run")
    lines.append("")
    lines.append(f"- Run ID: `{metadata.get('run_id', '')}`")
    lines.append(f"- Cases path: `{metadata.get('cases_path', '')}`")
    lines.append(f"- Generated at: `{metadata.get('generated_at', '')}`")
    lines.append(f"- Total cases: `{metadata.get('case_count', 0)}`")
    lines.append(f"- Total turns: `{metadata.get('turn_count', 0)}`")
    lines.append(f"- LLM requested by default: `{metadata.get('default_llm', False)}`")
    lines.append("")

    summary = report.get("summary", {})
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Cases with auto flags: `{summary.get('cases_with_flags', 0)}`")
    lines.append(f"- Turns with auto flags: `{summary.get('turns_with_flags', 0)}`")
    lines.append(
        f"- Route modes seen: `{', '.join(summary.get('route_modes_seen', [])) or 'none'}`"
    )
    lines.append(
        f"- Answer types seen: `{', '.join(summary.get('answer_types_seen', [])) or 'none'}`"
    )
    lines.append("")

    for case in report.get("cases", []):
        lines.append(f"## {case['id']}")
        lines.append("")
        lines.append(f"- Category: `{case.get('category', '')}`")
        lines.append(f"- Goal: {case.get('goal', '')}")
        if case.get("case_flags"):
            lines.append(f"- Auto flags: `{', '.join(case['case_flags'])}`")
        else:
            lines.append("- Auto flags: `none`")
        lines.append("")

        for turn in case.get("turns", []):
            lines.append(f"### Turn {turn['turn_index']}")
            lines.append("")
            lines.append(f"- Endpoint: `{turn.get('endpoint', '')}`")
            lines.append(f"- Prompt: {turn.get('prompt', '')}")
            lines.append(f"- Status: `{turn.get('status_code', '')}`")
            lines.append(f"- Route mode: `{turn.get('route_mode', '')}`")
            lines.append(f"- Answer type: `{turn.get('answer_type', '')}`")
            lines.append(f"- Grounding: `{turn.get('grounding_status', '')}`")
            lines.append(f"- Mode: `{turn.get('mode', '')}`")
            if turn.get("auto_flags"):
                lines.append(f"- Auto flags: `{', '.join(turn['auto_flags'])}`")
            else:
                lines.append("- Auto flags: `none`")
            if turn.get("review_focus"):
                lines.append(f"- Review focus: `{', '.join(turn['review_focus'])}`")
            lines.append("- Manual review:")
            lines.append("  - Routing: ")
            lines.append("  - Grounding: ")
            lines.append("  - Caveat quality: ")
            lines.append("  - Usefulness: ")
            lines.append("  - Follow-up quality: ")
            lines.append("  - Failure tags: ")
            lines.append("  - Notes: ")
            lines.append("")
            lines.append("```text")
            lines.append(turn.get("response_excerpt", ""))
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    """CLI entry — runs the curated case set and writes review artifacts."""
    args = parse_args()
    if args.skip_agent_init:
        os.environ["GROUNDWATERGPT_SKIP_AGENT_INIT"] = "1"

    from api.main import app

    cases = _load_cases(args.cases)
    if args.limit > 0:
        cases = cases[: args.limit]

    run_id = _timestamp_slug()
    if args.label:
        run_id = f"{run_id}_{args.label}"
    out_dir = args.output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    client = TestClient(app)
    executed_cases: list[dict[str, Any]] = []
    jsonl_lines: list[str] = []
    route_modes_seen: set[str] = set()
    answer_types_seen: set[str] = set()
    turns_with_flags = 0

    for case in cases:
        messages: list[dict[str, Any]] = []
        active_chart_context: dict[str, Any] | None = None
        executed_turns: list[dict[str, Any]] = []

        for idx, turn in enumerate(case.get("turns", []), start=1):
            endpoint_path, payload = _request_payload(
                turn,
                active_chart_context=active_chart_context,
                messages=messages,
                default_use_llm=args.enable_llm,
            )
            started = time.perf_counter()
            response = client.post(endpoint_path, json=payload)
            elapsed = time.perf_counter() - started
            try:
                body = response.json()
            except Exception:
                body = {"status": "error", "response": response.text}

            active_chart_context = _chart_context_from_body(body) or active_chart_context
            messages.append(
                {
                    "role": "user",
                    "content_preview": str(turn.get("prompt", ""))[:260],
                    "mode": "",
                    "chart_id": None,
                    "site_ids": [],
                    "wells": [],
                    "aquifer": "",
                    "cohort_risk_level": "",
                    "question_intent": "",
                    "direct_answer": "",
                }
            )
            messages.append(
                _assistant_turn_entry(str(turn.get("prompt", "")), body, active_chart_context)
            )

            auto_flags = _auto_flags(turn, body, status_code=response.status_code)
            if auto_flags:
                turns_with_flags += 1
            route_mode = str(body.get("route_mode") or "")
            answer_type = str(body.get("answer_type") or "")
            if route_mode:
                route_modes_seen.add(route_mode)
            if answer_type:
                answer_types_seen.add(answer_type)

            executed_turn = {
                "turn_index": idx,
                "endpoint": endpoint_path,
                "prompt": turn.get("prompt", ""),
                "audience": turn.get("audience"),
                "status_code": response.status_code,
                "elapsed_seconds": round(elapsed, 3),
                "mode": body.get("mode"),
                "route_mode": route_mode,
                "answer_type": answer_type,
                "grounding_status": body.get("grounding_status"),
                "response_excerpt": _response_excerpt(body),
                "review_focus": turn.get("review_focus", []),
                "auto_flags": auto_flags,
                "request_payload": payload,
                "response_body": body,
            }
            executed_turns.append(executed_turn)
            jsonl_lines.append(
                json.dumps({"case_id": case.get("id"), **executed_turn}, default=str)
            )

        case_flags = sorted(
            {flag for turn in executed_turns for flag in turn.get("auto_flags", [])}
        )
        executed_cases.append(
            {
                "id": case.get("id"),
                "category": case.get("category", ""),
                "goal": case.get("goal", ""),
                "case_flags": case_flags,
                "turns": executed_turns,
            }
        )

    report = {
        "metadata": {
            "run_id": run_id,
            "cases_path": str(args.cases),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "case_count": len(executed_cases),
            "turn_count": sum(len(case.get("turns", [])) for case in executed_cases),
            "default_llm": args.enable_llm,
            "skip_agent_init": args.skip_agent_init,
        },
        "summary": {
            "cases_with_flags": sum(1 for case in executed_cases if case.get("case_flags")),
            "turns_with_flags": turns_with_flags,
            "route_modes_seen": sorted(route_modes_seen),
            "answer_types_seen": sorted(answer_types_seen),
        },
        "cases": executed_cases,
    }

    _write_json(out_dir / "report.json", report)
    (out_dir / "responses.jsonl").write_text("\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""))
    (out_dir / "responses.md").write_text(_markdown_report(report))

    print("Chat review complete")
    print(f"- Run ID: {run_id}")
    print(f"- Cases: {report['metadata']['case_count']}")
    print(f"- Turns: {report['metadata']['turn_count']}")
    print(f"- Cases with auto flags: {report['summary']['cases_with_flags']}")
    print(f"- Output: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
