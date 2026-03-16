# GroundwaterGPT Deliverable Plan (Depth-First)

**Last Updated:** March 8, 2026
**Focus:** Production-ready claim-verification quality slice for deep research output

## Goal

Ship one high-confidence deliverable that improves factual reliability of `POST /api/research` by hardening claim-level verification and measurable quality gates.

## Deliverable Scope

1. Stable response contract for claim verification:
- `claim_verdicts[]`
- `claim_verdict_summary`

2. Benchmark quality gates for verification robustness:
- `min_avg_claim_verdict_coverage`
- `max_avg_contradicted_claim_rate`
- `max_avg_high_risk_claim_rate`

3. Test coverage and docs updates to support CI adoption.

## Non-Goals (This Slice)

- Full multi-agent orchestrator implementation
- New UI feature development
- Cloud deployment/infra rollout

## Acceptance Criteria

1. `POST /api/research` returns `claim_verdicts` and `claim_verdict_summary` in both deep and fallback modes.
2. Benchmark runner reports verdict coverage and risk-rate metrics.
3. Threshold configs include verdict quality gates for fallback and live benchmark modes.
4. Unit + benchmark tests validate response shape and threshold behavior.
5. Focused test suite passes in deterministic mode.

## Execution Plan

1. Implement deterministic verdict summary builder and wire to API responses.
2. Add benchmark metrics for verdict coverage and contradiction/high-risk rates.
3. Add threshold keys and failure-reason reporting.
4. Expand tests for summary schema and threshold checks.
5. Update capability/status/runbook docs.

## Risk Controls

- Keep fallback-mode deterministic to avoid flaky CI outcomes.
- Require explicit threshold keys in benchmark configs before CI enforcement.
- Preserve backward compatibility by adding fields without removing existing ones.

## Next Session (After This Deliverable)

1. Add contradiction-aware synthesis hints to report generation (surface uncertainty explicitly when contradictions are detected).
2. Add UI exposure for `claim_verdict_summary` in research results.
3. Start Sprint 5 planner/checkpoint loop on top of the now-stable quality contract.
