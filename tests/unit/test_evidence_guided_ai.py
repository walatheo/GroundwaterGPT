"""Tests for shared evidence-guided AI progression helpers."""

from api.routes.answering import followups as guided_ai


def test_deterministic_progression_builds_goal_and_groups():
    seed = {
        "question": "What are the groundwater sources the Village of Estero uses?",
        "direct_answer": "Village of Estero relies on Sand and Shell and the Floridan aquifer proxies.",  # noqa: E501
        "supporting_evidence": [
            "Sand and Shell is the primary supply unit in this deterministic mapping.",
        ],
        "evidence_needed": ["utility construction records"],
        "supply_units": [{"zone": "Sand and Shell"}, {"zone": "Floridan"}],
        "well_names": ["Lee L-729", "Lee L-581"],
        "follow_up_questions": ["Which proxy wells represent the Sand and Shell supply unit?"],
    }

    progression = guided_ai.build_evidence_guided_progression(seed, allow_llm_rewrite=False)

    assert "utility construction records" in progression["next_goal"].lower()
    assert progression["follow_up_groups"]
    assert progression["follow_up_questions"]
    assert any(group["label"] == "Understand this" for group in progression["follow_up_groups"])


def test_progression_rewrite_rejects_generic_output(monkeypatch):
    seed = {
        "question": "Why is this declining?",
        "direct_answer": "The chart shows a decline, but it does not prove the cause.",
        "supporting_evidence": ["Lee L-729 declines faster than the cohort average."],
        "well_names": ["Lee L-729"],
    }

    monkeypatch.setattr(
        guided_ai,
        "_invoke_progression_rewrite",
        lambda *_args, **_kwargs: guided_ai.ProgressionRewrite(
            next_goal="Learn more.",
            follow_up_groups=[
                guided_ai.FollowUpGroup(
                    label="Understand this",
                    questions=["Tell me more?"],
                )
            ],
        ),
    )

    progression = guided_ai.build_evidence_guided_progression(seed, allow_llm_rewrite=True)

    assert progression["progression_source"] == "deterministic"
    assert progression["progression_guardrail_flags"]


def test_progression_rewrite_accepts_grounded_specific_output(monkeypatch):
    seed = {
        "question": "Which well is changing fastest?",
        "question_intent": "fastest_changing",
        "direct_answer": "Lee L-729 is declining fastest at -0.42 ft/yr.",
        "answer_text": "Lee L-729 is declining fastest at -0.42 ft/yr.",
        "supporting_evidence": ["Lee L-581 is less negative than Lee L-729."],
        "well_names": ["Lee L-729", "Lee L-581"],
        "follow_up_questions": [
            "Compare Lee L-729 and Lee L-581 using the same chart and well metadata."
        ],
    }

    monkeypatch.setattr(
        guided_ai,
        "_invoke_progression_rewrite",
        lambda *_args, **_kwargs: guided_ai.ProgressionRewrite(
            next_goal="Compare Lee L-729 with Lee L-581 before generalizing the chart signal.",
            follow_up_groups=[
                guided_ai.FollowUpGroup(
                    label="Compare wells or units",
                    questions=[
                        "How does Lee L-729 compare with Lee L-581 on the same chart?",
                    ],
                )
            ],
        ),
    )

    progression = guided_ai.build_evidence_guided_progression(seed, allow_llm_rewrite=True)

    assert progression["progression_source"] == "llm_rewrite"
    assert "Lee L-729" in progression["next_goal"]
    assert progression["follow_up_groups"][0]["label"] == "Compare wells or units"


def test_reasoning_gaps_are_promoted_into_followups():
    seed = {
        "question": "What do these aquifer trends mean?",
        "question_intent": "general",
        "direct_answer": "The cohort is mixed across aquifers.",
        "well_names": ["Lee L-729", "Lee L-581"],
    }

    progression = guided_ai.build_evidence_guided_progression(
        seed,
        allow_llm_rewrite=False,
        reasoning_trace=[
            {
                "step_label": "Compare aquifers",
                "observation": "Seasonal behavior may differ across shallow and confined wells.",
                "inference": "Need more confidence about whether this is seasonal or persistent.",
                "confidence": "medium",
            },
            {
                "step_label": "Map supply proxies",
                "observation": "Supply proxy fit is only moderate for this cohort.",
                "inference": "Utility construction records would reduce uncertainty.",
                "confidence": "low",
            },
        ],
    )

    questions = progression["follow_up_questions"]
    assert questions
    assert questions[0] == "Is this decline seasonal or persistent?"
    assert any("utility or construction records" in question.lower() for question in questions)
