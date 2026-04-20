"""Grounded chart-context interpreter for conversational follow-ups."""

from __future__ import annotations

import inspect
import json
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from api.routes._citation import (
    _build_citation_integrity,
    _build_citation_summary,
    _build_claim_verdict_summary,
    _build_claim_verdicts,
    _build_section_confidence_from_claims,
)
from api.routes._detection import (
    _SUPPLY_QUERY_RE,
    _WATER_SUPPLY_SOURCES,
    ESTERO_REFERENCE_LAT,
    ESTERO_REFERENCE_LNG,
    _bearing_label,
    _build_wells_payload,
    _distance_miles,
    _load_site_timeseries,
    _usgs_site_url,
)
from api.routes._evidence_guided_ai import build_evidence_guided_progression
from api.routes._grounded_reasoning import derive_question_frame
from api.routes._grounded_reasoning import grounded_reasoning_enabled as _grounded_reasoning_enabled
from api.routes._grounded_reasoning import (
    invoke_grounded_reasoning,
    invoke_with_llm_timeout,
    llm_timeout_seconds,
)
from api.routes._site_analysis import (
    _build_chart_explainability,
    _build_chart_insights,
    _build_supply_interpretation,
    _cross_well_analysis,
    _seasonal_decomposition,
)
from api.site_metadata import SITE_METADATA

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HYDRO_INTERPRETATION_BANK_PATH = PROJECT_ROOT / "config" / "interpretation_answer_bank.json"
INTERPRETATION_RUBRIC_PATH = PROJECT_ROOT / "config" / "interpretation_rubric.json"
ESTERO_HYDRO_CONTEXT_PATH = PROJECT_ROOT / "config" / "estero_hydrogeology_context.json"
TRUSTED_RAG_LEVELS = {"verified", "primary", "trusted", "curated"}

INTERPRETER_PROMPT_HEAD = """You are a groundwater chart interpreter.

Use only the supplied EvidencePack. Quote numeric values only when they appear
in the EvidencePack. Every factual sentence must be anchored to a citation URL
or a deterministic chart metric. If a user asks for a cause, say the available
record does not prove causation unless pumping, rainfall, recharge, and model
context are supplied. Do not invent measurements, forecasts, or site metadata.

Example trend answer:
Question: which well is changing fastest?
Answer: The fastest decline is the well with the most negative annual_change_ft_yr
in the EvidencePack. Cite the USGS URL and include a NumericClaim with unit ft/yr.

Example guardrail answer:
Question: is this caused by pumping?
Answer: The chart shows an observed trend, but the available record does not
prove pumping caused it. Pumping attribution would require pumping records,
rainfall/recharge data, and groundwater-flow model context.
"""

HEDGE_PHRASES = (
    "does not prove",
    "available record does not show",
    "cannot attribute",
    "would require",
    "not enough evidence",
)

EXPLAINER_ECHO_PHRASES = (
    "this chart connects",
    "context site ids include",
    "key deterministic rates are",
    "highlighted wells mark",
)

EXPLAINER_LABEL_PHRASES = (
    "question intent",
    "direct answer",
    "supporting evidence",
    "meaning brief",
    "possible drivers",
    "evidence needed",
    "confidence note",
    "numeric claims",
    "chart context",
    "site ids",
)

LEARNER_TERM_LIBRARY = (
    {
        "term": "cohort average",
        "triggers": ("cohort average", "cohort mean", "mean annual change", "group summary"),
        "plain_definition": (
            "A cohort average is the mean trend across the selected monitored wells, not a real "
            "physical well."
        ),
        "why_it_matters_here": (
            "It helps you see the group-level direction before you inspect which individual wells "
            "are pulling the average up or down."
        ),
    },
    {
        "term": "screening risk",
        "triggers": ("screening risk", "risk level", "high risk", "moderate risk"),
        "plain_definition": (
            "Screening risk is a triage label that tells you the chart is worth follow-up review."
        ),
        "why_it_matters_here": (
            "It helps prioritize where to look next, but it is not a diagnosis or a forecast."
        ),
    },
    {
        "term": "drawdown",
        "triggers": ("drawdown",),
        "plain_definition": (
            "Drawdown means water levels or pressure head are lower than before in the monitored "
            "aquifer."
        ),
        "why_it_matters_here": (
            "A declining line can be consistent with drawdown, but the chart alone does not tell "
            "you what caused it."
        ),
    },
    {
        "term": "confined aquifer",
        "triggers": ("confined aquifer", "confined units", "pressure-head change"),
        "plain_definition": (
            "A confined aquifer is a deeper water-bearing layer under confining material, so water "
            "levels often behave like pressure changes rather than a shallow water table."
        ),
        "why_it_matters_here": (
            "That matters because a deeper confined well can respond differently from a shallow "
            "unconfined well even in the same area."
        ),
    },
    {
        "term": "depth-to-water",
        "triggers": ("depth-to-water", "feet below land surface", "ft_bls", "depth to water"),
        "plain_definition": (
            "Depth-to-water is how far below land surface the measured water level sits."
        ),
        "why_it_matters_here": (
            "Smaller values mean shallower groundwater, while larger values mean the water level is "  # noqa: E501
            "deeper."
        ),
    },
    {
        "term": "trend line",
        "triggers": ("trend line", "annual change", "annual rate", "ft/yr"),
        "plain_definition": (
            "A trend line is a smoothed summary of the overall direction of the record."
        ),
        "why_it_matters_here": (
            "It helps compare wells quickly, but it compresses wet, dry, and noisy periods into one "  # noqa: E501
            "screening rate."
        ),
    },
)


@lru_cache(maxsize=1)
def _load_hydro_interpretation_bank() -> list[dict[str, Any]]:
    """Load curated hydrogeology concepts used as fast local RAG fallback."""
    try:
        with HYDRO_INTERPRETATION_BANK_PATH.open() as fh:
            payload = json.load(fh)
    except Exception as exc:
        logger.debug("Hydro interpretation bank unavailable: %s", exc)
        return []
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


@lru_cache(maxsize=1)
def _load_interpretation_rubric() -> dict[str, Any]:
    """Load reusable answer-quality rules for interpretation intents."""
    try:
        with INTERPRETATION_RUBRIC_PATH.open() as fh:
            payload = json.load(fh)
    except Exception as exc:
        logger.debug("Interpretation rubric unavailable: %s", exc)
        return {"schema_version": "interpretation_rubric_v1", "intents": {}}
    if isinstance(payload, dict):
        return payload
    return {"schema_version": "interpretation_rubric_v1", "intents": {}}


def _rubric_for_intent(intent: str) -> dict[str, Any]:
    rubric = _load_interpretation_rubric()
    intents = rubric.get("intents") if isinstance(rubric, dict) else {}
    entry = intents.get(intent) if isinstance(intents, dict) else None
    return entry if isinstance(entry, dict) else {}


@lru_cache(maxsize=1)
def _load_estero_hydro_context() -> dict[str, Any]:
    try:
        with ESTERO_HYDRO_CONTEXT_PATH.open() as fh:
            payload = json.load(fh)
    except Exception as exc:
        logger.debug("Estero hydro context unavailable: %s", exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _expose_interpretation_rubric() -> bool:
    return os.getenv("GROUNDWATERGPT_EXPOSE_INTERPRETATION_RUBRIC", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _unique_terms(values: list[Any], limit: int = 28) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        terms.append(text)
        seen.add(key)
        if len(terms) >= limit:
            break
    return terms


def _series_period(series: Any) -> tuple[str | None, str | None]:
    if series is None or getattr(series, "empty", True):
        return None, None
    if "datetime" not in series:
        return None, None
    try:
        start = series["datetime"].min()
        end = series["datetime"].max()
        return str(start.date()), str(end.date())
    except Exception:
        return None, None


def _borehole_code(name: str) -> str:
    match = re.search(r"\b([A-Z]+-\d+[A-Z]?)\b", str(name or ""))
    return match.group(1) if match else ""


def _well_reference_tokens(name: str) -> set[str]:
    text = str(name or "").strip()
    if not text:
        return set()
    tokens = {text.lower()}
    borehole = _borehole_code(text)
    if borehole:
        tokens.add(borehole.lower())
    parts = re.findall(r"\b[A-Z]+-\d+[A-Z]?\b", text, flags=re.I)
    tokens.update(part.lower() for part in parts if part)
    return {token for token in tokens if token}


def _claim_reference_tokens(label: str) -> set[str]:
    tokens = set(_well_reference_tokens(label))
    normalized = re.sub(r"[^a-z0-9]+", " ", str(label or "").lower()).strip()
    if normalized:
        tokens.add(normalized)
        for part in normalized.split():
            if len(part) >= 4:
                tokens.add(part)
    return {token for token in tokens if token}


def _context_location_name(question: str, chart_context: dict[str, Any] | None) -> str:
    title = str((chart_context or {}).get("chart_id") or "").lower()
    summary_title = str(
        ((chart_context or {}).get("summary_metrics") or {}).get("title") or ""
    ).lower()
    text = f"{question} {title} {summary_title}".lower()
    for key, supply_info in (_WATER_SUPPLY_SOURCES or {}).items():
        municipality = str((supply_info or {}).get("municipality") or "").lower()
        utility = str((supply_info or {}).get("utility") or "").lower()
        aliases = {
            str(key).replace("_", " ").lower(),
            municipality,
            utility,
        }
        aliases = {alias for alias in aliases if alias}
        if any(alias in text for alias in aliases):
            return str(key)
    if "estero" in text:
        return "estero"
    if "lee county" in text or re.search(r"\blee\b", text):
        return "lee"
    return ""


def _should_attach_estero_context(
    question: str,
    chart_context: dict[str, Any] | None,
    sites: list[dict[str, Any]],
) -> bool:
    if _context_location_name(question, chart_context) in {"estero", "lee"}:
        return True
    counties = {str(site.get("county", "")).lower() for site in sites}
    return bool(counties) and counties == {"lee"}


def _location_label_from_context(
    question: str,
    chart_context: dict[str, Any] | None,
    pack: dict[str, Any],
) -> str:
    explicit = _context_location_name(question, chart_context)
    if explicit == "estero":
        return "Estero"
    if explicit == "lee":
        return "Lee County"
    title = str((chart_context or {}).get("chart_id") or "").strip()
    if title:
        return title.replace("Monthly Groundwater Levels", "").strip(" -—")
    counties = {
        str(well.get("county")).strip()
        for well in pack.get("wells", []) or []
        if well.get("county")
    }
    if len(counties) == 1:
        return next(iter(counties))
    return "Active chart cohort"


def _site_computed_entries(
    pack: dict[str, Any],
    *,
    ref_lat: float | None = None,
    ref_lng: float | None = None,
) -> list[dict[str, Any]]:
    metrics_by_site = {
        str(metric.get("site_id")): metric
        for metric in (pack.get("cross_well") or {}).get("per_site_metrics", []) or []
        if metric.get("site_id")
    }
    entries: list[dict[str, Any]] = []
    for well in pack.get("wells", []) or []:
        site_id = str(well.get("site_id") or "")
        metric = metrics_by_site.get(site_id, {})
        lat = well.get("lat")
        lng = well.get("lng")
        distance_from_reference = None
        if ref_lat is not None and ref_lng is not None and lat is not None and lng is not None:
            miles = _distance_miles(ref_lat, ref_lng, float(lat), float(lng))
            bearing = _bearing_label(ref_lat, ref_lng, float(lat), float(lng))
            distance_from_reference = f"{miles:.1f} mi {bearing}"
        entries.append(
            {
                "site_id": site_id,
                "name": well.get("name"),
                "aq_label": well.get("aquifer"),
                "aq_zone": well.get("aquifer_zone"),
                "well_depth_ft": well.get("well_depth_ft"),
                "confined": bool(well.get("confined")),
                "trend": metric.get("trend"),
                "annual_change": float(metric.get("annual_change_ft_yr", 0.0)),
                "net_change_ft": metric.get("net_change_ft"),
                "lat": lat,
                "lng": lng,
                "distance_from_reference": distance_from_reference,
                "seasonal": next(
                    (
                        site.get("seasonal")
                        for site in pack.get("sites", []) or []
                        if str(site.get("site_id")) == site_id
                    ),
                    {},
                ),
                "years": next(
                    (
                        site.get("record_years")
                        for site in pack.get("sites", []) or []
                        if str(site.get("site_id")) == site_id
                    ),
                    None,
                ),
            }
        )
    return entries


def _aquifer_summaries_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    entries = _site_computed_entries(pack)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        key = str(entry.get("aq_zone") or entry.get("aq_label") or "Unknown")
        grouped.setdefault(key, []).append(entry)

    def _sort_key(item: tuple[str, list[dict[str, Any]]]) -> float:
        depths = [
            float(entry["well_depth_ft"])
            for entry in item[1]
            if entry.get("well_depth_ft") is not None
        ]
        return min(depths) if depths else 9999.0

    summaries: list[dict[str, Any]] = []
    for zone, zone_entries in sorted(grouped.items(), key=_sort_key):
        rates = [float(entry.get("annual_change", 0.0)) for entry in zone_entries]
        mean_rate = sum(rates) / len(rates) if rates else 0.0
        summaries.append(
            {
                "aquifer": zone_entries[0].get("aq_label") or zone,
                "zone": zone,
                "n_wells": len(zone_entries),
                "mean_annual_change": round(mean_rate, 4),
                "n_falling": sum(1 for entry in zone_entries if entry.get("trend") == "falling"),
                "n_stable": sum(1 for entry in zone_entries if entry.get("trend") == "stable"),
                "n_rising": sum(1 for entry in zone_entries if entry.get("trend") == "rising"),
                "well_names": [
                    str(entry.get("name")) for entry in zone_entries if entry.get("name")
                ],
            }
        )
    sorted_summaries = sorted(
        summaries,
        key=lambda item: float(item.get("mean_annual_change", 0.0)),
    )
    for idx, summary in enumerate(sorted_summaries, start=1):
        summary["rank_by_decline"] = idx
    return sorted_summaries


def _well_summaries_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    cross_well = pack.get("cross_well") or {}
    cohort_mean = cross_well.get("mean_annual_change_ft_yr")
    summaries = []
    for entry in _site_computed_entries(pack):
        summary = {
            "site_id": entry.get("site_id"),
            "name": entry.get("name"),
            "borehole_code": next(
                (
                    well.get("borehole_code")
                    for well in pack.get("wells", []) or []
                    if str(well.get("site_id")) == str(entry.get("site_id"))
                ),
                "",
            ),
            "aquifer": entry.get("aq_label"),
            "aquifer_zone": entry.get("aq_zone"),
            "confined": bool(entry.get("confined")),
            "trend": entry.get("trend"),
            "annual_change_ft_yr": entry.get("annual_change"),
            "net_change_ft": entry.get("net_change_ft"),
            "lat": entry.get("lat"),
            "lng": entry.get("lng"),
            "record_start": next(
                (
                    site.get("record_start")
                    for site in pack.get("sites", []) or []
                    if str(site.get("site_id")) == str(entry.get("site_id"))
                ),
                None,
            ),
            "record_end": next(
                (
                    site.get("record_end")
                    for site in pack.get("sites", []) or []
                    if str(site.get("site_id")) == str(entry.get("site_id"))
                ),
                None,
            ),
            "record_years": entry.get("years"),
        }
        if cohort_mean is not None and entry.get("annual_change") is not None:
            summary["deviation_from_cohort_mean_ft_yr"] = round(
                float(entry.get("annual_change")) - float(cohort_mean),
                4,
            )
        summaries.append(summary)
    summaries.sort(key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
    for idx, summary in enumerate(summaries, start=1):
        summary["rank_by_decline"] = idx
    rising_rank = sorted(
        summaries,
        key=lambda item: float(item.get("annual_change_ft_yr", 0.0)),
        reverse=True,
    )
    for idx, summary in enumerate(rising_rank, start=1):
        summary["rank_by_rise"] = idx
    return summaries


def _supply_unit_summaries_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    supply = pack.get("supply_interpretation") or {}
    units = []
    for item in supply.get("supply_units", []) or []:
        proxies = item.get("proxy_wells") or []
        trend_summary = item.get("trend_summary") or {}
        rates = []
        for proxy in proxies:
            try:
                rates.append(float(proxy.get("annual_change_ft_yr")))
            except (TypeError, ValueError):
                continue
        mean_rate = trend_summary.get("mean_annual_change")
        try:
            mean_value = (
                float(mean_rate)
                if mean_rate is not None
                else (sum(rates) / len(rates) if rates else None)
            )
        except (TypeError, ValueError):
            mean_value = None
        summary = {
            "aquifer": item.get("aquifer"),
            "zone": item.get("zone"),
            "usage": item.get("usage"),
            "n_proxy_wells": len(proxies),
            "proxy_well_names": [proxy.get("name") for proxy in proxies if proxy.get("name")],
            "mean_annual_change_ft_yr": round(mean_value, 4) if mean_value is not None else None,
            "n_falling": trend_summary.get(
                "n_falling", sum(1 for proxy in proxies if proxy.get("trend") == "falling")
            ),
            "n_stable": trend_summary.get(
                "n_stable", sum(1 for proxy in proxies if proxy.get("trend") == "stable")
            ),
            "n_rising": trend_summary.get(
                "n_rising", sum(1 for proxy in proxies if proxy.get("trend") == "rising")
            ),
            "notes": item.get("notes"),
            "limitations": [
                proxy.get("limitations") for proxy in proxies if proxy.get("limitations")
            ][:2],
        }
        units.append(summary)
    units = [item for item in units if item.get("zone") or item.get("aquifer")]
    units.sort(
        key=lambda item: (
            float(item.get("mean_annual_change_ft_yr"))
            if item.get("mean_annual_change_ft_yr") is not None
            else 9999.0
        )
    )
    for idx, summary in enumerate(units, start=1):
        summary["rank_by_decline"] = idx
    return units


def _comparison_features_from_pack(pack: dict[str, Any]) -> dict[str, Any]:
    cross_well = pack.get("cross_well") or {}
    per_site = (cross_well.get("per_site_metrics") or [])[:]
    fastest_decline = (
        min(per_site, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
        if per_site
        else None
    )
    strongest_rise = (
        max(per_site, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
        if per_site
        else None
    )
    largest_gap_pair = None
    divergent_pairs = cross_well.get("divergent_pairs") or []
    if divergent_pairs:
        largest_gap_pair = max(
            divergent_pairs,
            key=lambda item: float(item.get("divergence_magnitude", 0.0)),
        )
    aquifers = pack.get("aquifer_summaries") or []
    supply_units = pack.get("supply_unit_summaries") or []
    return {
        "cohort_mean_annual_change_ft_yr": cross_well.get("mean_annual_change_ft_yr"),
        "risk_level": cross_well.get("risk_level"),
        "fastest_decline": fastest_decline,
        "strongest_rise": strongest_rise,
        "largest_gap_pair": largest_gap_pair,
        "most_negative_aquifer": aquifers[0] if aquifers else None,
        "most_positive_aquifer": aquifers[-1] if aquifers else None,
        "most_negative_supply_unit": supply_units[0] if supply_units else None,
        "most_positive_supply_unit": supply_units[-1] if supply_units else None,
    }


def _entity_catalog_from_pack(pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "wells": [
            {
                "label": item.get("name"),
                "site_id": item.get("site_id"),
                "borehole_code": item.get("borehole_code"),
                "aquifer": item.get("aquifer"),
                "zone": item.get("aquifer_zone"),
            }
            for item in pack.get("well_summaries") or []
        ],
        "aquifers": [
            {
                "label": item.get("zone") or item.get("aquifer"),
                "aquifer": item.get("aquifer"),
                "zone": item.get("zone"),
            }
            for item in pack.get("aquifer_summaries") or []
        ],
        "supply_units": [
            {
                "label": item.get("zone") or item.get("aquifer"),
                "aquifer": item.get("aquifer"),
                "zone": item.get("zone"),
                "usage": item.get("usage"),
            }
            for item in pack.get("supply_unit_summaries") or []
        ],
    }


def _supply_interpretation_from_pack(
    question: str,
    chart_context: dict[str, Any] | None,
    pack: dict[str, Any],
) -> dict[str, Any] | None:
    location_key = _context_location_name(question, chart_context)
    supply_info = _WATER_SUPPLY_SOURCES.get(location_key) if location_key else None
    supply_hint = bool(
        _SUPPLY_QUERY_RE.search(question)
        or re.search(
            r"\b(supply unit|proxy well|production well|utility|municipal|asr|reverse osmosis|ro)\b",  # noqa: E501
            question,
            re.I,
        )
    )
    if not supply_info and location_key == "lee":
        supply_info = _WATER_SUPPLY_SOURCES.get("estero")
    if not supply_info and "estero" in question.lower():
        supply_info = _WATER_SUPPLY_SOURCES.get("estero")
    if not supply_info:
        return None
    if not supply_hint:
        focus_text = question.lower()
        matched_supply_term = any(
            str(unit.get("zone", "")).lower() in focus_text
            or str(unit.get("aquifer", "")).lower() in focus_text
            for unit in supply_info.get("supply_aquifers", [])
        )
        if not matched_supply_term:
            return None

    entries = _site_computed_entries(
        pack,
        ref_lat=ESTERO_REFERENCE_LAT,
        ref_lng=ESTERO_REFERENCE_LNG,
    )
    aquifer_summaries = pack.get("aquifer_summaries") or _aquifer_summaries_from_pack(pack)
    return _build_supply_interpretation(
        supply_info=supply_info,
        site_computed=entries,
        aquifer_summaries=aquifer_summaries,
        ref_lat=ESTERO_REFERENCE_LAT,
        ref_lng=ESTERO_REFERENCE_LNG,
    )


def _build_location_hydro_context(
    question: str,
    chart_context: dict[str, Any] | None,
    pack: dict[str, Any],
) -> dict[str, Any]:
    label = _location_label_from_context(question, chart_context, pack)
    counties = sorted(
        {
            str(well.get("county")).strip()
            for well in pack.get("wells", []) or []
            if well.get("county")
        }
    )
    aquifer_units = []
    for summary in pack.get("aquifer_summaries", []) or []:
        matching_wells = [
            well
            for well in pack.get("wells", []) or []
            if str(well.get("aquifer_zone") or well.get("aquifer") or "").lower()
            == str(summary.get("zone") or summary.get("aquifer") or "").lower()
        ]
        aquifer_units.append(
            {
                "aquifer": summary.get("aquifer"),
                "zone": summary.get("zone"),
                "n_wells": summary.get("n_wells"),
                "mean_annual_change_ft_yr": summary.get("mean_annual_change"),
                "well_names": [well.get("name") for well in matching_wells[:6] if well.get("name")],
                "depths_ft": [
                    well.get("well_depth_ft")
                    for well in matching_wells
                    if well.get("well_depth_ft") is not None
                ][:6],
                "confined": sorted(
                    {
                        "confined" if well.get("confined") else "unconfined"
                        for well in matching_wells
                    }
                ),
            }
        )
    context = {
        "schema_version": "location_hydro_context_v1",
        "location_name": label,
        "monitoring_basis": "USGS groundwater monitoring wells",
        "counties": counties,
        "cohort_period": {
            "start": pack.get("cohort_period_start"),
            "end": pack.get("cohort_period_end"),
        },
        "aquifer_units": aquifer_units,
        "supply_context": pack.get("supply_interpretation"),
        "proxy_limitations": [
            "Monitoring wells are proxies for aquifer behavior and are not direct production-well allocation records.",  # noqa: E501
            "Aquifer-zone matches support screening interpretation, but production-well construction records would be stronger evidence.",  # noqa: E501
        ],
    }
    if _should_attach_estero_context(question, chart_context, pack.get("sites", []) or []):
        supplemental = _load_estero_hydro_context()
        if supplemental:
            context["supplemental_location_context"] = supplemental
    return context


def _trend_terms(cross_well: dict[str, Any] | None) -> list[str]:
    if not isinstance(cross_well, dict):
        return []
    terms: list[str] = []
    mean = cross_well.get("mean_annual_change_ft_yr")
    try:
        mean_value = float(mean)
    except (TypeError, ValueError):
        mean_value = 0.0
    if mean_value < -0.02:
        terms.extend(["declining groundwater levels", "drawdown", "negative trend"])
    elif mean_value > 0.02:
        terms.extend(["rising groundwater levels", "recovery", "positive trend"])
    trend_distribution = cross_well.get("trend_distribution") or {}
    if isinstance(trend_distribution, dict):
        if trend_distribution.get("decreasing") or trend_distribution.get("falling"):
            terms.extend(["declining wells", "pumping stress"])
        if trend_distribution.get("increasing") or trend_distribution.get("rising"):
            terms.append("rising wells")
    risk = str(cross_well.get("risk_level") or "").strip()
    if risk:
        terms.append(f"{risk} screening risk")
    return terms


def _context_terms_from_sites(
    sites: list[dict[str, Any]] | None,
    cross_well: dict[str, Any] | None,
    turn_history: list[dict[str, Any]] | None,
) -> list[str]:
    values: list[Any] = []
    for site in sites or []:
        values.extend(
            [
                site.get("name"),
                site.get("site_id"),
                site.get("aquifer"),
                site.get("aquifer_type"),
                site.get("aquifer_zone"),
                site.get("aquifer_description"),
                site.get("county"),
                "confined aquifer" if site.get("confined") else "unconfined aquifer",
            ]
        )
    for metric in (cross_well or {}).get("per_site_metrics", []) or []:
        values.extend([metric.get("name"), metric.get("aquifer"), metric.get("county")])
    values.extend(_trend_terms(cross_well))
    for turn in list(turn_history or [])[-4:]:
        if not isinstance(turn, dict):
            continue
        values.extend([turn.get("aquifer"), turn.get("cohort_risk_level")])
        for well in turn.get("wells") or []:
            if isinstance(well, dict):
                values.extend([well.get("name"), well.get("aquifer"), well.get("site_id")])
    return _unique_terms(values)


def _build_enriched_rag_query(
    question: str,
    sites: list[dict[str, Any]] | None = None,
    cross_well: dict[str, Any] | None = None,
    turn_history: list[dict[str, Any]] | None = None,
) -> str:
    """Build a retrieval query grounded in the active chart context."""
    terms = _context_terms_from_sites(sites, cross_well, turn_history)
    query_parts = _unique_terms([question, *terms, "groundwater interpretation"], limit=32)
    return " ".join(query_parts)


def _score_hydro_bank_entry(entry: dict[str, Any], search_text: str) -> int:
    score = 0
    for term in entry.get("trigger_terms") or []:
        term_text = str(term).strip().lower()
        if term_text and term_text in search_text:
            score += 4
    for tag in entry.get("tags") or []:
        tag_text = str(tag).strip().lower()
        if tag_text and tag_text in search_text:
            score += 3
    if "declin" in search_text and "decline" in entry.get("tags", []):
        score += 3
    if "season" in search_text and "seasonal" in entry.get("tags", []):
        score += 3
    if "supply" in search_text and "supply" in entry.get("tags", []):
        score += 3
    if "salt" in search_text and "saltwater" in entry.get("tags", []):
        score += 3
    if "confined" in search_text and "confined" in entry.get("tags", []):
        score += 2
    return score


def _select_hydro_bank_snippets(
    question: str,
    sites: list[dict[str, Any]] | None = None,
    cross_well: dict[str, Any] | None = None,
    turn_history: list[dict[str, Any]] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Select curated hydro concept snippets for the active interpretation."""
    query = _build_enriched_rag_query(question, sites, cross_well, turn_history)
    search_text = query.lower()
    question_text = str(question or "").lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for entry in _load_hydro_interpretation_bank():
        score = _score_hydro_bank_entry(entry, search_text)
        for term in entry.get("trigger_terms") or []:
            term_text = str(term).strip().lower()
            if term_text and term_text in question_text:
                score += 16
                if term_text != "why":
                    score += 40
        for tag in entry.get("tags") or []:
            tag_text = str(tag).strip().lower()
            if tag_text and tag_text in question_text:
                score += 5
        if score <= 0:
            continue
        scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
    snippets: list[dict[str, Any]] = []
    for score, entry in scored[:limit]:
        content_parts = [str(entry.get("summary", "")).strip()]
        caveat = str(entry.get("caveat", "")).strip()
        if caveat:
            content_parts.append(f"Caveat: {caveat}")
        snippets.append(
            {
                "doc_id": f"hydro_bank:{entry.get('id')}",
                "content": " ".join(part for part in content_parts if part)[:700],
                "url": "local://eagle/hydro-interpretation-bank",
                "trust_level": "curated",
                "similarity_score": round(min(score / 12.0, 1.0), 3),
                "tags": entry.get("tags", []),
                "interpretive_move": entry.get("interpretive_move"),
                "evidence_needed": entry.get("evidence_needed", []),
                "implication": entry.get("implication"),
                "follow_up_questions": entry.get("follow_up_questions", []),
                "source_type": "curated_hydro_context",
            }
        )
    return snippets


class NumericClaim(BaseModel):
    """One numeric statement that must map to deterministic evidence."""

    site: str
    value: float
    unit: Literal["ft/yr", "ft", "ft_bls", "yr"]
    source: str

    @model_validator(mode="after")
    def _source_unit_must_match(self) -> "NumericClaim":
        source = str(self.source)
        expected_by_source = {
            "annual_change_ft_yr": "ft/yr",
            "mean_annual_change_ft_yr": "ft/yr",
            "aquifer_mean_annual_change_ft_yr": "ft/yr",
            "supply_unit_mean_annual_change_ft_yr": "ft/yr",
            "net_change_ft": "ft",
            "well_depth_ft": "ft",
            "record_years": "yr",
            "latest_depth_to_water_ft": "ft_bls",
        }
        expected = expected_by_source.get(source)
        if expected and self.unit != expected:
            raise ValueError(f"{source} claims must use {expected}")
        return self


class InterpretationResult(BaseModel):
    """Structured chart interpretation result."""

    answer: str
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    evidence_used: dict[str, Any] = Field(default_factory=dict)
    grounding_status: Literal["grounded", "partial", "refused"]
    follow_up_questions: list[str] = Field(default_factory=list)
    guardrail_flags: list[str] = Field(default_factory=list)
    what_to_notice: str = ""
    why_it_matters: str = ""


def _site_ids_from_chart_context(chart_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(chart_context, dict):
        return []
    raw_site_ids = chart_context.get("site_ids") or []
    if not raw_site_ids and isinstance(chart_context.get("summary_metrics"), dict):
        raw_site_ids = chart_context["summary_metrics"].get("site_ids") or []
    site_ids = []
    for raw in raw_site_ids:
        site_id = str(raw).strip()
        if site_id and site_id not in site_ids:
            site_ids.append(site_id)
    return site_ids[:12]


def _sites_from_chart_context(chart_context: dict[str, Any] | None) -> list[dict[str, Any]]:
    sites: list[dict[str, Any]] = []
    for site_id in _site_ids_from_chart_context(chart_context):
        meta = SITE_METADATA.get(site_id)
        if not meta:
            continue
        series = _load_site_timeseries(site_id)
        if series is None or series.empty:
            continue
        record_start, record_end = _series_period(series)
        record_years = None
        if record_start and record_end:
            try:
                record_years = round((len(series) / 365.25), 1)
            except Exception:
                record_years = None
        sites.append(
            {
                "site_id": site_id,
                "name": meta.get("name", site_id),
                "borehole_code": _borehole_code(meta.get("name", site_id)),
                "county": meta.get("county", "Florida"),
                "aquifer": meta.get("aquifer", "Unknown"),
                "aquifer_type": meta.get("aquifer_type", "unconfined"),
                "confined": meta.get("confined", False),
                "aquifer_zone": meta.get("aquifer_zone", ""),
                "aquifer_zone_depth_range_ft": meta.get("aquifer_zone_depth_range_ft", [0, 100]),
                "aquifer_description": meta.get("aquifer_description", ""),
                "well_depth_ft": meta.get("well_depth_ft", meta.get("depth")),
                "lat": meta.get("lat"),
                "lng": meta.get("lng"),
                "record_start": record_start,
                "record_end": record_end,
                "record_years": record_years,
                "series": series,
            }
        )
    return sites


def _highlighted_site_ids(cross_well: dict[str, Any]) -> set[str]:
    highlighted: set[str] = set()
    for pair in cross_well.get("divergent_pairs", []) or []:
        for side in ("site_a", "site_b"):
            site_id = str((pair.get(side) or {}).get("site_id", "")).strip()
            if site_id:
                highlighted.add(site_id)
    per_site = cross_well.get("per_site_metrics", []) or []
    if per_site:
        fastest_decline = min(per_site, key=lambda item: item["annual_change_ft_yr"])
        strongest_rise = max(per_site, key=lambda item: item["annual_change_ft_yr"])
        highlighted.add(str(fastest_decline["site_id"]))
        if strongest_rise["annual_change_ft_yr"] > 0:
            highlighted.add(str(strongest_rise["site_id"]))
    return highlighted


def _rag_snippets(question: str) -> list[dict[str, Any]]:
    if os.getenv("GROUNDWATERGPT_ENABLE_INTERPRETER_VECTOR_RAG", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return []
    if os.getenv("GROUNDWATERGPT_DISABLE_INTERPRETER_RAG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return []
    try:
        from src.agent.knowledge import search_knowledge

        docs = search_knowledge(question, k=5, score_threshold=0.45)
    except Exception as exc:
        logger.debug("Chart interpreter KB search unavailable: %s", exc)
        return []

    snippets = []
    for idx, doc in enumerate(docs):
        metadata = dict(getattr(doc, "metadata", {}) or {})
        snippets.append(
            {
                "doc_id": metadata.get("doc_id") or f"rag_{idx + 1}",
                "content": str(getattr(doc, "page_content", ""))[:700],
                "url": metadata.get("source_url")
                or metadata.get("url")
                or metadata.get("source")
                or "",
                "trust_level": metadata.get("trust_level", "unknown"),
                "similarity_score": metadata.get("similarity_score"),
            }
        )
    return snippets[:3]


def _rag_snippets_with_context(
    question: str,
    sites: list[dict[str, Any]] | None = None,
    cross_well: dict[str, Any] | None = None,
    turn_history: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve curated and vector KB snippets using chart-aware context."""
    if os.getenv("GROUNDWATERGPT_DISABLE_INTERPRETER_RAG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return []
    curated = _select_hydro_bank_snippets(question, sites, cross_well, turn_history, limit=3)
    enriched_query = _build_enriched_rag_query(question, sites, cross_well, turn_history)
    try:
        vector_snippets = _rag_snippets(enriched_query)
    except Exception as exc:
        logger.debug("Contextual KB search failed: %s", exc)
        vector_snippets = []
    snippets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for snippet in [*curated, *vector_snippets]:
        doc_id = str(snippet.get("doc_id") or snippet.get("content", "")[:80])
        if doc_id in seen:
            continue
        snippets.append(snippet)
        seen.add(doc_id)
        if len(snippets) >= 5:
            break
    return snippets


def _extract_prior_context(turn_history: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Extract prior intent, answer, and focus wells from turn history for follow-ups."""
    prior: dict[str, Any] = {}
    for turn in reversed(list(turn_history or [])):
        if turn.get("role") != "assistant":
            continue
        if turn.get("question_intent"):
            prior.setdefault("prior_intent", str(turn["question_intent"]))
        if turn.get("direct_answer"):
            prior.setdefault("prior_answer_preview", str(turn["direct_answer"])[:500])
        prior_wells = [
            str(w.get("name") or w.get("site_id") or "")
            for w in (turn.get("wells") or [])[:4]
            if w.get("name") or w.get("site_id")
        ]
        if prior_wells:
            prior.setdefault("prior_focus_wells", prior_wells)
        if prior:
            break
    return prior


def build_evidence_pack(
    question: str,
    chart_context: dict[str, Any] | None,
    turn_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build deterministic chart evidence for interpreter prompts and tests."""
    trimmed = list(turn_history or [])[-4:]
    prior_context = _extract_prior_context(trimmed)
    sites = _sites_from_chart_context(chart_context)
    if not sites:
        return {
            "question": question,
            "chart_context": chart_context or {},
            "turn_history": trimmed,
            "prior_context": prior_context,
            "sites": [],
            "site_ids": [],
            "wells": [],
            "cross_well": {},
            "insights": [],
            "explainability": {},
            "aquifer_summaries": [],
            "well_summaries": [],
            "supply_unit_summaries": [],
            "comparison_features": {},
            "entity_catalog": {},
            "supply_interpretation": None,
            "location_hydro_context": {},
            "cohort_period_start": None,
            "cohort_period_end": None,
            "rag_snippets": _rag_snippets_with_context(question, turn_history=turn_history),
            "enriched_rag_query": _build_enriched_rag_query(question, turn_history=turn_history),
        }

    cross_well = _cross_well_analysis(sites)
    highlighted = _highlighted_site_ids(cross_well)
    explainability = _build_chart_explainability(cross_well, highlighted, len(sites))
    insights = _build_chart_insights(cross_well, highlighted)
    wells = _build_wells_payload(sites)
    well_by_id = {str(well.get("site_id")): dict(well) for well in wells}
    site_payload = []
    site_periods: list[tuple[str, str]] = []
    for site in sites:
        site_id = str(site["site_id"])
        record_start = site.get("record_start")
        record_end = site.get("record_end")
        if record_start and record_end:
            site_periods.append((str(record_start), str(record_end)))
        well = well_by_id.get(site_id, {})
        well.update(
            {
                "borehole_code": site.get("borehole_code"),
                "record_start": record_start,
                "record_end": record_end,
                "record_years": site.get("record_years"),
            }
        )
        well_by_id[site_id] = well
        site_payload.append(
            {
                "site_id": site["site_id"],
                "name": site["name"],
                "borehole_code": site.get("borehole_code"),
                "aquifer": site.get("aquifer"),
                "aquifer_type": site.get("aquifer_type"),
                "aquifer_zone": site.get("aquifer_zone"),
                "county": site.get("county"),
                "lat": site.get("lat"),
                "lng": site.get("lng"),
                "confined": bool(site.get("confined", False)),
                "well_depth_ft": site.get("well_depth_ft"),
                "record_start": record_start,
                "record_end": record_end,
                "record_years": site.get("record_years"),
                "seasonal": _seasonal_decomposition(site.get("series")),
            }
        )
    cohort_period_start = min((start for start, _ in site_periods), default=None)
    cohort_period_end = max((end for _, end in site_periods), default=None)
    pack = {
        "question": question,
        "chart_context": chart_context or {},
        "turn_history": trimmed,
        "prior_context": prior_context,
        "sites": site_payload,
        "site_ids": [site["site_id"] for site in sites],
        "wells": list(well_by_id.values()),
        "cross_well": cross_well,
        "insights": insights,
        "explainability": explainability,
        "cohort_period_start": cohort_period_start,
        "cohort_period_end": cohort_period_end,
        "rag_snippets": _rag_snippets_with_context(question, sites, cross_well, turn_history),
        "enriched_rag_query": _build_enriched_rag_query(question, sites, cross_well, turn_history),
    }
    pack["aquifer_summaries"] = _aquifer_summaries_from_pack(pack)
    pack["well_summaries"] = _well_summaries_from_pack(pack)
    pack["supply_interpretation"] = _supply_interpretation_from_pack(question, chart_context, pack)
    pack["supply_unit_summaries"] = _supply_unit_summaries_from_pack(pack)
    pack["comparison_features"] = _comparison_features_from_pack(pack)
    pack["entity_catalog"] = _entity_catalog_from_pack(pack)
    pack["location_hydro_context"] = _build_location_hydro_context(question, chart_context, pack)
    return pack


def _numeric_claims_from_pack(pack: dict[str, Any]) -> list[NumericClaim]:
    claims: list[NumericClaim] = []
    for metric in pack.get("cross_well", {}).get("per_site_metrics", []) or []:
        claims.append(
            NumericClaim(
                site=str(metric["name"]),
                value=float(metric["annual_change_ft_yr"]),
                unit="ft/yr",
                source="annual_change_ft_yr",
            )
        )
        claims.append(
            NumericClaim(
                site=str(metric["name"]),
                value=float(metric["net_change_ft"]),
                unit="ft",
                source="net_change_ft",
            )
        )
    mean = pack.get("cross_well", {}).get("mean_annual_change_ft_yr")
    if mean is not None:
        claims.append(
            NumericClaim(
                site="cohort",
                value=float(mean),
                unit="ft/yr",
                source="mean_annual_change_ft_yr",
            )
        )
    for summary in pack.get("aquifer_summaries", []) or []:
        if summary.get("mean_annual_change") is None:
            continue
        label = str(summary.get("zone") or summary.get("aquifer") or "aquifer")
        claims.append(
            NumericClaim(
                site=label,
                value=float(summary.get("mean_annual_change")),
                unit="ft/yr",
                source="aquifer_mean_annual_change_ft_yr",
            )
        )
    for summary in pack.get("supply_unit_summaries", []) or []:
        if summary.get("mean_annual_change_ft_yr") is None:
            continue
        label = str(summary.get("zone") or summary.get("aquifer") or "supply unit")
        claims.append(
            NumericClaim(
                site=label,
                value=float(summary.get("mean_annual_change_ft_yr")),
                unit="ft/yr",
                source="supply_unit_mean_annual_change_ft_yr",
            )
        )
    return claims


def _citations_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    citations = [
        {
            "url": _usgs_site_url(str(site_id)),
            "trust_level": "verified",
            "anchor": str(site_id),
            "verified": True,
        }
        for site_id in pack.get("site_ids", [])[:10]
    ]
    for snippet in pack.get("rag_snippets", []) or []:
        if snippet.get("url"):
            citations.append(
                {
                    "url": snippet["url"],
                    "trust_level": snippet.get("trust_level", "unknown"),
                    "anchor": snippet.get("doc_id", "knowledge_base"),
                    "verified": snippet.get("trust_level") in TRUSTED_RAG_LEVELS,
                }
            )
    return citations


def _hydro_concepts_from_pack(pack: dict[str, Any]) -> list[dict[str, Any]]:
    concepts: list[dict[str, Any]] = []
    for snippet in pack.get("rag_snippets", []) or []:
        if snippet.get("source_type") != "curated_hydro_context":
            continue
        concepts.append(
            {
                "id": snippet.get("doc_id"),
                "summary": snippet.get("content"),
                "tags": snippet.get("tags", []),
                "interpretive_move": snippet.get("interpretive_move"),
                "evidence_needed": snippet.get("evidence_needed", []),
                "implication": snippet.get("implication"),
                "source": snippet.get("url"),
            }
        )
    return concepts[:4]


def _hydro_caveats_from_pack(pack: dict[str, Any]) -> list[str]:
    caveats: list[str] = []
    for concept in _hydro_concepts_from_pack(pack):
        text = str(concept.get("summary") or "")
        marker = "Caveat:"
        if marker not in text:
            continue
        caveat = text.split(marker, 1)[1].strip()
        if caveat and caveat not in caveats:
            caveats.append(caveat)
    return caveats[:4]


def _followups_from_hydro_context(pack: dict[str, Any]) -> list[str]:
    followups: list[str] = []
    if pack.get("site_ids"):
        followups.extend(
            [
                "Explain the decline using these wells.",
                "Which well is changing fastest?",
                "What caveats should I mention?",
                "Is this seasonal or long-term?",
            ]
        )
    for snippet in pack.get("rag_snippets", []) or []:
        for question in snippet.get("follow_up_questions") or []:
            text = str(question).strip()
            if text and text not in followups:
                followups.append(text)
    return followups[:4]


def _is_causal_question(question: str) -> bool:
    return bool(
        re.search(
            r"\b(why|pumping|climate change|run dry|prove|forecast|by 2030"
            r"|management claim)\b|caus\w*|overpump\w*",
            question,
            re.I,
        )
    )


def _select_relevant_claims(
    question: str,
    numeric_claims: list[NumericClaim],
) -> list[NumericClaim]:
    lowered = question.lower()
    selected = [
        claim
        for claim in numeric_claims
        if any(token in lowered for token in _claim_reference_tokens(claim.site))
    ]
    if selected:
        return selected[:6]
    selected = [
        claim
        for claim in numeric_claims
        if claim.unit == "ft/yr"
        and claim.site.lower() != "cohort"
        and any(token in lowered for token in _well_reference_tokens(claim.site))
    ]
    if selected:
        return selected[:4]
    annual = [
        claim
        for claim in numeric_claims
        if claim.unit == "ft/yr" and claim.site.lower() != "cohort"
    ]
    if not annual:
        return numeric_claims[:4]
    fastest_decline = min(annual, key=lambda claim: claim.value)
    strongest_rise = max(annual, key=lambda claim: claim.value)
    selected = [fastest_decline]
    if strongest_rise.site != fastest_decline.site:
        selected.append(strongest_rise)
    cohort = next((claim for claim in numeric_claims if claim.site == "cohort"), None)
    if cohort:
        selected.append(cohort)
    return selected[:4]


def _concept_summary(concept: dict[str, Any]) -> str:
    return str(concept.get("summary", "")).split("Caveat:", 1)[0].strip()


def _concept_tags(pack: dict[str, Any]) -> set[str]:
    tags: set[str] = set()
    for concept in _hydro_concepts_from_pack(pack):
        for tag in concept.get("tags", []) or []:
            text = str(tag).strip().lower()
            if text:
                tags.add(text)
    return tags


def _observed_signal_text(selected_claims: list[NumericClaim], pack: dict[str, Any]) -> str:
    if not selected_claims:
        return (
            "The available chart context does not contain enough deterministic trend "
            "metrics to summarize the observed signal."
        )
    rate_text = "; ".join(
        f"{claim.site}: {claim.value:+.3f} {claim.unit}"
        for claim in selected_claims
        if claim.unit == "ft/yr"
    )
    if not rate_text:
        rate_text = "; ".join(
            f"{claim.site}: {claim.value:+.2f} {claim.unit}" for claim in selected_claims
        )
    risk = str((pack.get("cross_well") or {}).get("risk_level") or "").strip().lower()
    risk_text = f" The cohort screening risk is {risk}." if risk else ""
    return f"The chart-backed signal is {rate_text}.{risk_text}"


def _possible_driver_texts(pack: dict[str, Any]) -> list[str]:
    tags = _concept_tags(pack)
    drivers: list[str] = []
    if {"decline", "drawdown", "stress"} & tags:
        drivers.append("drawdown or reduced aquifer pressure")
    if {"seasonal", "recharge", "wet season", "dry season"} & tags:
        drivers.append("seasonal recharge and dry-season variability")
    if {"pumping", "demand", "causality"} & tags:
        drivers.append("pumping stress or changing water demand")
    if {"confined", "artesian", "pressure"} & tags:
        drivers.append("pressure-head change in confined aquifer units")
    if {"shallow", "deep", "aquifer comparison", "confinement"} & tags:
        drivers.append("different responses between shallow and deeper monitored zones")
    if {"saltwater", "coastal", "intrusion", "risk"} & tags:
        drivers.append("coastal saltwater-intrusion concern if supported by water-quality data")
    if {"supply", "proxy", "monitoring well", "aquifer source"} & tags:
        drivers.append("proxy mismatch between monitoring wells and production wells")
    if not drivers:
        drivers.append(
            "site-specific recharge, withdrawals, aquifer confinement, or record-length effects"
        )
    return drivers[:5]


def _evidence_needed_texts(pack: dict[str, Any]) -> list[str]:
    tags = _concept_tags(pack)
    needed: list[str] = []
    for concept in _hydro_concepts_from_pack(pack):
        for item in concept.get("evidence_needed") or []:
            text = str(item).strip()
            if text:
                needed.append(text)
    needed.extend(
        [
            "pumping or withdrawal records",
            "rainfall, recharge, and drought-period data",
            "well construction, screened interval, and aquifer-unit documentation",
            "nearby monitoring wells to test whether the signal is local or regional",
        ]
    )
    if {"saltwater", "coastal", "intrusion", "risk"} & tags:
        needed.extend(
            [
                "chloride, salinity, or conductivity records",
                "coastal boundary, canal-stage, or tidal context",
            ]
        )
    if {"supply", "proxy", "monitoring well", "aquifer source"} & tags:
        needed.append("production-well or utility supply-source documentation")
    if {"seasonal", "recharge", "wet season", "dry season"} & tags:
        needed.append("seasonality-aware trend checks over multiple wet and dry cycles")
    return list(dict.fromkeys(needed))[:7]


def _build_meaning_brief(
    pack: dict[str, Any],
    hydro_meaning: str,
    implication: str,
    evidence_needed: list[str],
    confidence_note: str,
) -> dict[str, str]:
    cross_well = pack.get("cross_well") or {}
    metrics = _enriched_metrics(pack)
    dist = cross_well.get("trend_distribution") or {}
    n_total = int(cross_well.get("n_total") or len(metrics) or 0)
    falling = int(dist.get("falling", 0))
    stable = int(dist.get("stable", 0))
    rising = int(dist.get("rising", 0))
    risk = str(cross_well.get("risk_level") or "unknown").lower()
    mean_rate = cross_well.get("mean_annual_change_ft_yr")
    annual = [m for m in metrics if m.get("annual_change_ft_yr") is not None]
    strongest = None
    if annual:
        strongest = min(annual, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))

    if falling and rising:
        headline = "The chart is showing a mixed groundwater signal, not one uniform story."
    elif falling >= max(rising, stable, 1):
        headline = "The chart is showing a decline-oriented screening signal."
    elif rising >= max(falling, stable, 1):
        headline = "The chart is showing a recovery-oriented screening signal."
    elif stable:
        headline = "The chart is mostly stable, with changes that still need context."
    else:
        headline = "The chart is a screening view of monitored groundwater behavior."

    rate_text = ""
    try:
        if mean_rate is not None:
            rate_text = f" The cohort mean annual change is {_format_rate(mean_rate)}."
    except (TypeError, ValueError):
        rate_text = ""

    distribution = (
        f"Across the selected wells, {falling} are falling, {stable} are stable, "
        f"and {rising} are rising."
        if n_total
        else "The available chart context does not include enough wells for a cohort summary."
    )
    if strongest:
        distribution += (
            f" The strongest negative rate is {strongest.get('name')} at "
            f"{_format_rate(strongest.get('annual_change_ft_yr'))}."
        )

    plain_language = f"{distribution}{rate_text} {hydro_meaning}".strip()
    if risk in {"moderate", "high"}:
        why_it_matters = (
            f"Because the screening risk is {risk}, this pattern is useful for prioritizing "
            "follow-up review, not for making a final causation claim."
        )
    else:
        why_it_matters = implication

    how_to_read = (
        "Read this as an observed monitoring pattern: the chart can show which wells are "
        "moving together or diverging, while the cause still has to be tested with outside data."
    )
    next_checks = (
        "; ".join(evidence_needed[:3]) if evidence_needed else "nearby wells and outside covariates"
    )
    next_best_check = f"Next, compare the chart with {next_checks}."
    classroom_takeaway = (
        "Separate observation from interpretation: the observed rates are reproducible, while "
        "drawdown, pumping stress, recharge change, or saltwater concern are hypotheses to test."
    )

    return {
        "headline": headline,
        "plain_language": plain_language,
        "why_it_matters": why_it_matters,
        "how_to_read": how_to_read,
        "next_best_check": next_best_check,
        "classroom_takeaway": classroom_takeaway,
        "confidence": confidence_note,
    }


def _build_interpretive_sections(
    question: str,
    pack: dict[str, Any],
    selected_claims: list[NumericClaim],
) -> dict[str, Any]:
    concepts = _hydro_concepts_from_pack(pack)
    tags = _concept_tags(pack)
    primary_concept = _concept_summary(concepts[0]) if concepts else ""
    observed_signal = _observed_signal_text(selected_claims, pack)
    possible_drivers = _possible_driver_texts(pack)
    evidence_needed = _evidence_needed_texts(pack)
    risk = str((pack.get("cross_well") or {}).get("risk_level") or "").strip().lower()

    if primary_concept:
        hydro_meaning = primary_concept
    elif selected_claims:
        hydro_meaning = (
            "The pattern is useful as a groundwater screening signal, but its meaning depends on "
            "aquifer setting, seasonality, record length, and nearby well behavior."
        )
    else:
        hydro_meaning = (
            "The available chart context is not sufficient for a hydrogeologic interpretation."
        )

    if "saltwater" in tags:
        implication = (
            "For a coastal or supply-planning discussion, this is a prompt to check water-quality "
            "and pumping evidence before making an intrusion claim."
        )
    elif {"supply", "proxy", "monitoring well", "aquifer source"} & tags:
        implication = (
            "For supply interpretation, the chart can support a proxy-based screening discussion, "
            "but production-well documentation is needed before treating the monitoring wells "
            "as the utility source."
        )
    elif {"decline", "drawdown", "stress"} & tags or risk in {"moderate", "high"}:
        implication = (
            "For students, sponsors, or analysts, this is a screening flag: the wells deserve "
            "follow-up because persistent decline can matter for sustainability, drawdown, "
            "and monitoring priorities."
        )
    else:
        implication = (
            "The result is most useful as an auditable starting point for comparing monitored "
            "wells and deciding which outside evidence to collect next."
        )

    confidence_note = (
        "Confidence is strongest for the observed USGS trend metrics and weaker for causes; "
        "the chart does not prove pumping, recharge change, saltwater intrusion, or "
        "management impact without external covariates."
    )
    if "seasonal" in tags:
        confidence_note += (
            " Seasonal and long-term signals should be separated before making a trend claim."
        )
    if "confined" in tags:
        confidence_note += (
            " In confined units, water-level change is interpreted as pressure-head change, "
            "not simple water-table drainage."
        )
    meaning_brief = _build_meaning_brief(
        pack=pack,
        hydro_meaning=hydro_meaning,
        implication=implication,
        evidence_needed=evidence_needed,
        confidence_note=confidence_note,
    )

    findings = [
        {"label": "Observed signal", "text": observed_signal},
        {"label": "Hydrogeologic meaning", "text": hydro_meaning},
        {"label": "What this means", "text": meaning_brief["plain_language"]},
        {"label": "Possible explanations", "text": "; ".join(possible_drivers) + "."},
        {"label": "Evidence needed", "text": "; ".join(evidence_needed) + "."},
        {"label": "Implication", "text": implication},
        {"label": "Confidence note", "text": confidence_note},
    ]

    return {
        "observed_signal": observed_signal,
        "hydrogeologic_meaning": hydro_meaning,
        "possible_drivers": possible_drivers,
        "evidence_needed": evidence_needed,
        "management_implications": [implication],
        "confidence_notes": [confidence_note],
        "meaning_brief": meaning_brief,
        "what_this_means": [
            meaning_brief["headline"],
            meaning_brief["why_it_matters"],
            meaning_brief["next_best_check"],
        ],
        "interpretive_findings": findings,
        "question_intent": str(question or "").strip(),
    }


def _format_rate(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{numeric:+.3f} ft/yr"


def _metric_context_by_site(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}
    for site in pack.get("sites", []) or []:
        site_id = str(site.get("site_id") or "").strip()
        if site_id:
            context[site_id] = dict(site)
    return context


def _enriched_metrics(pack: dict[str, Any]) -> list[dict[str, Any]]:
    site_context = _metric_context_by_site(pack)
    enriched: list[dict[str, Any]] = []
    for metric in (pack.get("cross_well") or {}).get("per_site_metrics", []) or []:
        site_id = str(metric.get("site_id") or "").strip()
        merged = {**metric, **site_context.get(site_id, {})}
        merged["site_id"] = site_id or metric.get("site_id")
        enriched.append(merged)
    return enriched


def _mean_rate(metrics: list[dict[str, Any]]) -> float | None:
    values = []
    for metric in metrics:
        try:
            values.append(float(metric["annual_change_ft_yr"]))
        except (KeyError, TypeError, ValueError):
            continue
    return sum(values) / len(values) if values else None


def _mean_seasonal_amplitude(metrics: list[dict[str, Any]]) -> float | None:
    values = []
    for metric in metrics:
        seasonal = metric.get("seasonal") or {}
        if not seasonal.get("has_seasonal"):
            continue
        try:
            values.append(float(seasonal.get("seasonal_amplitude_ft")))
        except (TypeError, ValueError):
            continue
    return sum(values) / len(values) if values else None


def _group_metrics_by_confinement(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = {
        "shallow_unconfined": {
            "label": "shallow/unconfined",
            "metrics": [],
        },
        "deep_confined": {
            "label": "deep/confined",
            "metrics": [],
        },
    }
    for metric in _enriched_metrics(pack):
        key = "deep_confined" if metric.get("confined") else "shallow_unconfined"
        groups[key]["metrics"].append(metric)
    for key, group in groups.items():
        metrics = group["metrics"]
        group["count"] = len(metrics)
        group["mean_annual_change_ft_yr"] = _mean_rate(metrics)
        group["mean_seasonal_amplitude_ft"] = _mean_seasonal_amplitude(metrics)
        group["well_names"] = [str(metric.get("name")) for metric in metrics if metric.get("name")]
        group["site_ids"] = [
            str(metric.get("site_id")) for metric in metrics if metric.get("site_id")
        ]
        group.pop("metrics", None)
    return groups


def _largest_rate_gap(metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(metrics) < 2:
        return None
    sorted_metrics = sorted(metrics, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
    low = sorted_metrics[0]
    high = sorted_metrics[-1]
    return {
        "site_a": low,
        "site_b": high,
        "gap_ft_yr": abs(
            float(high.get("annual_change_ft_yr", 0.0)) - float(low.get("annual_change_ft_yr", 0.0))
        ),
    }


def _detect_question_intent(question: str, pack: dict[str, Any]) -> str:
    text = str(question or "").lower()
    mentioned_wells = 0
    named_well_tokens = re.findall(r"\b[a-z]+(?:\s+[a-z]+)?\s+[a-z]-\d+[a-z]?\b", text)
    for well in pack.get("well_summaries") or pack.get("wells") or []:
        name = str(well.get("name") or "").strip().lower()
        site_id = str(well.get("site_id") or "").strip().lower()
        if (name and name in text) or (site_id and site_id in text):
            mentioned_wells += 1

    if (
        ("diverge" in text or "divergent" in text)
        and (mentioned_wells >= 1 or len(named_well_tokens) >= 2)
        and not re.search(r"\b(shallow|deep|confined|unconfined)\b", text)
    ):
        if re.search(r"\b(why|cause|because|explain|reason)\b", text):
            return "cause_or_why"
        return "general"

    if re.search(r"\b(shallow|deep|confined|unconfined|diverge|divergent|aquifer wells?)\b", text):
        return "shallow_deep_comparison"
    if re.search(
        r"\b(fastest|most|which well|which one|steepest|largest change|changing fastest)\b", text
    ):
        return "fastest_changing"
    if re.search(r"\b(risk|screening|what does this mean|why does this matter|concern)\b", text):
        return "risk_explanation"
    if re.search(
        r"\b(cohort|average|mean annual|mean rate|mean change|what does the average mean)\b", text
    ):
        return "cohort_meaning"
    if re.search(
        r"\b(when did|shift|accelerat|change\s*point|turning point|got worse|got better"
        r"|started declining|started rising|trend change|break\s*point)\b",
        text,
    ):
        return "trend_change"
    if re.search(
        r"\b(season|wet|dry|summer|winter|rainy|rainfall|annual cycle|cycl|monsoon)\b", text
    ):
        return "seasonal"
    if re.search(
        r"\b(why|cause|because|explain|what.s driving|what drove|pumping|recharge"
        r"|what caused|reason)\b",
        text,
    ):
        return "cause_or_why"
    return "general"


def _shallow_deep_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    metrics = _enriched_metrics(pack)
    groups = _group_metrics_by_confinement(pack)
    shallow = groups["shallow_unconfined"]
    deep = groups["deep_confined"]
    if not shallow["count"] or not deep["count"]:
        present = shallow if shallow["count"] else deep
        direct = (
            "This chart does not contain both shallow/unconfined and deep/confined groups, "
            f"so it cannot support a true shallow-vs-deep divergence comparison. It contains "
            f"{present['count']} {present['label']} well{'s' if present['count'] != 1 else ''}."
        )
        return direct, [direct], {"comparison_groups": groups}

    shallow_rate = float(shallow["mean_annual_change_ft_yr"])
    deep_rate = float(deep["mean_annual_change_ft_yr"])
    gap = abs(shallow_rate - deep_rate)
    diverges = gap >= 0.05
    direction = "Yes, they diverge" if diverges else "They differ, but only modestly"
    direct = (
        f"{direction}: the {shallow['count']} shallow/unconfined well"
        f"{'s' if shallow['count'] != 1 else ''} average {_format_rate(shallow_rate)}, "
        f"while the {deep['count']} deep/confined well{'s' if deep['count'] != 1 else ''} "
        f"average {_format_rate(deep_rate)}."
    )
    largest_gap = _largest_rate_gap(metrics)
    evidence = []
    if largest_gap:
        a = largest_gap["site_a"]
        b = largest_gap["site_b"]
        evidence.append(
            f"The largest well-level gap is between {a.get('name')} "
            f"({_format_rate(a.get('annual_change_ft_yr'))}) "
            f"and {b.get('name')} ({_format_rate(b.get('annual_change_ft_yr'))})."
        )
    if (
        shallow.get("mean_seasonal_amplitude_ft") is not None
        or deep.get("mean_seasonal_amplitude_ft") is not None
    ):
        shallow_amp = shallow.get("mean_seasonal_amplitude_ft")
        deep_amp = deep.get("mean_seasonal_amplitude_ft")
        amp_parts = []
        if shallow_amp is not None:
            amp_parts.append(f"shallow seasonal amplitude averages {shallow_amp:.1f} ft")
        if deep_amp is not None:
            amp_parts.append(f"deep/confined amplitude averages {deep_amp:.1f} ft")
        evidence.append("; ".join(amp_parts) + ".")
    return direct, evidence, {"comparison_groups": groups, "largest_gap": largest_gap}


def _fastest_changing_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    metrics = _enriched_metrics(pack)
    annual = [m for m in metrics if m.get("annual_change_ft_yr") is not None]
    if not annual:
        direct = (
            "The chart does not include enough rate information to identify the "
            "fastest-changing well."
        )
        return direct, [direct], {}
    by_decline = sorted(annual, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
    fastest_decline = by_decline[0]
    strongest_rise = by_decline[-1]
    direct = (
        f"{fastest_decline.get('name')} is declining fastest at "
        f"{_format_rate(fastest_decline.get('annual_change_ft_yr'))}."
    )
    evidence = []
    if len(by_decline) > 1:
        second = by_decline[1]
        evidence.append(
            f"Next most negative is {second.get('name')} at "
            f"{_format_rate(second.get('annual_change_ft_yr'))}."
        )
    if (
        strongest_rise is not fastest_decline
        and float(strongest_rise.get("annual_change_ft_yr", 0.0)) > 0
    ):
        evidence.append(
            f"The strongest rising well is {strongest_rise.get('name')} at "
            f"{_format_rate(strongest_rise.get('annual_change_ft_yr'))}."
        )
    return direct, evidence, {"fastest_decline": fastest_decline, "strongest_rise": strongest_rise}


def _cohort_meaning_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    cross_well = pack.get("cross_well") or {}
    metrics = _enriched_metrics(pack)
    mean = cross_well.get("mean_annual_change_ft_yr")
    n_total = int(cross_well.get("n_total") or len(metrics))
    dist = cross_well.get("trend_distribution") or {}
    try:
        mean_value = float(mean)
    except (TypeError, ValueError):
        mean_value = None
    if mean_value is None:
        direct = "The chart does not include enough wells to compute a meaningful cohort average."
        return direct, [direct], {}
    below = [m for m in metrics if float(m.get("annual_change_ft_yr", 0.0)) < mean_value]
    above = [m for m in metrics if float(m.get("annual_change_ft_yr", 0.0)) >= mean_value]
    annual = [m for m in metrics if m.get("annual_change_ft_yr") is not None]
    fastest_decline = (
        min(annual, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
        if annual
        else None
    )
    strongest_rise = (
        max(annual, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
        if annual
        else None
    )
    spread = None
    if fastest_decline and strongest_rise:
        spread = abs(
            float(strongest_rise.get("annual_change_ft_yr", 0.0))
            - float(fastest_decline.get("annual_change_ft_yr", 0.0))
        )
    if mean_value < -0.02:
        group_signal = "slightly falling"
    elif mean_value > 0.02:
        group_signal = "slightly rising"
    else:
        group_signal = "near stable"
    direct = (
        "The cohort average is a group summary, not a physical well: it is the mean annual "
        f"change across the {n_total} monitored wells. Here it is {_format_rate(mean_value)}, "
        f"so the group-level signal is {group_signal}."
    )
    evidence = [
        (
            f"{dist.get('falling', 0)} wells are falling, "
            f"{dist.get('stable', 0)} are stable, and "
            f"{dist.get('rising', 0)} are rising."
        ),
        (
            "Use the average as a first screen, then inspect individual wells because "
            "opposite-moving wells can cancel each other out."
        ),
    ]
    if fastest_decline and strongest_rise and fastest_decline is not strongest_rise:
        evidence.append(
            f"The spread from {fastest_decline.get('name')} "
            f"({_format_rate(fastest_decline.get('annual_change_ft_yr'))}) to "
            f"{strongest_rise.get('name')} "
            f"({_format_rate(strongest_rise.get('annual_change_ft_yr'))}) shows why "
            "highlighted divergent wells matter."
        )
    evidence.append(
        "For a student or analyst, the value is triage: the cohort average tells the network "
        "story, while the outliers tell where to look next."
    )
    rubric = _rubric_for_intent("cohort_meaning")
    return (
        direct,
        evidence,
        {
            "cohort_meaning": {
                "below_average": len(below),
                "at_or_above_average": len(above),
                "mean_annual_change_ft_yr": mean_value,
                "group_signal": group_signal,
                "falling_count": int(dist.get("falling", 0)),
                "stable_count": int(dist.get("stable", 0)),
                "rising_count": int(dist.get("rising", 0)),
                "fastest_decline": fastest_decline,
                "strongest_rise": strongest_rise,
                "spread_ft_yr": spread,
                "student_takeaway": rubric.get(
                    "student_takeaway",
                    "Start with the cohort average, then inspect individual wells and outliers.",
                ),
                "limitations": [
                    "The average is not a forecast.",
                    "The average can hide divergent individual wells.",
                    "Screening risk is a prioritization flag, not a diagnosis.",
                ],
            }
        },
    )


def _risk_explanation_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    cross_well = pack.get("cross_well") or {}
    metrics = _enriched_metrics(pack)
    dist = cross_well.get("trend_distribution") or {}
    n_total = int(cross_well.get("n_total") or len(metrics) or 0)
    falling = int(dist.get("falling", 0))
    pct = float(falling / n_total) if n_total else 0.0
    risk = str(cross_well.get("risk_level") or "unknown").lower()
    direct = (
        f"The {risk} screening risk means {falling} of {n_total} wells "
        f"({pct:.0%}) are falling or the cohort has enough decline to warrant follow-up."
    )
    annual = [m for m in metrics if m.get("annual_change_ft_yr") is not None]
    evidence = []
    if annual:
        worst = min(annual, key=lambda item: float(item.get("annual_change_ft_yr", 0.0)))
        evidence.append(
            f"The strongest contributor to concern is {worst.get('name')} at "
            f"{_format_rate(worst.get('annual_change_ft_yr'))}."
        )
    mean = cross_well.get("mean_annual_change_ft_yr")
    if mean is not None:
        evidence.append(f"The cohort mean is {_format_rate(mean)}.")
    return (
        direct,
        evidence,
        {
            "risk_summary": {
                "risk_level": risk,
                "falling_count": falling,
                "n_total": n_total,
                "pct_falling": pct,
            }
        },
    )


def _trend_change_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    changepoints = (pack.get("cross_well") or {}).get("changepoints") or []
    if not changepoints:
        direct = (
            "No statistically significant trend shift was detected in the monitored wells. "
            "This can happen when records are too short, change is gradual rather than abrupt, "
            "or the wells have been declining (or rising) at a steady rate throughout the record."
        )
        return direct, [direct], {}

    lines = []
    for cp in changepoints[:3]:
        name = cp.get("name", "a well")
        split = cp.get("split_date", "unknown date")
        pre = cp.get("pre_annual_rate_ft_yr")
        post = cp.get("post_annual_rate_ft_yr")
        conf = cp.get("confidence", "")
        if pre is not None and post is not None:
            lines.append(
                f"At {name}, the trend shifted around {split}: before that, "
                f"levels changed at {_format_rate(pre)}; after, at {_format_rate(post)}"
                + (f" ({conf} confidence)." if conf else ".")
            )
    if not lines:
        direct = "Changepoint metadata is present but does not contain enough rate detail."
        return direct, [direct], {}

    direct = lines[0]
    evidence = lines[1:] if len(lines) > 1 else []
    evidence.append(
        "A trend shift is an observed pattern change, not proof of a specific cause; "
        "pumping, land-use, or climate shifts need separate evidence."
    )
    return direct, evidence, {"changepoints": changepoints[:3]}


def _seasonal_answer(pack: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    seasonal_data = []
    for site in pack.get("sites") or []:
        s = site.get("seasonal") or {}
        if s.get("seasonal_amplitude_ft") is not None:
            seasonal_data.append(
                {
                    "name": site.get("name", "?"),
                    "amplitude_ft": s["seasonal_amplitude_ft"],
                    "wet_mean": s.get("wet_season_mean"),
                    "dry_mean": s.get("dry_season_mean"),
                    "wet_trend": s.get("wet_season_trend"),
                    "dry_trend": s.get("dry_season_trend"),
                }
            )
    if not seasonal_data:
        direct = (
            "The available records do not contain enough data to separate seasonal patterns. "
            "At least two full years of measurements are needed for seasonal decomposition."
        )
        return direct, [direct], {}

    seasonal_data.sort(key=lambda x: x["amplitude_ft"], reverse=True)
    top = seasonal_data[0]
    if top.get("wet_mean") is not None and top.get("dry_mean") is not None:
        direct = (
            f"At {top['name']}, wet-season levels average {top['wet_mean']:.1f} ft "
            f"vs. {top['dry_mean']:.1f} ft in dry season, a {top['amplitude_ft']:.1f} ft "
            f"seasonal swing."
        )
    else:
        direct = (
            f"At {top['name']}, the monitoring record shows about a {top['amplitude_ft']:.1f} ft "
            "seasonal swing, although the wet/dry mean split is incomplete in the loaded decomposition."  # noqa: E501
        )
    evidence = []
    if top.get("wet_trend") or top.get("dry_trend"):
        parts = []
        if top["wet_trend"]:
            parts.append(f"the wet season is {top['wet_trend']}")
        if top["dry_trend"]:
            parts.append(f"the dry season is {top['dry_trend']}")
        evidence.append(f"Season-specific trends show {' and '.join(parts)}.")

    if len(seasonal_data) > 1:
        amps = [s["amplitude_ft"] for s in seasonal_data]
        evidence.append(
            f"Seasonal amplitude ranges from {min(amps):.1f} ft to {max(amps):.1f} ft "
            f"across {len(seasonal_data)} wells."
        )

    evidence.append(
        "Large seasonal swings can mask or mimic a long-term trend; separate the "
        "seasonal cycle from the multi-year signal before drawing conclusions."
    )
    return direct, evidence, {"seasonal_summary": seasonal_data[:5]}


def _cause_or_why_answer(
    question: str,
    pack: dict[str, Any],
    interpretive_sections: dict[str, Any],
) -> tuple[str, list[str], dict[str, Any]]:
    cross_well = pack.get("cross_well") or {}
    metrics = _enriched_metrics(pack)
    annual = [m for m in metrics if m.get("annual_change_ft_yr") is not None]
    question_text = str(question or "")
    lower_question = question_text.lower()
    named_well_tokens = re.findall(
        r"\b([A-Za-z]+(?:-[A-Za-z]+)?\s+[A-Za-z]-\d+[A-Za-z]?)\b",
        question_text,
    )

    if ("diverge" in lower_question or "divergent" in lower_question) and len(
        named_well_tokens
    ) >= 2:
        referenced_metrics = []
        missing_tokens = []
        for token in named_well_tokens[:2]:
            match = next(
                (
                    metric
                    for metric in annual
                    if str(metric.get("name") or "").lower() == token.lower()
                ),
                None,
            )
            if match is not None:
                referenced_metrics.append(match)
            else:
                missing_tokens.append(token)

        if len(referenced_metrics) < 2:
            present = (
                ", ".join(str(metric.get("name") or "") for metric in referenced_metrics)
                or "neither named well"
            )
            requested = " and ".join(named_well_tokens[:2])
            direct = (
                f"This question asks about {requested}, but the current chart only includes {present}, "  # noqa: E501
                "so it cannot show why that pair diverges on its own."
            )
            evidence = [
                "Use a chart or comparison that includes both named wells before interpreting pairwise divergence.",  # noqa: E501
                "Once both wells are in view, compare their annual rates, screened intervals, and aquifer assignments before discussing causes.",  # noqa: E501
            ]
            return direct, evidence, {"guardrail": "missing_named_pair_in_chart"}

        left, right = referenced_metrics[:2]
        left_rate = float(left.get("annual_change_ft_yr", 0.0))
        right_rate = float(right.get("annual_change_ft_yr", 0.0))
        gap = abs(left_rate - right_rate)
        direct = (
            f"{left.get('name')} and {right.get('name')} do not move at the same rate in this chart: "  # noqa: E501
            f"{left.get('name')} changes at {_format_rate(left_rate)}, while {right.get('name')} changes at "  # noqa: E501
            f"{_format_rate(right_rate)}."
        )
        evidence = [
            f"The absolute gap between their annual trends is {gap:.3f} ft/yr in the monitored record.",  # noqa: E501
            "That observed divergence can come from different screened intervals, aquifer conditions, or local stresses, but the chart alone does not identify which explanation is correct.",  # noqa: E501
            "To explain the divergence, check pumping, rainfall/recharge, screened interval metadata, and nearby wells in the same aquifer unit.",  # noqa: E501
        ]
        return direct, evidence, {"guardrail": "pairwise_divergence_not_causal"}

    # State the observation clearly
    mean = cross_well.get("mean_annual_change_ft_yr")
    n_total = int(cross_well.get("n_total") or len(metrics) or 0)
    if mean is not None and n_total:
        observation = (
            f"The observed signal across {n_total} wells is a cohort mean of "
            f"{_format_rate(mean)}."
        )
    elif annual:
        worst = min(annual, key=lambda m: float(m.get("annual_change_ft_yr", 0.0)))
        observation = (
            f"The strongest observed change is at {worst.get('name')} at "
            f"{_format_rate(worst.get('annual_change_ft_yr'))}."
        )
    else:
        observation = "The chart does not contain enough trend data to characterize the signal."

    # Possible drivers from existing helper
    drivers = interpretive_sections.get("possible_drivers") or []
    driver_text = (
        "Plausible explanations include: " + "; ".join(drivers) + "."
        if drivers
        else "Without external data the possible drivers cannot be narrowed."
    )

    # What evidence would actually prove causation
    needed = interpretive_sections.get("evidence_needed") or []
    needed_text = (
        "To test these hypotheses, you would need: " + "; ".join(needed[:4]) + "." if needed else ""
    )

    direct = (
        f"{observation} The chart alone cannot prove why — it shows the pattern, " f"not the cause."
    )
    evidence = [driver_text]
    if needed_text:
        evidence.append(needed_text)
    evidence.append(
        "Treat the observed change as a screening signal; causation claims "
        "require pumping records, rainfall data, recharge models, or water-quality evidence."
    )
    return direct, evidence, {"guardrail": "causation_not_supported"}


def _general_answer(
    pack: dict[str, Any], interpretive_sections: dict[str, Any]
) -> tuple[str, list[str], dict[str, Any]]:
    direct = interpretive_sections["hydrogeologic_meaning"]
    evidence = [interpretive_sections["observed_signal"]]
    extra: dict[str, Any] = {}

    # Surface changepoints already computed in cross_well
    changepoints = (pack.get("cross_well") or {}).get("changepoints") or []
    for cp in changepoints[:2]:
        name = cp.get("name", "a well")
        split = cp.get("split_date", "")
        pre = cp.get("pre_annual_rate_ft_yr")
        post = cp.get("post_annual_rate_ft_yr")
        if split and pre is not None and post is not None:
            evidence.append(
                f"At {name}, the trend shifted around {split}: before that, levels "
                f"changed at {_format_rate(pre)}; after, at {_format_rate(post)}."
            )
    if changepoints:
        extra["changepoints"] = changepoints[:2]

    # Surface seasonal contrast from per-site decomposition
    for site in (pack.get("sites") or [])[:3]:
        seasonal = site.get("seasonal") or {}
        amplitude = seasonal.get("seasonal_amplitude_ft")
        wet_mean = seasonal.get("wet_season_mean")
        dry_mean = seasonal.get("dry_season_mean")
        if (
            amplitude is not None
            and amplitude > 1.0
            and wet_mean is not None
            and dry_mean is not None
        ):
            evidence.append(
                f"At {site.get('name', 'one well')}, wet-season levels average "
                f"{wet_mean:.1f} ft vs. {dry_mean:.1f} ft in dry season "
                f"(a {amplitude:.1f} ft swing that can mask long-term trends)."
            )
            break  # one example is enough

    # Surface divergent pairs
    divergent = (pack.get("cross_well") or {}).get("divergent_pairs") or []
    if divergent:
        pair = divergent[0]
        a = pair.get("site_a") or {}
        b = pair.get("site_b") or {}
        evidence.append(
            f"{a.get('name', '?')} and {b.get('name', '?')} are moving in opposite "
            f"directions ({_format_rate(a.get('annual_change_ft_yr'))} vs. "
            f"{_format_rate(b.get('annual_change_ft_yr'))}), which warrants "
            f"site-specific investigation."
        )
        extra["divergent_pair"] = pair

    return direct, evidence, extra


def _build_intent_answer(
    question: str,
    pack: dict[str, Any],
    interpretive_sections: dict[str, Any],
) -> dict[str, Any]:
    intent = _detect_question_intent(question, pack)
    # Builders that take only pack
    pack_builders = {
        "shallow_deep_comparison": _shallow_deep_answer,
        "fastest_changing": _fastest_changing_answer,
        "cohort_meaning": _cohort_meaning_answer,
        "risk_explanation": _risk_explanation_answer,
        "trend_change": _trend_change_answer,
        "seasonal": _seasonal_answer,
    }
    if intent in pack_builders:
        direct_answer, supporting_evidence, extra = pack_builders[intent](pack)
    elif intent == "cause_or_why":
        direct_answer, supporting_evidence, extra = _cause_or_why_answer(
            question, pack, interpretive_sections
        )
    else:
        direct_answer, supporting_evidence, extra = _general_answer(pack, interpretive_sections)
    rubric = _rubric_for_intent(intent)
    caveat = interpretive_sections["confidence_notes"][0]
    answer = " ".join(
        [
            direct_answer,
            " ".join(supporting_evidence[:2]),
            caveat,
        ]
    )
    observations = [direct_answer, *supporting_evidence]
    payload = {
        "question_intent": intent,
        "direct_answer": direct_answer,
        "supporting_evidence": supporting_evidence,
        "answer_relevant_observations": observations[:5],
        "caveat": caveat,
        "answer": answer,
        **extra,
    }
    if _expose_interpretation_rubric():
        payload["interpretation_rubric"] = {
            "intent": intent,
            "goal": rubric.get("goal"),
            "required_moves": rubric.get("required_moves", []),
            "weak_answer_signals": rubric.get("weak_answer_signals", []),
            "student_takeaway": rubric.get("student_takeaway"),
        }
    return payload


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _sentenceish(text: str) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return ""
    if clean.endswith((".", "!", "?")):
        return clean
    return f"{clean}."


def _learner_next_question(
    intent: str,
    evidence_needed: list[str],
    follow_up_questions: list[str] | None = None,
) -> str:
    if follow_up_questions:
        first = _first_nonempty(*(follow_up_questions or []))
        if first:
            return first
    if intent == "fastest_changing":
        return "Does the fastest-declining well also diverge from the cohort average?"
    if intent == "cohort_meaning":
        return "Which individual wells are pulling the cohort average down or up?"
    if intent == "risk_explanation":
        return "What outside data would tell us whether this screening risk reflects pumping, recharge, or something else?"  # noqa: E501
    if intent == "shallow_deep_comparison":
        return "Do the shallow and deep wells stay separated through wet and dry seasons?"
    if evidence_needed:
        return f"What would we learn next from {evidence_needed[0]}?"
    return "What outside data would strengthen this interpretation?"


def _build_learner_brief(
    pack: dict[str, Any],
    interpretive_sections: dict[str, Any],
    intent_answer: dict[str, Any],
    follow_up_questions: list[str] | None = None,
    llm_result: InterpretationResult | None = None,
) -> dict[str, str]:
    del pack
    meaning_brief = interpretive_sections.get("meaning_brief") or {}
    support = intent_answer.get("supporting_evidence") or []
    confidence_notes = interpretive_sections.get("confidence_notes") or []
    evidence_needed = interpretive_sections.get("evidence_needed") or []

    # Use LLM answer as direct_answer when available; fall back to deterministic
    if llm_result is not None and llm_result.answer.strip():
        direct_answer = _sentenceish(llm_result.answer.strip())
    else:
        direct_answer = _sentenceish(intent_answer.get("direct_answer"))

    # Prefer LLM-generated interpretive fields; fall back to deterministic
    if llm_result is not None and llm_result.what_to_notice.strip():
        what_to_notice = _sentenceish(llm_result.what_to_notice.strip())
    else:
        what_to_notice = _sentenceish(
            _first_nonempty(
                support[0] if support else "",
                meaning_brief.get("headline"),
                meaning_brief.get("plain_language"),
            )
        )

    if llm_result is not None and llm_result.why_it_matters.strip():
        why_it_matters = _sentenceish(llm_result.why_it_matters.strip())
    else:
        why_it_matters = _sentenceish(
            _first_nonempty(
                meaning_brief.get("why_it_matters"),
                meaning_brief.get("plain_language"),
                (interpretive_sections.get("management_implications") or [None])[0],
            )
        )

    important_limit = _sentenceish(
        _first_nonempty(
            confidence_notes[0] if confidence_notes else "",
            "The chart shows observed monitoring patterns, but it does not prove a cause by itself.",  # noqa: E501
        )
    )
    next_best_question = _learner_next_question(
        str(intent_answer.get("question_intent") or "general"),
        evidence_needed,
        follow_up_questions,
    )
    next_question_text = " ".join(str(next_best_question or "").split()).strip()
    if next_question_text:
        next_question_text = next_question_text.rstrip(".?") + "?"
    return {
        "direct_answer": direct_answer,
        "what_to_notice": what_to_notice,
        "why_it_matters": why_it_matters,
        "important_limit": important_limit,
        "next_best_question": next_question_text,
    }


def _terms_to_know(
    question: str,
    pack: dict[str, Any],
    interpretive_sections: dict[str, Any],
    intent_answer: dict[str, Any],
) -> list[dict[str, str]]:
    cross_well = pack.get("cross_well") or {}
    risk = str(cross_well.get("risk_level") or "").strip().lower()
    question_intent = str(intent_answer.get("question_intent") or "general")
    text_blob = " ".join(
        [
            str(question or ""),
            str(intent_answer.get("direct_answer") or ""),
            " ".join(str(item) for item in intent_answer.get("supporting_evidence") or []),
            str((interpretive_sections.get("meaning_brief") or {}).get("plain_language") or ""),
            " ".join(str(item) for item in interpretive_sections.get("possible_drivers") or []),
            " ".join(str(item) for item in interpretive_sections.get("confidence_notes") or []),
        ]
    ).lower()
    terms: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in LEARNER_TERM_LIBRARY:
        include = any(trigger in text_blob for trigger in entry["triggers"])
        if entry["term"] == "screening risk" and risk:
            include = (
                include or risk in {"moderate", "high"} or question_intent == "risk_explanation"
            )
        if entry["term"] == "cohort average" and question_intent == "cohort_meaning":
            include = True
        if entry["term"] == "confined aquifer" and question_intent == "shallow_deep_comparison":
            include = True
        if not include or entry["term"] in seen:
            continue
        terms.append(
            {
                "term": entry["term"],
                "plain_definition": entry["plain_definition"],
                "why_it_matters_here": entry["why_it_matters_here"],
            }
        )
        seen.add(entry["term"])
    return terms[:4]


def misconception_warnings(
    question: str,
    *,
    intent: str = "",
    text_blob: str = "",
) -> list[str]:
    """Shared misconception rules usable by both interpreter and chat paths.

    When *intent* is provided (interpreter path) it drives the selection.
    When only *question* / *text_blob* are available (chat path) text-matching
    is used as a fallback so the same canonical rules apply everywhere.
    """
    resolved_intent = intent.strip().lower() if intent else ""
    lowered_q = question.lower()
    lowered_text = text_blob.lower() if text_blob else ""
    notes: list[str] = []

    if resolved_intent == "cohort_meaning" or (
        not resolved_intent and ("cohort" in lowered_q or "cohort average" in lowered_text)
    ):
        notes.append("The cohort average is not a physical well.")
        notes.append("An average can hide wells that are moving in opposite directions.")

    if resolved_intent == "risk_explanation" or (
        not resolved_intent and ("risk" in lowered_q or "screening risk" in lowered_text)
    ):
        notes.append("High screening risk is not a forecast.")

    if resolved_intent == "shallow_deep_comparison" or (
        not resolved_intent
        and any(term in lowered_q for term in ("shallow", "deep", "confined", "unconfined"))
    ):
        notes.append("Shallow versus deep comparison does not prove hydraulic connection.")

    if (
        resolved_intent in {"fastest_changing", "general", "risk_explanation"}
        or _is_causal_question(question)
        or (not resolved_intent and "drawdown" in lowered_text)
    ):
        notes.append("A falling line is not proof of causation.")

    return list(dict.fromkeys(notes))[:4]


def _misconceptions_to_avoid(
    question: str,
    pack: dict[str, Any],
    intent_answer: dict[str, Any],
) -> list[str]:
    del pack
    return misconception_warnings(
        question,
        intent=str(intent_answer.get("question_intent") or "general"),
    )


def _progression_seed_from_interpretation(
    question: str,
    pack: dict[str, Any],
    interpretive_sections: dict[str, Any],
    intent_answer: dict[str, Any],
    follow_up_questions: list[str],
    answer_text: str,
    reasoning_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "question": question,
        "mode": "chart_interpreter",
        "question_intent": intent_answer.get("question_intent"),
        "direct_answer": intent_answer.get("direct_answer") or answer_text,
        "answer_text": answer_text,
        "supporting_evidence": intent_answer.get("supporting_evidence") or [],
        "caveat": intent_answer.get("caveat")
        or (interpretive_sections.get("confidence_notes") or [None])[0],
        "evidence_needed": interpretive_sections.get("evidence_needed") or [],
        "follow_up_questions": follow_up_questions,
        "well_names": [
            well.get("name")
            for well in pack.get("wells", [])[:8]
            if isinstance(well, dict) and well.get("name")
        ],
        "wells": pack.get("wells") or [],
        "divergent_pairs": (pack.get("cross_well") or {}).get("divergent_pairs") or [],
        "supply_units": (pack.get("supply_interpretation") or {}).get("supply_units") or [],
        "date_references": re.findall(r"\b(?:19|20)\d{2}\b", f"{question} {answer_text}")[:4],
        "meaning_brief": interpretive_sections.get("meaning_brief") or {},
        "reasoning_trace": reasoning_trace or [],
    }


def _build_explainer_seed(
    question: str,
    pack: dict[str, Any],
    selected_claims: list[NumericClaim],
    interpretive_sections: dict[str, Any],
    intent_answer: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact deterministic seed for explainer-style LLM synthesis."""
    meaning_brief = interpretive_sections.get("meaning_brief") or {}
    intent = str(intent_answer.get("question_intent") or "general")
    seed: dict[str, Any] = {
        "question": question,
        "question_intent": intent,
        "direct_answer": intent_answer.get("direct_answer", ""),
        "supporting_evidence": (intent_answer.get("supporting_evidence") or [])[:3],
        "meaning_brief": {
            "headline": meaning_brief.get("headline", ""),
            "plain_language": meaning_brief.get("plain_language", ""),
            "why_it_matters": meaning_brief.get("why_it_matters", ""),
            "next_best_check": meaning_brief.get("next_best_check", ""),
        },
        "possible_drivers": (interpretive_sections.get("possible_drivers") or [])[:4],
        "evidence_needed": (interpretive_sections.get("evidence_needed") or [])[:4],
        "confidence_notes": (interpretive_sections.get("confidence_notes") or [])[:1],
        "numeric_claims": [claim.model_dump() for claim in selected_claims[:4]],
        "site_names": [
            str(well.get("name")) for well in pack.get("wells", [])[:8] if well.get("name")
        ],
        "allowed_citation_urls": [
            str(citation.get("url"))
            for citation in _citations_from_pack(pack)
            if citation.get("url")
        ][:8],
        "guardrails": [
            "Start with the answer, not metadata about the chart.",
            "Explain what the numbers mean in plain language.",
            "Do not mention site IDs, chart-context labels, or internal field names.",
            "Do not claim causation from the chart alone.",
        ],
    }
    # --- Intent-specific focus data for the LLM ---
    if intent == "fastest_changing":
        fastest = intent_answer.get("fastest_decline") or {}
        strongest_rise = intent_answer.get("strongest_rise") or {}
        seed["explainer_shape"] = [
            "Name the fastest-changing well and its annual rate first.",
            "Compare it with the next most negative or strongest rising well.",
            "Explain what that contrast says about the chart as a whole.",
            "Close with a non-causal caveat grounded in the deterministic record.",
        ]
        seed["intent_focus"] = {
            "fastest_decline_name": fastest.get("name"),
            "fastest_decline_rate_ft_yr": fastest.get("annual_change_ft_yr"),
            "strongest_rise_name": strongest_rise.get("name"),
            "strongest_rise_rate_ft_yr": strongest_rise.get("annual_change_ft_yr"),
            "cohort_mean_rate_ft_yr": next(
                (
                    claim.value
                    for claim in selected_claims
                    if claim.site == "cohort" and claim.source == "mean_annual_change_ft_yr"
                ),
                None,
            ),
        }

    # --- Enrichment: surface computed analytics the LLM can weave into prose ---
    changepoints = (pack.get("cross_well") or {}).get("changepoints") or []
    if changepoints:
        seed["changepoints"] = [
            {
                "well": cp.get("name"),
                "split_date": cp.get("split_date"),
                "pre_rate_ft_yr": cp.get("pre_annual_rate_ft_yr"),
                "post_rate_ft_yr": cp.get("post_annual_rate_ft_yr"),
            }
            for cp in changepoints[:3]
            if cp.get("split_date")
        ]

    seasonal_highlights = []
    for site in (pack.get("sites") or [])[:6]:
        s = site.get("seasonal") or {}
        amp = s.get("seasonal_amplitude_ft")
        if amp is not None and amp > 0.5:
            seasonal_highlights.append(
                {
                    "well": site.get("name"),
                    "amplitude_ft": round(amp, 1),
                    "wet_mean_ft": (
                        round(s["wet_season_mean"], 1)
                        if s.get("wet_season_mean") is not None
                        else None
                    ),
                    "dry_mean_ft": (
                        round(s["dry_season_mean"], 1)
                        if s.get("dry_season_mean") is not None
                        else None
                    ),
                }
            )
    if seasonal_highlights:
        seed["seasonal_highlights"] = seasonal_highlights[:3]

    divergent_pairs = (pack.get("cross_well") or {}).get("divergent_pairs") or []
    if divergent_pairs:
        seed["divergent_pairs"] = [
            {
                "well_a": p.get("site_a", {}).get("name"),
                "well_b": p.get("site_b", {}).get("name"),
                "gap_ft_yr": round(p.get("divergence_magnitude", 0), 3),
            }
            for p in divergent_pairs[:2]
        ]

    prior_context = pack.get("prior_context") or {}
    if prior_context:
        seed["prior_context"] = prior_context

    return seed


def _build_structured_llm_messages(
    question: str,
    pack: dict[str, Any],
    explainer_seed: dict[str, Any],
    provider_name: str,
) -> list[tuple[str, str]]:
    """Build compact explainer-oriented LLM messages without dumping the raw pack."""
    prompt_payload = {
        "question": question,
        "provider": provider_name,
        "chart_title": (pack.get("chart_context") or {}).get("chart_id")
        or ((pack.get("chart_context") or {}).get("summary_metrics") or {}).get("title"),
        "deterministic_explainer_seed": explainer_seed,
        "style_requirements": [
            "Answer like an explainer for a curious reader.",
            "Use the deterministic explainer seed as the source of truth.",
            "Keep the answer plain-language and grounded.",
            "Connect data points to each other — what pattern matters, what stands out, "
            "what would a hydrogeologist notice first.",
            "Avoid summary-echo phrasing such as: "
            + ", ".join(f"'{phrase}'" for phrase in EXPLAINER_ECHO_PHRASES),
        ],
        "output_requirements": {
            "answer": "2-4 sentences of explainer prose",
            "what_to_notice": (
                "1-2 sentences: the single most important pattern in this data. "
                "What would jump out to someone reading the chart for the first time? "
                "Reference specific wells or rates from the seed."
            ),
            "why_it_matters": (
                "1-2 sentences: why this pattern matters for water resources. "
                "Connect the observed signal to real-world consequences — supply, "
                "sustainability, monitoring priority — without claiming causation."
            ),
            "numeric_claims": "Include only deterministic values that you actually used",
            "citations": "Use only allowed citation URLs",
            "grounding_status": "Return grounded when the answer stays within the seed",
        },
    }
    human_prompt = (
        "Write a grounded explainer answer from this deterministic seed.\n\n"
        "Do not echo chart-summary metadata. Do not mention site IDs. "
        "Do not dump field labels.\n\n"
        f"{json.dumps(prompt_payload, indent=2, sort_keys=True)}\n\n"
        "Return a grounded InterpretationResult."
    )
    return [("system", INTERPRETER_PROMPT_HEAD), ("human", human_prompt)]


def _has_rate_language(text: str) -> bool:
    lowered = text.lower()
    return (
        "ft/yr" in lowered
        or "feet per year" in lowered
        or "foot per year" in lowered
        or "per year" in lowered
    )


def _sentence_count(text: str) -> int:
    return len([part for part in re.split(r"[.!?]+", text) if part.strip()])


def _llm_answer_validation_flags(
    question: str,
    answer: str,
    explainer_seed: dict[str, Any],
) -> list[str]:
    """Return rejection flags for weak explainer-style LLM answers."""
    del question
    lowered = " ".join(answer.lower().split())
    flags: list[str] = []
    if not lowered:
        return ["llm_explainer_empty_answer"]
    if any(phrase in lowered for phrase in EXPLAINER_ECHO_PHRASES):
        flags.append("llm_explainer_summary_echo")
    if re.search(r"\b\d{15}\b", answer):
        flags.append("llm_explainer_site_id_dump")
    if any(label in lowered for label in EXPLAINER_LABEL_PHRASES):
        flags.append("llm_explainer_label_dump")
    if _sentence_count(answer) < 2:
        flags.append("llm_explainer_too_thin")

    intent = str(explainer_seed.get("question_intent") or "general")
    if intent == "fastest_changing":
        focus = explainer_seed.get("intent_focus") or {}
        fastest_name = str(focus.get("fastest_decline_name") or "").lower()
        strongest_rise_name = str(focus.get("strongest_rise_name") or "").lower()
        if fastest_name and fastest_name not in lowered:
            flags.append("llm_explainer_missing_fastest_well")
        if not _has_rate_language(answer):
            flags.append("llm_explainer_missing_rate_language")
        if strongest_rise_name and strongest_rise_name not in lowered and "rising" not in lowered:
            flags.append("llm_explainer_missing_comparison")
        if not any(
            term in lowered
            for term in (
                "means",
                "shows",
                "matters",
                "because",
                "contrast",
                "cohort",
                "screening",
                "overall",
            )
        ):
            flags.append("llm_explainer_missing_meaning")
    elif intent == "cohort_meaning":
        if "cohort" not in lowered and "average" not in lowered:
            flags.append("llm_explainer_missing_cohort_reference")
        if "group" not in lowered and "not a physical well" not in lowered:
            flags.append("llm_explainer_missing_group_meaning")
    elif intent == "risk_explanation":
        if "screening risk" not in lowered and "risk" not in lowered:
            flags.append("llm_explainer_missing_risk_reference")
    elif intent == "shallow_deep_comparison":
        if "shallow" not in lowered or "deep" not in lowered:
            flags.append("llm_explainer_missing_depth_comparison")
    return flags


def _deterministic_result_from_pack(
    question: str,
    pack: dict[str, Any],
) -> InterpretationResult:
    numeric_claims = _numeric_claims_from_pack(pack)
    citations = _citations_from_pack(pack)
    if not pack.get("site_ids") or not numeric_claims:
        return InterpretationResult(
            answer=(
                "The available evidence does not support a confident "
                "interpretation at this time."
            ),
            numeric_claims=[],
            citations=citations,
            evidence_used={"metric_keys": [], "rag_doc_ids": []},
            grounding_status="refused",
            follow_up_questions=[
                "Which chart or wells should I use as evidence?",
                "Can you first generate a chart for the location or wells?",
            ],
            guardrail_flags=["missing_chart_context"],
        )

    selected_claims = _select_relevant_claims(question, numeric_claims)
    interpretive_sections = _build_interpretive_sections(question, pack, selected_claims)
    intent_answer = _build_intent_answer(question, pack, interpretive_sections)
    guardrail_flags: list[str] = []
    if _is_causal_question(question):
        guardrail_flags.append("causation_not_supported")

    return InterpretationResult(
        answer=intent_answer["answer"],
        numeric_claims=selected_claims,
        citations=citations,
        evidence_used={
            "metric_keys": sorted(
                {claim.source for claim in selected_claims} | {"cross_well", "chart_explainability"}
            ),
            "rag_doc_ids": [
                snippet.get("doc_id") for snippet in pack.get("rag_snippets", []) if snippet
            ],
            "site_ids": pack.get("site_ids", []),
            **intent_answer,
        },
        grounding_status="grounded",
        follow_up_questions=(
            _followups_from_hydro_context(pack)
            or pack.get("explainability", {}).get(
                "suggested_questions",
                [
                    "Which highlighted well is changing fastest?",
                    "What outside data would help test a possible cause?",
                ],
            )
        )[:4],
        guardrail_flags=guardrail_flags,
    )


def _reconcile_llm_numeric_claims(
    llm_claims: list[NumericClaim],
    pack: dict[str, Any],
    tolerance: float = 0.1,
) -> tuple[list[NumericClaim], list[str]]:
    """Cross-check LLM numeric claims against the deterministic EvidencePack.

    Replaces any value that disagrees with the deterministic metric by more
    than ``tolerance`` with the deterministic value and records a guardrail flag.
    Drops claims whose ``source`` has no deterministic counterpart.
    """
    cross_well = pack.get("cross_well", {}) or {}
    truth: dict[tuple[str, str], float] = {}
    for metric in cross_well.get("per_site_metrics", []) or []:
        name = str(metric.get("name", "")).strip()
        if not name:
            continue
        truth[(name, "annual_change_ft_yr")] = float(metric.get("annual_change_ft_yr", 0.0))
        truth[(name, "net_change_ft")] = float(metric.get("net_change_ft", 0.0))
    cohort_mean = cross_well.get("mean_annual_change_ft_yr")
    if cohort_mean is not None:
        truth[("cohort", "mean_annual_change_ft_yr")] = float(cohort_mean)
    for summary in pack.get("aquifer_summaries", []) or []:
        label = str(summary.get("zone") or summary.get("aquifer") or "").strip()
        if label and summary.get("mean_annual_change") is not None:
            truth[(label, "aquifer_mean_annual_change_ft_yr")] = float(
                summary.get("mean_annual_change")
            )
    for summary in pack.get("supply_unit_summaries", []) or []:
        label = str(summary.get("zone") or summary.get("aquifer") or "").strip()
        if label and summary.get("mean_annual_change_ft_yr") is not None:
            truth[(label, "supply_unit_mean_annual_change_ft_yr")] = float(
                summary.get("mean_annual_change_ft_yr")
            )

    reconciled: list[NumericClaim] = []
    flags: list[str] = []
    for claim in llm_claims:
        key = (str(claim.site).strip(), str(claim.source).strip())
        anchor = truth.get(key)
        if anchor is None:
            flags.append(f"llm_claim_unknown_source:{claim.source}")
            continue
        if abs(float(claim.value) - anchor) > tolerance:
            flags.append(f"llm_claim_value_mismatch:{claim.site}:{claim.source}")
            reconciled.append(
                NumericClaim(
                    site=claim.site,
                    value=anchor,
                    unit=claim.unit,
                    source=claim.source,
                )
            )
        else:
            reconciled.append(claim)
    return reconciled, flags


def _coerce_structured_response(raw: Any) -> InterpretationResult:
    if isinstance(raw, InterpretationResult):
        return raw
    if hasattr(raw, "dict"):
        raw = raw.dict()
    elif hasattr(raw, "content") and isinstance(raw.content, dict):
        raw = raw.content
    if isinstance(raw, dict):
        return InterpretationResult(**raw)
    raise ValueError("LLM did not return an InterpretationResult")


def _invoke_structured_llm(
    question: str,
    pack: dict[str, Any],
    *,
    deadline: float | None = None,
) -> InterpretationResult | None:
    providers = []
    if os.getenv("DASHSCOPE_API_KEY"):
        providers.append(("qwen", os.getenv("GROUNDWATERGPT_INTERPRETER_MODEL", "qwen-plus")))
    providers.append(("ollama", os.getenv("SYNTHESIS_MODEL", "llama3.2")))

    numeric_claims = _numeric_claims_from_pack(pack)
    if not pack.get("site_ids") or not numeric_claims:
        return None
    selected_claims = _select_relevant_claims(question, numeric_claims)
    interpretive_sections = _build_interpretive_sections(question, pack, selected_claims)
    intent_answer = _build_intent_answer(question, pack, interpretive_sections)
    explainer_seed = _build_explainer_seed(
        question,
        pack,
        selected_claims,
        interpretive_sections,
        intent_answer,
    )

    if deadline is None:
        deadline = time.monotonic() + llm_timeout_seconds()

    for provider_name, model in providers:
        try:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                logger.warning(
                    "Chart interpreter skipped LLM polish because the 30s LLM budget was exhausted"
                )
                break
            from src.agent.llm_factory import LLMProvider, get_llm

            provider = LLMProvider(provider_name)
            llm_kwargs: dict[str, Any] = {"temperature": 0}
            if provider_name == "ollama":
                client_timeout = {"timeout": remaining}
                llm_kwargs.update(
                    {
                        "client_kwargs": client_timeout,
                        "sync_client_kwargs": client_timeout,
                        "async_client_kwargs": client_timeout,
                    }
                )
            else:
                llm_kwargs.update({"timeout": remaining, "max_retries": 0})
            llm = get_llm(provider=provider, model=model, **llm_kwargs)
            if hasattr(llm, "with_structured_output"):
                structured_llm = llm.with_structured_output(InterpretationResult)
                raw = invoke_with_llm_timeout(
                    lambda: structured_llm.invoke(
                        _build_structured_llm_messages(
                            question,
                            pack,
                            explainer_seed,
                            provider_name,
                        )
                    ),
                    timeout_seconds=max(0.0, deadline - time.monotonic()),
                    label=f"chart interpreter {provider_name}/{model}",
                )
                if raw is None:
                    continue
                result = _coerce_structured_response(raw)
                evidence_used = dict(result.evidence_used or {})
                evidence_used.setdefault("llm_provider", provider_name)
                evidence_used.setdefault("llm_model", model)
                evidence_used.setdefault("question_intent", intent_answer.get("question_intent"))
                evidence_used.setdefault("direct_answer", intent_answer.get("direct_answer"))
                evidence_used.setdefault(
                    "supporting_evidence", intent_answer.get("supporting_evidence", [])
                )
                result.evidence_used = evidence_used
                return result
        except Exception as exc:
            logger.debug("Chart interpreter %s path unavailable: %s", provider_name, exc)
            continue
    return None


def _grounded_to_interpretation_result(grounded: Any) -> InterpretationResult:
    answer_parts = [
        str(grounded.direct_answer or "").strip(),
        str(getattr(grounded, "what_matters_most", "") or "").strip(),
        str(grounded.why_it_matters or "").strip(),
    ]
    evidence_summary = list(getattr(grounded, "evidence_used_summary", []) or [])
    important_limits = list(getattr(grounded, "important_limits", []) or [])
    if evidence_summary:
        answer_parts.append(
            "Evidence used: " + " ".join(str(item).strip() for item in evidence_summary[:2] if item)
        )
    if important_limits:
        answer_parts.append(
            "Important limits: "
            + " ".join(str(item).strip() for item in important_limits[:2] if item)
        )
    numeric_claims = []
    for claim in grounded.numeric_claims:
        try:
            numeric_claims.append(
                NumericClaim(
                    site=str(claim.site),
                    value=float(claim.value),
                    unit=str(claim.unit),
                    source=str(claim.source),
                )
            )
        except Exception:
            continue
    return InterpretationResult(
        answer=" ".join(part for part in answer_parts if part),
        numeric_claims=numeric_claims,
        citations=[],
        evidence_used={
            "llm_provider": getattr(grounded, "llm_provider", ""),
            "llm_model": getattr(grounded, "llm_model", ""),
            "grounded_reasoning": True,
            "framing": getattr(getattr(grounded, "framing", None), "model_dump", lambda: {})(),
            "answer_moves_completed": list(getattr(grounded, "answer_moves_completed", []) or []),
            "evidence_used_summary": evidence_summary,
            "important_limits": important_limits,
        },
        grounding_status=str(getattr(grounded, "grounding_status", "grounded")),
        follow_up_questions=list(getattr(grounded, "follow_up_questions", []) or []),
        guardrail_flags=[],
        what_to_notice=str(
            getattr(grounded, "what_matters_most", "") or getattr(grounded, "direct_answer", "")
        ).strip(),
        why_it_matters=str(getattr(grounded, "why_it_matters", "")).strip(),
    )


def _claim_citations_from_result(
    result: InterpretationResult,
    pack: dict[str, Any],
) -> list[dict[str, Any]]:
    citations = result.citations or _citations_from_pack(pack)
    primary_citation = citations[0] if citations else {}
    claims = [
        {
            "claim_id": "claim_001",
            "claim": result.answer,
            "claim_type": "chart_interpretation",
            "confidence": 0.72 if result.grounding_status == "grounded" else 0.45,
            "citations": citations[:5],
        }
    ]
    for idx, claim in enumerate(result.numeric_claims[:8], start=2):
        site_id = None
        for site in pack.get("sites", []):
            if site.get("name") == claim.site:
                site_id = site.get("site_id")
                break
        citation = (
            {
                "url": _usgs_site_url(str(site_id)),
                "trust_level": "verified",
                "verified": True,
            }
            if site_id
            else primary_citation
        )
        claims.append(
            {
                "claim_id": f"claim_{idx:03d}",
                "claim": f"{claim.site} {claim.source}: {claim.value:+.3f} {claim.unit}.",
                "claim_type": "chart_numeric",
                "confidence": 0.85,
                "citations": [citation] if citation else [],
            }
        )
    return claims


def interpret_with_context(
    question: str,
    chart_context: dict | None,
    turn_history: list[dict] | None,
    audience: str | None = None,
    allow_llm_synthesis: bool = True,
) -> dict[str, Any]:
    """Interpret a chart-bound follow-up using deterministic evidence and optional LLM."""
    del audience  # The 5.4 prompt is deliberately tone-neutral.
    clean_question = str(question or "").strip()
    trimmed_history = list(turn_history or [])[-4:]
    pack = build_evidence_pack(clean_question, chart_context, trimmed_history)
    llm_rejection_flags: list[str] = []
    reasoning_trace: list[dict[str, Any]] = []
    reasoning_source = "deterministic"
    grounded_result = None
    derived_frame = derive_question_frame(clean_question, pack)

    numeric_claims = _numeric_claims_from_pack(pack)
    selected_claims = _select_relevant_claims(clean_question, numeric_claims)
    interpretive_sections = _build_interpretive_sections(clean_question, pack, selected_claims)
    intent_answer = _build_intent_answer(clean_question, pack, interpretive_sections)
    explainer_seed = _build_explainer_seed(
        clean_question,
        pack,
        selected_claims,
        interpretive_sections,
        intent_answer,
    )
    rubric = _rubric_for_intent(str(intent_answer.get("question_intent") or "general"))

    llm_result = None
    llm_deadline = time.monotonic() + llm_timeout_seconds()
    if allow_llm_synthesis and _grounded_reasoning_enabled():
        try:
            grounded_result = invoke_grounded_reasoning(
                clean_question,
                pack,
                rubric=rubric,
                deadline=llm_deadline,
            )
        except Exception as exc:
            logger.debug("Chart interpreter grounded reasoning failed: %s", exc)
            grounded_result = None
        if grounded_result is not None:
            llm_result = _grounded_to_interpretation_result(grounded_result)
            reasoning_trace = [step.model_dump() for step in grounded_result.reasoning_steps]
            reasoning_source = "grounded_llm"

    if llm_result is None:
        try:
            if allow_llm_synthesis:
                invoke_params = inspect.signature(_invoke_structured_llm).parameters
                if "deadline" in invoke_params:
                    llm_result = _invoke_structured_llm(
                        clean_question,
                        pack,
                        deadline=llm_deadline,
                    )
                else:
                    llm_result = _invoke_structured_llm(clean_question, pack)
            else:
                llm_result = None
        except Exception as exc:
            logger.debug("Chart interpreter structured LLM failed: %s", exc)
            llm_result = None
    if llm_result is not None:
        reconciled_claims, reconciliation_flags = _reconcile_llm_numeric_claims(
            llm_result.numeric_claims, pack
        )
        llm_result.numeric_claims = reconciled_claims
        if reconciliation_flags:
            llm_result.guardrail_flags = list(llm_result.guardrail_flags) + reconciliation_flags
        if reasoning_source != "grounded_llm":
            llm_rejection_flags = _llm_answer_validation_flags(
                clean_question, llm_result.answer, explainer_seed
            )
            if not llm_result.answer.strip() or llm_rejection_flags:
                llm_result = None
            else:
                reasoning_source = "llm_polish"
    result = llm_result or _deterministic_result_from_pack(clean_question, pack)
    if llm_result is None and llm_rejection_flags:
        result.guardrail_flags = list(result.guardrail_flags) + llm_rejection_flags
        reasoning_source = "deterministic"

    claim_citations = _claim_citations_from_result(result, pack)
    claim_verdicts = _build_claim_verdicts(claim_citations)
    section_confidence = _build_section_confidence_from_claims(claim_citations)
    citation_integrity = _build_citation_integrity(claim_citations, section_confidence)
    numeric_claims = [claim.model_dump() for claim in result.numeric_claims]
    citations = result.citations or _citations_from_pack(pack)
    llm_evidence = result.evidence_used or {}
    hydro_concepts = _hydro_concepts_from_pack(pack)
    hydro_caveats = _hydro_caveats_from_pack(pack)
    rag_doc_ids = [snippet.get("doc_id") for snippet in pack.get("rag_snippets", []) if snippet]
    selected_claims = result.numeric_claims or _select_relevant_claims(
        clean_question,
        _numeric_claims_from_pack(pack),
    )
    interpretive_sections = _build_interpretive_sections(clean_question, pack, selected_claims)
    intent_payload = _build_intent_answer(clean_question, pack, interpretive_sections)
    if grounded_result is not None:
        intent_payload["direct_answer"] = grounded_result.direct_answer or intent_payload.get(
            "direct_answer"
        )
        if grounded_result.why_it_matters:
            interpretive_sections["management_implications"] = [grounded_result.why_it_matters]
        if grounded_result.what_matters_most:
            interpretive_sections["meaning_brief"]["headline"] = grounded_result.what_matters_most
    intent_fields = {key: value for key, value in intent_payload.items() if key != "answer"}
    learner_brief = _build_learner_brief(
        pack,
        interpretive_sections,
        intent_payload,
        result.follow_up_questions[:4],
        llm_result=llm_result,
    )
    terms_to_know = _terms_to_know(clean_question, pack, interpretive_sections, intent_payload)
    misconceptions = _misconceptions_to_avoid(clean_question, pack, intent_payload)
    progression = build_evidence_guided_progression(
        _progression_seed_from_interpretation(
            clean_question,
            pack,
            interpretive_sections,
            intent_payload,
            result.follow_up_questions[:4],
            result.answer,
            reasoning_trace=reasoning_trace,
        ),
        allow_llm_rewrite=allow_llm_synthesis
        and (
            llm_result is not None
            or os.getenv("GROUNDWATERGPT_ENABLE_PROGRESSION_LLM", "").strip().lower()
            in {"1", "true", "yes", "on"}
        ),
        reasoning_trace=reasoning_trace,
    )
    if progression.get("follow_up_questions"):
        learner_brief["next_best_question"] = progression["follow_up_questions"][0]
    active_frame = (
        grounded_result.framing.model_dump()
        if grounded_result is not None
        else derived_frame.model_dump()
    )
    interpretation_details = {
        "aquifer_summaries": (
            grounded_result.aquifer_summaries
            if grounded_result is not None
            else pack.get("aquifer_summaries", [])
        ),
        "supply_interpretation": pack.get("supply_interpretation"),
        "supply_unit_summaries": pack.get("supply_unit_summaries"),
        "well_summaries": pack.get("well_summaries"),
        "comparison_features": pack.get("comparison_features"),
        "risk_level": (pack.get("cross_well") or {}).get("risk_level"),
        "location_hydro_context": pack.get("location_hydro_context") or {},
    }
    interpretation_response = {
        "schema_version": "interpretation_response_v1",
        "question": clean_question,
        "audience": "general",
        "interpretation": result.answer,
        "answer": result.answer,
        "reasoning_trace": reasoning_trace,
        "reasoning_source": reasoning_source,
        "framing": active_frame,
        "scope_type": active_frame.get("scope_type"),
        "focus_entities": active_frame.get("focus_entities", []),
        "comparison_entities": active_frame.get("comparison_entities", []),
        "question_goal": active_frame.get("question_goal"),
        "answer_moves_completed": (
            list(getattr(grounded_result, "answer_moves_completed", []) or [])
            if grounded_result is not None
            else []
        ),
        "numeric_claims": numeric_claims,
        "citations": citations,
        "evidence": citations,
        "evidence_used": {
            **(result.evidence_used or {}),
            "rag_doc_ids": (result.evidence_used or {}).get("rag_doc_ids") or rag_doc_ids,
            "enriched_rag_query": pack.get("enriched_rag_query"),
        },
        "grounding_status": {
            "uses_chart_context": bool(pack.get("site_ids")),
            "uses_usgs_data": bool(pack.get("site_ids")),
            "invented_measurements_allowed": False,
            "interpreter_status": result.grounding_status,
            "has_llm_synthesis": llm_result is not None,
            "llm_provider": llm_evidence.get("llm_provider") if llm_result is not None else None,
            "llm_model": llm_evidence.get("llm_model") if llm_result is not None else None,
            "citation_integrity_passed": citation_integrity.get("passed", False),
        },
        "guardrail_flags": result.guardrail_flags,
        "follow_up_questions": progression["follow_up_questions"],
        "follow_up_groups": progression["follow_up_groups"],
        "next_goal": progression["next_goal"],
        "progression_source": progression["progression_source"],
        "progression_guardrail_flags": progression["progression_guardrail_flags"],
        "learner_brief": learner_brief,
        "terms_to_know": terms_to_know,
        "misconceptions_to_avoid": misconceptions,
        "groundwater_concepts": hydro_concepts,
        "aquifer_summaries": interpretation_details["aquifer_summaries"],
        "supply_interpretation": interpretation_details["supply_interpretation"],
        "supply_unit_summaries": interpretation_details["supply_unit_summaries"],
        "well_summaries": interpretation_details["well_summaries"],
        "comparison_features": interpretation_details["comparison_features"],
        "interpretation_details": interpretation_details,
        **interpretive_sections,
        **intent_fields,
        "chart_context": {
            "summary": pack.get("explainability", {}).get("summary"),
            "how_to_read": pack.get("explainability", {}).get("how_to_read", []),
            "data_contract": pack.get("explainability", {}).get("data_contract", []),
            "llm_role": pack.get("explainability", {}).get("llm_role"),
        },
        "key_observations": pack.get("insights", [])[:6],
        "data_references": [
            {
                "site_id": well.get("site_id"),
                "well_name": well.get("name"),
                "borehole_code": well.get("borehole_code"),
                "aquifer": well.get("aquifer"),
                "aquifer_zone": well.get("aquifer_zone"),
                "county": well.get("county"),
                "lat": well.get("lat"),
                "lng": well.get("lng"),
                "record_start": well.get("record_start"),
                "record_end": well.get("record_end"),
                "source": "USGS NWIS",
                "url": _usgs_site_url(str(well.get("site_id"))),
            }
            for well in pack.get("wells", [])[:12]
        ],
        "limits": [
            "This is a chart-bound interpretation of observed monitoring records.",
            "The available record does not show causation by itself.",
            "Causal attribution requires external covariates and modeling evidence.",
            *hydro_caveats,
            *(
                grounded_result.limitations
                if grounded_result is not None
                else (pack.get("supply_interpretation") or {}).get("limitations", [])
            ),
        ],
    }
    return {
        "response": result.answer,
        "context": "Chart-context interpretation",
        "sources": [citation.get("url") for citation in citations if citation.get("url")],
        "mode": "chart_interpreter",
        "status": "ok",
        "wells": pack.get("wells", []),
        "claim_citations": claim_citations,
        "claim_verdicts": claim_verdicts,
        "claim_verdict_summary": _build_claim_verdict_summary(claim_verdicts),
        "citation_summary": _build_citation_summary(claim_citations),
        "section_confidence": section_confidence,
        "citation_integrity": citation_integrity,
        "hallucination_guardrail": {
            "strategy": "chart_context_interpreter",
            "removed_uncited_factual_sentences": 0,
            "all_factual_claims_cited": bool(claim_citations),
            "has_llm_synthesis": llm_result is not None,
            "guardrail_flags": result.guardrail_flags,
        },
        "interpretation_details": interpretation_details,
        "interpretation_response": interpretation_response,
        "next_goal": progression["next_goal"],
        "follow_up_groups": progression["follow_up_groups"],
        "follow_up_questions": progression["follow_up_questions"],
        "progression_source": progression["progression_source"],
        "progression_guardrail_flags": progression["progression_guardrail_flags"],
        "numeric_claims": numeric_claims,
        "chart_context_used": chart_context or {},
        "turn_history_used": trimmed_history,
    }
