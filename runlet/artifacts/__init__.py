"""Typed pipeline artifacts — Pydantic models, JSONL serialization, and version tracking."""

from .base import BaseArtifact
from .decorator import artifact
from .errors import (
    ArtifactError,
    SchemaError,
    SchemaVersionMismatchError,
    UnknownArtifactError,
)
from .ref import ArtifactRef
from .registry import ArtifactRegistry, registry
from .serializer import ArtifactSerializer

__all__ = [
    "ArtifactError",
    "ArtifactRef",
    "ArtifactRegistry",
    "ArtifactSerializer",
    "BaseArtifact",
    "SchemaError",
    "SchemaVersionMismatchError",
    "UnknownArtifactError",
    "artifact",
    "registry",
]
