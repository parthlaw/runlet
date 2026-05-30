"""PreludeStep — a BaseStep variant that runs before the DAG topology begins."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterator
from typing import Any

from runlet.artifacts.base import BaseArtifact
from runlet.steps.base import BaseStep


class PreludeStep(BaseStep):
    """
    A step that executes before topology begins, receiving only pipeline metadata.

    Subclass this and set ``prelude = True`` on a step config to use it.
    PreludeStep.execute receives no upstream artifacts; it produces artifacts
    directly from metadata.
    """

    @abstractmethod
    def execute_prelude(self, metadata: dict[str, Any]) -> Iterator[BaseArtifact]:
        """Run pre-topology logic against pipeline metadata."""
        ...

    def execute(self, context: Any) -> Iterator[BaseArtifact]:
        return self.execute_prelude(context.metadata)
