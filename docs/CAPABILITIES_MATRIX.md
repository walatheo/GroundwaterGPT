# GroundwaterGPT Capabilities Matrix

**Last Updated:** February 28, 2026
**Phase:** Phase 5 - AI Research Integration

## Capability Summary

| Area | Capability | Surface | Status | Demo Ready |
|---|---|---|---|---|
| Data API | Site catalog, time series, heatmap, comparison | FastAPI (`/api/sites*`, `/api/compare*`) | Complete | Yes |
| Visualization | Map, charts, analysis dashboards | React (`Map`, `Time Series`, `Heatmap`, `Analysis`) | Complete | Yes |
| Chat QA | Groundwater Q&A with fallback behavior | FastAPI (`POST /api/chat`) + React `AI Assistant` | Beta | Yes |
| Deep Research | Structured research report generation | FastAPI (`POST /api/research`) | In Progress | Yes |
| Claim Citations | Claim-level citation objects + coverage summary | `POST /api/research` response fields | Implemented | Yes |
| Research Workflow API | Plan -> run logging -> manuscript draft | FastAPI (`/api/research/plans*`) | Implemented | Yes |
| Reproducibility Schema | Required run metadata (`seed`, `commit`, `env`, `executor`) | Run logging API + UI | Implemented | Yes |
| Manuscript Provenance | Draft provenance metadata + citations persisted | Draft API + manuscript/provenance files | Implemented | Yes |
| Research Workflow UI | End-to-end researcher flow in dashboard | React `Research Lab` tab | Implemented | Yes |
| KB Runtime Health | Runtime/readiness visibility and graceful failures | `/api/knowledge/status`, `/api/knowledge/ingest` | Implemented | Yes |
| Chat Benchmark Harness | Automated benchmark scoring + thresholds | `scripts/run_chat_benchmark.py` | Implemented | Yes |
| CI Benchmark Job | Benchmark run + artifact upload (optional enforcement) | GitHub Actions `chat-evaluation` job | Implemented | Yes |

## API Capability Matrix

| Endpoint | Purpose | Key Outputs | Notes |
|---|---|---|---|
| `POST /api/chat` | Conversational groundwater Q&A | `response`, `sources`, `mode` | Fallback mode available when LLM unavailable |
| `POST /api/research` | Multi-step research response | `report`, `insights`, `sources`, `claim_citations`, `citation_summary` | Includes deterministic Estero benchmark fallback path |
| `GET /api/chat/status` | Runtime and feature status | `agent_available`, `research_available`, `features` | Useful for demo readiness check |
| `GET /api/knowledge/status` | KB runtime readiness | dependency/storage readiness | Returns degraded states explicitly |
| `POST /api/research/plans` | Create experiment plan | `plan`, `summary`, storage path | Start of research workflow |
| `POST /api/research/plans/{id}/runs` | Log reproducible run | run record + reproducibility fields | Enforces required reproducibility metadata |
| `POST /api/research/plans/{id}/draft` | Generate draft paper | markdown + provenance path + citations | Produces manuscript artifact |

## Evaluation Capability Matrix

| Evaluation Goal | Mechanism | Current Outcome |
|---|---|---|
| Automated benchmark execution | `scripts/run_chat_benchmark.py` | Passing in current local fallback benchmark mode |
| Threshold policy | `tests/benchmark/chat_eval_thresholds.json` | Defined and machine-checked |
| CI integration | `.github/workflows/ci.yml` (`chat-evaluation`) | Active, artifact uploaded each run |
| Claim citation coverage | `citation_summary.citation_coverage` | Computed per response |

## Known Constraints

| Constraint | Impact | Mitigation |
|---|---|---|
| External model/download access may be unavailable | LLM/embedding startup can fail | Fallback mode + skip-agent-init support for deterministic demos |
| Local data horizon may be < 30 years for some benchmark prompts | Report period may differ from requested horizon | Response includes explicit date range and caveat |
| Phase 5 LLM quality targets not fully closed | Production-grade factual performance still in progress | Benchmark harness and Sprint 3 quality gates now in place |
