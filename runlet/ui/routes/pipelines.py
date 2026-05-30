"""GET /api/pipelines — list all registered pipelines with their DAG shapes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from runlet.ui.server import registry

router = APIRouter()


def _pipeline_to_dict(name: str) -> dict[str, Any]:
    entry = registry[name]
    config = entry.config
    dag = entry.dag
    nodes = [
        {
            "id": step.name,
            "label": step.name,
            "has_condition": step.condition is not None,
            "execution_order": dag.topological_order.index(step.name),
        }
        for step in config.steps
    ]
    edges = [
        {"source": dep, "target": step.name}
        for step in config.steps
        for dep in step.depends_on
    ]
    return {"name": name, "nodes": nodes, "edges": edges}


@router.get("/pipelines")
def list_pipelines() -> list[dict[str, Any]]:
    return [_pipeline_to_dict(name) for name in registry]


@router.get("/pipelines/{name}")
def get_pipeline(name: str) -> dict[str, Any]:
    if name not in registry:
        raise HTTPException(status_code=404, detail=f"Pipeline '{name}' not found")
    return _pipeline_to_dict(name)
