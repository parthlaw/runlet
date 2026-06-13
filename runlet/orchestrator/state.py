"""
RunState — durable execution state for a pipeline run.

Design
------
The state file lives in the artifact store alongside all other artifacts so
the entire run is self-contained and auditable from one place.

Key pattern:
    {store_prefix}{run_id}/_state/run_state.json

The file contains a single JSON object capturing current run state:

  {
    "run_id": "...",
    "pipeline_name": "...",
    "run_status": "running" | "success" | "failed" | "cancelled",
    "steps": {
      "<step_name>": {
        "status": "pending" | "running" | "success" | "failed" | "skipped",
        "output": {...}   // only present on success
      }
    }
  }

On resume, the runner loads the state file and skips all steps already in
``StepStatus.SUCCESS`` state. Intermediate retry records are NOT stored in
the state file — the metastore retains full per-attempt history.

Thread safety
-------------
All ``mark_*`` methods hold ``_flush_lock`` across both the in-memory dict
mutation and the file write so concurrent step completions cannot interleave.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from runlet.artifact_store import ArtifactStore
from runlet.orchestrator.errors import StateNotFoundError

logger = logging.getLogger(__name__)

_OUTPUT_SIZE_WARN_BYTES = 64_000


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RunState:
    """
    Mutable execution state for a single pipeline run.

    All state transitions are immediately flushed to the artifact store so the
    run can be resumed after any failure.
    """

    run_id: str
    pipeline_name: str
    store: ArtifactStore
    store_prefix: str

    run_status: RunStatus = field(default=RunStatus.RUNNING, init=False)
    _step_statuses: dict[str, StepStatus] = field(
        default_factory=dict, init=False, repr=False
    )
    _step_outputs: dict[str, dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    _flush_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @property
    def store_key(self) -> str:
        return f"{self.store_prefix}{self.run_id}/_state/run_state.json"

    @property
    def store_uri(self) -> str:
        return self.store.to_uri(self.store_key)

    def mark_run_started(self) -> None:
        with self._flush_lock:
            self.run_status = RunStatus.RUNNING
            self._flush()
        logger.info("Run '%s' started.", self.run_id)

    def mark_run_success(self) -> None:
        with self._flush_lock:
            self.run_status = RunStatus.SUCCESS
            self._flush()
        logger.info("Run '%s' completed successfully.", self.run_id)

    def mark_run_failed(self, error: str) -> None:
        with self._flush_lock:
            self.run_status = RunStatus.FAILED
            self._flush()
        logger.error("Run '%s' failed: %s", self.run_id, error)

    def mark_run_cancelled(self) -> None:
        with self._flush_lock:
            self.run_status = RunStatus.CANCELLED
            self._flush()
        logger.info("Run '%s' cancelled.", self.run_id)

    def mark_step_running(self, step_name: str, attempt: int = 1) -> None:
        with self._flush_lock:
            self._step_statuses[step_name] = StepStatus.RUNNING
            self._flush()
        logger.info("[%s] → RUNNING (attempt %d)", step_name, attempt)

    def mark_step_success(
        self,
        step_name: str,
        output: dict[str, Any],
        duration_seconds: float,
        attempt: int = 1,
    ) -> None:
        serialized = json.dumps(output)
        if len(serialized) > _OUTPUT_SIZE_WARN_BYTES:
            logger.warning(
                "Step '%s' output is %d bytes. Store large data in the artifact store and return a URI instead.",
                step_name,
                len(serialized),
            )
        with self._flush_lock:
            self._step_statuses[step_name] = StepStatus.SUCCESS
            self._step_outputs[step_name] = output
            self._flush()
        logger.info("[%s] → SUCCESS (%.2fs, attempt %d)", step_name, duration_seconds, attempt)

    def mark_step_failed(
        self,
        step_name: str,
        error: str,
        duration_seconds: float,
        attempt: int = 1,
    ) -> None:
        with self._flush_lock:
            self._step_statuses[step_name] = StepStatus.FAILED
            self._flush()
        logger.error(
            "[%s] → FAILED (%.2fs, attempt %d): %s", step_name, duration_seconds, attempt, error
        )

    def mark_step_skipped(self, step_name: str) -> None:
        with self._flush_lock:
            self._step_statuses[step_name] = StepStatus.SKIPPED
            self._flush()
        logger.info("[%s] → SKIPPED", step_name)

    def step_status(self, step_name: str) -> StepStatus:
        return self._step_statuses.get(step_name, StepStatus.PENDING)

    def is_step_complete(self, step_name: str) -> bool:
        status = self._step_statuses.get(step_name)
        return status in (StepStatus.SUCCESS, StepStatus.SKIPPED)

    def step_output(self, step_name: str) -> dict[str, Any]:
        return dict(self._step_outputs.get(step_name, {}))

    def all_step_outputs(self) -> dict[str, dict[str, Any]]:
        return {name: dict(out) for name, out in self._step_outputs.items()}

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "run_status": self.run_status.value,
            "steps": {
                name: status.value
                for name, status in self._step_statuses.items()
            },
        }

    def _to_dict(self) -> dict[str, Any]:
        """Serialize current in-memory state to a JSON-compatible dict."""
        steps: dict[str, Any] = {}
        for name, status in self._step_statuses.items():
            entry: dict[str, Any] = {"status": status.value}
            if name in self._step_outputs:
                entry["output"] = self._step_outputs[name]
            steps[name] = entry
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "run_status": self.run_status.value,
            "steps": steps,
        }

    def _flush(self) -> None:
        """Write current state atomically. Must be called with _flush_lock held."""
        self.store.upload_json(self._to_dict(), key=self.store_key)
        logger.debug("State flushed to %s", self.store_uri)

    @classmethod
    def create_new(
        cls,
        run_id: str,
        pipeline_name: str,
        store: ArtifactStore,
        store_prefix: str,
    ) -> RunState:
        state = cls(
            run_id=run_id,
            pipeline_name=pipeline_name,
            store=store,
            store_prefix=store_prefix,
        )
        state.mark_run_started()
        return state

    @classmethod
    def load_existing(
        cls,
        run_id: str,
        pipeline_name: str,
        store: ArtifactStore,
        store_prefix: str,
    ) -> RunState:
        state = cls(
            run_id=run_id,
            pipeline_name=pipeline_name,
            store=store,
            store_prefix=store_prefix,
        )

        if not state.store.exists(state.store_uri):
            raise StateNotFoundError(
                f"No state file found for run '{run_id}' at {state.store_uri}. "
                "Cannot resume a run that has not been started."
            )

        data = store.download_json(uri=state.store_uri)
        state._restore(data)
        logger.info(
            "Resumed run '%s'. Completed steps: %s",
            run_id,
            [n for n, s in state._step_statuses.items() if s == StepStatus.SUCCESS],
        )
        return state

    def _restore(self, data: dict[str, Any]) -> None:
        """Rebuild in-memory state from a persisted JSON snapshot."""
        self.run_status = RunStatus(data["run_status"])
        for name, step in data.get("steps", {}).items():
            self._step_statuses[name] = StepStatus(step["status"])
            if "output" in step:
                self._step_outputs[name] = step["output"]
