"""Integration tests for the artifact system (Pydantic-based)."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from runlet.artifact_store.stores.filesystem import FilesystemStore
from runlet.artifacts import ArtifactSerializer, BaseArtifact, SchemaError, artifact
from runlet.artifacts.base import BaseArtifact
from runlet.artifacts.errors import SchemaError
from runlet.artifacts.registry import ArtifactRegistry
from runlet.artifacts.writer import EmptyArtifact, write_step_artifacts
from runlet.artifacts.ref import ArtifactRef
from runlet.orchestrator.context import PipelineContext, build_context


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_registry() -> ArtifactRegistry:
    return ArtifactRegistry()


@pytest.fixture
def fs_store(tmp_path):
    return FilesystemStore(base_dir=str(tmp_path))


@pytest.fixture
def pipeline_context(fs_store):
    return build_context(
        run_id="test-run",
        pipeline_name="test-pipeline",
        store=fs_store,
        upload_store=fs_store,
    )


# ---------------------------------------------------------------------------
# Registry collision detection
# ---------------------------------------------------------------------------

def test_registry_collision_raises():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Schema(BaseArtifact):
        v: int

    class Schema2(BaseArtifact):
        SCHEMA_NAME = "Schema"
        SCHEMA_VERSION = 1
        v: int

    with pytest.raises(ValueError, match="Schema collision"):
        reg.register(Schema2)


def test_registry_same_class_idempotent():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Idempotent(BaseArtifact):
        v: int

    # Must not raise.
    reg.register(Idempotent)
    assert len(reg.enumerate()) == 1


def test_registry_enumerate():
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class A(BaseArtifact):
        x: int

    @artifact(version=2, registry=reg)
    class B(BaseArtifact):
        y: str

    entries = reg.enumerate()
    assert len(entries) == 2
    names = {name for name, _, _ in entries}
    assert "A" in names
    assert "B" in names


# ---------------------------------------------------------------------------
# write_step_artifacts — pure JSONL (no header)
# ---------------------------------------------------------------------------

def test_write_step_artifacts_single_file(tmp_path):
    """write_step_artifacts must produce pure JSONL records in one file."""
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Row(BaseArtifact):
        n: int

    step = MagicMock()
    step.execute = MagicMock(return_value=iter([Row(n=1), Row(n=2), Row(n=3)]))

    ctx = MagicMock()
    tmp_final = str(tmp_path / "output.jsonl")

    artifact_cls, count = write_step_artifacts(
        step_instance=step,
        context=ctx,
        step_name="test_step",
        run_id="run-1",
        tmp_final_path=tmp_final,
    )

    assert count == 3
    assert artifact_cls is Row

    with open(tmp_final, encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip()]

    assert len(lines) == 3  # 3 pure data records, no header
    assert json.loads(lines[0]) == {"n": 1}
    assert json.loads(lines[1]) == {"n": 2}
    assert json.loads(lines[2]) == {"n": 3}


def test_write_step_artifacts_empty_step(tmp_path):
    step = MagicMock()
    step.execute = MagicMock(return_value=iter([]))
    ctx = MagicMock()
    tmp_final = str(tmp_path / "output.jsonl")

    artifact_cls, count = write_step_artifacts(
        step_instance=step,
        context=ctx,
        step_name="empty_step",
        run_id="run-1",
        tmp_final_path=tmp_final,
    )

    assert count == 0
    assert artifact_cls is EmptyArtifact

    with open(tmp_final, encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    assert lines == []  # empty file, no header


# ---------------------------------------------------------------------------
# iter_artifacts schema mismatch
# ---------------------------------------------------------------------------

def _write_artifact_file(path: str, records: list[dict[str, Any]]) -> None:
    """Write a pure JSONL artifact file (no header)."""
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def test_iter_artifacts_schema_mismatch_strict(tmp_path, fs_store):
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Expected(BaseArtifact):
        x: int

    # Write a file; the ArtifactRef will declare schema "Other", not "Expected".
    artifact_path = str(tmp_path / "artifact.jsonl")
    _write_artifact_file(artifact_path, [{"x": 1}])

    key = "run1/s1/output.jsonl"
    uri = fs_store.upload_file(artifact_path, key)

    ctx = build_context(
        run_id="run1",
        pipeline_name="p",
        store=fs_store,
        upload_store=fs_store,
        artifact_registry=reg,
    )
    # Ref says schema is "Other", but we request "Expected" → mismatch
    ctx.set_path("s1", "output", ArtifactRef.from_uri(uri, "Other", 1))

    with pytest.raises(SchemaError, match="Schema mismatch"):
        list(ctx.iter_artifacts("s1", Expected))


def test_iter_artifacts_schema_mismatch_non_strict(tmp_path, fs_store, caplog):
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Expected2(BaseArtifact):
        x: int

    artifact_path = str(tmp_path / "artifact.jsonl")
    _write_artifact_file(artifact_path, [{"x": 42}])

    key = "run2/s2/output.jsonl"
    uri = fs_store.upload_file(artifact_path, key)

    ctx = build_context(
        run_id="run2",
        pipeline_name="p",
        store=fs_store,
        upload_store=fs_store,
        artifact_registry=reg,
    )
    ctx.set_path("s2", "output", ArtifactRef.from_uri(uri, "Other", 1))

    with caplog.at_level(logging.WARNING):
        records = list(ctx.iter_artifacts("s2", Expected2, strict=False))

    assert len(records) == 1
    assert any("Schema mismatch" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Isolated registry per context
# ---------------------------------------------------------------------------

def test_two_contexts_with_distinct_registries():
    reg_a = make_registry()
    reg_b = make_registry()

    @artifact(version=1, registry=reg_a)
    class SharedName(BaseArtifact):
        v: int

    # Registering a *different* class with the same name in reg_b must succeed.
    @artifact(version=1, name="SharedName", registry=reg_b)
    class AnotherSharedName(BaseArtifact):
        v: int

    cls_a = reg_a.resolve("SharedName", 1)
    cls_b = reg_b.resolve("SharedName", 1)
    assert cls_a is not cls_b


# ---------------------------------------------------------------------------
# FilesystemStore range GET
# ---------------------------------------------------------------------------

def test_filesystem_range_get(tmp_path, fs_store):
    """FilesystemStore.download_bytes_range must return the correct byte slice."""
    content = b"0123456789abcdef"
    key = "run/step/file.bin"
    local = str(tmp_path / "file.bin")
    with open(local, "wb") as fh:
        fh.write(content)
    uri = fs_store.upload_file(local, key)

    result = fs_store.download_bytes_range(uri, 4, 10)
    assert result == b"456789"


def test_read_first_record_uses_range_get(tmp_path, fs_store):
    """read_first_record must not download the full file for non-gzip artifacts."""
    reg = make_registry()

    @artifact(version=1, registry=reg)
    class Item(BaseArtifact):
        val: int

    # Write a real artifact file (pure JSONL).
    artifact_path = str(tmp_path / "out.jsonl")
    _write_artifact_file(artifact_path, [{"val": 99}, {"val": 100}])
    key = "run3/s3/output.jsonl"
    uri = fs_store.upload_file(artifact_path, key)

    download_file_calls: list[str] = []
    original_download_file = fs_store.download_file

    def tracking_download_file(u: str, p: str) -> None:
        download_file_calls.append(u)
        return original_download_file(u, p)

    fs_store.download_file = tracking_download_file  # type: ignore[method-assign]

    ctx = build_context(
        run_id="run3",
        pipeline_name="p",
        store=fs_store,
        upload_store=fs_store,
        artifact_registry=reg,
    )
    ctx.set_path("s3", "output", ArtifactRef.from_uri(uri, "Item", 1))

    record = ctx.read_first_record("s3")
    assert record == {"val": 99}
    # The full download_file should NOT have been called since range read succeeded.
    assert download_file_calls == [], "range read should avoid full download_file call"
