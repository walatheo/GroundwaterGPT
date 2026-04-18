#!/usr/bin/env python3
"""Phase 6 latency benchmark for the grounded-chat deterministic pipeline.

Measures the wall-clock cost of:

- ``resolve_route`` — Phase 1 router, run against the real chat.py detectors.
- ``compose_grounded_answer`` — Phase 2 composer, fed a realistic envelope.
- ``validate_explanation`` — Phase 3 explainer guardrail.
- ``build_insufficient_from_decision`` — Phase 4 refusal path.

LLM invocation is intentionally excluded — the plan's p50<4s LLM gate depends
on provider latency, which lives in production monitoring. This script gates
the deterministic half of the pipeline (target p50<1500ms) and provides a
single command to catch refactor regressions.

Run::

    python3 scripts/benchmark_grounded_chat.py
    python3 scripts/benchmark_grounded_chat.py --iterations 200
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _build_detectors() -> dict[str, Any]:
    from api.routes.chat import (
        _chart_context_from_turn_history,
        _detect_aquifer,
        _detect_location,
        _detect_locations,
        _detect_site_names,
        _is_contextual_followup,
        _is_multi_location_compare_query,
        _is_network_wide_query,
        _kb_topic_matches,
        _should_prefer_chart_context,
    )

    return {
        "should_prefer_chart_context": _should_prefer_chart_context,
        "is_contextual_followup": _is_contextual_followup,
        "chart_context_from_turn_history": _chart_context_from_turn_history,
        "detect_site_names": _detect_site_names,
        "detect_aquifer": _detect_aquifer,
        "detect_locations": _detect_locations,
        "is_multi_location_compare_query": _is_multi_location_compare_query,
        "detect_location": _detect_location,
        "is_network_wide_query": _is_network_wide_query,
        "kb_topic_matches": _kb_topic_matches,
    }


QUESTIONS = [
    "tell me about G-3336",
    "how is the Biscayne aquifer?",
    "compare Estero and Naples",
    "wells near Estero",
    "which county has the most wells?",
    "how does irrigation affect groundwater?",
    "will it rise next year?",
    "how is groundwater in Antarctica?",
    "summarize well G-5004",
]


def _sample_envelope() -> dict[str, Any]:
    return {
        "response": "G-3336 has declined 0.8 ft over the record.",
        "answer_brief": "G-3336 trends down 0.8 ft",
        "chart": {"insights": ["Monthly mean fell 0.8 ft", "No seasonal recovery since 2020"]},
        "claim_citations": [{"claim": "Decline began in 2018"}],
        "wells": [{"site_id": "G-3336", "name": "G-3336", "aquifer": "Biscayne"}],
        "sources": ["https://waterdata.usgs.gov/nwis/uv?G-3336"],
        "citation_integrity": {"passed": True},
        "follow_up_questions": ["What pumping wells are nearby?"],
    }


def _time_ms(fn: Callable[[], Any], iterations: int) -> list[float]:
    timings: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        timings.append((time.perf_counter() - t0) * 1000)
    return timings


def _summary(label: str, timings: list[float]) -> dict[str, float]:
    timings_sorted = sorted(timings)
    p50 = statistics.median(timings_sorted)
    p95 = timings_sorted[min(len(timings_sorted) - 1, int(len(timings_sorted) * 0.95))]
    p99 = timings_sorted[min(len(timings_sorted) - 1, int(len(timings_sorted) * 0.99))]
    print(
        f"  {label:30s} "
        f"n={len(timings)}  "
        f"p50={p50:7.3f}ms  p95={p95:7.3f}ms  p99={p99:7.3f}ms  "
        f"max={max(timings):7.3f}ms"
    )
    return {"p50": p50, "p95": p95, "p99": p99, "max": max(timings)}


def run(iterations: int = 100) -> dict[str, dict[str, float]]:
    """Execute all four micro-benchmarks and return their summary stats."""
    from api.routes._explainer import validate_explanation
    from api.routes._grounded_answer import GroundedAnswer, compose_grounded_answer
    from api.routes._insufficient_evidence import build_insufficient_from_decision
    from api.routes._route_decision import resolve_route

    detectors = _build_detectors()
    envelope = _sample_envelope()
    sample_answer = GroundedAnswer(
        direct_answer="G-3336 fell 0.8 ft over the record.",
        grounded_findings=["Monthly mean fell 0.8 ft since 2018."],
        supporting_evidence=[{"kind": "well", "site_id": "G-3336"}],
    )

    # Warm every code path so the first iteration doesn't pay first-call costs
    # that would distort p50 for small iteration counts.
    for q in QUESTIONS:
        d = resolve_route(q, None, [], detectors=detectors)
        compose_grounded_answer(envelope)
        validate_explanation("G-3336 fell 0.8 ft.", sample_answer)
        build_insufficient_from_decision(d, question=q)

    print(f"\nBenchmark: {iterations} iterations across {len(QUESTIONS)} questions\n")

    resolve_timings: list[float] = []
    for q in QUESTIONS:
        resolve_timings.extend(
            _time_ms(lambda q=q: resolve_route(q, None, [], detectors=detectors), iterations)
        )
    compose_timings = _time_ms(
        lambda: compose_grounded_answer(envelope), iterations * len(QUESTIONS)
    )
    validate_timings = _time_ms(
        lambda: validate_explanation("G-3336 fell 0.8 ft since 2018.", sample_answer),
        iterations * len(QUESTIONS),
    )
    refusal_decision = resolve_route(
        "will it rise next year?",
        None,
        [],
        detectors=detectors,
    )
    refusal_timings = _time_ms(
        lambda: build_insufficient_from_decision(refusal_decision, question="will it rise?"),
        iterations * len(QUESTIONS),
    )

    results = {
        "resolve_route": _summary("resolve_route", resolve_timings),
        "compose_grounded_answer": _summary("compose_grounded_answer", compose_timings),
        "validate_explanation": _summary("validate_explanation", validate_timings),
        "build_insufficient": _summary("build_insufficient_from_decision", refusal_timings),
    }

    # Gate: deterministic budget.
    total_p50 = sum(r["p50"] for r in results.values())
    print(f"\nTotal deterministic p50: {total_p50:.2f}ms  (target <1500ms)")
    status = "PASS" if total_p50 < 1500 else "FAIL"
    print(f"Status: {status}\n")
    return results


def main() -> None:
    """CLI entry point — parses --iterations and runs the benchmark."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help="Number of iterations per question (default: 100)",
    )
    args = parser.parse_args()
    run(iterations=args.iterations)


if __name__ == "__main__":
    main()
