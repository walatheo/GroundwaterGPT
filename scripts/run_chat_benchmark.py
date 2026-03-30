"""Run AI chat/research benchmark suite and emit a JSON report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is importable when this script is run as `python scripts/...`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_benchmark_defaults() -> tuple[Path, Path]:
    """Load default benchmark config paths lazily after path bootstrapping."""
    from src.evaluation.chat_benchmark import DEFAULT_CASES_PATH, DEFAULT_THRESHOLDS_PATH

    return DEFAULT_CASES_PATH, DEFAULT_THRESHOLDS_PATH


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    default_cases_path, default_thresholds_path = _load_benchmark_defaults()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=default_cases_path,
        help="Path to benchmark cases JSON",
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=default_thresholds_path,
        help="Path to threshold configuration JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("chat_benchmark_report.json"),
        help="Output report path",
    )
    parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Exit non-zero if benchmark fails configured thresholds",
    )
    return parser.parse_args()


def main() -> int:
    """Entrypoint for benchmark execution."""
    from src.evaluation.chat_benchmark import run_chat_benchmark

    args = parse_args()
    report = run_chat_benchmark(cases_path=args.cases, thresholds_path=args.thresholds)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as fh:
        json.dump(report, fh, indent=2)

    summary = report.get("summary", {})
    print("Chat benchmark complete")
    print(f"- Cases: {report.get('metadata', {}).get('case_count', 0)}")
    print(f"- Overall score: {summary.get('overall_score', 0.0):.3f}")
    print("- Average citation coverage: " f"{summary.get('average_citation_coverage', 0.0):.3f}")
    print(f"- Threshold pass: {summary.get('passed', False)}")
    print(f"- Report: {args.output}")

    if args.enforce_thresholds and not summary.get("passed", False):
        print("Threshold enforcement enabled and benchmark did not pass.")
        reasons = summary.get("failed_reasons", [])
        for reason in reasons:
            print(f"  * {reason}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
