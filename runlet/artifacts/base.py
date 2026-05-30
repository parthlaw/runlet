"""Base artifact Pydantic model."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel


class BaseArtifact(BaseModel):
    """
    Base class for all typed pipeline artifact records.

    Subclasses must be registered via the :func:`~runlet.artifacts.decorator.artifact`
    decorator, which sets SCHEMA_NAME and SCHEMA_VERSION and registers with the registry.
    """

    model_config = {"frozen": True}

    SCHEMA_NAME: ClassVar[str]
    SCHEMA_VERSION: ClassVar[int]
