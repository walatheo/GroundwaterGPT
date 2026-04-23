"""Hybrid BM25 + vector retriever using reciprocal rank fusion.

The project already ships a ChromaDB vector store (``src.agent.knowledge``).
For publication-grade retrieval we want a cheap lexical companion so rare
hydrogeology terms (e.g. specific well codes, statute numbers, rock unit
names) aren't dropped by dense-only similarity. BM25 over the same document
corpus fills that gap.

Both retrievers return ranked lists; we fuse them with **reciprocal rank
fusion** (Cormack et al. 2009)::

    RRF(d) = sum_i( 1 / (k + rank_i(d)) )

which is the scoring function LangChain's ``EnsembleRetriever`` uses under
the hood. We re-implement it locally so we can mix in our own scoring
metadata and avoid an extra abstraction layer for the eval harness.

Enable with ``GROUNDWATERGPT_ENABLE_HYBRID_RETRIEVER=1``.  Callers should
gracefully fall back to vector-only when the flag is off or BM25 cannot be
constructed (empty KB, missing ``rank_bm25`` wheel).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

_RRF_K = 60
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def hybrid_retriever_enabled() -> bool:
    """Return True when the hybrid retriever should replace vector-only.

    Defaults ON so chat + chart-interpreter both cite the corpus.
    Set GROUNDWATERGPT_ENABLE_HYBRID_RETRIEVER=false to disable.
    """
    raw = os.getenv("GROUNDWATERGPT_ENABLE_HYBRID_RETRIEVER", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def reranker_enabled() -> bool:
    """Return True when the optional cross-encoder reranker should run."""
    return os.getenv("GROUNDWATERGPT_ENABLE_RERANKER", "").lower() in {
        "1",
        "true",
        "yes",
    }


@dataclass
class FusedDoc:
    """A fused search hit with its BM25 and vector ranks."""

    content: str
    metadata: dict
    score: float
    bm25_rank: Optional[int] = None
    vector_rank: Optional[int] = None

    @property
    def page_content(self) -> str:
        """LangChain-style accessor so this doc is drop-in compatible with Document."""
        return self.content


def _tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN_RE.findall(text or "")]


def _doc_key(doc: Any) -> str:
    """Stable key so the same chunk from both retrievers collapses into one hit."""
    meta = dict(getattr(doc, "metadata", {}) or {})
    for field in ("doc_id", "chunk_id", "id", "source"):
        if meta.get(field):
            return f"{field}:{meta[field]}"
    content = str(getattr(doc, "page_content", ""))
    return f"hash:{hash(content[:400])}"


def _load_corpus() -> list[Any]:
    """Pull every chunk out of the Chroma vectorstore.

    We need the full corpus to build BM25. ChromaDB exposes ``_collection.get``
    which returns documents + metadatas in a single round-trip.
    """
    from src.agent.knowledge import get_vectorstore

    store = get_vectorstore()
    try:
        raw = store._collection.get(include=["documents", "metadatas"])  # noqa: SLF001
    except Exception as exc:
        logger.debug("hybrid retriever could not load corpus: %s", exc)
        return []

    docs: list[Any] = []
    for content, metadata in zip(raw.get("documents", []), raw.get("metadatas", [])):
        if not content:
            continue
        docs.append(_StaticDoc(content=str(content), metadata=dict(metadata or {})))
    return docs


@dataclass
class _StaticDoc:
    content: str
    metadata: dict

    @property
    def page_content(self) -> str:
        """LangChain-style accessor so this doc is drop-in compatible with Document."""
        return self.content


def _bm25_search(corpus: list[Any], query: str, k: int) -> list[tuple[Any, float]]:
    try:
        from rank_bm25 import BM25Okapi
    except Exception as exc:  # pragma: no cover - surfaced at install time
        logger.debug("rank_bm25 unavailable: %s", exc)
        return []

    if not corpus:
        return []
    tokenized = [_tokenize(doc.page_content) for doc in corpus]
    bm25 = BM25Okapi(tokenized)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(
        zip(corpus, scores),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return ranked[:k]


def _vector_search(query: str, k: int) -> list[tuple[Any, float]]:
    try:
        from src.agent.knowledge import get_vectorstore

        store = get_vectorstore()
        return store.similarity_search_with_score(query, k=k)
    except Exception as exc:
        logger.debug("vector search unavailable: %s", exc)
        return []


def _rrf_fuse(
    bm25_hits: list[tuple[Any, float]],
    vector_hits: list[tuple[Any, float]],
    k: int,
) -> list[FusedDoc]:
    merged: dict[str, FusedDoc] = {}

    for rank, (doc, _score) in enumerate(bm25_hits, start=1):
        key = _doc_key(doc)
        contribution = 1.0 / (_RRF_K + rank)
        if key in merged:
            merged[key].score += contribution
            merged[key].bm25_rank = rank
        else:
            merged[key] = FusedDoc(
                content=str(doc.page_content),
                metadata=dict(getattr(doc, "metadata", {}) or {}),
                score=contribution,
                bm25_rank=rank,
            )

    for rank, (doc, _score) in enumerate(vector_hits, start=1):
        key = _doc_key(doc)
        contribution = 1.0 / (_RRF_K + rank)
        if key in merged:
            merged[key].score += contribution
            merged[key].vector_rank = rank
        else:
            merged[key] = FusedDoc(
                content=str(doc.page_content),
                metadata=dict(getattr(doc, "metadata", {}) or {}),
                score=contribution,
                vector_rank=rank,
            )

    ordered = sorted(merged.values(), key=lambda d: d.score, reverse=True)
    return ordered[:k]


def _maybe_rerank(query: str, hits: list[FusedDoc]) -> list[FusedDoc]:
    if not reranker_enabled() or not hits:
        return hits
    try:
        from sentence_transformers import CrossEncoder

        model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        pairs = [(query, hit.content) for hit in hits]
        scores = model.predict(pairs)
        reordered = [hit for _, hit in sorted(zip(scores, hits), key=lambda p: p[0], reverse=True)]
        return reordered
    except Exception as exc:
        logger.debug("reranker unavailable, returning RRF order: %s", exc)
        return hits


def hybrid_search(
    query: str,
    *,
    k: int = 5,
    corpus: Optional[Iterable[Any]] = None,
) -> list[FusedDoc]:
    """Run BM25 + vector retrieval and fuse via reciprocal rank fusion.

    ``corpus`` is exposed for tests so BM25 can run without touching Chroma.
    """
    if not query:
        return []

    materialized = list(corpus) if corpus is not None else _load_corpus()
    bm25 = _bm25_search(materialized, query, k=max(k * 2, 10))
    vector = _vector_search(query, k=max(k * 2, 10))
    fused = _rrf_fuse(bm25, vector, k=k)
    return _maybe_rerank(query, fused)


def hybrid_snippets(query: str, *, k: int = 3) -> list[dict]:
    """Public helper returning the same shape as ``_rag_snippets``."""
    hits = hybrid_search(query, k=k)
    out: list[dict] = []
    for idx, hit in enumerate(hits):
        meta = hit.metadata or {}
        out.append(
            {
                "doc_id": meta.get("doc_id") or f"rag_{idx + 1}",
                "content": hit.content[:700],
                "url": meta.get("source_url") or meta.get("url") or meta.get("source") or "",
                "trust_level": meta.get("trust_level", "unknown"),
                "bm25_rank": hit.bm25_rank,
                "vector_rank": hit.vector_rank,
                "rrf_score": round(hit.score, 6),
            }
        )
    return out
