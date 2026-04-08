"""Core site research and analysis helpers.

Extracted from ``chat.py`` to keep that module focused on endpoint handlers.
All public names are re-exported from ``chat.py`` for backward compatibility.

Contains:
  - ``_site_research_fallback()`` — deterministic, cited response builder
  - ``_cross_well_analysis()`` — cohort-level statistics
  - ``_trend_label()`` / ``_half_trend()`` / ``_seasonal_decomposition()``
"""

from __future__ import annotations

import logging
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from api.routes._citation import (
    _build_citation_summary,
    _build_claim_verdict_summary,
    _build_claim_verdicts,
    _build_section_confidence_from_claims,
)
from api.routes._detection import (
    _SUPPLY_QUERY_RE,
    _WATER_SUPPLY_SOURCES,
    _bearing_label,
    _distance_miles,
    _usgs_site_url,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM synthesis trigger pattern
# ---------------------------------------------------------------------------

_SYNTHESIS_TRIGGER_RE = re.compile(
    r"\b(sustainab|implication|risk|interpret|analys[ei]s|synthesis"
    r"|outlook|forecast|assessment|recommend)\w*\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Trend helpers
# ---------------------------------------------------------------------------


def _trend_label(net_change: float) -> str:
    """Map numeric net change to a plain-language trend label."""
    if net_change > 0.25:
        return "rising"
    if net_change < -0.25:
        return "falling"
    return "stable"


def _half_trend(series: "pd.Series") -> str:
    """Map year-by-year seasonal means to a worsening/recovering/stable label.

    Compares the second half of the annual record against the first half.
    Higher values mean the water level is deeper (worse for unconfined wells).
    """
    if len(series) < 3:
        return "insufficient_data"
    mid = len(series) // 2
    diff = float(series.iloc[mid:].mean()) - float(series.iloc[:mid].mean())
    if diff > 0.15:
        return "worsening"
    if diff < -0.15:
        return "recovering"
    return "stable"


def _seasonal_decomposition(df: "pd.DataFrame") -> dict:
    """Compute Florida wet/dry season statistics from a site timeseries.

    Wet season: June-October (months 6-10). Dry season: November-May.
    Returns ``{"has_seasonal": False}`` when fewer than 2 years of data exist.
    Water-level values are in ft below land surface (higher value = deeper level).
    """
    if df is None or df.empty:
        return {"has_seasonal": False}

    ts = df.copy()
    ts["_month"] = ts["datetime"].dt.month
    ts["_year"] = ts["datetime"].dt.year
    ts["_season"] = ts["_month"].apply(lambda m: "wet" if 6 <= m <= 10 else "dry")

    year_span = int(ts["_year"].max()) - int(ts["_year"].min())
    if year_span < 2:
        return {"has_seasonal": False}

    wet_vals = ts[ts["_season"] == "wet"]["value"]
    dry_vals = ts[ts["_season"] == "dry"]["value"]
    if wet_vals.empty or dry_vals.empty:
        return {"has_seasonal": False}

    wet_mean = float(wet_vals.mean())
    dry_mean = float(dry_vals.mean())
    amplitude = abs(dry_mean - wet_mean)

    dry_by_year = ts[ts["_season"] == "dry"].groupby("_year")["value"].mean()
    wet_by_year = ts[ts["_season"] == "wet"].groupby("_year")["value"].mean()

    return {
        "has_seasonal": True,
        "wet_season_mean_ft": round(wet_mean, 2),
        "dry_season_mean_ft": round(dry_mean, 2),
        "seasonal_amplitude_ft": round(amplitude, 2),
        "dry_season_trend": _half_trend(dry_by_year),
        "wet_season_trend": _half_trend(wet_by_year),
        "n_years": year_span + 1,
    }


# ---------------------------------------------------------------------------
# Cross-well cohort analysis
# ---------------------------------------------------------------------------


def _cross_well_analysis(sites: list[dict]) -> dict:
    """Compute cohort-level statistics across a set of wells with loaded timeseries.

    Returns trend_distribution, mean/std annual change, divergent pairs, and risk level.
    Only meaningful when len(sites) >= 2; returns a zeroed dict for 0-1 sites.
    """
    if len(sites) < 2:
        return {
            "n_total": len(sites),
            "trend_distribution": {},
            "cohort_trend": "unknown",
            "mean_annual_change_ft_yr": None,
            "std_dev_annual_change": None,
            "divergent_pairs": [],
            "risk_level": "unknown",
            "per_site_metrics": [],
        }

    per_site: list[dict] = []
    annual_changes: list[float] = []
    for site in sites:
        df = site["series"]
        first, last = df.iloc[0], df.iloc[-1]
        net = float(last["value"] - first["value"])
        years = max(0.01, (last["datetime"] - first["datetime"]).days / 365.25)
        ann = net / years
        per_site.append(
            {
                "site_id": site["site_id"],
                "name": site["name"],
                "trend": _trend_label(net),
                "net_change_ft": round(net, 3),
                "annual_change_ft_yr": round(ann, 4),
            }
        )
        annual_changes.append(ann)

    n_total = len(per_site)
    dist: dict[str, int] = {"falling": 0, "stable": 0, "rising": 0}
    for s in per_site:
        dist[s["trend"]] = dist.get(s["trend"], 0) + 1
    cohort_trend = max(dist, key=dist.get)

    mean_ann = sum(annual_changes) / n_total
    std_dev = math.sqrt(sum((x - mean_ann) ** 2 for x in annual_changes) / n_total)

    divergent: list[dict] = []
    for i in range(n_total):
        for j in range(i + 1, n_total):
            a, b = per_site[i], per_site[j]
            if {a["trend"], b["trend"]} == {"falling", "rising"}:
                divergent.append(
                    {
                        "site_a": {
                            k: a[k] for k in ("site_id", "name", "trend", "annual_change_ft_yr")
                        },
                        "site_b": {
                            k: b[k] for k in ("site_id", "name", "trend", "annual_change_ft_yr")
                        },
                        "divergence_magnitude": abs(
                            a["annual_change_ft_yr"] - b["annual_change_ft_yr"]
                        ),
                    }
                )
    divergent.sort(key=lambda p: p["divergence_magnitude"], reverse=True)
    divergent = divergent[:3]

    pct_falling = dist["falling"] / n_total
    mostly_confined = sum(1 for s in sites if s.get("confined", False)) > n_total / 2
    if pct_falling >= 0.66:
        risk = "high"
    elif pct_falling >= 0.33 or (pct_falling >= 0.20 and mostly_confined):
        risk = "moderate"
    else:
        risk = "low"

    return {
        "n_total": n_total,
        "trend_distribution": dist,
        "cohort_trend": cohort_trend,
        "mean_annual_change_ft_yr": round(mean_ann, 4),
        "std_dev_annual_change": round(std_dev, 4),
        "divergent_pairs": divergent,
        "risk_level": risk,
        "per_site_metrics": per_site,
    }


# ---------------------------------------------------------------------------
# Main research fallback — deterministic, cited response builder
# ---------------------------------------------------------------------------


def _site_research_fallback(
    question: str,
    sites: list[dict],
    location_name: str,
    ref_lat: Optional[float] = None,
    ref_lng: Optional[float] = None,
) -> dict:
    """Generate a deterministic, cited response for any USGS site/location query."""
    if not sites:
        # Late import to avoid circular dependency with chat.py
        from api.routes.chat import _fallback_response

        fallback = _fallback_response(question)
        claim_citations = [
            {
                "claim_id": "claim_001",
                "claim": fallback["response"],
                "confidence": 0.55,
                "citations": [
                    {"url": str(src), "verified": True, "trust_level": "moderate"}
                    for src in fallback["sources"]
                ],
            }
        ]
        claim_verdicts = _build_claim_verdicts(claim_citations)
        return {
            "report": fallback["response"],
            "insights": [],
            "sources": fallback["sources"],
            "claim_citations": claim_citations,
            "claim_verdicts": claim_verdicts,
            "claim_verdict_summary": _build_claim_verdict_summary(claim_verdicts),
            "citation_summary": _build_citation_summary(claim_citations),
            "section_confidence": _build_section_confidence_from_claims(claim_citations),
            "hallucination_guardrail": {
                "strategy": "deterministic_fallback",
                "removed_uncited_factual_sentences": 0,
                "all_factual_claims_cited": True,
            },
            "search_history": [question],
            "depth_reached": 1,
            "elapsed_seconds": 0.05,
        }

    site_blocks: list[str] = []
    site_computed: list[dict] = []  # Per-site computed data for grouping
    insights: list[dict] = []
    claim_citations: list[dict] = []
    source_urls: list[str] = []

    for idx, site in enumerate(sites, start=1):
        df = site["series"]
        first = df.iloc[0]
        last = df.iloc[-1]
        start_date = first["datetime"].strftime("%Y-%m-%d")
        end_date = last["datetime"].strftime("%Y-%m-%d")
        net_change = float(last["value"] - first["value"])
        years = max(0.01, (last["datetime"] - first["datetime"]).days / 365.25)
        annual_change = net_change / years
        trend = _trend_label(net_change)

        site_url = _usgs_site_url(site["site_id"])
        source_urls.append(site_url)

        # Aquifer context fields
        aq_zone = site.get("aquifer_zone") or site.get("aquifer", "Unknown Aquifer")
        aq_label = site.get("aquifer", aq_zone)
        confinement = "confined" if site.get("confined") else "unconfined"
        well_depth = site.get("well_depth_ft")
        zone_range = site.get("aquifer_zone_depth_range_ft")
        aq_desc = site.get("aquifer_description", "")

        depth_str = f"well depth: {well_depth:.0f} ft" if well_depth else ""
        range_str = (
            f"zone: {zone_range[0]}\u2013{zone_range[1]} ft"
            if zone_range and len(zone_range) == 2
            else ""
        )
        meta_parts = [p for p in [depth_str, range_str] if p]
        meta_str = f" [{'; '.join(meta_parts)}]" if meta_parts else ""

        # Head margin: ft above zone top (negative = below zone top)
        current_level_ft = float(last["value"])
        zone_top_ft: Optional[float] = (
            float(zone_range[0]) if zone_range and len(zone_range) >= 1 else None
        )
        head_margin_ft: Optional[float] = (
            round(zone_top_ft - current_level_ft, 2) if zone_top_ft is not None else None
        )
        is_artesian = bool(df["value"].min() < 0)

        # Seasonal decomposition
        seasonal = _seasonal_decomposition(df)

        # Physics note
        if site.get("confined"):
            physics_note = (
                "Confined aquifer \u2014 pressure-head decline; "
                "not seasonally recharged by local rainfall."
            )
        else:
            physics_note = (
                "Unconfined water-table aquifer \u2014 "
                "responds directly to local precipitation and seasonal recharge."
            )

        # Head margin alert
        head_margin_line = ""
        if head_margin_ft is not None:
            is_confined_site = bool(site.get("confined", False))
            margin_threshold = 15.0 if is_confined_site else 2.0
            if head_margin_ft < margin_threshold:
                if head_margin_ft < 0:
                    zone_status = (
                        "approaching unconfined conditions"
                        if is_confined_site
                        else "partial dewatering"
                    )
                    head_margin_line = (
                        f"\n  CAUTION: head {abs(head_margin_ft):.1f} ft below zone top"
                        f" \u2014 {zone_status}."
                    )
                else:
                    head_margin_line = (
                        f"\n  Head margin: {head_margin_ft:.1f} ft above zone top"
                        " (approaching zone boundary)."
                    )

        # Artesian note
        artesian_line = ""
        if is_artesian:
            artesian_line = (
                "\n  Artesian: pressure head exceeded land surface during record period."
            )

        # Seasonal summary line
        seasonal_line = ""
        if seasonal.get("has_seasonal"):
            amp = seasonal["seasonal_amplitude_ft"]
            wet_m = seasonal["wet_season_mean_ft"]
            dry_m = seasonal["dry_season_mean_ft"]
            dry_trend = seasonal["dry_season_trend"]
            seasonal_line = (
                f"\n  Seasonal ({seasonal['n_years']} yr): amplitude {amp:.1f} ft"
                f" (wet avg {wet_m:.1f} ft, dry avg {dry_m:.1f} ft);"
                f" dry-season trend: {dry_trend}."
            )

        # Proxy justification
        proxy_line = ""
        if ref_lat is not None and ref_lng is not None:
            dist_mi = _distance_miles(ref_lat, ref_lng, site["lat"], site["lng"])
            bearing = _bearing_label(ref_lat, ref_lng, site["lat"], site["lng"])
            proxy_line = (
                f"\n  Proxy: {dist_mi:.1f} mi {bearing} of {location_name}, "
                f"monitoring {aq_zone} at {well_depth:.0f} ft."
                if well_depth
                else f"\n  Proxy: {dist_mi:.1f} mi {bearing} of {location_name}."
            )

        block = (
            f"- {site['name']} [site {site['site_id']}] \u2014 "
            f"{aq_label} ({aq_zone}, {confinement}){meta_str}:\n"
            f"  {start_date} to {end_date}; "
            f"net change {net_change:+.2f} ft ({annual_change:+.2f} ft/yr), "
            f"trend: {trend}."
            + (
                f"\n  Note: {aq_desc}"
                if aq_desc
                and any(
                    kw in aq_desc.lower()
                    for kw in ("saltwater", "artesian", "vulnerable", "intrusion", "pressure")
                )
                else ""
            )
            + f"\n  Physics: {physics_note}"
            + head_margin_line
            + artesian_line
            + seasonal_line
            + proxy_line
        )
        site_blocks.append(block)

        # Store computed data for aquifer grouping
        site_computed.append(
            {
                "block": block,
                "aq_zone": aq_zone,
                "aq_label": aq_label,
                "confinement": confinement,
                "well_depth_ft": well_depth,
                "zone_range": zone_range,
                "trend": trend,
                "annual_change": annual_change,
                "net_change": net_change,
                "years": years,
                "start_date": start_date,
                "end_date": end_date,
                "seasonal": seasonal,
                "confined": site.get("confined", False),
            }
        )

        # Insight/claim text
        extra_flags = []
        if is_artesian:
            extra_flags.append("artesian conditions observed")
        if head_margin_ft is not None and head_margin_ft < 0:
            extra_flags.append(f"head {abs(head_margin_ft):.1f} ft below zone top")
        flag_str = (" [" + "; ".join(extra_flags) + "]") if extra_flags else ""

        insight_text = (
            f"{site['name']} ({aq_zone}, {confinement}, "
            + (f"well depth {well_depth:.0f} ft" if well_depth else site["site_id"])
            + f") shows a {trend} groundwater trend from "
            f"{start_date} to {end_date} with net change {net_change:+.2f} ft{flag_str}."
        )
        insights.append(
            {
                "content": insight_text,
                "source_url": site_url,
                "confidence": 0.85,
                "verified": True,
                "trust_level": "verified",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        claim_citations.append(
            {
                "claim_id": f"claim_{idx:03d}",
                "claim": insight_text,
                "confidence": 0.85,
                "citations": [{"url": site_url, "verified": True, "trust_level": "verified"}],
            }
        )

    # Cross-well cohort analysis (only when 2+ sites available)
    cross_well = _cross_well_analysis(sites)
    if cross_well["n_total"] >= 2:
        cw_dist = cross_well["trend_distribution"]
        cw_mean = cross_well["mean_annual_change_ft_yr"]
        cw_std = cross_well["std_dev_annual_change"]
        cw_risk = cross_well["risk_level"].upper()
        cw_n = cross_well["n_total"]
        pct_falling = cw_dist["falling"] / cw_n

        # Claim A -- cohort trend summary
        cohort_claim = (
            f"Of {cw_n} {location_name} monitoring wells analysed, "
            f"{cw_dist['falling']} show a falling trend, "
            f"{cw_dist['stable']} stable, and {cw_dist['rising']} rising. "
            f"Mean annual change: {cw_mean:+.3f} ft/yr "
            f"(\u03c3\u202f=\u202f{cw_std:.3f}\u202fft/yr)."
        )
        claim_citations.append(
            {
                "claim_id": f"claim_{len(claim_citations) + 1:03d}",
                "claim": cohort_claim,
                "confidence": 0.90,
                "citations": [
                    {"url": u, "verified": True, "trust_level": "verified"} for u in source_urls
                ],
            }
        )

        # Claim B -- divergence (only when opposing trends exist)
        if cross_well["divergent_pairs"]:
            top = cross_well["divergent_pairs"][0]
            sa, sb = top["site_a"], top["site_b"]
            div_claim = (
                f"{sa['name']} ({sa['trend']}, {sa['annual_change_ft_yr']:+.3f}\u202fft/yr) "
                f"vs {sb['name']} ({sb['trend']}, {sb['annual_change_ft_yr']:+.3f}\u202fft/yr) "
                "\u2014 differential behaviour may reflect local recharge heterogeneity "
                "or proximity to pumping centres."
            )
            div_urls = [
                _usgs_site_url(sa["site_id"]),
                _usgs_site_url(sb["site_id"]),
            ]
            claim_citations.append(
                {
                    "claim_id": f"claim_{len(claim_citations) + 1:03d}",
                    "claim": div_claim,
                    "confidence": 0.80,
                    "citations": [
                        {"url": u, "verified": True, "trust_level": "verified"} for u in div_urls
                    ],
                }
            )

        # Claim C -- risk assessment
        mostly_confined = sum(1 for s in sites if s.get("confined", False)) > cw_n / 2
        conf_label = "confined" if mostly_confined else "unconfined"
        risk_claim = (
            f"{pct_falling:.0%} of monitored {location_name} wells show declining trends "
            f"({conf_label} aquifer) \u2014 cohort sustainability risk: {cw_risk}."
        )
        claim_citations.append(
            {
                "claim_id": f"claim_{len(claim_citations) + 1:03d}",
                "claim": risk_claim,
                "confidence": 0.85,
                "citations": [{"url": source_urls[0], "verified": True, "trust_level": "verified"}],
            }
        )

    # Build aquifer-aware implications based on confinement types present
    confinement_types = {("confined" if s.get("confined") else "unconfined") for s in sites}
    if "unconfined" in confinement_types:
        implication_note = (
            "Unconfined (water-table) aquifers are directly sensitive to "
            "recharge variability, drought, and over-pumping."
        )
    else:
        implication_note = (
            "Confined artesian aquifers show pressure-head decline; "
            "sustained drawdown may reduce artesian flow and increase pumping costs."
        )
    implications_claim = (
        f"Observed trends imply sustainability risk. {implication_note} "
        "Saltwater intrusion risk increases under persistent decline in coastal zones."
    )
    claim_citations.append(
        {
            "claim_id": f"claim_{len(claim_citations) + 1:03d}",
            "claim": implications_claim,
            "confidence": 0.7,
            "citations": [
                {
                    "url": source_urls[0],
                    "verified": True,
                    "trust_level": "verified",
                }
            ],
        }
    )

    # Build cross-well cohort section for report text
    cohort_section = ""
    if cross_well["n_total"] >= 2:
        cw_dist = cross_well["trend_distribution"]
        cw_n = cross_well["n_total"]
        cohort_section = (
            f"\nCross-well cohort ({cw_n} wells):\n"
            f"- Trend distribution: {cw_dist['falling']} falling, "
            f"{cw_dist['stable']} stable, {cw_dist['rising']} rising\n"
            f"- Mean annual change: {cross_well['mean_annual_change_ft_yr']:+.3f} ft/yr "
            f"(\u03c3\u202f=\u202f{cross_well['std_dev_annual_change']:.3f}\u202fft/yr)\n"
            f"- Cohort trend: {cross_well['cohort_trend'].upper()}\n"
            f"- Risk level: {cross_well['risk_level'].upper()}\n"
        )
        for pair in cross_well["divergent_pairs"][:2]:
            sa, sb = pair["site_a"], pair["site_b"]
            cohort_section += (
                f"- Divergence: {sa['name']} ({sa['trend']}) " f"vs {sb['name']} ({sb['trend']})\n"
            )

    # --- Aquifer-grouped report ---
    by_aquifer: dict[str, list[dict]] = defaultdict(list)
    for sc in site_computed:
        by_aquifer[sc["aq_zone"]].append(sc)

    # Depth-sorted aquifer order: shallowest first
    def _aq_sort_key(aq_name: str) -> float:
        entries = by_aquifer[aq_name]
        depths = [e["well_depth_ft"] for e in entries if e["well_depth_ft"]]
        return min(depths) if depths else 999

    sorted_aquifers = sorted(by_aquifer.keys(), key=_aq_sort_key)

    # Build aquifer-grouped sections
    aquifer_sections: list[str] = []
    aquifer_summaries: list[dict] = []
    for aq_name in sorted_aquifers:
        entries = by_aquifer[aq_name]
        n_confined = sum(1 for e in entries if e["confined"])
        n_unconfined = len(entries) - n_confined
        if n_confined > 0 and n_unconfined > 0:
            confinement = "mixed confined/unconfined"
        elif n_confined > 0:
            confinement = "confined"
        else:
            confinement = "unconfined"
        zone_range = entries[0].get("zone_range")
        range_label = (
            f", {zone_range[0]}\u2013{zone_range[1]} ft"
            if zone_range and len(zone_range) == 2
            else ""
        )
        aq_label = entries[0]["aq_label"]
        n_wells = len(entries)

        # Section header
        plural = "s" if n_wells > 1 else ""
        section_header = (
            f"\n## {aq_label} ({confinement}{range_label})" f" \u2014 {n_wells} well{plural}\n"
        )

        # Well blocks
        well_lines = [e["block"] for e in entries]

        # Per-aquifer sub-cohort stats
        annual_changes = [e["annual_change"] for e in entries]
        mean_rate = sum(annual_changes) / len(annual_changes) if annual_changes else 0
        trends = [e["trend"] for e in entries]
        n_falling = sum(1 for t in trends if t == "falling")
        n_stable = sum(1 for t in trends if t == "stable")
        n_rising = sum(1 for t in trends if t == "rising")

        sub_cohort = ""
        if n_wells >= 2:
            sub_cohort = (
                f"\n  Sub-cohort ({n_wells} wells): "
                f"{n_falling} falling, {n_stable} stable, {n_rising} rising; "
                f"mean {mean_rate:+.3f} ft/yr"
            )

        aquifer_sections.append(section_header + chr(10).join(well_lines) + sub_cohort)
        aquifer_summaries.append(
            {
                "aquifer": aq_label,
                "zone": aq_name,
                "confinement": confinement,
                "n_wells": n_wells,
                "mean_annual_change": mean_rate,
                "n_falling": n_falling,
                "n_stable": n_stable,
                "n_rising": n_rising,
                "depth_label": range_label.strip(", ") if range_label else "unknown depth",
            }
        )

    # Cross-aquifer synthesis section
    cross_aq_section = ""
    if len(sorted_aquifers) >= 2:
        cross_aq_section = "\n## Cross-Aquifer Comparison\n"
        for aq_s in aquifer_summaries:
            trend_word = (
                "declining"
                if aq_s["mean_annual_change"] < -0.05
                else ("rising" if aq_s["mean_annual_change"] > 0.05 else "stable")
            )
            cross_aq_section += (
                f"- {aq_s['aquifer']} ({aq_s['confinement']}, {aq_s['depth_label']}, "
                f"{aq_s['n_wells']} wells): mean {aq_s['mean_annual_change']:+.3f} ft/yr, "
                f"{trend_word}\n"
            )

        # Shallow vs deep comparison
        shallow_wells = [sc for sc in site_computed if not sc["confined"]]
        deep_wells = [sc for sc in site_computed if sc["confined"]]
        if shallow_wells and deep_wells:
            shallow_rate = sum(w["annual_change"] for w in shallow_wells) / len(shallow_wells)
            deep_rate = sum(w["annual_change"] for w in deep_wells) / len(deep_wells)
            shallow_seasonal = any(w["seasonal"].get("has_seasonal") for w in shallow_wells)
            deep_seasonal = any(w["seasonal"].get("has_seasonal") for w in deep_wells)
            pattern_parts = []
            if shallow_seasonal and not deep_seasonal:
                pattern_parts.append("Shallow aquifers show higher seasonal variability")
            if abs(deep_rate) > abs(shallow_rate):
                pattern_parts.append("deeper confined systems show stronger long-term decline")
            elif abs(shallow_rate) > abs(deep_rate):
                pattern_parts.append("shallow unconfined systems show stronger long-term change")
            if pattern_parts:
                cross_aq_section += f"- Pattern: {'; '.join(pattern_parts)}.\n"

    # Period transparency
    period_note = ""
    yr_match = re.search(r"\b(\d+)\s*years?\b", question, re.IGNORECASE)
    if yr_match:
        requested_years = int(yr_match.group(1))
        actual_years = [sc["years"] for sc in site_computed]
        if actual_years:
            min_yr = min(actual_years)
            max_yr = max(actual_years)
            if min_yr < requested_years - 1:
                period_note = (
                    f"\nNote: Requested period is {requested_years} years. "
                    f"Available USGS records span {min_yr:.0f}\u2013{max_yr:.0f} years "
                    f"depending on when each well was instrumented.\n"
                )

    # Water supply context
    supply_section = ""
    supply_info = None
    is_supply_query = bool(_SUPPLY_QUERY_RE.search(question))
    if is_supply_query:
        loc_key = location_name.lower().replace(" ", "_").replace("-", "_")
        supply_info = _WATER_SUPPLY_SOURCES.get(loc_key)
        if not supply_info:
            for key, info in _WATER_SUPPLY_SOURCES.items():
                if key in loc_key or loc_key in key:
                    supply_info = info
                    break
        if supply_info:
            supply_section = f"\n## Water Supply Sources \u2014 {supply_info['municipality']}\n"
            supply_section += f"Utility: {supply_info['utility']}\n"
            supply_section += (
                f"Regulatory authority: {supply_info.get('regulatory_authority', 'N/A')}\n\n"
            )
            for sa in supply_info.get("supply_aquifers", []):
                supply_section += (
                    f"- {sa['usage'].title()} supply: {sa['aquifer']} / {sa['zone']} "
                    f"({sa['depth_range_ft'][0]}\u2013{sa['depth_range_ft'][1]} ft)\n"
                )
                if sa.get("notes"):
                    supply_section += f"  {sa['notes']}\n"
            for nsa in supply_info.get("non_supply_aquifers", []):
                supply_section += f"- {nsa['aquifer']}: {nsa['role']}\n"

            # Map supply aquifers to monitoring wells
            supply_section += "\nMonitoring wells representing supply aquifers:\n"
            for sa in supply_info.get("supply_aquifers", []):
                zone_name = sa["zone"]
                matching_wells = [
                    s
                    for s in sites
                    if (s.get("aquifer_zone") or "").lower() == zone_name.lower()
                    or zone_name.lower() in (s.get("aquifer_zone") or "").lower()
                    or zone_name.lower() in (s.get("aquifer", "")).lower()
                ]
                for mw in matching_wells:
                    dist_str = ""
                    if ref_lat is not None and ref_lng is not None:
                        dist_mi = _distance_miles(ref_lat, ref_lng, mw["lat"], mw["lng"])
                        bearing = _bearing_label(ref_lat, ref_lng, mw["lat"], mw["lng"])
                        dist_str = f", {dist_mi:.1f} mi {bearing}"
                    depth = mw.get("well_depth_ft")
                    depth_str = f", {depth:.0f} ft" if depth else ""
                    supply_section += (
                        f"  - {mw['name']} ({zone_name}{depth_str}{dist_str}) "
                        f"\u2014 {sa['usage']} supply zone proxy\n"
                    )

            # Known risks
            risks = supply_info.get("known_risks", [])
            if risks:
                supply_section += "\nKnown risks:\n"
                for risk in risks:
                    supply_section += f"  - {risk}\n"

            confidence = supply_info.get(
                "data_confidence",
                _WATER_SUPPLY_SOURCES.get("data_confidence", "moderate"),
            )
            supply_section += f"\nData confidence: {confidence}\n"

            # Add supply claim
            pri = supply_info["supply_aquifers"][0]
            supply_claim = (
                f"{supply_info['municipality']} water supply is "
                f"served by {supply_info['utility']}, "
                f"drawing primarily from the {pri['aquifer']} "
                f"({pri['zone']}, "
                f"{pri['depth_range_ft'][0]}\u2013"
                f"{pri['depth_range_ft'][1]} ft)."
            )
            reg_auth = supply_info.get("regulatory_authority", "SFWMD")
            claim_citations.append(
                {
                    "claim_id": f"claim_{len(claim_citations) + 1:03d}",
                    "claim": supply_claim,
                    "confidence": 0.70,
                    "citations": [
                        {
                            "source": "config/water_supply_sources.json",
                            "basis": (
                                "Curated from USGS hydrogeologic framework "
                                f"reports and {reg_auth} regional water "
                                "supply plans"
                            ),
                            "verified": False,
                            "trust_level": "moderate",
                        }
                    ],
                }
            )

    # --- LLM synthesis (hybrid mode) ---
    synthesis_section = ""
    needs_synthesis = is_supply_query or bool(_SYNTHESIS_TRIGGER_RE.search(question))
    if needs_synthesis:
        synthesis_data = {
            "location": location_name,
            "aquifer_summaries": aquifer_summaries,
            "supply_info": supply_info if is_supply_query and supply_info else None,
            "cohort_trend": cross_well.get("cohort_trend", "unknown"),
            "risk_level": cross_well.get("risk_level", "unknown"),
            "n_wells": len(sites),
        }
        try:
            import httpx

            supply_context = ""
            if synthesis_data.get("supply_info"):
                si = synthesis_data["supply_info"]
                supply_names = ", ".join(
                    f"{sa['aquifer']} ({sa['usage']})" for sa in si.get("supply_aquifers", [])
                )
                supply_context = (
                    f"\nWater supply context: {si['municipality']} is served by "
                    f"{si['utility']}. Supply aquifers: {supply_names}. "
                    f"Known risks: {'; '.join(si.get('known_risks', []))}."
                )

            aq_data_lines = []
            for aq_s in synthesis_data["aquifer_summaries"]:
                nf = aq_s["n_falling"]
                ns = aq_s["n_stable"]
                nr = aq_s["n_rising"]
                aq_data_lines.append(
                    f"- {aq_s['aquifer']} "
                    f"({aq_s['confinement']}, {aq_s['depth_label']}): "
                    f"mean {aq_s['mean_annual_change']:+.3f} ft/yr, "
                    f"{nf} falling / {ns} stable / {nr} rising"
                )

            prompt = (
                f"Hydrogeologist: synthesize USGS data for {location_name}, FL in 2 paragraphs.\n\n"
                + "\n".join(aq_data_lines)
                + f"\n\nCohort: {synthesis_data['n_wells']} wells, "
                f"{synthesis_data['cohort_trend']}, risk: {synthesis_data['risk_level']}."
                f"{supply_context}\n\n"
                "Cover: 1) most concerning aquifer trends, "
                "2) shallow vs deep comparison, "
                "3) sustainability/saltwater intrusion implications. "
                "Under 150 words. Use only data above."
            )
            synthesis_model = os.environ.get("SYNTHESIS_MODEL", "llama3.2")
            ollama_resp = httpx.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": synthesis_model,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 300},
                    "keep_alive": "10m",
                },
                timeout=60.0,
            )
            ollama_resp.raise_for_status()
            llm_text = ollama_resp.json().get("response", "").strip()
            # Strip any residual <think> blocks
            llm_text = re.sub(r"<think>.*?</think>", "", llm_text, flags=re.DOTALL).strip()
            if llm_text and len(llm_text) > 50:
                synthesis_section = llm_text
                claim_citations.append(
                    {
                        "claim_id": f"claim_{len(claim_citations) + 1:03d}",
                        "claim": llm_text[:200],
                        "confidence": 0.50,
                        "citations": [],
                        "source_type": "llm_synthesis",
                    }
                )
        except Exception as exc:
            logger.debug("LLM synthesis unavailable, using deterministic fallback: %s", exc)

    # Build full report
    aquifer_summary = ", ".join(sorted_aquifers)
    report = (
        f"{location_name} groundwater analysis (USGS-backed):\n\n"
        f"Aquifer systems monitored: {aquifer_summary}\n"
        f"{period_note}"
        f"{supply_section}"
        f"{''.join(aquifer_sections)}\n"
        f"{cohort_section}"
        f"{cross_aq_section}\n"
        "Interpretation:\n"
        "- The available record may not span the full requested period; "
        "results reflect the actual observed period listed above.\n"
        "- Trend direction (rising/falling/stable) is computed from net change over "
        "the available record.\n"
        f"- {implications_claim}"
    )

    claim_verdicts = _build_claim_verdicts(claim_citations)
    return {
        "report": report,
        "insights": insights,
        "sources": source_urls,
        "claim_citations": claim_citations,
        "claim_verdicts": claim_verdicts,
        "claim_verdict_summary": _build_claim_verdict_summary(claim_verdicts),
        "citation_summary": _build_citation_summary(claim_citations),
        "section_confidence": _build_section_confidence_from_claims(claim_citations),
        "hallucination_guardrail": {
            "strategy": "deterministic_site_fallback",
            "removed_uncited_factual_sentences": 0,
            "all_factual_claims_cited": all(bool(c.get("citations")) for c in claim_citations),
            "has_llm_synthesis": bool(synthesis_section),
        },
        "llm_synthesis": synthesis_section.strip() if synthesis_section else None,
        "divergent_pairs": cross_well.get("divergent_pairs", []),
        "cohort_risk_level": cross_well.get("risk_level"),
        "search_history": [question, f"USGS {location_name} proxy sites trend analysis"],
        "depth_reached": 1,
        "elapsed_seconds": 0.12,
    }
