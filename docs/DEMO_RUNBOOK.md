# EAGLE Demo Runbook

**Last updated:** April 15, 2026

This runbook is the recommended demo path for EAGLE: Evidence-Aligned Groundwater
Level Explorer. The demo should emphasize the real contribution: a deterministic
Florida USGS groundwater pipeline that turns public monitoring records into
auditable, chart-backed, claim-bound cross-cohort summaries. The language model
is a narration layer, not the source of groundwater facts.

## 1. Demo Thesis

Open with this framing:

> EAGLE makes public USGS groundwater records usable for research by selecting
> monitored Florida wells, computing reproducible trend and cohort summaries,
> generating charts and maps, and binding every factual claim to citations,
> evidence IDs, and provenance hashes. The LLM can help narrate, but the
> groundwater numbers come from deterministic code.

The strongest demo is not "chatbot answers." It is the pipeline:

- 44 Florida well metadata entries.
- 40 canonical local USGS time-series CSVs.
- Daily depth-to-water observations spanning 1994-01-01 through 2026-04-05 across the shipped dataset.
- Monthly aggregation, OLS trend summaries, divergent-pair screening, candidate changepoints, behavior clusters, aquifer grouping, chart payloads, citation integrity, and provenance.
- Deterministic benchmark: 68/68 cases passing, overall score 1.000, citation coverage 1.000, claim-verdict coverage 1.000.

## 2. Recommended 5-Minute Arc

### Step 1: State the Problem

Say:

> USGS groundwater data are public, but turning individual well records into a
> defensible local research answer usually requires manual site discovery,
> cleaning, trend analysis, plotting, and citation work.

Then show EAGLE as the bridge from raw monitoring records to auditable research
outputs.

### Step 2: Ask a Location Question

Use:

```text
What has been the change in groundwater level in Estero over the last 30 years?
```

Point out:

- The system selects nearby monitored wells using a reproducible Haversine/county heuristic.
- The report states the period of record.
- Trend values come from monthly means and deterministic OLS.
- Wells are grouped by aquifer context.
- Sources point back to USGS monitoring records.
- The chart uses the same deterministic series and trend values as the report.
- The y-axis is inverted because the measured variable is depth to water below land surface.
- The chart explanation panel translates the plotted monthly means, highlighted wells,
  cohort average, and trend overlays into an interpretation guide.

### Step 3: Show Cross-Cohort Novelty

Use one of:

```text
Compare groundwater trends across Lee County wells.
```

```text
Compare Biscayne and Floridan aquifer monitoring trends.
```

Point out:

- Cross-well trend distribution.
- Aquifer-grouped reporting.
- Divergent pairs.
- Candidate changepoints.
- Behavior clusters.
- Cohort risk label.
- Chart highlights for the fastest-changing or most divergent wells.

Say:

> This is where the novelty lives: EAGLE is not just answering a single site
> question. It converts public USGS records into an inspectable cross-cohort
> presentation layer.

### Step 4: Show Auditability

Open the response details, browser network payload, or terminal JSON output.

Point out these fields:

- `claim_citations`
- `claim_verdicts`
- `claim_verdict_summary`
- `citation_summary`
- `structured_response`
- `provenance`
- `chart`

Say:

> The language layer is not allowed to invent new groundwater facts. Factual
> claims must bind to registered claim IDs and evidence IDs. Unbacked claims are
> dropped by the parser.

### Step 5: Close With Benchmark Evidence

Show or mention:

```bash
python3 scripts/run_chat_benchmark.py --mode fallback --enforce-thresholds
```

Close with:

> The deterministic layer passes all 68 benchmark cases with complete citation
> and claim-verdict coverage. That benchmark validates software behavior and
> auditability, not that the OLS trend labels are hydrologically optimal.

## 3. Startup Options

Use deterministic mode for the most reliable live demo.

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT
export GROUNDWATERGPT_SKIP_AGENT_INIT=1
make demo
```

Open:

```text
http://127.0.0.1:3000
```

`make demo` intentionally starts the deterministic demo by setting
`GROUNDWATERGPT_SKIP_AGENT_INIT=1` inside [scripts/start_demo.sh](../scripts/start_demo.sh).

If you want the hybrid Ollama narration layer, start Ollama first and run the
backend/frontend manually instead of `make demo`.

```bash
ollama serve
ollama pull llama3.2
```

Then in a separate terminal:

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT
LLM_PROVIDER=ollama LLM_MODEL=llama3.2 uvicorn api.main:app --port 8000
```

And in another terminal:

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT/frontend
npm run dev -- --host 127.0.0.1 --port 3000
```

For manuscript-facing demos, deterministic mode is safer and more defensible.
Use the live-agent path only as an architectural preview.

## 4. Frontend Demo Checklist

In the app, show these surfaces in order:

- Site/map context: where the monitored wells are and which Florida locations are in scope.
- AI assistant: ask the Estero trend question.
- Chart panel: point to monthly depth-to-water series, cohort average, trend overlays, and highlighted wells.
- Chart explainability panel: show that the LLM receives bounded chart context and
  can explain how to read the data without inventing new measurements.
- Interpretation brief: ask "Interpret the Estero groundwater chart for a sponsor"
  and show the chart context, key observations, USGS references, limitations,
  `next_goal`, and grouped follow-up questions.
- Source/citation panel: point to USGS-backed sources and claim citations.
- Any provenance/details panel: point to response hashes, method flags, and data snapshot references if visible.
- Research workflow, if time allows: plan -> run -> draft as a reproducibility workflow rather than a scientific proof.

Avoid spending the main demo on generic chat. Keep returning to the pipeline:

> selected wells -> monthly means -> trend/cohort analysis -> chart -> claim/evidence IDs -> provenance.

## 5. API Demo Commands

If the frontend is unavailable, the API demo is enough.

### Terminal A: Start API

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT
export GROUNDWATERGPT_SKIP_AGENT_INIT=1
uvicorn api.main:app --reload --port 8000
```

### Terminal B: Health Check

```bash
curl -s http://127.0.0.1:8000/api/chat/status | jq
```

### Estero Research Query

```bash
curl -s http://127.0.0.1:8000/api/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"What has been the change in groundwater level in Estero over the last 30 years?"}' \
  | jq '{mode, report, citation_summary, claim_verdict_summary, structured_response, provenance}'
```

Expected:

- `mode` should route to a deterministic fallback branch for the location.
- `report` should include site selection, period of record, aquifer sections, and trend language.
- `citation_summary` should show high citation coverage.
- `claim_verdict_summary` should be present.
- `structured_response.schema_version` should be `evidence_response_v1`.
- `provenance.schema_version` should be `research_provenance_v1`.

### Fast Interpretation Query

```bash
curl -s http://127.0.0.1:8000/api/interpret \
  -H 'Content-Type: application/json' \
  -d '{"question":"Interpret the Estero groundwater chart for a sponsor.","audience":"sponsor","use_llm":false}' \
  | jq '{mode, interpretation_response, chart: {title: .chart.title, insights: .chart.insights}}'
```

Expected:

- `interpretation_response.schema_version` should be `interpretation_response_v1`.
- `grounding_status.uses_chart_context` and `grounding_status.uses_usgs_data` should be true.
- `grounding_status.invented_measurements_allowed` should be false.
- `next_goal` should be populated.
- `follow_up_groups` should be present with grouped questions.
- `data_references` should point back to USGS NWIS wells.

### Cross-Cohort Query

## 6. Learner Validation Protocol

Use this when you want a modest but honest claim about user help, not a learning-science claim.

### Task study

- Recruit 5-8 novice or non-specialist users.
- Give each person 5 chart-reading tasks:
  - "What does this chart mean?"
  - "Why should I care about this decline?"
  - "What does screening risk mean in plain English?"
  - "What does the cohort average mean?"
  - "What should we check before making a cause claim?"
- For each task, score three things:
  - correct takeaway
  - correct caveat
  - correct next check

### Evidence to collect

- Benchmark pass from `scripts/run_interpretation_benchmark.py`
- Lightweight learner events in `outputs/research/learner_events/`
- Manual scorecard notes from the novice task study

### Claim standard

- After benchmark only:
  - "The interpretation feature is designed to help curious non-expert users understand chart meaning, limits, and next checks."
- After benchmark plus learner-event evidence and the small task study:
  - "The interpretation feature can help curious non-expert users interpret chart-backed groundwater patterns."
- Do not claim improved learning outcomes or teaching effectiveness without comparative user-study evidence.

```bash
curl -s http://127.0.0.1:8000/api/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"Compare groundwater trends across Lee County wells."}' \
  | jq '{mode, report, chart, claim_citations, citation_summary}'
```

Expected:

- Multiple wells in the selected cohort.
- Trend distribution and aquifer context.
- Divergent-pair or fastest-changing-well language when applicable.
- A chart payload suitable for the frontend.

### Aquifer Comparison Query

```bash
curl -s http://127.0.0.1:8000/api/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"Compare Biscayne and Floridan aquifer monitoring trends."}' \
  | jq '{mode, report, chart, claim_citations, citation_summary}'
```

Expected:

- Aquifer-grouped sections.
- Cross-aquifer comparison language.
- Claims and evidence links for factual statements.

## 6. Benchmark Proof

Run the deterministic benchmark:

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT
python3 scripts/run_chat_benchmark.py --mode fallback --enforce-thresholds
jq '.summary' chat_benchmark_report.json
```

Shortcut:

```bash
make benchmark
```

Run the narrow evidence-guided AI benchmark:

```bash
cd /Users/salatheoclay/Desktop/GroundwaterGPT/GroundwaterGPT
python3 scripts/run_evidence_guided_synthesis_benchmark.py --enforce-thresholds
jq '.summary' evidence_guided_synthesis_benchmark_report.json
```

Shortcut:

```bash
make benchmark-evidence-guided
```

Current closeout result:

- Cases: 68.
- Overall score: 1.000.
- Average citation coverage: 1.000.
- Average claim-citation coverage: 1.000.
- Average section-citation coverage: 1.000.
- Average claim-verdict coverage: 1.000.
- Threshold pass: true.
- Median latency: 4.173 s.
- Max latency: 8.070 s.

Use this line when presenting:

> These benchmark numbers validate that the deterministic system returns the
> expected auditable fields. They do not validate hydrogeologic causality or
> claim that OLS-on-monthly-means is the best trend estimator.

## 7. LLM Synthesis Benchmark

Run this when Ollama is available and you want to show that the language-model
path can produce the same audit envelope while narrating the deterministic data.
The smoke command is the best last-day proof because it exercises the LLM path
without waiting for all 68 cases.

```bash
make benchmark-llm-smoke
jq '.summary, .agent_path_summary' agent_benchmark_report.json
```

Full live-agent suite:

```bash
make benchmark-llm
```

For a live demo with grounded chart narration, start Ollama and run the API
without `GROUNDWATERGPT_SKIP_AGENT_INIT`. Ask:

```text
Explain the Lee County groundwater chart like I am a student.
```

What to point out:

- The chart and deterministic report still come from USGS records.
- The LLM explanation is bounded by the chart payload, aquifer summaries, and cohort metrics.
- LLM synthesis claims cite `local://eagle/deterministic-chart-context` so the audit layer
  can distinguish grounded chart narration from raw USGS measurements.
- `claim_verdicts`, `structured_response`, and `provenance` remain present.

Current chart-LLM smoke result:

- Cases: 1.
- Passed: true.
- LLM synthesis coverage: 1.000.
- Chart explainability coverage: 1.000.
- Average elapsed: 44.816 s.

Current closeout smoke result:

- Cases: 1/68.
- Agent-routed rate: 1.000.
- Structured-response coverage: 1.000.
- Provenance coverage: 1.000.
- Citation coverage: 0.000.
- Claim-verdict coverage: 0.000.
- Overall score: 0.200.
- Median/max latency: 270.155 s.
- Threshold pass: false.

Say:

> The live agent path can emit the typed audit envelope, but full-suite LLM
> quality and latency are future work. The manuscript claim rests on the
> deterministic pipeline.

## 8. Things Not To Claim

Do not claim:

- The 1.000 benchmark score proves the hydrologic conclusions are scientifically optimal.
- The risk labels are calibrated against expert labels.
- Candidate changepoints are formal statistical regime shifts.
- Divergent pairs prove aquifer connectivity or causal mechanisms.
- The current system dynamically covers the national USGS network.
- The live LLM path is production-latency ready.

Safer wording:

- "Screening heuristic"
- "Exploratory cross-cohort summary"
- "Deterministic trend estimate"
- "Evidence-bound narration"
- "Auditable presentation layer"
- "Florida monitoring-network scope"

## 9. Backup Demo If Something Fails

If the frontend is down:

```bash
python3 scripts/run_chat_benchmark.py --mode fallback --enforce-thresholds
jq '.summary' chat_benchmark_report.json
```

If the API is down:

- Open [MANUSCRIPT_DRAFT.md](MANUSCRIPT_DRAFT.md) and show the Results section.
- Open [EAGLE_TECHNICAL_OVERVIEW.md](EAGLE_TECHNICAL_OVERVIEW.md) and show sections 3, 4, and 9.
- Open `chat_benchmark_report.json` and show `.summary`.

If Ollama is down:

- Keep the demo deterministic.
- Say the LLM path is optional and explicitly not the source of measured groundwater facts.

## 10. One-Sentence Close

End with:

> EAGLE shows how environmental data systems can use language interfaces without
> giving the language model authority over the science: the deterministic
> pipeline produces the claims, charts, citations, and provenance; the LLM only
> helps communicate them.
