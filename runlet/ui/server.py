"""
FastAPI application factory for the pipeline runner dashboard.

Build and start:
    app = build_app(["etl.json", "reporting.json"])
    uvicorn.run(app, host="0.0.0.0", port=8000)
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from runlet.artifact_store import ArtifactStore, build_store
from runlet.metastore import RunMetastore, build_metastore
from runlet.orchestrator.config import PipelineConfig
from runlet.orchestrator.dag import DAG


@dataclasses.dataclass
class PipelineEntry:
    config: PipelineConfig
    dag: DAG
    metastore: RunMetastore
    store: ArtifactStore


# Module-level registry populated by build_app — routes read from here.
registry: dict[str, PipelineEntry] = {}


def _load_pipeline(config_path: str) -> PipelineEntry:
    config = PipelineConfig.from_file(config_path)
    dag = DAG(config)
    metastore = build_metastore(config.raw.get("metastore"))
    store = build_store(config.store_raw)
    return PipelineEntry(config=config, dag=dag, metastore=metastore, store=store)


def build_app(config_paths: list[str]) -> FastAPI:
    global registry
    for path in config_paths:
        entry = _load_pipeline(path)
        registry[entry.config.name] = entry

    app = FastAPI(title="Pipeline Runner", docs_url="/api/docs")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    from runlet.ui.routes import artifacts, pipelines, runs

    app.include_router(pipelines.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(artifacts.router, prefix="/api")

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists() and any(static_dir.iterdir()):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
