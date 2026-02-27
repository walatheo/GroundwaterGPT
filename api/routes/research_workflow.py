"""Research workflow routes for experiment planning, run logging, and paper drafts."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agent.tools import (
    create_experiment_plan,
    generate_research_paper_draft,
    get_experiment_plan,
    list_experiment_plans,
    log_experiment_run_entry,
)

router = APIRouter(prefix="/api/research", tags=["research-workflow"])


class CreatePlanRequest(BaseModel):
    """Request payload for creating an experiment plan."""

    title: str = Field(min_length=1)
    research_question: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    methodology: str = Field(min_length=1)
    datasets: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    baselines: List[str] = Field(default_factory=list)
    notes: str = ""


class LogRunRequest(BaseModel):
    """Request payload for logging one experiment run."""

    run_name: str = Field(min_length=1)
    config: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    findings: str = ""
    artifacts: List[str] = Field(default_factory=list)


class DraftRequest(BaseModel):
    """Request payload for generating a manuscript draft."""

    target_venue: str = "arXiv"
    include_methods_detail: bool = True


def _plan_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Return the compact plan summary used in list/detail payloads."""
    return {
        "plan_id": plan.get("plan_id"),
        "title": plan.get("title"),
        "status": plan.get("status"),
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
        "run_count": len(plan.get("runs", [])),
        "datasets": plan.get("datasets", []),
        "metrics": plan.get("metrics", []),
        "baselines": plan.get("baselines", []),
    }


@router.post("/plans", status_code=201)
def create_plan(payload: CreatePlanRequest):
    """Create and persist a new research experiment plan."""
    try:
        result = create_experiment_plan(
            title=payload.title,
            research_question=payload.research_question,
            hypothesis=payload.hypothesis,
            methodology=payload.methodology,
            datasets=payload.datasets,
            metrics=payload.metrics,
            baselines=payload.baselines,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    plan = result["plan"]
    return {
        "status": "ok",
        "plan": plan,
        "summary": _plan_summary(plan),
        "storage": {"path": result["path"]},
    }


@router.get("/plans")
def list_plans(status: Optional[str] = None, limit: int = 10):
    """List persisted experiment plans with optional status filter."""
    try:
        plans = list_experiment_plans(status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "ok",
        "count": len(plans),
        "plans": [_plan_summary(plan) for plan in plans],
    }


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str):
    """Return a full experiment plan by ID."""
    try:
        plan = get_experiment_plan(plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "status": "ok",
        "plan": plan,
        "summary": _plan_summary(plan),
    }


@router.post("/plans/{plan_id}/runs", status_code=201)
def log_run(plan_id: str, payload: LogRunRequest):
    """Log an experiment run for an existing plan."""
    try:
        result = log_experiment_run_entry(
            plan_id=plan_id,
            run_name=payload.run_name,
            config=payload.config,
            metrics=payload.metrics,
            findings=payload.findings,
            artifacts=payload.artifacts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    plan = result["plan"]
    run = result["run"]
    return {
        "status": "ok",
        "plan_id": plan.get("plan_id"),
        "plan_status": plan.get("status"),
        "run_count": len(plan.get("runs", [])),
        "run": run,
        "numeric_metrics": result.get("numeric_metrics", {}),
    }


@router.post("/plans/{plan_id}/draft")
def draft_plan_paper(plan_id: str, payload: DraftRequest):
    """Generate and save a manuscript draft for the plan."""
    try:
        result = generate_research_paper_draft(
            plan_id=plan_id,
            target_venue=payload.target_venue,
            include_methods_detail=payload.include_methods_detail,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    plan = result["plan"]
    return {
        "status": "ok",
        "plan_id": plan.get("plan_id"),
        "plan_status": plan.get("status"),
        "draft": {
            "path": result["path"],
            "markdown": result["draft"],
            "target_venue": payload.target_venue,
        },
    }
