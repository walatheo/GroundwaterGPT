"""Tests for semantic auto-flags in the chat review harness."""

from scripts.run_chat_review import _auto_flags


def test_auto_flags_detect_missing_named_entity_and_rate_for_ranking_case():
    turn = {
        "prompt": "Which well is changing fastest in this dataset?",
        "expected_route_mode": "network",
        "expected_answer_type": "data_answer",
        "require_named_entity": True,
        "require_numeric_rate": True,
    }
    body = {
        "route_mode": "network",
        "answer_type": "data_answer",
        "grounded_answer": {
            "direct_answer": "The monitoring network is falling overall.",
            "limits": ["This is a screening view."],
            "next_best_question": "Which aquifer looks most stressed?",
        },
        "response": "The monitoring network is falling overall.",
    }

    flags = _auto_flags(turn, body, status_code=200)

    assert "missing_named_entity" in flags
    assert "missing_numeric_support" in flags


def test_auto_flags_detect_missing_screening_caveat():
    turn = {
        "prompt": "Which aquifer looks most stressed in this dataset?",
        "expected_route_mode": "network",
        "expected_answer_type": "data_answer",
        "require_numeric_rate": True,
        "require_screening_caveat": True,
    }
    body = {
        "route_mode": "network",
        "answer_type": "data_answer",
        "grounded_answer": {
            "direct_answer": "Surficial Aquifer is at -0.094 ft/yr.",
            "limits": ["Observed from monitoring wells."],
            "next_best_question": "How does that compare with Floridan?",
        },
        "response": "Surficial Aquifer is at -0.094 ft/yr.",
    }

    flags = _auto_flags(turn, body, status_code=200)

    assert "weak_screening_caveat" in flags


def test_auto_flags_detect_fallback_when_grounded_route_expected():
    turn = {
        "prompt": "Which well is changing fastest in this dataset?",
        "expected_route_mode": "network",
        "require_named_entity": True,
    }
    body = {
        "route_mode": "fallback",
        "answer_type": "data_answer",
        "grounded_answer": {
            "direct_answer": "Groundwater changes over time based on rainfall and pumping.",
            "limits": ["Generic groundwater guidance."],
            "next_best_question": "Could you name a well?",
        },
        "response": "Groundwater changes over time based on rainfall and pumping.",
    }

    flags = _auto_flags(turn, body, status_code=200)

    assert "fell_to_fallback_when_should_be_grounded" in flags
