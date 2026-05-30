"""Tests for Plan 4: core abstractions (ArtifactRef, blob store, context split,
store registry, run_id validation)."""

from __future__ import annotations

import pytest

from runlet.artifact_store import (
    FilesystemStore,
    build_store,
    register_store,
)
from runlet.artifacts.ref import ArtifactRef
from runlet.orchestrator.context import PipelineContext, RuntimeContext
from runlet.orchestrator.runner import _validate_run_id
from runlet.orchestrator.writer_context import WriterContext, build_context

# ---------------------------------------------------------------------------
# 4.1 — ArtifactRef
# ---------------------------------------------------------------------------

def test_artifact_ref_is_hashable():
    ref = ArtifactRef(uri="s3://bucket/key", schema_name="MySchema", schema_version=1)
    d = {ref: "value"}
    assert d[ref] == "value"
    s = {ref}
    assert ref in s


def test_artifact_ref_usable_as_dict_key():
    ref_a = ArtifactRef(uri="a", schema_name="A", schema_version=1)
    ref_b = ArtifactRef(uri="b", schema_name="B", schema_version=2)
    mapping = {ref_a: "first", ref_b: "second"}
    assert mapping[ref_a] == "first"
    assert mapping[ref_b] == "second"


def test_artifact_ref_with_hash():
    ref = ArtifactRef(uri="s3://bucket/blob", schema_name="S", schema_version=1)
    assert ref.content_hash is None
    ref2 = ref.with_hash("abc123")
    assert ref2.content_hash == "abc123"
    assert ref.content_hash is None  # original unchanged (frozen)


def test_artifact_ref_round_trip():
    ref = ArtifactRef(
        uri="file:///tmp/blobs/ab/cd/abcd",
        schema_name="Schema",
        schema_version=2,
        content_hash="abcd1234",
        is_compressed=True,
    )
    assert ArtifactRef.from_dict(ref.to_dict()) == ref


def test_artifact_ref_from_uri():
    ref = ArtifactRef.from_uri("s3://b/k", "Schema", 3)
    assert ref.uri == "s3://b/k"
    assert ref.schema_name == "Schema"
    assert ref.schema_version == 3
    assert ref.content_hash is None


# ---------------------------------------------------------------------------
# 4.2 — Content-addressed blob store (FilesystemStore)
# ---------------------------------------------------------------------------

@pytest.fixture
def fs_store(tmp_path):
    return FilesystemStore(str(tmp_path))


def test_put_blob_returns_sha256(fs_store):
    import hashlib
    data = b"hello world"
    h = fs_store.put_blob(data)
    assert h == hashlib.sha256(data).hexdigest()


def test_put_blob_same_content_same_hash_no_error(fs_store):
    data = b"duplicate content"
    h1 = fs_store.put_blob(data)
    h2 = fs_store.put_blob(data)
    assert h1 == h2


def test_put_blob_immutable_not_rewritten(fs_store, tmp_path):
    """Second put_blob with same content skips the write (blob file unchanged)."""
    import os
    data = b"immutable data"
    h = fs_store.put_blob(data)
    blob_path = tmp_path / "blobs" / h[:2] / h[2:4] / h
    mtime_before = os.stat(blob_path).st_mtime_ns
    fs_store.put_blob(data)
    mtime_after = os.stat(blob_path).st_mtime_ns
    assert mtime_before == mtime_after


def test_get_blob_round_trip(fs_store):
    data = b"round trip data"
    h = fs_store.put_blob(data)
    assert fs_store.get_blob(h) == data


def test_put_blob_accepts_file_object(fs_store, tmp_path):
    data = b"file object content"
    path = tmp_path / "input.bin"
    path.write_bytes(data)
    with open(path, "rb") as fh:
        h = fs_store.put_blob(fh)
    assert fs_store.get_blob(h) == data


def test_pointer_round_trip(fs_store):
    data = b"pointer test"
    h = fs_store.put_blob(data)
    fs_store.put_pointer("run1/step1/output", h)
    assert fs_store.get_pointer("run1/step1/output") == h


def test_get_pointer_returns_none_when_missing(fs_store):
    assert fs_store.get_pointer("nonexistent/key") is None


def test_blob_uri_format(fs_store, tmp_path):
    h = fs_store.put_blob(b"uri test")
    uri = fs_store.blob_uri(h)
    assert uri.startswith("file://")
    assert h in uri


# ---------------------------------------------------------------------------
# 4.5 — RuntimeContext is read-only to steps
# ---------------------------------------------------------------------------

def test_pipeline_context_is_alias_for_writer_context():
    assert PipelineContext is WriterContext


def test_runtime_context_has_no_set_path():
    ctx = build_context(
        run_id="r",
        pipeline_name="p",
        store=FilesystemStore.__new__(FilesystemStore),
        upload_store=FilesystemStore.__new__(FilesystemStore),
    )
    # WriterContext has set_path; RuntimeContext does not
    assert hasattr(ctx, "set_path")
    assert not hasattr(RuntimeContext, "set_path")


def test_writer_context_metadata_is_mutable(tmp_path):
    store = FilesystemStore(str(tmp_path))
    ctx = build_context(
        run_id="r",
        pipeline_name="p",
        store=store,
        upload_store=store,
        metadata={"key": "original"},
    )
    ctx.metadata["key"] = "mutated"
    assert ctx.metadata["key"] == "mutated"


def test_runtime_context_metadata_is_mapping(tmp_path):
    store = FilesystemStore(str(tmp_path))
    ctx = build_context(
        run_id="r",
        pipeline_name="p",
        store=store,
        upload_store=store,
        metadata={"key": "value"},
    )
    rc: RuntimeContext = ctx
    from collections.abc import Mapping
    assert isinstance(rc.metadata, Mapping)


# ---------------------------------------------------------------------------
# 4.6 — register_store extensibility
# ---------------------------------------------------------------------------

def test_register_store_custom():
    from runlet.artifact_store import STORE_REGISTRY

    class MockStore(FilesystemStore):
        @classmethod
        def from_config(cls, cfg):
            return cls(cfg.get("base_dir", "/tmp"))

    register_store("mock", MockStore)
    try:
        store = build_store({"type": "mock", "base_dir": "/tmp"})
        assert isinstance(store, MockStore)
    finally:
        STORE_REGISTRY.pop("mock", None)


def test_build_store_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown store type"):
        build_store({"type": "nonexistent_xyz"})


# ---------------------------------------------------------------------------
# 4.7 — run_id path-safety validation
# ---------------------------------------------------------------------------

def test_valid_run_ids():
    for run_id in ["run001", "run-001", "run_001", "a" * 128, "abc-def_123"]:
        _validate_run_id(run_id)  # must not raise


def test_run_id_with_slash_raises():
    with pytest.raises(ValueError, match="unsafe characters"):
        _validate_run_id("run/with/slash")


def test_run_id_with_dots_raises():
    with pytest.raises(ValueError, match="unsafe characters"):
        _validate_run_id("run.with.dots")


def test_run_id_too_long_raises():
    with pytest.raises(ValueError, match="unsafe characters"):
        _validate_run_id("a" * 129)


def test_run_id_empty_raises():
    with pytest.raises(ValueError, match="unsafe characters"):
        _validate_run_id("")
