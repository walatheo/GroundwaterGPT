"""Tests for retrieval precision benchmark utilities."""

from __future__ import annotations

import json

from langchain_core.documents import Document

from src.evaluation.retrieval_precision import evaluate_retrieval_case, run_retrieval_precision_eval


def test_evaluate_retrieval_case_precision():
    """Precision@k should reflect relevant-doc ratio."""
    case = {
        "id": "demo",
        "query": "Biscayne saltwater",
        "expected_terms": ["biscayne", "saltwater"],
    }
    docs = [
        Document(page_content="Biscayne aquifer saltwater intrusion discussed."),
        Document(page_content="General hydrology overview."),
    ]
    result = evaluate_retrieval_case(case, docs, k=2)
    assert result["case_id"] == "demo"
    assert result["precision_at_k"] == 0.5


def test_run_retrieval_precision_eval_selects_best_combo(tmp_path):
    """Best parameter combo should be selected by average precision."""
    cases_path = tmp_path / "retrieval_cases.json"
    cases_path.write_text(
        json.dumps(
            [
                {"id": "c1", "query": "q1", "expected_terms": ["alpha"]},
                {"id": "c2", "query": "q2", "expected_terms": ["beta"]},
            ]
        )
    )

    def fake_search(query: str, k: int, score_threshold: float):
        if score_threshold >= 0.5:
            if query == "q1":
                return [Document(page_content="alpha relevant doc")] * k
            return [Document(page_content="beta relevant doc")] * k
        return [Document(page_content="noise")] * k

    report = run_retrieval_precision_eval(
        cases_path=cases_path,
        k_values=(2, 4),
        score_threshold_values=(0.3, 0.5),
        target_precision=0.9,
        search_fn=fake_search,
    )
    assert report["recommended"]["score_threshold"] == 0.5
    assert report["recommended"]["passed"] is True
    assert report["status"] == "ok"
