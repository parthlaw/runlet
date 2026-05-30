"""
RunState — durable execution state for a pipeline run.

Design
------
The state file lives in the artifact store alongside all other artifacts so
the entire run is self-contained and auditable from one place.

Key pattern:
    {store_prefix}{run_id}/_state/run_state.jsonl

The file contains JSONL records:

  1. ``{"type": "run", ...}``      — run-level metadata (written at start)
  2. ``{"type": "step", ...}``     — one record per step status transition

On resume, the runner loads the state file, rebuilds the :class:`RunState`
object, and skips all steps already in ``StepStatus.SUCCESS`` state.

Step status lifecycle
---------------------
``PENDING`` → ``RUNNING`` → ``SUCCESS``
                          ↘ ``FAILED``

The state file is append-friendly by design: each transition is a new JSONL
record.  The *last* record for a given step name wins (handled by
:meth:`RunState.load`).
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from runlet.artifact_store import ArtifactStore
from runlet.artifacts.ref import ArtifactRef
from runlet.orchestrator.errors import StateNotFoundError

logger = logging.getLogger(__name__)


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


def _now_iso() -> str:
    return datetime.datetime.now(tz=datetime.UTC).isoformat()


def _run_record(
    run_id: str,
    pipeline_name: str,
    status: RunStatus,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": "run",
        "run_id": run_id,
        "pipeline_name": pipeline_name,
        "status": status.value,
        "timestamp": _now_iso(),
    }
    if error is not None:
        record["error"] = error
    return record


def _step_record(
    run_id: str,
    step_name: str,
    status: StepStatus,
    *,
    paths: dict[str, ArtifactRef] | None = None,
    schema: dict[str, dict[str, Any]] | None = None,
    error: str | None = None,
    duration_seconds: float | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": "step",
        "run_id": run_id,
        "step_name": step_name,
        "status": status.value,
        "timestamp": _now_iso(),
    }
    if paths is not None:
        record["paths"] = {k: v.to_dict() for k, v in paths.items()}
    if schema is not None:
        record["schema"] = schema
    if error is not None:
        record["error"] = error
    if duration_seconds is not None:
        record["duration_seconds"] = round(duration_seconds, 3)
    if attempt is not None:
        record["attempt"] = attempt
    return record


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
    _step_paths: dict[str, dict[str, ArtifactRef]] = field(
        default_factory=dict, init=False, repr=False
    )

    @property
    def store_key(self) -> str:
        return f"{self.store_prefix}{self.run_id}/_state/run_state.jsonl"

    @property
    def store_uri(self) -> str:
        return self.store.to_uri(self.store_key)

    def mark_run_started(self) -> None:
        self.run_status = RunStatus.RUNNING
        self._flush([_run_record(self.run_id, self.pipeline_name, RunStatus.RUNNING)])
        logger.info("Run '%s' started.", self.run_id)

    def mark_run_success(self) -> None:
        self.run_status = RunStatus.SUCCESS
        self._flush([_run_record(self.run_id, self.pipeline_name, RunStatus.SUCCESS)])
        logger.info("Run '%s' completed successfully.", self.run_id)

    def mark_run_failed(self, error: str) -> None:
        self.run_status = RunStatus.FAILED
        self._flush([
            _run_record(
                self.run_id,
                self.pipeline_name,
                RunStatus.FAILED,
                error=error,
            )
        ])
        logger.error("Run '%s' failed: %s", self.run_id, error)

    def mark_run_cancelled(self) -> None:
        self.run_status = RunStatus.CANCELLED
        self._flush([_run_record(self.run_id, self.pipeline_name, RunStatus.CANCELLED)])
        logger.info("Run '%s' cancelled.", self.run_id)

    def mark_step_running(self, step_name: str, attempt: int = 1) -> None:
        self._step_statuses[step_name] = StepStatus.RUNNING
        self._flush([
            _step_record(self.run_id, step_name, StepStatus.RUNNING, attempt=attempt)
        ])
        logger.info("[%s] → RUNNING (attempt %d)", step_name, attempt)

    def mark_step_success(
        self,
        step_name: str,
        paths: dict[str, ArtifactRef],
        duration_seconds: float,
        schema_info: dict[str, dict[str, Any]] | None = None,
        attempt: int = 1,
    ) -> None:
        self._step_statuses[step_name] = StepStatus.SUCCESS
        self._step_paths[step_name] = paths
        self._flush([
            _step_record(
                self.run_id,
                step_name,
                StepStatus.SUCCESS,
                paths=paths,
                schema=schema_info,
                duration_seconds=duration_seconds,
                attempt=attempt,
            )
        ])
        logger.info("[%s] → SUCCESS (%.2fs, attempt %d)", step_name, duration_seconds, attempt)

    def mark_step_failed(
        self,
        step_name: str,
        error: str,
        duration_seconds: float,
        attempt: int = 1,
    ) -> None:
        self._step_statuses[step_name] = StepStatus.FAILED
        self._flush([
            _step_record(
                self.run_id,
                step_name,
                StepStatus.FAILED,
                error=error,
                duration_seconds=duration_seconds,
                attempt=attempt,
            )
        ])
        logger.error(
            "[%s] → FAILED (%.2fs, attempt %d): %s", step_name, duration_seconds, attempt, error
        )

    def mark_step_skipped(self, step_name: str) -> None:
        self._step_statuses[step_name] = StepStatus.SKIPPED
        self._flush([
            _step_record(self.run_id, step_name, StepStatus.SKIPPED)
        ])
        logger.info("[%s] → SKIPPED", step_name)

    def step_status(self, step_name: str) -> StepStatus:
        return self._step_statuses.get(step_name, StepStatus.PENDING)

    def is_step_complete(self, step_name: str) -> bool:
        status = self._step_statuses.get(step_name)
        return status in (StepStatus.SUCCESS, StepStatus.SKIPPED)

    def step_paths(self, step_name: str) -> dict[str, ArtifactRef]:
        return dict(self._step_paths.get(step_name, {}))

    def all_step_paths(self) -> dict[str, dict[str, ArtifactRef]]:
        return {name: dict(paths) for name, paths in self._step_paths.items()}

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

    def _flush(self, records: list[dict[str, Any]]) -> None:
        existing: list[dict[str, Any]] = []
        if self.store.exists(self.store_uri):
            existing = self.store.download_jsonl(uri=self.store_uri)

        merged = existing + records
        self.store.upload_jsonl(records=merged, key=self.store_key)
        logger.debug(
            "State flushed to %s (%d total record(s))",
            self.store_uri,
            len(merged),
        )

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

        records = store.download_jsonl(uri=state.store_uri)
        state._replay(records)
        logger.info(
            "Resumed run '%s'. Completed steps: %s",
            run_id,
            [n for n, s in state._step_statuses.items() if s == StepStatus.SUCCESS],
        )
        return state

    def _replay(self, records: list[dict[str, Any]]) -> None:
        for record in records:
            record_type = record.get("type")
            if record_type == "run":
                self.run_status = RunStatus(record["status"])
            elif record_type == "step":
                step_name = record["step_name"]
                self._step_statuses[step_name] = StepStatus(record["status"])
                if "paths" in record:
                    step_refs: dict[str, ArtifactRef] = {}
                    for output_name, val in record["paths"].items():
                        if isinstance(val, dict):
                            step_refs[output_name] = ArtifactRef.from_dict(val)
                        else:
                            # Backward compat: old state files stored plain URI strings.
                            step_refs[output_name] = ArtifactRef(
                                uri=str(val), schema_name="", schema_version=0
                            )
                    self._step_paths[step_name] = step_refs


