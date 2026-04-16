"""Routing tests for chart-context conversational follow-ups."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.main import app  # noqa: E402

client = TestClient(app)


ESTERO_CONTEXT = {
    "chart_id": "Estero Monthly Groundwater Levels",
    "site_ids": ["263335081394301", "263532081592201", "262538082045701"],
    "chart_type": "comparison",
    "summary_metrics": {"title": "Estero Monthly Groundwater Levels"},
}


def _stub_interpreter(question, chart_context, turn_history, **_kwargs):
    return {
        "response": f"Stubbed chart answer for {question}",
        "context": "Chart-context interpretation",
        "sources": ["https://waterdata.usgs.gov/monitoring-location/263335081394301/"],
        "mode": "chart_interpreter",
        "status": "ok",
        "claim_citations": [],
        "interpretation_response": {
            "schema_version": "interpretation_response_v1",
            "question": question,
            "audience": "general",
            "interpretation": "Stubbed chart answer.",
            "numeric_claims": [],
            "follow_up_questions": ["What should I check next?"],
            "grounding_status": {
                "uses_chart_context": True,
                "uses_usgs_data": True,
                "invented_measurements_allowed": False,
                "interpreter_status": "grounded",
            },
            "chart_context": {"summary": "Stub context"},
            "data_references": [],
        },
        "chart_context_used": chart_context,
        "turn_history_used": turn_history,
    }


def test_chart_context_open_ended_routes_to_interpreter(monkeypatch):
    """Open-ended chart follow-ups should reach the interpreter branch."""
    from api.routes import chat as chat_routes

    monkeypatch.setattr(chat_routes._chart_interpreter, "interpret_with_context", _stub_interpreter)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Why are they declining?",
            "chart_context": ESTERO_CONTEXT,
            "allow_llm_synthesis": False,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "chart_interpreter"
    assert body["interpretation_response"]["grounding_status"]["uses_chart_context"] is True


def test_chart_context_compare_followup_routes_to_interpreter(monkeypatch):
    """Compare/using-chart follow-up chips should keep chart context."""
    from api.routes import chat as chat_routes

    monkeypatch.setattr(chat_routes._chart_interpreter, "interpret_with_context", _stub_interpreter)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Compare these wells using the chart.",
            "chart_context": ESTERO_CONTEXT,
            "allow_llm_synthesis": False,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "chart_interpreter"
    assert body["chart_context_used"]["chart_id"] == ESTERO_CONTEXT["chart_id"]


def test_turn_history_site_ids_recover_context_for_vague_followup(monkeypatch):
    """A vague follow-up should inherit recent wells instead of falling to KB."""
    from api.routes import chat as chat_routes

    monkeypatch.setattr(chat_routes._chart_interpreter, "interpret_with_context", _stub_interpreter)
    history = [
        {
            "role": "assistant",
            "content_preview": "Estero wells show a falling trend.",
            "mode": "site_fallback",
            "site_ids": ESTERO_CONTEXT["site_ids"],
            "wells": [
                {"site_id": "263335081394301", "name": "Lee L-729", "aquifer": "IAS"},
                {"site_id": "263532081592201", "name": "Lee L-581", "aquifer": "Hawthorn"},
            ],
            "cohort_risk_level": "high",
        }
    ]

    resp = client.post(
        "/api/chat",
        json={
            "message": "Why is it declining?",
            "turn_history": history,
            "allow_llm_synthesis": False,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "chart_interpreter"
    assert body["chart_context_used"]["site_ids"] == ESTERO_CONTEXT["site_ids"]


def test_contextual_well_decline_followup_preempts_generic_kb(monkeypatch):
    """The word 'well' should not trigger the basic KB when recent wells exist."""
    from api.routes import chat as chat_routes

    monkeypatch.setattr(chat_routes._chart_interpreter, "interpret_with_context", _stub_interpreter)
    history = [
        {
            "role": "assistant",
            "content_preview": "Here are the wells for the latest chart.",
            "site_ids": ESTERO_CONTEXT["site_ids"][:2],
            "wells": [
                {"site_id": "263335081394301", "name": "Lee L-729"},
                {"site_id": "263532081592201", "name": "Lee L-581"},
            ],
        }
    ]

    resp = client.post(
        "/api/chat",
        json={
            "message": "Which well decline matters most?",
            "turn_history": history,
            "allow_llm_synthesis": False,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "chart_interpreter"
    assert "Well permits required" not in body["response"]


def test_named_site_still_uses_deterministic_fast_path(monkeypatch):
    """Explicit site names should keep deterministic routing precedence."""
    from api.routes import chat as chat_routes

    def _should_not_call(*_args, **_kwargs):
        raise AssertionError("interpreter should not be called for named-site query")

    monkeypatch.setattr(
        chat_routes._chart_interpreter,
        "interpret_with_context",
        _should_not_call,
    )

    resp = client.post(
        "/api/chat",
        json={
            "message": "Why is Lee L-581 changing?",
            "chart_context": ESTERO_CONTEXT,
            "allow_llm_synthesis": False,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["mode"] == "site_fallback"


def test_no_chart_context_keeps_existing_routing():
    """No chart context means the regular deterministic router still owns the query."""
    resp = client.post(
        "/api/chat",
        json={
            "message": "Which Lee County wells are changing fastest?",
            "allow_llm_synthesis": False,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["mode"] == "site_fallback"


def test_no_context_well_definition_still_uses_kb():
    """Without chart or turn context, generic well questions can use the KB."""
    resp = client.post(
        "/api/chat",
        json={
            "message": "What is a well permit?",
            "allow_llm_synthesis": False,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "fallback"
    assert "Well permits required" in body["response"]


def test_chat_benchmark_case_regression_guard():
    """Re-run a real chat-benchmark case to pin its pre-5.4 mode invariant."""
    import json

    cases_path = Path(__file__).resolve().parents[1] / "benchmark" / "chat_eval_cases.json"
    with cases_path.open() as fh:
        cases = json.load(fh)
    case = next(c for c in cases if c["id"] == "L1_estero_trend_01")
    resp = client.post(
        "/api/chat",
        json={"message": case["question"], "allow_llm_synthesis": False},
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "site_fallback"


def test_turn_history_trimmed_before_interpreter(monkeypatch):
    """Only the last four turns should reach the interpreter helper."""
    from api.routes import chat as chat_routes

    captured = {}

    def _capture(question, chart_context, turn_history, **kwargs):
        captured["turn_history"] = turn_history
        return _stub_interpreter(question, chart_context, turn_history, **kwargs)

    monkeypatch.setattr(chat_routes._chart_interpreter, "interpret_with_context", _capture)
    history = [
        {"role": "user", "content_preview": f"turn {idx}", "chart_id": None} for idx in range(6)
    ]

    resp = client.post(
        "/api/chat",
        json={
            "message": "What does this chart mean?",
            "chart_context": ESTERO_CONTEXT,
            "turn_history": history,
            "allow_llm_synthesis": False,
        },
    )

    assert resp.status_code == 200
    assert len(captured["turn_history"]) == 4
    assert captured["turn_history"][0]["content_preview"] == "turn 2"


def test_interpretation_cache_key_includes_chart_context():
    """Same follow-up under different charts should not reuse a stale cache entry."""
    from api.routes import chat as chat_routes

    chat_routes._INTERPRETATION_CACHE.clear()
    context_a = {
        "chart_id": "Estero A",
        "site_ids": ["263335081394301", "263532081592201"],
        "chart_type": "comparison",
    }
    context_b = {
        "chart_id": "Estero B",
        "site_ids": ["262538082045701", "262711081413701"],
        "chart_type": "comparison",
    }

    first = client.post(
        "/api/interpret",
        json={
            "question": "Which one is changing fastest?",
            "use_llm": False,
            "chart_context": context_a,
        },
    )
    second = client.post(
        "/api/interpret",
        json={
            "question": "Which one is changing fastest?",
            "use_llm": False,
            "chart_context": context_b,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_refs = first.json()["interpretation_response"]["data_references"]
    second_refs = second.json()["interpretation_response"]["data_references"]
    assert first_refs[0]["site_id"] != second_refs[0]["site_id"]
    assert first.json()["interpretation_response"]["grounding_status"]["cache_hit"] is False
    assert second.json()["interpretation_response"]["grounding_status"]["cache_hit"] is False
