"""Tests for knowledge-base API routes."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Add project root to path so ``api`` package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.main import app  # noqa: E402
from api.routes import knowledge as knowledge_routes  # noqa: E402
from src.agent.source_verification import TrustLevel  # noqa: E402

client = TestClient(app)


class TestKnowledgeStatsEndpoint:
    """Tests for GET /api/knowledge/stats."""

    def test_stats_returns_200_and_payload(self, monkeypatch):
        monkeypatch.setattr(
            knowledge_routes,
            "get_knowledge_runtime_status",
            lambda: {
                "status": "ok",
                "search_ready": True,
                "ingestion_ready": True,
            },
        )
        monkeypatch.setattr(
            knowledge_routes,
            "get_knowledge_stats",
            lambda: {"total_chunks": 42, "pdf_files": 3, "status": "loaded"},
        )

        resp = client.get("/api/knowledge/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["knowledge_base"]["total_chunks"] == 42
        assert body["knowledge_base"]["pdf_files"] == 3
        assert body["runtime"]["search_ready"] is True


class TestKnowledgeStatusEndpoint:
    """Tests for GET /api/knowledge/status."""

    def test_status_returns_runtime(self, monkeypatch):
        monkeypatch.setattr(
            knowledge_routes,
            "get_knowledge_runtime_status",
            lambda: {
                "status": "degraded",
                "search_ready": False,
                "ingestion_ready": True,
            },
        )
        resp = client.get("/api/knowledge/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["runtime"]["search_ready"] is False


class TestKnowledgeIngestEndpoint:
    """Tests for POST /api/knowledge/ingest."""

    def test_ingest_uses_defaults(self, monkeypatch):
        captured = {}

        def fake_ingest(path=None, recursive=True, min_trust=None, force=False):
            captured.update(
                {
                    "path": path,
                    "recursive": recursive,
                    "min_trust": min_trust,
                    "force": force,
                }
            )
            return {"status": "ok", "scanned_files": 1, "ingested_files": 1}

        monkeypatch.setattr(knowledge_routes, "ingest_pdfs", fake_ingest)
        monkeypatch.setattr(
            knowledge_routes,
            "get_knowledge_runtime_status",
            lambda: {"status": "ok", "search_ready": True, "ingestion_ready": True},
        )
        monkeypatch.setattr(
            knowledge_routes,
            "get_knowledge_stats",
            lambda: {"total_chunks": 100, "pdf_files": 10, "status": "loaded"},
        )

        resp = client.post("/api/knowledge/ingest", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["ingestion"]["ingested_files"] == 1
        assert captured["path"] is None
        assert captured["recursive"] is True
        assert captured["force"] is False
        assert captured["min_trust"] == TrustLevel.MODERATE
        assert body["runtime"]["status"] == "ok"

    def test_ingest_accepts_custom_options(self, monkeypatch):
        captured = {}

        def fake_ingest(path=None, recursive=True, min_trust=None, force=False):
            captured.update(
                {
                    "path": path,
                    "recursive": recursive,
                    "min_trust": min_trust,
                    "force": force,
                }
            )
            return {"status": "ok", "scanned_files": 2, "ingested_files": 2}

        monkeypatch.setattr(knowledge_routes, "ingest_pdfs", fake_ingest)
        monkeypatch.setattr(
            knowledge_routes,
            "get_knowledge_runtime_status",
            lambda: {"status": "ok", "search_ready": True, "ingestion_ready": True},
        )
        monkeypatch.setattr(
            knowledge_routes,
            "get_knowledge_stats",
            lambda: {"total_chunks": 12, "pdf_files": 2, "status": "loaded"},
        )

        resp = client.post(
            "/api/knowledge/ingest",
            json={
                "path": "resources/pdfs/references",
                "recursive": False,
                "force": True,
                "min_trust": "trusted",
            },
        )
        assert resp.status_code == 200
        assert captured["path"] == "resources/pdfs/references"
        assert captured["recursive"] is False
        assert captured["force"] is True
        assert captured["min_trust"] == TrustLevel.TRUSTED

    def test_ingest_rejects_invalid_min_trust(self):
        resp = client.post("/api/knowledge/ingest", json={"min_trust": "very_trusted"})
        assert resp.status_code == 400

    def test_ingest_runtime_failure_returns_503(self, monkeypatch):
        def fake_ingest(**kwargs):
            raise RuntimeError("sentence-transformers is not installed")

        monkeypatch.setattr(knowledge_routes, "ingest_pdfs", fake_ingest)
        resp = client.post("/api/knowledge/ingest", json={})
        assert resp.status_code == 503
