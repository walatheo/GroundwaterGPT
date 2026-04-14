"""Helpers for synthesizing chart payloads from agent research results."""

from __future__ import annotations

import re
from typing import Any

from api.routes._detection import _detect_aquifer, _detect_location, _load_site_timeseries
from api.routes._site_analysis import _build_chart_payload, _cross_well_analysis
from api.site_metadata import SITE_METADATA

_SITE_ID_RE = re.compile(r"\b\d{15}\b")


def _append_site_id(candidate: Any, site_ids: list[str], seen: set[str]) -> None:
    """Append a valid site ID once, preserving discovery order."""
    if not isinstance(candidate, str):
        return
    if candidate in SITE_METADATA and candidate not in seen:
        site_ids.append(candidate)
        seen.add(candidate)


def _collect_site_ids(value: Any, site_ids: list[str], seen: set[str]) -> None:
    """Recursively walk nested result data for site identifiers."""
    if value is None:
        return

    if isinstance(value, dict):
        for key in ("site_id", "site_ids", "selected_site_ids"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                for site_id in candidate:
                    _append_site_id(site_id, site_ids, seen)
            else:
                _append_site_id(candidate, site_ids, seen)
        for nested in value.values():
            _collect_site_ids(nested, site_ids, seen)
        return

    if isinstance(value, list):
        for item in value:
            _collect_site_ids(item, site_ids, seen)
        return

    if isinstance(value, str):
        for match in _SITE_ID_RE.findall(value):
            _append_site_id(match, site_ids, seen)


def _extract_site_ids_from_agent_result(result: dict[str, Any]) -> list[str]:
    """Extract referenced site IDs from agent-produced artifacts."""
    site_ids: list[str] = []
    seen: set[str] = set()

    for key in ("chart_specs", "tool_trace", "wells", "sources"):
        _collect_site_ids(result.get(key), site_ids, seen)

    return site_ids


def _load_sites_for_ids(site_ids: list[str]) -> list[dict[str, Any]]:
    """Load metadata + timeseries for a set of site IDs."""
    sites: list[dict[str, Any]] = []
    for site_id in site_ids:
        meta = SITE_METADATA.get(site_id)
        if not meta:
            continue
        series = _load_site_timeseries(site_id)
        if series is None:
            continue
        sites.append(
            {
                "site_id": site_id,
                "name": meta.get("name", site_id),
                "county": meta.get("county", "Florida"),
                "aquifer": meta.get("aquifer", "Unknown Aquifer"),
                "aquifer_type": meta.get("aquifer_type", "unconfined"),
                "confined": meta.get("confined", False),
                "aquifer_zone": meta.get("aquifer_zone", ""),
                "aquifer_zone_depth_range_ft": meta.get("aquifer_zone_depth_range_ft", [0, 100]),
                "aquifer_description": meta.get("aquifer_description", ""),
                "well_depth_ft": meta.get("well_depth_ft"),
                "lat": meta.get("lat"),
                "lng": meta.get("lng"),
                "series": series,
            }
        )
    return sites


def _infer_location_label(result: dict[str, Any], sites: list[dict[str, Any]]) -> str:
    """Infer a human-readable label for a synthesized chart title."""
    plan = result.get("research_plan") or {}
    question = ""
    if isinstance(plan, dict):
        question = str(plan.get("main_question") or plan.get("original_query") or "").strip()

    if question:
        aq_hit = _detect_aquifer(question)
        if aq_hit is not None:
            return aq_hit[1]

        loc = _detect_location(question)
        if loc is not None:
            return loc[2]

    counties = {str(site.get("county", "")).strip() for site in sites if site.get("county")}
    if len(counties) == 1:
        county = next(iter(counties))
        if county and county.lower() != "florida":
            return county

    aquifers = {str(site.get("aquifer", "")).strip() for site in sites if site.get("aquifer")}
    if len(aquifers) == 1:
        aquifer = next(iter(aquifers))
        if aquifer:
            return aquifer

    return "Agent-selected wells"


def attach_chart_from_agent_result(result: dict[str, Any]) -> dict[str, Any]:
    """Attach a deterministic chart when the agent names sites but omits chart JSON."""
    if result.get("chart"):
        return result

    site_ids = _extract_site_ids_from_agent_result(result)
    if not site_ids:
        return result

    sites = _load_sites_for_ids(site_ids)
    if not sites:
        return result

    cross_well = _cross_well_analysis(sites) if len(sites) >= 2 else None
    result["chart"] = _build_chart_payload(
        sites,
        _infer_location_label(result, sites),
        cross_well=cross_well,
    )
    return result
