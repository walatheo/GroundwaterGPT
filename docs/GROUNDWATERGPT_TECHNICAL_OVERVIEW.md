# GroundwaterGPT — Technical Overview for Manuscript Development

**Document purpose.** This is a low-level, audit-oriented description of the GroundwaterGPT system as it exists in the repository on 2026-04-14. It is intended as source material for a NotebookLM-backed manuscript workflow: every architectural claim, every numeric threshold, every data-flow assertion is tied to concrete files and line ranges in the code so that a downstream author (or reviewer) can verify it without re-reading the codebase from scratch. The document is deliberately exhaustive in places where a paper's Methods section would need that level of fidelity (detection heuristics, chart synthesis, citation scoring) and compressed where a paper would only cite existence (UI chrome, build config).

The document is organized in six parts:

1. System purpose and scope
2. Data substrate and knowledge base
3. Backend architecture (the deterministic fallback, the LLM research agent, and their join point)
4. Frontend architecture and the user-visible surface
5. Evaluation harness, test coverage, and measured behaviour
6. Strengths, explicit limitations, threats to validity, and open questions

---

## 1. System purpose and scope

### 1.1 What GroundwaterGPT is

GroundwaterGPT is a research-grade, "whitebox" question-answering and visualization platform for Florida groundwater monitoring data. Its domain is a fixed set of **44 USGS groundwater wells** (counted directly from [api/site_metadata.py](api/site_metadata.py) via `len(SITE_METADATA)`) distributed across five Florida counties (Miami-Dade: 15, Lee: 11, Collier: 6, Hendry: 4, Sarasota: 4) and four generic "Florida" entries, with per-well water-level time series stored as CSV under [data/](data/). The site-level hydrogeologic metadata recognizes seven aquifer labels — Biscayne Aquifer (15 wells), Surficial Aquifer (7), Floridan Aquifer System (6), Tamiami Aquifer System (5), Florida Aquifer (4), Intermediate Aquifer System (4), Hawthorn Group (3) — and distinguishes confined vs unconfined settings, aquifer zone depth ranges, and well depths.

The system answers three broad classes of questions:

- **Descriptive and comparative questions over the USGS record** ("what has been the change in groundwater level in Estero over the last 30 years"; "compare G-3336 and G-5004"; "which wells in Miami-Dade have the steepest decline"). These are answered by a deterministic fallback engine that selects relevant wells, aggregates monthly means, computes per-well linear trends, and emits a cited report plus a Recharts-ready chart payload.
- **Domain knowledge questions** ("which aquifer supplies Estero"; "what confines the Floridan aquifer"). These retrieve from a ChromaDB-backed knowledge base built from hydrogeology PDFs and per-well USGS summaries, grounded by a source-verification layer.
- **Open-ended research questions** ("has groundwater in Lee County stabilized since 2015"; "cross-aquifer comparison of Biscayne vs Floridan trends"). These are routed to an LLM-backed `DeepResearchAgent` that plans sub-questions, executes prioritized searches against both the knowledge base and (optionally) the public web, reflects on coverage, and returns a structured report with citation integrity metadata.

The governing design goal — stated across the code and the in-repo docs — is **explainability**: every path that produces user-visible text must also produce (a) a list of sources, (b) a per-claim citation record, (c) a verdict and confidence score, and (d) a deterministic, reproducible chart whenever the question can be backed by monitored well data. The system is explicitly built so that the fallback path alone can answer the benchmark suite to a passing score, i.e. the LLM is an **enhancement**, not a **dependency**.

### 1.2 What GroundwaterGPT is not

It is not a hydrologic model. It does not solve Darcy's law, does not run groundwater-flow simulations, and does not couple surface-water and groundwater processes. Its "predictions" are a single scikit-learn-based 7-day forecast pipeline (see §2.4) trained on lag and rolling features of the well time series themselves — not a process model.

It is not a national or global service. The monitored network is hard-coded to the 44 USGS wells shipped under [api/site_metadata.py](api/site_metadata.py); adding new sites requires editing the metadata file and dropping a matching `usgs_<15-digit-id>.csv` into [data/](data/). There is no dynamic site discovery at request time.

It is not a general-purpose web-search research agent. The LLM path is gated by an explicit `_NETWORK_WIDE_KEYWORDS` / `_is_aquifer_query` routing policy, and its search budget (web + knowledge base) is capped per request. When the agent is unreachable, every request still produces a valid, grounded answer via the fallback routing chain.

---

## 2. Data substrate and knowledge base

### 2.1 USGS time-series CSVs

The canonical well data lives in [data/usgs_{15-digit-site-id}.csv](data/). There are 40 canonical files plus several timestamped snapshots (e.g. `*_20260227.csv`, `*_20260315.csv`) that appear to be refresh exports. Each canonical file has the schema `site_no, datetime, value`, where `value` is depth-to-water in feet relative to land surface. Probing 20 random files yields a combined date coverage of **1994-01-01 through 2026-04-05** with ~195k rows across those 20 files alone; several wells begin as early as 2003 and some as early as the mid-1990s. The values are stored as daily observations, though the downstream chart pipeline always resamples to month-start (`MS`) means (see §3.5).

The CSVs are loaded lazily and cached in-process by [`_load_site_timeseries`](api/routes/_detection.py) in [api/routes/_detection.py](api/routes/_detection.py) (the module-level `_SITE_SERIES_CACHE`). The loader reads the CSV, coerces `datetime` via `pd.to_datetime(errors="coerce")`, coerces `value` via `pd.to_numeric(errors="coerce")`, drops NaN rows, sorts by datetime, and returns the resulting DataFrame (or `None` if the file is missing or empty). Every downstream analysis path goes through this single loader, so the in-memory schema is a known invariant.

### 2.2 Site metadata

[api/site_metadata.py](api/site_metadata.py) exposes `SITE_METADATA: dict[str, dict]`, the authoritative per-site metadata table. It is loaded from `config/usgs_sites.json` at import time and, for sites present on disk but missing from that JSON, filled from a best-effort CSV scan. Each entry contains: `id, name, aquifer, aquifer_type, confined, aquifer_zone, aquifer_zone_depth_range_ft, aquifer_description, county, lat, lng, well_depth_ft, depth, description`. The aquifer strings are normalized (Biscayne, Floridan, Surficial, Tamiami, Intermediate, Hawthorn) so that downstream keyword detection is deterministic. This file is the **single source of truth** for the network's membership; everything else — the router, the chart builder, the KB ingestion summaries — derives from it.

### 2.3 Knowledge base

The knowledge base is a ChromaDB persistent store under [knowledge_base/](knowledge_base/) (`chroma.sqlite3`, ~156 MB on disk, with collection subdirectories named by UUID). The embedding model is `BAAI/bge-small-en-v1.5` (384-dimensional) loaded via `sentence-transformers`, configured in [src/agent/knowledge.py](src/agent/knowledge.py) at `EMBEDDING_MODEL_NAME` (line 58) and `CHROMA_DIR` (line 55). Ingestion uses LangChain's `PyPDFLoader` plus `RecursiveCharacterTextSplitter`; all of these are guarded by optional imports so the rest of the system runs even if `chromadb` / `langchain_chroma` are not installed.

The indexed corpus covers three source families:

- **Hydrogeology reference PDFs** shipped in [resources/pdfs/](resources/pdfs/): `a-glossary-of-hydrogeology.pdf`, `age-dating-young-groundwater.pdf`, `a-conceptual-overview-of-surface-and-near-surface-brines-and-evaporite-minerals.pdf`, and two subdirectories (`references/`, `usgs_reports/`) that are `.gitignore`'d for size.
- **Per-well USGS summaries** generated from the CSV data itself, so that queries like "what is the record length at G-3336" can be answered without re-parsing the CSV at request time.
- **Domain Q&A corpus** with hand-written short answers for frequent domain questions (aquifer supply sources, confinement, water-budget basics).

The [`api/routes/knowledge.py`](api/routes/knowledge.py) router exposes `/api/knowledge/stats` (document and embedding counts), `/api/knowledge/status` (a lightweight readiness check that does not load the embedding model), and `/api/knowledge/ingest` (run-time ingestion of a PDF path with `recursive`, `min_trust`, `force` flags). The runtime check is important because loading the embedding model is the slowest part of cold startup, and the frontend needs a way to tell the user "KB is configured" without paying that cost.

### 2.4 ML forecast pipeline

The ML component is a 7-day water-level forecast built from groundwater-only features (no climate data in the training loop). Training lives under [src/ml/](src/ml/) and produces joblib artifacts under [models/](models/). Features are temporal (day-of-year, cyclical sin/cos) plus lag windows (7, 14, 21, 30, 60 days) plus rolling statistics (7, 14, 30-day means and standard deviations). The test split is 20%. The README claims 93% accuracy; the manuscript should treat that number as a preliminary point estimate — it comes from a self-selected train/test partition and has not been cross-validated across hydrologically independent time windows in the code I could find. This is one of the clearest places where the paper should either add a proper evaluation or soften the claim.

---

## 3. Backend architecture

The backend is a FastAPI application defined in [api/main.py](api/main.py). Five routers are mounted: `data_router` (`/api/sites`, per-site data and heatmap endpoints in [api/routes/data.py](api/routes/data.py)), `chat_router` ([api/routes/chat.py](api/routes/chat.py), 2081 lines — the heart of the system), `knowledge_router`, `research_workflow_router` ([api/routes/research_workflow.py](api/routes/research_workflow.py), experiment-plan scaffolding), and `wells_router`. CORS is open to `http://localhost:3000` and `http://127.0.0.1:3000` only.

### 3.1 The request lifecycle and routing chain

Every textual question entering the system goes through one of three endpoints — `/api/chat` (quick answer), `/api/research` (deep research, non-streaming), or `/api/research/stream` (deep research over SSE). All three share the same **routing chain** implemented in [api/routes/chat.py](api/routes/chat.py), and that chain is the core contribution of the deterministic layer.

The chain executes in this order (all detection regex live in [api/routes/_detection.py](api/routes/_detection.py)):

1. **Site-name detection** (`_detect_site_names`): match `_WELL_NAME_RE = \b([A-Za-z]{1,3})[\s\-]?(\d{3,5})\b` (catches G-3336, C-1224) and `_RAW_SITE_ID_RE = \b(\d{15})\b` (catches raw USGS IDs). If a named site is present, route to the site-fallback branch.
2. **Aquifer detection** (`_detect_aquifer`): longest-first substring match against `_AQUIFER_DETECTION_MAP`, a hand-curated dict mapping 20+ surface forms (biscayne aquifer, tamiami, upper floridan, surficial, intermediate, hawthorn group, ...) to `(aquifer_key, display_name)`. If hit, route to the aquifer-fallback branch and load the cohort via `_sites_for_aquifer(aquifer_key, max_sites=8)`.
3. **Multi-location comparison** (`_detect_locations` + `_is_multi_location_compare_query`): if two or more location tokens are present and the query reads like a comparison, load a merged cohort via `_sites_for_multiple_locations`.
4. **Single-location detection** (`_detect_location`): word-boundary match against `_LOCATION_REFERENCE_POINTS`, a dict of 26+ Florida place names (Estero, Naples, Miami, Cape Coral, Immokalee, ...) each mapping to `(lat, lng, display_name, county_hint)`. If hit, call `_best_sites_near(lat, lng, county_hint, max_sites=10)` and route to the location-fallback branch.
5. **Network-wide detection** (`_is_network_wide_query`): keyword check against `_NETWORK_WIDE_KEYWORDS` (all wells, every county, network-wide, confined vs unconfined, ...). If hit, load `_all_sites_with_data(max_sites=36)` and route to the network-fallback branch.
6. **LLM research agent** (the default when nothing above matches and the `/api/research` endpoints are used): invoke `DeepResearchAgent.research(...)`. If the agent is unreachable or returns an empty report, fall back through the chain again as if the keyword filters had fired.

Nearest-neighbour selection (`_best_sites_near`) uses a simple scoring rule: Haversine distance plus a `-0.3` bonus for county matches; candidates are sorted by score and truncated to `max_sites`. This is deliberately crude — the paper should note it explicitly as a design choice that favours reproducibility over sophisticated spatial interpolation.

### 3.2 The deterministic fallback — `_site_research_fallback`

The core of the "deterministic, cited response for any USGS site/location query" (the file's own comment) is [`_site_research_fallback`](api/routes/_site_analysis.py) in [api/routes/_site_analysis.py](api/routes/_site_analysis.py). Given a question, a list of selected sites, a location label, and optional lat/lng pins, this function:

- Computes per-site summary statistics (start/end dates, record length, net change in feet, annual rate in ft/yr, trend classification).
- Runs `_cross_well_analysis` (same file) to build a cohort-level summary: distribution of `rising / falling / stable` trends, cohort mean and standard deviation of annual change, a ranked list of `divergent_pairs` (pairs whose trends disagree most strongly, bounded to the top 3), and a cohort `risk_level` in `{low, moderate, high}` driven by the fraction of falling wells and whether the cohort is mostly confined.
- Assembles a structured report with aquifer-grouped sections, a "cross-aquifer comparison" section when multiple aquifers are present, an explicit period-of-record statement, and (optionally) an LLM synthesis block produced by a separately-controlled `allow_llm_synthesis` flag.
- Builds a `claim_citations` list: each quantitative or domain claim in the report gets a `claim_id`, the literal claim text, a confidence score, and a list of `{url, verified, trust_level}` citations drawn from the USGS NWIS record URLs plus any KB matches.
- Calls `_build_claim_verdicts` and `_build_claim_verdict_summary` from [api/routes/_citation.py](api/routes/_citation.py) to turn claim-citations into verdicts (`supported / contradicted / insufficient_evidence` with a `risk_score` in [0, 1]); in the absence of the disagreement engine, the conservative fallback is "citations present → supported (risk 0.3); no citations → insufficient_evidence (risk 0.85)".
- Calls `_build_citation_integrity` (same citation module) to produce an integrity record with `claim_citation_coverage`, `section_citation_coverage`, and `passed` boolean keyed off two environment-configurable thresholds (`MIN_CLAIM_CITATION_COVERAGE` and `MIN_SECTION_CITATION_COVERAGE`, default 0.90 each).
- Calls `_build_chart_payload` (same file) to produce the Recharts-ready chart JSON (see §3.5).

Every keyword-routed path in the routing chain goes through this function. That is a deliberate architectural decision: it gives the system a single, tested, fully-cited code path for the "safe" subset of queries, and it means the benchmark suite (§5.2) can evaluate the system without requiring an LLM at all.

### 3.3 The LLM research agent

The LLM path is implemented by `DeepResearchAgent` in [src/agent/research_agent.py](src/agent/research_agent.py) (1738 lines). The agent is instantiated once at startup, wired through [api/routes/chat.py](api/routes/chat.py) as `_research_agent`, and reused across requests. Its constructor accepts `max_depth`, `max_results_per_search`, `use_web_search`, `llm_provider`, `auto_learn`, `timeout_seconds` (default 300 s), `enable_planning`, `enable_reflection`, `enable_budget_management`, and `enable_persistence` knobs.

The agent composes five components built in [src/agent/research_optimizer.py](src/agent/research_optimizer.py): `ResearchPlanner`, `PriorityRanker`, `SelfReflectionEvaluator`, `StructuredReportBuilder`, and `ResearchSessionPersistence`. The planner implements the **SmartSearch** style query decomposition (turn the user query into a main question plus sub-questions plus an ordered search priority); the ranker implements **ReSeek** (score-driven prioritization with trust-weighted combined scores); the reflector implements **WebSeer** (gap analysis, follow-up-query generation, confidence/coverage scoring). The "O-Researcher" multi-agent decomposition is referenced in the module docstring but in this codebase is implemented as a single-process iterative loop rather than a multi-agent fan-out.

Each `research(...)` call proceeds through phases — planning, iterative search (KB + web with budget tracking), insight extraction, synthesis, self-reflection, possibly one or more follow-up iterations, and finalization — and these phases are represented explicitly by `ResearchContext.phase_offsets` (planning 0.06, research_loop 0.12, query_optimization 0.18, searching 0.28, extracting_insights 0.42, follow_up_generation 0.56, synthesizing 0.82, learning 0.9, complete 1.0). Progress events are pushed to a caller-supplied `progress_callback(message, progress, snapshot)`; the streaming endpoint uses this to drive SSE updates.

The search budget is a hard limit: `SearchBudget` tracks `max_web_searches = max(3, depth*2+2)`, `max_kb_searches = max(6, depth*4)`, `max_api_calls = max(10, depth*6)`, and a per-query cost model. When the budget is exhausted the agent stops iterating regardless of coverage — a deliberate backstop against runaway loops.

The LLM itself is chosen through [src/agent/llm_factory.py](src/agent/llm_factory.py), which supports five providers: Ollama (local), OpenAI (GPT-4o, GPT-4.1, GPT-4o-mini), Anthropic (Claude 3.5 Sonnet by default, Claude 3 Opus), Google Gemini (2.0 Flash, 1.5 Pro), and Qwen via Alibaba DashScope. Provider and model are read from `LLM_PROVIDER` / `LLM_MODEL` env vars (Anthropic + `claude-3-5-sonnet-20241022` as defaults). Missing credentials raise at construction time so that an operator sees the failure immediately rather than discovering it mid-request. Embeddings also go through the factory (`get_embeddings()`), falling back to the HuggingFace BGE model if a provider-specific embedding is not available.

Web search is provided by DuckDuckGo via the `ddgs` (new) / `duckduckgo_search` (legacy) package, selected at import time. When the `use_web_search=False` flag is set or the package is missing, the agent degrades cleanly to KB-only retrieval.

### 3.4 The join point — `_agent_chart_hook`

There is one subtle but important join point between the two worlds. When the LLM agent returns a result, its output schema (defined in [src/agent/research_agent.py](src/agent/research_agent.py)) includes `report`, `insights`, `sources`, `chart_specs`, `tool_trace`, `claim_citations`, and friends — but **not** a chart payload in the Recharts shape that the frontend expects. Historically that meant the agent path silently emitted no chart even when the agent had clearly identified sites. The fix, in [api/routes/_agent_chart_hook.py](api/routes/_agent_chart_hook.py), is a post-hoc attachment layer:

```python
def attach_chart_from_agent_result(result):
    if result.get("chart"):
        return result
    site_ids = _extract_site_ids_from_agent_result(result)
    if not site_ids:
        return result
    sites = _load_sites_for_ids(site_ids)
    cross_well = _cross_well_analysis(sites) if len(sites) >= 2 else None
    result["chart"] = _build_chart_payload(sites, _infer_location_label(result, sites), cross_well=cross_well)
    return result
```

`_extract_site_ids_from_agent_result` walks `chart_specs`, `tool_trace`, `wells`, and `sources` recursively, picking up any 15-digit USGS site ID present in nested dicts, lists, or plain strings, and deduplicates while preserving discovery order. The chart is then synthesized by the **same** `_build_chart_payload` that the fallback uses. This is the architectural guarantee the system trades on: the agent path and the fallback path emit **byte-identical chart schemas** for the same selected cohort, because the chart is built by one function regardless of which path chose the sites.

Downstream, every chart emission goes through a tiny helper `_chart_from(result, *, path: str)` in [api/routes/chat.py](api/routes/chat.py) that reads `result.get("chart")`, logs a structured `chart_decision path=<label> emitted=<bool>` debug line, and returns the chart or `None`. This helper is called from all ~16 chat/research branches in the file (site, aquifer, multi-location, location, network, research variants of each, agent success, streaming agent success). Centralizing it means the "does this branch emit a chart" question is now observable and un-regressable.

### 3.5 Chart payload synthesis

`_build_chart_payload` in [api/routes/_site_analysis.py](api/routes/_site_analysis.py) is the deterministic chart builder. Its contract:

- Input: list of site dicts (metadata + pandas time series), a location label, an optional `cross_well` summary.
- Output: a Recharts-ready JSON object with `chart_type`, `title`, `x_label`, `y_label`, a `series` list, a `data` list (one row per month), an `insights` list, and a `cohort_risk_level`.

The builder resamples every well's time series to month-start means (`df.set_index("datetime")["value"].resample("MS").mean().dropna().round(2)`), unions the observed dates, and writes one `data` row per date with a column per site ID. When two or more wells are present, it adds a `"avg"` series (cohort mean, dashed stroke) and marks it `highlight=True`. It then computes linear trends on the cohort average and on any **highlighted** wells, where a well is highlighted if it is part of the top `divergent_pairs[0]` or is the fastest-declining / strongest-rising well per `_cross_well_analysis`. Per-well annual rates are pulled from `per_site_metrics[*].annual_change_ft_yr` (already computed by `_cross_well_analysis`) rather than re-derived, so the legend labels stay consistent with the text of the report.

Trend slopes are computed via `_linear_trend_values_with_slope` — an ordinary least-squares fit over the ordered monthly points, explicitly named `slope_per_bin` because one regression "x-unit" is one month. The annual rate is then `slope_per_bin * 12` and the trend series name is interpolated as e.g. `"Cohort Trend (-0.18 ft/yr)"`. Every trend legend entry ends in `ft/yr`, and there is a unit test in [tests/unit/test_inline_chart.py](tests/unit/test_inline_chart.py) asserting this exact property.

The `insights` block (`_build_chart_insights`) is capped at **five** bullets and lead with a "Highlighted wells mark the most divergent or fastest-changing series ({n} total)" explanation, followed by cohort trend + risk, fastest decline, strongest rise (if positive), and largest-divergence pair. This bullet order is load-bearing: the "highlighted wells" bullet is how a user reading the chart knows why certain lines are thick and the rest are dimmed.

### 3.6 Streaming (`/api/research/stream`)

The streaming endpoint wraps the research path in a server-sent-events generator. A thread-safe `queue.Queue` collects `{type: progress|result|error, ...}` frames produced by a callback inside the agent (or by the deterministic fallback's internal progress hooks). The HTTP handler writes each frame as `data: <json>\n\n`. The frontend reader in [frontend/src/api/client.js](frontend/src/api/client.js) uses a `ReadableStream` reader, decodes chunks with a `TextDecoder`, buffers partial events across chunk boundaries, and dispatches `onProgress(message, progress, snapshot)` callbacks per frame. The final `type: result` frame carries the full payload, including `chart` (which, post-hook, now matches the non-streaming path byte-for-byte for the same query).

A unit test in [tests/unit/test_inline_chart.py](tests/unit/test_inline_chart.py) — `test_streaming_agent_path_yields_chart_in_final_event` — exercises the streaming path end-to-end with a stubbed `_research_agent`, splits the SSE body, and asserts that the final `result` frame has `chart is not None` and non-empty `series` and `data`. This is the regression backstop for the cross-path parity invariant.

### 3.7 Citation integrity

The citation scaffolding lives in [api/routes/_citation.py](api/routes/_citation.py) (~224 lines). Trust levels are a ranked enum — `unknown` (0) → `moderate` (1) → `trusted` (2) → `verified` (3) — with a symmetrical `RANK_TO_TRUST_LEVEL` map. `verify_source` assigns trust based on domain: USGS, EPA, NOAA, NASA → verified; other `.gov` → trusted; peer-reviewed DOIs → trusted; universities (`.edu`) → moderate; Wikipedia and general reference → moderate; unknown → unknown. The long-form verifier (`src/agent/source_verification.py`, 664 lines) additionally tags each source with a category (`NUMERICAL_DATA`, `RESEARCH_PAPER`, `GOVERNMENT_REPORT`, `ACADEMIC`, `REFERENCE`, `NEWS`, `BLOG`, `UNKNOWN`) and a `priority_score` in [0, 1] used by the priority ranker.

`_build_claim_verdicts` runs each claim through the `ClaimDisagreementEngine` in [src/claim_disagreement.py](src/claim_disagreement.py) if available, producing `{verdict, risk_score, evidence_for, counter_evidence, rationale}`. The conservative fallback — cited → supported; uncited → insufficient — is the one that ships when the disagreement engine is disabled or when running in CI. `_build_claim_verdict_summary` aggregates these to `{total_claims, supported, contradicted, insufficient_evidence, high_risk_claim_ids, supported_rate, contradicted_rate, insufficient_rate}`.

`_build_section_confidence_from_claims` groups claims by report section and computes an average confidence per section plus an overall confidence and overall trust level. `_build_citation_integrity` then produces the integrity record: claim coverage (`cited_claims / total_claims`), section coverage (`cited_sections / total_sections`), and a boolean `passed` that is true when both coverages meet the configured thresholds (default 0.90). Every response in the chat/research surface carries the integrity record, so the UI can surface it without re-computing.

### 3.8 Research workflow endpoints

[api/routes/research_workflow.py](api/routes/research_workflow.py) and [api/routes/_research_workbench.py](api/routes/_research_workbench.py) expose a separate surface for **experiment-plan** and **workbench** functionality. This is the scaffolding for turning a research session into something that can be written up: `/api/research/plans` (create and list plans with title, research_question, hypothesis, methodology, datasets, metrics, baselines), `/api/research/plans/{plan_id}/runs` (log a run with config, metrics, findings, reproducibility fields including seed, code_commit, environment, executor, dependency_lock, and artifact hashes), and `/api/research/plans/{plan_id}/draft` (generate a target-venue-aware manuscript draft via the LLM). The workbench endpoint (`/api/research/workbench`) is a separate comparative-analysis surface with presets for date windows (`last_5y`, `last_10y`, `full_record`, `custom`), aggregations (monthly, quarterly, annual), and normalizations (raw, delta_from_first, z-score). The workbench produces its own chart payloads and is independent of the chat/research path.

These endpoints are important for the manuscript narrative because they are where "the system produced an answer" becomes "the system produced a reproducible experiment record" — they are the hooks a peer-reviewed author would use to cite the system's output.

---

## 4. Frontend architecture

### 4.1 Stack and build

The frontend is a React 18.2 + Vite 5 SPA styled with Tailwind 3.3. Charts use `recharts` 2.10 (all inline chart rendering) and `@visactor/react-vchart` 2.0.22 (research workbench). Maps use Leaflet 1.9.4 + `react-leaflet` 4.2.1. Markdown rendering is `react-markdown` 10.1.0. Icons are `lucide-react` 0.294.0. The Vite dev server runs on port 3000 and proxies `/api` to `http://localhost:8000` (configurable via `VITE_API_PROXY_TARGET`). E2E tests use Playwright.

### 4.2 Component graph

The user-visible surface is organized by mode. The top-level `App` mounts a sidebar-driven mode switcher: `Dashboard` (stats overview + map), `ChatView` (the primary question-answering surface, used for both Query mode and Research mode via a header toggle), `AnalysisView` (a per-site / per-cohort analysis panel), `ResearchSessionPanel` (session history and artifacts), `ResearchWorkflowView` (experiment plans, runs, drafts), and `ResearchWorkbenchView` (the comparative workbench).

`ChatView.jsx` is by far the largest component (~800 lines) and is where the cross-path parity invariant becomes user-visible. It subscribes to a `backendStatus` observable exported from `client.js`, renders a "Backend unreachable — check uvicorn on `:8000`" banner when the observable is in the `down` state, and auto-dismisses it on the next successful fetch. The chat message list renders an inline `<AgentChart>` whenever `msg.chart` is present (regardless of which backend path emitted it), shows a subtle "No time series available for this query" note when `msg.chart === null` and the user's query looks like a visualization request (the regex `/plot|chart|trend|visuali[sz]e|graph/i`), and otherwise just renders the report markdown plus its divergent-pair bullets and source list. `AgentChart` and `ResearchChartsPanel` are both lazy-loaded via `React.lazy` + `Suspense` with `<div className="h-[320px]" />` fallbacks — this is a deliberate bundle-size optimization because Recharts is the largest single dependency.

### 4.3 Chart UX polish

`AgentChart.jsx` is small (~225 lines) and has a handful of visual choices that deserve to be written up: it renders a risk pill next to the title that is hidden when `cohort_risk_level` is falsy or equal to `'unknown'`; it labels the CSV download button "Monthly CSV" with a tooltip of "Monthly-mean aggregation of all plotted wells" and writes `<slugified-title>-monthly.csv`; and it applies a **conditional legend payload** when the series count exceeds six — in that case, the legend filters to just highlighted wells, trend overlays, and the cohort average, while the underlying `<Line>` elements still render the non-highlighted wells as dim background context. This is the mechanism by which a 10-well cohort remains readable without the legend wrapping over multiple lines.

The Y-axis is **reversed** (`reversed` prop on `<YAxis>`), because `value` in the USGS CSV is depth-to-water — bigger is deeper, and hydrogeologists conventionally draw deeper-water downward. The Y-axis domain is computed from the data with a 5% padding. A `Brush` component is added only when `data.length > 60`, giving multi-year cohorts a zoom handle.

### 4.4 API client

[frontend/src/api/client.js](frontend/src/api/client.js) is the single entry point for all backend calls. Every fetch goes through `apiFetch(url, options, fallbackMessage)`, which wraps `fetch()` in a `try/catch` and converts any `TypeError` (i.e. `Failed to fetch`) into an `ApiError({kind: 'network'})` while emitting `'down'` on the `backendStatus` observable. On any successful response it emits `'up'`. HTTP errors are converted to `ApiError({kind: 'http', status})`, parse errors to `ApiError({kind: 'parse'})`. The streaming function `sendResearchQueryStreaming` reads the SSE body incrementally, splits on `\n\n`, handles partial frames, forwards `progress` events to an optional callback, stores `result` frames, raises on `error` frames, and resolves with the stored result when the stream closes.

The observable is ~15 lines — a `Set` of listeners plus `subscribe / getStatus` helpers. It is deliberately not a full store (no Redux/Zustand) because the only cross-cutting state it carries is the up/down status of the backend.

---

## 5. Evaluation and measured behaviour

### 5.1 Test coverage

The repository has **205 unit tests passing** on Python 3.10+ as of 2026-04-14 — [tests/unit/](tests/unit/) contains:

- `test_inline_chart.py` (13 tests): chart payload builder invariants, cross-path chart parity, agent-hook attach/leave-alone, streaming SSE result frame, ft/yr unit naming, monthly resampling, empty-input handling, KeyError surfacing when cross-well metrics are malformed.
- `test_detection.py`: detection chain tests (regex coverage, precedence, edge cases).
- `test_chat_api.py`: `/api/chat` endpoint tests against the FastAPI TestClient.
- `test_chart_api.py`: `/api/sites/{id}/chart` and `/api/compare/chart` endpoint tests.
- `test_knowledge_api.py`: knowledge base stat / status / ingest tests.
- `test_agent.py`: research agent tests with stubbed LLM.
- `test_tools.py`: tool invocation tests for the agent's tool surface.
- `test_claim_disagreement.py`: verdict engine tests.
- `test_features.py`: ML feature engineering tests.
- `test_research_workflow_api.py`: plan/run/draft endpoint tests.
- `test_research_workbench.py`: comparative workbench analysis tests.

A separate benchmark suite ([tests/benchmark/chat_eval_cases.json](tests/benchmark/chat_eval_cases.json)) contains **63 cases** spanning three difficulty levels (L1, L2, L3) across routing modes (`fallback`, `site_fallback`, `aquifer_fallback`, `network_fallback`). Each case lists `required_checks` (up to 20 boolean checks per case: `ok_status`, `has_report`, `has_sources`, `has_claim_citations`, `has_date_reference`, `has_well_id`, `has_trend_language`, `has_aquifer_language`, `within_time_budget`, `routes_to_location_fallback`, `reports_net_change_ft`, `reports_annual_rate`, `returns_6plus_wells`, `report_substantial`, `has_aquifer_sections`, `has_cross_aquifer_comparison`, `states_data_period`, `has_proxy_distance`, `response_has_hallucination_guardrail`, `response_has_citation_integrity`) and typed assertions (`expected_mode`, `has_net_change`, `has_annual_rate`, `min_wells`, `min_report_length`, ...). The harness lives in [scripts/run_chat_benchmark.py](scripts/run_chat_benchmark.py).

### 5.2 Measured performance

The current [chat_benchmark_report.json](chat_benchmark_report.json) summary (reading from the tracked file on disk):

- **63 / 63 cases passing**, `overall_score = 1.000`.
- Average citation coverage: **0.986** (threshold: 0.90).
- Maximum elapsed time on a single case: **12.314 s**.
- Median elapsed time: **0.085 s**.
- Thresholds the run was measured against: `min_overall_score=0.85`, `min_case_score=0.80`, `min_avg_citation_coverage=0.90`, `max_response_seconds=120`, `max_median_seconds=5.0`.
- Routing modes exercised: `fallback`, `site_fallback`, `aquifer_fallback`, `network_fallback` (note: the LLM agent path is **not** in the exercised set — the entire benchmark passes on the deterministic routes).

The key implication for the manuscript: the system's headline number ("63/63 benchmark pass, 98.6% citation coverage, 85 ms median latency") is a statement about **the deterministic fallback layer**, not about the LLM agent. This is a feature, not a bug — the fallback is what provides the system's reproducibility guarantees — but it needs to be framed that way in the paper so a reviewer does not read "63/63" as evidence for the LLM.

### 5.3 Benchmarks the paper should add

There is no equivalent **LLM-path benchmark** in the repository. A reviewer would want one: same 63 questions, routed through `DeepResearchAgent`, with the same check list applied to the result. This is straightforward to add (it would reuse the check harness) and is probably the single most valuable evaluation work the author could do before submission. Similarly, the 93% ML forecast accuracy deserves a proper rolling-origin cross-validation before it appears in a paper; right now the training script uses a single 80/20 split.

### 5.4 Retrieval precision harness

[scripts/run_retrieval_precision.py](scripts/run_retrieval_precision.py) runs a knowledge-base retrieval precision benchmark with a configurable top-k and a minimum average precision threshold (default 0.90). Its cases live in a companion JSON file. This is the right starting point for a Methods-section claim about KB retrieval quality; the manuscript should report precision@1, precision@5, and (if the KB supports it) MRR across those cases.

---

## 6. Strengths, limitations, threats to validity

### 6.1 Strengths

- **Single-source-of-truth chart schema.** Every backend path (four deterministic fallbacks, the LLM path, the streaming agent path) emits charts via one function, `_build_chart_payload`. The frontend consumes a single shape. This is cheap to test, cheap to observe, and hard to regress.
- **Explainability baked into the response contract.** Every response has `report`, `sources`, `claim_citations`, `claim_verdicts`, `claim_verdict_summary`, `citation_summary`, `section_confidence`, `citation_integrity`, `hallucination_guardrail`. There is no "unexplained" answer in the API surface; a reviewer can audit any reply end-to-end without a log trail.
- **LLM is decoupled from correctness.** The benchmark passes at 1.000 without the LLM active. The agent is a quality-of-life enhancement (better phrasing, open-ended follow-up, richer synthesis), not a correctness dependency. This is a defensible design choice for a domain where factual drift is expensive.
- **Reproducible data stack.** All time series are local CSVs, metadata is a single JSON, trust levels are an explicit enum, and cache keys are derived from the site ID. Bit-identical reruns are the default.
- **LLM provider portability.** The same agent code runs against Ollama, OpenAI, Anthropic, Gemini, or Qwen by changing two environment variables. This matters for reproducibility across institutional clusters with different procurement constraints.
- **Citation integrity as a first-class signal.** Coverage and trust are computed per request and surfaced back through the API, which is stronger than typical "retrieve and show links" designs.
- **Deterministic routing is testable.** Because routing is keyword-driven and regex-based, the test suite can enumerate routing decisions; the benchmark proves the chain behaves at 100% on 63 representative cases.

### 6.2 Limitations (stated plainly)

- **Scope is fixed and narrow.** 44 wells, 5 counties, 7 aquifer labels. The system has no way to reason about wells outside `SITE_METADATA`. A reviewer asking "what about the Panhandle" is asking for a config change, not a code change — but the manuscript must state this explicitly or it will read as overclaim.
- **Keyword routing is brittle at the edges.** `_is_network_wide_query` and `_is_multi_location_compare_query` are keyword checks, not intent classifiers. Questions that use novel phrasings ("across the whole dataset", "pan-aquifer") may miss the network-wide branch. The fallback to the LLM path mitigates this, but the deterministic guarantees disappear whenever the LLM takes over.
- **Trend methodology is OLS on monthly means.** `_linear_trend_values_with_slope` is an ordinary least-squares fit with no seasonality removal, no serial-correlation correction, and no uncertainty reporting. Reported annual rates are point estimates, not confidence intervals. For a hydrogeology paper, this is the most conspicuous methodological simplification — it should either be replaced with a proper trend estimator (Mann-Kendall + Sen's slope is the genre standard) or disclosed as a limitation.
- **Risk classification is a heuristic.** `_cross_well_analysis` sets `risk_level` to `high` when ≥66% of wells are falling, `moderate` at ≥33% falling (or ≥20% in a mostly-confined cohort), else `low`. These thresholds are reasonable-sounding and have no empirical calibration in the repo. The paper should either cite a domain source for them or present them as an engineering default.
- **Cohort "risk_level" and "divergent pairs" are not hydrologically validated.** Divergent pairs are the two wells with the largest opposite-sign annual changes. That is a defensible screening heuristic but not a hydrologic relationship — two wells can diverge for reasons unrelated to the aquifer system (localized pumping, instrumentation error, measurement gaps). The chart marks them as "highlighted" and the text calls them "divergent", which is a presentation choice the paper should be explicit about.
- **The LLM agent is under-evaluated.** There is no LLM-path benchmark file in the repository. Everything we can say about agent quality is based on ad-hoc testing, progress logs, and the passing of the deterministic 63/63 — none of which is evidence about the agent itself.
- **ML forecast accuracy is under-evaluated.** A single 80/20 split on a time series is not a sufficient validation. The model may be memorizing seasonal structure that a rolling-origin split would punish. The 93% number should not appear unqualified in a peer-reviewed manuscript.
- **Knowledge base coverage is small and not described at the page level.** Three hydrogeology PDFs plus per-well summaries plus a domain Q&A corpus is a useful seed but not a comprehensive literature base. A reviewer asking "what does the KB actually cover" is asking a fair question; the paper should answer it with a document-by-document inventory.
- **Web search is DuckDuckGo only.** There is no Google / Semantic Scholar / Crossref integration. For citation-heavy domain questions this is a meaningful quality ceiling.
- **Provenance within reports.** While every claim has citations, the mapping between a specific sentence in the report and a specific claim ID relies on regex post-processing of the synthesized text. A reviewer looking at the raw response can verify citations at the claim level but not always at the sentence level without matching by claim_id.
- **Concurrency and persistence.** The research session store (`ResearchSessionPersistence`) is file-based. The benchmark harness runs cases sequentially; concurrent request behaviour under load has not been measured. The paper should not claim "production" without qualifying that.
- **Timestamped refresh CSVs coexist with canonical CSVs.** The `data/` directory contains `usgs_<id>.csv` and several `usgs_<id>_<YYYYMMDD>.csv` snapshots with inconsistent content (some snapshots are literal duplicates of the same two rows). The `_load_site_timeseries` function only reads the canonical file, so the snapshots are effectively dead weight — but their presence could mislead a reader who assumes the directory listing reflects the serving data. This should be cleaned up before a reproducibility appendix is generated.

### 6.3 Threats to validity (for the manuscript)

- **Construct validity.** "Groundwater level" in the USGS schema is depth-to-water, which is conventionally drawn as a negative elevation. Papers sometimes report "water level" in the elevation sense. A reviewer could object to the Y-axis label ("Water Level (ft, monthly mean)") as ambiguous. The axis is reversed in the UI (bigger depth draws downward), which mitigates the confusion, but the paper should be explicit about sign convention.
- **External validity.** The system is trained and validated on wells that are in a handful of hydrologically related but not identical aquifer systems. Its behaviour on wells outside this set (e.g. Ogallala, Edwards, Central Valley) has not been measured. Claims about generalization should be limited to "the system can be configured to serve a similar-shape dataset" rather than "the system generalizes".
- **Internal validity of the risk label.** Because the risk heuristic is hand-tuned and the benchmark does not test it directly (the checks are for the presence of risk language, not for calibration), the benchmark cannot rule out miscalibration. An independent validation against a hydrogeologist's labelling of the same cohorts would strengthen any claim tied to `cohort_risk_level`.
- **Reproducibility of the LLM path.** The LLM is stochastic; a reviewer running the same query twice can get subtly different reports. The deterministic path guarantees reproducibility; the agent path does not. The experiment-plan/run scaffolding (`/api/research/plans/{id}/runs`) is the right tool to pin down a run with a seed + code commit + environment, but the paper will need to actually use it, not just cite it.

### 6.4 What the paper can confidently claim

- A working, tested pipeline for converting USGS groundwater records into cited, chart-backed answers with citation integrity as a first-class output.
- A deterministic routing chain that passes a 63-case benchmark at 1.000 on 205 unit tests, with sub-second median latency.
- A unified chart schema across deterministic and LLM paths, verified by a post-hoc attachment layer and a streaming regression test.
- An LLM-agent architecture decoupled from correctness, with explicit search-budget, reflection, and verification components — all wireable to five LLM providers.
- An experiment-plan scaffolding that closes the loop from question to reproducible run record to manuscript draft.
- A small but curated knowledge base with trust-level-aware verification.

### 6.5 What the paper should not claim without additional work

- Accurate 7-day prediction at 93% unless the ML pipeline gets a rolling-origin cross-validation with reported MAE / RMSE / skill-vs-persistence.
- State-of-the-art trend detection unless `_linear_trend_values_with_slope` is replaced with or augmented by Mann-Kendall + Sen's slope and the reported annual rates come with confidence intervals.
- Generalization beyond the monitored network unless the site metadata layer is tested against a non-Florida dataset.
- LLM-agent quality unless an LLM-path benchmark is added and reported.
- Production readiness unless concurrency and persistence are measured.

---

## Appendix A — File map for citation in the manuscript

| Component | Path | Size |
|---|---|---|
| Detection chain (regex, location map, site loader, cohort helpers) | [api/routes/_detection.py](api/routes/_detection.py) | 634 lines |
| Deterministic analysis (site fallback, cross-well, chart builder, insights, trend) | [api/routes/_site_analysis.py](api/routes/_site_analysis.py) | 1220 lines |
| Agent-to-chart join point | [api/routes/_agent_chart_hook.py](api/routes/_agent_chart_hook.py) | 146 lines |
| Citation integrity, verdicts, trust levels | [api/routes/_citation.py](api/routes/_citation.py) | 224 lines |
| Chat / research endpoints, routing chain, SSE streaming | [api/routes/chat.py](api/routes/chat.py) | 2081 lines |
| Knowledge base router | [api/routes/knowledge.py](api/routes/knowledge.py) | 88 lines |
| Data router | [api/routes/data.py](api/routes/data.py) | 239 lines |
| Research workflow (plans, runs, drafts) | [api/routes/research_workflow.py](api/routes/research_workflow.py) | 252 lines |
| Research workbench (comparative panel) | [api/routes/_research_workbench.py](api/routes/_research_workbench.py) | 569 lines |
| Site metadata loader | [api/site_metadata.py](api/site_metadata.py) | — |
| FastAPI app factory | [api/main.py](api/main.py) | 55 lines |
| Deep research agent | [src/agent/research_agent.py](src/agent/research_agent.py) | 1738 lines |
| Agent tool surface | [src/agent/tools.py](src/agent/tools.py) | 1482 lines |
| Research optimizer (planner, ranker, reflector, persistence) | [src/agent/research_optimizer.py](src/agent/research_optimizer.py) | 854 lines |
| Knowledge base loader | [src/agent/knowledge.py](src/agent/knowledge.py) | 760 lines |
| Source verification (trust levels, category, priority) | [src/agent/source_verification.py](src/agent/source_verification.py) | 664 lines |
| LLM provider factory | [src/agent/llm_factory.py](src/agent/llm_factory.py) | 180 lines |
| Research workflow orchestration (multi-phase loop) | [src/agent/research_workflow.py](src/agent/research_workflow.py) | 502 lines |
| Priority search engine | [src/agent/priority_search_engine.py](src/agent/priority_search_engine.py) | 536 lines |
| Groundwater LangGraph agent | [src/agent/groundwater_agent.py](src/agent/groundwater_agent.py) | 440 lines |
| Domain model and validation | [src/agent/groundwater_research_model.py](src/agent/groundwater_research_model.py) | 673 lines |
| Frontend chat surface | [frontend/src/components/ChatView.jsx](frontend/src/components/ChatView.jsx) | ~800 lines |
| Frontend chart component | [frontend/src/components/AgentChart.jsx](frontend/src/components/AgentChart.jsx) | 225 lines |
| API client with observable | [frontend/src/api/client.js](frontend/src/api/client.js) | 351 lines |
| Inline chart regression tests | [tests/unit/test_inline_chart.py](tests/unit/test_inline_chart.py) | 289 lines |
| Benchmark cases | [tests/benchmark/chat_eval_cases.json](tests/benchmark/chat_eval_cases.json) | 63 cases |
| Benchmark runner | [scripts/run_chat_benchmark.py](scripts/run_chat_benchmark.py) | — |
| Retrieval precision runner | [scripts/run_retrieval_precision.py](scripts/run_retrieval_precision.py) | — |
| USGS data verifier | [scripts/verify_usgs_data.py](scripts/verify_usgs_data.py) | — |

## Appendix B — Numeric facts worth citing verbatim

- Monitoring network: **44 wells** (verified from `len(SITE_METADATA)` at import time).
- County distribution: Miami-Dade 15, Lee 11, Collier 6, Hendry 4, Sarasota 4, generic "Florida" 4.
- Aquifer distribution: Biscayne 15, Surficial 7, Floridan 6, Tamiami 5, Florida 4, Intermediate 4, Hawthorn 3.
- USGS data date range across sampled CSVs: **1994-01-01 through 2026-04-05**; 40 canonical CSV files under [data/](data/), daily cadence, ~10k rows per well.
- Knowledge base: ChromaDB persistent store, BAAI/bge-small-en-v1.5 embeddings (384-dim), `chroma.sqlite3` ≈ 156 MB.
- Benchmark: **63 / 63 passing**, overall score **1.000**, average citation coverage **0.986**, median latency **0.085 s**, max latency **12.314 s**.
- Unit tests: **205 passing** as of 2026-04-14.
- Citation thresholds: `MIN_CLAIM_CITATION_COVERAGE = 0.90`, `MIN_SECTION_CITATION_COVERAGE = 0.90`.
- Insights bullet cap: 5 (ordered: highlighted wells → cohort trend + risk → fastest decline → strongest rise → largest divergence).
- Default LLM agent timeout: **300 s**; search budgets: `max(3, depth*2+2)` web searches, `max(6, depth*4)` KB searches, `max(10, depth*6)` API calls.
- Trend slope unit: feet per monthly bin × 12 → ft/yr; trend series are named e.g. `"Cohort Trend (-0.18 ft/yr)"` with the annual rate pulled from `per_site_metrics[*].annual_change_ft_yr`.
- Risk classification thresholds: `high` if ≥66% of wells falling, `moderate` if ≥33% falling (or ≥20% falling in a mostly-confined cohort), `low` otherwise.
- Frontend bundle: lazy-loaded `AgentChart` and `ResearchChartsPanel` via `React.lazy` + `Suspense` with `<div className="h-[320px]" />` fallbacks.
- Backend unreachable detection: `TypeError` from `fetch()` → `backendStatus → 'down'`, visible banner, auto-dismiss on next success.

---

*End of document. Intended use: upload to NotebookLM as a grounding source for manuscript drafting. Every numeric claim is verifiable against the cited file path or by running the benchmark harness locally.*
