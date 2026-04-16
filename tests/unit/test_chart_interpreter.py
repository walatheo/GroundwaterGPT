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
