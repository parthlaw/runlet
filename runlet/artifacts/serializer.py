"""JSONL record serialization for typed artifacts."""

from __future__ import annotations

import json
from typing import TypeVar

from .base import BaseArtifact
from .errors import SchemaVersionMismatchError

T = TypeVar("T", bound=BaseArtifact)


class ArtifactSerializer:
    """Stateless helpers for typed JSONL artifacts (pure JSONL, no header line)."""

    @staticmethod
    def dump_record(artifact: BaseArtifact) -> str:
        return json.dumps(artifact.model_dump(), ensure_ascii=False)

    @staticmethod
    def load_record(
        line: str,
        cls: type[T],
        written_version: int,
    ) -> T:
        if written_version != cls.SCHEMA_VERSION:
            raise SchemaVersionMismatchError(cls.SCHEMA_NAME, written_version, cls.SCHEMA_VERSION)
        return cls.model_validate(json.loads(line))
