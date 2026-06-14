"""
RunState — in-memory execution state for a pipeline run.

Design
------
RunState is a pure in-memory structure. It is populated on resume by calling
``restore_from_records`` with the step rows returned by the metastore. All
state transitions are driven by the runner and mirrored to the metastore via
``_safe_metastore`` calls; no object store writes happen here.

Thread safety
-------------
All ``mark_*`` methods hold ``_flush_lock`` across the in-memory dict mutation
so concurrent step completions via ThreadedExecutor cannot produce a torn read.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runlet.metastore.metastore import StepRecord

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
    """Mutable in-memory execution state for a single pipeline run."""

    run_id: str
    pipeline_name: str

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

    def mark_run_started(self) -> None:
        with self._flush_lock:
            self.run_status = RunStatus.RUNNING
        logger.info("Run '%s' started.", self.run_id)

    def mark_run_success(self) -> None:
        with self._flush_lock:
            self.run_status = RunStatus.SUCCESS
        logger.info("Run '%s' completed successfully.", self.run_id)

    def mark_run_failed(self, error: str) -> None:
        with self._flush_lock:
            self.run_status = RunStatus.FAILED
        logger.error("Run '%s' failed: %s", self.run_id, error)

    def mark_run_cancelled(self) -> None:
        with self._flush_lock:
            self.run_status = RunStatus.CANCELLED
        logger.info("Run '%s' cancelled.", self.run_id)

    def mark_step_running(self, step_name: str, attempt: int = 1) -> None:
        with self._flush_lock:
            self._step_statuses[step_name] = StepStatus.RUNNING
        logger.info("[%s] → RUNNING (attempt %d)", step_name, attempt)

    def mark_step_success(
        self,
        step_name: str,
        output: dict[str, Any],
        duration_seconds: float,
        attempt: int = 1,
    ) -> None:
        import json
        serialized = json.dumps(output)
        if len(serialized) > _OUTPUT_SIZE_WARN_BYTES:
            logger.warning(
                "Step '%s' output is %d bytes. Store large data in the artifact store"
                " and return a URI instead.",
                step_name,
                len(serialized),
            )
        with self._flush_lock:
            self._step_statuses[step_name] = StepStatus.SUCCESS
            self._step_outputs[step_name] = output
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
        logger.error(
            "[%s] → FAILED (%.2fs, attempt %d): %s", step_name, duration_seconds, attempt, error
        )

    def mark_step_skipped(self, step_name: str) -> None:
        with self._flush_lock:
            self._step_statuses[step_name] = StepStatus.SKIPPED
        logger.info("[%s] → SKIPPED", step_name)

    def step_status(self, step_name: str) -> StepStatus:
        with self._flush_lock:
            return self._step_statuses.get(step_name, StepStatus.PENDING)

    def is_step_complete(self, step_name: str) -> bool:
        with self._flush_lock:
            status = self._step_statuses.get(step_name)
        return status in (StepStatus.SUCCESS, StepStatus.SKIPPED)

    def step_output(self, step_name: str) -> dict[str, Any]:
        with self._flush_lock:
            return dict(self._step_outputs.get(step_name, {}))

    def all_step_outputs(self) -> dict[str, dict[str, Any]]:
        with self._flush_lock:
            return {name: dict(out) for name, out in self._step_outputs.items()}

    def summary(self) -> dict[str, Any]:
        with self._flush_lock:
            return {
                "run_id": self.run_id,
                "pipeline_name": self.pipeline_name,
                "run_status": self.run_status.value,
                "steps": {
                    name: status.value
                    for name, status in self._step_statuses.items()
                },
            }

    @classmethod
    def restore_from_records(
        cls,
        run_id: str,
        pipeline_name: str,
        records: list[StepRecord],
    ) -> RunState:
        """Reconstruct in-memory state from metastore step records.

        Groups records by step_name. A step is considered complete if any
        attempt has status='success' (uses that attempt's output) or
        status='skipped'. FAILED/RUNNING records mean the step will re-execute.
        Handles retry history correctly: attempt=1 FAILED + attempt=2 SUCCESS
        → step is complete with attempt=2's output.
        """
        state = cls(run_id=run_id, pipeline_name=pipeline_name)

        by_step: dict[str, list[StepRecord]] = defaultdict(list)
        for rec in records:
            by_step[rec.step_name].append(rec)

        completed = 0
        for step_name, attempts in by_step.items():
            success = next((r for r in attempts if r.status == "success"), None)
            if success is not None:
                state._step_statuses[step_name] = StepStatus.SUCCESS
                state._step_outputs[step_name] = success.output
                completed += 1
                continue
            skipped = next((r for r in attempts if r.status == "skipped"), None)
            if skipped is not None:
                state._step_statuses[step_name] = StepStatus.SKIPPED
                completed += 1

        logger.info(
            "Restored state for run '%s': %d step(s) already complete.", run_id, completed
        )
        return state
