"""
ArtifactStore — abstract interface for pipeline artifact persistence.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from abc import ABC, abstractmethod
from enum import Enum
from typing import IO, Any, ClassVar


class StoreType(str, Enum):
    FILESYSTEM = "filesystem"
    S3 = "s3"


class StoreConfig:
    """Marker base for all artifact store configuration dataclasses."""

    TYPE: ClassVar[StoreType]


class ArtifactStore(ABC):
    """Abstract store for pipeline artifacts and large data files."""

    @abstractmethod
    def build_key(self, run_id: str, step_name: str, filename: str) -> str:
        """
        Construct a canonical object key.

        Pattern: {prefix}{run_id}/{step_name}/{filename}.json
        """

    @abstractmethod
    def to_uri(self, key: str) -> str:
        """Return the full URI for *key* in this store's namespace."""

    @abstractmethod
    def upload_json(self, data: dict[str, Any], key: str) -> str:
        """Serialise *data* as JSON and persist atomically. Returns the object URI."""

    @abstractmethod
    def download_json(self, uri: str) -> dict[str, Any]:
        """Download and parse a JSON object at *uri*. Returns a dict."""

    @abstractmethod
    def exists(self, uri: str) -> bool:
        """Return True if the object at *uri* exists."""

    @abstractmethod
    def upload_file(self, local_path: str, key: str) -> str:
        """Upload a local file without loading it fully into memory. Returns URI."""

    @abstractmethod
    def download_file(self, uri: str, local_path: str) -> None:
        """Download an object at *uri* to *local_path*."""

    @abstractmethod
    def upload_file_raw(self, local_path: str, key: str) -> str:
        """Upload using a caller-supplied bare key (no build_key convention)."""

    @abstractmethod
    def delete(self, uri: str) -> None:
        """Delete the object at *uri*."""

    def download_bytes_range(self, uri: str, start: int, end: int) -> bytes:
        """
        Return bytes [start, end) from the object at *uri*.

        Default: full download then slice. Override in subclasses for efficiency
        (e.g. HTTP Range requests for S3, direct seek for local files).
        """
        tmp_fd, tmp_path = tempfile.mkstemp()
        try:
            os.close(tmp_fd)
            self.download_file(uri, tmp_path)
            with open(tmp_path, "rb") as fh:
                fh.seek(start)
                return fh.read(end - start)
        finally:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)

    # ------------------------------------------------------------------
    # Content-addressed blob storage
    # ------------------------------------------------------------------

    @abstractmethod
    def put_blob(self, data: bytes | IO[bytes], *, hint_key: str | None = None) -> str:
        """
        Write data to a content-addressed location.

        Returns the sha256 hex digest. The blob is stored at
        ``{prefix}blobs/{hash[:2]}/{hash[2:4]}/{hash}``.
        ``hint_key`` is an optional human-readable alias for debugging.
        If the blob already exists it is not re-written (immutable).
        """

    @abstractmethod
    def get_blob(self, content_hash: str) -> bytes:
        """Retrieve blob bytes by sha256 hex digest."""

    @abstractmethod
    def put_pointer(self, key: str, content_hash: str) -> None:
        """
        Write a mutable pointer: *key* → *content_hash*.

        Allows stable step/run keys while blobs remain immutable.
        """

    @abstractmethod
    def get_pointer(self, key: str) -> str | None:
        """Resolve a pointer to a content hash. Returns None if not set."""

    def blob_uri(self, content_hash: str) -> str:
        """Return the URI for a blob by content hash. Subclasses must override."""
        raise NotImplementedError

    @staticmethod
    def _hash_data(data: bytes | IO[bytes]) -> tuple[bytes, str]:
        """Read *data* fully and return (raw_bytes, sha256_hex)."""
        raw = bytes(data) if isinstance(data, (bytes, bytearray)) else data.read()
        h = hashlib.sha256(raw).hexdigest()
        return raw, h


class ArtifactStoreError(RuntimeError):
    """Base class for artifact store errors."""


class ArtifactStoreUploadError(ArtifactStoreError):
    """Raised when an upload or delete operation fails."""


class ArtifactStoreDownloadError(ArtifactStoreError):
    """Raised when a download or existence check fails."""
