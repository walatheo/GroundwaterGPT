"""Phase 6 latency gate for the deterministic grounded-chat pipeline.

The product target is ``p50 < 1500ms`` end-to-end for deterministic answers.
Phase 1-4 components (router + composer + validator + refusal builder) are
effectively free — the real budget gets consumed by data loading and chart
assembly in the branch handlers.

This test reserves a tight slice of that budget (50ms total p50) for the
grounded-chat core: if the resolver or composer regresses by 250x, CI
catches it here. Branch-level latency is tracked separately by the
existing interpretation benchmark.

The test is skipped under very slow CI where the absolute threshold would
false-positive; set ``GROUNDWATERGPT_SKIP_LATENCY_TEST=1`` to bypass.
"""

from __future__ import annotations

import os

import pytest

from scripts.benchmark_grounded_chat import run

# A generous ceiling relative to the actual measurement (~0.2ms total p50).
# We want the test to fail when something has gone meaningfully wrong,
# not to chase single-digit-millisecond noise on slow CI runners.
CORE_P50_BUDGET_MS = 50.0


@pytest.mark.skipif(
    os.getenv("GROUNDWATERGPT_SKIP_LATENCY_TEST", "").strip().lower() in {"1", "true", "yes"},
    reason="latency test disabled by env",
)
def test_deterministic_pipeline_p50_under_budget():
    results = run(iterations=30)
    total_p50 = sum(stats["p50"] for stats in results.values())
    assert total_p50 < CORE_P50_BUDGET_MS, (
        f"deterministic core p50 {total_p50:.2f}ms exceeds budget "
        f"{CORE_P50_BUDGET_MS}ms; per-stage: "
        + ", ".join(f"{name}={stats['p50']:.2f}ms" for name, stats in results.items())
    )
