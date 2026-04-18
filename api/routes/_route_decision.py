"""Phase 1 of the grounded-chat refactor: centralize route selection.

Before this module, ``chat_endpoint`` ran detection heuristics inline, one
after another, and each branch did its own thing. That spread routing
knowledge across a 300-line if/elif chain.

``resolve_route`` is the single place that answers: *given this question,
this chart context, and this turn history, which intent are we serving?*
It returns a ``RouteDecision`` that each downstream branch consumes.
Detection is done exactly once per request.

Phase 1 does NOT collapse the response assembly — that's Phase 2. The
branches in ``chat_endpoint`` still build their own payloads; they just
read detection results from the decision object instead of re-running the
detectors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from api.routes._answer_contract import RouteMode

# ---------------------------------------------------------------------------
# Unsupported-question detection (Phase 1 scope — Phase 4 expands this).
# ---------------------------------------------------------------------------

# Geographies we explicitly cannot answer about. We still reply, but the
# route_mode is UNSUPPORTED so the envelope is honest.
_OUT_OF_SCOPE_GEO = re.compile(
    r"\b(antarctica|siberia|sahara|arctic|europe|asia|africa|australia"
    r"|india|china|japan|brazil|mexico|canada|alaska|hawaii)\b",
    re.IGNORECASE,
)

# Future prediction / forecast asks — dataset is historical observation.
_FUTURE_PREDICTION = re.compile(
    r"\b(forecast|predict|will\s+(?:it|the|water|levels?|drop|rise|fall)"
    r"|going to|next (?:year|decade|century)|in \d{4}"
    r"|should i (?:drill|buy|invest|plant|water))\b",
    re.IGNORECASE,
)


def _detect_unsupported_reason(question: str) -> Optional[str]:
    """Return a short tag when the question cannot be answered from the dataset.

    ``None`` means the question is in-scope.
    """
    if not question:
        return None
    if _OUT_OF_SCOPE_GEO.search(question):
        return "out_of_scope_geography"
    if _FUTURE_PREDICTION.search(question):
        return "future_prediction"
    return None


# ---------------------------------------------------------------------------
# RouteDecision — the single output of the resolver.
# ---------------------------------------------------------------------------


@dataclass
class RouteDecision:
    """A normalized routing decision for a single chat request.

    Fields are plain Python types so the object serializes cleanly to JSON
    for observability. ``internal_mode`` preserves the historical
    ``payload['mode']`` string each branch writes — call sites should
    prefer ``route_mode`` (the canonical value).
    """

    # Canonical enums
    route_mode: str  # RouteMode.*
    internal_mode: str  # matches existing payload['mode'] conventions
    intent: str  # short semantic label for logs/tests

    # Chart context to route interpretation against. ``None`` means no
    # chart-based path should be taken. May be the caller-supplied context,
    # a context recovered from turn history, or ``None``.
    chart_context_to_use: Optional[dict[str, Any]] = None

    # Detection results — each branch in chat_endpoint reads what it needs.
    # All optional so the resolver only populates what applies.
    named_sites: list[dict[str, Any]] = field(default_factory=list)
    aquifer_hit: Optional[tuple[str, str]] = None
    location_hit: Optional[tuple[float, float, str, Optional[str]]] = None
    locations: list[tuple[float, float, str, Optional[str]]] = field(default_factory=list)
    is_multi_location: bool = False
    is_network_wide: bool = False
    kb_matches: list[tuple[str, str]] = field(default_factory=list)

    # Honest refusal metadata. When set, the route_mode is UNSUPPORTED.
    unsupported_reason: Optional[str] = None

    # Debug / observability — original inputs, trimmed to what matters.
    hints: dict[str, Any] = field(default_factory=dict)

    def to_observable(self) -> dict[str, Any]:
        """Compact dict for attaching to the response payload."""
        return {
            "route_mode": self.route_mode,
            "internal_mode": self.internal_mode,
            "intent": self.intent,
            "has_chart_context": self.chart_context_to_use is not None,
            "named_sites": [s.get("site_id") or s.get("id") for s in self.named_sites],
            "aquifer": self.aquifer_hit[1] if self.aquifer_hit else None,
            "location": self.location_hit[2] if self.location_hit else None,
            "multi_location_labels": [loc[2] for loc in self.locations],
            "is_multi_location": self.is_multi_location,
            "is_network_wide": self.is_network_wide,
            "unsupported_reason": self.unsupported_reason,
        }


# ---------------------------------------------------------------------------
# The resolver.
# ---------------------------------------------------------------------------


def resolve_route(
    user_query: str,
    chart_context: Optional[dict[str, Any]],
    turn_history: list[dict[str, Any]],
    *,
    detectors: dict[str, Any],
) -> RouteDecision:
    """Produce a RouteDecision for ``chat_endpoint`` to dispatch on.

    ``detectors`` is a dict of callables the resolver needs from ``chat.py``.
    Passing them in keeps ``_route_decision`` free of circular imports and
    lets tests inject fakes. Required keys:

    - ``should_prefer_chart_context(question, chart_context) -> bool``
    - ``is_contextual_followup(question) -> bool``
    - ``chart_context_from_turn_history(turn_history) -> dict | None``
    - ``detect_site_names(question) -> list[dict]``
    - ``detect_aquifer(question) -> tuple | None``
    - ``detect_locations(question, max_matches) -> list[tuple]``
    - ``is_multi_location_compare_query(question) -> bool``
    - ``detect_location(question) -> tuple | None``
    - ``is_network_wide_query(question) -> bool``
    - ``kb_topic_matches(question) -> list[tuple]``
    """
    hints = {
        "has_caller_chart_context": isinstance(chart_context, dict),
        "turn_history_depth": len(turn_history or []),
    }

    unsupported_reason = _detect_unsupported_reason(user_query)

    # --- Chart-context interpretation (caller-supplied) ---
    if detectors["should_prefer_chart_context"](user_query, chart_context):
        return RouteDecision(
            route_mode=RouteMode.CHART_FOLLOWUP,
            internal_mode="chart_interpreter",
            intent="chart_followup_with_active_chart",
            chart_context_to_use=chart_context,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- Contextual follow-up recovery (inherit prior chart context) ---
    recovered = None
    if chart_context is None and detectors["is_contextual_followup"](user_query):
        recovered = detectors["chart_context_from_turn_history"](turn_history)
    if recovered is not None:
        return RouteDecision(
            route_mode=RouteMode.CHART_FOLLOWUP,
            internal_mode="chart_interpreter",
            intent="chart_followup_recovered_from_history",
            chart_context_to_use=recovered,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- Exact well / site lookup ---
    named_sites = detectors["detect_site_names"](user_query)
    if named_sites:
        return RouteDecision(
            route_mode=(RouteMode.UNSUPPORTED if unsupported_reason else RouteMode.EXACT_WELL),
            internal_mode="site_fallback",
            intent="exact_well_lookup",
            named_sites=named_sites,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- Aquifer cohort ---
    aquifer_hit = detectors["detect_aquifer"](user_query)
    if aquifer_hit is not None:
        return RouteDecision(
            route_mode=(RouteMode.UNSUPPORTED if unsupported_reason else RouteMode.COHORT),
            internal_mode="aquifer_fallback",
            intent="aquifer_cohort",
            aquifer_hit=aquifer_hit,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- Multi-location comparison ---
    locations = detectors["detect_locations"](user_query, 4)
    if len(locations) >= 2 and detectors["is_multi_location_compare_query"](user_query):
        return RouteDecision(
            route_mode=(RouteMode.UNSUPPORTED if unsupported_reason else RouteMode.COHORT),
            internal_mode="network_fallback",  # historical tag, kept for back-compat
            intent="multi_location_comparison",
            locations=locations,
            is_multi_location=True,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- Single-location cohort ---
    location_hit = detectors["detect_location"](user_query)
    if location_hit is not None:
        return RouteDecision(
            route_mode=(RouteMode.UNSUPPORTED if unsupported_reason else RouteMode.COHORT),
            internal_mode="site_fallback",
            intent="location_cohort",
            location_hit=location_hit,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- Network-wide ---
    if detectors["is_network_wide_query"](user_query):
        return RouteDecision(
            route_mode=(RouteMode.UNSUPPORTED if unsupported_reason else RouteMode.NETWORK),
            internal_mode="network_fallback",
            intent="network_wide",
            is_network_wide=True,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- Out-of-scope but no specific route triggered ---
    if unsupported_reason is not None:
        return RouteDecision(
            route_mode=RouteMode.UNSUPPORTED,
            internal_mode="fallback",
            intent="unsupported_question",
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- KB topic fallback ---
    kb_matches = detectors["kb_topic_matches"](user_query)
    if kb_matches:
        return RouteDecision(
            route_mode=RouteMode.FALLBACK,
            internal_mode="fallback",
            intent="kb_topic_match",
            kb_matches=kb_matches,
            hints=hints,
        )

    # --- Research / last-resort fallback ---
    return RouteDecision(
        route_mode=RouteMode.RESEARCH,  # upgraded to FALLBACK by caller if the agent is unavailable
        internal_mode="research_chat",
        intent="open_ended_research",
        hints=hints,
    )


__all__ = ["RouteDecision", "resolve_route"]
