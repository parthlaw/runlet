"""Tests for core abstractions (blob store, context split, store registry, run_id validation)."""

from __future__ import annotations

import pytest

from runlet.artifact_store import (
    FilesystemStore,
    build_store,
    build_store_config,
    register_store,
)
from runlet.orchestrator.config.models import StepConfig
from runlet.orchestrator.context.run_context import RunContext, build_context
from runlet.orchestrator.context.step_context import StepContext
from runlet.orchestrator.errors import ConfigValidationError
from runlet.orchestrator.execution.runner import _validate_run_id

# ---------------------------------------------------------------------------
# Content-addressed blob store (FilesystemStore)
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
# Context: StepContext is read-only, RunContext holds outputs
# ---------------------------------------------------------------------------

def test_step_context_has_no_set_output():
    """StepContext must not expose set_output or _register_output to steps."""
    ctx = build_context(
        run_id="r",
        pipeline_name="p",
        store=FilesystemStore.__new__(FilesystemStore),
        upload_store=FilesystemStore.__new__(FilesystemStore),
    )
    step_ctx = StepContext(ctx)
    assert not hasattr(step_ctx, "set_output")
    assert not hasattr(step_ctx, "_register_output")


def test_context_metadata_is_read_only(tmp_path):
    """Steps must not be able to mutate shared pipeline metadata."""
    store = FilesystemStore(str(tmp_path))
    ctx = build_context(
        run_id="r",
        pipeline_name="p",
        store=store,
        upload_store=store,
        metadata={"key": "original"},
    )
    step_ctx = StepContext(ctx)
    import pytest as _pytest
    with _pytest.raises(TypeError):
        step_ctx.metadata["key"] = "mutated"  # type: ignore[index]
    assert step_ctx.metadata["key"] == "original"


def test_step_context_metadata_is_mapping(tmp_path):
    store = FilesystemStore(str(tmp_path))
    ctx = build_context(
        run_id="r",
        pipeline_name="p",
        store=store,
        upload_store=store,
        metadata={"key": "value"},
    )
    step_ctx = StepContext(ctx)
    from collections.abc import Mapping
    assert isinstance(step_ctx.metadata, Mapping)


# ---------------------------------------------------------------------------
# register_store extensibility
# ---------------------------------------------------------------------------

def test_register_store_custom():
    from runlet.artifact_store import STORE_REGISTRY, FilesystemConfig

    class MockStore(FilesystemStore):
        pass

    register_store("mock", MockStore)
    try:
        cfg = FilesystemConfig(base_dir="/tmp")
        store = build_store(cfg)
        assert isinstance(store, FilesystemStore)
    finally:
        STORE_REGISTRY.pop("mock", None)


def test_build_store_unknown_type_raises():
    with pytest.raises(ValueError, match="is not a valid StoreType"):
        build_store_config({"type": "nonexistent_xyz"})


# ---------------------------------------------------------------------------
# run_id path-safety validation
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


# ---------------------------------------------------------------------------
# Step name path-safety validation (P1-C)
# ---------------------------------------------------------------------------



def _minimal_step(name: str) -> dict:
    return {"name": name, "module": "m", "class": "C"}


def test_valid_step_names():
    for name in ["extract", "load-data", "step_01", "a" * 128, "X-Y_Z"]:
        StepConfig.from_dict(_minimal_step(name))  # must not raise


def test_step_name_path_traversal_raises():
    with pytest.raises(ConfigValidationError, match="Invalid step name"):
        StepConfig.from_dict(_minimal_step("../../etc/passwd"))


def test_step_name_newline_raises():
    with pytest.raises(ConfigValidationError, match="Invalid step name"):
        StepConfig.from_dict(_minimal_step("step\nfoo"))


def test_step_name_dot_raises():
    with pytest.raises(ConfigValidationError, match="Invalid step name"):
        StepConfig.from_dict(_minimal_step("step.with.dots"))


def test_step_name_empty_raises():
    with pytest.raises(ConfigValidationError, match="Invalid step name"):
        StepConfig.from_dict(_minimal_step(""))


def test_step_name_too_long_raises():
    with pytest.raises(ConfigValidationError, match="Invalid step name"):
        StepConfig.from_dict(_minimal_step("a" * 129))
