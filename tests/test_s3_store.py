"""Tests for S3ArtifactStore using moto."""
import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from moto import mock_aws  # noqa: E402

from runlet.artifact_store.stores.s3 import S3ArtifactStore, S3Config  # noqa: E402

BUCKET = "test-bucket"
REGION = "us-east-1"


@pytest.fixture
def s3_store():
    with mock_aws():
        import boto3 as b3
        b3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
        config = S3Config(bucket=BUCKET, region=REGION, prefix="tests/")
        yield S3ArtifactStore(config)


def test_upload_download_json_roundtrip(s3_store):
    data = {"run_id": "r1", "run_status": "success", "steps": {"a": {"status": "success"}}}
    uri = s3_store.upload_json(data, "run1/state/run_state.json")
    result = s3_store.download_json(uri)
    assert result == data


def test_upload_download_file_roundtrip(s3_store, tmp_path):
    src = tmp_path / "file.txt"
    src.write_text("data")
    uri = s3_store.upload_file(str(src), "run1/step/file.txt")
    dest = str(tmp_path / "out.txt")
    s3_store.download_file(uri, dest)
    with open(dest) as fh:
        assert fh.read() == "data"


def test_exists_true_and_false(s3_store):
    uri = s3_store.upload_json({"a": 1}, "run1/step/data.json")
    assert s3_store.exists(uri)
    fake_uri = s3_store.to_uri("run1/step/missing.json")
    assert not s3_store.exists(fake_uri)
