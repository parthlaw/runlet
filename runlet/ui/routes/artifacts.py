"""
GET /api/runs/{run_id}/steps/{step}/artifacts
    Stream JSONL records for a step output (legacy endpoint, kept for compatibility).

GET /api/runs/{run_id}/steps/{step}/files
    List files available in a step's output dict as typed metadata.

GET /api/runs/{run_id}/steps/{step}/files/{key}
    Stream the raw file content for a named output key with correct Content-Type.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Generator
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from runlet.ui.server import registry

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_step_record(run_id: str, step: str):
    """Return (store, step_record) or raise HTTPException."""
    for entry in registry.values():
        run = entry.metastore.get_run(run_id)
        if run is None:
            continue
        step_records = entry.metastore.list_steps(run_id)
        record = next((s for s in step_records if s.step_name == step), None)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"Step '{step}' not found in run '{run_id}'"
            )
        return entry.store, record
    raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")


def _stream_jsonl(records: list[dict[str, Any]]) -> Generator[str, None, None]:
    for record in records:
        yield json.dumps(record) + "\n"


def _stream_raw_file(uri: str, store) -> Generator[bytes, None, None]:
    """Yield raw file bytes in 64 KB chunks, supporting file:// and store-backed URIs."""
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        with open(parsed.path, "rb") as fh:
            while chunk := fh.read(65_536):
                yield chunk
    else:
        tmp_fd, tmp_path = tempfile.mkstemp()
        os.close(tmp_fd)
        try:
            store.download_file(uri, tmp_path)
            with open(tmp_path, "rb") as fh:
                while chunk := fh.read(65_536):
                    yield chunk
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)


# ---------------------------------------------------------------------------
# Legacy artifacts endpoint
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/steps/{step}/artifacts")
def get_step_artifacts(
    run_id: str,
    step: str,
    output: str = Query(default="", description="Named output key (blank = first found)"),
) -> StreamingResponse:
    store, step_record = _find_step_record(run_id, step)

    output_dict: dict[str, Any] = step_record.output
    if not output_dict:
        raise HTTPException(status_code=404, detail=f"Step '{step}' has no recorded output")

    key = output if output and output in output_dict else next(iter(output_dict))
    uri = output_dict[key]
    if not isinstance(uri, str):
        raise HTTPException(status_code=422, detail=f"Output key '{key}' is not a URI string")

    try:
        from runlet.utils.streaming import iter_jsonl_dicts
        records = list(iter_jsonl_dicts(uri, store))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to load artifacts: {exc}") from exc

    return StreamingResponse(
        _stream_jsonl(records),
        media_type="application/x-ndjson",
        headers={"X-Total-Records": str(len(records)), "X-Output-Key": key},
    )


# ---------------------------------------------------------------------------
# New typed files endpoints
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/steps/{step}/files")
def list_step_files(run_id: str, step: str) -> list[dict[str, Any]]:
    """Return metadata for all file URIs found in the step's output dict."""
    _, step_record = _find_step_record(run_id, step)
    from runlet.utils.file_detector import scan_output_files
    return scan_output_files(step_record.output)


@router.get("/runs/{run_id}/steps/{step}/files/{key}")
def get_step_file(run_id: str, step: str, key: str) -> StreamingResponse:
    """Stream the file content for a named output key with format-appropriate Content-Type."""
    store, step_record = _find_step_record(run_id, step)

    output_dict: dict[str, Any] = step_record.output
    uri = output_dict.get(key)
    if uri is None:
        raise HTTPException(status_code=404, detail=f"Output key '{key}' not found in step '{step}'")
    if not isinstance(uri, str):
        raise HTTPException(status_code=422, detail=f"Output key '{key}' is not a URI string")

    from runlet.utils.file_detector import detect_format, get_size_bytes, is_file_uri
    if not is_file_uri(uri):
        raise HTTPException(status_code=422, detail=f"Output key '{key}' value is not a file URI")

    fmt = detect_format(uri)
    size = get_size_bytes(uri)
    headers: dict[str, str] = {"X-Format": fmt}
    if size is not None:
        headers["X-Size-Bytes"] = str(size)

    if fmt == "jsonl":
        try:
            from runlet.utils.streaming import iter_jsonl_dicts
            records = list(iter_jsonl_dicts(uri, store))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to read file: {exc}") from exc
        return StreamingResponse(
            _stream_jsonl(records),
            media_type="application/x-ndjson",
            headers={**headers, "X-Total-Records": str(len(records))},
        )
    elif fmt == "json":
        try:
            data = store.download_json(uri)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to read file: {exc}") from exc
        return StreamingResponse(
            iter([json.dumps(data, ensure_ascii=False)]),
            media_type="application/json",
            headers=headers,
        )
    else:
        # csv, tsv, text — stream raw bytes
        media = "text/csv" if fmt in ("csv", "tsv") else "text/plain"
        return StreamingResponse(
            _stream_raw_file(uri, store),
            media_type=media,
            headers=headers,
        )
