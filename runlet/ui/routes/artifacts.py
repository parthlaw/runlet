"""
GET /api/runs/{run_id}/steps/{step}/artifacts
    Stream JSONL records for a step output as newline-delimited JSON.
    Query param ?output selects which named output (default: first one found).
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from runlet.ui.server import registry

router = APIRouter()


def _stream_records(records: list[dict[str, Any]]) -> Generator[str, None, None]:
    for record in records:
        yield json.dumps(record) + "\n"


@router.get("/runs/{run_id}/steps/{step}/artifacts")
def get_step_artifacts(
    run_id: str,
    step: str,
    output: str = Query(default="", description="Named output key (blank = first found)"),
) -> StreamingResponse:
    # Find which pipeline owns this run
    for entry in registry.values():
        run = entry.metastore.get_run(run_id)
        if run is None:
            continue

        step_records = entry.metastore.list_steps(run_id)
        step_record = next((s for s in step_records if s.step_name == step), None)
        if step_record is None:
            raise HTTPException(
                status_code=404, detail=f"Step '{step}' not found in run '{run_id}'"
            )

        paths: dict[str, Any] = step_record.paths
        if not paths:
            raise HTTPException(status_code=404, detail=f"Step '{step}' has no recorded artifacts")

        # Select the requested output name or fall back to the first one
        key = output if output and output in paths else next(iter(paths))
        ref = paths[key]
        uri: str = ref["uri"] if isinstance(ref, dict) else ref.uri

        try:
            records = entry.store.download_jsonl(uri)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to load artifacts: {exc}") from exc

        return StreamingResponse(
            _stream_records(records),
            media_type="application/x-ndjson",
            headers={"X-Total-Records": str(len(records)), "X-Output-Key": key},
        )

    raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
