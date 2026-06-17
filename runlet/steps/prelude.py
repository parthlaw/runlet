from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from typing import Any

from runlet.orchestrator.context.step_context import StepContext
from runlet.steps.base import BaseStep


class PreludeStep(BaseStep):
    """
    A step that executes before topology begins, receiving only pipeline metadata.

    Subclass this and set ``prelude = True`` on a step config to use it.
    PreludeStep.execute receives no upstream outputs; it produces its output
    dict directly from pipeline metadata.
    """

    @abstractmethod
    def execute_prelude(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        """Run pre-topology logic against pipeline metadata. Return a JSON-serializable dict."""
        ...

    def execute(self, context: StepContext) -> dict[str, Any]:
        return self.execute_prelude(context.metadata)
