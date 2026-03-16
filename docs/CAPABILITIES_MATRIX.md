# GroundwaterGPT Capabilities Matrix

**Last Updated:** March 8, 2026
**Phase:** Phase 5 - AI Research Integration

## Capability Summary

| Area | Capability | Surface | Status | Demo Ready |
|---|---|---|---|---|
| Data API | Site catalog, time series, heatmap, comparison | FastAPI (`/api/sites*`, `/api/compare*`) | Complete | Yes |
| Visualization | Map, charts, analysis dashboards | React (`Map`, `Time Series`, `Heatmap`, `Analysis`) | Complete | Yes |
| Chat QA | Groundwater Q&A with fallback behavior | FastAPI (`POST /api/chat`) + React `AI Assistant` | Beta | Yes |
| Deep Research | Structured research report generation | FastAPI (`POST /api/research`) | In Progress | Yes |
| Claim Citations | Claim-level citation objects + coverage summary | `POST /api/research` response fields | Implemented | Yes |
| Claim Disagreement Engine | Adversarial claim verification (`supported/contradicted/insufficient_evidence`) with risk scoring | `POST /api/research` (`claim_verdicts`, `claim_verdict_summary`) | Implemented | Yes |
| Citation Integrity | Claim + section coverage checks with pass/fail flags | `POST /api/research` (`citation_integrity`) | Implemented | Yes |
| Hallucination Guardrail | Removes uncited factual sentences from synthesized reports | Research agent synthesis output | Implemented | Yes |
| Section Confidence | Section-level confidence/trust metadata | `POST /api/research` (`section_confidence`) | Implemented | Yes |
| Research Workflow API | Plan -> run logging -> manuscript draft | FastAPI (`/api/research/plans*`) | Implemented | Yes |
| Reproducibility Schema | Required run metadata (`seed`, `commit`, `env`, `executor`) | Run logging API + UI | Implemented | Yes |
| Manuscript Provenance | Draft provenance metadata + citations persisted | Draft API + manuscript/provenance files | Implemented | Yes |
| Research Workflow UI | End-to-end researcher flow in dashboard | React `Research Lab` tab | Implemented | Yes |
| KB Runtime Health | Runtime/readiness visibility and graceful failures | `/api/knowledge/status`, `/api/knowledge/ingest` | Implemented | Yes |
| Chat Benchmark Harness | Automated benchmark scoring + thresholds + execution modes (`fallback/live/both`) | `scripts/run_chat_benchmark.py` | Implemented | Yes |
| Retrieval Precision Harness | Precision@k benchmark and recommended retrieval params | `scripts/run_retrieval_precision.py` | Implemented | Yes |
| CI Benchmark Job | Benchmark run + artifact upload (optional live enforcement) | GitHub Actions `chat-evaluation` job | Implemented | Yes |

## API Capability Matrix

| Endpoint | Purpose | Key Outputs | Notes |
|---|---|---|---|
| `POST /api/chat` | Conversational groundwater Q&A | `response`, `sources`, `mode` | Fallback mode available when LLM unavailable |
| `POST /api/research` | Multi-step research response | `report`, `insights`, `sources`, `claim_citations`, `claim_verdicts`, `claim_verdict_summary`, `citation_summary`, `section_confidence`, `citation_integrity`, `hallucination_guardrail` | Includes deterministic Estero fallback + citation integrity checks |
| `GET /api/chat/status` | Runtime and feature status | `agent_available`, `research_available`, `degraded_reasons`, `runtime_checks` | Useful for readiness + error diagnostics |
| `GET /api/knowledge/status` | KB runtime readiness | dependency/storage readiness | Returns degraded states explicitly |
| `POST /api/research/plans` | Create experiment plan | `plan`, `summary`, storage path | Start of research workflow |
| `POST /api/research/plans/{id}/runs` | Log reproducible run | run record + reproducibility fields | Enforces required reproducibility metadata |
| `POST /api/research/plans/{id}/draft` | Generate draft paper | markdown + provenance path + citations | Produces manuscript artifact |

## Evaluation Capability Matrix

| Evaluation Goal | Mechanism | Current Outcome |
|---|---|---|
| Automated benchmark execution | `scripts/run_chat_benchmark.py --mode {fallback|live|both}` | Fallback + live modes available with per-mode reporting |
| Threshold policy | `tests/benchmark/chat_eval_thresholds.json` | Defined and machine-checked |
| Live-agent gate policy | `tests/benchmark/chat_eval_live_thresholds.json` | Defined (`require_live_mode=true`) |
| CI integration | `.github/workflows/ci.yml` (`chat-evaluation`) | Active with optional live/retrieval enforcement flags |
| Claim citation coverage | `citation_summary.citation_coverage` | Computed per response |
| Section citation coverage | `citation_integrity.section_citation_coverage` | Computed per response |
| Claim verdict coverage | Benchmark summary (`average_claim_verdict_coverage`) | Machine-checked via benchmark thresholds |

## Known Constraints

| Constraint | Impact | Mitigation |
|---|---|---|
| External model/download access may be unavailable | LLM/embedding startup can fail | Fallback mode + skip-agent-init support for deterministic demos |
| Local data horizon may be < 30 years for some benchmark prompts | Report period may differ from requested horizon | Response includes explicit date range and caveat |
| Phase 5 LLM quality targets not fully closed | Production-grade factual performance still in progress | Benchmark harness and Sprint 3 quality gates now in place |
