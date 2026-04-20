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
from datetime import datetime
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
# Note: bare "in YYYY" was previously here but matched historical years too
# (e.g., "what happened in 2015"). Future-year detection now lives in
# ``_mentions_future_year`` below, which checks the year against today.
_FUTURE_PREDICTION = re.compile(
    r"\b(forecast|predict|will\s+(?:it|the|water|levels?|drop|rise|fall)"
    r"|going to|next (?:year|decade|century))\b",
    re.IGNORECASE,
)

# Yes/no decision asks ("should I drill a well here?") — refused because we
# observe, we don't advise. Practical info questions that happen to contain the
# same verb ("how deep should I drill?") are left alone via ``_WH_LEAD``.
_DECISION_QUESTION = re.compile(
    r"\bshould\s+i\s+(?:drill|buy|invest|plant|water)\b",
    re.IGNORECASE,
)
_WH_LEAD = re.compile(r"^\s*(?:how|what|where|when|why|which)\b", re.IGNORECASE)

_YEAR_RE = re.compile(r"\b(19|20|21)\d{2}\b")
_PAST_TENSE_HINT = re.compile(
    r"\b(was|were|happened|did|had|occurred|recorded|observed|measured|past|history|"
    r"historic(?:ally)?|previously|back in|since|until|before)\b",
    re.IGNORECASE,
)
_NAMED_SITE_CHART_COMPARISON = re.compile(
    r"\b(compare|compares?|comparison|diverge|divergent|other wells?|rest of the chart|"
    r"this chart|the chart|using the chart|cohort|average|highlighted)\b",
    re.IGNORECASE,
)
_NAMED_SITE_COMPARISON = re.compile(
    r"\b(compare|compares?|comparison|contrast|versus|vs\.?|diverge|divergent|different)\b",
    re.IGNORECASE,
)

# Dataset-wide "which is the fastest/most stressed" asks. We route these
# through the network-wide deterministic path so the ranking signal is
# computed from the monitored record, not improvised. Two scopes:
#   - well_rate: "which well is changing fastest" / "biggest drop"
#   - aquifer_stress: "which aquifer is most stressed"
_RANKING_WELL = re.compile(
    r"\bwhich\s+(?:well|site|monitoring\s+well)\b[^?]*"
    r"\b(?:fastest|slowest|most|biggest|largest|worst|steepest|sharpest)\b"
    r"|\b(?:fastest|biggest|steepest|worst|sharpest)\s+"
    r"(?:declining|changing|rising|falling|drop(?:ping)?|drawdown)\s+(?:well|site)\b"
    r"|\bchanging\s+fastest\b|\bdeclining\s+(?:the\s+)?most\b",
    re.IGNORECASE,
)
_RANKING_AQUIFER = re.compile(
    r"\bwhich\s+aquifer\b[^?]*"
    r"\b(?:most\s+stressed|least\s+stable|most\s+depleted|worst|biggest\s+decline|"
    r"declining\s+fastest|stressed|in\s+trouble)\b"
    r"|\bmost\s+stressed\s+aquifer\b|\bwhich\s+aquifer\s+looks\s+(?:most\s+)?stressed\b",
    re.IGNORECASE,
)

# Proxy / supply guardrail: "can monitoring wells stand in for drinking-water
# wells?". Monitoring wells measure head, not pumpable supply — we hedge
# honestly rather than routing this to a data path that would imply yes.
_PROXY_SUPPLY = re.compile(
    r"\bmonitoring\s+wells?\b[^.?]*"
    r"\b(?:stand\s+in|stand-in|proxy|substitute|instead\s+of|replace|predict|"
    r"answer\s+for|represent|tell\s+us\s+about)\b"
    r"[^.?]*"
    r"\b(?:drinking|supply|pumping|production|irrigation|withdrawal|public\s+water)\b"
    r"|\bcan\s+(?:these\s+)?monitoring\s+wells?\s+"
    r"(?:stand\s+in|substitute|proxy|replace|answer\s+for)\b",
    re.IGNORECASE,
)

# Ambiguous deictic: "groundwater there", "is that bad?", "why is it declining?"
# with no resolvable referent (no named site, aquifer, location, or active
# chart context). We ask the user to narrow, rather than inventing a subject.
_DEICTIC_TOKENS = re.compile(r"\b(?:there|here|that|this|it)\b", re.IGNORECASE)

# Intents that demand grounded evidence to answer honestly. If the resolver
# reached the bottom of the chain without producing an entity match, these
# verbs imply we'd be inventing the comparison/ranking/cause — flip to
# insufficient instead of letting the KB or research fallback paper over it.
# Chart interpretation is included only when the user explicitly says so;
# generic "what does this mean?" is left to chart-context detection upstream.
_NEEDS_GROUNDING_INTENT = re.compile(
    r"\b(?:"
    r"compare|comparison|contrast|differ(?:ence)?|"  # comparison
    r"why\s+(?:is|are|did|do|does|has|have)\b|caused?\s+by|due\s+to|"  # causation
    r"rank(?:ing|ed)?|top\s+\d+|"  # ranking
    r"interpret\s+(?:the|this)\s+\w+|"  # explicit interpretation ask
    r"explain\s+(?:the|this)\s+(?:chart|trend|pattern|decline|rise)"
    r")\b",
    re.IGNORECASE,
)


def _detect_ranking_ask(question: str) -> Optional[str]:
    """Return ``'well_rate'`` / ``'aquifer_stress'`` when the question is a ranking ask."""
    if _RANKING_WELL.search(question or ""):
        return "well_rate"
    if _RANKING_AQUIFER.search(question or ""):
        return "aquifer_stress"
    return None


def _is_proxy_question(question: str) -> bool:
    """True when the question asks whether monitoring wells stand in for supply wells."""
    return bool(_PROXY_SUPPLY.search(question or ""))


def _is_ambiguous_deictic(question: str) -> bool:
    """True for short follow-ups whose subject is only a pronoun/deictic.

    Called at the end of route resolution — only fires when no named entity,
    aquifer, location, or chart context resolved the referent.
    """
    q = (question or "").strip()
    if not q or len(q) > 160:
        return False
    return bool(_DEICTIC_TOKENS.search(q))


def _needs_grounded_path(question: str) -> bool:
    """True when the question's intent verbs demand grounded evidence to answer.

    Called only after every entity-based route has missed: at this point the
    KB / research fallback would have to invent the comparison, ranking, or
    cause. We'd rather say "insufficient" honestly.
    """
    return bool(_NEEDS_GROUNDING_INTENT.search(question or ""))


def _chart_context_matches_named_sites(
    chart_context: Optional[dict[str, Any]],
    named_sites: list[dict[str, Any]],
) -> bool:
    """True when the active chart actually contains the named sites in the question."""
    if not isinstance(chart_context, dict) or not named_sites:
        return False
    raw_site_ids = chart_context.get("site_ids") or []
    if not raw_site_ids and isinstance(chart_context.get("summary_metrics"), dict):
        raw_site_ids = chart_context["summary_metrics"].get("site_ids") or []
    chart_site_ids = {str(site_id).strip() for site_id in raw_site_ids if str(site_id).strip()}
    if not chart_site_ids:
        return False
    named_ids = {
        str(site.get("site_id") or site.get("id")).strip()
        for site in named_sites
        if str(site.get("site_id") or site.get("id") or "").strip()
    }
    return bool(named_ids) and named_ids.issubset(chart_site_ids)


def _mentions_future_year(question: str) -> bool:
    """True when the question references a year strictly in the future.

    Past-tense framing ("what happened in 2015", "since 2020") is a strong
    signal the user is asking about history, even if a year token is present.
    """
    if _PAST_TENSE_HINT.search(question):
        return False
    current_year = datetime.now().year
    for match in _YEAR_RE.finditer(question):
        if int(match.group(0)) > current_year:
            return True
    return False


def _is_decision_question(question: str) -> bool:
    """True when the question is a yes/no decision ask, not an info ask.

    "should I drill a well here?" is a decision; "how deep should I drill?" is
    a depth question. The wh-word lead distinguishes the two cheaply.
    """
    if not _DECISION_QUESTION.search(question or ""):
        return False
    return _WH_LEAD.match(question or "") is None


def extract_out_of_scope_geo(question: str) -> Optional[str]:
    """Return the matched out-of-scope geography (title-cased) or ``None``."""
    match = _OUT_OF_SCOPE_GEO.search(question or "")
    if match is None:
        return None
    return match.group(0).title()


def _detect_unsupported_reason(question: str) -> Optional[str]:
    """Return a short tag when the question cannot be answered from the dataset.

    ``None`` means the question is in-scope.
    """
    if not question:
        return None
    if _OUT_OF_SCOPE_GEO.search(question):
        return "out_of_scope_geography"
    if (
        _FUTURE_PREDICTION.search(question)
        or _mentions_future_year(question)
        or _is_decision_question(question)
    ):
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

    # Ranking asks ride the network-wide deterministic path but need to be
    # observable separately so transcripts/tests can distinguish a generic
    # "all-wells" ask from a "which well is fastest" ranking ask.
    is_ranking_ask: bool = False
    ranking_scope: Optional[str] = None  # 'well_rate' | 'aquifer_stress'

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
            "is_ranking_ask": self.is_ranking_ask,
            "ranking_scope": self.ranking_scope,
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

    # --- Proxy/supply guardrail (explicit hedge, not a data path) ---
    # Monitoring wells measure head, not pumpable supply. An honest answer
    # names that caveat rather than running the same trend path and letting
    # the user draw the wrong conclusion.
    if unsupported_reason is None and _is_proxy_question(user_query):
        return RouteDecision(
            route_mode=RouteMode.UNSUPPORTED,
            internal_mode="fallback",
            intent="monitoring_vs_supply_proxy",
            unsupported_reason="monitoring_vs_supply_proxy",
            hints=hints,
        )

    named_sites = detectors["detect_site_names"](user_query)
    explicit_named_chart_followup = bool(_NAMED_SITE_CHART_COMPARISON.search(user_query or ""))
    named_sites_match_chart = _chart_context_matches_named_sites(chart_context, named_sites)

    # --- Named site within an explicitly comparative chart question ---
    if (
        named_sites
        and explicit_named_chart_followup
        and named_sites_match_chart
        and detectors["should_prefer_chart_context"](user_query, chart_context)
    ):
        return RouteDecision(
            route_mode=RouteMode.CHART_FOLLOWUP,
            internal_mode="chart_interpreter",
            intent="chart_followup_with_named_site",
            chart_context_to_use=chart_context,
            named_sites=named_sites,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    recovered = None
    if chart_context is None and detectors["is_contextual_followup"](user_query):
        recovered = detectors["chart_context_from_turn_history"](turn_history)
    recovered_matches_named_sites = _chart_context_matches_named_sites(recovered, named_sites)
    if (
        named_sites
        and explicit_named_chart_followup
        and recovered is not None
        and recovered_matches_named_sites
    ):
        return RouteDecision(
            route_mode=RouteMode.CHART_FOLLOWUP,
            internal_mode="chart_interpreter",
            intent="chart_followup_named_site_recovered_from_history",
            chart_context_to_use=recovered,
            named_sites=named_sites,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- Exact well / site lookup ---
    if named_sites:
        return RouteDecision(
            route_mode=(RouteMode.UNSUPPORTED if unsupported_reason else RouteMode.EXACT_WELL),
            internal_mode="site_fallback",
            intent=(
                "named_well_comparison"
                if len(named_sites) >= 2 and _NAMED_SITE_COMPARISON.search(user_query or "")
                else "exact_well_lookup"
            ),
            named_sites=named_sites,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

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
    if recovered is not None:
        return RouteDecision(
            route_mode=RouteMode.CHART_FOLLOWUP,
            internal_mode="chart_interpreter",
            intent="chart_followup_recovered_from_history",
            chart_context_to_use=recovered,
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

    # --- Network-wide (generic all-fleet asks) ---
    if detectors["is_network_wide_query"](user_query):
        return RouteDecision(
            route_mode=(RouteMode.UNSUPPORTED if unsupported_reason else RouteMode.NETWORK),
            internal_mode="network_fallback",
            intent="network_wide",
            is_network_wide=True,
            unsupported_reason=unsupported_reason,
            hints=hints,
        )

    # --- Dataset-wide ranking ask ("fastest well", "most stressed aquifer") ---
    # These ride the network-wide deterministic path (which already computes
    # per-site trends) but we stamp ranking_scope so the response surface and
    # transcripts can see the user asked for a ranking, not a summary.
    ranking_scope = _detect_ranking_ask(user_query)
    if ranking_scope is not None:
        return RouteDecision(
            route_mode=(RouteMode.UNSUPPORTED if unsupported_reason else RouteMode.NETWORK),
            internal_mode="network_fallback",
            intent=f"ranking_{ranking_scope}",
            is_network_wide=True,
            is_ranking_ask=True,
            ranking_scope=ranking_scope,
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

    # --- Ambiguous deictic ("groundwater there", "is that bad?") ---
    # Nothing resolved the referent (no named site, aquifer, location, chart,
    # or recovered chart context). Ask the user to narrow rather than letting
    # a generic KB answer paper over the ambiguity.
    if _is_ambiguous_deictic(user_query):
        return RouteDecision(
            route_mode=RouteMode.UNSUPPORTED,
            internal_mode="fallback",
            intent="ambiguous_reference",
            unsupported_reason="ambiguous_reference",
            hints=hints,
        )

    # --- Ungrounded ranking / comparison / causation intent ---
    # We're past every entity route. If the verb still implies we'd need
    # grounded evidence (compare, why, rank, interpret), the honest move is
    # to admit insufficiency rather than fall back to KB blurbs that imply
    # we did the comparison.
    if _needs_grounded_path(user_query):
        return RouteDecision(
            route_mode=RouteMode.UNSUPPORTED,
            internal_mode="fallback",
            intent="ungrounded_intent",
            unsupported_reason="no_evidence",
            hints=hints,
        )

    # --- KB topic fallback (basics / orientation only) ---
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


__all__ = ["RouteDecision", "extract_out_of_scope_geo", "resolve_route"]
