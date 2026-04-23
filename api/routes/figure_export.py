"""Server-side figure export for publication-ready SVG/PNG.

Reconstructs the chart payload (same JSON the frontend renders) with
matplotlib so the output is reproducible from pure JSON — callers can cite
the endpoint in a paper's methods section as "Figures rendered from the
deterministic chart payload via ``/api/figures/export``".

POST body::

    {
        "chart_payload": { ... same shape as /api/chat chart field ... },
        "format": "svg" | "png",
        "dpi": 160
    }

Returns the rendered image as a streamed response with the appropriate
content-type. matplotlib is imported lazily so normal chat requests don't
pay the cost.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/figures", tags=["figures"])


class FigureExportRequest(BaseModel):
    """Request payload for ``POST /api/figures/export``."""

    chart_payload: dict[str, Any]
    format: Literal["svg", "png"] = "svg"
    dpi: int = Field(default=160, ge=72, le=600)


@router.post("/export")
def export_figure(req: FigureExportRequest) -> Response:
    """Render ``chart_payload`` to SVG or PNG via matplotlib."""
    try:
        payload = req.chart_payload
        buf = _render(payload, fmt=req.format, dpi=req.dpi)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("figure export failed: %s", exc)
        raise HTTPException(status_code=500, detail="figure render error") from exc

    media = "image/svg+xml" if req.format == "svg" else "image/png"
    return Response(content=buf.getvalue(), media_type=media)


def _render(payload: dict[str, Any], *, fmt: str, dpi: int) -> io.BytesIO:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = payload.get("data") or []
    series = payload.get("series") or []
    if not data or not series:
        raise ValueError("chart_payload must include non-empty 'data' and 'series'")

    dates = [row.get("date") for row in data]
    has_precip = any(row.get("precip_mm") is not None for row in data)

    fig, ax_level = plt.subplots(figsize=(9.0, 4.5), dpi=dpi)
    ax_level.invert_yaxis()

    for s in series:
        key = s.get("key")
        if not key:
            continue
        xs = []
        ys = []
        for row in data:
            value = row.get(key)
            if value is None:
                continue
            xs.append(row["date"])
            ys.append(value)
        if not xs:
            continue
        ax_level.plot(
            xs,
            ys,
            label=s.get("name", key),
            color=s.get("color", "#3b82f6"),
            linewidth=s.get("strokeWidth", 1.5),
            linestyle=_matplotlib_dash(s.get("strokeDasharray")),
            alpha=s.get("opacity", 1.0),
        )

    ax_level.set_xlabel(payload.get("x_label") or "Month")
    ax_level.set_ylabel(payload.get("y_label") or "Water level (ft)")
    if payload.get("title"):
        ax_level.set_title(str(payload["title"]), fontsize=11)

    if has_precip:
        ax_precip = ax_level.twinx()
        precip_xs = [row["date"] for row in data if row.get("precip_mm") is not None]
        precip_ys = [row["precip_mm"] for row in data if row.get("precip_mm") is not None]
        ax_precip.bar(precip_xs, precip_ys, alpha=0.25, color="#60a5fa", label="Precip (mm/mo)")
        ax_precip.set_ylabel("Precip (mm/mo)")

    annotations = payload.get("annotations") or []
    for ann in annotations:
        if ann.get("type") != "changepoint":
            continue
        sid = ann.get("site_id")
        date = ann.get("date")
        row = next((r for r in data if r.get("date") == date), None)
        if not row or sid not in row:
            continue
        ax_level.plot(
            date,
            row[sid],
            marker="o",
            markersize=7 if ann.get("highlight") else 4,
            markerfacecolor="#dc2626" if ann.get("highlight") else "#f97316",
            markeredgecolor="#ffffff",
            markeredgewidth=1.0,
        )

    if len(dates) > 24:
        step = max(1, len(dates) // 12)
        ax_level.set_xticks(dates[::step])
    ax_level.tick_params(axis="x", rotation=45, labelsize=8)

    ax_level.legend(loc="best", fontsize=8)
    ax_level.grid(True, linestyle="--", alpha=0.35)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _matplotlib_dash(pattern: str | None) -> str:
    if not pattern:
        return "-"
    if pattern.strip() in {"2 4", "4 4"}:
        return ":"
    if pattern.strip() in {"5 5", "6 4"}:
        return "--"
    return "-"
