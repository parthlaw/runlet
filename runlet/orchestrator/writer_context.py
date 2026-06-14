"""
WriterContext — extends RuntimeContext with write operations for the runner.

Steps receive RuntimeContext (read-only). The runner holds WriterContext and
calls set_output/restore_outputs after each step completes.
"""

from __future__ import annotations

import logging
import threading
import types
from collections.abc import Mapping
from typing import Any

from runlet.artifact_store import ArtifactStore
from runlet.orchestrator.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)


class WriterContext(RuntimeContext):
    """
    Full context held by the runner — adds output registration.

    Steps only see RuntimeContext so they cannot accidentally call set_output
    or modify the output registry.
    """

    @property
    def metadata(self) -> Mapping[str, Any]:
        return types.MappingProxyType(self._metadata)

    def set_output(self, step_name: str, output: dict[str, Any]) -> None:
        """Register the output dict produced by *step_name*."""
        with self._outputs_lock:
            self._outputs[step_name] = output
        logger.debug("Context: registered output for step '%s'", step_name)

    def restore_outputs(self, outputs: dict[str, dict[str, Any]]) -> None:
        """Restore a previously serialised output registry (used on resume)."""
        for step_name, output in outputs.items():
            self.set_output(step_name, output)
        logger.info("Context restored: %d step(s) with registered outputs", len(outputs))


def build_context(
    run_id: str,
    pipeline_name: str,
    store: ArtifactStore,
    upload_store: ArtifactStore,
    metadata: dict[str, Any] | None = None,
    llm: Any | None = None,
    cancel_event: threading.Event | None = None,
) -> WriterContext:
    """Construct a WriterContext. Intended for use by the runner."""
    return WriterContext(
        run_id=run_id,
        pipeline_name=pipeline_name,
        store=store,
        upload_store=upload_store,
        metadata=metadata or {},
        llm=llm,
        cancel_event=cancel_event,
    )
