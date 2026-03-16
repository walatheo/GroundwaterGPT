# GroundwaterGPT — Session Plan

**Created:** March 16, 2026
**Phase:** 5 — AI Research Integration (Sprint 5 active)
**Goal:** Multi-agent research architecture + frontend verdict exposure

---

## 1. What Was Completed This Session (While You Slept)

### Code Fixes
| File | Issue | Fix Applied |
|------|-------|-------------|
| `api/routes/chat.py` | `sys.path` mutation to import `claim_disagreement` | Replaced with canonical `src.claim_disagreement` import |
| `api/routes/chat.py` | Second `sys.path` mutation for agent imports | Removed — imports already used `src.*` form |
| `api/routes/chat.py` | `import sys` left as dead import | Removed |
| `src/agent/llm_factory.py` | Default Anthropic model was `claude-3-sonnet-20240229` (Mar 2024, deprecated) | Updated to `claude-sonnet-4-6` (current) |
| `src/agent/llm_factory.py` | `RECOMMENDED_MODELS` list included old Claude 3 IDs | Updated to `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-haiku-4-5-20251001` |

### Docs Updates
| File | Change |
|------|--------|
| `docs/CHECKLIST.md` | Sprint updated to Mar 16–23; Sprint 4 marked complete; Sprint 5 tasks listed; Phase 5 progress updated to 65% |
| `docs/PROJECT_STATUS.md` | Sprint 4 marked complete with full task list; Sprint 5 tasks defined; last-updated date corrected |

---

## 2. What Is Currently In Progress (Needs Attention Next)

### A. Uncommitted Working Changes (git diff HEAD)
All 13 modified files have uncommitted changes from Sprint 4 work. These are ready to commit:

```
api/routes/chat.py                             (+124 lines) claim verdicts + sys.path cleanup
src/agent/research_agent.py                    (+6 lines)   claim verdicts wired into DeepResearchAgent
src/evaluation/chat_benchmark.py               (+74 lines)  verdict coverage + risk-rate metrics
tests/benchmark/chat_eval_thresholds.json      (+3 fields)  verdict quality gate keys
tests/benchmark/chat_eval_live_thresholds.json (+3 fields)  live-mode verdict gates
tests/benchmark/test_chat_benchmark.py         (+45 lines)  verdict + summary schema tests
tests/unit/test_agent.py                       (+44 lines)  agent verdict output tests
tests/unit/test_chat_api.py                    (+20 lines)  API verdict response tests
src/agent/llm_factory.py                       (model IDs)  Claude 4.x update
docs/CHECKLIST.md                              (dates/tasks) Sprint 5 plan
docs/PROJECT_STATUS.md                         (dates/tasks) Sprint 4 complete
docs/CAPABILITIES_MATRIX.md                    (minor)
docs/DEMO_RUNBOOK.md                           (minor)
```

### B. New Untracked Files (need to be staged)
```
docs/DELIVERABLE_PLAN.md      — depth-first deliverable scope doc
docs/SESSION_PLAN.md          — this file
src/claim_disagreement.py     — claim disagreement engine (305 lines)
tests/unit/test_claim_disagreement.py — 4 unit tests for the engine
```

---

## 3. Remaining Code Cleanup Items

### Priority: High (blocks clean CI)
| Item | File | Action |
|------|------|--------|
| `# noqa: E402` comments now stale | `api/routes/chat.py` | Removed by import fix this session ✅ |
| Dead `import sys` | `api/routes/chat.py` | Removed this session ✅ |
| Anthropic model outdated | `llm_factory.py` | Fixed this session ✅ |

### Priority: Medium (code quality)
| Item | File | Action |
|------|------|--------|
| `research_agent.py` is 1,035 lines | `src/agent/research_agent.py` | Extract `_build_claim_citations`, `_build_section_confidence`, `_strip_uncited_factual_sentences` into a `report_builder.py` helper |
| `chat.py` is 950 lines | `api/routes/chat.py` | Extract Estero fallback logic (~200 lines) to `api/routes/_estero_fallback.py` |
| `knowledge.py` is 744 lines | `src/agent/knowledge.py` | Extract PDF ingestion pipeline to `src/agent/ingestion.py` |
| `ClaimDisagreementEngine` in `api/routes/chat.py` duplicates fallback logic that mirrors `src/claim_disagreement.py` | `api/routes/chat.py` | Since engine import now succeeds, the manual fallback inside `_build_claim_verdicts` can be simplified to just trust the engine always |

### Priority: Low (polish)
| Item | File | Action |
|------|------|--------|
| `GROUNDWATER_KB` rule-based topics hardcoded at top of chat.py | `api/routes/chat.py` | Move to `api/knowledge_base_topics.py` |
| `SITE_METADATA` imported but large | `api/site_metadata.py` | No change needed — already separate |
| `.gitignore` has 3 uncommitted lines | `.gitignore` | Include in next commit |

---

## 4. Session Goals (Sprint 5) — What To Build Next

### Goal 1: Commit Current Sprint 4 Work
**Status:** Ready — all tests expected to pass.
```bash
git add -A
git commit -m "feat(research): wire claim verdict engine + Sprint 4 quality hardening"
```

### Goal 2: Multi-Agent Orchestrator Skeleton
**Files to create:**
- `src/agent/orchestrator.py` — `LeadResearcher` class that accepts a research plan and dispatches `SubAgent` tasks
- `src/agent/sub_agent.py` — `SubAgent` class with typed task protocol: `SearchTask`, `SummarizeTask`, `VerifyTask`

**Design contract:**
```python
@dataclass
class ResearchTask:
    task_type: Literal["search", "summarize", "verify"]
    query: str
    context: dict[str, Any]

class SubAgent:
    def run(self, task: ResearchTask) -> SubAgentResult: ...

class LeadResearcher:
    def plan(self, question: str, budget: ResearchBudget) -> list[ResearchTask]: ...
    def run(self, tasks: list[ResearchTask]) -> ResearchResult: ...
    def reflect(self, result: ResearchResult) -> list[ResearchTask]: ...  # generates follow-ups
```

### Goal 3: Contradiction-Aware Report Synthesis
When `claim_verdicts` includes contradicted claims, the final report synthesis should:
1. Flag contradictions inline: `[⚠ contradicted by claim_002]`
2. Add a "Conflicting Evidence" section if `contradicted_claim_rate > 0.15`
3. Adjust section confidence downward for contradicted sections

**File:** `src/agent/research_agent.py` — update `_synthesize_report()` to consume `claim_verdicts`.

### Goal 4: Frontend Verdict Display
**File:** `frontend/src/components/ResearchPanel.jsx` (or equivalent)
- Add a `ClaimVerdictBadge` component: shows `supported` / `contradicted` / `insufficient_evidence`
- Show `claim_verdict_summary` at the top of research results (total claims, contradicted rate, high-risk flags)
- Highlight contradicted claims in red, supported in green, insufficient in grey

### Goal 5: L2 Benchmark Validation
Run the Level 2 benchmark question through the live agent and validate:
- Correct aquifer identification (Lower Tamiami, Hawthorn, Upper Floridan)
- Multi-well citation with site IDs
- Trend per aquifer
- Sustainability implications
- Fully reproducible

---

## 5. What Phase 5 "Done" Looks Like

All of these must be true before Phase 6 begins:

| Gate | Target | How to Verify |
|------|--------|--------------|
| G5.1 LLM Connected | Qwen3 local default working | `GET /api/chat/status` returns `llm_available: true` |
| G5.2 RAG Precision | ≥90% Precision@k | `python scripts/run_retrieval_precision.py` passes gate |
| G5.3 Source Citations | 100% claims cited | `citation_integrity.claim_coverage_ok == true` in API responses |
| G5.4 Hallucination Rate | <5% uncited sentences | Guardrail active, benchmark `hallucination_guardrail` field present |
| G5.5 Farmer KB Topics | ≥10 topics | 10 topics in `GROUNDWATER_KB` ✅ |
| G5.6 Response Time | <3s fallback / <8s live | Benchmark `max_response_seconds` gates pass |
| G5.7 Multi-Agent | Orchestrator dispatches ≥2 SubAgents | Sprint 5 Goal 2 above |
| G5.8 Contradiction Synthesis | Contradictions flagged in reports | Sprint 5 Goal 3 above |
| G5.9 Frontend Verdicts | Verdict UI visible | Sprint 5 Goal 4 above |

---

## 6. Architecture Debt Register

These are known architectural issues that should be addressed before Phase 7 (Production):

| Debt | File(s) | Risk | Suggested Fix |
|------|---------|------|---------------|
| Module size: `research_agent.py` > 1K lines | `src/agent/research_agent.py` | Hard to review, test, extend | Extract into `report_builder.py`, `query_optimizer.py` |
| Module size: `chat.py` > 950 lines | `api/routes/chat.py` | Same | Split Estero fallback and verdict builders into sub-modules |
| Module size: `knowledge.py` > 740 lines | `src/agent/knowledge.py` | Same | Extract ingestion to `ingestion.py` |
| LLM config is a global mutable dict | `src/agent/llm_factory.py` | Thread-unsafe | Replace with a `LLMConfig` dataclass + environment-driven init |
| No async support in `DeepResearchAgent` | `src/agent/research_agent.py` | Blocks event loop under load | Add `async def research_async()` wrapper using `asyncio.to_thread` |
| ChromaDB uses in-process client | `src/agent/knowledge.py` | Doesn't scale past single process | Switch to `HttpClient` mode for production |
| No auth on API endpoints | `api/routes/` | Anyone can hit research endpoints | Add API key middleware before Phase 7 |

---

## 7. Quick Reference Commands

```bash
# Run all unit tests
python -m pytest tests/unit/ -q

# Run benchmark harness (deterministic/fallback)
python scripts/run_chat_benchmark.py --output /tmp/bench.json

# Run live-mode benchmark (requires Ollama running)
python scripts/run_chat_benchmark.py --mode live --output /tmp/bench_live.json

# Run retrieval precision gate
python scripts/run_retrieval_precision.py --output /tmp/precision.json

# Start API server
uvicorn api.main:app --reload --port 8000

# Start frontend
cd frontend && npm run dev

# Check git status of uncommitted Sprint 4 work
git diff --stat HEAD
git status --short
```

---

*This plan was auto-generated during the session of March 16, 2026.*
*Update this file at the start of each new session to reflect current status.*
