"""Multi-well comparison route — side-by-side data viewer.

Despite its prior name, this endpoint does not perform research synthesis.
It loads the requested wells, aggregates them on a shared cadence, and
returns aligned series, derived metrics, and export-ready bundles for the
frontend's Research Workbench view.

The canonical path is ``POST /api/multi-well``. The legacy alias
``POST /api/research/workbench`` is preserved for one release for any
out-of-tree clients (e.g. the prebuilt frontend bundle).
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.routes._multi_well import build_multi_well_payload

router = APIRouter(tags=["multi-well"])


class MultiWellFilters(BaseModel):
    """Optional site-picker filters echoed back in the response."""

    county: List[str] = Field(default_factory=list)
    aquifer: List[str] = Field(default_factory=list)
    confined: Optional[bool] = None


class MultiWellDateWindow(BaseModel):
    """Date window selection for multi-well comparisons."""

    preset: str = "last_10y"
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class MultiWellRequest(BaseModel):
    """Request payload for comparative multi-well analysis."""

    site_ids: List[str] = Field(default_factory=list)
    filters: MultiWellFilters = Field(default_factory=MultiWellFilters)
    date_window: MultiWellDateWindow = Field(default_factory=MultiWellDateWindow)
    aggregation: str = "monthly"
    normalization: str = "raw"


def _model_to_dict(model: Any) -> Dict[str, Any]:
    """Compat helper for Pydantic v1/v2 model export."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _run(payload: MultiWellRequest) -> Dict[str, Any]:
    try:
        return build_multi_well_payload(
            site_ids=payload.site_ids,
            filters=_model_to_dict(payload.filters),
            date_window=_model_to_dict(payload.date_window),
            aggregation=payload.aggregation,
            normalization=payload.normalization,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/multi-well")
def multi_well(payload: MultiWellRequest):
    """Build a comparative groundwater payload for multiple wells."""
    return _run(payload)


@router.post("/api/research/workbench", include_in_schema=False)
def multi_well_legacy_alias(payload: MultiWellRequest):
    """Deprecated alias for ``/api/multi-well``; preserved for one release."""
    return _run(payload)
