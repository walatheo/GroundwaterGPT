# EAGLE Technical Overview

**Document purpose.** This is a low-level, audit-oriented description of EAGLE (Evidence-Aligned Groundwater Level Explorer) as it exists in the repository on 2026-04-16. It is intended as grounding material for a manuscript workflow. Every architectural claim, numeric threshold, and data-flow assertion is tied to concrete files and line ranges in the code so that a downstream author or reviewer can verify it without re-reading the codebase from scratch.

> Naming note: the repository directory, Python module names, and `GROUNDWATERGPT_*` environment-variable prefix predate the EAGLE rename and are intentionally preserved as stable interfaces. "EAGLE" is the user-facing system name; file paths and env vars in this document still read `GROUNDWATERGPT_*` because they do on disk.

**Central property the manuscript rests on.** EAGLE is primarily a **research utility for public Florida groundwater data**, not an LLM demonstration. Every quantitative claim about monitored groundwater behaviour is emitted by a **deterministic hydrogeologic pipeline** running directly over USGS CSVs. Retrieval and LLM components can help explain the hydrogeologic meaning of those measured patterns, but they do not create measured trend values, rates, charts, citations, or provenance. Structured LLM outputs are bound to deterministic claim-and-evidence identifiers; optional narration remains subordinate to the deterministic report and should not be treated as an independent evidence source. The recent chart-follow-up work mostly improves how deterministic interpretation is packaged on the chat surface (`learner_brief`, clearer caveats, grouped follow-ups); it should not be described as a new hydrogeologic inference engine or as evidence of a stronger LLM layer. The deterministic benchmark passes at 100% without the LLM active at all.

**Document structure.**

1. System purpose and scope
2. Data substrate: USGS monitoring records, per-site metadata, and the local knowledge base
3. Deterministic hydrogeologic analysis layer (the reference pipeline)
4. Language-model layer — what is active vs dormant
5. Join point, typed session contract, provenance, streaming, citation integrity
6. Worked example: the Village of Estero question
7. Auxiliary surfaces (research workflow, workbench, chat surface)
8. Frontend surface — how auditability reaches the user
9. Evaluation and measured behaviour
10. Strengths, limitations, threats to validity
11. **Cleanup status and remaining work**
12. Appendix A — File map for citation
13. Appendix B — Numeric facts worth citing verbatim

---

## 1. System purpose and scope

### 1.1 What EAGLE is

EAGLE is a research-grade, audit-oriented question-answering and visualization platform for Florida groundwater monitoring data. Its domain is a fixed set of **44 USGS groundwater wells** (counted from [api/site_metadata.py](api/site_metadata.py) via `len(SITE_METADATA)`) distributed across five Florida counties (Miami-Dade: 15, Lee: 11, Collier: 6, Hendry: 4, Sarasota: 4) plus four generic "Florida" entries. Per-well water-level time series are stored as CSV under [data/](data/). Site-level hydrogeologic metadata recognizes seven aquifer labels — Biscayne Aquifer (15), Surficial Aquifer (7), Floridan Aquifer System (6), Tamiami Aquifer System (5), Florida Aquifer (4), Intermediate Aquifer System (4), Hawthorn Group (3) — and distinguishes confined vs unconfined settings, aquifer zone depth ranges, and well depths.

The system answers three broad classes of questions:

- **Descriptive / comparative questions over the USGS record** ("what has been the change in groundwater level in Estero over the last 30 years"; "compare G-3336 and G-5004"; "which wells in Miami-Dade have the steepest decline"). These go through the deterministic fallback engine.
- **Domain knowledge questions** ("which aquifer supplies Estero", "what confines the Floridan aquifer"). These retrieve from a local ChromaDB knowledge base grounded by a source-verification layer.
- **Open-ended research questions** ("has groundwater in Lee County stabilized since 2015", "cross-aquifer comparison of Biscayne vs Floridan trends"). The codebase contains a `DeepResearchAgent` that plans sub-questions, iterates KB retrieval, and synthesizes a structured report — but this agent is **disabled in the demo and evaluation** (`GROUNDWATERGPT_SKIP_AGENT_INIT=1`). In practice, these questions fall through to the deterministic keyword routing and are answered by the same pipeline as descriptive questions. The agent is architecturally complete but operationally dormant (see §4).

The design goal, stated across the code and in-repo docs, is **explainability**: every path that produces user-visible text also produces (a) a list of sources, (b) a per-claim citation record, (c) a verdict and confidence score, (d) a deterministic chart whenever the question can be backed by monitored well data, and (e) a reproducibility block (`research_provenance_v1`) with `code_commit`, `response_sha256`, per-CSV `data_snapshot` hashes, and config hashes. The LLM is an **enhancement**, not a **dependency** — the fallback path alone passes the benchmark suite to 68/68.

### 1.2 What EAGLE is not

It is not a hydrologic model — it does not solve Darcy's law, does not run groundwater-flow simulations, and does not couple surface-water and groundwater processes. Historical forecast experiments have been removed from the maintained tree and should stay out of manuscript claims until a future served, validated forecasting path exists.

It is not a national or global service — adding a new site requires editing [api/site_metadata.py](api/site_metadata.py)'s underlying JSON and dropping a matching `usgs_<15-digit>.csv` into [data/](data/). There is no dynamic site discovery.

It is not a web-search research agent. An optional DuckDuckGo backend exists in [src/agent/research_agent.py](src/agent/research_agent.py) but is **off by default** — [api/routes/chat.py:363](api/routes/chat.py#L363) reads `GROUNDWATERGPT_ENABLE_WEB_SEARCH` and passes `use_web_search=False` unless explicitly opted in. In the deployed demo the LLM operates over the local KB and the deterministic-layer output only. The manuscript should not describe this as a web-research tool.

---

## 2. Data substrate

### 2.1 USGS time-series CSVs

The canonical well data lives in [data/usgs_{15-digit-site-id}.csv](data/). There are 40 canonical files with schema `site_no, datetime, value`, where `value` is depth-to-water in feet relative to land surface. Combined date coverage across sampled files is **1994-01-01 through 2026-04-05**; some wells begin as early as 2003 and some as early as the mid-1990s. Observations are stored daily and resampled to month-start (`MS`) means inside every analysis path.

The CSVs are loaded lazily and cached in-process by `_load_site_timeseries` at [api/routes/_detection.py:289](api/routes/_detection.py#L289) (module-level `_SITE_SERIES_CACHE`). The loader reads the CSV, coerces `datetime` via `pd.to_datetime(errors="coerce")`, coerces `value` via `pd.to_numeric(errors="coerce")`, drops NaN rows, sorts by datetime, and returns the resulting DataFrame (or `None` on failure). Every downstream analysis path goes through this single loader — the in-memory schema is an invariant.

The directory also contains several `usgs_<id>_<YYYYMMDD>.csv` snapshot files. `_load_site_timeseries` only reads the canonical `usgs_<id>.csv`, so the snapshots are **inactive** (see §11 Cleanup).

### 2.2 Site metadata

[api/site_metadata.py](api/site_metadata.py) exposes `SITE_METADATA: dict[str, dict]` — the authoritative per-site metadata table. It is loaded from `config/usgs_sites.json` at import time and, for sites present on disk but missing from that JSON, filled from a best-effort CSV scan. Each entry contains: `id, name, aquifer, aquifer_type, confined, aquifer_zone, aquifer_zone_depth_range_ft, aquifer_description, county, lat, lng, well_depth_ft, depth, description`. Aquifer strings are normalized (Biscayne, Floridan, Surficial, Tamiami, Intermediate, Hawthorn) so that downstream keyword detection is deterministic. Everything else — the router, the chart builder, the KB ingestion summaries — derives from this single file.

### 2.3 Knowledge base

The knowledge base is a ChromaDB persistent store under [knowledge_base/](knowledge_base/) (`chroma.sqlite3`, ≈156 MB). The embedding model is `BAAI/bge-small-en-v1.5` (384-dim) loaded via `sentence-transformers`, configured in [src/agent/knowledge.py](src/agent/knowledge.py) at `EMBEDDING_MODEL_NAME` (line 58) and `CHROMA_DIR` (line 55). Ingestion uses `PyPDFLoader` plus `RecursiveCharacterTextSplitter`; every import is guarded so the rest of the system runs even without `chromadb` / `langchain_chroma`.

The indexed corpus covers three source families:

- **Hydrogeology reference PDFs** under [resources/pdfs/](resources/pdfs/): `a-glossary-of-hydrogeology.pdf`, `age-dating-young-groundwater.pdf`, `a-conceptual-overview-of-surface-and-near-surface-brines-and-evaporite-minerals.pdf`, plus two `.gitignore`'d subdirectories (`references/`, `usgs_reports/`).
- **Per-well USGS summaries** generated from the CSV data itself, so that queries like "what is the record length at G-3336" can be answered without re-parsing the CSV.
- **Domain Q&A corpus** — hand-written short answers for frequent domain questions (aquifer supply, confinement, water-budget basics).
- **Curated hydro interpretation bank** in [config/interpretation_answer_bank.json](config/interpretation_answer_bank.json). This small local corpus gives the chart interpreter fast concept snippets for drawdown, recharge, seasonality, confinement, shallow/deep comparisons, supply-proxy limits, saltwater-intrusion risk, and causality caveats. It is treated as explanatory context only; it cannot add numeric trend claims.

[`api/routes/knowledge.py`](api/routes/knowledge.py) exposes `/api/knowledge/stats`, `/api/knowledge/status` (lightweight readiness check that does not load the embedding model), and `/api/knowledge/ingest`. The lightweight status check exists because loading the embedding model is the slowest part of cold startup.

For the manuscript argument the KB's role is narrow: it supplies aquifer supply / confinement / domain sentences and hydrogeologic interpretation language that help phrase the "what does this mean" half of a question like the Estero example. It does not contribute numeric trend values; every numeric conclusion traces back to a USGS CSV via `_load_site_timeseries`.

### 2.4 Forecasting status

Forecasting is not part of the maintained serving system. The previous standalone scikit-learn forecast experiment has been removed, along with generated model and plot artifacts, because it did not have a served endpoint, rolling-origin validation, uncertainty handling, or manuscript-ready evaluation.

---

## 3. Deterministic hydrogeologic analysis layer

This is the layer the manuscript should describe as the reference-truth pipeline. It turns USGS CSVs into cited, chart-backed conclusions without any language model in the loop, and it is the sole source of the quantitative claims that downstream LLM synthesis is allowed to cite.

### 3.1 FastAPI surface

The backend is a FastAPI application defined in [api/main.py](api/main.py) (54 lines). Five routers are mounted at [api/main.py:34-38](api/main.py#L34-L38):

- `data_router` — [api/routes/data.py](api/routes/data.py) (239 lines): `GET /api/sites`, `GET /api/sites/{site_id}`, `GET /api/sites/{site_id}/data`, `GET /api/sites/{site_id}/heatmap`, `GET /api/compare`, `GET /api/sites/{site_id}/chart`, `GET /api/compare/chart`.
- `chat_router` — [api/routes/chat.py](api/routes/chat.py) (2793 lines): `POST /api/chat`, `POST /api/interpret`, `POST /api/research`, `POST /api/research/stream`, `GET /api/chat/status`. Hosts the routing chain, chart-follow-up interpreter handoff, response normalization, provenance attachment, and both deterministic and LLM paths.
- `knowledge_router` — [api/routes/knowledge.py](api/routes/knowledge.py) (88 lines): `GET /api/knowledge/stats`, `GET /api/knowledge/status`, `POST /api/knowledge/ingest`.
- `research_workflow_router` — [api/routes/research_workflow.py](api/routes/research_workflow.py) (255 lines): `POST /api/research/plans`, `GET /api/research/plans`, `GET /api/research/plans/{plan_id}`, `POST /api/research/plans/{plan_id}/runs`, `POST /api/research/plans/{plan_id}/draft`, plus the `POST /api/research/workbench` mount at [line 243](api/routes/research_workflow.py#L243) that delegates to `build_research_workbench_payload` in [api/routes/_research_workbench.py](api/routes/_research_workbench.py) (581 lines).
- `wells_router` — [api/routes/wells.py](api/routes/wells.py) (176 lines): `GET /api/wells` — the canonical per-well metadata listing consumed by the frontend dashboard.

CORS is open only to `http://localhost:3000` and `http://127.0.0.1:3000` ([api/main.py:25-31](api/main.py#L25-L31)). The `_research_workbench` module is not its own router — it is a builder library imported by `research_workflow.py`.

### 3.2 Routing chain — selecting the cohort for a question

Every textual question enters through one of four chat-router endpoints — `POST /api/chat` (quick answer, [chat.py:1106](api/routes/chat.py#L1106)), `POST /api/research` (deep research, non-streaming, [chat.py:1335](api/routes/chat.py#L1335)), `POST /api/research/stream` (deep research over SSE, [chat.py:2113](api/routes/chat.py#L2113)), and `GET /api/chat/status` (readiness + degraded reasons, [chat.py:2186](api/routes/chat.py#L2186)). The first three share the same **routing chain** with detection helpers in [api/routes/_detection.py](api/routes/_detection.py):

1. **Site-name detection** (`_detect_site_names` at [_detection.py:439](api/routes/_detection.py#L439)): `_WELL_NAME_RE = \b([A-Za-z]{1,3})[\s\-]?(\d{3,5})\b` ([line 435](api/routes/_detection.py#L435), catches G-3336, C-1224) and `_RAW_SITE_ID_RE = \b(\d{15})\b` ([line 436](api/routes/_detection.py#L436)). If hit → site-fallback branch.
2. **Aquifer detection** (`_detect_aquifer` at [_detection.py:183](api/routes/_detection.py#L183)): longest-first substring match against `_AQUIFER_DETECTION_MAP` ([line 146](api/routes/_detection.py#L146), 20+ surface forms: biscayne aquifer, tamiami, upper floridan, surficial, intermediate, hawthorn group, …) → `(aquifer_key, display_name)`. If hit → aquifer-fallback branch with `_sites_for_aquifer(aquifer_key, max_sites=8)` ([line 372](api/routes/_detection.py#L372)).
3. **Multi-location comparison** (`_detect_locations` at [_detection.py:196](api/routes/_detection.py#L196) + `_is_multi_location_compare_query`): if two or more location tokens and the query reads like a comparison → merged cohort via `_sites_for_multiple_locations`.
4. **Single-location detection** (`_detect_location` at [_detection.py:132](api/routes/_detection.py#L132)): word-boundary match against `_LOCATION_REFERENCE_POINTS` ([line 95](api/routes/_detection.py#L95)), a dict of Florida place names (Estero, Naples, Miami, Cape Coral, Immokalee, …) each mapping to `(lat, lng, display_name, county_hint)`. If hit → `_best_sites_near(lat, lng, county_hint, max_sites=10)` ([line 320](api/routes/_detection.py#L320)) → location-fallback branch.
5. **Network-wide detection** (`_is_network_wide_query` at [_detection.py:538](api/routes/_detection.py#L538)): keyword check against `_NETWORK_WIDE_KEYWORDS` ([line 504](api/routes/_detection.py#L504), "all wells", "every county", "network-wide", "confined vs unconfined", …). If hit → `_all_sites_with_data(max_sites=36)` ([line 544](api/routes/_detection.py#L544)) → network-fallback branch.
6. **LLM research agent (dormant)** — the code path when `/api/research*` is used and nothing above matches. In the demo and evaluation configuration (`GROUNDWATERGPT_SKIP_AGENT_INIT=1`), `_research_agent` is `None` and the chain falls back through the keyword filters. The agent path is exercised only in a manual one-case smoke test (§9.3).

`_best_sites_near` uses Haversine distance plus a `-0.3` score bonus for county matches. It is deliberately crude — the manuscript should describe it as a reproducible proxy-selection rule, not a spatial interpolator.

### 3.3 `_site_research_fallback` — the reference pipeline

The core is `_site_research_fallback` at [api/routes/_site_analysis.py](api/routes/_site_analysis.py), inside a 1970-line module that also hosts the trend, changepoint, cluster, supply-interpretation, answer-brief, and chart primitives. Given a question, a list of selected sites, a location label, and optional lat/lng pins, it:

- Computes per-site summary statistics — start/end dates, record length, net change (ft), annual rate (ft/yr), trend classification.
- Runs `_cross_well_analysis` to build the cohort summary: `trend_distribution`, `mean_annual_change_ft_yr`, `std_annual_change_ft_yr`, `divergent_pairs` (bounded to top 3), **screened two-segment changepoints**, **standardized-feature behaviour clusters**, and `risk_level ∈ {low, moderate, high}`.
- Assembles a structured report with aquifer-grouped sections, a cross-aquifer comparison when multiple aquifers are present, and an explicit period-of-record statement.
- Builds a `claim_citations` list. Each quantitative or domain sentence in the report gets a `claim_id` (e.g. `claim_003`), `claim` text, `claim_type`, `confidence`, `evidence_ids`, and a `citations` list of `{url, verified, trust_level}` entries drawn from USGS NWIS URLs + KB matches.
- Calls `_build_claim_verdicts` / `_build_claim_verdict_summary` from [api/routes/_citation.py](api/routes/_citation.py) to produce verdicts (`supported / contradicted / insufficient_evidence` with `risk_score ∈ [0, 1]`). When the disagreement engine is disabled, the conservative fallback is "citations present → supported (risk 0.3); no citations → insufficient (risk 0.85)".
- Calls `_build_citation_integrity` (same citation module) to produce the integrity record: `claim_citation_coverage`, `section_citation_coverage`, `passed` boolean keyed off `MIN_CLAIM_CITATION_COVERAGE` and `MIN_SECTION_CITATION_COVERAGE` env-configurable thresholds (default 0.90).
- Calls `_build_chart_payload` to produce the Recharts-ready chart JSON (§3.5).

Every keyword-routed path in the routing chain goes through this function. This is the single, tested, fully-cited code path for the safe subset of queries, and it is what gives the benchmark its 68/68 pass rate without requiring the LLM.

### 3.4 Trend, changepoint, and cluster primitives

**Trend slope.** `_linear_trend_values_with_slope` at [api/routes/_site_analysis.py:472](api/routes/_site_analysis.py#L472) computes an ordinary least-squares fit over the ordered monthly points. It is explicitly named `slope_per_bin` because one regression x-unit is one month; the annual rate is `slope_per_bin × 12`. Per-well annual rates are computed once by `_cross_well_analysis` ([line 355](api/routes/_site_analysis.py#L355)) and pulled from `per_site_metrics[*].annual_change_ft_yr` downstream, so the report text, chart legend, and claim-citation objects all reference the same number. A unit test in [tests/unit/test_inline_chart.py](tests/unit/test_inline_chart.py) asserts every trend legend entry ends in `ft/yr`.

**Changepoint screen.** `_detect_changepoint` at [api/routes/_site_analysis.py:191](api/routes/_site_analysis.py#L191) compares a single-line OLS fit over all monthly bins against the best two-line split with at least 12 bins on each side. The supporting helpers `_monthly_values` ([line 166](api/routes/_site_analysis.py#L166)) and `_linear_fit_sse` ([line 174](api/routes/_site_analysis.py#L174)) keep the screen self-contained. A changepoint is reported only when residual error improves by ≥20%. Confidence label is `high ≥ 0.45 / moderate ≥ 0.30 / low ≥ 0.20`. The output records `date`, `pre_annual_change_ft_yr`, `post_annual_change_ft_yr`, `full_period_annual_change_ft_yr`, `improvement_ratio`, `confidence`. This is a **screening statistic, not a formal hypothesis test**; the report wording is conservative ("candidate changepoint"). `test_cross_well_analysis_adds_changepoints_and_clusters` in [tests/unit/test_inline_chart.py](tests/unit/test_inline_chart.py) asserts the screen fires on a synthetic step-change well.

**Cross-well clustering.** `_cluster_wells` at [api/routes/_site_analysis.py:246](api/routes/_site_analysis.py#L246) groups wells by deterministic local-data features: annual change, seasonal amplitude (from `_seasonal_decomposition` at [line 119](api/routes/_site_analysis.py#L119)), and a confinement indicator. Features are standardized (zero mean, unit std-dev or 1.0 if degenerate). Wells are assigned to `k=3` (or `k=2` if fewer than six wells) fixed-initialization k-means clusters — initial centroids are chosen deterministically (min / median / max by annual change), the algorithm runs for at most 20 iterations, and each cluster is labelled with a compact descriptor like `"declining seasonal wells"` plus `n_sites`, `site_ids`, `names`, `dominant_aquifer`, `mean_annual_change_ft_yr`, `mean_seasonal_amplitude_ft`.

**Risk classification.** `_cross_well_analysis` sets `risk_level = high` if ≥66% of wells are falling, `moderate` at ≥33% (or ≥20% in a mostly-confined cohort), else `low`. Thresholds are engineering defaults without empirical calibration (§10 Limitations).

**Divergent pairs.** The top divergent pairs are selected as the wells with the most opposite-signed annual rates in the cohort, bounded to 3. They drive the "highlighted" styling in the chart and one of the insight bullets.

`_cross_well_analysis` is the structured object that `_site_research_fallback` renders into both the markdown report **and** the `claim_citations` list — the same numbers appear in prose and in the machine-readable audit trail.

### 3.5 `_build_chart_payload` — the single chart builder

`_build_chart_payload` at [api/routes/_site_analysis.py:570](api/routes/_site_analysis.py#L570) is the deterministic chart builder, paired with `_build_chart_insights` at [line 518](api/routes/_site_analysis.py#L518).

- **Input:** list of site dicts (metadata + pandas time series), a location label, an optional `cross_well` summary.
- **Output:** a Recharts-ready JSON with `chart_type`, `title`, `x_label`, `y_label`, `series`, `data` (one row per month), `insights` (capped at 5), `cohort_risk_level`.

It resamples every well's time series to month-start means (`df.set_index("datetime")["value"].resample("MS").mean().dropna().round(2)`), unions observed dates, and writes one `data` row per date with a column per site ID. With two or more wells it adds an `"avg"` series (cohort mean, dashed stroke, `highlight=True`). It then computes linear trends on the cohort average and on highlighted wells — a well is highlighted if it is part of `divergent_pairs[0]` or is the fastest-declining / strongest-rising well per `_cross_well_analysis`. Trend series names are interpolated as e.g. `"Cohort Trend (-0.18 ft/yr)"`.

The `insights` block (`_build_chart_insights`) is capped at **five** bullets and leads with `"Highlighted wells mark the most divergent or fastest-changing series ({n} total)."`, followed by cohort trend + risk, fastest decline, strongest rise (if positive), largest-divergence pair. This ordering is load-bearing: it is how a user reading the chart knows why certain lines are thick and the rest are dim.

---

## 4. AI / language-model layer — what is active vs dormant

The AI layer exists to make deterministic groundwater analysis easier to ask about, interpret, and communicate. It does not independently conclude about monitored groundwater behaviour. The manuscript should describe the system as an **auditable interpretation pipeline** with **evidence-guided AI**: deterministic code owns the measured facts, and AI/RAG components help phrase, structure, explain, and progress to the next grounded question.

### 4.0 AI usage pipeline

For sponsor and manuscript purposes, AI is used in four bounded places:

1. **Optional natural-language narration of deterministic reports.** `_site_research_fallback` computes the wells, trends, charts, citations, claim verdicts, and provenance first. If local LLM synthesis is enabled and an Ollama daemon is available, the current/default model is local Ollama `llama3.2` (`SYNTHESIS_MODEL` can override it). The model narrates those deterministic findings in clearer hydrogeology language. This narration is subordinate to the deterministic report and is disabled during deterministic benchmark runs.
2. **Intent-aware chart interpretation.** Chart follow-ups are routed to [api/routes/_chart_interpreter.py](api/routes/_chart_interpreter.py). The primary answer path is deterministic: the interpreter detects the user intent, builds an `EvidencePack` from current chart site IDs, and answers from cross-well metrics, site metadata, and chart context. Structured LLM synthesis is optional here and is requested by the sponsor UI only when `VITE_ENABLE_LLM_INTERPRETATION=true`; otherwise chart follow-ups use the fast deterministic interpreter. The deterministic answer builders already handle shallow/deep comparison, fastest-changing well, cohort-average meaning, and risk explanation.
3. **Evidence-guided progression.** Grounded chat and interpretation replies now add a backend-owned `next_goal` plus grouped follow-up questions. These are derived deterministically from the current grounded answer, caveat, evidence-needed fields, chart context, well names, supply-unit mappings, and any surfaced date windows. An optional bounded LLM rewrite can sharpen wording, but it may not add new wells, dates, numbers, or causal claims; unsupported rewrites fall back to the deterministic progression contract.
4. **Curated RAG-style hydro context.** [config/interpretation_answer_bank.json](config/interpretation_answer_bank.json) supplies local hydrogeology concepts — drawdown, recharge, seasonality, confinement, supply-proxy limits, saltwater-intrusion caveats, uncertainty, and evidence-needed language. These snippets explain what an observed pattern may mean; they are not numeric evidence.
5. **Experimental research-agent architecture.** `DeepResearchAgent` remains in the repository as an architectural experiment for planned multi-step research, but it is hidden from the sponsor UI and disabled in the demo/evaluation startup path. It should be described as future work unless it is explicitly enabled and benchmarked.

The operational pipeline is therefore:

`User question` → `deterministic router/site selector` → `USGS CSV + metadata analysis` → `chart + numeric claims + citations + provenance` → `optional interpretation/narration layer` → `frontend answer + Analytical Depth panel`.

The important boundary is that **numbers flow left-to-right from deterministic analysis into AI**, never the other way around.

**Operational status.** In the current sponsor/demo configuration, the research agent is hidden and disabled. The default visible chart-follow-up path is deterministic. If optional LLM narration or chart synthesis is enabled and available, the default local model is Ollama `llama3.2`; Qwen is not the default active model and is used only when `DASHSCOPE_API_KEY` is configured.

1. **Hybrid in-process narration (available in demo, disabled in benchmarks).** Inside `_site_research_fallback`, every keyword-routed chat branch (site / aquifer / multi-location / single-location / network-wide) defaults `allow_llm_synthesis=True`, and the fallback can post a scoped hydrogeologist prompt to a local Ollama server (default `llama3.2` at `http://localhost:11434`) that narrates the deterministic numbers the pipeline has already produced. The narration is gated by `_llm_synthesis_enabled()` at [api/routes/_site_analysis.py](api/routes/_site_analysis.py), which reads the `GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS` env var — set it to `1` and the response reverts to pure-deterministic output. The deterministic benchmark sets this flag. If Ollama is not running, the deterministic answer still returns.
2. **Structured chart-interpreter LLM synthesis (optional, not required).** `interpret_with_context` can call `_invoke_structured_llm` only when `allow_llm_synthesis=True`. The frontend sends that flag from `VITE_ENABLE_LLM_INTERPRETATION`; the default sponsor setting is false to keep chart follow-ups fast and reliable. With no external key configured, the optional structured path uses local Ollama (`SYNTHESIS_MODEL`, default `llama3.2`). If `DASHSCOPE_API_KEY` is present, the interpreter can try Qwen first (`GROUNDWATERGPT_INTERPRETER_MODEL`, default `qwen-plus`) through the DashScope OpenAI-compatible endpoint. The LLM does not receive the raw chart summary as its visible-answer template; instead it receives a compact deterministic explainer seed built from `question_intent`, `direct_answer`, `supporting_evidence`, `meaning_brief`, numeric claims, evidence-needed fields, and the current caveat. The LLM must return an `InterpretationResult`; numeric claims are reconciled against deterministic values before emission, and low-quality summary-echo answers are rejected in favor of the deterministic intent answer. `grounding_status` reports `llm_provider` and `llm_model` when synthesis succeeds.
3. **`DeepResearchAgent` (dormant).** The demo startup script ([scripts/start_demo.sh:84](scripts/start_demo.sh#L84)) sets `GROUNDWATERGPT_SKIP_AGENT_INIT=1`, which prevents the agent from constructing ([api/routes/chat.py:558](api/routes/chat.py#L558)). All unit tests run with the same flag. The 68-case chat benchmark and the 25-case interpretation benchmark both run without the agent. A one-case manual smoke test exists (§9.3) but scored 0.200 and failed thresholds. **The manuscript should not describe the research agent as an active component of the evaluated system.**

### 4.1 `DeepResearchAgent` — architectural note (dormant)

`DeepResearchAgent` is defined at [src/agent/research_agent.py:246](src/agent/research_agent.py#L246) (1980 lines). It composes a `ResearchPlanner`, `PriorityRanker`, `SelfReflectionEvaluator`, `StructuredReportBuilder`, and `ResearchSessionPersistence` from [src/agent/research_optimizer.py](src/agent/research_optimizer.py). It supports five LLM providers through [src/agent/llm_factory.py](src/agent/llm_factory.py) (Ollama, OpenAI, Anthropic, Google, Qwen). DuckDuckGo web search is off by default. The agent is wired into [api/routes/chat.py](api/routes/chat.py) as `_research_agent` and would handle open-ended questions that miss the keyword routing chain, but in the demo and evaluation configuration it is `None` and those questions fall back to the deterministic pipeline.

The default LLM provider for optional local synthesis is therefore Ollama `llama3.2`, used only for narration/synthesis over deterministic context when enabled and available. Qwen is a provider option, not a separate evidence source or active research mode. In [src/agent/llm_factory.py](src/agent/llm_factory.py), `LLMProvider.QWEN` wraps Alibaba DashScope through an OpenAI-compatible `ChatOpenAI` client using `DASHSCOPE_API_KEY` and model names such as `qwen-plus`, `qwen-max`, or `qwen-turbo`. In the chart-interpreter path, Qwen is used only if that key exists and `VITE_ENABLE_LLM_INTERPRETATION=true` causes the frontend to request structured synthesis; otherwise the system uses local Ollama or the deterministic interpreter.

The agent's synthesis layer contains the evidence-registry and structured-response machinery (`_build_evidence_items`, `_parse_structured_response`, `_heuristic_structured_response`, `_render_structured_report`) that the evidence-binding argument depends on. These functions are unit-tested with mock LLMs in [tests/unit/test_agent.py](tests/unit/test_agent.py) — the tests verify that claim/evidence IDs survive the synthesis round-trip, that invalid IDs are dropped, and that the heuristic fallback produces valid `evidence_response_v1` objects. However, these tests use mock LLMs returning fixed strings, not real model outputs. The architectural guarantee (typed claim binding) is tested; the operational quality (does the agent produce good answers?) is not.

**What the 15 agent tests actually validate:**

| Test | Validates |
|---|---|
| `TestLlmRetry` (3 tests) | Retry logic succeeds, retries on failure, raises after exhaustion |
| `TestResearchContext` (3 tests) | `should_continue`, `request_stop`, `add_insight` control flow |
| `TestResearchAgentConstruction` (3 tests) | Agent constructs with mock LLM, reports idle status, stops cleanly |
| `TestResearchSectionConfidence` (1 test) | Section-confidence computation from claims |
| `TestStructuredResearchSynthesis` (2 tests) | `_heuristic_structured_response` preserves claim/evidence IDs; `_parse_structured_response` deduplicates and drops invalid claims |
| `TestClaimVerdicts` (1 test) | Claim verdicts are present in research output |
| `TestHallucinationGuardrail` (1 test) | Uncited factual sentences are stripped |
| `TestLlmFactory` (1 test) | Provider enum has expected members |

The tests prove the synthesis **machinery** works — not that the agent produces useful groundwater answers.

### 4.2 Evidence-binding contract — `evidence_response_v1`

The evidence-binding design is the architectural invariant the manuscript rests on. The deterministic response always carries a `structured_response`; optional narration is constrained by the deterministic report and should not be treated as an independent evidence source. The dormant agent path uses the same registry-and-parser machinery when it is enabled, but its operational quality has not been evaluated at scale.

**Evidence registry.** `_build_evidence_items` iterates over `claim_citations` entries (produced by `_site_research_fallback`) and emits `{evidence_id, claim_id, url, trust_level, verified}` records. Every `evidence_id` is a stable handle into a known source record. The registry is the source of the `structured_response` audit object and the constraint set for structured LLM synthesis paths.

**Structured response.** When the structured synthesis path is active, the LLM is asked to return JSON with `answer`, `claims[*] = {claim, claim_type, claim_ids, evidence_ids, confidence, is_interpretive, uncertainty}`, `limitations`, and `recommended_followup`. The parser (`_parse_structured_response`) filters `claim_ids` and `evidence_ids` to the intersection with valid registries; claims with no surviving IDs are dropped. When no structured LLM output is available, `_heuristic_structured_response` builds the same `evidence_response_v1` directly from the deterministic claim registry.

Either branch produces `schema_version = "evidence_response_v1"`. This is returned on every response via `_augment_research_payload` / `_build_chat_payload` so downstream code can rely on its presence.

**What is tested vs not.** The `_heuristic_structured_response` path — which is what actually runs in the demo and benchmarks — is unit-tested and exercises the full claim-binding round-trip. The LLM-narration parse path is unit-tested with synthetic JSON. Neither test exercises a real LLM generating real responses against real groundwater questions.

---

## 5. Join point, typed session contract, provenance, streaming, citation integrity

### 5.1 `_agent_chart_hook` — byte-identical cross-path charts

When the LLM agent returns a result, its output schema includes `report`, `insights`, `sources`, `chart_specs`, `tool_trace`, `claim_citations` — but **not** a chart payload in the Recharts shape the frontend expects. Historically the agent path silently emitted no chart even when it had clearly identified sites. The fix, in [api/routes/_agent_chart_hook.py](api/routes/_agent_chart_hook.py), is a post-hoc attachment layer:

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

`_extract_site_ids_from_agent_result` walks `chart_specs`, `tool_trace`, `wells`, and `sources` recursively, picking up any 15-digit USGS site ID (`_SITE_ID_RE = re.compile(r"\b\d{15}\b")`) and deduplicating in discovery order. The chart is then synthesized by the **same** `_build_chart_payload` the deterministic path uses. That is the architectural guarantee: the agent path and the fallback path emit **byte-identical chart schemas** for the same selected cohort, because the chart comes from one function regardless of which path chose the sites. **Operational note:** because the agent is dormant in the demo configuration, this hook is not exercised in normal operation. It is tested by a unit test with a stubbed agent result (`test_streaming_agent_path_yields_chart_in_final_event`) that confirms the chart shape is correct, but the test does not involve a real agent call.

Downstream, every chart emission is centralized through a helper `_chart_from(result, *, path: str)` in [api/routes/chat.py](api/routes/chat.py) that reads `result.get("chart")`, logs a structured `chart_decision path=<label> emitted=<bool>` debug line, and returns the chart or `None`. This helper is called from all ~16 chat/research branches in the file (site, aquifer, multi-location, location, network, research variants of each, agent success, streaming agent success). Centralizing it means the "does this branch emit a chart" question is now observable and un-regressable.

### 5.2 Typed session contract — `_augment_research_payload` and `_build_chat_payload`

Two helper functions in [api/routes/chat.py](api/routes/chat.py) normalise every response so that the payload contract is identical regardless of which routing branch served the answer.

`_augment_research_payload` at [api/routes/chat.py:928](api/routes/chat.py#L928) is called on every research-path response. It defaults `session_id` (deterministic hash of `(question, default_mode)`), `research_plan` (via `_heuristic_research_plan`), `budget_status` (via `_build_budget_status`), `checkpoints` (a single `cp_001` `response_ready` entry), `tool_trace`, `recommended_views`, `chart_specs`, `aquifer_info`, and crucially `structured_response`, `changepoints`, `cross_well_clusters`, and `provenance`. The `structured_response` default goes through `_build_structured_response_from_claims`, the `provenance` default goes through `build_research_provenance` (§5.3). Every research response therefore carries the full audit envelope even on the deterministic-only path.

`_build_chat_payload` at [api/routes/chat.py:1004](api/routes/chat.py#L1004) is the parallel for `/api/chat`. It guarantees the response object always carries `claim_citations`, `claim_verdicts`, `claim_verdict_summary`, `section_confidence`, `citation_summary`, `citation_integrity`, `hallucination_guardrail` (the deterministic guardrail object that records `strategy`, `removed_uncited_factual_sentences`, `all_factual_claims_cited`, `has_llm_synthesis`), and `cohort_risk_level`. The KB-only fallback uses `_ground_fallback_chat_response` ([line 1072](api/routes/chat.py#L1072)) which wraps the lightweight KB hit in the same shape with `strategy = "deterministic_kb_fallback"` so the response schema is invariant.

Both helpers run unconditionally — there is no branch in the routing chain that can emit a chat or research response without going through them. This is what makes the audit envelope a system-wide invariant rather than a best-effort feature.

### 5.3 Provenance block — `research_provenance_v1`

Every research response is passed through [api/routes/_provenance.py](api/routes/_provenance.py), which attaches `research_provenance_v1`:

- `schema_version`: literal `"research_provenance_v1"`.
- `generated_at`: UTC ISO timestamp.
- `route_mode`: which branch of the routing chain served the answer.
- `code_commit`: current git `HEAD` (via `subprocess` with a 2-second timeout), or `null`.
- `response_sha256`: SHA-256 over a stable-sorted JSON serialization of the report body, chart, claim-citations, structured response, changepoints, and cross-well clusters. Hash changes iff any of those fields changes.
- `data_snapshot`: list of referenced USGS site IDs plus per-site `{site_id, path, sha256, available}` records for each `data/usgs_<site_id>.csv`, plus a top-level `sha256` over the files block.
- `config_hashes`: SHA-256 over `config/usgs_sites.json` and `config/water_supply_sources.json`.
- `methodology`: flags recording `local_data_primary: True`, `trend_method = "monthly_OLS_with_screened_two_segment_changepoints"`, `cluster_method = "deterministic_standardized_kmeans"`, and an `external_covariates` block marked `included: False` with a note that external covariates are excluded until local-data trend, changepoint, clustering, and validation methods are stable.

The manuscript reproducibility argument rests on this block: given `response_sha256` plus `data_snapshot.sha256` plus `code_commit`, a reviewer can deterministically re-derive the deterministic portion of the answer and verify bit-identical output.

### 5.4 Streaming (`/api/research/stream`)

The streaming endpoint wraps the research path in an SSE generator. A thread-safe `queue.Queue` collects `{type: progress|result|error, ...}` frames produced by a callback inside the agent (or by the deterministic fallback's progress hooks). The HTTP handler writes each frame as `data: <json>\n\n`. The frontend reader in [frontend/src/api/client.js](frontend/src/api/client.js) uses a `ReadableStream` reader, decodes chunks with a `TextDecoder`, buffers partial events across chunk boundaries, dispatches `onProgress(message, progress, snapshot)` per frame, and resolves with the final `result` frame.

`test_streaming_agent_path_yields_chart_in_final_event` in [tests/unit/test_inline_chart.py](tests/unit/test_inline_chart.py) exercises the streaming path end-to-end with a stubbed `_research_agent`, splits the SSE body, and asserts the final `result` frame has `chart is not None` with non-empty `series` and `data`. This is the regression backstop for cross-path parity.

### 5.5 Citation integrity — `api/routes/_citation.py`

The citation scaffolding lives in [api/routes/_citation.py](api/routes/_citation.py) (224 lines). Trust levels are a ranked enum at [_citation.py:24](api/routes/_citation.py#L24): `unknown`/`untrusted` (0) → `moderate` (1) → `trusted` (2) → `verified` (3). The actual domain-to-trust assignment lives in `verify_source` at [src/agent/source_verification.py:244](src/agent/source_verification.py#L244) (664-line module): USGS, EPA, NOAA, NASA → verified; other `.gov` → trusted; peer-reviewed DOIs → trusted; universities (`.edu`) → moderate; Wikipedia and general reference → moderate; unknown → unknown. `source_verification.py` additionally tags each source with a category (`NUMERICAL_DATA`, `RESEARCH_PAPER`, `GOVERNMENT_REPORT`, `ACADEMIC`, `REFERENCE`, `NEWS`, `BLOG`, `UNKNOWN`) and a `priority_score` in `[0, 1]`. `_citation.py` consumes those trust levels via `_highest_trust_level` ([line 60](api/routes/_citation.py#L60)) and `_build_section_confidence_from_claims` ([line 69](api/routes/_citation.py#L69)).

`_build_claim_verdicts` ([_citation.py:166](api/routes/_citation.py#L166)) runs each claim through the `ClaimDisagreementEngine` in [src/claim_disagreement.py](src/claim_disagreement.py) when enabled. The engine is wired as a module-level singleton at [_citation.py:42-52](api/routes/_citation.py#L42-L52) and falls back gracefully if the import fails. The conservative fallback — cited → supported (risk 0.3); uncited → insufficient (risk 0.85) — ships by default. `_build_claim_verdict_summary` ([line 198](api/routes/_citation.py#L198)) aggregates these into `{total_claims, supported, contradicted, insufficient_evidence, high_risk_claim_ids, supported_rate, contradicted_rate, insufficient_rate}`.

`_build_section_confidence_from_claims` groups claims by report section and computes average confidence per section plus an overall confidence and trust level. `_build_citation_integrity` ([line 130](api/routes/_citation.py#L130)) produces the integrity record: claim coverage (`cited_claims / total_claims`), section coverage (`cited_sections / total_sections`), and a `passed` boolean true when both meet their configured thresholds (`MIN_CLAIM_CITATION_COVERAGE` and `MIN_SECTION_CITATION_COVERAGE` at [_citation.py:21-22](api/routes/_citation.py#L21-L22), default 0.90, env-overridable). Every response in the chat/research surface carries the integrity record.

---

## 6. Worked example: the Village of Estero question

The canonical manuscript-worthy question is:

> *"What are the groundwater sources the Village of Estero uses for water supply and what have been changes in groundwater levels there over the last 30 years?"*

This example exercises **both halves** of the data chain in a single request: the domain-knowledge half ("what does Estero draw from") and the monitored-record half ("what have the wells done since ~1994"). It is an illustrative code-path example: exact wells, aquifer labels, and risk summaries depend on the deterministic nearest-site selector and the current metadata/config files.

### 6.1 Routing

The query contains the token `Estero`. `_detect_location` word-boundary-matches `estero` against `_LOCATION_REFERENCE_POINTS`, which maps it to `(lat, lng, "Estero", county_hint="Lee")`. The routing chain falls through site-name and aquifer detection (no G-####, no aquifer keyword), fails multi-location (one place), and fires on single-location → `_best_sites_near(lat, lng, "Lee", max_sites=10)`. This returns the Lee County USGS wells closest to the Estero coordinates, scored by Haversine plus the `-0.3` county-match bonus. The selected cohort is therefore a reproducible proxy set for nearby monitoring wells, not a claim that those wells are the utility's production wells.

### 6.2 Deterministic analysis

`_site_research_fallback(question, sites, location_label="Estero", lat, lng)` is invoked on the cohort.

- Each site's monthly-mean water-level series is computed by resampling its CSV through `_load_site_timeseries`. Many wells start in the mid-1990s, giving the question its "last 30 years" frame.
- Per-site metrics are computed: `start_date`, `end_date`, `record_length_years`, `net_change_ft`, `annual_change_ft_yr` (from `_linear_trend_values_with_slope`), `trend` label (`rising / falling / stable`), and `changepoint` (from `_detect_changepoint` — usually populated only for wells with ≥36 monthly bins).
- `_cross_well_analysis` runs over the cohort and returns `trend_distribution`, `mean_annual_change_ft_yr`, `std_annual_change_ft_yr`, `divergent_pairs`, `risk_level`, `changepoints`, and `clusters`. The exact falling/stable/rising counts are output fields, not fixed assumptions.
- `_cluster_wells` groups the cohort by standardized annual change + seasonal amplitude + confinement. Cluster labels are deterministic descriptors of the selected wells, such as declining seasonal wells or muted-seasonality confined wells, and should be read as screening language rather than formal aquifer diagnoses.

### 6.3 KB contribution

The "what does Estero use for water supply" half is answered from the local knowledge base and water-supply config. Retrieval can surface supply-context sentences about the aquifer units represented in the configured source mapping, such as Lower Tamiami, Sandstone, Mid-Hawthorn, or related Lee County supply context when present. These sentences are added to `claim_citations` with `claim_type` tags like `"literature"` or `"metadata"` and cited to the corresponding KB/config source URLs with `trust_level` in `{trusted, moderate}`. The config file `config/water_supply_sources.json` (hashed into `research_provenance_v1.config_hashes`) holds the authoritative water-supply-source mapping used by the system.

### 6.4 Report assembly

`_site_research_fallback` composes the report as:

1. **Overview** — location, number of wells, period of record, cohort trend distribution, cohort mean annual change.
2. **Water supply context** — Lower Tamiami / Sandstone / Mid-Hawthorn sentences drawn from the config + KB, each with its own claim-citations.
3. **Cohort summary** — divergent pairs, candidate changepoints (up to 3), cross-well behaviour clusters, cohort risk level with explanation.
4. **Aquifer-grouped sections** — one section per aquifer present in the cohort, each listing its wells, annual rates, and net changes.
5. **Period-of-record statement** — the literal start and end dates across the cohort.

The chart payload is built by `_build_chart_payload` from the same site list and `cross_well` object: monthly-mean series per well, cohort `"avg"` series, trend overlay series for highlighted wells, five insight bullets leading with the highlighted-wells explanation, and a `cohort_risk_level`.

### 6.5 Claim/evidence binding

By the time the report is composed, `claim_citations` typically contains 6–12 claim objects per Estero question. Each carries:

- A `claim_id` such as `claim_003`.
- A `claim_type` such as `"trend"` (per-well annual rate sentences), `"metadata"` (cohort size / period-of-record), `"literature"` (KB-sourced water-supply sentences), `"interpretation"` (cohort risk sentence).
- A numeric `confidence` and a list of `citations`, each with `evidence_id`, `url`, `trust_level`, `verified`.

`_build_evidence_items` turns this into the registry the LLM synthesis step sees. If the LLM is enabled, it returns an `evidence_response_v1` JSON whose `answer` addresses both halves of the question and whose `claims` cite only registered IDs. If the LLM is disabled, the heuristic fallback renders the same structure from the registry.

### 6.6 Audit output

The final response for the Estero question carries:

- `report` — the markdown narrative.
- `chart` — the deterministic chart payload from `_build_chart_payload`.
- `claim_citations`, `claim_verdicts`, `claim_verdict_summary`.
- `citation_integrity` — coverage numbers and a `passed` flag.
- `structured_response` — the `evidence_response_v1` object with claims bound to registered IDs.
- `changepoints`, `cross_well_clusters` — raw deterministic outputs.
- `provenance` — `research_provenance_v1` with `code_commit`, `response_sha256`, `data_snapshot.sha256`, `config_hashes`, `methodology`.

A reviewer who wants to re-derive the Estero answer can check out `provenance.code_commit`, verify `data_snapshot.files[*].sha256` against the CSVs on disk, rerun the request, and confirm `response_sha256` matches bit-for-bit (for the deterministic layer; the LLM layer is stochastic across runs — see §10 Threats).

---

## 7. Auxiliary surfaces

### 7.1 Chat surface

`POST /api/chat` routes through the same manuscript-safe contract as the research surface. The six keyword-routed branches (site / aquifer / multi-location / single-location / network-wide / KB fallback) each delegate to `_site_research_fallback(..., allow_llm_synthesis=True)`, which runs the deterministic pipeline and then — unless `GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS` is set or an Ollama daemon is unavailable — can hand the structured findings to a local Ollama model (`llama3.2` by default) for a short hydrogeologist narration. If no keyword route matches and the user is on the `/api/chat` path, the code checks `_research_agent is not None`; in the demo configuration this is always `False`, so the question falls to the KB fallback. **In practice, benchmark questions are served by the deterministic pipeline with LLM synthesis disabled, while demo questions are deterministic-first with optional in-process Ollama narration. The `DeepResearchAgent` is never invoked in the sponsor demo.**

The quick-chat payload now exposes three layers of answer text: `answer_brief` for the natural-language answer users should read first, `raw_report` for the complete deterministic report, and `interpretation_details` for structured fields such as `aquifer_summaries`, `supply_interpretation`, risk level, limitations, and the deterministic brief. This is the API-level fix for the earlier failure mode where chat looked like it was dumping the full stored report rather than answering the user's question.

Chart-bound follow-up questions are handled by [api/routes/_chart_interpreter.py](api/routes/_chart_interpreter.py) (1607 lines). The frontend sends `chart_context` (site IDs, chart ID, chart title, and chart insights) plus the last four `turn_history` items. Turn history now includes lightweight context metadata (`site_ids`, wells, aquifer, mode, cohort risk) so underspecified follow-ups such as "why is it declining?" or "which well matters most?" can recover the recent data context even when the user does not repeat the location. The backend builds an `EvidencePack` directly from the chart's USGS site IDs, computes current cross-well metrics, builds an enriched RAG query from the question plus active wells, aquifers, county, trend direction, and risk level, then retrieves curated hydro concept snippets by default.

The interpreter now classifies each chart question through `_detect_question_intent` at [_chart_interpreter.py:998](api/routes/_chart_interpreter.py#L998), which uses regex matching against the question text to select one of five intents:

- **`shallow_deep_comparison`** — triggered by "shallow", "deep", "confined", "unconfined", "diverge", "aquifer wells". Handled by `_shallow_deep_answer` ([line 1016](api/routes/_chart_interpreter.py#L1016)), which calls `_group_metrics_by_confinement` to split `per_site_metrics` into confined and unconfined groups using `SITE_METADATA`, computes mean rate for each group, and builds a direct answer ("Yes, they diverge: the N shallow/unconfined wells average X ft/yr while the M confined wells average Y ft/yr"). Includes seasonal amplitude comparison when available and the largest well-level rate gap via `_largest_rate_gap`.
- **`fastest_changing`** — triggered by "fastest", "most", "which well", "steepest", "changing fastest". Handled by `_fastest_changing_answer` ([line 1066](api/routes/_chart_interpreter.py#L1066)), which sorts `per_site_metrics` by `annual_change_ft_yr` and leads with the named well and rate.
- **`cohort_meaning`** — triggered by "cohort", "average", "mean annual", "what does the average mean". Handled by `_cohort_meaning_answer` ([line 1100](api/routes/_chart_interpreter.py#L1100)), which explains the cohort average in terms of well count, mean rate, and how many wells are above/below.
- **`risk_explanation`** — triggered by "risk", "screening", "what does this mean", "concern". Handled by `_risk_explanation_answer` ([line 1196](api/routes/_chart_interpreter.py#L1196)), which explains the risk screening level in terms of percentage declining wells and connects to the strongest contributor.
- **`general`** — everything else. Handled by `_general_answer` ([line 1233](api/routes/_chart_interpreter.py#L1233)), which leads with the hydrogeologic meaning section.

`_build_meaning_brief` at [_chart_interpreter.py:725](api/routes/_chart_interpreter.py#L725) turns the same chart metrics into a stronger "what this means" block with a headline, plain-language meaning, why-it-matters sentence, how-to-read guidance, next evidence check, classroom takeaway, and confidence note. This is deterministic interpretation rather than LLM phrasing: the brief combines trend distribution, cohort risk, strongest negative rate, curated hydro context, and evidence-needed fields. The project now also has an explicit answer-quality rubric in [config/interpretation_rubric.json](config/interpretation_rubric.json). When a user interaction reveals a weak but technically correct answer, that gap can be converted into reusable required moves. For example, cohort-average answers must now state that the average is a group summary rather than a physical well, warn that it can hide divergent individual wells, explain why outliers matter, frame screening risk as prioritization rather than forecast, and tell the reader what to check next. `_build_intent_answer` at [_chart_interpreter.py:1241](api/routes/_chart_interpreter.py#L1241) dispatches to the appropriate builder and assembles a structured result with `question_intent`, `direct_answer`, `supporting_evidence`, `answer_relevant_observations`, `interpretation_rubric`, and intent-specific extras (`comparison_groups`, `largest_gap`, `fastest_decline`, `risk_summary`, `cohort_meaning`). `_deterministic_result_from_pack` at [line 1285](api/routes/_chart_interpreter.py#L1285) wraps this into the full `InterpretationResult`, composing the visible answer as: direct answer + up to two supporting evidence sentences + one caveat.

Optional vector KB retrieval can be enabled with `GROUNDWATERGPT_ENABLE_INTERPRETER_VECTOR_RAG=1`; it is not required for the sponsor path because cold embedding startup can be slow in offline environments. Curated snippets explain concepts such as drawdown, recharge, seasonality, aquifer confinement, supply-proxy limits, and saltwater risk; they are supporting language, not measurement evidence. Optional structured chart LLM synthesis is requested from the UI only when `VITE_ENABLE_LLM_INTERPRETATION=true`. When it succeeds, the response records `grounding_status.llm_provider` and `grounding_status.llm_model` (for example, `ollama` + `llama3.2`, or `qwen` + `qwen-plus`). The structured prompt is now explainer-oriented rather than a raw `EvidencePack` dump: it passes a deterministic explainer seed and explicit bans on metadata-style phrasing such as `This chart connects ...` or `Key deterministic rates are ...`. Numeric LLM claims are reconciled against deterministic `annual_change_ft_yr`, `net_change_ft`, and cohort-mean values before the response is emitted; unknown or mismatched numeric claims become guardrail flags. If the LLM returns a weak summary-echo, site-ID dump, or field-label dump, the interpreter falls back to the deterministic answer rather than emitting the bad synthesis. If vector retrieval or the LLM is unavailable, the deterministic chart interpreter still answers with the same `interpretation_response_v1` envelope and the curated local bank. The `/api/interpret` cache key includes a stable hash of `chart_context` plus `turn_history`, preventing stale answers from one chart being reused for another.

Every chat response carries `claim_citations`, `claim_verdicts`, `citation_integrity`, `structured_response`, and provenance regardless of which side served it. Chart-interpreter responses additionally carry `interpretation_response`, `direct_answer`, `supporting_evidence`, `answer_relevant_observations`, `interpretation_rubric`, `comparison_groups`, `largest_gap`, `numeric_claims`, `groundwater_concepts`, `meaning_brief`, `what_this_means`, `interpretive_findings`, `possible_drivers`, `evidence_needed`, `management_implications`, `confidence_notes`, `chart_context_used`, and `turn_history_used`. The visible chat answer remains short, but the optional Qwen/Ollama synthesis layer now rewrites the deterministic explainer seed into plain-language prose instead of paraphrasing the chart summary block. The deeper "Observed signal / hydrogeologic meaning / what this means / evidence needed / confidence" material remains in structured fields for the Analytical Depth panel and audit trail. The generic in-memory KB remains a final fallback for standalone concept questions; context-bearing follow-ups now route to the grounded interpreter before the KB can return a generic well definition. If Qwen or another structured LLM provider is enabled, its output is treated as optional synthesis over the same deterministic seed, numeric reconciliation rules, and explainer-quality guardrails; it does not replace the deterministic answer path.

### 7.2 Research workflow — plans, runs, drafts

[api/routes/research_workflow.py](api/routes/research_workflow.py) (255 lines) exposes an experiment-plan surface for turning a research session into a reproducible record: `POST /api/research/plans` ([line 119](api/routes/research_workflow.py#L119), create plans with `title`, `research_question`, `hypothesis`, `methodology`, `datasets`, `metrics`, `baselines`), `GET /api/research/plans` ([line 145](api/routes/research_workflow.py#L145)), `GET /api/research/plans/{plan_id}` ([line 160](api/routes/research_workflow.py#L160)), `POST /api/research/plans/{plan_id}/runs` ([line 177](api/routes/research_workflow.py#L177), log a run with `config`, `metrics`, `findings`, reproducibility fields: `seed`, `code_commit`, `environment`, `executor`, `dependency_lock`, artifact hashes), and `POST /api/research/plans/{plan_id}/draft` ([line 212](api/routes/research_workflow.py#L212), generate a target-venue-aware manuscript draft via the LLM). This is the hook that a peer-reviewed author would use to cite the system's output alongside a reproducible run record. It is live and served to the frontend.

### 7.3 Research workbench

[api/routes/_research_workbench.py](api/routes/_research_workbench.py) (581 lines) is a separate comparative-analysis builder library — not its own router — exposed via `POST /api/research/workbench` at [api/routes/research_workflow.py:243](api/routes/research_workflow.py#L243), which calls `build_research_workbench_payload`. It supports date-window presets (`last_5y`, `last_10y`, `full_record`, `custom`), aggregations (`monthly`, `quarterly`, `annual`), and normalizations (`raw`, `delta_from_first`, `z_score`). The workbench produces its own chart payloads and is consumed by [frontend/src/components/ResearchWorkbenchView.jsx](frontend/src/components/ResearchWorkbenchView.jsx). It is independent of the chat/research path and is live; it does not currently emit `claim_citations` or a `structured_response`, which is something the manuscript would need to either explain or extend.

### 7.4 Forecasting

No forecast pipeline is currently maintained in the serving repository. Future forecasting work should return as a separate feature with time-aware validation, explicit uncertainty, a served endpoint, and benchmark coverage before it is referenced in user-facing or manuscript-facing claims.

### 7.5 DuckDuckGo web search (default off)

[src/agent/research_agent.py](src/agent/research_agent.py) imports `ddgs` / `duckduckgo_search` at module load time and exposes a `WebSearch` tool to the agent. The tool is **off by default** in the serving configuration: `research_web_search_enabled = _env_flag("GROUNDWATERGPT_ENABLE_WEB_SEARCH", default=False)` at [api/routes/chat.py:363](api/routes/chat.py#L363), and `DeepResearchAgent` is constructed with `use_web_search=research_web_search_enabled`. It does not run in the deployed demo. The manuscript should not describe the system as a web-research agent.

---

## 8. Frontend surface

### 8.1 Stack

The frontend is a React 18.2 + Vite 5 SPA styled with Tailwind 3.3. Charts use `recharts` 2.10 for inline chart rendering and `@visactor/react-vchart` 2.0.22 in the research workbench. Maps use Leaflet 1.9.4 + `react-leaflet` 4.2.1. Markdown rendering is `react-markdown` 10.1.0. The Vite dev server runs on port 3000 and proxies `/api` to `http://localhost:8000`. E2E tests use Playwright.

### 8.2 Component graph

The top-level `App` mounts a sidebar-driven mode switcher with `Dashboard` (stats + map), `ChatView` (sponsor-facing grounded chat), `AnalysisView` (per-site / per-cohort panel), `ResearchSessionPanel` (session history), `ResearchWorkflowView` (plans, runs, drafts), and `ResearchWorkbenchView` (comparative workbench). When the active tab is chat, `Dashboard` now mounts `ChatView` as a full-height workspace instead of rendering it inside the generic dashboard card. `App` also removes page overflow for the chat tab, so the transcript is the single scroll owner. The previous Research toggle is hidden from the sponsor chat surface because live deep research remains backend-only future work until its timeout and citation-coverage issues are resolved.

`ChatView.jsx` is the primary surface. It subscribes to a `backendStatus` observable exported from [frontend/src/api/client.js](frontend/src/api/client.js), renders a "Backend unreachable — check uvicorn on :8000" banner when the observable is `'down'`, and auto-dismisses it on the next successful fetch. The chat message list renders an inline `<AgentChart>` whenever `msg.chart` is present (true whenever the cohort could be resolved, by the cross-path parity invariant). A visualization request whose cohort could not be resolved shows a "No time series available for this query" note, but chart-interpreter follow-ups suppress that note because they are explaining an existing chart rather than requesting a new one. The report body is rendered as markdown; claim-and-evidence references in square brackets render inline.

For sponsor-facing chart explainability, assistant messages can render a learner-first **Learner Brief** followed by a collapsed **See the evidence behind this explanation** panel. The learner block is built from deterministic fields and exposes `learner_brief`, optional `terms_to_know`, and optional `misconceptions_to_avoid` before any audit-depth material. The evidence panel then shows deterministic numeric claims, aquifer comparisons, supply proxy mapping, selected groundwater concepts, “What this means,” “Possible explanations,” “What would confirm it,” confidence notes, key observations, limits/guardrails, and grounding status (`uses_chart_context`, `uses_usgs_data`, `invented_measurements_allowed`). When the interpreter returns `comparison_groups`, the panel adds a shallow-vs-deep row with the unconfined/confined group means, seasonal amplitude when available, and the largest well-level rate gap. Key observations prefer `answer_relevant_observations`, so the panel follows the question intent instead of repeating generic chart boilerplate. Contextual "Ask Next" chips are now grouped by learner purpose (`Understand this`, `Compare wells`, `Check the caveat`, `What would strengthen this interpretation?`). Clicking a chip sends either the active `chart_context` or the enriched recent turn history back to the backend, which fixes the earlier poor follow-up behaviour where a chart question lost its data context. The frontend also emits lightweight learner telemetry (`learner_brief_shown`, `analytical_depth_expanded`, `terms_to_know_expanded`, `ask_next_clicked`, `learner_feedback`) to a local JSONL store under `outputs/research/learner_events/`; this is product evidence for usability, not scientific evidence about groundwater.

`AgentChart` and `ResearchChartsPanel` are lazy-loaded via `React.lazy` + `Suspense` with `<div className="h-[320px]" />` fallbacks — a deliberate bundle-size optimization because Recharts is the largest single dependency.

### 8.3 `AgentChart` — chart UX choices

[frontend/src/components/AgentChart.jsx](frontend/src/components/AgentChart.jsx) (267 lines) has decisions worth naming in the paper:

- Risk pill next to the title, **hidden** when `cohort_risk_level` is falsy or `'unknown'` — the system never shows a risk claim it cannot back.
- CSV download button labelled **Monthly CSV** with tooltip `"Monthly-mean aggregation of all plotted wells"` and file name `<slugified-title>-monthly.csv`. The CSV is built from the same monthly-mean series the chart renders, so the download and the visual are the same object.
- **Conditional legend payload** when `series.length > 6`: the legend filters to highlighted wells + trend overlays + cohort average, while the underlying `<Line>` elements still render non-highlighted wells as dim background context. This is how a 10-well cohort stays readable without wrapping the legend.
- Y-axis is **reversed** (`reversed` prop on `<YAxis>`), because `value` is depth-to-water — bigger means deeper. Y-domain is computed from data with a 5% padding.
- `Brush` is added only when `data.length > 60`, giving multi-year cohorts a zoom handle.
- Insight bullets render in a slate card below the chart, capped at five, leading with the highlighted-wells explanation.

### 8.4 API client and backend-status observable

[frontend/src/api/client.js](frontend/src/api/client.js) is the single entry point for all backend calls. Every fetch goes through `apiFetch(url, options, fallbackMessage)`, which wraps `fetch()` in a `try/catch` and converts any `TypeError` (`Failed to fetch`) into an `ApiError({kind: 'network'})` while emitting `'down'` on the `backendStatus` observable. On success it emits `'up'`. HTTP errors become `ApiError({kind: 'http', status})`, parse errors `ApiError({kind: 'parse'})`. `sendResearchQueryStreaming` reads the SSE body incrementally, splits on `\n\n`, handles partial frames, forwards `progress` events, stores `result` frames, raises on `error` frames, and resolves with the stored result on stream close.

The observable is ~15 lines — a `Set` of listeners plus `subscribe` / `getStatus`. Deliberately not a full store (no Redux/Zustand) because the only cross-cutting state it carries is up/down status.

---

## 9. Evaluation and measured behaviour

### 9.1 Test coverage

**219 unit tests passing** on Python 3.13 locally as of 2026-04-16. All tests run with `GROUNDWATERGPT_SKIP_AGENT_INIT=1`, so they exercise the deterministic pipeline, chart interpreter, detection chain, citation machinery, and provenance — **not** the live `DeepResearchAgent` path. Agent-related tests use mock LLMs and verify synthesis machinery, not operational quality (see §4.1). Key test files:

- `test_inline_chart.py` (13+ tests): chart payload invariants, cross-path parity, agent-hook attach/leave-alone, streaming SSE final frame, ft/yr unit naming, changepoint + cluster presence, empty-input handling, KeyError surfacing when cross-well metrics are malformed.
- `test_detection.py`: detection chain (regex coverage, precedence, edge cases).
- `test_chat_api.py`: `/api/chat` + `/api/research` + `/api/research/stream` tests against FastAPI TestClient, including `provenance`, `changepoints`, `cross_well_clusters`, `structured_response` presence and `schema_version` assertions.
- `test_chart_interpreter.py` (395 lines): direct tests for missing chart context, deterministic fallback, unavailable LLM providers, successful structured-LLM chart narration, numeric-claim reconciliation against the deterministic EvidencePack, intent-detection classification (`shallow_deep_comparison`, `fastest_changing`, `cohort_meaning`, `risk_explanation`, `general`), shallow/deep answer structure with comparison groups and largest gap, fastest-changing answer naming and rate, cohort-meaning answer with below/above counts, risk-explanation answer with percentage and strongest contributor, and single-group-only shallow/deep fallback.
- `test_chat_followup_routing.py` (344 lines): chart-context follow-up routing, no-context fallback behaviour, turn-history trimming, cache-key separation by chart context, a regression guard using the shared chat benchmark case file, and intent-specific routing for shallow/deep and fastest-changing follow-ups.
- `test_chart_api.py`: `/api/sites/{id}/chart` and `/api/compare/chart` tests.
- `test_knowledge_api.py`: KB stat / status / ingest.
- `test_agent.py`: research-agent tests with stubbed LLM, including `TestStructuredResearchSynthesis` which asserts `_heuristic_structured_response` + `_render_structured_report` preserve claim-and-evidence IDs end-to-end.
- `test_tools.py`, `test_claim_disagreement.py`, `test_research_workflow_api.py`, `test_research_workbench.py`.

The benchmark suite [tests/benchmark/chat_eval_cases.json](tests/benchmark/chat_eval_cases.json) contains **68 cases** spanning three difficulty levels (L1, L2, L3) across routing modes (`fallback`, `site_fallback`, `aquifer_fallback`, `network_fallback`). Each case lists up to 20 `required_checks` (`has_report`, `has_sources`, `has_claim_citations`, `reports_net_change_ft`, `reports_annual_rate`, `has_aquifer_sections`, `has_cross_aquifer_comparison`, `states_data_period`, `response_has_citation_integrity`, …) and typed assertions (`expected_mode`, `min_wells`, `min_report_length`, …). The harness is [scripts/run_chat_benchmark.py](scripts/run_chat_benchmark.py).

### 9.2 Current benchmark (deterministic column)

Current [chat_benchmark_report.json](chat_benchmark_report.json), generated with `scripts/run_chat_benchmark.py --mode fallback --enforce-thresholds` (hybrid narration disabled via `GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS=1`, agent disabled via `GROUNDWATERGPT_SKIP_AGENT_INIT=1`). **This benchmark exercises only the deterministic pipeline — no LLM of any kind is active during the run:**

- **68 / 68 cases passing**, `overall_score = 1.000`.
- Average citation coverage: **1.000** (threshold: 0.90).
- Average claim-citation coverage: **1.000** (threshold: 0.90).
- Average section-citation coverage: **1.000** (threshold: 0.90).
- Average claim-verdict coverage: **1.000** (threshold: 0.95).
- Average contradicted-claim rate: ≈ 0.010 (threshold: ≤0.40).
- Average high-risk-claim rate: ≈ 0.010 (threshold: ≤0.50).
- Median elapsed time: **1.554 s**.
- Maximum elapsed time: **3.247 s**.
- Latency measurement context: FastAPI in-process `TestClient`; deployed client-server latency will be higher and should be measured separately.
- Thresholds: `min_overall_score=0.85`, `min_case_score=0.80`, `min_avg_citation_coverage=0.90`, `max_response_seconds=120`, `max_median_seconds=5.0`.
- Routing modes exercised: `fallback`, `site_fallback`, `aquifer_fallback`, `network_fallback`. With `force_fallback_mode` set, the LLM synthesis layer is skipped by design so the reproducibility argument rests only on the deterministic layer.

The key implication for the manuscript: the headline ("68/68 benchmark pass, 100% citation coverage, 100% claim-verdict coverage, 1.554 s median latency") is a statement about **the deterministic layer**. That is the layer the reproducibility argument rests on. The framing must be explicit.

### 9.3 Current live-agent smoke benchmark

The repository now includes [scripts/run_agent_benchmark.py](scripts/run_agent_benchmark.py), which routes the same benchmark case format through `DeepResearchAgent` using the live-agent threshold file. A bounded local smoke run was cached in [agent_benchmark_report.json](agent_benchmark_report.json) using Ollama `llama3.2` and `--limit 1`.

- Cases: **1 / 68** shared benchmark cases, routed through `deep_research`.
- Agent-routed rate: **1.000**.
- Structured-response coverage: **1.000**.
- Provenance coverage: **1.000**.
- Citation coverage and claim-verdict coverage: **0.000** in the latest smoke.
- Overall score: **0.200**.
- Median / max latency: **270.155 s**.
- Threshold pass: **false** (`overall_score < 0.850`, citation/verdict coverage below threshold, max latency above 8 s).

This smoke result is useful as an architectural check: the live `DeepResearchAgent` path can still route and emit the typed audit envelope, but it is not yet a manuscript-quality LLM-performance claim. The stronger near-term LLM story is the bounded chart-explainability path, where local Ollama narration is constrained to deterministic chart context rather than asked to run the full research agent.

### 9.4 Current chart-explainability and interpretation benchmark

The chart-follow-up interpreter now has both unit-level regression tests and a dedicated interpretation benchmark. The unit tests (482 lines in [tests/unit/test_chart_interpreter.py](tests/unit/test_chart_interpreter.py)) assert that a chart-context question such as "Which one is changing fastest?" can answer from the deterministic EvidencePack without an LLM, that enriched RAG queries include the active wells/aquifers for vague follow-ups, that curated hydro context survives Chroma/vector retrieval failure, that contextual questions include interpretation sections rather than data-only restatement, that "what does this mean?" returns a `meaning_brief` with significance and next-evidence guidance, that cohort-average answers explain the average as a group summary rather than a physical well, that a structured LLM answer is threaded through when available, that successful structured LLM synthesis reports provider/model metadata, that bad LLM numeric claims are corrected before emission, and that intent detection correctly classifies shallow/deep, fastest-changing, cohort-meaning, risk-explanation, and general questions with structurally correct answers for each. The chat routing tests (344 lines in [tests/unit/test_chat_followup_routing.py](tests/unit/test_chat_followup_routing.py)) assert that open-ended chart follow-ups enter `mode = "chart_interpreter"`, that "well decline" does not fall into the generic well-definition KB when recent wells exist, that `/api/interpret` cache entries are separated by chart context, and that intent-specific follow-ups produce the right answer shape.

The interpretation benchmark harness lives at [scripts/run_interpretation_benchmark.py](scripts/run_interpretation_benchmark.py) and now includes explicit learner-usefulness checks in addition to grounding checks. The case file [tests/benchmark/interpretation_eval_cases.json](tests/benchmark/interpretation_eval_cases.json) now includes learner prompts such as “I’m new to this, what does this chart mean?”, “Why should I care about this decline?”, “What does screening risk mean in plain English?”, “What does the cohort average mean for a beginner?”, and “What’s the difference between a falling well and proving a cause?”. Each case is scored not only on schema presence, grounding status, data references, expected terms, numeric match, guardrails, and turn-context binding, but also on whether the visible response exposes a learner brief, plain-language meaning, an explicit limit, a next-step question, jargon explanations when required, and misconception guards when the intent is prone to chart-reading errors.

- Overall score: **0.943**, threshold pass **true**.
- Grounding coverage: **1.000** (threshold: 0.97).
- Chart context coverage: **1.000** (threshold: 0.85).
- Data reference coverage: **1.000** (threshold: 0.85).
- Numeric match rate: **1.000** (threshold: 0.95).
- Guardrail pass rate: **1.000** (threshold: 1.00).
- Fake measurement policy fail rate: **0.000** (threshold: ≤0.00).
- Suggested-question coverage: **1.000** (threshold: 0.85).
- Median elapsed: **1.066 s**; max elapsed: **2.517 s**.

### 9.5 Current chart-explainability LLM smoke benchmark

The repository also includes [scripts/run_chart_explainability_benchmark.py](scripts/run_chart_explainability_benchmark.py), which keeps deterministic routing enabled, asks the local model to explain the chart context, and checks that chart explainability, LLM synthesis, citations, claim verdicts, and guardrails are present.

- Cases: **1** chart-explainability smoke case.
- LLM synthesis coverage: **1.000**.
- Chart explainability coverage: **1.000**.
- Average elapsed: **44.816 s**.
- Threshold pass: **true**.

This is the sponsor-facing LLM result: the model communicates with the deterministic data product and helps explain the chart, while the measured groundwater values remain owned by the USGS-backed pipeline.

### 9.6 Benchmarks the paper should add

[scripts/run_retrieval_precision.py](scripts/run_retrieval_precision.py) runs a KB retrieval precision benchmark with a configurable top-k and a minimum average precision threshold (default 0.90). Its cases live in a companion JSON file. This is the right starting point for a Methods-section claim about KB retrieval quality; the paper should report precision@1, precision@5, and MRR across those cases.

---

## 10. Strengths, limitations, threats to validity

### 10.1 Strengths

- **Deterministic reference pipeline.** A single function (`_site_research_fallback` + `_cross_well_analysis` + `_build_chart_payload`) converts USGS CSVs into cited, chart-backed conclusions — trend, changepoint, cluster, divergent pairs, risk level — without any language model. It is what the benchmark measures and what the provenance block hashes.
- **Typed claim-and-evidence binding.** The synthesis layer returns JSON whose every factual claim cites `claim_ids` and `evidence_ids` from a registry built by the deterministic layer. The parser sanitizes by intersecting against valid ID sets; unbacked claims are dropped. This is tested with mock LLMs; the design is verified but not yet evaluated against real LLM output at scale. The response always carries the resulting `structured_response` (`evidence_response_v1`) for downstream auditing.
- **Cross-path chart parity (architectural).** All routing branches — deterministic, LLM agent, streaming agent — are wired to emit charts through one builder, joined by `_agent_chart_hook.attach_chart_from_agent_result`. A regression test with a stubbed agent result asserts the chart shape is correct. However, the agent path is dormant in the demo, so cross-path parity is an architectural guarantee tested in isolation, not an operational property of the running system.
- **Cryptographic provenance.** Every research response carries `research_provenance_v1` with `code_commit`, `response_sha256`, per-CSV `data_snapshot` hashes, `config_hashes`, and methodology flags. A reviewer can deterministically re-derive the deterministic portion of any answer.
- **Citation integrity as a first-class signal.** Coverage and trust are computed per request and surfaced through the API rather than logged post-hoc.
- **LLM decoupled from correctness.** Both the 68-case chat benchmark and the 25-case interpretation benchmark pass their thresholds without any LLM active. The 68-case deterministic chat benchmark scores 1.000; the 25-case interpretation benchmark scores 0.943 with 1.000 grounding, numeric-match, and guardrail coverage. The evaluated system is deterministic.
- **Intent-aware chart interpretation.** The chart-follow-up interpreter classifies questions into five intents and builds structurally correct answers directly from deterministic metrics, without an LLM. This is the evaluated and benchmarked interpretation path.
- **LLM provider portability (untested at scale).** Five providers through [src/agent/llm_factory.py](src/agent/llm_factory.py) by env var; tested only as enum membership and one-case smokes.
- **Deterministic routing is testable.** Keyword-driven and regex-based, so the test suite enumerates routing decisions.

### 10.2 Limitations (stated plainly)

- **Trend methodology is OLS on monthly means.** `_linear_trend_values_with_slope` has no seasonality removal, no serial-correlation correction, and no uncertainty reporting. Reported annual rates are point estimates, not confidence intervals. Mann-Kendall + Sen's slope is the genre standard and should replace or augment this.
- **Changepoints and clusters are screening tools.** The two-segment OLS residual-improvement screen and the standardized-feature k-means grouping are reproducible, but they are **not** formal regime-shift tests or connectivity inferences. The report wording is conservative; the paper should be too.
- **Risk classification thresholds are engineering defaults.** `high` ≥ 66%, `moderate` ≥ 33% (or ≥ 20% mostly-confined), else `low`. No empirical calibration in the repo.
- **Divergent pairs are a screening heuristic.** Two wells can diverge for reasons unrelated to the aquifer system.
- **Research agent is dormant.** The `DeepResearchAgent` is architecturally complete but disabled in the demo (`GROUNDWATERGPT_SKIP_AGENT_INIT=1`), all tests, and both benchmarks. A one-case manual smoke scored 0.200 and failed thresholds. The manuscript should not describe the agent as part of the evaluated system.
- **LLM layer is under-evaluated.** No stable full-suite benchmark exists for any LLM path — the in-process Ollama narration, the agent research path, or the chart-explainability LLM path. All three have only one-case smokes.
- **Reproducibility of the LLM path.** The LLM is stochastic; running the same query twice produces subtly different phrasing. Structured-response sanitization guarantees no *new* unbacked claims but cannot guarantee identical wording. The deterministic portion **is** reproducible and hash-verifiable.
- **Scope is fixed and narrow.** 44 wells, 5 counties, 7 aquifer labels. Adding wells requires a metadata edit.
- **Keyword routing is brittle at the edges.** Novel phrasings may miss a specialized branch. In the demo configuration (agent disabled), such queries fall to the KB fallback — they get a generic answer, not an agent-synthesized one. The intent classifier for chart follow-ups uses regex, which handles tested phrasings but may misclassify novel wording.
- **Date-window handling is uneven across surfaces.** Explicit `start_date` / `end_date` filtering and preset windows (`last_5y`, `last_10y`, `full_record`, `custom`) exist in the chart/data endpoints and the research workbench, but natural-language chat and the chart-follow-up interpreter do not yet reliably turn a prompt like "from 2010 to 2020" into those structured filters. For manuscript claims, timeframe-aware analysis should therefore be described as available in the workbench/API layer, not as a uniformly solved chat capability.
- **Knowledge base coverage is small.** Three hydrogeology PDFs + per-well summaries + hand-written Q&A. A document-level inventory is needed.
- **Forecasting is out of manuscript scope.** Historical forecast code is not wired to the serving API and should not be used for manuscript claims until it has time-aware validation and a served endpoint.
- **Concurrency and persistence.** Benchmark runs sequentially; session store is file-based; no concurrency measurement.

### 10.3 Threats to validity

- **Construct validity.** "Groundwater level" in the USGS schema is depth-to-water, conventionally negative-elevation. Other papers report water level in the elevation sense. The UI reverses the Y-axis to mitigate confusion, but the manuscript must state the sign convention.
- **External validity.** The validated network is Florida-specific across related aquifers. Claims about generalization should be limited to "the system can be configured against a similar-shape dataset".
- **Internal validity of the risk label.** The heuristic is hand-tuned and the benchmark only tests for risk-language presence, not calibration. A small validation against a hydrogeologist's labelling of the same cohorts would strengthen any claim tied to `cohort_risk_level`.

### 10.4 What the paper can confidently claim

- A deterministic hydrogeologic reference pipeline that converts USGS monitoring records into cited, chart-backed answers with cryptographic provenance. This is the evaluated system.
- A typed-binding design for LLM synthesis — every factual sentence in the final report is tied to a registered `claim_id` and `evidence_id`, and unbacked claims are sanitized out by construction. The design is unit-tested with mock LLMs; it has not been evaluated at scale against real model output.
- A single chart builder used across all routing paths, ensuring chart schemas are consistent by construction. The agent path is dormant, so this is an architectural property verified by a stubbed test, not an operational property of the running demo.
- An evaluation harness showing 68/68 cases passing, 100% average citation coverage, 100% claim-verdict coverage, and 1.554 s median latency — all on the deterministic layer with no LLM active.
- An intent-aware chart interpretation pipeline with a dedicated 25-case benchmark showing overall score 0.943, 100% grounding coverage, 100% numeric match rate, 100% guardrail compliance, and 1.066 s median latency — all deterministic, no LLM active.
- A reproducibility artefact (`research_provenance_v1`) that lets a reviewer deterministically re-derive the deterministic portion of any answer.

### 10.5 What the paper should not claim without additional work

- Generalization beyond the monitored network.
- LLM synthesis quality — the one-case smokes (agent, narration, chart-explainability) are architectural checks, not quality evaluations. No multi-case LLM benchmark exists.
- That the `DeepResearchAgent` is an active, evaluated component — it is dormant in demo, tests, and benchmarks.
- Calibrated risk classification.
- Confidence-interval-quality trend estimates.
- Production readiness.
- A validated forecasting capability — forecast code remains out of scope until it has serving-path integration and manuscript-ready evaluation.

---

## 11. Cleanup status and remaining work

The first cleanup pass removed code and documents that were not reachable from the serving paths described in this overview. The repository surface now more closely matches the manuscript system: FastAPI + React for the live application, the deterministic analysis layer under [api/routes/](api/routes/), and citation/provenance helpers under [api/routes/_citation.py](api/routes/_citation.py) and [api/routes/_provenance.py](api/routes/_provenance.py). The `DeepResearchAgent` under [src/agent/](src/agent/) remains in the repository as architecturally complete but dormant code — it is disabled in the demo, tests, and both benchmarks.

### 11.1 Removed in the cleanup pass

- Superseded Task 2 agent modules: `src/agent/priority_search_engine.py` and `src/agent/groundwater_research_model.py`.
- Private tests for those modules: `tests/agent/test_priority_search_engine.py` and `tests/agent/test_groundwater_research_model.py`.
- Superseded Task 2 planning/developer artifacts: `TASK_2_OVERVIEW.md`, `TASK_2_IMPLEMENTATION.md`, `TASK_2_COMPLETION_SUMMARY.md`, `DEVELOPER_GUIDE_AGENTIC_RESEARCH.md`, and `commit_task2.sh`.
- Legacy Streamlit UI files under `src/ui/` plus the root-level `main.py` CLI entry point.
- The unused `streamlit` Python dependency from [config/requirements.txt](config/requirements.txt).
- The deleted agent exports were removed from [src/agent/__init__.py](src/agent/__init__.py), so importing `src.agent` no longer references removed modules.

### 11.2 Retired: overlapping chat agent

- The previous `GroundwaterAgent` quick-chat path has been removed from the live system. `/api/chat` now uses deterministic routing first and falls to the KB fallback when no keyword route matches (the `DeepResearchAgent` code path exists but is disabled by `GROUNDWATERGPT_SKIP_AGENT_INIT=1` in demo and tests).
- The agent unit tests cover `DeepResearchAgent` construction and structured synthesis behavior with mock LLMs. They verify the evidence-binding machinery, not operational quality.

### 11.3 Gate or delete: DuckDuckGo web search

**[src/agent/research_agent.py](src/agent/research_agent.py) web-search path.** The optional `ddgs` / `duckduckgo_search` backend is imported only when a `DeepResearchAgent` is constructed with `use_web_search=True`; the serving configuration keeps that off by default ([api/routes/chat.py:363](api/routes/chat.py#L363)). Keep manuscript and demo claims focused on the local-data/local-knowledge configuration unless web search is explicitly enabled and evaluated.

### 11.4 Removed: standalone forecast experiment

- Forecasting is now explicitly out of manuscript scope. Unsupported forecast code, model-quality CI scaffolding, trained model artifacts, and generated forecast outputs were removed from the repository surface used for submission.
- Any future forecasting work should return only after it has a serving endpoint, rolling-origin validation, uncertainty handling, and manuscript-ready evaluation.

### 11.5 Clean up: timestamped refresh CSVs

- **[data/](data/)** contains snapshot files named `usgs_<id>_<YYYYMMDD>.csv` alongside the canonical `usgs_<id>.csv`. `_load_site_timeseries` only reads the canonical file, so the snapshots are inactive inputs — some are even literal 2-row duplicates. **Action:** delete the timestamped snapshots (or move them under `data/snapshots/` and `.gitignore` that path). The data directory should reflect exactly what the serving code loads, and the reproducibility appendix should be able to hash the directory listing without stale content.

### 11.6 Refactor: oversized modules

These are not dead, but they are large enough that they hide the architecture the manuscript is trying to describe. Splitting them would make the paper's file references more precise.

- **[api/routes/chat.py](api/routes/chat.py) (2793 lines).** Suggest splitting into: `chat_routes.py` (the FastAPI route handlers), `routing_chain.py` (the site/aquifer/multi/location/network detection wiring), `fallback_wiring.py` (how each routing branch calls `_site_research_fallback` and assembles the payload), `agent_wiring.py` (how the LLM branches call `DeepResearchAgent` and `_agent_chart_hook`), `interpretation_routes.py` (the `/api/interpret` cache and chart-context bridge), and `sse_streaming.py` (the streaming generator + thread-queue bridge).
- **[api/routes/_site_analysis.py](api/routes/_site_analysis.py) (1970 lines).** Suggest splitting into `_trend.py` (OLS slope, helpers), `_changepoint.py` (`_detect_changepoint`), `_cluster.py` (`_cluster_wells`), `_cross_well.py` (`_cross_well_analysis` orchestrator), `_supply.py` (water-supply proxy mapping and answer brief), `_chart.py` (`_build_chart_payload`, `_build_chart_insights`), and a thin `_site_analysis.py` that re-exports for existing imports.
- **[src/agent/research_agent.py](src/agent/research_agent.py) (~1980 lines).** Suggest splitting the synthesis layer (`_build_evidence_items`, `_parse_structured_response`, `_heuristic_structured_response`, `_render_structured_report`) into a dedicated `src/agent/structured_synthesis.py` so the claim/evidence binding that the paper's argument depends on lives in one small, testable file.

### 11.7 Remaining cleanup impact

After this pass, the largest remaining items are methodological rather than architectural: stronger hydrologic trend statistics than monthly OLS, evidence binding for the research workbench, and a final decision about whether the dormant DuckDuckGo code path belongs in the submission repository at all. The next meaningful improvements would come from broader data coverage and actual evaluation, not more UI- or prompt-level layering: more wells / covariates would allow better calibration of risk labels and causal caveats, and a real multi-case LLM benchmark would be required before claiming that the optional LLM layer materially improves interpretation quality.

---

## Appendix A — File map for citation in the manuscript

| Component | Path | Size |
|---|---|---|
| Detection chain (regex, location map, site loader, cohort helpers) | [api/routes/_detection.py](api/routes/_detection.py) | 639 lines |
| Deterministic analysis (site fallback, supply interpretation, answer brief, cross-well, changepoint, cluster, chart builder, insights, trend) | [api/routes/_site_analysis.py](api/routes/_site_analysis.py) | 1970 lines |
| Chart-context interpreter (intent detection, meaning brief, shallow/deep, fastest-changing, cohort, risk builders) | [api/routes/_chart_interpreter.py](api/routes/_chart_interpreter.py) | 1607 lines |
| Agent-to-chart join point | [api/routes/_agent_chart_hook.py](api/routes/_agent_chart_hook.py) | 142 lines |
| Citation integrity, verdicts, trust levels | [api/routes/_citation.py](api/routes/_citation.py) | 224 lines |
| Research provenance block | [api/routes/_provenance.py](api/routes/_provenance.py) | 143 lines |
| Chat / research endpoints, `/api/interpret`, routing chain, SSE streaming | [api/routes/chat.py](api/routes/chat.py) | 2793 lines |
| Knowledge base router | [api/routes/knowledge.py](api/routes/knowledge.py) | 88 lines |
| Data router | [api/routes/data.py](api/routes/data.py) | 239 lines |
| Research workflow (plans, runs, drafts, workbench mount) | [api/routes/research_workflow.py](api/routes/research_workflow.py) | 255 lines |
| Research workbench (comparative panel) | [api/routes/_research_workbench.py](api/routes/_research_workbench.py) | 581 lines |
| Site metadata loader | [api/site_metadata.py](api/site_metadata.py) | — |
| FastAPI app factory | [api/main.py](api/main.py) | 54 lines |
| Wells listing router | [api/routes/wells.py](api/routes/wells.py) | 176 lines |
| Deep research agent — **dormant in demo/eval** (phases, budget, evidence registry, structured synthesis) | [src/agent/research_agent.py](src/agent/research_agent.py) | 1980 lines |
| Agent tool surface — **dormant** | [src/agent/tools.py](src/agent/tools.py) | 1083 lines |
| Research optimizer — **dormant** (planner, ranker, reflector, persistence) | [src/agent/research_optimizer.py](src/agent/research_optimizer.py) | 854 lines |
| Knowledge base loader | [src/agent/knowledge.py](src/agent/knowledge.py) | 760 lines |
| Source verification (trust levels, category, priority) | [src/agent/source_verification.py](src/agent/source_verification.py) | 658 lines |
| LLM provider factory | [src/agent/llm_factory.py](src/agent/llm_factory.py) | 180 lines |
| **Retired:** quick-chat agent path | — | — |
| **Removed:** standalone forecast experiment (§11.4) | — | — |
| Frontend chat surface | [frontend/src/components/ChatView.jsx](frontend/src/components/ChatView.jsx) | 1364 lines |
| Frontend chart component | [frontend/src/components/AgentChart.jsx](frontend/src/components/AgentChart.jsx) | 267 lines |
| API client with observable | [frontend/src/api/client.js](frontend/src/api/client.js) | 373 lines |
| Inline chart regression tests | [tests/unit/test_inline_chart.py](tests/unit/test_inline_chart.py) | 383 lines |
| Chart interpreter tests (intent detection, meaning brief, answer builders, numeric reconciliation, LLM metadata) | [tests/unit/test_chart_interpreter.py](tests/unit/test_chart_interpreter.py) | 482 lines |
| Chart follow-up routing tests (intent routing, context binding) | [tests/unit/test_chat_followup_routing.py](tests/unit/test_chat_followup_routing.py) | 344 lines |
| Interpretation benchmark runner (25 eval cases, 20 checks/case) | [scripts/run_interpretation_benchmark.py](scripts/run_interpretation_benchmark.py) | 484 lines |
| Interpretation eval cases | [tests/benchmark/interpretation_eval_cases.json](tests/benchmark/interpretation_eval_cases.json) | 25 cases |
| Research agent structured-synthesis tests | [tests/unit/test_agent.py](tests/unit/test_agent.py) | — |
| Chat / research API tests (provenance, structured response) | [tests/unit/test_chat_api.py](tests/unit/test_chat_api.py) | — |
| Benchmark cases | [tests/benchmark/chat_eval_cases.json](tests/benchmark/chat_eval_cases.json) | 68 cases |
| Benchmark runner | [scripts/run_chat_benchmark.py](scripts/run_chat_benchmark.py) | — |
| Retrieval precision runner | [scripts/run_retrieval_precision.py](scripts/run_retrieval_precision.py) | — |
| Demo startup script | [scripts/start_demo.sh](scripts/start_demo.sh) | 103 lines |
| Makefile targets (demo, benchmark, test, build) | [Makefile](Makefile) | 11 lines |

## Appendix B — Numeric facts worth citing verbatim

- Monitoring network: **44 wells** (verified from `len(SITE_METADATA)` at import time).
- County distribution: Miami-Dade 15, Lee 11, Collier 6, Hendry 4, Sarasota 4, generic "Florida" 4.
- Aquifer distribution: Biscayne 15, Surficial 7, Floridan 6, Tamiami 5, Florida 4, Intermediate 4, Hawthorn 3.
- USGS data date range across sampled CSVs: **1994-01-01 through 2026-04-05**; 40 canonical CSV files under [data/](data/), daily cadence.
- Knowledge base: ChromaDB persistent store, `BAAI/bge-small-en-v1.5` embeddings (384-dim), `chroma.sqlite3` ≈ 156 MB.
- Benchmark (deterministic layer): **68 / 68 passing**, overall score **1.000**, average citation coverage **1.000**, average claim-citation coverage **1.000**, average section-citation coverage **1.000**, average claim-verdict coverage **1.000**, average contradicted-claim rate **0.010**, average high-risk-claim rate **0.010**, median latency **1.554 s**, max latency **3.247 s**. Routing modes exercised: `fallback`, `site_fallback`, `aquifer_fallback`, `network_fallback`.
- Benchmark (interpretation / chart-explainability): **25 eval cases**, all evaluated in the latest deterministic run, overall score **0.943**, grounding coverage **1.000**, chart context coverage **1.000**, data reference coverage **1.000**, suggested-question coverage **1.000**, numeric match rate **1.000**, guardrail pass rate **1.000**, fake measurement policy fail rate **0.000**, median latency **1.066 s**, max latency **2.517 s**, threshold pass **true**. Levels: core, source, aquifer, followup, chart-meta, numeric, guardrail, hydro-context.
- Benchmark (bounded live-agent smoke): **1 / 68 cases**, Ollama `llama3.2`, mode `deep_research`, overall score **0.200**, agent-routed rate **1.000**, structured-response coverage **1.000**, provenance coverage **1.000**, citation coverage **0.000**, claim-verdict coverage **0.000**, median/max latency **270.155 s**, threshold pass **false**.
- Benchmark (chart-explainability LLM smoke): **1 case**, Ollama `llama3.2`, LLM synthesis coverage **1.000**, chart explainability coverage **1.000**, average elapsed **44.816 s**, threshold pass **true**.
- Unit tests: **219 passing** as of 2026-04-16.
- Citation thresholds: `MIN_CLAIM_CITATION_COVERAGE = 0.90`, `MIN_SECTION_CITATION_COVERAGE = 0.90`.
- Insights bullet cap: 5 (ordered: highlighted wells → cohort trend + risk → fastest decline → strongest rise → largest divergence).
- Changepoint screen: two-segment OLS, min 12 monthly bins/side, improvement ≥ 20%, confidence labels `high ≥ 0.45 / moderate ≥ 0.30 / low ≥ 0.20`.
- Cross-well clustering: standardized features (annual change, seasonal amplitude, confinement), fixed-initialization k-means with `k=3` (or `k=2` if < 6 wells), up to 20 iterations.
- Risk classification thresholds: `high` if ≥66% of wells falling, `moderate` if ≥33% falling (or ≥20% falling in a mostly-confined cohort), `low` otherwise.
- Trend slope unit: feet per monthly bin × 12 → ft/yr; trend series are named e.g. `"Cohort Trend (-0.18 ft/yr)"`.
- Provenance schema: `research_provenance_v1` with `code_commit`, `response_sha256`, `data_snapshot.sha256`, `config_hashes`, `methodology.trend_method = "monthly_OLS_with_screened_two_segment_changepoints"`, `methodology.cluster_method = "deterministic_standardized_kmeans"`, `methodology.external_covariates.included = false`.
- Structured response schema: `evidence_response_v1` with `answer`, `claims[*] = {claim, claim_type, claim_ids, evidence_ids, confidence, is_interpretive, uncertainty}`, `limitations`, `recommended_followup`, `evidence`.
- Web search: off by default (`GROUNDWATERGPT_ENABLE_WEB_SEARCH` env flag, default `False` at [api/routes/chat.py:363](api/routes/chat.py#L363)).
- LLM agent timeout (dormant — agent disabled in demo/eval): class default **300 s** at [src/agent/research_agent.py:267](src/agent/research_agent.py#L267), code-level override **120 s** at [api/routes/chat.py:565](api/routes/chat.py#L565). Search budgets at `max_depth=3`: **8 web / 12 KB / 18 API**, `max_total_cost=6.0`. These numbers have not been exercised at scale.
- Frontend bundle: lazy-loaded `AgentChart` and `ResearchChartsPanel` via `React.lazy` + `Suspense`; backend unreachable detection surfaces as a banner via a ~15-line `backendStatus` observable.

---

*End of document. Intended use: manuscript grounding source for* "EAGLE: Evidence-Aligned Groundwater Level Explorer for Auditable Florida USGS Groundwater Trend Analysis." *Every numeric claim is verifiable against the cited file path or by running the benchmark harness locally. Remaining cleanup decisions in §11 should be resolved before submission so that the repository a reviewer sees matches the system the manuscript describes.*
