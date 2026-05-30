"""Tests for FilesystemStore."""
import threading

import pytest

from runlet.artifact_store import FilesystemStore


@pytest.fixture
def store(tmp_path):
    return FilesystemStore(str(tmp_path))


def test_upload_download_jsonl_roundtrip(store):
    records = [{"a": 1}, {"b": 2}]
    uri = store.upload_jsonl(records, "run1/step/out.jsonl")
    result = store.download_jsonl(uri)
    assert result == records


def test_upload_download_file_roundtrip(store, tmp_path):
    src = tmp_path / "input.txt"
    src.write_text("hello")
    uri = store.upload_file(str(src), "run1/step/input.txt")
    dest = str(tmp_path / "output.txt")
    store.download_file(uri, dest)
    with open(dest) as fh:
        assert fh.read() == "hello"


def test_exists_true_and_false(store):
    uri = store.upload_jsonl([{"x": 1}], "run1/step/data.jsonl")
    assert store.exists(uri)
    fake_uri = store.to_uri("run1/step/nope.jsonl")
    assert not store.exists(fake_uri)


def test_path_traversal_raises(store, tmp_path):
    src = tmp_path / "evil.txt"
    src.write_text("evil")
    with pytest.raises(ValueError, match="Path traversal"):
        store.upload_file_raw(str(src), "../../../etc/passwd")


def test_concurrent_upload_jsonl_no_torn_file(store):
    key = "run1/step/concurrent.jsonl"
    errors = []

    def writer(n):
        try:
            store.upload_jsonl([{"writer": n, "v": i} for i in range(10)], key)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    uri = store.to_uri(key)
    records = store.download_jsonl(uri)
    assert len(records) == 10  # exactly one writer's batch (last wins atomically)
