"""Run retrieval precision benchmark and emit a JSON report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _default_cases_path() -> Path:
    """Resolve default retrieval eval case path lazily."""
    from src.evaluation.retrieval_precision import DEFAULT_RETRIEVAL_CASES_PATH

    return DEFAULT_RETRIEVAL_CASES_PATH


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=_default_cases_path(),
        help="Path to retrieval evaluation cases JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("retrieval_precision_report.json"),
        help="Output report path",
    )
    parser.add_argument(
        "--target-precision",
        type=float,
        default=0.90,
        help="Minimum average precision@k target",
    )
    parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Exit non-zero when recommended configuration misses target precision",
    )
    return parser.parse_args()


def main() -> int:
    """Run the retrieval precision benchmark."""
    from src.evaluation.retrieval_precision import run_retrieval_precision_eval

    args = parse_args()
    report = run_retrieval_precision_eval(
        cases_path=args.cases,
        target_precision=args.target_precision,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as fh:
        json.dump(report, fh, indent=2)

    recommended = report.get("recommended", {})
    print("Retrieval precision benchmark complete")
    print(f"- Cases: {report.get('metadata', {}).get('case_count', 0)}")
    print(f"- Recommended k: {recommended.get('k', 0)}")
    print(f"- Recommended score_threshold: {recommended.get('score_threshold', 0.0):.2f}")
    print(f"- Average precision@k: {recommended.get('average_precision_at_k', 0.0):.3f}")
    print(f"- Target met: {recommended.get('passed', False)}")
    print(f"- Status: {report.get('status', 'unknown')}")
    print(f"- Report: {args.output}")

    if args.enforce_thresholds and not recommended.get("passed", False):
        print("Threshold enforcement enabled and retrieval precision target was not met.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
