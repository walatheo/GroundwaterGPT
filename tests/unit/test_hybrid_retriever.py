"""Unit tests for the hybrid BM25 + vector retriever."""

from unittest.mock import patch

from src.agent import hybrid_retriever
from src.agent.hybrid_retriever import (
    FusedDoc,
    _rrf_fuse,
    hybrid_retriever_enabled,
    hybrid_search,
    reranker_enabled,
)


class _StubDoc:
    def __init__(self, content, meta=None):
        self.page_content = content
        self.metadata = meta or {}


def test_flag_defaults_on(monkeypatch):
    monkeypatch.delenv("GROUNDWATERGPT_ENABLE_HYBRID_RETRIEVER", raising=False)
    assert hybrid_retriever_enabled() is True


def test_flag_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("GROUNDWATERGPT_ENABLE_HYBRID_RETRIEVER", "false")
    assert hybrid_retriever_enabled() is False


def test_flag_on_when_set(monkeypatch):
    monkeypatch.setenv("GROUNDWATERGPT_ENABLE_HYBRID_RETRIEVER", "1")
    assert hybrid_retriever_enabled() is True


def test_reranker_flag_respected(monkeypatch):
    monkeypatch.delenv("GROUNDWATERGPT_ENABLE_RERANKER", raising=False)
    assert reranker_enabled() is False
    monkeypatch.setenv("GROUNDWATERGPT_ENABLE_RERANKER", "yes")
    assert reranker_enabled() is True


def test_rrf_fuses_and_boosts_shared_hits():
    shared = _StubDoc("Biscayne aquifer confining layer", {"doc_id": "A"})
    only_bm = _StubDoc("Specific rare keyword", {"doc_id": "B"})
    only_vec = _StubDoc("Semantic match without keyword", {"doc_id": "C"})

    bm25_hits = [(shared, 2.3), (only_bm, 1.1)]
    vector_hits = [(shared, 0.1), (only_vec, 0.2)]

    fused = _rrf_fuse(bm25_hits, vector_hits, k=3)
    assert fused[0].metadata["doc_id"] == "A", "shared hit should win"
    assert fused[0].bm25_rank == 1
    assert fused[0].vector_rank == 1
    keys = {d.metadata["doc_id"] for d in fused}
    assert keys == {"A", "B", "C"}


def test_hybrid_search_returns_bm25_only_when_vector_fails():
    corpus = [
        _StubDoc("Biscayne aquifer recharge through limestone", {"doc_id": "B1"}),
        _StubDoc("Floridan aquifer saline wedge", {"doc_id": "F1"}),
    ]

    with patch.object(hybrid_retriever, "_vector_search", return_value=[]):
        results = hybrid_search("biscayne recharge", k=2, corpus=corpus)

    assert results, "BM25 alone should still return hits"
    assert results[0].metadata["doc_id"] == "B1"
    assert results[0].bm25_rank == 1
    assert results[0].vector_rank is None


def test_hybrid_search_empty_query_returns_empty():
    assert hybrid_search("", k=3, corpus=[]) == []


def test_fused_doc_exposes_page_content():
    fd = FusedDoc(content="abc", metadata={}, score=1.0)
    assert fd.page_content == "abc"
