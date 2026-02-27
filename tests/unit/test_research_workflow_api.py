"""Tests for research workflow API routes."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Add project root to path so ``api`` package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.main import app  # noqa: E402
from api.routes import research_workflow as research_routes  # noqa: E402

client = TestClient(app)


class TestCreatePlanEndpoint:
    """Tests for POST /api/research/plans."""

    def test_create_plan_returns_201(self, monkeypatch):
        def fake_create_experiment_plan(**kwargs):
            return {
                "plan": {
                    "plan_id": "exp_123",
                    "title": kwargs["title"],
                    "status": "planned",
                    "created_at": "2026-02-27T18:00:00+00:00",
                    "updated_at": "2026-02-27T18:00:00+00:00",
                    "datasets": ["USGS"],
                    "metrics": ["f1"],
                    "baselines": ["manual"],
                    "runs": [],
                },
                "path": "outputs/research/experiments/exp_123.json",
            }

        monkeypatch.setattr(research_routes, "create_experiment_plan", fake_create_experiment_plan)

        resp = client.post(
            "/api/research/plans",
            json={
                "title": "Agentic Study",
                "research_question": "Can agents improve reproducibility?",
                "hypothesis": "Structured logging improves outcomes.",
                "methodology": "Compare manual and agentic loops.",
                "datasets": ["USGS"],
                "metrics": ["f1"],
                "baselines": ["manual"],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "ok"
        assert body["plan"]["plan_id"] == "exp_123"
        assert body["summary"]["run_count"] == 0

    def test_create_plan_validation_error_returns_400(self, monkeypatch):
        def fake_create_experiment_plan(**kwargs):
            raise ValueError("title is required.")

        monkeypatch.setattr(research_routes, "create_experiment_plan", fake_create_experiment_plan)

        resp = client.post(
            "/api/research/plans",
            json={
                "title": "Valid title",
                "research_question": "RQ",
                "hypothesis": "H",
                "methodology": "M",
            },
        )
        assert resp.status_code == 400
        assert "title is required" in resp.json()["detail"]


class TestListPlansEndpoint:
    """Tests for GET /api/research/plans."""

    def test_list_plans_with_filters(self, monkeypatch):
        captured = {}

        def fake_list_experiment_plans(status=None, limit=10):
            captured.update({"status": status, "limit": limit})
            return [
                {
                    "plan_id": "exp_1",
                    "title": "Plan 1",
                    "status": "planned",
                    "created_at": "2026-02-27T18:00:00+00:00",
                    "updated_at": "2026-02-27T18:00:00+00:00",
                    "runs": [{"run_id": "run_001"}],
                    "datasets": [],
                    "metrics": [],
                    "baselines": [],
                }
            ]

        monkeypatch.setattr(research_routes, "list_experiment_plans", fake_list_experiment_plans)

        resp = client.get("/api/research/plans", params={"status": "planned", "limit": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["count"] == 1
        assert body["plans"][0]["run_count"] == 1
        assert captured["status"] == "planned"
        assert captured["limit"] == 5

    def test_list_plans_invalid_status_returns_400(self, monkeypatch):
        def fake_list_experiment_plans(status=None, limit=10):
            raise ValueError("Invalid status")

        monkeypatch.setattr(research_routes, "list_experiment_plans", fake_list_experiment_plans)

        resp = client.get("/api/research/plans", params={"status": "bad"})
        assert resp.status_code == 400


class TestGetPlanEndpoint:
    """Tests for GET /api/research/plans/{plan_id}."""

    def test_get_plan_returns_200(self, monkeypatch):
        def fake_get_experiment_plan(plan_id):
            return {
                "plan_id": plan_id,
                "title": "Plan A",
                "status": "in_progress",
                "created_at": "2026-02-27T18:00:00+00:00",
                "updated_at": "2026-02-27T18:05:00+00:00",
                "runs": [{"run_id": "run_001"}],
                "datasets": [],
                "metrics": [],
                "baselines": [],
            }

        monkeypatch.setattr(research_routes, "get_experiment_plan", fake_get_experiment_plan)

        resp = client.get("/api/research/plans/exp_abc")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["plan"]["plan_id"] == "exp_abc"
        assert body["summary"]["run_count"] == 1

    def test_get_plan_not_found_returns_404(self, monkeypatch):
        def fake_get_experiment_plan(plan_id):
            raise FileNotFoundError("Experiment plan not found")

        monkeypatch.setattr(research_routes, "get_experiment_plan", fake_get_experiment_plan)

        resp = client.get("/api/research/plans/missing")
        assert resp.status_code == 404


class TestRunLoggingEndpoint:
    """Tests for POST /api/research/plans/{plan_id}/runs."""

    def test_log_run_returns_201(self, monkeypatch):
        def fake_log_experiment_run_entry(**kwargs):
            return {
                "plan": {
                    "plan_id": kwargs["plan_id"],
                    "status": "in_progress",
                    "runs": [{"run_id": "run_001"}],
                },
                "run": {
                    "run_id": "run_001",
                    "name": kwargs["run_name"],
                    "metrics": kwargs["metrics"],
                },
                "numeric_metrics": {"f1": 0.82},
            }

        monkeypatch.setattr(
            research_routes, "log_experiment_run_entry", fake_log_experiment_run_entry
        )

        resp = client.post(
            "/api/research/plans/exp_abc/runs",
            json={
                "run_name": "baseline",
                "config": {"model": "ridge", "seed": 42},
                "metrics": {"f1": 0.82},
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "ok"
        assert body["plan_id"] == "exp_abc"
        assert body["run"]["run_id"] == "run_001"

    def test_log_run_missing_plan_returns_404(self, monkeypatch):
        def fake_log_experiment_run_entry(**kwargs):
            raise FileNotFoundError("Experiment plan not found")

        monkeypatch.setattr(
            research_routes, "log_experiment_run_entry", fake_log_experiment_run_entry
        )

        resp = client.post(
            "/api/research/plans/exp_missing/runs",
            json={
                "run_name": "baseline",
                "config": {"model": "ridge"},
                "metrics": {"f1": 0.82},
            },
        )
        assert resp.status_code == 404


class TestDraftEndpoint:
    """Tests for POST /api/research/plans/{plan_id}/draft."""

    def test_draft_returns_200(self, monkeypatch):
        def fake_generate_research_paper_draft(**kwargs):
            return {
                "plan": {
                    "plan_id": kwargs["plan_id"],
                    "status": "drafted",
                },
                "path": "outputs/research/manuscripts/exp_abc_20260227_180000.md",
                "draft": "# Draft\n\n## Abstract",
            }

        monkeypatch.setattr(
            research_routes,
            "generate_research_paper_draft",
            fake_generate_research_paper_draft,
        )

        resp = client.post(
            "/api/research/plans/exp_abc/draft",
            json={"target_venue": "NeurIPS", "include_methods_detail": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["plan_id"] == "exp_abc"
        assert body["draft"]["target_venue"] == "NeurIPS"

    def test_draft_missing_plan_returns_404(self, monkeypatch):
        def fake_generate_research_paper_draft(**kwargs):
            raise FileNotFoundError("Experiment plan not found")

        monkeypatch.setattr(
            research_routes,
            "generate_research_paper_draft",
            fake_generate_research_paper_draft,
        )

        resp = client.post(
            "/api/research/plans/exp_missing/draft",
            json={"target_venue": "arXiv"},
        )
        assert resp.status_code == 404
