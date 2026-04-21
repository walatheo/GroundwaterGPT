"""Shared evidence-guided AI helpers for grounded progression."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

GENERIC_REWRITE_QUESTION_PATTERNS = (
    "tell me more",
    "what else should i know",
    "what caveats should i mention",
    "can you elaborate",
)
GENERIC_REWRITE_GOAL_PATTERNS = (
    "learn more",
    "understand better",
    "dig deeper",
)
FOLLOW_UP_GROUP_ORDER = (
    "Understand this",
    "Compare wells or units",
    "Check the caveat",
    "Strengthen the evidence",
)


class FollowUpGroup(BaseModel):
    """Stable grouped follow-up contract."""

    label: str
    questions: list[str] = Field(default_factory=list)
    reason: str = ""


class ProgressionRewrite(BaseModel):
    """Optional bounded LLM rewrite contract."""

    next_goal: str = ""
    follow_up_groups: list[FollowUpGroup] = Field(default_factory=list)


def clean_sentence(value: Any) -> str:
    """Return a normalized single-sentence version of ``text``."""
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if text.endswith((".", "!", "?")):
        return text
    return f"{text}."


def questionize(value: Any) -> str:
    """Rewrite a declarative sentence as a question for follow-up prompts."""
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    return text.rstrip(".?") + "?"


def flatten_follow_up_groups(groups: list[dict[str, Any]], *, limit: int = 4) -> list[str]:
    """Flatten nested follow-up question groups into a single ordered list."""
    flat: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for question in group.get("questions", []):
            normalized = questionize(question)
            key = normalized.lower()
            if not normalized or key in seen:
                continue
            flat.append(normalized)
            seen.add(key)
            if len(flat) >= limit:
                return flat
    return flat


def _clean_list(values: Any, *, limit: int = 6) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = " ".join(str(value or "").split()).strip()
        lowered = text.lower()
        if not text or lowered in seen:
            continue
        items.append(text)
        seen.add(lowered)
        if len(items) >= limit:
            break
    return items


def _unique_names_from_values(values: Any, *, limit: int = 6) -> list[str]:
    return _clean_list(values, limit=limit)


def _extract_supply_units(seed: dict[str, Any]) -> list[str]:
    units = seed.get("supply_units") or []
    names: list[str] = []
    for unit in units:
        if isinstance(unit, dict):
            text = str(unit.get("zone") or unit.get("name") or "").strip()
        else:
            text = str(unit or "").strip()
        if text:
            names.append(text)
    return _unique_names_from_values(names, limit=5)


def _extract_well_names(seed: dict[str, Any]) -> list[str]:
    wells = seed.get("well_names") or []
    if wells:
        return _unique_names_from_values(wells, limit=6)
    well_payloads = seed.get("wells") or []
    names = [
        str(well.get("name") or well.get("well_name") or "").strip()
        for well in well_payloads
        if isinstance(well, dict)
    ]
    return _unique_names_from_values(names, limit=6)


def _extract_divergent_pair(seed: dict[str, Any]) -> tuple[str, str] | None:
    pair = (seed.get("divergent_pairs") or [None])[0]
    if not isinstance(pair, dict):
        return None
    site_a = pair.get("site_a") or {}
    site_b = pair.get("site_b") or {}
    a = str(site_a.get("name") or "").strip()
    b = str(site_b.get("name") or "").strip()
    if a and b:
        return a, b
    return None


def _extract_date_references(seed: dict[str, Any]) -> list[str]:
    explicit = _clean_list(seed.get("date_references") or [], limit=5)
    if explicit:
        return explicit
    text = " ".join(
        [
            str(seed.get("question") or ""),
            str(seed.get("direct_answer") or ""),
            str(seed.get("answer_text") or ""),
            " ".join(str(item) for item in seed.get("supporting_evidence") or []),
        ]
    )
    refs: list[str] = []
    for match in re.findall(
        r"\b(?:19|20)\d{2}\s*(?:-|to|through)\s*(?:19|20)\d{2}\b", text, flags=re.I
    ):
        refs.append(match)
    refs.extend(re.findall(r"\bover the last \d+\s+(?:year|years|months)\b", text, flags=re.I))
    refs.extend(re.findall(r"\b(?:19|20)\d{2}\b", text))
    return _clean_list(refs, limit=5)


def _build_next_goal(seed: dict[str, Any]) -> str:
    evidence_needed = _clean_list(seed.get("evidence_needed") or [], limit=3)
    supply_units = _extract_supply_units(seed)
    well_names = _extract_well_names(seed)
    date_refs = _extract_date_references(seed)
    question_intent = str(seed.get("question_intent") or "").strip().lower()
    divergent_pair = _extract_divergent_pair(seed)
    caveat = str(seed.get("caveat") or "").lower()

    if evidence_needed:
        return clean_sentence(f"Test the main caveat by checking {evidence_needed[0]}")
    if supply_units:
        return clean_sentence(
            f"Trace this answer back to the supply unit proxies, starting with {supply_units[0]}"
        )
    if divergent_pair:
        return clean_sentence(
            f"Explain why {divergent_pair[0]} and {divergent_pair[1]} diverge before treating the chart as one signal"  # noqa: E501
        )
    if question_intent == "cohort_meaning":
        return clean_sentence(
            "Translate the cohort summary into the wells pulling the average up or down"
        )
    if len(well_names) >= 2:
        return clean_sentence(
            f"Compare {well_names[0]} and {well_names[1]} to see what is driving the pattern"
        )
    if date_refs:
        return clean_sentence(
            f"Narrow this answer to the {date_refs[0]} window and compare it with another period"
        )
    if "does not prove" in caveat or "caus" in caveat:
        return clean_sentence(
            "Separate the observed pattern from the outside evidence needed to test a cause"
        )
    return clean_sentence(
        "Turn this grounded answer into the next narrow, testable groundwater question"
    )


def _deterministic_question_candidates(seed: dict[str, Any]) -> dict[str, list[str]]:
    question_intent = str(seed.get("question_intent") or "").strip().lower()
    evidence_needed = _clean_list(seed.get("evidence_needed") or [], limit=3)
    support = _clean_list(seed.get("supporting_evidence") or [], limit=3)
    supply_units = _extract_supply_units(seed)
    well_names = _extract_well_names(seed)
    date_refs = _extract_date_references(seed)
    divergent_pair = _extract_divergent_pair(seed)
    seeded_questions = _clean_list(seed.get("follow_up_questions") or [], limit=4)

    groups: dict[str, list[str]] = {label: [] for label in FOLLOW_UP_GROUP_ORDER}

    def add(label: str, question: str) -> None:
        normalized = questionize(question)
        if not normalized:
            return
        bucket = groups.setdefault(label, [])
        if normalized not in bucket and len(bucket) < 2:
            bucket.append(normalized)

    for question in seeded_questions:
        lower = question.lower()
        if re.search(r"\b(compare|diverge|shallow|deep)\b", lower):
            add("Compare wells or units", question)
        elif re.search(r"\b(caveat|outside data|prove|confirm|test|strengthen)\b", lower):
            add("Check the caveat", question)
        elif re.search(r"\b(evidence|proxy|source|record|period|time|dates?)\b", lower):
            add("Strengthen the evidence", question)
        else:
            add("Understand this", question)

    if question_intent == "fastest_changing":
        add("Understand this", "Which well is changing fastest, and what is its annual rate")
    if question_intent == "cohort_meaning":
        add("Understand this", "Which wells are pulling the cohort average down or up")
    if question_intent == "risk_explanation":
        add(
            "Check the caveat",
            "What outside data would tell us whether this screening risk reflects pumping, recharge, or something else",  # noqa: E501
        )
    if question_intent == "shallow_deep_comparison":
        add(
            "Compare wells or units",
            "Do the shallow and deep wells stay separated through wet and dry seasons",
        )

    if supply_units:
        add("Understand this", f"Which proxy wells represent the {supply_units[0]} supply unit")
        if len(supply_units) >= 2:
            add(
                "Compare wells or units",
                f"How do {supply_units[0]} and {supply_units[1]} differ in this monitoring record",
            )
        add(
            "Strengthen the evidence",
            "What utility or construction records would confirm how well these proxy wells represent supply wells",  # noqa: E501
        )

    if divergent_pair:
        add(
            "Compare wells or units",
            f"Why do {divergent_pair[0]} and {divergent_pair[1]} diverge on this chart",
        )
    elif len(well_names) >= 2:
        add(
            "Compare wells or units",
            f"Compare {well_names[0]} and {well_names[1]} using the same chart and well metadata",
        )

    if date_refs:
        add("Strengthen the evidence", f"How does this answer change if we isolate {date_refs[0]}")
        add(
            "Understand this", "What happened before and after that period in the monitoring record"
        )

    if evidence_needed:
        add("Check the caveat", "What caveats should I mention")
        add("Check the caveat", f"What would we learn from {evidence_needed[0]}")
    elif support:
        add("Check the caveat", "What caveats should I mention")
        add("Check the caveat", "What outside data would strengthen this interpretation")

    if not groups["Strengthen the evidence"]:
        add("Strengthen the evidence", "What outside data would strengthen this interpretation")

    return groups


def _questions_from_reasoning_gaps(
    reasoning_trace: list[dict[str, Any]] | None
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {label: [] for label in FOLLOW_UP_GROUP_ORDER}
    seen: set[str] = set()

    def add(label: str, question: str) -> None:
        normalized = questionize(question)
        if not normalized:
            return
        lowered = normalized.lower()
        if lowered in seen:
            return
        groups.setdefault(label, []).append(normalized)
        seen.add(lowered)

    for step in reasoning_trace or []:
        if not isinstance(step, dict):
            continue
        confidence = str(step.get("confidence") or "").lower()
        if confidence not in {"medium", "low"}:
            continue
        label = str(step.get("step_label") or "").lower()
        inference = str(step.get("inference") or "").lower()
        observation = str(step.get("observation") or "").lower()
        text = " ".join([label, inference, observation])

        if "season" in text:
            add("Understand this", "Is this decline seasonal or persistent")
        elif "proxy" in text or "supply" in text:
            add(
                "Strengthen the evidence",
                "What utility or construction records would confirm how well these proxy wells represent supply wells",  # noqa: E501
            )
            add(
                "Check the caveat",
                "What proxy limitations should I mention before using this as a supply-risk claim",
            )
        elif "aquifer" in text and "cover" in text:
            add("Compare wells or units", "What about the other aquifer units in this dataset")
        elif "diverg" in text:
            add("Compare wells or units", "Why do the key proxy wells diverge")
        else:
            add(
                "Strengthen the evidence",
                "What outside evidence would most reduce the uncertainty in this step",
            )

    return groups


def _render_groups(groups: dict[str, list[str]]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    for label in FOLLOW_UP_GROUP_ORDER:
        questions = groups.get(label) or []
        if not questions:
            continue
        reason = {
            "Understand this": "Clarify the main grounded signal.",
            "Compare wells or units": "Check whether one well, aquifer, or supply unit is driving the pattern.",  # noqa: E501
            "Check the caveat": "Keep interpretation separate from unsupported causal claims.",
            "Strengthen the evidence": "Identify the next outside evidence that would materially improve confidence.",  # noqa: E501
        }.get(label, "")
        rendered.append({"label": label, "questions": questions[:2], "reason": reason})
    return rendered


def _providers() -> list[tuple[str, str]]:
    providers: list[tuple[str, str]] = []
    if os.getenv("DASHSCOPE_API_KEY"):
        providers.append(("qwen", os.getenv("GROUNDWATERGPT_PROGRESS_MODEL", "qwen-plus")))
    providers.append(
        (
            "ollama",
            os.getenv("GROUNDWATERGPT_PROGRESS_MODEL", os.getenv("SYNTHESIS_MODEL", "qwen3:8b")),
        )
    )
    return providers


def _allowed_anchor_terms(seed: dict[str, Any], progression: dict[str, Any]) -> set[str]:
    terms = {
        *[item.lower() for item in _extract_supply_units(seed)],
        *[item.lower() for item in _extract_well_names(seed)],
        *[item.lower() for item in _extract_date_references(seed)],
    }
    for question in flatten_follow_up_groups(progression.get("follow_up_groups", []), limit=8):
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9/-]+", question.lower()):
            if len(token) >= 4:
                terms.add(token)
    return {term for term in terms if term}


def _validate_rewrite(
    rewrite: ProgressionRewrite,
    *,
    seed: dict[str, Any],
    deterministic: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    next_goal = " ".join(rewrite.next_goal.split()).strip().lower()
    if not next_goal:
        flags.append("empty_next_goal")
    if any(pattern in next_goal for pattern in GENERIC_REWRITE_GOAL_PATTERNS):
        flags.append("generic_next_goal")

    groups = [group.model_dump() for group in rewrite.follow_up_groups]
    flat_questions = flatten_follow_up_groups(groups, limit=8)
    if not flat_questions:
        flags.append("empty_follow_up_groups")
        return flags

    anchor_terms = _allowed_anchor_terms(seed, deterministic)
    deterministic_flat = flatten_follow_up_groups(
        deterministic.get("follow_up_groups", []), limit=8
    )
    deterministic_blob = " ".join(deterministic_flat).lower()
    for question in flat_questions:
        lowered = question.lower()
        if any(pattern in lowered for pattern in GENERIC_REWRITE_QUESTION_PATTERNS):
            flags.append("generic_follow_up_question")
        if not question.endswith("?"):
            flags.append("malformed_follow_up_question")
        if re.search(r"\b\d+(?:\.\d+)?\b", question) and not re.search(
            r"\b\d+(?:\.\d+)?\b", deterministic_blob
        ):
            flags.append("invented_numeric_detail")
        if anchor_terms and not any(term in lowered for term in anchor_terms):
            if not re.search(
                r"\b(chart|well|wells|aquifer|supply|trend|period|data|evidence|screening|cohort)\b",  # noqa: E501
                lowered,
            ):
                flags.append("unsupported_follow_up_question")
                break
    return list(dict.fromkeys(flags))


def _invoke_progression_rewrite(
    seed: dict[str, Any], progression: dict[str, Any]
) -> ProgressionRewrite | None:
    for provider_name, model in _providers():
        try:
            from src.agent.llm_factory import LLMProvider, get_llm

            provider = LLMProvider(provider_name)
            llm = get_llm(provider=provider, model=model, temperature=0)
            if not hasattr(llm, "with_structured_output"):
                continue
            structured_llm = llm.with_structured_output(ProgressionRewrite)
            prompt_payload = {
                "grounded_seed": seed,
                "deterministic_progression": progression,
                "rules": [
                    "Rewrite only wording, not the underlying factual premise.",
                    "Do not add new wells, dates, numbers, aquifers, or causal claims.",
                    "Keep the next_goal concise and specific.",
                    "Every follow-up question must remain grounded in the deterministic progression.",  # noqa: E501
                ],
            }
            raw = structured_llm.invoke(
                [
                    (
                        "system",
                        "You improve grounded groundwater follow-up wording without adding facts.",
                    ),
                    (
                        "human",
                        "Return a concise ProgressionRewrite.\n\n"
                        f"{json.dumps(prompt_payload, indent=2, sort_keys=True)}",
                    ),
                ]
            )
            if isinstance(raw, ProgressionRewrite):
                return raw
            if isinstance(raw, dict):
                return ProgressionRewrite(**raw)
        except Exception as exc:
            logger.debug("Progression rewrite unavailable via %s: %s", provider_name, exc)
            continue
    return None


def build_evidence_guided_progression(
    seed: dict[str, Any],
    *,
    allow_llm_rewrite: bool = False,
    reasoning_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build next-goal guidance and grouped follow-ups from grounded evidence."""
    deterministic_groups = _deterministic_question_candidates(seed)
    gap_groups = _questions_from_reasoning_gaps(reasoning_trace)
    merged_groups: dict[str, list[str]] = {label: [] for label in FOLLOW_UP_GROUP_ORDER}
    for label in FOLLOW_UP_GROUP_ORDER:
        for source in (gap_groups, deterministic_groups):
            for question in source.get(label, []):
                normalized = questionize(question)
                if normalized and normalized not in merged_groups[label]:
                    merged_groups[label].append(normalized)
    deterministic = {
        "next_goal": _build_next_goal(seed),
        "follow_up_groups": _render_groups(merged_groups),
    }
    deterministic["follow_up_questions"] = flatten_follow_up_groups(
        deterministic["follow_up_groups"],
        limit=4,
    )
    deterministic["progression_source"] = "deterministic"
    deterministic["progression_guardrail_flags"] = []

    if not allow_llm_rewrite:
        return deterministic

    rewrite = _invoke_progression_rewrite(seed, deterministic)
    if rewrite is None:
        return deterministic

    flags = _validate_rewrite(rewrite, seed=seed, deterministic=deterministic)
    if flags:
        deterministic["progression_guardrail_flags"] = flags
        return deterministic

    rewritten_groups = [group.model_dump() for group in rewrite.follow_up_groups]
    return {
        "next_goal": clean_sentence(rewrite.next_goal),
        "follow_up_groups": rewritten_groups,
        "follow_up_questions": flatten_follow_up_groups(rewritten_groups, limit=4),
        "progression_source": "llm_rewrite",
        "progression_guardrail_flags": [],
    }
