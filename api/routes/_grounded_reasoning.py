"""Grounded reasoning helpers for chart-context interpretation.

Supports two entry points:
 - ``invoke_grounded_reasoning()``  — chart interpreter (follow-ups)
 - ``invoke_grounded_synthesis()``  — chat path (initial answer, replaces
   Ollama httpx block in _site_analysis.py)

Feature-flagged: ``GROUNDWATERGPT_ENABLE_GROUNDED_REASONING=true``
"""

from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HYDRO_CONTEXT_PATH = PROJECT_ROOT / "config" / "estero_hydrogeology_context.json"

_NEGATIVE_SIGNAL_TERMS = (
    "declin",
    "falling",
    "most stressed",
    "fastest decline",
    "declining fastest",
    "sustainability risk",
    "drawdown",
)

_OPEN_REASONING_MODEL_RE = re.compile(r"(qwen3|deepseek-r1|qwq)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Feature flag & config
# ---------------------------------------------------------------------------


def grounded_reasoning_enabled() -> bool:
    """Check if grounded reasoning is enabled via env var."""
    return os.getenv("GROUNDWATERGPT_ENABLE_GROUNDED_REASONING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@lru_cache(maxsize=1)
def _load_hydro_contexts() -> dict[str, Any]:
    """Load location-specific hydrogeology context file."""
    if not HYDRO_CONTEXT_PATH.exists():
        return {}
    try:
        return json.loads(HYDRO_CONTEXT_PATH.read_text())
    except Exception as exc:
        logger.warning("Failed to load hydro context: %s", exc)
        return {}


def load_hydro_context(location_name: str) -> dict[str, Any] | None:
    """Return hydrogeology context for a location, or None."""
    contexts = _load_hydro_contexts()
    locations = contexts.get("locations", {})
    key = location_name.lower().strip()
    return locations.get(key)


# ---------------------------------------------------------------------------
# Raw evidence extraction (NOT pre-computed answers)
# ---------------------------------------------------------------------------


def _compact_well(site: dict[str, Any]) -> dict[str, Any]:
    """Build a compact well record — no nulls, no redundant fields."""
    seasonal = site.get("seasonal") or {}
    well: dict[str, Any] = {
        "name": site.get("name"),
        "site_id": site.get("site_id"),
        "aquifer": site.get("aquifer") or site.get("aq_label"),
        "zone": site.get("aquifer_zone") or site.get("zone") or site.get("aq_zone"),
        "depth_ft": site.get("well_depth_ft"),
        "coords": [site.get("lat"), site.get("lng")],
        "period": [site.get("record_start"), site.get("record_end")],
        "ft_yr": site.get("annual_change_ft_yr", site.get("annual_change")),
        "net_ft": site.get("net_change_ft"),
        "trend": site.get("trend_label") or site.get("trend"),
    }
    # Only include seasonal if present
    amp = seasonal.get("seasonal_amplitude_ft", site.get("seasonal_amplitude_ft"))
    if amp is not None:
        well["seasonal_amp_ft"] = amp
        wet = seasonal.get("wet_season_mean", site.get("wet_season_mean_ft"))
        dry = seasonal.get("dry_season_mean", site.get("dry_season_mean_ft"))
        if wet is not None and dry is not None:
            well["wet_dry_mean"] = [wet, dry]
    if site.get("confined") is not None:
        well["confined"] = site["confined"]
    return {k: v for k, v in well.items() if v is not None}


def _compact_hydro_context(hydro_context: dict[str, Any], pack_zones: set[str]) -> dict[str, Any]:
    """Extract only the aquifer context relevant to wells in the pack."""
    compact: dict[str, Any] = {}
    framework = hydro_context.get("aquifer_framework") or {}
    for _aq_name, aq_data in framework.items():
        zone = aq_data.get("zone", "")
        # Include if any pack well is in this zone, or if it's a supply unit
        if zone.lower() in pack_zones or aq_data.get("supply_role"):
            compact[zone] = {
                "supply_role": aq_data.get("supply_role"),
                "depth_ft": aq_data.get("depth_range_ft"),
                "risk_factors": aq_data.get("risk_factors", [])[:2],
                "proxy_limitations": aq_data.get("proxy_limitations", ""),
            }
    regional = hydro_context.get("regional_context")
    if regional:
        compact["regional"] = {
            "setting": regional.get("setting", "")[:150],
            "growth_pressure": regional.get("growth_pressure", "")[:150],
        }
    return compact


def _build_reasoning_evidence(
    pack: dict[str, Any], hydro_context: dict[str, Any] | None
) -> dict[str, Any]:
    """Extract raw evidence for the LLM to reason over.

    Token-optimized: no nulls, compact field names, hydro context trimmed
    to only the aquifers present in the pack.
    """
    wells = [_compact_well(site) for site in pack.get("sites") or pack.get("wells") or []]

    cross_well = pack.get("cross_well") or pack.get("comparison_features") or {}
    evidence: dict[str, Any] = {
        "wells": wells,
        "cohort": {
            k: v
            for k, v in {
                "mean_ft_yr": cross_well.get("mean_annual_change_ft_yr")
                or cross_well.get("cohort_mean_annual_change_ft_yr"),
                "std_ft_yr": cross_well.get("std_annual_change_ft_yr"),
                "trends": cross_well.get("trend_distribution"),
                "risk": cross_well.get("risk_level"),
                "n": cross_well.get("n_total"),
            }.items()
            if v is not None
        },
    }

    divergent = (cross_well.get("divergent_pairs") or [])[:3]
    if divergent:
        evidence["divergent_pairs"] = divergent
    changepoints = (cross_well.get("changepoints") or [])[:3]
    if changepoints:
        evidence["changepoints"] = changepoints

    supply_info = pack.get("supply_info") or pack.get("supply_interpretation")
    if supply_info:
        evidence["supply"] = supply_info

    aquifer_summaries = pack.get("aquifer_summaries")
    if aquifer_summaries:
        evidence["aquifer_groups"] = [
            {
                k: v
                for k, v in {
                    "aquifer": s.get("aquifer"),
                    "zone": s.get("zone"),
                    "n": s.get("n_wells"),
                    "mean_ft_yr": s.get("mean_annual_change"),
                    "falling": s.get("n_falling"),
                    "stable": s.get("n_stable"),
                    "rising": s.get("n_rising"),
                }.items()
                if v is not None
            }
            for s in aquifer_summaries
        ]

    if hydro_context:
        pack_zones = {str(w.get("zone") or "").lower() for w in wells if w.get("zone")}
        evidence["hydro"] = _compact_hydro_context(hydro_context, pack_zones)

    return evidence


class GroundedNumericClaim(BaseModel):
    """Structured numeric claim pulled from grounded evidence."""

    site: str
    value: float
    unit: Literal["ft/yr", "ft", "ft_bls", "yr"]
    source: Literal[
        "annual_change_ft_yr",
        "mean_annual_change_ft_yr",
        "aquifer_mean_annual_change_ft_yr",
        "supply_unit_mean_annual_change_ft_yr",
        "net_change_ft",
        "well_depth_ft",
        "record_years",
        "latest_depth_to_water_ft",
    ]


class GroundedFraming(BaseModel):
    """Framing of a grounded question — intent, focus entities, and goal."""

    scope_type: Literal[
        "well", "aquifer", "supply_unit", "cross_well", "cohort", "chart", "unknown"
    ] = "unknown"
    focus_entities: list[str] = Field(default_factory=list)
    comparison_entities: list[str] = Field(default_factory=list)
    question_goal: Literal[
        "explain", "compare", "rank", "contextualize", "why_it_matters", "source_proxy", "general"
    ] = "general"
    required_evidence_sections: list[str] = Field(default_factory=list)


class ReasoningStep(BaseModel):
    """Single step inside a grounded reasoning chain."""

    step_label: str
    observation: str
    evidence_keys: list[str] = Field(default_factory=list)
    inference: str
    confidence: Literal["high", "medium", "low"]


class GroundedInterpretation(BaseModel):
    """Full grounded interpretation: framing, steps, evidence, and limits."""

    intent: str
    framing: GroundedFraming = Field(default_factory=GroundedFraming)
    reasoning_steps: list[ReasoningStep] = Field(default_factory=list)
    direct_answer: str = ""
    what_matters_most: str = ""
    aquifer_summaries: list[dict[str, Any]] = Field(default_factory=list)
    why_it_matters: str = ""
    implications: str = ""
    evidence_used_summary: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    important_limits: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    numeric_claims: list[GroundedNumericClaim] = Field(default_factory=list)
    perspectives: list[str] = Field(default_factory=list)
    answer_moves_completed: list[str] = Field(default_factory=list)
    grounding_status: Literal["grounded", "partial", "refused"]
    llm_provider: str = ""
    llm_model: str = ""


def _normalize_entity(text: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    return normalized


def _entity_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        lowered = text.lower()
        normalized = _normalize_entity(text)
        tokens.update({lowered, normalized})
        for chunk in re.findall(r"[a-z0-9]+(?:\s+[a-z0-9]+){0,4}", normalized):
            chunk = chunk.strip()
            if len(chunk) >= 4:
                tokens.add(chunk)
        for code in re.findall(r"\b[A-Z]+-\d+[A-Z]?\b", text, flags=re.I):
            tokens.add(code.lower())
    return {token for token in tokens if token}


def _question_text(question: str) -> str:
    return " ".join(str(question or "").lower().split())


def _question_has_any(question: str, *patterns: str) -> bool:
    lowered = _question_text(question)
    return any(pattern in lowered for pattern in patterns)


def _well_catalog(pack: dict[str, Any]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for summary in pack.get("well_summaries") or []:
        label = str(summary.get("name") or "")
        if not label:
            continue
        catalog.append(
            {
                "label": label,
                "site_id": summary.get("site_id"),
                "tokens": _entity_tokens(
                    label, summary.get("borehole_code"), summary.get("site_id")
                ),
            }
        )
    return catalog


def _aquifer_catalog(pack: dict[str, Any]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for summary in pack.get("aquifer_summaries") or []:
        label = str(summary.get("zone") or summary.get("aquifer") or "")
        aquifer = str(summary.get("aquifer") or "")
        if not label and not aquifer:
            continue
        catalog.append(
            {
                "label": label or aquifer,
                "tokens": _entity_tokens(label, aquifer, f"{aquifer} {label}".strip()),
            }
        )
    return catalog


def _supply_unit_catalog(pack: dict[str, Any]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for summary in pack.get("supply_unit_summaries") or []:
        label = str(summary.get("zone") or summary.get("aquifer") or "")
        aquifer = str(summary.get("aquifer") or "")
        usage = str(summary.get("usage") or "")
        if not label and not aquifer:
            continue
        catalog.append(
            {
                "label": label or aquifer,
                "tokens": _entity_tokens(label, aquifer, usage, f"{usage} {label}".strip()),
            }
        )
    return catalog


def _match_labels(question: str, catalog: list[dict[str, Any]]) -> list[str]:
    lowered = _question_text(question)
    matches: list[str] = []
    for item in catalog:
        if any(token in lowered for token in item.get("tokens", set())):
            label = str(item.get("label") or "").strip()
            if label and label not in matches:
                matches.append(label)
    return matches


def derive_question_frame(question: str, pack: dict[str, Any]) -> GroundedFraming:
    """Derive the question frame (intent, focus, goal) from the user query."""
    lowered = _question_text(question)
    well_matches = _match_labels(question, _well_catalog(pack))
    aquifer_matches = _match_labels(question, _aquifer_catalog(pack))
    supply_matches = _match_labels(question, _supply_unit_catalog(pack))

    compare_like = bool(
        re.search(
            r"\b(compare|comparison|versus|vs\.?|diverg\w*|different|stand out|relative to|other wells?)\b",  # noqa: E501
            lowered,
        )
    )
    rank_like = bool(
        re.search(
            r"\b(most|least|fastest|strongest|weakest|most stressed|top|rank)\b",
            lowered,
        )
    )
    why_like = bool(re.search(r"\b(why|explain|because|what matters|meaning|what does)\b", lowered))
    proxy_like = bool(
        re.search(r"\b(proxy|supply|source|utility|municipal|production well)\b", lowered)
    )
    chart_like = bool(
        re.search(r"\b(chart|dataset|cohort|overall|across the wells|this data)\b", lowered)
    )

    if supply_matches and (proxy_like or chart_like or rank_like or why_like):
        goal = (
            "source_proxy"
            if proxy_like
            else "rank" if rank_like else "compare" if compare_like else "contextualize"
        )
        return GroundedFraming(
            scope_type="supply_unit",
            focus_entities=supply_matches[:2],
            comparison_entities=["dataset"] if chart_like else [],
            question_goal=goal,
            required_evidence_sections=[
                "supply_unit_summaries",
                "supply_interpretation",
                "comparison_features",
                "cohort_period_start",
                "cohort_period_end",
            ],
        )

    if len(well_matches) >= 2 or (well_matches and compare_like):
        return GroundedFraming(
            scope_type="cross_well",
            focus_entities=well_matches[:2],
            comparison_entities=well_matches[2:4] or ["cohort"],
            question_goal="compare" if compare_like else "contextualize",
            required_evidence_sections=[
                "well_summaries",
                "comparison_features",
                "cross_well",
                "cohort_period_start",
                "cohort_period_end",
            ],
        )

    if well_matches:
        goal = (
            "compare"
            if chart_like or compare_like
            else "rank" if rank_like else "explain" if why_like else "contextualize"
        )
        comparisons = ["cohort"] if chart_like or compare_like else []
        return GroundedFraming(
            scope_type="well",
            focus_entities=well_matches[:1],
            comparison_entities=comparisons,
            question_goal=goal,
            required_evidence_sections=[
                "well_summaries",
                "comparison_features",
                "cohort_period_start",
                "cohort_period_end",
            ],
        )

    if aquifer_matches:
        goal = (
            "rank"
            if rank_like
            else (
                "compare"
                if compare_like or chart_like
                else "explain" if why_like else "contextualize"
            )
        )
        return GroundedFraming(
            scope_type="aquifer",
            focus_entities=aquifer_matches[:2],
            comparison_entities=["dataset"] if chart_like or compare_like or rank_like else [],
            question_goal=goal,
            required_evidence_sections=[
                "aquifer_summaries",
                "well_summaries",
                "comparison_features",
                "cohort_period_start",
                "cohort_period_end",
            ],
        )

    if compare_like:
        return GroundedFraming(
            scope_type="cross_well",
            focus_entities=[],
            comparison_entities=["cohort"],
            question_goal="compare",
            required_evidence_sections=[
                "comparison_features",
                "cross_well",
                "well_summaries",
                "cohort_period_start",
                "cohort_period_end",
            ],
        )

    goal = (
        "why_it_matters"
        if _question_has_any(question, "why it matters", "why should", "why care")
        else "explain" if why_like else "contextualize"
    )
    return GroundedFraming(
        scope_type="cohort" if chart_like or pack.get("site_ids") else "chart",
        focus_entities=[],
        comparison_entities=["dataset"] if pack.get("site_ids") else [],
        question_goal=goal,
        required_evidence_sections=[
            "comparison_features",
            "cross_well",
            "aquifer_summaries",
            "cohort_period_start",
            "cohort_period_end",
        ],
    )


def _resolve_evidence_key(pack: dict[str, Any], key: str) -> bool:
    current: Any = pack
    for part in [piece for piece in str(key).split(".") if piece]:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(current):
                current = current[idx]
                continue
        return False
    return True


def _text_contains_period(text: str, start: str | None, end: str | None) -> bool:
    lowered = str(text or "").lower()
    if not start or not end:
        return True
    return start.lower() in lowered and end.lower() in lowered


def _frame_blob(interpretation: GroundedInterpretation) -> str:
    return " ".join(
        [
            interpretation.direct_answer,
            interpretation.what_matters_most,
            interpretation.why_it_matters,
            " ".join(interpretation.evidence_used_summary),
            " ".join(interpretation.limitations),
            " ".join(interpretation.important_limits),
            " ".join(step.observation for step in interpretation.reasoning_steps),
            " ".join(step.inference for step in interpretation.reasoning_steps),
        ]
    ).lower()


def _pack_sections_used(interpretation: GroundedInterpretation) -> set[str]:
    sections: set[str] = set()
    for step in interpretation.reasoning_steps:
        for key in step.evidence_keys:
            head = str(key).split(".", 1)[0]
            if head:
                sections.add(head)
    return sections


def _find_well_summary(pack: dict[str, Any], label: str) -> dict[str, Any] | None:
    target = _normalize_entity(label)
    for item in pack.get("well_summaries") or []:
        if target in _entity_tokens(
            item.get("name"), item.get("borehole_code"), item.get("site_id")
        ):
            return item
    return None


def _find_aquifer_summary(pack: dict[str, Any], label: str) -> dict[str, Any] | None:
    target = _normalize_entity(label)
    for item in pack.get("aquifer_summaries") or []:
        if target in _entity_tokens(
            item.get("zone"), item.get("aquifer"), f"{item.get('aquifer')} {item.get('zone')}"
        ):
            return item
    return None


def _find_supply_summary(pack: dict[str, Any], label: str) -> dict[str, Any] | None:
    target = _normalize_entity(label)
    for item in pack.get("supply_unit_summaries") or []:
        if target in _entity_tokens(item.get("zone"), item.get("aquifer"), item.get("usage")):
            return item
    return None


def _frame_mean_rate(pack: dict[str, Any], framing: GroundedFraming) -> float | None:
    if not framing.focus_entities:
        mean = (pack.get("comparison_features") or {}).get("cohort_mean_annual_change_ft_yr")
        return float(mean) if mean is not None else None
    entity = framing.focus_entities[0]
    if framing.scope_type == "well":
        item = _find_well_summary(pack, entity)
        return (
            float(item["annual_change_ft_yr"])
            if item and item.get("annual_change_ft_yr") is not None
            else None
        )
    if framing.scope_type == "aquifer":
        item = _find_aquifer_summary(pack, entity)
        return (
            float(item["mean_annual_change"])
            if item and item.get("mean_annual_change") is not None
            else None
        )
    if framing.scope_type == "supply_unit":
        item = _find_supply_summary(pack, entity)
        return (
            float(item["mean_annual_change_ft_yr"])
            if item and item.get("mean_annual_change_ft_yr") is not None
            else None
        )
    return None


def _frame_decline_rank(pack: dict[str, Any], framing: GroundedFraming) -> int | None:
    if not framing.focus_entities:
        return None
    entity = framing.focus_entities[0]
    if framing.scope_type == "well":
        item = _find_well_summary(pack, entity)
        return item.get("rank_by_decline") if item else None
    if framing.scope_type == "aquifer":
        item = _find_aquifer_summary(pack, entity)
        return item.get("rank_by_decline") if item else None
    if framing.scope_type == "supply_unit":
        item = _find_supply_summary(pack, entity)
        return item.get("rank_by_decline") if item else None
    return None


def validate_against_pack(
    interpretation: GroundedInterpretation,
    pack: dict[str, Any],
) -> list[str]:
    """Validate a grounded interpretation against the active evidence pack."""
    flags: list[str] = []
    valid_sites = {
        str(well.get("name")).lower(): str(well.get("site_id"))
        for well in pack.get("wells", []) or []
        if well.get("name")
    }
    for step in interpretation.reasoning_steps:
        if not step.evidence_keys:
            flags.append("grounded_reasoning_missing_evidence_keys")
        for key in step.evidence_keys:
            if not _resolve_evidence_key(pack, key):
                flags.append(f"grounded_reasoning_bad_evidence_key:{key}")
    text_blob = _frame_blob(interpretation)
    for name in re.findall(r"\bLee\s+L-\d+[A-Z]?\b", text_blob, flags=re.I):
        if name.lower() not in valid_sites:
            flags.append(f"grounded_reasoning_unknown_well:{name}")

    framing = interpretation.framing
    if framing.scope_type == "unknown":
        flags.append("grounded_reasoning_unknown_scope")
    if framing.focus_entities:
        for entity in framing.focus_entities:
            normalized = _normalize_entity(entity)
            if normalized and normalized not in text_blob:
                flags.append(f"grounded_reasoning_missing_focus_entity:{entity}")
    used_sections = _pack_sections_used(interpretation)
    for section in framing.required_evidence_sections:
        if section and section not in used_sections:
            flags.append(f"grounded_reasoning_missing_required_section:{section}")

    mean_rate = _frame_mean_rate(pack, framing)
    if mean_rate is not None and mean_rate > 0.02:
        if any(term in text_blob for term in _NEGATIVE_SIGNAL_TERMS):
            flags.append("grounded_reasoning_unsupported_negative_narrative")
    rank = _frame_decline_rank(pack, framing)
    if (
        rank
        and rank != 1
        and "most stressed" in text_blob
        and "not the most stressed" not in text_blob
    ):
        flags.append("grounded_reasoning_wrong_entity_ranking")
    return list(dict.fromkeys(flags))


def _check_success_criteria(
    interpretation: GroundedInterpretation,
    pack: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    start = pack.get("cohort_period_start")
    end = pack.get("cohort_period_end")
    answer_blob = _frame_blob(interpretation)
    if not _text_contains_period(answer_blob, start, end):
        flags.append("grounded_reasoning_missing_time_period")
    wells = pack.get("wells") or []
    if wells and "usgs" not in answer_blob.lower():
        flags.append("grounded_reasoning_missing_usgs_provenance")
    aquifer_summaries = pack.get("aquifer_summaries") or []
    if len(aquifer_summaries) >= 2 and interpretation.framing.scope_type in {
        "cohort",
        "cross_well",
        "supply_unit",
    }:
        if len(interpretation.aquifer_summaries) < 1:
            flags.append("grounded_reasoning_missing_aquifer_separation")
    if pack.get("supply_interpretation") and interpretation.framing.scope_type == "supply_unit":
        limits_blob = " ".join(
            [*interpretation.limitations, *interpretation.important_limits]
        ).lower()
        if "proxy" not in limits_blob and "production" not in limits_blob:
            flags.append("grounded_reasoning_missing_proxy_limitations")
    required_moves = (pack.get("interpretation_rubric") or {}).get("required_moves") or []
    if required_moves:
        move_blob = " ".join(
            [
                answer_blob,
                " ".join(interpretation.answer_moves_completed),
            ]
        )
        covered = sum(
            1
            for move in required_moves
            if any(token in move_blob for token in re.findall(r"[a-zA-Z]{5,}", str(move).lower()))
        )
        if covered == 0:
            flags.append("grounded_reasoning_missing_rubric_moves")
    return flags


def _top_aquifer(pack: dict[str, Any]) -> dict[str, Any] | None:
    summaries = [
        item
        for item in pack.get("aquifer_summaries") or []
        if item.get("mean_annual_change") is not None
    ]
    return (
        min(summaries, key=lambda item: float(item.get("mean_annual_change", 0.0)))
        if summaries
        else None
    )


def _top_supply_unit(pack: dict[str, Any]) -> dict[str, Any] | None:
    summaries = [
        item
        for item in pack.get("supply_unit_summaries") or []
        if item.get("mean_annual_change_ft_yr") is not None
    ]
    return (
        min(summaries, key=lambda item: float(item.get("mean_annual_change_ft_yr", 0.0)))
        if summaries
        else None
    )


def _well_fallback(
    frame: GroundedFraming, pack: dict[str, Any]
) -> tuple[str, str, list[str], list[str], list[str]]:
    item = _find_well_summary(pack, frame.focus_entities[0]) if frame.focus_entities else None
    if not item:
        return (
            "The current chart context does not contain a well-level summary for the requested focus well.",  # noqa: E501
            "The answer should stay at the cohort level instead of inventing a focused-well comparison.",  # noqa: E501
            [],
            ["The focused well could not be matched to the active chart context."],
            [],
        )
    relation = ""
    deviation = item.get("deviation_from_cohort_mean_ft_yr")
    if deviation is not None:
        if deviation < -0.05:
            relation = (
                f"It is more negative than the cohort mean by {abs(float(deviation)):.3f} ft/yr."
            )
        elif deviation > 0.05:
            relation = (
                f"It is more positive than the cohort mean by {abs(float(deviation)):.3f} ft/yr."
            )
        else:
            relation = (
                "It sits close to the cohort mean, so it looks representative rather than extreme."
            )
    direct = (
        f"Using USGS groundwater monitoring wells from {pack.get('cohort_period_start')} to {pack.get('cohort_period_end')}, "  # noqa: E501
        f"{item.get('name')} is the focused well in this dataset. It shows a {item.get('trend')} trend at "  # noqa: E501
        f"{float(item.get('annual_change_ft_yr', 0.0)):+.3f} ft/yr in {item.get('aquifer')} / {item.get('aquifer_zone')}."  # noqa: E501
    )
    matters = f"What matters most is how {item.get('name')} sits inside the chart rather than in isolation. {relation}".strip()  # noqa: E501
    evidence = [
        f"Evidence used: {item.get('name')} ({item.get('site_id')}) at {item.get('lat')}, {item.get('lng')}; "  # noqa: E501
        f"record {item.get('record_start')} to {item.get('record_end')}; rank {item.get('rank_by_decline')} by decline out of "  # noqa: E501
        f"{len(pack.get('well_summaries') or [])} wells."
    ]
    limits = [
        "A single monitoring well does not prove the cause of change.",
        "The chart shows observed water-level behavior, not pumping volumes or a forecast.",
    ]
    return (
        direct,
        matters,
        evidence,
        limits,
        ["identified_focused_well", "compared_to_dataset", "stated_limits"],
    )


def _aquifer_fallback(
    frame: GroundedFraming, pack: dict[str, Any]
) -> tuple[str, str, list[str], list[str], list[str]]:
    item = _find_aquifer_summary(pack, frame.focus_entities[0]) if frame.focus_entities else None
    top = _top_aquifer(pack)
    if not item:
        return (
            "The current chart context does not contain a matched aquifer summary for the requested unit.",  # noqa: E501
            "The answer should stay at the dataset level instead of guessing which aquifer was intended.",  # noqa: E501
            [],
            ["The aquifer focus could not be matched to the active chart context."],
            [],
        )
    mean = float(item.get("mean_annual_change", 0.0))
    if frame.question_goal == "rank" and top and str(top.get("zone")) != str(item.get("zone")):
        direct = (
            f"{item.get('zone')} is not the most decline-oriented aquifer in this dataset. "
            f"It averages {mean:+.3f} ft/yr, while {top.get('zone')} is more negative at "
            f"{float(top.get('mean_annual_change', 0.0)):+.3f} ft/yr."
        )
    else:
        direct = (
            f"In this dataset, {item.get('zone')} averages {mean:+.3f} ft/yr across {item.get('n_wells')} "  # noqa: E501
            f"USGS monitoring well{'s' if int(item.get('n_wells') or 0) != 1 else ''}."
        )
    matters = (
        f"What matters most is the relative position of {item.get('zone')} inside the current chart: "  # noqa: E501
        f"{item.get('n_falling', 0)} falling, {item.get('n_stable', 0)} stable, and {item.get('n_rising', 0)} rising wells."  # noqa: E501
    )
    evidence = [
        f"Evidence used: wells {', '.join((item.get('well_names') or [])[:4])}; record {pack.get('cohort_period_start')} to {pack.get('cohort_period_end')}; "  # noqa: E501
        f"rank {item.get('rank_by_decline')} by mean decline across aquifer units."
    ]
    limits = [
        "Aquifer summaries are screening aggregates of monitoring wells, not production-zone models.",  # noqa: E501
        "A mean aquifer trend can hide divergent behavior among individual wells.",
    ]
    return (
        direct,
        matters,
        evidence,
        limits,
        ["identified_focus_aquifer", "compared_within_dataset", "stated_limits"],
    )


def _supply_fallback(
    frame: GroundedFraming, pack: dict[str, Any]
) -> tuple[str, str, list[str], list[str], list[str]]:
    item = _find_supply_summary(pack, frame.focus_entities[0]) if frame.focus_entities else None
    top = _top_supply_unit(pack)
    if not item:
        return (
            "The current chart context does not contain a matched supply-unit summary for the requested unit.",  # noqa: E501
            "The answer should stay at the chart level instead of inferring supply-unit behavior that is not in the pack.",  # noqa: E501
            [],
            ["The supply-unit focus could not be matched to the active chart context."],
            [],
        )
    mean = float(item.get("mean_annual_change_ft_yr", 0.0))
    if frame.question_goal == "rank" and top and str(top.get("zone")) != str(item.get("zone")):
        direct = (
            f"{item.get('zone')} is not the most stressed supply unit in this dataset by observed monitored decline. "  # noqa: E501
            f"It averages {mean:+.3f} ft/yr from its proxy wells, while {top.get('zone')} is more negative at "  # noqa: E501
            f"{float(top.get('mean_annual_change_ft_yr', 0.0)):+.3f} ft/yr."
        )
    else:
        direct = (
            f"{item.get('zone')} is represented here by {item.get('n_proxy_wells')} USGS monitoring proxy well"  # noqa: E501
            f"{'s' if int(item.get('n_proxy_wells') or 0) != 1 else ''} with a mean observed change of {mean:+.3f} ft/yr."  # noqa: E501
        )
    matters = (
        f"What matters most is that supply-unit stress in this chart is a proxy-based comparison, not a direct utility pumping record. "  # noqa: E501
        f"{item.get('zone')} ranks {item.get('rank_by_decline')} by mean decline among mapped supply units."  # noqa: E501
    )
    evidence = [
        f"Evidence used: proxy wells {', '.join((item.get('proxy_well_names') or [])[:4])}; "
        f"usage {item.get('usage')}; record {pack.get('cohort_period_start')} to {pack.get('cohort_period_end')}."  # noqa: E501
    ]
    limits = [
        "Monitoring wells are proxies for supply units, not direct production-well records.",
        "Proxy matches are based on aquifer unit, depth, and metadata, so utility documentation would still be stronger evidence.",  # noqa: E501
    ]
    return (
        direct,
        matters,
        evidence,
        limits,
        ["identified_supply_unit", "compared_supply_units", "stated_proxy_limits"],
    )


def _cross_well_fallback(
    frame: GroundedFraming, pack: dict[str, Any]
) -> tuple[str, str, list[str], list[str], list[str]]:
    summaries = [_find_well_summary(pack, entity) for entity in frame.focus_entities[:2]]
    summaries = [item for item in summaries if item]
    if len(summaries) < 2:
        strongest_pair = (pack.get("comparison_features") or {}).get("largest_gap_pair") or {}
        left = strongest_pair.get("site_a") or {}
        right = strongest_pair.get("site_b") or {}
        direct = (
            f"The chart-level contrast is strongest between {left.get('name', 'one well')} and "
            f"{right.get('name', 'another well')}."
        )
        matters = "What matters most is the divergence inside the current dataset, not a single blended average."  # noqa: E501
        evidence = []
        limits = ["Cross-well comparison still does not prove the cause of divergence."]
        return direct, matters, evidence, limits, ["identified_cross_well_signal", "stated_limits"]
    left, right = summaries[:2]
    gap = abs(
        float(left.get("annual_change_ft_yr", 0.0)) - float(right.get("annual_change_ft_yr", 0.0))
    )
    direct = (
        f"{left.get('name')} and {right.get('name')} are diverging in this dataset: "
        f"{left.get('name')} is {float(left.get('annual_change_ft_yr', 0.0)):+.3f} ft/yr and "
        f"{right.get('name')} is {float(right.get('annual_change_ft_yr', 0.0)):+.3f} ft/yr."
    )
    matters = f"What matters most is the gap between them ({gap:.3f} ft/yr), because it shows the chart is not moving as one block."  # noqa: E501
    evidence = [
        f"Evidence used: {left.get('aquifer_zone')} versus {right.get('aquifer_zone')}; "
        f"record {pack.get('cohort_period_start')} to {pack.get('cohort_period_end')}."
    ]
    limits = [
        "Divergence alone does not prove hydraulic connection, pumping, or recharge differences.",
        "The comparison should be read as a monitoring contrast inside this chart.",
    ]
    return (
        direct,
        matters,
        evidence,
        limits,
        ["identified_compared_wells", "explained_divergence", "stated_limits"],
    )


def _cohort_fallback(pack: dict[str, Any]) -> tuple[str, str, list[str], list[str], list[str]]:
    comparison = pack.get("comparison_features") or {}
    mean = comparison.get("cohort_mean_annual_change_ft_yr")
    direct = (
        f"Using USGS groundwater monitoring wells from {pack.get('cohort_period_start')} to {pack.get('cohort_period_end')}, "  # noqa: E501
        f"the chart-level signal is {float(mean):+.3f} ft/yr at the cohort mean."
        if mean is not None
        else "The chart provides a cohort-level monitoring summary but not enough data for a mean rate."  # noqa: E501
    )
    matters = "What matters most is whether the wells move together, split into diverging groups, or isolate stress in specific units."  # noqa: E501
    evidence = []
    if comparison.get("fastest_decline"):
        evidence.append(
            f"Evidence used: fastest decline {comparison['fastest_decline'].get('name')} "
            f"at {float(comparison['fastest_decline'].get('annual_change_ft_yr', 0.0)):+.3f} ft/yr."
        )
    limits = [
        "The cohort average is a summary statistic, not a physical well.",
        "The chart alone does not establish cause.",
    ]
    return direct, matters, evidence, limits, ["summarized_dataset", "stated_limits"]


def fallback_from_deterministic(
    question: str,
    pack: dict[str, Any],
) -> GroundedInterpretation:
    """Build a deterministic fallback interpretation when the LLM path is unavailable."""
    frame = derive_question_frame(question, pack)
    if frame.scope_type == "well":
        direct, matters, evidence, limits, moves = _well_fallback(frame, pack)
    elif frame.scope_type == "aquifer":
        direct, matters, evidence, limits, moves = _aquifer_fallback(frame, pack)
    elif frame.scope_type == "supply_unit":
        direct, matters, evidence, limits, moves = _supply_fallback(frame, pack)
    elif frame.scope_type == "cross_well":
        direct, matters, evidence, limits, moves = _cross_well_fallback(frame, pack)
    else:
        direct, matters, evidence, limits, moves = _cohort_fallback(pack)
    return GroundedInterpretation(
        intent=str(pack.get("question_intent") or frame.question_goal or "general"),
        framing=frame,
        reasoning_steps=[
            ReasoningStep(
                step_label="Frame the question",
                observation=f"The evidence pack supports a {frame.scope_type} interpretation with focus on {', '.join(frame.focus_entities) or 'the cohort'}.",  # noqa: E501
                evidence_keys=["entity_catalog", *frame.required_evidence_sections[:2]],
                inference="The answer should stay on the dataset entities named or implied by the question.",  # noqa: E501
                confidence="high",
            ),
            ReasoningStep(
                step_label="Compare within the dataset",
                observation="The pack includes well-level, aquifer-level, and comparison features that show how the focus entity sits relative to the rest of the chart.",  # noqa: E501
                evidence_keys=["comparison_features", "well_summaries", "aquifer_summaries"],
                inference="Interpretation should explain what stands out in this dataset, not drift into generic statewide aquifer language.",  # noqa: E501
                confidence="high",
            ),
        ],
        direct_answer=direct,
        what_matters_most=matters,
        aquifer_summaries=pack.get("aquifer_summaries") or [],
        why_it_matters="This remains a chart-bound, monitoring-based interpretation anchored in the current dataset.",  # noqa: E501
        evidence_used_summary=evidence,
        limitations=limits,
        important_limits=limits[:2],
        follow_up_questions=[],
        numeric_claims=[],
        perspectives=[],
        answer_moves_completed=moves,
        grounding_status="partial",
    )


_RAW_EVIDENCE_SYSTEM_PROMPT = """You are a groundwater monitoring interpreter. Reason step-by-step from  # noqa: E501
the evidence below to answer the question. You must produce your own
interpretation — do not summarize or rephrase pre-written conclusions.

## Rules
- Every numeric value you state must come from the Evidence Pack exactly as given —
  do not round, invent, estimate, or interpolate.
- Cite the USGS well name (e.g., "Lee L-2194") for every well you discuss.
- State the actual data time period from the well records (start date to end date).
- Separate analysis by aquifer unit when multiple aquifers are present.
- If the question asks about causes: state what is observed and what requires
  external evidence (pumping records, rainfall, recharge data, models).
- Acknowledge proxy limitations when comparing monitoring wells to production wells.
- When the data is ambiguous or multiple readings are valid, present them.
- State what the analysis cannot tell you.

Return valid JSON matching the GroundedInterpretation schema."""


_FRAME_ONLY_SYSTEM_PROMPT = """You classify chart-scoped groundwater questions into the right
interpretation frame. Use only the provided dataset entities and return valid
JSON matching the GroundedFraming schema.

Rules:
- Choose the narrowest scope that still answers the question.
- If the question mentions 'this chart' or 'this dataset', keep the frame inside
  the active cohort instead of drifting to generic aquifer knowledge.
- Focus entities must come from the provided wells, aquifers, or supply units.
- required_evidence_sections must name real pack sections only."""


def _reasoning_providers() -> list[tuple[str, str]]:
    """Return Qwen provider/model pairs for grounded reasoning.

    Qwen is the project's only sanctioned synthesis model. Local Ollama Qwen is
    tried first (no API key, no per-call cost), with hosted DashScope Qwen as
    a higher-capability fallback when ``DASHSCOPE_API_KEY`` is configured.
    """
    providers: list[tuple[str, str]] = []
    reasoning_model = os.getenv("GROUNDWATERGPT_REASONING_MODEL", "")

    # Local Qwen via Ollama — preferred (no key, no network egress).
    ollama_model = reasoning_model or os.getenv("SYNTHESIS_MODEL") or os.getenv("LLM_MODEL", "")
    providers.append(("ollama", ollama_model or "qwen3:8b"))

    # Hosted Qwen via DashScope — used when an API key is configured.
    if os.getenv("DASHSCOPE_API_KEY"):
        hosted_model = reasoning_model or os.getenv("GROUNDWATERGPT_INTERPRETER_MODEL", "qwen-plus")
        providers.append(("qwen", hosted_model if "qwen" in hosted_model.lower() else "qwen-plus"))

    return providers


def _is_open_reasoning_model(provider_name: str, model: str) -> bool:
    return provider_name in {"ollama", "qwen"} and bool(
        _OPEN_REASONING_MODEL_RE.search(model or "")
    )


def _thinking_prefix(provider_name: str, model: str) -> str:
    if _is_open_reasoning_model(provider_name, model):
        return "/think\n"
    return ""


def _strip_reasoning_artifacts(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"^\s*/(?:think|no_think)\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _build_frame_prompt(
    question: str,
    pack: dict[str, Any],
    *,
    provider_name: str,
    model: str,
) -> list[tuple[str, str]]:
    frame_hint = derive_question_frame(question, pack)
    payload = {
        "question": question,
        "deterministic_frame_hint": frame_hint.model_dump(),
        "cohort_period": {
            "start": pack.get("cohort_period_start"),
            "end": pack.get("cohort_period_end"),
        },
        "entity_catalog": pack.get("entity_catalog") or {},
        "well_summaries": [
            {
                "name": well.get("name"),
                "site_id": well.get("site_id"),
                "aquifer": well.get("aquifer"),
                "aquifer_zone": well.get("aquifer_zone"),
            }
            for well in (pack.get("well_summaries") or [])[:12]
        ],
        "aquifer_summaries": [
            {
                "aquifer": item.get("aquifer"),
                "zone": item.get("zone"),
                "n_wells": item.get("n_wells"),
            }
            for item in (pack.get("aquifer_summaries") or [])[:8]
        ],
        "supply_unit_summaries": [
            {
                "aquifer": item.get("aquifer"),
                "zone": item.get("zone"),
                "usage": item.get("usage"),
            }
            for item in (pack.get("supply_unit_summaries") or [])[:8]
        ],
        "allowed_sections": [
            "well_summaries",
            "aquifer_summaries",
            "supply_unit_summaries",
            "comparison_features",
            "cross_well",
            "cohort_period_start",
            "cohort_period_end",
            "entity_catalog",
            "supply_interpretation",
        ],
    }
    return [
        ("system", _FRAME_ONLY_SYSTEM_PROMPT),
        (
            "human",
            _thinking_prefix(provider_name, model) + json.dumps(payload, indent=2, default=str),
        ),
    ]


def _build_multistage_reasoning_prompt(
    question: str,
    pack: dict[str, Any],
    hydro_context: dict[str, Any] | None,
    rubric_moves: list[str] | None,
    framing: GroundedFraming,
    *,
    provider_name: str,
    model: str,
) -> list[tuple[str, str]]:
    evidence = _build_reasoning_evidence(pack, hydro_context)
    payload = {
        "question": question,
        "framing": framing.model_dump(),
        "evidence_pack": evidence,
        "required_moves": rubric_moves or [],
        "output_expectations": {
            "direct_answer": "Lead with interpretation and keep it chart-scoped.",
            "what_matters_most": "Name the most important pattern for the framed scope.",
            "why_it_matters": "Hydrogeologic significance without generic boilerplate.",
            "evidence_used_summary": "Specific wells, aquifers, dates, and comparisons used.",
            "limitations": "Chart limits and missing outside evidence.",
        },
    }
    return [
        ("system", _RAW_EVIDENCE_SYSTEM_PROMPT),
        (
            "human",
            _thinking_prefix(provider_name, model) + json.dumps(payload, indent=2, default=str),
        ),
    ]


def _invoke_json_schema(
    llm: Any,
    schema: type[BaseModel],
    messages: list[tuple[str, str]],
) -> BaseModel | None:
    if hasattr(llm, "with_structured_output"):
        try:
            structured_llm = llm.with_structured_output(schema)
            raw = structured_llm.invoke(messages)
            return raw if isinstance(raw, schema) else schema(**raw)
        except Exception as exc:
            logger.debug("Structured output failed for %s: %s", schema.__name__, exc)

    raw_response = llm.invoke(messages)
    content = raw_response.content if hasattr(raw_response, "content") else str(raw_response)
    parsed = _parse_json_response(_strip_reasoning_artifacts(content))
    if not parsed:
        return None
    return schema(**parsed)


def _build_raw_evidence_prompt(
    question: str,
    pack: dict[str, Any],
    hydro_context: dict[str, Any] | None,
    rubric_moves: list[str] | None,
) -> list[tuple[str, str]]:
    """Build prompt with raw evidence (no pre-computed answers)."""
    evidence = _build_reasoning_evidence(pack, hydro_context)

    parts = [
        "## Evidence Pack\n" + json.dumps(evidence, indent=2, default=str),
    ]
    if rubric_moves:
        parts.append(
            "\n## Required Analytical Moves\n"
            "Your interpretation should address each of these:\n"
            + "\n".join(f"- {move}" for move in rubric_moves)
        )
    parts.append(f"\n## Question\n{question}")

    return [
        ("system", _RAW_EVIDENCE_SYSTEM_PROMPT),
        ("human", "\n\n".join(parts)),
    ]


def _parse_json_response(text: str) -> dict[str, Any] | None:
    """Extract JSON from LLM text response (may have markdown fences)."""
    text = _strip_reasoning_artifacts(text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def invoke_grounded_reasoning(
    question: str,
    pack: dict[str, Any],
    *,
    rubric: dict[str, Any] | None = None,
    hydro_context: dict[str, Any] | None = None,
    rubric_moves: list[str] | None = None,
) -> GroundedInterpretation | None:
    """Invoke grounded reasoning with raw evidence.

    Tries the Qwen provider chain: local Ollama Qwen first, hosted DashScope Qwen if configured.
    All providers receive raw evidence — the LLM must reason, not rephrase.
    Open reasoning models (qwen3, deepseek-r1) use a two-stage framing+reasoning
    pipeline; API models use a single raw-evidence prompt.
    """
    if not pack.get("site_ids") and not pack.get("sites"):
        return None

    if rubric_moves is None and rubric:
        rubric_moves = rubric.get("required_moves", [])

    # Auto-load hydro context from pack county metadata
    if hydro_context is None:
        for site in pack.get("sites") or pack.get("wells") or []:
            if str(site.get("county", "")).lower() == "lee":
                hydro_context = load_hydro_context("estero")
                break

    for provider_name, model in _reasoning_providers():
        try:
            from src.agent.llm_factory import LLMProvider, get_llm

            llm_kwargs: dict[str, Any] = {}
            if provider_name == "ollama":
                llm_kwargs["format"] = "json"
            llm = get_llm(
                provider=LLMProvider(provider_name),
                model=model,
                temperature=0,
                **llm_kwargs,
            )

            use_multistage = _is_open_reasoning_model(provider_name, model)

            if use_multistage:
                framing = _invoke_json_schema(
                    llm,
                    GroundedFraming,
                    _build_frame_prompt(question, pack, provider_name=provider_name, model=model),
                ) or derive_question_frame(question, pack)
                messages = _build_multistage_reasoning_prompt(
                    question,
                    pack,
                    hydro_context,
                    rubric_moves,
                    framing,
                    provider_name=provider_name,
                    model=model,
                )
            else:
                messages = _build_raw_evidence_prompt(
                    question,
                    pack,
                    hydro_context,
                    rubric_moves,
                )

            interpretation = _invoke_json_schema(llm, GroundedInterpretation, messages)
            if interpretation is None:
                continue

            if use_multistage and not interpretation.framing.scope_type:
                interpretation.framing = framing

            interpretation.llm_provider = provider_name
            interpretation.llm_model = model

            # Validate — flags are informational, not rejection criteria.
            # The deterministic validators downstream still protect the answer.
            flags = validate_against_pack(interpretation, pack)
            flags.extend(
                _check_success_criteria(
                    interpretation,
                    {**pack, "interpretation_rubric": rubric or {}},
                )
            )
            if flags:
                logger.info(
                    "Grounded reasoning via %s/%s: %d steps, flags: %s",
                    provider_name,
                    model,
                    len(interpretation.reasoning_steps),
                    flags,
                )
            else:
                logger.info(
                    "Grounded reasoning via %s/%s: %d steps, clean",
                    provider_name,
                    model,
                    len(interpretation.reasoning_steps),
                )
            return interpretation

        except Exception as exc:
            logger.debug("Grounded reasoning unavailable via %s/%s: %s", provider_name, model, exc)
            continue
    return None


# ---------------------------------------------------------------------------
# Chat-path entry point (replaces Ollama httpx in _site_analysis.py)
# ---------------------------------------------------------------------------


def invoke_grounded_synthesis(
    question: str,
    site_computed: list[dict[str, Any]],
    aquifer_summaries: list[dict[str, Any]],
    cross_well: dict[str, Any],
    supply_info: dict[str, Any] | None,
    location_name: str,
) -> GroundedInterpretation | None:
    """Entry point for the chat path.

    Assembles a minimal evidence pack from pre-computed site data and
    calls the grounded reasoning module.  Replaces the Ollama httpx block
    in ``_site_research_fallback()``.
    """
    pack = _build_chat_synthesis_pack(
        site_computed=site_computed,
        aquifer_summaries=aquifer_summaries,
        cross_well=cross_well,
        supply_info=supply_info,
    )

    hydro_context = load_hydro_context(location_name)

    # Detect intent for rubric moves
    intent = _detect_intent_simple(question)
    from api.routes._chart_interpreter import INTERPRETATION_RUBRIC_PATH

    rubric_moves: list[str] = []
    try:
        rubric_data = json.loads(INTERPRETATION_RUBRIC_PATH.read_text())
        rubric_moves = rubric_data.get("intents", {}).get(intent, {}).get("required_moves", [])
    except Exception:
        pass

    return invoke_grounded_reasoning(
        question,
        pack,
        hydro_context=hydro_context,
        rubric_moves=rubric_moves,
    )


def _detect_intent_simple(question: str) -> str:
    """Lightweight intent detection for rubric lookup."""
    text = question.lower()
    if re.search(
        r"\b(supply|water source|drinking water|municipal|where does.*get.*water)\b", text
    ):
        return "general"
    if re.search(r"\b(shallow|deep|confined|unconfined|diverge|aquifer wells?)\b", text):
        return "shallow_deep_comparison"
    if re.search(r"\b(fastest|which well|steepest|largest change)\b", text):
        return "fastest_changing"
    if re.search(r"\b(risk|screening|concern)\b", text):
        return "risk_explanation"
    if re.search(r"\b(cohort|average|mean annual)\b", text):
        return "cohort_meaning"
    if re.search(r"\b(why|cause|because|explain|pumping|recharge)\b", text):
        return "cause_or_why"
    if re.search(r"\b(season|wet|dry|summer|winter)\b", text):
        return "seasonal"
    if re.search(r"\b(shift|change\s*point|turning point|got worse)\b", text):
        return "trend_change"
    return "general"


def _normalize_chat_site(site: dict[str, Any]) -> dict[str, Any]:
    seasonal = {
        "seasonal_amplitude_ft": site.get("seasonal_amplitude_ft"),
        "wet_season_mean": site.get("wet_season_mean_ft"),
        "dry_season_mean": site.get("dry_season_mean_ft"),
    }
    return {
        **site,
        "aquifer": site.get("aquifer") or site.get("aq_label"),
        "aquifer_zone": site.get("aquifer_zone") or site.get("aq_zone") or site.get("zone"),
        "annual_change_ft_yr": site.get("annual_change_ft_yr", site.get("annual_change")),
        "record_years": site.get("record_years", site.get("years")),
        "trend_label": site.get("trend_label") or site.get("trend"),
        "seasonal": seasonal,
    }


def _build_chat_synthesis_pack(
    *,
    site_computed: list[dict[str, Any]],
    aquifer_summaries: list[dict[str, Any]],
    cross_well: dict[str, Any],
    supply_info: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_sites = [_normalize_chat_site(site) for site in site_computed]
    site_ids = [site.get("site_id") for site in normalized_sites if site.get("site_id")]
    well_summaries = [
        {
            "name": site.get("name"),
            "site_id": site.get("site_id"),
            "borehole_code": site.get("name"),
            "aquifer": site.get("aquifer"),
            "aquifer_zone": site.get("aquifer_zone"),
            "annual_change_ft_yr": site.get("annual_change_ft_yr"),
            "net_change_ft": site.get("net_change_ft"),
            "trend_label": site.get("trend_label"),
            "record_start": site.get("record_start"),
            "record_end": site.get("record_end"),
            "record_years": site.get("record_years"),
            "well_depth_ft": site.get("well_depth_ft"),
            "lat": site.get("lat"),
            "lng": site.get("lng"),
            "confined": site.get("confined"),
        }
        for site in normalized_sites
    ]

    supply_interpretation = None
    supply_unit_summaries: list[dict[str, Any]] = []
    if supply_info:
        supply_units = supply_info.get("supply_aquifers") or []
        supply_interpretation = {
            "municipality": supply_info.get("municipality"),
            "utility": supply_info.get("utility"),
            "confidence": supply_info.get("data_confidence"),
            "supply_units": supply_units,
            "known_risks": supply_info.get("known_risks") or [],
        }
        supply_unit_summaries = [
            {
                "aquifer": unit.get("aquifer"),
                "zone": unit.get("zone"),
                "usage": unit.get("usage"),
                "depth_range_ft": unit.get("depth_range_ft"),
                "proxy_wells": unit.get("proxy_wells") or [],
            }
            for unit in supply_units
        ]

    starts = [site.get("record_start") for site in normalized_sites if site.get("record_start")]
    ends = [site.get("record_end") for site in normalized_sites if site.get("record_end")]
    entity_catalog = {
        "well_names": [site.get("name") for site in normalized_sites if site.get("name")],
        "aquifer_labels": [
            summary.get("zone") or summary.get("aquifer")
            for summary in aquifer_summaries
            if summary.get("zone") or summary.get("aquifer")
        ],
        "supply_units": [
            summary.get("zone") or summary.get("aquifer")
            for summary in supply_unit_summaries
            if summary.get("zone") or summary.get("aquifer")
        ],
    }

    return {
        "sites": normalized_sites,
        "wells": normalized_sites,
        "site_ids": site_ids,
        "cross_well": cross_well,
        "comparison_features": cross_well,
        "aquifer_summaries": aquifer_summaries,
        "well_summaries": well_summaries,
        "supply_info": supply_info,
        "supply_interpretation": supply_interpretation,
        "supply_unit_summaries": supply_unit_summaries,
        "entity_catalog": entity_catalog,
        "cohort_period_start": min(starts) if starts else None,
        "cohort_period_end": max(ends) if ends else None,
    }
