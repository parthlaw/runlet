"""
RuntimeContext — read-only view of pipeline state passed to step execute().

Steps can read outputs from completed upstream steps and access the artifact
store for large-data I/O. Write operations live in WriterContext (held by the runner).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from typing import Any

from runlet.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


class RuntimeContext:
    """
    Read-only context passed to every step during execution.

    Exposes upstream step outputs, pipeline metadata, direct artifact store
    access, and an optional LLM proxy (context.llm) for agentic steps.

    A step's output is a plain JSON-serializable dict stored in SQL.
    Steps that need to pass large data write it to the artifact store and
    put the URI in their output dict. See :mod:`runlet.utils.streaming`
    for format-specific helpers.
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
    def artifact_store(self) -> ArtifactStore:
        """Direct access to the artifact store for large-data I/O."""
        return self.store

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._metadata

    def is_cancelled(self) -> bool:
        """Return True if the runner has been cancelled or a step has timed out."""
        return self._cancel_event.is_set()

    @property
    def outputs(self) -> Mapping[str, Any]:
        """Read-only view of values written by steps via set_output()."""
        return self._outputs

    def set_output(self, key: str, value: Any) -> None:
        """
        Record a step output value.

        Use this instead of writing to context.metadata. Values are surfaced
        in RunResult.outputs after the run completes and persisted to the
        metastore so async callers can retrieve them.
        """
        self._outputs[key] = value

    @property
    def llm(self) -> Any:
        """
        Return the configured LLMProxy for this pipeline.

        Raises RuntimeError if no 'llm' block was defined in pipeline.json.
        """
        if self._llm is None:
            raise RuntimeError(
                "No LLM is configured for this pipeline. "
                "Add an 'llm' block to pipeline.json."
            )
        return self._llm

    def get_output(self, step_name: str) -> dict[str, Any]:
        """
        Return the output dict produced by a completed upstream step.

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
        with self._outputs_lock:
            return {step: dict(out) for step, out in self._outputs.items()}

    def to_dict(self) -> dict[str, Any]:
        with self._outputs_lock:
            outputs_snapshot = {step: dict(out) for step, out in self._outputs.items()}
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "outputs": outputs_snapshot,
            "metadata": dict(self._metadata),
        }
