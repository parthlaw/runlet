"""
S3ArtifactStore — boto3-backed artifact store for JSONL pipeline outputs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import IO, Any, ClassVar, cast

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from runlet.artifact_store.store import (
    ArtifactStore,
    ArtifactStoreDownloadError,
    ArtifactStoreUploadError,
    StoreConfig,
    StoreType,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class S3Config(StoreConfig):
    """S3 connection settings sourced from pipeline.json → store block."""

    TYPE: ClassVar[StoreType] = StoreType.S3

    bucket: str
    region: str
    prefix: str  # e.g. "pipelines/" — trailing slash recommended
    endpoint_url: str | None = None  # optional, for LocalStack / MinIO

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> S3Config:
        return cls(
            bucket=data["bucket"],
            region=data["region"],
            prefix=data.get("prefix", "pipelines/"),
            endpoint_url=data.get("endpoint_url"),
        )


class S3ArtifactStore(ArtifactStore):
    """
    Boto3-backed store that speaks JSONL.

    Usage
    -----
    store = S3ArtifactStore(config)
    key = store.build_key(run_id="run-01", step_name="extract", filename="output")
    uri = store.upload_jsonl(records=[{"id": 1}], key=key)
    records = store.download_jsonl(uri)
    """

    def __init__(self, config: S3Config) -> None:
        self._config = config
        self._client = self._build_boto_client()

    def build_key(self, run_id: str, step_name: str, filename: str) -> str:
        return f"{self._config.prefix}{run_id}/{step_name}/{filename}.jsonl"

    def to_uri(self, key: str) -> str:
        return f"s3://{self._config.bucket}/{key}"

    def uri_to_key(self, uri: str) -> str:
        prefix = f"s3://{self._config.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError(
                f"S3 URI '{uri}' does not belong to bucket '{self._config.bucket}'"
            )
        return uri[len(prefix) :]

    def upload_jsonl(self, records: list[dict[str, Any]], key: str) -> str:
        body = _encode_jsonl(records)
        try:
            self._client.put_object(
                Bucket=self._config.bucket,
                Key=key,
                Body=body,
                ContentType="application/x-ndjson",
            )
        except ClientError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to upload to s3://{self._config.bucket}/{key}: {exc}"
            ) from exc

        uri = self.to_uri(key)
        logger.info("Uploaded %d record(s) → %s", len(records), uri)
        return uri

    def download_jsonl(self, uri: str) -> list[dict[str, Any]]:
        key = self.uri_to_key(uri)
        try:
            response = self._client.get_object(Bucket=self._config.bucket, Key=key)
            raw = response["Body"].read().decode("utf-8")
        except ClientError as exc:
            raise ArtifactStoreDownloadError(
                f"Failed to download {uri}: {exc}"
            ) from exc

        records = _decode_jsonl(raw)
        logger.info("Downloaded %d record(s) ← %s", len(records), uri)
        return records

    def exists(self, uri: str) -> bool:
        key = self.uri_to_key(uri)
        try:
            self._client.head_object(Bucket=self._config.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise ArtifactStoreDownloadError(
                f"Unexpected error checking existence of {uri}: {exc}"
            ) from exc

    def upload_file(self, local_path: str, key: str) -> str:
        try:
            self._client.upload_file(local_path, self._config.bucket, key)
        except ClientError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to upload {local_path} to "
                f"s3://{self._config.bucket}/{key}: {exc}"
            ) from exc
        uri = self.to_uri(key)
        logger.info("Uploaded file → %s", uri)
        return uri

    def download_file(self, uri: str, local_path: str) -> None:
        key = self.uri_to_key(uri)
        try:
            self._client.download_file(self._config.bucket, key, local_path)
        except ClientError as exc:
            raise ArtifactStoreDownloadError(
                f"Failed to download {uri} to {local_path}: {exc}"
            ) from exc
        logger.info("Downloaded file ← %s", uri)

    def upload_file_raw(self, local_path: str, key: str) -> str:
        try:
            self._client.upload_file(local_path, self._config.bucket, key)
        except ClientError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to upload {local_path} to "
                f"s3://{self._config.bucket}/{key}: {exc}"
            ) from exc
        uri = self.to_uri(key)
        logger.info("Uploaded raw file → %s", uri)
        return uri

    def delete(self, uri: str) -> None:
        key = self.uri_to_key(uri)
        try:
            self._client.delete_object(Bucket=self._config.bucket, Key=key)
            logger.debug("Deleted %s", uri)
        except ClientError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to delete {uri}: {exc}"
            ) from exc

    def download_bytes_range(self, uri: str, start: int, end: int) -> bytes:
        """Fetch bytes [start, end) using an S3 Range GET — avoids full object download."""
        key = self.uri_to_key(uri)
        try:
            response = self._client.get_object(
                Bucket=self._config.bucket,
                Key=key,
                Range=f"bytes={start}-{end - 1}",
            )
            return cast(bytes, response["Body"].read())
        except ClientError as exc:
            raise ArtifactStoreDownloadError(
                f"Failed range download {uri} [{start}:{end}]: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Content-addressed blob storage
    # ------------------------------------------------------------------

    def put_blob(self, data: bytes | IO[bytes], *, hint_key: str | None = None) -> str:
        raw, h = self._hash_data(data)
        key = self._blob_key(h)
        try:
            self._client.head_object(Bucket=self._config.bucket, Key=key)
            return h  # already exists, skip upload
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                raise ArtifactStoreDownloadError(
                    f"Unexpected error checking blob {h!r}: {exc}"
                ) from exc
        try:
            self._client.put_object(
                Bucket=self._config.bucket,
                Key=key,
                Body=raw,
                ContentType="application/octet-stream",
            )
        except ClientError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to upload blob {h!r}: {exc}"
            ) from exc
        return h

    def get_blob(self, content_hash: str) -> bytes:
        key = self._blob_key(content_hash)
        try:
            response = self._client.get_object(Bucket=self._config.bucket, Key=key)
            return cast(bytes, response["Body"].read())
        except ClientError as exc:
            raise ArtifactStoreDownloadError(
                f"Blob {content_hash!r} not found: {exc}"
            ) from exc

    def put_pointer(self, key: str, content_hash: str) -> None:
        ptr_key = f"{self._config.prefix}pointers/{key}.ptr"
        try:
            self._client.put_object(
                Bucket=self._config.bucket,
                Key=ptr_key,
                Body=content_hash.encode(),
                ContentType="text/plain",
            )
        except ClientError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to write pointer {key!r}: {exc}"
            ) from exc

    def get_pointer(self, key: str) -> str | None:
        ptr_key = f"{self._config.prefix}pointers/{key}.ptr"
        try:
            response = self._client.get_object(Bucket=self._config.bucket, Key=ptr_key)
            return cast(str, response["Body"].read().decode().strip())
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return None
            raise ArtifactStoreDownloadError(
                f"Failed to read pointer {key!r}: {exc}"
            ) from exc

    def blob_uri(self, content_hash: str) -> str:
        return self.to_uri(self._blob_key(content_hash))

    def _blob_key(self, content_hash: str) -> str:
        return f"{self._config.prefix}blobs/{content_hash[:2]}/{content_hash[2:4]}/{content_hash}"

    @property
    def bucket(self) -> str:
        """The S3 bucket name this store is configured against."""
        return self._config.bucket

    @property
    def prefix(self) -> str:
        """The key prefix prepended to all artifact keys."""
        return self._config.prefix

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> S3ArtifactStore:
        return cls(S3Config.from_dict(cfg))

    def _build_boto_client(self) -> Any:
        kwargs: dict[str, Any] = {"region_name": self._config.region}
        if self._config.endpoint_url:
            kwargs["endpoint_url"] = self._config.endpoint_url
        return boto3.client("s3", **kwargs)


def _encode_jsonl(records: list[dict[str, Any]]) -> bytes:
    lines = (json.dumps(record, ensure_ascii=False) for record in records)
    return "\n".join(lines).encode("utf-8")


def _decode_jsonl(raw: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records
