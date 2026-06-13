"""Tests for FilesystemStore."""
import threading

import pytest

from runlet.artifact_store import FilesystemStore


@pytest.fixture
def store(tmp_path):
    return FilesystemStore(str(tmp_path))


def test_upload_download_json_roundtrip(store):
    data = {"run_id": "r1", "run_status": "success", "steps": {"a": {"status": "success"}}}
    uri = store.upload_json(data, "run1/state/run_state.json")
    result = store.download_json(uri)
    assert result == data


def test_upload_download_file_roundtrip(store, tmp_path):
    src = tmp_path / "input.txt"
    src.write_text("hello")
    uri = store.upload_file(str(src), "run1/step/input.txt")
    dest = str(tmp_path / "output.txt")
    store.download_file(uri, dest)
    with open(dest) as fh:
        assert fh.read() == "hello"


def test_exists_true_and_false(store):
    uri = store.upload_json({"x": 1}, "run1/step/data.json")
    assert store.exists(uri)
    fake_uri = store.to_uri("run1/step/nope.json")
    assert not store.exists(fake_uri)


def test_path_traversal_raises(store, tmp_path):
    src = tmp_path / "evil.txt"
    src.write_text("evil")
    with pytest.raises(ValueError, match="Path traversal"):
        store.upload_file_raw(str(src), "../../../etc/passwd")


def test_concurrent_upload_json_last_write_wins(store):
    key = "run1/state/run_state.json"
    errors = []

    def writer(n):
        try:
            store.upload_json({"writer": n, "items": list(range(10))}, key)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    uri = store.to_uri(key)
    result = store.download_json(uri)
    assert "writer" in result
    assert "items" in result
