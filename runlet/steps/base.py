"""
BaseStep — the abstract contract every pipeline step must implement.

Quick start
-----------
Implement :meth:`execute` to return a JSON-serializable dict. That dict is
stored in SQL as the step's output and made available to downstream steps via
:meth:`~runlet.orchestrator.runtime_context.RuntimeContext.get_output`.

.. code-block:: python

    from runlet.steps import BaseStep
    from runlet.orchestrator.runtime_context import RuntimeContext


    class ExtractStep(BaseStep):
        def execute(self, context: RuntimeContext) -> dict:
            records = fetch_data()
            return {"count": len(records), "status": "ok"}


Passing large data between steps
---------------------------------
Store large data in the artifact store and put the reference URI in the
output dict. The downstream step retrieves it by key. The framework is
format-agnostic — use whatever serialization fits the data. For
streaming helpers see :mod:`runlet.utils.streaming`.

.. code-block:: python

    class ProducerStep(BaseStep):
        def execute(self, context: RuntimeContext) -> dict:
            key = context.artifact_store.build_key(context.run_id, self.name, "data")
            with tempfile.NamedTemporaryFile() as tmp:
                write_your_format(tmp, my_records())
                context.artifact_store.upload_file(tmp.name, key)
            return {"data_uri": context.artifact_store.to_uri(key), "record_count": 42}

    class ConsumerStep(BaseStep):
        def execute(self, context: RuntimeContext) -> dict:
            upstream = context.get_output("producer")
            with context.artifact_store.download_file(upstream["data_uri"]) as tmp:
                records = read_your_format(tmp)
            return {"processed": True}
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from runlet.orchestrator.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)


class BaseStep(ABC):
    """
    Abstract base class for all pipeline steps.

    Implement :meth:`execute` to return a JSON-serializable dict. The runner
    stores it in SQL and exposes it to downstream steps via
    ``context.get_output(step_name)``.
    """

    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        self.name: str = name
        self.config: dict[str, Any] = config or {}
        self.log: logging.Logger = logging.getLogger(f"step.{self.name}")

    @abstractmethod
    def execute(self, context: RuntimeContext) -> dict[str, Any]:
        """Run the step. Return a JSON-serializable dict stored as this step's output."""
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
