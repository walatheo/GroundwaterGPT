"""Knowledge routes — KB stats and document ingestion controls."""

from typing import Optional

from fastapi import APIRouter, HTTPException

from src.agent.knowledge import get_knowledge_stats, ingest_pdfs
from src.agent.source_verification import TrustLevel

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _parse_trust_level(raw: str) -> TrustLevel:
    mapping = {
        "verified": TrustLevel.VERIFIED,
        "trusted": TrustLevel.TRUSTED,
        "moderate": TrustLevel.MODERATE,
        "unknown": TrustLevel.UNKNOWN,
        "untrusted": TrustLevel.UNTRUSTED,
    }
    key = raw.strip().lower()
    if key not in mapping:
        raise HTTPException(
            status_code=400,
            detail="Invalid min_trust. Use: verified, trusted, moderate, unknown, untrusted",
        )
    return mapping[key]


@router.get("/stats")
def knowledge_stats():
    """Return current knowledge-base statistics."""
    return {
        "status": "ok",
        "knowledge_base": get_knowledge_stats(),
    }


@router.post("/ingest")
def ingest_documents(payload: Optional[dict] = None):
    """Ingest PDFs into the knowledge base.

    Request body (all fields optional):
        {
            "path": "resources/pdfs/references",
            "recursive": true,
            "min_trust": "moderate",
            "force": false
        }
    """
    data = payload or {}

    path = data.get("path")
    recursive = bool(data.get("recursive", True))
    force = bool(data.get("force", False))
    min_trust_raw = str(data.get("min_trust", TrustLevel.MODERATE.value))
    min_trust = _parse_trust_level(min_trust_raw)

    result = ingest_pdfs(
        path=path,
        recursive=recursive,
        min_trust=min_trust,
        force=force,
    )

    return {
        "status": "ok",
        "ingestion": result,
        "knowledge_base": get_knowledge_stats(),
    }
