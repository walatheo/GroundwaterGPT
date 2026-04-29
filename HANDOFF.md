# EAGLE — Project Handoff Notes

This document is for the next team picking up EAGLE. It is intentionally short
and honest. Read it before reading anything else.

## What works today

- **Deterministic USGS pipeline.** Site detection, time-series loading, monthly
  aggregation, OLS trend, cross-well metrics, divergent pairs, candidate
  changepoints, behavior clusters, cohort risk labels, citation integrity,
  provenance hashes. This is the layer the manuscript rests on.
- **Charts.** Recharts-ready payloads from a single deterministic builder used
  by chat, research, and streaming paths.
- **Tests.** 481 unit tests pass locally
  (`GROUNDWATERGPT_SKIP_AGENT_INIT=1 python3 -m pytest tests/unit/ -q`).
- **Demo.** `make demo` brings up FastAPI on :8000 and Vite on :3000.
- **Bench.** `scripts/run_chat_benchmark.py --mode fallback --enforce-thresholds`
  passes 68/68. **Note: this benchmark runs with the LLM disabled.** It is
  reproducibility evidence for the deterministic layer, not a quality signal
  for the live LLM path.

## What is known to be slow or fragile

- **LLM cold-start latency.** On local Ollama (Qwen variants), the first
  request after a cold start can take longer than the full per-request LLM
  budget. The framing step alone has been observed at 60+ seconds. After the
  recent fix (see CHANGELOG below) the framing call is now capped at 25% of
  the remaining budget, but the underlying performance issue remains: this
  project needs a faster Qwen variant or hosted DashScope to be reliably
  responsive.
- **Cache poisoning (now mitigated).** When the LLM path was skipped due to
  budget exhaustion, the deterministic-only response used to be cached and
  served forever. That's now fixed in `chat.py` via `_llm_synthesis_was_skipped`,
  but the underlying LLM-perf issue still means many users will see the
  deterministic answer rather than the LangGraph-synthesized one.
- **Question intent is not first-class outside chart interpretation.**
  `_chart_interpreter._detect_question_intent` exists and is used by the
  chart path, but `_site_analysis._site_research_fallback` does not surface
  a `question_intent` to the chat envelope. This means causal/limitations/
  drought phrasings on a specific well can collapse to a generic trend
  template even when the LLM does fire.
- **`src/data/continuous_learning.py` is legacy ingestion scaffolding.** It
  is lazily exported but not part of the tested API path. It duplicates site
  metadata, writes directly to `data/`, and should be treated as a starting
  point for a future ingestion service rather than production automation.

## Highest-leverage items for the next team

These came out of an architectural review on 2026-04-26. They are listed in
the order I'd tackle them.

1. **Make `question_intent` mandatory in the backend response contract for
   every route, not just chart interpreter.** Today
   `_progression_seed_from_chat_payload` only reads `question_intent` from
   the chart-interpreter response. Adding it to site/aquifer/location
   fallback results would let `api/routes/answering/followups.py` route follow-up
   generation correctly for all routes.
2. **Replace the repeated route-specific fallback dicts with one typed
   adapter.** Today the same envelope is hand-built three times in
   `chat.py` (site, research, streaming). Each new field — `chart_specs`,
   intent, provenance, trace, citations — needs three patches. One typed
   adapter from `_site_research_fallback` to chat/research/stream payloads
   would cut maintenance burden substantially.
3. **Move follow-up generation authority to the backend.** The frontend
   currently captures `questionIntent` but mostly ignores it, regenerating
   suggestions from chart/well heuristics. If the backend always sends
   grouped intent-aware suggestions, the UI just renders.
4. **Keep model-selection tests green when adding new LLM routes.** Local
   Qwen model precedence now lives in `src/agent/model_config.py`; new
   synthesis paths should use that helper instead of reading `SYNTHESIS_MODEL`
   or `LLM_MODEL` directly.
5. **Split the large files.** `chat.py`, `_chart_interpreter.py`,
   `answering/reasoning.py`, `_site_analysis.py`, and `ChatView.jsx` are
   each large enough that surgical changes are risky. Each deserves its
   own refactor plan.

## Things the docs explicitly say NOT to claim

(See `docs/DEMO_RUNBOOK.md` §8 for the full list. Repeated here for emphasis.)

- The 1.000 benchmark score does not prove the hydrologic conclusions are
  scientifically optimal. It validates software contract compliance.
- Risk labels are not calibrated against expert labels.
- Candidate changepoints are not formal regime shifts.
- Divergent pairs do not prove aquifer connectivity or causal mechanisms.
- The system does not dynamically cover the national USGS network.
- The live LLM path is not production-latency ready.

## Artifact policy for JSON, data, and outputs

- **Tracked JSON is source/config/test material.** Keep `config/*.json`,
  `tests/benchmark/*.json`, and edge-case fixture JSON files in git because
  they define expected behavior.
- **Generated JSON is run evidence.** Root benchmark reports,
  `outputs/chat_review/*/report.json`, `responses.jsonl`, research sessions,
  learner events, and manuscript provenance files are local artifacts by
  default. Regenerate them from `scripts/` instead of reviewing them as source.
- **Large local stores stay out of git.** `data/`, `knowledge_base/`,
  `outputs/`, browser test output, caches, logs, and local agent memory are
  intentionally ignored. Pin a final closeout artifact only when it is needed
  for a manuscript or release, and do that deliberately.

## Recent changes (2026-04-29 cleanup pass)

- `legacy/`: dormant `DeepResearchAgent`, `research_optimizer`,
  `evidence_guided_synthesis` (the agent's variant — not the live route),
  `tools.py`, `continuous_learning`, the agent benchmark script and
  cached report, and four agent-only test files were quarantined here.
  Excluded from the test suite via `pyproject.toml` `norecursedirs` and
  from pre-commit via `exclude: ^legacy/`. `chat.py` lost ~280 lines of
  agent-init / agent-branch plumbing that was already gated off in demo,
  tests, and benchmarks.
- `api/routes/multi_well.py` + `api/routes/_multi_well.py` (was
  `research_workflow.py` + `_research_workbench.py`): the side-by-side
  data viewer endpoint moved from `POST /api/research/workbench` to
  `POST /api/multi-well`. The old path still works for one release as a
  hidden alias; frontend client.js calls the new path. Old name lied —
  it never did research synthesis.
- `api/routes/answering/{composer,reasoning,followups,refusal}.py`: the
  four files that compose every chat response are now grouped in this
  subpackage. Public API is unchanged (re-exported from
  `api/routes/answering/__init__.py`); 18 import sites + a few mock-patch
  strings were rewritten.
- `legacy/tests/scaffolding/`: four eval/CLI test files
  (`test_chat_review_runner`, `test_eval_model_flag`, `test_langchain_eval`,
  `test_interpretation_benchmark`) moved out of `tests/unit/` because they
  exercise dev tooling, not the `/api/chat` UAT path.
- Verified parity: UAT 10/10 passes, 415 unit tests pass.

## Recent changes (2026-04-26 closeout)

- `answering/reasoning.py` (was `_grounded_reasoning.py`): framing LLM call
  capped at min(0.25 × remaining budget, 15s) so a slow framing call cannot
  starve the interpretation step.
- `chat.py`: cache writes are now skipped when the LLM path was meant to
  fire but didn't (prevents cache poisoning of LLM-failed responses).
- `requirements-lite.txt`: added `pytest-timeout` so the `pyproject.toml`
  declared timeout actually works.
- `.gitignore`: ignore `.remember/`, `docs/superpowers/`, and
  `tests/edge_cases/uat_ledger/`. Benchmark JSON reports are no longer
  re-included by default; pin them explicitly with `git add -f` for a
  manuscript closeout if needed.
- `README.md`, `HANDOFF.md`: clarified that generated JSON reports, `outputs/`,
  `data/`, and `knowledge_base/` are local artifacts rather than maintained
  project source.
- `CITATION.cff`: filled author block.
- `README.md`, `docs/MANUSCRIPT_DRAFT.md`: corrected stale test count,
  updated default LLM from `llama3.2` to Qwen, added cold-start latency
  caveat.
- `src/agent/model_config.py`: centralized local Qwen model precedence so
  `GROUNDWATERGPT_LLM_MODEL` and CLI `--model` overrides are not shadowed by
  legacy `SYNTHESIS_MODEL` / `LLM_MODEL` settings.
- `tests/unit/test_chart_api.py`: tightened chart tests from shape-only
  checks into behavior checks for series keys, date filtering, metadata, and
  rolling-average values.

## How to run

```bash
make demo                              # backend + frontend
make benchmark                         # deterministic chat benchmark
GROUNDWATERGPT_SKIP_AGENT_INIT=1 \
  python3 -m pytest tests/unit/ -q     # unit tests
```

To exercise the LLM path against the real Ollama, set
`GROUNDWATERGPT_LLM_MODEL` to a fast variant (e.g. `qwen3:1.5b`) before
starting the demo, and warm the model by issuing one throwaway request
before any timed evaluation.
