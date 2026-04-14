"""Research response provenance helpers."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SITE_ID_RE = re.compile(r"\b\d{15}\b")


def _sha256_bytes(data: bytes) -> str:
    """Return a SHA-256 hex digest for bytes."""
    return hashlib.sha256(data).hexdigest()


def _stable_json_hash(value: Any) -> str:
    """Hash a JSON-serializable object with deterministic key ordering."""
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return _sha256_bytes(encoded)


def _file_hash(path: Path) -> str | None:
    """Hash a file when it exists, otherwise return None."""
    if not path.exists() or not path.is_file():
        return None
    return _sha256_bytes(path.read_bytes())


def _git_commit() -> str | None:
    """Return the current git commit if available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    commit = result.stdout.strip()
    return commit or None


def _collect_site_ids(value: Any, site_ids: set[str]) -> None:
    """Recursively collect 15-digit USGS site IDs from response payloads."""
    if value is None:
        return
    if isinstance(value, dict):
        for nested in value.values():
            _collect_site_ids(nested, site_ids)
        return
    if isinstance(value, list):
        for item in value:
            _collect_site_ids(item, site_ids)
        return
    if isinstance(value, str):
        site_ids.update(SITE_ID_RE.findall(value))


def _data_snapshot(site_ids: list[str]) -> dict[str, Any]:
    """Build per-site file hashes and an aggregate data snapshot hash."""
    files = []
    for site_id in site_ids:
        rel_path = Path("data") / f"usgs_{site_id}.csv"
        digest = _file_hash(PROJECT_ROOT / rel_path)
        files.append(
            {
                "site_id": site_id,
                "path": str(rel_path),
                "sha256": digest,
                "available": digest is not None,
            }
        )
    return {
        "site_ids": site_ids,
        "files": files,
        "sha256": _stable_json_hash(files),
    }


def build_research_provenance(
    payload: dict[str, Any],
    *,
    question: str,
    route_mode: str,
) -> dict[str, Any]:
    """Build reproducibility metadata for a research response."""
    site_ids: set[str] = set()
    _collect_site_ids(payload, site_ids)
    ordered_site_ids = sorted(site_ids)

    config_files = [
        Path("config") / "usgs_sites.json",
        Path("config") / "water_supply_sources.json",
    ]
    config_hashes = [
        {
            "path": str(path),
            "sha256": _file_hash(PROJECT_ROOT / path),
        }
        for path in config_files
    ]

    response_material = {
        "question": question,
        "mode": payload.get("mode", route_mode),
        "report": payload.get("report") or payload.get("response"),
        "chart": payload.get("chart"),
        "claim_citations": payload.get("claim_citations", []),
        "structured_response": payload.get("structured_response"),
        "changepoints": payload.get("changepoints", []),
        "cross_well_clusters": payload.get("cross_well_clusters", []),
    }

    return {
        "schema_version": "research_provenance_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "route_mode": route_mode,
        "code_commit": _git_commit(),
        "response_sha256": _stable_json_hash(response_material),
        "data_snapshot": _data_snapshot(ordered_site_ids),
        "config_hashes": config_hashes,
        "methodology": {
            "local_data_primary": True,
            "trend_method": "monthly_OLS_with_screened_two_segment_changepoints",
            "cluster_method": "deterministic_standardized_kmeans",
            "external_covariates": {
                "included": False,
                "note": (
                    "External covariates are intentionally excluded until local-data "
                    "trend, changepoint, clustering, and validation methods are stable."
                ),
            },
        },
    }
