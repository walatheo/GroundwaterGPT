# Session 14: Estero Deep-Answer + Streaming Parity + Frontend Upgrade

**Date:** April 6, 2026

## Summary

This session completed the Estero deep-answer capability (aquifer-grouped responses, water supply context, LLM synthesis) and then closed the gap between the sync and streaming endpoints, upgraded the frontend to render markdown, and surfaced new API fields in the UI.

## Changes

### Phase 0: `llm_synthesis` Forwarding Fix

`_site_research_fallback()` returns an `llm_synthesis` field (separated from the report to enforce explicit opt-in), but the `/api/chat` and `/api/research` endpoint response dicts manually whitelist fields and were omitting it. Added `"llm_synthesis": result.get("llm_synthesis")` to all 8 response dict locations (4 per endpoint: site-name, aquifer, location, network paths).

### Phase 1: Streaming Endpoint Parity

- **`max_sites`**: Changed from 2 to 10 in the location branch so streaming returns the same well count as sync
- **Coordinate passthrough**: Added `ref_lat`/`ref_lng` to `_site_research_fallback()` call so proxy justification (distance + bearing) works in streaming
- **`_wrap()` fields**: Added `hallucination_guardrail`, `llm_synthesis`, and `citation_integrity` to the streaming response builder
- **`aquifer_info`**: Added to both aquifer and location branches
- **Aquifer `max_sites`**: Bumped from 6 to 8 to match sync endpoint

### Phase 2: Frontend Upgrade

- **Markdown rendering**: Replaced `whitespace-pre-wrap` plain text with `react-markdown` using custom Tailwind component overrides (no `@tailwindcss/typography` dependency)
- **LLM synthesis callout**: Purple-bordered box labeled "LLM Synthesis (interpretive -- uncited)" renders the `llm_synthesis` field as markdown, visually separated from the deterministic report
- **Guardrail badge**: Amber "Some claims uncited" badge appears when `hallucination_guardrail.all_factual_claims_cited` is false
- **Aquifer-grouped wells**: Wells are grouped by `w.aquifer` with section headers showing aquifer name and well count, only when multiple aquifer systems are present
- **State wiring**: Both research and chat mode handlers now pass `llm_synthesis` and `hallucination_guardrail` into message state

### Phase 3: Documentation

- Updated `DEMO_RUNBOOK.md` with water supply query example, new frontend features, benchmark count (63 cases / 40 sites)
- Created this session document

## Architecture

### LLM Synthesis Pipeline
1. Query matches `_SYNTHESIS_TRIGGER_RE` (supply/sustainability keywords) -> triggers synthesis
2. Direct `httpx.post` to Ollama API (`llama3.2`, `think: false`, `keep_alive: 10m`)
3. Synthesis text returned in separate `llm_synthesis` field (not in `report`)
4. Synthesis claim added to `claim_citations` with `confidence: 0.5`, empty citations, `source_type: llm_synthesis`
5. `hallucination_guardrail.all_factual_claims_cited` dynamically reflects uncited claims
6. Frontend renders synthesis in distinct purple callout with "uncited" label

### Response Field Contract
All three endpoint families (`/api/chat`, `/api/research`, `/api/research/stream`) now return:
- `report` — deterministic, USGS-data-backed markdown
- `llm_synthesis` — interpretive LLM text (null when not triggered)
- `hallucination_guardrail` — `{strategy, removed_uncited_factual_sentences, all_factual_claims_cited, has_llm_synthesis}`
- `citation_integrity` — `{overall_integrity, total_claims, ...}`
- `wells` — per-well structured data with aquifer, confinement, depth, margin
- `aquifer_info` — zone metadata (on aquifer and location paths)

## Key Files Modified
| File | Changes |
|------|---------|
| `api/routes/chat.py` | `llm_synthesis` forwarding (8 locations), streaming `_wrap()`, `max_sites`, `ref_lat`/`ref_lng`, `aquifer_info` |
| `frontend/src/components/ChatView.jsx` | ReactMarkdown, LLM synthesis callout, guardrail badge, aquifer-grouped wells |
| `frontend/package.json` | Added `react-markdown` |
| `docs/DEMO_RUNBOOK.md` | Water supply demo, frontend features, benchmark count |

## Benchmark
63 cases across 40 USGS sites, covering: Estero trends (L1/L2/L3), aquifer queries, metadata, multi-site, well-name, supply sources, sustainability. All passing at session start; verification run after changes confirms no regressions.
