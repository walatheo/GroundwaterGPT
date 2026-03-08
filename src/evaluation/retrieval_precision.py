"""Retrieval precision benchmark utilities for RAG quality tracking."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Callable

from langchain_core.documents import Document

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RETRIEVAL_CASES_PATH = PROJECT_ROOT / "tests" / "benchmark" / "retrieval_eval_cases.json"


def load_retrieval_cases(path: Path = DEFAULT_RETRIEVAL_CASES_PATH) -> list[dict[str, Any]]:
    """Load retrieval evaluation cases from disk."""
    with open(path) as fh:
        payload = json.load(fh)
    if not isinstance(payload, list):
        raise ValueError("Retrieval eval cases file must contain a JSON array.")
    return payload


def _doc_text(doc: Document) -> str:
    """Flatten a document's content + metadata to searchable text."""
    metadata_text = " ".join(f"{k}:{v}" for k, v in (doc.metadata or {}).items())
    return f"{doc.page_content} {metadata_text}".lower()


def _is_relevant(doc: Document, expected_terms: list[str]) -> bool:
    """Return True when all expected terms for a case are present in a document."""
    text = _doc_text(doc)
    lowered_terms = [str(term).strip().lower() for term in expected_terms if str(term).strip()]
    if not lowered_terms:
        return False
    return all(term in text for term in lowered_terms)


def evaluate_retrieval_case(
    case: dict[str, Any],
    docs: list[Document],
    k: int,
) -> dict[str, Any]:
    """Evaluate precision@k for one retrieval case."""
    query = str(case.get("query", "")).strip()
    expected_terms = case.get("expected_terms", [])
    expected = expected_terms if isinstance(expected_terms, list) else []

    top_docs = docs[:k]
    relevant = sum(1 for doc in top_docs if _is_relevant(doc, expected))
    precision_at_k = float(relevant / k) if k else 0.0
    return {
        "case_id": str(case.get("id", query or "unknown_case")),
        "query": query,
        "k": k,
        "relevant_docs": relevant,
        "retrieved_docs": len(top_docs),
        "precision_at_k": round(precision_at_k, 3),
    }


def run_retrieval_precision_eval(
    cases_path: Path = DEFAULT_RETRIEVAL_CASES_PATH,
    k_values: tuple[int, ...] = (3, 5, 8),
    score_threshold_values: tuple[float, ...] = (0.30, 0.40, 0.50),
    target_precision: float = 0.90,
    search_fn: Callable[..., list[Document]] | None = None,
) -> dict[str, Any]:
    """Run retrieval precision evaluation across parameter combinations.

    Args:
        cases_path: Path to retrieval benchmark case definitions.
        k_values: Candidate k values for retrieval.
        score_threshold_values: Candidate similarity thresholds.
        target_precision: Minimum average precision@k target.
        search_fn: Optional search function override for testing.
    """
    cases = load_retrieval_cases(cases_path)
    if search_fn is None:
        from src.agent.knowledge import search_knowledge as search_fn  # pragma: no cover

    combo_results: list[dict[str, Any]] = []
    errors: list[str] = []

    for k in k_values:
        for score_threshold in score_threshold_values:
            case_results: list[dict[str, Any]] = []
            for case in cases:
                query = str(case.get("query", "")).strip()
                if not query:
                    continue
                try:
                    docs = search_fn(query, k=k, score_threshold=score_threshold)
                except Exception as exc:
                    errors.append(f"{query}: {exc}")
                    docs = []
                case_results.append(evaluate_retrieval_case(case, docs, k))

            avg_precision = (
                statistics.mean(item["precision_at_k"] for item in case_results)
                if case_results
                else 0.0
            )
            combo_results.append(
                {
                    "k": k,
                    "score_threshold": score_threshold,
                    "average_precision_at_k": round(avg_precision, 3),
                    "case_results": case_results,
                }
            )

    if combo_results:
        best = max(
            combo_results,
            key=lambda item: (item["average_precision_at_k"], -item["k"], item["score_threshold"]),
        )
    else:
        best = {
            "k": 0,
            "score_threshold": 0.0,
            "average_precision_at_k": 0.0,
            "case_results": [],
        }

    passed = float(best.get("average_precision_at_k", 0.0)) >= target_precision
    return {
        "metadata": {
            "cases_path": str(cases_path),
            "case_count": len(cases),
            "k_values": list(k_values),
            "score_threshold_values": list(score_threshold_values),
        },
        "target_precision": target_precision,
        "recommended": {
            "k": int(best.get("k", 0)),
            "score_threshold": float(best.get("score_threshold", 0.0)),
            "average_precision_at_k": float(best.get("average_precision_at_k", 0.0)),
            "passed": passed,
        },
        "runs": combo_results,
        "errors": errors,
        "status": "ok" if not errors else "degraded",
    }
