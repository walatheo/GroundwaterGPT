"""Tests for chart-context interpretation helpers."""

import sys
import types

import pytest

from api.routes import _chart_interpreter as interpreter
from api.routes.answering.reasoning import (
    GroundedInterpretation,
    GroundedNumericClaim,
    ReasoningStep,
)

ESTERO_CONTEXT = {
    "chart_id": "Estero Monthly Groundwater Levels",
    "site_ids": ["263335081394301", "263532081592201", "262538082045701"],
    "chart_type": "comparison",
    "summary_metrics": {"title": "Estero Monthly Groundwater Levels"},
}

MIXED_CONFINEMENT_CONTEXT = {
    "chart_id": "Lee Mixed Confinement Groundwater Levels",
    "site_ids": ["261957081432201", "261957081432202", "263335081394301"],
    "chart_type": "comparison",
    "summary_metrics": {"title": "Lee Mixed Confinement Groundwater Levels"},
}

LEE_MULTI_AQUIFER_CONTEXT = {
    "chart_id": "Lee County Multi-Aquifer Groundwater Levels",
    "site_ids": [
        "263117082051001",
        "262538082045701",
        "263440082022001",
        "263532081592201",
        "263041081433102",
        "261957081432201",
        "262711081413701",
        "263335081394301",
        "263041081433103",
        "261957081432202",
        "262513081432601",
    ],
    "chart_type": "comparison",
    "summary_metrics": {"title": "Lee County Multi-Aquifer Groundwater Levels"},
}


def test_evidence_pack_assembles_cross_well_metrics(monkeypatch):
    """EvidencePack should reuse local chart/site data and expose metric keys."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    pack = interpreter.build_evidence_pack("Which well is changing fastest?", ESTERO_CONTEXT)

    assert pack["site_ids"] == ESTERO_CONTEXT["site_ids"]
    assert pack["cross_well"]["per_site_metrics"]
    assert pack["insights"]
    assert pack["explainability"]["how_to_read"]
    assert pack["well_summaries"]
    assert pack["comparison_features"]
    assert pack["entity_catalog"]["wells"]


def test_contextual_rag_query_includes_chart_terms(monkeypatch):
    """Retrieval should search with active wells/aquifers, not only the follow-up text."""
    captured = {}

    def _capture_query(query):
        captured["query"] = query
        return []

    monkeypatch.setattr(interpreter, "_rag_snippets", _capture_query)

    pack = interpreter.build_evidence_pack("Why is it declining?", ESTERO_CONTEXT)

    query = captured["query"].lower()
    assert "why is it declining" in query
    assert "lee" in query
    assert "aquifer" in query
    assert pack["enriched_rag_query"] == captured["query"]


def test_curated_hydro_context_enriches_decline_answer(monkeypatch):
    """Chart interpretation should include hydro concepts without requiring Chroma."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "Why is it declining?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    concepts = interpretation["groundwater_concepts"]
    assert concepts
    assert any("decline" in " ".join(concept.get("tags", [])) for concept in concepts)
    assert "drawdown" in interpretation["interpretation"].lower()
    assert interpretation["direct_answer"]
    assert interpretation["supporting_evidence"]
    assert "Possible explanations to test:" not in interpretation["interpretation"]
    assert "What would confirm it:" not in interpretation["interpretation"]
    assert interpretation["interpretive_findings"]
    assert interpretation["possible_drivers"]
    assert interpretation["evidence_needed"]
    assert interpretation["management_implications"]
    assert interpretation["confidence_notes"]
    assert interpretation["meaning_brief"]["headline"]
    assert interpretation["meaning_brief"]["plain_language"]
    assert interpretation["meaning_brief"]["why_it_matters"]
    assert interpretation["meaning_brief"]["next_best_check"]
    assert (
        "observation from interpretation" in interpretation["meaning_brief"]["classroom_takeaway"]
    )
    assert interpretation["what_this_means"]
    assert interpretation["next_goal"]
    assert interpretation["follow_up_groups"]
    assert "pumping" in " ".join(interpretation["evidence_needed"]).lower()
    assert "does not prove" in interpretation["confidence_notes"][0].lower()
    assert "enriched_rag_query" in interpretation["evidence_used"]
    assert "What caveats should I mention?" in interpretation["follow_up_questions"]


def test_what_this_means_is_interpretive_not_data_only(monkeypatch):
    """A meaning question should explain significance, not only restate rates."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "What does this mean for the groundwater system?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    meaning = result["interpretation_response"]["meaning_brief"]
    blob = " ".join(meaning.values()).lower()
    assert "screening" in blob
    assert "follow-up" in blob or "next" in blob
    assert "outside data" in blob or "pumping" in blob or "recharge" in blob
    assert "observation from interpretation" in blob


def test_curated_hydro_context_survives_vector_rag_failure(monkeypatch):
    """Unavailable vector retrieval should not break grounded chart interpretation."""

    def _boom(_query):
        raise RuntimeError("vector store unavailable")

    monkeypatch.setattr(interpreter, "_rag_snippets", _boom)

    result = interpreter.interpret_with_context(
        "Is this seasonal or long-term?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    assert result["status"] == "ok"
    assert interpretation["grounding_status"]["interpreter_status"] == "grounded"
    assert interpretation["groundwater_concepts"]
    assert len(interpretation["groundwater_concepts"]) <= 4


def test_interpretation_response_exposes_framing_and_entity_summaries(monkeypatch):
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "Why is Upper Floridan the most stressed supply unit in this dataset?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    assert interpretation["framing"]["scope_type"] in {"supply_unit", "aquifer", "cohort"}
    assert "question_goal" in interpretation["framing"]
    assert interpretation["well_summaries"]
    assert interpretation["comparison_features"]


@pytest.mark.parametrize(
    ("question", "expected_terms"),
    [
        ("What does this mean?", ["screening", "evidence", "does not prove"]),
        ("Is this seasonal or long-term?", ["seasonal", "recharge", "multiple years"]),
        (
            "Could this indicate saltwater intrusion risk?",
            ["saltwater", "chloride", "does not prove"],
        ),
        ("How do shallow and deep wells compare?", ["shallow", "deep", "screened interval"]),
    ],
)
def test_interpretation_depth_for_contextual_followups(monkeypatch, question, expected_terms):
    """Common follow-ups should provide hydro interpretation, not only rates."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        question,
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    blob = " ".join(
        [
            interpretation["interpretation"],
            interpretation.get("direct_answer", ""),
            " ".join(interpretation.get("supporting_evidence", []) or []),
            " ".join(interpretation["possible_drivers"]),
            " ".join(interpretation["evidence_needed"]),
            " ".join(interpretation["confidence_notes"]),
            " ".join(interpretation["limits"]),
        ]
    ).lower()
    assert interpretation["interpretive_findings"]
    assert interpretation["hydrogeologic_meaning"]
    assert interpretation["possible_drivers"]
    assert interpretation["evidence_needed"]
    for term in expected_terms:
        assert term in blob


def test_shallow_deep_intent_answers_directly(monkeypatch):
    """Shallow/deep questions should get a comparison answer, not a metadata wall."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "Do the shallow and deep aquifer wells diverge on this chart?",
        chart_context=MIXED_CONFINEMENT_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    assert interpretation["question_intent"] == "shallow_deep_comparison"
    assert "shallow/unconfined" in interpretation["direct_answer"]
    assert "deep/confined" in interpretation["direct_answer"]
    assert "ft/yr" in interpretation["direct_answer"]
    assert "Observed signal:" not in interpretation["interpretation"]
    assert "Context site IDs include" not in interpretation["interpretation"]
    assert interpretation["comparison_groups"]["shallow_unconfined"]["count"] >= 1
    assert interpretation["comparison_groups"]["deep_confined"]["count"] >= 1
    assert interpretation["largest_gap"]


def test_named_divergence_pair_does_not_route_to_shallow_deep(monkeypatch):
    """Named well divergence should stay a cross-well question, not a shallow/deep fallback."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "Why do Lee L-1998 and Lee L-729 diverge?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    blob = " ".join(
        [
            interpretation.get("interpretation", ""),
            interpretation.get("direct_answer", ""),
            " ".join(interpretation.get("supporting_evidence", []) or []),
            " ".join(interpretation.get("limits", []) or []),
        ]
    ).lower()

    assert interpretation["question_intent"] != "shallow_deep_comparison"
    assert interpretation["scope_type"] == "cross_well"
    assert "lee l-1998" in blob
    assert "lee l-729" in blob
    assert "true shallow-vs-deep divergence comparison" not in blob


def test_fastest_changing_intent_names_well_first(monkeypatch):
    """Fastest-changing questions should lead with the named well and rate."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "Which well is changing fastest?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    assert interpretation["question_intent"] == "fastest_changing"
    assert "declining fastest" in interpretation["direct_answer"]
    assert "ft/yr" in interpretation["direct_answer"]
    assert interpretation["fastest_decline"]["name"] in interpretation["interpretation"]


def test_cohort_meaning_intent_explains_average(monkeypatch):
    """Average/cohort questions should explain the cohort statistic."""
    monkeypatch.setenv("GROUNDWATERGPT_EXPOSE_INTERPRETATION_RUBRIC", "1")
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "What does the cohort average mean?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    assert interpretation["question_intent"] == "cohort_meaning"
    assert "mean annual change" in interpretation["direct_answer"]
    assert "not a physical well" in interpretation["direct_answer"]
    assert "first screen" in " ".join(interpretation["supporting_evidence"])
    assert "outliers" in " ".join(interpretation["supporting_evidence"]).lower()
    assert interpretation["cohort_meaning"]["below_average"] >= 0
    assert interpretation["cohort_meaning"]["group_signal"]
    assert interpretation["cohort_meaning"]["student_takeaway"]
    assert interpretation["cohort_meaning"]["limitations"]
    assert interpretation["interpretation_rubric"]["intent"] == "cohort_meaning"
    assert interpretation["interpretation_rubric"]["required_moves"]


def test_risk_explanation_intent_explains_counts(monkeypatch):
    """Risk questions should explain the screening count behind the label."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "What does high screening risk mean?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    assert interpretation["question_intent"] == "risk_explanation"
    assert "screening risk means" in interpretation["direct_answer"]
    assert interpretation["risk_summary"]["n_total"] >= 1


def test_learner_brief_is_present_for_general_chart_interpretation(monkeypatch):
    """General-audience interpretation should always include the learner brief contract."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "What does this chart mean?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    brief = result["interpretation_response"]["learner_brief"]
    assert brief["direct_answer"]
    assert brief["what_to_notice"]
    assert brief["why_it_matters"]
    assert brief["important_limit"]
    assert brief["next_best_question"].endswith("?")


def test_terms_to_know_explain_jargon_when_used(monkeypatch):
    """Learner-facing outputs should explain cohort/risk jargon when it appears."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "What does the cohort average mean, and what does screening risk mean?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    terms = result["interpretation_response"]["terms_to_know"]
    blob = " ".join(
        " ".join(
            [
                item.get("term", ""),
                item.get("plain_definition", ""),
                item.get("why_it_matters_here", ""),
            ]
        ).lower()
        for item in terms
    )
    assert "cohort average" in blob
    assert "screening risk" in blob
    assert "not a real physical well" in blob or "not a physical well" in blob
    assert "not a diagnosis or a forecast" in blob


@pytest.mark.parametrize(
    ("question", "expected_warning"),
    [
        ("What does the cohort average mean?", "The cohort average is not a physical well."),
        ("What does high screening risk mean?", "High screening risk is not a forecast."),
        (
            "Do the shallow and deep aquifer wells diverge on this chart?",
            "Shallow versus deep comparison does not prove hydraulic connection.",
        ),
        ("Why is this well falling?", "A falling line is not proof of causation."),
    ],
)
def test_misconceptions_to_avoid_match_intent(monkeypatch, question, expected_warning):
    """Each learner-sensitive intent should carry the right chart-reading warning."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        question,
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    misconceptions = result["interpretation_response"]["misconceptions_to_avoid"]
    assert expected_warning in misconceptions


def test_prompt_head_is_stable():
    """The static prompt head should keep the grounding rules visible."""
    assert "Use only the supplied EvidencePack" in interpreter.INTERPRETER_PROMPT_HEAD
    assert "Do not invent measurements" in interpreter.INTERPRETER_PROMPT_HEAD
    assert "does not prove causation" in interpreter.INTERPRETER_PROMPT_HEAD


def test_numeric_claim_unit_enum_enforced():
    """Annual-change claims must use ft/yr."""
    with pytest.raises(ValueError):
        interpreter.NumericClaim(
            site="Lee L-729",
            value=-0.355,
            unit="ft",
            source="annual_change_ft_yr",
        )


def test_empty_evidence_pack_refuses_without_fabricating_numbers(monkeypatch):
    """Missing chart context should refuse gracefully."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    result = interpreter.interpret_with_context(
        "Why is it declining?",
        chart_context=None,
        turn_history=[],
        allow_llm_synthesis=False,
    )

    interpretation = result["interpretation_response"]
    assert interpretation["grounding_status"]["interpreter_status"] == "refused"
    assert interpretation["numeric_claims"] == []
    assert "does not support" in interpretation["interpretation"]


def test_llm_failure_falls_back_without_500(monkeypatch):
    """Malformed or unavailable structured LLM calls should not escape."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    monkeypatch.setattr(interpreter, "_grounded_reasoning_enabled", lambda: False)

    def _boom(_question, _pack):
        raise RuntimeError("bad tool call")

    monkeypatch.setattr(interpreter, "_invoke_structured_llm", _boom)

    result = interpreter.interpret_with_context(
        "Which one is changing fastest?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=True,
    )

    interpretation = result["interpretation_response"]
    assert result["status"] == "ok"
    assert interpretation["grounding_status"]["interpreter_status"] == "grounded"
    assert interpretation["numeric_claims"]


def test_both_llm_providers_unavailable_returns_grounded_not_500(monkeypatch):
    """With no Qwen key and no Ollama daemon, the deterministic path still answers 200."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    monkeypatch.setattr(interpreter, "_grounded_reasoning_enabled", lambda: False)

    def _no_llm(_provider, **_kwargs):
        raise RuntimeError("no LLM available")

    monkeypatch.setitem(
        __import__("sys").modules,
        "src.agent.llm_factory",
        type(
            "StubFactory",
            (),
            {
                "LLMProvider": type(
                    "Provider", (), {"__call__": classmethod(lambda cls, name: name)}
                ),
                "get_llm": _no_llm,
            },
        )(),
    )

    result = interpreter.interpret_with_context(
        "Which one is changing fastest?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=True,
    )
    assert result["status"] == "ok"
    assert result["interpretation_response"]["grounding_status"]["has_llm_synthesis"] is False


def test_structured_llm_provider_metadata_is_reported(monkeypatch):
    """When optional chart LLM synthesis runs, the API should expose provider/model."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", raising=False)
    monkeypatch.delenv("GROUNDWATERGPT_LLM_MODEL", raising=False)
    monkeypatch.delenv("GROUNDWATERGPT_INTERPRETER_MODEL", raising=False)
    monkeypatch.setenv("SYNTHESIS_MODEL", "fake-llama")
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    class FakeStructuredLLM:
        def invoke(self, _messages):
            return interpreter.InterpretationResult(
                answer=(
                    "Lee L-729 is declining fastest at -0.355 ft/yr. Compared with the "
                    "rising wells, that contrast shows the chart is mixed rather than "
                    "uniform. The available record still does not prove a cause."
                ),
                numeric_claims=[],
                citations=[{"url": "https://waterdata.usgs.gov/", "trust_level": "verified"}],
                evidence_used={"metric_keys": ["annual_change_ft_yr"]},
                grounding_status="grounded",
                follow_up_questions=[],
                guardrail_flags=[],
            )

    class FakeLLM:
        def with_structured_output(self, _schema):
            return FakeStructuredLLM()

    def _fake_get_llm(**_kwargs):
        return FakeLLM()

    monkeypatch.setitem(
        sys.modules,
        "src.agent.llm_factory",
        types.SimpleNamespace(
            LLMProvider=lambda provider_name: provider_name,
            get_llm=_fake_get_llm,
        ),
    )

    result = interpreter.interpret_with_context(
        "Which one is changing fastest?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=True,
    )

    interpretation = result["interpretation_response"]
    evidence_used = interpretation["evidence_used"]
    grounding = interpretation["grounding_status"]
    assert grounding["has_llm_synthesis"] is True
    assert grounding["llm_provider"] == "ollama"
    assert grounding["llm_model"] == "fake-llama"
    assert evidence_used["llm_provider"] == "ollama"
    assert evidence_used["llm_model"] == "fake-llama"


def test_llm_success_path_threads_answer_through(monkeypatch):
    """When structured LLM returns valid grounded content, its answer flows through."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    monkeypatch.setattr(interpreter, "_grounded_reasoning_enabled", lambda: False)

    def _good_llm(question, pack):
        per_site = pack["cross_well"]["per_site_metrics"]
        truth = min(per_site, key=lambda m: m["annual_change_ft_yr"])
        rise = max(per_site, key=lambda m: m["annual_change_ft_yr"])
        return interpreter.InterpretationResult(
            answer=(
                f"{truth['name']} is declining fastest at {truth['annual_change_ft_yr']:+.3f} "
                "ft/yr. Compared with "
                f"{rise['name']}, that contrast shows the chart is mixed rather than moving "
                "in one direction. The record still does not prove a cause."
            ),
            numeric_claims=[
                interpreter.NumericClaim(
                    site=truth["name"],
                    value=float(truth["annual_change_ft_yr"]),
                    unit="ft/yr",
                    source="annual_change_ft_yr",
                )
            ],
            citations=[{"url": "https://waterdata.usgs.gov/", "trust_level": "verified"}],
            evidence_used={"metric_keys": ["annual_change_ft_yr"], "rag_doc_ids": []},
            grounding_status="grounded",
            follow_up_questions=["What outside data would help test a cause?"],
            guardrail_flags=[],
        )

    monkeypatch.setattr(interpreter, "_invoke_structured_llm", _good_llm)

    result = interpreter.interpret_with_context(
        "Which one is changing fastest?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=True,
    )
    interpretation = result["interpretation_response"]
    assert interpretation["grounding_status"]["has_llm_synthesis"] is True
    assert "declining fastest" in interpretation["interpretation"].lower()
    assert interpretation["numeric_claims"]
    assert interpretation["numeric_claims"][0]["unit"] == "ft/yr"
    assert "shows the chart is mixed" in interpretation["interpretation"].lower()


def test_llm_bad_numerics_are_reconciled_against_pack(monkeypatch):
    """LLM claims that diverge from the deterministic pack must be corrected."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    def _bad_llm(question, pack):
        per_site = pack["cross_well"]["per_site_metrics"]
        truth = min(per_site, key=lambda m: m["annual_change_ft_yr"])
        return interpreter.InterpretationResult(
            answer=(
                f"{truth['name']} is the clearest declining signal on this chart. "
                "Compared with the rising wells, that ft/yr decline shows the chart is not moving uniformly and is worth follow-up. "  # noqa: E501
                "The chart still does not prove why it is happening."
            ),
            numeric_claims=[
                interpreter.NumericClaim(
                    site=truth["name"],
                    value=999.0,
                    unit="ft/yr",
                    source="annual_change_ft_yr",
                )
            ],
            citations=[],
            evidence_used={"metric_keys": ["annual_change_ft_yr"], "rag_doc_ids": []},
            grounding_status="grounded",
            follow_up_questions=[],
            guardrail_flags=[],
        )

    monkeypatch.setattr(interpreter, "_invoke_structured_llm", _bad_llm)

    result = interpreter.interpret_with_context(
        "Which one is changing fastest?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=True,
    )
    interpretation = result["interpretation_response"]
    reconciled = interpretation["numeric_claims"]
    assert reconciled, "Reconciled claims should still be present"
    assert (
        abs(float(reconciled[0]["value"])) < 50.0
    ), "Hallucinated 999 ft/yr should be reconciled back to the deterministic metric"
    flags = interpretation.get("guardrail_flags") or []
    assert any("llm_claim_value_mismatch" in str(flag) for flag in flags)


def test_qwen_success_path_returns_explainer_style_answer(monkeypatch):
    """Qwen synthesis should produce an explainer-style answer, not chart-summary echo."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.delenv("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", raising=False)
    monkeypatch.setenv("GROUNDWATERGPT_INTERPRETER_MODEL", "fake-qwen")
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    class FakeStructuredLLM:
        def invoke(self, _messages):
            return interpreter.InterpretationResult(
                answer=(
                    "Lee L-729 is declining fastest at -0.355 ft/yr. Compared with "
                    "Lee L-581 on the rising side, that tells you the chart is split "
                    "between decline and recovery rather than moving as one block. "
                    "That contrast matters more than the average alone, and it still "
                    "does not prove a cause."
                ),
                numeric_claims=[
                    interpreter.NumericClaim(
                        site="Lee L-729",
                        value=-0.355,
                        unit="ft/yr",
                        source="annual_change_ft_yr",
                    )
                ],
                citations=[{"url": "https://waterdata.usgs.gov/", "trust_level": "verified"}],
                evidence_used={"metric_keys": ["annual_change_ft_yr"]},
                grounding_status="grounded",
                follow_up_questions=[],
                guardrail_flags=[],
            )

    class FakeLLM:
        def with_structured_output(self, _schema):
            return FakeStructuredLLM()

    monkeypatch.setitem(
        sys.modules,
        "src.agent.llm_factory",
        types.SimpleNamespace(
            LLMProvider=lambda provider_name: provider_name,
            get_llm=lambda **_kwargs: FakeLLM(),
        ),
    )

    result = interpreter.interpret_with_context(
        "Which wells on this chart are changing fastest, and what are their rates?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=True,
    )

    interpretation = result["interpretation_response"]
    assert interpretation["grounding_status"]["has_llm_synthesis"] is True
    assert interpretation["grounding_status"]["llm_provider"] == "qwen"
    assert "Lee L-729" in interpretation["interpretation"]
    assert "ft/yr" in interpretation["interpretation"]
    assert "tells you the chart is split" in interpretation["interpretation"]
    assert all(
        phrase not in interpretation["interpretation"].lower()
        for phrase in interpreter.EXPLAINER_ECHO_PHRASES
    )


def test_summary_echo_llm_answer_falls_back_to_deterministic(monkeypatch):
    """Weak metadata-like LLM answers should be rejected in favor of deterministic output."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.delenv("GROUNDWATERGPT_DISABLE_LLM_SYNTHESIS", raising=False)
    monkeypatch.setenv("GROUNDWATERGPT_INTERPRETER_MODEL", "fake-qwen")
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    class FakeStructuredLLM:
        def invoke(self, _messages):
            return interpreter.InterpretationResult(
                answer=(
                    "This chart connects 3 USGS wells to a falling cohort trend. "
                    "Key deterministic rates are Lee L-729: -0.355 ft/yr. "
                    "Highlighted wells mark the most divergent or fastest-changing series."
                ),
                numeric_claims=[
                    interpreter.NumericClaim(
                        site="Lee L-729",
                        value=-0.355,
                        unit="ft/yr",
                        source="annual_change_ft_yr",
                    )
                ],
                citations=[{"url": "https://waterdata.usgs.gov/", "trust_level": "verified"}],
                evidence_used={"metric_keys": ["annual_change_ft_yr"]},
                grounding_status="grounded",
                follow_up_questions=[],
                guardrail_flags=[],
            )

    class FakeLLM:
        def with_structured_output(self, _schema):
            return FakeStructuredLLM()

    monkeypatch.setitem(
        sys.modules,
        "src.agent.llm_factory",
        types.SimpleNamespace(
            LLMProvider=lambda provider_name: provider_name,
            get_llm=lambda **_kwargs: FakeLLM(),
        ),
    )

    result = interpreter.interpret_with_context(
        "Which wells on this chart are changing fastest, and what are their rates?",
        chart_context=ESTERO_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=True,
    )

    interpretation = result["interpretation_response"]
    flags = interpretation.get("guardrail_flags") or []
    assert interpretation["grounding_status"]["has_llm_synthesis"] is False
    assert "This chart connects" not in interpretation["interpretation"]
    assert "Key deterministic rates are" not in interpretation["interpretation"]
    assert any("llm_explainer_summary_echo" in str(flag) for flag in flags)


def test_evidence_pack_builds_generalized_location_context(monkeypatch):
    """Evidence packs should expose generalized hydro context for any loaded cohort."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    pack = interpreter.build_evidence_pack(
        "How do these aquifer systems compare over time?",
        LEE_MULTI_AQUIFER_CONTEXT,
    )

    hydro = pack["location_hydro_context"]
    assert hydro["monitoring_basis"] == "USGS groundwater monitoring wells"
    assert hydro["cohort_period"]["start"]
    assert hydro["cohort_period"]["end"]
    assert len(hydro["aquifer_units"]) >= 3
    assert all(unit["zone"] for unit in hydro["aquifer_units"])
    assert pack["aquifer_summaries"]


def test_grounded_reasoning_path_threads_trace_and_metadata(monkeypatch):
    """Grounded reasoning should expose trace, source label, and reproducible references."""
    monkeypatch.setenv("GROUNDWATERGPT_ENABLE_GROUNDED_REASONING", "1")
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    monkeypatch.setattr(interpreter, "_invoke_structured_llm", lambda *_args, **_kwargs: None)

    def _grounded(*_args, **_kwargs):
        return GroundedInterpretation(
            intent="general",
            reasoning_steps=[
                ReasoningStep(
                    step_label="Identify wells",
                    observation="USGS groundwater monitoring wells Lee L-729 and Lee L-581 bound the current multi-aquifer chart context.",  # noqa: E501
                    evidence_keys=["wells", "cohort_period_start", "cohort_period_end"],
                    inference="The answer can be tied to specific monitoring wells and an explicit record window.",  # noqa: E501
                    confidence="high",
                ),
                ReasoningStep(
                    step_label="Compare aquifers",
                    observation="Aquifer summaries show different mean annual change across Surficial Sand, Sand and Shell, Hawthorn, and Floridan zones.",  # noqa: E501
                    evidence_keys=["aquifer_summaries", "cross_well.per_site_metrics"],
                    inference="The response should stay separated by aquifer rather than flattening all wells into one cohort signal.",  # noqa: E501
                    confidence="medium",
                ),
            ],
            direct_answer=(
                "Using USGS groundwater monitoring wells from 1994-01-01 to 2026-04-05, "
                "the Lee County cohort shows different long-term behavior across aquifer units."
            ),
            aquifer_summaries=[
                {
                    "zone": "Surficial Sand",
                    "mean_annual_change": -0.11,
                    "n_falling": 3,
                    "n_rising": 0,
                },
                {
                    "zone": "Sand and Shell",
                    "mean_annual_change": -0.08,
                    "n_falling": 3,
                    "n_rising": 1,
                },
            ],
            why_it_matters="That split matters because shallow and confined units may reflect different stresses and monitoring priorities.",  # noqa: E501
            limitations=[
                "Monitoring wells are proxies for aquifer behavior rather than direct production-well records."  # noqa: E501
            ],
            follow_up_questions=["Is this decline seasonal or persistent?"],
            numeric_claims=[
                GroundedNumericClaim(
                    site="Lee L-729",
                    value=-0.355,
                    unit="ft/yr",
                    source="annual_change_ft_yr",
                )
            ],
            perspectives=[],
            grounding_status="grounded",
            llm_provider="ollama",
            llm_model="fake-grounded",
        )

    monkeypatch.setattr(interpreter, "invoke_grounded_reasoning", _grounded)

    result = interpreter.interpret_with_context(
        "What has been the change in groundwater level across these aquifer units?",
        chart_context=LEE_MULTI_AQUIFER_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=True,
    )

    interpretation = result["interpretation_response"]
    assert interpretation["reasoning_source"] == "grounded_llm"
    assert interpretation["reasoning_trace"]
    assert interpretation["grounding_status"]["has_llm_synthesis"] is True
    assert interpretation["grounding_status"]["llm_model"] == "fake-grounded"
    assert interpretation["aquifer_summaries"]
    assert interpretation["data_references"][0]["lat"] is not None
    assert interpretation["data_references"][0]["record_start"]
    assert interpretation["data_references"][0]["record_end"]


def _make_grounded_with_langgraph_trace(trace):
    grounded = GroundedInterpretation(
        intent="general",
        reasoning_steps=[
            ReasoningStep(
                step_label="Identify wells",
                observation="USGS wells Lee L-729 and Lee L-581 anchor the chart context.",
                evidence_keys=["wells"],
                inference="Answer can be tied to specific monitoring wells.",
                confidence="high",
            ),
        ],
        direct_answer=(
            "Across the loaded USGS records the cohort declines unevenly by aquifer; "
            "Hawthorn wells are falling fastest while Surficial Sand stays near zero."
        ),
        aquifer_summaries=[
            {"zone": "Surficial Sand", "mean_annual_change": -0.05, "n_falling": 1, "n_rising": 1},
        ],
        why_it_matters="Confined and unconfined units respond to different stresses.",
        limitations=["Monitoring records, not production-well data."],
        follow_up_questions=["Is this decline seasonal or persistent?"],
        numeric_claims=[
            GroundedNumericClaim(
                site="Lee L-729", value=-0.355, unit="ft/yr", source="annual_change_ft_yr"
            )
        ],
        perspectives=[],
        grounding_status="grounded",
        llm_provider="ollama",
        llm_model="fake-langgraph",
    )
    object.__setattr__(grounded, "langgraph_trace", list(trace))
    return grounded


def test_langgraph_path_preserves_source_trace_and_deadline(monkeypatch):
    """LangGraph results must keep reasoning_source=langgraph and expose trace separately."""
    monkeypatch.setenv("GROUNDWATERGPT_ENABLE_GROUNDED_REASONING", "1")
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    # Simulate a polish LLM that would normally trip rejection flags — should be ignored
    # because the langgraph branch already produced a grounded answer.
    monkeypatch.setattr(
        interpreter,
        "_invoke_structured_llm",
        lambda *_args, **_kwargs: None,
    )

    captured: dict = {}
    sample_trace = [
        {"node": "frame", "scope": "site", "goal": "trend"},
        {"node": "sample_reason", "samples": 2},
        {"node": "synthesize", "emitted": True},
    ]

    fake_module = types.ModuleType("src.agent.interpretation_graph")

    def _enabled() -> bool:
        return True

    def _run(question, pack, **kwargs):
        captured["kwargs"] = kwargs
        captured["question"] = question
        return _make_grounded_with_langgraph_trace(sample_trace)

    fake_module.langgraph_interpreter_enabled = _enabled
    fake_module.run_interpretation_graph = _run
    monkeypatch.setitem(sys.modules, "src.agent.interpretation_graph", fake_module)

    result = interpreter.interpret_with_context(
        "What has been the change in groundwater level across these aquifer units?",
        chart_context=LEE_MULTI_AQUIFER_CONTEXT,
        turn_history=[],
        allow_llm_synthesis=True,
    )

    interpretation = result["interpretation_response"]
    assert interpretation["reasoning_source"] == "langgraph"
    # reasoning_trace must remain flat step dicts the UI can render
    assert interpretation["reasoning_trace"]
    for step in interpretation["reasoning_trace"]:
        assert isinstance(step, dict)
        assert "langgraph_trace" not in step
        assert "step_label" in step
    # langgraph_trace exposed as a separate, opaque field
    assert interpretation["langgraph_trace"] == sample_trace
    # deadline must have been forwarded into the graph
    assert "deadline" in captured["kwargs"]
    assert captured["kwargs"]["deadline"] is not None
