"""
RunContext — the runner-held execution context for a pipeline run.

Holds all mutable state needed during execution: step outputs, artifact stores,
metadata, LLM proxy, and the cancellation event.

Never passed to steps. The runner constructs a StepContext view from this object
and passes that to step.execute() instead.
"""

from __future__ import annotations

import json
import logging
import threading
import types
from collections.abc import Mapping
from typing import Any

from runlet.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)

_OUTPUT_SIZE_WARN_BYTES = 64_000


class RunContext:
    """
    Full execution context held by the runner.

    Steps never receive this object directly — they receive a StepContext
    built from this, which exposes only read operations.
    """

    def __init__(
        self,
        *,
        run_id: str,
        pipeline_name: str,
        store: ArtifactStore,
        upload_store: ArtifactStore,
        metadata: dict[str, Any],
        llm: Any | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.run_id = run_id
        self.pipeline_name = pipeline_name
        self.store = store
        self.upload_store = upload_store
        self._metadata: dict[str, Any] = metadata
        self._outputs: dict[str, dict[str, Any]] = {}
        self._outputs_lock = threading.RLock()
        self._llm = llm
        self._cancel_event: threading.Event = cancel_event or threading.Event()

    @property
    def metadata(self) -> Mapping[str, Any]:
        return types.MappingProxyType(self._metadata)

    def is_cancelled(self) -> bool:
        """Return True if the runner has been cancelled."""
        return self._cancel_event.is_set()

    def _register_output(self, step_name: str, output: dict[str, Any]) -> None:
        """Register the output dict produced by *step_name*.

        Called by StepRunner after step.execute() returns. Not exposed to steps.
        """
        serialized = json.dumps(output)
        if len(serialized) > _OUTPUT_SIZE_WARN_BYTES:
            logger.warning(
                "Step '%s' output is %d bytes. Store large data in the artifact store"
                " and return a URI instead.",
                step_name,
                len(serialized),
            )
        with self._outputs_lock:
            self._outputs[step_name] = output
        logger.debug("Context: registered output for step '%s'", step_name)

    def restore_outputs(self, outputs: dict[str, dict[str, Any]]) -> None:
        """Restore a previously serialised output registry (used on resume)."""
        for step_name, output in outputs.items():
            self._register_output(step_name, output)
        logger.info("Context restored: %d step(s) with registered outputs", len(outputs))

    def get_output(self, step_name: str) -> dict[str, Any]:
        """Return the output dict produced by a completed upstream step.

        Raises KeyError if the step has not completed or produced no output.
        """
        with self._outputs_lock:
            if step_name not in self._outputs:
                raise KeyError(
                    f"No output registered for step '{step_name}'. "
                    f"Available: {list(self._outputs)}"
                )
            return dict(self._outputs[step_name])

    def has_output(self, step_name: str) -> bool:
        """Return True if a completed step with registered output exists."""
        with self._outputs_lock:
            return step_name in self._outputs

    def list_outputs(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot copy of all registered step outputs."""
        with self._outputs_lock:
            return {step: dict(out) for step, out in self._outputs.items()}


def build_context(
    run_id: str,
    pipeline_name: str,
    store: ArtifactStore,
    upload_store: ArtifactStore,
    metadata: dict[str, Any] | None = None,
    llm: Any | None = None,
    cancel_event: threading.Event | None = None,
) -> RunContext:
    """Construct a RunContext. Intended for use by the runner."""
    return RunContext(
        run_id=run_id,
        pipeline_name=pipeline_name,
        store=store,
        upload_store=upload_store,
        metadata=metadata or {},
        llm=llm,
        cancel_event=cancel_event,
    )
