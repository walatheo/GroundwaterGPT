"""Tests for chart-context interpretation helpers."""

import pytest

from api.routes import _chart_interpreter as interpreter

ESTERO_CONTEXT = {
    "chart_id": "Estero Monthly Groundwater Levels",
    "site_ids": ["263335081394301", "263532081592201", "262538082045701"],
    "chart_type": "comparison",
    "summary_metrics": {"title": "Estero Monthly Groundwater Levels"},
}


def test_evidence_pack_assembles_cross_well_metrics(monkeypatch):
    """EvidencePack should reuse local chart/site data and expose metric keys."""
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])

    pack = interpreter.build_evidence_pack("Which well is changing fastest?", ESTERO_CONTEXT)

    assert pack["site_ids"] == ESTERO_CONTEXT["site_ids"]
    assert pack["cross_well"]["per_site_metrics"]
    assert pack["insights"]
    assert pack["explainability"]["how_to_read"]


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
