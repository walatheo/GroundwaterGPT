"""Research workbench route — side-by-side well comparison for researchers.

This module exposes only the ``POST /api/research/workbench`` endpoint.
The experiment-plan and paper-drafter endpoints were intentionally removed
from the demo surface; only the workbench (well-comparison) payload remains.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.routes._research_workbench import build_research_workbench_payload

router = APIRouter(prefix="/api/research", tags=["research-workflow"])


class WorkbenchFilters(BaseModel):
    """Optional site-picker filters echoed back by the workbench."""

    county: List[str] = Field(default_factory=list)
    aquifer: List[str] = Field(default_factory=list)
    confined: Optional[bool] = None


class WorkbenchDateWindow(BaseModel):
    """Date window selection for research workbench comparisons."""

    preset: str = "last_10y"
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ResearchWorkbenchRequest(BaseModel):
    """Request payload for comparative research workbench analysis."""

    site_ids: List[str] = Field(default_factory=list)
    filters: WorkbenchFilters = Field(default_factory=WorkbenchFilters)
    date_window: WorkbenchDateWindow = Field(default_factory=WorkbenchDateWindow)
    aggregation: str = "monthly"
    normalization: str = "raw"


def _model_to_dict(model: Any) -> Dict[str, Any]:
    """Compat helper for Pydantic v1/v2 model export."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


@router.post("/workbench")
def research_workbench(payload: ResearchWorkbenchRequest):
    """Build a comparative groundwater workbench payload for researchers."""
    try:
        return build_research_workbench_payload(
            site_ids=payload.site_ids,
            filters=_model_to_dict(payload.filters),
            date_window=_model_to_dict(payload.date_window),
            aggregation=payload.aggregation,
            normalization=payload.normalization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
