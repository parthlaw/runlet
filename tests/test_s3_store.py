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


def test_upload_download_jsonl_roundtrip(s3_store):
    records = [{"x": 1}, {"y": 2}]
    uri = s3_store.upload_jsonl(records, "run1/step/out.jsonl")
    result = s3_store.download_jsonl(uri)
    assert result == records


def test_upload_download_file_roundtrip(s3_store, tmp_path):
    src = tmp_path / "file.txt"
    src.write_text("data")
    uri = s3_store.upload_file(str(src), "run1/step/file.txt")
    dest = str(tmp_path / "out.txt")
    s3_store.download_file(uri, dest)
    with open(dest) as fh:
        assert fh.read() == "data"


def test_exists_true_and_false(s3_store):
    uri = s3_store.upload_jsonl([{"a": 1}], "run1/step/data.jsonl")
    assert s3_store.exists(uri)
    fake_uri = s3_store.to_uri("run1/step/missing.jsonl")
    assert not s3_store.exists(fake_uri)
