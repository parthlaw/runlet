"""Tests for streaming utilities and store."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from runlet.artifact_store.stores.filesystem import FilesystemStore
from runlet.orchestrator.context import build_context
from runlet.utils.streaming import iter_jsonl, iter_jsonl_dicts, write_jsonl

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
# write_jsonl / iter_jsonl round-trip
# ---------------------------------------------------------------------------

class Row(BaseModel):
    n: int


def test_write_and_iter_jsonl_round_trip(tmp_path, fs_store):
    records = [Row(n=1), Row(n=2), Row(n=3)]
    uri = write_jsonl(records, fs_store, "run1/step/data.jsonl")
    assert uri

    result = list(iter_jsonl(uri, fs_store, Row))
    assert len(result) == 3
    assert [r.n for r in result] == [1, 2, 3]


def test_write_jsonl_with_dicts(tmp_path, fs_store):
    records = [{"x": 10}, {"x": 20}]
    uri = write_jsonl(records, fs_store, "run2/step/data.jsonl")
    result = list(iter_jsonl_dicts(uri, fs_store))
    assert result == [{"x": 10}, {"x": 20}]


def test_write_jsonl_compressed(tmp_path, fs_store):
    records = [Row(n=i) for i in range(5)]
    uri = write_jsonl(records, fs_store, "run3/step/data.jsonl.gz", compress=True)
    assert uri.endswith(".gz")

    result = list(iter_jsonl(uri, fs_store, Row))
    assert [r.n for r in result] == list(range(5))


def test_write_jsonl_empty(tmp_path, fs_store):
    uri = write_jsonl([], fs_store, "run4/step/data.jsonl")
    result = list(iter_jsonl_dicts(uri, fs_store))
    assert result == []


# ---------------------------------------------------------------------------
# context.get_output / has_output
# ---------------------------------------------------------------------------

def test_context_set_and_get_output(pipeline_context):
    pipeline_context.set_output("step_a", {"count": 42, "uri": "s3://bucket/key"})
    assert pipeline_context.has_output("step_a")
    out = pipeline_context.get_output("step_a")
    assert out == {"count": 42, "uri": "s3://bucket/key"}


def test_context_get_output_missing_raises(pipeline_context):
    with pytest.raises(KeyError, match="step_missing"):
        pipeline_context.get_output("step_missing")


def test_context_has_output_false(pipeline_context):
    assert not pipeline_context.has_output("nonexistent")



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
