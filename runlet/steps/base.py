"""
BaseStep — the abstract contract every pipeline step must implement.

Quick start
-----------
Define a typed artifact, then yield instances from :meth:`execute`:

.. code-block:: python

    from dataclasses import dataclass
    from runlet.artifacts import artifact
    from runlet.steps import BaseStep
    from runlet.orchestrator.context import PipelineContext


    @artifact(version=1)
    @dataclass
    class ExtractRecord:
        page: int
        text: str


    class ExtractStep(BaseStep):
        def execute(self, context: PipelineContext):
            for page in pages:
                yield ExtractRecord(page=page.num, text=page.text)

Reading upstream data
---------------------
Use :meth:`~runlet.orchestrator.context.PipelineContext.iter_artifacts`:

.. code-block:: python

    class SummarizeStep(BaseStep):
        def execute(self, context: PipelineContext):
            for record in context.iter_artifacts("extract", ExtractRecord):
                yield SummaryRecord(page=record.page, summary=...)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from runlet.artifacts import BaseArtifact
from runlet.orchestrator.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)


class BaseStep(ABC):
    """
    Abstract base class for all pipeline steps.

    Implement :meth:`execute` as a generator that yields
    :class:`~runlet.artifacts.BaseArtifact` instances. The runner
    serializes them to JSONL and uploads to the artifact store.
    """

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        self.name: str = name
        self.config: dict[str, Any] = config or {}
        self.log: logging.Logger = logging.getLogger(f"step.{self.name}")

    @abstractmethod
    def execute(self, context: RuntimeContext) -> Iterator[BaseArtifact]:
        """Run the step logic. Yield one :class:`BaseArtifact` per output record."""
        ...

    def validate_config(self) -> None:  # noqa: B027
        """Optional: validate ``self.config`` before execution."""

    def teardown(self, context: RuntimeContext, success: bool) -> None:  # noqa: B027
        """Optional: cleanup after :meth:`execute` finishes."""

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def require_config(self, key: str) -> Any:
        if key not in self.config:
            raise ValueError(
                f"[{self.name}] Required config key '{key}' is missing. "
                f"Add it to pipeline.json → steps[{self.name!r}].config"
            )
        return self.config[key]

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"
