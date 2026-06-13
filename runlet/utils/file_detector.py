"""Detect file format and metadata from artifact URIs."""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

_EXT_TO_FORMAT: dict[str, str] = {
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".json": "json",
    ".csv": "csv",
    ".tsv": "tsv",
}

_URI_SCHEMES = ("file://", "s3://", "s3a://", "gs://")


def is_file_uri(value: Any) -> bool:
    """Return True if *value* is a string that looks like a file URI."""
    return isinstance(value, str) and any(value.startswith(p) for p in _URI_SCHEMES)


def detect_format(uri: str) -> str:
    """Infer file format from the URI path extension."""
    base = uri.removesuffix(".gz")
    path = urlparse(base).path
    _, ext = os.path.splitext(path)
    return _EXT_TO_FORMAT.get(ext.lower(), "text")


def get_size_bytes(uri: str) -> int | None:
    """Return file size in bytes for file:// URIs; None for other schemes."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    try:
        return os.path.getsize(parsed.path)
    except OSError:
        return None


def scan_output_files(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Scan a step output dict for URI values and return file metadata."""
    return [
        {
            "key": key,
            "format": detect_format(value),
            "size_bytes": get_size_bytes(value),
        }
        for key, value in output.items()
        if is_file_uri(value)
    ]
