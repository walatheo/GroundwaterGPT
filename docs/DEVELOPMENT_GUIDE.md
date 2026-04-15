# EAGLE Development Guide

**Last updated:** April 15, 2026

This guide describes the repository as it exists now. EAGLE is a FastAPI + React
groundwater research app built around deterministic USGS analysis, evidence-bound
LLM assistance, and reproducible research outputs. Retired forecast experiments,
generated plot artifacts, and empty model-test scaffolding are no longer part of
the maintained development surface.

## Current Architecture

The application has four active layers:

| Layer | Files | Responsibility |
| --- | --- | --- |
| Frontend | `frontend/src/` | React dashboard, map, chart panels, chat, research workflow UI |
| API | `api/main.py`, `api/routes/` | FastAPI route registration, deterministic chat routing, interpretation, site/well/data endpoints |
| Analysis | `api/routes/_site_analysis.py`, `api/routes/_research_workbench.py` | Monthly aggregation, trend summaries, cohort comparison, chart payloads |
| Agent and evidence | `src/agent/`, `api/routes/_citation.py`, `api/routes/_provenance.py` | Knowledge search, evidence-linked synthesis, citation metrics, provenance envelopes |

The data path is intentionally plain: local `data/usgs_<site_id>.csv` files are
loaded by API helpers, enriched with `config/usgs_sites.json`, and converted into
deterministic text, chart, and evidence payloads. LLM output is allowed to
summarize and organize the evidence, but measured groundwater facts come from the
deterministic layer.

The sponsor-facing LLM surface is now the chart/data interpretation path:
`POST /api/interpret` returns an `interpretation_response_v1` object with chart
context, key observations, USGS data references, evidence, suggested follow-up
questions, explicit limitations, and grounding status. It can request the local
LLM narration layer with `use_llm=true`, or run in fast deterministic mode with
`use_llm=false` for classroom/demo interactions where latency matters.

## Repository Map

```text
api/
  main.py                      FastAPI app and router registration
  helpers.py                   Shared CSV loading and summary stats
  site_metadata.py             Site metadata loader from config/usgs_sites.json
  routes/
    chat.py                    Chat, interpretation, research, and streaming endpoints
    data.py                    Site data, heatmap, comparison endpoints
    wells.py                   Well catalogue endpoint
    knowledge.py               Knowledge-base status and ingestion endpoints
    research_workflow.py       Research plans, runs, drafts, workbench
    _site_analysis.py          Deterministic trend/cohort/chart analysis
    _citation.py               Claim/citation metrics
    _provenance.py             Reproducibility payloads

frontend/
  src/App.jsx                  Main React shell
  src/api/client.js            API client helpers
  src/components/              Dashboard, charts, map, chat, research views
  tests/e2e/                   Playwright coverage for chart/workbench flows

src/
  agent/                       DeepResearchAgent, tools, knowledge, verification
  data/                        USGS download and pipeline utilities
  evaluation/                  Chat and retrieval benchmark helpers
  claim_disagreement.py        Claim-verdict normalization

tests/
  unit/                        API, chart, chat, agent, and workflow tests
  data/                        Data quality and local USGS integrity checks
  agent/                       Agent budget and workflow behavior tests
  benchmark/                   Deterministic benchmark cases and thresholds
  knowledge/                   Optional local Chroma accuracy tests

docs/
  EAGLE_TECHNICAL_OVERVIEW.md  Audit-oriented system description
  MANUSCRIPT_DRAFT.md          Submission-facing draft
  DEVELOPMENT_GUIDE.md         This file
  ENGINEERING_STANDARDS.md     Review and quality standards
  DEMO_RUNBOOK.md              Demo and benchmark walkthrough
```

## Active Runtime Paths

Use these paths when deciding whether a file is still part of the system:

| Surface | Entry point | Notes |
| --- | --- | --- |
| Local demo | `make demo` | Starts FastAPI on `127.0.0.1:8000` with `GROUNDWATERGPT_SKIP_AGENT_INIT=1`, then Vite on `localhost:3000` |
| API app | `uvicorn api.main:app --reload` | Loads `.env`, registers all routers, and exposes `/docs` |
| Frontend | `cd frontend && npm run dev` | Vite dev server |
| Unit tests | `make test` | Runs `GROUNDWATERGPT_SKIP_AGENT_INIT=1 python3 -m pytest tests/unit/ -q` |
| Fallback benchmark | `make benchmark` | Runs deterministic chat benchmark with thresholds |
| Chart LLM benchmark | `make benchmark-chart-llm` | Runs the bounded local-LLM chart explanation smoke |
| Interpretation benchmark | `make benchmark-interpretation` | Runs the fast interpretation question bank with thresholds |
| Interpretation LLM benchmark | `make benchmark-interpretation-llm` | Runs the same question bank with local LLM synthesis enabled |
| E2E tests | `cd frontend && npm run test:e2e` | Requires app servers to be available per Playwright config |

## Environment

Required local tools:

- Python 3.10 or newer, with Python 3.11 used by CI.
- Node 18 or newer for the Vite frontend.
- A populated local `data/` directory for site-level chart and integrity tests.
- Optional local `knowledge_base/` for Chroma retrieval tests.
- Optional Ollama/OpenAI/Anthropic/Gemini credentials for live LLM paths.

Recommended setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

Keep secrets in `.env`, using `.env.example` as the root template. The API loads
`.env` before route imports so agent providers can see credentials at startup.

## Development Workflow

1. Inspect the affected route/component/test before editing.
2. Keep deterministic groundwater calculations in the API analysis layer.
3. Keep React components focused on rendering state returned by the API.
4. Add or update the smallest meaningful test for the behavior changed.
5. Run the narrow test first, then the broader suite that matches the risk.
6. Do not commit generated local artifacts from `data/`, `outputs/`,
   `knowledge_base/`, `frontend/dist/`, `frontend/test-results/`, caches, or
   virtual environments.

Common commands:

```bash
make demo
make test
make benchmark
make benchmark-chart-llm
make benchmark-interpretation
cd frontend && npm run build
cd frontend && npm run test:e2e
```

## Testing Policy

The maintained tests are not intended to be live network tests by default.
Unit tests use monkeypatching and lightweight stubs to isolate deterministic
logic, API contracts, and agent envelope behavior. That is expected. A test is
considered stale when it only preserves a removed feature, asserts implementation
details for a retired module, or lives in an empty package with no executable
coverage.

Current test groups:

| Group | Purpose |
| --- | --- |
| `tests/unit/` | Fast API contract checks, deterministic chat fallback, chart payloads, research workflow endpoints |
| `tests/data/` | Local CSV shape, canonical file naming, stale artifact guards |
| `tests/agent/` | Search budget, cost limits, agent status behavior |
| `tests/benchmark/` | Regression cases for deterministic answer quality and retrieval scoring |
| `tests/knowledge/` | Optional local Chroma/embedding accuracy checks, skipped when dependencies or indexes are unavailable |
| `frontend/tests/e2e/` | Browser-level workbench and inline-chart rendering checks |

When adding tests, prefer stable local fixtures over network calls. If a test
needs a live service, mark it clearly and skip when that service is unavailable.

Interpretation benchmark cases live in
`tests/benchmark/interpretation_eval_cases.json`; thresholds live in
`tests/benchmark/interpretation_eval_thresholds.json`. Keep the cases phrased as
real chart/data interpretation prompts, not generic tutoring prompts. Education
can be a use case, but the product contract is evidence-bound data
interpretation.

## Data And Generated Artifacts

Tracked source files should define the app; generated state should stay local.

Ignored/generated paths include:

- `data/` local USGS CSVs and timestamped refresh snapshots.
- `knowledge_base/` Chroma persistent indexes.
- `outputs/` research sessions, generated manuscripts, plots, and reports.
- `frontend/dist/` production build output.
- `frontend/test-results/` Playwright artifacts.
- `__pycache__/`, `.pytest_cache/`, `.vite/`, `.venv/`, `frontend/node_modules/`.

Generated benchmark reports can be regenerated with the scripts in `scripts/`.
Only intentionally pinned reports should remain tracked.

## Refactor Notes

The active code is clean enough to run, but three modules are still large:

| Module | Why it is large | Preferred future split |
| --- | --- | --- |
| `api/routes/chat.py` | Endpoint handlers, deterministic routing, streaming, agent wiring | Route handlers, routing/detection wiring, fallback response assembly, SSE streaming |
| `api/routes/_site_analysis.py` | Trend math, cohort logic, chart payloads, narrative helpers | Trend helpers, changepoints, cohort analysis, chart payload builders |
| `src/agent/research_agent.py` | Planning, search, synthesis, evidence parsing, rendering | Agent orchestration, structured synthesis, persistence/session helpers |

Split these only when touching related behavior. Avoid broad refactors that do
not reduce a concrete maintenance risk.

## Retired Scope

The previous standalone scikit-learn groundwater forecast experiment has been
removed from the maintained tree. Forecast claims should stay out of the app and
manuscript until a future implementation has a served endpoint, rolling-origin
validation, uncertainty handling, and benchmark coverage.

Optional DuckDuckGo web search remains disabled by default through
`GROUNDWATERGPT_ENABLE_WEB_SEARCH=false`. The demo and manuscript-facing path are
local-data and local-knowledge first; do not describe EAGLE as a web-search
agent unless that path is explicitly enabled and evaluated.

## Review Checklist

Before opening a PR or making a handoff:

- `git status --short` shows only intentional source/doc changes.
- No generated caches, local outputs, or browser test artifacts are tracked.
- `make test` passes, or any failure is documented with the failing command.
- `cd frontend && npm run build` passes for frontend changes.
- The development guide and technical overview still describe the current
  architecture after any route, dependency, or data-surface change.
