"""Phase 3 tests — the single explainer's prompt and policy validator."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.routes._explainer import (
    EXPLAINER_SYSTEM_PROMPT,
    ExplainerResult,
    build_explainer_messages,
    explain_grounded_answer,
    validate_explanation,
)
from api.routes.answering.composer import GroundedAnswer


def _answer(
    *,
    direct: str = "G-3336 fell 0.8 ft over the record.",
    findings: list[str] | None = None,
    limits: list[str] | None = None,
    nbq: str | None = None,
    evidence: list[dict] | None = None,
) -> GroundedAnswer:
    return GroundedAnswer(
        direct_answer=direct,
        grounded_findings=findings or ["Monthly mean fell 0.8 ft since 2018."],
        limits=limits or ["Record covers 2010-2024."],
        next_best_question=nbq,
        supporting_evidence=evidence
        or [{"kind": "well", "site_id": "G-3336", "name": "G-3336", "aquifer": "Biscayne"}],
    )


class FakeLLM:
    """Minimal LLM double — records the messages and returns a canned reply."""

    def __init__(self, reply: str, *, raises: Exception | None = None):
        self.reply = reply
        self.raises = raises
        self.calls: list = []

    def invoke(self, messages):  # noqa: D401 — mirrors langchain signature
        self.calls.append(messages)
        if self.raises:
            raise self.raises
        return SimpleNamespace(content=self.reply)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class TestValidator:
    def test_empty_narrative_is_clean(self):
        assert validate_explanation("", _answer()) == []

    def test_narrative_using_only_evidence_is_clean(self):
        narrative = "G-3336 has fallen 0.8 ft since 2018. The record covers 2010-2024."
        assert validate_explanation(narrative, _answer()) == []

    def test_invented_number_is_flagged(self):
        narrative = "G-3336 fell 2.4 ft — a serious decline."
        violations = validate_explanation(narrative, _answer())
        assert "unsupported_number:2.4" in violations

    def test_invented_year_is_flagged(self):
        narrative = "G-3336 fell 0.8 ft, starting in 2005."
        violations = validate_explanation(narrative, _answer())
        assert "unsupported_year:2005" in violations

    def test_invented_site_id_is_flagged(self):
        narrative = "G-3336 fell 0.8 ft, while G-9999 held steady."
        violations = validate_explanation(narrative, _answer())
        assert any(v.startswith("unsupported_site_id:") and "G9999" in v for v in violations)

    def test_numbers_in_evidence_are_allowed(self):
        answer = _answer(findings=["The cohort of 12 wells averaged -0.3 ft/yr."])
        narrative = "The cohort of 12 wells saw an average drop of -0.3 ft/yr."
        assert validate_explanation(narrative, answer) == []

    def test_year_matches_dont_count_as_number_violation(self):
        # Evidence lists 2018 only; narrative uses 2018. No number violation
        # because years and numbers are tracked separately.
        narrative = "The decline began in 2018 after a stable prior decade."
        assert validate_explanation(narrative, _answer()) == []

    def test_site_id_in_supporting_evidence_is_allowed(self):
        answer = _answer(
            evidence=[{"kind": "well", "site_id": "G-3336"}, {"kind": "well", "site_id": "G-5004"}]
        )
        narrative = "G-3336 and G-5004 both showed declines."
        assert validate_explanation(narrative, answer) == []

    def test_multiple_violations_reported(self):
        narrative = "G-9999 fell 2.4 ft in 2005."
        violations = validate_explanation(narrative, _answer())
        # Expect three: bad site id, bad number, bad year.
        assert len(violations) == 3


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


class TestPromptBuilder:
    def test_messages_carry_system_and_human(self):
        messages = build_explainer_messages(_answer(), question="Why is G-3336 falling?")
        assert len(messages) == 2
        assert messages[0][0] == "system"
        assert messages[0][1] == EXPLAINER_SYSTEM_PROMPT
        assert messages[1][0] == "human"

    def test_user_message_includes_all_answer_fields(self):
        answer = _answer(
            direct="G-3336 fell 0.8 ft.",
            findings=["Monthly mean fell.", "Seasonal swing narrowed."],
            limits=["Only 10 years of record."],
            nbq="What nearby wells show the same pattern?",
            evidence=[{"kind": "well", "site_id": "G-3336", "name": "Estero Monitor"}],
        )
        user = build_explainer_messages(answer, question="Why?")[1][1]
        assert "G-3336 fell 0.8 ft." in user
        assert "Monthly mean fell." in user
        assert "Seasonal swing narrowed." in user
        assert "Only 10 years of record." in user
        assert "What nearby wells show the same pattern?" in user
        assert "G-3336" in user
        assert "Estero Monitor" in user

    def test_empty_sections_render_cleanly(self):
        answer = GroundedAnswer(direct_answer="No data available.")
        user = build_explainer_messages(answer, question="Anything?")[1][1]
        assert "(none)" in user  # findings / limits / evidence all empty


# ---------------------------------------------------------------------------
# explain_grounded_answer end-to-end with a FakeLLM
# ---------------------------------------------------------------------------


class TestExplainGroundedAnswer:
    def test_accepts_clean_narrative(self):
        llm = FakeLLM(
            "G-3336 has declined 0.8 ft since 2018. The trend is consistent across the record."
        )
        result = explain_grounded_answer(_answer(), question="Why is it falling?", llm=llm)
        assert result.accepted is True
        assert result.violations == []
        assert "G-3336" in result.narrative

    def test_rejects_narrative_with_invented_number(self):
        llm = FakeLLM("G-3336 has declined 3.7 ft — dramatic.")
        result = explain_grounded_answer(_answer(), question="Why?", llm=llm)
        assert result.accepted is False
        assert "unsupported_number:3.7" in result.violations

    def test_llm_exception_returns_unavailable(self):
        llm = FakeLLM("", raises=RuntimeError("boom"))
        result = explain_grounded_answer(_answer(), question="Why?", llm=llm)
        assert result.accepted is False
        assert result.violations == ["llm_invoke_failed"]
        assert result.narrative == ""

    def test_result_to_dict_round_trips(self):
        result = ExplainerResult(narrative="hi", accepted=True, provider="ollama", model="qwen3")
        as_dict = result.to_dict()
        assert as_dict == {
            "narrative": "hi",
            "accepted": True,
            "violations": [],
            "provider": "ollama",
            "model": "qwen3",
        }

    def test_plain_string_reply_is_handled(self):
        class PlainLLM:
            def invoke(self, _messages):
                return "G-3336 fell 0.8 ft."

        result = explain_grounded_answer(_answer(), question="Why?", llm=PlainLLM())
        assert result.accepted is True
        assert result.narrative == "G-3336 fell 0.8 ft."


@pytest.mark.parametrize(
    "narrative,expected_substring",
    [
        ("A clean reply.", None),
        ("The well fell 0.8 ft.", None),
        ("Invented 5.6 ft claim.", "unsupported_number:5.6"),
        ("Invented year 1999.", "unsupported_year:1999"),
        ("Referenced G-0001.", "unsupported_site_id:G0001"),
    ],
)
def test_validator_parametrized(narrative, expected_substring):
    violations = validate_explanation(narrative, _answer())
    if expected_substring is None:
        assert violations == []
    else:
        assert expected_substring in violations
