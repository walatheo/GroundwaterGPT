# Grounded Chat Contract (Phase 0)

This is the product-level contract every chat surface must honour. Routing,
response assembly, LLM usage, and frontend rendering are all derived from this
document. If you are about to add a new chat path and it does not fit, the
contract is wrong — update it first, don't smuggle a fourth shape into the
envelope.

The canonical source-of-truth for the enums below is
`api/routes/_answer_contract.py`. Do not hard-code these strings anywhere else.

## One paragraph

GroundwaterGPT is a grounded chat assistant over a fixed Florida USGS dataset.
Every reply is one of three things: a deterministic data answer, a grounded
interpretation built on top of deterministic evidence, or an explicit
"insufficient evidence" refusal with next steps. Numeric claims always come
from deterministic code; the LLM may explain, it may not originate
measurements. If the LLM is unavailable or produces low-quality output, we
fall back to deterministic prose and the grounding status reflects it.

## Answer types

Exactly three `answer_type` values exist. No fourth.

| `answer_type`             | What it is                                                              | Narrative allowed? |
| ------------------------- | ----------------------------------------------------------------------- | ------------------ |
| `data_answer`             | Deterministic metrics with minimal framing. No LLM synthesis attached.  | No                 |
| `interpretation_answer`   | Deterministic evidence + grounded explanation of what it means.         | Yes, bounded       |
| `insufficient_evidence`   | Question cannot be answered from the dataset. Returns next steps.       | No                 |

The frontend renders each type with one presentation pattern — a chat surface
with more than three visual layouts is a regression.

## Route modes

`route_mode` describes *how the backend selected the reply*. It is a coarse
intent tag, not an implementation detail. Keep it stable across refactors —
benchmark coverage is keyed on this field.

| `route_mode`       | Trigger                                                  |
| ------------------ | -------------------------------------------------------- |
| `exact_well`       | Explicit site IDs / well names (G-3336, C-1224, 15-digit).|
| `cohort`           | Aquifer, location, or multi-location cohort queries.     |
| `chart_followup`   | User is referring to an active chart or previous chart.  |
| `interpretation`   | Explicit ask for interpretation / "what does this mean". |
| `network`          | Network-wide questions ("all wells", "which county").    |
| `research`         | Deep research endpoint (LLM-led, citation-bound).        |
| `unsupported`      | Causal, predictive, or out-of-dataset questions.         |
| `fallback`         | KB / rule-based fallback when nothing else routed.       |

## Grounding status

`grounding_status` is the single top-level string that tells the UI and any
downstream evaluator how tightly the reply is bound to evidence.

| `grounding_status`  | Meaning                                                             |
| ------------------- | ------------------------------------------------------------------- |
| `grounded`          | Deterministic evidence present AND citation integrity passed.       |
| `partial`           | Deterministic evidence present but integrity/completeness imperfect.|
| `insufficient`      | Not enough evidence in the dataset to answer.                       |
| `refused`           | Interpreter declined (out-of-scope, unsupported causal, etc.).      |

The richer per-field dict that already lives inside
`interpretation_response.grounding_status` is kept as-is. The top-level
`grounding_status` is the product-level summary; the dict is the audit trail.

## LLM policy

One sentence: **the LLM may explain, it may not originate measurements.**

- LLM input: route intent, deterministic metrics, grounded findings, limits,
  required caveats.
- LLM output is post-processed to reject or reconcile any numeric claim not
  present in the deterministic evidence pack.
- If the LLM is unavailable, times out, or produces malformed output, the
  chat path returns deterministic prose with `grounding_status = "partial"`
  and `has_llm_synthesis = false`.
- There is **one** explainer interface. Site answers and chart interpretation
  both call it. No separate "narration" vs "interpretation" paths at the
  product level.

## Response envelope

Every chat response (`/api/chat`, `/api/interpret`, `/api/research`) carries
these top-level fields after `stamp_contract_fields` runs:

```jsonc
{
  // Canonical triad (Phase 0, stamped at envelope exit)
  "answer_type": "data_answer" | "interpretation_answer" | "insufficient_evidence",
  "route_mode": "exact_well" | "cohort" | "chart_followup" | "interpretation"
              | "network" | "research" | "unsupported" | "fallback",
  "grounding_status": "grounded" | "partial" | "insufficient" | "refused",

  // Existing envelope (unchanged in Phase 0, will be consolidated in Phase 2)
  "response": "...",                    // human-facing text
  "answer_brief": "...",                // short headline (optional)
  "chart": { ... } | null,              // Recharts-ready payload
  "wells": [ ... ],                     // well metadata
  "sources": [ ... ],
  "claim_citations": [ ... ],
  "citation_integrity": { "passed": bool, ... },
  "interpretation_response": { ... } | null,  // rich interpreter output
  "llm_synthesis": "..." | null,              // narrative from the explainer
  "follow_up_questions": [ ... ],
  "next_goal": "...",
  "mode": "site_fallback" | "chart_interpreter" | ... ,  // internal, not canonical
  // ... other existing fields ...
}
```

### Internal `mode` vs canonical `route_mode`

`mode` remains the internal implementation tag (`site_fallback`,
`chart_interpreter`, `aquifer_fallback`, etc.). `route_mode` is the canonical
product-level view derived from `mode` via `canonical_route_mode`. External
consumers should read `route_mode`; internal code that still branches on
`mode` is acceptable in Phase 0 and will be refactored in Phase 1.

## Acceptance criteria (Phase 0)

- [x] Three `answer_type` values, no more.
- [x] One shared module owns the enums (`_answer_contract.py`).
- [x] Every chat payload carries `answer_type`, `route_mode`, `grounding_status`
      at the top level after `_augment_chat_payload` or `_augment_research_payload`.
- [x] `/api/interpret` re-stamps the triad after rewriting `mode`.
- [x] LLM policy stated in one place and referenced from code.
- [x] Unit tests lock in the derivation rules.

Phase 0 intentionally does **not** restructure the existing envelope or
collapse the routing tree. Its only job is to freeze the vocabulary so
Phase 1 (unify routing) and Phase 2 (shared answer builder) have a stable
target to converge on.

## What Phase 0 does NOT solve

- Frontend heuristics are still authoritative in some followup paths (Phase 1).
- `_build_chat_payload` still has ~25 fields — reduction happens in Phase 2.
- There are still two narrative paths internally (site and chart) — merged in
  Phase 3.
- `insufficient_evidence` is detectable today but not yet a distinct code path
  — first-class handling ships in Phase 4.
