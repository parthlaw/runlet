"""
Streaming utilities for step authors.

Steps that need to pass large datasets between each other can use these
helpers to write JSONL to the artifact store and read it back. Put the
returned URI in your step's output dict so downstream steps can find it.

Example
-------
.. code-block:: python

    from runlet.utils.streaming import write_jsonl, iter_jsonl

    class ProducerStep(BaseStep):
        def execute(self, context):
            uri = write_jsonl(
                generate_records(),
                context.artifact_store,
                f"{context.run_id}/producer/data.jsonl",
            )
            return {"data_uri": uri}

    class ConsumerStep(BaseStep):
        def execute(self, context):
            upstream = context.get_output("producer")
            for record in iter_jsonl(upstream["data_uri"], context.artifact_store, MyModel):
                process(record)
            return {"done": True}
"""

from __future__ import annotations

import contextlib
import gzip
import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from typing import Any, TypeVar

from pydantic import BaseModel

from runlet.artifact_store import ArtifactStore

T = TypeVar("T", bound=BaseModel)


def write_jsonl(
    records: Iterable[BaseModel | dict[str, Any]],
    store: ArtifactStore,
    key: str,
    *,
    compress: bool = False,
) -> str:
    """
    Stream *records* into a JSONL file and upload it to *store* at *key*.

    Returns the URI for the uploaded file. Pass that URI in your step's
    output dict for downstream steps to consume via :func:`iter_jsonl`.

    Parameters
    ----------
    records:
        Any iterable of Pydantic models or plain dicts.
    store:
        The artifact store to upload to (use ``context.artifact_store``).
    key:
        Store key, e.g. ``f"{context.run_id}/my_step/data.jsonl"``.
    compress:
        If True, write gzip-compressed JSONL (key should end with ``.jsonl.gz``).
    """
    suffix = ".jsonl.gz" if compress else ".jsonl"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(tmp_fd)
    try:
        open_fn = gzip.open(tmp_path, "wt", encoding="utf-8") if compress else open(tmp_path, "w", encoding="utf-8")
        with open_fn as fh:
            for record in records:
                if isinstance(record, BaseModel):
                    fh.write(record.model_dump_json() + "\n")
                else:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return store.upload_file(tmp_path, key)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)


def iter_jsonl(
    uri: str,
    store: ArtifactStore,
    cls: type[T],
) -> Iterator[T]:
    """
    Stream typed records from a JSONL artifact in *store*.

    Handles gzip-compressed artifacts transparently (detected by URI suffix).

    Parameters
    ----------
    uri:
        URI returned by :func:`write_jsonl` or stored in an upstream step's output.
    store:
        The artifact store to download from (use ``context.artifact_store``).
    cls:
        Pydantic model class to deserialize each record into.
    """
    is_gzip = uri.endswith(".gz")
    suffix = ".jsonl.gz" if is_gzip else ".jsonl"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(tmp_fd)
    try:
        store.download_file(uri, tmp_path)
        open_fn = gzip.open(tmp_path, "rt", encoding="utf-8") if is_gzip else open(tmp_path, encoding="utf-8")
        with open_fn as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield cls.model_validate_json(line)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)


def iter_jsonl_dicts(
    uri: str,
    store: ArtifactStore,
) -> Iterator[dict[str, Any]]:
    """
    Stream raw dicts from a JSONL artifact without Pydantic deserialization.

    Useful when schema is not known at call time or for schema-agnostic processing.
    """
    is_gzip = uri.endswith(".gz")
    suffix = ".jsonl.gz" if is_gzip else ".jsonl"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(tmp_fd)
    try:
        store.download_file(uri, tmp_path)
        open_fn = gzip.open(tmp_path, "rt", encoding="utf-8") if is_gzip else open(tmp_path, encoding="utf-8")
        with open_fn as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp_path)
