"""Run the LLM-path benchmark — same 68 cases routed through DeepResearchAgent.

Mirrors ``run_chat_benchmark.py`` but boots the live agent against a local
Ollama provider so every case exercises the evidence-bound synthesis layer
instead of pure deterministic routing. Writes ``agent_benchmark_report.json``.

The cases live in ``tests/benchmark/chat_eval_cases.json``. Reusing the same
suite lets the manuscript directly compare the deterministic-only column to
the agent column on identical questions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "llama3.2"


def _force_local_agent_env(provider: str, model: str) -> None:
    """Pin the LLM factory to a local provider before any imports.

    ``llm_factory`` reads ``LLM_PROVIDER`` / ``LLM_MODEL`` at module-load
    time, so this must run before ``api.main`` is imported.
    """
    os.environ["LLM_PROVIDER"] = provider
    os.environ["LLM_MODEL"] = model
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.pop("GROUNDWATERGPT_SKIP_AGENT_INIT", None)
    # Hybrid Ollama narration in the deterministic fallback can stay on —
    # it is what makes fallback cases comparable to the agent cases.
    os.environ.pop("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", None)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the live-agent benchmark."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=PROJECT_ROOT / "tests" / "benchmark" / "chat_eval_cases.json",
        help="Path to benchmark cases JSON",
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=PROJECT_ROOT / "tests" / "benchmark" / "chat_eval_live_thresholds.json",
        help=(
            "Path to live-agent threshold configuration JSON "
            "(defaults to the non-fallback live thresholds)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "agent_benchmark_report.json",
        help="Output report path",
    )
    parser.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        help="LLM provider for the agent path (default: ollama)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="LLM model name (default: llama3.2)",
    )
    parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Exit non-zero if benchmark fails configured thresholds",
    )
    return parser.parse_args()


def _summarise_agent_path(case_results: list[dict]) -> dict:
    """LLM-path-specific signals on top of the shared metric summary.

    These are the numbers a manuscript reviewer wants to see for the
    agent column: how often did the agent actually run vs fall through
    to deterministic, and did every response carry the typed envelope.
    """
    total = len(case_results)
    agent_modes = {"deep_research", "research_chat", "live", "agent"}
    agent_cases = sum(1 for r in case_results if str(r.get("mode", "")).lower() in agent_modes)
    fallback_cases = sum(1 for r in case_results if "fallback" in str(r.get("mode", "")).lower())
    structured_present = sum(1 for r in case_results if r.get("structured_response_present"))
    provenance_present = sum(1 for r in case_results if r.get("provenance_present"))
    return {
        "total_cases": total,
        "agent_routed_cases": agent_cases,
        "deterministic_fallback_cases": fallback_cases,
        "agent_routed_rate": round(agent_cases / total, 3) if total else 0.0,
        "structured_response_coverage": round(structured_present / total, 3) if total else 0.0,
        "provenance_coverage": round(provenance_present / total, 3) if total else 0.0,
    }


def main() -> int:
    """Run the live-agent benchmark and write a JSON report."""
    args = parse_args()
    _force_local_agent_env(args.provider, args.model)

    # Imports happen AFTER env is set so llm_factory and chat.py pick up
    # the local provider.
    from src.evaluation.chat_benchmark import run_chat_benchmark

    report = run_chat_benchmark(
        cases_path=args.cases,
        thresholds_path=args.thresholds,
        mode="live",
    )

    report["agent_path_summary"] = _summarise_agent_path(report.get("results", []))
    report["metadata"]["llm_provider"] = args.provider
    report["metadata"]["llm_model"] = args.model

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as fh:
        json.dump(report, fh, indent=2)

    summary = report.get("summary", {})
    agent_summary = report["agent_path_summary"]
    print("Agent benchmark complete")
    print(f"- Provider: {args.provider} / model: {args.model}")
    print(f"- Cases: {report.get('metadata', {}).get('case_count', 0)}")
    print(f"- Overall score: {summary.get('overall_score', 0.0):.3f}")
    print(f"- Average citation coverage: {summary.get('average_citation_coverage', 0.0):.3f}")
    print(f"- Median latency: {summary.get('median_elapsed_seconds', 0.0):.3f} s")
    print(f"- Max latency: {summary.get('max_elapsed_seconds', 0.0):.3f} s")
    print(f"- Agent-routed rate: {agent_summary['agent_routed_rate']:.3f}")
    print(f"- Structured response coverage: {agent_summary['structured_response_coverage']:.3f}")
    print(f"- Provenance coverage: {agent_summary['provenance_coverage']:.3f}")
    print(f"- Threshold pass: {summary.get('passed', False)}")
    print(f"- Report: {args.output}")

    if args.enforce_thresholds and not summary.get("passed", False):
        print("Threshold enforcement enabled and benchmark did not pass.")
        for reason in summary.get("failed_reasons", []):
            print(f"  * {reason}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
