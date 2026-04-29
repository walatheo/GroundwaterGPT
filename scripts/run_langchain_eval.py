#!/usr/bin/env python3
"""LangChain-powered rubric evaluator for grounded interpretations.

Runs each case in ``tests/benchmark/interpretation_eval_cases.json`` through
the chart interpreter, then scores every draft on four rubric criteria with
a Qwen judge:

    - **grounding**  — does every factual sentence anchor to evidence?
    - **hedge**       — is causal language hedged appropriately?
    - **completeness** — does the answer cover the rubric moves?
    - **clarity**     — would a hydrogeology student understand it?

The per-case scorecard is emitted as JSON so the paper can cite the numbers
directly. Qwen-only: we never instantiate OpenAI / Anthropic / Gemini.

Usage::

    python3 scripts/run_langchain_eval.py --out /tmp/eval.json --cases 5

The script is intentionally tolerant: if the LLM is offline, it emits the
cases with a ``"judge": "unavailable"`` marker so CI doesn't fail.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("langchain_eval")

DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "benchmark" / "interpretation_eval_cases.json"
)

CRITERIA: dict[str, str] = {
    "grounding": (
        "Does every factual sentence anchor to a USGS site URL, a numeric "
        "value from the evidence pack, or a deterministic chart metric? "
        "Penalize any claim that invents data or cites no evidence."
    ),
    "hedge": (
        "When the answer discusses cause (pumping, drought, recharge), does "
        "it correctly hedge — e.g. 'the record does not prove'? Penalize "
        "unqualified causal claims; reward explicit mention of missing "
        "pumping/rainfall data."
    ),
    "completeness": (
        "Does the answer cover the rubric moves for this intent "
        "(observation, inference, limitations, follow-ups)? Penalize "
        "single-sentence or shallow responses."
    ),
    "clarity": (
        "Could a hydrogeology graduate student follow this answer without "
        "rereading? Penalize jargon salad, broken references, unexplained "
        "acronyms."
    ),
}


@dataclass
class CriterionScore:
    """A single rubric criterion score for one interpretation draft."""

    name: str
    score: float  # 0.0 .. 1.0
    reasoning: str


@dataclass
class CaseScorecard:
    """Aggregated scorecard for one benchmark case across all criteria."""

    case_id: str
    question: str
    grounding_status: str
    criterion_scores: list[CriterionScore]
    overall: float
    judge: str
    provider: str = ""


_JUDGE_PROMPT = """You are an impartial reviewer scoring a groundwater
interpretation against one rubric criterion. Respond with a JSON object of
the form {{"score": <float between 0 and 1>, "reasoning": <short string>}}.
Do not include any other text.

Criterion: {criterion_name}
Description: {criterion_desc}

Interpretation draft:
---
{draft}
---

Score the draft strictly on this criterion."""


def _load_cases(path: Path, limit: Optional[int]) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text())
    return cases[:limit] if limit else cases


def _get_judge_llm():
    """Instantiate the Qwen judge LLM; return ``None`` when unavailable."""
    try:
        from src.agent.llm_factory import LLMProvider, get_llm

        if os.getenv("DASHSCOPE_API_KEY"):
            return get_llm(provider=LLMProvider("dashscope"), model="qwen-plus", temperature=0)
        return get_llm(provider=LLMProvider("ollama"), model="qwen3:8b", temperature=0)
    except Exception as exc:
        logger.warning("Judge LLM unavailable: %s", exc)
        return None


def _score_one_criterion(llm, draft: str, name: str, description: str) -> CriterionScore:
    if llm is None:
        return CriterionScore(name=name, score=0.0, reasoning="judge unavailable")
    prompt = _JUDGE_PROMPT.format(
        criterion_name=name, criterion_desc=description, draft=draft[:4000]
    )
    try:
        response = llm.invoke(prompt)
        raw = getattr(response, "content", response)
        payload = json.loads(str(raw).strip())
        return CriterionScore(
            name=name,
            score=float(payload.get("score", 0.0)),
            reasoning=str(payload.get("reasoning", ""))[:400],
        )
    except Exception as exc:
        logger.debug("judge parse failed for %s: %s", name, exc)
        return CriterionScore(name=name, score=0.0, reasoning=f"judge error: {exc}")


def _draft_text(interpretation: Any) -> str:
    """Collapse a ``GroundedInterpretation`` into judge-ready text."""
    if interpretation is None:
        return ""
    parts: list[str] = []
    for attr in ("direct_answer", "why_it_matters", "what_matters_most", "implications"):
        value = getattr(interpretation, attr, "")
        if value:
            parts.append(f"{attr}: {value}")
    for step in getattr(interpretation, "reasoning_steps", []) or []:
        parts.append(f"step: {step.step_label} — {step.observation} -> {step.inference}")
    limits = getattr(interpretation, "limitations", None) or []
    if limits:
        parts.append("limits: " + "; ".join(str(x) for x in limits))
    return "\n".join(parts)


def score_interpretation(interpretation: Any, llm) -> list[CriterionScore]:
    """Score one interpretation draft against every criterion in CRITERIA."""
    draft = _draft_text(interpretation)
    if not draft:
        return [CriterionScore(name=n, score=0.0, reasoning="empty draft") for n in CRITERIA]
    return [_score_one_criterion(llm, draft, name, desc) for name, desc in CRITERIA.items()]


def _run_case(case: dict, llm) -> CaseScorecard:
    question = case.get("question", "")
    case_id = str(case.get("id", ""))

    grounded = None
    provider = ""
    try:
        os.environ.setdefault("GROUNDWATERGPT_SKIP_AGENT_INIT", "1")
        from api.routes.answering.reasoning import invoke_grounded_synthesis

        grounded = invoke_grounded_synthesis(
            question,
            site_computed=[],
            aquifer_summaries=[],
            cross_well={},
            supply_info=None,
            location_name="estero",
        )
        provider = getattr(grounded, "llm_provider", "") if grounded else ""
    except Exception as exc:
        logger.warning("interpreter failed for %s: %s", case_id, exc)

    scores = score_interpretation(grounded, llm)
    overall = sum(s.score for s in scores) / max(len(scores), 1)
    return CaseScorecard(
        case_id=case_id,
        question=question,
        grounding_status=getattr(grounded, "grounding_status", "missing"),
        criterion_scores=scores,
        overall=round(overall, 3),
        judge="qwen" if llm is not None else "unavailable",
        provider=provider,
    )


def main() -> int:
    """CLI entry point: run the eval across all cases and write a report."""
    logging.basicConfig(level=os.getenv("GROUNDWATERGPT_LOG", "WARNING"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=None, help="limit number of cases")
    parser.add_argument("--out", type=Path, default=None, help="output JSON path")
    parser.add_argument("--cases-path", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override synthesis model (sets GROUNDWATERGPT_LLM_MODEL for the run).",
    )
    args = parser.parse_args()

    if args.model:
        os.environ["GROUNDWATERGPT_LLM_MODEL"] = args.model

    cases = _load_cases(args.cases_path, args.cases)
    llm = _get_judge_llm()

    scorecards = [asdict(_run_case(c, llm)) for c in cases]
    report = {
        "n_cases": len(cases),
        "judge_available": llm is not None,
        "criteria": list(CRITERIA.keys()),
        "cases": scorecards,
        "aggregate": {
            criterion: round(
                sum(
                    next(
                        (s["score"] for s in card["criterion_scores"] if s["name"] == criterion),
                        0.0,
                    )
                    for card in scorecards
                )
                / max(len(scorecards), 1),
                3,
            )
            for criterion in CRITERIA
        },
    }

    if args.out:
        args.out.write_text(json.dumps(report, indent=2))
        print(f"wrote scorecard to {args.out}")
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
