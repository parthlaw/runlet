"""@artifact decorator — register Pydantic BaseArtifact subclasses as pipeline artifacts."""

from __future__ import annotations

from typing import TypeVar

from .base import BaseArtifact
from .registry import ArtifactRegistry
from .registry import registry as _global_registry

T = TypeVar("T", bound=type[BaseArtifact])


def artifact(
    version: int,
    name: str | None = None,
    registry: ArtifactRegistry | None = None,
) -> ArtifactDecorator[T]:
    """
    Register a BaseArtifact subclass as a versioned pipeline artifact.

    Usage::

        @artifact(version=1)
        class ExtractRecord(BaseArtifact):
            page: int
            text: str
    """

    def decorator(cls: T) -> T:
        if not (isinstance(cls, type) and issubclass(cls, BaseArtifact)):
            raise TypeError(
                f"@artifact requires a BaseArtifact subclass, got {cls!r}. "
                "Define your artifact class as: class Foo(BaseArtifact): ..."
            )
        schema_name = name or cls.__name__
        cls.SCHEMA_NAME = schema_name  # type: ignore[attr-defined]
        cls.SCHEMA_VERSION = version  # type: ignore[attr-defined]
        (registry or _global_registry).register(cls)
        return cls

    return decorator  # type: ignore[return-value]


# Type alias used only for the return annotation above
from collections.abc import Callable  # noqa: E402

ArtifactDecorator = Callable[[T], T]
