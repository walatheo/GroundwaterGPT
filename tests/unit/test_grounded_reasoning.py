"""Tests for grounded reasoning validation helpers."""

import time

from api.routes import _chart_interpreter as interpreter
from api.routes.answering import reasoning as grounded

LEE_CONTEXT = {
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


def test_validate_against_pack_rejects_unknown_evidence_keys(monkeypatch):
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    pack = interpreter.build_evidence_pack("Summarize this chart.", LEE_CONTEXT, [])

    interpretation = grounded.GroundedInterpretation(
        intent="general",
        framing=grounded.GroundedFraming(
            scope_type="cohort",
            question_goal="contextualize",
            required_evidence_sections=["wells"],
        ),
        reasoning_steps=[
            grounded.ReasoningStep(
                step_label="Bad key",
                observation="Observation",
                evidence_keys=["not_a_real_key"],
                inference="Inference",
                confidence="high",
            )
        ],
        direct_answer="Using USGS groundwater monitoring wells from 1994-01-01 to 2026-04-05, the cohort is mixed.",  # noqa: E501
        aquifer_summaries=pack["aquifer_summaries"][:2],
        why_it_matters="It matters for monitoring priority.",
        limitations=[],
        follow_up_questions=[],
        numeric_claims=[],
        perspectives=[],
        grounding_status="grounded",
    )

    flags = grounded.validate_against_pack(interpretation, pack)
    assert any("grounded_reasoning_bad_evidence_key" in flag for flag in flags)


def test_success_criteria_require_period_and_aquifer_coverage(monkeypatch):
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    pack = interpreter.build_evidence_pack("Summarize this chart.", LEE_CONTEXT, [])

    interpretation = grounded.GroundedInterpretation(
        intent="general",
        framing=grounded.GroundedFraming(
            scope_type="cohort",
            question_goal="contextualize",
            required_evidence_sections=["wells", "aquifer_summaries"],
        ),
        reasoning_steps=[
            grounded.ReasoningStep(
                step_label="Compare aquifers",
                observation="USGS groundwater monitoring wells indicate differing aquifer behavior.",  # noqa: E501
                evidence_keys=["wells", "aquifer_summaries"],
                inference="Different aquifers should be separated in the answer.",
                confidence="high",
            )
        ],
        direct_answer="USGS groundwater monitoring wells show change in this cohort.",
        aquifer_summaries=[],
        why_it_matters="This matters for monitoring priority.",
        limitations=[],
        follow_up_questions=[],
        numeric_claims=[],
        perspectives=[],
        grounding_status="grounded",
    )

    flags = grounded._check_success_criteria(
        interpretation,
        {
            **pack,
            "interpretation_rubric": {
                "required_moves": ["State the observed signal from chart metrics."]
            },
        },
    )
    assert "grounded_reasoning_missing_time_period" in flags
    assert "grounded_reasoning_missing_aquifer_separation" in flags


def test_derive_question_frame_detects_cross_well_context(monkeypatch):
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    pack = interpreter.build_evidence_pack(
        "Why do Lee L-1998 and Lee L-729 diverge?",
        LEE_CONTEXT,
        [],
    )

    frame = grounded.derive_question_frame(
        "Why do Lee L-1998 and Lee L-729 diverge?",
        pack,
    )

    assert frame.scope_type == "cross_well"
    assert "Lee L-1998" in frame.focus_entities
    assert "Lee L-729" in frame.focus_entities
    assert frame.question_goal == "compare"


def test_invoke_with_llm_timeout_returns_none_for_slow_call():
    started = time.monotonic()
    result = grounded.invoke_with_llm_timeout(
        lambda: (time.sleep(0.05), {"ok": True})[1],
        timeout_seconds=0.01,
        label="slow-test-call",
    )
    elapsed = time.monotonic() - started

    assert result is None
    assert elapsed < 0.2


def test_llm_timeout_seconds_is_clamped(monkeypatch):
    # Budget cap was raised to 120s in df52195; a mid-range value passes through.
    monkeypatch.setenv("GROUNDWATERGPT_LLM_TIMEOUT_SECONDS", "45")
    assert grounded.llm_timeout_seconds() == 45.0
    # Above the cap is still clamped so runaway configs cannot stall requests.
    monkeypatch.setenv("GROUNDWATERGPT_LLM_TIMEOUT_SECONDS", "500")
    assert grounded.llm_timeout_seconds() == 120.0


def test_derive_question_frame_detects_supply_unit_scope(monkeypatch):
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    pack = interpreter.build_evidence_pack(
        "Why is Upper Floridan the most stressed supply unit in this dataset?",
        {
            "chart_id": "Estero Monthly Groundwater Levels",
            "site_ids": ["263335081394301", "263532081592201", "262538082045701"],
            "chart_type": "comparison",
            "summary_metrics": {"title": "Estero Monthly Groundwater Levels"},
        },
        [],
    )

    frame = grounded.derive_question_frame(
        "Why is Upper Floridan the most stressed supply unit in this dataset?",
        pack,
    )

    assert frame.scope_type == "supply_unit"
    assert "Upper Floridan" in frame.focus_entities
    assert frame.question_goal in {"rank", "source_proxy"}


def test_validate_against_pack_rejects_missing_focus_entity(monkeypatch):
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    pack = interpreter.build_evidence_pack(
        "On G-3764, what matters most in this chart and why?",
        {
            "chart_id": "Miami-Dade comparison",
            "site_ids": ["254815080343801", "255055080304801"],
            "chart_type": "comparison",
            "summary_metrics": {"title": "Miami-Dade comparison"},
        },
        [],
    )

    interpretation = grounded.GroundedInterpretation(
        intent="general",
        framing=grounded.GroundedFraming(
            scope_type="well",
            focus_entities=["Miami-Dade G-3764"],
            comparison_entities=["cohort"],
            question_goal="contextualize",
            required_evidence_sections=["well_summaries", "comparison_features"],
        ),
        reasoning_steps=[
            grounded.ReasoningStep(
                step_label="Summarize",
                observation="The cohort is mixed.",
                evidence_keys=["comparison_features", "well_summaries"],
                inference="The answer should explain the dataset pattern.",
                confidence="high",
            )
        ],
        direct_answer="Using USGS groundwater monitoring wells from 1994-01-01 to 2026-04-05, the chart is mixed.",  # noqa: E501
        what_matters_most="The dataset contains both rising and falling wells.",
        aquifer_summaries=pack["aquifer_summaries"],
        why_it_matters="This matters for monitoring priority.",
        evidence_used_summary=["Evidence used: the cohort mean and chart contrast."],
        limitations=["The chart does not prove causation."],
        important_limits=["The chart does not prove causation."],
        follow_up_questions=[],
        numeric_claims=[],
        perspectives=[],
        answer_moves_completed=["summarized_dataset"],
        grounding_status="grounded",
    )

    flags = grounded.validate_against_pack(interpretation, pack)
    assert any(flag.startswith("grounded_reasoning_missing_focus_entity") for flag in flags)


def test_build_reasoning_evidence_normalizes_chat_style_site_fields():
    evidence = grounded._build_reasoning_evidence(
        {
            "sites": [
                {
                    "name": "Miami-Dade G-3764",
                    "site_id": "254815080343801",
                    "aq_label": "Biscayne Aquifer",
                    "aq_zone": "Biscayne",
                    "annual_change": 0.079,
                    "record_start": "1994-01-01",
                    "record_end": "2024-01-01",
                    "trend": "rising",
                    "seasonal_amplitude_ft": 1.5,
                    "wet_season_mean_ft": 4.2,
                    "dry_season_mean_ft": 3.5,
                }
            ],
            "cross_well": {},
        },
        None,
    )

    well = evidence["wells"][0]
    assert well["aquifer"] == "Biscayne Aquifer"
    assert well["zone"] == "Biscayne"
    assert well["ft_yr"] == 0.079
    assert well["period"] == ["1994-01-01", "2024-01-01"]
    assert well["trend"] == "rising"
    assert well["seasonal_amp_ft"] == 1.5
    assert well["wet_dry_mean"] == [4.2, 3.5]


def test_build_chat_synthesis_pack_exposes_framing_fields():
    pack = grounded._build_chat_synthesis_pack(
        site_computed=[
            {
                "name": "Lee L-729",
                "site_id": "263041081433102",
                "aq_label": "Intermediate Aquifer System",
                "aq_zone": "Sand and Shell",
                "annual_change": -0.25,
                "record_start": "1994-01-01",
                "record_end": "2026-04-05",
            }
        ],
        aquifer_summaries=[
            {
                "aquifer": "Intermediate Aquifer System",
                "zone": "Sand and Shell",
                "mean_annual_change": -0.25,
            }
        ],
        cross_well={"risk_level": "moderate"},
        supply_info={
            "municipality": "Village of Estero",
            "utility": "Lee County Utilities",
            "data_confidence": "moderate",
            "known_risks": ["Saltwater intrusion"],
            "supply_aquifers": [
                {
                    "aquifer": "Intermediate Aquifer System",
                    "zone": "Sand and Shell",
                    "usage": "Primary municipal supply",
                    "proxy_wells": [{"name": "Lee L-729"}],
                }
            ],
        },
    )

    assert pack["well_summaries"][0]["aquifer_zone"] == "Sand and Shell"
    assert pack["supply_unit_summaries"][0]["zone"] == "Sand and Shell"
    assert "Lee L-729" in pack["entity_catalog"]["well_names"]
    assert "Sand and Shell" in pack["entity_catalog"]["supply_units"]
    assert pack["cohort_period_start"] == "1994-01-01"
    assert pack["cohort_period_end"] == "2026-04-05"


def test_strip_reasoning_artifacts_removes_think_blocks():
    raw = '<think>internal reasoning</think>\n{"scope_type":"cohort"}'
    cleaned = grounded._strip_reasoning_artifacts(raw)
    assert cleaned == '{"scope_type":"cohort"}'


def test_build_frame_prompt_uses_open_reasoning_prefix(monkeypatch):
    monkeypatch.setattr(interpreter, "_rag_snippets", lambda _question: [])
    pack = interpreter.build_evidence_pack("Summarize this chart.", LEE_CONTEXT, [])
    messages = grounded._build_frame_prompt(
        "Why is Upper Floridan the most stressed supply unit in this dataset?",
        pack,
        provider_name="ollama",
        model="qwen3:32b",
    )

    assert messages[0][0] == "system"
    assert messages[1][1].startswith("/think\n")
