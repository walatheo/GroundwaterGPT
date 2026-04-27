# Legacy

Quarantined code that is **not part of the live system**. Kept for provenance only — every benchmark, the demo, all unit tests, and the UAT walkthrough run with `_research_agent = None`, so none of this code path is exercised by anything users see.

| Path | What it was | Why it's here |
|------|-------------|---------------|
| `src_agent/research_agent.py` | `DeepResearchAgent` — multi-step LLM-driven research orchestrator. | Disabled in demo, tests, and benchmarks (`GROUNDWATERGPT_SKIP_AGENT_INIT=1`). One-case manual smoke scored 0.200 and failed thresholds. |
| `src_agent/research_optimizer.py` | Query-refinement / priority-ranking helpers. | Only consumed by `research_agent.py`. |
| `src_agent/evidence_guided_synthesis.py` | Evidence-progression synthesis primitives used by the agent. | Only consumed by `research_agent.py`. (Distinct from the live `api/routes/_evidence_guided_ai.py`, which stays.) |
| `src_agent/tools.py` | LangChain-style tool definitions for an earlier agent design. | Replaced by direct `_grounded_reasoning.py` path; no live import. |
| `src_data/continuous_learning.py` | Online-learning scaffold. | Never wired into the pipeline. |
| `scripts/run_agent_benchmark.py` | Eval harness for `DeepResearchAgent`. | Targets a dormant module. |
| `reports/agent_benchmark_report.json` | Frozen output of the above. | Reference only. |
| `tests/test_research_agent_v2.py`, `test_evidence_guided_synthesis.py`, `test_tools.py` | Tests for the modules above. | Excluded from the suite via `pyproject.toml` `norecursedirs`. |

If you need to revive any of this, restore the file to its original location and re-add its imports — `git log --follow` on the path will surface the prior history.
