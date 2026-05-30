"""Internal artifact registry — maps (schema_name, version) to artifact class."""

from __future__ import annotations

from .base import BaseArtifact
from .errors import UnknownArtifactError


class ArtifactRegistry:
    """Maps (schema_name, version) → artifact class for read-time mismatch detection."""

    def __init__(self) -> None:
        self._schemas: dict[tuple[str, int], type[BaseArtifact]] = {}

    def register(self, cls: type[BaseArtifact]) -> type[BaseArtifact]:
        key = (cls.SCHEMA_NAME, cls.SCHEMA_VERSION)
        existing = self._schemas.get(key)
        if existing is not None:
            if existing is not cls:
                raise ValueError(
                    f"Schema collision: {cls.SCHEMA_NAME!r} v{cls.SCHEMA_VERSION} is already "
                    f"registered by {existing.__module__}.{existing.__qualname__}. "
                    f"Conflicting registration from {cls.__module__}.{cls.__qualname__}."
                )
            return cls  # same class re-registered (e.g. module reload) — idempotent
        self._schemas[key] = cls
        return cls

    def enumerate(self) -> list[tuple[str, int, type[BaseArtifact]]]:
        """Return all registered schemas as (name, version, cls) triples."""
        return [(name, ver, cls) for (name, ver), cls in self._schemas.items()]

    def resolve(self, schema_name: str, version: int) -> type[BaseArtifact]:
        try:
            return self._schemas[(schema_name, version)]
        except KeyError as exc:
            raise UnknownArtifactError(schema_name, version) from exc


registry = ArtifactRegistry()
