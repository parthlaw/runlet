"""File open helpers for optional gzip-compressed JSONL artifacts."""

from __future__ import annotations

import gzip
from typing import IO


def is_gzip_path(path: str) -> bool:
    return path.endswith(".gz") or path.endswith(".jsonl.gz")


def open_artifact_read(path: str) -> IO[str]:
    if is_gzip_path(path):
        return gzip.open(path, mode="rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def open_artifact_write(path: str, *, compress: bool | None = None) -> IO[str]:
    if compress is None:
        compress = is_gzip_path(path)
    if compress:
        return gzip.open(path, mode="wt", encoding="utf-8")
    return open(path, "w", encoding="utf-8")
