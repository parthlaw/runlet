"""
GET /api/pipelines/{name}/runs  — paginated run history for a pipeline
GET /api/runs/{run_id}          — run detail with all step records
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from runlet.ui.server import registry

router = APIRouter()


def _run_to_dict(r: Any) -> dict[str, Any]:
    return {
        **dataclasses.asdict(r),
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def _step_to_dict(s: Any) -> dict[str, Any]:
    return {
        **dataclasses.asdict(s),
        "recorded_at": s.recorded_at.isoformat(),
    }


@router.get("/pipelines/{name}/runs")
def list_runs(
    name: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    if name not in registry:
        raise HTTPException(status_code=404, detail=f"Pipeline '{name}' not found")
    entry = registry[name]
    runs = entry.metastore.list_runs(pipeline_name=name, limit=limit, offset=offset)
    return [_run_to_dict(r) for r in runs]


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    # Search across all pipelines since run_id is globally unique
    for entry in registry.values():
        run = entry.metastore.get_run(run_id)
        if run is not None:
            steps = entry.metastore.list_steps(run_id)
            return {
                "run": _run_to_dict(run),
                "steps": [_step_to_dict(s) for s in steps],
            }
    raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
