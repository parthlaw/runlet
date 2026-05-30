"""
FilesystemStore — local filesystem artifact store for development and testing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from runlet.artifact_store.store import (
    ArtifactStore,
    ArtifactStoreDownloadError,
    ArtifactStoreUploadError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilesystemConfig:
    """Filesystem store settings."""

    base_dir: str
    prefix: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilesystemConfig:
        return cls(
            base_dir=data["base_dir"],
            prefix=data.get("prefix", ""),
        )


class FilesystemStore(ArtifactStore):
    """
    Stores artifacts as files under *base_dir*.

    URIs use the ``file://`` scheme with absolute paths.
    """

    def __init__(self, base_dir: str, prefix: str = "") -> None:
        self._base_dir = os.path.abspath(base_dir)
        self._prefix = prefix
        os.makedirs(self._base_dir, exist_ok=True)

    @classmethod
    def from_config(cls, config: FilesystemConfig) -> FilesystemStore:
        return cls(base_dir=config.base_dir, prefix=config.prefix)

    def build_key(self, run_id: str, step_name: str, filename: str) -> str:
        return f"{self._prefix}{run_id}/{step_name}/{filename}.jsonl"

    def to_uri(self, key: str) -> str:
        path = self._path_for_key(key)
        return f"file://{path}"

    def uri_to_path(self, uri: str) -> str:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError(f"Not a file URI: {uri}")
        return parsed.path

    def upload_jsonl(self, records: list[dict[str, Any]], key: str) -> str:
        path = self._path_for_key(key)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(path), prefix=".tmp_"
            )
            try:
                with os.fdopen(tmp_fd, "wb") as fh:
                    fh.write(_encode_jsonl(records))
                os.replace(tmp_path, path)
            except Exception:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
        except OSError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to write JSONL to {path}: {exc}"
            ) from exc

        uri = self.to_uri(key)
        logger.info("Uploaded %d record(s) → %s", len(records), uri)
        return uri

    def download_jsonl(self, uri: str) -> list[dict[str, Any]]:
        path = self.uri_to_path(uri)
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            raise ArtifactStoreDownloadError(
                f"Failed to read JSONL from {uri}: {exc}"
            ) from exc

        records = _decode_jsonl(raw)
        logger.info("Downloaded %d record(s) ← %s", len(records), uri)
        return records

    def exists(self, uri: str) -> bool:
        return os.path.isfile(self.uri_to_path(uri))

    def upload_file(self, local_path: str, key: str) -> str:
        dest = self._path_for_key(key)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(local_path, dest)
        except OSError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to copy {local_path} to {dest}: {exc}"
            ) from exc
        uri = self.to_uri(key)
        logger.info("Uploaded file → %s", uri)
        return uri

    def download_file(self, uri: str, local_path: str) -> None:
        src = self.uri_to_path(uri)
        try:
            os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
            shutil.copy2(src, local_path)
        except OSError as exc:
            raise ArtifactStoreDownloadError(
                f"Failed to copy {uri} to {local_path}: {exc}"
            ) from exc
        logger.info("Downloaded file ← %s", uri)

    def upload_file_raw(self, local_path: str, key: str) -> str:
        dest = self._safe_resolve(key)
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(local_path, dest)
        except OSError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to copy {local_path} to {dest}: {exc}"
            ) from exc
        uri = self.to_uri(key)
        logger.info("Uploaded raw file → %s", uri)
        return uri

    def delete(self, uri: str) -> None:
        path = self.uri_to_path(uri)
        try:
            if os.path.isfile(path):
                os.remove(path)
                logger.debug("Deleted %s", uri)
        except OSError as exc:
            raise ArtifactStoreUploadError(
                f"Failed to delete {uri}: {exc}"
            ) from exc

    def download_bytes_range(self, uri: str, start: int, end: int) -> bytes:
        """Seek directly into the local file — no temp file needed."""
        path = self.uri_to_path(uri)
        try:
            with open(path, "rb") as fh:
                fh.seek(start)
                return fh.read(end - start)
        except OSError as exc:
            raise ArtifactStoreDownloadError(
                f"Failed range read {uri} [{start}:{end}]: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Content-addressed blob storage
    # ------------------------------------------------------------------

    def put_blob(self, data: bytes | "IO[bytes]", *, hint_key: str | None = None) -> str:
        raw, h = self._hash_data(data)
        blob_path = os.path.join(self._base_dir, "blobs", h[:2], h[2:4], h)
        os.makedirs(os.path.dirname(blob_path), exist_ok=True)
        if not os.path.exists(blob_path):
            tmp_fd, tmp = tempfile.mkstemp(dir=os.path.dirname(blob_path))
            try:
                with os.fdopen(tmp_fd, "wb") as fh:
                    fh.write(raw)
                os.replace(tmp, blob_path)
            except Exception:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        return h

    def get_blob(self, content_hash: str) -> bytes:
        blob_path = os.path.join(self._base_dir, "blobs", content_hash[:2], content_hash[2:4], content_hash)
        try:
            with open(blob_path, "rb") as fh:
                return fh.read()
        except OSError as exc:
            raise ArtifactStoreDownloadError(
                f"Blob {content_hash!r} not found: {exc}"
            ) from exc

    def put_pointer(self, key: str, content_hash: str) -> None:
        ptr_path = self._safe_resolve(f"pointers/{key}.ptr")
        os.makedirs(os.path.dirname(ptr_path), exist_ok=True)
        tmp_fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ptr_path))
        try:
            with os.fdopen(tmp_fd, "w") as fh:
                fh.write(content_hash)
            os.replace(tmp, ptr_path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def get_pointer(self, key: str) -> str | None:
        ptr_path = self._safe_resolve(f"pointers/{key}.ptr")
        if not os.path.exists(ptr_path):
            return None
        with open(ptr_path) as fh:
            return fh.read().strip()

    def blob_uri(self, content_hash: str) -> str:
        blob_path = os.path.join(self._base_dir, "blobs", content_hash[:2], content_hash[2:4], content_hash)
        return f"file://{blob_path}"

    @property
    def prefix(self) -> str:
        return self._prefix

    def _safe_resolve(self, key: str) -> str:
        base = os.path.realpath(self._base_dir)
        dest = os.path.realpath(os.path.join(self._base_dir, key))
        if not dest.startswith(base + os.sep):
            raise ValueError(f"Path traversal attempt: key={key!r}")
        return dest

    def _path_for_key(self, key: str) -> str:
        return self._safe_resolve(key)


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
