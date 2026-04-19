#!/usr/bin/env python3
"""User-acceptance walkthrough for the grounded-chat product.

Runs each case in ``tests/edge_cases/user_acceptance_cases.json`` against
the live ``/api/chat`` endpoint (in-process via FastAPI's TestClient — no
server needed) and evaluates a set of invariants on the response.

Output:

- Colored terminal report: per-case summary with one line per invariant.
- JSON ledger written to ``tests/edge_cases/uat_ledger/<timestamp>.json``
  containing the full response payloads + verdicts. Diff two ledgers to
  see how answers evolve between iterations.

Run::

    python3 scripts/run_user_acceptance.py
    python3 scripts/run_user_acceptance.py --case ew_g3336
    python3 scripts/run_user_acceptance.py --no-ledger
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CASES_PATH = PROJECT_ROOT / "tests" / "edge_cases" / "user_acceptance_cases.json"
LEDGER_DIR = PROJECT_ROOT / "tests" / "edge_cases" / "uat_ledger"


# ---------------------------------------------------------------------------
# ANSI color helpers — kept tiny and dependency-free.
# ---------------------------------------------------------------------------


class Color:
    """Minimal ANSI color codes for terminal output."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"


def _green(text: str) -> str:
    return f"{Color.GREEN}{text}{Color.RESET}"


def _red(text: str) -> str:
    return f"{Color.RED}{text}{Color.RESET}"


def _yellow(text: str) -> str:
    return f"{Color.YELLOW}{text}{Color.RESET}"


def _cyan(text: str) -> str:
    return f"{Color.CYAN}{text}{Color.RESET}"


def _bold(text: str) -> str:
    return f"{Color.BOLD}{text}{Color.RESET}"


# ---------------------------------------------------------------------------
# Invariant evaluation.
# ---------------------------------------------------------------------------


@dataclass
class InvariantResult:
    """Verdict for one invariant on one case."""

    name: str
    passed: bool
    detail: str


@dataclass
class CaseResult:
    """Per-case rollup: the response payload plus per-invariant verdicts."""

    case_id: str
    category: str
    question: str
    response: dict[str, Any]
    invariants: list[InvariantResult] = field(default_factory=list)
    error: str | None = None

    @property
    def all_passed(self) -> bool:
        """True when every invariant passed and no transport error fired."""
        return self.error is None and all(inv.passed for inv in self.invariants)


def _as_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(v) for v in value}
    return {str(value)}


def _check_route_mode(want: Any, response: dict[str, Any]) -> InvariantResult:
    got = response.get("route_mode")
    allowed = _as_set(want)
    return InvariantResult(
        "route_mode",
        got in allowed,
        f"want one of {sorted(allowed)} got {got!r}",
    )


def _check_grounding_status(want: Any, response: dict[str, Any]) -> InvariantResult:
    got = response.get("grounding_status")
    allowed = _as_set(want)
    return InvariantResult(
        "grounding_status",
        got in allowed,
        f"want one of {sorted(allowed)} got {got!r}",
    )


def _check_answer_type(want: Any, response: dict[str, Any]) -> InvariantResult:
    got = response.get("answer_type")
    allowed = _as_set(want)
    return InvariantResult(
        "answer_type",
        got in allowed,
        f"want one of {sorted(allowed)} got {got!r}",
    )


def _response_text(response: dict[str, Any]) -> str:
    parts = [
        response.get("response") or "",
        response.get("answer_brief") or "",
        json.dumps(response.get("grounded_answer") or {}),
    ]
    return " ".join(parts).lower()


def _check_must_mention(want: list[str], response: dict[str, Any]) -> InvariantResult:
    text = _response_text(response)
    missing = [token for token in want if token.lower() not in text]
    return InvariantResult(
        "must_mention",
        not missing,
        "all present" if not missing else f"missing: {missing}",
    )


def _check_must_mention_one_of(want: list[str], response: dict[str, Any]) -> InvariantResult:
    text = _response_text(response)
    hits = [token for token in want if token.lower() in text]
    return InvariantResult(
        "must_mention_one_of",
        bool(hits),
        f"matched: {hits}" if hits else f"none of {want} present",
    )


def _check_must_not_mention(want: list[str], response: dict[str, Any]) -> InvariantResult:
    text = _response_text(response)
    leaks = [token for token in want if token.lower() in text]
    return InvariantResult(
        "must_not_mention",
        not leaks,
        "clean" if not leaks else f"leaked: {leaks}",
    )


def _check_min_sources(want: int, response: dict[str, Any]) -> InvariantResult:
    sources = response.get("sources") or []
    got = len(sources)
    return InvariantResult(
        "min_sources",
        got >= want,
        f"want >= {want} got {got}",
    )


def _check_max_sources(want: int, response: dict[str, Any]) -> InvariantResult:
    sources = response.get("sources") or []
    got = len(sources)
    return InvariantResult(
        "max_sources",
        got <= want,
        f"want <= {want} got {got}",
    )


def _check_requires_chart(want: bool, response: dict[str, Any]) -> InvariantResult:
    chart = response.get("chart")
    has_chart = bool(chart)
    return InvariantResult(
        "requires_chart",
        has_chart == bool(want),
        f"want chart={want} got chart={has_chart}",
    )


def _check_requires_wells(want: bool, response: dict[str, Any]) -> InvariantResult:
    wells = response.get("wells") or []
    has_wells = bool(wells)
    return InvariantResult(
        "requires_wells",
        has_wells == bool(want),
        f"want wells={want} got n_wells={len(wells)}",
    )


_CHECKERS = {
    "route_mode": _check_route_mode,
    "grounding_status": _check_grounding_status,
    "answer_type": _check_answer_type,
    "must_mention": _check_must_mention,
    "must_mention_one_of": _check_must_mention_one_of,
    "must_not_mention": _check_must_not_mention,
    "min_sources": _check_min_sources,
    "max_sources": _check_max_sources,
    "requires_chart": _check_requires_chart,
    "requires_wells": _check_requires_wells,
}


def evaluate_invariants(
    invariants: dict[str, Any], response: dict[str, Any]
) -> list[InvariantResult]:
    """Run every declared invariant against ``response`` and return verdicts."""
    results: list[InvariantResult] = []
    for name, want in invariants.items():
        checker = _CHECKERS.get(name)
        if checker is None:
            results.append(InvariantResult(name, False, f"unknown invariant {name!r}"))
            continue
        results.append(checker(want, response))
    return results


# ---------------------------------------------------------------------------
# Runner.
# ---------------------------------------------------------------------------


def _build_client():
    """Build an in-process FastAPI TestClient against the chat router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes.chat import router as chat_router

    app = FastAPI()
    app.include_router(chat_router)
    return TestClient(app)


def run_case(client, case: dict[str, Any]) -> CaseResult:
    """Issue one /api/chat call and evaluate the case's invariants."""
    # Default LLM off for the walkthrough — Qwen wiring is still in flux
    # and the legacy fallbacks rate-limit. Cases can opt back in explicitly.
    body = {"message": case["question"], "allow_llm_synthesis": False}
    if "allow_llm_synthesis" in case:
        body["allow_llm_synthesis"] = case["allow_llm_synthesis"]
    if case.get("chart_context"):
        body["chart_context"] = case["chart_context"]
    if case.get("turn_history"):
        body["turn_history"] = case["turn_history"]

    result = CaseResult(
        case_id=case["id"],
        category=case.get("category", "uncategorized"),
        question=case["question"],
        response={},
    )
    try:
        response = client.post("/api/chat", json=body)
        result.response = (
            response.json()
            if response.headers.get("content-type", "").startswith("application/json")
            else {"_raw": response.text, "_status": response.status_code}
        )
        if response.status_code != 200:
            result.error = f"HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    result.invariants = evaluate_invariants(case.get("invariants") or {}, result.response)
    return result


def _print_case(result: CaseResult) -> None:
    status = _green("PASS") if result.all_passed else _red("FAIL")
    header = f"{status} {_bold(result.case_id):20s} [{_cyan(result.category)}]"
    print(f"\n{header}")
    print(f"  Q: {result.question}")
    if result.error:
        print(f"  {_red('error:')} {result.error}")
    for inv in result.invariants:
        mark = _green("✓") if inv.passed else _red("✗")
        print(f"    {mark} {inv.name:24s} {Color.DIM}{inv.detail}{Color.RESET}")
    snippet = (result.response.get("response") or "")[:160].replace("\n", " ")
    if snippet:
        print(f"  {_yellow('answer:')} {snippet}{'…' if len(snippet) >= 160 else ''}")


def _print_summary(results: list[CaseResult]) -> bool:
    total = len(results)
    passed = sum(1 for r in results if r.all_passed)
    failed = total - passed
    by_category: dict[str, list[CaseResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    print("\n" + _bold("=== Coverage ==="))
    for cat, cases in sorted(by_category.items()):
        ok = sum(1 for c in cases if c.all_passed)
        print(f"  {cat:24s} {ok}/{len(cases)}")

    print("\n" + _bold("=== Summary ==="))
    print(f"  total:  {total}")
    print(f"  passed: {_green(str(passed))}")
    print(f"  failed: {_red(str(failed)) if failed else '0'}")
    return failed == 0


def _write_ledger(results: list[CaseResult]) -> Path:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    path = LEDGER_DIR / f"{ts}.json"
    payload = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(results),
        "passed": sum(1 for r in results if r.all_passed),
        "cases": [
            {
                "id": r.case_id,
                "category": r.category,
                "question": r.question,
                "all_passed": r.all_passed,
                "error": r.error,
                "invariants": [
                    {"name": inv.name, "passed": inv.passed, "detail": inv.detail}
                    for inv in r.invariants
                ],
                "response": r.response,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def main() -> int:
    """CLI entry — runs all cases (or one) and writes a ledger record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="Run only the named case id")
    parser.add_argument("--no-ledger", action="store_true", help="Skip writing the JSON ledger")
    args = parser.parse_args()

    cases = json.loads(CASES_PATH.read_text())["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(_red(f"no case with id {args.case!r}"))
            return 2

    print(_bold(f"\nUser-acceptance walkthrough — {len(cases)} case(s)\n"))
    client = _build_client()
    results = [run_case(client, case) for case in cases]
    for result in results:
        _print_case(result)
    all_green = _print_summary(results)

    if not args.no_ledger:
        path = _write_ledger(results)
        print(f"\n{_cyan('ledger:')} {path.relative_to(PROJECT_ROOT)}")

    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())
