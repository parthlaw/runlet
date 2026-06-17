"""
StepContext — the read-only context passed to step.execute().

Built from a RunContext by StepRunner immediately before dispatching a step.
Exposes only read operations — steps cannot register outputs or modify
shared state. Output registration happens in StepRunner after execute()
returns the output dict.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from runlet.orchestrator.context.run_context import RunContext


class StepContext:
    """
    Read-only context passed to every step during execution.

    Exposes upstream step outputs, pipeline metadata, artifact store access,
    and an optional LLM proxy for agentic steps.

    Steps return a JSON-serializable dict from execute(). The runner
    (via StepRunner) registers that dict as the step's output — steps
    never write to the context directly.
    """

    def __init__(self, run_context: RunContext) -> None:
        self._ctx = run_context

    @property
    def run_id(self) -> str:
        return self._ctx.run_id

    @property
    def pipeline_name(self) -> str:
        return self._ctx.pipeline_name

    @property
    def artifact_store(self):
        """Access to the artifact store for large-data I/O."""
        return self._ctx.store

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._ctx.metadata

    @property
    def llm(self) -> Any:
        """
        Return the configured LLMProxy for this pipeline.

        Raises RuntimeError if no 'llm' block was defined in pipeline.json.
        """
        if self._ctx._llm is None:
            raise RuntimeError(
                "No LLM is configured for this pipeline. "
                "Add an 'llm' block to pipeline.json."
            )
        return self._ctx._llm

    def is_cancelled(self) -> bool:
        """Return True if the runner has been cancelled."""
        return self._ctx.is_cancelled()

    def get_output(self, step_name: str) -> dict[str, Any]:
        """
        Return the output dict produced by a completed upstream step.

        Raises KeyError if the step has not completed or produced no output.
        """
        return self._ctx.get_output(step_name)

    def has_output(self, step_name: str) -> bool:
        """Return True if a completed step with registered output exists."""
        return self._ctx.has_output(step_name)

    def list_outputs(self) -> dict[str, dict[str, Any]]:
        """Return a snapshot copy of all registered step outputs."""
        return self._ctx.list_outputs()
