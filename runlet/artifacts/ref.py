from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class ArtifactRef:
    """Typed, immutable handle for a pipeline step artifact."""

    uri: str
    schema_name: str
    schema_version: int
    content_hash: str | None = None
    is_compressed: bool = False

    def with_hash(self, h: str) -> ArtifactRef:
        return dataclasses.replace(self, content_hash=h)

    @classmethod
    def from_uri(cls, uri: str, schema_name: str, schema_version: int) -> ArtifactRef:
        return cls(uri=uri, schema_name=schema_name, schema_version=schema_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
            "is_compressed": self.is_compressed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactRef:
        return cls(
            uri=data["uri"],
            schema_name=data.get("schema_name", ""),
            schema_version=int(data.get("schema_version", 0)),
            content_hash=data.get("content_hash"),
            is_compressed=bool(data.get("is_compressed", False)),
        )
