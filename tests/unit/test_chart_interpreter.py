"""Tests for chart-context interpretation helpers."""

import pytest

from api.routes import _chart_interpreter as interpreter

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


def test_evidence_pack_assembles_cross_well_metrics(monkeypatch):
    """EvidencePack should reuse local chart/site data and expose metric keys."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    pack = interpreter.build_evidence_pack("Which well is changing fastest?", ESTERO_CONTEXT)

    assert pack["site_ids"] == ESTERO_CONTEXT["site_ids"]
    assert pack["cross_well"]["per_site_metrics"]
    assert pack["insights"]
    assert pack["explainability"]["how_to_read"]


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
    assert "pumping" in " ".join(interpretation["evidence_needed"]).lower()
    assert "does not prove" in interpretation["confidence_notes"][0].lower()
    assert "enriched_rag_query" in interpretation["evidence_used"]
    assert "What caveats should I mention?" in interpretation["follow_up_questions"]


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
    assert interpretation["cohort_meaning"]["below_average"] >= 0


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


def test_llm_success_path_threads_answer_through(monkeypatch):
    """When structured LLM returns valid grounded content, its answer flows through."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    def _good_llm(question, pack):
        per_site = pack["cross_well"]["per_site_metrics"]
        truth = min(per_site, key=lambda m: m["annual_change_ft_yr"])
        return interpreter.InterpretationResult(
            answer=(
                f"The fastest decline belongs to {truth['name']} "
                f"at {truth['annual_change_ft_yr']:+.3f} ft/yr according to the EvidencePack."
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
    assert "fastest decline" in interpretation["interpretation"].lower()
    assert interpretation["numeric_claims"]
    assert interpretation["numeric_claims"][0]["unit"] == "ft/yr"


def test_llm_bad_numerics_are_reconciled_against_pack(monkeypatch):
    """LLM claims that diverge from the deterministic pack must be corrected."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    def _bad_llm(question, pack):
        per_site = pack["cross_well"]["per_site_metrics"]
        truth = min(per_site, key=lambda m: m["annual_change_ft_yr"])
        return interpreter.InterpretationResult(
            answer=f"The fastest decline is about 999 ft/yr at {truth['name']}.",
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
