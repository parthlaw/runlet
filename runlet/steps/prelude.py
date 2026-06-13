from __future__ import annotations

from abc import abstractmethod
from typing import Any

from runlet.steps.base import BaseStep
from runlet.orchestrator.runtime_context import RuntimeContext


class PreludeStep(BaseStep):
    """
    A step that executes before topology begins, receiving only pipeline metadata.

    Subclass this and set ``prelude = True`` on a step config to use it.
    PreludeStep.execute receives no upstream outputs; it produces its output
    dict directly from pipeline metadata.
    """

    @abstractmethod
    def execute_prelude(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Run pre-topology logic against pipeline metadata. Return a JSON-serializable dict."""
        ...

    def execute(self, context: RuntimeContext) -> dict[str, Any]:
        return self.execute_prelude(context.metadata)
